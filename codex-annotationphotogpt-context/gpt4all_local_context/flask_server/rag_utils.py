# rag_utils.py - Extraction de contenu RAG local (expertise judiciaire)

from pathlib import Path
import fitz  # PyMuPDF
import csv



# === Extraction du contenu texte d'un fichier PDF ===
def extraire_pdf(fichier: Path) -> str:
    try:
        with fitz.open(fichier) as doc:
            textes = [page.get_text() for page in doc]
        return "\n".join(textes)
    except Exception as e:
        return f"[ERREUR LECTURE PDF: {fichier.name}] {e}"

# === Extraction du contenu texte d'un fichier texte ou CSV ===
def extraire_texte(fichier: Path) -> str:
    try:
        if fichier.suffix.lower() == ".csv":
            with open(fichier, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                lignes = ["; ".join(row) for row in reader]
                return "\n".join(lignes)
        else:
            return fichier.read_text(encoding="utf-8")
    except Exception as e:
        return f"[ERREUR LECTURE TEXTE: {fichier.name}] {e}"

# === Fonction principale : extraire tout le contenu texte d'un dossier RAG (récursif) ===
def extraire_contenu_rag(dossier: str) -> str:
    dossier_path = Path(dossier)
    if not dossier_path.exists():
        return f"[ERREUR] Dossier introuvable : {dossier}"

    corpus = []
    extensions_autorisees = [".txt", ".md", ".csv", ".pdf"]

    for fichier in dossier_path.rglob("*.*"):
        if fichier.suffix.lower() in extensions_autorisees:
            rel_path = fichier.relative_to(dossier_path)
            if fichier.suffix.lower() == ".pdf":
                contenu = extraire_pdf(fichier)
            else:
                contenu = extraire_texte(fichier)
            bloc = f"\n--- {rel_path} ---\n{contenu}\n"
            corpus.append(bloc)

    return "\n".join(corpus) if corpus else "[Aucun fichier lisible trouvé]"

# === Variante : retourner une liste de blocs (pour vectorisation) ===
def extraire_blocs_rag(dossier: str) -> list:
    dossier_path = Path(dossier)
    if not dossier_path.exists():
        return []

    blocs = []
    extensions_autorisees = [".txt", ".md", ".csv", ".pdf"]

    for fichier in dossier_path.rglob("*.*"):
        if fichier.suffix.lower() in extensions_autorisees:
            rel_path = fichier.relative_to(dossier_path)
            if fichier.suffix.lower() == ".pdf":
                contenu = extraire_pdf(fichier)
            else:
                contenu = extraire_texte(fichier)
            blocs.append({
                "filename": fichier.name,
                "relative_path": str(rel_path),
                "content": contenu.strip()
            })

    return blocs


# Exemple d'appel CLI (test local)
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Tester l'extraction RAG")
    parser.add_argument("--dossier", type=str, help="Chemin du dossier RAG")
    parser.add_argument("--mode", type=str, choices=["texte", "blocs"], default="texte")
    args = parser.parse_args()

    if args.mode == "texte":
        texte = extraire_contenu_rag(args.dossier)
        print(texte[:2000])
    else:
        blocs = extraire_blocs_rag(args.dossier)
        for bloc in blocs[:5]:
            print(f"\n== {bloc['relative_path']} ==\n{bloc['content'][:500]}...")
