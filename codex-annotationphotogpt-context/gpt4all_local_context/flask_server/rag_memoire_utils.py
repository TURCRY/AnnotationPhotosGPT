from __future__ import annotations

import os, json, uuid, logging, re
from typing import List, Callable
from pathlib import Path
import requests

from chromadb import PersistentClient
from chromadb.utils import embedding_functions

from helper_paths import load_paths, chroma_client as _chroma_client

# =========================
# PATHS & config de base
# =========================

try:
    PATHS = load_paths()
except Exception:
    PATHS = {}

def _as_int(value, default: int) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except Exception:
        m = re.search(r'(\d{2,5})\s*$', str(value))
        return int(m.group(1)) if m else default

def build_memory_append(messages: list[dict], n_turns: int = 6) -> str:
    """
    Construit une mémoire glissante sur N tours (USER+ASSISTANT).
    - n_turns=6 => ~6 paires Q/R max
    - Prend uniquement les messages user/assistant.
    """
    if not messages:
        return ""

    ua = [m for m in messages if m.get("role") in ("user", "assistant")]

    keep = max(2, int(n_turns) * 2)
    ua = ua[-keep:]

    lines = []
    for m in ua:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"USER: {content}")
        else:
            lines.append(f"ASSISTANT: {content}")

    return "\n".join(lines).strip()


# ---------------- Chroma config ----------------

CHROMA_MODE = os.getenv("CHROMA_MODE", "rest").lower()  # "rest" | "local"

CHROMA_BASE = os.getenv("CHROMA_BASE", PATHS.get("CHROMA_BASE", r"C:\Chroma_DB"))
CHROMA_MEM_PATH = Path(CHROMA_BASE) / "_memoire"
CHROMA_MEM_PATH.mkdir(parents=True, exist_ok=True)

print(f"[rag_memoire] CHROMA_MODE={CHROMA_MODE!r} CHROMA_BASE={CHROMA_BASE!r}")

# ---------------- Logging ----------------
log = logging.getLogger("rag_memory")
logging.basicConfig(level=logging.INFO)

# --- Config commune (lit ton config.json existant)
DEFAULT_CONFIG_PATH = r"D:\GPT4All_Local\flask_server\config\config.json"
CONFIG_PATH = Path(os.getenv("APP_CONFIG_PATH", DEFAULT_CONFIG_PATH))
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
DEFAULT_EMBED_MODEL = CONFIG.get("default_embed", "BGE_M3")

# =========================
# Client Chroma LAZY
# =========================

def _get_chroma_client():
    """
    Renvoie un client Chroma utilisable.
    - En mode 'rest' : réutilise helper_paths.chroma_client
    - En mode 'local': PersistentClient sur CHROMA_MEM_PATH
    Ne fait AUCUN appel réseau à l'import du module.
    """
    if CHROMA_MODE == "local":
        # Mode purement local sur disque, sans passer par Docker
        return PersistentClient(path=str(CHROMA_MEM_PATH))

    # Mode REST (Docker)
    if _chroma_client is None:
        raise RuntimeError(
            "Chroma REST indisponible (helper_paths.chroma_client est None). "
            "Les fonctions de mémoire RAG ne sont pas utilisables tant que Chroma n'est pas prêt."
        )
    return _chroma_client

# ⚠️ IMPORTANT :
# PAS de `client = _get_chroma_client()` ici.
# On ne touche Chroma que lorsqu'une fonction RAG est réellement appelée.


# =========================
# Embeddings
# =========================

LOCAL_EMBED_HTTP   = os.getenv("LOCAL_EMBED_HTTP", "1").lower() not in ("0", "false", "no")
LOCAL_API_KEY      = os.getenv("LOCAL_API_KEY", "")
HF_FALLBACK_MODEL  = os.getenv("HUGGINGFACE_EMBED_MODEL", "intfloat/multilingual-e5-base")
_EMBED_FN = None

embed_http = ((CONFIG.get("embedding") or {}).get("http_endpoint") or "").strip()
if embed_http:
    # ex: "http://127.0.0.1:5050/embeddings"
    if embed_http.endswith("/embeddings"):
        LOCAL_BASE = embed_http[:-len("/embeddings")].rstrip("/")
        LOCAL_EMBED_PATH = "/embeddings"
    else:
        LOCAL_BASE = embed_http.rstrip("/")
        LOCAL_EMBED_PATH = "/embeddings"
else:
    LOCAL_BASE = os.getenv("LOCAL_BASE", "http://127.0.0.1:5050").rstrip("/")
    LOCAL_EMBED_PATH = os.getenv("LOCAL_EMBED_PATH", "/embeddings")

log.info(
    "Embeddings: mode=%s endpoint=%s%s model=%s",
    "http" if LOCAL_EMBED_HTTP else "hf",
    LOCAL_BASE,
    LOCAL_EMBED_PATH,
    DEFAULT_EMBED_MODEL
)

def _get_embed_fn():
    global _EMBED_FN
    if _EMBED_FN is None:
        _EMBED_FN = _build_embedder()
    return _EMBED_FN

def _direct_embedder(model: str) -> Callable[[List[str]], List[List[float]]]:
    def _emb(texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # Import tardif pour éviter une boucle d'import au chargement
        import gpt4all_flask as gf

        embedder = gf._get_embedder(model)
        if not hasattr(embedder, "encode"):
            raise TypeError(f"Embedder invalide pour {model}: {type(embedder)}")

        vecs = embedder.encode(
            texts,
            normalize_embeddings=True,
            batch_size=32,
        )

        # SentenceTransformer renvoie en général un numpy array
        return vecs.tolist() if hasattr(vecs, "tolist") else vecs

    return _emb


def _http_embedder(model: str) -> Callable[[List[str]], List[List[float]]]:
    url = f"{LOCAL_BASE}{LOCAL_EMBED_PATH}"
    headers = {"Content-Type": "application/json"}
    if LOCAL_API_KEY:
        headers["x-api-key"] = LOCAL_API_KEY

    def _emb(texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        r = requests.post(
            url,
            json={"texts": texts, "model": model},
            headers=headers,
            timeout=60
        )
        r.raise_for_status()
        embs = (r.json() or {}).get("embeddings")
        if not isinstance(embs, list):
            raise RuntimeError("Réponse embeddings inattendue")
        return embs

    return _emb


def _hf_embedder(model: str) -> Callable[[List[str]], List[List[float]]]:
    st = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model)
    return lambda texts: st(texts)


def _build_embedder() -> Callable[[List[str]], List[List[float]]]:
    # 1) appel Python direct dans le même processus
    try:
        return _direct_embedder(DEFAULT_EMBED_MODEL)
    except Exception as e:
        log.warning("Embedder direct indisponible (%s)", e)

    # 2) secours HTTP local
    if LOCAL_EMBED_HTTP:
        try:
            return _http_embedder(DEFAULT_EMBED_MODEL)
        except Exception as e:
            log.warning(
                "Embeddings HTTP local indispo (%s) → fallback HF %s",
                e, HF_FALLBACK_MODEL
            )

    # 3) fallback HF
    return _hf_embedder(HF_FALLBACK_MODEL)



# =========================
# Fonctions utilitaires Chroma
# =========================

def _get_mem_collection(name: str):
    client = _get_chroma_client()
    # pas d'embedding côté serveur HTTP : on envoie toujours des embeddings explicites si besoin
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )


def _coll(name: str):
    client = _get_chroma_client()
    return client.get_or_create_collection(name=name)


# =========================
# API publique
# =========================

def add_docs(collection: str, docs: List[str]) -> int:
    if not docs:
        return 0
    vecs = _get_embed_fn()(docs)
    ids = [f"doc_{uuid.uuid4().hex[:12]}" for _ in docs]
    _coll(collection).add(ids=ids, documents=docs, embeddings=vecs)
    return len(docs)

def query_docs(collection: str, query: str, top_k: int) -> List[str]:
    qvec = _get_embed_fn()([query])[0]
    res = _coll(collection).query(query_embeddings=[qvec], n_results=int(top_k or 4))
    docs = res.get("documents", [[]])
    return docs[0] if docs else []



def build_context(collection: str, documents: List[str], query: str, top_k: int = 4) -> str:
    """
    Construit un contexte de mémoire RAG.
    Si Chroma n'est pas disponible, on journalise et on renvoie une chaîne vide
    (pour ne pas faire tomber tout le serveur).
    """
    try:
        if documents:
            add_docs(collection, documents)
        hits = query_docs(collection, query, top_k)
        return "\n\n".join(hits)
    except RuntimeError as e:
        log.warning("Mémoire RAG désactivée : %s", e)
        return ""
    except Exception as e:
        log.error("Erreur inattendue RAG mémoire : %s", e, exc_info=True)
        return ""
