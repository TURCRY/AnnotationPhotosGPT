import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
from utils import (
    lire_infos_projet, sauvegarder_infos_projet,
    convertir_hms_en_secondes, convertir_secondes_en_hms,
    get_audio_duration, get_photo_datetime

)

from streamlit_wavesurfer import wavesurfer
import requests
#----------------------------------------------------------------------------
from pathlib import Path
from pandas import Timestamp
import numpy as np
import re


# ⬆️ près des imports

from pathlib import Path
import pandas as pd
import glob  

def _load_photos(path):
    p = Path(path)
    if p.suffix.lower() == ".xlsx":
        df = pd.read_excel(p, engine="openpyxl")
    else:
        # 1️⃣ essayer d’abord UTF-8 avec BOM (cohérent avec gen_tout_depuis_JPG.py)
        try:
            df = pd.read_csv(p, sep=";", encoding="utf-8-sig")
        except UnicodeDecodeError:
            # 2️⃣ repli possible sur latin-1 au cas où vous auriez d’anciens CSV
            df = pd.read_csv(p, sep=";", encoding="latin-1")

    # Nettoyage des noms de colonnes (BOM « normale » et BOM mal décodée)
    def _clean_col(col):
        s = str(col)
        s = s.replace("\ufeff", "")      # vrai caractère BOM
        s = s.replace("ï»¿", "")         # séquence due à mauvaise lecture UTF-8 en latin-1
        return s.strip()

    df.columns = [_clean_col(c) for c in df.columns]
    return df

def _save_photos(df, path):
    p = Path(path)
    if p.suffix.lower() == ".xlsx":
        df.to_excel(p, index=False, engine="openpyxl")
    else:
        df.to_csv(p, sep=";", index=False, encoding="utf-8-sig")


def ss_default(key, value):
    if key not in st.session_state:
        st.session_state[key] = value

def _to_dt(s, default_date=None):
    # accepte datetime Excel, pandas Timestamp ou string
    if isinstance(s, (Timestamp, datetime)):
        return pd.to_datetime(s).to_pydatetime()
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None

    s = str(s).strip().replace(',', '.')  # décimales virgule -> point

    fmts = (
        "%d/%m/%Y %H:%M:%S.%f",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    # ✅ Support HH:MM:SS(.ms) (sans date) -> ancré sur default_date
    #    ex: "12:03:04" ou "12:03:04.250"
    if default_date is not None:
        try:
            parts = s.split(":")
            if len(parts) == 3:
                h = int(parts[0]); m = int(parts[1]); sec = float(parts[2])
                micro = int((sec - int(sec)) * 1_000_000)
                return datetime(
                    default_date.year, default_date.month, default_date.day,
                    h, m, int(sec), micro
                )
        except Exception:
            pass

    return None

def _to_secs_since_audio0(s):
    dt = _to_dt(s, default_date=heure_creation_audio)
    return (dt - heure_creation_audio).total_seconds() if dt else pd.NA


def _strip_prefixes(text: str, prefixes=("libellé", "libelle", "label", "titre", "title")) -> str:
    if not isinstance(text, str):
        return text
    s = _strip_wrapping_quotes(text).strip()
    pat = r'^\s*(?:' + '|'.join(prefixes) + r')\s*[:：-]\s*'
    return re.sub(pat, '', s, flags=re.IGNORECASE).strip()

def _normalize_text(text: str, field: str|None=None) -> str:
    s = _strip_wrapping_quotes(text or "").strip()
    if field == "libelle":
        s = _strip_prefixes(s, ("libellé", "libelle", "label", "titre", "title"))
    elif field == "commentaire":
        s = _strip_prefixes(s, ("commentaire", "comment", "note"))
    return s

def _slice_text_dir(df, t0, before, after, prefer="both"):
    # 1) fenêtre primaire
    m = (df["temps"] >= t0 - before) & (df["temps"] <= t0 + after)
    txt = df.loc[m, "texte"].str.cat(sep=" ").strip()
    if txt:
        return txt
    # 2) fallback directionnel pour différencier les champs
    if prefer == "before":
        prev = df.loc[df["temps"] < t0].tail(2)
        return prev["texte"].str.cat(sep=" ").strip()
    if prefer == "after":
        nxt = df.loc[df["temps"] >= t0].head(2)
        return nxt["texte"].str.cat(sep=" ").strip()
    # 3) repli neutre
    prev_row = df.loc[df["temps"] <= t0].tail(1)
    next_row = df.loc[df["temps"] >= t0].head(1)
    if not prev_row.empty and not next_row.empty:
        prev_t = float(prev_row["temps"].iloc[0]); next_t = float(next_row["temps"].iloc[0])
        return prev_row["texte"].iloc[0] if (t0 - prev_t) <= (next_t - t0) else next_row["texte"].iloc[0]
    if not prev_row.empty: return prev_row["texte"].iloc[0]
    if not next_row.empty: return next_row["texte"].iloc[0]
    return ""

def _reset_annotation_files():
    """
    Supprime les fichiers d’annotation (_GTP_*.csv / _GTP_*.xlsx)
    et progression_annotation.json pour ce projet.
    """
    fichier_photos = infos.get("fichier_photos", "")
    if fichier_photos:
        base_dir  = os.path.dirname(os.path.abspath(fichier_photos))
        base_name = os.path.splitext(os.path.basename(fichier_photos))[0]

        # CSV + XLSX de ce projet
        for ext in (".csv", ".xlsx"):
            pattern = os.path.join(base_dir, f"{base_name}_GTP_*{ext}")
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                except OSError:
                    pass

    # progression_annotation.json (s’il existe)
    prog_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "data", "progression_annotation.json")
    )
    if os.path.exists(prog_path):
        try:
            os.remove(prog_path)
        except OSError:
            pass



def show_sync_interface():
    infos = lire_infos_projet()
    st.session_state.setdefault("points_sync", [])
    st.session_state.setdefault("indices_sync", [])
    fichier_photos = infos.get("fichier_photos", "")
    base_dir  = os.path.dirname(os.path.abspath(fichier_photos)) if fichier_photos else ""
    base_name = os.path.splitext(os.path.basename(fichier_photos))[0] if fichier_photos else ""


    # --- Horodatage t=0 audio ---
    try:
        heure_creation_audio = datetime.strptime(
            infos["horodatage_audio"], "%Y-%m-%d %H:%M:%S"
        )
    except Exception as e:
        st.error(f"⛔ Erreur horodatage_audio dans infos_projet.json : {e}")
        return

    # --- Paramètres de départ choisis dans infos_projet.json ---
    photo_depart = int(infos.get("photo_depart", 1))
    photo_start_index = max(0, photo_depart - 1)

    audio_depart_str = str(infos.get("audio_depart", "00:00:00") or "00:00:00")
    try:
        audio_depart_sec = convertir_hms_en_secondes(audio_depart_str)
    except Exception:
        audio_depart_sec = 0.0

    # --- Valeurs par défaut dans la session ---
    if "photo_index" not in st.session_state:
        st.session_state.photo_index = photo_start_index
    if "lecture_audio_position" not in st.session_state:
        st.session_state.lecture_audio_position = audio_depart_sec


    # Chemin local & URL de l'audio compatible servi par Flask
    audio_local = os.path.join("data", "temp", "audio_compatible.wav")
    audio_url   = "http://127.0.0.1:5000/audio/audio_compatible.wav"
    # Paramètres de retour arrière (infos_projet.json)
    retour_arriere = float(infos.get("retour_arriere", 10.0))

    if not os.path.exists(audio_local):
        st.error("Audio compatible introuvable : data/temp/audio_compatible.wav. Passe d'abord par la sélection/conversion.")
        return


    audio_path          = str(infos.get("fichier_audio", "") or "").strip()
    audio_src_path      = str(infos.get("fichier_audio_source", "") or "").strip()
    audio_compat_source = str(infos.get("audio_compat_source", "") or "").strip()

    # --- 1) Audio compatible présent ? ---
    if not audio_path or not os.path.exists(audio_path):
        st.error("❌ Aucun fichier audio compatible valide. "
                 "Veuillez revenir à l’étape 1 pour le (re)générer.")
        st.stop()

    # --- 2) Cohérence source / compatible ---
    if audio_src_path and audio_compat_source and \
       os.path.abspath(audio_src_path) != os.path.abspath(audio_compat_source):
        st.error("❌ Le fichier audio compatible ne correspond plus au fichier audio source. "
                 "Veuillez repasser par l’étape 1 (sélection des fichiers).")
        st.stop()


    # Durée (utile si affichage des bornes)

    # Durée (utile si affichage des bornes)
    duree_audio = get_audio_duration(audio_local)

    # Conversion audio_depart "HH:MM:SS" → secondes
    try:
        audio_depart_sec = convertir_hms_en_secondes(audio_depart_str)
    except Exception:
        audio_depart_sec = 0.0
        st.warning(f"⚠️ audio_depart invalide dans infos_projet.json : {audio_depart_str}")

    # curseurs globaux utilisés pendant la synchro
    ss_default("cursor_audio", audio_depart_sec)   # position de lecture courante (en s)
    ss_default("photo_index", photo_start_index)   # index photo de départ

    # anciens init (lecture_audio_position, lecture_active, etc.)
    if "lecture_audio_position" not in st.session_state:
        st.session_state.lecture_audio_position = audio_depart_sec
    if "lecture_active" not in st.session_state:
        st.session_state.lecture_active = False
    if "timestamp_captured" not in st.session_state:
        st.session_state.timestamp_captured = None


    try:
        audio_depart_sec = convertir_hms_en_secondes(audio_depart_str)
    except Exception:
        audio_depart_sec = 0.0
        st.warning(f"⚠️ audio_depart invalide dans infos_projet.json : {audio_depart_str}")

    if "lecture_audio_position" not in st.session_state:
        st.session_state.lecture_audio_position = audio_depart_sec

    if "lecture_active" not in st.session_state:
        st.session_state.lecture_active = False

    if "timestamp_captured" not in st.session_state:
        st.session_state.timestamp_captured = None

    if "photo_index_actuel" not in st.session_state:
        st.session_state.photo_index_actuel = None

    st.title("🛍️ AnnotationPhotosGPT – Étape 2.1 : Synchronisation audio/photos")

    fichier_photos = infos.get("fichier_photos")
    fichier_audio = infos.get("fichier_audio")
    photo_depart = infos.get("photo_depart", 1)
    

    try:
        photos_df = _load_photos(fichier_photos)

        NUM_COLS = ["horodatage_secondes", "synchro_audio", "t_audio",
                    "decalage_individuel", "decalage_moyen"]

        # 1) garantir l’existence des colonnes
        for col in NUM_COLS:
            if col not in photos_df.columns:
                photos_df[col] = pd.NA

        # 2) normaliser en numérique
        for col in NUM_COLS:
            photos_df[col] = pd.to_numeric(
                photos_df[col].astype(str).str.replace(",", "."), errors="coerce"
            )

    except Exception as e:
        st.error(f"Erreur lecture fichier photos : {e}")
        return

    # ─────────────────────────────────────────────────────────────
    # 🔄 Recalcul des points de sync déjà validés
    # ─────────────────────────────────────────────────────────────
    # On relit le CSV pour récupérer toutes les synchronisations existantes
    synchros_valides = photos_df[photos_df["decalage_individuel"].notna()]
    st.session_state.points_sync = synchros_valides["decalage_individuel"].tolist()
    st.session_state.indices_sync = synchros_valides.index.tolist()


    st.markdown("""
    ---
    🔧 **Instructions** :
    - Cliquez sur ▶️ pour écouter l'audio.
    - Utilisez ⏪ pour revenir en arrière si vous avez dépassé le clic.
    - Quand le *clic photo* est audible, cliquez sur 📍 *C’est ce moment-là*.
    - Répétez pour 2 à 6 photos.
    - Cliquez ensuite sur 🔁 *Valider et appliquer le décalage moyen* pour passer à l'étape suivante.
    - Vous pouvez également 🗑️ *Recommencer la calibration* à tout moment.
    """)

    # ── Barre d’actions principales ──
    col1, col2 = st.columns([1, 1])
    with col1:
        # ------------------------------------------------------------
        if st.button("🗑️ Recommencer la calibration"):
            photos_df = _load_photos(fichier_photos)
            NUM_COLS = [
                "horodatage_secondes",
                "synchro_audio",
                "t_audio",
                "decalage_individuel",
                "decalage_moyen",
            ]

            for col in NUM_COLS:
                if col not in photos_df.columns:
                    photos_df[col] = pd.NA
                photos_df[col] = pd.to_numeric(
                    photos_df[col].astype(str).str.replace(",", "."),
                    errors="coerce",
                )

            # Efface les champs de sync
            for col in ["synchro_audio", "t_audio", "decalage_individuel", "decalage_moyen"]:
                if col in photos_df.columns:
                    photos_df[col] = pd.NA

            # Recalcule horodatage_secondes depuis t0 audio
            if "horodatage_photo" in photos_df.columns:
                def _to_secs_since_audio0_local(s):
                    dt = _to_dt(s, default_date=heure_creation_audio)
                    return (dt - heure_creation_audio).total_seconds() if dt else pd.NA

                photos_df["horodatage_secondes"] = photos_df["horodatage_photo"].apply(_to_secs_since_audio0_local)

        
            for col in NUM_COLS:
                if col in photos_df.columns:
                    photos_df[col] = pd.to_numeric(photos_df[col], errors="coerce")

            _save_photos(photos_df, fichier_photos)

            # ⚠️ NE PLUS TOUCHER à photo_depart / audio_depart
            # On ne fait que marquer le calibrage comme invalide
            infos["calibrage_valide"] = False
            sauvegarder_infos_projet(infos)


            # 🔁 Purge systématique des fichiers d’annotation pour ce projet
            if base_dir and base_name:
                for ext in (".csv", ".xlsx"):
                    pattern = os.path.join(base_dir, f"{base_name}_GTP_*{ext}")
                    for f in glob.glob(pattern):
                        try:
                            os.remove(f)
                        except OSError:
                            pass

            prog_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "data", "progression_annotation.json")
            )
            if os.path.exists(prog_path):
                try:
                    os.remove(prog_path)
                except OSError:
                    pass


            # Repartir aux paramètres demandés dans infos_projet.json
            photo_depart = int(infos.get("photo_depart", 1))
            photo_start_index = max(0, photo_depart - 1)

            audio_depart_str = str(infos.get("audio_depart", "00:00:00") or "00:00:00")
            try:
                audio_depart_sec = convertir_hms_en_secondes(audio_depart_str)
            except Exception:
                audio_depart_sec = 0.0

            # Reset de l'état de synchro
            st.session_state.points_sync = []
            st.session_state.indices_sync = []
            st.session_state.lecture_audio_position = audio_depart_sec
            st.session_state.photo_index = photo_start_index
            st.session_state.photo_index_actuel = photo_start_index
            st.session_state.timestamp_captured = None

            st.success(
                f"Calibration réinitialisée. Reprise à la photo {photo_depart} "
                f"et à t = {audio_depart_str}."
            )
            st.rerun()


    with col2:
        if len(st.session_state.points_sync) >= 2 and st.button("🔁 Appliquer le décalage moyen"):
            # 1) Estimation du décalage global (en s) = moyenne des décalages individuels
            #    decalage_individuel = photo_dt - (audio0 + t_audio)
            decals = []
            for idx in st.session_state.indices_sync:
                d = photos_df.loc[idx, "decalage_individuel"]
                if pd.notna(d):
                    decals.append(float(d))

            if len(decals) < 2:
                st.error("Il faut au moins 2 points valides pour valider le calibrage.")
                return

            t0_global_sec = float(np.mean(decals))                   # décalage moyen en secondes
            t0_global_dt  = heure_creation_audio + timedelta(seconds=t0_global_sec)  # datetime

            
            # 2) Mise à jour de chaque photo
           
            # après: df = _load_photos(fichier_photos)
            NUM_COLS = ["horodatage_secondes","synchro_audio","t_audio","decalage_individuel","decalage_moyen"]
            for col in NUM_COLS:
                if col in photos_df.columns:
                    photos_df[col] = pd.to_numeric(photos_df[col].astype(str).str.replace(",", "."), errors="coerce")
            def _to_secs_since_audio0_local(s):
                dt = _to_dt(s, default_date=heure_creation_audio)
                return (dt - heure_creation_audio).total_seconds() if dt else pd.NA
            if "horodatage_photo" in photos_df.columns:
                photos_df["horodatage_secondes"] = photos_df["horodatage_photo"].apply(_to_secs_since_audio0_local)

            def compute_synchro(row):
                hs = row.get("horodatage_secondes")
                if pd.isna(hs):
                    return pd.NA
                d_ind = row.get("decalage_individuel")
                base  = d_ind if not pd.isna(d_ind) else t0_global_sec
                return hs - base

            photos_df["synchro_audio"] = photos_df.apply(compute_synchro, axis=1)
            photos_df["t_audio"]       = photos_df["synchro_audio"]          # même valeur, par cohérence
            photos_df["decalage_moyen"] = t0_global_sec               # garde le nom pour compatibilité
          
            n_hs_na = int(photos_df["horodatage_secondes"].isna().sum())
            n_sync_na = int(photos_df["synchro_audio"].isna().sum())
            if n_hs_na:
                st.warning(f"ℹ️ {n_hs_na} photo(s) sans horodatage exploitable : synchro non calculée pour elles.")
            if n_sync_na:
                st.warning(f"ℹ️ {n_sync_na} photo(s) sans synchro (horodatage manquant).") 


            # 3) Sauvegarde en floats (pas de conversion en texte)
            _save_photos(photos_df, fichier_photos)

# -------------------------------------------------------------

            # 4) Mise à jour des infos projet
            infos["decalage_moyen"] = t0_global_sec              # seconds
            infos["t0_global"]      = t0_global_dt.strftime("%Y-%m-%d %H:%M:%S")  # datetime absolu
            infos["calibrage_valide"] = True
            sauvegarder_infos_projet(infos)

            # 🔁 Nouveau t0 global → on supprime toutes les annotations existantes
            if base_dir and base_name:
                for ext in (".csv", ".xlsx"):
                    pattern = os.path.join(base_dir, f"{base_name}_GTP_*{ext}")
                    for f in glob.glob(pattern):
                        try:
                            os.remove(f)
                        except OSError:
                            pass

            prog_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "data", "progression_annotation.json")
            )
            if os.path.exists(prog_path):
                try:
                    os.remove(prog_path)
                except OSError:
                    pass


            # --- Debug console facultatif sur le CSV final (df) ---
            cols_voulues = ["nom_fichier_image",
                            "horodatage_secondes",
                            "synchro_audio",
                            "t_audio"]
            print("DEBUG photos_df – colonnes présentes :", list(photos_df.columns))
            cols_ok = [c for c in cols_voulues if c in photos_df.columns]
            cols_missing = [c for c in cols_voulues if c not in photos_df.columns]

            print("DEBUG photos_df – colonnes manquantes :", cols_missing)

            if cols_ok:
                print("DEBUG photos_df – aperçu :")
                print(photos_df[cols_ok].head())
            else:
                print("DEBUG photos_df – aucune des colonnes attendues n'est présente.")

            # --- Message utilisateur unique dans Streamlit ---
            st.success(
                f"✅ Calibrage validé : décalage global = {t0_global_sec:.2f} s "
                f"(t0_global = {infos['t0_global']})"
            )

            # 👉 Forcer le reload de l'app : main.py relira infos_projet.json
            #    et pourra passer à l'étape 2.2
            st.rerun()


    if not fichier_photos or not fichier_audio:
        st.error("Fichiers manquants. Veuillez vérifier les chemins dans infos_projet.json")
        return
    
    st.subheader("🔢 Points de synchronisation validés")

    for idx, val in zip(st.session_state.indices_sync, st.session_state.points_sync):
        nom_photo = photos_df.at[idx, "nom_fichier_image"]
        t_audio_val = None
        if "t_audio" in photos_df.columns:
            t_audio_val = photos_df.at[idx, "t_audio"]

        if t_audio_val is not None and not pd.isna(t_audio_val):
            msg = (
                f"- ✅ {nom_photo} (Photo {idx+1}) → "
                f"clic audio à `{float(t_audio_val):.2f}` s ; "
                f"décalage = `{float(val):.2f}` s"
            )
        else:
            msg = f"- ✅ {nom_photo} (Photo {idx+1}) → Décalage = `{float(val):.2f}` s"

        st.markdown(msg)


    photos_a_synchro = photos_df[photos_df["synchro_audio"].isna() & (photos_df.index >= (photo_depart - 1))]

    if photos_a_synchro.empty:
        st.warning("⚠️ Aucune photo à synchroniser.")
        return

    photo_courante = photos_a_synchro.iloc[0]
    i = photo_courante.name

    if i > 0:
        prev_sync = pd.to_numeric(str(photos_df.loc[i-1, "synchro_audio"]).replace(",", "."), errors="coerce")
        if pd.notna(prev_sync):
            st.session_state.lecture_audio_position = max(0.0, float(prev_sync) - float(retour_arriere))
        else:
            st.session_state.lecture_audio_position = audio_depart_sec
    else:
        st.session_state.lecture_audio_position = audio_depart_sec


    st.subheader(f"📸 Photo à synchroniser maintenant : {photo_courante['nom_fichier_image']} (Photo {i+1})")
    chemin_complet = os.path.join(photo_courante['chemin_photo_reduite'], photo_courante['nom_fichier_image'])
    st.image(chemin_complet, width=500)
    st.write(f"🕒 Horodatage photo : {photo_courante['horodatage_photo']}")
    
    # 🔧 Bloc technique repliable
    with st.expander("🔧 Informations techniques", expanded=False):
        # Horodatage t=0
        st.markdown(
            f"🕓 Horodatage t=0 du fichier audio : " +
            f"`{heure_creation_audio.strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        # Test HTTP sur le serveur audio
  


# ----------------------------------------------------------------       
        try:
            r = requests.head(audio_url, timeout=5)
            ok = r.status_code in (200, 206)
            if not ok:
                r = requests.get(audio_url, headers={"Range": "bytes=0-0"}, timeout=5)
                ok = r.status_code in (200, 206)
            if ok:
                st.success("✅ Serveur audio : accessible")
                try:
                    info = requests.get("http://127.0.0.1:5000/info", timeout=3).json()
                    if info.get("size_bytes"):
                        st.caption(f"Fichier : {info.get('filename')} • ~{info['size_bytes']/1_000_000:.1f} Mo")
                except Exception:
                    pass
            else:
                st.warning(f"⚠️ Réponse HTTP {r.status_code}")
        except Exception as e:
            st.error(f"❌ Serveur audio injoignable : {e}")

        # Position de lecture actuelle
        try:
            pos = float(st.session_state.get("lecture_audio_position", 0.0))
            st.code(f"⏱ lecture_audio_position = {pos:.2f} s")
        except Exception:
            st.warning("⚠️ lecture_audio_position est invalide")

        # État de session (debug)
        st.markdown("🧪 Session state (debug)")
        st.json({
            "photo_index_actuel": st.session_state.get("photo_index_actuel"),
            "lecture_active": st.session_state.get("lecture_active"),
            "timestamp_captured": st.session_state.get("timestamp_captured"),
        })
  
    try:
        pos = float(st.session_state.lecture_audio_position)
        st.write(f"DEBUG : lecture_audio_position actuelle = {pos:.2f} s")
    except Exception:
        st.warning("⚠️ lecture_audio_position est invalide ou non numérique")

    if not st.session_state.lecture_active:
        st.info(f"⏸️ Lecture en pause. Cliquez ci-dessous pour commencer à écouter cette photo (à {st.session_state.lecture_audio_position:.2f} sec).")
        clicked = st.button("▶️ Reprendre la lecture pour cette photo", key="play_button")
        if clicked:
            st.session_state.lecture_active = True
            st.rerun()

    # 🔁 Lecture active → afficher le composant React
    if st.session_state.lecture_active:
        start_sec = st.session_state.get("lecture_audio_position", 0.0)
        st.write("📍 composant appelé")
              
        # ► appel du nouveau composant
        t_audio = wavesurfer(
            audio_url=audio_url,           # variable déjà définie au début
            height=140,
            start_sec=start_sec,           # reprend la lecture ici
            key="audio-sync",
        )
        
        # ---------- Retour JS & validation opérateur ----------
        if isinstance(t_audio, (int, float)):
            st.session_state.t_audio_courant = t_audio
            st.markdown(f"⏱ Temps courant : `{t_audio:.2f} s`")
                    

        # Bloc toujours visible pour valider le moment
        st.markdown("### 📍 Capturer ce moment audio")

        # Affiche le t_audio capté s’il existe
        if isinstance(t_audio, (int, float)):
            st.info(f"🕒 Temps capté par l’onde : {t_audio:.2f} s")
        else:
            st.warning("⚠️ Aucun retour détecté depuis le composant audio.")

        # Bouton toujours affiché
        if st.button("📍 C’est ce moment-là"):
            if isinstance(t_audio, (int, float)):
                st.session_state.timestamp_captured = t_audio
                st.session_state.lecture_active = False   # → stoppe la lecture au moment de la capture

                if t_audio <= 0.1:
                    st.warning("⚠️ Le temps capté est très proche de zéro. Utilisez la saisie manuelle si besoin.")
                else:
                    st.success(f"✅ Point enregistré à {t_audio:.2f} s")
            else:
                st.error("⛔ Aucun temps capté automatiquement. Saisie manuelle requise.")
     
        
        # 🔁 Champ manuel pour saisir le temps
        # 🔁 Saisie manuelle (tous les arguments numériques sont des floats)
        t_audio_manuel = st.number_input(
            "⏱ Entrez manuellement le temps (en secondes)",
            value=float(st.session_state.get("t_audio_courant", 0.0)),  # valeur par défaut float
            min_value=0.0,
            step=0.1,
            key="saisie_manuelle",
        )

        # ✅ Bouton de validation manuelle juste en dessous
        if st.button("✅ Forcer la validation à ce temps"):
            st.session_state.timestamp_captured = t_audio_manuel
            st.success(f"✅ Point saisi manuellement à {t_audio_manuel:.2f} s")


        # ⏪ Réécoute -10 s
        if st.button("⏪ Réécouter 10 s en arrière"):
            st.session_state.lecture_audio_position = max(0, start_sec - retour_arriere)
            st.session_state.lecture_active = True
            st.rerun()

        # ---------- Si un point vient d’être validé ----------
        if st.session_state.timestamp_captured is not None:
            try:
                t_audio_valide = float(st.session_state.timestamp_captured)
                horodatage_audio_absolu = heure_creation_audio + timedelta(seconds=t_audio_valide)
                chemin_native = os.path.join(
                    photo_courante.get("chemin_photo_native", photo_courante["chemin_photo_reduite"]),
                    photo_courante["nom_fichier_image"]
                )
                horodatage_photo = get_photo_datetime(chemin_native)
                if horodatage_photo is None:
                    st.error("⛔ Impossible de lire les métadonnées EXIF de la photo.")
                    st.session_state.timestamp_captured = None
                    st.session_state.lecture_active = False
                    return  # ou st.stop()

                # ... calculs ...

                horodatage_sec = (horodatage_photo - heure_creation_audio).total_seconds()
                decalage = (horodatage_photo - horodatage_audio_absolu).total_seconds()


                photos_df.at[i, "horodatage_secondes"] = horodatage_sec
                photos_df.at[i, "t_audio"]             = t_audio_valide
                photos_df.at[i, "synchro_audio"]       = t_audio_valide
                photos_df.at[i, "decalage_individuel"] = decalage

                # ✅ assertions sur la ligne i uniquement
                assert pd.notna(photos_df.at[i, "horodatage_secondes"]), "horodatage_secondes manquant (ligne courante) !"
                assert pd.notna(photos_df.at[i, "synchro_audio"]),       "synchro_audio manquant (ligne courante) !"
                assert photos_df.at[i, "synchro_audio"] == photos_df.at[i, "t_audio"], "t_audio ≠ synchro_audio (ligne courante) !"

                _save_photos(photos_df, fichier_photos)

                # Préparer la prochaine boucle
                st.session_state.lecture_audio_position = max(0, t_audio_valide - retour_arriere)
                st.session_state.lecture_active = False
                st.session_state.photo_index_actuel = i + 1
                st.session_state.timestamp_captured = None


                st.success("✅ Synchronisation enregistrée !")
                st.rerun()

            except Exception as e:
                st.error(f"Erreur lors du calcul du décalage : {e}")


