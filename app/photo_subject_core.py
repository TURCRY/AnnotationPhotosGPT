"""Affectation manuelle des photographies aux sujets (Lot 1).

Ce module porte uniquement l interface et la persistance de l affectation
humaine photo -> sujet. Il n appelle aucun LLM, ne cree aucun job et ne
modifie ni photos_batch.csv ni le pipeline compte-rendu.

Le module est scinde en deux parties :
  * une couche metier pure (aucune dependance Streamlit), testable ;
  * une couche de rendu Streamlit (render_photo_subject_section).
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

try:  # package import (LLM_Assistant/app.py) et import direct
    from . import photo_time_helper as _time_helper
except ImportError:  # pragma: no cover
    import photo_time_helper as _time_helper  # type: ignore[no-redef]

SCHEMA_VERSION = 1
ASSIGNMENTS_FILENAME = "photo_subject_assignments.json"

STATUS_NON_AFFECTEE = "non_affectee"
STATUS_AFFECTEE = "affectee"
STATUS_EXCLUE = "exclue"
VALID_STATUSES = (STATUS_NON_AFFECTEE, STATUS_AFFECTEE, STATUS_EXCLUE)

# Etats de controle des prerequis.
STATE_OK = "OK"
STATE_ABSENT = "ABSENT"
STATE_INVALID = "INVALIDE"

# Colonnes metier de Sujets.xlsx, en minuscules pour la normalisation.
SUBJECT_COLUMN_ALIASES = {
    "numero": "numero",
    "numéro": "numero",
    "n°": "numero",
    "no": "numero",
    "titre": "titre",
    "localisation": "localisation",
    "description": "description",
    "commentaire": "commentaire",
}


# ---------------------------------------------------------------------------
# Modele de donnees
# ---------------------------------------------------------------------------


@dataclass
class Subject:
    """Un sujet du referentiel Sujets.xlsx."""

    numero: int
    titre: str = ""
    localisation: str = ""
    description: str = ""
    commentaire: str = ""
    has_cr_context: bool = False

    @property
    def label(self) -> str:
        titre = self.titre.strip() or f"Sujet {self.numero}"
        return f"Sujet {self.numero} — {titre}"


@dataclass
class PhotoRef:
    """Une photo dans l ordre canonique du CSV."""

    index: int
    photo_rel_native: str
    display_name: str
    thumb_path: Path | None = None
    native_path: Path | None = None
    # Datetime canonique de prise de vue (source : photos.csv), jamais recalculee.
    photo_datetime: datetime | None = None


@dataclass
class Assignment:
    """Decision humaine pour une photo."""

    photo_rel_native: str
    status: str = STATUS_NON_AFFECTEE
    subject_numero: int | None = None
    subject_title: str | None = None
    subject_location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "photo_rel_native": self.photo_rel_native,
            "status": self.status,
            "subject_numero": self.subject_numero,
            "subject_title": self.subject_title,
            "subject_location": self.subject_location,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Assignment":
        return cls(
            photo_rel_native=str(data.get("photo_rel_native") or "").strip(),
            status=str(data.get("status") or STATUS_NON_AFFECTEE).strip(),
            subject_numero=_coerce_optional_int(data.get("subject_numero")),
            subject_title=_coerce_optional_str(data.get("subject_title")),
            subject_location=_coerce_optional_str(data.get("subject_location")),
        )


@dataclass
class IntegrityIssue:
    """Anomalie detectee au rechargement d un fichier d affectation."""

    kind: str
    photo_rel_native: str = ""
    subject_numero: int | None = None
    message: str = ""
    details: dict[str, str] = field(default_factory=dict)


@dataclass
class AssignmentsDocument:
    """Contenu complet de photo_subject_assignments.json."""

    id_affaire: str = ""
    id_captation: str = ""
    updated_at: str = ""
    assignments: list[Assignment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "id_affaire": self.id_affaire,
            "id_captation": self.id_captation,
            "updated_at": self.updated_at,
            "assignments": [a.to_dict() for a in self.assignments],
        }


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_key(value: Any) -> str:
    """Normalise un nom de colonne Excel : casse, accents, espaces."""
    text = str(value or "").strip().lower()
    text = text.replace("’", "'").replace(" ", " ")
    return " ".join(text.split())


def normalize_subject_columns(fieldnames: Iterable[Any]) -> dict[str, str]:
    """Retourne la correspondance nom d origine -> colonne metier normalisee.

    La casse des en-tetes varie selon les affaires (``Numero`` / ``numero``).
    Seules les colonnes reconnues sont retournees.
    """
    mapping: dict[str, str] = {}
    for raw in fieldnames:
        key = _normalize_key(raw)
        canonical = SUBJECT_COLUMN_ALIASES.get(key)
        if canonical and canonical not in mapping.values():
            mapping[str(raw)] = canonical
    return mapping


# ---------------------------------------------------------------------------
# Lecture de Sujets.xlsx
# ---------------------------------------------------------------------------


def load_subjects_from_rows(
    rows: Sequence[dict[str, Any]],
    *,
    cr_numeros: set[int] | None = None,
) -> tuple[list[Subject], list[str]]:
    """Construit la liste de sujets a partir de lignes deja normalisees.

    ``rows`` doit contenir les cles metier normalisees (``numero``, ``titre``,
    ``localisation``, ``description``, ``commentaire``).

    Retourne ``(sujets, erreurs)``. Les numeros ``<= 0`` sont ignores. Les
    doublons sont signales sans tentative de resolution automatique.
    """
    subjects: list[Subject] = []
    errors: list[str] = []
    seen: dict[int, int] = {}
    cr_numeros = cr_numeros or set()

    for position, row in enumerate(rows, start=1):
        numero = _coerce_optional_int(row.get("numero"))
        if numero is None:
            continue
        if numero <= 0:
            continue
        if numero in seen:
            errors.append(
                f"Numéro de sujet dupliqué : {numero} "
                f"(lignes {seen[numero]} et {position}). "
                "Aucun rapprochement automatique n'est effectué : "
                "corriger Sujets.xlsx avant de poursuivre."
            )
            continue
        seen[numero] = position
        subjects.append(
            Subject(
                numero=numero,
                titre=str(row.get("titre") or "").strip(),
                localisation=str(row.get("localisation") or "").strip(),
                description=str(row.get("description") or "").strip(),
                commentaire=str(row.get("commentaire") or "").strip(),
                has_cr_context=numero in cr_numeros,
            )
        )

    subjects.sort(key=lambda s: s.numero)
    return subjects, errors


def read_sujets_xlsx(path: str | Path, *, cr_numeros: set[int] | None = None):
    """Lit Sujets.xlsx sans coder de nom de feuille en dur.

    Retourne ``(sujets, erreurs)``. Le nom de la feuille n est pas stable
    selon les affaires : la feuille active est utilisee, comme le fait le
    pipeline compte-rendu (``Import-Excel`` sans ``-WorksheetName``).
    """
    try:
        from openpyxl import load_workbook
    except ImportError:  # pragma: no cover - dependance de l application
        return [], ["openpyxl indisponible : lecture de Sujets.xlsx impossible."]

    path = Path(path)
    if not path.is_file():
        return [], [f"Sujets.xlsx introuvable : {path}"]

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        return [], [f"Sujets.xlsx illisible : {exc}"]

    try:
        worksheet = workbook.worksheets[0]
        rows_iter = worksheet.iter_rows(values_only=True)
        header = next(rows_iter, None)
        if header is None:
            return [], ["Sujets.xlsx vide : aucune ligne d'en-tête."]
        mapping = normalize_subject_columns(header)
        if "numero" not in mapping.values():
            return [], [
                "Sujets.xlsx : colonne Numero introuvable "
                f"(en-têtes lus : {', '.join(str(h) for h in header if h)})."
            ]
        normalized: list[dict[str, Any]] = []
        for raw_row in rows_iter:
            if raw_row is None:
                continue
            record: dict[str, Any] = {}
            for index, source_name in enumerate(header):
                canonical = mapping.get(str(source_name))
                if not canonical:
                    continue
                value = raw_row[index] if index < len(raw_row) else None
                record[canonical] = value
            if any(record.get(k) not in (None, "") for k in record):
                normalized.append(record)
    finally:
        workbook.close()

    return load_subjects_from_rows(normalized, cr_numeros=cr_numeros)


# ---------------------------------------------------------------------------
# Lecture de photos_batch.csv (ordre canonique)
# ---------------------------------------------------------------------------


def read_photos_batch(path: str | Path) -> tuple[list[PhotoRef], list[str]]:
    """Lit photos_batch.csv en preservant l ordre des lignes du CSV.

    L ordre canonique de la serie est l ordre des lignes du CSV (ordre
    chronologique de prise de vue), et non un tri alphabetique des noms de
    fichiers. Les doublons de ``photo_rel_native`` sont ignores.
    """
    path = Path(path)
    if not path.is_file():
        return [], [f"photos_batch.csv introuvable : {path}"]

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            fieldnames = reader.fieldnames or []
            if "photo_rel_native" not in fieldnames:
                return [], [
                    "photos_batch.csv : colonne photo_rel_native absente "
                    f"(colonnes lues : {', '.join(fieldnames)})."
                ]
            rows = list(reader)
    except Exception as exc:
        return [], [f"photos_batch.csv illisible : {exc}"]

    photos: list[PhotoRef] = []
    seen: set[str] = set()
    for row in rows:
        rel = str(row.get("photo_rel_native") or "").strip()
        if not rel or rel in seen:
            continue
        seen.add(rel)
        photos.append(
            PhotoRef(
                index=len(photos) + 1,
                photo_rel_native=rel,
                display_name=Path(rel.replace("\\", "/")).name or rel,
            )
        )
    return photos, []


# ---------------------------------------------------------------------------
# Horodatage photo + origine audio (galerie)
# ---------------------------------------------------------------------------


def _normalize_photo_key(value: Any) -> str:
    """Cle de jointure photo : chemin natif normalise (slashes, casse)."""
    text = str(value or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip("/").lower()


def read_photo_times(
    path: str | Path,
    *,
    infos: dict[str, Any] | None = None,
) -> tuple[dict[str, datetime], datetime | None, list[str]]:
    """Lit les horodatages canoniques depuis ``photos.csv``.

    Retourne ``(table, debut_audio_reconstruit, erreurs)`` ou la table est
    indexee par cle de photo normalisee. Aucune lecture EXIF : on utilise
    uniquement la donnee canonique deja ecrite par le pipeline
    (``horodatage_photo``, sinon ``horodatage_secondes``).

    ``debut_audio_reconstruit`` n'est renseigne que si ``photos.csv`` porte
    ``horodatage_secondes`` + ``decalage_moyen`` (cf.
    ``photo_time_helper.resolve_audio_start_from_photos_csv``).
    """
    path = Path(path)
    if not path.is_file():
        return {}, None, [f"photos.csv introuvable : {path}"]

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            fieldnames = reader.fieldnames or []
            rows = list(reader)
    except Exception as exc:
        return {}, None, [f"photos.csv illisible : {exc}"]

    has_dt = any(column in fieldnames for column in _time_helper.PHOTO_DATETIME_COLUMNS)
    has_seconds = any(column in fieldnames for column in _time_helper.PHOTO_SECONDS_COLUMNS)
    if not has_dt and not has_seconds:
        return {}, None, [
            "photos.csv : aucune colonne d'horodatage exploitable "
            f"(colonnes lues : {', '.join(fieldnames)})."
        ]

    # Reference de repli pour les colonnes en secondes : premiere datetime lue.
    reference: datetime | None = None
    if not has_dt:
        for row in rows:
            for column in _time_helper.PHOTO_DATETIME_COLUMNS:
                candidate = _time_helper.parse_photo_datetime(row.get(column))
                if candidate is not None:
                    reference = candidate
                    break
            if reference is not None:
                break

    table: dict[str, datetime] = {}
    for row in rows:
        moment = _time_helper.parse_photo_datetime_from_row(row, default_date=reference)
        if moment is None:
            continue
        key = _normalize_photo_key(
            row.get("photo_rel_native") or row.get("photo_rel_reduite") or ""
        )
        if not key:
            continue
        table.setdefault(key, moment)

    audio_start, _origin = _time_helper.resolve_audio_start_from_photos_csv(rows, infos)
    return table, audio_start, []


def _read_photos_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    """Lignes brutes de photos.csv (tolere l'absence du fichier)."""
    path = Path(path)
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter=";"))
    except Exception:
        return []


def resolve_audio_start_from_paths(
    infos_path: str | Path | None,
    photos_csv_path: str | Path | None,
) -> tuple[datetime | None, str]:
    """Origine audio = infos_projet.json (t0_global > horodatage_audio),
    puis photos.csv (decalage_moyen), puis metadonnee du WAV source.

    Le WAV source est teste en dernier : son horodatage systeme peut n'etre
    qu'une date de copie, alors que decalage_moyen est valide par le calibrage.
    """
    infos = _time_helper.load_infos_projet(infos_path)
    rows = _read_photos_csv_rows(photos_csv_path) if photos_csv_path else []

    # 1/2 : valeurs canoniques de infos_projet.json
    for key in _time_helper.AUDIO_ORIGIN_KEYS:
        parsed = _time_helper.parse_audio_datetime(infos.get(key))
        if parsed is not None:
            return parsed, f"infos_projet.json:{key}"

    # 3 : reconstruction depuis photos.csv
    from_csv, origin = _time_helper.resolve_audio_start_from_photos_csv(rows, infos)
    if from_csv is not None:
        return from_csv, origin

    # 4 : metadonnee du WAV source reel (garde-fou 24 h)
    return _time_helper.resolve_audio_start(infos)


def apply_photo_times(
    photos: list[PhotoRef],
    table: dict[str, datetime],
) -> int:
    """Complete ``photo.photo_datetime`` depuis la table. Retourne le nb completes."""
    if not table:
        return 0
    count = 0
    for photo in photos:
        key = _normalize_photo_key(photo.photo_rel_native)
        moment = table.get(key)
        if moment is None:
            moment = table.get(_normalize_photo_key(photo.display_name))
        if moment is not None:
            photo.photo_datetime = moment
            count += 1
    return count


# ---------------------------------------------------------------------------
# Jointure avec global_final.json
# ---------------------------------------------------------------------------


def read_global_final_numeros(path: str | Path) -> tuple[set[int], list[str]]:
    """Retourne les numeros de sujets presents dans global_final.json."""
    path = Path(path)
    if not path.is_file():
        return set(), [f"global_final.json introuvable : {path}"]
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except Exception as exc:
        return set(), [f"global_final.json illisible : {exc}"]
    if not isinstance(data, dict):
        return set(), ["global_final.json invalide : objet JSON attendu."]
    sujets = data.get("sujets")
    if not isinstance(sujets, list):
        return set(), ["global_final.json invalide : champ 'sujets' absent."]
    numeros: set[int] = set()
    for item in sujets:
        if not isinstance(item, dict):
            continue
        numero = _coerce_optional_int(item.get("numero"))
        if numero is not None and numero > 0:
            numeros.add(numero)
    return numeros, []


# ---------------------------------------------------------------------------
# Persistance de photo_subject_assignments.json
# ---------------------------------------------------------------------------


def load_assignments(path: str | Path) -> tuple[AssignmentsDocument, list[str]]:
    """Charge photo_subject_assignments.json.

    Un fichier absent n est pas une erreur : il n y a simplement encore
    aucune decision enregistree.
    """
    path = Path(path)
    if not path.is_file():
        return AssignmentsDocument(), []

    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except Exception as exc:
        return AssignmentsDocument(), [f"photo_subject_assignments.json illisible : {exc}"]

    if not isinstance(data, dict):
        return AssignmentsDocument(), [
            "photo_subject_assignments.json invalide : objet JSON attendu."
        ]

    version = _coerce_optional_int(data.get("schema_version"))
    errors: list[str] = []
    if version is not None and version != SCHEMA_VERSION:
        errors.append(
            f"Version de schéma inattendue : {version} (attendu {SCHEMA_VERSION})."
        )

    raw_assignments = data.get("assignments")
    if not isinstance(raw_assignments, list):
        if raw_assignments is not None:
            errors.append("Champ 'assignments' invalide : liste attendue.")
        raw_assignments = []

    assignments: list[Assignment] = []
    seen: set[str] = set()
    for item in raw_assignments:
        if not isinstance(item, dict):
            continue
        assignment = Assignment.from_dict(item)
        if not assignment.photo_rel_native or assignment.photo_rel_native in seen:
            continue
        if assignment.status not in VALID_STATUSES:
            errors.append(
                f"Statut inconnu '{assignment.status}' pour "
                f"{assignment.photo_rel_native} : ignoré."
            )
            continue
        if assignment.status == STATUS_AFFECTEE and assignment.subject_numero is None:
            errors.append(
                f"Affectation incohérente pour {assignment.photo_rel_native} : "
                "statut 'affectee' sans subject_numero."
            )
            continue
        if assignment.status != STATUS_AFFECTEE:
            # Un seul sujet principal : hors statut affectee, aucune sujet.
            assignment.subject_numero = None
            assignment.subject_title = None
            assignment.subject_location = None
        seen.add(assignment.photo_rel_native)
        assignments.append(assignment)

    return (
        AssignmentsDocument(
            id_affaire=str(data.get("id_affaire") or "").strip(),
            id_captation=str(data.get("id_captation") or "").strip(),
            updated_at=str(data.get("updated_at") or "").strip(),
            assignments=assignments,
        ),
        errors,
    )


def save_assignments(
    path: str | Path,
    document: AssignmentsDocument,
    *,
    id_affaire: str = "",
    id_captation: str = "",
) -> AssignmentsDocument:
    """Ecrit photo_subject_assignments.json de facon atomique.

    Les photos ``non_affectee`` ne sont pas persistees : leur absence du
    fichier signifie exactement « aucune decision enregistree ». Le contrat
    reste ainsi minimal et le fichier ne grossit pas inutilement.
    """
    path = Path(path)
    document.id_affaire = id_affaire or document.id_affaire
    document.id_captation = id_captation or document.id_captation
    document.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    kept: list[Assignment] = []
    seen: set[str] = set()
    for assignment in document.assignments:
        rel = assignment.photo_rel_native
        if not rel or rel in seen:
            continue
        if assignment.status == STATUS_NON_AFFECTEE:
            continue
        seen.add(rel)
        kept.append(assignment)
    kept.sort(key=lambda a: a.photo_rel_native)
    document.assignments = kept

    payload = json.dumps(document.to_dict(), ensure_ascii=False, indent=2)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".photo_subject_assignments.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return document


# ---------------------------------------------------------------------------
# Operations metier
# ---------------------------------------------------------------------------


def build_assignment_index(document: AssignmentsDocument) -> dict[str, Assignment]:
    return {a.photo_rel_native: a for a in document.assignments}


def get_status(
    index: dict[str, Assignment], photo_rel_native: str
) -> str:
    assignment = index.get(photo_rel_native)
    return assignment.status if assignment else STATUS_NON_AFFECTEE


def assign_photos(
    document: AssignmentsDocument,
    photos: Sequence[str],
    subject: Subject,
) -> list[tuple[str, str]]:
    """Affecte des photos a un sujet (un seul sujet principal par photo).

    Retourne la liste des ``(photo, ancien_statut)`` ayant ete remplaces
    afin que l UI puisse rendre le remplacement explicite.
    """
    index = build_assignment_index(document)
    replaced: list[tuple[str, str]] = []
    for rel in photos:
        rel = str(rel).strip()
        if not rel:
            continue
        existing = index.get(rel)
        if existing is not None and existing.status == STATUS_AFFECTEE:
            if existing.subject_numero != subject.numero:
                replaced.append((rel, existing.subject_title or f"Sujet {existing.subject_numero}"))
            existing.status = STATUS_AFFECTEE
            existing.subject_numero = subject.numero
            existing.subject_title = subject.titre
            existing.subject_location = subject.localisation
            continue
        if existing is None:
            assignment = Assignment(photo_rel_native=rel)
            index[rel] = assignment
            document.assignments.append(assignment)
        else:
            assignment = existing
        assignment.status = STATUS_AFFECTEE
        assignment.subject_numero = subject.numero
        assignment.subject_title = subject.titre
        assignment.subject_location = subject.localisation
    return replaced


def exclude_photos(document: AssignmentsDocument, photos: Sequence[str]) -> None:
    """Exclut des photos de la future contextualisation."""
    index = build_assignment_index(document)
    for rel in photos:
        rel = str(rel).strip()
        if not rel:
            continue
        assignment = index.get(rel)
        if assignment is None:
            assignment = Assignment(photo_rel_native=rel)
            index[rel] = assignment
            document.assignments.append(assignment)
        assignment.status = STATUS_EXCLUE
        assignment.subject_numero = None
        assignment.subject_title = None
        assignment.subject_location = None


def reset_photos(document: AssignmentsDocument, photos: Sequence[str]) -> None:
    """Remet des photos a l etat non_affectee."""
    index = build_assignment_index(document)
    for rel in photos:
        rel = str(rel).strip()
        if not rel:
            continue
        assignment = index.get(rel)
        if assignment is None:
            continue
        assignment.status = STATUS_NON_AFFECTEE
        assignment.subject_numero = None
        assignment.subject_title = None
        assignment.subject_location = None


# ---------------------------------------------------------------------------
# Selection par plage
# ---------------------------------------------------------------------------


def select_range(
    photos: Sequence[PhotoRef],
    first: str | None,
    last: str | None,
) -> list[str]:
    """Retourne les photos comprises entre deux bornes dans l ordre canonique.

    L ordre utilise est celui de ``photos`` (ordre des lignes du CSV), jamais
    un tri alphabetique. Si les bornes sont inversees, la plage est tout de
    meme retournee.
    """
    if not first or not last:
        return []
    order = [p.photo_rel_native for p in photos]
    try:
        start = order.index(first)
        end = order.index(last)
    except ValueError:
        return []
    if start > end:
        start, end = end, start
    return order[start : end + 1]


# ---------------------------------------------------------------------------
# Selection temporaire UI
# ---------------------------------------------------------------------------


def normalize_photo_selection(values: Iterable[str] | None) -> set[str]:
    """Retourne une selection UI explicite, independante des affectations."""
    selected: set[str] = set()
    for value in values or []:
        rel = str(value).strip()
        if rel:
            selected.add(rel)
    return selected


def replace_photo_selection(values: Iterable[str] | None) -> set[str]:
    """Remplace integralement la selection temporaire courante."""
    return normalize_photo_selection(values)


def update_photo_selection(
    selection: Iterable[str] | None,
    photo_rel_native: str,
    checked: bool,
) -> set[str]:
    """Applique le cochage/decochage d une photo a la selection UI."""
    selected = normalize_photo_selection(selection)
    rel = str(photo_rel_native or "").strip()
    if not rel:
        return selected
    if checked:
        selected.add(rel)
    else:
        selected.discard(rel)
    return selected


def clear_photo_selection() -> set[str]:
    """Vide la selection temporaire sans modifier l etat metier."""
    return set()


def snapshot_photo_selection(
    photos: Sequence[PhotoRef],
    selection: Iterable[str] | None,
) -> list[str]:
    """Fige la selection UI dans l ordre canonique des photos."""
    selected = normalize_photo_selection(selection)
    return [p.photo_rel_native for p in photos if p.photo_rel_native in selected]


# ---------------------------------------------------------------------------
# Controles d integrite
# ---------------------------------------------------------------------------


def check_integrity(
    document: AssignmentsDocument,
    photos: Sequence[PhotoRef],
    subjects: Sequence[Subject],
) -> list[IntegrityIssue]:
    """Compare les affectations enregistrees aux referentiels courants.

    Ne corrige jamais automatiquement : les ecarts sont uniquement signales.
    """
    issues: list[IntegrityIssue] = []
    photo_set = {p.photo_rel_native for p in photos}
    subject_by_numero = {s.numero: s for s in subjects}

    for assignment in document.assignments:
        rel = assignment.photo_rel_native
        if rel not in photo_set:
            issues.append(
                IntegrityIssue(
                    kind="photo_missing",
                    photo_rel_native=rel,
                    message=(
                        f"⚠ Photo référencée dans les affectations mais absente "
                        f"du photos_batch.csv : {Path(rel.replace(chr(92), '/')).name}"
                    ),
                )
            )
            continue

        if assignment.status != STATUS_AFFECTEE:
            continue

        numero = assignment.subject_numero
        if numero is None:
            continue
        subject = subject_by_numero.get(numero)
        if subject is None:
            issues.append(
                IntegrityIssue(
                    kind="subject_missing",
                    photo_rel_native=rel,
                    subject_numero=numero,
                    message=f"⚠ Sujet {numero} absent du référentiel actuel",
                )
            )
            continue

        recorded_title = (assignment.subject_title or "").strip()
        recorded_location = (assignment.subject_location or "").strip()
        current_title = subject.titre.strip()
        current_location = subject.localisation.strip()
        if recorded_title != current_title or recorded_location != current_location:
            issues.append(
                IntegrityIssue(
                    kind="subject_metadata_changed",
                    photo_rel_native=rel,
                    subject_numero=numero,
                    message=(
                        "⚠ L'affectation enregistrée ne correspond plus exactement "
                        "au référentiel actuel."
                    ),
                    details={
                        "numero": str(numero),
                        "ancien_titre": recorded_title,
                        "titre_actuel": current_title,
                        "ancienne_localisation": recorded_location,
                        "localisation_actuelle": current_location,
                    },
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def build_summary(
    photos: Sequence[PhotoRef],
    index: dict[str, Assignment],
    subjects: Sequence[Subject],
) -> dict[str, Any]:
    """Construit le recapitulatif global de l affectation."""
    counts = {STATUS_NON_AFFECTEE: 0, STATUS_AFFECTEE: 0, STATUS_EXCLUE: 0}
    per_subject: dict[int, int] = {s.numero: 0 for s in subjects}
    for photo in photos:
        status = get_status(index, photo.photo_rel_native)
        counts[status] = counts.get(status, 0) + 1
        if status == STATUS_AFFECTEE:
            assignment = index.get(photo.photo_rel_native)
            if assignment and assignment.subject_numero is not None:
                per_subject[assignment.subject_numero] = (
                    per_subject.get(assignment.subject_numero, 0) + 1
                )

    subjects_with = sum(1 for count in per_subject.values() if count > 0)
    return {
        "total": len(photos),
        "affectees": counts[STATUS_AFFECTEE],
        "non_affectees": counts[STATUS_NON_AFFECTEE],
        "exclues": counts[STATUS_EXCLUE],
        "sujets_avec_photos": subjects_with,
        "sujets_sans_photos": len(per_subject) - subjects_with,
        "per_subject": per_subject,
    }


# ---------------------------------------------------------------------------
# Controle des prerequis
# ---------------------------------------------------------------------------


def check_prerequisites(
    *,
    sujets_path: Path | None,
    photos_batch_path: Path | None,
    global_final_path: Path | None,
    photos_dir: Path | None = None,
    photo_count: int = 0,
) -> list[dict[str, str]]:
    """Controle les quatre prerequis de la section.

    Retourne une liste de ``{element, etat, chemin, detail}``.
    """
    checks: list[dict[str, str]] = []

    def _add(element: str, path: Path | None, present: bool, detail: str = "") -> None:
        checks.append(
            {
                "element": element,
                "etat": STATE_OK if present else STATE_ABSENT,
                "chemin": str(path) if path else "",
                "detail": detail,
            }
        )

    _add("Sujets.xlsx", sujets_path, bool(sujets_path and sujets_path.is_file()))
    _add(
        "photos_batch.csv",
        photos_batch_path,
        bool(photos_batch_path and photos_batch_path.is_file()),
    )
    _add(
        "global_final.json",
        global_final_path,
        bool(global_final_path and global_final_path.is_file()),
        "Nécessaire au futur batch de contextualisation.",
    )

    photos_ok = bool(photos_dir and photos_dir.exists()) and photo_count > 0
    checks.append(
        {
            "element": "photos physiques",
            "etat": STATE_OK if photos_ok else STATE_ABSENT,
            "chemin": str(photos_dir) if photos_dir else "",
            "detail": f"{photo_count} photo(s) référencée(s) dans photos_batch.csv.",
        }
    )
    return checks


def mark_invalid(checks: list[dict[str, str]], element: str, detail: str) -> None:
    """Bascule un prerequis present mais inexploitable a l etat INVALIDE."""
    for check in checks:
        if check["element"] == element:
            check["etat"] = STATE_INVALID
            check["detail"] = detail
            return


# ---------------------------------------------------------------------------
# Filtres de galerie
# ---------------------------------------------------------------------------


def filter_photos(
    photos: Sequence[PhotoRef],
    index: dict[str, Assignment],
    filter_key: str,
    subject_numero: int | None = None,
) -> list[PhotoRef]:
    """Filtre la galerie sans jamais modifier l ordre canonique."""
    if filter_key == "Toutes":
        return list(photos)
    if filter_key == "Non affectées":
        return [p for p in photos if get_status(index, p.photo_rel_native) == STATUS_NON_AFFECTEE]
    if filter_key == "Affectées":
        return [p for p in photos if get_status(index, p.photo_rel_native) == STATUS_AFFECTEE]
    if filter_key == "Exclues":
        return [p for p in photos if get_status(index, p.photo_rel_native) == STATUS_EXCLUE]
    if filter_key == "Sujet sélectionné" and subject_numero is not None:
        return [
            p
            for p in photos
            if get_status(index, p.photo_rel_native) == STATUS_AFFECTEE
            and (index[p.photo_rel_native].subject_numero == subject_numero)
        ]
    return list(photos)
