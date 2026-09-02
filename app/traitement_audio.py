import os
import subprocess
import shutil
import sys
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
AUDIO_SERVER_HOST = "127.0.0.1"
AUDIO_SERVER_PORT = 5000
AUDIO_SERVER_BASE_URL = f"http://{AUDIO_SERVER_HOST}:{AUDIO_SERVER_PORT}"


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

def _canonical_audio_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(str(path)))


def audio_file_identity(path: str) -> dict:
    p = _canonical_audio_path(path)
    stat = os.stat(p)
    return {
        "source_path": p,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def audio_identity_fingerprint(identity_or_path) -> str:
    identity = (
        audio_file_identity(identity_or_path)
        if isinstance(identity_or_path, (str, os.PathLike))
        else identity_or_path
    )
    raw = (
        f"{os.path.normcase(_canonical_audio_path(identity.get('source_path', '')))}|"
        f"{int(identity.get('size', -1))}|"
        f"{int(identity.get('mtime_ns', -1))}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def audio_url_for_identity(identity_or_path) -> str:
    fingerprint = audio_identity_fingerprint(identity_or_path)
    return f"{AUDIO_SERVER_BASE_URL}/audio/audio_compatible.wav?v={fingerprint}"


def audio_component_key_for_identity(identity_or_path) -> str:
    return f"audio-sync-{audio_identity_fingerprint(identity_or_path)}"


def _identity_matches(served: dict | None, expected: dict) -> bool:
    if not served:
        return False
    try:
        served_path = served.get("source_path") or served.get("audio_path")
        served_size = served.get("size", served.get("size_bytes"))
        served_mtime = served.get("mtime_ns")
        return (
            os.path.normcase(_canonical_audio_path(served_path))
            == os.path.normcase(_canonical_audio_path(expected["source_path"]))
            and int(served_size) == int(expected["size"])
            and int(served_mtime) == int(expected["mtime_ns"])
        )
    except Exception:
        return False



def _get_server_audio_path():
    try:
        r = requests.get(f"{AUDIO_SERVER_BASE_URL}/ping", timeout=0.5)
        if r.ok:
            return (r.json() or {}).get("audio_path")
    except Exception:
        return None
    return None

def _get_server_audio_info():
    try:
        r = requests.get(f"{AUDIO_SERVER_BASE_URL}/audio/info", timeout=0.8)
        if r.ok:
            return r.json() or {}
    except Exception:
        return None
    return None


def _listener_pids_on_port(port: int = AUDIO_SERVER_PORT) -> set[int]:
    pids: set[int] = set()
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            for line in (result.stdout or "").splitlines():
                parts = line.split()
                if len(parts) < 5 or parts[0].upper() != "TCP":
                    continue
                local_addr, state, pid_text = parts[1], parts[3].upper(), parts[4]
                if state != "LISTENING":
                    continue
                if local_addr.rsplit(":", 1)[-1] == str(port):
                    try:
                        pids.add(int(pid_text))
                    except ValueError:
                        pass
        except Exception:
            return set()
        return pids

    for cmd in (["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"], ["fuser", f"{port}/tcp"]):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
        except Exception:
            continue
        for token in (result.stdout or "").replace("\n", " ").split():
            try:
                pids.add(int(token))
            except ValueError:
                pass
        if pids:
            break
    return pids


def _process_command_line(pid: int) -> str:
    if os.name == "nt":
        commands = [
            ["wmic", "process", "where", f"ProcessId={int(pid)}", "get", "CommandLine", "/value"],
            [
                r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
            ],
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
            ],
        ]
    else:
        commands = [["ps", "-p", str(int(pid)), "-o", "command="]]

    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except Exception:
            continue
        output = (result.stdout or "").strip()
        if not output:
            continue
        if "CommandLine=" in output:
            output = output.split("CommandLine=", 1)[1].strip()
        return output
    return ""


def _is_our_audio_server_process(pid: int) -> bool:
    cmdline = _process_command_line(pid)
    if not cmdline:
        return False
    cmd_norm = cmdline.replace("/", "\\").lower()
    script = os.path.realpath(os.path.join(os.path.dirname(__file__), "audio_server.py"))
    script_norm = script.replace("/", "\\").lower()
    return "audio_server.py" in cmd_norm and (
        script_norm in cmd_norm or "\\annotationphotosgpt\\" in cmd_norm
    )


def _terminate_process_tree(pid: int) -> None:
    if int(pid) == os.getpid():
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    else:
        os.kill(int(pid), signal.SIGTERM)


def _session_state_get(key):
    try:
        return st.session_state.get(key)
    except Exception:
        return None


def _session_state_set(key, value):
    try:
        st.session_state[key] = value
    except Exception:
        pass


def _stop_stale_audio_servers_on_port(port: int = AUDIO_SERVER_PORT) -> list[int]:
    stopped: list[int] = []
    for pid in sorted(_listener_pids_on_port(port)):
        if _is_our_audio_server_process(pid):
            _terminate_process_tree(pid)
            stopped.append(pid)
    return stopped


def start_audio_server_if_needed(audio_path: str):
    wanted = _canonical_audio_path(audio_path)
    if not os.path.exists(wanted):
        raise FileNotFoundError(f"Fichier audio introuvable : {wanted}")

    expected = audio_file_identity(wanted)

    if _port_open(AUDIO_SERVER_HOST, AUDIO_SERVER_PORT):
        served = _get_server_audio_info()
        if _identity_matches(served, expected):
            return expected

        proc = _session_state_get("_audio_srv")
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            _session_state_set("_audio_srv", None)

        _stop_stale_audio_servers_on_port(AUDIO_SERVER_PORT)

        for _ in range(30):
            if not _port_open(AUDIO_SERVER_HOST, AUDIO_SERVER_PORT):
                break
            time.sleep(0.1)

        if _port_open(AUDIO_SERVER_HOST, AUDIO_SERVER_PORT):
            served_after_stop = _get_server_audio_info()
            if _identity_matches(served_after_stop, expected):
                return expected
            raise RuntimeError(
                "Le port audio 127.0.0.1:5000 est occupe par un serveur qui ne "
                "sert pas le fichier audio demande, et il n'a pas pu etre remplace "
                "avec les garde-fous actuels."
            )

    env = os.environ.copy()
    env["AUDIO_FILE_PATH"] = wanted

    base_dir = os.path.abspath(os.path.dirname(__file__))
    script = os.path.join(base_dir, "audio_server.py")
    if not os.path.exists(script):
        raise RuntimeError(f"Serveur audio introuvable : {script}")

    proc = subprocess.Popen(
        [sys.executable, script],
        cwd=base_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _session_state_set("_audio_srv", proc)

    for _ in range(30):
        if proc.poll() is not None:
            _session_state_set("_audio_srv", None)
            raise RuntimeError(
                "Le serveur audio local s'est arrêté immédiatement après son lancement."
            )
        if _port_open(AUDIO_SERVER_HOST, AUDIO_SERVER_PORT):
            served = _get_server_audio_info()
            if _identity_matches(served, expected):
                return expected
        time.sleep(0.1)

    _session_state_set("_audio_srv", None)
    try:
        proc.terminate()
    except Exception:
        pass
    raise RuntimeError(
        "Impossible de demarrer un serveur audio local coherent avec le fichier demande "
        "sur 127.0.0.1:5000."
    )


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
