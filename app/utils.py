
import os
import json
import uuid
import shutil
import glob
import re
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS
import soundfile as sf
import streamlit as st
import streamlit.components.v1 as components
import tempfile
import pandas as pd
from pathlib import Path
import shutil

from compat_affaire_captation import normalize_infos_aliases
from path_migration import migrate_local_user_paths, migrate_photo_dataframe_paths

CANONICAL_UNC_AFFAIRES_ROOT = r"\\192.168.1.20\Affaires"
PCFIXE_LOCAL_AFFAIRES_ROOT = r"C:\Affaires"
_AFFAIRES_ROOT_RE = re.compile(
    r"^(?P<root>(?:[A-Za-z]:\\Affaires|\\\\[^\\]+\\Affaires))(?:\\(?P<suffix>.*))?$",
    re.IGNORECASE,
)

# Fonctions existantes utiles

def get_canonical_affaires_root() -> str:
    return CANONICAL_UNC_AFFAIRES_ROOT


def _normalize_windows_path_string(path_value: str) -> str:
    return str(path_value or "").strip().replace("/", "\\").rstrip("\\")


def split_affaires_root_and_suffix(path_value: str) -> tuple[str, str]:
    raw = _normalize_windows_path_string(path_value)
    if not raw:
        return "", ""
    match = _AFFAIRES_ROOT_RE.match(raw)
    if not match:
        return "", ""
    return match.group("root") or "", (match.group("suffix") or "").strip("\\")


def path_uses_noncanonical_affaires_root(path_value: str) -> bool:
    root, _ = split_affaires_root_and_suffix(path_value)
    if not root:
        return False
    return root.lower() != CANONICAL_UNC_AFFAIRES_ROOT.lower()


def canonicalize_affaires_path(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    root, suffix = split_affaires_root_and_suffix(raw)
    if not root:
        return raw
    if suffix:
        return str(Path(CANONICAL_UNC_AFFAIRES_ROOT) / Path(suffix))
    return CANONICAL_UNC_AFFAIRES_ROOT


def canonicalize_infos_paths(data):
    if isinstance(data, dict):
        return {key: canonicalize_infos_paths(value) for key, value in data.items()}
    if isinstance(data, list):
        return [canonicalize_infos_paths(value) for value in data]
    if isinstance(data, str):
        return canonicalize_affaires_path(data)
    return data


def build_canonical_snapshot_paths(id_affaire: str, id_captation: str) -> dict[str, Path]:
    root = Path(CANONICAL_UNC_AFFAIRES_ROOT) / str(id_affaire or "").strip()
    base_cap = root / "AE_Expert_captations" / str(id_captation or "").strip()
    trans_dir = root / "AF_Expert_ASR" / "transcriptions" / str(id_captation or "").strip()
    photos_dir = base_cap / "photos"
    return {
        "root_affaire": root,
        "base_cap": base_cap,
        "photos_dir": photos_dir,
        "audio_dir": base_cap / "audio",
        "trans_dir": trans_dir,
        "infos": trans_dir / "infos_projet.json",
        "photos_csv": photos_dir / "photos.csv",
        "photos_batch_csv": photos_dir / "photos_batch.csv",
    }


def build_pcfixe_snapshot_paths(id_affaire: str, id_captation: str) -> dict[str, Path]:
    root = Path(PCFIXE_LOCAL_AFFAIRES_ROOT) / str(id_affaire or "").strip()
    base_cap = root / "AE_Expert_captations" / str(id_captation or "").strip()
    trans_dir = root / "AF_Expert_ASR" / "transcriptions" / str(id_captation or "").strip()
    photos_dir = base_cap / "photos"
    return {
        "root_affaire": root,
        "base_cap": base_cap,
        "photos_dir": photos_dir,
        "audio_dir": base_cap / "audio",
        "trans_dir": trans_dir,
        "infos": trans_dir / "infos_projet.json",
        "photos_csv": photos_dir / "photos.csv",
        "photos_batch_csv": photos_dir / "photos_batch.csv",
        "config_llm": trans_dir / "config_llm.json",
        "prompt_gpt": trans_dir / "prompt_gpt.json",
        "prompt_gpt_batch": trans_dir / "prompt_gpt_batch_only.json",
    }


def pcfixe_affaires_path(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    root, suffix = split_affaires_root_and_suffix(raw)
    if not root:
        return raw
    if suffix:
        return str(Path(PCFIXE_LOCAL_AFFAIRES_ROOT) / Path(suffix))
    return PCFIXE_LOCAL_AFFAIRES_ROOT


def comparable_affaires_path(path_value: str) -> str:
    """Normalise seulement les racines Affaires equivalentes pour comparer deux chemins."""
    raw = str(path_value or "").strip().strip('"')
    if not raw:
        return ""
    canonical = canonicalize_affaires_path(raw)
    return os.path.normcase(os.path.abspath(canonical))


def same_project_path(left: str, right: str) -> bool:
    return bool(left and right and comparable_affaires_path(left) == comparable_affaires_path(right))


def project_path_exists(path_value: str) -> bool:
    """Teste existence avec miroirs C:\\Affaires et UNC canonique."""
    raw = str(path_value or "").strip().strip('"')
    if not raw:
        return False
    if os.path.exists(raw):
        return True

    candidates = []
    canonical = canonicalize_affaires_path(raw)
    if canonical and canonical != raw:
        candidates.append(canonical)
    pcfixe = pcfixe_affaires_path(raw)
    if pcfixe and pcfixe != raw:
        candidates.append(pcfixe)

    return any(candidate and os.path.exists(candidate) for candidate in candidates)


def detect_canonical_snapshot(id_affaire: str, id_captation: str) -> dict:
    paths = build_canonical_snapshot_paths(id_affaire, id_captation)
    photos_dir = paths["photos_dir"]
    pattern_csv = str(photos_dir / "*_GTP_*.csv")
    pattern_xlsx = str(photos_dir / "*_GTP_*.xlsx")
    gtp_files = sorted(glob.glob(pattern_csv)) + sorted(glob.glob(pattern_xlsx))
    return {
        "root": CANONICAL_UNC_AFFAIRES_ROOT,
        "root_exists": Path(CANONICAL_UNC_AFFAIRES_ROOT).exists(),
        "paths": paths,
        "infos_exists": paths["infos"].exists(),
        "photos_csv_exists": paths["photos_csv"].exists(),
        "photos_batch_exists": paths["photos_batch_csv"].exists(),
        "gtp_files": gtp_files,
        "snapshot_exists": bool(
            paths["infos"].exists()
            or paths["photos_csv"].exists()
            or paths["photos_batch_csv"].exists()
            or gtp_files
        ),
    }


def load_canonical_snapshot_infos(id_affaire: str, id_captation: str) -> tuple[dict, dict]:
    probe = detect_canonical_snapshot(id_affaire, id_captation)
    infos_path = probe["paths"]["infos"]
    if not probe["infos_exists"]:
        raise FileNotFoundError(f"Snapshot canonique introuvable : {infos_path}")
    with open(infos_path, "r", encoding="utf-8") as f:
        infos = json.load(f)
    infos = normalize_infos_aliases(canonicalize_infos_paths(infos))
    infos.setdefault("pcfixe", {})
    if isinstance(infos["pcfixe"], dict):
        pc_paths = build_pcfixe_snapshot_paths(id_affaire, id_captation)
        pcfixe = infos["pcfixe"]
        pcfixe["root_affaires"] = PCFIXE_LOCAL_AFFAIRES_ROOT
        pcfixe["infos"] = str(pc_paths["infos"])
        pcfixe["fichier_photos"] = str(pc_paths["photos_csv"])
        pcfixe["fichier_photos_batch"] = str(pc_paths["photos_batch_csv"])
        pcfixe["config_llm"] = str(pc_paths["config_llm"])
        pcfixe["prompt_gpt"] = str(pc_paths["prompt_gpt"])
        pcfixe["prompt_gpt_batch"] = str(pc_paths["prompt_gpt_batch"])
        for key in (
            "fichier_transcription",
            "fichier_contexte_general",
            "fichier_audio_source",
            "audio_compat_source",
            "fichier_audio",
            "fichier_audio_compatible",
        ):
            value = pcfixe.get(key) or infos.get(key)
            if value:
                pcfixe[key] = pcfixe_affaires_path(str(value))
    infos["id_affaire"] = str(id_affaire or "").strip()
    infos["project_id"] = infos["id_affaire"]
    infos["id_captation"] = str(id_captation or "").strip()
    infos["captation_id"] = infos["id_captation"]
    return infos, probe

def init_session_state(defaults: dict):
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def parse_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Format de date invalide : {value}")

def format_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def convertir_horodatage_en_secondes(horodatage: str) -> float:
    """Convertit un horodatage en secondes depuis minuit.
       Accepte : 'HH:MM:SS' ou 'JJ/MM/AAAA HH:MM:SS'.
    """
    s = horodatage.strip()

    # Cas 1 : format complet "JJ/MM/AAAA HH:MM:SS"
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.hour * 3600 + dt.minute * 60 + dt.second
        except Exception:
            pass

    # Cas 2 : format "HH:MM:SS"
    try:
        h, m, sec = map(int, s.split(":"))
        return h * 3600 + m * 60 + sec
    except Exception:
        raise ValueError(f"Horodatage invalide : {horodatage}")

def lire_infos_projet():
    """Lit l'etat local de travail de l'application depuis infos_projet.json."""
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "infos_projet.json"))
    if not os.path.exists(path):
        raise FileNotFoundError(f"infos_projet.json introuvable à : {path}")
    with open(path, "r", encoding="utf-8") as f:
        infos = json.load(f)
    infos, changed = migrate_local_user_paths(infos)
    canonical_infos = canonicalize_infos_paths(infos)
    changed = changed or (canonical_infos != infos)
    infos = canonical_infos
    infos = normalize_infos_aliases(infos)
    if changed:
        sauvegarder_infos_projet(infos)
    return infos

def sauvegarder_infos_projet(donnees: dict):
    """Ecrit l'etat local de travail; ce fichier ne remplace pas la configuration projet serveur."""
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "infos_projet.json"))
    tmp = path + ".tmp"
    donnees = normalize_infos_aliases(canonicalize_infos_paths(donnees))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)



def get_photo_datetime(photo_path):
    try:
        image = Image.open(photo_path)
        exif_data = image._getexif()
        if not exif_data:
            return None
        for tag, value in exif_data.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "DateTimeOriginal":
                return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
def extraire_audio(fichier_audio: str, t_debut: float, t_fin: float, fichier_temp: str) -> str:
    y, sr = sf.read(fichier_audio)
    start = int(max(0, t_debut) * sr)
    end = int(min(len(y), t_fin * sr))
    extrait = y[start:end]

    if (end - start) <= 0:
        raise ValueError("Segment audio vide ou invalide (start >= end)")

    os.makedirs(os.path.dirname(fichier_temp), exist_ok=True)
    sf.write(fichier_temp, extrait, sr)
    return fichier_temp




def copy_audio_to_static(fichier_audio: str) -> str:
    """
    Convertit un fichier audio source en PCM 16 bits mono 44.1kHz
    et le place dans /data/temp/audio_temp_001.wav pour usage web.
    """
    import subprocess

    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
    os.makedirs(static_dir, exist_ok=True)
    
    chemin_destination = os.path.join(static_dir, "wave_audio_temp.wav")

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i", fichier_audio,
            "-acodec", "pcm_s16le",
            "-ac", "1",
            "-ar", "44100",
            "-f", "wav",
            chemin_destination
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        print(f"✅ Audio converti avec succès : {chemin_destination}")
        return "/static/wave_audio_temp.wav"

    except Exception as e:
        st.error(f"Erreur conversion audio : {e}")
        return ""


def purge_dossiers_temp_static():
    """Supprime les fichiers audio temporaires dans /data/temp/ et /app/public/audio_temp.wav"""
    # Purge /data/temp
    temp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "temp"))
    if os.path.exists(temp_dir):
        for nom_fichier in os.listdir(temp_dir):
            chemin = os.path.join(temp_dir, nom_fichier)
            if os.path.isfile(chemin) and (nom_fichier.endswith(".wav") or nom_fichier.endswith(".mp3")):
                os.remove(chemin)

def convertir_hms_en_secondes(hms: str) -> float:
    """Convertit une chaîne HH:MM:SS en secondes float"""
    try:
        h, m, s = map(int, hms.strip().split(':'))
        return h * 3600 + m * 60 + s
    except Exception:
        return 0.0
    



def copier_audio_temp(path_source):
    extension = os.path.splitext(path_source)[1].lower()
    nom_fichier_temp = f"audio_temp{extension}"
    
    # destination 1 : data/temp/
    chemin_temp = os.path.join("data", "temp", f"wave_audio_temp{extension}")
    shutil.copy2(path_source, chemin_temp)

    # destination 2 : app/static/
    chemin_static = os.path.join("app", "static", nom_fichier_temp)
    shutil.copy2(path_source, chemin_static)
    st.info(f"✅ Fichier audio exposé pour navigateur : /static/{os.path.basename(chemin_static)}")

    return chemin_temp

def purge_temp_audio():
    """Purge les fichiers audio temporaires au lancement de la phase 2."""
    dossier_temp = os.path.join("data", "temp")
    if os.path.exists(dossier_temp):
        for f in os.listdir(dossier_temp):
            if f.endswith(".wav") or f.endswith(".mp3"):
                try:
                    os.remove(os.path.join(dossier_temp, f))
                    print(f"🧹 Supprimé : {f}")
                except Exception as e:
                    print(f"⚠️ Impossible de supprimer {f} : {e}")

def convertir_secondes_en_hms(sec: float) -> str:
    """Inverse de convertir_hms_en_secondes : 3723.5 -> '01:02:03.500'"""
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h*3600 - m*60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

def get_audio_duration(path: str) -> float:
    """Retourne la durée (s) du fichier audio via soundfile."""
    return float(sf.info(path).duration)

def charger_photos(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Fichier introuvable: {p}")
    if p.suffix.lower() == ".xlsx":
        df = pd.read_excel(p, engine="openpyxl")
        df, changed = migrate_photo_dataframe_paths(df)
        if changed:
            sauver_photos(df, str(p))
        return df

    last_err = None
    for enc in ("utf-8-sig", "cp1252", "latin1"):
        try:
            df = pd.read_csv(p, sep=";", encoding=enc)
            df, changed = migrate_photo_dataframe_paths(df)
            if changed:
                sauver_photos(df, str(p))
            return df
        except UnicodeDecodeError as e:
            last_err = e
    raise last_err or RuntimeError(f"Impossible de lire le CSV : {p}")

def sauver_photos(df: pd.DataFrame, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() == ".xlsx":
        df.to_excel(p, index=False, engine="openpyxl")
    else:
        df.to_csv(p, sep=";", index=False, encoding="utf-8-sig")

def charger_photos_ui(infos: dict) -> pd.DataFrame:
    return charger_photos(infos["fichier_photos"])

def charger_photos_batch(infos: dict) -> pd.DataFrame:
    p = (infos.get("fichier_photos_batch") or "").strip()
    if not p or not os.path.exists(p):
        return pd.DataFrame()
    return charger_photos(p)


def charger_transcription_flexible(path: str, audio0_dt=None) -> pd.DataFrame:
    """
    Charge un CSV de transcription dans l'un des formats suivants :

    1) Format 'horodatage' :
       - colonne 'horodatage' (HH:MM:SS ou JJ/MM/AAAA HH:MM:SS)
       - colonne 'texte' ou 'text' (ou équivalent)
       -> si audio0_dt est fourni : 'temps' = (horodatage - audio0_dt) en secondes (base t=0 wav)
       -> sinon : 'temps' = secondes depuis minuit (fallback, moins fiable)

    2) Format ASR (secondes) :
       - colonnes 'start', 'end', 'text' (et éventuellement 'speaker')
       -> 'temps' = start (float), 'texte' = text

    Retourne toujours un DataFrame avec au moins :
        - 'temps' (float)
        - 'texte' (str)
    """
    p = Path(path)

    # Lecture robuste : essayer ; puis ,
    df = pd.read_csv(p, sep=";", encoding="utf-8-sig")
    cols = {c.lower(): c for c in df.columns}

    if "start" not in cols and "horodatage" not in cols:
        df = pd.read_csv(p, sep=",", encoding="utf-8-sig")
        cols = {c.lower(): c for c in df.columns}

    # ---- Cas ASR : start/text en secondes ----
    if "start" in cols and "text" in cols:
        start_col = cols["start"]
        text_col  = cols["text"]
        df["temps"] = pd.to_numeric(df[start_col], errors="coerce")
        df["texte"] = df[text_col].astype(str)
        return df

    # ---- Cas horodatage ----
    if "horodatage" in cols:
        horo_col = cols["horodatage"]

        # colonne texte
        if "texte" in cols:
            text_col = cols["texte"]
        elif "text" in cols:
            text_col = cols["text"]
        elif "transcription" in cols:
            text_col = cols["transcription"]
        else:
            raise ValueError(
                f"Impossible de trouver une colonne texte dans {path} "
                "(attendu: 'texte', 'text' ou 'transcription')."
            )

        if audio0_dt is not None:
            dt_series = pd.to_datetime(df[horo_col], dayfirst=True, errors="coerce")

            # Si HH:MM:SS, ancrer sur la date de audio0_dt
            mask = dt_series.isna()
            if mask.any():
                hms = df.loc[mask, horo_col].astype(str).str.strip()
                dt_series.loc[mask] = pd.to_datetime(
                    audio0_dt.date().strftime("%d/%m/%Y") + " " + hms,
                    dayfirst=True,
                    errors="coerce",
                )

            df["temps"] = (dt_series - pd.to_datetime(audio0_dt)).dt.total_seconds()
        else:
            df["temps"] = df[horo_col].astype(str).apply(convertir_horodatage_en_secondes)

        df["texte"] = df[text_col].astype(str)
        return df

    raise ValueError(
        f"Format de transcription non reconnu pour {path} : "
        "attendu soit (start,end,text[,speaker]), soit (horodatage, texte)."
    )
