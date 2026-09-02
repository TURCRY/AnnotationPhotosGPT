"""Interface Streamlit d affectation manuelle des photos aux sujets (Lot 1).

Ce module ne fait aucun appel LLM, ne cree aucun job et n ecrit que
``photo_subject_assignments.json``. Il est branche depuis
``LLM_Assistant/app.py`` dans la page « Annotation photos / Rapport Word ».
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

try:
    from . import photo_subject_core as core
except ImportError:  # chargement direct par chemin (tests, app.py)
    import photo_subject_core as core  # type: ignore[no-redef]

ASSIGNMENTS_FILENAME = core.ASSIGNMENTS_FILENAME

FILTER_OPTIONS = ("Toutes", "Non affectées", "Affectées", "Exclues", "Sujet sélectionné")

GALLERY_COLUMNS = 4
THUMB_WIDTH = 160


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------


def assignments_path_for(photos_dir: Path) -> Path:
    return Path(photos_dir) / ASSIGNMENTS_FILENAME


def _resolve_photo_paths(photo: core.PhotoRef, photos_dir: Path) -> tuple[Path | None, Path | None]:
    """Retrouve la miniature et l original d une photo.

    L arborescence type est ``<photos_dir>/JPG/<fichier>`` avec un dossier
    ``JPG reduit`` pour les miniatures. On reste tolerant : si la miniature
    est absente, l original est utilise.
    """
    rel = photo.photo_rel_native.replace("\\", "/")
    name = Path(rel).name
    native = photos_dir / name
    if not native.is_file():
        candidate = photos_dir / rel.split("/photos/")[-1] if "/photos/" in rel else None
        if candidate and candidate.is_file():
            native = candidate
    thumb: Path | None = None
    if native.is_file():
        reduced_dir = native.parent.parent / (native.parent.name + " reduit")
        candidate = reduced_dir / native.name
        thumb = candidate if candidate.is_file() else native
    return (thumb if thumb and thumb.is_file() else None), (native if native.is_file() else None)


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
        cr_numeros, cr_errors = core.read_global_final_numeros(global_final_path)

    photos, photo_errors = core.read_photos_batch(photos_batch_path)
    subjects, subject_errors = core.read_sujets_xlsx(sujets_path, cr_numeros=cr_numeros)

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
    document, load_errors = core.load_assignments(assignments_file)
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
            for rel in core.select_range(photos, first, last):
                st.session_state[f"{state_key}::sel::{rel}"] = True
            st.rerun()

    # --- 8. Galerie --------------------------------------------------------
    st.markdown("#### 4.5 Galerie")
    for start in range(0, len(visible), GALLERY_COLUMNS):
        chunk = visible[start : start + GALLERY_COLUMNS]
        columns = st.columns(GALLERY_COLUMNS)
        for column, photo in zip(columns, chunk):
            with column:
                _render_photo_cell(photo, photos_dir, index, state_key)

    # --- 9. Operations -----------------------------------------------------
    selected = [
        p.photo_rel_native
        for p in photos
        if bool(st.session_state.get(f"{state_key}::sel::{p.photo_rel_native}", False))
    ]
    st.markdown("#### 4.6 Opérations")
    st.write(f"{len(selected)} photo(s) sélectionnée(s).")

    col_aff, col_exc, col_rst = st.columns(3)
    with col_aff:
        if st.button(
            "Affecter les photos sélectionnées",
            key=f"{state_key}::assign",
            disabled=not selected,
        ):
            replaced = core.assign_photos(document, selected, selected_subject)
            core.save_assignments(
                assignments_file, document, id_affaire=id_affaire, id_captation=id_captation
            )
            if replaced:
                st.warning(
                    f"{len(replaced)} photo(s) déjà affectée(s) ont changé de sujet "
                    f"→ Sujet {selected_subject.numero}."
                )
            st.success(f"{len(selected)} photo(s) affectée(s) au sujet {selected_subject.numero}.")
            st.rerun()
    with col_exc:
        if st.button(
            "Exclure les photos sélectionnées",
            key=f"{state_key}::exclude",
            disabled=not selected,
        ):
            core.exclude_photos(document, selected)
            core.save_assignments(
                assignments_file, document, id_affaire=id_affaire, id_captation=id_captation
            )
            st.success(f"{len(selected)} photo(s) exclue(s).")
            st.rerun()
    with col_rst:
        if st.button(
            "Remettre en non affectée",
            key=f"{state_key}::reset",
            disabled=not selected,
        ):
            core.reset_photos(document, selected)
            core.save_assignments(
                assignments_file, document, id_affaire=id_affaire, id_captation=id_captation
            )
            st.success(f"{len(selected)} photo(s) remise(s) en non affectée.")
            st.rerun()

    if st.button("Tout désélectionner", key=f"{state_key}::clear"):
        for photo in photos:
            st.session_state.pop(f"{state_key}::sel::{photo.photo_rel_native}", None)
        st.rerun()

    st.caption(f"Fichier d'affectation : `{assignments_file}`")


def _render_photo_cell(
    photo: core.PhotoRef,
    photos_dir: Path,
    index: dict[str, core.Assignment],
    state_key: str,
) -> None:
    """Rend une vignette : index, nom, etat courant, case de selection."""
    thumb, native = _resolve_photo_paths(photo, photos_dir)
    if thumb is not None:
        try:
            st.image(str(thumb), width=THUMB_WIDTH)
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
    st.checkbox(
        "Sélectionner",
        key=f"{state_key}::sel::{photo.photo_rel_native}",
        label_visibility="collapsed",
    )
