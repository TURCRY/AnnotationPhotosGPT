from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = PROJECT_ROOT / "flask_server" / "gpt4all_flask.py"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "API_MAP.generated.md"


def literal_eval_safe(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def extract_route_info(tree: ast.AST) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue

            func = decorator.func
            if not isinstance(func, ast.Attribute):
                continue

            if func.attr != "route":
                continue

            route_path = None
            methods = None

            if decorator.args:
                route_path = literal_eval_safe(decorator.args[0])

            for kw in decorator.keywords:
                if kw.arg == "methods":
                    methods = literal_eval_safe(kw.value)

            routes.append(
                {
                    "function": node.name,
                    "path": route_path,
                    "methods": methods or ["GET"],
                    "lineno": getattr(node, "lineno", None),
                    "category": classify_route(str(route_path)),
                }
            )
        

    # tri lisible
    routes.sort(key=lambda x: (str(x["path"]), x["function"]))
    return routes


def build_markdown(routes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# API_MAP.generated.md")
    lines.append("")
    lines.append("Cartographie générée automatiquement depuis `flask_server/gpt4all_flask.py`.")
    lines.append("")
    lines.append(f"Nombre de routes détectées : **{len(routes)}**")
    lines.append("")


    from collections import Counter

    counter = Counter(route["category"] for route in routes)

    lines.append("## Répartition par catégorie")
    lines.append("")
    for cat, count in sorted(counter.items()):
        lines.append(f"- **{cat}** : {count} route(s)")
    lines.append("")
    lines.append("| Catégorie | Méthodes | Route | Fonction | Ligne |")
    lines.append("|---|---|---|---|---:|")

    for route in routes:
        methods = ", ".join(route["methods"]) if isinstance(route["methods"], list) else str(route["methods"])
        path = str(route["path"])
        func = route["function"]
        lineno = route["lineno"] or ""
        category = route["category"]
        lines.append(f"| {category} | `{methods}` | `{path}` | `{func}` | {lineno} |")

    lines.append("")
    lines.append("## Détail par route")
    lines.append("")

    for route in routes:
        methods = ", ".join(route["methods"]) if isinstance(route["methods"], list) else str(route["methods"])
        path = str(route["path"])
        func = route["function"]
        lineno = route["lineno"] or "?"
        lines.append(f"### `{path}`")
        lines.append("")
        lines.append(f"- **Méthodes** : `{methods}`")
        lines.append(f"- **Fonction** : `{func}`")
        lines.append(f"- **Ligne** : `{lineno}`")
        lines.append("")

    return "\n".join(lines)

def classify_route(path: str) -> str:
    p = (path or "").lower()

    if p in ("/chat_llm", "/chat_orchestre"):
        return "LLM"
    if p.startswith("/annoter"):
        return "Annotation"
    if p.startswith("/annoter_rag") or p.startswith("/rag/") or p.startswith("/vector/") \
       or p in ("/export_rag_to_chroma", "/index_chroma_from_csv"):
        return "RAG"
    if p.startswith("/ocr"):
        return "OCR"
    if p.startswith("/asr") or p.startswith("/voxtral"):
        return "ASR"
    if p.startswith("/comfyui") or p == "/sd_generate":
        return "Vision"
    if p in ("/search_web", "/annoter_web"):
        return "Web"
    if p.startswith("/pseudonym") or p == "/anonymization_reports":
        return "Pseudonymisation"
    if p.startswith("/qa_logs"):
        return "Journalisation"
    if p in ("/debug_paths", "/scaffold_project_dirs"):
        return "Maintenance"
    if p in ("/upload_file", "/files", "/download_file"):
        return "Fichiers"
    if p.startswith("/api/split_pdf") or p == "/api/detect_piece_boundaries" or p == "/infer_piece_titles":
        return "PDF"
    if p in ("/ping", "/health", "/info", "/models", "/models_index", "/models_status", "/model_info", "/__routes"):
        return "Administration"
    if p in ("/prompts_structures", "/prompts_structures/item"):
        return "Prompts"
    return "Autre"

def main() -> None:
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(f"Fichier introuvable : {SOURCE_FILE}")

    source = SOURCE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    routes = extract_route_info(tree)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(build_markdown(routes), encoding="utf-8")

    print(f"Fichier généré : {OUTPUT_FILE}")
    print(f"Routes détectées : {len(routes)}")


if __name__ == "__main__":
    main()