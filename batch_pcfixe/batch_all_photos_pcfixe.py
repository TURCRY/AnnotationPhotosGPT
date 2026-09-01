#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
batch_all_photos_pcfixe.py

PASS 1 : VLM (description_vlm_batch) en batch
PASS 1bis : ASR dictées différées
PASS 2 : LLM (libellé / commentaire) photo par photo

Pré-requis:
- requests
- local_llm_client.py dans le même dossier (ou PYTHONPATH)
"""

from __future__ import annotations
import re
import argparse
import csv
import json
import hashlib
import shutil
import shlex
import subprocess

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sys
import uuid, threading
import requests
sys.path.insert(0, str(Path(__file__).parent))
from local_llm_client import LocalLLMClient
import logging
from logging.handlers import RotatingFileHandler
import os, socket
from urllib.parse import urlparse

import time, random
import requests


log = logging.getLogger("batch_all_photos_pcfixe")
log.setLevel(logging.INFO)

_handler = RotatingFileHandler(
    filename="batch_all_photos_pcfixe.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_handler)
log.propagate = False

BATCH_ENV_PATH = Path(__file__).with_name("batch.env")
DEFAULT_LOCAL_FLASK_BASE_URL = "http://127.0.0.1:5050"
PHOTOS_CSV_BUSINESS_FINGERPRINT_COLUMNS = [
    "photo_rel_native",
    "retenue",
    "annotation_validee",
    "description_vlm_ui",
    "libelle_propose_ui",
    "commentaire_propose_ui",
    "dictee_asr_text",
    "dictee_asr_status",
    "dictee_asr_ts",
]

UI_DEFAULTS = {
    "annotation_validee": "0",
    "dictee_audio_path_pcfixe": "",
    "dictee_audio_sha256": "",
    "dictee_audio_size": "",
    "dictee_asr_status": "",
    "dictee_asr_text": "",
    "dictee_asr_error": "",
    "dictee_asr_ts": "",
    "dictee_asr_csv_path_pcfixe": "",
    "dictee_asr_photo_csv_path_pcfixe": "",
    "dictee_llm_status": "",
    "dictee_llm_asr_ts": "",
    "dictee_llm_error": "",
    "dictee_llm_ts": "",
}

ASR_RECONCILE_STATUSES = {"SUBMITTED", "LOCAL_PENDING"}
ASR_CSV_FIELDNAMES = ["start", "end", "speaker", "text"]
DEBRIEF_DICTEES_FILENAME = "debrief_dictees.csv"
DEBRIEF_DICTEES_MANIFEST_FILENAME = "debrief_dictees.manifest.json"
DICTATION_ID_RE = re.compile(r"dictee_\d{8}_\d{6}_\d+_[0-9a-fA-F]{8}")
NAS_SSH_ALIAS = "nas"
NAS_SSH_ROOT = "/volume1/Affaires"
NAS_SSH_INSTALL_CONFIG = Path(r"C:\Users\Nicolas\.ssh\config")
NAS_SSH_OPTS = (
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "NumberOfPasswordPrompts=0",
    "-o", "LogLevel=ERROR",
)
NAS_SSH_PREFLIGHT_TIMEOUT = 15
NAS_SSH_COMMAND_TIMEOUT = 30
NAS_SSH_TRANSFER_TIMEOUT = 120
BUSINESS_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


class BatchSyncError(RuntimeError):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}


def _normalize_flask_base_url(raw: str, source: str) -> str:
    base_url = str(raw or "").strip()
    if not base_url:
        return ""
    base_url = base_url.rstrip("/")
    if "://" not in base_url:
        base_url = "http://" + base_url
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError(f"Base URL Flask/VLM invalide ({source}): {base_url!r}")
    return base_url


def resolve_flask_base_url(config_value: str = "") -> str:
    for source, raw in (
        ("local_llm.base_url", config_value),
        ("LOCAL_LLM_BASE_URL", os.getenv("LOCAL_LLM_BASE_URL", "")),
        ("default", DEFAULT_LOCAL_FLASK_BASE_URL),
    ):
        base_url = _normalize_flask_base_url(raw, source)
        if base_url:
            return base_url
    raise RuntimeError(
        "Base URL Flask/VLM vide: renseigner local_llm.base_url ou LOCAL_LLM_BASE_URL."
    )

HEADER_BATCH = [
  # clé de jointure
  "photo_rel_native",

  # disponibilité / chemins PC fixe
  "chemin_photo_native_pcfixe",
  "chemin_photo_reduite_pcfixe",
  "photo_disponible_pcfixe",
  "date_copie_pcfixe",

  # sorties “métier” batch
  "description_vlm_batch",
  "libelle_propose_batch",
  "commentaire_propose_batch",
  "dictee_asr_text",
  "dictee_dictation_ids",
  "dictee_asr_csv_paths",
  "dictee_audio_paths",

  # traçabilité exécution
  "batch_status",     # OK / ERR / SKIP / EMPTY
  "batch_id",
  "job_id",
  "batch_ts",

  # diagnostics VLM (optionnels mais ok en batch)
  "vlm_status",
  "vlm_batch_id",
  "vlm_batch_ts", 
  "vlm_err", 
  "vlm_prompt_ctx_len", 
  "vlm_img_bytes", 
  "vlm_mode", 
  "vlm_call_id",

  # diagnostics LLM (optionnels mais ok en batch)
  "llm_err_lib",
  "llm_err_com",
  "llm_http_status_lib",
  "llm_http_status_com",
  "llm_trace_lib",
  "llm_trace_com",

   # sujets (si vous les exploitez réellement)
  "sujets_ids",
  "sujets_scores",
  "sujets_method",
  "sujets_justif",
]

RESET_VLM_PLUS_FIELDS = [
  "description_vlm_batch",
  "vlm_status",
  "vlm_err",
  "vlm_batch_id",
  "vlm_batch_ts",
  "batch_status",
  "batch_id",
  "job_id",
  "batch_ts",
  "libelle_propose_batch",
  "commentaire_propose_batch",
  "llm_err_lib",
  "llm_err_com",
  "llm_http_status_lib",
  "llm_http_status_com",
  "llm_trace_lib",
  "llm_trace_com",
]

RESET_LLM_FIELDS = [
  "libelle_propose_batch",
  "commentaire_propose_batch",
  "llm_err_lib",
  "llm_err_com",
  "llm_http_status_lib",
  "llm_http_status_com",
  "llm_trace_lib",
  "llm_trace_com",
  "batch_status",
  "batch_id",
  "job_id",
  "batch_ts",
]

_last_call_ts = 0.0

def throttle(min_interval_s: float):
    global _last_call_ts
    now = time.time()
    wait = (_last_call_ts + min_interval_s) - now
    if wait > 0:
        time.sleep(wait)
    _last_call_ts = time.time()



# -------------------------
# Constantes VLM
# -------------------------

def vlm_limits(night: bool) -> tuple[int, int, int]:
    if night:
        return (24 * 1024 * 1024, 8 * 1024 * 1024, 12)
    return (22 * 1024 * 1024, 8 * 1024 * 1024, 8)


# -------------------------
# Utils généraux
# -------------------------

def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def parse_ts_or_none(raw: Any) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def is_weak_libelle(text: str) -> bool:
    s = " ".join(str(text or "").strip().lower().split())
    if len(s) < 8:
        return True
    weak_patterns = [
        "vue generale",
        "vue générale",
        "element non precise",
        "élément non précisé",
        "ensemble non precise",
        "ensemble non précisé",
        "vue d'ensemble",
        "vue d’ensemble",
        "photo non exploitable",
        "element non identifié",
        "élément non identifié",
    ]
    return any(pattern in s for pattern in weak_patterns)

def weak_libelle_reason(text: str) -> str | None:
    s = " ".join(str(text or "").strip().lower().split())
    if len(s) < 8:
        return "too_short"
    if is_weak_libelle(text):
        return "boilerplate"
    return None

def weak_commentaire_reason(text: str, desc_vlm: str = "") -> str | None:
    s = " ".join(str(text or "").strip().lower().split())
    d = " ".join(str(desc_vlm or "").strip().lower().split())

    if len(s) < 24:
        return "too_short"

    weak_patterns = [
        "photo non exploitable",
        "aucun element precis",
        "aucun élément précis",
        "pas d'information exploitable",
        "commentaire non precise",
        "commentaire non précisé",
        "vue generale",
        "vue générale",
        "element non precise",
        "élément non précisé",
    ]
    if any(pattern in s for pattern in weak_patterns):
        return "boilerplate"

    sentences = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"[.!?]+", s) if part.strip()]
    if len(sentences) >= 2 and len(set(sentences)) < len(sentences):
        return "repetition"

    if d and (s == d or (s in d or d in s) and abs(len(s) - len(d)) <= 20):
        return "no_contextual_added_value"

    return None

def is_weak_commentaire(text: str, desc_vlm: str = "") -> bool:
    return weak_commentaire_reason(text, desc_vlm) is not None

def append_trace(prev: Any, msg: str, max_len: int = 1200) -> str:
    base = str(prev or "").strip()
    out = f"{base}\n{msg}" if base else msg
    return out[-max_len:]

def die(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code

def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def resolve_batch_prompt_path(prompts_dir: Path) -> Path:
    for filename in (
        "prompt_gpt_batch_only_updated.json",
        "prompt_gpt_batch_only.json",
        "prompt_gpt.json",
    ):
        candidate = prompts_dir / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Aucun template de prompt disponible dans {prompts_dir}")


def resolve_transcript_window(infos: dict, cfg: dict, key: str) -> tuple[float, float]:
    plages = infos.get("plages_utilisees") or {}
    project_window = plages.get(key) or {}
    before = project_window.get("avant")
    after = project_window.get("apres")
    if before is not None and after is not None:
        return float(before), float(after)

    config_window = ((cfg.get("default_delays") or {}).get(key) or {})
    before = config_window.get("before")
    after = config_window.get("after")
    if before is not None and after is not None:
        return float(before), float(after)

    raise RuntimeError(
        f"Fenetre temporelle {key} absente de plages_utilisees et de config_llm.default_delays"
    )

def _job_id_component(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return text or "unknown"

def _manual_annotation_job_id(id_affaire: str, id_captation: str, *, prefix: str = "manual_annotation") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return (
        f"{prefix}_"
        f"{_job_id_component(id_affaire)}_"
        f"{_job_id_component(id_captation)}_"
        f"{ts}_{suffix}"
    )

def _job_id_from_mapping(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("job_id", "batch_job_id", "annotation_job_id"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    for key in ("runtime_manifest", "manifest", "spooler_manifest", "batch_manifest"):
        value = _job_id_from_mapping(data.get(key))
        if value:
            return value
    for key in ("runtime_manifest_path", "manifest_path", "source_manifest"):
        path_text = str(data.get(key) or "").strip()
        if not path_text:
            continue
        try:
            value = _job_id_from_mapping(read_json(Path(path_text)))
        except Exception:
            value = ""
        if value:
            return value
    return ""

def resolve_annotation_batch_job_id(
    *,
    infos: dict[str, Any],
    cli_job_id: str,
    id_affaire: str,
    id_captation: str,
) -> str:
    job_id = _job_id_from_mapping(infos)
    if not job_id:
        job_id = str(cli_job_id or "").strip()
    if not job_id:
        for env_key in ("SPOOLER_JOB_ID", "ANNOTATION_BATCH_JOB_ID", "BATCH_JOB_ID", "JOB_ID"):
            job_id = str(os.getenv(env_key) or "").strip()
            if job_id:
                break
    if not job_id:
        job_id = _manual_annotation_job_id(id_affaire, id_captation)
    if not str(job_id or "").strip():
        raise RuntimeError("BATCH_JOB_ID_INVALID: job_id vide pour execution annotation_photos_batch")
    return str(job_id).strip()

def norm_bool(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "oui", "ok", "y")

def safe_float(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None

def resolve_img_path(row: dict) -> Path | None:
    base = (row.get("chemin_photo_reduite_pcfixe") or "").strip().strip('"')
    name = (row.get("nom_fichier_image") or "").strip().strip('"')

    if not base or not name:
        return None

    # Normalisation séparateurs / fin de chemin
    base = base.rstrip("\\/")

    # Mapping UNC -> local (PC fixe)
    # Ajustez si nécessaire (IP, partage, lettre, etc.)
    if base.lower().startswith(r"\\192.168.0.155\affaires".lower()):
        base = "C:\\Affaires" + base[len(r"\\192.168.0.155\Affaires") :]

    try:
        p = Path(base) / name
    except Exception:
        return None

    return p if p.exists() else None


def _result_name(r: dict) -> str | None:
    keys = ("filename", "file", "name", "original_filename",
            "input_filename", "uploaded_filename", "path", "image")
    for key in keys:
        v = r.get(key)
        if isinstance(v, str) and v:
            return v.replace("\\", "/").split("/")[-1]
        if isinstance(v, dict):
            for k2 in keys:
                v2 = v.get(k2)
                if isinstance(v2, str) and v2:
                    return v2.replace("\\", "/").split("/")[-1]
    return None

def upsert_batch_row(df, row_dict):
    key = row_dict["photo_rel_native"]
    if "photo_rel_native" not in df.columns:
        df = df.reindex(columns=HEADER_BATCH)
    df = df.set_index("photo_rel_native", drop=False)
    df.loc[key, list(row_dict.keys())] = list(row_dict.values())
    df = df.reset_index(drop=True)
    return df

def load_or_init_batch(path: Path) -> list[dict]:
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            br = list(csv.DictReader(f, delimiter=";"))
    else:
        br = []
    # garantir colonnes
    if not br:
        return []
    for r in br:
        for c in HEADER_BATCH:
            r.setdefault(c, "")
    return br


def reset_fields_in_row(row: Dict[str, Any], fields: List[str], *, presets: Optional[Dict[str, Any]] = None) -> None:
    for field in fields:
        row[field] = ""
    if presets:
        for key, value in presets.items():
            row[key] = value

def write_json(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_env_value_from_file(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() != key:
                continue
            return v.strip().strip('"').strip("'")
    except Exception:
        return ""
    return ""


def resolve_openai_api_key() -> str:
    existing = str(os.getenv("OPENAI_API_KEY", "") or "").strip()
    if existing:
        return existing

    if not BATCH_ENV_PATH.exists():
        return ""

    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        load_dotenv = None

    if load_dotenv is not None:
        try:
            load_dotenv(BATCH_ENV_PATH, override=False)
        except Exception:
            pass
        existing = str(os.getenv("OPENAI_API_KEY", "") or "").strip()
        if existing:
            return existing

    return _read_env_value_from_file(BATCH_ENV_PATH, "OPENAI_API_KEY")


def _is_placeholder_secret(value: str) -> bool:
    s = str(value or "").strip()
    if not s:
        return True
    return "PLACEHOLDER" in s.upper()


def resolve_local_llm_api_key(config_value: str = "") -> str:
    existing = str(os.getenv("LOCAL_LLM_API_KEY", "") or "").strip()
    if existing:
        return existing

    if BATCH_ENV_PATH.exists():
        try:
            from dotenv import load_dotenv  # type: ignore
        except Exception:
            load_dotenv = None

        if load_dotenv is not None:
            try:
                load_dotenv(BATCH_ENV_PATH, override=False)
            except Exception:
                pass
            existing = str(os.getenv("LOCAL_LLM_API_KEY", "") or "").strip()
            if existing:
                return existing

        existing = _read_env_value_from_file(BATCH_ENV_PATH, "LOCAL_LLM_API_KEY")
        if existing:
            return existing

    config_value = str(config_value or "").strip()
    if not _is_placeholder_secret(config_value):
        return config_value

    return ""

def _set_llm_err(b: dict, which: str, e: Exception, resp_text: str | None = None, http_status: int | None = None):
    key = (which or "").strip().lower()
    if key not in ("lib", "com"):
        key = "lib"
    msg = (str(e) or repr(e))[:600]
    b[f"llm_err_{key}"] = msg
    b[f"llm_http_status_{key}"] = (str(http_status) if http_status is not None else "")
    b[f"llm_trace_{key}"] = (resp_text[:1200] if resp_text else "")
    b["batch_ts"] = now_ts()


LLM_CONTENT_REJECT_MARKERS = (
    "server_reject",
    "json_incomplet",
    "json_invalide",
    "invalid_json",
    "json invalid",
    "ancrage",
    "ancrage_absent",
    "nombre_mots",
    "longueur",
    "format",
    "lib_empty",
    "com_empty",
)


def is_llm_content_reject(e: Exception | str) -> bool:
    if isinstance(
        e,
        (
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.RequestException,
        ),
    ):
        return False
    msg = (str(e) or repr(e)).strip().lower()
    return any(marker in msg for marker in LLM_CONTENT_REJECT_MARKERS)


def llm_status_after_exception(which: str, e: Exception | str, *, lib_ok: bool = False) -> str:
    key = (which or "").strip().upper()
    if key == "COM" and lib_ok and is_llm_content_reject(e):
        return "OK_LIB_COM_WEAK"
    if key == "LIB" and is_llm_content_reject(e):
        return "WEAK_LIB"
    return "OK_LIB_ERR_COM" if key == "COM" and lib_ok else "ERR_LIB"


def clear_llm_active_error(b: dict, which: str, reason: str) -> None:
    key = (which or "").strip().lower()
    if key not in ("lib", "com"):
        key = "lib"
    prev = str(b.get(f"llm_err_{key}") or "").strip()
    prev_http = str(b.get(f"llm_http_status_{key}") or "").strip()
    if prev or prev_http:
        b[f"llm_trace_{key}"] = append_trace(
            b.get(f"llm_trace_{key}"),
            f"[previous_llm_error_cleared reason={reason} http={prev_http or '-'} err={prev[:300]}]",
        )
    b[f"llm_err_{key}"] = ""
    b[f"llm_http_status_{key}"] = ""


def llm_rerun_plan_for_status(batch_status: str, lib_existing: str = "", com_existing: str = "") -> tuple[bool, bool]:
    bs = (batch_status or "").strip().upper()
    if bs == "WEAK_LIB":
        return True, not bool(str(com_existing or "").strip())
    if bs == "OK_LIB_COM_WEAK":
        return False, True
    return False, False


def reinterpret_llm_weak_status(row: dict[str, Any]) -> tuple[str, str]:
    current = str(row.get("batch_status") or "").strip().upper()
    vlm_status = str(row.get("vlm_status") or "").strip().upper()
    desc = str(row.get("description_vlm_batch") or "").strip()
    if current.startswith("ERR_VLM") or vlm_status != "OK" or not desc:
        return current, "VLM absent ou invalide"

    lib = str(row.get("libelle_propose_batch") or "").strip()
    com = str(row.get("commentaire_propose_batch") or "").strip()
    err_lib = str(row.get("llm_err_lib") or "").strip()
    err_com = str(row.get("llm_err_com") or "").strip()

    if not lib:
        return "WEAK_LIB", "libelle manquant"
    if err_lib and is_llm_content_reject(err_lib):
        return "WEAK_LIB", f"rejet libelle reprenable: {err_lib[:160]}"
    if not com:
        return "OK_LIB_COM_WEAK", "commentaire manquant"
    if err_com and is_llm_content_reject(err_com):
        return "OK_LIB_COM_WEAK", f"rejet commentaire reprenable: {err_com[:160]}"
    return current, ""


def purge_vlm(base_url: str, api_key: str, *, timeout: int = 30, wait_step: float = 1.0) -> bool:
    """
    Demande au serveur Flask de purger le VLM (libérer VRAM / éviter rémanence VLM->LLM).
    - Retourne True si purge ok.
    - Retourne False si timeout (VLM resté busy) ou erreur non récupérable.
    """
    url = resolve_flask_base_url(base_url) + "/vision/purge_vlm"
    headers = {"x-api-key": api_key}

    t0 = time.time()
    attempts = 0

    while True:
        attempts += 1
        try:
            r = requests.post(url, headers=headers, timeout=10)
        except Exception as e:
            print(f"[VLM PURGE] erreur réseau: {e}")
            return False

        # 200 OK -> purge effectuée
        if r.status_code == 200:
            try:
                js = r.json()
            except Exception:
                js = {}
            print(f"[VLM PURGE] OK attempts={attempts} resp={js}")
            return True

        # 409 -> VLM busy, on attend et on retente jusqu'au timeout global
        if r.status_code == 409:
            elapsed = time.time() - t0
            if elapsed >= timeout:
                try:
                    js = r.json()
                except Exception:
                    js = {"raw": r.text[:200]}
                print(f"[VLM PURGE] TIMEOUT after {elapsed:.1f}s attempts={attempts} last={js}")
                return False

            # backoff léger (peut être augmenté progressivement si besoin)
            try:
                js = r.json()
                active = js.get("active")
            except Exception:
                active = None

            print(f"[VLM PURGE] busy (active={active}) -> retry in {wait_step:.1f}s (elapsed={elapsed:.1f}s)")
            time.sleep(wait_step)
            continue

        # autres codes = erreur
        try:
            js = r.json()
        except Exception:
            js = {"raw": r.text[:300]}
        print(f"[VLM PURGE] ERROR status={r.status_code} resp={js}")
        return False

LLM_INFLIGHT = threading.BoundedSemaphore(value=1)  # MAX_INFLIGHT_GLOBAL = 1
RETRY_HTTP = {408, 429, 500, 502, 503, 504}

def _should_retry_http(status: int | None) -> bool:
    return (status in RETRY_HTTP) if status is not None else False

def generate_with_retry(
    client,
    *,
    llm_backend: str,
    prompt: str,
    system: str,
    model: str,
    openai_api_key: str,
    temperature: float,
    max_tokens: int,
    task: str,
    expect_json: bool,
    salient_families,
    prefer_dictee: bool,
    b: dict,
    which: str,                 # "LIB" ou "COM"
    max_attempts: int = 3,
    base_sleep: float = 0.6,
    overrides: dict | None = None,
    marge: int | None = None,
    min_prompt_tokens: int | None = None,
    dictee_asr_text: str = "",
):
    last_exc = None

    # MAX_INFLIGHT_GLOBAL = 1 : aucune autre requête ne part tant que celle-ci n'a pas fini (y compris retries)
    with LLM_INFLIGHT:
        for attempt in range(1, max_attempts + 1):
            request_id = f"{which}-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}"

            try:
                throttle(0.8 if which == "LIB" else 2.0)
                print(f"[BATCH] SEND {request_id}")

                if llm_backend == "openai":
                    if not openai_api_key:
                        raise RuntimeError("OPENAI_API_KEY_MISSING")
                    if client is None:
                        from openai import OpenAI
                        client = OpenAI(api_key=openai_api_key)
                    response = client.chat.completions.create(
                        model=model or "gpt-4o-mini",
                        temperature=float(temperature),
                        max_tokens=int(max_tokens),
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                    )
                    out = str(response.choices[0].message.content or "").strip()
                else:
                    out = client.generate(
                        prompt=prompt,
                        system=system,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        task=task,
                        expect_json=expect_json,
                        salient_families=salient_families,
                        prefer_dictee=prefer_dictee,
                        dictee_asr_text=dictee_asr_text,
                        request_id=request_id,
                        overrides=overrides,
                        marge=marge,
                        min_prompt_tokens=min_prompt_tokens,
                    ).strip()

                print(f"[BATCH] RECV {request_id}")

                if not out:
                    raise ValueError(f"{which}_EMPTY")

                # succès après retry
                if attempt > 1:
                    k = f"llm_trace_{which.lower()}"
                    b[k] = (b.get(k, "") + f"\n[retry_ok attempt={attempt} rid={request_id}]")[-1200:]

                return out

            except requests.exceptions.HTTPError as e:
                last_exc = e
                r = getattr(e, "response", None)
                status = getattr(r, "status_code", None)
                headers = getattr(r, "headers", {}) if r is not None else {}
                srv_rid = headers.get("X-Request-Id") or request_id

                _set_llm_err(
                    b, which, e,
                    resp_text=(getattr(r, "text", None) if r is not None else None),
                    http_status=status
                )

                # Retry-After si fourni
                ra = 0
                try:
                    ra = int(headers.get("Retry-After") or 0)
                except Exception:
                    ra = 0

                if status in (429, 503) and attempt < max_attempts:
                    sleep_s = (ra if ra > 0 else (base_sleep * (2 ** (attempt - 1))))
                    sleep_s += random.uniform(0.0, 0.25)
                    k = f"llm_trace_{which.lower()}"
                    b[k] = (b.get(k, "") + f"\n[retry_http {status} attempt={attempt} rid={srv_rid} sleep={sleep_s:.2f}s]")[-1200:]
                    time.sleep(sleep_s)
                    continue

                raise

            except (requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.RequestException,
                    ValueError) as e:
                last_exc = e
                _set_llm_err(b, which, e)

                if attempt == max_attempts:
                    raise

                sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0.0, 0.25)
                time.sleep(sleep_s)
                continue
            except Exception as e:
                last_exc = e
                _set_llm_err(b, which, e)
                if attempt == max_attempts:
                    raise
                sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0.0, 0.25)
                time.sleep(sleep_s)
                continue

    raise last_exc or RuntimeError("generate_with_retry: failed without exception")


# -------------------------
# CSV helpers
# -------------------------

def atomic_write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    tmp = path.with_suffix(".tmp")
    bak = path.with_suffix(".bak")

    if path.exists():
        bak.write_bytes(path.read_bytes())

    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    tmp.replace(path)


def atomic_write_csv_timestamp_backup(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str], label: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.{ts}.{label}.bak")
    tmp = path.with_suffix(".tmp")

    if path.exists():
        backup.write_bytes(path.read_bytes())

    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    tmp.replace(path)
    return backup


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def photos_csv_business_fingerprint(rows: list[dict[str, Any]]) -> str:
    columns = PHOTOS_CSV_BUSINESS_FINGERPRINT_COLUMNS
    row_lines = []
    for row in rows:
        values = []
        for column in columns:
            value = str(row.get(column, "") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            values.append(value)
        row_lines.append("\x1f".join(values))
    payload = "annotation_batch_business_v1\n" + "\x1f".join(columns) + "\n" + "\x1e".join(sorted(row_lines))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def photos_csv_business_fingerprint_from_file(path: Path) -> str:
    rows, fieldnames = read_csv_semicolon(path)
    if not rows:
        raise RuntimeError(f"BATCH_OUTPUT_INVALID: photos.csv sans lignes: {path}")
    if "photo_rel_native" not in set(fieldnames):
        raise RuntimeError(f"BATCH_OUTPUT_INVALID: colonne manquante dans photos.csv: photo_rel_native")
    return photos_csv_business_fingerprint(rows)


def read_csv_semicolon(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def _norm_path_text(value: Any) -> str:
    return str(value or "").strip().replace("/", "\\").rstrip("\\")


def _path_rel_under(path_value: Any, root_value: Any) -> Optional[str]:
    path_text = _norm_path_text(path_value)
    root_text = _norm_path_text(root_value)
    if not path_text or not root_text:
        return None
    path_cmp = path_text.lower()
    root_cmp = root_text.lower()
    if path_cmp == root_cmp:
        return ""
    prefix = root_cmp + "\\"
    if path_cmp.startswith(prefix):
        return path_text[len(root_text):].lstrip("\\")
    return None


def _join_root(root_value: Any, rel_value: str) -> Path:
    root_text = str(root_value or "").strip().rstrip("\\/")
    rel_text = str(rel_value or "").strip().replace("\\", os.sep).replace("/", os.sep)
    return Path(root_text) / rel_text if rel_text else Path(root_text)


def _roots_for_sync(infos: dict[str, Any], pc: dict[str, Any], id_affaire: str) -> tuple[str, str]:
    roots = infos.get("roots") or {}
    pc_root = (
        pc.get("root_affaires")
        or roots.get("pcfixe_local")
        or os.getenv("PCFIXE_AFFAIRES_ROOT")
        or r"C:\Affaires"
    )
    nas_root = (
        roots.get("nas")
        or os.getenv("NAS_AFFAIRES_ROOT")
        or r"\\192.168.1.20\Affaires"
    )
    if _norm_path_text(pc_root).startswith("\\\\"):
        pc_root = os.getenv("PCFIXE_AFFAIRES_ROOT") or r"C:\Affaires"
    if id_affaire:
        nas_parts = [p for p in _norm_path_text(nas_root).split("\\") if p]
        pc_parts = [p for p in _norm_path_text(pc_root).split("\\") if p]
        if nas_parts and nas_parts[-1].lower() == id_affaire.lower() and (not pc_parts or pc_parts[-1].lower() != id_affaire.lower()):
            pc_root = str(Path(str(pc_root)) / id_affaire)
    return str(pc_root).rstrip("\\/"), str(nas_root).rstrip("\\/")


def _counterpart_path(path_value: Path, from_root: str, to_root: str) -> Optional[Path]:
    rel = _path_rel_under(path_value, from_root)
    if rel is None:
        return None
    return _join_root(to_root, rel)


def _local_counterpart_if_available(path_value: Path, infos: dict[str, Any], pc: dict[str, Any], id_affaire: str) -> Path:
    try:
        if path_value.exists():
            return path_value
    except OSError:
        pass
    except PermissionError:
        pass
    try:
        pc_root, nas_root = _roots_for_sync(infos, pc, id_affaire)
        local = _counterpart_path(path_value, nas_root, pc_root)
    except Exception:
        local = None
    if local and local.exists():
        return local
    return path_value


def load_batch_context_general(
    infos: dict[str, Any],
    pc: dict[str, Any],
    id_affaire: str,
) -> tuple[dict[str, Any], str]:
    historical_context = {
        "mission": str(infos.get("mission") or "").strip(),
        "system": str(infos.get("system") or "").strip(),
        "user": str(infos.get("user") or "").strip(),
        "vlm_system": str(infos.get("vlm_system") or "").strip(),
        "vlm_user": str(infos.get("vlm_user") or "").strip(),
    }
    recognized_context_fields = ("mission", "system", "user", "vlm_system", "vlm_user", "etat_avancement")
    base_dirs: list[Path] = []
    for raw_path in (
        pc.get("fichier_contexte_general"),
        infos.get("fichier_contexte_general"),
        pc.get("fichier_transcription"),
        infos.get("fichier_transcription"),
    ):
        text = str(raw_path or "").strip()
        if not text:
            continue
        path = Path(text)
        base_dirs.append(path if path.suffix == "" else path.parent)

    seen: set[str] = set()
    candidates: list[Path] = []
    for filename in ("contexte_general_photos.json", "contexte_general.json"):
        for base_dir in base_dirs:
            candidate = base_dir / filename
            key = str(candidate).lower()
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)

    for candidate in candidates:
        ctx_path = _local_counterpart_if_available(candidate, infos, pc, id_affaire)
        exists, error = _path_exists_safe(ctx_path)
        if not exists:
            if error:
                log.warning("Contexte general inaccessible: path=%s error=%s", str(ctx_path), error)
            continue
        try:
            data = read_json(ctx_path)
        except Exception as exc:
            log.warning("Contexte general invalide ignore: path=%s error=%s", str(ctx_path), exc)
            continue
        if not isinstance(data, dict):
            log.warning("Contexte general invalide ignore: path=%s error=JSON non objet", str(ctx_path))
            continue
        if not any(str(data.get(field) or "").strip() for field in recognized_context_fields):
            log.warning("Contexte general invalide ignore: path=%s error=aucun champ contextuel reconnu non vide", str(ctx_path))
            continue
        return data, str(ctx_path)

    return historical_context, "infos_projet.json"


def batch_context_mission(ctx_general: dict[str, Any]) -> str:
    return str(ctx_general.get("mission") or "").strip()


def _path_exists_safe(path_value: Path) -> tuple[bool, str]:
    try:
        return path_value.exists(), ""
    except (OSError, PermissionError) as exc:
        return False, str(exc)


def _file_mtime_safe(path_value: Path) -> float:
    try:
        return path_value.stat().st_mtime
    except Exception:
        return 0.0


def _require_business_path(path_value: Path, id_affaire: str, id_captation: str, label: str) -> None:
    text = _norm_path_text(path_value).lower()
    if id_affaire and id_affaire.lower() not in text:
        raise RuntimeError(f"INVALID_JOB_CONTRACT: {label} hors affaire {id_affaire}: {path_value}")
    if id_captation and id_captation.lower() not in text:
        raise RuntimeError(f"INVALID_JOB_CONTRACT: {label} hors captation {id_captation}: {path_value}")


def copy_file_atomic_verified(src: Path, dst: Path, error_code: str) -> str:
    try:
        if not src.exists():
            raise FileNotFoundError(str(src))
        src_hash = sha256_file(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + f".tmp.{os.getpid()}")
        shutil.copy2(src, tmp)
        actual_hash = sha256_file(tmp)
        if actual_hash != src_hash:
            try:
                tmp.unlink()
            except Exception:
                pass
            raise RuntimeError(f"hash source={src_hash} copie={actual_hash}")
        tmp.replace(dst)
        final_hash = sha256_file(dst)
        if final_hash != src_hash:
            raise RuntimeError(f"hash source={src_hash} destination={final_hash}")
        return final_hash
    except Exception as exc:
        raise RuntimeError(f"{error_code}: copie atomique impossible src={src} dst={dst}. {exc}") from exc


def _normalize_photo_rel(value: Any) -> str:
    return str(value or "").strip().replace("/", "\\").lower()


def _photo_rel_match_keys(value: Any) -> list[str]:
    key = _normalize_photo_rel(value)
    if not key:
        return []
    name = Path(key).name.lower()
    return [key] if name == key else [key, name]


def parse_only_photo_rel_targets(values: list[str] | None, csv_list: str | None) -> list[str]:
    raw: list[str] = []
    for value in values or []:
        if str(value or "").strip():
            raw.append(str(value).strip())
    for part in str(csv_list or "").split(","):
        if part.strip():
            raw.append(part.strip())
    seen: set[str] = set()
    targets: list[str] = []
    for value in raw:
        key = _normalize_photo_rel(value)
        if not key:
            continue
        if key in seen:
            raise RuntimeError(f"INVALID_JOB_CONTRACT: doublon --only-photo-rel: {value}")
        seen.add(key)
        targets.append(value)
    return targets


def _field_present(row: dict[str, Any], field: str) -> bool:
    return bool(str(row.get(field) or "").strip())


def _only_photo_rel_plan_for_batch_row(row: dict[str, Any]) -> dict[str, Any]:
    lib_missing = not _field_present(row, "libelle_propose_batch")
    com_missing = not _field_present(row, "commentaire_propose_batch")
    fields: list[str] = []
    if lib_missing:
        fields.append("libelle")
    if com_missing:
        fields.append("commentaire")
    return {
        "photo_rel_native": str(row.get("photo_rel_native") or "").strip(),
        "fields": fields,
        "run_lib": lib_missing,
        "run_com": com_missing,
        "vlm_calls": 0,
    }


def apply_only_photo_rel_filter(
    *,
    selected_idx: list[int],
    rows_ui: list[dict[str, Any]],
    batch_index: dict[str, dict[str, Any]],
    batch_existing_keys: set[str] | None = None,
    targets: list[str],
    id_affaire: str,
    id_captation: str,
) -> tuple[list[int], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if not targets:
        return selected_idx, {}, []

    ui_seen: dict[str, list[int]] = {}
    for idx, row in enumerate(rows_ui):
        for key in _photo_rel_match_keys(row.get("photo_rel_native")):
            ui_seen.setdefault(key, []).append(idx)

    batch_seen: dict[str, list[dict[str, Any]]] = {}
    for row in batch_index.values():
        for key in _photo_rel_match_keys(row.get("photo_rel_native")):
            batch_seen.setdefault(key, []).append(row)

    selected_set = set(selected_idx)
    target_keys = {_normalize_photo_rel(value): value for value in targets}
    selected_filtered: list[int] = []
    plans_by_key: dict[str, dict[str, Any]] = {}
    plans: list[dict[str, Any]] = []

    for key, original in target_keys.items():
        ui_matches = ui_seen.get(key, [])
        if not ui_matches:
            raise RuntimeError(f"INVALID_JOB_CONTRACT: photo absente de photos.csv: {original}")
        if len(ui_matches) > 1:
            raise RuntimeError(f"INVALID_JOB_CONTRACT: photo ambigue dans photos.csv: {original}")
        batch_matches = batch_seen.get(key, [])
        if not batch_matches or (batch_existing_keys is not None and key not in batch_existing_keys):
            raise RuntimeError(f"INVALID_JOB_CONTRACT: photo absente de photos_batch.csv: {original}")
        if len(batch_matches) > 1:
            raise RuntimeError(f"INVALID_JOB_CONTRACT: photo ambigue dans photos_batch.csv: {original}")

        row_idx = ui_matches[0]
        if row_idx not in selected_set:
            raise RuntimeError(f"INVALID_JOB_CONTRACT: photo cible hors selection metier normale: {original}")

        batch_row = batch_matches[0]
        for label, field in (
            ("photo native", "chemin_photo_native_pcfixe"),
            ("photo reduite", "chemin_photo_reduite_pcfixe"),
        ):
            value = str(batch_row.get(field) or "").strip()
            if value:
                _require_business_path(Path(value), id_affaire, id_captation, label)

        plan = _only_photo_rel_plan_for_batch_row(batch_row)
        for plan_key in _photo_rel_match_keys(batch_row.get("photo_rel_native")):
            plans_by_key[plan_key] = plan
        plans.append(plan)
        selected_filtered.append(row_idx)

    return selected_filtered, plans_by_key, plans


def _validate_remote_business_id(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not BUSINESS_ID_RE.fullmatch(text):
        raise RuntimeError(f"INVALID_JOB_CONTRACT: {label} invalide pour publication SSH: {value!r}")
    return text


def _remote_quote(path_value: str) -> str:
    return shlex.quote(path_value)


def _nas_ssh_config_path() -> Path:
    configured = str(os.getenv("NAS_SSH_CONFIG") or "").strip()
    if configured:
        return Path(configured)
    userprofile = str(os.getenv("USERPROFILE") or "").strip()
    if userprofile:
        return Path(userprofile) / ".ssh" / "config"
    return NAS_SSH_INSTALL_CONFIG


def _nas_ssh_args() -> list[str]:
    config_path = _nas_ssh_config_path()
    try:
        config_exists = config_path.exists()
    except PermissionError:
        config_exists = True
    if not config_exists:
        raise RuntimeError(f"NAS SSH config introuvable: {config_path}")
    return ["-F", str(config_path), *NAS_SSH_OPTS]


def _nas_ssh_creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        taskkill = subprocess.Popen(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_nas_ssh_creationflags(),
        )
        try:
            taskkill.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                taskkill.kill()
            except Exception:
                pass
    try:
        proc.kill()
    except Exception:
        pass


def _run_nas_process(argv: list[str], *, action: str, timeout_s: int, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    started = time.monotonic()
    print(f"[NAS_SSH] start action={action} argv={argv!r} timeout={timeout_s}")
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_nas_ssh_creationflags(),
    )
    try:
        stdout, stderr = proc.communicate(input=input_bytes, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        print(f"[NAS_SSH] timeout action={action} duration={duration:.1f}")
        _kill_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = b"", b""
        raise RuntimeError(f"NAS_PUBLISH_FAILED: timeout SSH action={action} duration={duration:.1f}s timeout={timeout_s}s") from exc
    duration = time.monotonic() - started
    print(f"[NAS_SSH] done action={action} rc={proc.returncode} duration={duration:.1f}")
    return subprocess.CompletedProcess(argv, int(proc.returncode or 0), stdout, stderr)


def _run_nas_ssh_config_probe() -> subprocess.CompletedProcess[bytes]:
    return _run_nas_process(
        ["ssh", *_nas_ssh_args(), "-G", NAS_SSH_ALIAS],
        action="ssh_config_probe",
        timeout_s=NAS_SSH_PREFLIGHT_TIMEOUT,
    )


def _run_nas_ssh(
    script: str,
    *,
    input_bytes: bytes | None = None,
    timeout_s: int | None = None,
    action: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    timeout_s = timeout_s or (NAS_SSH_TRANSFER_TIMEOUT if input_bytes is not None else NAS_SSH_COMMAND_TIMEOUT)
    action = action or ("ssh_transfer" if input_bytes is not None else "ssh_command")
    return _run_nas_process(
        ["ssh", *_nas_ssh_args(), NAS_SSH_ALIAS, script],
        input_bytes=input_bytes,
        action=action,
        timeout_s=timeout_s,
    )


def _nas_ssh_stdout(script: str, *, timeout_s: int = NAS_SSH_COMMAND_TIMEOUT, action: str = "ssh_command") -> str:
    proc = _run_nas_ssh(script, timeout_s=timeout_s, action=action)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        stdout = proc.stdout.decode("utf-8", "replace").strip()
        raise RuntimeError(stderr or stdout or f"ssh exit={proc.returncode}")
    return proc.stdout.decode("utf-8", "replace")


def _check_nas_ssh_ready() -> None:
    probe = _run_nas_ssh_config_probe()
    if probe.returncode != 0:
        stderr = probe.stderr.decode("utf-8", "replace").strip()
        stdout = probe.stdout.decode("utf-8", "replace").strip()
        raise RuntimeError(f"alias SSH {NAS_SSH_ALIAS!r} non resolu via config {_nas_ssh_config_path()}: {stderr or stdout or probe.returncode}")
    ok = _nas_ssh_stdout("printf SSH_OK", timeout_s=NAS_SSH_PREFLIGHT_TIMEOUT, action="ssh_preflight_ok")
    if ok != "SSH_OK":
        raise RuntimeError(f"test SSH inattendu: {ok!r}")
    sha = _nas_ssh_stdout("command -v sha256sum").strip()
    if not sha:
        raise RuntimeError("sha256sum indisponible sur le NAS")


def _nas_ssh_hash(path_value: str) -> str:
    q = _remote_quote(path_value)
    out = _nas_ssh_stdout(f"sha256sum {q}")
    return out.strip().split()[0].lower()


def _nas_ssh_size(path_value: str) -> int:
    q = _remote_quote(path_value)
    out = _nas_ssh_stdout(f"wc -c {q}")
    return int(out.strip().split()[0])


def _nas_ssh_exists(path_value: str) -> bool:
    q = _remote_quote(path_value)
    proc = _run_nas_ssh(f"test -e {q}")
    return proc.returncode == 0


def _nas_ssh_publish_file(src: Path, remote_dir: str, remote_name: str, expected_sha256: str) -> dict[str, Any]:
    if not src.exists():
        raise FileNotFoundError(f"source locale introuvable: {src}")
    expected_hash = str(expected_sha256 or "").strip().lower()
    local_hash = sha256_file(src)
    if local_hash != expected_hash:
        raise RuntimeError(f"hash source locale different pour {src}")
    local_size = src.stat().st_size
    target = f"{remote_dir}/{remote_name}"
    tmp = f"{remote_dir}/.{remote_name}.tmp.{uuid.uuid4().hex}"
    backup = ""
    try:
        _nas_ssh_stdout(f"mkdir -p {_remote_quote(remote_dir)}")
        data = src.read_bytes()
        proc = _run_nas_ssh(f"cat > {_remote_quote(tmp)}", input_bytes=data)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip() or f"copie tmp ssh exit={proc.returncode}")
        tmp_size = _nas_ssh_size(tmp)
        if tmp_size != local_size:
            raise RuntimeError(f"taille tmp distante differente pour {target}: expected={local_size} actual={tmp_size}")
        tmp_hash = _nas_ssh_hash(tmp)
        if tmp_hash != local_hash:
            raise RuntimeError(f"hash tmp distant different pour {target}: expected={local_hash} actual={tmp_hash}")
        if _nas_ssh_exists(target):
            backup = f"{target}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
            _nas_ssh_stdout(f"cp -p {_remote_quote(target)} {_remote_quote(backup)}")
        _nas_ssh_stdout(f"mv -f {_remote_quote(tmp)} {_remote_quote(target)}")
        final_size = _nas_ssh_size(target)
        if final_size != local_size:
            raise RuntimeError(f"taille finale distante differente pour {target}: expected={local_size} actual={final_size}")
        final_hash = _nas_ssh_hash(target)
        if final_hash != local_hash:
            raise RuntimeError(f"hash final distant different pour {target}: expected={local_hash} actual={final_hash}")
        return {
            "remote_path": target,
            "remote_sha256": final_hash,
            "remote_size": final_size,
            "backup_path": backup,
        }
    except Exception:
        try:
            _run_nas_ssh(f"rm -f {_remote_quote(tmp)}")
        except Exception:
            pass
        raise


def publish_batch_outputs_to_nas_ssh_fallback(
    *,
    photos_csv: Path,
    photos_batch_csv: Path,
    stamp_path: Path,
    id_affaire: str,
    id_captation: str,
    photos_csv_sha256: str,
    photos_batch_sha256: str,
    stamp_sha256: str,
) -> dict[str, Any]:
    affaire = _validate_remote_business_id(id_affaire, "affaire")
    captation = _validate_remote_business_id(id_captation, "captation")
    remote_dir = f"{NAS_SSH_ROOT}/{affaire}/AE_Expert_captations/{captation}/photos"
    _check_nas_ssh_ready()
    backups: list[str] = []
    photos_info = _nas_ssh_publish_file(photos_csv, remote_dir, "photos.csv", photos_csv_sha256)
    if photos_info.get("backup_path"):
        backups.append(str(photos_info["backup_path"]))
    batch_info = _nas_ssh_publish_file(photos_batch_csv, remote_dir, "photos_batch.csv", photos_batch_sha256)
    if batch_info.get("backup_path"):
        backups.append(str(batch_info["backup_path"]))
    stamp_info = _nas_ssh_publish_file(stamp_path, remote_dir, "photos_batch.csv.stamp", stamp_sha256)
    if stamp_info.get("backup_path"):
        backups.append(str(stamp_info["backup_path"]))
    return {
        "nas_publish_method": "ssh_fallback",
        "nas_publish_ssh_attempted": True,
        "nas_publish_ssh_error": "",
        "nas_publish_succeeded": True,
        "nas_publish_pending": False,
        "publish_pending": False,
        "photos_csv_nas_path": photos_info["remote_path"],
        "photos_csv_nas_sha256": photos_info["remote_sha256"],
        "photos_batch_csv_nas_path": batch_info["remote_path"],
        "photos_batch_csv_nas_sha256": batch_info["remote_sha256"],
        "photos_batch_stamp_nas_path": stamp_info["remote_path"],
        "photos_batch_stamp_nas_sha256": stamp_info["remote_sha256"],
        "nas_backup_paths": backups,
    }


def prepare_batch_sync_sources(
    *,
    infos: dict[str, Any],
    pc: dict[str, Any],
    photos_csv: Path,
    photos_batch_csv: Path,
    id_affaire: str,
    id_captation: str,
    is_dry: bool,
) -> tuple[Path, Path, dict[str, Any]]:
    pc_root, nas_root = _roots_for_sync(infos, pc, id_affaire)
    context: dict[str, Any] = {
        "sync_pc_root": pc_root,
        "sync_nas_root": nas_root,
        "affaire": id_affaire,
        "captation": id_captation,
        "id_affaire": id_affaire,
        "id_captation": id_captation,
        "nas_publish_attempted": False,
        "nas_publish_succeeded": False,
        "nas_publish_error": "",
        "nas_source_available": False,
        "nas_source_error": "",
        "nas_publish_pending": False,
        "photos_csv_source": "",
        "photos_csv_nas_path": "",
        "photos_csv_local_path": str(photos_csv),
        "photos_csv_pulled_from_nas": False,
        "photos_batch_csv_nas_path": "",
        "photos_batch_csv_local_path": str(photos_batch_csv),
        "photos_batch_pulled_from_nas": False,
    }
    if is_dry:
        local_photos_csv = _local_counterpart_if_available(photos_csv, infos, pc, id_affaire)
        local_batch_csv = _local_counterpart_if_available(photos_batch_csv, infos, pc, id_affaire)
        context["photos_csv_nas_path"] = str(photos_csv)
        context["photos_csv_local_path"] = str(local_photos_csv)
        context["photos_batch_csv_nas_path"] = str(photos_batch_csv)
        context["photos_batch_csv_local_path"] = str(local_batch_csv)
        nas_exists, nas_error = _path_exists_safe(photos_csv)
        context["nas_source_available"] = nas_exists
        if not nas_exists:
            context["nas_publish_pending"] = True
            context["nas_source_error"] = f"NAS_SOURCE_UNAVAILABLE: photos.csv NAS inaccessible: {photos_csv}. {nas_error}".strip()
        return local_photos_csv, local_batch_csv, context

    local_photos_csv = photos_csv
    nas_photos_csv = _counterpart_path(photos_csv, pc_root, nas_root)
    if nas_photos_csv is None:
        nas_photos_csv = photos_csv
        local_photos_csv = _counterpart_path(photos_csv, nas_root, pc_root) or photos_csv
    _require_business_path(nas_photos_csv, id_affaire, id_captation, "photos.csv NAS")
    _require_business_path(local_photos_csv, id_affaire, id_captation, "photos.csv local")
    context["photos_csv_nas_path"] = str(nas_photos_csv)
    context["photos_csv_local_path"] = str(local_photos_csv)
    local_exists, local_error = _path_exists_safe(local_photos_csv)
    if not local_exists:
        raise FileNotFoundError(f"LOCAL_SOURCE_UNAVAILABLE: photos.csv PC fixe introuvable: {local_photos_csv}. {local_error}")
    try:
        local_hash = sha256_file(local_photos_csv)
        local_business_hash = photos_csv_business_fingerprint_from_file(local_photos_csv)
    except Exception as exc:
        raise RuntimeError(f"LOCAL_SOURCE_INVALID: photos.csv PC fixe invalide: {local_photos_csv}. {exc}") from exc
    context["photos_csv_local_sha256_at_start"] = local_hash
    context["photos_csv_local_business_sha256_at_start"] = local_business_hash
    context["photos_csv_sha256_used"] = local_hash
    context["photos_csv_source"] = "local"

    nas_exists, nas_error = _path_exists_safe(nas_photos_csv)
    if not nas_exists:
        context["nas_source_available"] = False
        context["nas_publish_pending"] = True
        context["nas_source_error"] = f"NAS_SOURCE_UNAVAILABLE: photos.csv NAS inaccessible: {nas_photos_csv}. {nas_error}".strip()
    else:
        context["nas_source_available"] = True
        try:
            nas_hash = sha256_file(nas_photos_csv)
            nas_business_hash = photos_csv_business_fingerprint_from_file(nas_photos_csv)
        except Exception as exc:
            context["nas_source_available"] = False
            context["nas_publish_pending"] = True
            context["nas_source_error"] = f"NAS_SOURCE_UNAVAILABLE: photos.csv NAS illisible: {nas_photos_csv}. {exc}"
        else:
            context["photos_csv_nas_sha256_at_start"] = nas_hash
            context["photos_csv_nas_business_sha256_at_start"] = nas_business_hash
            local_mtime = _file_mtime_safe(local_photos_csv)
            nas_mtime = _file_mtime_safe(nas_photos_csv)
            context["photos_csv_local_mtime_at_start"] = local_mtime
            context["photos_csv_nas_mtime_at_start"] = nas_mtime
            if nas_hash == local_hash:
                context["photos_csv_source"] = "local_same_as_nas"
            elif local_mtime > nas_mtime:
                context["photos_csv_source"] = "local_newer_than_nas"
                context["nas_publish_pending"] = True
            elif nas_mtime > local_mtime and nas_business_hash == local_business_hash:
                copied_hash = copy_file_atomic_verified(nas_photos_csv, local_photos_csv, "PHOTOS_CSV_PULL_FAILED")
                if copied_hash != nas_hash:
                    raise RuntimeError(
                        f"PHOTOS_CSV_HASH_MISMATCH: photos.csv modifie pendant le pull. expected={nas_hash} actual={copied_hash} path={nas_photos_csv}"
                    )
                context["photos_csv_pulled_from_nas"] = True
                context["photos_csv_sha256_used"] = copied_hash
                context["photos_csv_source"] = "nas_newer_business_same"
            elif nas_business_hash == local_business_hash:
                context["photos_csv_source"] = "local_business_same_as_nas"
                context["nas_publish_pending"] = True
            else:
                raise RuntimeError(
                    "PHOTOS_CSV_SOURCE_DIVERGENCE: divergence metier entre photos.csv PC fixe et NAS; "
                    f"local={local_photos_csv} nas={nas_photos_csv}"
                )

            xlsx_nas = nas_photos_csv.with_suffix(".xlsx")
            xlsx_local = local_photos_csv.with_suffix(".xlsx")
            xlsx_exists, _xlsx_error = _path_exists_safe(xlsx_nas)
            if xlsx_exists:
                copy_file_atomic_verified(xlsx_nas, xlsx_local, "PHOTOS_CSV_PULL_FAILED")
                context["photos_xlsx_pulled_from_nas"] = True
                context["photos_xlsx_nas_path"] = str(xlsx_nas)
                context["photos_xlsx_local_path"] = str(xlsx_local)

            gtp_pulled: list[str] = []
            gtp_patterns = ("*_GTP_*.csv", "*_GTP_*.xlsx")
            for pattern in gtp_patterns:
                try:
                    gtp_candidates = sorted(nas_photos_csv.parent.glob(pattern))
                except Exception:
                    gtp_candidates = []
                for gtp_nas in gtp_candidates:
                    gtp_local = local_photos_csv.parent / gtp_nas.name
                    copy_file_atomic_verified(gtp_nas, gtp_local, "PHOTOS_CSV_PULL_FAILED")
                    gtp_pulled.append(str(gtp_local))
            context["gtp_files_pulled_from_nas"] = gtp_pulled

    local_batch = _counterpart_path(photos_batch_csv, nas_root, pc_root) or photos_batch_csv
    nas_batch = _counterpart_path(local_batch, pc_root, nas_root) or photos_batch_csv
    _require_business_path(nas_batch, id_affaire, id_captation, "photos_batch.csv NAS")
    _require_business_path(local_batch, id_affaire, id_captation, "photos_batch.csv local")
    context["photos_batch_csv_nas_path"] = str(nas_batch)
    context["photos_batch_csv_local_path"] = str(local_batch)
    local_batch_exists, _local_batch_error = _path_exists_safe(local_batch)
    nas_batch_exists, _nas_batch_error = _path_exists_safe(nas_batch)
    if (not local_batch_exists) and nas_batch_exists:
        copy_file_atomic_verified(nas_batch, local_batch, "PHOTOS_BATCH_PULL_FAILED")
        context["photos_batch_pulled_from_nas"] = True
        nas_stamp = nas_batch.with_suffix(nas_batch.suffix + ".stamp")
        nas_stamp_exists, _nas_stamp_error = _path_exists_safe(nas_stamp)
        if nas_stamp_exists:
            copy_file_atomic_verified(nas_stamp, local_batch.with_suffix(local_batch.suffix + ".stamp"), "PHOTOS_BATCH_PULL_FAILED")
            context["photos_batch_stamp_pulled_from_nas"] = True
    return local_photos_csv, local_batch, context


def publish_batch_outputs_to_nas(
    *,
    photos_batch_csv: Path,
    stamp_path: Path,
    sync_context: dict[str, Any],
    batch_started_at: float,
) -> dict[str, Any]:
    nas_batch_raw = sync_context.get("photos_batch_csv_nas_path") or ""
    if not nas_batch_raw:
        return {
            "nas_publish_attempted": False,
            "nas_publish_succeeded": False,
            "nas_publish_error": "photos_batch_csv_nas_path absent",
        }
    nas_batch = Path(str(nas_batch_raw))
    nas_stamp = nas_batch.with_suffix(nas_batch.suffix + ".stamp")
    result: dict[str, Any] = {
        "nas_publish_attempted": False,
        "nas_publish_succeeded": False,
        "nas_publish_method": "",
        "nas_publish_smb_error": "",
        "nas_publish_ssh_attempted": False,
        "nas_publish_ssh_error": "",
        "nas_publish_pending": True,
        "publish_pending": True,
        "photos_batch_csv_nas_path": str(nas_batch),
        "photos_batch_stamp_nas_path": str(nas_stamp),
        "nas_publish_error": "",
    }
    try:
        nas_photos_csv_raw = sync_context.get("photos_csv_nas_path") or ""
        expected_photos_hash = str(sync_context.get("photos_csv_nas_sha256_at_start") or "").strip().lower()
        if nas_photos_csv_raw:
            nas_photos_csv = Path(str(nas_photos_csv_raw))
            if expected_photos_hash:
                actual_photos_hash = sha256_file(nas_photos_csv)
                result["photos_csv_nas_sha256_before_publish"] = actual_photos_hash
                if actual_photos_hash != expected_photos_hash:
                    result["nas_publish_error"] = (
                        f"photos.csv NAS modifie pendant le batch. expected={expected_photos_hash} "
                        f"actual={actual_photos_hash} path={nas_photos_csv}"
                    )
                    raise BatchSyncError(
                        f"PHOTOS_CSV_CHANGED_DURING_BATCH: {result['nas_publish_error']}",
                        result,
                    )
            local_photos_csv_raw = sync_context.get("photos_csv_local_path") or ""
            if local_photos_csv_raw:
                local_photos_csv = Path(str(local_photos_csv_raw))
                photos_hash = copy_file_atomic_verified(local_photos_csv, nas_photos_csv, "NAS_PUBLISH_FAILED")
                result["photos_csv_nas_path"] = str(nas_photos_csv)
                result["photos_csv_nas_sha256"] = photos_hash
        local_hash = sha256_file(photos_batch_csv)
        backup_paths: list[str] = []
        if nas_batch.exists():
            nas_hash_before = sha256_file(nas_batch)
            if nas_hash_before != local_hash:
                if nas_batch.stat().st_mtime > batch_started_at:
                    raise RuntimeError(f"destination NAS modifiee apres demarrage: {nas_batch}")
                backup = nas_batch.with_name(nas_batch.name + "." + datetime.now().strftime("%Y%m%d-%H%M%S") + ".bak")
                shutil.copy2(nas_batch, backup)
                backup_paths.append(str(backup))
        result["nas_publish_attempted"] = True
        nas_hash = copy_file_atomic_verified(photos_batch_csv, nas_batch, "NAS_PUBLISH_FAILED")
        stamp_hash = copy_file_atomic_verified(stamp_path, nas_stamp, "NAS_PUBLISH_FAILED")
        result.update({
            "nas_publish_method": "smb",
            "nas_publish_succeeded": True,
            "nas_publish_pending": False,
            "publish_pending": False,
            "photos_batch_csv_nas_sha256": nas_hash,
            "photos_batch_stamp_nas_sha256": stamp_hash,
            "nas_backup_paths": backup_paths,
        })
        return result
    except BatchSyncError:
        raise
    except Exception as exc:
        smb_error = str(exc)
        result["nas_publish_attempted"] = True
        result["nas_publish_smb_error"] = smb_error
        result["nas_publish_error"] = smb_error
        try:
            local_photos_csv_raw = sync_context.get("photos_csv_local_path") or sync_context.get("photos_csv_path_used") or ""
            local_photos_csv = Path(str(local_photos_csv_raw))
            photos_hash = sha256_file(local_photos_csv)
            batch_hash = sha256_file(photos_batch_csv)
            stamp_hash = sha256_file(stamp_path)
            ssh_result = publish_batch_outputs_to_nas_ssh_fallback(
                photos_csv=local_photos_csv,
                photos_batch_csv=photos_batch_csv,
                stamp_path=stamp_path,
                id_affaire=str(sync_context.get("id_affaire") or sync_context.get("affaire") or ""),
                id_captation=str(sync_context.get("id_captation") or sync_context.get("captation") or ""),
                photos_csv_sha256=photos_hash,
                photos_batch_sha256=batch_hash,
                stamp_sha256=stamp_hash,
            )
            result.update(ssh_result)
            result["nas_publish_error"] = ""
            return result
        except Exception as ssh_exc:
            result["nas_publish_ssh_attempted"] = True
            result["nas_publish_ssh_error"] = str(ssh_exc)
            result["nas_publish_succeeded"] = False
            result["nas_publish_pending"] = True
            result["publish_pending"] = True
            result["nas_publish_error"] = f"SMB: {smb_error}; SSH: {ssh_exc}"
            raise BatchSyncError(f"NAS_PUBLISH_FAILED: publication photos_batch.csv vers NAS impossible: {result['nas_publish_error']}", result) from ssh_exc


def _affaire_root(root_value: str, id_affaire: str) -> Path:
    root = Path(str(root_value or "").strip().rstrip("\\/"))
    if id_affaire and root.name.lower() != id_affaire.lower():
        return root / id_affaire
    return root


def debrief_dictees_paths(
    *,
    infos: dict[str, Any],
    pc: dict[str, Any],
    id_affaire: str,
    id_captation: str,
) -> tuple[Path, Path]:
    pc_root, nas_root = _roots_for_sync(infos, pc, id_affaire)
    rel = Path("AF_Expert_ASR") / "transcriptions" / id_captation / "debrief" / DEBRIEF_DICTEES_FILENAME
    local_path = _affaire_root(pc_root, id_affaire) / rel
    nas_path = _affaire_root(nas_root, id_affaire) / rel
    _require_business_path(local_path, id_affaire, id_captation, "debrief_dictees.csv local")
    _require_business_path(nas_path, id_affaire, id_captation, "debrief_dictees.csv NAS")
    return local_path, nas_path


def write_debrief_dictees_csv_atomic(
    *,
    path: Path,
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = ""
    if path.exists():
        backup = path.with_name(f"{path.name}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
        shutil.copy2(path, backup)
        backup_path = str(backup)
    tmp = path.with_name(f".{path.name}.tmp.{uuid.uuid4().hex}")
    manifest_path = path.with_name(DEBRIEF_DICTEES_MANIFEST_FILENAME)
    manifest_tmp = manifest_path.with_name(f".{manifest_path.name}.tmp.{uuid.uuid4().hex}")
    try:
        with tmp.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ASR_CSV_FIELDNAMES, delimiter=";")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in ASR_CSV_FIELDNAMES})
        reloaded_rows, reloaded_fields = read_csv_semicolon(tmp)
        if reloaded_fields != ASR_CSV_FIELDNAMES:
            raise RuntimeError(f"schema invalide: {reloaded_fields}")
        if len(reloaded_rows) != len(rows):
            raise RuntimeError(f"nombre lignes incoherent: expected={len(rows)} actual={len(reloaded_rows)}")
        for row in reloaded_rows:
            if not _clean_cell(row.get("text")):
                raise RuntimeError("texte vide apres relecture")
        tmp_hash = sha256_file(tmp)
        manifest_payload = dict(manifest)
        manifest_payload.update({
            "csv_path": str(path),
            "rows_written": len(rows),
            "sha256": tmp_hash,
        })
        manifest_tmp.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        manifest_tmp.replace(manifest_path)
        final_hash = sha256_file(path)
        if final_hash != tmp_hash:
            raise RuntimeError(f"hash final incoherent: expected={tmp_hash} actual={final_hash}")
        return {
            "debrief_dictees_generated": True,
            "debrief_dictees_rows": len(rows),
            "debrief_dictees_local_path": str(path),
            "debrief_dictees_local_sha256": final_hash,
            "debrief_dictees_manifest_path": str(manifest_path),
            "debrief_dictees_backup_path": backup_path,
            "debrief_dictees_error": "",
        }
    finally:
        for leftover in (tmp, manifest_tmp):
            try:
                if leftover.exists():
                    leftover.unlink()
            except Exception:
                pass


def publish_debrief_dictees_to_nas(
    *,
    local_path: Path,
    nas_path: Path,
    id_affaire: str,
    id_captation: str,
) -> dict[str, Any]:
    result = {
        "debrief_dictees_nas_path": str(nas_path),
        "debrief_dictees_nas_sha256": "",
        "debrief_dictees_publish_method": "",
        "debrief_dictees_publish_succeeded": False,
        "debrief_dictees_publish_pending": True,
        "debrief_dictees_publish_error": "",
    }
    local_hash = sha256_file(local_path)
    try:
        nas_hash = copy_file_atomic_verified(local_path, nas_path, "DEBRIEF_DICTEES_NAS_PUBLISH_FAILED")
        result.update({
            "debrief_dictees_nas_sha256": nas_hash,
            "debrief_dictees_publish_method": "smb",
            "debrief_dictees_publish_succeeded": True,
            "debrief_dictees_publish_pending": False,
        })
        return result
    except Exception as smb_exc:
        result["debrief_dictees_publish_error"] = str(smb_exc)
        try:
            affaire = _validate_remote_business_id(id_affaire, "affaire")
            captation = _validate_remote_business_id(id_captation, "captation")
            remote_dir = f"{NAS_SSH_ROOT}/{affaire}/AF_Expert_ASR/transcriptions/{captation}/debrief"
            _check_nas_ssh_ready()
            ssh_result = _nas_ssh_publish_file(local_path, remote_dir, DEBRIEF_DICTEES_FILENAME, local_hash)
            result.update({
                "debrief_dictees_nas_path": ssh_result["remote_path"],
                "debrief_dictees_nas_sha256": ssh_result["remote_sha256"],
                "debrief_dictees_publish_method": "ssh_fallback",
                "debrief_dictees_publish_succeeded": True,
                "debrief_dictees_publish_pending": False,
                "debrief_dictees_publish_error": "",
            })
        except Exception as ssh_exc:
            result["debrief_dictees_publish_error"] = f"SMB: {smb_exc}; SSH: {ssh_exc}"
        return result


def validate_existing_debrief_dictees(
    *,
    local_path: Path,
    id_affaire: str,
    id_captation: str,
) -> dict[str, Any]:
    manifest_path = local_path.with_name(DEBRIEF_DICTEES_MANIFEST_FILENAME)
    result = {
        "debrief_dictees_generated": False,
        "debrief_dictees_publish_attempted": False,
        "debrief_dictees_publish_method": "",
        "debrief_dictees_publish_succeeded": False,
        "debrief_dictees_publish_pending": False,
        "debrief_dictees_local_path": str(local_path),
        "debrief_dictees_local_sha256": "",
        "debrief_dictees_local_size": 0,
        "debrief_dictees_manifest_path": str(manifest_path),
        "debrief_dictees_manifest_sha256": "",
        "debrief_dictees_manifest_size": 0,
        "debrief_dictees_rows": 0,
        "debrief_dictees_nas_sha256": "",
        "debrief_dictees_nas_size": 0,
        "debrief_dictees_manifest_nas_sha256": "",
        "debrief_dictees_manifest_nas_size": 0,
        "debrief_dictees_error": "",
        "debrief_dictees_valid": False,
    }
    csv_exists = local_path.exists()
    manifest_exists = manifest_path.exists()
    if not csv_exists and not manifest_exists:
        return result
    if csv_exists != manifest_exists:
        result["debrief_dictees_publish_pending"] = True
        result["debrief_dictees_error"] = "debrief_dictees.csv et manifest incoherents: fichier manquant"
        return result

    try:
        rows, fieldnames = read_csv_semicolon(local_path)
        if fieldnames != ASR_CSV_FIELDNAMES:
            raise RuntimeError(f"schema invalide: {fieldnames}")
        if any(not _clean_cell(row.get("text")) for row in rows):
            raise RuntimeError("texte vide detecte")
        manifest = read_json(manifest_path)
        csv_hash = sha256_file(local_path)
        manifest_hash = sha256_file(manifest_path)
        expected_hash = str(manifest.get("sha256") or "").strip().lower()
        if expected_hash and expected_hash != csv_hash:
            raise RuntimeError(f"sha256 incoherent: manifest={expected_hash} csv={csv_hash}")
        expected_rows = manifest.get("rows_written")
        if expected_rows is not None and int(expected_rows) != len(rows):
            raise RuntimeError(f"nombre lignes incoherent: manifest={expected_rows} csv={len(rows)}")
        manifest_affaire = _clean_cell(manifest.get("affaire"))
        manifest_captation = _clean_cell(manifest.get("captation"))
        if manifest_affaire and manifest_affaire != id_affaire:
            raise RuntimeError(f"affaire manifeste differente: {manifest_affaire}")
        if manifest_captation and manifest_captation != id_captation:
            raise RuntimeError(f"captation manifeste differente: {manifest_captation}")
        result.update({
            "debrief_dictees_local_sha256": csv_hash,
            "debrief_dictees_local_size": local_path.stat().st_size,
            "debrief_dictees_manifest_sha256": manifest_hash,
            "debrief_dictees_manifest_size": manifest_path.stat().st_size,
            "debrief_dictees_rows": len(rows),
            "debrief_dictees_valid": True,
        })
    except Exception as exc:
        result["debrief_dictees_publish_pending"] = True
        result["debrief_dictees_error"] = str(exc)
    return result


def publish_existing_debrief_dictees_to_nas(
    *,
    local_path: Path,
    nas_path: Path,
    id_affaire: str,
    id_captation: str,
) -> dict[str, Any]:
    manifest_path = local_path.with_name(DEBRIEF_DICTEES_MANIFEST_FILENAME)
    nas_manifest_path = nas_path.with_name(DEBRIEF_DICTEES_MANIFEST_FILENAME)
    validation = validate_existing_debrief_dictees(
        local_path=local_path,
        id_affaire=id_affaire,
        id_captation=id_captation,
    )
    validation["debrief_dictees_nas_path"] = str(nas_path)
    validation["debrief_dictees_manifest_nas_path"] = str(nas_manifest_path)
    if not validation["debrief_dictees_valid"]:
        return validation

    csv_hash = str(validation["debrief_dictees_local_sha256"])
    manifest_hash = str(validation["debrief_dictees_manifest_sha256"])
    validation["debrief_dictees_publish_attempted"] = True
    try:
        nas_csv_hash = copy_file_atomic_verified(local_path, nas_path, "DEBRIEF_DICTEES_NAS_PUBLISH_FAILED")
        nas_csv_size = nas_path.stat().st_size
        if nas_csv_size != local_path.stat().st_size:
            raise RuntimeError(f"taille CSV distante differente: expected={local_path.stat().st_size} actual={nas_csv_size}")
        nas_manifest_hash = copy_file_atomic_verified(manifest_path, nas_manifest_path, "DEBRIEF_DICTEES_NAS_PUBLISH_FAILED")
        nas_manifest_size = nas_manifest_path.stat().st_size
        if nas_manifest_size != manifest_path.stat().st_size:
            raise RuntimeError(f"taille manifeste distante differente: expected={manifest_path.stat().st_size} actual={nas_manifest_size}")
        validation.update({
            "debrief_dictees_nas_sha256": nas_csv_hash,
            "debrief_dictees_nas_size": nas_csv_size,
            "debrief_dictees_manifest_nas_sha256": nas_manifest_hash,
            "debrief_dictees_manifest_nas_size": nas_manifest_size,
            "debrief_dictees_publish_method": "smb",
            "debrief_dictees_publish_succeeded": True,
            "debrief_dictees_publish_pending": False,
        })
        return validation
    except Exception as smb_exc:
        validation["debrief_dictees_error"] = str(smb_exc)
        try:
            affaire = _validate_remote_business_id(id_affaire, "affaire")
            captation = _validate_remote_business_id(id_captation, "captation")
            remote_dir = f"{NAS_SSH_ROOT}/{affaire}/AF_Expert_ASR/transcriptions/{captation}/debrief"
            _check_nas_ssh_ready()
            csv_info = _nas_ssh_publish_file(local_path, remote_dir, DEBRIEF_DICTEES_FILENAME, csv_hash)
            manifest_info = _nas_ssh_publish_file(manifest_path, remote_dir, DEBRIEF_DICTEES_MANIFEST_FILENAME, manifest_hash)
            validation.update({
                "debrief_dictees_nas_path": csv_info["remote_path"],
                "debrief_dictees_nas_sha256": csv_info["remote_sha256"],
                "debrief_dictees_nas_size": csv_info["remote_size"],
                "debrief_dictees_manifest_nas_path": manifest_info["remote_path"],
                "debrief_dictees_manifest_nas_sha256": manifest_info["remote_sha256"],
                "debrief_dictees_manifest_nas_size": manifest_info["remote_size"],
                "debrief_dictees_publish_method": "ssh_fallback",
                "debrief_dictees_publish_succeeded": True,
                "debrief_dictees_publish_pending": False,
                "debrief_dictees_error": "",
            })
        except Exception as ssh_exc:
            validation["debrief_dictees_publish_succeeded"] = False
            validation["debrief_dictees_publish_pending"] = True
            validation["debrief_dictees_error"] = f"SMB: {smb_exc}; SSH: {ssh_exc}"
        return validation


def publish_existing_debrief_dictees_for_publish_only(
    *,
    infos: dict[str, Any],
    pc: dict[str, Any],
    id_affaire: str,
    id_captation: str,
) -> dict[str, Any]:
    local_path, nas_path = debrief_dictees_paths(
        infos=infos,
        pc=pc,
        id_affaire=id_affaire,
        id_captation=id_captation,
    )
    return publish_existing_debrief_dictees_to_nas(
        local_path=local_path,
        nas_path=nas_path,
        id_affaire=id_affaire,
        id_captation=id_captation,
    )


def generate_and_publish_debrief_dictees(
    *,
    rows_ui: list[Dict[str, Any]],
    batch_rows: list[Dict[str, Any]],
    infos: dict[str, Any],
    pc: dict[str, Any],
    id_affaire: str,
    id_captation: str,
    mapping_path: Path | None,
    preview_only: bool = False,
) -> dict[str, Any]:
    local_path, nas_path = debrief_dictees_paths(
        infos=infos,
        pc=pc,
        id_affaire=id_affaire,
        id_captation=id_captation,
    )
    rows, manifest, stats = build_debrief_dictees_rows(
        rows_ui=rows_ui,
        batch_rows=batch_rows,
        mapping_path=mapping_path,
        affaire=id_affaire,
        captation=id_captation,
    )
    result: dict[str, Any] = {
        "debrief_dictees_generated": False,
        "debrief_dictees_rows": len(rows),
        "debrief_dictees_local_path": str(local_path),
        "debrief_dictees_local_sha256": "",
        "debrief_dictees_nas_path": str(nas_path),
        "debrief_dictees_nas_sha256": "",
        "debrief_dictees_publish_method": "",
        "debrief_dictees_publish_succeeded": False,
        "debrief_dictees_publish_pending": False,
        "debrief_dictees_error": "",
        "debrief_dictees_preview": stats.preview,
    }
    stats.rows_written = len(rows)
    if preview_only:
        return result
    if not rows:
        result["debrief_dictees_error"] = "aucune dictee exploitable"
        return result
    try:
        local_info = write_debrief_dictees_csv_atomic(path=local_path, rows=rows, manifest=manifest)
        result.update(local_info)
        stats.local_sha256 = str(local_info.get("debrief_dictees_local_sha256") or "")
        publish_info = publish_debrief_dictees_to_nas(
            local_path=local_path,
            nas_path=nas_path,
            id_affaire=id_affaire,
            id_captation=id_captation,
        )
        result.update(publish_info)
        stats.nas_publish_method = str(publish_info.get("debrief_dictees_publish_method") or "")
        stats.nas_publish_succeeded = bool(publish_info.get("debrief_dictees_publish_succeeded"))
        stats.publish_pending = bool(publish_info.get("debrief_dictees_publish_pending"))
    except Exception as exc:
        result["debrief_dictees_error"] = str(exc)
        result["debrief_dictees_publish_pending"] = bool(result.get("debrief_dictees_generated"))
        stats.error = str(exc)
        stats.publish_pending = bool(result.get("debrief_dictees_generated"))
    finally:
        print(
            "[DEBRIEF_DICTEES] "
            f"photos_total={stats.photos_total} photos_avec_dictee={stats.photos_avec_dictee} "
            f"dictees_candidates={stats.dictees_candidates} dictees_retenues={stats.dictees_retenues} "
            f"photos_sans_dictee={stats.photos_sans_dictee} dictees_status_invalide={stats.dictees_status_invalide} "
            f"doublons_ambigus={stats.doublons_ambigus} rows_written={stats.rows_written} "
            f"local_sha256={stats.local_sha256} nas_publish_method={stats.nas_publish_method} "
            f"nas_publish_succeeded={stats.nas_publish_succeeded} publish_pending={stats.publish_pending}"
        )
    return result


def verify_photos_batch_output(
    *,
    photos_csv: Path,
    photos_batch_csv: Path,
    stamp_path: Path,
    batch_id: str,
    job_id: str,
    id_affaire: str,
    id_captation: str,
) -> dict[str, Any]:
    job_id = str(job_id or "").strip()
    if not job_id:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: job_id vide refuse pour nouvelle execution")
    if not photos_csv.exists():
        raise FileNotFoundError(f"BATCH_OUTPUT_MISSING: photos.csv introuvable: {photos_csv}")
    if not photos_batch_csv.exists():
        raise FileNotFoundError(f"BATCH_OUTPUT_MISSING: photos_batch.csv introuvable: {photos_batch_csv}")
    size = photos_batch_csv.stat().st_size
    if size <= 0:
        raise RuntimeError(f"BATCH_OUTPUT_INVALID: photos_batch.csv vide: {photos_batch_csv}")

    rows, fieldnames = read_csv_semicolon(photos_batch_csv)
    required = {"photo_rel_native", "batch_status", "batch_id", "batch_ts"}
    missing = sorted(required - set(fieldnames))
    if missing:
        raise RuntimeError(f"BATCH_OUTPUT_INVALID: colonnes manquantes dans photos_batch.csv: {', '.join(missing)}")
    if not rows:
        raise RuntimeError(f"BATCH_OUTPUT_INVALID: photos_batch.csv sans lignes: {photos_batch_csv}")

    try:
        photos_csv_hash = sha256_file(photos_csv)
        photos_csv_business_hash = photos_csv_business_fingerprint_from_file(photos_csv)
        photos_batch_hash = sha256_file(photos_batch_csv)
    except Exception as exc:
        raise RuntimeError(f"BATCH_OUTPUT_HASH_FAILED: calcul SHA256 impossible: {exc}") from exc

    stamp_payload = {
        "batch_id": batch_id,
        "job_id": job_id,
        "affaire": id_affaire,
        "captation": id_captation,
        "id_affaire": id_affaire,
        "id_captation": id_captation,
        "photos_csv_sha256_used": photos_csv_hash,
        "photos_csv_business_sha256_used": photos_csv_business_hash,
        "photos_batch_csv_sha256": photos_batch_hash,
        "last_batch_ts": now_ts(),
        "host": socket.gethostname(),
    }
    try:
        tmp_stamp = stamp_path.with_suffix(stamp_path.suffix + ".tmp")
        tmp_stamp.write_text(json.dumps(stamp_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_stamp.replace(stamp_path)
        reloaded = read_json(stamp_path)
    except Exception as exc:
        raise RuntimeError(f"BATCH_OUTPUT_STAMP_FAILED: ecriture/relecture stamp impossible: {exc}") from exc

    for key, expected in stamp_payload.items():
        if str(reloaded.get(key, "")) != str(expected):
            raise RuntimeError(f"BATCH_OUTPUT_STAMP_FAILED: champ stamp incoherent: {key}")

    return {
        "photos_csv_path_used": str(photos_csv),
        "photos_csv_sha256_used": photos_csv_hash,
        "photos_csv_business_sha256_used": photos_csv_business_hash,
        "photos_batch_csv_path": str(photos_batch_csv),
        "photos_batch_csv_sha256": photos_batch_hash,
        "photos_batch_csv_local_sha256": photos_batch_hash,
        "photos_batch_csv_size": size,
        "photos_batch_csv_rows": len(rows),
        "photos_batch_stamp_path": str(stamp_path),
        "batch_id": batch_id,
        "job_id": job_id,
        "output_verified": True,
        "output_verified_local": True,
    }


def attach_job_id_to_batch_rows(
    rows: list[dict[str, Any]],
    *,
    batch_id: str,
    job_id: str,
) -> int:
    count = 0
    for row in rows:
        if str(row.get("batch_id") or "").strip() == batch_id:
            row["job_id"] = job_id
            count += 1
    return count


def set_successful_llm_batch_value(
    row: dict[str, Any],
    *,
    field: str,
    value: str,
    batch_id: str,
) -> None:
    row[field] = value
    row["batch_id"] = batch_id


def verify_existing_photos_batch_stamp(
    *,
    photos_csv: Path,
    photos_batch_csv: Path,
    stamp_path: Path,
    id_affaire: str,
    id_captation: str,
) -> dict[str, Any]:
    if not photos_csv.exists():
        raise FileNotFoundError(f"BATCH_OUTPUT_MISSING: photos.csv introuvable: {photos_csv}")
    if not photos_batch_csv.exists():
        raise FileNotFoundError(f"BATCH_OUTPUT_MISSING: photos_batch.csv introuvable: {photos_batch_csv}")
    if not stamp_path.exists():
        raise FileNotFoundError(f"BATCH_OUTPUT_STAMP_FAILED: stamp introuvable: {stamp_path}")

    rows, fieldnames = read_csv_semicolon(photos_batch_csv)
    required = {"photo_rel_native", "batch_status", "batch_id", "batch_ts"}
    missing = sorted(required - set(fieldnames))
    if missing:
        raise RuntimeError(f"BATCH_OUTPUT_INVALID: colonnes manquantes dans photos_batch.csv: {', '.join(missing)}")
    if not rows:
        raise RuntimeError(f"BATCH_OUTPUT_INVALID: photos_batch.csv sans lignes: {photos_batch_csv}")

    try:
        stamp = read_json(stamp_path)
    except Exception as exc:
        raise RuntimeError(f"BATCH_OUTPUT_STAMP_FAILED: stamp illisible: {stamp_path}. {exc}") from exc

    for field in ("batch_id", "job_id", "affaire", "captation", "photos_csv_sha256_used", "photos_batch_csv_sha256", "last_batch_ts", "host"):
        if not str(stamp.get(field) or "").strip():
            raise RuntimeError(f"BATCH_OUTPUT_STAMP_FAILED: champ stamp manquant: {field}")
    if str(stamp.get("affaire") or "").strip() != id_affaire:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: stamp affaire differente")
    if str(stamp.get("captation") or "").strip() != id_captation:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: stamp captation differente")

    photos_hash = sha256_file(photos_csv)
    photos_business_hash = photos_csv_business_fingerprint_from_file(photos_csv)
    batch_hash = sha256_file(photos_batch_csv)
    stamp_hash = sha256_file(stamp_path)
    if str(stamp.get("photos_csv_sha256_used") or "").strip().lower() != photos_hash:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: stamp photos_csv_sha256 different")
    if str(stamp.get("photos_batch_csv_sha256") or "").strip().lower() != batch_hash:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: stamp photos_batch_csv_sha256 different")
    stamp_business_hash = str(stamp.get("photos_csv_business_sha256_used") or "").strip().lower()
    if stamp_business_hash and stamp_business_hash != photos_business_hash:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: stamp photos_csv_business_sha256 different")

    return {
        "job_id": str(stamp.get("job_id") or "").strip(),
        "batch_id": str(stamp.get("batch_id") or "").strip(),
        "photos_csv_path_used": str(photos_csv),
        "photos_csv_sha256_used": photos_hash,
        "photos_csv_business_sha256_used": photos_business_hash,
        "photos_batch_csv_path": str(photos_batch_csv),
        "photos_batch_csv_sha256": batch_hash,
        "photos_batch_csv_local_sha256": batch_hash,
        "photos_batch_csv_rows": len(rows),
        "photos_batch_stamp_path": str(stamp_path),
        "photos_batch_stamp_sha256": stamp_hash,
        "output_verified": True,
        "output_verified_local": True,
    }


def publish_only_existing_batch_outputs(
    *,
    infos: dict[str, Any],
    pc: dict[str, Any],
    photos_csv: Path,
    photos_batch_csv: Path,
    id_affaire: str,
    id_captation: str,
) -> dict[str, Any]:
    pc_root, nas_root = _roots_for_sync(infos, pc, id_affaire)
    local_photos_csv = _local_counterpart_if_available(photos_csv, infos, pc, id_affaire)
    local_batch_csv = _local_counterpart_if_available(photos_batch_csv, infos, pc, id_affaire)
    nas_photos_csv = _counterpart_path(local_photos_csv, pc_root, nas_root) or photos_csv
    nas_batch_csv = _counterpart_path(local_batch_csv, pc_root, nas_root) or photos_batch_csv
    _require_business_path(local_photos_csv, id_affaire, id_captation, "photos.csv local")
    _require_business_path(local_batch_csv, id_affaire, id_captation, "photos_batch.csv local")
    _require_business_path(nas_photos_csv, id_affaire, id_captation, "photos.csv NAS")
    _require_business_path(nas_batch_csv, id_affaire, id_captation, "photos_batch.csv NAS")

    stamp_path = local_batch_csv.with_suffix(local_batch_csv.suffix + ".stamp")
    output_info = verify_existing_photos_batch_stamp(
        photos_csv=local_photos_csv,
        photos_batch_csv=local_batch_csv,
        stamp_path=stamp_path,
        id_affaire=id_affaire,
        id_captation=id_captation,
    )
    output_info.update({
        "publication_only": True,
        "vlm_calls": 0,
        "llm_calls": 0,
        "affaire": id_affaire,
        "captation": id_captation,
        "id_affaire": id_affaire,
        "id_captation": id_captation,
        "photos_csv_local_path": str(local_photos_csv),
        "photos_csv_nas_path": str(nas_photos_csv),
        "photos_batch_csv_local_path": str(local_batch_csv),
        "photos_batch_csv_nas_path": str(nas_batch_csv),
        "nas_publish_attempted": False,
        "nas_publish_succeeded": False,
        "nas_publish_pending": True,
        "publish_pending": True,
    })
    output_info.update(publish_existing_debrief_dictees_for_publish_only(
        infos=infos,
        pc=pc,
        id_affaire=id_affaire,
        id_captation=id_captation,
    ))
    sync_context = dict(output_info)
    try:
        output_info.update(publish_batch_outputs_to_nas(
            photos_batch_csv=local_batch_csv,
            stamp_path=stamp_path,
            sync_context=sync_context,
            batch_started_at=time.time(),
        ))
    except BatchSyncError as exc:
        output_info.update(exc.details)
        output_info["local_done"] = True
        output_info["publish_pending"] = True
        output_info["publish_error_code"] = "NAS_PUBLISH_FAILED"
        output_info["publish_error_message"] = str(exc)
        output_info["nas_publish_succeeded"] = False
    return output_info


def repair_empty_photos_batch_stamp_job_id(
    *,
    photos_csv: Path,
    photos_batch_csv: Path,
    stamp_path: Path,
    id_affaire: str,
    id_captation: str,
    repair_job_id: str = "",
) -> dict[str, Any]:
    if not photos_csv.exists():
        raise FileNotFoundError(f"BATCH_OUTPUT_MISSING: photos.csv introuvable: {photos_csv}")
    if not photos_batch_csv.exists():
        raise FileNotFoundError(f"BATCH_OUTPUT_MISSING: photos_batch.csv introuvable: {photos_batch_csv}")
    if not stamp_path.exists():
        raise FileNotFoundError(f"BATCH_OUTPUT_STAMP_FAILED: stamp introuvable: {stamp_path}")

    stamp = read_json(stamp_path)
    existing_job_id = str(stamp.get("job_id") or "").strip()
    if existing_job_id:
        raise RuntimeError(f"BATCH_OUTPUT_STAMP_FAILED: stamp deja renseigne job_id={existing_job_id}")

    photos_hash = sha256_file(photos_csv)
    batch_hash = sha256_file(photos_batch_csv)
    expected_photos_hash = str(stamp.get("photos_csv_sha256_used") or "").strip()
    expected_batch_hash = str(stamp.get("photos_batch_csv_sha256") or "").strip()
    if photos_hash != expected_photos_hash:
        raise RuntimeError(
            "BATCH_OUTPUT_STAMP_FAILED: refus reparation stamp, hash photos.csv different "
            f"expected={expected_photos_hash} actual={photos_hash} path={photos_csv}"
        )
    if batch_hash != expected_batch_hash:
        raise RuntimeError(
            "BATCH_OUTPUT_STAMP_FAILED: refus reparation stamp, hash photos_batch.csv different "
            f"expected={expected_batch_hash} actual={batch_hash} path={photos_batch_csv}"
        )

    job_id = str(repair_job_id or "").strip() or _manual_annotation_job_id(
        id_affaire,
        id_captation,
        prefix="manual_annotation_migration",
    )
    if not job_id:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: job_id de reparation vide")

    repaired = dict(stamp)
    repaired["job_id"] = job_id
    repaired["job_id_repaired_at"] = now_ts()
    repaired["job_id_repair_reason"] = "empty_manual_cli_stamp"

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = stamp_path.with_name(f"{stamp_path.name}.{ts}.empty_job_id.bak")
    tmp_stamp = stamp_path.with_name(f"{stamp_path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        shutil.copy2(stamp_path, backup)
        tmp_stamp.write_text(json.dumps(repaired, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_stamp.replace(stamp_path)
        reloaded = read_json(stamp_path)
    except Exception as exc:
        try:
            if tmp_stamp.exists():
                tmp_stamp.unlink()
        except Exception:
            pass
        raise RuntimeError(f"BATCH_OUTPUT_STAMP_FAILED: reparation stamp impossible: {exc}") from exc

    if str(reloaded.get("job_id") or "").strip() != job_id:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: relecture job_id repare incoherente")
    if str(reloaded.get("photos_csv_sha256_used") or "").strip() != photos_hash:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: relecture hash photos.csv incoherente")
    if str(reloaded.get("photos_batch_csv_sha256") or "").strip() != batch_hash:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: relecture hash photos_batch.csv incoherente")

    return {
        "status": "done",
        "repair": "empty_stamp_job_id",
        "job_id": job_id,
        "photos_csv_path_used": str(photos_csv),
        "photos_csv_sha256_used": photos_hash,
        "photos_batch_csv_path": str(photos_batch_csv),
        "photos_batch_csv_sha256": batch_hash,
        "photos_batch_stamp_path": str(stamp_path),
        "photos_batch_stamp_backup_path": str(backup),
        "output_verified": True,
        "output_verified_local": True,
    }


def ensure_columns(rows: List[Dict[str, Any]], required: Dict[str, Any]) -> List[str]:
    if not rows:
        # schéma minimal quand le CSV est vide / absent
        return list(required.keys())

    existing = set().union(*(r.keys() for r in rows))
    for col, default in required.items():
        if col not in existing:
            for r in rows:
                r[col] = default

    base = list(rows[0].keys())
    for c in required.keys():
        if c not in base:
            base.append(c)
    return base


def csv_fieldnames_without_internal(fieldnames: List[str]) -> List[str]:
    return [f for f in fieldnames if f != "idx"]


def _clean_cell(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() == "nan" else text


def _dictation_csv_candidates_from_row(row: Dict[str, Any]) -> list[Path]:
    candidates: list[Path] = []
    for key in ("dictee_asr_csv_path_pcfixe", "dictee_asr_photo_csv_path_pcfixe"):
        value = _clean_cell(row.get(key))
        if value:
            candidates.append(Path(value))

    audio_path = _clean_cell(row.get("dictee_audio_path_pcfixe"))
    if audio_path:
        p = Path(audio_path)
        stem = p.stem
        suffix = p.suffix.lstrip(".")
        out_dirs: list[Path] = []
        for existing in candidates:
            if str(existing):
                out_dirs.append(existing.parent)
        out_dirs.append(p.parent)
        if p.parent.name.lower() == "asr_in":
            out_dirs.append(p.parent.parent / "asr_out")
        seen_dirs = set()
        for out_dir in out_dirs:
            key = str(out_dir).lower()
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            if suffix:
                candidates.append(out_dir / f"{stem}({suffix}).csv")
                candidates.append(out_dir / f"{stem}({suffix})(photo).csv")
            candidates.append(out_dir / f"{p.name}.csv")
            candidates.append(out_dir / f"{p.name}(photo).csv")
            candidates.append(out_dir / f"{stem}.csv")
            candidates.append(out_dir / f"{stem}(photo).csv")

    out: list[Path] = []
    seen = set()
    for p in candidates:
        key = str(p).lower()
        if key not in seen:
            out.append(p)
            seen.add(key)
    return out


def _read_asr_text_from_csv(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            if not reader.fieldnames:
                return ""
            text_col = "text" if "text" in reader.fieldnames else "texte" if "texte" in reader.fieldnames else ""
            if not text_col:
                return ""
            parts = [_clean_cell(row.get(text_col)) for row in reader]
    except Exception:
        return ""
    return "\n".join(p for p in parts if p).strip()


def _exact_asr_artifacts_from_audio(audio_path: str) -> dict[str, Path]:
    p = Path(audio_path)
    suffix = p.suffix.lstrip(".")
    token = f"{p.stem}({suffix})" if suffix else p.stem
    out_dir = p.parent.parent / "asr_out" if p.parent.name.lower() == "asr_in" else p.parent
    return {
        "asr_csv": out_dir / f"{token}.csv",
        "photo_csv": out_dir / f"{token}(photo).csv",
        "srt": out_dir / f"{token}.srt",
        "vtt": out_dir / f"{token}.vtt",
    }


def _photo_key(row: Dict[str, Any]) -> str:
    for key in ("photo_rel_native", "photo_path", "nom_fichier_image", "photo"):
        value = _clean_cell(row.get(key))
        if value:
            return value.replace("/", "\\").lower()
    return ""


def _metadata_value_matches(row_value: str, artifact_value: str) -> bool:
    left = _clean_cell(row_value).replace("/", "\\").lower()
    right = _clean_cell(artifact_value).replace("/", "\\").lower()
    if not left or not right:
        return True
    return left == right or left.endswith("\\" + right) or right.endswith("\\" + left)


def _csv_artifact_metadata_errors(path: Path, row: Dict[str, Any], id_affaire: str, id_captation: str) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            fieldnames = reader.fieldnames or []
            first = next(reader, {})
    except Exception as exc:
        return [f"csv illisible: {exc}"]

    errors: list[str] = []
    photo_fields = ("photo_rel_native", "photo_path", "nom_fichier_image", "photo")
    artifact_photo = next((_clean_cell(first.get(k)) for k in photo_fields if k in fieldnames and _clean_cell(first.get(k))), "")
    if artifact_photo and not _metadata_value_matches(_photo_key(row), artifact_photo):
        errors.append(f"photo cible differente: {artifact_photo}")

    if id_affaire and "id_affaire" in fieldnames and not _metadata_value_matches(id_affaire, first.get("id_affaire", "")):
        errors.append(f"id_affaire different: {first.get('id_affaire')}")
    if id_captation and "id_captation" in fieldnames and not _metadata_value_matches(id_captation, first.get("id_captation", "")):
        errors.append(f"id_captation different: {first.get('id_captation')}")
    return errors


def _csv_artifact_photo_key(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            fieldnames = reader.fieldnames or []
            first = next(reader, {})
    except Exception:
        return ""
    for key in ("photo_rel_native", "photo_path", "nom_fichier_image", "photo"):
        if key in fieldnames and _clean_cell(first.get(key)):
            return _clean_cell(first.get(key)).replace("/", "\\").lower()
    return ""


@dataclass
class AsrReconcileStats:
    scanned: int = 0
    propagable: int = 0
    changed: int = 0
    true_pending: int = 0
    conflicts: int = 0
    duplicates: int = 0
    orphans: int = 0
    invalid_photo_mapping: int = 0
    backup_path: str = ""
    details: list[dict[str, Any]] = field(default_factory=list)


def reconcile_submitted_asr_results(
    *,
    rows_ui: list[dict[str, Any]],
    photos_csv: Path,
    ui_fieldnames: list[str],
    id_affaire: str,
    id_captation: str,
    dry_run: bool,
) -> AsrReconcileStats:
    stats = AsrReconcileStats()
    pending_rows = [
        row for row in rows_ui
        if _clean_cell(row.get("dictee_asr_status")).upper() in ASR_RECONCILE_STATUSES
    ]
    audio_counts: dict[str, int] = {}
    for row in pending_rows:
        audio = _clean_cell(row.get("dictee_audio_path_pcfixe")).lower()
        if audio:
            audio_counts[audio] = audio_counts.get(audio, 0) + 1

    expected_photo_csvs = {
        str(_exact_asr_artifacts_from_audio(_clean_cell(row.get("dictee_audio_path_pcfixe")))["photo_csv"]).lower()
        for row in pending_rows
        if _clean_cell(row.get("dictee_audio_path_pcfixe"))
    }
    pending_photo_keys = {_photo_key(row) for row in pending_rows if _photo_key(row)}
    scanned_artifacts: set[str] = set()
    for row in pending_rows:
        audio_path = _clean_cell(row.get("dictee_audio_path_pcfixe"))
        if not audio_path:
            continue
        out_dir = _exact_asr_artifacts_from_audio(audio_path)["photo_csv"].parent
        if not out_dir.exists():
            continue
        for artifact in out_dir.glob("*(photo).csv"):
            artifact_key = str(artifact).lower()
            if artifact_key in scanned_artifacts or artifact_key in expected_photo_csvs:
                continue
            scanned_artifacts.add(artifact_key)
            artifact_photo = _csv_artifact_photo_key(artifact)
            if not artifact_photo:
                continue
            if artifact_photo in pending_photo_keys:
                stats.duplicates += 1
                stats.details.append({
                    "photo_rel_native": artifact_photo,
                    "status": "",
                    "audio_path": "",
                    "result": "duplicate",
                    "reason": f"artefact ASR concurrent ignore: {artifact}",
                })
            else:
                stats.orphans += 1
                stats.details.append({
                    "photo_rel_native": artifact_photo,
                    "status": "",
                    "audio_path": "",
                    "result": "orphan",
                    "reason": f"artefact ASR sans ligne SUBMITTED/LOCAL_PENDING correspondante: {artifact}",
                })

    for row in pending_rows:
        stats.scanned += 1
        photo = _clean_cell(row.get("photo_rel_native"))
        status = _clean_cell(row.get("dictee_asr_status")).upper()
        audio_path = _clean_cell(row.get("dictee_audio_path_pcfixe"))
        detail = {
            "photo_rel_native": photo,
            "status": status,
            "audio_path": audio_path,
            "result": "",
            "reason": "",
        }

        if not audio_path:
            stats.true_pending += 1
            detail["result"] = "pending"
            detail["reason"] = "dictee_audio_path_pcfixe absent"
            stats.details.append(detail)
            continue

        if audio_counts.get(audio_path.lower(), 0) > 1:
            stats.duplicates += 1
            detail["result"] = "duplicate"
            detail["reason"] = "meme WAV reference par plusieurs lignes"
            stats.details.append(detail)
            continue

        artifacts = _exact_asr_artifacts_from_audio(audio_path)
        asr_csv = artifacts["asr_csv"]
        photo_csv = artifacts["photo_csv"]
        detail["asr_csv"] = str(asr_csv)
        detail["photo_csv"] = str(photo_csv)

        if not asr_csv.exists() and not photo_csv.exists():
            stats.true_pending += 1
            detail["result"] = "pending"
            detail["reason"] = "artefacts ASR exacts absents"
            stats.details.append(detail)
            continue

        errors: list[str] = []
        if asr_csv.name != f"{Path(audio_path).stem}({Path(audio_path).suffix.lstrip('.')}).csv":
            errors.append("nom CSV ASR incoherent avec le WAV")
        for csv_path in (asr_csv, photo_csv):
            errors.extend(_csv_artifact_metadata_errors(csv_path, row, id_affaire, id_captation))
        if errors:
            stats.conflicts += 1
            if any("photo cible differente" in err for err in errors):
                stats.invalid_photo_mapping += 1
            detail["result"] = "conflict"
            detail["reason"] = "; ".join(errors)
            stats.details.append(detail)
            continue

        text = _read_asr_text_from_csv(asr_csv) or _read_asr_text_from_csv(photo_csv)
        if not text:
            stats.true_pending += 1
            detail["result"] = "pending"
            detail["reason"] = "texte ASR vide"
            stats.details.append(detail)
            continue

        stats.propagable += 1
        detail["result"] = "propagable"
        detail["reason"] = "artefacts ASR exacts valides"
        stats.details.append(detail)

        if dry_run:
            continue

        changed = False
        changed |= _set_row_value(row, "dictee_asr_text", text)
        changed |= _set_row_value(row, "dictee_asr_status", "OK")
        changed |= _set_row_value(row, "dictee_asr_error", "")
        ts_source = asr_csv if asr_csv.exists() else photo_csv
        asr_ts = datetime.fromtimestamp(ts_source.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        changed |= _set_row_value(row, "dictee_asr_ts", asr_ts)
        if asr_csv.exists():
            changed |= _set_row_value(row, "dictee_asr_csv_path_pcfixe", str(asr_csv))
        if photo_csv.exists():
            changed |= _set_row_value(row, "dictee_asr_photo_csv_path_pcfixe", str(photo_csv))
        audio_file = Path(audio_path)
        if audio_file.exists():
            if not _clean_cell(row.get("dictee_audio_sha256")):
                changed |= _set_row_value(row, "dictee_audio_sha256", sha256_file(audio_file))
            if not _clean_cell(row.get("dictee_audio_size")):
                changed |= _set_row_value(row, "dictee_audio_size", str(audio_file.stat().st_size))
        changed |= _set_row_value(row, "dictee_llm_status", "TODO")
        changed |= _set_row_value(row, "dictee_llm_error", "")
        if changed:
            stats.changed += 1

    if stats.changed and not dry_run:
        backup = atomic_write_csv_timestamp_backup(
            photos_csv,
            rows_ui,
            csv_fieldnames_without_internal(ui_fieldnames),
            "asr_reconcile",
        )
        stats.backup_path = str(backup)
        log.info(
            "ASR reconcile -> photos.csv changed=%d propagable=%d pending=%d conflicts=%d duplicates=%d backup=%s",
            stats.changed,
            stats.propagable,
            stats.true_pending,
            stats.conflicts,
            stats.duplicates,
            str(backup),
        )
        print(f"[DICTEE_RECONCILE] changed={stats.changed} backup={backup} photos_csv={photos_csv}")
    return stats


def print_asr_reconcile_report(stats: AsrReconcileStats) -> None:
    print(
        "[DICTEE_RECONCILE_DRY_RUN] "
        f"scanned={stats.scanned} propagable={stats.propagable} true_pending={stats.true_pending} "
        f"conflicts={stats.conflicts} duplicates={stats.duplicates} orphans={stats.orphans} "
        f"invalid_photo_mapping={stats.invalid_photo_mapping}"
    )
    for detail in stats.details:
        print(
            "[DICTEE_RECONCILE_DRY_RUN_ROW] "
            f"result={detail.get('result')} photo={detail.get('photo_rel_native')} "
            f"status={detail.get('status')} reason={detail.get('reason')} "
            f"audio={detail.get('audio_path')}"
        )


def _read_deferred_asr_text(row: Dict[str, Any]) -> tuple[str, str]:
    for csv_path in _dictation_csv_candidates_from_row(row):
        text = _read_asr_text_from_csv(csv_path)
        if text:
            return text, str(csv_path)
    return "", ""


@dataclass
class DictationAttachStats:
    jobs_read: int = 0
    historical_mappings_read: int = 0
    dictations_joined: int = 0
    photos_enriched: int = 0
    duplicate_dictations: int = 0
    orphans: int = 0
    missing_photo_keys: int = 0
    duplicate_photo_keys: int = 0
    csv_missing_or_unreadable: int = 0


def _list_cell_values(value: Any) -> list[str]:
    text = _clean_cell(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"[\n|]+", text) if part.strip()]


def _join_cell_values(values: list[str]) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_cell(value)
        if cleaned and cleaned not in seen:
            out.append(cleaned)
            seen.add(cleaned)
    return "\n".join(out)


def _dictation_sort_key(item: Dict[str, Any]) -> tuple[str, str]:
    created_at = _clean_cell(item.get("created_at"))
    if created_at:
        return (created_at, _clean_cell(item.get("dictation_id")))
    return (_clean_cell(item.get("dictation_id")), "")


def _dictation_datetime_from_id(value: Any) -> datetime | None:
    match = DICTATION_ID_RE.search(_clean_cell(value))
    if not match:
        return None
    parts = match.group(0).split("_")
    if len(parts) < 4:
        return None
    try:
        return datetime.strptime(parts[1] + parts[2], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _dictation_order_value(item: Dict[str, Any]) -> tuple[float, str]:
    for key in ("created_at", "dictation_ts", "mtime"):
        parsed = parse_ts_or_none(item.get(key))
        if parsed is not None:
            return (parsed.timestamp(), _clean_cell(item.get("dictation_id")))
    parsed_id = _dictation_datetime_from_id(item.get("dictation_id"))
    if parsed_id is not None:
        return (parsed_id.timestamp(), _clean_cell(item.get("dictation_id")))
    return (0.0, _clean_cell(item.get("dictation_id")))


def _split_dictation_ids(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in DICTATION_ID_RE.findall(_clean_cell(value)):
        key = match.strip()
        if key and key not in seen:
            out.append(key)
            seen.add(key)
    return out


def _dictation_csv_path_from_cell(value: Any, dictation_id: str) -> str:
    text = _clean_cell(value)
    marker = _clean_cell(dictation_id)
    if not text or not marker:
        return ""
    pos = text.find(marker)
    if pos < 0:
        return ""
    matches = []
    for suffix in ("(wav).csv", "(wav)(photo).csv", ".csv"):
        found = text.find(suffix, pos)
        if found >= 0:
            matches.append((found, suffix))
    if not matches:
        return ""
    found, suffix = min(matches, key=lambda item: item[0])
    end = found + len(suffix)
    starts = [text.rfind(prefix, 0, pos + 1) for prefix in ("C:\\", "\\\\", "/")]
    start = max(starts)
    if start < 0:
        return ""
    return text[start:end]


def _dictation_id_from_path(path_value: Any) -> str:
    stem = Path(_clean_cell(path_value)).stem
    if not stem:
        return ""
    return re.sub(r"\([^)]*\)$", "", stem)


def _dictation_id_from_job(job: Dict[str, Any]) -> str:
    return (
        _clean_cell(job.get("dictation_id"))
        or _clean_cell(job.get("job_id"))
        or _dictation_id_from_path(job.get("audio_path") or job.get("audio_input"))
        or _dictation_id_from_path(job.get("expected_csv"))
    )


def _load_dictation_photo_map(path: Path | None) -> list[Dict[str, Any]]:
    if not path or not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        log.error("Mapping dictee illisible: path=%s err=%s", str(path), e)
        print(f"[DICTEE_MAP][ERR] path={path} err={e}")
        return []
    if not isinstance(data, list):
        log.error("Mapping dictee ignore: racine JSON non-liste path=%s", str(path))
        print(f"[DICTEE_MAP][ERR] path={path} root_not_list")
        return []
    return [item for item in data if isinstance(item, dict)]


def _index_dictation_photo_map(mappings: list[Dict[str, Any]]) -> tuple[dict[str, Dict[str, Any]], dict[str, Dict[str, Any]], dict[str, Dict[str, Any]]]:
    by_id: dict[str, Dict[str, Any]] = {}
    by_audio: dict[str, Dict[str, Any]] = {}
    by_csv: dict[str, Dict[str, Any]] = {}
    for item in mappings:
        dictation_id = _clean_cell(item.get("dictation_id"))
        if dictation_id and dictation_id not in by_id:
            by_id[dictation_id] = item
        for key in ("audio_path", "server_audio_path"):
            audio = _norm_dictee_path(item.get(key))
            if audio and audio not in by_audio:
                by_audio[audio] = item
        expected_csv = _norm_dictee_path(item.get("expected_csv"))
        if expected_csv and expected_csv not in by_csv:
            by_csv[expected_csv] = item
    return by_id, by_audio, by_csv


def _resolve_historical_dictation_mapping(
    job: Dict[str, Any],
    by_id: dict[str, Dict[str, Any]],
    by_audio: dict[str, Dict[str, Any]],
    by_csv: dict[str, Dict[str, Any]],
) -> Dict[str, Any] | None:
    dictation_id = _dictation_id_from_job(job)
    if dictation_id and dictation_id in by_id:
        return by_id[dictation_id]
    audio = _norm_dictee_path(job.get("audio_path") or job.get("audio_input"))
    if audio and audio in by_audio:
        return by_audio[audio]
    expected_csv = _norm_dictee_path(job.get("expected_csv"))
    if expected_csv and expected_csv in by_csv:
        return by_csv[expected_csv]
    return None


def load_done_dictation_jobs(
    *,
    jobs_root: Path = Path(r"C:\Affaires\_jobs"),
    mapping_path: Path | None = None,
    affaire: str = "",
    captation: str = "",
) -> tuple[list[Dict[str, Any]], DictationAttachStats]:
    stats = DictationAttachStats()
    mappings = _load_dictation_photo_map(mapping_path)
    stats.historical_mappings_read = len(mappings)
    by_id, by_audio, by_csv = _index_dictation_photo_map(mappings)
    records: list[Dict[str, Any]] = []
    done_dir = jobs_root / "done"
    if not done_dir.exists():
        log.info("Dossier jobs done absent: %s", str(done_dir))
        return records, stats
    try:
        job_paths = sorted(done_dir.glob("dictee_*.json"))
    except OSError as e:
        log.error("Lecture jobs done impossible: path=%s err=%s", str(done_dir), e)
        return records, stats

    for job_path in job_paths:
        try:
            job = read_json(job_path)
        except Exception as e:
            log.warning("Job dictee illisible ignore: path=%s err=%s", str(job_path), e)
            continue
        if _clean_cell(job.get("type")) != "asr_voxtral":
            continue
        if affaire and _clean_cell(job.get("affaire")) != affaire:
            continue
        if captation and _clean_cell(job.get("captation")) != captation:
            continue
        stats.jobs_read += 1
        dictation_id = _dictation_id_from_job(job)
        photo_rel_native = _clean_cell(job.get("photo_rel_native"))
        nom_fichier_image = _clean_cell(job.get("nom_fichier_image"))
        created_at = _clean_cell(job.get("created_at"))
        if not photo_rel_native:
            mapped = _resolve_historical_dictation_mapping(job, by_id, by_audio, by_csv)
            if mapped:
                photo_rel_native = _clean_cell(mapped.get("photo_rel_native"))
                nom_fichier_image = nom_fichier_image or _clean_cell(mapped.get("nom_fichier_image"))
                created_at = created_at or _clean_cell(mapped.get("created_at"))
                dictation_id = dictation_id or _clean_cell(mapped.get("dictation_id"))
            else:
                stats.orphans += 1
                log.warning("Dictee ORPHAN sans photo_rel_native ni mapping explicite: job=%s dictation_id=%s", str(job_path), dictation_id)
                continue
        if not photo_rel_native:
            stats.orphans += 1
            log.warning("Dictee ORPHAN mapping sans photo_rel_native: job=%s dictation_id=%s", str(job_path), dictation_id)
            continue
        records.append({
            "dictation_id": dictation_id,
            "photo_rel_native": photo_rel_native,
            "nom_fichier_image": nom_fichier_image,
            "audio_path": _clean_cell(job.get("audio_path") or job.get("audio_input")),
            "expected_csv": _clean_cell(job.get("expected_csv")),
            "created_at": created_at,
            "job_path": str(job_path),
        })
    return records, stats


def _build_unique_photo_index(batch_rows: list[Dict[str, Any]], stats: DictationAttachStats) -> dict[str, Dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in batch_rows:
        key = _clean_cell(row.get("photo_rel_native"))
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    stats.duplicate_photo_keys = sum(1 for count in counts.values() if count > 1)
    out: dict[str, Dict[str, Any]] = {}
    for row in batch_rows:
        key = _clean_cell(row.get("photo_rel_native"))
        if key and counts.get(key) == 1:
            out[key] = row
    return out


def attach_done_dictations_to_batch(
    *,
    batch_rows: list[Dict[str, Any]],
    jobs_root: Path = Path(r"C:\Affaires\_jobs"),
    mapping_path: Path | None = None,
    affaire: str = "",
    captation: str = "",
) -> DictationAttachStats:
    records, stats = load_done_dictation_jobs(
        jobs_root=jobs_root,
        mapping_path=mapping_path,
        affaire=affaire,
        captation=captation,
    )
    photo_index = _build_unique_photo_index(batch_rows, stats)
    grouped: dict[str, list[Dict[str, Any]]] = {}
    for record in records:
        key = _clean_cell(record.get("photo_rel_native"))
        if not key:
            stats.missing_photo_keys += 1
            continue
        if key not in photo_index:
            stats.missing_photo_keys += 1
            log.error("Cle photo dictee absente ou dupliquee dans photos_batch.csv: dictation_id=%s photo_rel_native=%s", record.get("dictation_id"), key)
            continue
        grouped.setdefault(key, []).append(record)

    for photo_key, items in grouped.items():
        row = photo_index[photo_key]
        existing_ids = set(_list_cell_values(row.get("dictee_dictation_ids")))
        texts = _list_cell_values(row.get("dictee_asr_text"))
        ids = _list_cell_values(row.get("dictee_dictation_ids"))
        csv_paths = _list_cell_values(row.get("dictee_asr_csv_paths"))
        audio_paths = _list_cell_values(row.get("dictee_audio_paths"))
        row_changed = False
        for item in sorted(items, key=_dictation_sort_key):
            dictation_id = _clean_cell(item.get("dictation_id"))
            if dictation_id and dictation_id in existing_ids:
                stats.duplicate_dictations += 1
                continue
            expected_csv = _clean_cell(item.get("expected_csv"))
            text = _read_asr_text_from_csv(Path(expected_csv)) if expected_csv else ""
            if not text:
                stats.csv_missing_or_unreadable += 1
                log.error("CSV ASR absent ou illisible: dictation_id=%s expected_csv=%s", dictation_id, expected_csv)
                continue
            texts.append(text)
            if dictation_id:
                ids.append(dictation_id)
                existing_ids.add(dictation_id)
            if expected_csv:
                csv_paths.append(expected_csv)
            audio_path = _clean_cell(item.get("audio_path"))
            if audio_path:
                audio_paths.append(audio_path)
            stats.dictations_joined += 1
            row_changed = True
        if row_changed:
            row["dictee_asr_text"] = _join_cell_values(texts)
            row["dictee_dictation_ids"] = _join_cell_values(ids)
            row["dictee_asr_csv_paths"] = _join_cell_values(csv_paths)
            row["dictee_audio_paths"] = _join_cell_values(audio_paths)
            row["dictee_llm_status"] = "TODO"
            stats.photos_enriched += 1
    log.info(
        "Dictees jobs done -> photos_batch: jobs_read=%d mappings=%d joined=%d photos=%d duplicates=%d orphans=%d missing_photo=%d duplicate_photo=%d csv_missing=%d",
        stats.jobs_read,
        stats.historical_mappings_read,
        stats.dictations_joined,
        stats.photos_enriched,
        stats.duplicate_dictations,
        stats.orphans,
        stats.missing_photo_keys,
        stats.duplicate_photo_keys,
        stats.csv_missing_or_unreadable,
    )
    print(
        "[DICTEE_ATTACH] "
        f"jobs_read={stats.jobs_read} mappings={stats.historical_mappings_read} "
        f"joined={stats.dictations_joined} photos={stats.photos_enriched} "
        f"duplicates={stats.duplicate_dictations} orphans={stats.orphans} "
        f"missing_photo_keys={stats.missing_photo_keys} duplicate_photo_keys={stats.duplicate_photo_keys} "
        f"csv_missing_or_unreadable={stats.csv_missing_or_unreadable}"
    )
    return stats


@dataclass
class DebriefDicteesStats:
    photos_total: int = 0
    photos_avec_dictee: int = 0
    dictees_candidates: int = 0
    dictees_retenues: int = 0
    photos_sans_dictee: int = 0
    dictees_status_invalide: int = 0
    doublons_ambigus: int = 0
    rows_written: int = 0
    local_sha256: str = ""
    nas_publish_method: str = ""
    nas_publish_succeeded: bool = False
    publish_pending: bool = False
    error: str = ""
    preview: list[dict[str, Any]] = field(default_factory=list)


def _asr_csv_text_and_bounds(path: Path) -> tuple[str, str, str]:
    if not path.exists():
        return "", "", ""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            if list(reader.fieldnames or []) != ASR_CSV_FIELDNAMES:
                return "", "", ""
            rows = list(reader)
    except Exception:
        return "", "", ""
    parts = [_clean_cell(row.get("text")) for row in rows]
    text = "\n".join(part for part in parts if part).strip()
    start = _clean_cell(rows[0].get("start")) if rows else ""
    end = _clean_cell(rows[-1].get("end")) if rows else ""
    return text, start, end


def _photo_timestamp_seconds(row: Dict[str, Any]) -> float | None:
    for key in ("t_audio", "horodatage_secondes", "sec_of_day"):
        text = _clean_cell(row.get(key)).replace(",", ".")
        if not text:
            continue
        try:
            return float(text)
        except ValueError:
            continue
    return None


def _format_asr_seconds(value: float) -> str:
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _photo_index_from_ui_rows(rows_ui: list[Dict[str, Any]]) -> tuple[dict[str, Dict[str, Any]], int]:
    counts: dict[str, int] = {}
    for row in rows_ui:
        key = _clean_cell(row.get("photo_rel_native"))
        if key:
            counts[key] = counts.get(key, 0) + 1
    duplicates = sum(1 for count in counts.values() if count > 1)
    return {
        _clean_cell(row.get("photo_rel_native")): row
        for row in rows_ui
        if _clean_cell(row.get("photo_rel_native")) and counts.get(_clean_cell(row.get("photo_rel_native"))) == 1
    }, duplicates


def _dictation_records_by_id(
    *,
    jobs_root: Path,
    mapping_path: Path | None,
    affaire: str,
    captation: str,
) -> dict[str, Dict[str, Any]]:
    records, _stats = load_done_dictation_jobs(
        jobs_root=jobs_root,
        mapping_path=mapping_path,
        affaire=affaire,
        captation=captation,
    )
    out: dict[str, Dict[str, Any]] = {}
    for record in records:
        dictation_id = _clean_cell(record.get("dictation_id"))
        if dictation_id and dictation_id not in out:
            out[dictation_id] = record
    return out


def build_debrief_dictees_rows(
    *,
    rows_ui: list[Dict[str, Any]],
    batch_rows: list[Dict[str, Any]],
    jobs_root: Path = Path(r"C:\Affaires\_jobs"),
    mapping_path: Path | None = None,
    affaire: str = "",
    captation: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any], DebriefDicteesStats]:
    stats = DebriefDicteesStats(photos_total=len(batch_rows))
    photo_index, duplicate_photos = _photo_index_from_ui_rows(rows_ui)
    stats.doublons_ambigus += duplicate_photos
    job_records = _dictation_records_by_id(
        jobs_root=jobs_root,
        mapping_path=mapping_path,
        affaire=affaire,
        captation=captation,
    )
    output_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    seen_photo_keys: set[str] = set()

    for batch_row in batch_rows:
        photo_key = _clean_cell(batch_row.get("photo_rel_native"))
        if not photo_key:
            stats.photos_sans_dictee += 1
            continue
        if photo_key in seen_photo_keys:
            stats.doublons_ambigus += 1
            continue
        seen_photo_keys.add(photo_key)

        ui_row = photo_index.get(photo_key)
        if not ui_row:
            stats.photos_sans_dictee += 1
            continue
        photo_ts = _photo_timestamp_seconds(ui_row)
        if photo_ts is None:
            stats.photos_sans_dictee += 1
            continue

        candidates: list[dict[str, Any]] = []
        for dictation_id in _split_dictation_ids(batch_row.get("dictee_dictation_ids")):
            record = dict(job_records.get(dictation_id) or {})
            record["dictation_id"] = dictation_id
            expected_csv = _clean_cell(record.get("expected_csv"))
            if not expected_csv:
                expected_csv = _dictation_csv_path_from_cell(batch_row.get("dictee_asr_csv_paths"), dictation_id)
            record["expected_csv"] = expected_csv
            candidates.append(record)

        stats.dictees_candidates += len(candidates)
        if not candidates:
            stats.photos_sans_dictee += 1
            continue
        stats.photos_avec_dictee += 1
        latest = sorted(candidates, key=_dictation_order_value)[-1]
        expected_csv = _clean_cell(latest.get("expected_csv"))
        text, source_start, source_end = _asr_csv_text_and_bounds(Path(expected_csv)) if expected_csv else ("", "", "")
        if not text:
            stats.dictees_status_invalide += 1
            continue

        photo_start = _format_asr_seconds(photo_ts)
        output_rows.append({
            "start": photo_start,
            "end": photo_start,
            "speaker": "SPEAKER",
            "text": text,
        })
        stats.dictees_retenues += 1
        preview_item = {
            "photo_rel_native": photo_key,
            "nom_fichier_image": _clean_cell(ui_row.get("nom_fichier_image")) or Path(photo_key).name,
            "photo_timestamp": photo_start,
            "dictation_job_id": _clean_cell(latest.get("dictation_id")),
            "dictation_timestamp": _dictation_order_value(latest)[0],
            "dictation_csv": expected_csv,
            "dictation_source_start": source_start,
            "dictation_source_end": source_end,
            "text_excerpt": text[:180],
        }
        stats.preview.append(preview_item)
        manifest_rows.append(preview_item)

    paired = sorted(zip(output_rows, manifest_rows), key=lambda item: float(item[0]["start"]))
    output_rows = [row for row, _manifest in paired]
    manifest_rows = [manifest for _row, manifest in paired]
    stats.rows_written = len(output_rows)
    manifest = {
        "schema": ASR_CSV_FIELDNAMES,
        "rows": manifest_rows,
        "generated_at": now_ts(),
        "affaire": affaire,
        "captation": captation,
    }
    return output_rows, manifest, stats


def sync_batch_dictations_to_ui_rows(rows_ui: list[Dict[str, Any]], batch_index: dict[str, Dict[str, Any]]) -> int:
    changed = 0
    for row in rows_ui:
        key = _clean_cell(row.get("photo_rel_native"))
        if not key:
            continue
        batch_row = batch_index.get(key)
        if not batch_row:
            continue
        text = _clean_cell(batch_row.get("dictee_asr_text"))
        if not text:
            continue
        row_changed = False
        row_changed |= _set_row_value(row, "dictee_asr_status", "OK")
        row_changed |= _set_row_value(row, "dictee_asr_text", text)
        row_changed |= _set_row_value(row, "dictee_asr_csv_path_pcfixe", _clean_cell(batch_row.get("dictee_asr_csv_paths")))
        row_changed |= _set_row_value(row, "dictee_audio_path_pcfixe", _clean_cell(batch_row.get("dictee_audio_paths")))
        row_changed |= _set_row_value(row, "dictee_llm_status", "TODO")
        if row_changed:
            changed += 1
    return changed


def _norm_dictee_path(value: Any) -> str:
    text = _clean_cell(value).strip().strip('"')
    if not text:
        return ""
    return str(Path(text)).replace("/", "\\").rstrip("\\").lower()


def _set_row_value(row: Dict[str, Any], key: str, value: Any) -> bool:
    value = "" if value is None else value
    if row.get(key) == value:
        return False
    row[key] = value
    return True


def _mark_deferred_asr_ok(row: Dict[str, Any], text: str, csv_path: str) -> bool:
    changed = False
    changed |= _set_row_value(row, "dictee_asr_status", "OK")
    changed |= _set_row_value(row, "dictee_asr_text", text)
    changed |= _set_row_value(row, "dictee_asr_error", "")
    changed |= _set_row_value(row, "dictee_llm_status", "TODO")
    changed |= _set_row_value(row, "dictee_llm_error", "")
    if csv_path and not _clean_cell(row.get("dictee_asr_csv_path_pcfixe")):
        changed |= _set_row_value(row, "dictee_asr_csv_path_pcfixe", csv_path)
    if not _clean_cell(row.get("dictee_asr_ts")):
        changed |= _set_row_value(row, "dictee_asr_ts", now_ts())
    return changed


def _find_spooler_dictee_job(
    row: Dict[str, Any],
    jobs_root: Path = Path(r"C:\Affaires\_jobs"),
) -> dict | None:
    audio = _norm_dictee_path(row.get("dictee_audio_path_pcfixe"))
    csv_candidates = {
        normalized
        for normalized in (_norm_dictee_path(p) for p in _dictation_csv_candidates_from_row(row))
        if normalized
    }
    if not audio and not csv_candidates:
        return None

    for state in ("queued", "running", "done", "failed"):
        state_dir = jobs_root / state
        if not state_dir.exists():
            continue
        try:
            job_paths = list(state_dir.glob("dictee_*.json"))
        except OSError:
            continue
        for job_path in job_paths:
            try:
                job = read_json(job_path)
            except Exception:
                continue
            if _clean_cell(job.get("type")) != "asr_voxtral":
                continue
            job_audio = _norm_dictee_path(job.get("audio_path") or job.get("audio_input"))
            if audio and job_audio and job_audio == audio:
                return {"state": state, "path": str(job_path), "job": job, "matched_on": "audio_path"}
            job_csv = _norm_dictee_path(job.get("expected_csv"))
            if job_csv and job_csv in csv_candidates:
                return {"state": state, "path": str(job_path), "job": job, "matched_on": "expected_csv"}
    return None

def _asr_output_dir_from_row(row: Dict[str, Any]) -> str:
    for key in ("dictee_asr_csv_path_pcfixe", "dictee_asr_photo_csv_path_pcfixe"):
        value = _clean_cell(row.get(key))
        if value:
            return str(Path(value).parent)
    audio_path = _clean_cell(row.get("dictee_audio_path_pcfixe"))
    if not audio_path:
        return ""
    parent = Path(audio_path).parent
    if parent.name.lower() == "asr_in":
        return str(parent.parent / "asr_out")
    return str(parent)


def _post_asr_voxtral_deferred(
    *,
    base_url: str,
    api_key: str,
    audio_path: str,
    output_csv_dir: str,
    timeout: float,
) -> dict:
    headers = {"x-api-key": api_key} if api_key else {}
    payload: Dict[str, Any] = {
        "audio_path": audio_path,
        "lang": "fr",
        "timestamps": True,
        "diarize": False,
        "auto_chunk": True,
        "export_raw_csv": True,
        "export_photo_csv": True,
        "export_chat_csv": False,
        "export_chat_docx": False,
        "temperature": 0.0,
        "top_p": 0.9,
        "client_tag": "annotationphotogpt_batch_deferred_dictee",
    }
    if output_csv_dir:
        payload["output_csv_dir"] = output_csv_dir
    r = requests.post(
        resolve_flask_base_url(base_url) + "/asr_voxtral",
        json=payload,
        headers=headers,
        timeout=max(float(timeout or 0), 600.0),
    )
    if r.status_code == 409:
        raise RuntimeError("HTTP 409: ASR Voxtral deja en cours")
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        detail = ""
        try:
            js = r.json() or {}
            detail = js.get("error") or js.get("detail") or js.get("message") or ""
        except Exception:
            detail = (r.text or "").strip()
        raise RuntimeError(f"HTTP {r.status_code}: {detail or str(e)}") from e
    try:
        return r.json() or {}
    except Exception:
        return {}


def needs_dictee_llm_retry(row_ui: Dict[str, Any]) -> bool:
    if norm_bool(row_ui.get("annotation_validee")):
        return False
    status = _clean_cell(row_ui.get("dictee_asr_status")).upper()
    text = _clean_cell(row_ui.get("dictee_asr_text"))
    if status != "OK" or not text:
        return False
    llm_status = _clean_cell(row_ui.get("dictee_llm_status")).upper()
    asr_ts = _clean_cell(row_ui.get("dictee_asr_ts"))
    llm_asr_ts = _clean_cell(row_ui.get("dictee_llm_asr_ts"))
    if llm_status != "OK":
        return True
    return bool(asr_ts and llm_asr_ts != asr_ts)


def process_deferred_dictees(
    *,
    rows_ui: List[Dict[str, Any]],
    photos_csv: Path,
    ui_fieldnames: List[str],
    base_url: str,
    api_key: str,
    timeout: float,
    selected_indices: set[int] | None = None,
) -> int:
    changed = 0
    now = now_ts()
    for row_pos, row in enumerate(rows_ui):
        if selected_indices is not None and row_pos not in selected_indices:
            continue
        status = _clean_cell(row.get("dictee_asr_status")).upper()
        audio_path = _clean_cell(row.get("dictee_audio_path_pcfixe"))
        asr_text = _clean_cell(row.get("dictee_asr_text"))

        if norm_bool(row.get("annotation_validee")):
            llm_status = _clean_cell(row.get("dictee_llm_status")).upper()
            asr_ts = _clean_cell(row.get("dictee_asr_ts"))
            llm_asr_ts = _clean_cell(row.get("dictee_llm_asr_ts"))
            if status == "OK" and asr_text and (llm_status == "TODO" or (asr_ts and llm_asr_ts != asr_ts)):
                row["dictee_llm_status"] = "SKIP_VALIDATED"
                row["dictee_llm_ts"] = now
                changed += 1
            continue

        if not asr_text:
            reloaded_text, csv_path = _read_deferred_asr_text(row)
            if reloaded_text:
                if _mark_deferred_asr_ok(row, reloaded_text, csv_path):
                    changed += 1
                continue

        if not audio_path or asr_text:
            continue

        spooler_job = _find_spooler_dictee_job(row)
        if spooler_job:
            state = spooler_job["state"]
            job = spooler_job["job"]
            job_path = spooler_job["path"]
            if state in {"queued", "running"}:
                row_changed = False
                row_changed |= _set_row_value(row, "dictee_asr_status", "PENDING")
                row_changed |= _set_row_value(row, "dictee_asr_error", f"ASR spooler {state}: {job_path}")
                if not _clean_cell(row.get("dictee_asr_ts")):
                    row_changed |= _set_row_value(row, "dictee_asr_ts", now_ts())
                if row_changed:
                    changed += 1
                continue
            if state == "done":
                expected_csv = _clean_cell(job.get("expected_csv"))
                text = _read_asr_text_from_csv(Path(expected_csv)) if expected_csv else ""
                if text:
                    if _mark_deferred_asr_ok(row, text, expected_csv):
                        changed += 1
                else:
                    row_changed = False
                    row_changed |= _set_row_value(row, "dictee_asr_status", "ERR")
                    row_changed |= _set_row_value(row, "dictee_asr_error", f"ASR spooler done sans texte exploitable: {job_path}")
                    if expected_csv and not _clean_cell(row.get("dictee_asr_csv_path_pcfixe")):
                        row_changed |= _set_row_value(row, "dictee_asr_csv_path_pcfixe", expected_csv)
                    if not _clean_cell(row.get("dictee_asr_ts")):
                        row_changed |= _set_row_value(row, "dictee_asr_ts", now_ts())
                    if row_changed:
                        changed += 1
                continue
            if state == "failed":
                row_changed = False
                row_changed |= _set_row_value(row, "dictee_asr_status", "ERR")
                row_changed |= _set_row_value(row, "dictee_asr_error", f"ASR spooler failed: {job_path}")
                if not _clean_cell(row.get("dictee_asr_ts")):
                    row_changed |= _set_row_value(row, "dictee_asr_ts", now_ts())
                if row_changed:
                    changed += 1
                continue

        if status != "TODO":
            continue

        if not Path(audio_path).exists():
            row["dictee_asr_status"] = "ERR"
            row["dictee_asr_error"] = "WAV absent"
            row["dictee_asr_ts"] = _clean_cell(row.get("dictee_asr_ts")) or now_ts()
            changed += 1
            continue

        try:
            payload = _post_asr_voxtral_deferred(
                base_url=base_url,
                api_key=api_key,
                audio_path=audio_path,
                output_csv_dir=_asr_output_dir_from_row(row),
                timeout=timeout,
            )
            text = _clean_cell(payload.get("text"))
            if not text:
                text, csv_path = _read_deferred_asr_text(row)
                if csv_path and not _clean_cell(row.get("dictee_asr_csv_path_pcfixe")):
                    row["dictee_asr_csv_path_pcfixe"] = csv_path
            if not text:
                raise RuntimeError("ASR OK mais texte vide")
            row["dictee_asr_status"] = "OK"
            row["dictee_asr_text"] = text
            row["dictee_asr_error"] = ""
            row["dictee_asr_ts"] = _clean_cell(row.get("dictee_asr_ts")) or now_ts()
            row["dictee_llm_status"] = "TODO"
            row["dictee_llm_error"] = ""
            changed += 1
        except Exception as e:
            err = str(e)
            if "HTTP 409" in err and "ASR Voxtral" in err:
                row["dictee_asr_status"] = "BUSY"
                row["dictee_asr_error"] = "HTTP 409: ASR Voxtral deja en cours"
            else:
                row["dictee_asr_status"] = "ERR"
                row["dictee_asr_error"] = err[:600]
            row["dictee_asr_ts"] = _clean_cell(row.get("dictee_asr_ts")) or now_ts()
            changed += 1

    if changed:
        atomic_write_csv(photos_csv, rows_ui, csv_fieldnames_without_internal(ui_fieldnames))
        log.info("Dictées différées traitées: changed=%d photos_csv=%s", changed, str(photos_csv))
        print(f"[DICTEE_ASR] changed={changed} photos_csv={photos_csv}")
    return changed


def reset_vlm_plus_rows(rows: List[Dict[str, Any]]) -> int:
    touched = 0
    for row in rows:
        changed = False
        for field in RESET_VLM_PLUS_FIELDS:
            if row.get(field, "") != "":
                changed = True
            row[field] = ""
        if changed:
            touched += 1
    return touched



def apply_template(s: str, mapping: Dict[str, str]) -> str:
    out = s or ""
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", v or "")
    return out


DICTEE_PHOTO_PRIORITY_INSTRUCTIONS = (
    "La dictée photo est prioritaire sur la description VLM et sur la transcription temporelle.\n"
    "Le VLM peut compléter les éléments visibles compatibles avec la dictée.\n"
    "La transcription temporelle est un contexte secondaire et ne doit pas introduire un fait "
    "qui contredit la dictée ou qui n'est pas clairement rattachable à la photo.\n"
    "Le contexte général et la mission constituent uniquement le cadre général."
)


def append_priority_dictation_to_prompt(
    user_template: str,
    final_prompt: str,
    *,
    dictee_text: str,
    dictee_ok: bool,
    task: str,
) -> str:
    text = (dictee_text or "").strip()
    if not dictee_ok or not text or "{{dictee_block}}" in (user_template or ""):
        return final_prompt

    prompt = (final_prompt or "").rstrip()
    task_instruction = (
        "Pour le libellé, utiliser prioritairement la dictée pour identifier l'ouvrage, "
        "la zone ou le désordre visé. La transcription temporelle ne doit pas détourner "
        "le libellé vers un sujet voisin."
        if task == "libelle"
        else "Pour le commentaire, reprendre la dictée comme source principale."
    )
    dictation_content = "" if text in prompt else f"{text}\n\n"
    block = (
        "DICTÉE PHOTO — SOURCE PRIORITAIRE\n"
        f"{dictation_content}"
        f"{DICTEE_PHOTO_PRIORITY_INSTRUCTIONS}\n"
        f"{task_instruction}"
    )
    return f"{prompt}\n\n{block}" if prompt else block


def build_prompt_with_desc_compat(user_template: str, final_prompt: str, desc_vlm: str) -> str:
    if "{{description_vlm_batch}}" in (user_template or ""):
        return final_prompt
    desc = (desc_vlm or "").strip()
    if not desc:
        return final_prompt
    prefix = "Description de la photo (éléments visibles uniquement) :\n" + desc + "\n\n"
    return prefix + final_prompt


def is_exploitable_vlm_prompt_source(desc_vlm: str) -> bool:
    normalized = " ".join((desc_vlm or "").strip().lower().split())
    if not normalized:
        return False
    weak_values = {
        "photo non exploitable",
        "aucun element precis",
        "aucun élément précis",
        "vue generale",
        "vue générale",
        "element non precise",
        "élément non précisé",
    }
    return normalized not in weak_values


def append_comment_fallback_policy(
    final_prompt: str,
    *,
    dictee_text: str,
    dictee_ok: bool,
    desc_vlm: str,
    transcription: str,
) -> str:
    available_sources = []
    if dictee_ok and (dictee_text or "").strip():
        available_sources.append("dictée photo")
    if is_exploitable_vlm_prompt_source(desc_vlm):
        available_sources.append("description VLM")
    if (transcription or "").strip():
        available_sources.append("transcription temporelle")

    prompt = (final_prompt or "").rstrip()
    if available_sources:
        policy = (
            "CONTRAINTE DE FALLBACK\n"
            "La réponse « Données insuffisantes dans la transcription pour un commentaire factuel. » "
            f"est interdite : source(s) exploitable(s) disponible(s) ({', '.join(available_sources)})."
        )
    else:
        policy = (
            "CONTRAINTE DE FALLBACK\n"
            "Aucune dictée photo, description VLM ou transcription temporelle exploitable n'est disponible ; "
            "la réponse de fallback est autorisée."
        )
    return f"{prompt}\n\n{policy}" if prompt else policy


def compute_pcfixe_dirs_from_photo_rel(photo_rel_native: str, pc_root_affaires: str, id_affaire: str) -> tuple[str, str]:
    """
    photo_rel_native attendu: AE_Expert_captations/<id_captation>/photos/JPG/<nom>
    Retourne: (native_dir_pcfixe, reduced_dir_pcfixe)
    """
    rel = (photo_rel_native or "").strip().replace("\\", "/")
    if not rel:
        return ("", "")

    jpg_dir_rel = Path(rel).parent  # .../photos/JPG
    native_dir = Path(pc_root_affaires) / id_affaire / jpg_dir_rel
    reduced_dir = native_dir.parent / "JPG reduit"
    return (str(native_dir), str(reduced_dir))


# -------------------------
# Transcription
# -------------------------

@dataclass
class TransRow:
    t: float
    text: str
    end: float | None = None

def load_transcription(path: Path) -> List[TransRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f, delimiter=";")
        out = []
        for row in r:
            t = safe_float(row.get("start"))
            end = safe_float(row.get("end"))
            txt = (row.get("text") or "").strip()
            if t is not None and txt:
                spk = (row.get("speaker") or "").strip()
                if spk:
                    txt = f"{spk}: {txt}"
                out.append(TransRow(t, txt, end))
        out.sort(key=lambda x: x.t)
        return out

def extract_transcript_window(trs, center, before, after, max_chars=2000) -> str:
    window_start = center - before
    window_end = center + after
    parts = [
        tr.text
        for tr in trs
        if (tr.end if tr.end is not None else tr.t) >= window_start and tr.t <= window_end
    ]
    s = " ".join(parts)
    return (s[:max_chars] + "…") if len(s) > max_chars else s


# -------------------------
# VLM batch
# -------------------------

_VLM_CHECK_TERMS = [
    "fissure", "fissures", "microfissure", "micro-fissure",
    "cloque", "cloques", "boursouflure", "boursouflures",
    "déformation", "déformations", "voilement", "affaissement",
    "décollement", "gondolement", "gonflement",
    "humidité", "moisi", "mousse", "infiltration", "fuite", "gouttes",
]

VLM_BATCH_PROMPT = (
    "Décris l’image de façon factuelle, en français.\n"
    "Contraintes générales :\n"
    "- Décrire uniquement ce qui est visible. Ne rien inventer.\n"
    "- Si une information est incertaine, l’indiquer explicitement : (certain / probable / incertain).\n"
    "- Ne pas conclure sur un matériau si l’indice visuel n’est pas clair.\n"
    "- Attention particulière aux éléments pertinents pour des constats d’ouvrage : ouvrages, matériaux, assemblages, finitions, désordres apparents, inachèvements.\n"
    "- Ne pas faire d’un objet parasite visible mais hors sujet l’élément central de la description.\n"
    "- Ignorer les personnes, vêtements, meubles, décoration, électroménager, objets personnels, jouets, sauf si leur présence est indispensable pour qualifier l’échelle.\n"
    "- Attention particulière aux conduites/tuyaux/gouttières : segments, coudes, raccords, colliers, changements d’aspect.\n"
    "\n"
    "RÈGLE D’ÉCHELLE (OBLIGATOIRE) :\n"
    "- Pour tout objet pouvant être confondu avec un objet réel (ex : véhicule, engin, outil, figurine, jouet, maquette),\n"
    "  tu DOIS qualifier l’échelle avec l’un des mots exacts suivants :\n"
    "  « jouet », « miniature », « maquette », « figurine », « réel », « échelle incertaine ».\n"
    "- Interdiction d’utiliser un mot ambigu sans qualificatif lorsque l’échelle n’est pas certaine.\n"
    "\n"
    "Sortie attendue :\n"
    "A) Description factuelle (6 à 10 phrases courtes)\n"
    "B) Vérifications guidées (si un contexte est fourni) :\n"
    "   - Lister les éléments mentionnés et donner un statut : [VISIBLE]/[PROBABLE]/[NON VISIBLE]/[INCERTAIN]\n"
    "   - Si [VISIBLE] ou [PROBABLE] : donner 1–2 indices visuels.\n"
)

RERUN_WEAK_LIB = """CORRECTION CIBLEE - LIBELLE

Le precedent libelle etait juge trop faible ou trop generique.

Consignes renforcees :
- Produire un libelle de photo factuel, concret, precis.
- Une seule ligne.
- Viser 5 a 12 mots.
- Decrire l'element principal reellement visible sur la photo.
- Privilegier un nom d'ouvrage, de materiau, de desordre apparent ou d'assemblage visible.
- Eviter absolument les formulations vagues ou passe-partout :
  « vue generale », « element non precise », « photo non exploitable », « ensemble », « detail », ou toute formule equivalente.
- Ne pas faire de commentaire general.
- Ne pas expliquer.
- Ne pas conclure.
- Ne pas employer de formulation de support, de procedure ou de meta-discours.
- Si une dictee ou transcription existe, l'utiliser seulement pour mieux cibler l'objet visible, sans inventer ce qui n'apparait pas sur l'image.

Attendu :
- un libelle court, specifique, exploitable tel quel dans un tableau d'expertise photo.
"""

RERUN_WEAK_COM = """CORRECTION CIBLEE - COMMENTAIRE

Le precedent commentaire etait juge trop faible, trop generique, ou trop proche de la simple description visuelle.

Consignes renforcees :
- Produire un commentaire utile, factuel et exploitable.
- Rester concis.
- Eviter toute redite quasi brute de la description visuelle.
- Apporter une vraie valeur contextuelle a partir de la transcription ou de la dictee si elle existe.
- Ne pas inventer.
- Ne pas conclure.
- Ne pas employer de langage normatif, juridique, causal ou speculatif.
- Eviter absolument les formulations vagues ou passe-partout :
  « photo non exploitable », « aucun element precis », « vue generale », « commentaire non precise », ou toute formule equivalente.
- Faire apparaitre clairement :
  1. ce qui est visible sur la photo ;
  2. ce qui est indique par la transcription ou la dictee ;
  3. sans confondre les deux sources.

Attendu :
- un commentaire plus precis, mieux ancre, et distinct de la seule description VLM.
"""


def build_vlm_context(ctx_general: dict) -> str:
    mission = (ctx_general.get("mission") or "").strip()
    vlm_system = (ctx_general.get("vlm_system") or "").strip()
    vlm_user = (ctx_general.get("vlm_user") or "").strip()
    if vlm_system or vlm_user:
        parts = [
            "CADRE VISUEL (VLM dédié) :",
            "- Le contexte texte ne décrit pas l'image : il sert uniquement à guider l'attention.",
            "- Ne jamais reprendre une donnée textuelle comme élément visible.",
        ]
        if vlm_system:
            parts.append("")
            parts.append("INSTRUCTIONS SYSTÈME VLM :")
            parts.append(vlm_system)
        if vlm_user:
            parts.append("")
            parts.append("CONSIGNE UTILISATEUR VLM :")
            parts.append(vlm_user)
        return "\n".join(parts).strip()

    mission_label = "expertise bâtiment"
    if mission:
        mission_norm = mission.lower()
        if "expert" in mission_norm or "bât" in mission_norm or "ouvrage" in mission_norm:
            mission_label = "expertise bâtiment"
    return (
        "CADRE VISUEL (filtré pour VLM) :\n"
        f"- Type de dossier : {mission_label}\n"
        "- Photo d'expertise bâtiment.\n"
        "- Le contexte texte ne décrit pas l'image : il sert uniquement à guider l'attention.\n"
        "- Ne jamais reprendre une donnée textuelle comme élément visible.\n\n"
        "INSTRUCTIONS VISION (obligatoires) :\n"
        "1) Décrire UNIQUEMENT ce qui est visible et pertinent pour des constats d'ouvrage.\n"
        "2) Priorité : ouvrages, matériaux, assemblages, finitions, désordres apparents, inachèvements.\n"
        "3) Ignorer : personnes, vêtements, meubles, décoration, électroménager, objets personnels, jouets.\n"
        "4) Ne pas inférer (pas de cause, pas de conformité, pas d'explication).\n"
        "5) Si un élément hors sujet apparaît : ne pas en faire l'élément central de la description.\n"
        "6) Exclure toute adresse, état d'avancement, historique procédural ou documentaire du visible décrit.\n"
    )


def extract_vlm_checklist(transcription: str) -> list[str]:
    t = (transcription or "").lower()
    hits = []
    for w in _VLM_CHECK_TERMS:
        if re.search(rf"\b{w}\b", t):
            hits.append(w)
    return sorted(set(hits))[:12]


def build_vlm_specific_context(transcription_extrait: str) -> str:
    transcription_extrait = (transcription_extrait or "").strip()
    parts = []
    if transcription_extrait:
        parts.append("TRANSCRIPTION (extrait) :\n" + transcription_extrait)
    items = extract_vlm_checklist(transcription_extrait)
    if items:
        parts.append(
            "VÉRIFICATIONS GUIDÉES (à contrôler sur l’image — ne pas en déduire que c’est présent) :\n"
            + "\n".join([f"- {it}" for it in items])
        )
    return "\n\n".join(parts).strip()


def post_vision_describe_batch(base_url, api_key, images, *, mode="quality", timeout, context_global="", prompt=""):
    url = resolve_flask_base_url(base_url) + "/vision/describe_batch"
    headers = {"x-api-key": api_key} if api_key else {}

    files, ctx = [], {}
    handles = []

    try:
        for p, c in images:
            fh = p.open("rb")
            handles.append(fh)
            files.append(("files", (p.name, fh, "image/jpeg")))
            if c:
                ctx[p.name] = c

        data = {
            "mode": mode,
            "contexts_json": json.dumps(ctx, ensure_ascii=False),
        }
        if context_global:
            data["context"] = context_global
        if prompt:
            data["prompt"] = prompt

        r = requests.post(url, headers=headers, files=files, data=data, timeout=timeout)
        r.raise_for_status()
        try:
            payload = r.json()
        except Exception:
            raise ValueError(f"Non-JSON response: {r.status_code} {r.text[:500]}")

        # cas normal (API actuelle)
        if isinstance(payload, dict) and "results" in payload:
            return payload["results"]

        # fallback (API legacy / erreur de route)
        if isinstance(payload, list):
            return payload

        # sinon : expliciter l’anomalie
        raise ValueError(f"Bad response shape: {type(payload)} keys={list(payload.keys()) if isinstance(payload, dict) else 'NA'}")

    finally:
        for h in handles:
            h.close()

def get_batch_row(batch_index: dict, photo_rel_native: str, *, defaults: dict | None = None) -> dict:
    k = (photo_rel_native or "").strip()
    if not k:
        raise ValueError("photo_rel_native vide — clé pivot invalide pour photos_batch.csv")

    b = batch_index.get(k)
    if b is None:
        b = {c: "" for c in HEADER_BATCH}
        b["photo_rel_native"] = k

        # État initial cohérent
        b["vlm_status"] = "PENDING"
        b["batch_status"] = ""

        if defaults:
            for kk, vv in defaults.items():
                if kk in b and not b.get(kk):
                    b[kk] = vv

        batch_index[k] = b

    return b


def mark_vlm_err_batch(b: dict, reason: str, *, batch_id: str,
                       vlm_call_id: str | None = None, mode: str | None = None,
                       preserve_existing_reason: bool = True):
    if not b:
        return

    if preserve_existing_reason:
        existing = (b.get("batch_status") or "").strip()
        reason_to_write = existing if (existing and existing.upper().startswith("ERR_")) else reason
    else:
        reason_to_write = reason

    b["vlm_err"] = reason_to_write
    b["vlm_batch_ts"] = now_ts()
    b["batch_status"] = reason_to_write
    b["batch_id"] = batch_id
    b["batch_ts"] = now_ts()

    # ✅ toujours poser
    b["vlm_status"] = "ERR"

    if vlm_call_id is not None:
        b["vlm_call_id"] = vlm_call_id
    if mode is not None:
        b["vlm_mode"] = mode

    if reason_to_write.upper().startswith("ERR_VLM"):
        b["description_vlm_batch"] = ""


def flush_vlm_batch(batch, *, batch_index, base_url, api_key, mode, current_batch_id, context_global="", prompt=""):
    """
    batch: list[tuple[str, Path, str]] = (photo_key, img_path, ctx)
    """
    if not batch:
        return 0, 0

    # (A) marquer RUNNING dans le batch
    for (photo_key, _, _) in batch:
        b = get_batch_row(batch_index, photo_key)
        b["vlm_status"] = "RUNNING"
        b["vlm_batch_id"] = current_batch_id
        b["vlm_mode"] = mode
        b["vlm_batch_ts"] = now_ts()
        b["vlm_err"] = ""

    try:
        timeout = max(300, 150 * len(batch) + 150)
        results = post_vision_describe_batch(
            base_url, api_key,
            [(p, c) for (_, p, c) in batch],
            mode=mode,
            context_global=context_global,
            prompt=prompt,
            timeout=timeout,
        )
        if not isinstance(results, list) or len(results) != len(batch):
            for (photo_key, _, _) in batch:
                b = get_batch_row(batch_index, photo_key)
                mark_vlm_err_batch(b, "ERR_VLM_BAD_RESPONSE_SHAPE", batch_id=current_batch_id)
            return 0, len(batch)

    except Exception as e:
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None)
        body_prefix = ""
        try:
            if resp is not None and getattr(resp, "text", None):
                body_prefix = str(resp.text)[:500]
        except Exception:
            body_prefix = ""
        log.error(
            "flush_vlm_batch exception class=%s message=%s status_http=%s body_prefix=%r",
            type(e).__name__,
            str(e),
            status,
            body_prefix,
        )
        for (photo_key, _, _) in batch:
            b = get_batch_row(batch_index, photo_key)
            mark_vlm_err_batch(b, "ERR_VLM_BATCH", batch_id=current_batch_id)
        log.exception("Erreur dans flush_vlm_batch: %s", e)
        return 0, len(batch)

    time.sleep(2.0)

    # (B) mapping par nom (si le serveur renvoie les noms)
    by_name = {}
    for r in results:
        if isinstance(r, dict):
            kname = _result_name(r)
            if kname:
                by_name[kname.lower()] = r

    expected_names = [p.name.lower() for (_, p, _) in batch]
    have_all = all(n in by_name for n in expected_names)

    ok = err = 0

    # (C) fallback par ordre si mapping incomplet
    if not have_all:
        for (photo_key, img_path, _), r in zip(batch, results):
            b = get_batch_row(batch_index, photo_key)

            if not isinstance(r, dict) or r.get("error"):
                mark_vlm_err_batch(b, "ERR_VLM_RESULT", batch_id=current_batch_id)
                err += 1
                continue

            desc = str(r.get("description") or "").strip()
            if not desc:
                mark_vlm_err_batch(b, "ERR_VLM_EMPTY", batch_id=current_batch_id)
                err += 1
                continue
            ts = now_ts()
            b["description_vlm_batch"] = desc
            b["vlm_status"] = "OK"
            b["vlm_err"] = ""
            b["batch_id"] = current_batch_id
            b["vlm_batch_id"] = current_batch_id
            b["batch_ts"] = ts
            b["vlm_batch_ts"] = ts
            ok += 1

        return ok, err

    # (D) mapping complet par nom
    for (photo_key, img_path, _) in batch:
        b = get_batch_row(batch_index, photo_key)

        r = by_name.get(img_path.name.lower())
        if not r or r.get("error"):
            mark_vlm_err_batch(b, "ERR_VLM_RESULT", batch_id=current_batch_id)
            err += 1
            continue

        desc = str(r.get("description") or "").strip()
        if not desc:
            mark_vlm_err_batch(b, "ERR_VLM_EMPTY", batch_id=current_batch_id)
            err += 1
            continue
        ts = now_ts()
        b["description_vlm_batch"] = desc
        b["vlm_status"] = "OK"
        b["vlm_err"] = ""
        b["vlm_batch_id"] = current_batch_id
        b["vlm_batch_ts"] = ts
        b["batch_id"] = current_batch_id
        b["batch_ts"] = ts

        ok += 1

    return ok, err





# --- Référentiel "points saillants" (détection transcription) ---
POINTS_SAILLANTS_REF = {
    "changement_materiau": [
        "changement de matériau",
        "différence de matériau",
        "plastique",
        "métal",
        "coude en plastique",
        "raccord en plastique"
    ],
    "fissure": [
        "fissure", "fissures", "microfissure", "micro-fissure"
    ],
    "deformation": [
        "déformation", "voilement", "affaissement", "écart"
    ],
    "cloque": [
        "cloque", "cloques", "boursouflure", "boursouflures"
    ],
    "humidite_fuite": [
        "fuite", "fuites", "goutte", "gouttes", "humidité", "mouillé", "infiltration"
    ]
}

# --- Familles lexicales (croisement PHOTO/VLM + TRANSCRIPTION) ---
TERM_FAMILIES = {
    "fissures": [
        "fissure", "fissures", "microfissure", "micro-fissure",
        "craquelure", "craquelures", "lézarde", "lézardes",
    ],
    "aspect": [
        "changement d'aspect", "changement d’aspect",
        "différence d'aspect", "différence d’aspect",
        "aspect", "teinte", "décoloration", "décolorations",
        "tache", "taches", "traces", "salissure", "salissures",
        "auréole", "auréoles", "coulure", "coulures",
    ],
    "humidite": [
        "humidité", "humide", "mouillé", "mouillée",
        "infiltration", "fuite", "gouttes",
    ],
    "materiau": [
        "plastique", "métal", "metal", "alu", "aluminium", "pvc", "raccord", "coude",
    ],
}


def detect_points_saillants(transcription: str) -> list[str]:
    if not transcription:
        return []

    t = transcription.lower()
    detected = []

    for family, keywords in POINTS_SAILLANTS_REF.items():
        for kw in keywords:
            if kw in t:
                detected.append(family)
                break

    return sorted(set(detected))

def format_points_saillants(points: list[str]) -> str:
    if not points:
        return "Aucun point saillant détecté."

    mapping = {
        "changement_materiau": "changement de matériau ou de composant",
        "fissure": "fissure ou microfissuration",
        "deformation": "déformation ou écart géométrique",
        "cloque": "cloque ou boursouflure",
        "humidite_fuite": "présence d’humidité, gouttes ou fuite",
    }

    return "; ".join(mapping[p] for p in points if p in mapping)



def extract_points_saillants(desc_vlm: str, transcription: str, max_items: int = 4) -> list[str]:
    """
    Extrait des "familles" saillantes en croisant :
    - description_vlm (PHOTO)
    - transcription (AUDIO)
    La logique est : une famille est retenue si au moins un terme de la famille
    apparaît dans la description ET dans la transcription.
    """
    d = (desc_vlm or "").lower()
    t = (transcription or "").lower()
    hits: list[str] = []

    for family, words in TERM_FAMILIES.items():
        if any(w in d for w in words) and any(w in t for w in words):
            hits.append(family)

    return hits[:max_items]

SALIENT_REGEX_CLIENT = {
    "changement_materiau": [
        r"\bplastique\b",
        r"\bmétal\b",
        r"\baluminium\b",
        r"\bPVC\b",
        r"\bcoude\b",
        r"\braccord\b",
        r"\bchangement d[eu] matériau\b",
    ],
    "fissure": [
        r"\bfissure[s]?\b",
        r"\bmicro[- ]?fissure[s]?\b",
        r"\bfa[iî]ençage\b",
    ],
    "déformation": [
        r"\bdéformation[s]?\b",
        r"\bvoilement\b",
        r"\baffaissement\b",
        r"\bflèche\b",
    ],
    "cloque": [
        r"\bcloque[s]?\b",
        r"\bboursouflure[s]?\b",
        r"\bdécollement\b",
    ],
    "humidite_fuite": [
        r"\bhumidit[ée]\b",
        r"\bmouill[ée]e?s?\b",
        r"\binfiltration[s]?\b",
        r"\bfuite[s]?\b",
        r"\bgoutte[s]?\b",
    ],
}


def salient_families_from_vlm(desc_vlm: str, max_items: int = 3) -> list[str]:
    """
    Détection UNIQUEMENT sur la description VLM.
    Les clés retournées doivent correspondre STRICTEMENT
    à celles attendues par le serveur Flask.
    """
    d = (desc_vlm or "").strip()
    if not d:
        return []

    out: list[str] = []
    for fam, regexes in SALIENT_REGEX_CLIENT.items():
        if any(re.search(rx, d, re.IGNORECASE) for rx in regexes):
            out.append(fam)
            if len(out) >= max_items:
                break
    return out

def salient_additif_for_commentaire(salient_families: list[str]) -> str:
    if not salient_families:
        return ""

    # Objectif : forcer l'apparition explicite d'au moins un saillant,
    # sans imposer qu'il soit en phrase 1 (qui doit rester "photo uniquement").
    return (
        "\nCONTRAINTE SERVEUR (POINTS SAILLANTS)\n"
        "- Le commentaire DOIT mentionner explicitement AU MOINS UN des points saillants fournis.\n"
        "- Cette mention peut se trouver dans n’importe laquelle des phrases (1 à 4).\n"
        "- Employer des termes explicites (ex. fissure, cloque, déformation, humidité/fuite, plastique, métal, coude, raccord).\n"
        "- Ne pas inventer : si le point saillant n’est pas visible sur la photo, le formuler uniquement dans une phrase ancrée "
        "(\"La transcription/dictée mentionne …\").\n"
    )

# clés autorisées côté Flask (doivent correspondre à SALIENT_REGEX du serveur)
FLASK_SALIENT_KEYS = {"changement_materiau", "fissure", "déformation", "cloque", "humidite_fuite"}

def pick_salient_for_server(desc_vlm: str, fams: list[str]) -> list[str]:
    # voie normale : 1 seul
    kept = filter_salient_for_server(desc_vlm, fams, max_items=1)
    if kept:
        return normalize_salient_families_for_flask(kept)

    # option rare : 2 si vraiment évident (à activer uniquement si vous le souhaitez)
    kept2 = filter_salient_for_server(desc_vlm, fams, max_items=2)
    return normalize_salient_families_for_flask(kept2)


def filter_salient_for_server(desc_vlm: str, fams: list[str], *, max_items: int = 1) -> list[str]:
    """
    Retourne une liste réduite de familles à imposer au serveur (phrase 1).
    Principe : seulement si c'est très probablement "visible" et non incertain.
    """
    if not fams:
        return []

    d = (desc_vlm or "").lower()

    # si la description VLM nuance, on n'impose rien
    if any(m in d for m in UNCERTAINTY_MARKERS):
        return []

    kept: list[str] = []
    for fam in fams:
        # fam doit exister dans le référentiel regex du client
        regexes = SALIENT_REGEX_CLIENT.get(fam, [])
        if not regexes:
            continue

        # au moins un motif doit matcher la description VLM
        if any(re.search(rx, d, re.IGNORECASE) for rx in regexes):
            kept.append(fam)

        if len(kept) >= max_items:
            break

    return kept

def normalize_salient_families_for_flask(fams: list[str]) -> list[str]:
    if not fams:
        return []

    norm: list[str] = []
    for f in fams:
        f0 = (f or "").strip().lower()

        if f0 == "deformation":
            f0 = "déformation"

        if f0 in FLASK_SALIENT_KEYS and f0 not in norm:
            norm.append(f0)

    return norm



UNCERTAINTY_MARKERS = [
    "probable", "incertain", "non certain", "non certaine", "semble", "pourrait"
]


def vlm_backoff_sleep(fail_streak: int):
    if fail_streak <= 0:
        return
    if fail_streak == 1:
        time.sleep(3)
    elif fail_streak == 2:
        time.sleep(10)
    else:
        time.sleep(30)


def make_request_id(photo_id: str, task: str, attempt: int) -> str:
    # photo_id: index CSV, hash de path, ou nom fichier
    # task: "libelle" / "commentaire"
    # attempt: 1..n
    ts = int(time.time() * 1000)
    rnd = uuid.uuid4().hex[:6]
    return f"{photo_id}-{task}-a{attempt}-{ts}-{rnd}"



# -------------------------
# Main
# -------------------------

def main() -> int:
    global UI_DEFAULTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--infos", required=True)
    ap.add_argument("--dry-run", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--night", type=int, default=0)
    ap.add_argument("--vlm-strict", type=int, default=0)  # 1 => 1 image par flush
    ap.add_argument("--reset-vlm", type=int, default=0)  # 1 => relance VLM même si ERR/SKIP
    ap.add_argument("--reset-llm", type=int, default=0)  # 1 => relance PASS 2 sans effacer le VLM
    ap.add_argument("--reset-vlm-plus", type=int, default=0)  # 1 => remise à blanc ciblée des sorties VLM/LLM
    ap.add_argument("--only-new-dictee", type=int, default=0)
    ap.add_argument("--dictation-photo-map", default="")
    ap.add_argument("--rerun-weak", type=int, default=0)
    ap.add_argument("--rerun-weak-backend", default="same")
    ap.add_argument("--reconcile-dictee-dry-run", type=int, default=0)
    ap.add_argument("--only-photo-rel", action="append", default=[])
    ap.add_argument("--only-photo-rel-list", default="")
    ap.add_argument("--job-id", default="")
    ap.add_argument("--repair-empty-stamp-job-id", type=int, default=0)
    ap.add_argument("--repair-job-id", default="")
    ap.add_argument("--publish-only", type=int, default=0)
    ap.add_argument("--debrief-dictees-dry-run", type=int, default=0)
    ap.add_argument("--debrief-dictees-only", type=int, default=0)


    args = ap.parse_args()
    reset_vlm = bool(args.reset_vlm)
    reset_llm = bool(args.reset_llm)
    reset_vlm_plus = bool(args.reset_vlm_plus)
    print(f"[DEBUG] reset_vlm={bool(args.reset_vlm)}")
    print(f"[DEBUG] reset_llm={bool(args.reset_llm)}")
    print(f"[DEBUG] reset_vlm_plus={bool(args.reset_vlm_plus)}")
    if sum(1 for x in (reset_vlm, reset_llm, reset_vlm_plus) if x) > 1:
        return die(2, "Options incompatibles : utiliser un seul reset parmi --reset-vlm / --reset-llm / --reset-vlm-plus")
    is_dry = bool(args.dry_run)
    debrief_dictees_dry_run = bool(args.debrief_dictees_dry_run)
    debrief_dictees_only = bool(args.debrief_dictees_only)
    only_new_dictee = bool(args.only_new_dictee)
    rerun_weak = bool(args.rerun_weak)
    reconcile_dictee_dry_run = bool(args.reconcile_dictee_dry_run)
    only_photo_rel_targets = parse_only_photo_rel_targets(args.only_photo_rel, args.only_photo_rel_list)
    rerun_weak_backend = str(args.rerun_weak_backend or "same").strip().lower()
    if rerun_weak_backend not in ("same", "local", "remote", "openai"):
        return die(2, "Option invalide pour --rerun-weak-backend : same / local / remote")
    print(f"[DEBUG] is_dry={is_dry} args.dry_run={args.dry_run} args.limit={args.limit}")
    vlm_strict = bool(args.vlm_strict)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    vlm_call_id = uuid.uuid4().hex[:10]
    t_call0 = time.time()


    VLM_STATUSES = ("PENDING", "RUNNING", "OK", "ERR")


    infos_path = Path(args.infos).resolve()
    infos = read_json(infos_path)
    id_affaire = str(infos.get("id_affaire") or infos.get("affaire") or os.getenv("SPOOLER_ID_AFFAIRE", "")).strip()
    id_captation = str(infos.get("id_captation") or infos.get("captation") or os.getenv("SPOOLER_ID_CAPTATION", "")).strip()
    pc = infos.get("pcfixe", {}) or {}

    # photos_csv : priorité pcfixe, sinon racine
    photos_csv = Path(pc.get("fichier_photos") or infos["fichier_photos"])

    # photos_batch_csv : priorité pcfixe, sinon racine, sinon fallback canonique
    batch_path_str = str(pc.get("fichier_photos_batch") or infos.get("fichier_photos_batch") or "").strip()
    photos_batch_csv = Path(batch_path_str) if batch_path_str else photos_csv.with_name(photos_csv.stem + "_batch.csv")

    # si absent dans pcfixe, inscrire et sauvegarder dans le même JSON passé en argument
    if not pc.get("fichier_photos_batch"):
        pc["fichier_photos_batch"] = str(photos_batch_csv)
        infos["pcfixe"] = pc
        if not reconcile_dictee_dry_run and not debrief_dictees_dry_run and not debrief_dictees_only and not bool(args.repair_empty_stamp_job_id) and not bool(args.publish_only):
            write_json(infos_path, infos)

    if bool(args.repair_empty_stamp_job_id):
        repair_photos_csv = _local_counterpart_if_available(photos_csv, infos, pc, id_affaire)
        repair_batch_csv = _local_counterpart_if_available(photos_batch_csv, infos, pc, id_affaire)
        repair_stamp = repair_batch_csv.with_suffix(repair_batch_csv.suffix + ".stamp")
        result = repair_empty_photos_batch_stamp_job_id(
            photos_csv=repair_photos_csv,
            photos_batch_csv=repair_batch_csv,
            stamp_path=repair_stamp,
            id_affaire=id_affaire,
            id_captation=id_captation,
            repair_job_id=args.repair_job_id,
        )
        print("[BATCH_OUTPUT] " + json.dumps(result, ensure_ascii=False, sort_keys=True))
        log.info("Stamp job_id repare: %s", json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if bool(args.publish_only):
        print("[PUBLISH_ONLY] Publication only = true")
        print("[RUN] VLM calls=0 images=0 | LLM calls=0 (lib=0, com=0)")
        result = publish_only_existing_batch_outputs(
            infos=infos,
            pc=pc,
            photos_csv=photos_csv,
            photos_batch_csv=photos_batch_csv,
            id_affaire=id_affaire,
            id_captation=id_captation,
        )
        print("[BATCH_OUTPUT] " + json.dumps(result, ensure_ascii=False, sort_keys=True))
        log.info("Publication only terminee: %s", json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if debrief_dictees_only:
        local_photos_csv = _local_counterpart_if_available(photos_csv, infos, pc, id_affaire)
        local_batch_csv = _local_counterpart_if_available(photos_batch_csv, infos, pc, id_affaire)
        if not local_photos_csv.exists():
            raise FileNotFoundError(f"photos.csv PC fixe introuvable: {local_photos_csv}")
        if not local_batch_csv.exists():
            raise FileNotFoundError(f"photos_batch.csv PC fixe introuvable: {local_batch_csv}")
        stamp_path = local_batch_csv.with_suffix(local_batch_csv.suffix + ".stamp")
        output_info = verify_existing_photos_batch_stamp(
            photos_csv=local_photos_csv,
            photos_batch_csv=local_batch_csv,
            stamp_path=stamp_path,
            id_affaire=id_affaire,
            id_captation=id_captation,
        )
        rows_ui, _ui_fields = read_csv_semicolon(local_photos_csv)
        batch_rows, _batch_fields = read_csv_semicolon(local_batch_csv)
        dictation_photo_map = Path(args.dictation_photo_map) if str(args.dictation_photo_map or "").strip() else infos_path.with_name("dictation_photo_map.json")
        debrief_info = generate_and_publish_debrief_dictees(
            rows_ui=rows_ui,
            batch_rows=batch_rows,
            infos=infos,
            pc=pc,
            id_affaire=id_affaire,
            id_captation=id_captation,
            mapping_path=dictation_photo_map,
            preview_only=False,
        )
        output_info.update({k: v for k, v in debrief_info.items() if k != "debrief_dictees_preview"})
        print("[BATCH_OUTPUT] " + json.dumps(output_info, ensure_ascii=False, sort_keys=True))
        log.info("Debrief dictees only termine: %s", json.dumps(output_info, ensure_ascii=False, sort_keys=True))
        return 0

    annotation_job_id = resolve_annotation_batch_job_id(
        infos=infos,
        cli_job_id=args.job_id,
        id_affaire=id_affaire,
        id_captation=id_captation,
    )
    print(f"[JOB] job_id={annotation_job_id}")
    log.info("Annotation batch job_id=%s affaire=%s captation=%s", annotation_job_id, id_affaire, id_captation)

    pf_vlm = 0
    pf_llm = 0
    pf_skip = 0
    actual_vlm_calls = 0
    actual_vlm_images = 0
    actual_llm_calls = 0
    actual_llm_lib = 0
    actual_llm_com = 0

    rid = uuid.uuid4().hex[:8]
    current_batch_id = uuid.uuid4().hex[:10]
    t0 = time.time()
    

    pf_reasons = {}  # dict[str, int]

    def pf_skip_reason(reason: str):
        pf_reasons[reason] = pf_reasons.get(reason, 0) + 1

    photos_csv, photos_batch_csv, batch_sync_context = prepare_batch_sync_sources(
        infos=infos,
        pc=pc,
        photos_csv=photos_csv,
        photos_batch_csv=photos_batch_csv,
        id_affaire=id_affaire,
        id_captation=id_captation,
        is_dry=is_dry or debrief_dictees_dry_run,
    )
    pc["fichier_photos"] = str(photos_csv)
    pc["fichier_photos_batch"] = str(photos_batch_csv)
    batch_sync_context["job_id"] = annotation_job_id

    if reconcile_dictee_dry_run:
        photos_csv_reconcile = _local_counterpart_if_available(photos_csv, infos, pc, id_affaire)
        if not photos_csv_reconcile.exists():
            raise FileNotFoundError(f"photos.csv PC fixe introuvable pour reconciliation: {photos_csv_reconcile}")
        with photos_csv_reconcile.open("r", encoding="utf-8-sig", newline="") as f:
            rows_ui_reconcile = list(csv.DictReader(f, delimiter=";"))
        if not rows_ui_reconcile:
            raise RuntimeError(f"photos.csv vide pour reconciliation: {photos_csv_reconcile}")
        for i, row in enumerate(rows_ui_reconcile):
            row["idx"] = i
        ui_fieldnames_reconcile = ensure_columns(rows_ui_reconcile, UI_DEFAULTS)
        stats = reconcile_submitted_asr_results(
            rows_ui=rows_ui_reconcile,
            photos_csv=photos_csv_reconcile,
            ui_fieldnames=ui_fieldnames_reconcile,
            id_affaire=id_affaire,
            id_captation=id_captation,
            dry_run=True,
        )
        print(f"[DICTEE_RECONCILE_DRY_RUN] photos_csv={photos_csv_reconcile}")
        print_asr_reconcile_report(stats)
        return 0

    config_llm_path = _local_counterpart_if_available(Path(pc["config_llm"]), infos, pc, id_affaire)
    pc["config_llm"] = str(config_llm_path)
    cfg_llm = read_json(config_llm_path)

    lib_before, lib_after = resolve_transcript_window(infos, cfg_llm, "libelle")
    com_before, com_after = resolve_transcript_window(infos, cfg_llm, "commentaire")


    photos_csv = Path(pc["fichier_photos"])
    batch_path_str = str(pc.get("fichier_photos_batch") or "").strip()
    photos_batch_csv = Path(batch_path_str) if batch_path_str else photos_csv.with_name(photos_csv.stem + "_batch.csv")
    log.info("Preflight paths photos_csv=%s photos_batch_csv=%s", str(photos_csv), str(photos_batch_csv))
    print(f"[PREFLIGHT] photos_csv={photos_csv}")
    print(f"[PREFLIGHT] photos_batch_csv={photos_batch_csv}")
    if not photos_csv.exists():
        raise FileNotFoundError(f"photos.csv PC fixe introuvable: {photos_csv}")
    batch_rows = load_or_init_batch(photos_batch_csv)
    batch_existing_keys = {
        key
        for r in batch_rows
        for key in _photo_rel_match_keys(r.get("photo_rel_native"))
    }
    batch_index = {r["photo_rel_native"]: r for r in batch_rows if r.get("photo_rel_native")}


    trans_csv  = Path(pc["fichier_transcription"])
    cfg_llm    = read_json(Path(pc["config_llm"]))
    ctx_general, ctx_general_source = load_batch_context_general(infos, pc, id_affaire)
    log.info("Contexte general utilise: %s", ctx_general_source)
    vlm_context_global = build_vlm_context(ctx_general)

    vlm_log_path = photos_csv.with_suffix(f".vlm_{run_id}.jsonl")
    def log_vlm_event(event: dict):
        with vlm_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    trs = load_transcription(trans_csv)



    with photos_csv.open("r", encoding="utf-8-sig", newline="") as f:
        rows_ui = list(csv.DictReader(f, delimiter=";"))
    log.info("CSV runtime photos_csv=%s rows_ui=%d", str(photos_csv), len(rows_ui))
    print(f"[CSV] photos_csv={photos_csv} rows={len(rows_ui)}")
    if not rows_ui:
        raise RuntimeError(f"photos.csv PC fixe vide ou sans lignes exploitables: {photos_csv}")
    for i, row in enumerate(rows_ui):
        row["idx"] = i

    UI_DEFAULTS = {
        "annotation_validee": "0",
        "dictee_audio_path_pcfixe": "",
        "dictee_asr_status": "",
        "dictee_asr_text": "",
        "dictee_asr_error": "",
        "dictee_asr_ts": "",
        "dictee_asr_csv_path_pcfixe": "",
        "dictee_asr_photo_csv_path_pcfixe": "",
        "dictee_llm_status": "",
        "dictee_llm_asr_ts": "",
        "dictee_llm_error": "",
        "dictee_llm_ts": "",
        # éventuellement d'autres champs UI si vous voulez les garantir
    }

    UI_DEFAULTS.setdefault("dictee_audio_sha256", "")
    UI_DEFAULTS.setdefault("dictee_audio_size", "")
    ui_fieldnames = ensure_columns(rows_ui, UI_DEFAULTS)
    reconcile_stats = reconcile_submitted_asr_results(
        rows_ui=rows_ui,
        photos_csv=photos_csv,
        ui_fieldnames=ui_fieldnames,
        id_affaire=id_affaire,
        id_captation=id_captation,
        dry_run=is_dry,
    )
    if is_dry and reconcile_stats.scanned:
        print_asr_reconcile_report(reconcile_stats)

    batch_rows = []
    if photos_batch_csv.exists():
        with photos_batch_csv.open("r", encoding="utf-8-sig", newline="") as f:
            batch_rows = list(csv.DictReader(f, delimiter=";"))
    log.info("CSV runtime photos_batch_csv=%s exists=%s batch_rows=%d", str(photos_batch_csv), photos_batch_csv.exists(), len(batch_rows))
    print(f"[CSV] photos_batch_csv={photos_batch_csv} exists={photos_batch_csv.exists()} rows={len(batch_rows)}")
    ui_keys = {
        (r.get("photo_rel_native") or "").strip()
        for r in rows_ui
        if (r.get("photo_rel_native") or "").strip()
    }
    batch_keys = {
        (r.get("photo_rel_native") or "").strip()
        for r in batch_rows
        if (r.get("photo_rel_native") or "").strip()
    }
    common_keys = ui_keys & batch_keys
    batch_keys_missing_in_ui = batch_keys - ui_keys
    log.info(
        "Preflight coherence nb_rows_ui=%d nb_rows_batch=%d common_photo_rel_native=%d batch_keys_missing_in_ui=%d",
        len(rows_ui),
        len(batch_rows),
        len(common_keys),
        len(batch_keys_missing_in_ui),
    )
    print(
        f"[PREFLIGHT] nb_rows_ui={len(rows_ui)} nb_rows_batch={len(batch_rows)} "
        f"common_photo_rel_native={len(common_keys)} batch_keys_missing_in_ui={len(batch_keys_missing_in_ui)}"
    )

    # Garantir le schéma batch (HEADER_BATCH)
    BATCH_DEFAULTS = {c: "" for c in HEADER_BATCH}
    batch_fieldnames = ensure_columns(batch_rows, BATCH_DEFAULTS)

    dictation_photo_map = Path(args.dictation_photo_map) if str(args.dictation_photo_map or "").strip() else infos_path.with_name("dictation_photo_map.json")
    if debrief_dictees_dry_run:
        preview_info = generate_and_publish_debrief_dictees(
            rows_ui=rows_ui,
            batch_rows=batch_rows,
            infos=infos,
            pc=pc,
            id_affaire=id_affaire,
            id_captation=id_captation,
            mapping_path=dictation_photo_map,
            preview_only=True,
        )
        print(f"[DEBRIEF_DICTEES_DRY_RUN] rows={preview_info['debrief_dictees_rows']}")
        print(f"[DEBRIEF_DICTEES_DRY_RUN] local_path={preview_info['debrief_dictees_local_path']}")
        print(f"[DEBRIEF_DICTEES_DRY_RUN] nas_path={preview_info['debrief_dictees_nas_path']}")
        for item in preview_info.get("debrief_dictees_preview", []):
            print(
                "[DEBRIEF_DICTEES_DRY_RUN_ROW] "
                f"photo={item.get('photo_rel_native')} nom={item.get('nom_fichier_image')} "
                f"photo_ts={item.get('photo_timestamp')} dictation_job_id={item.get('dictation_job_id')} "
                f"dictation_ts={item.get('dictation_timestamp')} excerpt={item.get('text_excerpt')}"
            )
        print("[BATCH_OUTPUT] " + json.dumps(preview_info, ensure_ascii=False, sort_keys=True))
        return 0
    if not is_dry:
        attach_done_dictations_to_batch(
            batch_rows=batch_rows,
            mapping_path=dictation_photo_map,
            affaire=_clean_cell(infos.get("id_affaire")),
            captation=infos_path.parent.name,
        )

    if reset_vlm_plus:
        touched = reset_vlm_plus_rows(batch_rows)
        atomic_write_csv(photos_batch_csv, batch_rows, HEADER_BATCH)
        log.info("Reset VLM+ applied path=%s rows=%d touched=%d", str(photos_batch_csv), len(batch_rows), touched)
        print(f"[RESET_VLM_PLUS] path={photos_batch_csv} rows={len(batch_rows)} touched={touched}")
        return 0

    # Index par clé
    batch_index = {}
    for r in batch_rows:
        k = (r.get("photo_rel_native") or "").strip()
        if k:
            batch_index[k] = r

    sync_batch_dictations_to_ui_rows(rows_ui, batch_index)

    rerun_weak_reclassified = 0
    if rerun_weak:
        for b in batch_rows:
            original_status = str(b.get("batch_status") or "").strip()
            interpreted_status, reason = reinterpret_llm_weak_status(b)
            if interpreted_status and interpreted_status != original_status.strip().upper():
                b["__rerun_weak_original_status"] = original_status
                b["__rerun_weak_interpreted_status"] = interpreted_status
                b["__rerun_weak_reason"] = reason
                b["batch_status"] = interpreted_status
                rerun_weak_reclassified += 1
            elif interpreted_status in ("WEAK_LIB", "OK_LIB_COM_WEAK"):
                b["__rerun_weak_original_status"] = original_status
                b["__rerun_weak_interpreted_status"] = interpreted_status
                b["__rerun_weak_reason"] = reason or "statut deja faible"
        if rerun_weak_reclassified:
            print(f"[SELECT] rerun_weak reclassification_memoire={rerun_weak_reclassified}")



    n_ok = 0
    n_weak = 0
    n_weak_com = 0
    n_err = 0
    n_skip = 0
    n_done = 0  # nombre de lignes effectivement traitées (OK/ERR/SKIP)
    n_rerun_weak = 0
    n_rerun_weak_ok = 0
    n_rerun_weak_still = 0


    llm_backend = str(cfg_llm.get("llm_backend", "local") or "local").strip().lower()
    local_cfg = cfg_llm.get("local_llm", {}) or {}
    base_url = resolve_flask_base_url(local_cfg.get("base_url", "")) if not is_dry else str(local_cfg.get("base_url", "") or "").strip()
    api_key  = str(local_cfg.get("api_key", "") or "").strip()
    local_model = str(local_cfg.get("model", "") or "").strip()
    openai_api_key = resolve_openai_api_key()
    local_llm_api_key = resolve_local_llm_api_key(api_key)
    if rerun_weak:
        if rerun_weak_backend in ("remote", "openai"):
            llm_backend = "openai"
        elif rerun_weak_backend == "local":
            llm_backend = "local"
    if llm_backend not in ("local", "openai"):
        raise RuntimeError(f"llm_backend non supporté: {llm_backend}")
    if llm_backend == "openai" and not openai_api_key:
        raise RuntimeError(f"OPENAI_API_KEY introuvable (env ou {BATCH_ENV_PATH})")

    batch_cfg = cfg_llm.get("batch", {})
    mt = (batch_cfg.get("max_tokens") or {})
    temp = (batch_cfg.get("temperature") or {})


    prompts_dir = Path(pc["config_llm"]).resolve().parent
    prompt_path = resolve_batch_prompt_path(prompts_dir)
    prompts = read_json(prompt_path)
    log.info("Template prompts batch utilise: %s", str(prompt_path))

    sys_lib = prompts["libelle"]["system"]
    usr_lib = prompts["libelle"]["user"]
    sys_com = prompts["commentaire"]["system"]
    usr_com = prompts["commentaire"]["user"]

    batch_cfg = cfg_llm.get("batch") or {}
    max_tokens_lib = int((batch_cfg.get("max_tokens") or {}).get("libelle", cfg_llm.get("max_tokens_libelle", 120)))
    max_tokens_com = int((batch_cfg.get("max_tokens") or {}).get("commentaire", cfg_llm.get("max_tokens_commentaire", 500)))
    temp_lib = float((batch_cfg.get("temperature") or {}).get("libelle", cfg_llm.get("temperature", 0.25)))
    temp_com = float((batch_cfg.get("temperature") or {}).get("commentaire", cfg_llm.get("temperature", 0.2)))

    # 0) Construire UNE fois la sélection

    pc_root = (pc.get("root_affaires") or r"C:\Affaires").rstrip("\\/")
    id_affaire = str(infos.get("id_affaire") or "").strip()
    if not id_affaire:
        raise RuntimeError("id_affaire manquant dans infos_projet.json")

    for row_ui in rows_ui:
        photo_key = (row_ui.get("photo_rel_native") or "").strip()
        if not photo_key:
            continue

        # IMPORTANT : get_batch_row doit créer une ligne par défaut si absente
        b = get_batch_row(batch_index, photo_key)

        native_dir, reduced_dir = compute_pcfixe_dirs_from_photo_rel(photo_key, pc_root, id_affaire)

        if native_dir and not b.get("chemin_photo_native_pcfixe"):
            b["chemin_photo_native_pcfixe"] = native_dir
        if reduced_dir and not b.get("chemin_photo_reduite_pcfixe"):
            b["chemin_photo_reduite_pcfixe"] = reduced_dir

        # Disponibilité : on préfère "JPG reduit", sinon "JPG"
        name = row_ui.get("nom_fichier_image", "") or ""
        img = resolve_img_path({"chemin_photo_reduite_pcfixe": b.get("chemin_photo_reduite_pcfixe", ""), "nom_fichier_image": name})
        if img is None:
            img = resolve_img_path({"chemin_photo_reduite_pcfixe": b.get("chemin_photo_native_pcfixe", ""), "nom_fichier_image": name})

        b["photo_disponible_pcfixe"] = "1" if img else "0"
        if img and not (b.get("date_copie_pcfixe") or "").strip():
            b["date_copie_pcfixe"] = now_ts()


    selected_idx: list[int] = []
    reject_counts: dict[str, int] = {}

    def reject(reason: str):
        reject_counts[reason] = reject_counts.get(reason, 0) + 1

    def ui_row(i: int) -> dict:
        return rows_ui[i]

    def batch_row_from_ui_index(i: int) -> dict:
        photo_key = (rows_ui[i].get("photo_rel_native") or "").strip()
        return get_batch_row(batch_index, photo_key)



    for i, row in enumerate(rows_ui):
        if args.limit and len(selected_idx) >= args.limit:
            break
        if norm_bool(row.get("annotation_validee")):
            reject("annotation_validee")
            continue

        photo_key = (row.get("photo_rel_native") or "").strip()
        if not photo_key:
            reject("photo_rel_native_absent")
            continue
        b = get_batch_row(batch_index, photo_key)
        dictee_retry_target = needs_dictee_llm_retry(row)

        if safe_float(row.get("t_audio")) is None and not dictee_retry_target:
            reject("t_audio_absent")
            continue

        if only_new_dictee:
            dictee_status = (row.get("dictee_asr_status") or "").strip().upper()
            dictee_text = (row.get("dictee_asr_text") or "").strip()
            dictee_ts = parse_ts_or_none(row.get("dictee_asr_ts"))
            last_batch_ts = parse_ts_or_none(b.get("batch_ts"))

            if dictee_status != "OK":
                reject("dictee_status_not_ok")
                continue
            if not dictee_text:
                reject("dictee_text_empty")
                continue
            if dictee_ts is None:
                reject("dictee_ts_absent_or_invalid")
                continue
            if last_batch_ts is not None and not (dictee_ts > last_batch_ts):
                reject("dictee_not_newer_than_batch")
                continue

        # disponibilité PC fixe : champ batch
        if not norm_bool(b.get("photo_disponible_pcfixe")):
            reject("photo_disponible_pcfixe_false")
            continue

        # statut VLM/batch : champs batch
        bs_u = (b.get("batch_status") or "").strip().upper()
        vs   = (b.get("vlm_status") or "").strip().upper()
        if rerun_weak:
            if bs_u not in ("WEAK_LIB", "OK_LIB_COM_WEAK"):
                reject("rerun_weak_not_target")
                continue

        if bs_u.startswith("ERR_VLM") or bs_u == "SKIP_VLM_EN_ERREUR":
            b["batch_status"] = ""
            b["vlm_status"] = "PENDING"
            vs = "PENDING"

        if vs not in VLM_STATUSES:
            b["vlm_status"] = "PENDING"
            vs = "PENDING"

        resolver_row = {
            "chemin_photo_reduite_pcfixe": b.get("chemin_photo_reduite_pcfixe", ""),
            "nom_fichier_image": row.get("nom_fichier_image", ""),
        }
        img = resolve_img_path(resolver_row)
        if img is None:
            reject("image_introuvable_apres_resolution")
            continue

        selected_idx.append(i)
        print(f"[DBG] idx={i} img=OK vlm_status=[{b.get('vlm_status')}] batch_status=[{b.get('batch_status')}]")


    log.info("Selection diagnostics total_ui=%d selected=%d reject_counts=%s", len(rows_ui), len(selected_idx), reject_counts)
    print(f"[SELECT] total_ui={len(rows_ui)} selected={len(selected_idx)} reject_counts={reject_counts}")
    if rerun_weak and not selected_idx:
        print("[SELECT] rerun_weak: aucune ligne WEAK a retraiter")
    if is_dry and rerun_weak and selected_idx:
        planned_lib = 0
        planned_com = 0
        print("\n[DRY-RUN / RERUN_WEAK]")
        print("  VLM a lancer   : 0")
        print("  Recalcul lignes deja valides : 0")
        print("  ERR_VLM_BATCH selectionnes   : 0")
        for i in selected_idx:
            row = ui_row(i)
            b = batch_row_from_ui_index(i)
            status = str(b.get("batch_status") or "").strip().upper()
            original_status = str(b.get("__rerun_weak_original_status") or status).strip()
            interpreted_status = str(b.get("__rerun_weak_interpreted_status") or status).strip()
            reason = str(b.get("__rerun_weak_reason") or "statut faible").strip()
            lib_existing = str(b.get("libelle_propose_batch") or "").strip()
            com_existing = str(b.get("commentaire_propose_batch") or "").strip()
            run_lib, run_com = llm_rerun_plan_for_status(interpreted_status, lib_existing, com_existing)
            planned_lib += 1 if run_lib else 0
            planned_com += 1 if run_com else 0
            if run_lib and run_com:
                calls = "LIB+COM"
            elif run_lib:
                calls = "LIB"
            elif run_com:
                calls = "COM"
            else:
                calls = "none"
            photo = str(row.get("photo_rel_native") or b.get("photo_rel_native") or "").strip()
            print(
                f"   - photo_rel_native={photo} | batch_status_actuel={original_status or '-'} "
                f"| statut_cible={interpreted_status or '-'} | appel_prevu={calls} | raison={reason}"
            )
        print(f"  LIB a lancer   : {planned_lib}")
        print(f"  COM a lancer   : {planned_com}")
        print("  Sorties LLM existantes valides : conservees")
        print("\nAucune requete serveur envoyee.")
        print("Aucune ecriture CSV effectuee.")
        return 0
    only_photo_rel_plans_by_key: dict[str, dict[str, Any]] = {}
    only_photo_rel_plans: list[dict[str, Any]] = []
    if only_photo_rel_targets:
        selected_idx, only_photo_rel_plans_by_key, only_photo_rel_plans = apply_only_photo_rel_filter(
            selected_idx=selected_idx,
            rows_ui=rows_ui,
            batch_index=batch_index,
            batch_existing_keys=batch_existing_keys,
            targets=only_photo_rel_targets,
            id_affaire=id_affaire,
            id_captation=id_captation,
        )
        planned_lib = sum(1 for item in only_photo_rel_plans if item["run_lib"])
        planned_com = sum(1 for item in only_photo_rel_plans if item["run_com"])
        print(f"[ONLY_PHOTO_REL] targets={len(only_photo_rel_targets)} selected={len(selected_idx)} planned_lib={planned_lib} planned_com={planned_com} planned_vlm=0")
        for item in only_photo_rel_plans:
            fields = ",".join(item["fields"]) if item["fields"] else "none"
            print(f"[ONLY_PHOTO_REL] photo={item['photo_rel_native']} fields={fields} vlm=0")
    print(f"[LIMIT] sélection={len(selected_idx)} / limit={args.limit or 0} indices={selected_idx}")
    if not selected_idx:
        log.info("Selection vide: sortie immediate sans VLM, ASR ni LLM")
        print("[SELECT] selected=0 -> sortie immediate sans VLM, ASR ni LLM")
        return 0
    if is_dry and only_photo_rel_targets:
        planned_lib = sum(1 for item in only_photo_rel_plans if item["run_lib"])
        planned_com = sum(1 for item in only_photo_rel_plans if item["run_com"])
        print("\n[DRY-RUN / ONLY_PHOTO_REL]")
        print(f"  Photos ciblees : {len(only_photo_rel_plans)}")
        print(f"  VLM a lancer   : 0")
        print(f"  LIB a lancer   : {planned_lib}")
        print(f"  COM a lancer   : {planned_com}")
        for item in only_photo_rel_plans:
            fields = ",".join(item["fields"]) if item["fields"] else "none"
            print(f"   - {item['photo_rel_native']}: {fields}")
        print("\nAucune requete serveur envoyee.")
        print("Aucune ecriture CSV effectuee.")
        return 0

    if only_photo_rel_targets and reset_vlm:
        raise RuntimeError("INVALID_JOB_CONTRACT: --only-photo-rel interdit avec --reset-vlm")
    if only_photo_rel_targets and reset_vlm_plus:
        raise RuntimeError("INVALID_JOB_CONTRACT: --only-photo-rel interdit avec --reset-vlm-plus")
    if only_photo_rel_targets and reset_llm:
        raise RuntimeError("INVALID_JOB_CONTRACT: --only-photo-rel interdit avec --reset-llm")

    if reset_vlm:
        for i in selected_idx:
            row_ui = rows_ui[i]
            photo_key = (row_ui.get("photo_rel_native") or "").strip()
            b = get_batch_row(batch_index, photo_key)

            b["batch_status"] = ""
            b["batch_ts"] = ""
            b["vlm_status"] = "PENDING"
            b["vlm_batch_ts"] = ""
            b["vlm_batch_id"] = ""
            b["vlm_err"] = ""
            b["description_vlm_batch"] = ""
    elif reset_llm:
        for i in selected_idx:
            row_ui = rows_ui[i]
            photo_key = (row_ui.get("photo_rel_native") or "").strip()
            b = get_batch_row(batch_index, photo_key)

            reset_fields_in_row(b, RESET_LLM_FIELDS)



    # -------------------------
    # PASS 1 — VLM
    # -------------------------

    max_total, max_file, max_files = vlm_limits(bool(args.night))
    # RTX 3060 12 Go: stabilité prioritaire, 1 photo par appel VLM.
    max_files = 1
    vlm_mode = "quality"
    vlm_fail_streak = 0

    if only_photo_rel_targets:
        log.info("ONLY_PHOTO_REL: PASS 1 VLM ignoree, descriptions existantes conservees")
        print("[ONLY_PHOTO_REL] PASS 1 VLM ignoree: VLM calls=0")
    elif is_dry:
        for i in selected_idx:
            row_ui = ui_row(i)
            b = batch_row_from_ui_index(i)

            # reset marqueur ERR_VLM (optionnel)
            if str(b.get("batch_status") or "").upper().startswith("ERR_VLM"):
                b["batch_status"] = ""

            # déjà une description
            if (b.get("description_vlm_batch") or "").strip():
                pf_skip += 1
                pf_skip_reason("description_vlm_deja_presente")
                continue

            # image : JPG reduit puis JPG
            name = row_ui.get("nom_fichier_image", "") or ""
            img = resolve_img_path({"chemin_photo_reduite_pcfixe": b.get("chemin_photo_reduite_pcfixe",""), "nom_fichier_image": name})
            if img is None:
                img = resolve_img_path({"chemin_photo_reduite_pcfixe": b.get("chemin_photo_native_pcfixe",""), "nom_fichier_image": name})
            if img is None:
                pf_skip += 1
                pf_skip_reason("image_introuvable")
                continue

            size = img.stat().st_size
            if size > max_file:
                pf_skip += 1
                pf_skip_reason("image_trop_volumineuse")
                continue

            t = safe_float(row_ui.get("t_audio"))
            if t is None:
                pf_skip += 1
                pf_skip_reason("t_audio_absent")
                continue

            pf_vlm += 1

    else:
        batch: list[tuple[str, Path, str]] = []   # (photo_key, img, ctx)
        size_sum = 0

        for i in selected_idx:
            row_ui = ui_row(i)
            photo_key = (row_ui.get("photo_rel_native") or "").strip()
            if not photo_key:
                continue
            b = get_batch_row(batch_index, photo_key)

            if reset_vlm and (b.get("vlm_status") or "").upper() == "ERR":
                b["vlm_status"] = "PENDING"
                b["vlm_batch_ts"] = ""
                b["vlm_batch_id"] = ""
                b["vlm_err"] = ""
                b["description_vlm_batch"] = ""

            # déjà traité
            if (b.get("description_vlm_batch") or "").strip():
                b["vlm_status"] = "OK"
                b["vlm_batch_ts"] = now_ts()
                b["batch_id"] = current_batch_id
                b["batch_ts"] = now_ts()
                b["vlm_batch_id"] = current_batch_id
                continue

            # si déjà en erreur et pas reset
            if (b.get("vlm_status") or "").upper() == "ERR" and not reset_vlm:
                if not (b.get("batch_status") or "").strip():
                    b["batch_status"] = "SKIP_vlm_en_erreur"
                b["batch_id"] = current_batch_id
                b["batch_ts"] = now_ts()
                continue

            # image : JPG reduit puis JPG
            name = row_ui.get("nom_fichier_image", "") or ""
            img = resolve_img_path({"chemin_photo_reduite_pcfixe": b.get("chemin_photo_reduite_pcfixe",""), "nom_fichier_image": name})
            if img is None:
                img = resolve_img_path({"chemin_photo_reduite_pcfixe": b.get("chemin_photo_native_pcfixe",""), "nom_fichier_image": name})
            if img is None:
                mark_vlm_err_batch(b, "ERR_image_introuvable", batch_id=current_batch_id)
                continue

            s = img.stat().st_size
            if s > max_file:
                b["batch_status"] = "SKIP_image_trop_volumineuse"
                b["batch_id"] = current_batch_id
                b["batch_ts"] = now_ts()
                continue

            t = safe_float(row_ui.get("t_audio"))
            if t is None:
                b["batch_status"] = "SKIP_t_audio_absent"
                b["batch_id"] = current_batch_id
                b["batch_ts"] = now_ts()
                continue

            transcript_excerpt = extract_transcript_window(trs, t, com_before, com_after, max_chars=1200)
            ctx = build_vlm_specific_context(transcript_excerpt)

            should_flush = (size_sum + s > max_total) or (len(batch) >= max_files) or vlm_strict
            if should_flush and batch:
                actual_vlm_calls += 1
                actual_vlm_images += len(batch)

                ok, err = flush_vlm_batch(
                    batch,                       # <-- plus de "rows"
                    batch_index=batch_index,
                    base_url=base_url,
                    api_key=local_llm_api_key,
                    mode=vlm_mode,
                    current_batch_id=current_batch_id,
                    context_global=vlm_context_global,
                    prompt=VLM_BATCH_PROMPT,
                )

                vlm_fail_streak = 0 if ok > 0 else (vlm_fail_streak + 1)
                vlm_backoff_sleep(vlm_fail_streak)

                batch = []
                size_sum = 0

            batch.append((photo_key, img, ctx))
            size_sum += s

        if batch:
            actual_vlm_calls += 1
            actual_vlm_images += len(batch)
            ok, err = flush_vlm_batch(
                batch,
                batch_index=batch_index,
                base_url=base_url,
                api_key=local_llm_api_key,
                mode=vlm_mode,
                current_batch_id=current_batch_id,
                context_global=vlm_context_global,
                prompt=VLM_BATCH_PROMPT,
            )
            vlm_fail_streak = 0 if ok > 0 else (vlm_fail_streak + 1)
            vlm_backoff_sleep(vlm_fail_streak)


            batch = []
            size_sum = 0

    # -------------------------
    # BARRIÈRE DE PHASAGE VLM
    # -------------------------

    vlm_pending = []
    for i in selected_idx:
        row_ui = rows_ui[i]
        photo_key = (row_ui.get("photo_rel_native") or "").strip()
        if not photo_key:
            continue
        b = get_batch_row(batch_index, photo_key)

        if (b.get("vlm_batch_id") == current_batch_id
            and (b.get("vlm_status") or "").upper() not in ("OK", "ERR")):
            vlm_pending.append(photo_key)

    
    if vlm_pending:
        raise RuntimeError(f"Passe 1 VLM incomplète : {len(vlm_pending)} photo(s)")

    # Passe 1 terminée -> purge VLM avant passe 2 (LLM texte /annoter)

    if not only_photo_rel_targets:
        ok_purge = purge_vlm(base_url, local_llm_api_key, timeout=30, wait_step=1.0)
        if not ok_purge:
            raise RuntimeError("Purge VLM impossible (VLM busy trop longtemps ou erreur serveur).")

    # PASS 1bis - ASR des dictees differees, apres purge VLM et avant les prompts LLM.
    if not is_dry and base_url and not only_photo_rel_targets:
        process_deferred_dictees(
            rows_ui=rows_ui,
            photos_csv=photos_csv,
            ui_fieldnames=ui_fieldnames,
            base_url=base_url,
            api_key=local_llm_api_key,
            timeout=float(local_cfg.get("timeout") or 600),
            selected_indices=set(selected_idx),
        )


    # -------------------------
    # PASS 2 — LLM (libellé / commentaire)
    # -------------------------


    # 0) contexte/mission
    contexte_general_str = json.dumps(ctx_general, ensure_ascii=False, indent=2)
    mission = batch_context_mission(ctx_general)

    # 1) charger le template batch updated, avec fallbacks legacy
    prompts_dir = Path(pc["config_llm"]).resolve().parent
    prompt_path = resolve_batch_prompt_path(prompts_dir)
    prompts = read_json(prompt_path)

    sys_lib = str(prompts["libelle"].get("system") or "")
    usr_lib = str(prompts["libelle"].get("user") or "")
    sys_com = str(prompts["commentaire"].get("system") or "")
    usr_com = str(prompts["commentaire"].get("user") or "")


    
    # 3) fenêtres audio (déjà calculées chez vous : lib_before/lib_after, com_before/com_after)
    #    => on les réutilise

    timeout_s = float(local_cfg.get("timeout", 240))
    timeout_s = max(timeout_s, 600.0)  # test “sécurisé”

    client = None
    model = str(cfg_llm.get("model", "gpt-4o-mini") or "gpt-4o-mini").strip() if llm_backend == "openai" else local_model
    if llm_backend == "local":
        client = LocalLLMClient(base_url=base_url, api_key=local_llm_api_key, timeout=timeout_s)
        print(f"[BATCH] client.timeout={timeout_s}s")
        log.info("LLM runtime backend=local model=%s base_url=%s", model, base_url)
    else:
        log.info("LLM runtime backend=openai model=%s", model)
    print(f"[BATCH] LLM runtime backend={llm_backend} model={model}" + (f" base_url={base_url}" if llm_backend == "local" else ""))
    if rerun_weak:
        print(f"[BATCH] rerun_weak=1 backend={llm_backend}")
        log.info("WEAK rerun mode enabled backend=%s requested=%s", llm_backend, rerun_weak_backend)

    
    done_llm = 0
    ui_dirty = False

    for i in selected_idx:
        row_ui = rows_ui[i]
        photo_key = (row_ui.get("photo_rel_native") or "").strip()
        if not photo_key:
            continue
        b = get_batch_row(batch_index, photo_key)

        if is_dry:
            if norm_bool(row_ui.get("annotation_validee")):
                pf_skip += 1; pf_skip_reason("SKIP_annotation_validee_deja"); continue
            if not norm_bool(b.get("photo_disponible_pcfixe")):
                pf_skip += 1; pf_skip_reason("SKIP_photo_absente_pcfixe"); continue
                
            if (b.get("vlm_status") or "").upper() == "ERR":
                pf_skip += 1; pf_skip_reason("SKIP_vlm_en_erreur"); continue
            if not (b.get("description_vlm_batch") or "").strip():
                pf_skip += 1; pf_skip_reason("SKIP_description_absente"); continue
            if safe_float(row_ui.get("t_audio")) is None:
                pf_skip += 1; pf_skip_reason("SKIP_t_audio_absent"); continue

            pf_llm += 1
            if args.limit and pf_llm >= args.limit:
                break
            continue

        # MODE RÉEL
        bs = (b.get("batch_status") or "").upper().strip()
        lib_existing = (b.get("libelle_propose_batch") or "").strip()
        com_existing = (b.get("commentaire_propose_batch") or "").strip()
        dictee_retry_target = needs_dictee_llm_retry(row_ui)
        libelle_weak_existing = bool(lib_existing) and is_weak_libelle(lib_existing)
        commentaire_weak = (bs == "OK_LIB_COM_WEAK")
        weak_target = (bs == "WEAK_LIB") or commentaire_weak
        if rerun_weak and not weak_target:
            continue
        rerun_lib, rerun_com = llm_rerun_plan_for_status(bs, lib_existing, com_existing) if rerun_weak else (False, False)
        if not only_photo_rel_targets and bs.startswith("OK") and lib_existing and not dictee_retry_target:
            if not commentaire_weak and not libelle_weak_existing:
                # si vous voulez aussi exiger commentaire :
                # if (b.get("commentaire_propose_batch") or "").strip():
                continue
            # si vous voulez aussi exiger commentaire :
            # if (b.get("commentaire_propose_batch") or "").strip():
            pass

        if args.limit and done_llm >= args.limit:
            break

        if norm_bool(row_ui.get("annotation_validee")):
            b["batch_status"] = "SKIP_annotation_validee_deja_OK"
            b["batch_ts"] = now_ts()
            n_skip += 1; n_done += 1
            continue

        if not norm_bool(b.get("photo_disponible_pcfixe")):
            b["batch_status"] = "SKIP_photo_absente_pcfixe"
            b["batch_ts"] = now_ts()
            n_skip += 1; n_done += 1
            continue

        if (b.get("vlm_status") or "").upper() == "ERR":
            if not (b.get("batch_status") or "").strip():
                b["batch_status"] = "SKIP_vlm_en_erreur"
            b["batch_ts"] = now_ts()
            n_skip += 1; n_done += 1
            continue


        description_vlm_batch = (b.get("description_vlm_batch") or "").strip()
        if (b.get("vlm_status") or "").upper() != "OK" or not description_vlm_batch:
            b["batch_status"] = "ERR_VLM_INCOHERENT_P2"
            b["batch_ts"] = now_ts()
            n_err += 1; n_done += 1
            continue


        t = safe_float(row_ui.get("t_audio"))
        if t is None and not dictee_retry_target:
            b["batch_status"] = "SKIP_t_audio_absent"
            b["batch_ts"] = now_ts()
            n_skip += 1; n_done += 1
            continue

        # à partir d’ici : on VA tenter le LLM => consomme le quota
        done_llm += 1

        # 1) fenêtres transcription
        trans_lib = extract_transcript_window(trs, t, lib_before, lib_after, max_chars=2000) if t is not None else ""
        trans_com = extract_transcript_window(trs, t, com_before, com_after, max_chars=2000) if t is not None else ""

        # dictee vient de row_ui

        dictee_status = (row_ui.get("dictee_asr_status") or "").upper().strip()
        dictee_text   = (row_ui.get("dictee_asr_text") or "").strip()

        prefer_dictee = (dictee_status == "OK" and dictee_text)

        dictee_ok = (dictee_status == "OK" and bool(dictee_text))

        photo_ref = (
            (row_ui.get("photo_rel_native") or "").strip()
            or (row_ui.get("nom_fichier_image") or "").strip()
            or (b.get("photo_rel_native") or "").strip()
            or "UNKNOWN"
        )
        targeted_run_lib = True
        targeted_run_com = True
        if only_photo_rel_targets:
            target_plan = next((only_photo_rel_plans_by_key.get(k) for k in _photo_rel_match_keys(photo_key) if k in only_photo_rel_plans_by_key), None)
            if not target_plan:
                continue
            targeted_run_lib = bool(target_plan["run_lib"])
            targeted_run_com = bool(target_plan["run_com"])
            if not targeted_run_lib and not targeted_run_com:
                log.info("[ONLY_PHOTO_REL] photo=%s no-op: libelle/commentaire deja presents", photo_ref)
                continue
        elif rerun_weak:
            targeted_run_lib = rerun_lib
            targeted_run_com = rerun_com
        if rerun_weak and weak_target:
            rerun_target = []
            if rerun_lib:
                rerun_target.append("lib")
            if rerun_com:
                rerun_target.append("com")
            n_rerun_weak += 1
            log.info(
                "[WEAK][RERUN][START] photo=%s target=%s prev_status=%s backend=%s model=%s",
                photo_ref,
                "+".join(rerun_target) or "unknown",
                bs or "EMPTY",
                llm_backend,
                model,
            )
            if rerun_lib:
                b["llm_trace_lib"] = append_trace(
                    b.get("llm_trace_lib"),
                    f"[rerun_weak start photo={photo_ref} prev_status={bs or 'EMPTY'} backend={llm_backend} model={model}]",
                )
            if rerun_com:
                b["llm_trace_com"] = append_trace(
                    b.get("llm_trace_com"),
                    f"[rerun_weak start photo={photo_ref} prev_status={bs or 'EMPTY'} backend={llm_backend} model={model}]",
                )

        libelle_seed = ""
        libelle_seed_source = "EMPTY"

        if (trans_lib or "").strip():
            libelle_seed = trans_lib.strip()
            libelle_seed_source = "trans_lib"
        elif dictee_ok and (dictee_text or "").strip():
            libelle_seed = dictee_text.strip()
            libelle_seed_source = "dictee_asr"
        elif (trans_com or "").strip():
            libelle_seed = trans_com.strip()
            libelle_seed_source = "trans_com"

        log.info("[LIB][SRC] photo=%s source=%s", photo_ref, libelle_seed_source)


        # 2) salient_families + points_saillants texte (pour le prompt)

        salient_visible = salient_families_from_vlm(description_vlm_batch)
        salient_visible = normalize_salient_families_for_flask(salient_visible)

        # => ce que l'on impose réellement au serveur (contrainte phrase 1)
        salient_for_server = filter_salient_for_server(description_vlm_batch, salient_visible, max_items=1)

        # libellé : je recommande de NE PAS imposer de salient_families
        salient_lib = []
        salient_com = salient_for_server

        points_saillants_lib = format_points_saillants(salient_lib)
        points_saillants_com = format_points_saillants(salient_com)

        if dictee_ok and (dictee_text or "").strip():
            dictee_block = (
                "Dictée (ASR) :\n"
                "Statut : OK\n"
                "Texte :\n"
                f"{dictee_text.strip()}"
            )
        else:
            dictee_block = ""   # IMPORTANT : pas de mot "dictée" dans le prompt

        if dictee_retry_target and dictee_ok and (dictee_text or "").strip():
            dictee_block = (
                "Correction / complément de l'expert à appliquer prioritairement :\n"
                f"{dictee_text.strip()}"
            )
        lib_dictee_block = dictee_block if dictee_retry_target else ("" if libelle_seed_source == "dictee_asr" else dictee_block)

        # 3) Prompts
        mapping_lib = {
            "contexte_general": contexte_general_str,
            "mission": mission,
            "description_vlm": description_vlm_batch,      # attention au nom (voir §2)
            "points_saillants": points_saillants_lib,
            "transcription": libelle_seed,
            "dictee_block": lib_dictee_block,
        }

        mapping_com = {
            "contexte_general": contexte_general_str,
            "mission": mission,
            "description_vlm": description_vlm_batch,
            "points_saillants": points_saillants_com,
            "transcription": trans_com,
            "dictee_block": dictee_block,
        }


        final_lib = apply_template(usr_lib, mapping_lib)
        final_lib = append_priority_dictation_to_prompt(
            usr_lib,
            final_lib,
            dictee_text=dictee_text,
            dictee_ok=dictee_ok,
            task="libelle",
        )
        final_lib = build_prompt_with_desc_compat(usr_lib, final_lib, description_vlm_batch)
        if rerun_weak and libelle_weak_existing:
            final_lib += "\n\n" + RERUN_WEAK_LIB

        final_com = apply_template(usr_com, mapping_com)
        final_com = append_priority_dictation_to_prompt(
            usr_com,
            final_com,
            dictee_text=dictee_text,
            dictee_ok=dictee_ok,
            task="commentaire",
        )
        final_com = append_comment_fallback_policy(
            final_com,
            dictee_text=dictee_text,
            dictee_ok=dictee_ok,
            desc_vlm=description_vlm_batch,
            transcription=trans_com,
        )

        # additif seulement si on envoie salient_families (sinon inutile)
        if salient_com:
            marker = "STRUCTURE OBLIGATOIRE DU COMMENTAIRE"
            add = (
                "\nCONTRAINTE SERVEUR (PHRASE 2)\n"
                "- La phrase 2 (celle qui commence STRICTEMENT par \"Selon la description visuelle\") "
                "DOIT contenir au moins un terme correspondant à chacun des points saillants listés.\n"
                "- Utiliser les termes exacts (ex. fissure, cloque, déformation, plastique, métal, coude, raccord).\n"
                "- Ne pas déplacer ces termes dans la phrase 1.\n"
            )
            if marker in final_com:
                final_com = final_com.replace(marker, marker + add, 1)
            else:
                final_com += "\n\n" + marker + add

        # appeler uniquement si le template n'a PAS déjà {{description_vlm_batch}}
        if "{{description_vlm_batch}}" not in (usr_com or ""):
            final_com = build_prompt_with_desc_compat(usr_com, final_com, description_vlm_batch)
        if rerun_weak and commentaire_weak:
            final_com += "\n\n" + RERUN_WEAK_COM

        # --- LIBELLE (obligatoire) ---
        SLEEP_OK  = 0.25   # apres succes
        SLEEP_ERR = 0.75   # apres erreur (evite l emballement)

        lib_ok = False
        lib_weak = False
        lib_weak_reason = None
        if not targeted_run_lib:
            lib_ok = bool(lib_existing)
            if not lib_ok:
                b["batch_status"] = "ERR_LIB"
            else:
                clear_llm_active_error(b, "LIB", "existing_valid_libelle")
                b["batch_status"] = "OK_LIB"
        else:
            try:
                actual_llm_calls += 1
                actual_llm_lib += 1

                lib = generate_with_retry(
                    client,
                    llm_backend=llm_backend,
                    prompt=final_lib,
                    system=sys_lib,
                    model=model,
                    openai_api_key=openai_api_key,
                    temperature=temp_lib,
                    max_tokens=max_tokens_lib,
                    task="libelle",
                    expect_json=True,
                    salient_families=[],
                    prefer_dictee=bool(prefer_dictee),
                    dictee_asr_text=dictee_text if dictee_ok else "",
                    b=b,
                    which="LIB",
                    max_attempts=3,
                    base_sleep=0.6,
                )

                if not lib:
                    raise ValueError("LIB_EMPTY")
                lib_weak_reason = weak_libelle_reason(lib)
                if lib_weak_reason:
                    lib_weak = True
                    log.warning("[LIB][WEAK] idx=%s reason=%s photo=%s lib=%r", i, lib_weak_reason, photo_ref, lib)

                set_successful_llm_batch_value(
                    b,
                    field="libelle_propose_batch",
                    value=lib,
                    batch_id=current_batch_id,
                )
                clear_llm_active_error(b, "LIB", "valid_libelle")
                if rerun_lib:
                    lib_rerun_result = "still_weak" if lib_weak else "recovered"
                    b["llm_trace_lib"] = append_trace(
                        b.get("llm_trace_lib"),
                        f"[rerun_weak end photo={photo_ref} result={lib_rerun_result} batch_status={'WEAK_LIB' if lib_weak else 'OK_LIB'}]",
                    )
                    log.info(
                        "[WEAK][RERUN][LIB][END] photo=%s result=%s batch_status=%s",
                        photo_ref,
                        lib_rerun_result,
                        "WEAK_LIB" if lib_weak else "OK_LIB",
                    )
                else:
                    b["llm_trace_lib"] = b.get("llm_trace_lib") or ""
                b["batch_status"] = "WEAK_LIB" if lib_weak else "OK_LIB"
                lib_ok = not lib_weak

            except Exception as e:
                _set_llm_err(b, "LIB", e)
                b["batch_status"] = llm_status_after_exception("LIB", e)
            finally:
                time.sleep(SLEEP_OK if lib_ok else SLEEP_ERR)


        # --- COMMENTAIRE (optionnel, non bloquant) ---
        com_ok = False
        com_weak = False
        if lib_ok and targeted_run_com:
            try:
                actual_llm_calls += 1
                actual_llm_com += 1

                com = generate_with_retry(
                    client,
                    llm_backend=llm_backend,
                    prompt=final_com,
                    system=sys_com,
                    model=model,
                    openai_api_key=openai_api_key,
                    temperature=temp_com,
                    max_tokens=max_tokens_com,
                    task="commentaire",
                    expect_json=True,
                    salient_families=salient_com,
                    prefer_dictee=bool(prefer_dictee),
                    dictee_asr_text=dictee_text if dictee_ok else "",
                    b=b,
                    which="COM",
                    max_attempts=1,
                    base_sleep=0.8,
                )

                if not com:
                    raise ValueError("COM_EMPTY")
                com_weak_reason = weak_commentaire_reason(com, description_vlm_batch)
                if com_weak_reason:
                    com_weak = True
                    log.warning("[COM][WEAK] photo=%s reason=%s com=%r", photo_ref, com_weak_reason, com)

                set_successful_llm_batch_value(
                    b,
                    field="commentaire_propose_batch",
                    value=com,
                    batch_id=current_batch_id,
                )
                clear_llm_active_error(b, "COM", "valid_commentaire")
                if rerun_com:
                    com_rerun_result = "still_weak" if com_weak else "recovered"
                    b["llm_trace_com"] = append_trace(
                        b.get("llm_trace_com"),
                        f"[rerun_weak end photo={photo_ref} result={com_rerun_result} batch_status={'OK_LIB_COM_WEAK' if com_weak else 'OK_LIB_COM'}]",
                    )
                    log.info(
                        "[WEAK][RERUN][COM][END] photo=%s result=%s batch_status=%s",
                        photo_ref,
                        com_rerun_result,
                        "OK_LIB_COM_WEAK" if com_weak else "OK_LIB_COM",
                    )
                else:
                    b["llm_trace_com"] = b.get("llm_trace_com") or ""
                b["batch_status"] = "OK_LIB_COM_WEAK" if com_weak else "OK_LIB_COM"
                com_ok = True

            except Exception as e:
                # on garde le libelle valide; les rejets de contenu commentaire sont reprenables.
                _set_llm_err(b, "COM", e)
                b["batch_status"] = llm_status_after_exception("COM", e, lib_ok=True)
            finally:
                time.sleep(SLEEP_OK if com_ok else SLEEP_ERR)
        elif lib_ok and not targeted_run_com and com_existing:
            com_ok = True
            if not str(b.get("batch_status") or "").upper().startswith("OK_LIB_COM"):
                b["batch_status"] = "OK_LIB_COM"


        # comptage (une seule fois par ligne)
        b["batch_ts"] = now_ts()
        final_status = (b.get("batch_status") or "").strip().upper()
        if dictee_retry_target:
            row_ui["dictee_llm_ts"] = now_ts()
            row_ui["dictee_llm_asr_ts"] = _clean_cell(row_ui.get("dictee_asr_ts"))
            if final_status in ("OK_LIB", "OK_LIB_COM", "OK_LIB_COM_WEAK", "WEAK_LIB"):
                row_ui["dictee_llm_status"] = "OK"
                row_ui["dictee_llm_error"] = ""
            else:
                row_ui["dictee_llm_status"] = "ERR"
                row_ui["dictee_llm_error"] = (b.get("llm_err_lib") or b.get("llm_err_com") or final_status or "LLM error")[:600]
            ui_dirty = True
        if final_status == "WEAK_LIB":
            n_weak += 1
        elif lib_ok:
            if final_status == "OK_LIB_COM_WEAK":
                n_weak_com += 1
            elif final_status.startswith("OK"):
                n_ok += 1
            else:
                n_err += 1
        else:
            n_err += 1
        if rerun_weak and weak_target:
            if final_status in ("WEAK_LIB", "OK_LIB_COM_WEAK"):
                n_rerun_weak_still += 1
                log.warning("[WEAK][RERUN][FINAL] photo=%s result=still_weak batch_status=%s", photo_ref, final_status)
            elif final_status.startswith("OK"):
                n_rerun_weak_ok += 1
                log.info("[WEAK][RERUN][FINAL] photo=%s result=recovered batch_status=%s", photo_ref, final_status)
        n_done += 1


    print(f"[RUN] VLM calls={actual_vlm_calls} images={actual_vlm_images} | LLM calls={actual_llm_calls} (lib={actual_llm_lib}, com={actual_llm_com})")
    print(f"[INFO] total_ui={len(rows_ui)} OK={n_ok} WEAK={n_weak} WEAK_COM={n_weak_com} SKIP={n_skip} ERR={n_err} dry_run={is_dry}")
    if rerun_weak:
        print(f"[INFO] rerun_weak={n_rerun_weak} rerun_weak_ok={n_rerun_weak_ok} rerun_weak_still={n_rerun_weak_still}")

    # --- DRY-RUN / PREFLIGHT : on affiche et on sort SANS ECRITURE ---
    if is_dry:
        print("\n[DRY-RUN / PREFLIGHT]")
        print(f"  VLM à lancer : {pf_vlm}")
        print(f"  LLM à lancer : {pf_llm}")
        print(f"  SKIP total   : {pf_skip}")

        if pf_reasons:
            print("  Détail des SKIP :")
            for k, v in sorted(pf_reasons.items()):
                print(f"   - {k}: {v}")

        print("\nAucune requête serveur envoyée.")
        print("Aucune écriture CSV effectuée.")
        return 0


    # --- MODE REEL : écriture CSV (batch uniquement) ---
    if ui_dirty:
        atomic_write_csv(photos_csv, rows_ui, csv_fieldnames_without_internal(ui_fieldnames))
        log.info("photos.csv dictee_llm mis a jour: %s", str(photos_csv))

    if not isinstance(batch_index, dict) or not batch_index:
        raise RuntimeError("BATCH_OUTPUT_MISSING: batch_index vide, aucune ecriture photos_batch.csv possible")

    batch_rows = list(batch_index.values())
    job_rows = attach_job_id_to_batch_rows(batch_rows, batch_id=current_batch_id, job_id=annotation_job_id)
    if job_rows <= 0:
        raise RuntimeError("BATCH_OUTPUT_STAMP_FAILED: aucune ligne batch ne porte le batch_id courant")
    atomic_write_csv(photos_batch_csv, batch_rows, HEADER_BATCH)
    log.info("photos_batch.csv écrit: %s (%d lignes)", str(photos_batch_csv), len(batch_rows))

    now = time.time()
    stamp_path = photos_batch_csv.with_suffix(photos_batch_csv.suffix + ".stamp")
    output_info = verify_photos_batch_output(
        photos_csv=photos_csv,
        photos_batch_csv=photos_batch_csv,
        stamp_path=stamp_path,
        batch_id=current_batch_id,
        job_id=annotation_job_id,
        id_affaire=id_affaire,
        id_captation=id_captation,
    )
    os.utime(photos_batch_csv, (now, now))  # force mtime/atime
    output_info.update(batch_sync_context)
    debrief_info = generate_and_publish_debrief_dictees(
        rows_ui=rows_ui,
        batch_rows=batch_rows,
        infos=infos,
        pc=pc,
        id_affaire=id_affaire,
        id_captation=id_captation,
        mapping_path=dictation_photo_map,
        preview_only=False,
    )
    output_info.update({k: v for k, v in debrief_info.items() if k != "debrief_dictees_preview"})
    try:
        output_info.update(publish_batch_outputs_to_nas(
            photos_batch_csv=photos_batch_csv,
            stamp_path=stamp_path,
            sync_context=batch_sync_context,
            batch_started_at=t0,
        ))
    except BatchSyncError as exc:
        output_info.update(exc.details)
        output_info["local_done"] = True
        output_info["publish_pending"] = True
        output_info["publish_error_code"] = "NAS_PUBLISH_FAILED"
        output_info["publish_error_message"] = str(exc)
        output_info["nas_publish_succeeded"] = False
        print("[BATCH_OUTPUT] " + json.dumps(output_info, ensure_ascii=False, sort_keys=True))
        log.error("Publication NAS en attente: %s", json.dumps(output_info, ensure_ascii=False, sort_keys=True))
        return 0
    print("[BATCH_OUTPUT] " + json.dumps(output_info, ensure_ascii=False, sort_keys=True))
    log.info("photos_batch.csv vérifié: %s", json.dumps(output_info, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
