from __future__ import annotations
import os, json, uuid, logging, csv
from typing import List, Callable, Dict, Any, Optional, Tuple, Literal
from pathlib import Path
from datetime import datetime
from helpers_embed import load_embedder
import requests
import chromadb
from chromadb import PersistentClient  # client local (disque)
from chromadb.config import Settings
from chromadb.api.types import EmbeddingFunction  # pour typer la classe custom
from sentence_transformers import SentenceTransformer

from chromadb import Client
from chromadb.utils import embedding_functions
from chromadb import HttpClient
from qdrant_client import QdrantClient
from uuid import uuid4
from hashlib import sha256
from qdrant_client.http.models import Distance, VectorParams
try:
    from qdrant_client.http.models import PointStruct, Filter, FieldCondition, MatchValue
    _HAS_QDRANT = True
except Exception:
    _HAS_QDRANT = False

from collections import Counter

# --- load_paths: import + fallback ---
try:
    # si helper_paths.py est présent sur cette machine
    from helper_paths import load_paths
except Exception:
    # fallback si helper_paths.py n'est pas dispo (ex: autre machine/conteneur)
    def load_paths() -> dict:
        return {
            "CHROMA_HOST": os.getenv("CHROMA_HOST", "localhost"),
            "CHROMA_PORT": int(os.getenv("CHROMA_PORT", "8800")),
            "CHROMA_BASE": os.getenv("CHROMA_BASE", r"C:\Chroma_DB"),
            "QDRANT_URL": os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            "QDRANT_API_KEY": os.getenv("QDRANT_API_KEY", None),
            "AFFAIRES_ROOT": os.getenv("AFFAIRES_ROOT", r"C:\Affaires"),
            "LOG_DIR": os.getenv("APP_LOG_DIR", "./logs"),
        }
PATHS = load_paths()

DEFAULT_CONFIG_PATH = r"D:\GPT4All_Local\config\config.json"
CONFIG_PATH = Path(
    PATHS.get("APP_CONFIG_PATH")
    or os.getenv("APP_CONFIG_PATH")
    or DEFAULT_CONFIG_PATH
).resolve()

# CHROMADB (priorité PATHS, puis ENV, puis fallback)
DEFAULT_CHROMA_BASE = PATHS.get("CHROMA_BASE") or os.getenv("CHROMA_BASE", r"C:\Chroma_DB")
CHROMA_HOST = os.getenv("CHROMA_HOST") or PATHS.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT") or PATHS.get("CHROMA_PORT", "8800"))
CHROMA_URL  = os.getenv("CHROMA_URL", f"http://{CHROMA_HOST}:{CHROMA_PORT}")
CHROMA_MODE = os.getenv("CHROMA_MODE", "rest").lower()  # "rest" (docker) / "local" (disque)
CHROMA_REST_HOST   = CHROMA_HOST
CHROMA_REST_PORT   = CHROMA_PORT
ChromaMode = Literal["local", "rest"]

# QDRANT
QDRANT_URL = os.getenv("QDRANT_URL") or PATHS.get("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or PATHS.get("QDRANT_API_KEY") or None


# === Choix du modèle (env > constante) ===
# - v1.5 = meilleure qualité (nécessite trust_remote_code=True + einops)
# - v1   = standard (sans code dynamique)
ENV_USE_V15 = os.getenv("NOMIC_USE_V15", "1").strip()  # "1" par défaut
USE_NOMIC_V15_DEFAULT = ENV_USE_V15 not in ("0", "false", "False", "no", "No")


def get_qdrant():
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)



log = logging.getLogger("rag_vector")
logging.basicConfig(level=logging.INFO)

# =========================
# Chargement config globale (même que le Flask)
# =========================

if CONFIG_PATH.exists():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
else:
    log.warning("CONFIG_PATH introuvable: %s — fallback valeurs par défaut", CONFIG_PATH)
    CONFIG = {}

DEFAULT_EMBED_MODEL = CONFIG.get("default_embed", "BGE_M3")
AFFAIRES_ROOT = os.getenv("AFFAIRES_ROOT") or PATHS.get("AFFAIRES_ROOT", r"C:\Affaires")


FILTER_KEYS = {"source_id", "doc_type", "party_origin", "piece_ref", "version_label"}


# défauts (env ou fallback)

def get_chroma_collection(
    collection_name: str,
    chroma_mode: ChromaMode = CHROMA_MODE,
    chroma_dir: Optional[str] = None,
    affaire_id: Optional[str] = None,
    affaires_root: Optional[str] = None,
    rest_host: Optional[str] = None,
    rest_port: Optional[int] = None,
):
    if chroma_mode == "local":
        base = affaires_root or AFFAIRES_ROOT
        if affaire_id:
            db_path = os.path.join(base, affaire_id, ".chroma")
        else:
            db_path = chroma_dir or DEFAULT_CHROMA_BASE

        client = chromadb.PersistentClient(path=db_path)
        return client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )

    # REST
    host = rest_host or CHROMA_HOST
    port = int(rest_port or CHROMA_PORT)
    client = HttpClient(host=host, port=port)
    return client.get_or_create_collection(name=collection_name)



# Pseudonymisation 

try:
    from pseudonymizer import load_registry, save_registry, _load_secret_key, pseudonymize_text
except Exception:
    # fallback no-op si le module n'est pas présent
    def load_registry(): return {}
    def save_registry(_): pass
    def _load_secret_key(): return b""
    def pseudonymize_text(t, *_args, **_kwargs): return t

# --- AJOUTS POUR QDRANT ---






# === Cache global de modèles (éviter rechargements coûteux) ===



# === Embedding wrapper Chroma ===
class NomicEmbedding(EmbeddingFunction):
    """
    EmbeddingFunction pour Chroma. Normalise les embeddings pour cosine.
    On s'appuie sur le cache de modèles ci-dessus.
    """
    def __init__(self, model_name: Optional[str] = None, use_v15: Optional[bool] = None):
        # au lieu de forcer un ID HF spécifique, on résout proprement :
        logical = model_name or DEFAULT_EMBED_MODEL # ou lis depuis config si tu préfères
        self.model_name = logical
        self.model = load_embedder(logical)


    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        docs = [f"search_document: {t}" for t in texts]
        return self.model.encode(docs, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> List[float]:
        q = f"search_query: {text}"
        return self.model.encode([q], normalize_embeddings=True).tolist()[0]
    

# --- Normalisation metadata (filtres robustes) ---
def _norm(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    v = v.lower().replace(".", "")
    return " ".join(v.split())


def build_filters(**kwargs) -> dict:
    f = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        if k not in FILTER_KEYS:
            continue
        f[k] = _norm(v) if k in {"doc_type", "party_origin", "piece_ref", "version_label"} else str(v).strip()
    return f


# === Accès collection Chroma (persistante) ===


# === Ingestion CSV -> vecteurs ===



def retrieve_top_k_with_fallback(
    query: str,
    collection_name: str,
    chroma_dir: Optional[str] = None,
    k: int = 5,
    model_name: Optional[str] = None,
    use_v15: Optional[bool] = None,
    include_distances: bool = True,
    filters: Optional[dict] = None,
    fallback: bool = True,
    chroma_mode: ChromaMode = "local",
    affaire_id: Optional[str] = None,
    affaires_root: Optional[str] = None,
    rest_host: Optional[str] = None,
    rest_port: Optional[int] = None,
) -> Dict:

    # 1️⃣ requête initiale
    res = retrieve_top_k(
        query=query,
        collection_name=collection_name,
        chroma_dir=chroma_dir,
        k=k,
        model_name=model_name,
        use_v15=use_v15,
        include_distances=include_distances,
        filters=filters,
        chroma_mode=chroma_mode,
        affaire_id=affaire_id,
        affaires_root=affaires_root,
        rest_host=rest_host,
        rest_port=rest_port,
    )

    # 2️⃣ mode strict → on ne fallback pas
    if filters or not fallback:
        return res

    metas = res.get("metadatas", [[]])[0]
    if not metas:
        return res

    # 3️⃣ heuristique : doc_type + piece_ref dominants
    dt = Counter(
        [m.get("doc_type") for m in metas if m.get("doc_type")]
    ).most_common(1)

    pr = Counter(
        [m.get("piece_ref") for m in metas if m.get("piece_ref")]
    ).most_common(1)

    ff = {}
    if dt:
        ff["doc_type"] = dt[0][0]
    if pr:
        ff["piece_ref"] = pr[0][0]

    if not ff:
        return res

    # 4️⃣ nouvelle requête filtrée
    return retrieve_top_k(
        query=query,
        collection_name=collection_name,
        chroma_dir=chroma_dir,
        k=k,
        model_name=model_name,
        use_v15=use_v15,
        include_distances=include_distances,
        filters=ff,
        chroma_mode=chroma_mode,
        affaire_id=affaire_id,
        affaires_root=affaires_root,
        rest_host=rest_host,
        rest_port=rest_port,
    )



def upsert_csv_folder_into_chroma(
    csv_dir: str, 
    collection_name: str, 
    chroma_dir: str = None,
    enable_pseudonym: bool = False,
    text_column: str = "text",
    batch_size: int = 64,
    model_name: Optional[str] = None,
    use_v15: Optional[bool] = None,
) -> dict:
    """
    Parcourt un dossier de CSV, crée/upsert les embeddings dans la collection Chroma.
    - enable_pseudonym: si True, applique une pseudonymisation réversible (registre local).
    - text_column: nom de la colonne texte (par défaut 'text').
    - batch_size: taille d'upsert.
    Retourne le nombre d'items upsertés.
    """
    csv_path = Path(csv_dir)
    if not csv_path.exists():
        raise FileNotFoundError(f"csv_dir introuvable: {csv_dir}")
    collection = get_chroma_collection(collection_name=collection_name, chroma_dir=chroma_dir)
    embedder = NomicEmbedding(model_name=model_name, use_v15=use_v15)

    # Pseudonymisation: charge registre AVANT pour détecter ce qui est nouveau
    reg = load_registry()
    key = _load_secret_key()
    before_aliases = set(reg.values())

    upserted = 0
    batch_docs, batch_meta, batch_ids = [], [], []

    seen_by_source = {}  # dict[source_id] -> set(fingerprint)
    for f in csv_path.glob("*.csv"):
        with f.open("r", encoding="utf-8", newline="") as fh:
            # auto-détection séparateur (priorité ; puis ,)
            head = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(head, delimiters=";,")
                delim = dialect.delimiter
            except Exception:
                delim = ";" if ";" in head else ","
            reader = csv.DictReader(fh, delimiter=delim)
            fields = reader.fieldnames or []

            # Détermination de la colonne texte
            tcol = text_column
            if tcol not in fields:
                for alt in ("texte", "Texte", "Text"):
                    if alt in fields:
                        tcol = alt
                        break

            # OCR (page;line;text)
            use_ocr_triplet = (tcol not in fields) and all(x in fields for x in ("page", "line", "text"))


            #----------------------------------------------
            row_idx = 0  # avant la boucle for row

            for row in reader:
                txt = row.get("text", "") if use_ocr_triplet else (row.get(tcol, "") or "")

                # 1) fingerprint sur texte normalisé (avant pseudonymisation)
                norm = " ".join((txt or "").split()).lower()
                fp = sha256(norm.encode("utf-8", errors="ignore")).hexdigest()

                # 2) métadonnées probatoires (avant source_id)

                meta = {
                    "ingest_path": str(f),
                    "filename": f.name,
                    "collection": collection_name,
                    "page": None,
                    "line": None,
                    "doc_type": _norm(row.get("doc_type")),
                    "party_origin": _norm(row.get("party_origin")),
                    "version_label": _norm(row.get("version_label")),
                    "parent_doc_path": row.get("parent_doc_path") or row.get("source_path"),
                    "doc_date": (str(row.get("doc_date")).strip() if row.get("doc_date") else None),
                    "piece_ref": row.get("piece_ref") or row.get("piece_number"),
                    "text_fingerprint": fp,
                }

                # 3) source_id stable (phase 1)
                p = str(meta.get("parent_doc_path") or meta.get("ingest_path") or str(f)).strip()
                source_id = sha256(p.encode("utf-8", errors="ignore")).hexdigest()[:16]
                meta["source_id"] = source_id

                # 4) dédoublonnage strict DANS la source
                sset = seen_by_source.setdefault(source_id, set())
                if fp in sset:
                    continue
                sset.add(fp)

                # 5) pseudonymisation après fingerprint
                if enable_pseudonym:
                    txt = pseudonymize_text(txt, reg, key)

                # 6) ID stable avec fallback page/line
                row_idx += 1
                page = str(row.get("page") or row.get("Page") or row.get("PAGE") or "").strip()
                line = str(row.get("line") or row.get("Line") or row.get("LINE") or "").strip()

                if not page:
                    page = "?"
                if not line:
                    line = str(row_idx)

                item_id = f"{source_id}:{page}:{line}:{fp[:8]}"

                # normalisation meta pour affichage/recherche
                meta["page"] = page
                meta["line"] = line
                meta["embedding_model"] = embedder.model_name
                meta["chunk_id"] = item_id
                meta["piece_ref"] = _norm(row.get("piece_ref") or row.get("piece_number"))



                batch_docs.append(txt)
                batch_meta.append(meta)
                batch_ids.append(item_id)

                if len(batch_docs) >= batch_size:
                    vecs = embedder.embed_documents(batch_docs)
                    collection.upsert(documents=batch_docs, embeddings=vecs,
                                    metadatas=batch_meta, ids=batch_ids)
                    upserted += len(batch_docs)
                    batch_docs, batch_meta, batch_ids = [], [], []

    if batch_docs:
        vecs = embedder.embed_documents(batch_docs)
        collection.upsert(documents=batch_docs, embeddings=vecs, metadatas=batch_meta, ids=batch_ids)
        upserted += len(batch_docs)

    report_path = None
    aliases_created = 0
    if enable_pseudonym:
        # Sauvegarde du registre après enrichissement
        save_registry(reg)
        after_aliases = set(reg.values())
        new_aliases = sorted(list(after_aliases - before_aliases))
        aliases_created = len(new_aliases)
        # Écrit un rapport daté par collection
        try:
            # logs/exports depuis PATHS si dispo, sinon dossier courant
            log_dir = Path(PATHS.get("LOG_DIR", ".")) / "exports"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = log_dir / f"anonymization_{collection_name}_{ts}.json"
            report = {
                "collection": collection_name,
                "csv_dir": str(csv_path),
                "chroma_dir": str(chroma_dir or DEFAULT_CHROMA_BASE),
                "aliases_created": aliases_created,
                "aliases": new_aliases  # ⚠️ pas de noms réels ici (RGPD)
            }
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            report_path = None

    return {
        "upserted": upserted,
        "pseudonymized": bool(enable_pseudonym),
        "aliases_created": aliases_created,
        "report_path": (str(report_path) if report_path else None),
        "collection": collection_name
    }

# === Retrieval top-k brut ===
def retrieve_top_k(
    query: str,
    collection_name: str,
    chroma_dir: Optional[str] = None,
    k: int = 5,
    model_name: Optional[str] = None,
    use_v15: Optional[bool] = None,
    include_distances: bool = True,
    filters: Optional[dict] = None,   # <-- AJOUT
    chroma_mode: ChromaMode = "local",
    affaire_id: Optional[str] = None,
    affaires_root: Optional[str] = None,
    rest_host: Optional[str] = None,
    rest_port: Optional[int] = None,
) -> Dict:
    embedder = NomicEmbedding(model_name=model_name, use_v15=use_v15)
    qvec = embedder.embed_query(query)

    coll = get_chroma_collection(
        collection_name=collection_name,
        chroma_mode=chroma_mode,
        chroma_dir=chroma_dir,
        affaire_id=affaire_id,
        affaires_root=affaires_root,
        rest_host=rest_host,
        rest_port=rest_port,
    )
    include = ["documents", "metadatas"] + (["distances"] if include_distances else [])

    if filters:
        return coll.query(
            query_embeddings=[qvec],
            n_results=max(1, int(k)),
            where=filters,
            include=include,
        )

    return coll.query(
        query_embeddings=[qvec],
        n_results=max(1, int(k)),
        include=include,
    )

# === Sources formatées ===
def retrieve_sources(res: Dict, k: int, with_distances: bool = True) -> List[Dict[str, str]]:
    docs  = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]

    scores = res.get("scores", [[]])[0] if "scores" in res else None
    dists  = res.get("distances", [[]])[0] if "distances" in res else None

    out = []
    for i, (doc, meta) in enumerate(zip(docs, metas), 1):
        meta = meta or {}

        val = None
        metric = None
        if with_distances:
            if scores is not None and i-1 < len(scores):
                val = scores[i-1]
                metric = "similarity"
            elif dists is not None and i-1 < len(dists):
                val = dists[i-1]
                metric = "cosine_dist"

        path = meta.get("parent_doc_path") or meta.get("source_path") or meta.get("ingest_path") or meta.get("path") or "?"
        filename = meta.get("filename") or (Path(path).name if path not in ("?", "") else "?")

        out.append({
            "rank": i,
            "path": path,
            "filename": filename,
            "doc_type": meta.get("doc_type"),
            "piece_ref": meta.get("piece_ref"),
            "page": meta.get("page"),
            "line": meta.get("line"),
            "source_id": meta.get("source_id"),
            "embedding_model": meta.get("embedding_model"),
            "metric": metric,
            "metric_value": (float(val) if val is not None else None),
            "excerpt": (doc or "").strip(),
        })
        if i >= k:
            break
    return out


# === Contexte pour LLM ===
def _truncate_context(text: str, max_chars: Optional[int]) -> str:
    if not max_chars or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n…[TRONQUÉ]…"

def format_passages_for_prompt(
    res: Dict,
    k: int,
    show_distances: bool = False,
    max_total_chars: Optional[int] = None,
    max_excerpt_chars: int = 1200,
) -> str:
    docs  = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]

    scores = res.get("scores", [[]])[0] if "scores" in res else None
    dists  = res.get("distances", [[]])[0] if "distances" in res else None

    blocks = []
    total = 0

    for i, (doc, meta) in enumerate(zip(docs, metas), 1):
        meta = meta or {}
        src = meta.get("parent_doc_path") or meta.get("ingest_path") or "?"
        head = (
            f"### Source #{i} — {meta.get('doc_type','?')} — {src} — "
            f"{meta.get('piece_ref', '?')} — p.{meta.get('page','?')} [{meta.get('filename','?')}]"
        )

        if show_distances:
            if scores is not None and i-1 < len(scores) and scores[i-1] is not None:
                head += f"  (similarity={float(scores[i-1]):.4f})"
            elif dists is not None and i-1 < len(dists) and dists[i-1] is not None:
                head += f"  (cosine_dist={float(dists[i-1]):.4f})"

        excerpt = (doc or "").strip()
        if max_excerpt_chars and len(excerpt) > max_excerpt_chars:
            excerpt = excerpt[:max_excerpt_chars] + "\n…[EXTRAIT TRONQUÉ]…"

        block = f"\n{head}\n{excerpt}\n"

        # ✅ limite globale "safe" : on n'ajoute pas un bloc qui dépasserait
        if max_total_chars and max_total_chars > 0:
            if total + len(block) > max_total_chars:
                break

        blocks.append(block)
        total += len(block)

        if i >= k:
            break

    corpus = "\n".join(blocks).strip()
    if not corpus:
        return ""

    return f"\n\n===== CONTEXTE RAG (Top-{len(blocks)}) =====\n{corpus}\n===== FIN CONTEXTE RAG =====\n"

def build_rag_context(
    query: str,
    collection_name: str,
    chroma_dir: Optional[str] = None,
    k: int = 5,
    show_distances: bool = False,
    filters: Optional[dict] = None,
    max_total_chars: Optional[int] = None,
    model_name: Optional[str] = None,
    use_v15: Optional[bool] = None,
    chroma_mode: ChromaMode = "local",
    affaire_id: Optional[str] = None,
    affaires_root: Optional[str] = None,
    rest_host: Optional[str] = None,
    rest_port: Optional[int] = None,
) -> Tuple[str, List[Dict[str, str]]]:
    res = retrieve_top_k(
        query=query,
        collection_name=collection_name,
        chroma_dir=chroma_dir,
        k=k,
        model_name=model_name,
        use_v15=use_v15,
        include_distances=show_distances,
        filters=filters,
        chroma_mode=chroma_mode,
        affaire_id=affaire_id,
        affaires_root=affaires_root,
        rest_host=rest_host,
        rest_port=rest_port,
    )
    context = format_passages_for_prompt(res=res, k=k, show_distances=show_distances, max_total_chars=max_total_chars)
    sources = retrieve_sources(res, k=k, with_distances=show_distances)
    return context, sources



VecBackend = Literal["chroma", "qdrant"]

def _ensure_qdrant_collection(
    client: "QdrantClient",
    collection_name: str,
    vector_size: int
):
    """
    Vérifie l’existence d’une collection Qdrant ; la crée si elle n’existe pas.
    Ne la recrée jamais automatiquement (préserve les données existantes).
    """
    
    try:
        return client.get_collection(collection_name)

    except Exception as e:
        existing = [c.name for c in client.get_collections().collections]

        if collection_name in existing:
            # collection existe mais get_collection a échoué
            return client.get_collection(collection_name)

        # collection réellement absente → création
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )
        print(f"[Qdrant] Collection '{collection_name}' créée (dim={vector_size})")
        return client.get_collection(collection_name)

def get_vector_store(
    vec_backend: VecBackend,
    collection_name: str,
    chroma_dir: Optional[str] = None,
    qdrant_url: Optional[str] = None,
    qdrant_host: Optional[str] = None,
    qdrant_port: Optional[int] = None,
    qdrant_api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    use_v15: Optional[bool] = None,
) -> Any:
    """
    Retourne un handle de store selon le backend.
    - chroma -> collection Chroma
    - qdrant -> QdrantClient + nom de collection
    """
    if vec_backend == "chroma":
        return get_chroma_collection(collection_name=collection_name, chroma_dir=chroma_dir)

    if vec_backend == "qdrant":
        if not _HAS_QDRANT:
            raise RuntimeError("qdrant-client n'est pas installé (pip install qdrant-client).")

        if qdrant_url:
            client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        else:
            client = QdrantClient(host=qdrant_host or "127.0.0.1",
                                  port=int(qdrant_port or 6333),
                                  api_key=qdrant_api_key)

        probe = NomicEmbedding(model_name=model_name, use_v15=use_v15).embed_query("probe")
        vector_size = len(probe)

        _ensure_qdrant_collection(client, collection_name, vector_size=vector_size)

        info = client.get_collection(collection_name)
        vectors = info.config.params.vectors

        if hasattr(vectors, "size"):
            existing_size = vectors.size
        else:
            existing_size = next(iter(vectors.values())).size

        if existing_size != vector_size:
            raise RuntimeError(
                f"Vector dimension mismatch: collection={existing_size}, model={vector_size}. "
                f"collection={collection_name} model={model_name or DEFAULT_EMBED_MODEL}"
            )

        return (client, collection_name)

    raise ValueError(f"vec_backend inconnu: {vec_backend}")


def upsert_csv_folder_into_store(
    csv_dir: str,
    collection_name: str,
    vec_backend: VecBackend = "chroma",
    chroma_dir: str = None,
    enable_pseudonym: bool = False,
    text_column: str = "text",
    batch_size: int = 64,
    model_name: Optional[str] = None,
    use_v15: Optional[bool] = None,
    qdrant_url: Optional[str] = None,
    qdrant_host: Optional[str] = None,
    qdrant_port: Optional[int] = None,
    qdrant_api_key: Optional[str] = None,
) -> dict:
    """
    Version générique: Chroma ou Qdrant.
    Garde le même retour que la version Chroma.
    """
    csv_path = Path(csv_dir)
    if not csv_path.exists():
        raise FileNotFoundError(f"csv_dir introuvable: {csv_dir}")

    embedder = NomicEmbedding(model_name=model_name, use_v15=use_v15)

    # pseudonymisation: identique à la version Chroma
    reg = load_registry(); key = _load_secret_key(); before_aliases = set(reg.values())

    upserted = 0
    if vec_backend == "chroma":
        collection = get_chroma_collection(collection_name=collection_name, chroma_dir=chroma_dir)
    else:
        client, col = get_vector_store(
            "qdrant", collection_name,
            qdrant_url=qdrant_url, qdrant_host=qdrant_host, qdrant_port=qdrant_port, qdrant_api_key=qdrant_api_key,
            model_name=model_name, use_v15=use_v15
        )

    batch_texts, batch_meta, batch_ids = [], [], []
    seen_by_source = {}
    for f in csv_path.glob("*.csv"):
        with f.open("r", encoding="utf-8", newline="") as fh:
            head = fh.read(4096); fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(head, delimiters=";,")
                delim = dialect.delimiter
            except Exception:
                delim = ";" if ";" in head else ","
            reader = csv.DictReader(fh, delimiter=delim)
            fields = reader.fieldnames or []
            tcol = text_column if text_column in fields else ("text" if "text" in fields else (fields[-1] if fields else "text"))
            use_ocr_triplet = (tcol not in fields) and all(x in fields for x in ("page", "line", "text"))
            
            row_idx = 0  # avant la boucle for row
            
            for row in reader:
                txt = row.get("text", "") if use_ocr_triplet else (row.get(tcol, "") or "")

                # 1) fingerprint sur texte normalisé (avant pseudonymisation)
                norm = " ".join((txt or "").split()).lower()
                fp = sha256(norm.encode("utf-8", errors="ignore")).hexdigest()

                # 2) métadonnées probatoires (on les calcule avant source_id)
                meta = {
                    "ingest_path": str(f),
                    "filename": f.name,
                    "collection": collection_name,
                    "page": None,
                    "line": None,
                    "doc_type": _norm(row.get("doc_type")),
                    "party_origin": _norm(row.get("party_origin")),
                    "version_label": _norm(row.get("version_label")),
                    "parent_doc_path": row.get("parent_doc_path") or row.get("source_path"),
                    "doc_date": (str(row.get("doc_date")).strip() if row.get("doc_date") else None),
                    "piece_ref": row.get("piece_ref") or row.get("piece_number"),
                    "text_fingerprint": fp,
                }

                # 3) source_id stable (phase 1)
                p = str(meta.get("parent_doc_path") or meta.get("ingest_path") or str(f)).strip()
                source_id = sha256(p.encode("utf-8", errors="ignore")).hexdigest()[:16]
                meta["source_id"] = source_id

                # 4) dédoublonnage strict DANS la source (évite de supprimer des clauses communes entre docs)
                sset = seen_by_source.setdefault(source_id, set())
                if fp in sset:
                    continue
                sset.add(fp)

                # 5) pseudonymisation après le fingerprint (optionnel)
                if enable_pseudonym:
                    txt = pseudonymize_text(txt, reg, key)

                # 6) ID stable (remplace uuid4)
                row_idx += 1
                page = str(row.get("page") or row.get("Page") or row.get("PAGE") or "").strip()
                line = str(row.get("line") or row.get("Line") or row.get("LINE") or "").strip()

                # fallback si page/line manquants : on utilise row_idx (stable car CSV stable)
                if not page:
                    page = "?"
                if not line:
                    line = str(row_idx)

                pid = f"{source_id}:{page}:{line}:{fp[:8]}"

                meta["page"] = page
                meta["line"] = line
                meta["embedding_model"] = embedder.model_name
                meta["chunk_id"] = pid
                meta["piece_ref"] = _norm(row.get("piece_ref") or row.get("piece_number"))


                # Option si page/line manquants dans vos CSV "non OCR" :
                # pid = f"{source_id}:{f.stem}:{row.get('row_id','?')}"  # si vous avez un identifiant ligne

                batch_texts.append(txt)
                batch_meta.append(meta)
                batch_ids.append(pid)

                if len(batch_texts) >= batch_size:
                    vecs = embedder.embed_documents(batch_texts)
                    if vec_backend == "chroma":
                        collection.upsert(documents=batch_texts, embeddings=vecs, metadatas=batch_meta, ids=batch_ids)
                    else:
                        points = [
                            PointStruct(id=_pid, vector=v, payload={**m, "text": t})
                            for _pid, v, m, t in zip(batch_ids, vecs, batch_meta, batch_texts)
                        ]
                        client.upsert(collection_name=collection_name, points=points)
                    upserted += len(batch_texts)
                    batch_texts, batch_meta, batch_ids = [], [], []


    if batch_texts:
        vecs = embedder.embed_documents(batch_texts)
        if vec_backend == "chroma":
            collection.upsert(documents=batch_texts, embeddings=vecs, metadatas=batch_meta, ids=batch_ids)
        else:
            # ✅ Même correctif ici
            points = [
                PointStruct(id=pid, vector=v, payload={**m, "text": t})
                for pid, v, m, t in zip(batch_ids, vecs, batch_meta, batch_texts)
            ]
            client.upsert(collection_name=collection_name, points=points)
        upserted += len(batch_texts)

    # rapport pseudonymisation (identique)
    report_path = None; aliases_created = 0
    if enable_pseudonym:
        save_registry(reg)
        after_aliases = set(reg.values()); new_aliases = sorted(list(after_aliases - before_aliases))
        aliases_created = len(new_aliases)
        try:
            log_dir = Path(PATHS.get("LOG_DIR", ".")) / "exports"; log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = log_dir / f"anonymization_{collection_name}_{ts}.json"
            report = {"collection": collection_name, "csv_dir": str(csv_path),
                      "backend": vec_backend, "aliases_created": aliases_created,
                      "aliases": new_aliases}
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            report_path = None

    return {"upserted": upserted, "pseudonymized": bool(enable_pseudonym),
            "aliases_created": aliases_created,
            "report_path": (str(report_path) if report_path else None),
            "collection": collection_name, "backend": vec_backend}

def retrieve_top_k_store(
    query: str,
    collection_name: str,
    vec_backend: VecBackend = "chroma",
    chroma_dir: Optional[str] = None,
    k: int = 5,
    model_name: Optional[str] = None,
    use_v15: Optional[bool] = None,
    include_distances: bool = True,
    filters: Optional[dict] = None,
    strict: bool = True,   
    qdrant_url: Optional[str] = None,
    qdrant_host: Optional[str] = None,
    qdrant_port: Optional[int] = None,
    qdrant_api_key: Optional[str] = None,
) -> Dict:
    embedder = NomicEmbedding(model_name=model_name, use_v15=use_v15)
    qvec = embedder.embed_query(query)

    # Chroma
    if vec_backend == "chroma":
        collection = get_chroma_collection(collection_name=collection_name, chroma_dir=chroma_dir)
        include = ["documents", "metadatas"] + (["distances"] if include_distances else [])
        if filters:
            res = collection.query(query_embeddings=[qvec], n_results=max(1, int(k)), where=filters, include=include)
        else:
            res = collection.query(query_embeddings=[qvec], n_results=max(1, int(k)), include=include)

        # contrôle cohérence modèle (Chroma)
        expected = embedder.model_name
        metas = res.get("metadatas", [[]])[0]
        for m in metas:
            got = (m or {}).get("embedding_model")
            if got and got != expected:
                raise RuntimeError(
                    f"Embedding model mismatch: expected={expected} got={got} collection={collection_name}. "
                    "Réindexez la collection ou utilisez le même modèle."
                )
        return res


    # Qdrant
    client, col = get_vector_store(
        "qdrant", collection_name,
        qdrant_url=qdrant_url, qdrant_host=qdrant_host, qdrant_port=qdrant_port, qdrant_api_key=qdrant_api_key,
        model_name=model_name, use_v15=use_v15
    )


    if filters:
        filter_ = Filter(must=[
            FieldCondition(key=kk, match=MatchValue(value=vv))
            for kk, vv in filters.items()
        ])

        try:
            srch = client.search(
                collection_name=collection_name,
                query_vector=qvec,
                limit=max(1, int(k)),
                query_filter=filter_,
            )
        except TypeError:
            if strict:
                # pas de fallback en mode strict
                raise
            log.info("Qdrant client: fallback param 'filter=' (ancien) au lieu de 'query_filter='")
            srch = client.search(
                collection_name=collection_name,
                query_vector=qvec,
                limit=max(1, int(k)),
                filter=filter_,
            )
    else:
        srch = client.search(
            collection_name=collection_name,
            query_vector=qvec,
            limit=max(1, int(k)),
        )

    documents, metadatas, scores = [], [], []
    for p in srch:
        payload = p.payload or {}
        documents.append(payload.get("text", ""))
        metadatas.append(payload)
        scores.append(float(p.score) if include_distances else None)

    expected = embedder.model_name
    for m in metadatas:
        got = (m or {}).get("embedding_model")
        if got and got != expected:
            raise RuntimeError(
                f"Embedding model mismatch: expected={expected} got={got} collection={collection_name}. "
                "Réindexez la collection ou utilisez le même modèle."
            )


    return {"documents": [documents], "metadatas": [metadatas], "scores": [scores]}


def build_rag_context_store(
    query: str,
    collection_name: str,
    vec_backend: VecBackend = "chroma",
    chroma_dir: Optional[str] = None,
    k: int = 5,
    show_distances: bool = False,
    filters: Optional[dict] = None,
    max_total_chars: Optional[int] = None,
    strict: bool = True,      
    model_name: Optional[str] = None,
    use_v15: Optional[bool] = None,
    qdrant_url: Optional[str] = None,
    qdrant_host: Optional[str] = None,
    qdrant_port: Optional[int] = None,
    qdrant_api_key: Optional[str] = None
) -> Tuple[str, List[Dict[str, str]]]:
    res = retrieve_top_k_store(
        query=query, 
        collection_name=collection_name, 
        vec_backend=vec_backend, 
        chroma_dir=chroma_dir,
        k=k, 
        model_name=model_name, 
        use_v15=use_v15, 
        include_distances=show_distances, 
        filters=filters,
        strict=strict,  
        qdrant_url=qdrant_url, 
        qdrant_host=qdrant_host, 
        qdrant_port=qdrant_port, 
        qdrant_api_key=qdrant_api_key
    )
    context = format_passages_for_prompt(res=res, k=k, show_distances=show_distances, max_total_chars=max_total_chars)
    sources = retrieve_sources(res, k=k, with_distances=show_distances)
    return context, sources
