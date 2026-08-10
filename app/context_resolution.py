from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PHOTO_CONTEXT_FIELDS = (
    "mission",
    "system",
    "user",
    "vlm_system",
    "vlm_user",
    "etat_avancement",
)


def _clean_path(value: Any) -> Path | None:
    text = str(value or "").strip().strip('"')
    if not text:
        return None
    return Path(text)


def _append_unique(paths: list[Path], candidate: Path | None) -> None:
    if candidate is None:
        return
    text = str(candidate)
    if not text or text == ".":
        return
    if all(str(existing).lower() != text.lower() for existing in paths):
        paths.append(candidate)


def _candidate_dirs(infos: dict[str, Any], base_dir: Path | None) -> list[Path]:
    dirs: list[Path] = []
    _append_unique(dirs, base_dir)
    pcfixe = infos.get("pcfixe") if isinstance(infos.get("pcfixe"), dict) else {}
    for key in (
        "fichier_contexte_general",
        "fichier_transcription",
        "config_llm",
    ):
        for mapping in (pcfixe, infos):
            path = _clean_path(mapping.get(key))
            if path is not None:
                _append_unique(dirs, path.parent)
    return dirs


def _configured_context_paths(infos: dict[str, Any], expected_name: str) -> list[Path]:
    candidates: list[Path] = []
    pcfixe = infos.get("pcfixe") if isinstance(infos.get("pcfixe"), dict) else {}
    for mapping in (pcfixe, infos):
        path = _clean_path(mapping.get("fichier_contexte_general"))
        if path is not None and path.name.lower() == expected_name.lower():
            _append_unique(candidates, path)
    return candidates


def _context_candidates(infos: dict[str, Any], base_dir: Path | None, filename: str) -> list[Path]:
    candidates = _configured_context_paths(infos, filename)
    for directory in _candidate_dirs(infos, base_dir):
        _append_unique(candidates, directory / filename)
    return candidates


def _read_json_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        if not path.exists() or not path.is_file():
            return None, "absent"
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None, "json_non_objet"
        if not any(str(data.get(field) or "").strip() for field in PHOTO_CONTEXT_FIELDS):
            return None, "contexte_vide"
        return data, ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _historical_context_from_infos(infos: dict[str, Any]) -> dict[str, str]:
    return {field: str(infos.get(field) or "").strip() for field in PHOTO_CONTEXT_FIELDS}


def _active_context_from_json(data: dict[str, Any]) -> dict[str, str]:
    return {field: str(data.get(field) or "").strip() for field in PHOTO_CONTEXT_FIELDS}


def resolve_photo_context(
    infos: dict[str, Any] | None,
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve the active photo context using photos JSON, legacy JSON, then infos fields."""
    infos = infos if isinstance(infos, dict) else {}
    base_path = Path(base_dir) if base_dir is not None else None
    attempts: list[dict[str, str]] = []

    levels = (
        ("contexte_general_photos", "contexte_general_photos.json"),
        ("contexte_general", "contexte_general.json"),
    )
    for level, filename in levels:
        for candidate in _context_candidates(infos, base_path, filename):
            data, error = _read_json_object(candidate)
            attempts.append({
                "level": level,
                "path": str(candidate),
                "status": "ok" if data is not None else error,
            })
            if data is not None:
                return {
                    "context": _active_context_from_json(data),
                    "source": level,
                    "source_path": str(candidate),
                    "attempts": attempts,
                }

    return {
        "context": _historical_context_from_infos(infos),
        "source": "infos_projet",
        "source_path": "",
        "attempts": attempts,
    }
