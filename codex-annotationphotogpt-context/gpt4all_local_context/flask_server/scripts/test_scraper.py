# test_scraper.py - Test du module web_scraper.py avec un fichier log web

import sys
import os
from pathlib import Path

# Assure l'import du dossier parent
sys.path.append(str(Path(__file__).resolve().parents[1]))

from web_scraper import scraper_sources_publiques

if __name__ == "__main__":
    log_dir = Path("D:/GPT4All_Local/logs/sources_web")
    fichiers = sorted(log_dir.glob("sources_web_*.json"), reverse=True)

    if not fichiers:
        print("❌ Aucun fichier sources_web trouvé dans le dossier.")
        sys.exit(1)

    print("📄 Fichiers disponibles :")
    for i, f in enumerate(fichiers, 1):
        print(f"[{i}] {f.name}")

    choix = input("➡️ Numéro du fichier à tester : ").strip()
    if not choix.isdigit() or not (1 <= int(choix) <= len(fichiers)):
        print("❌ Choix invalide.")
        sys.exit(1)

    fichier_selectionne = fichiers[int(choix) - 1]
    print(f"🔍 Traitement du fichier : {fichier_selectionne.name}")

    scraper_sources_publiques(fichier_selectionne)
