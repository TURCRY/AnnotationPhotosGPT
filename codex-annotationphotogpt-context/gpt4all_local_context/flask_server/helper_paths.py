# helper_paths.py
from pathlib import Path
import json, os
import chromadb
from chromadb.config import Settings
from chromadb import HttpClient
from qdrant_client import QdrantClient


_DEFAULTS = {
    "AFFAIRES_ROOT": r"C:\Affaires",
    "APP_CONFIG_PATH": r"D:\GPT4All_Local\config\config.json",
    "SYSTEM_PROMPT_PATH": r"D:\GPT4All_Local\config\system_prompt.json",
    "APP_LOG_DIR": r"D:\GPT4All_Local\logs",
    "LOG_DIR": r"D:\GPT4All_Local\logs",
    "MODELS_PATH": r"C:\GPT4All_Models",



    # --- GLOBAL / TYPE 2 (OpenWebUI, AppFlowy, etc.) ---
    "RAG_BASE": r"C:\Dossier_RAG",                        # <- ton souhait
    # ChromaDB
    "CHROMA_BASE_CENTRAL": r"C:\Dossier_RAG\Chroma_Central",
    "CHROMA_BASE": r"C:\Chroma_DB",
    # vectordb (réseau local Windows)
    "CHROMA_HOST": "172.18.94.101",
    "CHROMA_PORT": "8800",


    # Qdrant
    "QDRANT_URL": "http://172.18.94.101:6333",
    "QDRANT_DATA_DIR": r"C:\Dossier_RAG\Qdrant\storage",
    "QDRANT_HOST": "172.18.94.101",
    # vectordb (réseau local Windows)
    "QDRANT_PORT": "6333",
    "QDRANT_GRPC": "6334",

    # --- PAR AFFAIRE / TYPE 1 (persistant local par dossier) ---
    "AFFAIRE_CSV_SUBDIR":       r"AD_Expert_Traitements\_CSV_RAG",
    "AFFAIRE_CHROMA_SUBDIR":    r"AD_Expert_Traitements\_Vec_Chroma",
    "AFFAIRE_EXPORTS_SUBDIR":   r"AD_Expert_Traitements\_Vec_Exports",
    "AFFAIRE_MANIFESTS_SUBDIR": r"AD_Expert_Traitements\_Vec_Manifests",


}

# 1) Fichier forcé par ENV (utile NAS/containers)
_FORCE_FILE = os.getenv("APP_PATHS_FILE")

# 2) Candidats (ordre de recherche)
_CANDIDATES = [
    Path("paths.json"),
    Path(r"D:\GPT4All_Local\config\paths.json"),
    Path(r"C:\LLM_Assistant\config\paths.json"),
]
#============================================================

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _apply_env_overrides(paths: dict) -> dict:
    # Permet d’overrider chaque clé par une variable d’env du même nom
    out = dict(paths)
    for k in _DEFAULTS.keys():
        v = os.getenv(k)
        if v: out[k] = v
    return out

def _normalize(paths: dict) -> dict:
    out = {}

    # Ces clés NE SONT PAS des chemins de fichiers, on ne les passe pas à Path.resolve()
    SKIP_NORMALIZE = {
        "CHROMA_HOST",
        "CHROMA_PORT",
        "QDRANT_HOST",
        "QDRANT_PORT",
        "QDRANT_GRPC",
        "QDRANT_URL",
    }

    for k, v in paths.items():
        if k in SKIP_NORMALIZE:
            out[k] = v
            continue
        try:
            # garde les UNC \\... valides ; Path().resolve() fonctionne aussi
            out[k] = str(Path(v).resolve())
        except Exception:
            out[k] = v
    return out


def load_paths() -> dict:
    # base = defaults
    conf = dict(_DEFAULTS)

    # fichier forcé (si défini et existant)
    if _FORCE_FILE:
        p = Path(_FORCE_FILE)
        if p.exists():
            conf.update(_read_json(p))

    # sinon, premier paths.json existant parmi _CANDIDATES
    if not _FORCE_FILE:
        for p in _CANDIDATES:
            if p.exists():
                conf.update(_read_json(p))
                break

    # variables d’environnement en dernier (plus haute priorité)
    conf = _apply_env_overrides(conf)

    # --- ajout pour compatibilité LOG_DIR <-> APP_LOG_DIR ---
    if "LOG_DIR" not in conf and "APP_LOG_DIR" in conf:
        conf["LOG_DIR"] = conf["APP_LOG_DIR"]

    # normalise les chemins
    return _normalize(conf)

def debug_paths_snapshot(paths: dict) -> dict:
    # petit utilitaire pour /ping ou un endpoint debug
    return {k: paths.get(k) for k in sorted(paths.keys())}

PATHS = load_paths()

#==========================================================
# --- CHROMA en REST (chromadb 1.2.x)
#==========================================================

# 1) Charger PATHS une fois pour toutes
try:
    PATHS = load_paths()
except Exception as e:
    print(f"[WARN] Impossible de charger paths.json, utilisation des DEFAULTS : {e!r}")
    PATHS = dict(_DEFAULTS)

def _safe_int(value, default: int) -> int:
    """
    Convertit en int, sinon log un warning et renvoie default.
    Utile si une variable d'env est polluée (ex: 'D:\\...\\8800').
    """
    try:
        return int(str(value))
    except Exception:
        print(f"[WARN] valeur de port invalide {value!r}, fallback {default}")
        return default


# --- CHROMA en REST (chromadb 1.2.x) ---
# On force l'utilisation de 127.0.0.1 pour éviter les soucis type "PC-Fixe"
# qui donnent des "Empty reply from server".


# ---------------- CHROMA ----------------

CHROMA_HOST = os.getenv("CHROMA_HOST") or PATHS.get("CHROMA_HOST", "172.18.94.101")
CHROMA_PORT = _safe_int(
    os.getenv("CHROMA_PORT") or PATHS.get("CHROMA_PORT", "8800"),
    8800,
)

try:
    chroma_client = HttpClient(
        host=CHROMA_HOST,
        port=CHROMA_PORT,
    )
    print(f"[INFO] Chroma REST détecté sur {CHROMA_HOST}:{CHROMA_PORT}")
except Exception as e:
    print(f"[WARN] Chroma REST indisponible ({CHROMA_HOST}:{CHROMA_PORT}) : {e!r}")
    chroma_client = None



# --- QDRANT (HTTP)

QDRANT_HOST = os.getenv("QDRANT_HOST") or PATHS.get("QDRANT_HOST", "172.18.94.101")
QDRANT_PORT = _safe_int(
    os.getenv("QDRANT_PORT") or PATHS.get("QDRANT_PORT", "6333"),
    6333,
)

try:
    qdrant = QdrantClient(
        host=QDRANT_HOST,
        port=QDRANT_PORT,
        https=False,
    )
    print(f"[INFO] Qdrant REST détecté sur {QDRANT_HOST}:{QDRANT_PORT}")
except Exception as e:
    print(f"[WARN] Qdrant REST indisponible ({QDRANT_HOST}:{QDRANT_PORT}) : {e!r}")
    qdrant = None

