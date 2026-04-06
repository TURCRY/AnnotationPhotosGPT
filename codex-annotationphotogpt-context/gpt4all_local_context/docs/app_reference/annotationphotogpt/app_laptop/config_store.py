from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = ROOT_DIR / "config"
LEGACY_INFOS_PATH = DATA_DIR / "infos_projet.json"
LEGACY_APP_CONFIG_PATH = CONFIG_DIR / "config.json"
STRUCTURED_PROJECTS_DIR = DATA_DIR / "projects"

PROJECT_SCHEMA = "annotationphotogpt.project.v1"
CAPTATION_SCHEMA = "annotationphotogpt.captation.v1"

PROJECT_PROMPT_KEYS = ("mission", "system", "user")
BATCH_TOP_LEVEL_KEYS = ("fichier_photos_batch",)
BATCH_PCFIXE_KEYS = ("config_llm", "out_dir", "boost_file", "max_speakers", "proper_names_file")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def extract_ids(payload: dict | None) -> tuple[str, str]:
    data = dict(payload or {})
    project_id = str(data.get("project_id") or data.get("id_affaire") or "").strip()
    captation_id = str(data.get("captation_id") or data.get("id_captation") or "").strip()
    return project_id, captation_id


def ensure_id_aliases(payload: dict | None) -> dict:
    out = dict(payload or {})
    project_id, captation_id = extract_ids(out)
    if project_id:
        out["project_id"] = project_id
        out["id_affaire"] = project_id
    if captation_id:
        out["captation_id"] = captation_id
        out["id_captation"] = captation_id
    return out


def resolve_project_config(project_id: str) -> Path | None:
    project_id = str(project_id or "").strip()
    if not project_id:
        return None
    return STRUCTURED_PROJECTS_DIR / project_id / "project_config.json"


def resolve_captation_config(project_id: str, captation_id: str) -> Path | None:
    project_id = str(project_id or "").strip()
    captation_id = str(captation_id or "").strip()
    if not project_id or not captation_id:
        return None
    return STRUCTURED_PROJECTS_DIR / project_id / "captations" / captation_id / "captation_config.json"


def _split_infos_levels(payload: dict) -> tuple[dict, dict, dict]:
    data = ensure_id_aliases(payload)
    project_id, captation_id = extract_ids(data)

    project = {
        "project_id": project_id,
        "id_affaire": project_id,
    }
    prompts = {}
    captation = {}
    batch_derived = {}

    for key, value in data.items():
        if key in ("project_id", "id_affaire", "captation_id", "id_captation"):
            continue
        if key in PROJECT_PROMPT_KEYS:
            prompts[key] = value
            continue
        if key in BATCH_TOP_LEVEL_KEYS:
            batch_derived[key] = value
            continue
        if key == "pcfixe" and isinstance(value, dict):
            pcfixe = dict(value)
            batch_pcfixe = {}
            for batch_key in BATCH_PCFIXE_KEYS:
                if batch_key in pcfixe:
                    batch_pcfixe[batch_key] = pcfixe.pop(batch_key)
            if pcfixe:
                captation["pcfixe"] = pcfixe
            if batch_pcfixe:
                batch_derived["pcfixe"] = batch_pcfixe
            continue
        captation[key] = value

    captation["project_id"] = project_id
    captation["id_affaire"] = project_id
    captation["captation_id"] = captation_id
    captation["id_captation"] = captation_id
    return project, prompts, captation, batch_derived


def _flatten_structured(project_doc: dict, captation_doc: dict) -> dict:
    out: dict[str, Any] = {}
    out.update(project_doc.get("project") or {})
    out.update(project_doc.get("prompts") or {})
    out.update(captation_doc.get("captation") or {})
    out.update(captation_doc.get("batch_derived") or {})

    project_id, captation_id = extract_ids(out)
    if project_id:
        out["project_id"] = project_id
        out["id_affaire"] = project_id
    if captation_id:
        out["captation_id"] = captation_id
        out["id_captation"] = captation_id
    return out


def load_infos_projet() -> dict:
    legacy = ensure_id_aliases(_read_json(LEGACY_INFOS_PATH, {}))
    project_id, captation_id = extract_ids(legacy)
    if not project_id or not captation_id:
        return legacy

    project_path = resolve_project_config(project_id)
    captation_path = resolve_captation_config(project_id, captation_id)
    if not project_path or not captation_path or not captation_path.exists():
        return legacy

    project_doc = _read_json(project_path, {})
    captation_doc = _read_json(captation_path, {})
    if not isinstance(project_doc, dict) or not isinstance(captation_doc, dict):
        return legacy

    return _flatten_structured(project_doc, captation_doc)


def save_infos_projet(payload: dict) -> dict:
    normalized = ensure_id_aliases(payload)
    project_id, captation_id = extract_ids(normalized)
    if project_id and captation_id:
        project_path = resolve_project_config(project_id)
        captation_path = resolve_captation_config(project_id, captation_id)
        project, prompts, captation, batch_derived = _split_infos_levels(normalized)

        project_doc = {
            "schema": PROJECT_SCHEMA,
            "project_id": project_id,
            "project": project,
            "prompts": prompts,
        }
        captation_doc = {
            "schema": CAPTATION_SCHEMA,
            "project_id": project_id,
            "captation_id": captation_id,
            "captation": captation,
            "batch_derived": batch_derived,
        }
        _atomic_write_json(project_path, project_doc)
        _atomic_write_json(captation_path, captation_doc)

    _atomic_write_json(LEGACY_INFOS_PATH, normalized)
    return normalized


def load_annotation_app_config(project_id: str = "", captation_id: str = "") -> dict:
    base_cfg = _read_json(LEGACY_APP_CONFIG_PATH, {})
    project_id = str(project_id or "").strip()
    captation_id = str(captation_id or "").strip()

    if not project_id or not captation_id:
        legacy = _read_json(LEGACY_INFOS_PATH, {})
        project_id, captation_id = extract_ids(legacy)

    captation_path = resolve_captation_config(project_id, captation_id)
    if not captation_path or not captation_path.exists():
        return base_cfg if isinstance(base_cfg, dict) else {}

    structured = _read_json(captation_path, {})
    overrides = (structured.get("app_config_overrides") or {}) if isinstance(structured, dict) else {}
    if not isinstance(overrides, dict):
        return base_cfg if isinstance(base_cfg, dict) else {}

    merged = dict(base_cfg or {})
    merged.update(overrides)
    return merged
