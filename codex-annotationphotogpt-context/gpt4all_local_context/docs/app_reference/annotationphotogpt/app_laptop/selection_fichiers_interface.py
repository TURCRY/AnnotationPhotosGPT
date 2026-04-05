import os
import json
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st
import glob

from utils import lire_infos_projet, sauvegarder_infos_projet

from traitement_audio import (
    traiter_fichier_audio_selectionne,
    purge_audio_temp,
    start_audio_server_if_needed,
    stop_audio_server_if_any,
    AUDIO_COMPAT,
)

import re
from datetime import datetime

# ---------------------------------------------------------------------
# CONSTANTES
# ---------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPLOADS_DIR = os.path.join(BASE_DIR, "data", "uploads")
TEMP_DIR = os.path.join(BASE_DIR, "data", "temp")
AUDIO_EXT = {".wav", ".mp3"}
UI_DEFAULTS = {
    "photo_rel_native": "",
    "nom_fichier_image": "",

    "id_affaire": "",
    "id_captation": "",

    "chemin_photo_native": "",
    "chemin_photo_reduite": "",

    "horodatage_photo": "",
    "horodatage_secondes": "",
    "synchro_audio": "",
    "t_audio": "",
    "decalage_individuel": "",
    "decalage_moyen": "",

    "orientation_photo": "",   # ou "0" si vous préférez
    "retenue": "1",            # si vous souhaitez “retenue par défaut”
    "description_vlm_ui": "",
    "vlm_ui_status": "",
    "vlm_ui_ts": "",
    "ui_ts": "",

    "libelle_propose_ui": "",
    "libelle_ui_ts": "",
    "libelle_ui_status": "",

    "commentaire_propose_ui": "",
    "commentaire_ui_ts": "",
    "commentaire_ui_status": "",

    "annotation_validee": "0",

    "dictee_asr_text": "",
    "dictee_asr_status": "",
    "dictee_asr_ts": "",
    "dictee_audio_path_pcfixe": "",
    "dictee_asr_csv_path_pcfixe": "",
    "dictee_asr_photo_csv_path_pcfixe": "",
    "dictee_audio_sha256": "",
    "dictee_audio_size": "",
}



# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------
def _is_uploads_path(p: str) -> bool:
    if not p:
        return False
    return os.path.abspath(p).startswith(os.path.abspath(UPLOADS_DIR) + os.sep)


def _is_temp_audio_path(p: str) -> bool:
    if not p:
        return False
    p_abs = os.path.abspath(p)
    if p_abs.startswith(os.path.abspath(TEMP_DIR) + os.sep):
        return True
    if os.path.basename(p_abs).lower() == "audio_compatible.wav":
        return True
    return False


def _real_or_empty(p: str) -> str:
    if not p:
        return ""
    p_abs = os.path.abspath(p)
    if _is_uploads_path(p_abs):
        return ""
    if p_abs.startswith(os.path.abspath(TEMP_DIR) + os.sep):
        return ""
    return p_abs

def _load_csv_flexible(path: str) -> pd.DataFrame:
    """Lit un CSV en essayant plusieurs encodages usuels (UTF-8, cp1252...)."""
    encodings = ["utf-8-sig", "cp1252", "latin1"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(path, sep=";", encoding=enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
    # si rien ne marche, on propage la dernière erreur
    if last_err is not None:
        raise last_err
    raise RuntimeError(f"Impossible de lire le CSV : {path}")

def _detect_audio_candidates_and_dirs():
    """Cherche des .wav/.mp3 autour du CSV de transcription RÉEL."""
    t = st.session_state.get("fichiers_temp", {}) or {}
    csv_real = t.get("fichier_transcription_reel", "")
    if not csv_real:
        return [], []

    csv_real = os.path.abspath(csv_real)
    if not os.path.isfile(csv_real):
        return [], []

    dirs_to_scan = set()
    d = os.path.dirname(csv_real)
    if os.path.isdir(d):
        dirs_to_scan.add(d)
    parent = os.path.dirname(d)
    if parent and os.path.isdir(parent):
        dirs_to_scan.add(parent)
        try:
            for name in os.listdir(parent):
                sib = os.path.join(parent, name)
                if os.path.isdir(sib):
                    dirs_to_scan.add(sib)
        except Exception:
            pass

    candidats, vus = [], set()
    for directory in sorted(dirs_to_scan):
        try:
            for name in os.listdir(directory):
                full = os.path.join(directory, name)
                if os.path.isfile(full):
                    ext = os.path.splitext(name)[1].lower()
                    if ext in AUDIO_EXT and not _is_temp_audio_path(full):
                        full_norm = os.path.abspath(full)
                        if full_norm not in vus:
                            vus.add(full_norm)
                            candidats.append(full_norm)
        except Exception:
            continue
    return sorted(candidats), sorted(dirs_to_scan)

import re
from datetime import datetime

def normalize_id_affaire(s: str) -> str:
    return (s or "").strip().upper()

def validate_id_affaire(s: str) -> tuple[bool, str, str]:
    s = normalize_id_affaire(s)
    if not s:
        return False, s, "id_affaire est vide."
    if not re.fullmatch(r"\d{4}-J\d{1,3}", s):
        return False, s, "Format attendu : YYYY-JNN (ex: 2025-J37)."
    return True, s, ""

def normalize_id_captation(s: str) -> str:
    return (s or "").strip()

def validate_id_captation(s: str) -> tuple[bool, str, str]:
    s = normalize_id_captation(s)
    if not s:
        return False, s, "id_captation est vide."
    m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_-]{2,40})-(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return False, s, "Format attendu : <slug>-YYYY-MM-DD (ex: accedit-2025-09-02)."
    # Vérification date réelle
    try:
        datetime.strptime(f"{m.group(2)}-{m.group(3)}-{m.group(4)}", "%Y-%m-%d")
    except ValueError:
        return False, s, "Date invalide dans id_captation (YYYY-MM-DD)."
    return True, s, ""

def ensure_photo_rel_native_pcfixe(df: pd.DataFrame, id_captation: str) -> pd.DataFrame:
    if "photo_rel_native" not in df.columns:
        df["photo_rel_native"] = ""

    id_captation = (id_captation or "").strip()
    if not id_captation:
        raise ValueError("id_captation manquant : impossible de fabriquer photo_rel_native.")

    for i, row in df.iterrows():
        cur = str(row.get("photo_rel_native", "") or "").strip()
        if cur:
            df.at[i, "photo_rel_native"] = cur.replace("\\", "/")
            continue

        name = str(row.get("nom_fichier_image", "") or "").strip()
        if not name:
            continue

        df.at[i, "photo_rel_native"] = f"AE_Expert_captations/{id_captation}/photos/JPG/{name}"

    return df

def ensure_ui_schema(df: pd.DataFrame, id_affaire: str, id_captation: str) -> pd.DataFrame:
    # 1) créer colonnes manquantes
    for col, default in UI_DEFAULTS.items():
        if col not in df.columns:
            df[col] = default

    # 2) ne pas écraser : remplir seulement les vides (NaN / "")
    for col, default in UI_DEFAULTS.items():
        s = df[col]
        df[col] = s.where(~(s.isna() | (s.astype(str).str.strip() == "")), default)

    # 3) imposer id_affaire / id_captation si absents ou vides
    df["id_affaire"] = df["id_affaire"].where(df["id_affaire"].astype(str).str.strip() != "", id_affaire)
    df["id_captation"] = df["id_captation"].where(df["id_captation"].astype(str).str.strip() != "", id_captation)

    return df
# ---------------------------------------------------------------------
# INIT SESSION
# ---------------------------------------------------------------------
DEFAULTS = {
    "fichiers_temp": {
        "fichier_photos_temp": "",
        "fichier_photos_reel": "",
        "fichier_transcription_temp": "",
        "fichier_transcription_reel": "",
        "fichier_audio_source": "",
        "fichier_audio_compatible": "",
        "fichier_audio": "",
        "fichier_contexte_general_temp": "",
        "fichier_contexte_general_reel": "",
        "fichier_contexte_general": "",
    },
    "audio_server_running": False,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ---------------------------------------------------------------------
# UI PRINCIPALE
# ---------------------------------------------------------------------

def show_selection_interface():
    try:
        infos = lire_infos_projet()
    except Exception:
        infos = {}

    temp = st.session_state.get("fichiers_temp", {}) or {}

    st.title("📁 Sélection des fichiers du projet")

    st.subheader("Fichiers actuellement utilisés (infos_projet.json)")
    st.code(
        json.dumps(
            {
                "Transcription": infos.get("fichier_transcription", ""),
                "Photos": infos.get("fichier_photos", ""),
                "Audio_source": infos.get(
                    "fichier_audio_source", infos.get("fichier_audio", "")
                ),
                "Audio_compatible": infos.get("fichier_audio", ""),
            },
            indent=2,
            ensure_ascii=False,
        ),
        language="json",
    )

    # --- synchronisation initiale ---
    if not temp.get("fichier_photos_reel") and infos.get("fichier_photos"):
        temp["fichier_photos_reel"] = os.path.abspath(infos["fichier_photos"])
        temp["fichier_photos"] = temp["fichier_photos_reel"]

    if not temp.get("fichier_transcription_reel") and infos.get("fichier_transcription"):
        temp["fichier_transcription_reel"] = os.path.abspath(infos["fichier_transcription"])
        temp["fichier_transcription"] = temp["fichier_transcription_reel"]

    if not temp.get("fichier_audio_source"):
        if infos.get("fichier_audio_source"):
            temp["fichier_audio_source"] = os.path.abspath(infos["fichier_audio_source"])
        elif infos.get("fichier_audio"):
            temp["fichier_audio_source"] = os.path.abspath(infos["fichier_audio"])

    if not temp.get("fichier_audio"):
        if infos.get("fichier_audio"):
            temp["fichier_audio"] = os.path.abspath(infos["fichier_audio"])
        elif temp.get("fichier_audio_source"):
            temp["fichier_audio"] = temp["fichier_audio_source"]

    if not temp.get("fichier_contexte_general_reel") and infos.get("fichier_contexte_general"):
        temp["fichier_contexte_general_reel"] = os.path.abspath(infos["fichier_contexte_general"])
        temp["fichier_contexte_general"] = temp["fichier_contexte_general_reel"]

    if not temp.get("fichier_audio_compatible") and infos.get("fichier_audio"):
        temp["fichier_audio_compatible"] = os.path.abspath(infos["fichier_audio"])

    st.session_state["fichiers_temp"] = temp

    st.divider()
    # ======================================================================
    # PHOTOS
    # ======================================================================
    st.markdown("### 📷 Fichier de photos")

    # 1) Chemin RÉEL par dossier + choix de fichier
    st.markdown("#### Chemin RÉEL du dossier des photos")

    photos_dir_input = st.text_input(
        "Chemin du DOSSIER où se trouvent les photos (.xlsx ou .csv) :",
        value=os.path.dirname(temp.get("fichier_photos_reel", "")) if temp.get("fichier_photos_reel") else "",
        key="photos_dir_input",
        placeholder=r"C:\Users\...\Photos\J46 zanato 06 11 2025",
    )

    photos_dir = photos_dir_input.strip().strip('"')
    if photos_dir:
        if os.path.isdir(photos_dir):
            candidates = [
                f for f in os.listdir(photos_dir)
                if f.lower().endswith((".xlsx", ".csv"))
            ]
            if candidates:
                photos_file_selected = st.selectbox(
                    "Choisir le fichier de photos dans ce dossier :",
                    candidates,
                    key="photos_file_select",
                )
                if photos_file_selected:
                    real_path = os.path.abspath(os.path.join(photos_dir, photos_file_selected))
                    temp["fichier_photos_reel"] = real_path
                    temp["fichier_photos"] = real_path
                    st.success(f"✅ Fichier photos (chemin RÉEL) : {real_path}")
            else:
                st.warning("Aucun fichier .xlsx ou .csv trouvé dans ce dossier.")
        else:
            st.error(f"⛔ Ce chemin de dossier n'existe pas : `{photos_dir}`")

    st.markdown(
        f"**Chemin RÉEL photos courant :** "
        f"`{temp.get('fichier_photos_reel', '') or '—'}`"
    )

    # 2) Upload -> copie temporaire (optionnelle)
    uploaded_photos = st.file_uploader(
        "📂 (Optionnel) Sélectionner le fichier des photos (.xlsx ou .csv) [copie temporaire]",
        type=["xlsx", "csv"],
        key="upload_photos",
    )
    if uploaded_photos is not None:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        raw_path = os.path.join(UPLOADS_DIR, uploaded_photos.name)
        with open(raw_path, "wb") as f:
            f.write(uploaded_photos.getbuffer())

        ext = Path(raw_path).suffix.lower()
        fichier_final = raw_path

        if ext == ".csv":
            try:
                df = _load_csv_flexible(raw_path)
                xlsx_path = str(Path(raw_path).with_suffix(".xlsx"))
                df.to_excel(xlsx_path, index=False, engine="openpyxl")
                fichier_final = xlsx_path
                st.success(f"✅ CSV converti en Excel (copie temp) : {xlsx_path}")
            except Exception as e:
                st.error(f"Erreur conversion CSV→XLSX : {e}")

        temp["fichier_photos_temp"] = fichier_final
        st.info(f"📂 Copie temporaire photos : {fichier_final}")

    # Vérification colonnes sur le fichier utilisé (réel si dispo, sinon temp)
    photos_to_check = temp.get("fichier_photos_reel") or temp.get("fichier_photos_temp", "")
    if photos_to_check:
        try:
            p = Path(photos_to_check)
            if p.suffix.lower() == ".xlsx":
                df_test = pd.read_excel(p, engine="openpyxl")
            else:
                last_err = None
                df_test = None
                for enc in ("utf-8-sig", "cp1252", "latin-1"):
                    try:
                        df_test = pd.read_csv(p, sep=";", encoding=enc)
                        break
                    except UnicodeDecodeError as e:
                        last_err = e
                        df_test = None
                if df_test is None:
                    raise last_err or Exception("Impossible de lire le fichier photos")

            cols = {str(c).strip().lstrip("\ufeff").lower() for c in df_test.columns}
            expected = {
                "nom_fichier_image",
                "horodatage_photo",
                "horodatage_secondes",
                "synchro_audio",
                "t_audio",
                "decalage_individuel",
                "decalage_moyen",
            }
            missing = sorted(expected - cols)
            if missing:
                st.warning(
                    "⚠️ Fichier photos incomplet, colonnes manquantes : "
                    + ", ".join(missing)
                )
            else:
                st.success("✅ Le fichier photo contient toutes les colonnes nécessaires.")
        except Exception as e:
            st.error(f"Erreur lecture fichier photos : {e}")
    else:
        st.info("ℹ️ Aucun fichier photos sélectionné (temporaire ou réel).")

    st.divider()

    # ======================================================================
    # TRANSCRIPTION
    # ======================================================================
    st.markdown("### 📝 Fichier de transcription")

    st.markdown("#### Chemin RÉEL du dossier de transcription")

    trans_dir_input = st.text_input(
        "Chemin du DOSSIER où se trouve le CSV de transcription :",
        value=os.path.dirname(temp.get("fichier_transcription_reel", "")) if temp.get("fichier_transcription_reel") else "",
        key="trans_dir_input",
        placeholder=r"C:\Users\...\Audio",
    )

    trans_dir = trans_dir_input.strip().strip('"')
    if trans_dir:
        if os.path.isdir(trans_dir):
            candidates = [
                f for f in os.listdir(trans_dir)
                if f.lower().endswith(".csv")
            ]
            if candidates:
                trans_file_selected = st.selectbox(
                    "Choisir le CSV de transcription dans ce dossier :",
                    candidates,
                    key="trans_file_select",
                )
                if trans_file_selected:
                    real_path = os.path.abspath(os.path.join(trans_dir, trans_file_selected))
                    temp["fichier_transcription_reel"] = real_path
                    temp["fichier_transcription"] = real_path
                    st.success(f"✅ Fichier transcription (chemin RÉEL) : {real_path}")
            else:
                st.warning("Aucun fichier .csv trouvé dans ce dossier.")
        else:
            st.error(f"⛔ Ce chemin de dossier n'existe pas : `{trans_dir}`")

    st.markdown(
        f"**Chemin RÉEL transcription courant :** "
        f"`{temp.get('fichier_transcription_reel', '') or '—'}`"
    )

    # Upload temporaire (optionnel)
    uploaded_trans = st.file_uploader(
        "📂 (Optionnel) Sélectionner le fichier CSV de transcription [copie temporaire]",
        type=["csv"],
        key="upload_transcription",
    )
    if uploaded_trans is not None:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        path = os.path.join(UPLOADS_DIR, uploaded_trans.name)
        with open(path, "wb") as f:
            f.write(uploaded_trans.getbuffer())
        temp["fichier_transcription_temp"] = path
        st.info(f"📂 Copie temporaire transcription : {path}")

    st.divider()

    # =====================================================================
    # AUDIO
    # =====================================================================
    st.markdown("### 🎧 Sélection du fichier audio principal")

    candidates, scanned_dirs = _detect_audio_candidates_and_dirs()
    if not temp.get("fichier_transcription_reel"):
        st.warning("Renseignez d’abord le **chemin RÉEL** du CSV de transcription.")
        selected_audio = ""
    elif candidates:
        selected_audio = st.selectbox(
            "Fichiers audio détectés automatiquement :",
            [""] + candidates,
            key="audio_detected_select",
            format_func=lambda x: x if x else "— aucun (laisser vide) —",
        )
    else:
        st.info("Aucun .wav/.mp3 détecté automatiquement.")
        with st.expander("Dossiers scannés"):
            for d in scanned_dirs:
                st.write(d)
        selected_audio = ""

    st.markdown("#### Ou bien sélectionner l’audio par dossier")

    audio_dir_input = st.text_input(
        "Chemin du DOSSIER où se trouve le fichier audio (.wav ou .mp3) :",
        value=os.path.dirname(temp.get("fichier_audio_source", "")) if temp.get("fichier_audio_source") else "",
        key="audio_dir_input",
        placeholder=r"C:\Users\...\Audio",
    )

    audio_dir = audio_dir_input.strip().strip('"')
    audio_file_from_dir = None

    if audio_dir:
        if os.path.isdir(audio_dir):
            audio_cands = [
                f for f in os.listdir(audio_dir)
                if f.lower().endswith((".wav", ".mp3"))
            ]
            if audio_cands:
                audio_file_from_dir = st.selectbox(
                    "Choisir un fichier audio dans ce dossier :",
                    audio_cands,
                    key="audio_file_from_dir_select",
                )
            else:
                st.warning("Aucun .wav/.mp3 trouvé dans ce dossier.")
        else:
            st.error(f"⛔ Ce chemin de dossier n'existe pas : `{audio_dir}`")

    manual_audio = st.text_input(
        "Ou saisir/coller un chemin complet du fichier audio (.wav ou .mp3) :",
        value="",
        key="audio_manual_input",
    )

    if st.button("✅ Valider le fichier audio"):
        chosen = (selected_audio or "").strip()

        if not chosen and audio_file_from_dir and audio_dir:
            chosen = os.path.join(audio_dir, audio_file_from_dir)

        if not chosen and manual_audio.strip():
            chosen = manual_audio.strip()

        if not chosen:
            st.warning("Merci de sélectionner un fichier audio ou de saisir un chemin complet.")
        else:
            abs_audio = os.path.abspath(chosen)

            # --- Lecture de l'ancien fichier source (si existant)
            old_source = temp.get("fichier_audio_source", "")

            temp["fichier_audio_source"] = abs_audio
            temp["fichier_audio"] = abs_audio

            # --- Si la source change → l'audio compatible doit être régénéré
            if old_source and old_source != abs_audio:
                temp["fichier_audio_compatible"] = ""
                st.warning("🔁 Nouveau fichier audio sélectionné : l'audio compatible devra être régénéré.")
            else:
                # On garde le fichier compatible existant (utile pour reprise d'annotation)
                st.info("ℹ️ Fichier audio identique : l'audio compatible sera réutilisé si présent.")

            st.success(f"Fichier audio source enregistré : {abs_audio}")

    # =====================================================================
    # Contexte général (JSON)
    # =====================================================================
    st.divider()
    st.markdown("### 🧩 Contexte général (contexte_general.json)")

    ctx_dir_input = st.text_input(
        "Chemin du DOSSIER où se trouve le fichier contexte_general.json :",
        value=os.path.dirname(temp.get("fichier_contexte_general_reel", "")) if temp.get("fichier_contexte_general_reel") else "",
        key="ctx_dir_input",
        placeholder=r"C:\Users\...\Dossier_affaire",
    )

    ctx_dir = ctx_dir_input.strip().strip('"')
    if ctx_dir:
        if os.path.isdir(ctx_dir):
            candidates = [f for f in os.listdir(ctx_dir) if f.lower().endswith(".json")]
            if candidates:
                ctx_file_selected = st.selectbox(
                    "Choisir le fichier JSON de contexte dans ce dossier :",
                    candidates,
                    key="ctx_file_select",
                )
                if ctx_file_selected:
                    real_path = os.path.abspath(os.path.join(ctx_dir, ctx_file_selected))
                    temp["fichier_contexte_general_reel"] = real_path
                    temp["fichier_contexte_general"] = real_path
                    st.success(f"✅ Contexte général (chemin RÉEL) : {real_path}")
            else:
                st.warning("Aucun fichier .json trouvé dans ce dossier.")
        else:
            st.error(f"⛔ Ce chemin de dossier n'existe pas : `{ctx_dir}`")

    st.markdown(
        f"**Chemin RÉEL contexte général courant :** "
        f"`{temp.get('fichier_contexte_general_reel', '') or '—'}`"
    )

    uploaded_ctx = st.file_uploader(
        "📂 (Optionnel) Sélectionner le contexte_general.json [copie temporaire]",
        type=["json"],
        key="upload_contexte_general",
    )
    if uploaded_ctx is not None:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        path = os.path.join(UPLOADS_DIR, uploaded_ctx.name)
        with open(path, "wb") as f:
            f.write(uploaded_ctx.getbuffer())
        temp["fichier_contexte_general_temp"] = path
        st.info(f"📂 Copie temporaire contexte général : {path}")

    # -----------------------------------------------------------------
    # Identifiants affaire / captation (utilisés pour les chemins PC fixe + batch)
    # -----------------------------------------------------------------
    st.subheader("🆔 Identifiants (affaire / captation)")

    id_affaire_input = st.text_input(
        "id_affaire (ex: 2025-J37)",
        value=str(infos.get("id_affaire", "") or ""),
        key="id_affaire_input",
    )

    id_captation_input = st.text_input(
        "id_captation (ex: accedit-2025-09-02)",
        value=str(infos.get("id_captation", "") or ""),
        key="id_captation_input",
    )

    # -----------------------------------------------------------------
    # Fichier batch (photos_batch.csv) : affichage + auto-proposition
    # -----------------------------------------------------------------
    photos_batch_current = str(infos.get("fichier_photos_batch", "") or "").strip()
    if not photos_batch_current:
        # propose par défaut dans le même dossier que fichier_photos réel (quand connu)
        photos_real = temp.get("fichier_photos_reel") or infos.get("fichier_photos", "")
        if photos_real:
            photos_batch_current = str(Path(os.path.abspath(photos_real)).parent / "photos_batch.csv")

    exists_batch = bool(photos_batch_current) and os.path.exists(photos_batch_current)

    st.caption("📦 Fichier batch (photos_batch.csv)")
    st.code(photos_batch_current if photos_batch_current else "(non défini)")
    if exists_batch:
        st.success("✅ photos_batch.csv présent")
    else:
        st.warning("⚠️ photos_batch.csv absent (normal si le batch n’a pas encore tourné)")

    # stocke en session pour réutilisation au moment de l’enregistrement
    st.session_state["photos_batch_path_candidate"] = photos_batch_current


    # -----------------------------------------------------------------
    # Sauvegarde du state temp pour la suite et pour _detect_audio_candidates
    # -----------------------------------------------------------------

    st.session_state["fichiers_temp"] = temp

    # =====================================================================
    # APERÇU TEMPORAIRE
    # =====================================================================
    st.markdown("### 🔍 Aperçu des fichiers sélectionnés (temporaire)")
    preview = {
        "fichier_photos_reel": temp.get("fichier_photos_reel", ""),
        "fichier_transcription_reel": temp.get("fichier_transcription_reel", ""),
        "fichier_audio_source": temp.get("fichier_audio_source", ""),
        "fichier_audio_compatible": temp.get("fichier_audio_compatible", ""),
        "fichier_photos_temp": temp.get("fichier_photos_temp", ""),
        "fichier_transcription_temp": temp.get("fichier_transcription_temp", ""),
        "fichier_contexte_general_reel": temp.get("fichier_contexte_general_reel", ""),
        "fichier_contexte_general_temp": temp.get("fichier_contexte_general_temp", ""),
    }
    st.code(json.dumps(preview, indent=2, ensure_ascii=False), language="json")

    # =====================================================================
    # ENREGISTREMENT DANS infos_projet.json
    # =====================================================================
    if st.button("💾 Enregistrer ces fichiers"):
        t = st.session_state.get("fichiers_temp", {})

        photos_real    = _real_or_empty(t.get("fichier_photos_reel", ""))
        trans_real     = _real_or_empty(t.get("fichier_transcription_reel", ""))
        audio_src_real = _real_or_empty(t.get("fichier_audio_source", ""))
        ctx_selected = _real_or_empty(t.get("fichier_contexte_general_reel", ""))


        ok_a, id_affaire, err_a = validate_id_affaire(id_affaire_input)
        ok_c, id_captation, err_c = validate_id_captation(id_captation_input)

        if not ok_a or not ok_c:
            if err_a: st.error(f"❌ id_affaire : {err_a}")
            if err_c: st.error(f"❌ id_captation : {err_c}")
            st.stop()

        infos["id_affaire"] = id_affaire
        infos["id_captation"] = id_captation

        # Contexte général (si sélectionné)
        if ctx_selected:
            infos["fichier_contexte_general"] = ctx_selected

        # Chemins
        if photos_real:
            infos["fichier_photos"] = photos_real
        if trans_real:
            infos["fichier_transcription"] = trans_real
        if audio_src_real:
            infos["fichier_audio_source"] = audio_src_real

        # ⚠️ IMPORTANT : mettre à jour + sauver le CSV photos (photo_rel_native)
        if photos_real:
            df_photos = _load_csv_flexible(photos_real, sep=";")

            # 1) clé pivot
            df_photos = ensure_photo_rel_native_pcfixe(df_photos, id_captation)

            # 2) schéma UI complet (sans écraser les valeurs existantes)
            df_photos = ensure_ui_schema(df_photos, id_affaire, id_captation)

            # 3) unicité photo_rel_native
            key = df_photos["photo_rel_native"].astype(str).str.strip()
            dups = key.duplicated(keep=False)
            if dups.any():
                st.error("❌ Doublons dans photo_rel_native : clé pivot invalide.")
                st.dataframe(df_photos.loc[dups, ["nom_fichier_image", "photo_rel_native"]].head(50))
                st.stop()

            # 4) écriture atomique sur le fichier réel
            tmp = photos_real + ".tmp"
            df_photos.to_csv(tmp, sep=";", encoding="utf-8-sig", index=False)
            os.replace(tmp, photos_real)

        # Chemin batch (si proposé)
        batch_path = str(st.session_state.get("photos_batch_path_candidate", "") or "").strip()
        if batch_path:
            infos["fichier_photos_batch"] = os.path.abspath(batch_path)

#---------------------------------------------------------------------------
        # 2) Contrôle : un audio doit être sélectionné
        if not audio_src_real:
            infos["fichier_audio"] = ""
            infos["fichier_audio_compatible"] = ""
            infos["audio_compat_source"] = ""
            infos["calibrage_valide"] = False
            sauvegarder_infos_projet(infos)
            st.error("❌ Aucun fichier audio sélectionné. Merci d’en choisir un.")
            st.stop()


        # 3) IMPORTANT : empêcher la réutilisation d'un ancien audio_compatible.wav
        stop_audio_server_if_any()   # évite un serveur qui garde l'ancien fichier
        purge_audio_temp()           # supprime data/temp/audio_compatible.wav

        audio_compat_abs = ""
        ok = traiter_fichier_audio_selectionne(audio_src_real)
        if ok and os.path.exists(AUDIO_COMPAT):
            audio_compat_abs = os.path.abspath(AUDIO_COMPAT)

        if not audio_compat_abs:
            infos["fichier_audio"] = ""
            infos["fichier_audio_compatible"] = ""
            infos["audio_compat_source"] = ""
            infos["calibrage_valide"] = False
            sauvegarder_infos_projet(infos)
            st.error("❌ Impossible de générer un audio compatible à partir du fichier sélectionné.")
            st.stop()

        # (re)démarrage du serveur audio sur le bon WAV
        start_audio_server_if_needed(audio_compat_abs)


        # 4) Si on arrive ici, on a un audio compatible valide
        infos["fichier_audio"] = audio_compat_abs                  # toujours le compatible
        infos["fichier_audio_compatible"] = audio_compat_abs       # redondant mais explicite
        infos["audio_compat_source"] = audio_src_real              # trace du WAV source
        infos["horodatage_audio"] = st.session_state.get("horodatage_audio", "")
        infos["calibrage_valide"] = False                          # la synchro devra être refaite

        sauvegarder_infos_projet(infos)
        st.success("✅ Fichiers enregistrés dans infos_projet.json.")
        st.rerun()

    # =====================================================================
    # LANCEMENT SERVEUR AUDIO SI COMPATIBLE DISPO
    # =====================================================================
    if os.path.exists(AUDIO_COMPAT) and not st.session_state.get("audio_server_running", False):
        try:
            server_path = os.path.join(os.path.dirname(__file__), "audio_server.py")
            subprocess.Popen(
                ["python", server_path],
                env={**os.environ, "AUDIO_FILE_PATH": AUDIO_COMPAT},
            )
            st.session_state["audio_server_running"] = True
            st.info("🔊 Serveur audio lancé avec le fichier compatible.")
        except Exception as e:
            st.warning(f"⚠️ Erreur au lancement du serveur audio : {e}")
