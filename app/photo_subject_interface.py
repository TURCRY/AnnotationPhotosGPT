"""Interface Streamlit d affectation manuelle des photos aux sujets (Lot 1).

Ce module ne fait aucun appel LLM, ne cree aucun job et n ecrit que
``photo_subject_assignments.json``. Il est branche depuis
``LLM_Assistant/app.py`` dans la page « Annotation photos / Rapport Word ».
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import streamlit as st

try:
    from . import photo_subject_core as core
except ImportError:  # chargement direct par chemin (tests, app.py)
    import photo_subject_core as core  # type: ignore[no-redef]

ASSIGNMENTS_FILENAME = core.ASSIGNMENTS_FILENAME

FILTER_OPTIONS = ("Toutes", "Non affectées", "Affectées", "Exclues", "Sujet sélectionné")

GALLERY_COLUMNS = 3
GALLERY_IMAGE_MAX_WIDTH = 480


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------


def assignments_path_for(photos_dir: Path) -> Path:
    return Path(photos_dir) / ASSIGNMENTS_FILENAME


def _resolve_photo_paths(photo: core.PhotoRef, photos_dir: Path) -> tuple[Path | None, Path | None]:
    """Retrouve la miniature et l original d une photo."""
    rel = photo.photo_rel_native.replace("\\", "/")
    name = Path(rel).name
    suffix = rel.split("/photos/", 1)[-1] if "/photos/" in rel else rel

    native_candidates = [
        photos_dir / suffix,
        photos_dir / "JPG" / name,
        photos_dir / name,
    ]
    native = next((candidate for candidate in native_candidates if candidate.is_file()), None)

    thumb_candidates = [photos_dir / "JPG reduit" / name]
    if suffix.startswith("JPG/"):
        thumb_candidates.append(photos_dir / suffix.replace("JPG/", "JPG reduit/", 1))
    if native is not None:
        reduced_dir = native.parent.parent / (native.parent.name + " reduit")
        thumb_candidates.append(reduced_dir / native.name)
        thumb_candidates.append(native)

    thumb = next((candidate for candidate in thumb_candidates if candidate.is_file()), None)
    return thumb, native


def _file_cache_token(path: Path) -> tuple[str, int | None, int | None]:
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return str(path), None, None
    return str(path), stat.st_mtime_ns, stat.st_size


def _dir_cache_token(path: Path) -> tuple[str, int | None]:
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return str(path), None
    return str(path), stat.st_mtime_ns


@st.cache_data(show_spinner=False)
def _cached_read_global_final_numeros(path_text: str, token: tuple[str, int | None, int | None]):
    del token
    return core.read_global_final_numeros(Path(path_text))


@st.cache_data(show_spinner=False)
def _cached_read_photos_batch(path_text: str, token: tuple[str, int | None, int | None]):
    del token
    return core.read_photos_batch(Path(path_text))


@st.cache_data(show_spinner=False)
def _cached_read_sujets_xlsx(
    path_text: str,
    token: tuple[str, int | None, int | None],
    cr_numeros_key: tuple[int, ...],
):
    del token
    return core.read_sujets_xlsx(Path(path_text), cr_numeros=set(cr_numeros_key))


@st.cache_data(show_spinner=False)
def _cached_load_assignments(path_text: str, token: tuple[str, int | None, int | None]):
    del token
    return core.load_assignments(Path(path_text))


@st.cache_data(show_spinner=False)
def _cached_resolve_photo_paths(
    rel: str,
    display_name: str,
    photos_dir_text: str,
    photos_dir_token: tuple[str, int | None],
    jpg_dir_token: tuple[str, int | None],
    reduced_dir_token: tuple[str, int | None],
) -> tuple[str | None, str | None]:
    del photos_dir_token, jpg_dir_token, reduced_dir_token
    photo = core.PhotoRef(index=0, photo_rel_native=rel, display_name=display_name)
    thumb, native = _resolve_photo_paths(photo, Path(photos_dir_text))
    return (str(thumb) if thumb else None), (str(native) if native else None)


@st.cache_data(show_spinner=False, max_entries=800)
def _cached_gallery_image_bytes(
    path_text: str,
    token: tuple[str, int | None, int | None],
    max_width: int,
) -> bytes:
    del token
    from PIL import Image, ImageOps

    with Image.open(path_text) as image:
        try:
            image.draft("RGB", (max_width, max_width))
        except Exception:
            pass
        image = ImageOps.exif_transpose(image)
        if image.width > max_width:
            height = max(1, int(image.height * max_width / image.width))
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=82)
        return buffer.getvalue()


def _selection_key(state_key: str) -> str:
    return f"{state_key}::selected"


def _checkbox_key(state_key: str, photo_rel_native: str) -> str:
    return f"{state_key}::sel::{photo_rel_native}"


def _selection_reset_key(state_key: str) -> str:
    return f"{state_key}::selection_reset_pending"


def _get_selection(state_key: str) -> set[str]:
    return core.normalize_photo_selection(st.session_state.get(_selection_key(state_key), set()))


def _set_selection(state_key: str, photos: list[core.PhotoRef], selected: set[str]) -> None:
    selected = core.normalize_photo_selection(selected)
    st.session_state[_selection_key(state_key)] = selected
    for photo in photos:
        st.session_state[_checkbox_key(state_key, photo.photo_rel_native)] = (
            photo.photo_rel_native in selected
        )


def _clear_selection(state_key: str, photos: list[core.PhotoRef]) -> None:
    del photos
    st.session_state[_selection_key(state_key)] = core.clear_photo_selection()
    st.session_state[_selection_reset_key(state_key)] = True


def _ensure_selection_state(state_key: str, photos: list[core.PhotoRef]) -> set[str]:
    key = _selection_key(state_key)
    if st.session_state.pop(_selection_reset_key(state_key), False) or key not in st.session_state:
        _set_selection(state_key, photos, core.clear_photo_selection())
        return set()

    selected = _get_selection(state_key)
    known = {p.photo_rel_native for p in photos}
    selected = {rel for rel in selected if rel in known}
    for photo in photos:
        checkbox_value = bool(st.session_state.get(_checkbox_key(state_key, photo.photo_rel_native), False))
        selected = core.update_photo_selection(selected, photo.photo_rel_native, checkbox_value)
    st.session_state[key] = selected
    return selected


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------


def render_photo_subject_section(
    *,
    id_affaire: str,
    id_captation: str,
    sujets_path: Path,
    photos_batch_path: Path,
    global_final_path: Path,
    photos_dir: Path,
) -> None:
    """Rend la section « Contextualisation des photos par sujet »."""
    st.markdown("### 4. Contextualisation des photos par sujet")
    st.caption(
        "Affectation manuelle des photographies aux sujets. "
        "Aucun traitement LLM n'est lancé depuis cette section."
    )

    scope = f"{id_affaire}|{id_captation}"
    state_key = f"photo_subject::{scope}"

    # --- 1. Prerequis -----------------------------------------------------
    st.markdown("#### 4.1 Prérequis")
    cr_numeros: set[int] = set()
    cr_errors: list[str] = []
    if global_final_path.is_file():
        cr_numeros, cr_errors = _cached_read_global_final_numeros(
            str(global_final_path), _file_cache_token(global_final_path)
        )

    photos, photo_errors = _cached_read_photos_batch(
        str(photos_batch_path), _file_cache_token(photos_batch_path)
    )
    subjects, subject_errors = _cached_read_sujets_xlsx(
        str(sujets_path), _file_cache_token(sujets_path), tuple(sorted(cr_numeros))
    )

    checks = core.check_prerequisites(
        sujets_path=sujets_path,
        photos_batch_path=photos_batch_path,
        global_final_path=global_final_path,
        photos_dir=photos_dir,
        photo_count=len(photos),
    )
    if photo_errors:
        core.mark_invalid(checks, "photos_batch.csv", " ".join(photo_errors))
    if subject_errors:
        core.mark_invalid(checks, "Sujets.xlsx", " ".join(subject_errors))
    if cr_errors and global_final_path.is_file():
        core.mark_invalid(checks, "global_final.json", " ".join(cr_errors))

    for check in checks:
        icon = {"OK": "✅", "ABSENT": "❌", "INVALIDE": "⚠️"}.get(check["etat"], "•")
        line = f"{icon} **{check['element']}** — `{check['etat']}`"
        if check["detail"]:
            line += f" — {check['detail']}"
        if check["etat"] == "OK":
            st.markdown(line)
        elif check["etat"] == "INVALIDE":
            st.warning(line)
        else:
            st.error(line)

    blocking = [c for c in checks if c["etat"] != "OK" and c["element"] != "global_final.json"]
    if blocking:
        st.info(
            "L'affectation reste possible tant que Sujets.xlsx et photos_batch.csv "
            "sont exploitables."
        )

    if not subjects:
        st.error("Aucun sujet exploitable : impossible d'afficher la galerie.")
        return
    if not photos:
        st.error("Aucune photo exploitable : impossible d'afficher la galerie.")
        return

    # --- 2. Chargement des affectations -----------------------------------
    assignments_file = assignments_path_for(photos_dir)
    document, load_errors = _cached_load_assignments(
        str(assignments_file), _file_cache_token(assignments_file)
    )
    for message in load_errors:
        st.warning(message)

    index = core.build_assignment_index(document)

    # --- 3. Controles d integrite -----------------------------------------
    issues = core.check_integrity(document, photos, subjects)
    if issues:
        st.markdown("#### 4.2 Contrôles d'intégrité")
        seen: set[tuple[str, str | None]] = set()
        for issue in issues:
            dedup = (issue.kind, issue.photo_rel_native)
            if dedup in seen:
                continue
            seen.add(dedup)
            st.warning(issue.message)
            if issue.details:
                st.caption(
                    f"Numéro : {issue.details.get('numero', '')} · "
                    f"Ancien titre : « {issue.details.get('ancien_titre', '')} » · "
                    f"Titre actuel : « {issue.details.get('titre_actuel', '')} » · "
                    f"Ancienne localisation : « {issue.details.get('ancienne_localisation', '')} » · "
                    f"Localisation actuelle : « {issue.details.get('localisation_actuelle', '')} »"
                )
        st.caption("Aucune correction automatique n'est appliquée.")

    # --- 4. Resume ---------------------------------------------------------
    summary = core.build_summary(photos, index, subjects)
    st.markdown("#### 4.3 Résumé")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Photos totales", summary["total"])
    col2.metric("Affectées", summary["affectees"])
    col3.metric("Non affectées", summary["non_affectees"])
    col4.metric("Exclues", summary["exclues"])
    st.caption(
        f"Sujets avec photos : {summary['sujets_avec_photos']} · "
        f"Sujets sans photos : {summary['sujets_sans_photos']}"
    )
    with st.expander("Détail par sujet", expanded=False):
        for subject in subjects:
            count = summary["per_subject"].get(subject.numero, 0)
            flag = "✓" if subject.has_cr_context else "⚠"
            st.write(f"{flag} Sujet {subject.numero} — {subject.titre or '(sans titre)'} : {count} photo(s)")

    # --- 5. Choix du sujet -------------------------------------------------
    st.markdown("#### 4.4 Affectation")
    subject_labels = []
    for subject in subjects:
        flag = "✓" if subject.has_cr_context else "⚠"
        subject_labels.append(f"{flag} Sujet {subject.numero} — {subject.titre or '(sans titre)'}")
    selected_label = st.selectbox(
        "Sujet cible",
        subject_labels,
        key=f"{state_key}::subject",
    )
    selected_subject = subjects[subject_labels.index(selected_label)]
    if selected_subject.has_cr_context:
        st.success("✓ contexte compte-rendu disponible")
    else:
        st.warning("⚠ contexte compte-rendu absent")
    if selected_subject.localisation:
        st.write(f"Localisation : {selected_subject.localisation}")
    if selected_subject.description:
        st.caption(selected_subject.description)

    # --- 6. Filtres --------------------------------------------------------
    filter_key = st.radio(
        "Filtre de galerie",
        FILTER_OPTIONS,
        horizontal=True,
        key=f"{state_key}::filter",
    )
    visible = core.filter_photos(
        photos, index, filter_key, subject_numero=selected_subject.numero
    )
    _ensure_selection_state(state_key, photos)
    st.caption(f"{len(visible)} photo(s) affichée(s) — ordre canonique du CSV conservé.")

    # --- 7. Selection par plage -------------------------------------------
    with st.expander("Sélectionner une plage", expanded=False):
        options = [f"{p.index:03d} — {p.display_name}" for p in photos]
        col_a, col_b = st.columns(2)
        first_label = col_a.selectbox("Première photo", options, key=f"{state_key}::range_first")
        last_label = col_b.selectbox(
            "Dernière photo",
            options,
            index=len(options) - 1 if options else 0,
            key=f"{state_key}::range_last",
        )
        if st.button("Sélectionner cette plage", key=f"{state_key}::range_apply"):
            first = photos[options.index(first_label)].photo_rel_native
            last = photos[options.index(last_label)].photo_rel_native
            selected_range = core.replace_photo_selection(core.select_range(photos, first, last))
            _set_selection(state_key, photos, selected_range)
            st.rerun()

    # --- 8. Operations -----------------------------------------------------
    _render_photo_operations(
        block_id="top",
        photos=photos,
        document=document,
        assignments_file=assignments_file,
        selected_subject=selected_subject,
        id_affaire=id_affaire,
        id_captation=id_captation,
        state_key=state_key,
    )

    # --- 9. Galerie --------------------------------------------------------
    st.markdown("#### 4.5 Galerie")
    for start in range(0, len(visible), GALLERY_COLUMNS):
        chunk = visible[start : start + GALLERY_COLUMNS]
        columns = st.columns(GALLERY_COLUMNS, gap="small")
        for column, photo in zip(columns, chunk):
            with column:
                _render_photo_cell(photo, photos_dir, index, state_key)

    # --- 10. Operations bas de galerie -------------------------------------
    _render_photo_operations(
        block_id="bottom",
        photos=photos,
        document=document,
        assignments_file=assignments_file,
        selected_subject=selected_subject,
        id_affaire=id_affaire,
        id_captation=id_captation,
        state_key=state_key,
    )

    st.caption(f"Fichier d'affectation : `{assignments_file}`")


def _render_photo_operations(
    *,
    block_id: str,
    photos: list[core.PhotoRef],
    document: core.AssignmentsDocument,
    assignments_file: Path,
    selected_subject: core.Subject,
    id_affaire: str,
    id_captation: str,
    state_key: str,
) -> None:
    """Rend les actions sur un snapshot explicite de la selection UI."""
    selected = core.snapshot_photo_selection(photos, _get_selection(state_key))
    st.markdown("#### Opérations")
    st.write(f"{len(selected)} photo(s) sélectionnée(s).")

    col_aff, col_exc, col_rst = st.columns(3)
    with col_aff:
        if st.button(
            "Affecter les photos sélectionnées",
            key=f"{state_key}::{block_id}::assign",
            disabled=not selected,
        ):
            selected_now = core.snapshot_photo_selection(photos, _get_selection(state_key))
            replaced = core.assign_photos(document, selected_now, selected_subject)
            core.save_assignments(
                assignments_file, document, id_affaire=id_affaire, id_captation=id_captation
            )
            _cached_load_assignments.clear()
            _clear_selection(state_key, photos)
            if replaced:
                st.warning(
                    f"{len(replaced)} photo(s) déjà affectée(s) ont changé de sujet "
                    f"→ Sujet {selected_subject.numero}."
                )
            st.success(f"{len(selected_now)} photo(s) affectée(s) au sujet {selected_subject.numero}.")
            st.rerun()
    with col_exc:
        if st.button(
            "Exclure les photos sélectionnées",
            key=f"{state_key}::{block_id}::exclude",
            disabled=not selected,
        ):
            selected_now = core.snapshot_photo_selection(photos, _get_selection(state_key))
            core.exclude_photos(document, selected_now)
            core.save_assignments(
                assignments_file, document, id_affaire=id_affaire, id_captation=id_captation
            )
            _cached_load_assignments.clear()
            _clear_selection(state_key, photos)
            st.success(f"{len(selected_now)} photo(s) exclue(s).")
            st.rerun()
    with col_rst:
        if st.button(
            "Remettre en non affectée",
            key=f"{state_key}::{block_id}::reset",
            disabled=not selected,
        ):
            selected_now = core.snapshot_photo_selection(photos, _get_selection(state_key))
            core.reset_photos(document, selected_now)
            core.save_assignments(
                assignments_file, document, id_affaire=id_affaire, id_captation=id_captation
            )
            _cached_load_assignments.clear()
            _clear_selection(state_key, photos)
            st.success(f"{len(selected_now)} photo(s) remise(s) en non affectée.")
            st.rerun()

    if st.button("Tout désélectionner", key=f"{state_key}::{block_id}::clear"):
        _clear_selection(state_key, photos)
        st.rerun()


def _render_photo_cell(
    photo: core.PhotoRef,
    photos_dir: Path,
    index: dict[str, core.Assignment],
    state_key: str,
) -> None:
    """Rend une vignette : index, nom, etat courant, case de selection."""
    thumb_text, native_text = _cached_resolve_photo_paths(
        photo.photo_rel_native,
        photo.display_name,
        str(photos_dir),
        _dir_cache_token(photos_dir),
        _dir_cache_token(photos_dir / "JPG"),
        _dir_cache_token(photos_dir / "JPG reduit"),
    )
    del native_text
    if thumb_text is not None:
        try:
            image_bytes = _cached_gallery_image_bytes(
                thumb_text, _file_cache_token(Path(thumb_text)), GALLERY_IMAGE_MAX_WIDTH
            )
            st.image(image_bytes, use_container_width=True)
        except Exception as exc:
            st.caption(f"Miniature illisible : {exc}")
    else:
        st.caption("(miniature absente)")

    status = core.get_status(index, photo.photo_rel_native)
    if status == core.STATUS_AFFECTEE:
        assignment = index[photo.photo_rel_native]
        state_text = f"Sujet {assignment.subject_numero}"
    elif status == core.STATUS_EXCLUE:
        state_text = "Exclue"
    else:
        state_text = "Non affectée"

    st.caption(f"**{photo.index:03d}** · {photo.display_name}")
    st.caption(state_text)
    checked = st.checkbox(
        "Sélectionner",
        key=_checkbox_key(state_key, photo.photo_rel_native),
        label_visibility="collapsed",
    )
    st.session_state[_selection_key(state_key)] = core.update_photo_selection(
        _get_selection(state_key), photo.photo_rel_native, checked
    )
