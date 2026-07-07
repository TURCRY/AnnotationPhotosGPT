from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import requests
from dotenv import load_dotenv
from app.server_locator import resolve_flask_base_url, request_with_endpoint_fallback


def _load_app_config() -> dict[str, Any]:
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_env_for_api_keys() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        os.getenv("LLM_ASSISTANT_ENV", ""),
        str(repo_root / "config" / ".env"),
        str(repo_root / ".env"),
    ]
    for p in candidates:
        p = (p or "").strip()
        if p and Path(p).exists():
            load_dotenv(p, override=False)


def _is_placeholder_api_key(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    u = v.upper()
    return ("PLACEHOLDER" in u) or (u in {"LOCAL_LLM_API_KEY", "LOCAL_LLM_API_KEY_PLACEHOLDER"})


def _resolve_server_base_url(appcfg: dict[str, Any]) -> str:
    server_url = (os.getenv("SERVER_URL") or "").strip()
    if server_url:
        return resolve_flask_base_url(extra_candidates=[server_url])

    local_env = (os.getenv("LOCAL_LLM_BASE_URL") or "").strip()
    if local_env:
        return resolve_flask_base_url(extra_candidates=[local_env])

    local_cfg = (appcfg.get("local_llm") or {}) if isinstance(appcfg, dict) else {}
    cfg_url = str(local_cfg.get("base_url") or "").strip()
    if cfg_url:
        return resolve_flask_base_url(extra_candidates=[cfg_url])

    return resolve_flask_base_url()


def _resolve_api_key(appcfg: dict[str, Any]) -> str:
    _load_env_for_api_keys()

    env_key = (os.getenv("LOCAL_LLM_API_KEY") or "").strip()
    if env_key and not _is_placeholder_api_key(env_key):
        return env_key

    local_cfg = (appcfg.get("local_llm") or {}) if isinstance(appcfg, dict) else {}
    cfg_key = str(local_cfg.get("api_key") or "").strip()
    if cfg_key and not _is_placeholder_api_key(cfg_key):
        return cfg_key

    return ""


def _resolve_timeout(appcfg: dict[str, Any]) -> float:
    local_cfg = (appcfg.get("local_llm") or {}) if isinstance(appcfg, dict) else {}
    try:
        return float(local_cfg.get("timeout") or 30)
    except Exception:
        return 30.0


def create_affaire_server_compatible(project_id: str, nom: str = "", affaires_root: str = "") -> dict[str, Any]:
    """Appelle la route serveur POST /create_affaire (compatibilité opérationnelle).

    Fail-safe: renvoie toujours un dict et ne propage pas d'exception.
    """
    project_id = (project_id or "").strip()
    if not project_id:
        return {"ok": False, "error": "project_id vide"}

    appcfg = _load_app_config()
    base_url = _resolve_server_base_url(appcfg)
    api_key = _resolve_api_key(appcfg)
    timeout = _resolve_timeout(appcfg)

    payload = {
        "project_id": project_id,
        "id_affaire": project_id,
        "nom": (nom or "").strip(),
        "affaires_root": (affaires_root or "").strip(),
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    try:
        r = request_with_endpoint_fallback(
            "POST",
            "/create_affaire",
            extra_candidates=[base_url],
            json=payload,
            headers=headers,
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"HTTP create_affaire impossible: {exc}", "project_id": project_id}

    try:
        data = r.json() if r.text else {}
    except Exception:
        data = {}

    if r.ok and isinstance(data, dict) and data.get("ok") is True:
        return data

    err = data.get("error") if isinstance(data, dict) else ""
    if not err:
        err = (r.text or "").strip() or f"HTTP {r.status_code}"

    return {
        "ok": False,
        "error": err,
        "project_id": project_id,
        "status_code": r.status_code,
    }
