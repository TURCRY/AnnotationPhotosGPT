# purge_chroma_collection.py
# Purge sécurisée d'une collection Chroma avec export RGPD (journal JSON)
# - Exporte (optionnel) les documents / métadonnées avant suppression
# - Mode "dry-run" pour simuler la purge
# - Journalise les opérations dans D:/GPT4All_Local/logs/exports

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import chromadb

# ---------- Répertoires par défaut ----------
try:
    from helper_paths import load_paths
    PATHS = load_paths()
    DEFAULT_CHROMA_DIR = PATHS.get("CHROMA_BASE", "D:/GPT4All_Local/chroma_db")
    EXPORT_LOG_DIR = Path(PATHS.get("LOG_DIR", "D:/GPT4All_Local/logs/exports"))
except Exception:
    # fallback anciens chemins
    DEFAULT_CHROMA_DIR = "D:/GPT4All_Local/chroma_db"
    EXPORT_LOG_DIR = Path("D:/GPT4All_Local/logs/exports")
EXPORT_LOG_DIR.mkdir(parents=True, exist_ok=True)


def export_collection_snapshot(
    client: chromadb.PersistentClient,
    collection_name: str,
    out_dir: Path,
    batch_size: int = 500,
    limit_max_items: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Exporte la collection (ids, metadatas, documents) par lots dans un JSON unique.
    Si limit_max_items est défini, on tronque l'export à ce nombre d'éléments.
    """
    coll = client.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})
    total = coll.count()
    to_fetch = min(total, limit_max_items) if limit_max_items else total

    snapshot = {
        "collection": collection_name,
        "exported_at": datetime.now().isoformat(),
        "total_count_at_export": total,
        "items": []
    }

    fetched = 0
    offset = 0
    print(f"⏳ Export RGPD : {to_fetch}/{total} éléments à exporter (batch={batch_size})…")

    while fetched < to_fetch:
        current_batch = min(batch_size, to_fetch - fetched)
        # API "get" avec pagination offset/limit
        batch = coll.get(
            include=["ids", "metadatas", "documents"],
            limit=current_batch,
            offset=offset
        )
        ids = batch.get("ids", [])
        docs = batch.get("documents", [])
        metas = batch.get("metadatas", [])

        # Normalisation en liste de dict
        for _id, _doc, _meta in zip(ids, docs, metas):
            snapshot["items"].append({
                "id": _id,
                "document": _doc,
                "metadata": _meta
            })

        fetched += len(ids)
        offset += len(ids)

        print(f"  → exporté {fetched}/{to_fetch}")

        # Si la collection renvoie moins que demandé, on stoppe
        if len(ids) == 0:
            break

    # Écriture fichier
    filename = f"rgpd_export_{collection_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path = out_dir / filename
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print(f"✅ Export terminé : {out_path}")
    return {"path": str(out_path), "count_exported": len(snapshot["items"]), "total_count": total}


def delete_collection(client: chromadb.PersistentClient, collection_name: str) -> None:
    """
    Supprime la collection de la base Chroma.
    """
    print(f"🧽 Suppression de la collection '{collection_name}'…")
    client.delete_collection(collection_name)
    print(f"✅ Collection supprimée : {collection_name}")


def main():
    parser = argparse.ArgumentParser(description="Purge sécurisée d'une collection Chroma avec export RGPD.")
    parser.add_argument("--chroma_dir", default=DEFAULT_CHROMA_DIR, help="Répertoire de la base Chroma persistante")
    parser.add_argument("--collection", required=True, help="Nom de la collection à purger (ex: mon_projet)")
    parser.add_argument("--dry_run", action="store_true", help="Simulation : AUCUNE suppression n'est effectuée")
    parser.add_argument("--no_export", action="store_true", help="Ne pas exporter la collection avant suppression")
    parser.add_argument("--export_dir", default=str(EXPORT_LOG_DIR), help="Dossier pour le JSON d'export RGPD")
    parser.add_argument("--batch_size", type=int, default=500, help="Taille des lots pour l'export")
    parser.add_argument("--limit_max_items", type=int, default=None, help="Limiter le nombre d'éléments exportés (debug)")
    parser.add_argument("--confirm", action="store_true", help="Confirmer explicitement la suppression")
    args = parser.parse_args()

    chroma_dir = args.chroma_dir
    collection_name = args.collection
    dry_run = args.dry_run
    do_export = not args.no_export
    export_dir = Path(args.export_dir)
    batch_size = args.batch_size
    limit_max_items = args.limit_max_items

    # Connexion Chroma
    client = chromadb.PersistentClient(path=chroma_dir)

    # Vérifier existence collection (compte)
    try:
        coll = client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
        total_count = coll.count()
    except Exception as e:
        print(f"❌ Erreur d'accès à la collection '{collection_name}': {e}")
        return

    if total_count == 0:
        print(f"ℹ️ La collection '{collection_name}' est vide ({total_count} éléments).")
    else:
        print(f"📊 Collection '{collection_name}' : {total_count} éléments détectés.")

    # Export RGPD (sauf si --no_export)
    export_info = None
    if do_export and total_count > 0:
        export_dir.mkdir(parents=True, exist_ok=True)
        try:
            export_info = export_collection_snapshot(
                client=client,
                collection_name=collection_name,
                out_dir=export_dir,
                batch_size=batch_size,
                limit_max_items=limit_max_items
            )
        except Exception as e:
            print(f"❌ Erreur durant l'export RGPD : {e}")
            # Par sécurité, on propose de ne PAS supprimer si l'export a échoué.
            if not dry_run:
                print("⚠️ Suppression annulée car l'export RGPD a échoué. Relance avec --no_export si tu veux forcer.")
                return

    # Suppression
    if dry_run:
        print("🧪 Dry-run activé : aucune suppression effectuée.")
        return

    if not args.confirm:
        print("⚠️ Suppression non confirmée. Relance la commande avec --confirm pour procéder.")
        return

    try:
        delete_collection(client, collection_name)
    except Exception as e:
        print(f"❌ Erreur durant la suppression : {e}")
        return

    # Journal de purge (métadonnées)
    purge_log = {
        "collection": collection_name,
        "deleted_at": datetime.now().isoformat(),
        "chroma_dir": chroma_dir,
        "export": export_info if export_info else {"skipped": True},
        "previous_count": total_count
    }
    purge_log_path = export_dir / f"purge_rgpd_{collection_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(purge_log_path, "w", encoding="utf-8") as f:
        json.dump(purge_log, f, indent=2, ensure_ascii=False)

    print(f"📝 Log de purge : {purge_log_path}")
    print("🎉 Purge terminée.")

if __name__ == "__main__":
    main()
