from __future__ import annotations

import ast
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = PROJECT_ROOT / "flask_server" / "gpt4all_flask.py"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "MODULE_MAP.generated.md"


# Liste élargie des modules de la standard library
STDLIB_ROOTS = {
    "ast","base64","collections","concurrent","contextlib","csv","datetime",
    "difflib","functools","gc","glob","hashlib","html","importlib","inspect",
    "io","json","logging","math","mimetypes","os","pathlib","platform",
    "random","re","shutil","socket","subprocess","sys","threading","time",
    "traceback","typing","unicodedata","urllib","uuid"
}


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


def classify_import(module_name: str) -> str:

    if not module_name:
        return "Inconnu"

    root = module_name.split(".")[0]

    if root in INTERNAL_MODULES:
        return "Interne"

    if root in STDLIB_ROOTS:
        return "Standard library"

    return "Tiers"


def extract_imports(tree: ast.AST):

    imports = []

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):

            for alias in node.names:

                module_name = alias.name

                imports.append({
                    "type": "import",
                    "module": module_name,
                    "name": "",
                    "lineno": getattr(node, "lineno", None),
                    "category": classify_import(module_name)
                })


        elif isinstance(node, ast.ImportFrom):

            module_name = node.module or ""

            for alias in node.names:

                imports.append({
                    "type": "from",
                    "module": module_name,
                    "name": alias.name,
                    "lineno": getattr(node, "lineno", None),
                    "category": classify_import(module_name)
                })


    # suppression des doublons
    unique = {}
    for imp in imports:
        key = (imp["type"], imp["module"], imp["name"], imp["lineno"])
        unique[key] = imp

    imports = list(unique.values())

    imports.sort(key=lambda x: (x["category"], x["module"], x["name"]))

    return imports


def build_markdown(imports):

    lines = []

    lines.append("# MODULE_MAP.generated.md\n")

    lines.append(
        "Cartographie générée automatiquement depuis `flask_server/gpt4all_flask.py`.\n"
    )

    lines.append(f"Nombre d'imports détectés : **{len(imports)}**\n")

    counter = defaultdict(int)

    for imp in imports:
        counter[imp["category"]] += 1

    lines.append("## Répartition par catégorie\n")

    for category in sorted(counter):
        lines.append(f"- **{category}** : {counter[category]} import(s)")

    lines.append("")

    lines.append("| Catégorie | Type | Module | Élément importé | Ligne |")
    lines.append("|---|---|---|---|---:|")

    for imp in imports:

        lines.append(
            f"| {imp['category']} | `{imp['type']}` | `{imp['module']}` | `{imp['name']}` | {imp['lineno'] or ''} |"
        )

    lines.append("")
    lines.append("## Modules internes utilisés\n")

    grouped = defaultdict(list)

    for imp in imports:

        if imp["category"] == "Interne":
            grouped[imp["module"]].append(imp["name"])

    for module in sorted(grouped):

        lines.append(f"### `{module}`\n")

        names = sorted(set(n for n in grouped[module] if n))

        if names:

            lines.append("Éléments importés :")

            for n in names:
                lines.append(f"- `{n}`")

        else:
            lines.append("- import direct du module")

        lines.append("")

    return "\n".join(lines)


def main():

    if not SOURCE_FILE.exists():
        raise FileNotFoundError(SOURCE_FILE)

    source = SOURCE_FILE.read_text(encoding="utf-8")

    tree = ast.parse(source)

    imports = extract_imports(tree)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    OUTPUT_FILE.write_text(build_markdown(imports), encoding="utf-8")

    print("MODULE_MAP généré :", OUTPUT_FILE)
    print("Imports détectés :", len(imports))


if __name__ == "__main__":
    main()