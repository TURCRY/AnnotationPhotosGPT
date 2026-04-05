# export_to_chroma.py
# Indexe un dossier RAG dans une base Chroma en lisant automatiquement les chemins depuis paths.json.
# - Utilise Nomic Embed (v1.5 par défaut) via sentence-transformers
# - Résolution automatique des chemins via helper_paths.load_paths()
# - Support --project (RAG_BASE/<project> ; CHROMA_BASE/<project>) ou chemins explicites

import argparse
import uuid
from pathlib import Path
from typing import List

import chromadb
from chromadb.utils.embedding_functions import EmbeddingFunction
from sentence_transformers import SentenceTransformer

from helper_paths import load_paths
from rag_utils import extraire_blocs_rag

# ========= Config par défaut via paths.json =========
PATHS = load_paths()
DEFAULT_CHROMA_BASE = Path(PATHS["CHROMA_BASE"])
DEFAULT_RAG_BASE    = Path(PATHS["RAG_BASE"])

# ========= Embeddings Nomic =========
class NomicEmbedding(EmbeddingFunction):
    def __init__(self, model_name: str, use_v15: bool):
        # v1.5 -> trust_remote_code=True (nécessite 'einops')
        self.model = SentenceTransformer(
            model_name,
            trust_remote_code=True if use_v15 else False
        )

    def __call__(self, inputs: List[str]) -> List[List[float]]:
        docs = [f"search_document: {t}" for t in inputs]
        vecs = self.model.encode(docs, normalize_embeddings=True)
        return vecs.tolist()

# ========= Anonymisation simple (RGPD) =========
import re
def anonymize_text(t: str) -> str:
    t = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[EMAIL]', t)
    t = re.sub(r'\b(?:\+33|0)\s?[1-9](?:[\s.-]?\d{2}){4}\b', '[TEL]', t)
    t = re.sub(r'\b[12]\s?\d{2}\s?(?:0[1-9]|1[0-2])(?:\s?\d{2}){3}\s?\d{2}\b', '[NIR]', t)
    return t

def main():
    p = argparse.ArgumentParser(description="Export RAG -> Chroma (Nomic Embed).")
    # Choix projet OU chemins explicites
    p.add_argument("--project", help="Identifiant projet (utilise RAG_BASE/<project> & CHROMA_BASE/<project>)")
    p.add_argument("--rag_dir", help="Chemin dossier RAG (si pas --project)")
    p.add_argument("--chroma_dir", help="Chemin DB Chroma (si pas --project)")
    p.add_argument("--collection", help="Nom de collection Chroma (défaut = nom du projet ou nom du dossier)")
    # Qualité embeddings
    p.add_argument("--use_v15", action="store_true", default=True, help="Utiliser nomic-embed-text-v1.5 (par défaut)")
    p.add_argument("--use_v1",  action="store_true", help="Forcer nomic-embed-text-v1 (sans code dynamique)")
    # Options RAG
    p.add_argument("--anonymize", action="store_true", help="Anonymiser textes avant indexation (RGPD)")
    p.add_argument("--batch", type=int, default=64, help="Taille de lot pour l'ingestion")
    args = p.parse_args()

    # Résolution modèle
    use_v15 = args.use_v15 and not args.use_v1
    model_name = "nomic-ai/nomic-embed-text-v1.5" if use_v15 else "nomic-ai/nomic-embed-text-v1"

    # Résolution chemins
    if args.project:
        project   = args.project
        rag_dir   = DEFAULT_RAG_BASE / project
        chroma_dir = (DEFAULT_CHROMA_BASE / project)
        collection = args.collection or project
    else:
        if not args.rag_dir:
            raise SystemExit("❌ Spécifie --project ou --rag_dir")
        rag_dir = Path(args.rag_dir)
        chroma_dir = Path(args.chroma_dir) if args.chroma_dir else DEFAULT_CHROMA_BASE
        collection = args.collection or (rag_dir.name)

    if not rag_dir.exists():
        raise SystemExit(f"❌ Dossier RAG introuvable: {rag_dir}")

    blocs = extraire_blocs_rag(str(rag_dir))
    if not blocs:
        raise SystemExit("⚠️ Aucun bloc lisible trouvé, abandon.")

    client = chromadb.PersistentClient(path=str(chroma_dir))
    coll = client.get_or_create_collection(
        name=collection,
        metadata={"hnsw:space": "cosine"},
        embedding_function=NomicEmbedding(model_name, use_v15)
    )

    ids, metas, docs = [], [], []
    total = len(blocs)
    print(f"⏳ Indexation {total} blocs -> {collection} @ {chroma_dir}")

    for i, b in enumerate(blocs, 1):
        text = b["content"] or ""
        if args.anonymize:
            text = anonymize_text(text)

        ids.append(str(uuid.uuid4()))
        metas.append({"filename": b["filename"], "path": b["relative_path"], "source": "RAG"})
        docs.append(text)

        if len(ids) >= args.batch or i == total:
            coll.add(ids=ids, metadatas=metas, documents=docs)
            print(f"✅ Ajout {len(ids)} (total {i}/{total})")
            ids, metas, docs = [], [], []

    print(f"🎉 Terminé : collection='{collection}', base='{chroma_dir}'")

if __name__ == "__main__":
    main()
