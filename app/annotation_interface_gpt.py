import streamlit as st
import pandas as pd
import numpy as np
import soundfile as sf
import time
import os
import shutil
from openai import OpenAI
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta, date
import glob
from utils import (
    lire_infos_projet,
    sauvegarder_infos_projet,
    convertir_horodatage_en_secondes,
)
from path_migration import migrate_photo_dataframe_paths
from traitement_audio import start_audio_server_if_needed
from streamlit_wavesurfer import wavesurfer
import requests
from pathlib import Path
from PIL import Image
import math
import re
from app.local_llm_client import LocalLLMClient
from app.server_locator import DEFAULT_FLASK_ENDPOINTS, resolve_flask_base_url, _vpn_active
from app.wol_util import wake_on_lan, wait_for_server, is_server_up
from utils import charger_transcription_flexible
import inspect
import uuid
import io
import hashlib
import logging
import socket

log = logging.getLogger("dictée_asr")
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_DIR = _REPO_ROOT / "config"
_DICTEES_ROOT = _REPO_ROOT / "data" / "dictees"
_DICTEES_PENDING_DIR = _DICTEES_ROOT / "pending"
_SYNC_PENDING_DIR = _REPO_ROOT / "data" / "sync_pending"
_PHOTOS_NAS_PENDING_PATH = _SYNC_PENDING_DIR / "photos_nas_pending.json"
_GTP_EXPORTS_NAS_PENDING_PATH = _SYNC_PENDING_DIR / "gtp_exports_nas_pending.json"
_PCFIXE_AFFAIRES_SMB_ROOTS = (
    r"\\10.0.1.10\Affaires",
    r"\\192.168.0.155\Affaires",
    r"\\192.168.0.120\Affaires",
)
_NAS_AFFAIRES_SMB_ROOT = r"\\192.168.1.20\Affaires"
_PCFIXE_LOCAL_AFFAIRES_ROOT = r"C:\Affaires"
_DICTEE_SCHEMA_VERSION = 1
_LOCAL_LLM_BUSY_RESULT = "[LLM local occupe, reessayez dans quelques secondes.]"
_UNC_PROBE_TIMEOUT_S = 0.6


def _load_env_for_runtime_config() -> None:
    candidates = [
        os.getenv("ANNOTATIONPHOTOSGPT_ENV", ""),
        str(_CONFIG_DIR / ".env"),
        str(_REPO_ROOT / ".env"),
    ]
    for p in candidates:
        p = (p or "").strip()
        if p and Path(p).exists():
            load_dotenv(p, override=False)


def _is_local_llm_busy_result(value: str) -> bool:
    return str(value or "").strip() == _LOCAL_LLM_BUSY_RESULT


def _is_llm_runtime_message(value: str) -> bool:
    text = str(value or "").strip()
    if not text.startswith("[") or not text.endswith("]"):
        return False
    prefixes = (
        "[Erreur LLM local:",
        "[Erreur GPT OpenAI :",
        "[Erreur config LLM:",
        "[Réponse LLM local vide ou inexploitable]",
        "[LLM local occupé,",
        "[LLM local ok=False:",
    )
    return any(text.startswith(prefix) for prefix in prefixes)


def _is_placeholder_secret(value: str, names: set[str] | None = None) -> bool:
    v = str(value or "").strip()
    if not v:
        return True
    u = v.upper()
    if "PLACEHOLDER" in u:
        return True
    if names and u in {name.upper() for name in names}:
        return True
    return False


def _deep_merge_dict(base: dict, override: dict) -> dict:
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged.get(key, {}), value)
        else:
            merged[key] = value
    return merged


def _load_json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_project_config_llm_path(infos: dict | None = None) -> Path | None:
    infos = infos or {}
    candidates: list[Path] = []

    transcription = str(infos.get("fichier_transcription") or "").strip()
    if transcription:
        candidates.append(Path(transcription).resolve().parent / "config_llm.json")

    contexte = str(infos.get("fichier_contexte_general") or "").strip()
    if contexte:
        candidates.append(Path(contexte).resolve().parent / "config_llm.json")

    explicit_local = str(infos.get("config_llm") or "").strip()
    if explicit_local:
        candidates.append(Path(explicit_local))

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except Exception:
            continue
    return None


def _resolve_openai_api_key(appcfg: dict) -> str:
    _load_env_for_runtime_config()
    env_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if env_key and not _is_placeholder_secret(env_key, {"OPENAI_API_KEY"}):
        return env_key
    cfg_key = str(appcfg.get("openai_api_key") or "").strip()
    if cfg_key and not _is_placeholder_secret(cfg_key, {"OPENAI_API_KEY"}):
        return cfg_key
    return ""


def _resolve_local_llm_settings(appcfg: dict) -> dict:
    _load_env_for_runtime_config()
    local_cfg = dict(appcfg.get("local_llm") or {})

    server_url = (os.getenv("SERVER_URL") or "").strip()
    base_url_env = (os.getenv("LOCAL_LLM_BASE_URL") or "").strip()
    base_url_cfg = str(local_cfg.get("base_url") or "").strip()
    extra_candidates: list[str] = []
    if server_url or base_url_env:
        extra_candidates.append(server_url or base_url_env)
    elif base_url_cfg and base_url_cfg.rstrip("/") not in DEFAULT_FLASK_ENDPOINTS:
        extra_candidates.append(base_url_cfg)
    local_cfg["base_url"] = resolve_flask_base_url(extra_candidates=extra_candidates)

    env_key = (os.getenv("LOCAL_LLM_API_KEY") or "").strip()
    cfg_key = str(local_cfg.get("api_key") or "").strip()
    if env_key and not _is_placeholder_secret(env_key, {"LOCAL_LLM_API_KEY", "LOCAL_LLM_API_KEY_PLACEHOLDER"}):
        local_cfg["api_key"] = env_key
    elif cfg_key and not _is_placeholder_secret(cfg_key, {"LOCAL_LLM_API_KEY", "LOCAL_LLM_API_KEY_PLACEHOLDER"}):
        local_cfg["api_key"] = cfg_key
    else:
        local_cfg["api_key"] = ""

    return local_cfg


def _resolve_local_asr_model_key(appcfg: dict) -> str:
    _load_env_for_runtime_config()
    for candidate in (
        os.getenv("LOCAL_ASR_MODEL_KEY"),
        os.getenv("ASR_MODEL_KEY"),
        str((appcfg.get("local_llm") or {}).get("asr_model_key") or "").strip(),
        str(appcfg.get("local_asr_model_key") or "").strip(),
    ):
        value = str(candidate or "").strip()
        if value:
            return value
    return "Voxtral_Mini_3B_Transformers"


def _config_bool(appcfg: dict, key: str, default: bool) -> bool:
    value = appcfg.get(key, default)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "oui", "on"}:
        return True
    if text in {"0", "false", "no", "n", "non", "off"}:
        return False
    return default


def _config_positive_int(appcfg: dict, key: str, default: int) -> int:
    value = appcfg.get(key, default)
    try:
        value = int(value)
    except Exception:
        return default
    return value if value > 0 else default


def _build_dictation_local_asr_options(appcfg: dict, duration_s: float) -> dict:
    dictation_is_long = float(duration_s or 0.0) >= (45 * 60)
    default_chunk = 120 if dictation_is_long else 30
    default_stride = 5 if dictation_is_long else 10
    default_auto_chunk = bool(dictation_is_long)

    client_tag = str(appcfg.get("dictation_asr_client_tag") or "annotationphotogpt_dictation_ui").strip()
    if not client_tag:
        client_tag = "annotationphotogpt_dictation_ui"

    return {
        "model_key": str(appcfg.get("dictation_asr_model") or _resolve_local_asr_model_key(appcfg)).strip(),
        "cpu": _config_bool(appcfg, "dictation_asr_force_cpu", False),
        "no4bit": _config_bool(appcfg, "dictation_asr_no4bit", False),
        "chunk": _config_positive_int(appcfg, "dictation_asr_chunk", default_chunk),
        "stride": _config_positive_int(appcfg, "dictation_asr_stride", default_stride),
        "batch_size": _config_positive_int(appcfg, "dictation_asr_batch_size", 1),
        "auto_chunk": _config_bool(appcfg, "dictation_asr_auto_chunk", default_auto_chunk),
        "client_tag": client_tag,
    }


def _resolve_libelle_transcript_fallback(
    *,
    extrait_lib: str,
    extrait_com: str,
    dictee_text: str,
    dictee_status: str,
    commentaire_value: str,
) -> tuple[str, str]:
    extrait_lib = _normalize_text(extrait_lib, "libelle")
    if extrait_lib:
        return extrait_lib, "extrait_lib"

    dictee_status = str(dictee_status or "").strip().upper()
    dictee_text = _normalize_text(dictee_text, "commentaire")
    if dictee_status == "OK" and dictee_text:
        return dictee_text, "dictee_asr"

    commentaire_value = _normalize_text(commentaire_value, "commentaire")
    if commentaire_value:
        return commentaire_value, "commentaire_existant"

    extrait_com = _normalize_text(extrait_com, "commentaire")
    if extrait_com:
        return extrait_com, "extrait_com"

    return "", ""


def _ensure_photo_text_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df
    for col in columns:
        if col not in out.columns:
            out[col] = ""
        else:
            out[col] = out[col].astype("string")
    return out


def _ui_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _analyze_audio_bytes(audio_bytes: bytes) -> dict:
    if not audio_bytes:
        raise RuntimeError("Audio dicté vide.")

    try:
        audio_data, sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=True)
    except Exception as e:
        raise RuntimeError(f"Audio dicté illisible ou non décodable : {e}") from e

    frames = int(audio_data.shape[0]) if audio_data.ndim >= 1 else 0
    channels = int(audio_data.shape[1]) if audio_data.ndim >= 2 else 1
    duration_s = float(frames / sample_rate) if sample_rate and frames else 0.0

    if frames <= 0 or channels <= 0:
        return {
            "sample_rate": int(sample_rate or 0),
            "channels": channels,
            "frames": frames,
            "duration_s": duration_s,
            "rms": 0.0,
            "peak": 0.0,
            "is_effectively_silent": True,
        }

    peak = float(np.max(np.abs(audio_data)))
    rms = float(np.sqrt(np.mean(np.square(audio_data))))
    is_effectively_silent = (peak < 1e-4) or (rms < 1e-5)

    return {
        "sample_rate": int(sample_rate or 0),
        "channels": channels,
        "frames": frames,
        "duration_s": duration_s,
        "rms": rms,
        "peak": peak,
        "is_effectively_silent": bool(is_effectively_silent),
    }


def _audio_diag_verdict(audio_diag: dict) -> tuple[str, str]:
    peak = float(audio_diag.get("peak") or 0.0)
    rms = float(audio_diag.get("rms") or 0.0)
    if audio_diag.get("is_effectively_silent"):
        return "audio silencieux", "error"
    if peak < 5e-3 or rms < 5e-4:
        return "audio trop faible", "warning"
    return "audio exploitable", "success"


def _perf_log(label: str, started_at: float) -> None:
    print(f"[PERF] {label}: {time.perf_counter() - started_at:.3f}s")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_id_part(value: str, default: str = "item") -> str:
    text = str(value or "").strip().replace("\\", "_").replace("/", "_")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return text[:96] or default


def _dictation_registry_paths() -> tuple[Path, Path]:
    _DICTEES_PENDING_DIR.mkdir(parents=True, exist_ok=True)
    return _DICTEES_ROOT, _DICTEES_PENDING_DIR


def _dictation_json_path(dictation_id: str) -> Path:
    _, pending_dir = _dictation_registry_paths()
    return pending_dir / f"{_safe_id_part(dictation_id, 'dictee')}.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _load_dictation_record(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_dictation_record(record: dict) -> None:
    _atomic_write_json(_dictation_json_path(str(record.get("dictation_id") or "")), record)


def _iter_dictation_records(status: str | None = None) -> list[tuple[Path, dict]]:
    _, pending_dir = _dictation_registry_paths()
    rows: list[tuple[Path, dict]] = []
    for path in sorted(pending_dir.glob("*.json")):
        record = _load_dictation_record(path)
        if not record:
            continue
        if status and str(record.get("status") or "").upper() != status.upper():
            continue
        rows.append((path, record))
    return rows


def _photo_stable_key(row, ui_index: int | None = None) -> str:
    photo_rel = _ui_text(row.get("photo_rel_native"))
    if photo_rel:
        return photo_rel
    nom = _ui_text(row.get("nom_fichier_image"))
    if nom:
        return nom
    return f"ui_index:{ui_index}" if ui_index is not None else ""


def _load_dictation_spooler_config(infos: dict | None = None) -> dict:
    cfg = _load_json_file(_CONFIG_DIR / "config.json")
    project_cfg_path = _resolve_project_config_llm_path(infos)
    if project_cfg_path:
        cfg = _deep_merge_dict(cfg, _load_json_file(project_cfg_path))
    return cfg


def _pcfixe_smb_roots_from_infos(pcfixe: dict) -> list[str]:
    def _dedupe(values: list[str]) -> list[str]:
        roots: list[str] = []
        for value in values:
            root = str(value or "").strip().rstrip("\\/")
            if root and root.lower() not in {r.lower() for r in roots}:
                roots.append(root)
        return roots

    def _is_vpn_root(value: str) -> bool:
        root = str(value or "").strip().lower()
        return root.startswith(r"\\10.0.1.")

    def _is_lan_root(value: str) -> bool:
        root = str(value or "").strip().lower()
        return root.startswith(r"\\192.168.0.")

    configured = str((pcfixe or {}).get("root_affaires") or "").strip().rstrip("\\/")
    if configured.lower() == _NAS_AFFAIRES_SMB_ROOT.lower():
        configured = ""

    if _vpn_active():
        roots = [r"\\10.0.1.10\Affaires"]
        if configured and _is_vpn_root(configured):
            roots.append(configured)
        return _dedupe(roots[:2])

    roots = []
    if configured and _is_lan_root(configured):
        roots.append(configured)
    roots.extend([r"\\192.168.0.155\Affaires", r"\\192.168.0.120\Affaires"])
    return _dedupe(roots)[:2]


def _server_affaires_path(*parts: str) -> str:
    suffix = "\\".join(str(p).strip("\\/") for p in parts if str(p or "").strip("\\/"))
    return _PCFIXE_LOCAL_AFFAIRES_ROOT + ("\\" + suffix if suffix else "")


def _canonical_laptop_photos_dir(infos: dict) -> Path:
    id_affaire = _ui_text((infos or {}).get("id_affaire") or (infos or {}).get("project_id"))
    id_captation = _ui_text((infos or {}).get("id_captation") or (infos or {}).get("captation_id"))
    if not id_affaire or not id_captation:
        raise RuntimeError("id_affaire/id_captation absents : miroir C:\\Affaires impossible.")
    return (
        Path(_PCFIXE_LOCAL_AFFAIRES_ROOT)
        / id_affaire
        / "AE_Expert_captations"
        / id_captation
        / "photos"
    )


def _nas_photos_csv_path(infos: dict) -> Path | None:
    pcfixe = (infos or {}).get("pcfixe") or {}
    if not isinstance(pcfixe, dict):
        return None
    raw = _ui_text(pcfixe.get("fichier_photos"))
    return Path(raw) if raw else None


def _nas_photos_batch_path(infos: dict) -> Path | None:
    pcfixe = (infos or {}).get("pcfixe") or {}
    if not isinstance(pcfixe, dict):
        return None
    raw = _ui_text(pcfixe.get("fichier_photos_batch"))
    return Path(raw) if raw else None


def _nas_photos_dir(infos: dict) -> Path | None:
    nas_csv = _nas_photos_csv_path(infos)
    return nas_csv.parent if nas_csv else None


def _unc_host(path: str | Path) -> str:
    raw = str(path or "").strip().replace("/", "\\")
    if not raw.startswith("\\\\"):
        return ""
    parts = [p for p in raw.split("\\") if p]
    return parts[0] if parts else ""


def _unc_available(path: str | Path, timeout_s: float = _UNC_PROBE_TIMEOUT_S) -> bool:
    host = _unc_host(path)
    if not host:
        return True
    try:
        with socket.create_connection((host, 445), timeout=timeout_s):
            return True
    except OSError:
        return False


def _atomic_tmp_path(target: Path, suffix: str = ".tmp") -> Path:
    return target.with_name(f".apg-tmp-{os.getpid()}-{uuid.uuid4().hex}-{target.name}{suffix}")


def _fsync_path(path: Path) -> None:
    try:
        with Path(path).open("rb") as f:
            os.fsync(f.fileno())
    except Exception:
        pass


def _atomic_write_dataframe_csv(df: pd.DataFrame, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _atomic_tmp_path(target)
    try:
        df.to_csv(tmp, sep=";", encoding="utf-8-sig", index=False)
        _fsync_path(tmp)
        os.replace(str(tmp), str(target))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return target


def _atomic_write_dataframe_xlsx(df: pd.DataFrame, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _atomic_tmp_path(target, suffix=".tmp.xlsx")
    try:
        df.to_excel(tmp, index=False, engine="openpyxl")
        _fsync_path(tmp)
        os.replace(str(tmp), str(target))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return target


def _copy_file_atomic(src: str | Path, dst: str | Path) -> Path:
    src_path = Path(src)
    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _atomic_tmp_path(dst_path)
    try:
        shutil.copy2(str(src_path), str(tmp))
        _fsync_path(tmp)
        os.replace(str(tmp), str(dst_path))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return dst_path


def _atomic_write_json_file(path: str | Path, payload: dict) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = _atomic_tmp_path(target)
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(target))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return target


def _sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _photo_rel_at(photos_df: pd.DataFrame, idx: int) -> str:
    try:
        if "photo_rel_native" in photos_df.columns:
            return _ui_text(photos_df.at[idx, "photo_rel_native"])
    except Exception:
        pass
    return ""


def _photos_csv_profile(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"path": str(p), "exists": False}
    profile = {
        "path": str(p),
        "exists": True,
        "sha256": _sha256_file(p),
        "rows": 0,
        "dictee_cells": 0,
        "max_ts": "",
    }
    try:
        df = pd.read_csv(p, sep=";", encoding="utf-8-sig")
    except Exception as exc:
        profile["error"] = str(exc)
        return profile
    profile["rows"] = int(len(df))
    dictee_cols = [c for c in df.columns if str(c).startswith("dictee_") or str(c) == "dictation_id"]
    if dictee_cols:
        profile["dictee_cells"] = int(
            df[dictee_cols].fillna("").astype(str).apply(lambda col: col.str.strip().ne("").sum()).sum()
        )
    max_values = []
    for col in ("dictee_asr_ts", "ui_ts"):
        if col not in df.columns:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        if parsed.notna().any():
            max_values.append(parsed.max())
    if max_values:
        profile["max_ts"] = max(max_values).isoformat(sep=" ", timespec="seconds")
    return profile


def _profile_signature(profile: dict) -> tuple:
    return (
        bool(profile.get("exists")),
        profile.get("sha256", ""),
        int(profile.get("rows") or 0),
        int(profile.get("dictee_cells") or 0),
        profile.get("max_ts", ""),
    )


def _profile_has_business_changes(profile: dict) -> bool:
    return bool(int(profile.get("dictee_cells") or 0) > 0 or profile.get("max_ts"))


def _conflict_backup_path(path: Path, source_name: str, stamp: str) -> Path:
    return path.with_name(f"{path.name}.sync-conflict-{stamp}-{source_name}.bak")


def _create_photos_csv_conflict_backups(profiles: dict) -> list[str]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups: list[str] = []
    for source_name, profile in profiles.items():
        if not profile.get("exists") or not _profile_has_business_changes(profile):
            continue
        src = Path(_ui_text(profile.get("path")))
        if _unc_host(src) and not _unc_available(src):
            continue
        backup = _conflict_backup_path(src, source_name, stamp)
        shutil.copy2(str(src), str(backup))
        backups.append(str(backup))
    return backups


def _load_pending_nas_registry() -> dict:
    if not _PHOTOS_NAS_PENDING_PATH.exists():
        return {}
    try:
        payload = json.loads(_PHOTOS_NAS_PENDING_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("[PHOTOS_SYNC] pending registry unreadable: %s", exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_pending_nas_registry(payload: dict) -> None:
    _atomic_write_json_file(_PHOTOS_NAS_PENDING_PATH, payload)


def _delete_pending_nas_registry() -> None:
    try:
        _PHOTOS_NAS_PENDING_PATH.unlink(missing_ok=True)
    except Exception as exc:
        log.warning("[PHOTOS_SYNC] pending registry delete failed: %s", exc)


def _sync_photos_csv_on_launch(infos: dict, photos_csv: str) -> None:
    work_csv = Path(str(photos_csv or "").strip())
    if not str(work_csv).strip():
        return
    mirror_csv = _canonical_laptop_photos_dir(infos) / "photos.csv"
    nas_csv = _nas_photos_csv_path(infos)

    profiles = {
        "work": _photos_csv_profile(work_csv),
        "mirror": _photos_csv_profile(mirror_csv),
    }
    if nas_csv and _unc_available(nas_csv):
        profiles["nas"] = _photos_csv_profile(nas_csv)
    else:
        profiles["nas"] = {"path": str(nas_csv or ""), "exists": False, "error": "NAS indisponible ou non configure"}

    st.session_state["photos_csv_source_profiles"] = profiles
    existing = {name: p for name, p in profiles.items() if p.get("exists")}
    if not existing:
        return

    work = profiles["work"]
    if not work.get("exists"):
        for name in ("nas", "mirror"):
            candidate = profiles.get(name, {})
            if candidate.get("exists") and not candidate.get("error"):
                _copy_file_atomic(candidate["path"], work_csv)
                st.caption(f"photos.csv retenu depuis {name} : {candidate['path']}")
                return

    signatures = {name: _profile_signature(p) for name, p in existing.items()}
    if len(set(signatures.values())) <= 1:
        return

    comparable = {
        name: {
            "path": p.get("path"),
            "sha256": p.get("sha256"),
            "rows": p.get("rows"),
            "dictee_cells": p.get("dictee_cells"),
            "max_ts": p.get("max_ts"),
            "error": p.get("error", ""),
        }
        for name, p in profiles.items()
    }
    changed_sources = [name for name, p in existing.items() if _profile_has_business_changes(p)]
    if len(changed_sources) >= 2:
        conflict_signature = json.dumps(comparable, ensure_ascii=False, sort_keys=True)
        if st.session_state.get("photos_csv_conflict_signature") != conflict_signature:
            backups = _create_photos_csv_conflict_backups(existing)
            st.session_state["photos_csv_conflict_signature"] = conflict_signature
            st.session_state["photos_csv_conflict_backups"] = backups
            comparable["conflict_backups"] = backups
        st.session_state["photos_csv_sync_conflict"] = comparable
    log.warning("[PHOTOS_SYNC] photos.csv divergence on launch: %s", json.dumps(comparable, ensure_ascii=False))
    st.warning("Conflit photos.csv detecte entre travail, C:\\Affaires et/ou NAS : aucune copie automatique.")


def _record_photos_persistence_state(**payload) -> None:
    state = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "local_saved": False,
        "canonical_mirror_saved": False,
        "nas_saved": False,
        **payload,
    }
    st.session_state["photos_persistence_state"] = state
    log.info("[PHOTOS_SYNC] %s", json.dumps(state, ensure_ascii=False, sort_keys=True))


def _clear_nas_pending() -> None:
    st.session_state["nas_sync_pending"] = False
    st.session_state.pop("nas_sync_pending_payload", None)
    st.session_state["nas_sync_error"] = ""
    _delete_pending_nas_registry()


def _set_nas_pending(payload: dict, error: Exception | str) -> None:
    previous = _load_pending_nas_registry()
    previous_attempts = int(previous.get("attempts") or previous.get("tentatives") or 0)
    payload_attempts = int(payload.get("attempts") or payload.get("tentatives") or 0)
    attempts = max(previous_attempts, payload_attempts) + 1
    pending_payload = {
        "operation_id": _ui_text(payload.get("operation_id")),
        "reason": _ui_text(payload.get("reason")) or "photos_csv_sync",
        "photo_rel_native": _ui_text(payload.get("photo_rel_native")),
        "work_csv": _ui_text(payload.get("work_csv")),
        "mirror_csv": _ui_text(payload.get("mirror_csv")),
        "mirror_xlsx": _ui_text(payload.get("mirror_xlsx")),
        "nas_csv": _ui_text(payload.get("nas_csv")),
        "local_hash": _ui_text(payload.get("local_hash")),
        "mirror_hash": _ui_text(payload.get("mirror_hash")),
        "last_error": str(error),
        "derniere_erreur": str(error),
        "attempts": attempts,
        "tentatives": attempts,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_pending_nas_registry(pending_payload)
    st.session_state["nas_sync_pending"] = True
    st.session_state["nas_sync_pending_payload"] = pending_payload
    st.session_state["nas_sync_error"] = str(error)


def _try_copy_to_nas(
    *,
    mirror_csv: Path,
    mirror_xlsx: Path,
    nas_csv: Path | None,
    reason: str,
    photo_rel_native: str,
) -> dict:
    result = {
        "nas_saved": False,
        "nas_csv": str(nas_csv or ""),
        "nas_xlsx": "",
        "nas_hash": "",
        "nas_xlsx_hash": "",
        "nas_error": "",
    }
    if nas_csv is None:
        result["nas_error"] = "infos.pcfixe.fichier_photos absent"
        return result
    if not _unc_available(nas_csv):
        result["nas_error"] = f"SMB indisponible ou trop lent ({_UNC_PROBE_TIMEOUT_S:.1f}s): {_unc_host(nas_csv)}"
        return result
    try:
        _copy_file_atomic(mirror_csv, nas_csv)
        result["nas_hash"] = _sha256_file(nas_csv)
        if result["nas_hash"] != _sha256_file(mirror_csv):
            raise RuntimeError(f"Hash different apres copie NAS: {nas_csv}")

        if mirror_xlsx.exists():
            nas_xlsx = nas_csv.with_suffix(".xlsx")
            _copy_file_atomic(mirror_xlsx, nas_xlsx)
            result["nas_xlsx"] = str(nas_xlsx)
            result["nas_xlsx_hash"] = _sha256_file(nas_xlsx)
            if result["nas_xlsx_hash"] != _sha256_file(mirror_xlsx):
                raise RuntimeError(f"Hash different apres copie NAS: {nas_xlsx}")
        result["nas_saved"] = True
        _clear_nas_pending()
        log.info(
            "[PHOTOS_SYNC] nas_saved reason=%s photo_rel_native=%s nas=%s",
            reason,
            photo_rel_native,
            nas_csv,
        )
    except Exception as exc:
        result["nas_error"] = str(exc)
    return result


def _retry_pending_nas_sync(infos: dict) -> bool:
    pending = st.session_state.get("nas_sync_pending_payload")
    if not st.session_state.get("nas_sync_pending") or not isinstance(pending, dict):
        pending = _load_pending_nas_registry()
    if not isinstance(pending, dict) or not pending:
        return False
    st.session_state["nas_sync_pending"] = True
    st.session_state["nas_sync_pending_payload"] = pending
    mirror_csv = Path(_ui_text(pending.get("mirror_csv")))
    mirror_xlsx_raw = _ui_text(pending.get("mirror_xlsx"))
    mirror_xlsx = Path(mirror_xlsx_raw) if mirror_xlsx_raw else Path("__photos_xlsx_absent__")
    nas_csv = Path(_ui_text(pending.get("nas_csv"))) if _ui_text(pending.get("nas_csv")) else _nas_photos_csv_path(infos)
    if not mirror_csv.exists():
        _set_nas_pending(pending, f"Miroir introuvable pour reprise NAS: {mirror_csv}")
        return False
    result = _try_copy_to_nas(
        mirror_csv=mirror_csv,
        mirror_xlsx=mirror_xlsx,
        nas_csv=nas_csv,
        reason=_ui_text(pending.get("reason")) or "retry_pending",
        photo_rel_native=_ui_text(pending.get("photo_rel_native")),
    )
    if result["nas_saved"]:
        return True
    _set_nas_pending(pending, result["nas_error"])
    return False


def _load_gpt_exports_pending_registry() -> dict:
    if not _GTP_EXPORTS_NAS_PENDING_PATH.exists():
        return {"entries": {}}
    try:
        payload = json.loads(_GTP_EXPORTS_NAS_PENDING_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("[GTP_EXPORT_SYNC] pending registry unreadable: %s", exc)
        return {"entries": {}}
    if not isinstance(payload, dict):
        return {"entries": {}}
    payload.setdefault("entries", {})
    if not isinstance(payload["entries"], dict):
        payload["entries"] = {}
    return payload


def _write_gpt_exports_pending_registry(payload: dict) -> None:
    payload = payload if isinstance(payload, dict) else {}
    payload.setdefault("entries", {})
    _atomic_write_json_file(_GTP_EXPORTS_NAS_PENDING_PATH, payload)


def _set_gpt_exports_sync_pending(is_pending: bool, payload: dict | None = None) -> None:
    st.session_state["gpt_exports_sync_pending"] = bool(is_pending)
    st.session_state["gtp_exports_sync_pending"] = bool(is_pending)
    if payload is None:
        st.session_state.pop("gpt_exports_sync_pending_payload", None)
        st.session_state.pop("gtp_exports_sync_pending_payload", None)
    else:
        st.session_state["gpt_exports_sync_pending_payload"] = payload
        st.session_state["gtp_exports_sync_pending_payload"] = payload


def _set_gpt_exports_publish_state(state: dict) -> None:
    st.session_state["gpt_exports_publish_state"] = state
    st.session_state["gtp_exports_publish_state"] = state


def _gpt_pending_key(nas_path: str | Path) -> str:
    return hashlib.sha256(str(nas_path).casefold().encode("utf-8")).hexdigest()[:24]


def _register_gpt_export_pending(
    *,
    infos: dict,
    local_path: Path,
    nas_path: Path,
    file_type: str,
    error: Exception | str,
    status: str = "pending",
    operation_id: str = "",
) -> dict:
    payload = _load_gpt_exports_pending_registry()
    entries = payload.setdefault("entries", {})
    key = _gpt_pending_key(nas_path)
    previous = entries.get(key, {}) if isinstance(entries.get(key), dict) else {}
    retry_count = int(previous.get("retry_count") or previous.get("attempts") or previous.get("tentatives") or 0) + 1
    now = datetime.now().isoformat(timespec="seconds")
    local_sha256 = _sha256_file(local_path) if local_path.exists() else ""
    entry = {
        "operation_id": _ui_text(operation_id) or _ui_text(previous.get("operation_id")) or uuid.uuid4().hex,
        "affaire": _ui_text((infos or {}).get("id_affaire") or (infos or {}).get("project_id")),
        "captation": _ui_text((infos or {}).get("id_captation") or (infos or {}).get("captation_id")),
        "type": file_type,
        "local_path": str(local_path),
        "nas_path": str(nas_path),
        "local_sha256": local_sha256,
        "sha256_local": local_sha256,
        "file_type": file_type,
        "created_at": previous.get("created_at") or now,
        "last_attempt_at": now,
        "last_error": str(error),
        "retry_count": retry_count,
        "attempts": retry_count,
        "tentatives": retry_count,
        "status": status,
    }
    entries[key] = entry
    _write_gpt_exports_pending_registry(payload)
    _set_gpt_exports_sync_pending(True, payload)
    return entry


def _clear_gpt_export_pending(nas_path: str | Path) -> None:
    payload = _load_gpt_exports_pending_registry()
    entries = payload.setdefault("entries", {})
    entries.pop(_gpt_pending_key(nas_path), None)
    if entries:
        _write_gpt_exports_pending_registry(payload)
        _set_gpt_exports_sync_pending(True, payload)
    else:
        try:
            _GTP_EXPORTS_NAS_PENDING_PATH.unlink(missing_ok=True)
        except Exception:
            _write_gpt_exports_pending_registry(payload)
        _set_gpt_exports_sync_pending(False)


def _conflict_backup_existing_nas(path: Path) -> str:
    if not path.exists():
        return ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.conflict-{stamp}.nas.bak")
    shutil.copy2(str(path), str(backup))
    return str(backup)


def _copy_file_atomic_verified(src: Path, dst: Path) -> dict:
    src = Path(src)
    dst = Path(dst)
    if not src.is_file():
        raise FileNotFoundError(f"Fichier source introuvable : {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_hash = _sha256_file(src)
    src_size = src.stat().st_size
    if dst.exists():
        dst_hash = _sha256_file(dst)
        if dst_hash == src_hash:
            return {
                "ok": True,
                "already": True,
                "sha256": src_hash,
                "size": src_size,
                "path": str(dst),
            }
        backup = _conflict_backup_existing_nas(dst)
        raise FileExistsError(
            f"Conflit NAS : {dst} existe avec un hash different. Sauvegarde creee : {backup}"
        )
    tmp = _atomic_tmp_path(dst)
    try:
        shutil.copy2(str(src), str(tmp))
        _fsync_path(tmp)
        if tmp.stat().st_size != src_size:
            raise RuntimeError(f"Taille differente avant publication NAS : {dst}")
        if _sha256_file(tmp) != src_hash:
            raise RuntimeError(f"Hash different avant publication NAS : {dst}")
        os.replace(str(tmp), str(dst))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    final_hash = _sha256_file(dst)
    if final_hash != src_hash:
        raise RuntimeError(f"Hash different apres publication NAS : {dst}")
    return {"ok": True, "already": False, "sha256": final_hash, "size": src_size, "path": str(dst)}


def _retry_pending_gpt_exports(infos: dict) -> dict:
    payload = _load_gpt_exports_pending_registry()
    entries = payload.get("entries", {})
    result = {"resolved": 0, "pending": 0, "conflicts": 0, "errors": []}
    if not entries:
        _set_gpt_exports_sync_pending(False)
        return result
    for key, entry in list(entries.items()):
        local_path = Path(_ui_text(entry.get("local_path")))
        nas_path = Path(_ui_text(entry.get("nas_path")))
        expected_hash = _ui_text(entry.get("local_sha256") or entry.get("sha256_local"))
        if not local_path.is_file():
            entry["last_error"] = f"Fichier local introuvable : {local_path}"
            entry["last_attempt_at"] = datetime.now().isoformat(timespec="seconds")
            result["pending"] += 1
            continue
        if nas_path.exists() and _sha256_file(nas_path) == expected_hash:
            entries.pop(key, None)
            result["resolved"] += 1
            continue
        try:
            if not _unc_available(nas_path):
                raise ConnectionError(f"NAS indisponible ou trop lent ({_UNC_PROBE_TIMEOUT_S:.1f}s): {_unc_host(nas_path)}")
            _copy_file_atomic_verified(local_path, nas_path)
            entries.pop(key, None)
            result["resolved"] += 1
        except FileExistsError as exc:
            entry.update({
                "status": "conflict",
                "last_error": str(exc),
                "last_attempt_at": datetime.now().isoformat(timespec="seconds"),
                "retry_count": int(entry.get("retry_count") or entry.get("attempts") or 0) + 1,
            })
            entry["attempts"] = entry["retry_count"]
            entry["tentatives"] = entry["retry_count"]
            result["conflicts"] += 1
            result["errors"].append(str(exc))
        except Exception as exc:
            entry.update({
                "status": "pending",
                "last_error": str(exc),
                "last_attempt_at": datetime.now().isoformat(timespec="seconds"),
                "retry_count": int(entry.get("retry_count") or entry.get("attempts") or 0) + 1,
            })
            entry["attempts"] = entry["retry_count"]
            entry["tentatives"] = entry["retry_count"]
            result["pending"] += 1
            result["errors"].append(str(exc))
    if entries:
        _write_gpt_exports_pending_registry(payload)
        _set_gpt_exports_sync_pending(True, payload)
    else:
        try:
            _GTP_EXPORTS_NAS_PENDING_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        _set_gpt_exports_sync_pending(False)
    return result


def _publish_validated_annotation_file(
    *,
    infos: dict,
    local_path: Path,
    nas_path: Path,
    file_type: str,
    operation_id: str = "",
) -> dict:
    result = {
        "operation_id": operation_id,
        "file_type": file_type,
        "local_path": str(local_path),
        "nas_path": str(nas_path),
        "local_hash": _sha256_file(local_path) if local_path.exists() else "",
        "nas_saved": False,
        "pending": False,
        "conflict": False,
        "error": "",
    }
    try:
        if not _unc_available(nas_path):
            raise ConnectionError(f"NAS indisponible ou trop lent ({_UNC_PROBE_TIMEOUT_S:.1f}s): {_unc_host(nas_path)}")
        copy_result = _copy_file_atomic_verified(local_path, nas_path)
        result.update({
            "nas_saved": True,
            "nas_hash": copy_result.get("sha256", ""),
            "nas_size": copy_result.get("size", ""),
        })
        _clear_gpt_export_pending(nas_path)
    except FileExistsError as exc:
        result.update({"conflict": True, "error": str(exc)})
        _register_gpt_export_pending(
            infos=infos,
            local_path=local_path,
            nas_path=nas_path,
            file_type=file_type,
            error=exc,
            status="conflict",
            operation_id=operation_id,
        )
    except Exception as exc:
        result.update({"pending": True, "error": str(exc)})
        _register_gpt_export_pending(
            infos=infos,
            local_path=local_path,
            nas_path=nas_path,
            file_type=file_type,
            error=exc,
            status="pending",
            operation_id=operation_id,
        )
    return result


def _write_and_publish_validated_annotations(
    annotations_df: pd.DataFrame,
    annotations_path: str | Path,
    infos: dict,
    *,
    operation_id: str = "",
) -> dict:
    operation_id = _ui_text(operation_id) or uuid.uuid4().hex
    work_csv = Path(annotations_path)
    filename_csv = work_csv.name
    filename_xlsx = work_csv.with_suffix(".xlsx").name
    canonical_dir = _canonical_laptop_photos_dir(infos)
    local_csv = canonical_dir / filename_csv
    local_xlsx = canonical_dir / filename_xlsx
    nas_dir = _nas_photos_dir(infos)
    if nas_dir is None:
        raise RuntimeError("Chemin NAS photos introuvable dans infos.pcfixe.fichier_photos")
    nas_csv = nas_dir / filename_csv
    nas_xlsx = nas_dir / filename_xlsx

    local_csv = _atomic_write_dataframe_csv(annotations_df, local_csv)
    local_xlsx = _atomic_write_dataframe_xlsx(annotations_df, local_xlsx)

    work_results = []
    if str(work_csv.resolve()).casefold() != str(local_csv.resolve()).casefold():
        _copy_file_atomic(local_csv, work_csv)
        work_results.append(str(work_csv))
    work_xlsx = work_csv.with_suffix(".xlsx")
    if str(work_xlsx.resolve()).casefold() != str(local_xlsx.resolve()).casefold():
        _copy_file_atomic(local_xlsx, work_xlsx)
        work_results.append(str(work_xlsx))

    csv_result = _publish_validated_annotation_file(
        infos=infos,
        local_path=local_csv,
        nas_path=nas_csv,
        file_type="gtp_csv",
        operation_id=operation_id,
    )
    xlsx_result = _publish_validated_annotation_file(
        infos=infos,
        local_path=local_xlsx,
        nas_path=nas_xlsx,
        file_type="gtp_xlsx",
        operation_id=operation_id,
    )
    partial = bool(csv_result.get("nas_saved")) != bool(xlsx_result.get("nas_saved"))
    state = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "operation_id": operation_id,
        "csv": csv_result,
        "xlsx": xlsx_result,
        "partial": partial,
        "work_compat_copies": work_results,
    }
    _set_gpt_exports_publish_state(state)
    log.info("[GTP_EXPORT_SYNC] %s", json.dumps(state, ensure_ascii=False, sort_keys=True))
    return state


def _persist_photos_csv(
    photos_df: pd.DataFrame,
    photos_csv: str,
    infos: dict,
    *,
    reason: str = "",
    photo_rel_native: str = "",
    maintain_xlsx: bool = True,
    operation_id: str = "",
    create_backup: bool = False,
) -> None:
    _retry_pending_nas_sync(infos)
    state_payload = {
        "operation_id": _ui_text(operation_id),
        "reason": reason,
        "photo_rel_native": photo_rel_native,
        "work_csv": str(photos_csv),
        "mirror_csv": "",
        "nas_csv": "",
        "local_saved": False,
        "canonical_mirror_saved": False,
        "nas_saved": False,
    }
    photos_csv_path = Path(photos_csv)
    if create_backup and photos_csv_path.exists():
        backup = photos_csv_path.with_name(
            f"{photos_csv_path.stem}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}{photos_csv_path.suffix}"
        )
        shutil.copy2(photos_csv_path, backup)
        state_payload["backup_csv"] = str(backup)
    work_csv = _atomic_write_dataframe_csv(photos_df, photos_csv)
    state_payload["work_csv"] = str(work_csv)
    state_payload["local_saved"] = True
    state_payload["local_hash"] = _sha256_file(work_csv)
    st.session_state["canonical_mirror_pending"] = False
    st.session_state["canonical_mirror_error"] = ""

    work_xlsx = work_csv.with_suffix(".xlsx")
    if maintain_xlsx:
        try:
            _atomic_write_dataframe_xlsx(photos_df, work_xlsx)
            state_payload["work_xlsx"] = str(work_xlsx)
            state_payload["local_xlsx_hash"] = _sha256_file(work_xlsx)
        except Exception as exc:
            st.warning(f"Recreation photos.xlsx impossible : {exc}")

    try:
        canonical_dir = _canonical_laptop_photos_dir(infos)
        mirror_csv = canonical_dir / "photos.csv"
        state_payload["mirror_csv"] = str(mirror_csv)
        _copy_file_atomic(work_csv, mirror_csv)
        mirror_hash = _sha256_file(mirror_csv)
        state_payload["mirror_hash"] = mirror_hash
        if state_payload["local_hash"] != mirror_hash:
            raise RuntimeError(f"Hash different apres copie miroir: {mirror_csv}")
        state_payload["canonical_mirror_saved"] = True

        mirror_xlsx = canonical_dir / "photos.xlsx"
        if maintain_xlsx and work_xlsx.exists():
            _copy_file_atomic(work_xlsx, mirror_xlsx)
            mirror_xlsx_hash = _sha256_file(mirror_xlsx)
            state_payload["mirror_xlsx"] = str(mirror_xlsx)
            state_payload["mirror_xlsx_hash"] = mirror_xlsx_hash
            if state_payload.get("local_xlsx_hash") != mirror_xlsx_hash:
                raise RuntimeError(f"Hash different apres copie miroir: {mirror_xlsx}")

        nas_csv = _nas_photos_csv_path(infos)
        state_payload["nas_csv"] = str(nas_csv or "")
        nas_result = _try_copy_to_nas(
            mirror_csv=mirror_csv,
            mirror_xlsx=mirror_xlsx,
            nas_csv=nas_csv,
            reason=reason,
            photo_rel_native=photo_rel_native,
        )
        state_payload.update(nas_result)
        if nas_result["nas_saved"]:
            st.session_state["nas_sync_error"] = ""
        else:
            _set_nas_pending(state_payload, nas_result["nas_error"])
            st.warning("Sauvegarde locale effectuée — synchronisation NAS en attente")
        _record_photos_persistence_state(**state_payload)
    except Exception as exc:
        st.session_state["canonical_mirror_pending"] = True
        st.session_state["canonical_mirror_error"] = str(exc)
        _record_photos_persistence_state(**{**state_payload, "canonical_mirror_error": str(exc)})
        st.warning(f"Miroir canonique en attente : {exc}")


def _csv_has_coherent_photos_schema(path: Path) -> bool:
    try:
        df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    except Exception:
        return False
    return bool(not df.empty and "photo_rel_native" in df.columns and "nom_fichier_image" in df.columns)


_PHOTOS_BATCH_MTIME_TOLERANCE_SECONDS = 2.0


def _affaires_path_suffix(path_value: str | Path) -> str:
    raw = str(path_value or "").strip().replace("/", "\\").rstrip("\\")
    marker = "\\Affaires"
    lower = raw.lower()
    idx = lower.find(marker.lower())
    if idx < 0:
        return ""
    return raw[idx + len(marker):].strip("\\")


def _canonical_nas_photos_batch_path(infos: dict) -> Path | None:
    pcfixe = (infos or {}).get("pcfixe") or {}
    if not isinstance(pcfixe, dict):
        pcfixe = {}
    raw = _ui_text(pcfixe.get("fichier_photos_batch"))
    if raw:
        path = Path(raw)
        suffix = _affaires_path_suffix(path)
        if suffix:
            return Path(_NAS_AFFAIRES_SMB_ROOT) / Path(suffix)
        return path
    try:
        local_batch = _canonical_laptop_photos_dir(infos) / "photos_batch.csv"
    except Exception:
        return None
    suffix = _affaires_path_suffix(local_batch)
    if not suffix:
        return None
    return Path(_NAS_AFFAIRES_SMB_ROOT) / Path(suffix)


def _photos_batch_profile(label: str, path: Path | None) -> dict:
    profile = {
        "label": label,
        "path": str(path or ""),
        "exists": False,
        "mtime": 0.0,
        "modified": "",
        "size": "",
        "sha256": "",
        "schema_ok": False,
        "error": "",
    }
    if path is None:
        profile["error"] = "chemin non resolu"
        return profile
    try:
        if _unc_host(path) and not _unc_available(path):
            profile["error"] = f"SMB indisponible: {_unc_host(path)}"
            return profile
        if not path.is_file():
            profile["error"] = "fichier absent"
            return profile
        stat = path.stat()
        profile.update({
            "exists": True,
            "mtime": float(stat.st_mtime),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "size": str(stat.st_size),
            "sha256": _sha256_file(path),
            "schema_ok": _csv_has_coherent_photos_schema(path),
            "error": "",
        })
    except Exception as exc:
        profile["error"] = str(exc)
    return profile


def _same_path(left: Path | None, right: Path | None) -> bool:
    if left is None or right is None:
        return False
    return str(left).replace("/", "\\").rstrip("\\").casefold() == str(right).replace("/", "\\").rstrip("\\").casefold()


def _copy_photos_batch_if_needed(source: Path, target: Path, profiles: dict[str, dict]) -> bool:
    if _same_path(source, target):
        return False
    target_profile = _photos_batch_profile("target", target)
    if (
        target_profile.get("exists")
        and target_profile.get("sha256")
        and target_profile.get("sha256") == profiles["source"]["sha256"]
    ):
        return False
    _copy_file_atomic(source, target)
    return True


def _photos_batch_conflict(message: str, profiles: dict[str, dict]) -> None:
    rows = [
        {
            "emplacement": label,
            "chemin": profile.get("path", ""),
            "present": "oui" if profile.get("exists") else "non",
            "date": profile.get("modified", ""),
            "taille": profile.get("size", ""),
            "sha256": profile.get("sha256", ""),
            "schema_ok": "oui" if profile.get("schema_ok") else "non",
            "erreur": profile.get("error", ""),
        }
        for label, profile in profiles.items()
    ]
    st.session_state["photos_batch_sync_conflict"] = {
        "message": message,
        "profiles": rows,
    }
    st.warning(message + " Aucune copie automatique de photos_batch.csv.")
    for row in rows:
        st.warning(
            "photos_batch.csv {emplacement}: {chemin} | date={date} | taille={taille} | sha256={sha256} | present={present}".format(
                **row
            )
        )


def _sync_photos_batch_from_canonical(infos: dict) -> None:
    local_batch_raw = str((infos or {}).get("fichier_photos_batch") or "").strip()
    if not local_batch_raw:
        return
    local_batch = Path(local_batch_raw)
    try:
        pcfixe_batch = _canonical_laptop_photos_dir(infos) / "photos_batch.csv"
        nas_batch = _canonical_nas_photos_batch_path(infos) or _nas_photos_batch_path(infos)
        paths = {
            "pcfixe": pcfixe_batch,
            "nas": nas_batch,
            "travail": local_batch,
        }
        profiles = {
            label: _photos_batch_profile(label, path)
            for label, path in paths.items()
        }
        st.session_state["photos_batch_sync_profiles"] = profiles
        st.session_state.pop("photos_batch_sync_conflict", None)

        existing = {label: profile for label, profile in profiles.items() if profile.get("exists")}
        if not existing:
            st.caption("photos_batch.csv absent sur PC fixe canonique, NAS et fichier de travail.")
            return

        invalid = {label: profile for label, profile in existing.items() if not profile.get("schema_ok")}
        if invalid:
            _photos_batch_conflict("Schema photos_batch.csv incoherent.", profiles)
            return

        hashes = {profile.get("sha256") for profile in existing.values() if profile.get("sha256")}
        if len(existing) == 3 and len(hashes) == 1:
            st.caption("photos_batch.csv deja aligne sur PC fixe, NAS et fichier de travail.")
            return

        mtimes = [float(profile.get("mtime") or 0.0) for profile in existing.values()]
        if max(mtimes) - min(mtimes) <= _PHOTOS_BATCH_MTIME_TOLERANCE_SECONDS and len(hashes) > 1:
            _photos_batch_conflict("Conflit photos_batch.csv : dates proches mais hashes differents.", profiles)
            return

        newest_mtime = max(mtimes)
        newest = {
            label: profile
            for label, profile in existing.items()
            if newest_mtime - float(profile.get("mtime") or 0.0) <= _PHOTOS_BATCH_MTIME_TOLERANCE_SECONDS
        }
        newest_hashes = {profile.get("sha256") for profile in newest.values() if profile.get("sha256")}
        if len(newest_hashes) > 1:
            _photos_batch_conflict("Conflit photos_batch.csv : plusieurs sources recentes divergent.", profiles)
            return

        if "travail" in newest and (
            "pcfixe" not in newest
            or profiles["travail"].get("sha256") != profiles["pcfixe"].get("sha256")
        ):
            _photos_batch_conflict("Fichier de travail photos_batch.csv plus recent que les sources canoniques.", profiles)
            return

        if "pcfixe" in newest:
            source = paths["pcfixe"]
            source_profile = profiles["pcfixe"]
            copied_work = False
            if source and (not profiles["travail"].get("exists") or profiles["travail"].get("sha256") != source_profile.get("sha256")):
                copied_work = _copy_photos_batch_if_needed(
                    source,
                    local_batch,
                    {"source": source_profile},
                )
            st.warning("photos_batch.csv PC fixe plus recent : publication NAS en retard, non effectuee automatiquement.")
            st.caption(
                "photos_batch.csv retenu depuis le PC fixe canonique : "
                + str(source)
                + (" (copie travail mise a jour)" if copied_work else "")
            )
            return

        if "nas" in newest:
            source = paths["nas"]
            source_profile = profiles["nas"]
            copied = []
            if source is None:
                return
            if not profiles["travail"].get("exists") or profiles["travail"].get("sha256") != source_profile.get("sha256"):
                if _copy_photos_batch_if_needed(source, local_batch, {"source": source_profile}):
                    copied.append("travail")
            if not profiles["pcfixe"].get("exists") or profiles["pcfixe"].get("sha256") != source_profile.get("sha256"):
                if _copy_photos_batch_if_needed(source, pcfixe_batch, {"source": source_profile}):
                    copied.append("PC fixe")
            st.caption(
                f"photos_batch.csv retenu depuis le NAS : {source}"
                + (f" ; copie vers {', '.join(copied)}" if copied else "")
            )
            return

        if profiles["travail"].get("exists"):
            st.caption(f"photos_batch.csv retenu depuis le fichier de travail : {local_batch}")
    except Exception as exc:
        st.warning(f"Synchronisation locale photos_batch.csv impossible : {exc}")


def _server_affaires_suffix(path_value: str) -> str:
    raw = str(path_value or "").strip().replace("/", "\\")
    prefix = _PCFIXE_LOCAL_AFFAIRES_ROOT.lower()
    if raw.lower() == prefix:
        return ""
    if raw.lower().startswith(prefix + "\\"):
        return raw[len(_PCFIXE_LOCAL_AFFAIRES_ROOT) :].strip("\\")
    raise RuntimeError(f"Chemin hors C:\\Affaires: {path_value}")


def _smb_path_for_server_path(smb_root: str, server_path: str) -> Path:
    suffix = _server_affaires_suffix(server_path)
    return Path(str(smb_root).rstrip("\\/")) / Path(suffix)


def _first_available_pcfixe_smb_root(pcfixe: dict) -> str:
    for root in _pcfixe_smb_roots_from_infos(pcfixe):
        try:
            if Path(root).exists():
                return root
        except Exception:
            continue
    return ""


def _expected_csv_read_candidates(record: dict) -> list[Path]:
    expected = str(record.get("expected_csv") or "").strip()
    candidates: list[Path] = []
    if expected:
        roots = []
        submitted_root = str(record.get("submitted_smb_root") or "").strip()
        if submitted_root:
            roots.append(submitted_root)
        for root in _PCFIXE_AFFAIRES_SMB_ROOTS:
            if root.lower() not in {r.lower() for r in roots}:
                roots.append(root)
        for root in roots:
            try:
                candidates.append(_smb_path_for_server_path(root, expected))
            except Exception:
                pass
        candidates.append(Path(expected))
        try:
            candidates.append(_smb_path_for_server_path(_NAS_AFFAIRES_SMB_ROOT, expected))
        except Exception:
            pass
    return candidates


def _persist_local_dictation(
    *,
    audio_bytes: bytes,
    audio_diag: dict,
    row,
    ui_index: int,
    infos: dict,
    pcfixe: dict,
    model_key: str,
) -> dict:
    started = time.perf_counter()
    id_affaire, id_captation, _ = extract_affaire_captation(pcfixe)
    photo_rel_native = _ui_text(row.get("photo_rel_native"))
    nom_fichier_image = _ui_text(row.get("nom_fichier_image"))
    photo_key = _photo_stable_key(row, ui_index)
    dictation_id = "dictee_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    wav_name = f"{dictation_id}.wav"
    server_audio_path = _server_affaires_path(
        id_affaire,
        "AF_Expert_ASR",
        "transcriptions",
        id_captation,
        "asr_in",
        wav_name,
    )
    local_wav_path = Path(server_audio_path)
    local_wav_path.parent.mkdir(parents=True, exist_ok=True)
    local_wav_path.write_bytes(audio_bytes)

    server_out_dir = _server_affaires_path(
        id_affaire,
        "AF_Expert_ASR",
        "transcriptions",
        id_captation,
        "asr_out",
    )
    expected_csv, photo_csv = _dictation_csv_candidates(server_audio_path, server_out_dir)
    record = {
        "schema_version": _DICTEE_SCHEMA_VERSION,
        "dictation_id": dictation_id,
        "created_at": _now_iso(),
        "id_affaire": id_affaire,
        "id_captation": id_captation,
        "photo_key": photo_key,
        "photo_rel_native": photo_rel_native,
        "nom_fichier_image": nom_fichier_image,
        "ui_index": int(ui_index),
        "local_wav_path": str(local_wav_path),
        "duration_s": float(audio_diag.get("duration_s") or 0.0),
        "status": "LOCAL_PENDING",
        "server_audio_path": server_audio_path,
        "expected_csv": str(expected_csv),
        "expected_photo_csv": str(photo_csv),
        "spooler_job_id": dictation_id,
        "submitted_at": "",
        "completed_at": "",
        "error": "",
        "model_key": model_key,
        "audio_sha256": hashlib.sha256(audio_bytes).hexdigest(),
        "audio_size": len(audio_bytes),
    }
    _save_dictation_record(record)
    print(f"[DICTEE] persisted_local id={dictation_id} wav={local_wav_path}")
    _perf_log("dictee_persist_local", started)
    return record


def _mark_current_dictation_error(
    photos_df: pd.DataFrame,
    photos_csv: str,
    infos: dict,
    ui_index: int,
    exc: Exception,
) -> None:
    err_text = str(exc)
    photos_df.at[ui_index, "dictee_asr_status"] = (
        "ERR_SILENT_AUDIO" if "silencieux ou inexploitable" in err_text else "ERR"
    )
    photos_df.at[ui_index, "dictee_asr_error"] = err_text
    photos_df.at[ui_index, "dictee_asr_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _persist_photos_csv(
        photos_df,
        photos_csv,
        infos,
        reason="dictation_error",
        photo_rel_native=_photo_rel_at(photos_df, ui_index),
    )


def _persist_current_micro_dictation(
    *,
    audio_in,
    row,
    ui_index: int,
    infos: dict,
    photos_df: pd.DataFrame,
    photos_csv: str,
    mic_nonce_key: str,
    saved_audio_sha_key: str,
    submit_to_pcfixe: bool = True,
) -> tuple[dict | None, bool, str]:
    if audio_in is None:
        return None, False, "absent"

    audio_bytes = audio_in.getvalue()
    audio_sha = hashlib.sha256(audio_bytes).hexdigest()
    if st.session_state.get(saved_audio_sha_key) == audio_sha:
        return None, False, "already_saved"

    audio_diag = _analyze_audio_bytes(audio_bytes)
    log.info(
        "[ASR][DICTEE] sr=%sHz channels=%s frames=%s duration=%.3fs rms=%.8f peak=%.8f silent=%s",
        audio_diag["sample_rate"],
        audio_diag["channels"],
        audio_diag["frames"],
        audio_diag["duration_s"],
        audio_diag["rms"],
        audio_diag["peak"],
        audio_diag["is_effectively_silent"],
    )
    if audio_diag["is_effectively_silent"]:
        raise RuntimeError(
            "Audio dicté silencieux ou inexploitable. Vérifiez le micro, le niveau d'entrée et réessayez."
        )
    if float(audio_diag.get("duration_s") or 0.0) < 0.5:
        raise RuntimeError("Audio dicte trop court (< 0,5 s).")

    _, pcfixe = _require_server_project_context(infos)
    if submit_to_pcfixe:
        appcfg = _load_dictation_spooler_config(infos)
        model_key = str(appcfg.get("dictation_asr_model") or _resolve_local_asr_model_key(appcfg)).strip()
    else:
        model_key = "Voxtral_Mini_3B_Transformers"
    record = _persist_local_dictation(
        audio_bytes=audio_bytes,
        audio_diag=audio_diag,
        row=row,
        ui_index=ui_index,
        infos=infos,
        pcfixe=pcfixe,
        model_key=model_key,
    )
    submitted = _submit_dictation_to_pcfixe(record, pcfixe) if submit_to_pcfixe else False
    existing_dictee_text = _ui_text(photos_df.at[ui_index, "dictee_asr_text"])
    photos_df.at[ui_index, "dictee_audio_path_pcfixe"] = record.get("server_audio_path", "")
    photos_df.at[ui_index, "dictee_asr_status"] = (
        "OK" if existing_dictee_text else ("SUBMITTED" if submitted else "LOCAL_PENDING")
    )
    photos_df.at[ui_index, "dictee_asr_error"] = ""
    photos_df.at[ui_index, "dictee_asr_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    photos_df.at[ui_index, "dictee_asr_csv_path_pcfixe"] = record.get("expected_csv", "")
    photos_df.at[ui_index, "dictee_asr_photo_csv_path_pcfixe"] = record.get("expected_photo_csv", "")
    _persist_photos_csv(
        photos_df,
        photos_csv,
        infos,
        reason="dictation_persisted",
        photo_rel_native=_ui_text(record.get("photo_rel_native")),
    )
    st.session_state[saved_audio_sha_key] = audio_sha
    st.session_state[mic_nonce_key] = int(st.session_state.get(mic_nonce_key, 0)) + 1
    return record, submitted, "persisted"


def _build_spooler_job(record: dict) -> dict:
    base_trans_dir = _server_affaires_path(
        record.get("id_affaire", ""),
        "AF_Expert_ASR",
        "transcriptions",
        record.get("id_captation", ""),
    )
    return {
        "job_id": record["spooler_job_id"],
        "type": "asr_voxtral",
        "dictation_id": record["dictation_id"],
        "photo_rel_native": record["photo_rel_native"],
        "nom_fichier_image": record.get("nom_fichier_image", ""),
        "affaire": record["id_affaire"],
        "captation": record["id_captation"],
        "audio_path": record["server_audio_path"],
        "output_dir": _server_affaires_path(
            record.get("id_affaire", ""),
            "AF_Expert_ASR",
            "transcriptions",
            record.get("id_captation", ""),
            "asr_out",
        ),
        "proper_names": str(Path(base_trans_dir) / "proper_names.txt"),
        "expected_csv": record["expected_csv"],
        "model_key": record.get("model_key") or "Voxtral_Mini_3B_Transformers",
        "diarize": False,
    }


def _submit_dictation_to_pcfixe(record: dict, pcfixe: dict) -> bool:
    started = time.perf_counter()
    root = _first_available_pcfixe_smb_root(pcfixe)
    if not root:
        record["status"] = "LOCAL_PENDING"
        record["error"] = "PC fixe SMB indisponible"
        _save_dictation_record(record)
        print(f"[DICTEE] pcfixe_unavailable id={record.get('dictation_id')}")
        _perf_log("dictee_submit_pcfixe", started)
        return False

    try:
        local_wav = Path(str(record.get("local_wav_path") or ""))
        if not local_wav.exists():
            raise RuntimeError(f"WAV local introuvable: {local_wav}")

        wav_dest = _smb_path_for_server_path(root, record["server_audio_path"])
        wav_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(local_wav), str(wav_dest))
        if not wav_dest.exists() or wav_dest.stat().st_size != local_wav.stat().st_size:
            raise RuntimeError(f"Verification copie WAV echouee: {wav_dest}")
        print(f"[DICTEE] wav_copied id={record.get('dictation_id')} dest={wav_dest}")

        job = _build_spooler_job(record)
        queued_dir = Path(str(root).rstrip("\\/")) / "_jobs" / "queued"
        queued_dir.mkdir(parents=True, exist_ok=True)
        final_job = queued_dir / f"{record['spooler_job_id']}.json"
        tmp_job = queued_dir / f"{record['spooler_job_id']}.json.tmp"
        tmp_job.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp_job), str(final_job))

        record["status"] = "SUBMITTED"
        record["submitted_at"] = _now_iso()
        record["submitted_smb_root"] = root
        record["error"] = ""
        _save_dictation_record(record)
        print(f"[DICTEE] job_submitted id={record.get('dictation_id')} job={final_job}")
        _perf_log("dictee_submit_pcfixe", started)
        return True
    except Exception as exc:
        record["status"] = "LOCAL_PENDING"
        record["error"] = str(exc)
        _save_dictation_record(record)
        print(f"[DICTEE] pcfixe_unavailable id={record.get('dictation_id')} error={exc}")
        _perf_log("dictee_submit_pcfixe", started)
        return False


def _append_dictee_text_to_photo(
    *,
    photos_df: pd.DataFrame,
    photos_csv: str,
    infos: dict,
    record: dict,
    text: str,
    expected_ui_index: int | None = None,
) -> bool:
    photo_rel = _ui_text(record.get("photo_rel_native"))
    nom = _ui_text(record.get("nom_fichier_image"))
    target_idx = None
    if expected_ui_index is not None:
        try:
            candidate_idx = int(expected_ui_index)
        except Exception:
            candidate_idx = -1
        if 0 <= candidate_idx < len(photos_df):
            target_idx = candidate_idx
            mapping_ok, mapping_error = _record_matches_photo(record, photos_df.iloc[target_idx], row_index=target_idx)
            if not mapping_ok:
                record["error"] = mapping_error
                _save_dictation_record(record)
                return False
    else:
        if photo_rel and "photo_rel_native" in photos_df.columns:
            matches = photos_df.index[photos_df["photo_rel_native"].astype(str).str.strip() == photo_rel].tolist()
            if matches:
                target_idx = matches[0]
        if target_idx is None and nom and "nom_fichier_image" in photos_df.columns:
            matches = photos_df.index[photos_df["nom_fichier_image"].astype(str).str.strip() == nom].tolist()
            if matches:
                target_idx = matches[0]
    if target_idx is None:
        record["error"] = f"Photo introuvable pour photo_rel_native={photo_rel!r} nom={nom!r}"
        _save_dictation_record(record)
        return False

    previous = _ui_text(photos_df.at[target_idx, "dictee_asr_text"] if "dictee_asr_text" in photos_df.columns else "")
    aggregated = previous + ("\n\n" if previous else "") + text.strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    photos_df.at[target_idx, "dictee_asr_text"] = aggregated
    photos_df.at[target_idx, "dictee_asr_status"] = "OK"
    photos_df.at[target_idx, "dictee_asr_ts"] = now
    photos_df.at[target_idx, "dictee_asr_error"] = ""
    photos_df.at[target_idx, "dictee_audio_path_pcfixe"] = record.get("server_audio_path", "")
    photos_df.at[target_idx, "dictee_asr_csv_path_pcfixe"] = record.get("expected_csv", "")
    photos_df.at[target_idx, "dictee_asr_photo_csv_path_pcfixe"] = record.get("expected_photo_csv", "")
    _persist_photos_csv(
        photos_df,
        photos_csv,
        infos,
        reason="dictation_asr_completed",
        photo_rel_native=photo_rel,
    )
    st.session_state[f"dictee_{int(target_idx)}"] = aggregated
    return True


def _submit_local_pending_dictees(infos: dict) -> tuple[int, int]:
    _, pcfixe = _require_server_project_context(infos)
    submitted = 0
    remaining = 0
    for _, record in _iter_dictation_records("LOCAL_PENDING"):
        if _submit_dictation_to_pcfixe(record, pcfixe):
            submitted += 1
        else:
            remaining += 1
    return submitted, remaining


def _refresh_submitted_local_dictees(
    *,
    photos_df: pd.DataFrame,
    photos_csv: str,
    infos: dict,
    apply: bool = False,
    return_plan: bool = False,
) -> tuple[int, int] | tuple[int, int, dict[str, object]]:
    plan = _build_dictation_reconciliation_plan(photos_df, infos=infos)
    still_pending = int(plan.get("summary", {}).get("still_pending", 0))
    if not apply:
        st.session_state["dictee_reconciliation_plan"] = plan
        summary = plan.get("summary", {}) if isinstance(plan, dict) else {}
        st.info(
            "Previsualisation ASR uniquement : "
            f"{int(summary.get('would_update') or 0)} ligne(s) seraient propagee(s), "
            f"{still_pending} restent en attente. Aucune modification de photos.csv n'a ete ecrite."
        )
        if return_plan:
            return 0, still_pending, plan
        return 0, still_pending
    completed = _apply_dictation_reconciliation_plan(
        photos_df,
        photos_csv=photos_csv,
        infos=infos,
        plan=plan,
    )
    if completed:
        for item in plan.get("rows", []):
            if isinstance(item, dict) and item.get("action") == "update":
                record = _load_dictation_record(_dictation_json_path(_ui_text(item.get("dictation_id"))))
                if record:
                    record["status"] = "COMPLETED"
                    record["completed_at"] = _now_iso()
                    record["error"] = ""
                    _save_dictation_record(record)
    st.session_state["dictee_reconciliation_plan"] = plan
    if return_plan:
        return completed, still_pending, plan
    return completed, still_pending


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

log = logging.getLogger("dictée_asr")

def _check_under(path_str: str, root_abs: str, label: str):
    try:
        p = Path(path_str).resolve()
        root = Path(root_abs).resolve()
        ok = p.is_relative_to(root)
    except Exception:
        ok = False
    if not ok:
        msg = f"[ASR][WARN] {label} hors dossier attendu: {p} (attendu sous {root})"
        log.warning(msg)
        st.warning(msg)
    else:
        log.info(f"[ASR][OK] {label}: {p}")


def _require_server_project_context(infos: dict) -> tuple[str, dict]:
    """Valide le minimum requis cote client avant un appel serveur structurel."""
    project_id = str(infos.get("project_id") or infos.get("id_projet") or "").strip()
    if not project_id:
        raise RuntimeError(
            "project_id absent dans infos_projet.json : appel serveur impossible. "
            "Renseignez un identifiant de projet serveur valide dans l'etat local."
        )

    pcfixe = infos.get("pcfixe", {}) or {}
    if not isinstance(pcfixe, dict) or not pcfixe:
        raise RuntimeError(
            "Bloc pcfixe absent dans infos_projet.json : impossible de calculer les chemins serveur attendus."
        )

    return project_id, pcfixe



@st.cache_resource
def charger_prompts():
    """Charge les prompts système / utilisateur stockés dans config/prompt_gpt.json."""
    with open("config/prompt_gpt.json", "r", encoding="utf-8") as f:
        return json.load(f)
    

def extract_affaire_captation(pcfixe: dict) -> tuple[str, str, str]:
    r"""
    Retourne (id_affaire, id_captation, base_transcriptions_dir)
    base_transcriptions_dir = ...\AF_Expert_ASR\transcriptions\<id_captation>
    """
    if not isinstance(pcfixe, dict) or not pcfixe:
        raise RuntimeError("Bloc pcfixe manquant : impossible d'extraire id_affaire/id_captation.")

    candidates = [
        pcfixe.get("fichier_contexte_general", ""),
        pcfixe.get("config_llm", ""),
        pcfixe.get("fichier_transcription", ""),
    ]
    p = next((c for c in candidates if c and os.path.isabs(c)), "")
    if not p:
        raise RuntimeError("Impossible d'extraire id_affaire/id_captation : chemins pcfixe absents.")

    # Normalisation
    p = str(Path(p))
    # 1) id_affaire : segment après \Affaires\
    m_aff = re.search(r"[\\/](Affaires)[\\/](?P<id>[^\\/]+)[\\/]", p, flags=re.IGNORECASE)
    if not m_aff:
        raise RuntimeError(f"id_affaire introuvable dans le chemin: {p}")
    id_affaire = m_aff.group("id")

    # 2) id_captation : segment après \transcriptions\
    m_cap = re.search(r"[\\/](transcriptions)[\\/](?P<cap>[^\\/]+)[\\/]", p, flags=re.IGNORECASE)
    if not m_cap:
        raise RuntimeError(f"id_captation introuvable (segment 'transcriptions') dans le chemin: {p}")
    id_captation = m_cap.group("cap")

    pp = Path(p)
    try:
        i = next(i for i, x in enumerate(pp.parts) if x.lower() == "transcriptions")
    except StopIteration:
        raise RuntimeError(f"Segment 'transcriptions' introuvable dans le chemin: {p}")

    if i + 1 >= len(pp.parts):
        raise RuntimeError(f"id_captation introuvable après 'transcriptions' dans {p}")

    base_transcriptions_dir = Path(*pp.parts[: i + 2]).resolve()

    expected = re.compile(rf"[\\/](transcriptions)[\\/]{re.escape(id_captation)}$", re.I)
    if not expected.search(str(base_transcriptions_dir)):
        raise RuntimeError(
            "Chemin pcfixe incoherent : impossible de confirmer le dossier "
            f"transcriptions/{id_captation} a partir de {p}"
        )

    return id_affaire, id_captation, str(base_transcriptions_dir)

def compute_dictee_target_dir(pcfixe: dict) -> str:
    id_affaire, id_captation, base_trans_dir = extract_affaire_captation(pcfixe)
    target = str(Path(base_trans_dir) / "asr_in")
    return target

def compute_asr_subdir_from_pcfixe(pcfixe: dict) -> str:
    id_affaire, id_captation, _ = extract_affaire_captation(pcfixe)
    subdir = str(
        Path(id_affaire)
        / "AF_Expert_ASR"
        / "transcriptions"
        / id_captation
    )
    if not id_affaire or not id_captation or subdir in ("", "."):
        raise RuntimeError("Impossible de calculer le sous-repertoire ASR serveur.")
    return subdir

def compute_asr_out_dir_from_pcfixe(pcfixe: dict) -> str:
    _, _, base_transcriptions_dir = extract_affaire_captation(pcfixe)
    out_dir = str(Path(base_transcriptions_dir) / "asr_out")
    if not os.path.isabs(out_dir):
        raise RuntimeError("Impossible de calculer le dossier absolu de sortie ASR.")
    return out_dir


def _preferred_transcription_csv(csv_path: str) -> Path:
    p = Path(str(csv_path or "").strip())
    if not p:
        return p
    if "(photo)" in p.name:
        alt = p.with_name(p.name.replace("(photo)", ""))
        if alt.exists():
            return alt
    return p


def _dictation_csv_candidates(audio_path_server: str, out_dir_abs: str) -> tuple[Path, Path]:
    audio_name = Path(str(audio_path_server or "").strip()).name
    if not audio_name:
        return Path(""), Path("")

    out_dir = Path(out_dir_abs)
    stem = Path(audio_name).stem
    suffix = Path(audio_name).suffix.lstrip(".")

    raw_candidates = [
        out_dir / f"{audio_name}.csv",
        out_dir / f"{stem}({suffix}).csv" if suffix else out_dir / f"{stem}.csv",
        out_dir / f"{stem}.csv",
    ]
    photo_candidates = [
        out_dir / f"{audio_name}(photo).csv",
        out_dir / f"{stem}({suffix})(photo).csv" if suffix else out_dir / f"{stem}(photo).csv",
        out_dir / f"{stem}(photo).csv",
    ]

    raw_csv = next((p for p in raw_candidates if p.exists()), raw_candidates[1])
    photo_csv = next((p for p in photo_candidates if p.exists()), photo_candidates[1])
    return raw_csv, photo_csv


def _read_dictee_text_from_csv(csv_path: str) -> str:
    p = _preferred_transcription_csv(csv_path)
    if not p or not p.exists():
        return ""
    try:
        df = read_csv_fallback(str(p), sep=";")
    except Exception:
        return ""
    if df is None or df.empty:
        return ""
    text_col = next((col for col in ("text", "texte", "dictee_asr_text") if col in df.columns), "")
    if not text_col:
        return ""
    parts = [str(v).strip() for v in df[text_col].tolist() if str(v or "").strip() and str(v).strip().lower() != "nan"]
    return "\n".join(parts).strip()


def _dictation_id_from_path(path_value: str | Path) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    name = Path(raw).name
    if "(wav)" in name:
        return name.split("(wav)", 1)[0]
    if name.lower().endswith(".wav"):
        return Path(name).stem
    if name.lower().endswith(".csv"):
        return Path(name).stem
    return Path(name).stem


def _record_matches_photo(record: dict, row, *, row_index: int) -> tuple[bool, str]:
    if not isinstance(record, dict) or not record:
        return True, ""
    row_rel = _ui_text(row.get("photo_rel_native"))
    row_name = _ui_text(row.get("nom_fichier_image"))
    rec_rel = _ui_text(record.get("photo_rel_native"))
    rec_name = _ui_text(record.get("nom_fichier_image"))
    if rec_rel and row_rel and rec_rel != row_rel:
        return False, f"mapping photo invalide: record photo_rel_native={rec_rel!r}, ligne={row_rel!r}"
    if rec_name and row_name and rec_name != row_name:
        return False, f"mapping photo invalide: record nom_fichier_image={rec_name!r}, ligne={row_name!r}"
    if not (rec_rel or rec_name):
        return False, f"photo cible inconnue dans le registre pour la ligne {row_index}"
    return True, ""


def _dictation_records_by_id() -> dict[str, dict]:
    return {
        str(record.get("dictation_id") or ""): record
        for _, record in _iter_dictation_records()
        if str(record.get("dictation_id") or "")
    }


def _find_concurrent_dictation_results(
    *,
    dictation_id: str,
    row,
    records_by_id: dict[str, dict],
) -> list[dict[str, str]]:
    row_rel = _ui_text(row.get("photo_rel_native"))
    row_name = _ui_text(row.get("nom_fichier_image"))
    out: list[dict[str, str]] = []
    for other_id, record in records_by_id.items():
        if not other_id or other_id == dictation_id:
            continue
        rec_rel = _ui_text(record.get("photo_rel_native"))
        rec_name = _ui_text(record.get("nom_fichier_image"))
        if not ((row_rel and rec_rel == row_rel) or (row_name and rec_name == row_name)):
            continue
        csv_path = Path(_ui_text(record.get("expected_csv")))
        photo_csv_path = Path(_ui_text(record.get("expected_photo_csv")))
        if csv_path.exists() or photo_csv_path.exists():
            out.append({
                "dictation_id": other_id,
                "csv_path": str(csv_path if csv_path.exists() else ""),
                "photo_csv_path": str(photo_csv_path if photo_csv_path.exists() else ""),
                "status": _ui_text(record.get("status")),
            })
    return out


def _build_dictation_reconciliation_plan(
    photos_df: pd.DataFrame,
    *,
    infos: dict,
    records_by_id: dict[str, dict] | None = None,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    summary = {
        "would_update": 0,
        "still_pending": 0,
        "duplicates": 0,
        "orphans": 0,
        "conflicts": 0,
        "invalid_mappings": 0,
    }
    if "dictee_asr_status" not in photos_df.columns:
        return {"summary": summary, "rows": rows}
    try:
        _, pcfixe = _require_server_project_context(infos)
        out_dir_abs = compute_asr_out_dir_from_pcfixe(pcfixe)
    except Exception as exc:
        return {"summary": {**summary, "error": str(exc)}, "rows": rows}

    records_by_id = records_by_id if records_by_id is not None else _dictation_records_by_id()
    for idx in range(len(photos_df)):
        row = photos_df.iloc[idx]
        status = _ui_text(row.get("dictee_asr_status")).upper()
        if status not in {"SUBMITTED", "LOCAL_PENDING", "PENDING", "TODO", "BUSY"}:
            continue
        audio_path = _ui_text(row.get("dictee_audio_path_pcfixe"))
        if not audio_path:
            continue
        dictation_id = _dictation_id_from_path(audio_path)
        csv_path = _ui_text(row.get("dictee_asr_csv_path_pcfixe"))
        photo_csv_path = _ui_text(row.get("dictee_asr_photo_csv_path_pcfixe"))
        raw_candidate, photo_candidate = _dictation_csv_candidates(audio_path, out_dir_abs)
        if not csv_path:
            csv_path = str(raw_candidate)
        if not photo_csv_path:
            photo_csv_path = str(photo_candidate)
        raw_csv = Path(csv_path)
        photo_csv = Path(photo_csv_path)
        text = _read_dictee_text_from_csv(str(raw_csv)) or _read_dictee_text_from_csv(str(photo_csv))
        record = records_by_id.get(dictation_id, {})
        mapping_ok, mapping_error = _record_matches_photo(record, row, row_index=idx)
        concurrent = _find_concurrent_dictation_results(
            dictation_id=dictation_id,
            row=row,
            records_by_id=records_by_id,
        )
        action = "unchanged"
        reason = ""
        if not text:
            summary["still_pending"] += 1
            reason = "aucun résultat ASR exact pour le WAV référencé"
        elif not photo_csv.exists():
            summary["conflicts"] += 1
            reason = "CSV (photo) absent pour le WAV référencé"
        elif not mapping_ok:
            summary["invalid_mappings"] += 1
            reason = mapping_error
        elif status == "LOCAL_PENDING":
            summary["conflicts"] += 1
            reason = "LOCAL_PENDING conservé : résultat exact présent mais validation explicite requise"
        else:
            action = "update"
            summary["would_update"] += 1
            reason = "résultat exact prêt à propager"
        if concurrent:
            summary["duplicates"] += len(concurrent)
            if action != "update":
                reason = (reason + " ; " if reason else "") + f"{len(concurrent)} résultat(s) concurrent(s)"
        rows.append({
            "index": idx,
            "nom_fichier_image": _ui_text(row.get("nom_fichier_image")),
            "photo_rel_native": _ui_text(row.get("photo_rel_native")),
            "dictation_id": dictation_id,
            "status": status,
            "action": action,
            "reason": reason,
            "text": text,
            "text_preview": text[:160],
            "csv_path": str(raw_csv),
            "photo_csv_path": str(photo_csv),
            "photo_csv_exists": photo_csv.exists(),
            "audio_path": audio_path,
            "audio_sha256": _ui_text(row.get("dictee_audio_sha256")),
            "concurrent_results": concurrent,
        })
    return {"summary": summary, "rows": rows}


def _apply_dictation_reconciliation_plan(
    photos_df: pd.DataFrame,
    *,
    photos_csv: str,
    infos: dict,
    plan: dict[str, object],
) -> int:
    changed = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for item in plan.get("rows", []):
        if not isinstance(item, dict) or item.get("action") != "update":
            continue
        idx = int(item["index"])
        text = _ui_text(item.get("text"))
        if not text:
            continue
        photos_df.at[idx, "dictee_asr_text"] = text
        photos_df.at[idx, "dictee_asr_status"] = "OK"
        photos_df.at[idx, "dictee_asr_ts"] = now
        photos_df.at[idx, "dictee_asr_error"] = ""
        photos_df.at[idx, "dictee_audio_path_pcfixe"] = _ui_text(item.get("audio_path"))
        photos_df.at[idx, "dictee_asr_csv_path_pcfixe"] = _ui_text(item.get("csv_path"))
        photos_df.at[idx, "dictee_asr_photo_csv_path_pcfixe"] = _ui_text(item.get("photo_csv_path"))
        if _ui_text(item.get("audio_sha256")):
            photos_df.at[idx, "dictee_audio_sha256"] = _ui_text(item.get("audio_sha256"))
        st.session_state[f"dictee_{idx}"] = text
        changed += 1
    if changed:
        _persist_photos_csv(
            photos_df,
            photos_csv,
            infos,
            reason="dictation_asr_reconciliation",
            maintain_xlsx=False,
            create_backup=True,
        )
    return changed


def _is_asr_busy_error(exc: Exception) -> bool:
    msg = str(exc or "")
    return "HTTP 409" in msg and "ASR Voxtral" in msg


def _refresh_pending_dictee(
    i: int,
    row,
    *,
    photos_df: pd.DataFrame,
    photos_csv: str,
    infos: dict,
) -> tuple[str, str, str, str]:
    status = _ui_text(row.get("dictee_asr_status"))
    audio_path = _ui_text(row.get("dictee_audio_path_pcfixe"))
    text = _ui_text(row.get("dictee_asr_text"))
    csv_path = _ui_text(row.get("dictee_asr_csv_path_pcfixe"))
    photo_csv_path = _ui_text(row.get("dictee_asr_photo_csv_path_pcfixe"))

    if not _is_dictee_pending(status) or not audio_path:
        return status, text, csv_path, photo_csv_path

    try:
        _, pcfixe = _require_server_project_context(infos)
        out_dir_abs = compute_asr_out_dir_from_pcfixe(pcfixe)
    except Exception:
        return status, text, csv_path, photo_csv_path

    if not csv_path or not photo_csv_path:
        raw_csv, photo_csv = _dictation_csv_candidates(audio_path, out_dir_abs)
        csv_path = str(raw_csv) if raw_csv else csv_path
        photo_csv_path = str(photo_csv) if photo_csv else photo_csv_path

    reloaded_text = _read_dictee_text_from_csv(csv_path or photo_csv_path)
    if reloaded_text:
        st.session_state.setdefault("dictee_reconciliation_preview_required", True)
    elif (csv_path and Path(csv_path).exists()) or (photo_csv_path and Path(photo_csv_path).exists()):
        st.session_state.setdefault("dictee_reconciliation_preview_required", True)
    return status, text, csv_path, photo_csv_path


def _is_dictee_pending(value) -> bool:
    return _ui_text(value).upper() in {"PENDING", "TODO", "BUSY", "LOCAL_PENDING", "SUBMITTED"}


def _refresh_all_pending_dictees(
    photos_df: pd.DataFrame,
    *,
    photos_csv: str,
    infos: dict,
) -> None:
    if "dictee_asr_status" not in photos_df.columns:
        return
    pending_indices = [
        idx
        for idx in range(len(photos_df))
        if _is_dictee_pending(photos_df.iloc[idx].get("dictee_asr_status"))
    ]
    for idx in pending_indices:
        _refresh_pending_dictee(
            idx,
            photos_df.iloc[idx],
            photos_df=photos_df,
            photos_csv=photos_csv,
            infos=infos,
        )


def _next_actionable_photo_index(
    photos_df: pd.DataFrame,
    annoted_names: set[str],
    *,
    start_after: int | None = None,
) -> int | None:
    total = len(photos_df)
    if total <= 0:
        return None

    start_idx = 0 if start_after is None else max(0, int(start_after) + 1)
    for idx in range(start_idx, total):
        row = photos_df.iloc[idx]
        nom_image = str(row.get("nom_fichier_image") or "").strip()
        if nom_image in annoted_names:
            continue
        if _is_dictee_pending(row.get("dictee_asr_status")):
            continue
        return idx
    return None


def _next_non_validated_photo_index(
    photos_df: pd.DataFrame,
    annoted_names: set[str],
    *,
    start_after: int | None = None,
) -> int | None:
    total = len(photos_df)
    if total <= 0:
        return None

    start_idx = 0 if start_after is None else max(0, int(start_after) + 1)
    for idx in range(start_idx, total):
        row = photos_df.iloc[idx]
        nom_image = str(row.get("nom_fichier_image") or "").strip()
        if nom_image in annoted_names:
            continue
        return idx
    return None


# -----------------------------------------------------------------------------
    
def _strip_wrapping_quotes(s: str) -> str:
    if not isinstance(s, str):
        return s
    s = s.strip()
    pairs = [('“','”'), ('"','"'), ("'", "'"), ("«","»")]
    changed = True
    while changed and len(s) >= 2:
        changed = False
        for L, R in pairs:
            if s.startswith(L) and s.endswith(R):
                s = s[len(L):-len(R)].strip()
                changed = True
                break
    return s

def _strip_prefixes(text: str, prefixes=("libellé", "libelle", "label", "titre", "title", "commentaire", "comment", "note")) -> str:
    if not isinstance(text, str):
        return text
    s = _strip_wrapping_quotes(text).strip()
    pat = r'^\s*(?:' + '|'.join(prefixes) + r')\s*[:：-]\s*'
    return re.sub(pat, '', s, flags=re.IGNORECASE).strip()

def _normalize_text(text, field_type: str) -> str:
    """Nettoie le texte pour l'affichage / stockage."""
    if text is None:
        text = ""
    elif isinstance(text, float):
        text = "" if math.isnan(text) else str(text)
    elif not isinstance(text, str):
        text = str(text)

    s = _strip_wrapping_quotes(text or "").strip()

    # ✅ enlève le markdown le plus fréquent
    s = s.replace("**", "").strip()

    if field_type == "libelle":
        s = _strip_prefixes(s, ("libellé", "libelle", "label", "titre", "title"))
        # ✅ le libellé doit être 1 ligne (évite préambules / multi-lignes)
        s = s.splitlines()[0].strip() if s else ""
    elif field_type == "commentaire":
        s = _strip_prefixes(s, ("commentaire", "comment", "note"))

    return s

def _post_clean_llm(raw: str, field_type: str) -> str:
    r"""
    Post-traitement des sorties LLM pour éviter le 'caviardage' (préambules, rôles, markdown, etc.)
    et produire un texte directement exploitable dans l'UI et en batch.
    """
    if raw is None:
        return ""

    s = str(raw).strip()

    # 1) Retirer fences markdown éventuels
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()

    # 2) Enlever les marqueurs de rôle / bavardage typiques
    # (on reste volontairement simple et robuste)
    s = re.sub(r"^\s*(assistant|réponse|sortie)\s*[:：-]\s*", "", s, flags=re.IGNORECASE)

    # 3) Si le modèle renvoie des sections, garder la partie la plus pertinente
    #    - On privilégie un bloc après "Libellé:" / "Commentaire:" si présent
    if field_type == "libelle":
        m = re.search(r"(libellé|libelle|titre|label)\s*[:：-]\s*(.+)", s, flags=re.IGNORECASE | re.DOTALL)
        if m:
            s = m.group(2).strip()
    elif field_type == "commentaire":
        m = re.search(r"(commentaire|note)\s*[:：-]\s*(.+)", s, flags=re.IGNORECASE | re.DOTALL)
        if m:
            s = m.group(2).strip()

    # 4) Couper à l’apparition d’un “méta-discours” fréquent
    CUT = [
        r"\n\s*remarque[s]?\s*[:：-]",
        r"\n\s*explication[s]?\s*[:：-]",
        r"\n\s*analyse\s*[:：-]",
        r"\n\s*je vais\s",
        r"\n\s*voici\s",
        r"\n\s*bien sûr",
    ]
    for pat in CUT:
        s2 = re.split(pat, s, flags=re.IGNORECASE)
        if s2 and len(s2[0].strip()) >= 3:
            s = s2[0].strip()

    # 5) Normalisation finale (déjà en place dans votre fichier)
    s = _normalize_text(s, field_type)

    # 6) Garde-fous longueur
    if field_type == "libelle":
        # 1 ligne max
        s = s.splitlines()[0].strip() if s else ""
        # éviter les retours trop courts/vides
        if len(s) < 3:
            return ""
        return s[:200].strip()
    else:
        # commentaire : limiter sans casser l'UI
        s = s.strip()
        if len(s) < 5:
            return ""
        return s[:2000].strip()


def _hms_signed(sec: float) -> str:
    try:
        s = float(sec)
    except Exception:
        return "?"
    sign = "-" if s < 0 else ""
    s = abs(s)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    ss = int(s % 60)
    return f"{sign}{h}:{m:02d}:{ss:02d}"

def _parse_photo_dt(raw, default_date=None):
    """Accepte: 'JJ/MM/AAAA HH:MM[:SS]' ; 'YYYY-MM-DD HH:MM[:SS]' ; ou 'HH:MM[:SS]'."""
    if raw is None:
        return None

    # cas où pandas fournit déjà un Timestamp/datetime
    if isinstance(raw, (datetime, pd.Timestamp)):
        return pd.to_datetime(raw).to_pydatetime()

    s = str(raw).strip()
    if not s:
        return None

    # formats date+heure (avec ou sans secondes)
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass

    # formats heure seule (avec ou sans secondes)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(s, fmt).time()
            if default_date is None:
                default_date = datetime.strptime(
                    lire_infos_projet()["horodatage_audio"], "%Y-%m-%d %H:%M:%S"
                ).date()
            return datetime.combine(default_date, t)
        except Exception:
            pass

    return None



def read_csv_fallback(path, sep=";"):
    r"""
    Lecture CSV robuste :
    - tente utf-8-sig (recommandé pour accents + BOM),
    - puis utf-8,
    - puis latin-1 (compatibilité historique Windows).
    """
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df = pd.read_csv(path, sep=sep, encoding=enc)
            df, changed = migrate_photo_dataframe_paths(df)
            if changed:
                df.to_csv(path, sep=sep, encoding="utf-8-sig", index=False)
            return df
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Impossible de lire {path}. Dernière erreur: {last_err}")

def _parse_audio0(s: str):
    s = str(s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None

def _get_time_series(df):
    if "temps" in df.columns:
        return df["temps"]
    if {"start_sec","end_sec"}.issubset(df.columns):
        return (df["start_sec"] + df["end_sec"]) / 2.0
    return None

def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return float("nan")

def format_duree_secondes(sec: float) -> str:
    """Retourne une durée en secondes au format HH:MM:SS."""
    return str(timedelta(seconds=int(sec)))


FORBIDDEN_GUARDRAILS = """
Interdictions absolues :
- Ne pas inventer, ne pas extrapoler, ne pas expliquer les causes.
- Ne pas transformer une question/doute en affirmation.
- Ne pas employer de langage normatif/évaluatif : « règles de l’art », « conforme/non conforme », « durable », 
  « inadéquat », « anormal », « ne devrait pas », etc.
- Ne pas conclure, ne pas attribuer de responsabilité.
Style : factuel, neutre, phrases courtes.
"""
STOP_LIBELLE = ["\n", "\r\n"]
STOP_COMMENTAIRE = ["\n\n", "\r\n\r\n"]

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


SAILLANT_TERMS = [
    # fissuration
    "fissure", "fissures", "microfissure", "micro-fissure", "craquelure", "craquelures",
    "lézarde", "lézardes",

    # changements d’aspect / surface
    "changement d'aspect", "changement d’aspect", "différence d'aspect", "différence d’aspect",
    "aspect", "teinte", "décoloration", "décolorations", "tache", "taches", "traces",
    "salissure", "salissures", "auréole", "rouille", "auréoles",
    "coulure", "coulures",

    # soulèvements / cloques / décollements (souvent associés aux “aspects”)
    "cloque", "cloques", "boursouflure", "boursouflures",
    "décollement", "décollé", "décollée", "décollés", "décollées",
    "gondolement", "gonflement",

    # humidité / infiltration (souvent décrite comme “traces”, “mouillé”, etc.)
    "humidité", "humide", "mouillé", "mouillée", "infiltration", "fuite", "gouttes",
]

# --- familles lexicales (photo + transcription) orientées "fissures / aspect" ---
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
        "humidite_fuite": "présence d’humidité, gouttes ou fuite"
    }

    return "; ".join(mapping[p] for p in points if p in mapping)

def extract_salient_families(desc_vlm: str, transcription: str, max_items: int = 3) -> list[str]:
    d = (desc_vlm or "").lower()
    t = (transcription or "").lower()
    hits: list[str] = []
    for family, words in TERM_FAMILIES.items():
        if any(w in d for w in words) and any(w in t for w in words):
            hits.append(family)
    return hits[:max_items]



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



def _compose_system(task_system: str | None, context_system: str | None) -> str:
    parts = []
    if task_system:
        parts.append(task_system.strip())
    parts.append(FORBIDDEN_GUARDRAILS.strip())
    if context_system:
        parts.append(context_system.strip())
    return "\n\n".join([p for p in parts if p])

def build_payload(prompt_json: dict, kind: str, mission: str, contexte: str, transcription: str) -> dict:
    bloc = prompt_json[kind]
    system_txt = str(bloc.get("system","")).strip()
    user_tpl   = str(bloc.get("user","")).strip()
    user_txt   = (user_tpl
                  .replace("{{mission}}", mission or "")
                  .replace("{{contexte_general}}", contexte or "")
                  .replace("{{transcription}}", transcription or "")
                 ).strip()
    return {"system": system_txt, "prompt": user_txt}


def generer_texte_gpt(role_systeme: str, prompt_user: str) -> str:
    r"""
    Route vers OpenAI ou LLM local selon config/config.json.
    Affiche des messages clairs en cas de non-réponse, avec WOL si nécessaire.
    """
    if not prompt_user.strip():
        return "[Transcription vide – GPT non sollicité]"

    try:
        infos = lire_infos_projet()
        appcfg = _load_app_config(infos)
    except Exception as e:
        return f"[Erreur config LLM: {e}]"

    backend = str(appcfg.get("llm_backend", "openai")).lower()

    if backend == "local":
        local_cfg = appcfg.get("local_llm", {}) or {}
        wol_cfg   = appcfg.get("wol", {}) or {}
        busy_key  = "llm_local_request_inflight"

        base_url  = local_cfg.get("base_url") or resolve_flask_base_url()
        api_key   = local_cfg.get("api_key", "")
        model     = local_cfg.get("model")
        timeout   = float(local_cfg.get("timeout", 30))
        fallback  = bool(local_cfg.get("fallback_to_openai", False))

        mac_pcfixe    = wol_cfg.get("mac_pcfixe", "")
        broadcast_ip  = wol_cfg.get("broadcast_ip", "255.255.255.255")
        wol_port      = int(wol_cfg.get("port", 9))
        max_wait_sec  = int(wol_cfg.get("max_wait_sec", 90))
        ping_path     = wol_cfg.get("ping_path", "/ping")
        poll_interval = int(wol_cfg.get("poll_interval_sec", 3))

        if st.session_state.get(busy_key):
            return _LOCAL_LLM_BUSY_RESULT

        status = st.empty()
        try:
            st.session_state[busy_key] = True
            # (1) deux checks rapides avant WOL
            if not is_server_up(base_url, ping_path=ping_path, timeout=2.0):
                time.sleep(1.0)
            if not is_server_up(base_url, ping_path=ping_path, timeout=2.0):
                # WOL si toujours KO
                if mac_pcfixe:
                    status.info("⏳ Réveil du PC fixe (WOL)…")
                    # Option: utiliser wake_and_wait si tu l'ajoutes dans wol_util
                    wake_on_lan(mac_pcfixe, broadcast_ip=broadcast_ip, port=wol_port)
                    ok = wait_for_server(
                        base_url, ping_path=ping_path,
                        max_wait_sec=max_wait_sec, poll_interval_sec=poll_interval, timeout_single=3.0
                    )
                    if not ok:
                        status.warning("⚠️ Le serveur local ne répond pas après WOL.")
                        if fallback:
                            status.info("↪️ Bascule automatique vers OpenAI (fallback).")
                            backend = "openai"  # on tombera sur le bloc OpenAI ci-dessous
                        else:
                            return f"[LLM local injoignable après WOL – vérifie le PC fixe, le réseau et {base_url}]"
                else:
                    status.error("❌ LLM local KO et aucune MAC définie pour WOL (wol.mac_pcfixe).")
                    if fallback:
                        status.info("↪️ Bascule automatique vers OpenAI (fallback).")
                        backend = "openai"
                    else:
                        return "[LLM local KO et 'wol.mac_pcfixe' absent de config/config.json]"
            if backend == "local":

                status.info("🔌 Connexion au LLM local…")

                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["x-api-key"] = api_key.strip()

                max_tok = appcfg.get("max_tokens")
                u = (prompt_user or "").upper()
                if "TÂCHE — LIBELLÉ" in u or "LIBELLE:" in u or "LIBELLÉ:" in u:
                    max_tok = 120
                elif "TÂCHE — COMMENTAIRE" in u or "COMMENTAIRE:" in u:
                    max_tok = 470


                task = ""
                u2 = u.replace("—", "-")
                if ("TÂCHE - LIBELLÉ" in u2) or ("TÂCHE - LIBELLE" in u2) or ("TACHE - LIBELLE" in u2) or ("LIBELLE PHOTO" in u2) or ("LIBELLÉ PHOTO" in u2):
                    task = "libelle"
                elif ("TÂCHE - COMMENTAIRE" in u2) or ("TACHE - COMMENTAIRE" in u2) or ("COMMENTAIRE PHOTO" in u2):
                    task = "commentaire"

                payload = {
                    "system": role_systeme,
                    "prompt": (prompt_user or "").strip(),
                    "model_name": model,
                    "temperature": float(appcfg.get("temperature", 0.3)),
                    "max_tokens": max_tok,
                    "expect_json": True,
                    "task": task,   # ✅ ajout
                }

                for attempt in (1, 2):
                    try:
                        st.write("DEBUG LLM base_url:", base_url)
                        st.write("DEBUG api_key len:", len(api_key or ""))
                        safe_headers = dict(headers)
                        if "x-api-key" in safe_headers:
                            safe_headers["x-api-key"] = "***"
                        st.write("DEBUG headers:", safe_headers)

                        r = requests.post(
                            base_url.rstrip("/") + "/annoter",
                            json=payload,
                            headers=headers,
                            timeout=timeout,
                        )
                        r.raise_for_status()
                        j = r.json()
                        st.write("DEBUG keys:", list(j.keys()))
                        st.write("DEBUG reponse_json:", j.get("reponse_json"))
                        st.write("DEBUG reponse (raw):", (j.get("reponse") or "")[:300])

                        status.empty()

                        if j.get("ok") is False:
                            reason = (
                                j.get("error")
                                or j.get("detail")
                                or j.get("message")
                                or j.get("reponse")
                                or "Réponse rejetée par le serveur."
                            )
                            return f"[LLM local ok=False: {reason}]"

                        rj = j.get("reponse_json")
                        if isinstance(rj, dict) and "texte" in rj:
                            return str(rj.get("texte") or "").strip()

                        # fallback brut
                        rep = str(j.get("reponse") or "").strip()
                        if rep:
                            return rep

                        return "[Réponse LLM local vide ou inexploitable]"

                    except requests.HTTPError as e:
                        response = getattr(e, "response", None)
                        if getattr(response, "status_code", None) == 503:
                            status.warning("LLM local occupe : reessayez dans quelques secondes.")
                            return _LOCAL_LLM_BUSY_RESULT
                        if attempt == 2:
                            raise
                        time.sleep(1.0)
                    except Exception:
                        if attempt == 2:
                            raise
                        time.sleep(1.0)

               
        except Exception as e:
            status.error("❌ Erreur LLM local.")
            if fallback:
                status.info("↪️ Bascule automatique vers OpenAI (fallback).")
                backend = "openai"
            else:
                return f"[Erreur LLM local: {e}]"
        finally:
            st.session_state[busy_key] = False

    # ---- OpenAI (fallback possible)
    api_key = appcfg.get("openai_api_key", "")
    if not api_key:
        return "[Erreur GPT : Clé API OpenAI introuvable (env OPENAI_API_KEY ou config.openai_api_key).]"
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=appcfg.get("model", "gpt-4o-mini"),
            temperature=float(appcfg.get("temperature", 0.3)),
            max_tokens=appcfg.get("max_tokens"),
            messages=[
                {"role": "system", "content": role_systeme},
                {"role": "user", "content": prompt_user},
            ],
        )
        return _strip_wrapping_quotes(response.choices[0].message.content or "")
    except Exception as e:
        return f"[Erreur GPT OpenAI : {e}]"


def _load_app_config(infos: dict | None = None) -> dict:
    cfg_path = _CONFIG_DIR / "config.json"
    cfg = _load_json_file(cfg_path)

    project_cfg_path = _resolve_project_config_llm_path(infos)
    if project_cfg_path:
        cfg = _deep_merge_dict(cfg, _load_json_file(project_cfg_path))

    backend_from_infos = str((infos or {}).get("llm_backend") or "").strip().lower()
    if backend_from_infos in {"local", "openai"}:
        cfg["llm_backend"] = backend_from_infos

    cfg["local_llm"] = _resolve_local_llm_settings(cfg)
    cfg["openai_api_key"] = _resolve_openai_api_key(cfg)
    return cfg


def _persist_llm_backend(infos: dict, backend: str) -> tuple[bool, str]:
    backend = str(backend or "").strip().lower()
    if backend not in {"local", "openai"}:
        return False, ""

    infos["llm_backend"] = backend
    config_path = _resolve_project_config_llm_path(infos)
    if not config_path:
        return False, ""

    cfg = _load_json_file(config_path)
    cfg["llm_backend"] = backend
    config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return True, str(config_path)

def pick_libelle(row):
    v = _ui_text(row.get("libelle_propose_ui"))
    if v:
        return v
    v = _ui_text(row.get("libelle_propose"))
    if v:
        return v
    return _ui_text(row.get("libelle_propose_batch"))

def pick_commentaire(row):
    v = _ui_text(row.get("commentaire_propose_ui"))
    if v:
        return v
    v = _ui_text(row.get("commentaire_propose"))
    if v:
        return v
    return _ui_text(row.get("commentaire_propose_batch"))


def _batch_status_badge(status: str) -> str:
    status = str(status or "").strip().upper()
    if not status:
        return "—"
    if status.startswith("ERR"):
        return f"🔴 {status}"
    if "WEAK" in status:
        return f"🟠 {status}"
    if status.startswith("OK"):
        return f"🟢 {status}"
    return status


def _show_vlm_error(exc: Exception) -> None:
    detail = str(exc or "").strip()
    log.exception("VLM UI error: %s", detail)
    st.error("Erreur lors du calcul de la description VLM.")
    if detail:
        st.caption(f"Détail technique : {detail}")


def asr_dictee(audio_bytes: bytes, audio_path_server: str | None, lang: str = "fr") -> str:
    r"""
    Transcrit la dictée selon config:
    - asr_backend=local  -> /asr_voxtral (audio_path serveur requis)
    - asr_backend=openai -> OpenAI audio/transcriptions (bytes requis)
    """
    appcfg = _load_app_config()
    asr_backend = str(appcfg.get("asr_backend", "local")).lower().strip()

    if asr_backend == "local":
        if not audio_path_server:
            raise RuntimeError("ASR local: audio_path_server manquant (upload /files requis).")
        return asr_voxtral_from_server_path(audio_path_server, lang=lang)

    if asr_backend == "openai":
        asr_model = str(appcfg.get("asr_model", "gpt-4o-mini-transcribe")).strip()
        api_key = appcfg.get("openai_api_key", "")
        if not api_key:
            raise RuntimeError("ASR OpenAI: clé API absente (OPENAI_API_KEY ou config.openai_api_key).")

        client = OpenAI(api_key=api_key)

        # OpenAI SDK attend un fichier-like (form-data)
        bio = io.BytesIO(audio_bytes)
        bio.name = "dictee.wav"  # certains clients utilisent .name

        tr = client.audio.transcriptions.create(
            model=asr_model,
            file=bio,
            language=lang,
        )
        return (tr.text or "").strip()

    raise RuntimeError(f"asr_backend invalide: {asr_backend}")


def call_vlm_single(image_path: str, context: str = "", prompt: str = "", model_name: str | None = None, mode: str | None = None) -> str:
    appcfg = _load_app_config()
    local_cfg = appcfg.get("local_llm", {}) or {}

    base_url = (local_cfg.get("base_url") or resolve_flask_base_url()).rstrip("/")
    api_key  = local_cfg.get("api_key", "")
    url = base_url + "/vision/describe"

    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    suffix = Path(image_path).suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"

    data = {}
    if context:
        data["context"] = context
    if prompt:
        data["prompt"] = prompt
    if model_name:
        data["model_name"] = model_name
    if mode:
        data["mode"] = mode  # fast | quality | quality_plus | auto (si vous l’exploitez)

    with open(image_path, "rb") as f:
        files = {"file": (Path(image_path).name, f, mime)}
        try:
            r = requests.post(url, files=files, data=data, headers=headers, timeout=180)
            r.raise_for_status()
        except requests.HTTPError as e:
            response = getattr(e, "response", None)
            if response is not None:
                try:
                    payload = response.json() or {}
                except Exception:
                    payload = {}
                detail = (
                    payload.get("error")
                    or payload.get("detail")
                    or payload.get("message")
                    or (response.text or "").strip()
                )
                if detail:
                    raise RuntimeError(f"VLM /vision/describe HTTP {response.status_code}: {detail}") from e
            raise

    payload = r.json()
    if payload.get("error"):
        raise RuntimeError(f"VLM /vision/describe: {payload['error']}")
    return str(payload.get("description", "")).strip()

def merge_vlm_audio(desc_vlm: str, extrait_audio: str) -> str:
    if desc_vlm:
        return f"[PHOTO]\n{desc_vlm}\n\n[AUDIO]\n{extrait_audio}"
    return extrait_audio

@st.cache_data(show_spinner=False)
def cached_vlm(image_path: str, context: str, prompt: str) -> str:
    return call_vlm_single(image_path, context=context, prompt=prompt)


def build_vlm_context(ctx_general: dict) -> str:
    mission = (ctx_general.get("mission") or "").strip()
    system  = (ctx_general.get("vlm_system") or ctx_general.get("system") or "").strip()
    user    = (ctx_general.get("vlm_user") or ctx_general.get("user") or "").strip()

    return (
        "CADRE (expertise — photos) :\n"
        f"- Mission : {mission}\n"
        f"- Cadrage VLM : {system}\n"
        f"- Guidage VLM : {user}\n\n"
        "INSTRUCTIONS VISION (obligatoires) :\n"
        "1) Décrire UNIQUEMENT ce qui est visible et pertinent pour des constats d'ouvrage.\n"
        "2) Priorité : ouvrages, matériaux, assemblages, finitions, désordres apparents, inachèvements.\n"
        "3) Ignorer : personnes, vêtements, meubles, décoration, électroménager, objets personnels, jouets.\n"
        "4) Ne pas inférer (pas de cause, pas de conformité, pas d'explication).\n"
        "5) Si un élément hors contexte apparaît : ne pas le décrire.\n"
    )


VLM_PROMPT = (
    "Décris l’image de façon factuelle, en français.\n"
    "Contraintes générales :\n"
    "- Décrire uniquement ce qui est visible. Ne rien inventer.\n"
    "- Si une information est incertaine, l’indiquer explicitement : (certain / probable / incertain).\n"
    "- Ne pas conclure sur un matériau si l’indice visuel n’est pas clair.\n"
    "- Attention particulière aux conduites/tuyaux/gouttières : segments, coudes, raccords, colliers, changements d’aspect.\n"
    "\n"
    "RÈGLE D’ÉCHELLE (OBLIGATOIRE) :\n"
    "- Pour tout objet pouvant être confondu avec un objet réel (ex : véhicule, engin, outil, figurine, jouet, maquette),\n"
    "  tu DOIS qualifier l’échelle avec l’un des mots exacts suivants :\n"
    "  « jouet », « miniature », « maquette », « figurine », « réel », « échelle incertaine ».\n"
    "- Interdiction d’utiliser un mot ambigu sans qualificatif lorsque l’échelle n’est pas certaine.\n"
    "  Exemple : écrire « camion-jouet (probable) » et non « camion ».\n"
    "  Si doute : « objet de type camion (échelle incertaine) ».\n"
    "\n"
    "Sortie attendue (texte structuré) :\n"
    "A) Description factuelle (6 à 10 phrases courtes)\n"
    "B) Vérifications guidées (si un contexte est fourni) :\n"
    "   - Lister les éléments mentionnés et donner un statut : [VISIBLE]/[PROBABLE]/[NON VISIBLE]/[INCERTAIN]\n"
    "   - Si [VISIBLE] ou [PROBABLE] : donner 1–2 indices visuels.\n"
    "C) Objets potentiellement miniatures / hors échelle ouvrage (OBLIGATOIRE si présent) :\n"
    "   - [JOUET]/[MINIATURE]/[MAQUETTE]/[FIGURINE]/[ECHELLE INCERTAINE] : objet — 1 indice visuel (taille relative, détails, proportions).\n"
)

EN_META = re.compile(r"\b(we need|must|should|produce a json|json with)\b", re.I)

_CHECK_TERMS = [
    "fissure", "fissures", "microfissure", "micro-fissure",
    "cloque", "cloques", "boursouflure", "boursouflures",
    "déformation", "déformations", "voilement", "affaissement",
    "décoll(e|é|ée|és|ées)ment", "décollement",
    "gondolement", "gonflement",
    "humidité", "moisi", "mousse", "infiltration", "fuite", "gouttes",
]

def extract_vlm_checklist(transcription: str) -> list[str]:
    t = (transcription or "").lower()
    hits = []
    for w in _CHECK_TERMS:
        if re.search(rf"\b{w}\b", t):
            hits.append(w)
    # dédoublonnage simple
    return sorted(set(hits))[:12]  # on limite pour rester lisible

def build_vlm_context_guided(ctx_general: dict, transcription_extrait: str) -> str:
    base = build_vlm_context(ctx_general)
    items = extract_vlm_checklist(transcription_extrait)
    if not items:
        return base + "\n\nVÉRIFICATIONS GUIDÉES : aucune."
    return (
        base
        + "\n\nVÉRIFICATIONS GUIDÉES (à contrôler sur l’image — ne pas en déduire que c’est présent) :\n"
        + "\n".join([f"- {it}" for it in items])
    )

def ensure_desc_vlm(
    i,
    row_view,
    guide_src: str,
    *,
    photos_df,
    photos_csv,
    infos,
    mission,
    context_system,
    context_user="",
    vlm_system="",
    vlm_user="",
    force: bool = False,
) -> str:
    if not force:
        # 1) priorité absolue : UI explicite
        desc = _ui_text(row_view.get("description_vlm_ui"))
        if desc:
            return desc

        # 2) fallback : colonne UI historique (si encore utilisée)
        desc = _ui_text(row_view.get("description_vlm"))
        if desc:
            return desc

        # 3) fallback batch (merge suffix _batch ou colonne native si déjà présente)
        #    (selon votre merge, c’est souvent "description_vlm_batch")
        desc = _ui_text(row_view.get("description_vlm_batch"))
        if desc:
            return desc

    # 4) sinon : appel VLM UI
    image_path = os.path.join(
        str(row_view.get("chemin_photo_reduite", "") or ""),
        str(row_view.get("nom_fichier_image", "") or ""),
    )

    if not os.path.exists(image_path):
        # optionnel mais conseillé : éviter appel serveur inutile
        photos_df.at[i, "vlm_ui_status"] = "ERR_IMAGE_NOT_FOUND"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        photos_df.at[i, "vlm_ui_ts"] = now
        photos_df.at[i, "ui_ts"] = now
        photo_dirty = True
        if photo_dirty:
            _persist_photos_csv(
                photos_df,
                photos_csv,
                infos,
                reason="vlm_image_missing",
                photo_rel_native=_photo_rel_at(photos_df, i),
            )
        return ""

    ctx_general = {
        "mission": mission,
        "system": context_system,
        "user": context_user,
        "vlm_system": vlm_system,
        "vlm_user": vlm_user,
    }
    ctx_vlm = build_vlm_context_guided(ctx_general, guide_src)

    desc_new = call_vlm_single(image_path, context=ctx_vlm, prompt=VLM_PROMPT)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if desc_new:
        photos_df.at[i, "description_vlm_ui"] = desc_new
        photos_df.at[i, "vlm_ui_status"] = "OK"
    else:
        photos_df.at[i, "vlm_ui_status"] = "EMPTY"

    photos_df.at[i, "vlm_ui_ts"] = now
    photos_df.at[i, "ui_ts"] = now

    _persist_photos_csv(
        photos_df,
        photos_csv,
        infos,
        reason="vlm_description",
        photo_rel_native=_photo_rel_at(photos_df, i),
    )

    return desc_new or ""


# -----------------------------------------------------------------------------
# Interface principale
# -----------------------------------------------------------------------------

def show_annotation_interface():
    r"""
    Interface Streamlit pour l’annotation guidée par GPT.
    Tout le code d’annotation (widgets, boucles, GPT, enregistrement)
    doit être indenté sous cette signature.
    """
    infos = lire_infos_projet()
    appcfg = _load_app_config(infos)

    photos_csv              = infos.get("fichier_photos")
    transcription_csv_photo = infos.get("fichier_transcription")  # CSV choisi dans l’interface
    audio_path              = infos.get("fichier_audio")

    # Mission par défaut : prise dans infos_projet.json (compatibilité anciens projets)
    mission_from_infos = infos.get("mission", "")
    mission = mission_from_infos


    audio_path          = str(infos.get("fichier_audio", "") or "").strip()
    audio_src_path      = str(infos.get("fichier_audio_source", "") or "").strip()
    audio_compat_source = str(infos.get("audio_compat_source", "") or "").strip()
    calibrage_valide    = bool(infos.get("calibrage_valide", False))

    # 1) Audio compatible présent ?
    if not audio_path or not os.path.exists(audio_path):
        st.session_state["selection_return_reason"] = "annotation bloquée: fichier audio compatible manquant"
        st.error("❌ Aucun fichier audio compatible valide. "
                 "Veuillez revenir à l’étape 1 pour le (re)générer.")
        st.stop()

    # 2) Cohérence source / compatible
    if audio_src_path and audio_compat_source and \
       os.path.abspath(audio_src_path) != os.path.abspath(audio_compat_source):
        st.session_state["selection_return_reason"] = "annotation bloquée: incohérence entre audio source et audio compatible"
        st.error("❌ Le fichier audio compatible ne correspond plus au fichier audio source. "
                 "Veuillez repasser par l’étape 1 (sélection des fichiers).")
        st.stop()

    # 3) Calibrage obligatoire avant annotation
    if not calibrage_valide:
        st.session_state["selection_return_reason"] = "annotation bloquée: calibrage invalide"
        st.error("❌ Le calibrage n’est pas valide. Veuillez d’abord réaliser la synchronisation (étape 2.1).")
        st.stop()


    decalage_raw = infos.get("decalage_moyen", 0.0)
    try:
        decalage = float(str(decalage_raw).replace(",", "."))
    except Exception:
        decalage = 0.0

    st.title("🖋️ Annotation guidée avec GPT")

    current_backend = str(infos.get("llm_backend") or appcfg.get("llm_backend") or "local").strip().lower()
    if current_backend not in {"local", "openai"}:
        current_backend = "local"
    st.session_state.setdefault("llm_backend_input", current_backend)

    # ─────────────────────────────────────────────────────────────
    # 🔗 Vérifications de base
    # ─────────────────────────────────────────────────────────────
    if not photos_csv:
        st.error("Fichier photos introuvable dans infos_projet.json")
        return

    if not transcription_csv_photo:
        st.error("Aucun fichier de transcription défini dans infos_projet.json.")
        return

    base_dir  = os.path.dirname(photos_csv)
    base_name = os.path.splitext(os.path.basename(photos_csv))[0]

    # Valeurs par défaut depuis infos_projet.json
    mission = mission_from_infos
    context_system = infos.get("system", "")
    context_user   = infos.get("user", "")
    vlm_system     = infos.get("vlm_system", "")
    vlm_user       = infos.get("vlm_user", "")

    contexte_path = infos.get("fichier_contexte_general")
    if contexte_path and os.path.exists(contexte_path):
        with open(contexte_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Override si présent dans le contexte
        mission        = data.get("mission", mission)
        context_system = data.get("system", context_system)
        context_user   = data.get("user", context_user)
        vlm_system     = data.get("vlm_system", vlm_system)
        vlm_user       = data.get("vlm_user", vlm_user)
        ctx_general = {
            "mission": mission,
            "system": context_system,
            "user": context_user,
            "vlm_system": vlm_system,
            "vlm_user": vlm_user,
        }

        # État d’avancement (optionnel)
        etat_avancement = data.get("etat_avancement", "")
        if etat_avancement:
            context_user = (context_user + "\n\nÉtat d’avancement : " + etat_avancement).strip()


    # ─────────────────────────────────────────────────────────────
    # 🧠 Choix du CSV de transcription effectif
    #   - si on a "...(wav)(photo).csv" ET le jumeau "...(wav).csv" → on utilise ce dernier (Voxtral)
    #   - sinon on utilise le CSV indiqué dans infos_projet.json tel quel
    # ─────────────────────────────────────────────────────────────
    p = Path(transcription_csv_photo)
    csv_effectif = p

    if "(photo)" in p.name:
        alt = p.with_name(p.name.replace("(photo)", ""))  # "…(wav)(photo).csv" → "…(wav).csv"
        if alt.exists():
            csv_effectif = alt
            st.info(f"Transcription utilisée : fichier à intervalles (start/end) → {alt.name}")
        else:
            st.info(f"Transcription utilisée : fichier horodaté → {p.name}")
    else:
        st.info(f"Transcription utilisée : {p.name}")


    # ─────────────────────────────────────────────────────────────
    # 🔊 Chargement de la transcription (format flexible)
    #   - soit format horodatage (colonne "horodatage" → "temps")
    #   - soit format Voxtral (start/end/speaker/text → start_sec/end_sec/texte/temps)
    #   géré par utils.charger_transcription_flexible()
    # ─────────────────────────────────────────────────────────────
    # === Source de vérité pour t=0 audio (sans médiane) ===
    t0_global_str = str(infos.get("t0_global", "")).strip()
    audio0_dt = _parse_audio0(t0_global_str) or _parse_audio0(infos.get("horodatage_audio", ""))

    if audio0_dt is None:
        st.error("Référence t=0 audio introuvable (t0_global / horodatage_audio).")
        st.stop()
    trans_df = charger_transcription_flexible(str(csv_effectif), audio0_dt=audio0_dt)

    # ─────────────────────────────────────────────────────────────
    # ⏱ Seconds-of-day à partir de "HH:MM:SS" pour les photos
    # ─────────────────────────────────────────────────────────────
    def _sec_of_day(hms):
        try:
            h, m, s = str(hms).split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        except Exception:
            return float("nan")

     
    # ---verification serveur audio --------------------------------------------------

    audio_url = "http://127.0.0.1:5000/audio/audio_compatible.wav"
    audio_compat = str(infos.get("fichier_audio", "") or infos.get("fichier_audio_compatible", "") or "").strip()
    audio_server_start_error = ""
    if audio_compat and os.path.exists(audio_compat):
        try:
            start_audio_server_if_needed(audio_compat)
        except Exception as e:
            audio_server_start_error = str(e)




    with st.expander("🔧 Serveur audio", expanded=False):
        if audio_server_start_error:
            st.error(f"❌ Relance du serveur audio impossible : {audio_server_start_error}")
        try:
            # HEAD d’abord (léger), sinon GET sur un octet avec Range
            r = requests.get(audio_url, headers={"Range": "bytes=0-0"}, timeout=4)
            ok = r.status_code in (200, 206)
            if ok:
                st.success("✅ Serveur audio : accessible")
                try:
                    info = requests.get("http://127.0.0.1:5000/info", timeout=3).json()
                    if info.get("size_bytes"):
                        st.caption(f"Fichier : {info.get('filename')} • ~{info['size_bytes']/1_000_000:.1f} Mo")
                except Exception:
                    pass
            else:
                st.warning(f"⚠️ Réponse HTTP {r.status_code}")
        except Exception as e:
            st.error(f"❌ Serveur audio injoignable : {e}")

# -----------------------------------------------------    

    
    # ─────────────────────────────────────────────────────────────
    # 🔄 Choix du fichier d’annotation (session existante ou nouvelle)
    # ─────────────────────────────────────────────────────────────
    annotations_existantes = sorted(
        glob.glob(os.path.join(base_dir, f"{base_name}_GTP_*.csv"))
    )
    ANNOT_COLS = [
        "nom_fichier_image",
        "horodatage_photo",
        "orientation_photo",
        "transcription_libelle",
        "libelle",
        "transcription_commentaire",
        "commentaire",
        "chemin_photo_reduite",
        "retenue",
        "t_audio_sec",
        "audio_timecode_hms",
        "audio_datetime_abs",
        "audio_start_sec",
        "audio_end_sec",
        "annotation_validee"
    ]


    if annotations_existantes:
        # On reprend la dernière session existante
        annotations_path = annotations_existantes[-1]
        annotations_df   = read_csv_fallback(annotations_path, sep=";")
        annotations_df = annotations_df.reindex(columns=ANNOT_COLS)
        if "annotation_validee" not in annotations_df.columns:
            annotations_df["annotation_validee"] = 0
            annotations_df["annotation_validee"] = pd.to_numeric(
                annotations_df["annotation_validee"], errors="coerce"
            ).fillna(0).astype(int).clip(0, 1)


    else:
        # Nouvelle session → on génère un fichier vierge
        timestamp        = datetime.now().strftime("%Y%m%d_%H%M")
        annotations_path = os.path.join(base_dir, f"{base_name}_GTP_{timestamp}.csv")
        annotations_df   = pd.DataFrame(columns=[
            "nom_fichier_image",
            "horodatage_photo",
            "orientation_photo",
            "transcription_libelle",
            "libelle",
            "transcription_commentaire",
            "commentaire",
            "chemin_photo_reduite",
            "retenue",
            # 🔽 nouvelles colonnes pour réécoute / vérification
            "t_audio_sec",                 # secondes depuis t=0 audio (float)
            "audio_timecode_hms",          # HH:MM:SS.mmm (lisible / VLC)
            "audio_datetime_abs",          # horodatage absolu (t=0 audio + t_audio)
            "audio_start_sec",             # fenêtre écoutée : début
            "audio_end_sec",                # fenêtre écoutée : fin
            "annotation_validee"
        ])


        annotations_df = annotations_df.reindex(columns=ANNOT_COLS)
        # ✅ Sécurise la nouvelle session : flag présent et à 0
        annotations_df["annotation_validee"] = pd.to_numeric(
            annotations_df["annotation_validee"], errors="coerce"
        ).fillna(0).astype(int).clip(0, 1)

    # ─────────────────────────────────────────────────────────────
    # 🔄 Gestion de session d’annotation : chargement des photos
    # ─────────────────────────────────────────────────────────────
    _sync_photos_csv_on_launch(infos, photos_csv)
    _retry_pending_nas_sync(infos)
    _retry_pending_gpt_exports(infos)
    photos_df = read_csv_fallback(photos_csv, sep=";")
    if st.session_state.get("canonical_mirror_pending"):
        err = _ui_text(st.session_state.get("canonical_mirror_error"))
        st.warning("Miroir canonique en attente" + (f" : {err}" if err else "."))
    if st.session_state.get("nas_sync_pending"):
        err = _ui_text(st.session_state.get("nas_sync_error"))
        st.warning("Sauvegarde locale effectuée — synchronisation NAS en attente" + (f" : {err}" if err else "."))
    if st.session_state.get("gpt_exports_sync_pending"):
        st.warning("Enregistré localement — publication NAS en attente pour un export *_GTP_*.csv/xlsx.")
        if st.button("Retenter la publication NAS des exports GTP", key="retry_gpt_exports_nas"):
            retry_result = _retry_pending_gpt_exports(infos)
            if retry_result.get("pending") or retry_result.get("conflicts"):
                st.warning(f"Publication GTP encore incomplète : {retry_result}")
            else:
                st.success("Publications GTP en attente résolues.")
            st.rerun()
    photos_df = _ensure_photo_text_columns(
        photos_df,
        [
            "dictee_asr_status",
            "dictee_asr_ts",
            "dictee_asr_text",
            "dictee_asr_error",
            "dictee_audio_path_pcfixe",
            "dictee_asr_csv_path_pcfixe",
            "dictee_asr_photo_csv_path_pcfixe",
        ],
    )
    photos_df["sec_of_day"] = photos_df["horodatage_photo"].apply(_sec_of_day)

    if "orientation_photo" in photos_df.columns:
        photos_df["orientation_photo"] = pd.to_numeric(
            photos_df["orientation_photo"], errors="coerce"
        ).fillna(0).astype(int)


    if "annotation_validee" not in photos_df.columns:
        photos_df["annotation_validee"] = 0
    
    photos_df["annotation_validee"] = pd.to_numeric(
        photos_df["annotation_validee"], errors="coerce"
    ).fillna(0).astype(int).clip(0, 1)
    # ✅ Ne pas déduire "validée" par simple présence dans GTP.
    #    On recopie la valeur 0/1 réellement portée par le GTP.
    if not annotations_df.empty and "annotation_validee" in annotations_df.columns:
        ann_map = (
            annotations_df[["nom_fichier_image", "annotation_validee"]]
            .dropna(subset=["nom_fichier_image"])
            .assign(nom_fichier_image=lambda d: d["nom_fichier_image"].astype(str).str.strip())
            .drop_duplicates(subset=["nom_fichier_image"], keep="last")
            .set_index("nom_fichier_image")["annotation_validee"]
        )
        photos_df["annotation_validee"] = photos_df["nom_fichier_image"].astype(str).str.strip().map(ann_map).fillna(
            photos_df["annotation_validee"]
        )
        photos_df["annotation_validee"] = pd.to_numeric(photos_df["annotation_validee"], errors="coerce").fillna(0).astype(int).clip(0, 1)

    # Normalisation des colonnes numériques (accepte '.' ou ',')
    def _to_float_series(s):
        return pd.to_numeric(s.astype(str).str.replace(',', '.', regex=False), errors='coerce')

    num_cols = ["horodatage_secondes", "synchro_audio",
                "decalage_individuel", "decalage_moyen", "t_audio"]
    for col in num_cols:
        if col in photos_df.columns:
            photos_df[col] = _to_float_series(photos_df[col])



    # ─────────────────────────────────────────────────────────────
    # 🚀 Boucle principale d’annotation (toujours exécutée)
    # ─────────────────────────────────────────────────────────────
    
    # Sauvegarde unique si des corrections t_audio ont eu lieu
    # Sauvegarde unique si des corrections t_audio ont eu lieu
    
            

    with st.expander("📦 Enregistrer les paramètres dans infos_projet.json", expanded=False):
        if st.session_state.get("debug"):
            st.write("LocalLLMClient loaded from:", inspect.getfile(LocalLLMClient))
            st.write("Has STOP_LIBELLE:", hasattr(LocalLLMClient, "STOP_LIBELLE"))

        llm_backend_ui = st.selectbox(
            "Backend LLM",
            ["local", "openai"],
            index=0 if st.session_state.get("llm_backend_input", current_backend) == "local" else 1,
            key="llm_backend_input",
        )
        st.caption("`local` utilise SERVER_URL/LOCAL_LLM_API_KEY ; `openai` utilise OPENAI_API_KEY.")

        st.markdown("Cliquez sur le bouton ci-dessous pour sauvegarder les durées actuellement utilisées.")
        if st.button("💾 Enregistrer les durées dans le fichier projet"):
            infos["plages_utilisees"] = {
                "libelle": {"avant": float(st.session_state.get("lib_av_input", 0.5)),
                            "apres": float(st.session_state.get("lib_ap_input", 0.5))},
                "commentaire": {"avant": float(st.session_state.get("com_av_input", 1.0)),
                                "apres": float(st.session_state.get("com_ap_input", 1.0))}
                }
            infos["audio_av"] = float(st.session_state.get("audio_av_input", 10))
            infos["audio_ap"] = float(st.session_state.get("audio_ap_input", 10))
            infos["llm_backend"] = llm_backend_ui

            sauvegarder_infos_projet(infos)
            persisted_cfg, cfg_path = _persist_llm_backend(infos, llm_backend_ui)
            st.success("✅ Les durées ont été enregistrées dans `infos_projet.json`.")
            if persisted_cfg:
                st.caption(f"Backend LLM aussi répercuté dans `{cfg_path}`.")

            
    # ─────────────────────────────────────────────────────────────
    # 🚀 Boucle principale sur les photos
    # ─────────────────────────────────────────────────────────────
        

    
    # Assurez-vous d'avoir bien initialisé ces clés avant la boucle :
    st.session_state.setdefault("lib_avant", 0.5)
    st.session_state.setdefault("lib_apres", 0.5)
    st.session_state.setdefault("com_avant", 1.0)
    st.session_state.setdefault("com_apres", 1.0)
    st.session_state.setdefault("audio_avant", 10)
    st.session_state.setdefault("audio_apres", 10)

    
    prompts = charger_prompts()
    # ─── Réglages globaux ───
    projet = lire_infos_projet()

    audio_av = float(projet.get("audio_av", 10))
    audio_ap = float(projet.get("audio_ap", 10))
    pl = projet.get("plages_utilisees", {}) or {}
    lib_av = float(pl.get("libelle", {}).get("avant", 0.5))
    lib_ap = float(pl.get("libelle", {}).get("apres", 0.5))
    com_av = float(pl.get("commentaire", {}).get("avant", 1.0))
    com_ap = float(pl.get("commentaire", {}).get("apres", 1.0))

    with st.expander("🛠 Régler les durées globales", expanded=False):
        audio_av = st.number_input("▶️ Audio avant (s)", min_value=0.0, value=float(audio_av), step=1.0, key="audio_av_input")
        audio_ap = st.number_input("▶️ Audio après (s)", min_value=0.0, value=float(audio_ap), step=1.0, key="audio_ap_input")
        lib_av   = st.number_input("🏷 Libellé avant (s)",     min_value=0.0, value=float(lib_av), step=0.5, key="lib_av_input")
        lib_ap   = st.number_input("🏷 Libellé après (s)",     min_value=0.0, value=float(lib_ap), step=0.5, key="lib_ap_input")
        com_av   = st.number_input("📝 Commentaire avant (s)", min_value=0.0, value=float(com_av), step=0.5, key="com_av_input")
        com_ap   = st.number_input("📝 Commentaire après (s)", min_value=0.0, value=float(com_ap), step=0.5, key="com_ap_input")

        if st.button("💾 Mettre à jour ces durées", key="save_durees"):
            projet["audio_av"] = audio_av
            projet["audio_ap"] = audio_ap
            projet["llm_backend"] = st.session_state.get("llm_backend_input", current_backend)
            projet.setdefault("plages_utilisees", {})
            projet["plages_utilisees"].setdefault("libelle", {})
            projet["plages_utilisees"].setdefault("commentaire", {})
            projet["plages_utilisees"]["libelle"]["avant"]     = lib_av
            projet["plages_utilisees"]["libelle"]["apres"]     = lib_ap
            projet["plages_utilisees"]["commentaire"]["avant"] = com_av
            projet["plages_utilisees"]["commentaire"]["apres"] = com_ap
            sauvegarder_infos_projet(projet)
            _persist_llm_backend(projet, projet["llm_backend"])
            st.success("✅ Durées globales mises à jour.")

    # 📷 Affichage du numéro de photo courant

    # --- Déterminer la première photo non annotée ---

    # --- Mode d’annotation ---
    edit_mode = st.radio(
        "Mode d’annotation",
        ("Séquentiel (sécurisé)", "Réédition libre (expert)"),
        index=0,
        horizontal=True,
        key="edit_mode",
    )

    col_dictee_submit, col_dictee_refresh = st.columns(2)
    reconciliation_plan = st.session_state.get("dictee_reconciliation_plan")
    if isinstance(reconciliation_plan, dict):
        summary = reconciliation_plan.get("summary", {}) if isinstance(reconciliation_plan.get("summary"), dict) else {}
        rows = [row for row in reconciliation_plan.get("rows", []) if isinstance(row, dict)]
        preview_rows = [
            {
                "photo": row.get("nom_fichier_image", ""),
                "dictation_id": row.get("dictation_id", ""),
                "statut": row.get("status", ""),
                "action": row.get("action", ""),
                "raison": row.get("reason", ""),
                "texte": row.get("text_preview", ""),
                "csv": row.get("csv_path", ""),
                "csv_photo": row.get("photo_csv_path", ""),
                "concurrents": len(row.get("concurrent_results") or []),
            }
            for row in rows
        ]
        st.caption(
            "Previsualisation ASR : "
            f"{int(summary.get('would_update') or 0)} propagation(s), "
            f"{int(summary.get('still_pending') or 0)} pending, "
            f"{int(summary.get('duplicates') or 0)} concurrent(s), "
            f"{int(summary.get('orphans') or 0)} orphelin(s), "
            f"{int(summary.get('conflicts') or 0) + int(summary.get('invalid_mappings') or 0)} conflit(s)."
        )
        if preview_rows:
            st.dataframe(preview_rows, use_container_width=True)
        can_apply_reconciliation = int(summary.get("would_update") or 0) > 0
        if st.button(
            "Appliquer la reconciliation ASR validee",
            key="apply_local_dictee_reconciliation",
            disabled=not can_apply_reconciliation,
        ):
            completed, still_pending, plan = _refresh_submitted_local_dictees(
                photos_df=photos_df,
                photos_csv=photos_csv,
                infos=infos,
                apply=True,
                return_plan=True,
            )
            st.session_state["dictee_reconciliation_plan"] = plan
            st.success(
                f"{completed} transcription(s) propagee(s) dans photos.csv ; "
                f"{still_pending} encore reellement en attente."
            )
            st.rerun()
    with col_dictee_submit:
        if st.button("Soumettre les dictées locales en attente", key="submit_local_dictees"):
            try:
                submitted, remaining = _submit_local_pending_dictees(infos)
                st.success(f"{submitted} dictée(s) soumise(s) ; {remaining} reste(nt) en attente.")
            except Exception as exc:
                st.error(f"Soumission des dictées locales impossible : {exc}")
    with col_dictee_refresh:
        if st.button("Rafraîchir les transcriptions", key="refresh_local_dictees"):
            completed, still_pending = _refresh_submitted_local_dictees(
                photos_df=photos_df,
                photos_csv=photos_csv,
                infos=infos,
            )
            st.success(f"{completed} transcription(s) complétée(s) ; {still_pending} encore en attente.")

    # --- Déterminer la première photo non annotée ---
    annoted_names = set(annotations_df["nom_fichier_image"].astype(str))
    first_non = _next_actionable_photo_index(photos_df, annoted_names)
    has_pending_unannotated = any(
        str(photos_df.iloc[idx].get("nom_fichier_image") or "").strip() not in annoted_names
        and _is_dictee_pending(photos_df.iloc[idx].get("dictee_asr_status"))
        for idx in range(len(photos_df))
    )
    seq_override_index = st.session_state.pop("seq_override_index", None)
    seq_context_key = "|".join(
        [
            _ui_text(infos.get("id_affaire") or infos.get("project_id")),
            _ui_text(infos.get("id_captation") or infos.get("captation_id")),
            str(Path(photos_csv).resolve()),
        ]
    )

    if edit_mode == "Séquentiel (sécurisé)":
        if st.session_state.get("seq_current_context") != seq_context_key:
            st.session_state["seq_current_context"] = seq_context_key
            if first_non is not None:
                st.session_state["seq_current_index"] = int(first_non)
            else:
                st.session_state.pop("seq_current_index", None)

        if isinstance(seq_override_index, int):
            override_ok = 0 <= seq_override_index < len(photos_df)
            if override_ok:
                st.session_state["seq_current_index"] = int(seq_override_index)

        seq_current_index = st.session_state.get("seq_current_index")
        if isinstance(seq_current_index, int) and 0 <= seq_current_index < len(photos_df):
            target_indices = [seq_current_index]
        elif first_non is not None:
            st.session_state["seq_current_index"] = int(first_non)
            target_indices = [first_non]
        else:
            if has_pending_unannotated:
                st.info("Toutes les photos restantes sont en attente de transcription. Vous pouvez continuer plus tard ou passer en Réédition libre (expert).")
            else:
                st.info("Toutes les photos sont déjà annotées ...")
            return
    else:
        target_indices = list(range(len(photos_df)))

    # En mode séquentiel : si tout est déjà annoté, on informe et on s’arrête proprement
    if edit_mode == "Séquentiel (sécurisé)" and first_non is None:
        if has_pending_unannotated:
            st.info("Toutes les photos restantes sont en attente de transcription. Revenez plus tard ou passez en **Réédition libre (expert)** pour consulter une photo précise.")
        else:
            st.info("Toutes les photos sont déjà annotées. Passez en **Réédition libre (expert)** pour modifier des annotations existantes.")
        return
    
    # ─────────────────────────────────────────────────────────────
    # 📦 Batch (lecture seule) : construction d'une vue merge UI+Batch
    # ─────────────────────────────────────────────────────────────

    photos_batch_csv = str(infos.get("fichier_photos_batch", "") or "").strip()
    _sync_photos_batch_from_canonical(infos)
    batch_df = None
    photos_view_df = photos_df

    if photos_batch_csv and os.path.exists(photos_batch_csv):
        try:
            batch_df = read_csv_fallback(photos_batch_csv, sep=";")
        except Exception:
            batch_df = None

    if batch_df is not None and not batch_df.empty:
        key = "photo_rel_native"
        photos_df = photos_df.copy()
        photo_dirty = True

        if key in photos_df.columns:
            photos_df[key] = photos_df[key].astype(str).str.strip()

        if key in photos_df.columns and key in batch_df.columns:
            batch_df = batch_df.dropna(subset=[key]).copy()
            photos_df = photos_df.copy()
            photo_dirty = True
            photos_df[key] = photos_df[key].astype(str).str.strip()
            batch_df[key] = batch_df[key].astype(str).str.strip()
            batch_df = batch_df.drop_duplicates(subset=[key], keep="last")
            try:
                photos_view_df = photos_df.merge(
                    batch_df,
                    on=key,
                    how="left",
                    suffixes=("", "_batch"),
                    validate="one_to_one",   # ou "one_to_many" si vous assumez un cas, mais alors il faut changer la logique iloc
                    sort=False,
                )
            except Exception as e:
                st.error(f"❌ Merge UI/batch invalide (doublon sur {key} ?) : {e}")
                photos_view_df = photos_df    
        else:
            st.warning(f"⚠️ Merge UI/batch impossible : clé '{key}' absente.")
    
    else:
        if photos_batch_csv:
            st.info("ℹ️ photos_batch.csv non présent ou vide : affichage UI seul.")


    batch_filter_labels = []
    if edit_mode == "Réédition libre (expert)" and batch_df is not None and not batch_df.empty:
        with st.expander("🎯 Filtre batch", expanded=False):
            show_weak = st.checkbox("Afficher WEAK_LIB / OK_LIB_COM_WEAK", value=False, key="batch_filter_weak")
            show_err = st.checkbox("Afficher ERR_LIB / OK_LIB_ERR_COM", value=False, key="batch_filter_err")

        if show_weak or show_err:
            batch_status_series = photos_view_df.get("batch_status", pd.Series("", index=photos_view_df.index)).astype(str)
            selected_mask = pd.Series(False, index=photos_view_df.index)
            if show_weak:
                selected_mask |= batch_status_series.str.contains("WEAK", case=False, na=False)
                batch_filter_labels.append("WEAK")
            if show_err:
                selected_mask |= batch_status_series.str.startswith("ERR", na=False) | batch_status_series.str.contains(
                    "ERR_COM",
                    case=False,
                    na=False,
                )
                batch_filter_labels.append("ERR")
            target_indices = [idx for idx in target_indices if bool(selected_mask.iloc[idx])]

            if batch_filter_labels:
                st.caption(f"Filtre batch actif : {', '.join(batch_filter_labels)}")
            if not target_indices:
                st.info(f"Aucune photo ne correspond au filtre batch sélectionné : {', '.join(batch_filter_labels)}.")
                return

    # --- BOUCLE PRINCIPALE SUR LES PHOTOS ---

    photos_df = photos_df.reset_index(drop=True)
    photos_view_df = photos_view_df.reset_index(drop=True)

    edit_mode = st.session_state.get("edit_mode", "Séquentiel (sécurisé)")

    texte_lib = ""
    texte_com = ""



    for i in target_indices:
        row = photos_df.iloc[i]              # écriture
        row_view = photos_view_df.iloc[i]    # lecture (UI + batch)
        photo_dirty = False

        current_seq_target = i if edit_mode == "Séquentiel (sécurisé)" else first_non

        if edit_mode == "Séquentiel (sécurisé)":
            # On n'affiche qu'une seule photo : la première non annotée
            if current_seq_target is None:
                if has_pending_unannotated:
                    st.info("Toutes les photos restantes sont en attente de transcription.")
                else:
                    st.info("Toutes les photos sont déjà annotées.")
                return
            if i != current_seq_target:
                continue

        nom_image = row["nom_fichier_image"]
        is_annotated = str(nom_image) in annoted_names

        if edit_mode == "Séquentiel (sécurisé)":
            if is_annotated and i != current_seq_target:
                st.caption(f"✅ {nom_image} déjà annotée — édition verrouillée.")
                continue
        else:
            if is_annotated and not st.session_state.get(f"edit_{i}", False):
                cols = st.columns([1, 3])
                cols[0].caption(f"✅ {nom_image} déjà annotée — édition verrouillée.")
                with cols[1]:
                    if st.button("🔓 Ré-éditer cette photo", key=f"reopen_{i}"):
                        st.session_state[f"edit_{i}"] = True
                        st.rerun()
                continue
        # --- t0 basé sur l'horodatage photo et la référence audio0_dt ---
        photo_dt = _parse_photo_dt(row.get("horodatage_photo"), default_date=audio0_dt.date())
        if photo_dt is None:
            st.warning(f"{nom_image} : horodatage_photo illisible → je passe.")
            continue

        t0 = (photo_dt - audio0_dt).total_seconds()
        unsync_mode = (t0 < 0)

        # Toujours initialiser
        csv_ta = float("nan")
        t_ref = float(t0)  # fallback
        # Référence unique en secondes audio (calibrée si dispo)

        TOL_SEC = 2.0
        if not unsync_mode:
            csv_ta = _num(row.get("synchro_audio"))
            if math.isnan(csv_ta):
                csv_ta = _num(row.get("t_audio"))


            # Référence unique : audio-seconds (calibrée si dispo)
            if not math.isnan(csv_ta):
                t_ref = float(csv_ta)

                ecart = float(csv_ta) - float(t0)
                if abs(ecart) > TOL_SEC:
                    st.warning(
                        f"📏 Écart t_audio pour {nom_image} : CSV={csv_ta:.2f}s, attendu={t0:.2f}s "
                        f"(écart {ecart:+.2f}s > {TOL_SEC:.1f}s)."
                    )
            else:
                # t_audio absent : option 1 (prudente) : ne pas écrire
                # option 2 : écrire t_ref (qui vaut t0 ici)
                photos_df.at[i, "t_audio"] = float(t_ref)
                photos_df.at[i, "synchro_audio"] = float(t_ref)
                st.info(f"🧩 t_audio absent pour {nom_image} → reconstruit à {t_ref:.2f}s (sera sauvegardé).")

        if not unsync_mode:
            cur = _num(row.get("synchro_audio"))
            if math.isnan(cur) or abs(cur - t_ref) > 0.01:
                photos_df.at[i, "t_audio"] = float(t_ref)
                photos_df.at[i, "synchro_audio"] = float(t_ref)
                photo_dirty = True

        t0_hms = _hms_signed(t0)
        st.markdown(f"### 📸 {nom_image} — ⏱️ t₀ {t0_hms}")
        if unsync_mode:
            st.caption("⚠️ Photo antérieure au début de l'audio : non synchronisable (GPT désactivé).")
        else:
            st.caption(f"⚙️ Décalage moyen : {decalage:.2f}s • 🔊 t₀ brut : {t0:.2f}s • 🔊 t_ref : {t_ref:.2f}s")

        cur_av = float(st.session_state.get("audio_av_input", audio_av))
        cur_ap = float(st.session_state.get("audio_ap_input", audio_ap))

        listen_key = f"show_wave_{i}"
        want_listen = st.checkbox("🎧 Afficher le lecteur audio pour cette photo", key=listen_key, value=False)

        if want_listen and not unsync_mode:
            try:
                duree_audio = float(sf.info(audio_path).duration)
                t_debut = max(0.0, t_ref - cur_av)
                t_fin   = min(duree_audio, t_ref + cur_ap)
                clip_url = f"http://127.0.0.1:5000/audio_clip?start={t_debut:.3f}&end={t_fin:.3f}"

                st.write({"t_ref": t_ref, "t_debut": t_debut, "t_fin": t_fin})

                st.audio(clip_url)
                wavesurfer(audio_url=clip_url, height=120, key=f"wave-{i}-{int(t_debut*10)}")
            except Exception as e:
                st.warning(f"Audio non disponible : {e}")
        elif not unsync_mode:
            st.caption("💤 Lecteur audio non chargé pour cette photo (cocher la case ci-dessus pour l’afficher).")
        else:
            st.info("⏳ Photo antérieure au début du fichier audio : pas de lecture possible.")

        if photo_dirty:
            _persist_photos_csv(
                photos_df,
                photos_csv,
                infos,
                reason="audio_sync_fields",
                photo_rel_native=_photo_rel_at(photos_df, i),
            )

        # 2) Photo (2/3) et info (1/3)
        
        col_photo, col_ctrl = st.columns([2, 1])
        thumb_path = os.path.join(row["chemin_photo_reduite"], nom_image)

        # juste après col_photo, col_ctrl = st.columns([2, 1])
        row_ann = annotations_df[annotations_df["nom_fichier_image"] == nom_image]

        retenue_key = f"retenue_{i}"
        if retenue_key not in st.session_state:
            if not row_ann.empty and "retenue" in annotations_df.columns:
                st.session_state[retenue_key] = bool(row_ann["retenue"].iloc[0])
            else:
                st.session_state[retenue_key] = True

        st.checkbox("✅ Photo retenue", key=retenue_key)
        retenue = bool(st.session_state[retenue_key])


        # Colonne photo
        with col_photo:
            thumb_path = os.path.join(row["chemin_photo_reduite"], nom_image)
            orientation_init = int(row.get("orientation_photo", 0) or 0)

            # état par photo pour que la rotation survive aux reruns
            key_rot = f"orientation_{i}"
            if key_rot not in st.session_state:
                st.session_state[key_rot] = orientation_init

            if os.path.exists(thumb_path):
                try:
                    img = Image.open(thumb_path)
                    rot = int(st.session_state[key_rot])
                    if rot in (90, 180, 270):
                        img = img.rotate(-rot, expand=True)  # sens horaire
                    st.image(img, use_container_width=True)
                except Exception as e:
                    st.warning(f"Image illisible ({e}) : {thumb_path}")
            else:
                st.warning(f"Image introuvable : {thumb_path}")


        # Colonne info
        # ----------------------------------------------------------------------------------
        with col_ctrl:
            st.markdown("### Paramètres de plage autour de t_audio")
            # On aligne les labels et inputs en deux colonnes

            # Sélecteur de rotation (affecte l’aperçu et sera sauvegardé avec l’annotation)
            key_rot = f"orientation_{i}"
            rotations = [0, 90, 180, 270]
            try:
                idx = rotations.index(int(st.session_state.get(key_rot, int(row.get("orientation_photo", 0) or 0))))
            except ValueError:
                idx = 0
            new_rot = st.selectbox("🔄 Rotation photo (°)", rotations, index=idx, key=key_rot)

            # ─────────────────────────────────────────────
            # VLM — Affichage de la description (si dispo)
            # ─────────────────────────────────────────────

            def pick_desc_vlm(r):
                v = _ui_text(r.get("description_vlm_ui"))
                if v:
                    return v
                v = _ui_text(r.get("description_vlm"))
                if v:
                    return v
                return _ui_text(r.get("description_vlm_batch"))

            desc_vlm = pick_desc_vlm(row_view)  # ✅ UI > legacy > batch
            vlm_status = _ui_text(row.get("vlm_ui_status"))  # ✅ UI
            vlm_ts     = _ui_text(row.get("vlm_ui_ts"))
            batch_status = _ui_text(row_view.get("batch_status"))

            st.caption(
                f"Statut VLM: {vlm_status or '—'} • Batch: {_batch_status_badge(batch_status)} • Date: {vlm_ts or '—'}"
            )

            with st.expander("🧠 Description VLM (photo)", expanded=True):
                
                if desc_vlm:
                    st.write(desc_vlm)
                else:
                    st.caption("Aucune description VLM enregistrée pour cette photo.")

                colv1, colv2 = st.columns(2)

                # 1) calcul si vide (inchangé, mais gardé)
                with colv1:
                    if st.button("🔎 Calculer la description VLM", key=f"vlm_only_{i}"):
                        try:
                            existing_desc = pick_desc_vlm(row_view)
                            if existing_desc:
                                st.info("Une description VLM est déjà disponible pour cette photo. Utilisez « Régénérer description VLM » pour forcer un nouveau calcul.")
                            else:
                                guide_src = (texte_com or texte_lib or "").strip()
                                desc_new = ensure_desc_vlm(
                                    i, row_view, guide_src=guide_src,
                                    photos_df=photos_df, photos_csv=photos_csv,
                                    infos=infos,
                                    mission=mission, context_system=context_system,
                                    context_user=context_user, vlm_system=vlm_system, vlm_user=vlm_user,
                                    force=False,
                                )
                                if desc_new:
                                    st.success("Description VLM calculée et enregistrée.")
                                    st.rerun()
                                else:
                                    vlm_status_now = str(photos_df.at[i, "vlm_ui_status"] if "vlm_ui_status" in photos_df.columns else "").strip()
                                    if vlm_status_now == "ERR_IMAGE_NOT_FOUND":
                                        st.warning("Impossible de calculer la description VLM : image introuvable côté laptop.")
                                    else:
                                        st.warning("VLM a répondu vide.")
                        except Exception as e:
                            _show_vlm_error(e)

                # 2) régénération forcée (NOUVEAU)
                with colv2:
                    if st.button("↻ Régénérer description VLM", key=f"vlm_force_{i}"):
                        try:
                            guide_src = (texte_com or texte_lib or "").strip()
                            desc_new = ensure_desc_vlm(
                                i, row_view, guide_src=guide_src,
                                photos_df=photos_df, photos_csv=photos_csv,
                                infos=infos,
                                mission=mission, context_system=context_system,
                                context_user=context_user, vlm_system=vlm_system, vlm_user=vlm_user,
                                force=True,
                            )
                            if desc_new:
                                st.success("Description VLM régénérée et enregistrée.")
                                st.rerun()
                            else:
                                st.warning("VLM a répondu vide.")
                        except Exception as e:
                            _show_vlm_error(e)




            #===============================================================================
            if unsync_mode:
                key_lib = f"libelle_{i}"
                key_com = f"commentaire_{i}"

                if key_lib not in st.session_state:
                    if nom_image in annotations_df["nom_fichier_image"].values:
                        st.session_state[key_lib] = annotations_df.loc[
                            annotations_df["nom_fichier_image"] == nom_image, "libelle"
                        ].iat[0]
                    else:
                        st.session_state[key_lib] = pick_libelle(row_view)   # ✅
                if key_com not in st.session_state:
                    if nom_image in annotations_df["nom_fichier_image"].values:
                        st.session_state[key_com] = annotations_df.loc[
                            annotations_df["nom_fichier_image"] == nom_image, "commentaire"
                        ].iat[0]
                    else:
                        st.session_state[key_com] = pick_commentaire(row_view)   # ✅


                libelle = st.text_input(
                    "🏷️ Libellé proposé",

                    value=_normalize_text(st.session_state.get(f"libelle_input_{i}", st.session_state.get(key_lib, "")), "libelle"),
                    key=f"libelle_input_{i}",
                )
                commentaire = st.text_area(
                    "📝 Commentaire proposé",
                    value=_normalize_text(st.session_state.get(f"commentaire_input_{i}", st.session_state.get(f"commentaire_{i}", "")), "commentaire"),
                    key=f"commentaire_input_{i}",
                )

            else:
                # === Mode synchronisé : extraits + marges + autosnap + audio + GPT ===
                lb = float(st.session_state.get("lib_av_input",  st.session_state.get("lib_avant",  0.5)))
                la = float(st.session_state.get("lib_ap_input",  st.session_state.get("lib_apres",  0.5)))
                cb = float(st.session_state.get("com_av_input",  st.session_state.get("com_avant",  1.0)))
                ca = float(st.session_state.get("com_ap_input",  st.session_state.get("com_apres",  1.0)))

                def _slice_text_dir(df, t0, before, after, prefer="both"):
                    r"""
                    Extrait le texte autour de t0 :
                    - soit via start_sec/end_sec (format Noota),
                    - soit via temps (format horodaté).
                    """
                    # 1) Mode intervalles (start/end)
                    if {"start_sec", "end_sec"}.issubset(df.columns):
                        win_start = t0 - before
                        win_end   = t0 + after

                        m = (df["end_sec"] >= win_start) & (df["start_sec"] <= win_end)
                        txt = df.loc[m, "texte"].astype(str).str.cat(sep=" ").strip()
                        if txt:
                            return txt

                        mid = (df["start_sec"] + df["end_sec"]) / 2.0
                        if prefer == "before":
                            prev = df.loc[mid < t0].tail(2)
                            return prev["texte"].astype(str).str.cat(sep=" ").strip()
                        if prefer == "after":
                            nxt = df.loc[mid >= t0].head(2)
                            return nxt["texte"].astype(str).str.cat(sep=" ").strip()

                        prev_row = df.loc[mid <= t0].tail(1)
                        next_row = df.loc[mid >= t0].head(1)
                        if not prev_row.empty and not next_row.empty:
                            prev_t = float(prev_row["start_sec"].iloc[0])
                            next_t = float(next_row["start_sec"].iloc[0])
                            return prev_row["texte"].iloc[0] if (t0 - prev_t) <= (next_t - t0) else next_row["texte"].iloc[0]
                        if not prev_row.empty:
                            return prev_row["texte"].iloc[0]
                        if not next_row.empty:
                            return next_row["texte"].iloc[0]
                        return ""

                    # 2) Mode horodatage (colonne "temps")
                    if "temps" in df.columns:
                        m = (df["temps"] >= t0 - before) & (df["temps"] <= t0 + after)
                        txt = df.loc[m, "texte"].astype(str).str.cat(sep=" ").strip()
                        if txt:
                            return txt

                        if prefer == "before":
                            prev = df.loc[df["temps"] < t0].tail(2)
                            return prev["texte"].astype(str).str.cat(sep=" ").strip()
                        if prefer == "after":
                            nxt = df.loc[df["temps"] >= t0].head(2)
                            return nxt["texte"].astype(str).str.cat(sep=" ").strip()

                        prev_row = df.loc[df["temps"] <= t0].tail(1)
                        next_row = df.loc[df["temps"] >= t0].head(1)
                        if not prev_row.empty and not next_row.empty:
                            prev_t = float(prev_row["temps"].iloc[0])
                            next_t = float(next_row["temps"].iloc[0])
                            return prev_row["texte"].iloc[0] if (t0 - prev_t) <= (next_t - t0) else next_row["texte"].iloc[0]
                        if not prev_row.empty:
                            return prev_row["texte"].iloc[0]
                        if not next_row.empty:
                            return next_row["texte"].iloc[0]
                        return ""

                    # 3) Repli : aucune des colonnes attendues
                    return ""

                # Fenêtres (tu les lis déjà dans st.session_state) 
                texte_lib = _slice_text_dir(trans_df, t0, lb, la, prefer="before")
                texte_com = _slice_text_dir(trans_df, t0, cb, ca, prefer="after")

                # Si identiques, on élargit légèrement le commentaire vers l'AP
                if texte_lib == texte_com:
                    texte_com = _slice_text_dir(trans_df, t0, cb, max(ca, ca + 1.0), prefer="after")

                # Nettoyage préfixes AVANT affichage/GPT
                texte_lib = _normalize_text(texte_lib, "libelle")
                texte_com = _normalize_text(texte_com, "commentaire")
                

                st.markdown("**Extrait libellé:**");     st.write(texte_lib or "_(vide)_")
                st.markdown("**Extrait commentaire:**"); st.write(texte_com or "_(vide)_")

                # =========================================================
                # VLM : lecture seule au chargement/rerun.
                # Aucun appel VLM automatique ici : seuls les boutons dédiés
                # peuvent déclencher ensure_desc_vlm / call_vlm_single.
                # =========================================================
                desc_vlm = pick_desc_vlm(row_view)


                #************************************************************************
                # --- Affiche les marges courantes autour de t0 ---
                cur_av = float(st.session_state.get("audio_av_input", audio_av))
                cur_ap = float(st.session_state.get("audio_ap_input", audio_ap))
                st.caption(f"⏱️ Marges actuelles — AV: {cur_av:.1f}s • AP: {cur_ap:.1f}s")

                # --- Boutons d’extension rapide ---
                c1, c2, c3, c4, c5 = st.columns(5)
                with c1:
                    if st.button("⏮ +2s AV", key=f"m2_{i}"):
                        st.session_state["audio_av_pending"] = max(0.0, cur_av + 2.0)
                        st.rerun()
                with c2:
                    if st.button("⏮ +5s AV", key=f"m5_{i}"):
                        st.session_state["audio_av_pending"] = max(0.0, cur_av + 5.0)
                        st.rerun()
                with c3:
                    st.button("⏯ Rejouer", key=f"replay_{i}")
                with c4:
                    if st.button("⏭ +2s AP", key=f"p2_{i}"):
                        st.session_state["audio_ap_pending"] = cur_ap + 2.0
                        st.rerun()
                with c5:
                    if st.button("⏭ +5s AP", key=f"p5_{i}"):
                        st.session_state["audio_ap_pending"] = cur_ap + 5.0
                        st.rerun()

                # --- Autosnap pour couvrir le premier texte avant/après t0 ---
                c6, c7 = st.columns(2)
                with c6:
                    if st.button("🧲 Inclure texte AV", key=f"autosnap_av_{i}"):
                        ts = _get_time_series(trans_df)
                        if ts is None:
                            st.warning("Autosnap indisponible : pas de colonne temps/start/end.")
                        else:
                            mask = ts <= t0
                            if mask.any():
                                t_near = float(ts[mask].max())
                                needed = max(0.0, t0 - t_near + 0.2)
                                if needed > cur_av:
                                    st.session_state["audio_av_pending"] = needed
                                    st.rerun()
                            else:
                                st.warning("Aucun texte avant t0.")

                with c7:
                    if st.button("🧲 Inclure texte AP", key=f"autosnap_ap_{i}"):
                        ts = _get_time_series(trans_df)
                        if ts is None:
                            st.warning("Autosnap indisponible : pas de colonne temps/start/end.")
                        else:
                            mask = ts >= t0
                            if mask.any():
                                t_near = float(ts[mask].min())
                                needed = max(0.0, t_near - t0 + 0.2)
                                if needed > cur_ap:
                                    st.session_state["audio_ap_pending"] = needed
                                    st.rerun()
                            else:
                                st.warning("Aucun texte après t0.")


                # --- Promouvoir les marges courantes en réglages globaux ---
                if st.button("📌 Utiliser ces marges comme réglages globaux", key=f"promote_glob_{i}"):
                    cur_av = float(st.session_state.get("audio_av_input", audio_av))
                    cur_ap = float(st.session_state.get("audio_ap_input", audio_ap))
                    infos["audio_av"] = cur_av
                    infos["audio_ap"] = cur_ap
                    sauvegarder_infos_projet(infos)
                    st.session_state["audio_av_pending"] = cur_av
                    st.session_state["audio_ap_pending"] = cur_ap
                    st.success("Réglages globaux mis à jour avec les marges courantes.")
                    st.rerun()

                # --- (Re)calcul fenêtre + lecture audio ---
                # --- (Re)calcul fenêtre audio (info uniquement, lecture via wavesurfer) ---
                cur_av = float(st.session_state.get("audio_av_input", audio_av))
                cur_ap = float(st.session_state.get("audio_ap_input", audio_ap))
                start = max(0, t0 - cur_av)
                end   = t0 + cur_ap

                st.write(f"Fenêtre audio : de {start:.2f}s à {end:.2f}s (lecture via le lecteur au-dessus).")

                # -----------------------------------------------------------------------------------------
                # Generation avec GPT du libellé et commenataire
                #-------------------------------------------------------------------------------------------
                
                # --- Boutons GPT (utiliser bien texte_lib / texte_com) ---
                gen_col, _ = st.columns(2)
                with gen_col:
                    current_dictee_for_gpt = _ui_text(
                        st.session_state.get(f"dictee_{i}") or row.get("dictee_asr_text")
                    )
                    current_dictee_status = _ui_text(row.get("dictee_asr_status"))
                    current_commentaire_for_gpt = _ui_text(
                        st.session_state.get(f"commentaire_input_{i}")
                        or st.session_state.get(f"commentaire_{i}")
                        or row.get("commentaire_propose_ui")
                        or row.get("commentaire_propose")
                        or row.get("commentaire_propose_batch")
                    )

                    # --- Regénérer LIBELLÉ ---
                    if st.button("↻ Régénérer libellé", key=f"regen_lab_{i}"):

                        extrait_lib = _normalize_text(texte_lib, "libelle")
                        extrait_com = _normalize_text(texte_com, "commentaire")
                        libelle_source_text, libelle_source_kind = _resolve_libelle_transcript_fallback(
                            extrait_lib=extrait_lib,
                            extrait_com=extrait_com,
                            dictee_text=current_dictee_for_gpt,
                            dictee_status=current_dictee_status,
                            commentaire_value=current_commentaire_for_gpt,
                        )
                        desc_vlm = pick_desc_vlm(row_view)

                        if not desc_vlm:
                            guide_src = (libelle_source_text or texte_lib or texte_com or "").strip()
                            desc_vlm = ensure_desc_vlm(
                                i, row_view, guide_src=guide_src,
                                photos_df=photos_df, photos_csv=photos_csv,
                                infos=infos,
                                mission=mission, context_system=context_system,
                                context_user=context_user, vlm_system=vlm_system, vlm_user=vlm_user
                            )
                            if not desc_vlm:
                                st.warning("VLM a répondu vide : libellé non généré pour cette photo.")
                                pass  # ou: pass, puis la logique externe ne génère pas


                        if libelle_source_text:
                            system_lib = _compose_system(prompts["libelle"].get("system"), context_system)
                            tpl_lib = str(prompts.get("libelle", {}).get("user", "") or "")

                            desc_vlm_safe = (desc_vlm or "").strip()
                            trans_safe    = (libelle_source_text or "").strip()
                            mission_safe  = (mission or "").strip()
                            ctx_safe      = (context_user or "").strip()

                            if "{{description_vlm}}" not in tpl_lib and desc_vlm_safe:
                                tpl_lib = "Description de la photo (éléments visibles uniquement) :\n{{description_vlm}}\n\n" + tpl_lib

                            dictee = (current_dictee_for_gpt or "").strip()

                            prompt_lib = (tpl_lib
                                .replace("{{description_vlm}}", desc_vlm_safe)
                                .replace("{{transcription}}", trans_safe)
                                .replace("{{mission}}", mission_safe)
                                .replace("{{contexte_general}}", ctx_safe)
                            )

                            if dictee:
                                prompt_lib += "\n\n[DICTÉE MICRO]\n" + dictee

                            if "{{transcription}}" in tpl_lib and not trans_safe:
                                st.warning("Transcription vide après normalisation (libellé).")

                            if libelle_source_kind != "extrait_lib":
                                st.info(f"Libellé généré avec source de secours : {libelle_source_kind}.")

                            raw = generer_texte_gpt(system_lib, prompt_lib)
                            runtime_message_handled = False
                            if _is_local_llm_busy_result(raw):
                                st.warning("LLM local occupe, reessayez dans quelques secondes.")
                                runtime_message_handled = True
                                new_lib = ""
                            elif _is_llm_runtime_message(raw):
                                st.warning(raw.strip()[1:-1])
                                runtime_message_handled = True
                                new_lib = ""
                            else:
                                new_lib = _post_clean_llm(raw, "libelle")

                            if (not runtime_message_handled) and (not new_lib or new_lib in ("*", "**")):
                                st.warning("⚠️ Libellé vide ou tronqué.")
                            elif not runtime_message_handled:
                                st.session_state[f"libelle_{i}"] = new_lib
                                st.session_state[f"libelle_input_{i}"] = new_lib
                                st.rerun()
                        else:
                            st.warning("⛔ Aucun texte utilisable pour le libellé : extrait, dictée, commentaire et extrait commentaire sont vides.")


                    # --- Regénérer COMMENTAIRE ---
                    if st.button("↻ Régénérer comment.", key=f"regen_com_{i}"):

                        extrait_com = _normalize_text(texte_com, "commentaire")
                        desc_vlm = pick_desc_vlm(row_view)

                        if not desc_vlm:
                            guide_src = (texte_com or texte_lib or "").strip()
                            desc_vlm = ensure_desc_vlm(
                                i, row_view, guide_src=guide_src,
                                photos_df=photos_df, photos_csv=photos_csv,
                                infos=infos,
                                mission=mission, context_system=context_system,
                                context_user=context_user, vlm_system=vlm_system, vlm_user=vlm_user
                            )
                            if not desc_vlm:
                                st.warning("VLM a répondu vide : commentaire non généré pour cette photo.")
                                pass

                        if extrait_com:
                            system_com = _compose_system(prompts["commentaire"].get("system"), context_system)
                            tpl_com = str(prompts.get("commentaire", {}).get("user", "") or "")

                            desc_vlm_safe = (desc_vlm or "").strip()
                            trans_safe    = (extrait_com or "").strip()
                            mission_safe  = (mission or "").strip()
                            ctx_safe      = (context_user or "").strip()

                            if "{{description_vlm}}" not in tpl_com and desc_vlm_safe:
                                tpl_com = (
                                    "Description de la photo (éléments visibles uniquement) :\n"
                                    "{{description_vlm}}\n\n" + tpl_com
                                )

                            dictee = (st.session_state.get(f"dictee_{i}") or "").strip()                         

                            points = detect_points_saillants(trans_safe)
                            points_saillants_txt = format_points_saillants(points)

                            prompt_com = (tpl_com
                                .replace("{{description_vlm}}", desc_vlm_safe)
                                .replace("{{transcription}}", trans_safe)
                                .replace("{{mission}}", mission_safe)
                                .replace("{{contexte_general}}", ctx_safe)
                                .replace("{{points_saillants}}", points_saillants_txt)
                            )

                            if dictee:
                                prompt_com += "\n\n[DICTÉE MICRO]\n" + dictee

                            raw = generer_texte_gpt(system_com, prompt_com)
                            runtime_message_handled = False
                            if _is_local_llm_busy_result(raw):
                                st.warning("LLM local occupe, reessayez dans quelques secondes.")
                                runtime_message_handled = True
                                new_com = ""
                            elif _is_llm_runtime_message(raw):
                                st.warning(raw.strip()[1:-1])
                                runtime_message_handled = True
                                new_com = ""
                            elif not runtime_message_handled:
                                new_com = _post_clean_llm(raw, "commentaire")

                            if (not runtime_message_handled) and (not new_com or new_com in ("*", "**")):
                                st.warning("⚠️ Commentaire vide ou tronqué.")
                            elif not runtime_message_handled:
                                st.session_state[f"commentaire_{i}"] = new_com
                                st.session_state[f"commentaire_input_{i}"] = new_com
                                st.rerun()
                        else:
                            st.warning("⛔ Aucun texte utilisable pour le commentaire (extrait vide).")


                    # --- Recalculer LIBELLÉ + COMMENTAIRE ---
                    recalculer = st.button("🔁 Recalculer avec GPT", key=f"recalc_{i}")
                    if recalculer:

                        extrait_lib = _normalize_text(texte_lib, "libelle")
                        extrait_com = _normalize_text(texte_com, "commentaire")
                        libelle_source_text, libelle_source_kind = _resolve_libelle_transcript_fallback(
                            extrait_lib=extrait_lib,
                            extrait_com=extrait_com,
                            dictee_text=current_dictee_for_gpt,
                            dictee_status=current_dictee_status,
                            commentaire_value=current_commentaire_for_gpt,
                        )
                        desc_vlm = pick_desc_vlm(row_view)
                        # (1) VLM si description absente
                        if not desc_vlm:
                            guide_src = (libelle_source_text or extrait_com or extrait_lib or "").strip()
                            desc_vlm = ensure_desc_vlm(
                                i, row_view, guide_src=guide_src,
                                photos_df=photos_df, photos_csv=photos_csv,
                                infos=infos,
                                mission=mission, context_system=context_system,
                                context_user=context_user, vlm_system=vlm_system, vlm_user=vlm_user
                            )
                            if not desc_vlm:
                                st.warning("⚠️ VLM indisponible : recalcul GPT poursuivi sans description photo.")
                                # pas de continue

                        # Valeurs sûres (jamais None)
                        desc_vlm_safe = (desc_vlm or "").strip()
                        mission_safe  = (mission or "").strip()
                        ctx_safe      = (context_user or "").strip()

                        dictee = (current_dictee_for_gpt or "").strip()
                        local_request_blocked = False

                        # --- Libellé ---
                        if libelle_source_text:
                            system_lib = _compose_system(prompts["libelle"].get("system"), context_system)
                            tpl_lib = str(prompts.get("libelle", {}).get("user", "") or "")

                            trans_lib_safe = (libelle_source_text or "").strip()

                            # Compat : si le template ne prévoit pas description_vlm, on le préfixe
                            if "{{description_vlm}}" not in tpl_lib and desc_vlm_safe:
                                tpl_lib = (
                                    "Description de la photo (éléments visibles uniquement) :\n"
                                    "{{description_vlm}}\n\n" + tpl_lib
                                )


                            prompt_lib = (tpl_lib
                                .replace("{{description_vlm}}", desc_vlm_safe)
                                .replace("{{transcription}}", trans_lib_safe)
                                .replace("{{mission}}", mission_safe)
                                .replace("{{contexte_general}}", ctx_safe)
                            )

                            if dictee:
                                prompt_lib += "\n\n[DICTÉE MICRO]\n" + dictee

                            raw = generer_texte_gpt(system_lib, prompt_lib)
                            if _is_local_llm_busy_result(raw):
                                st.warning("LLM local occupe, reessayez dans quelques secondes.")
                                local_request_blocked = True
                                new_lib = ""
                            elif _is_llm_runtime_message(raw):
                                st.warning(raw.strip()[1:-1])
                                local_request_blocked = True
                                new_lib = ""
                            elif not local_request_blocked:
                                new_lib = _post_clean_llm(raw, "libelle")

                            if new_lib and new_lib not in ("*", "**"):
                                st.session_state[f"libelle_{i}"] = new_lib
                                st.session_state[f"libelle_input_{i}"] = new_lib
                                photos_df.at[i, "libelle_propose_ui"] = new_lib
                                photos_df.at[i, "libelle_ui_status"] = "OK"
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                photos_df.at[i, "libelle_ui_ts"] = now
                                photos_df.at[i, "ui_ts"] = now
                                _persist_photos_csv(
                                    photos_df,
                                    photos_csv,
                                    infos,
                                    reason="gpt_libelle",
                                    photo_rel_native=_photo_rel_at(photos_df, i),
                                )
                                if libelle_source_kind != "extrait_lib":
                                    st.info(f"Libellé recalculé avec source de secours : {libelle_source_kind}.")
                            elif not local_request_blocked:
                                st.warning("⛔ Libellé non recalculé : sortie vide / tronquée.")
                        else:
                            st.warning("⛔ Libellé non recalculé : aucune source exploitable (extrait, dictée, commentaire, extrait commentaire).")

                        # --- Commentaire ---
                        if (not local_request_blocked) and extrait_com:
                            system_com = _compose_system(prompts["commentaire"].get("system"), context_system)
                            tpl_com = str(prompts.get("commentaire", {}).get("user", "") or "")

                            desc_vlm_safe = (desc_vlm or "").strip()
                            trans_safe    = (extrait_com or "").strip()
                            mission_safe  = (mission or "").strip()
                            ctx_safe      = (context_user or "").strip()

                            if "{{description_vlm}}" not in tpl_com and desc_vlm_safe:
                                tpl_com = (
                                    "Description de la photo (éléments visibles uniquement) :\n"
                                    "{{description_vlm}}\n\n" + tpl_com
                                )

                            points = detect_points_saillants(trans_safe)
                            points_saillants_txt = format_points_saillants(points)

                            prompt_com = (tpl_com
                                .replace("{{description_vlm}}", desc_vlm_safe)
                                .replace("{{transcription}}", trans_safe)
                                .replace("{{mission}}", mission_safe)
                                .replace("{{contexte_general}}", ctx_safe)
                                .replace("{{points_saillants}}", points_saillants_txt)
                            )

                            if dictee:
                                prompt_com += "\n\n[DICTÉE MICRO]\n" + dictee

                            raw = generer_texte_gpt(system_com, prompt_com)
                            if _is_local_llm_busy_result(raw):
                                st.warning("LLM local occupe, reessayez dans quelques secondes.")
                                local_request_blocked = True
                                new_com = ""
                            elif _is_llm_runtime_message(raw):
                                st.warning(raw.strip()[1:-1])
                                local_request_blocked = True
                                new_com = ""
                            else:
                                new_com = _post_clean_llm(raw, "commentaire")

                            if (not local_request_blocked) and (not new_com or new_com in ("*", "**")):
                                st.warning("⚠️ Commentaire vide ou tronqué.")
                            elif not local_request_blocked:
                                st.session_state[f"commentaire_{i}"] = new_com
                                st.session_state[f"commentaire_input_{i}"] = new_com
                                photos_df.at[i, "commentaire_propose_ui"] = new_com
                                photos_df.at[i, "commentaire_ui_status"] = "OK"
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                photos_df.at[i, "commentaire_ui_ts"] = now
                                photos_df.at[i, "ui_ts"] = now
                                photo_dirty = True
                                if photo_dirty:
                                    _persist_photos_csv(
                                        photos_df,
                                        photos_csv,
                                        infos,
                                        reason="gpt_commentaire",
                                        photo_rel_native=_photo_rel_at(photos_df, i),
                                    )
                                st.rerun()                                

                        elif not local_request_blocked:
                            st.warning("⛔ Aucun texte utilisable pour le commentaire (extrait vide).")

                    # --- Dictée micro : ASR -> aide libellé/commentaire ---
                    dictation_nav_feedback = _ui_text(st.session_state.pop("dictation_nav_feedback", ""))
                    if dictation_nav_feedback:
                        st.success(dictation_nav_feedback)

                    dictee_expanded = _is_dictee_pending(row.get("dictee_asr_status")) or (
                        _ui_text(st.session_state.get(f"dictee_feedback_{i}")) == "pending"
                    )
                    with st.expander("🎙️ Dictée micro → proposer libellé & commentaire", expanded=dictee_expanded):
                        persisted_dictee_text = _ui_text(row.get("dictee_asr_text"))
                        persisted_dictee_status = _ui_text(row.get("dictee_asr_status"))
                        persisted_dictee_ts = _ui_text(row.get("dictee_asr_ts"))
                        persisted_audio_path = _ui_text(row.get("dictee_audio_path_pcfixe"))
                        persisted_dictee_csv_path = _ui_text(row.get("dictee_asr_csv_path_pcfixe"))
                        persisted_dictee_photo_csv_path = _ui_text(row.get("dictee_asr_photo_csv_path_pcfixe"))
                        has_persisted_audio = bool(persisted_audio_path)
                        has_persisted_text = bool(persisted_dictee_text)

                        current_dictee_text = _ui_text(
                            st.session_state.get(f"dictee_{i}") or persisted_dictee_text
                        )
                        st.session_state[f"dictee_{i}"] = current_dictee_text
                        has_current_dictee_text = bool(current_dictee_text)

                        dictee_feedback = _ui_text(st.session_state.pop(f"dictee_feedback_{i}", ""))
                        if dictee_feedback == "submitted":
                            st.success("✓ Dictée enregistrée — transcription en attente")
                        elif dictee_feedback == "local_pending":
                            st.success("✓ Dictée enregistrée localement — en attente de soumission")
                        elif dictee_feedback == "success":
                            st.success("Dictée transcrite.")
                        elif dictee_feedback == "empty":
                            st.warning("Dictee traitee, mais aucun texte ASR n'a ete renvoye.")

                        if persisted_dictee_status or has_persisted_audio or has_persisted_text:
                            meta = []
                            if persisted_dictee_status:
                                meta.append(f"statut={persisted_dictee_status}")
                            if persisted_dictee_ts:
                                meta.append(f"horodatage={persisted_dictee_ts}")
                            if has_persisted_audio:
                                meta.append("audio serveur present")
                            if has_persisted_text:
                                meta.append("texte ASR disponible")
                            st.caption("Derniere dictee connue : " + " | ".join(meta))

                        st.text_area("Texte dicté (ASR)", value=current_dictee_text, height=120, disabled=True)
                        if persisted_dictee_status in {"LOCAL_PENDING", "SUBMITTED", "PENDING"}:
                            st.info("⏳ Dictée enregistrée. Utilisez les boutons globaux pour soumettre ou rafraîchir les transcriptions.")
                        elif persisted_dictee_status == "BUSY":
                            st.warning("ASR occupé : la dictée est conservée et sera reprise par le batch.")
                        elif persisted_dictee_status == "OK" and has_current_dictee_text:
                            st.success("✅ Transcription disponible")
                            st.info("Le texte dicté affiché ci-dessus est la source actuellement réutilisée dans les prompts GPT pour proposer le libellé et le commentaire.")
                        elif persisted_dictee_status == "ERR":
                            st.error("❌ Transcription échouée")
                            if persisted_dictee_csv_path or persisted_dictee_photo_csv_path:
                                st.caption("Des fichiers ASR existent côté serveur, mais aucun texte exploitable n'a pu être relu.")
                        elif has_persisted_audio:
                            st.warning("Une ancienne dictée audio existe, mais aucun texte transcrit n'est actuellement disponible.")
                        else:
                            st.caption("Aucune dictée exploitable n'est actuellement disponible.")

                        photo_key_for_widget = _safe_id_part(_photo_stable_key(row, i), f"photo_{i}")
                        mic_nonce_key = f"mic_nonce_{photo_key_for_widget}"
                        saved_audio_sha_key = f"mic_saved_sha_{photo_key_for_widget}"
                        st.session_state.setdefault(mic_nonce_key, 0)
                        audio_in = st.audio_input(
                            "Enregistrer (micro)",
                            key=f"mic_{photo_key_for_widget}_{st.session_state[mic_nonce_key]}",
                        )
                        has_new_audio = audio_in is not None
                        live_audio_diag = None
                        live_audio_diag_error = ""
                        if has_new_audio:
                            try:
                                live_audio_diag = _analyze_audio_bytes(audio_in.getvalue())
                            except Exception as e:
                                live_audio_diag_error = str(e)

                        if live_audio_diag_error:
                            st.error(f"Diagnostic audio impossible : {live_audio_diag_error}")
                        elif live_audio_diag:
                            verdict_text, verdict_level = _audio_diag_verdict(live_audio_diag)
                            diag_msg = (
                                f"Diagnostic micro : durée={live_audio_diag['duration_s']:.2f}s | "
                                f"fréquence={live_audio_diag['sample_rate']} Hz | "
                                f"canaux={live_audio_diag['channels']} | "
                                f"RMS={live_audio_diag['rms']:.6f} | "
                                f"peak={live_audio_diag['peak']:.6f} | "
                                f"verdict={verdict_text}"
                            )
                            if verdict_level == "success":
                                st.success(diag_msg)
                            elif verdict_level == "warning":
                                st.warning(diag_msg)
                            else:
                                st.error(diag_msg)
                                st.info(
                                    "Le problème vient probablement de la capture micro côté navigateur : "
                                    "vérifiez le micro sélectionné dans le navigateur, les permissions micro du site, "
                                    "testez un autre périphérique d'entrée et fermez les autres applications "
                                    "susceptibles de monopoliser le micro."
                                )
                        next_non_validated_idx = _next_non_validated_photo_index(
                            photos_df,
                            annoted_names,
                            start_after=i,
                        )
                        if edit_mode == "Séquentiel (sécurisé)":
                            if st.button(
                                "➡️ Passer à la photo suivante",
                                key=f"seq_next_non_validating_{i}",
                                disabled=next_non_validated_idx is None,
                                help="Navigue sans valider la photo courante et sans attendre l'ASR.",
                            ):
                                if next_non_validated_idx is not None:
                                    try:
                                        _record, _submitted, dictation_save_status = _persist_current_micro_dictation(
                                            audio_in=audio_in,
                                            row=row,
                                            ui_index=i,
                                            infos=infos,
                                            photos_df=photos_df,
                                            photos_csv=photos_csv,
                                            mic_nonce_key=mic_nonce_key,
                                            saved_audio_sha_key=saved_audio_sha_key,
                                            submit_to_pcfixe=False,
                                        )
                                        if dictation_save_status == "persisted":
                                            st.session_state["dictation_nav_feedback"] = (
                                                "✓ Dictée de la photo précédente enregistrée localement"
                                            )
                                        if dictation_save_status in {"absent", "already_saved", "persisted"}:
                                            st.session_state["seq_current_index"] = int(next_non_validated_idx)
                                            st.rerun()
                                    except Exception as e:
                                        _mark_current_dictation_error(photos_df, photos_csv, infos, i, e)
                                        st.error(f"Dictée non enregistrée : {e}")
                                        st.info(
                                            "La photo courante reste affichée pour éviter de perdre une dictée non sauvegardée."
                                        )
                            if next_non_validated_idx is None:
                                st.caption("Aucune autre photo non validée.")
                        st.caption("Le bouton ci-dessous enregistre la dictée et tente une soumission courte au spooler PC fixe. Aucune transcription Voxtral n'est attendue dans l'interface.")
                        try:
                            project_id, _pcfixe_preview = _require_server_project_context(infos)
                        except Exception as e:
                            project_id = ""
                            st.warning(str(e))

                        if project_id:
                            if st.button(
                                "Enregistrer cette dictée",
                                key=f"mic_go_{i}",
                                disabled=not has_new_audio,
                                help="Enregistrez d'abord un nouvel audio micro.",
                            ):
                                try:
                                    if audio_in is None:
                                        if has_current_dictee_text:
                                            st.info("Aucun nouvel audio enregistré. Le dernier texte dicté persistant reste affiché ci-dessus. Il restera réutilisable par les prompts GPT, mais aucune nouvelle transcription n'est lancée sans nouvel enregistrement.")
                                        elif has_persisted_audio:
                                            st.warning("Aucun nouvel audio enregistré. Une ancienne dictée audio existe, mais aucun texte transcrit n'est actuellement disponible.")
                                        else:
                                            st.warning("Aucune dictée exploitable n'est actuellement disponible.")
                                    else:
                                        _record, submitted, dictation_save_status = _persist_current_micro_dictation(
                                            audio_in=audio_in,
                                            row=row,
                                            ui_index=i,
                                            infos=infos,
                                            photos_df=photos_df,
                                            photos_csv=photos_csv,
                                            mic_nonce_key=mic_nonce_key,
                                            saved_audio_sha_key=saved_audio_sha_key,
                                        )

                                        if dictation_save_status == "persisted":
                                            st.session_state[f"dictee_feedback_{i}"] = "submitted" if submitted else "local_pending"
                                        elif dictation_save_status == "already_saved":
                                            st.session_state[f"dictee_feedback_{i}"] = (
                                                "submitted"
                                                if _ui_text(photos_df.at[i, "dictee_asr_status"]).upper() == "SUBMITTED"
                                                else "local_pending"
                                            )
                                        st.session_state["seq_override_index"] = int(i)
                                        st.rerun()

                                except Exception as e:
                                    _mark_current_dictation_error(photos_df, photos_csv, infos, i, e)
                                    st.error(f"Erreur dictée/ASR : {e}")
                   


                    if st.button("↩️ Revenir au batch", key=f"back_batch_{i}"):
                        # 1) vider les colonnes UI persistées
                        for c in (
                            "description_vlm_ui",
                            "libelle_propose_ui",
                            "commentaire_propose_ui",
                            "vlm_ui_status",
                            "vlm_ui_ts",
                        ):
                            if c in photos_df.columns:
                                photos_df.at[i, c] = ""

                        # 2) PURGE session_state pour forcer ré-init depuis batch
                        for k in (
                            f"libelle_input_{i}", f"commentaire_input_{i}",
                            f"libelle_{i}", f"commentaire_{i}",
                            f"reuse_prev_{i}", f"reuse_applied_{i}",
                        ):
                            if k in st.session_state:
                                del st.session_state[k]

                        _persist_photos_csv(
                            photos_df,
                            photos_csv,
                            infos,
                            reason="back_to_batch",
                            photo_rel_native=_photo_rel_at(photos_df, i),
                        )
                        st.rerun()


                # --- Afficher les transcriptions utilisées (utile en mode sync) ---
                with st.expander("🔍 Transcription utilisée pour le libellé"):
                    st.write(texte_lib or "*(aucune)*")
                with st.expander("🔍 Transcription utilisée pour le commentaire"):
                    st.write(texte_com or "*(aucune)*")




        # --------------------------------------------------------------------------------------------------   
        # texte_lib / texte_com ont déjà été calculés plus haut avec fallback.
        # (On n’écrase plus ces valeurs ici.)
        #
        # ─── Initialisation des valeurs dans session_state si elles n’existent pas
        if not unsync_mode:
            # 1) Clés de mémoire et de saisie
            key_lib       = f"libelle_{i}"
            key_com       = f"commentaire_{i}"
            key_lib_input = f"libelle_input_{i}"
            key_com_input = f"commentaire_input_{i}"

            # 📌 Cas particulier : nouvelle photo en mode séquentiel


            # Annotation déjà enregistrée pour cette photo ?
            deja_annotee = not row_ann.empty

             # 3) mémoire libelle_i / commentaire_i
            if key_lib not in st.session_state:
                if deja_annotee:
                    st.session_state[key_lib] = row_ann["libelle"].iloc[0] or ""
                else:
                    st.session_state[key_lib] = pick_libelle(row_view)

            if key_com not in st.session_state:
                if deja_annotee:
                    st.session_state[key_com] = row_ann["commentaire"].iloc[0] or ""
                else:
                    st.session_state[key_com] = pick_commentaire(row_view)


            # Nettoyage des guillemets éventuels
            if isinstance(st.session_state.get(key_lib), str):
                st.session_state[key_lib] = _strip_wrapping_quotes(st.session_state[key_lib])


            # ---  Checkbox "Utiliser le libellé précédent" (tous modes, si i > 0) ---
            reuse = False
             # 4) Checkbox "Utiliser le libellé précédent"
            if i > 0:
                reuse_key = f"reuse_prev_{i}"
                if reuse_key not in st.session_state:
                    st.session_state[reuse_key] = False
                reuse = st.checkbox("🔁 Utiliser le libellé précédent", key=reuse_key)

            # Si la case est cochée, on copie UNE FOIS le libellé/commentaire de la photo précédente
            if reuse and i > 0:
                applied_key = f"reuse_applied_{i}"
                if not st.session_state.get(applied_key, False):
                    nom_prec = photos_df.iloc[i - 1]["nom_fichier_image"]
                    row_prec = annotations_df[annotations_df["nom_fichier_image"] == nom_prec]
                    if not row_prec.empty:
                        lib_prec = row_prec["libelle"].iloc[0] or ""
                        com_prec = row_prec["commentaire"].iloc[0] or ""
                        st.session_state[key_lib_input] = _normalize_text(lib_prec, "libelle")
                        st.session_state[key_com_input] = _normalize_text(com_prec, "commentaire")
                    st.session_state[applied_key] = True


            # 5) Initialisation finale des champs
            init_lib = _normalize_text(st.session_state.get(key_lib, ""), "libelle")
            init_com = _normalize_text(st.session_state.get(key_com, ""), "commentaire")

            if key_lib_input not in st.session_state:
                st.session_state[key_lib_input] = init_lib
            if key_com_input not in st.session_state:
                st.session_state[key_com_input] = init_com

            # Champs visibles
            libelle = st.text_input("🏷️ Libellé proposé", key=key_lib_input)
            commentaire = st.text_area("📝 Commentaire proposé", key=key_com_input)



        # Bouton d’enregistrement (gère synchro ET hors-synchro)
        if st.button(f"💾 Enregistrer l’annotation pour Photo {i + 1}", key=f"save_{i}"):
            annotation_validee = 1
            retenue = bool(st.session_state.get(f"retenue_{i}", True))

            if t0 < 0:
            # Hors synchro : pas d'audio, pas d'extraits
                audio_fields = {
                    "t_audio_sec": "",
                    "audio_timecode_hms": "",
                    "audio_datetime_abs": "",
                    "audio_start_sec": "",
                    "audio_end_sec": "",
                }
                texte_lib_to_save = ""
                texte_com_to_save = ""
            else:
                # Synchro : calcul des bornes audio + timecode
                cur_av = float(st.session_state.get("audio_av_input", projet["audio_av"]))
                cur_ap = float(st.session_state.get("audio_ap_input", projet["audio_ap"]))
                start  = max(0.0, t_ref - cur_av)
                end    = t_ref + cur_ap

                def hms_millis(sec: float) -> str:
                    ms = int(round((float(sec) - int(sec)) * 1000))
                    return f"{str(timedelta(seconds=int(sec)))}.{ms:03d}"
                
                audio_fields = {
                    "t_audio_sec": t_ref,
                    "audio_timecode_hms": hms_millis(t_ref),
                    "audio_datetime_abs": (audio0_dt + timedelta(seconds=t_ref)).strftime("%Y-%m-%d %H:%M:%S"),
                    "audio_start_sec": start,
                    "audio_end_sec": end,
                }


                # En mode synchro, on sauvegarde aussi les extraits utilisés
                texte_lib_to_save = texte_lib
                texte_com_to_save = texte_com

            # Construction de la ligne (commune aux 2 cas)
            ligne = {
                "nom_fichier_image": nom_image,
                "horodatage_photo": row["horodatage_photo"],
                "orientation_photo": int(st.session_state.get(f"orientation_{i}", int(row.get("orientation_photo", 0) or 0))),
                "transcription_libelle": texte_lib_to_save,
                "libelle": st.session_state.get(f"libelle_input_{i}", ""),
                "retenue": retenue,
                "transcription_commentaire": texte_com_to_save,
                "commentaire": st.session_state.get(f"commentaire_input_{i}", ""),
                "chemin_photo_reduite": row["chemin_photo_reduite"],
                 **audio_fields,
                "annotation_validee": 1,
            }

            # -- ÉCRITURE FICHIERS + PROGRESSION --
            annotations_df = annotations_df[annotations_df["nom_fichier_image"] != nom_image]
            annotations_df = pd.concat([annotations_df, pd.DataFrame([ligne])], ignore_index=True)
            annotations_df = annotations_df.reindex(columns=ANNOT_COLS)
            annotation_operation_id = f"annotation_saved-{datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:8]}"
            try:
                publish_state = _write_and_publish_validated_annotations(
                    annotations_df,
                    annotations_path,
                    infos,
                    operation_id=annotation_operation_id,
                )
                csv_state = publish_state.get("csv", {})
                xlsx_state = publish_state.get("xlsx", {})
                if publish_state.get("partial"):
                    st.warning("Publication NAS partielle des exports GTP : CSV/XLSX incohérents, reprise en attente.")
                elif csv_state.get("conflict") or xlsx_state.get("conflict"):
                    st.error("Conflit NAS sur un export GTP : aucune écriture divergente n'a été écrasée.")
                elif csv_state.get("pending") or xlsx_state.get("pending"):
                    st.warning("Enregistré localement — publication NAS en attente")
                else:
                    st.info("Export GTP CSV/XLSX publié localement et sur le NAS.")
            except Exception as e:
                st.error(f"Export GTP impossible : {e}")
                st.stop()

            # Persister la rotation dans le CSV photos
            if "orientation_photo" in photos_df.columns:
                photos_df.at[i, "orientation_photo"] = int(st.session_state[f"orientation_{i}"])
                photo_dirty = True
            
            photos_df.at[i, "annotation_validee"] = 1
            photo_dirty = True


            # Progression: "index" designe la derniere photo enregistree.
            # En session interactive, seq_current_index reste l'autorite de navigation.
            prev_index = None
            try:
                with open("data/progression_annotation.json", "r", encoding="utf-8") as f:
                    prev_index = json.load(f).get("index")
            except Exception:
                prev_index = None

            if st.session_state.get("edit_mode") == "Réédition libre (expert)":
                new_index = prev_index if (prev_index is not None and i < prev_index) else i
            else:
                new_index = i

            progression = {
                "derniere_photo_traitee": nom_image,
                "index": new_index,
                "total": len(photos_df),
                "terminé": (new_index + 1 == len(photos_df)) if new_index is not None else False
            }

            if photo_dirty:
                _persist_photos_csv(
                    photos_df,
                    photos_csv,
                    infos,
                    reason="annotation_saved",
                    photo_rel_native=_photo_rel_at(photos_df, i),
                    operation_id=annotation_operation_id,
                )

            os.makedirs("data", exist_ok=True)
            with open("data/progression_annotation.json", "w", encoding="utf-8") as f:
                json.dump(progression, f, indent=2, ensure_ascii=False)

            st.success("💾 Annotation enregistrée et progression mise à jour.")
            
            st.session_state[f"annotation_saved_local_{i}"] = True

        if st.session_state.get("edit_mode") == "Séquentiel (sécurisé)" and (is_annotated or st.session_state.get(f"annotation_saved_local_{i}", False)):
            next_idx = i + 1 if i + 1 < len(photos_df) else None
            prev_idx = i - 1 if i > 0 else None
            nav_prev, nav_next = st.columns(2)
            with nav_prev:
                if prev_idx is not None and st.button(
                    "⬅️ Photo précédente",
                    key=f"seq_prev_after_save_{i}",
                ):
                    st.session_state["seq_current_index"] = int(prev_idx)
                    st.rerun()
            with nav_next:
                if next_idx is not None:
                    if st.button(
                        "➡️ Photo suivante",
                        key=f"seq_next_after_save_{i}",
                    ):
                        st.session_state["seq_current_index"] = int(next_idx)
                        st.rerun()
                else:
                    st.caption("Dernière photo atteinte.")



#            # Optionnel en séquentiel : passer automatiquement à la suivante
#            if st.session_state.get("edit_mode") == "Séquentiel (sécurisé)" and i + 1 < len(photos_df):
#                if st.button("➡️ Passer à la photo suivante"):
#                    st.session_state["photo_index_actuel"] = i + 1
#                    st.rerun() 
#
