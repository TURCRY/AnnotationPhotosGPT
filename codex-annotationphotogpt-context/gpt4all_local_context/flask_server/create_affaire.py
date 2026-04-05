# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


DEFAULT_AFFAIRES_ROOT = Path(os.getenv("AFFAIRES_ROOT", r"C:\Affaires"))
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_APP_CONFIG_DIR = Path(os.getenv("APP_CONFIG_DIR", str(REPO_ROOT / "config")))


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def resolve_projets_index_path() -> Path:
    env_path = (os.getenv("PROJETS_INDEX_PATH") or "").strip()
    if env_path:
        path = Path(env_path).resolve()
        _log(f"[INFO] projets_index.json via PROJETS_INDEX_PATH: {path}")
        return path

    app_config_dir = (os.getenv("APP_CONFIG_DIR") or "").strip()
    if app_config_dir:
        path = (Path(app_config_dir).resolve() / "projets_index.json")
        _log(f"[INFO] projets_index.json via APP_CONFIG_DIR: {path}")
        return path

    path = (DEFAULT_APP_CONFIG_DIR / "projets_index.json").resolve()
    _log(f"[INFO] projets_index.json via fallback: {path}")
    return path


def load_projets_index(path: Path) -> list[dict]:
    if not path.exists():
        _log(f"[WARN] projets_index.json introuvable: {path}")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log(f"[WARN] lecture projets_index.json impossible: {exc}")
        return []
    if not isinstance(data, list):
        _log(f"[WARN] projets_index.json invalide (liste attendue): {path}")
        return []
    return [dict(item) for item in data]


def write_json_atomic(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8", suffix=".tmp") as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def build_project_config(project_id: str, nom: str, project_root: Path) -> dict:
    return {
        "id": project_id,
        "title": nom or project_id,
        "roots": {
            "pcfixe": str(project_root),
            "laptop": str(project_root),
            "nas": str(project_root),
        },
        "paths": {
            "sqlite": r"_DB\project.sqlite",
        },
    }


def ensure_placeholder_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    conn = sqlite3.connect(str(path))
    conn.close()


def _project_exists(index: list[dict], project_id: str) -> bool:
    for item in index:
        if item.get("id") == project_id or item.get("id_projet") == project_id:
            return True
    return False


def create_affaire(project_id: str, nom: str = "", affaires_root: Path | None = None) -> dict:
    project_id = (project_id or "").strip()
    if not project_id:
        raise ValueError("project_id requis")

    projets_index_path = resolve_projets_index_path()
    index = load_projets_index(projets_index_path)
    if _project_exists(index, project_id):
        _log(f"[INFO] affaire deja presente dans le registre: {project_id}")
        return {
            "ok": True,
            "created": False,
            "project_id": project_id,
        }

    root = Path(affaires_root or DEFAULT_AFFAIRES_ROOT).resolve()
    project_root = root / project_id
    config_dir = project_root / "_Config"
    db_path = project_root / "_DB" / "project.sqlite"
    project_config_path = config_dir / "project_config.json"

    project_root.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if not project_config_path.exists():
        cfg = build_project_config(project_id, nom, project_root)
        project_config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    ensure_placeholder_sqlite(db_path)

    index.append(
        {
            "id": project_id,
            "id_projet": project_id,
            "nom": nom or project_id,
            "chemin_config": str(project_config_path),
            "chemin_config_pcfixe": str(project_config_path),
        }
    )
    write_json_atomic(projets_index_path, index)
    _log(f"[INFO] affaire creee: {project_id}")

    return {
        "ok": True,
        "created": True,
        "project_id": project_id,
        "project_config_path": str(project_config_path),
        "projets_index_path": str(projets_index_path),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", "--id", dest="project_id", required=True, help="Identifiant affaire")
    parser.add_argument("--nom", "--title", dest="nom", default="", help="Nom ou titre")
    parser.add_argument(
        "--affaires_root",
        "--root",
        dest="affaires_root",
        default=str(DEFAULT_AFFAIRES_ROOT),
        help="Racine des affaires",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        payload = create_affaire(
            project_id=args.project_id,
            nom=args.nom,
            affaires_root=Path(args.affaires_root),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        _log(f"[ERROR] create_affaire: {exc}")
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
