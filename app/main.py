import sys
import os
import shutil
import threading
import logging
import wave
from pathlib import Path
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
st.set_page_config(layout="wide")  # <-- doit être AVANT tout autre st.*

from selection_fichiers_interface import show_selection_interface
from synchronisation_interface import show_sync_interface
from annotation_interface_gpt import show_annotation_interface
from utils import (
    lire_infos_projet,
    purge_temp_audio,
    get_canonical_affaires_root,
    canonicalize_affaires_path,
    project_path_exists,
    same_project_path,
)
from path_migration import migrate_photo_dataframe_paths
from datetime import datetime
import time
from contextlib import contextmanager


if os.environ.get("ANNOTATIONPHOTOSGPT_PYTHONPATH_LOGGED") != "1":
    print("✅ PYTHONPATH temporaire ajouté :", sys.path[0])
    os.environ["ANNOTATIONPHOTOSGPT_PYTHONPATH_LOGGED"] = "1"

log = logging.getLogger("batch_sync")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_handler)
log.setLevel(logging.INFO)
log.propagate = False

NAS_AFFAIRES_ROOT = get_canonical_affaires_root()
_BATCH_SYNC_RESULTS: dict[str, dict] = {}
_BATCH_SYNC_RESULTS_LOCK = threading.Lock()


BATCH_COLS = [
    "description_vlm",
    "libelle_propose",
    "commentaire_propose",
    "batch_status",
    "batch_ts",
    "vlm_batch_id",
    "vlm_err",
    "vlm_prompt_ctx_len",
    "vlm_img_bytes",
    "vlm_mode",
    "vlm_call_id",
]


DICTEE_COLS = [
    "dictee_audio_path_pcfixe",
    "dictee_asr_text",
    "dictee_asr_status",
    "dictee_asr_ts",
    "dictee_audio_sha256",
    "dictee_audio_size",
]

def _is_nan_or_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    s = str(v).strip()
    return (s == "" or s.lower() == "nan")

def load_latest_annotations_xlsx(base_dir: Path, base_name: str) -> Path | None:
    candidates = sorted(base_dir.glob(f"{base_name}_GTP_*.xlsx"))
    return candidates[-1] if candidates else None


def get_locked_photo_keys_from_annotations(annotations_xlsx: Path) -> set[str]:
    try:
        df = pd.read_excel(annotations_xlsx)
    except Exception:
        return set()
    if "nom_fichier_image" not in df.columns:
         return set()
    # ✅ Verrouillage uniquement si annotation_validee == 1
    if "annotation_validee" not in df.columns:
        # Ancien format : ne pas verrouiller par présence, sinon on bloquera tout
        return set()

    df["annotation_validee"] = pd.to_numeric(df["annotation_validee"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    locked = df.loc[df["annotation_validee"] == 1, "nom_fichier_image"]
    return set(locked.astype(str).str.strip())



def atomic_write_csv(df: pd.DataFrame, target_path: Path):
    tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
    df.to_csv(tmp_path, sep=";", encoding="utf-8-sig", index=False)
    os.replace(tmp_path, target_path)


def _parse_ts(v) -> datetime | None:
    """Parse un TS CSV (ex: '2026-02-11 14:32:01'). Retourne None si invalide."""
    if _is_nan_or_empty(v):
        return None
    s = str(v).strip()
    # tolérance : 'YYYY-MM-DD HH:MM:SS' ou ISO
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None

def _is_newer(ts_new, ts_old) -> bool:
    """True si ts_new est strictement plus récent que ts_old."""
    a = _parse_ts(ts_new)
    b = _parse_ts(ts_old)
    if a is None or b is None:
        return False
    return a > b

def _has_any_value(row, cols) -> bool:
    for c in cols:
        if c in row.index and not _is_nan_or_empty(row.get(c, "")):
            return True
    return False

def _safe_stat(path: str) -> tuple[bool, float]:
    try:
        return (bool(path) and os.path.exists(path), os.path.getmtime(path))
    except Exception:
        return (False, 0.0)


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path) if path and os.path.exists(path) else -1
    except Exception:
        return -1


def _normalized_abs_path(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(path or "").strip()))
    except Exception:
        return str(path or "").strip()


def _pcfixe_to_nas(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    return canonicalize_affaires_path(raw)


def _publish_batch_sync_result(sync_id: str | None, **payload) -> None:
    if not sync_id:
        return
    with _BATCH_SYNC_RESULTS_LOCK:
        _BATCH_SYNC_RESULTS[sync_id] = dict(payload)


def _pop_batch_sync_result(sync_id: str | None) -> dict | None:
    if not sync_id:
        return None
    with _BATCH_SYNC_RESULTS_LOCK:
        return _BATCH_SYNC_RESULTS.pop(sync_id, None)


def _sync_batch_from_nas_impl(infos: dict, sync_id: str | None = None) -> None:
    try:
        pcfixe = infos.get("pcfixe", {}) or {}
        if not isinstance(pcfixe, dict):
            _publish_batch_sync_result(sync_id, done=True, copied=False, error="", branch="invalid_pcfixe")
            return

        # `pcfixe.fichier_photos_batch` est la source canonique produite
        # par le batch NAS/PC fixe ; `fichier_photos_batch` est la copie
        # locale consommée par l'application laptop.
        nas_path = _pcfixe_to_nas(pcfixe.get("fichier_photos_batch", ""))
        local_path = str(infos.get("fichier_photos_batch", "") or "").strip()
        infos_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "infos_projet.json"))
        log.info("[BATCH_SYNC] resolved_nas_path=%s", nas_path)
        if not nas_path or not local_path:
            log.info(
                "[BATCH_SYNC][TEMP] branche=paths_missing infos_path=%s nas_path=%s local_path=%s",
                infos_path,
                nas_path,
                local_path,
            )
            _publish_batch_sync_result(sync_id, done=True, copied=False, error="", branch="paths_missing")
            return

        normalized_nas_path = _normalized_abs_path(nas_path)
        normalized_local_path = _normalized_abs_path(local_path)
        nas_ok, nas_mtime = _safe_stat(nas_path)
        local_ok, local_mtime = _safe_stat(local_path)
        nas_size = _safe_size(nas_path)
        local_size = _safe_size(local_path)

        log.info(
            "[BATCH_SYNC][TEMP] infos_path=%s nas_path=%s local_path=%s normalized_nas_path=%s normalized_local_path=%s nas_ok=%s local_ok=%s nas_mtime=%s local_mtime=%s nas_size=%s local_size=%s",
            infos_path,
            nas_path,
            local_path,
            normalized_nas_path,
            normalized_local_path,
            nas_ok,
            local_ok,
            nas_mtime,
            local_mtime,
            nas_size,
            local_size,
        )

        if normalized_nas_path == normalized_local_path:
            log.warning("[BATCH_SYNC][TEMP] branche=same_file")
            log.warning("[BATCH_SYNC] Synchronisation ignorée : le chemin local du batch pointe déjà vers la source canonique")
            _publish_batch_sync_result(sync_id, done=True, copied=False, error="", branch="same_file")
            return

        if not nas_ok:
            log.warning("[BATCH_SYNC][TEMP] branche=source_absente")
            _publish_batch_sync_result(sync_id, done=True, copied=False, error="", branch="source_absente")
            return

        if not local_ok:
            log.info("[BATCH_SYNC][TEMP] branche=destination_absente")

        if local_ok and nas_mtime <= local_mtime and nas_size == local_size:
            log.info("[BATCH_SYNC][TEMP] branche=deja_a_jour")
            log.info("[BATCH_SYNC] Déjà à jour (copie locale du batch)")
            _publish_batch_sync_result(sync_id, done=True, copied=False, error="", branch="deja_a_jour")
            return

        log.info("[BATCH_SYNC][TEMP] branche=copie_necessaire")
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(nas_path, local_path)
        log.info("[BATCH_SYNC] Copie effectuée source canonique -> copie locale")
        _publish_batch_sync_result(sync_id, done=True, copied=True, error="", branch="copie_necessaire")
    except Exception as e:
        log.warning(f"[BATCH_SYNC] Erreur accès NAS (non bloquant): {e}")
        _publish_batch_sync_result(sync_id, done=True, copied=False, error=str(e), branch="error")


def sync_batch_from_nas(infos: dict, sync_id: str | None = None) -> threading.Thread:
    worker = threading.Thread(
        target=_sync_batch_from_nas_impl,
        args=(dict(infos or {}), sync_id),
        daemon=True,
        name="batch-sync-from-nas",
    )
    worker.start()
    return worker


def _refresh_batch_sync_state_from_worker() -> None:
    worker = st.session_state.get("_batch_sync_worker")
    if worker is not None and not worker.is_alive():
        st.session_state["batch_sync_in_progress"] = False
        st.session_state["batch_sync_done"] = True
        st.session_state["_batch_sync_worker"] = None

    sync_id = str(st.session_state.get("_batch_sync_id") or "").strip()
    if not sync_id:
        return
    result = _pop_batch_sync_result(sync_id)
    if not result:
        return
    st.session_state["batch_sync_in_progress"] = False
    st.session_state["batch_sync_done"] = True
    st.session_state["batch_sync_error"] = str(result.get("error") or "").strip()
    st.session_state["batch_sync_branch"] = str(result.get("branch") or "").strip()
    st.session_state["batch_sync_copied"] = bool(result.get("copied"))


def show_batch_status(infos: dict):
    p = str(infos.get("fichier_photos_batch", "") or "").strip()
    ok, mtime = _safe_stat(p)
    st.subheader("📦 État photos_batch.csv")
    st.write(p if p else "(non défini dans infos_projet.json)")
    if st.session_state.get("batch_sync_in_progress", False):
        st.info("Synchronisation du batch en cours...")
        return
    if st.session_state.get("batch_sync_error", ""):
        st.warning(f"Synchronisation batch terminée avec erreur : {st.session_state.get('batch_sync_error')}")
    elif st.session_state.get("batch_sync_done", False):
        branch = str(st.session_state.get("batch_sync_branch") or "").strip()
        copied = bool(st.session_state.get("batch_sync_copied", False))
        if copied:
            st.success("Synchronisation batch terminée : copie locale mise à jour.")
        elif branch:
            st.caption(f"Synchronisation batch terminée ({branch}).")
    if ok:
        st.success(f"✅ Présent — modifié le {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        st.warning("⚠️ Absent — le batch n’a peut-être pas encore produit le fichier, ou la copie n’a pas été faite.")


def _set_ui_return_reason(reason: str) -> None:
    if reason:
        st.session_state["selection_return_reason"] = reason


def _consume_ui_return_reason() -> str:
    return str(st.session_state.pop("selection_return_reason", "") or "").strip()

def _norm_path(path_value: str) -> str:
    return os.path.normcase(os.path.abspath(str(path_value or "").strip().strip('"')))


def _same_path(left: str, right: str) -> bool:
    return same_project_path(left, right)


def _is_expected_compatible_wav(path_value: str) -> bool:
    path_abs = str(path_value or "").strip()
    if not path_abs or not os.path.isfile(path_abs) or not path_abs.lower().endswith(".wav"):
        return False
    try:
        with wave.open(path_abs, "rb") as wav_file:
            return (
                wav_file.getcomptype() == "NONE"
                and wav_file.getnchannels() == 1
                and wav_file.getsampwidth() == 2
                and wav_file.getframerate() == 16000
            )
    except Exception:
        return False


def _horodatage_audio_status(infos: dict) -> tuple[str, str]:
    raw = str(infos.get("horodatage_audio") or "").strip()
    if not raw:
        return "absent", "Horodatage de debut de l'audio absent. Renseignez-le pour initialiser la synchronisation Audio / Photos."
    try:
        datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return "valide", ""
    except ValueError:
        return "format_invalide", "Format de horodatage_audio invalide. Format attendu : YYYY-MM-DD HH:MM:SS."


def _project_status(infos: dict) -> dict:
    file_blockers = []

    photos = str(infos.get("fichier_photos", "") or "").strip()
    if not photos or not project_path_exists(photos):
        file_blockers.append("fichier_photos manquant")

    transcription = str(infos.get("fichier_transcription", "") or "").strip()
    if not transcription or not project_path_exists(transcription):
        file_blockers.append("fichier_transcription manquant")

    audio_source = str(infos.get("fichier_audio_source", "") or "").strip()
    audio_compat = str(infos.get("fichier_audio_compatible", "") or infos.get("fichier_audio", "") or "").strip()
    compat_source = str(infos.get("audio_compat_source", "") or "").strip()
    audio_blockers = []

    if not audio_source or not project_path_exists(audio_source):
        audio_blockers.append("fichier_audio_source manquant")
    elif not audio_compat or not project_path_exists(audio_compat):
        audio_blockers.append("audio compatible manquant")
    elif compat_source and not _same_path(compat_source, audio_source):
        audio_blockers.append("audio compatible incoherent avec la source")
    elif _same_path(audio_compat, audio_source) and not _is_expected_compatible_wav(audio_source):
        audio_blockers.append("audio compatible incoherent avec la source")

    horodatage_state, horodatage_message = _horodatage_audio_status(infos)

    return {
        "files_ready": not file_blockers,
        "audio_ready": not audio_blockers,
        "calibrage_ready": bool(infos.get("calibrage_valide", False)),
        "contexte_ready": True,
        "horodatage_audio_state": horodatage_state,
        "horodatage_audio_message": horodatage_message,
        "file_blockers": file_blockers,
        "audio_blockers": audio_blockers,
        "blockers": file_blockers + audio_blockers,
    }


def _project_blockers(infos: dict) -> list[str]:
    return list(_project_status(infos)["blockers"])

def load_csv(path: str, sep=";") -> pd.DataFrame:
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, sep=sep, encoding=enc)
            df, changed = migrate_photo_dataframe_paths(df)
            if changed:
                df.to_csv(path, sep=sep, encoding="utf-8-sig", index=False)
            return df
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Impossible de lire {path}. Dernière erreur: {last_err}")



def preview_merge(infos: dict):
    photos_ui = str(infos.get("fichier_photos", "") or "")
    photos_batch = str(infos.get("fichier_photos_batch", "") or "")

    if not photos_ui or not os.path.exists(photos_ui):
        st.error("photos_ui.csv introuvable.")
        return

    df_ui = load_csv(photos_ui)
    if df_ui.empty:
        st.warning("photos_ui.csv est vide.")
        return

    if not photos_batch or not os.path.exists(photos_batch):
        st.info("Aucun photos_batch.csv à merger pour l’instant.")
        st.dataframe(df_ui.head(30))
        return

    df_b = load_csv(photos_batch)

    key = "photo_rel_native"
    if key not in df_ui.columns or key not in df_b.columns:
        st.warning(f"Clé '{key}' absente dans un des fichiers : merge impossible.")
        return

    df_m = df_ui.merge(df_b, on=key, how="left", suffixes=("", "_batch"))
    st.subheader("🔎 Aperçu merge UI + Batch (30 premières lignes)")
    st.dataframe(df_m.head(30))


# ---------------- UI ----------------
st.title("🧭 AnnotationPhotosGPT – Étape 2")

infos = lire_infos_projet()
_refresh_batch_sync_state_from_worker()
if not st.session_state.get("_batch_sync_started", False):
    # Synchronise la copie locale du batch sans retarder l'ouverture de l'UI.
    sync_id = str(time.time_ns())
    st.session_state["_batch_sync_id"] = sync_id
    st.session_state["batch_sync_in_progress"] = True
    st.session_state["batch_sync_done"] = False
    st.session_state["batch_sync_error"] = ""
    st.session_state["batch_sync_branch"] = ""
    st.session_state["batch_sync_copied"] = False
    st.session_state["_batch_sync_worker"] = sync_batch_from_nas(infos, sync_id=sync_id)
    st.session_state["_batch_sync_last_poll"] = 0.0
    st.session_state["_batch_sync_started"] = True
return_reason = _consume_ui_return_reason()
if return_reason:
    st.info(f"Sélection fichiers ouverte : {return_reason}")

status = _project_status(infos)
blockers = list(status["blockers"])

if blockers:
    reason = "etat projet incomplet: " + ", ".join(blockers)
    _set_ui_return_reason(reason)
    st.subheader("📁 Fichiers du projet")
    show_selection_interface()
    latest_infos = lire_infos_projet()
    latest_status = _project_status(latest_infos)
    latest_blockers = list(latest_status["blockers"])
    if not latest_blockers:
        st.session_state["selection_return_reason"] = "etat projet fichiers/audio complete"
        st.rerun()
    latest_reason = "etat projet incomplet: " + ", ".join(latest_blockers)
    st.divider()
    st.warning("Certains fichiers sont manquants ou invalides.")
    st.caption(f"Cause détectée : {latest_reason}")
    st.stop()

if not status["calibrage_ready"]:
    if status["horodatage_audio_state"] == "absent":
        reason = status["horodatage_audio_message"]
    elif status["horodatage_audio_state"] == "format_invalide":
        reason = status["horodatage_audio_message"]
    else:
        reason = "calibrage invalide ou absent"
    _set_ui_return_reason(reason)
    st.subheader("📁 Fichiers du projet")
    show_selection_interface()
    st.divider()
    st.subheader("🕓 Synchronisation Audio / Photos")
    st.caption(f"Cause détectée : {reason}")
    show_sync_interface()
else:
    if st.toggle("Modifier les fichiers du projet", key="show_project_files_editor"):
        st.subheader("📁 Fichiers du projet")
        show_selection_interface()
        st.divider()
    _refresh_batch_sync_state_from_worker()
    show_batch_status(infos)      # ✅ nouveau
    preview_merge(infos)          # ✅ optionnel mais très utile pour debug
    show_annotation_interface()
    if st.session_state.get("batch_sync_in_progress", False):
        worker = st.session_state.get("_batch_sync_worker")
        if worker is not None and worker.is_alive():
            now = time.time()
            last_poll = float(st.session_state.get("_batch_sync_last_poll") or 0.0)
            if (now - last_poll) >= 1.0:
                st.session_state["_batch_sync_last_poll"] = now
                time.sleep(0.25)
                st.rerun()
        else:
            _refresh_batch_sync_state_from_worker()
            if not st.session_state.get("batch_sync_in_progress", False):
                st.rerun()
