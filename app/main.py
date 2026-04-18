import sys
import os
import shutil
import threading
import logging
from pathlib import Path
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
st.set_page_config(layout="wide")  # <-- doit être AVANT tout autre st.*

from selection_fichiers_interface import show_selection_interface
from synchronisation_interface import show_sync_interface
from annotation_interface_gpt import show_annotation_interface
from utils import lire_infos_projet, purge_temp_audio
from datetime import datetime
import time
from contextlib import contextmanager


print("✅ PYTHONPATH temporaire ajouté :", sys.path[0])

log = logging.getLogger("batch_sync")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_handler)
log.setLevel(logging.INFO)
log.propagate = False


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


def _sync_batch_from_nas_impl(infos: dict) -> None:
    try:
        pcfixe = infos.get("pcfixe", {}) or {}
        if not isinstance(pcfixe, dict):
            return

        # `pcfixe.fichier_photos_batch` est la source canonique produite
        # par le batch NAS/PC fixe ; `fichier_photos_batch` est la copie
        # locale consommée par l'application laptop.
        nas_path = str(pcfixe.get("fichier_photos_batch", "") or "").strip()
        local_path = str(infos.get("fichier_photos_batch", "") or "").strip()
        if not nas_path or not local_path:
            return

        nas_ok, nas_mtime = _safe_stat(nas_path)
        if not nas_ok:
            return

        local_ok, local_mtime = _safe_stat(local_path)
        if local_ok and nas_mtime <= local_mtime:
            log.info("[BATCH_SYNC] Déjà à jour (copie locale du batch)")
            return

        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(nas_path, local_path)
        log.info("[BATCH_SYNC] Copie effectuée source canonique -> copie locale")
    except Exception as e:
        log.warning(f"[BATCH_SYNC] Erreur accès NAS (non bloquant): {e}")


def sync_batch_from_nas(infos: dict) -> None:
    worker = threading.Thread(
        target=_sync_batch_from_nas_impl,
        args=(dict(infos or {}),),
        daemon=True,
        name="batch-sync-from-nas",
    )
    worker.start()

def show_batch_status(infos: dict):
    p = str(infos.get("fichier_photos_batch", "") or "").strip()
    ok, mtime = _safe_stat(p)
    st.subheader("📦 État photos_batch.csv")
    st.write(p if p else "(non défini dans infos_projet.json)")
    if ok:
        st.success(f"✅ Présent — modifié le {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        st.warning("⚠️ Absent — le batch n’a peut-être pas encore produit le fichier, ou la copie n’a pas été faite.")


def _set_ui_return_reason(reason: str) -> None:
    if reason:
        st.session_state["selection_return_reason"] = reason


def _consume_ui_return_reason() -> str:
    return str(st.session_state.pop("selection_return_reason", "") or "").strip()


def _project_blockers(infos: dict) -> list[str]:
    blockers = []

    photos = str(infos.get("fichier_photos", "") or "").strip()
    if not photos or not os.path.exists(photos):
        blockers.append("fichier_photos manquant")

    transcription = str(infos.get("fichier_transcription", "") or "").strip()
    if not transcription or not os.path.exists(transcription):
        blockers.append("fichier_transcription manquant")

    audio_source = str(infos.get("fichier_audio_source", "") or "").strip()
    audio_compat = str(infos.get("fichier_audio", "") or infos.get("fichier_audio_compatible", "") or "").strip()
    compat_source = str(infos.get("audio_compat_source", "") or "").strip()

    if not audio_source or not os.path.exists(audio_source):
        blockers.append("fichier_audio_source manquant")
    elif not audio_compat or not os.path.exists(audio_compat):
        blockers.append("audio compatible manquant")
    elif compat_source and os.path.abspath(compat_source) != os.path.abspath(audio_source):
        blockers.append("audio compatible incohérent avec la source")

    return blockers

def load_csv(path: str, sep=";") -> pd.DataFrame:
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(path, sep=sep, encoding=enc)
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
if not st.session_state.get("_batch_sync_started", False):
    # Synchronise la copie locale du batch sans retarder l'ouverture de l'UI.
    sync_batch_from_nas(infos)
    st.session_state["_batch_sync_started"] = True
return_reason = _consume_ui_return_reason()
if return_reason:
    st.info(f"Retour vers sélection fichiers : {return_reason}")

blockers = _project_blockers(infos)

if blockers:
    reason = "état projet incomplet: " + ", ".join(blockers)
    _set_ui_return_reason(reason)
    st.subheader("📁 Fichiers du projet")
    show_selection_interface()
    st.divider()
    st.warning("Certains fichiers sont manquants ou invalides.")
    st.caption(f"Cause détectée : {reason}")
    st.stop()

if not infos.get("calibrage_valide", False):
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
    show_batch_status(infos)      # ✅ nouveau
    preview_merge(infos)          # ✅ optionnel mais très utile pour debug
    show_annotation_interface()
