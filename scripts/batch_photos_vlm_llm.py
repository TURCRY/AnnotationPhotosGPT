#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
batch_photos_vlm_llm.py (CONSOLIDÉ)

- Remplit description_vlm via VLM (/vision/describe_batch)
- Calcule libelle_gpt + commentaire_gpt via LLM (/annoter)
- Utilise infos_projet.json pour trouver:
    - nom du fichier transcription (on n'utilise que le basename)
    - chemin du contexte photos (contexte_general_photos.json) si référencé
- Utilise prompt_gpt.json (snapshot) dans le dossier transcription
- Injecte la description VLM dans le prompt (dans {{transcription}}) au format:
    [PHOTO]
    <desc>
    [AUDIO]
    <extrait>
"""

import argparse
import json
import logging
from pathlib import Path
from datetime import datetime
from contextlib import ExitStack

import pandas as pd
import requests

VLM_ENDPOINT = "/vision/describe_batch"
LLM_ENDPOINT = "/annoter"
DEFAULT_BATCH_SIZE = 20
PROMPT_VERSION = "batch_vlm_v2_consolide"


def load_app_config(transcript_dir: Path) -> dict:
    """
    Charge la configuration LLM figée (snapshot affaire).
    Emplacement attendu :
    AF_Expert_ASR/transcriptions/<id_captation>/config_llm.json
    """
    cfg_path = transcript_dir / "config_llm.json"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"config_llm.json absent : {cfg_path} — configuration LLM requise."
        )

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    # Résolution sécurisée de la clé OpenAI
    if not cfg.get("openai_api_key"):
        env_key = os.getenv("OPENAI_API_KEY")
        if env_key:
            cfg["openai_api_key"] = env_key

    return cfg

def load_llm_config(transcript_dir: Path, user_path: str | None) -> dict:
    p = Path(user_path) if user_path else (transcript_dir / "config_llm.json")
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8", errors="ignore"))

def load_and_sanitize_llm_config(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))

    cfg = {
        "llm_backend": raw.get("llm_backend", "local"),
        "local_llm": raw.get("local_llm", {}),
        "openai_api_key": raw.get("openai_api_key"),
        "model": raw.get("model"),
        "temperature": raw.get("temperature", 0.3),
        "max_tokens": raw.get("max_tokens", 120),
        "default_delays": raw.get("default_delays", {}),
    }

    return cfg

from pathlib import Path
import json

def load_llm_config_sanitized(config_path: Path) -> dict:
    """
    Charge un config_llm.json copié depuis le laptop et
    n'en conserve que les paramètres utiles au batch.

    Le batch ne dépend JAMAIS du config UI complet.
    """

    if not config_path.exists():
        raise FileNotFoundError(f"Config LLM introuvable : {config_path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))

    cfg = {}

    # ------------------------------------------------------------------
    # Backend LLM
    # ------------------------------------------------------------------
    cfg["llm_backend"] = raw.get("llm_backend", "local")

    # --- LLM local ---
    cfg["local_llm"] = {
        "base_url": raw.get("local_llm", {}).get("base_url"),
        "model": raw.get("local_llm", {}).get("model"),
        "timeout": raw.get("local_llm", {}).get("timeout", 30),
    }

    # --- OpenAI (fallback ou usage direct) ---
    cfg["openai_api_key"] = raw.get("openai_api_key")
    cfg["model"]          = raw.get("model", "gpt-4o-mini")
    cfg["temperature"]    = raw.get("temperature", 0.3)
    cfg["max_tokens"]     = raw.get("max_tokens", 120)

    # ------------------------------------------------------------------
    # Fenêtres temporelles (INDISPENSABLE pour le batch)
    # ------------------------------------------------------------------
    delays = raw.get("default_delays", {})

    cfg["default_delays"] = {
        "libelle": {
            "before": float(delays.get("libelle", {}).get("before", 30)),
            "after":  float(delays.get("libelle", {}).get("after", 15)),
        },
        "commentaire": {
            "before": float(delays.get("commentaire", {}).get("before", 120)),
            "after":  float(delays.get("commentaire", {}).get("after", 120)),
        },
    }

    return cfg

# ------------------------------
# LOG
# ------------------------------
def setup_logger(log_path: Path):
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    logging.getLogger().addHandler(logging.StreamHandler())

# ------------------------------
# Helpers
# ------------------------------
def ensure_columns(df: pd.DataFrame, cols):
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df

def _as_int01(v) -> int:
    try:
        if pd.isna(v):
            return 0
        if isinstance(v, (int, float)):
            return 1 if int(v) == 1 else 0
        s = str(v).strip().lower()
        return 1 if s in ("1", "true", "ok", "yes", "y") else 0
    except Exception:
        return 0

def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))

def pick_transcript_filename(infos: dict) -> str:
    # infos_projet.json contient souvent un chemin complet → on ne garde que le nom
    for k in ("fichier_transcription", "transcription_csv", "asr_transcription_csv", "transcription_file", "chemin_transcription"):
        v = infos.get(k)
        if isinstance(v, str) and v.strip():
            return Path(v.strip()).name
    raise KeyError("Nom du fichier de transcription introuvable dans infos_projet.json")

def pick_contexte_photos_path(infos: dict, transcript_dir: Path) -> Path:
    # Si vous voulez pointer explicitement un autre nom, c'est ici.
    for k in ("contexte_general_photos", "contexte_general_photos_json", "chemin_contexte_general_photos"):
        v = infos.get(k)
        if isinstance(v, str) and v.strip():
            p = Path(v.strip())
            return p if p.is_absolute() else (transcript_dir / p)
    # fallback canonique (validé ensemble)
    return transcript_dir / "contexte_general_photos.json"

def load_contexte_photos(contexte_path: Path) -> tuple[str, str]:
    data = load_json(contexte_path)
    if not isinstance(data, dict):
        raise ValueError("contexte_general_photos.json invalide")
    mission = str(data.get("mission", "") or "").strip()
    contexte = str(data.get("user", "") or data.get("contexte", "") or "").strip()
    return mission, contexte

def pick_prompt_gpt_path(transcript_dir: Path) -> Path:
    """
    On utilise STRICTEMENT prompt_gpt.json (singulier),
    déjà copié sur PC fixe par run_all_laptop.bat dans transcript_dir.
    """
    return transcript_dir / "prompt_gpt.json"


def resolve_base_affaire(root_affaires: str, id_affaire: str) -> Path:
    return Path(root_affaires) / id_affaire

# ------------------------------
# Transcription
# ------------------------------
def load_transcript(transcript_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(transcript_csv, sep=";", encoding="utf-8-sig")

    # Variantes possibles
    if {"start", "end"}.issubset(df.columns):
        df["start"] = pd.to_numeric(df["start"], errors="coerce")
        df["end"]   = pd.to_numeric(df["end"], errors="coerce")
    elif {"start_sec", "end_sec"}.issubset(df.columns):
        df["start"] = pd.to_numeric(df["start_sec"], errors="coerce")
        df["end"]   = pd.to_numeric(df["end_sec"], errors="coerce")
    else:
        raise ValueError("Transcription: colonnes start/end ou start_sec/end_sec introuvables")

    # Texte
    if "text" in df.columns:
        df["text"] = df["text"].astype(str)
    elif "texte" in df.columns:
        df["text"] = df["texte"].astype(str)
    else:
        raise ValueError("Transcription: colonne text/texte introuvable")

    # Speaker optionnel
    if "speaker" not in df.columns:
        df["speaker"] = ""

    df = df.dropna(subset=["start", "end"])
    return df



def extract_transcript_window(df_tr: pd.DataFrame, t_audio: float, before_s: float, after_s: float) -> str:
    t0 = max(0.0, float(t_audio) - float(before_s))
    t1 = float(t_audio) + float(after_s)
    sub = df_tr[(df_tr["end"] >= t0) & (df_tr["start"] <= t1)].copy()
    if sub.empty:
        return ""
    sub = sub.sort_values("start")
    lines = []
    for _, r in sub.iterrows():
        spk = str(r.get("speaker", "")).strip()
        txt = str(r.get("text", "")).strip()
        if not txt:
            continue
        lines.append(f"{spk}: {txt}" if spk else txt)
    return "\n".join(lines)

def merge_vlm_audio(desc_vlm: str, extrait_audio: str) -> str:
    desc_vlm = (desc_vlm or "").strip()
    extrait_audio = (extrait_audio or "").strip()
    if desc_vlm:
        if extrait_audio:
            return f"[PHOTO]\n{desc_vlm}\n\n[AUDIO]\n{extrait_audio}"
        return f"[PHOTO]\n{desc_vlm}"
    return extrait_audio

# ------------------------------
# VLM
# ------------------------------
def run_vlm_batch(rows, base_affaire: Path, flask_url: str) -> dict:
    index_map = []
    with ExitStack() as stack:
        files = []
        for idx, row in rows:
            rel = str(row.get("photo_rel_reduite", "")).strip() or str(row.get("photo_rel_native", "")).strip()
            if not rel:
                continue
            img_path = base_affaire / Path(rel)
            if not img_path.exists():
                continue
            f = stack.enter_context(open(img_path, "rb"))
            files.append(("files", (img_path.name, f, "image/jpeg")))
            index_map.append(idx)

        if not files:
            return {}

        resp = requests.post(flask_url + VLM_ENDPOINT, files=files, timeout=300)
        resp.raise_for_status()
        data = resp.json()

        descs = data.get("descriptions", [])
        if not isinstance(descs, list):
            raise ValueError("Réponse VLM inattendue: 'descriptions' non liste")
        return dict(zip(index_map, descs))

# ------------------------------
# Prompt LLM
# ------------------------------
def render_prompt(template: str, mission: str, contexte: str, transcription: str) -> str:
    return (template
            .replace("{{mission}}", mission or "")
            .replace("{{contexte_general}}", contexte or "")
            .replace("{{transcription}}", transcription or "")
            )

def build_prompt(prompt: dict, kind: str, mission: str, contexte: str, transcription: str) -> str:
    bloc = prompt.get(kind, {})
    sys_txt = str(bloc.get("system", "") or "").strip()
    user_tpl = str(bloc.get("user", "") or "").strip()
    user_txt = render_prompt(user_tpl, mission, contexte, transcription)
    # On envoie au serveur /annoter un seul "prompt" texte (comme votre UI)
    return (sys_txt + "\n\n" + user_txt).strip()

def call_llm(prompt: str) -> str:
    cfg = load_app_config()
    backend = cfg.get("llm_backend", "local").lower()

    if backend == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=cfg["openai_api_key"])
        r = client.chat.completions.create(
            model=cfg.get("model", "gpt-4o-mini"),
            temperature=float(cfg.get("temperature", 0.25)),
            max_tokens=int(cfg.get("max_tokens", 120)),
            messages=[{"role": "user", "content": prompt}],
        )
        return r.choices[0].message.content.strip()

    # fallback local (strictement identique UI)
    local = cfg.get("local_llm", {})
    url = local.get("base_url", "").rstrip("/")
    r = requests.post(
        url + "/annoter",
        json={"prompt": prompt},
        timeout=float(local.get("timeout", 30)),
    )
    r.raise_for_status()
    return str(r.json().get("reponse", "")).strip()


# ------------------------------
# MAIN
# ------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos_csv", required=True)
    ap.add_argument("--root_affaires", required=True)
    ap.add_argument("--flask_url", required=True)
    ap.add_argument("--infos_projet_json", required=True)
    ap.add_argument("--transcript_dir", required=True)
    ap.add_argument("--batch_size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--only_missing", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    # --- Charger config LLM figée (snapshot affaire) ---
    config_llm_path = Path(args.transcript_dir) / "config_llm.json"
    llm_cfg = load_llm_config_sanitized(config_llm_path)
    delays = llm_cfg["default_delays"]

    lib_before = delays["libelle"]["before"]
    lib_after  = delays["libelle"]["after"]
    com_before = delays["commentaire"]["before"]
    com_after  = delays["commentaire"]["after"]

    
    csv_path = Path(args.photos_csv)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    infos = load_json(Path(args.infos_projet_json))

    transcript_dir = Path(args.transcript_dir)
    transcript_filename = pick_transcript_filename(infos)
    transcript_csv = transcript_dir / transcript_filename
    if not transcript_csv.exists():
        raise FileNotFoundError(transcript_csv)

    # Contexte photos (lié à la transcription)
    contexte_path = pick_contexte_photos_path(infos, transcript_dir)
    if not contexte_path.exists():
        raise FileNotFoundError(contexte_path)
    mission, contexte = load_contexte_photos(contexte_path)

    # Prompt snapshot (lié à la transcription)
    # Prompt (STRICTEMENT prompt_gpt.json, déjà copié par run_all_laptop.bat)
    prompt_path = pick_prompt_gpt_path(transcript_dir)
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"prompt_gpt.json introuvable sur PC fixe: {prompt_path}. "
            "Il doit être copié par run_all_laptop.bat dans le dossier transcription."
        )

    prompt = load_json(prompt_path)

    # Lecture photos.csv
    df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig")

    required = ["id_affaire", "photo_rel_native", "photo_rel_reduite", "photo_disponible_pcfixe", "t_audio"]
    for c in required:
        if c not in df.columns:
            raise ValueError(f"Colonne requise absente de photos.csv : {c}")

    df = ensure_columns(df, [
        "description_vlm", "vlm_status", "vlm_ts",
        "libelle_gpt", "commentaire_gpt",
        "llm_status", "llm_ts", "prompt_version"
    ])

    id_affaire = str(df["id_affaire"].iloc[0]).strip()
    base_affaire = resolve_base_affaire(args.root_affaires, id_affaire)

    log_path = csv_path.parent / f"batch_photos_{datetime.now():%Y%m%d_%H%M%S}.log"
    setup_logger(log_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logging.info("=== DÉMARRAGE BATCH PHOTOS (CONSOLIDÉ) ===")
    logging.info("Affaire      : %s", id_affaire)
    logging.info("Base affaire  : %s", base_affaire)
    logging.info("CSV           : %s", csv_path)
    logging.info("Transcription : %s", transcript_csv)
    logging.info("Contexte      : %s", contexte_path)
    logging.info("Prompt gpt    : %s", prompt_path)

    df_tr = load_transcript(transcript_csv)

    def is_eligible(row) -> bool:
        if _as_int01(row.get("photo_disponible_pcfixe")) != 1:
            return False
        try:
            float(row.get("t_audio"))
        except Exception:
            return False
        if args.force:
            return True
        if args.only_missing:
            return str(row.get("llm_status", "")).strip() != "OK"
        return str(row.get("llm_status", "")).strip() != "OK"

    rows = [(i, r) for i, r in df.iterrows() if is_eligible(r)]
    logging.info("Photos éligibles : %d", len(rows))

    # -------- VLM --------
    for i in range(0, len(rows), args.batch_size):
        batch = rows[i:i + args.batch_size]
        batch_vlm = [(idx, row) for idx, row in batch
                     if args.force or not str(df.at[idx, "description_vlm"]).strip()]
        if not batch_vlm:
            continue

        try:
            vlm_res = run_vlm_batch(batch_vlm, base_affaire, args.flask_url)
            for idx, desc in vlm_res.items():
                if desc:
                    df.at[idx, "description_vlm"] = desc
                    df.at[idx, "vlm_status"] = "OK"
                else:
                    df.at[idx, "vlm_status"] = "ERR_EMPTY"
                df.at[idx, "vlm_ts"] = now
        except Exception as e:
            logging.error("Erreur VLM batch: %s", e)
            for idx, _ in batch_vlm:
                df.at[idx, "vlm_status"] = "ERR"
                df.at[idx, "vlm_ts"] = now

        df.to_csv(csv_path, sep=";", encoding="utf-8-sig", index=False)

    # -------- LLM --------

    for idx, row in rows:
        desc_vlm = str(df.at[idx, "description_vlm"]).strip()
        if not desc_vlm:
            df.at[idx, "llm_status"] = "SKIP_NO_VLM"
            df.at[idx, "llm_ts"] = now
            df.to_csv(csv_path, sep=";", encoding="utf-8-sig", index=False)
            continue

        try:
            t_audio = float(row.get("t_audio"))

            extrait_lib = extract_transcript_window(df_tr, t_audio, lib_before, lib_after)
            extrait_com = extract_transcript_window(df_tr, t_audio, com_before, com_after)

            mix_lib = merge_vlm_audio(desc_vlm, extrait_lib)
            mix_com = merge_vlm_audio(desc_vlm, extrait_com)

            prompt_lib = build_prompt(prompt, "libelle", mission, contexte, mix_lib)
            prompt_com = build_prompt(prompt, "commentaire", mission, contexte, mix_com)

            lib = call_llm(prompt_lib, llm_cfg)
            com = call_llm(prompt_com, llm_cfg)

            df.at[idx, "libelle_gpt"] = lib.replace("\n", " ").strip()
            df.at[idx, "commentaire_gpt"] = com.replace("\n", " ").strip()

            df.at[idx, "llm_status"] = "OK"
            df.at[idx, "llm_ts"] = now
            df.at[idx, "prompt_version"] = PROMPT_VERSION

        except Exception as e:
            logging.error("Erreur LLM idx=%s : %s", idx, e)
            df.at[idx, "llm_status"] = "ERR"
            df.at[idx, "llm_ts"] = now
            df.at[idx, "prompt_version"] = PROMPT_VERSION

        df.to_csv(csv_path, sep=";", encoding="utf-8-sig", index=False)

    logging.info("=== FIN BATCH PHOTOS ===")

if __name__ == "__main__":
    main()


