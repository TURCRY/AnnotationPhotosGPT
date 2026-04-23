#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
batch_all_photos_pcfixe.py

PASS 1 : VLM (description_vlm_batch) en batch
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

import time
from dataclasses import dataclass
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

  # traçabilité exécution
  "batch_status",     # OK / ERR / SKIP / EMPTY
  "batch_id",
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


def purge_vlm(base_url: str, api_key: str, *, timeout: int = 30, wait_step: float = 1.0) -> bool:
    """
    Demande au serveur Flask de purger le VLM (libérer VRAM / éviter rémanence VLM->LLM).
    - Retourne True si purge ok.
    - Retourne False si timeout (VLM resté busy) ou erreur non récupérable.
    """
    url = base_url.rstrip("/") + "/vision/purge_vlm"
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

def load_transcription(path: Path) -> List[TransRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f, delimiter=";")
        out = []
        for row in r:
            t = safe_float(row.get("start"))
            txt = (row.get("text") or "").strip()
            if t is not None and txt:
                spk = (row.get("speaker") or "").strip()
                if spk:
                    txt = f"{spk}: {txt}"
                out.append(TransRow(t, txt))
        out.sort(key=lambda x: x.t)
        return out

def extract_transcript_window(trs, center, before, after, max_chars=2000) -> str:
    parts = [tr.text for tr in trs if center-before <= tr.t <= center+after]
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
    url = base_url.rstrip("/") + "/vision/describe_batch"
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
    ap.add_argument("--rerun-weak", type=int, default=0)
    ap.add_argument("--rerun-weak-backend", default="same")


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
    only_new_dictee = bool(args.only_new_dictee)
    rerun_weak = bool(args.rerun_weak)
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
        write_json(infos_path, infos)



    def get_window(infos: dict, cfg: dict, key: str, default_before: float, default_after: float) -> tuple[float, float]:
        # 1) priorité à infos_projet.json (réglage par affaire)
        plages = (infos.get("plages_utilisees") or {})
        if key in plages:
            b = plages[key].get("avant", plages[key].get("before"))
            a = plages[key].get("apres", plages[key].get("after"))
            if b is not None and a is not None:
                return float(b), float(a)

        # 2) sinon config_llm.json default_delays
        dd = (cfg.get("default_delays") or {}).get(key) or {}
        b = dd.get("before")
        a = dd.get("after")
        if b is not None and a is not None:
            return float(b), float(a)

        # 3) fallback
        return float(default_before), float(default_after)

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

    cfg_llm = read_json(Path(pc["config_llm"]))

    lib_before, lib_after = get_window(infos, cfg_llm, "libelle", 45, 30)
    com_before, com_after = get_window(infos, cfg_llm, "commentaire", 90, 60)


    photos_csv = Path(pc["fichier_photos"])
    batch_path_str = str(pc.get("fichier_photos_batch") or "").strip()
    photos_batch_csv = Path(batch_path_str) if batch_path_str else photos_csv.with_name(photos_csv.stem + "_batch.csv")
    log.info("Preflight paths photos_csv=%s photos_batch_csv=%s", str(photos_csv), str(photos_batch_csv))
    print(f"[PREFLIGHT] photos_csv={photos_csv}")
    print(f"[PREFLIGHT] photos_batch_csv={photos_batch_csv}")
    if not photos_csv.exists():
        raise FileNotFoundError(f"photos.csv PC fixe introuvable: {photos_csv}")
    batch_rows = load_or_init_batch(photos_batch_csv)
    batch_index = {r["photo_rel_native"]: r for r in batch_rows if r.get("photo_rel_native")}


    trans_csv  = Path(pc["fichier_transcription"])
    ctx_path   = Path(pc["fichier_contexte_general"])
    cfg_llm    = read_json(Path(pc["config_llm"]))
    ctx_general_vlm = {
        "mission": str(infos.get("mission") or "").strip(),
        "system": str(infos.get("system") or "").strip(),
        "user": str(infos.get("user") or "").strip(),
        "vlm_system": str(infos.get("vlm_system") or "").strip(),
        "vlm_user": str(infos.get("vlm_user") or "").strip(),
    }
    if ctx_path.exists():
        try:
            ctx_data_vlm = read_json(ctx_path)
            ctx_general_vlm["mission"] = str(ctx_data_vlm.get("mission") or ctx_general_vlm["mission"]).strip()
            ctx_general_vlm["system"] = str(ctx_data_vlm.get("system") or ctx_general_vlm["system"]).strip()
            ctx_general_vlm["user"] = str(ctx_data_vlm.get("user") or ctx_general_vlm["user"]).strip()
            ctx_general_vlm["vlm_system"] = str(ctx_data_vlm.get("vlm_system") or ctx_general_vlm["vlm_system"]).strip()
            ctx_general_vlm["vlm_user"] = str(ctx_data_vlm.get("vlm_user") or ctx_general_vlm["vlm_user"]).strip()
        except Exception:
            pass
    vlm_context_global = build_vlm_context(ctx_general_vlm)

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
        # éventuellement d'autres champs UI si vous voulez les garantir
    }

    ui_fieldnames = ensure_columns(rows_ui, UI_DEFAULTS)

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
    base_url = str(local_cfg.get("base_url", "") or "").strip()
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


    prompts_dir = Path(pc["config_llm"]).resolve().parent  # ou le dossier où sont les prompts
    p_batch = prompts_dir / "prompt_gpt_batch_only.json"
    p_ui = prompts_dir / "prompt_gpt.json"

    prompts = read_json(p_batch) if p_batch.exists() else read_json(p_ui)

    sys_lib = prompts["libelle"]["system"]
    usr_lib = prompts["libelle"]["user"]
    sys_com = prompts["commentaire"]["system"]
    usr_com = prompts["commentaire"]["user"]

    delays = cfg_llm.get("default_delays") or {}
    lib_before = float((delays.get("libelle") or {}).get("before", 45))
    lib_after  = float((delays.get("libelle") or {}).get("after", 30))
    com_before = float((delays.get("commentaire") or {}).get("before", 90))
    com_after  = float((delays.get("commentaire") or {}).get("after", 60))

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
        if safe_float(row.get("t_audio")) is None:
            reject("t_audio_absent")
            continue

        photo_key = (row.get("photo_rel_native") or "").strip()
        if not photo_key:
            reject("photo_rel_native_absent")
            continue
        b = get_batch_row(batch_index, photo_key)

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
    print(f"[LIMIT] sélection={len(selected_idx)} / limit={args.limit or 0} indices={selected_idx}")

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

    if is_dry:
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

    ok_purge = purge_vlm(base_url, local_llm_api_key, timeout=30, wait_step=1.0)
    if not ok_purge:
        raise RuntimeError("Purge VLM impossible (VLM busy trop longtemps ou erreur serveur).")



    # -------------------------
    # PASS 2 — LLM (libellé / commentaire)
    # -------------------------


    # 0) contexte/mission (inchangé)
    ctx_general = read_json(ctx_path)
    contexte_general_str = json.dumps(ctx_general, ensure_ascii=False, indent=2)
    mission = str(infos.get("mission") or ctx_general.get("mission") or "")

    # 1) charger prompts batch si présent sinon UI
    prompts_dir = Path(pc["config_llm"]).resolve().parent  # même dossier que config_llm.json
    p_batch = prompts_dir / "prompt_gpt_batch_only.json"
    p_ui    = prompts_dir / "prompt_gpt.json"
    prompts = read_json(p_batch) if p_batch.exists() else read_json(p_ui)

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

    
    def build_prompt_with_desc_compat(user_template: str, final_prompt: str, desc_vlm: str) -> str:
        """
        Compat UI :
        - Si le template ne contient pas {{description_vlm_batch}}, on préfixe une section Description.
        - Sinon, rien à faire (déjà injecté via mapping).
        """
        if "{{description_vlm_batch}}" in (user_template or ""):
            return final_prompt
        desc = (desc_vlm or "").strip()
        if not desc:
            return final_prompt
        prefix = "Description de la photo (éléments visibles uniquement) :\n" + desc + "\n\n"
        return prefix + final_prompt

    done_llm = 0

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
        libelle_weak_existing = bool(lib_existing) and is_weak_libelle(lib_existing)
        commentaire_weak = (bs == "OK_LIB_COM_WEAK")
        weak_target = (bs == "WEAK_LIB") or commentaire_weak
        if rerun_weak and not weak_target:
            continue
        rerun_lib = bool(rerun_weak and bs == "WEAK_LIB")
        rerun_com = bool(rerun_weak and commentaire_weak)
        if bs.startswith("OK") and lib_existing:
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
        if t is None:
            b["batch_status"] = "SKIP_t_audio_absent"
            b["batch_ts"] = now_ts()
            n_skip += 1; n_done += 1
            continue

        # à partir d’ici : on VA tenter le LLM => consomme le quota
        done_llm += 1

        # 1) fenêtres transcription
        trans_lib = extract_transcript_window(trs, t, lib_before, lib_after, max_chars=2000)
        trans_com = extract_transcript_window(trs, t, com_before, com_after, max_chars=2000)

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

        lib_dictee_block = "" if libelle_seed_source == "dictee_asr" else dictee_block

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
        final_lib = build_prompt_with_desc_compat(usr_lib, final_lib, description_vlm_batch)
        if rerun_weak and libelle_weak_existing:
            final_lib += "\n\n" + RERUN_WEAK_LIB

        final_com = apply_template(usr_com, mapping_com)

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

        # --- LIBELLÉ (obligatoire) ---
        SLEEP_OK  = 0.25   # après succès
        SLEEP_ERR = 0.75   # après erreur (évite l’emballement)

        # --- LIBELLÉ (obligatoire) ---
        lib_ok = False
        lib_weak = False
        lib_weak_reason = None
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

            b["libelle_propose_batch"] = lib
            b["llm_err_lib"] = ""
            b["llm_http_status_lib"] = ""
            if rerun_lib:
                lib_rerun_result = "still_weak" if lib_weak else "recovered"
                b["llm_trace_lib"] = append_trace(
                    "",
                    f"[rerun_weak end photo={photo_ref} result={lib_rerun_result} batch_status={'WEAK_LIB' if lib_weak else 'OK_LIB'}]",
                )
                log.info(
                    "[WEAK][RERUN][LIB][END] photo=%s result=%s batch_status=%s",
                    photo_ref,
                    lib_rerun_result,
                    "WEAK_LIB" if lib_weak else "OK_LIB",
                )
            else:
                b["llm_trace_lib"] = ""
            b["batch_status"] = "WEAK_LIB" if lib_weak else "OK_LIB"
            lib_ok = not lib_weak

        except Exception as e:
            # generate_with_retry a déjà appelé _set_llm_err dans la plupart des cas
            if not (b.get("batch_status") or "").startswith("ERR_"):
                _set_llm_err(b, "LIB", e)
                b["batch_status"] = "ERR_LIB"
        finally:
            time.sleep(SLEEP_OK if lib_ok else SLEEP_ERR)


        # --- COMMENTAIRE (optionnel, non bloquant) ---
        com_ok = False
        com_weak = False
        if lib_ok:
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

                b["commentaire_propose_batch"] = com
                b["llm_err_com"] = ""
                b["llm_http_status_com"] = ""
                if rerun_com:
                    com_rerun_result = "still_weak" if com_weak else "recovered"
                    b["llm_trace_com"] = append_trace(
                        "",
                        f"[rerun_weak end photo={photo_ref} result={com_rerun_result} batch_status={'OK_LIB_COM_WEAK' if com_weak else 'OK_LIB_COM'}]",
                    )
                    log.info(
                        "[WEAK][RERUN][COM][END] photo=%s result=%s batch_status=%s",
                        photo_ref,
                        com_rerun_result,
                        "OK_LIB_COM_WEAK" if com_weak else "OK_LIB_COM",
                    )
                else:
                    b["llm_trace_com"] = ""
                b["batch_status"] = "OK_LIB_COM_WEAK" if com_weak else "OK_LIB_COM"
                com_ok = True

            except Exception as e:
                # on garde OK_LIB et on marque l’échec commentaire
                if not (b.get("batch_status") or "").startswith("OK_LIB_ERR_"):
                    _set_llm_err(b, "COM", e)
                    b["batch_status"] = "OK_LIB_ERR_COM"
            finally:
                time.sleep(SLEEP_OK if com_ok else SLEEP_ERR)


        # comptage (une seule fois par ligne)
        b["batch_ts"] = now_ts()
        final_status = (b.get("batch_status") or "").strip().upper()
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
    batch_write_ok = False
    try:
        if isinstance(batch_index, dict) and batch_index:
            batch_rows = list(batch_index.values())
            atomic_write_csv(photos_batch_csv, batch_rows, HEADER_BATCH)
            log.info("photos_batch.csv écrit: %s (%d lignes)", str(photos_batch_csv), len(batch_rows))
            batch_write_ok = True
        else:
            log.info("batch_index vide: aucune écriture photos_batch.csv")
    except Exception as e:
        log.exception("Impossible d'écrire photos_batch.csv: %s", e)

    # Stamp + mtime : sur le CSV BATCH (pas sur photos_csv UI)
    try:
        now = time.time()
        stamp_path = photos_batch_csv.with_suffix(photos_batch_csv.suffix + ".stamp")

        stamp_payload = {
            "last_batch_ts": now_ts(),
            "host": socket.gethostname(),
            "batch_id": str(uuid.uuid4()),
        }

        with open(stamp_path, "w", encoding="utf-8") as f:
            json.dump(stamp_payload, f, ensure_ascii=False, indent=2)

        os.utime(photos_batch_csv, (now, now))  # force mtime/atime
    except Exception as e:
        log.exception("Impossible d'écrire le fichier .stamp: %s", e)


if __name__ == "__main__":
    raise SystemExit(main())

