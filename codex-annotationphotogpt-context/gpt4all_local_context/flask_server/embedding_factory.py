# embedding_factory.py
from __future__ import annotations
from typing import Optional, Dict, Any
import logging
from sentence_transformers import SentenceTransformer

log = logging.getLogger("embedding_factory")

# Table des modèles supportés (à enrichir si besoin)
EMBEDDING_MODELS = {
    "Nomic_Embed": {
        "model": "nomic-ai/nomic-embed-text-v1.5",
        "q_prefix": "search_query: ",
        "d_prefix": "search_document: ",
        "normalize": True,
        "dim": 768
    },
    "E5_multilingual_large": {
        "model": "intfloat/multilingual-e5-large",
        "q_prefix": "query: ",
        "d_prefix": "passage: ",
        "normalize": True,
        "dim": 1024
    },
    "BGE": {
        "model": "BAAI/bge-base-en-v1.5",
        "q_prefix": "query: ",
        "d_prefix": "passage: ",
        "normalize": True,
        "dim": 768
    },
    "BGE_3": {
        "model": "BAAI/bge-m3",
        "q_prefix": "query: ",
        "d_prefix": "passage: ",
        "normalize": True,
        "dim": 1024
    },
    "MiniLM_L6_v2": {
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "q_prefix": "",
        "d_prefix": "",
        "normalize": True,
        "dim": 384
    },
    "Jina_2": {
        "model": "jinaai/jina-embeddings-v2-base-fr",
        "q_prefix": "query: ",
        "d_prefix": "passage: ",
        "normalize": True,
        "dim": 768
    },
    "Matryoshka": {
        "model": "Alibaba-NLP/gte-multilingual-base",
        "q_prefix": "search_query: ",
        "d_prefix": "search_document: ",
        "normalize": True,
        "dim": 768
    }
}

# === Classe Factory principale ===
class EmbeddingFactory:
    def __init__(self, default_key: str = "nomic"):
        self.default_key = default_key.lower()
        self.cache: Dict[str, SentenceTransformer] = {}

    def get_config(self, key: Optional[str] = None) -> Dict[str, Any]:
        key = (key or self.default_key).lower()
        if key not in EMBEDDING_MODELS:
            log.warning(f"[EmbeddingFactory] Modèle '{key}' inconnu → fallback '{self.default_key}'")
            key = self.default_key
        return EMBEDDING_MODELS[key]

    def get_model(self, key: Optional[str] = None) -> SentenceTransformer:
        cfg = self.get_config(key)
        model_name = cfg["model"]
        if model_name not in self.cache:
            log.info(f"Chargement embedding model: {model_name}")
            self.cache[model_name] = SentenceTransformer(model_name)
        return self.cache[model_name]

    def embed_query(self, text: str, key: Optional[str] = None) -> list[float]:
        cfg = self.get_config(key)
        model = self.get_model(key)
        prefix = cfg["q_prefix"]
        q = f"{prefix}{text}"
        vec = model.encode([q], normalize_embeddings=cfg["normalize"])
        return vec[0].tolist()

    def embed_documents(self, docs: list[str], key: Optional[str] = None) -> list[list[float]]:
        cfg = self.get_config(key)
        model = self.get_model(key)
        prefix = cfg["d_prefix"]
        docs_prefixed = [f"{prefix}{d}" for d in docs]
        return model.encode(docs_prefixed, normalize_embeddings=cfg["normalize"]).tolist()
