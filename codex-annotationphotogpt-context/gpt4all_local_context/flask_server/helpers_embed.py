# helpers_embed.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Tuple, Callable, Optional
from sentence_transformers import SentenceTransformer

# === CONFIG À ADAPTER SI BESOIN ===
# Racine de tes modèles sur le PC/serveur Flask
MODELS_ROOT = Path(r"C:\GPT4All_Models")  # <-- ajuste à ton arbo locale
MODELS_INDEX_PATH = MODELS_ROOT / "models_index.json"

# Charge l'index une seule fois
with open(MODELS_INDEX_PATH, "r", encoding="utf-8") as f:
    _MODELS_INDEX: Dict[str, Any] = json.load(f)

# Construire un mapping insensible à la casse
_INDEX_CI = {k.lower(): (k, v) for k, v in _MODELS_INDEX.items()}

# Petits utilitaires
def _is_embedding(entry: Dict[str, Any]) -> bool:
    return (entry.get("type") or "").lower() == "embedding"

def _resolve_entry(name: str) -> Tuple[str, Dict[str, Any]]:
    key_ci = (name or "").strip().lower()
    if key_ci not in _INDEX_CI:
        raise KeyError(f"Modèle inconnu dans models_index.json: {name!r}")
    orig_key, entry = _INDEX_CI[key_ci]
    if not _is_embedding(entry):
        raise ValueError(f"{orig_key} n'est pas de type 'embedding' (type={entry.get('type')})")
    return orig_key, entry

def _local_dir(entry: Dict[str, Any]) -> Optional[Path]:
    # Certaines entrées ont directory="Embeddings/XXX" (chemin relatif)
    rel = entry.get("directory")
    if not rel:
        return None
    p = MODELS_ROOT / rel
    return p if p.is_dir() else None

def _hf_id(entry: Dict[str, Any]) -> Optional[str]:
    man = entry.get("manifest") or {}
    mid = man.get("model_id")
    # Corriger Nomic s'il manque le préfixe "nomic-ai/"
    if isinstance(mid, str) and mid.startswith("nomic-embed-text-"):
        mid = "nomic-ai/" + mid
    return mid

def _needs_trust(model_id: str) -> bool:
    # Nomic/BGE peuvent nécessiter trust_remote_code
    return model_id.startswith(("nomic-ai/", "BAAI/"))

def get_embed_info(name: str) -> Dict[str, Any]:
    orig_key, entry = _resolve_entry(name)
    local = _local_dir(entry)
    mid = _hf_id(entry)
    backend = (entry.get("manifest") or {}).get("backend") or entry.get("backend")
    info = {
        "alias": orig_key,
        "backend": backend,
        "local_dir": str(local) if local else None,
        "model_id": mid,
        "source": (entry.get("manifest") or {}).get("source"),
        "dims": (entry.get("manifest") or {}).get("dims"),
    }
    return info

# --- API principale : retourne TOUJOURS un objet .encode(...) ---
def load_embedder(name: str) -> SentenceTransformer:
    """
    Retourne un SentenceTransformer prêt (objet avec .encode).
    name: clé telle que présente dans models_index.json (p.ex. 'BGE_M3', 'E5_Multilingual_Large', 'MiniLM_L6_v2', 'Nomic_Embed').
    """
    info = get_embed_info(name)
    # Choix du chemin/local vs HF
    model_path_or_id: Optional[str] = None
    if info["local_dir"]:
        model_path_or_id = info["local_dir"]
    elif info["model_id"]:
        model_path_or_id = info["model_id"]
    else:
        raise RuntimeError(f"Impossible de résoudre un modèle pour {name!r} (ni local ni HF).")

    trust = _needs_trust(str(model_path_or_id))
    # Nomic_Embed: l'index indique v1.5 -> trust recommandé
    model = SentenceTransformer(model_path_or_id, trust_remote_code=trust)
    return model

# --- Compatibilité: retourner une fonction + info, si des appels en ont besoin ---
def load_embedder_fn(name: str) -> Tuple[Callable[[list[str]], list[list[float]]], Dict[str, Any]]:
    model = load_embedder(name)
    info = get_embed_info(name)

    def embed_fn(texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return model.encode(texts, normalize_embeddings=True).tolist()

    return embed_fn, info
