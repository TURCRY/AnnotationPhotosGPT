from __future__ import annotations

r"""Helper temporel pour la galerie photo (Lot 1).

Objectif : afficher sous chaque vignette :

    ``014 · P1080231.JPG    10:42:37 · +00:27:14``

Regles de source de verite (pas de recalcul EXIF) :

* heure photo  -> colonne ``horodatage_photo`` de ``photos.csv`` (format
  reel ``JJ/MM/AAAA HH:MM:SS``), ou ``horodatage_secondes`` en repli,
  jamais recalculee depuis les EXIF ;
* debut audio  -> ``infos_projet.json`` : ``t0_global`` (valeur canonique
  ecrite par le calibrage) puis ``horodatage_audio`` ; en dernier recours
  ``min(ctime, mtime)`` du WAV *source* (``fichier_audio_source``).
  Le WAV compatible ``audio_compatible.wav`` genere apres coup n'est
  jamais utilise comme reference.

Le calcul utilise toujours les datetime completes (date incluse), meme si
l'UI n'affiche que l'heure.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any


# Format reellement rencontre dans photos.csv (cf. data/uploads/photos.csv).
PHOTO_DATETIME_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S.%f",
)

PHOTO_TIME_FORMATS = ("%H:%M:%S", "%H:%M")

PHOTO_DATETIME_COLUMNS = ("horodatage_photo", "horodatage", "date_photo", "datetime_photo")
PHOTO_SECONDS_COLUMNS = ("horodatage_secondes", "t_audio", "synchro_audio")

# Clefs de infos_projet.json, par ordre de priorite decroissant.
AUDIO_ORIGIN_KEYS = ("t0_global", "horodatage_audio")

AUDIO_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
)

UNKNOWN_AUDIO_MARKER = "audio ?"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_photo_datetime(raw: Any, default_date: datetime | None = None) -> datetime | None:
    """Parse un horodatage photo (format CSV reel ou ISO).

    Une heure seule (``HH:MM:SS``) n'est acceptee que si ``default_date``
    est fourni : on ne fabrique jamais de date au hasard.
    """
    text = _clean(raw)
    if not text:
        return None

    for fmt in PHOTO_DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    for fmt in PHOTO_TIME_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if default_date is None:
            return None
        return datetime.combine(default_date.date(), parsed.time())

    return None


def parse_audio_datetime(raw: Any) -> datetime | None:
    """Parse ``t0_global`` / ``horodatage_audio`` de infos_projet.json."""
    text = _clean(raw)
    if not text:
        return None
    for fmt in AUDIO_DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_seconds(raw: Any) -> float | None:
    text = _clean(raw).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_photo_datetime_from_row(
    row: dict[str, Any],
    *,
    default_date: datetime | None = None,
) -> datetime | None:
    """Extrait la datetime photo canonique d'une ligne de ``photos.csv``.

    Priorite : colonne de datetime complete, puis colonne de secondes
    interpretee comme un delai depuis ``default_date``. Aucune lecture EXIF.
    """
    for column in PHOTO_DATETIME_COLUMNS:
        parsed = parse_photo_datetime(row.get(column), default_date=default_date)
        if parsed is not None:
            return parsed

    if default_date is not None:
        for column in PHOTO_SECONDS_COLUMNS:
            seconds = _parse_seconds(row.get(column))
            if seconds is not None:
                return default_date + timedelta(seconds=seconds)

    return None


def format_duration(seconds: Any) -> str:
    """Formate une duree signee ``[+-]HH:MM:SS``.

    Le total d'heures n'est pas limite a 24 : 26 h donne ``26:00:00``.
    """
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return UNKNOWN_AUDIO_MARKER
    sign = "-" if total < 0 else "+"
    whole = int(abs(total))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"


def format_photo_time(moment: datetime | None) -> str:
    return moment.strftime("%H:%M:%S") if moment is not None else ""


def format_gallery_time_badge(
    photo_dt: datetime | None,
    audio_start: datetime | None,
) -> str:
    """Construit la partie temporelle du libelle de vignette.

    * ``"10:42:37 · +00:27:14"``  photo + origine audio connues ;
    * ``"10:42:37 · audio ?"``    origine audio inconnue ;
    * ``""``                      horodatage photo absent (rien invente).
    """
    if photo_dt is None:
        return ""
    time_text = format_photo_time(photo_dt)
    if audio_start is None:
        return f"{time_text} · {UNKNOWN_AUDIO_MARKER}"
    offset = (photo_dt - audio_start).total_seconds()
    return f"{time_text} · {format_duration(offset)}"


def _audio_origin_from_source_file(
    infos: dict[str, Any],
    *,
    reference: datetime | None = None,
) -> tuple[datetime | None, str]:
    """Avant-dernier recours : min(ctime, mtime) du WAV source de la captation.

    Le WAV compatible (``audio_compatible.wav``) est exclu : il est genere
    apres coup et son horodatage ne represente pas le debut de captation.

    Garde-fou : les metadonnees systeme peuvent correspondre a une date de
    copie, pas a la captation. Si ``reference`` est fourni (date de captation
    connue par ailleurs) et que l'ecart depasse 24 h, la valeur est rejetee.
    """
    source = _clean(infos.get("fichier_audio_source"))
    if not source or not os.path.exists(source):
        return None, ""
    try:
        stat = os.stat(source)
    except OSError:
        return None, ""
    moment = datetime.fromtimestamp(min(stat.st_ctime, stat.st_mtime)).replace(microsecond=0)
    if reference is not None and abs((moment - reference).total_seconds()) > 86400:
        return None, ""
    return moment, f"horodatage source WAV ({source})"


def resolve_audio_start(
    infos: dict[str, Any] | None,
    *,
    photos_rows: list[dict[str, Any]] | None = None,
) -> tuple[datetime | None, str]:
    """Retourne ``(datetime_debut_audio, origine_lisible)``.

    Priorite :
    1. ``infos_projet.json:t0_global``   (canonique, ecrit par le calibrage) ;
    2. ``infos_projet.json:horodatage_audio`` ;
    3. origine reconstruite depuis ``photos.csv`` (``decalage_moyen``) ;
    4. metadonnee du WAV source reel, garde-fou 24 h (fallback documente).

    Le WAV source passe APRES ``photos.csv`` : son horodatage systeme peut
    n'etre qu'une date de copie, alors que ``decalage_moyen`` est la valeur
    validee par le calibrage photo/audio.
    """
    infos = infos if isinstance(infos, dict) else {}
    for key in AUDIO_ORIGIN_KEYS:
        parsed = parse_audio_datetime(infos.get(key))
        if parsed is not None:
            return parsed, f"infos_projet.json:{key}"

    from_csv, origin = resolve_audio_start_from_photos_csv(photos_rows or [], infos)
    if from_csv is not None:
        return from_csv, origin

    fallback, origin = _audio_origin_from_source_file(infos, reference=from_csv)
    return fallback, origin


def resolve_audio_start_from_photos_csv(
    rows: list[dict[str, Any]],
    infos: dict[str, Any] | None = None,
) -> tuple[datetime | None, str]:
    """Origine audio reconstruite depuis ``photos.csv`` (fallback documente).

    Utilise uniquement quand ``infos_projet.json`` ne porte pas de
    ``t0_global`` / ``horodatage_audio`` exploitables. Regle du pipeline de
    synchronisation :

        ``t0 = horodatage_photo - horodatage_secondes + decalage_moyen``

    ou ``decalage_moyen`` est le decalage global photo/audio valide au
    calibrage. La valeur retenue est la mediane des estimations, afin qu un
    point de synchro aberrant ne decale pas toute la galerie.
    """
    estimates: list[datetime] = []
    for row in rows or []:
        moment = parse_photo_datetime(row.get("horodatage_photo"))
        offset = _parse_seconds(row.get("horodatage_secondes"))
        if moment is None or offset is None:
            continue
        decalage = _parse_seconds(row.get("decalage_moyen"))
        if decalage is None:
            decalage = _parse_seconds((infos or {}).get("decalage_moyen")) or 0.0
        estimates.append(
            moment - timedelta(seconds=offset) + timedelta(seconds=decalage)
        )

    if not estimates:
        return None, ""

    ordered = sorted(estimates)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        chosen = ordered[middle]
    else:
        low = ordered[middle - 1]
        high = ordered[middle]
        chosen = low + timedelta(seconds=(high - low).total_seconds() / 2)
    count = len(estimates)
    return chosen.replace(microsecond=0), f"photos.csv:decalage_moyen ({count} estimation(s))"


def load_infos_projet(path: Any) -> dict[str, Any]:
    """Charge infos_projet.json sans lever d'exception."""
    if not path:
        return {}
    try:
        with open(str(path), "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_audio_start_from_file(
    path: Any,
    *,
    photos_rows: list[dict[str, Any]] | None = None,
) -> tuple[datetime | None, str]:
    return resolve_audio_start(load_infos_projet(path), photos_rows=photos_rows)
