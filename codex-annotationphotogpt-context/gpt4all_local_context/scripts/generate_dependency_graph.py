from __future__ import annotations

import ast
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = PROJECT_ROOT / "flask_server" / "gpt4all_flask.py"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "SYSTEM_DEPENDENCY_GRAPH.generated.md"

INTERNAL_MODULES = {
    "helper_paths",
    "helpers_embed",
    "ocr_utils",
    "pseudonymizer",
    "rag_utils",
    "rag_vector_utils",
    "rag_memoire_utils",
    "voxtral_utils",
    "web_scraper",
    "web_scraper_premium",
    "web_search_utils",
}


def extract_internal_dependencies(tree: ast.AST):
    deps = defaultdict(set)

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in INTERNAL_MODULES:
                    deps["gpt4all_flask.py"].add(root)

        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            root = module_name.split(".")[0] if module_name else ""
            if root in INTERNAL_MODULES:
                deps["gpt4all_flask.py"].add(root)

    return deps


def build_markdown(deps):
    lines = []

    lines.append("# SYSTEM_DEPENDENCY_GRAPH.generated.md")
    lines.append("")
    lines.append("Cartographie générée automatiquement des dépendances internes de `gpt4all_flask.py`.")
    lines.append("")

    root = "gpt4all_flask.py"
    children = sorted(deps.get(root, []))

    lines.append("## Graphe simplifié")
    lines.append("")

    lines.append("```text")
    lines.append(root)
    for idx, child in enumerate(children):
        connector = "└─" if idx == len(children) - 1 else "├─"
        lines.append(f"{connector} {child}")
    lines.append("```")
    lines.append("")

    lines.append("## Modules internes appelés")
    lines.append("")

    for child in children:
        lines.append(f"- `{child}`")

    lines.append("")
    lines.append("## Interprétation")
    lines.append("")
    lines.append("Ces modules sont importés directement par `gpt4all_flask.py` et doivent être analysés avant toute modification significative du serveur principal.")
    lines.append("")

    return "\n".join(lines)


def main():
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(f"Fichier introuvable : {SOURCE_FILE}")

    source = SOURCE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    deps = extract_internal_dependencies(tree)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(build_markdown(deps), encoding="utf-8")

    print(f"Fichier généré : {OUTPUT_FILE}")
    print(f"Modules internes détectés : {len(deps.get('gpt4all_flask.py', []))}")


if __name__ == "__main__":
    main()