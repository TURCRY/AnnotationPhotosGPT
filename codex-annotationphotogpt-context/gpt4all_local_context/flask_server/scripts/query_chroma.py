# query_chroma.py
# Interroge une collection Chroma avec embeddings Nomic, chemins auto via paths.json.
# - Support --project (CHROMA_BASE/<project>) ou --chroma_dir + --collection
# - Affiche top-k passages + métadonnées (path/filename) + distances

import argparse
from typing import List
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import EmbeddingFunction
from sentence_transformers import SentenceTransformer

from helper_paths import load_paths

PATHS = load_paths()
DEFAULT_CHROMA_BASE = Path(PATHS["CHROMA_BASE"])

class NomicEmbedding(EmbeddingFunction):
    def __init__(self, model_name: str, use_v15: bool):
        self.model = SentenceTransformer(
            model_name,
            trust_remote_code=True if use_v15 else False
        )
    def embed_query(self, text: str) -> List[float]:
        q = f"search_query: {text}"
        return self.model.encode([q], normalize_embeddings=True).tolist()[0]

def main():
    p = argparse.ArgumentParser(description="Query Chroma (Nomic embeddings).")
    # Choix projet OU chemins explicites
    p.add_argument("--project", help="Identifiant projet (CHROMA_BASE/<project>)")
    p.add_argument("--chroma_dir", help="Chemin DB Chroma (si pas --project)")
    p.add_argument("--collection", help="Nom de la collection (si pas --project)")
    # Requête
    p.add_argument("--query", required=True, help="Question utilisateur")
    p.add_argument("--k", type=int, default=5, help="Top-k passages")
    # Modèle Nomic
    p.add_argument("--use_v15", action="store_true", default=True, help="nomic-embed-text-v1.5 (par défaut)")
    p.add_argument("--use_v1",  action="store_true", help="Forcer nomic-embed-text-v1")
    args = p.parse_args()

    use_v15 = args.use_v15 and not args.use_v1
    model_name = "nomic-ai/nomic-embed-text-v1.5" if use_v15 else "nomic-ai/nomic-embed-text-v1"

    if args.project:
        project = args.project
        chroma_dir = DEFAULT_CHROMA_BASE / project
        collection = project
    else:
        if not args.collection:
            raise SystemExit("❌ Spécifie --project ou --collection")
        chroma_dir = Path(args.chroma_dir) if args.chroma_dir else DEFAULT_CHROMA_BASE
        collection = args.collection

    client = chromadb.PersistentClient(path=str(chroma_dir))
    coll = client.get_or_create_collection(
        name=collection,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None  # on fournit l'embedding de la requête
    )

    embedder = NomicEmbedding(model_name, use_v15)
    qvec = embedder.embed_query(args.query)

    res = coll.query(
        query_embeddings=[qvec],
        n_results=args.k,
        include=["documents", "metadatas", "distances"]
    )

    docs  = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    print(f"\n🔎 Top-{args.k} résultats pour : {args.query}")
    print(f"📚 Base : {chroma_dir} | Collection : {collection}\n")
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        path = meta.get("path", "?")
        fname = meta.get("filename", "?")
        preview = (doc or "").replace("\n", " ")
        if len(preview) > 300:
            preview = preview[:300] + "..."
        print(f"— #{i}  (cosine distance: {dist:.4f})")
        print(f"   {path}  [{fname}]")
        print(f"   {preview}\n")

if __name__ == "__main__":
    main()
