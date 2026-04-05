# test_rag_utils.py - Test d'extraction RAG local (à placer dans /scripts)

import sys
from pathlib import Path

# Ajouter le dossier parent au path pour importer rag_utils.py
sys.path.append(str(Path(__file__).resolve().parents[1]))

from rag_utils import extraire_contenu_rag, extraire_blocs_rag

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test de lecture de contenu RAG")
    parser.add_argument("--dossier", type=str, required=True, help="Chemin du dossier RAG")
    parser.add_argument("--mode", type=str, choices=["texte", "blocs"], default="texte")
    args = parser.parse_args()

    dossier_rag = args.dossier

    print("\n🔎 Lecture du dossier :", dossier_rag)
    print("🧪 Mode :", args.mode)

    if args.mode == "texte":
        texte = extraire_contenu_rag(dossier_rag)
        print("\n=== CONTENU CONCATÉNÉ (début) ===")
        print(texte[:2000])
        print("\n=== FIN APERCU ===")
    else:
        blocs = extraire_blocs_rag(dossier_rag)
        print(f"\n📦 {len(blocs)} blocs extraits")
        for i, bloc in enumerate(blocs[:3]):
            print(f"\n[{i+1}] {bloc['relative_path']}\n{bloc['content'][:500]}...")
