import sys
from pathlib import Path

# Pour accéder à web_search_utils.py situé un dossier au-dessus
sys.path.append(str(Path(__file__).resolve().parents[1]))

from web_search_utils import recherche_duckduckgo, log_sources

def main():
    print("🔍 Test de recherche DuckDuckGo")
    query = input("➡️ Entrer une requête : ").strip()
    if not query:
        print("❌ Requête vide.")
        return

    projet = input("📁 Nom du projet : ").strip() or "demo"

    try:
        resultats = recherche_duckduckgo(query, max_results=5)
    except Exception as e:
        print(f"❌ Erreur de recherche : {e}")
        return

    print(f"\n🔗 Résultats pour : {query}\n")
    for i, r in enumerate(resultats, 1):
        print(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}\n")

    if resultats:
        log_sources(resultats, projet)
        print("✅ Résultats enregistrés dans logs/sources_web/")

if __name__ == "__main__":
    main()
