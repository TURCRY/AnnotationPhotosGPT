import os
import subprocess
import shutil
from datetime import datetime
import time
import json
import hashlib

import streamlit as st
import socket

import signal
import requests

# soundfile est optionnel : si absent, on convertira systématiquement le WAV
try:
    import soundfile as sf
except Exception:
    sf = None

# Fichier audio technique utilisé par le serveur
AUDIO_COMPAT = os.path.join("data", "temp", "audio_compatible.wav")


# -------------------------------------------------------
# Utilitaires de conversion
# -------------------------------------------------------
def convertir_en_pcm_wav(source: str, cible: str, overwrite: bool = True) -> bool:
    """
    Convertit `source` en WAV PCM 16 bits, mono, 44.1kHz -> `cible`.
    Retourne True si OK.
    """
    if not shutil.which("ffmpeg"):
        st.error("⛔ FFmpeg n'est pas installé ou n'est pas dans le PATH.")
        return False

    cmd = [
        "ffmpeg",
        "-y" if overwrite else "-n",
        "-i", source,
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", "44100",
        "-f", "wav",
        cible,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        st.success("✅ Conversion réalisée avec succès.")
        return True
    except subprocess.CalledProcessError as e:
        st.error("❌ Erreur lors de la conversion avec FFmpeg :")
        st.code((e.stderr or "")[:500])
        return False
    except FileNotFoundError:
        st.error("⛔ FFmpeg introuvable.")
        return False
    except Exception as e:
        st.error(f"❌ Erreur inattendue FFmpeg : {e}")
        return False


def ensure_audio_ready(source_audio: str) -> bool:
    """
    Si AUDIO_COMPAT existe déjà et non vide → OK.
    Sinon, le génère à partir de `source_audio`.
    """
    os.makedirs(os.path.dirname(AUDIO_COMPAT), exist_ok=True)
    if os.path.exists(AUDIO_COMPAT) and os.path.getsize(AUDIO_COMPAT) > 0:
        return True
    return convertir_en_pcm_wav(source_audio, AUDIO_COMPAT)


def purge_audio_temp():
    """Supprime l'audio compatible technique."""
    try:
        if os.path.exists(AUDIO_COMPAT):
            os.remove(AUDIO_COMPAT)
    except Exception:
        pass

def is_compat_for_source(source_path: str) -> bool:
    meta_path = os.path.join(os.path.dirname(AUDIO_COMPAT), "audio_meta.json")
    if not os.path.exists(AUDIO_COMPAT) or os.path.getsize(AUDIO_COMPAT) == 0:
        return False
    if not os.path.exists(meta_path):
        return False

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        if os.path.abspath(meta.get("source", "")) != os.path.abspath(source_path):
            return False
        if meta.get("source_size") != os.path.getsize(source_path):
            return False


        h = hashlib.sha1()
        with open(source_path, "rb") as fsrc:
            h.update(fsrc.read(1_000_000))
        if meta.get("source_sha1_1mo") != h.hexdigest():
            return False

        return True
    except Exception:
        return False


def save_audio_meta(source_path: str, compat_path: str):
    meta_path = os.path.join(os.path.dirname(compat_path), "audio_meta.json")
    try:
        h = hashlib.sha1()
        with open(source_path, "rb") as fsrc:
            h.update(fsrc.read(1_000_000))

        meta = {
            "source": os.path.abspath(source_path),
            "source_size": os.path.getsize(source_path),
            "source_sha1_1mo": h.hexdigest(),
            "compat": os.path.abspath(compat_path),
            "compat_size": os.path.getsize(compat_path),
            "written_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] Impossible d'écrire audio_meta.json : {e}")


def _same_source_meta(source_path: str, wav_path: str) -> bool:
    """
    Compare les dates de création + un hash rapide si audio_meta.json existe.
    Permet de vérifier si le WAV compatible correspond bien à la même source.
    """
    meta_path = os.path.join(os.path.dirname(AUDIO_COMPAT), "audio_meta.json")

    try:
        # comparaison directe date de création
        src_ctime = os.path.getctime(source_path)
        wav_ctime = os.path.getctime(wav_path)

        if abs(src_ctime - wav_ctime) > 1.0:
            return False  # dates différentes → pas la même affaire

        # si les métadonnées sont disponibles, on va plus loin
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            # Fichier source différent ?
            if meta.get("source") != source_path:
                return False

            # Taille différente ?
            if meta.get("size") != os.path.getsize(source_path):
                return False

            # Hash rapide différent ?
            h = hashlib.sha1()
            with open(source_path, "rb") as f:
                h.update(f.read(1_000_000))

            if meta.get("sha1_1mo") != h.hexdigest():
                return False

        return True

    except Exception:
        return False
 
def _port_open(host="127.0.0.1", port=5000, timeout=0.3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

# -------------------------------------------------------
# Serveur audio
# -------------------------------------------------------



def _get_server_audio_path():
    try:
        r = requests.get("http://127.0.0.1:5000/ping", timeout=0.5)
        if r.ok:
            return (r.json() or {}).get("audio_path")
    except Exception:
        return None
    return None

def start_audio_server_if_needed(audio_path: str):
    wanted = os.path.abspath(audio_path)

    if _port_open("127.0.0.1", 5000):
        served = _get_server_audio_path()
        # si le serveur répond et sert déjà le bon fichier → rien à faire
        if served and os.path.abspath(served) == wanted:
            return

        # sinon → tenter d’arrêter proprement le process qu’on a mémorisé
        proc = st.session_state.get("_audio_srv")
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            st.session_state["_audio_srv"] = None

        # attendre la libération du port
        for _ in range(30):
            if not _port_open("127.0.0.1", 5000):
                break
            time.sleep(0.1)

    env = os.environ.copy()
    env["AUDIO_FILE_PATH"] = wanted

    base_dir = os.path.abspath(os.path.dirname(__file__))
    script = os.path.join(base_dir, "app", "audio_server.py")

    proc = subprocess.Popen(["python", script], cwd=base_dir, env=env)
    st.session_state["_audio_srv"] = proc

    for _ in range(30):
        if _port_open("127.0.0.1", 5000):
            # option : vérifier que le serveur sert bien le bon fichier
            served = _get_server_audio_path()
            if served and os.path.abspath(served) == wanted:
                break
        time.sleep(0.1)


def stop_audio_server_if_any():
    proc = st.session_state.get("_audio_srv")
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
        st.session_state["_audio_srv"] = None


# -------------------------------------------------------
# Horodatage
# -------------------------------------------------------

def _extraire_horodatage_source(path: str) -> str:
    """
    Horodatage "origine" basé sur les métadonnées système :
    on prend le min(ctime, mtime), ce qui évite de prendre la date de copie
    quand le fichier a juste été déplacé.
    (Pour encore mieux faire : lire les métadonnées BWF/EXIF si dispo.)
    """
    try:
        st_stat = os.stat(path)
        ts = min(st_stat.st_ctime, st_stat.st_mtime)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


# -------------------------------------------------------
# Traitement principal
# -------------------------------------------------------
def traiter_fichier_audio_selectionne(path: str) -> bool:
    """
    Prépare un audio compatible à partir du fichier `path` (.wav/.mp3).

    - Si AUDIO_COMPAT existe déjà → pas de reconversion.
    - WAV : copie directe si déjà PCM 16 / mono / 44.1kHz, sinon conversion.
    - MP3 : conversion en WAV compatible.
    - En sortie :
        * st.session_state.fichiers_temp["fichier_audio_source"] = path
        * st.session_state.fichiers_temp["fichier_audio_compatible"] = AUDIO_COMPAT (si ok)
        * st.session_state.fichiers_temp["fichier_audio"] = path  (pour compatibilité)
        * st.session_state.horodatage_audio = horodatage du fichier source
    """
    if not path:
        st.info("Sélection audio annulée.")
        return False

    os.makedirs(os.path.dirname(AUDIO_COMPAT), exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    ok = False

    # --- Cas WAV ---
    if ext == ".wav":
        try:
            meta_path = os.path.join(os.path.dirname(AUDIO_COMPAT), "audio_meta.json")

            reuse_possible = (
                os.path.exists(AUDIO_COMPAT)
                and os.path.getsize(AUDIO_COMPAT) > 0
                and is_compat_for_source(path)
            )

            if reuse_possible:
                st.info("ℹ️ Audio compatible déjà présent pour ce fichier source (métadonnées OK), aucune reconversion.")
                ok = True
            else:
                # purge ancien compatible + meta si pas compatible
                if os.path.exists(AUDIO_COMPAT):
                    try:
                        os.remove(AUDIO_COMPAT)
                        st.warning("🗑 Ancien audio compatible supprimé (source différente).")
                    except OSError:
                        st.warning("⚠️ Impossible de supprimer l'ancien audio compatible, il sera écrasé si possible.")

                if os.path.exists(meta_path):
                    try:
                        os.remove(meta_path)
                    except OSError:
                        pass

                # génération du compatible
                if sf is None:
                    ok = convertir_en_pcm_wav(path, AUDIO_COMPAT)
                else:
                    info = sf.info(path)
                    if (
                        info.samplerate == 44100
                        and info.channels == 1
                        and info.subtype
                        and info.subtype.lower() in ["pcm_16", "pcm_s16le"]
                    ):
                        shutil.copy2(path, AUDIO_COMPAT)
                        st.info("✅ WAV compatible copié tel quel.")
                        ok = True
                    else:
                        ok = convertir_en_pcm_wav(path, AUDIO_COMPAT)
                        if ok:
                            st.warning("🔁 WAV non standard – converti automatiquement.")


        except Exception as e:
            st.error(f"Erreur lecture/traitement WAV : {e}")
            ok = False

    # --- Cas MP3 ---
    elif ext == ".mp3":
        st.warning(
            "⚠️ MP3 sélectionné – le WAV d’origine est recommandé pour un horodatage fiable. "
            "Utilisation du MP3 comme source technique."
        )

        # Vérifier si un audio compatible existant correspond à la même source
        reuse_possible = (
            os.path.exists(AUDIO_COMPAT)
            and os.path.getsize(AUDIO_COMPAT) > 0
            and _same_source_meta(path, AUDIO_COMPAT)
        )

        if reuse_possible:
            st.info("ℹ️ Audio compatible déjà présent pour ce MP3 source, aucune reconversion.")
            ok = True
        else:
            # On supprime l’ancien audio incompatible
            if os.path.exists(AUDIO_COMPAT):
                try:
                    os.remove(AUDIO_COMPAT)
                    st.warning("🗑 Ancien audio compatible supprimé (source différente).")
                except OSError:
                    st.warning("⚠️ Impossible de supprimer le précédent fichier audio compatible.")

            # Conversion mp3 → wav PCM compatible
            ok = ensure_audio_ready(path)

            if ok and os.path.exists(AUDIO_COMPAT):
                # Copier la date de création du MP3 source vers le WAV compatible
                try:
                    src_ctime = os.path.getctime(path)
                    os.utime(AUDIO_COMPAT, (src_ctime, src_ctime))
                except Exception:
                    pass

                st.info("📁 WAV compatible généré depuis MP3.")


    # --- Types non supportés ---
    else:
        st.error("Type de fichier audio non supporté. Choisissez un .wav ou .mp3.")
        ok = False

    # --- Horodatage depuis le fichier source si OK ---
    if ok:
        horodatage = _extraire_horodatage_source(path)
        if horodatage:
            st.session_state.horodatage_audio = horodatage
            st.info(f"🕒 Horodatage extrait (fichier source) : {horodatage}")
        else:
            st.warning("⚠️ Impossible de déterminer l'horodatage du fichier audio source.")

    # --- Mémorisation dans l'état ---
    st.session_state.setdefault("fichiers_temp", {})
    st.session_state.fichiers_temp["fichier_audio_source"] = path

    if ok and os.path.exists(AUDIO_COMPAT):
        try:
            save_audio_meta(path, AUDIO_COMPAT)
        except Exception:
            pass
        st.session_state.fichiers_temp["fichier_audio_compatible"] = AUDIO_COMPAT
        # Pour le reste du code, `fichier_audio` = fichier source (ce que tu veux exploiter)
        st.session_state.fichiers_temp["fichier_audio"] = path
        st.info(f"📁 Fichier compatible généré : {AUDIO_COMPAT}")
        return True

    st.error("❌ Aucun fichier audio compatible n'a été généré.")
    return False
