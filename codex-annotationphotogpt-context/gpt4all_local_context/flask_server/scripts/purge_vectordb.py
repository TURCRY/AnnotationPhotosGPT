# purge_vectordb.py - Simulation de suppression RAG distante (RGPD)

import os
import json
from datetime import datetime
from pathlib import Path

# === Paramètres de simulation ===
EXPORT_LOG_DIR = Path("D:/GPT4All_Local/logs/exports")
EXPORT_LOG_DIR.mkdir(parents=True, exist_ok=True)

SIMULATED_INDEX = Path("D:/GPT4All_Local/temp/index_vectordb.json")

# === Purge fictive ===
def purger_vectordb():
    if not SIMULATED_INDEX.exists():
        print("🔍 Aucun index vectoriel simulé à purger.")
        return

    try:
        with open(SIMULATED_INDEX, "r", encoding="utf-8") as f:
            index = json.load(f)

        print(f"🧽 Suppression de {len(index)} documents vectoriels simulés...")

        # Log de suppression RGPD
        log_path = EXPORT_LOG_DIR / f"purge_rgpd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        SIMULATED_INDEX.unlink()
        print(f"✅ Index supprimé. Log sauvegardé : {log_path}")

    except Exception as e:
        print(f"❌ Erreur durant la purge : {e}")

if __name__ == "__main__":
    purger_vectordb()
