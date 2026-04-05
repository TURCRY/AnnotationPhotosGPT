import json
from pathlib import Path
from urllib.parse import urlparse
from web_scraper_premium import scraper_url

# === Config ===
LOGS_DIR = Path("D:/GPT4All_Local/logs/sources_web/")
PROJET = "expertise_demo"  # À adapter au projet actif
MAX_URLS = 5  # Limite d'URLs premium à traiter

def choisir_log():
    fichiers = sorted(LOGS_DIR.glob("sources_web_*.json"), reverse=True)
    if not fichiers:
        print("❌ Aucun fichier sources_web_*.json trouvé.")
        return None
    print("\n📂 Fichiers disponibles :")
    for i, f in enumerate(fichiers):
        print(f"{i + 1}. {f.name}")
    choix = input("\n➡️ Choisir un fichier (1–N) : ")
    try:
        index = int(choix) - 1
        return fichiers[index]
    except:
        print("❌ Choix invalide.")
        return None

def est_premium(url):
    domaine = urlparse(url).netloc
    return any(site in domaine for site in ["lemonde.fr", "lesechos.fr"])

def main():
    log = choisir_log()
    if not log:
        return

    with open(log, "r", encoding="utf-8") as f:
        data = json.load(f)

    urls = [item["url"] for item in data if est_premium(item["url"])]

    if not urls:
        print("❌ Aucune URL premium trouvée dans ce fichier.")
        return

    print(f"\n🔐 {len(urls)} URL(s) premium détectées (limité à {MAX_URLS}) :\n")
    for i, url in enumerate(urls[:MAX_URLS]):
        print(f"- {url}")
        scraper_url(url, projet=PROJET, index=i+1)

if __name__ == "__main__":
    main()
