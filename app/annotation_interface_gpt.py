import streamlit as st
import pandas as pd
import soundfile as sf
import time
import os
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
from streamlit_wavesurfer import wavesurfer
import requests
from pathlib import Path
from PIL import Image
import math
import re
from app.local_llm_client import LocalLLMClient
from app.wol_util import wake_on_lan, wait_for_server, is_server_up
from utils import charger_transcription_flexible
import inspect
import uuid
import io
import hashlib
import logging


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
        base_transcriptions_dir = Path(p).parent.resolve()

    return id_affaire, id_captation, str(base_transcriptions_dir)

def compute_dictee_target_dir(pcfixe: dict) -> str:
    id_affaire, id_captation, base_trans_dir = extract_affaire_captation(pcfixe)
    target = str(Path(base_trans_dir) / "asr_in")
    return target

def compute_asr_subdir_from_pcfixe(pcfixe: dict) -> str:
    id_affaire, id_captation, _ = extract_affaire_captation(pcfixe)
    return str(
        Path(id_affaire)
        / "AF_Expert_ASR"
        / "transcriptions"
        / id_captation
    )

def compute_asr_out_dir_from_pcfixe(pcfixe: dict) -> str:
    _, _, base_transcriptions_dir = extract_affaire_captation(pcfixe)
    return str(Path(base_transcriptions_dir) / "asr_out")


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
            return pd.read_csv(path, sep=sep, encoding=enc)
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
        appcfg = _load_app_config()
    except Exception as e:
        return f"[Erreur config LLM: {e}]"

    backend = str(appcfg.get("llm_backend", "openai")).lower()

    if backend == "local":
        local_cfg = appcfg.get("local_llm", {}) or {}
        wol_cfg   = appcfg.get("wol", {}) or {}

        base_url  = local_cfg.get("base_url", "http://127.0.0.1:5050")
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

        status = st.empty()
        try:
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

                        rj = j.get("reponse_json")
                        if isinstance(rj, dict) and "texte" in rj:
                            return str(rj.get("texte") or "").strip()

                        # fallback brut
                        rep = str(j.get("reponse") or "").strip()
                        if rep:
                            return rep

                        return "[Réponse LLM local vide ou inexploitable]"

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

    # ---- OpenAI (fallback possible)
    api_key = os.getenv("OPENAI_API_KEY", "") or appcfg.get("openai_api_key", "")
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


def _load_app_config() -> dict:
    cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "config.json"))
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)

def pick_libelle(row):
    v = str(row.get("libelle_propose_ui", "") or "").strip()
    if v:
        return v
    return str(row.get("libelle_propose", "") or row.get("libelle_propose_batch", "") or "").strip()

def pick_commentaire(row):
    v = str(row.get("commentaire_propose_ui", "") or "").strip()
    if v:
        return v
    return str(row.get("commentaire_propose", "") or row.get("commentaire_propose_batch", "") or "").strip()


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
        api_key = os.getenv("OPENAI_API_KEY", "") or appcfg.get("openai_api_key", "")
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

    base_url = (local_cfg.get("base_url") or "http://127.0.0.1:5050").rstrip("/")
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
        r = requests.post(url, files=files, data=data, headers=headers, timeout=180)

    r.raise_for_status()
    return str(r.json().get("description", "")).strip()

def merge_vlm_audio(desc_vlm: str, extrait_audio: str) -> str:
    if desc_vlm:
        return f"[PHOTO]\n{desc_vlm}\n\n[AUDIO]\n{extrait_audio}"
    return extrait_audio

@st.cache_data(show_spinner=False)
def cached_vlm(image_path: str, context: str, prompt: str) -> str:
    return call_vlm_single(image_path, context=context, prompt=prompt)


def build_vlm_context(ctx_general: dict) -> str:
    mission = (ctx_general.get("mission") or "").strip()
    system  = (ctx_general.get("system") or "").strip()
    user    = (ctx_general.get("user") or "").strip()

    return (
        "CADRE (expertise — photos) :\n"
        f"- Mission : {mission}\n"
        f"- Finalité : {system}\n"
        f"- Consigne : {user}\n\n"
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

def ensure_desc_vlm(i, row_view, guide_src: str, *, photos_df, photos_csv, mission, context_system) -> str:
    # 1) priorité absolue : UI explicite
    desc = str(row_view.get("description_vlm_ui", "") or "").strip()
    if desc:
        return desc

    # 2) fallback : colonne UI historique (si encore utilisée)
    desc = str(row_view.get("description_vlm", "") or "").strip()
    if desc:
        return desc

    # 3) fallback batch (merge suffix _batch ou colonne native si déjà présente)
    #    (selon votre merge, c’est souvent "description_vlm_batch")
    desc = str(row_view.get("description_vlm_batch", "") or "").strip()
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
            photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)
        return ""

    ctx_general = {"mission": mission, "system": context_system}
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

    photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)

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
        st.error("❌ Aucun fichier audio compatible valide. "
                 "Veuillez revenir à l’étape 1 pour le (re)générer.")
        st.stop()

    # 2) Cohérence source / compatible
    if audio_src_path and audio_compat_source and \
       os.path.abspath(audio_src_path) != os.path.abspath(audio_compat_source):
        st.error("❌ Le fichier audio compatible ne correspond plus au fichier audio source. "
                 "Veuillez repasser par l’étape 1 (sélection des fichiers).")
        st.stop()

    # 3) Calibrage obligatoire avant annotation
    if not calibrage_valide:
        st.error("❌ Le calibrage n’est pas valide. Veuillez d’abord réaliser la synchronisation (étape 2.1).")
        st.stop()


    decalage_raw = infos.get("decalage_moyen", 0.0)
    try:
        decalage = float(str(decalage_raw).replace(",", "."))
    except Exception:
        decalage = 0.0

    st.title("🖋️ Annotation guidée avec GPT")

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

    contexte_path = infos.get("fichier_contexte_general")
    if contexte_path and os.path.exists(contexte_path):
        with open(contexte_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Override si présent dans le contexte
        mission        = data.get("mission", mission)
        context_system = data.get("system", context_system)
        context_user   = data.get("user", context_user)
        ctx_general = {
            "mission": mission,
            "system": context_system,
            "user": context_user,
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




    with st.expander("🔧 Serveur audio", expanded=False):
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
    photos_df = read_csv_fallback(photos_csv, sep=";")
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

            sauvegarder_infos_projet(infos)
            st.success("✅ Les durées ont été enregistrées dans `infos_projet.json`.")

            
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
            projet.setdefault("plages_utilisees", {})
            projet["plages_utilisees"].setdefault("libelle", {})
            projet["plages_utilisees"].setdefault("commentaire", {})
            projet["plages_utilisees"]["libelle"]["avant"]     = lib_av
            projet["plages_utilisees"]["libelle"]["apres"]     = lib_ap
            projet["plages_utilisees"]["commentaire"]["avant"] = com_av
            projet["plages_utilisees"]["commentaire"]["apres"] = com_ap
            sauvegarder_infos_projet(projet)
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

    # --- Déterminer la première photo non annotée ---
    annoted_names = set(annotations_df["nom_fichier_image"].astype(str))
    first_non = next(
        (idx for idx, r in photos_df.iterrows() if str(r["nom_fichier_image"]) not in annoted_names),
        None
    )
    if edit_mode == "Séquentiel (sécurisé)":
        if first_non is None:
            st.info("Toutes les photos sont déjà annotées ...")
            return
        target_indices = [first_non]
    else:
        target_indices = list(range(len(photos_df)))

    # En mode séquentiel : si tout est déjà annoté, on informe et on s’arrête proprement
    if edit_mode == "Séquentiel (sécurisé)" and first_non is None:
        st.info("Toutes les photos sont déjà annotées. Passez en **Réédition libre (expert)** pour modifier des annotations existantes.")
        return
    
    # ─────────────────────────────────────────────────────────────
    # 📦 Batch (lecture seule) : construction d'une vue merge UI+Batch
    # ─────────────────────────────────────────────────────────────

    photos_batch_csv = str(infos.get("fichier_photos_batch", "") or "").strip()
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


        if edit_mode == "Séquentiel (sécurisé)":
            # On n'affiche qu'une seule photo : la première non annotée
            if first_non is None:
                st.info("Toutes les photos sont déjà annotées.")
                return
            if i != first_non:
                continue

        nom_image = row["nom_fichier_image"]
        is_annotated = str(nom_image) in annoted_names

        if edit_mode == "Séquentiel (sécurisé)":
            if is_annotated and i != first_non:
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
            photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)

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
                v = str(r.get("description_vlm_ui", "") or "").strip()
                if v:
                    return v
                v = str(r.get("description_vlm", "") or "").strip()
                if v:
                    return v
                return str(r.get("description_vlm_batch", "") or "").strip()

            desc_vlm = pick_desc_vlm(row_view)  # ✅ UI > legacy > batch
            vlm_status = str(row.get("vlm_ui_status", "") or "").strip()  # ✅ UI
            vlm_ts     = str(row.get("vlm_ui_ts", "") or "").strip()

            st.caption(f"Statut: {vlm_status or '—'} • Date: {vlm_ts or '—'}")

            with st.expander("🧠 Description VLM (photo)", expanded=True):
                
                if desc_vlm:
                    st.write(desc_vlm)
                else:
                    st.caption("Aucune description VLM enregistrée pour cette photo.")

                colv1, colv2 = st.columns(2)

                # 1) calcul si vide (inchangé, mais gardé)
                with colv1:
                    if st.button("🔎 Calculer la description VLM", key=f"vlm_only_{i}"):
                        image_path = os.path.join(row["chemin_photo_reduite"], row["nom_fichier_image"])
                        try:
                            ctx_general = {"mission": mission, "system": context_system}
                            guide_src = (texte_com or texte_lib or "").strip()
                            ctx_vlm = build_vlm_context_guided(ctx_general, guide_src)
                            desc_new = call_vlm_single(image_path, context=ctx_vlm, prompt=VLM_PROMPT)


                            if desc_new:
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                if desc_new:
                                    photos_df.at[i, "description_vlm_ui"] = desc_new
                                    photos_df.at[i, "vlm_ui_status"] = "OK"
                                else:
                                    photos_df.at[i, "vlm_ui_status"] = "EMPTY"  # ou "ERR" si vous considérez “vide” comme erreur

                                photos_df.at[i, "vlm_ui_ts"] = now
                                photos_df.at[i, "ui_ts"] = now
                                photo_dirty = True
                                if photo_dirty:
                                    photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)
                                st.rerun()
                            else:
                                st.warning("VLM a répondu vide.")
                        except Exception as e:
                            st.error(f"Erreur VLM : {e}")

                # 2) régénération forcée (NOUVEAU)
                with colv2:
                    if st.button("↻ Régénérer description VLM", key=f"vlm_force_{i}"):
                        image_path = os.path.join(row["chemin_photo_reduite"], row["nom_fichier_image"])
                        try:
                            # Option : injecter un contexte court (extrait audio) pour guider les “vérifications”
                            ctx_src = (texte_com or texte_lib or "").strip()[:1200]
                            ctx = ""
                            if ctx_src:
                                ctx = "TRANSCRIPTION (extrait, pour guider les vérifications — ne pas en déduire des faits) :\n" + ctx_src

                            desc_new = call_vlm_single(image_path, context=ctx, prompt=VLM_PROMPT)
                            if desc_new:
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                photos_df.at[i, "description_vlm_ui"] = desc_new
                                photos_df.at[i, "vlm_ui_status"] = "OK"
                                photos_df.at[i, "vlm_ui_ts"] = now
                                photos_df.at[i, "ui_ts"] = now
                                photo_dirty = True
                                st.success("Description VLM régénérée et enregistrée.")
                                if photo_dirty:
                                    photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)
                                st.rerun()
                            else:
                                st.warning("VLM a répondu vide.")
                        except Exception as e:
                            st.error(f"Erreur VLM : {e}")




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
                # VLM : description photo (fallback UI si batch non lancé)
                # =========================================================
                try:
                    photo_dirty = False

                    # Lecture unique via row_view (UI + batch)
                    desc_vlm = pick_desc_vlm(row_view)

                    if not desc_vlm:
                        if not is_annotated:
                            guide_src = (texte_com or texte_lib or "").strip()
                            desc_vlm = ensure_desc_vlm(
                                i, row_view, guide_src=guide_src,
                                photos_df=photos_df, photos_csv=photos_csv,
                                mission=mission, context_system=context_system
                            )
                            photo_dirty = True
                            if not desc_vlm:
                                photos_df.at[i, "vlm_ui_status"] = "EMPTY"
                                photo_dirty = True
                        else:
                            photos_df.at[i, "vlm_ui_status"] = "SKIP"
                            photo_dirty = True

                except Exception as e:
                    photos_df.at[i, "vlm_ui_status"] = "ERR"
                    photo_dirty = True
                    st.error(f"Erreur VLM : {e}")

                if photo_dirty:
                    photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)


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

                    # --- Regénérer LIBELLÉ ---
                    if st.button("↻ Regénérer libellé", key=f"regen_lab_{i}"):

                        extrait_lib = _normalize_text(texte_lib, "libelle")
                        desc_vlm = pick_desc_vlm(row_view)

                        if not desc_vlm:
                            guide_src = (texte_lib or "").strip()
                            desc_vlm = ensure_desc_vlm(
                                i, row_view, guide_src=guide_src,
                                photos_df=photos_df, photos_csv=photos_csv,
                                mission=mission, context_system=context_system
                            )
                            if not desc_vlm:
                                st.warning("VLM a répondu vide : libellé non généré pour cette photo.")
                                pass  # ou: pass, puis la logique externe ne génère pas


                        if extrait_lib:
                            system_lib = _compose_system(prompts["libelle"].get("system"), context_system)
                            tpl_lib = str(prompts.get("libelle", {}).get("user", "") or "")

                            desc_vlm_safe = (desc_vlm or "").strip()
                            trans_safe    = (extrait_lib or "").strip()
                            mission_safe  = (mission or "").strip()
                            ctx_safe      = (context_user or "").strip()

                            if "{{description_vlm}}" not in tpl_lib and desc_vlm_safe:
                                tpl_lib = "Description de la photo (éléments visibles uniquement) :\n{{description_vlm}}\n\n" + tpl_lib

                            dictee = (st.session_state.get(f"dictee_{i}") or "").strip()

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

                            raw = generer_texte_gpt(system_lib, prompt_lib)
                            new_lib = _post_clean_llm(raw, "libelle")

                            if not new_lib or new_lib in ("*", "**"):
                                st.warning("⚠️ Libellé vide ou tronqué.")
                            else:
                                st.session_state[f"libelle_{i}"] = new_lib
                                st.session_state[f"libelle_input_{i}"] = new_lib
                                st.rerun()
                        else:
                            st.warning("⛔ Aucun texte utilisable pour le libellé (extrait vide).")


                    # --- Regénérer COMMENTAIRE ---
                    if st.button("↻ Regénérer comment.", key=f"regen_com_{i}"):

                        extrait_com = _normalize_text(texte_com, "commentaire")
                        desc_vlm = pick_desc_vlm(row_view)

                        if not desc_vlm:
                            guide_src = (texte_com or texte_lib or "").strip()
                            desc_vlm = ensure_desc_vlm(
                                i, row_view, guide_src=guide_src,
                                photos_df=photos_df, photos_csv=photos_csv,
                                mission=mission, context_system=context_system
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
                            new_com = _post_clean_llm(raw, "commentaire")

                            if not new_com or new_com in ("*", "**"):
                                st.warning("⚠️ Commentaire vide ou tronqué.")
                            else:
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
                        desc_vlm = pick_desc_vlm(row_view)
                        # (1) VLM si description absente
                        if not desc_vlm:
                            guide_src = (extrait_com or extrait_lib or "").strip()
                            desc_vlm = ensure_desc_vlm(
                                i, row_view, guide_src=guide_src,
                                photos_df=photos_df, photos_csv=photos_csv,
                                mission=mission, context_system=context_system
                            )
                            if not desc_vlm:
                                st.warning("⚠️ VLM indisponible : recalcul GPT poursuivi sans description photo.")
                                # pas de continue

                        # Valeurs sûres (jamais None)
                        desc_vlm_safe = (desc_vlm or "").strip()
                        mission_safe  = (mission or "").strip()
                        ctx_safe      = (context_user or "").strip()


                        dictee = (st.session_state.get(f"dictee_{i}") or "").strip()

                        # --- Libellé ---
                        if extrait_lib:
                            system_lib = _compose_system(prompts["libelle"].get("system"), context_system)
                            tpl_lib = str(prompts.get("libelle", {}).get("user", "") or "")

                            trans_lib_safe = (extrait_lib or "").strip()

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
                            new_lib = _post_clean_llm(raw, "libelle")

                            if new_lib and new_lib not in ("*", "**"):
                                st.session_state[f"libelle_{i}"] = new_lib
                                st.session_state[f"libelle_input_{i}"] = new_lib
                                photos_df.at[i, "libelle_propose_ui"] = new_lib
                                photos_df.at[i, "libelle_ui_status"] = "OK"
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                photos_df.at[i, "libelle_ui_ts"] = now
                                photos_df.at[i, "ui_ts"] = now
                                photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)
                            else:
                                st.warning("⛔ Libellé non recalculé : sortie vide / tronquée.")
                        else:
                            st.warning("⛔ Libellé non recalculé : extrait vide.")

                        # --- Commentaire ---
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
                            new_com = _post_clean_llm(raw, "commentaire")

                            if not new_com or new_com in ("*", "**"):
                                st.warning("⚠️ Commentaire vide ou tronqué.")
                            else:
                                st.session_state[f"commentaire_{i}"] = new_com
                                st.session_state[f"commentaire_input_{i}"] = new_com
                                photos_df.at[i, "commentaire_propose_ui"] = new_com
                                photos_df.at[i, "commentaire_ui_status"] = "OK"
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                photos_df.at[i, "commentaire_ui_ts"] = now
                                photos_df.at[i, "ui_ts"] = now
                                photo_dirty = True
                                if photo_dirty:
                                    photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)
                                st.rerun()                                

                        else:
                            st.warning("⛔ Aucun texte utilisable pour le commentaire (extrait vide).")

                        st.rerun()


                    # --- Dictée micro : ASR -> aide libellé/commentaire ---
                    with st.expander("🎙️ Dictée micro → proposer libellé & commentaire", expanded=False):
                        audio_in = st.audio_input("Enregistrer (micro)", key=f"mic_{i}")
                        project_id = str(infos.get("project_id") or infos.get("id_projet") or "").strip()

                        if not project_id:
                            st.warning("project_id absent dans infos_projet.json : upload /files impossible.")
                        else:
                            if st.button("🪄 Utiliser la dictée pour proposer libellé + commentaire", key=f"mic_go_{i}"):
                                try:
                                    if audio_in is None:
                                        st.warning("Aucun audio enregistré.")
                                    else:
                                        audio_bytes = audio_in.getvalue()
                                        fname = f"mic_{uuid.uuid4().hex}.wav"

                                        appcfg = _load_app_config()
                                        local_cfg = appcfg.get("local_llm", {}) or {}

                                        client = LocalLLMClient(
                                            base_url=(local_cfg.get("base_url") or "http://127.0.0.1:5050"),
                                            api_key=(local_cfg.get("api_key") or ""),
                                            timeout=float(local_cfg.get("timeout") or 30),
                                        )

                                        asr_backend = str(appcfg.get("asr_backend", "local")).lower().strip()

                                        audio_path_server = None
                                        texte_dictee = ""

                                        if asr_backend == "local":
                                            pcfixe = infos.get("pcfixe", {}) or {}

                                            # (A) subdir relatif sous C:\Affaires pour /files
                                            subdir_base = compute_asr_subdir_from_pcfixe(pcfixe)
                                            subdir_in   = str(Path(subdir_base) / "asr_in")

                                            # (B) chemin ABSOLU côté PC fixe pour la sortie CSV
                                            _, _, base_trans_dir_abs = extract_affaire_captation(pcfixe)
                                            out_dir_abs = str(Path(base_trans_dir_abs) / "asr_out")

                                            # 1) Upload wav -> asr_in (PC fixe)
                                            audio_path_server = client.upload_file_bytes(
                                                file_bytes=audio_bytes,
                                                filename=fname,
                                                project_id=project_id,
                                                area="asr_in",
                                                overwrite=True,
                                                subdir=subdir_in,   # ✅ aiguillage
                                            )

                                            # 2) ASR -> /asr_voxtral (UN SEUL appel) + export CSV dans asr_out
                                            payload = client.asr_voxtral(
                                                audio_path_server,
                                                lang="fr",
                                                timestamps=False,
                                                auto_chunk=True,
                                                output_csv_dir=out_dir_abs,     # ✅ ABSOLU PC fixe
                                                export_raw_csv=True,
                                                export_photo_csv=True,
                                                export_chat_csv=False,
                                                return_payload=True,
                                            )


                                            texte_dictee = (payload.get("text") or "").strip()
                                            dictee_csv_path = payload.get("csv_path") or ""
                                            dictee_photo_csv_path = payload.get("photo_csv_path") or ""

                                            # --- après client.asr_voxtral(..., return_payload=True) ---
                                            pcfixe_root = (pcfixe.get("root_affaires") or r"C:\Affaires")
                                            root_in_abs = str(Path(pcfixe_root) / subdir_in)
                                            _check_under(audio_path_server, root_in_abs, "WAV dictée (asr_in)")
                                            if dictee_csv_path:
                                                _check_under(dictee_csv_path, out_dir_abs, "CSV ASR brut (asr_out)")

                                            if dictee_photo_csv_path:
                                                _check_under(dictee_photo_csv_path, out_dir_abs, "CSV ASR photo (asr_out)")

                                            # 3) Persist dans le CSV photos (laptop)
                                            photos_df.at[i, "dictee_audio_path_pcfixe"] = audio_path_server
                                            photos_df.at[i, "dictee_asr_text"] = texte_dictee
                                            photos_df.at[i, "dictee_asr_status"] = "OK"
                                            photos_df.at[i, "dictee_asr_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                                            if dictee_csv_path:
                                                photos_df.at[i, "dictee_asr_csv_path_pcfixe"] = dictee_csv_path
                                            if dictee_photo_csv_path:
                                                photos_df.at[i, "dictee_asr_photo_csv_path_pcfixe"] = dictee_photo_csv_path


                                        elif asr_backend == "openai":
                                            # OpenAI : pas besoin d’upload /files (sauf audit volontaire)
                                            texte_dictee = asr_dictee(audio_bytes, audio_path_server=None, lang="fr")

                                            photos_df.at[i, "dictee_audio_path_pcfixe"] = ""  # pas d’upload
                                            photos_df.at[i, "dictee_asr_text"] = texte_dictee
                                            photos_df.at[i, "dictee_asr_status"] = "OK"
                                            photos_df.at[i, "dictee_asr_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                                            photos_df.at[i, "dictee_audio_sha256"] = hashlib.sha256(audio_bytes).hexdigest()
                                            photos_df.at[i, "dictee_audio_size"] = len(audio_bytes)

                                        else:
                                            raise RuntimeError(f"asr_backend invalide: {asr_backend}")

                                        # Sauvegarde CSV photos + UI
                                        photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)

                                        st.session_state[f"dictee_{i}"] = texte_dictee
                                        st.success("Dictée transcrite.")
                                        st.text_area("Texte dicté (ASR)", texte_dictee, height=120, key=f"dictee_view_{i}")

                                except Exception as e:
                                    photos_df.at[i, "dictee_asr_status"] = "ERR"
                                    photos_df.at[i, "dictee_asr_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)
                                    st.error(f"Erreur dictée/ASR : {e}")
                   


                    if st.button("↩️ Revenir au batch", key=f"back_batch_{i}"):
                        # 1) vider les colonnes UI persistées
                        for c in ("description_vlm_ui", "libelle_propose_ui", "commentaire_propose_ui"):
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


                        photos_df.to_csv(photos_csv, sep=";", encoding="utf-8-sig", index=False)
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
            annotations_df.to_csv(annotations_path, sep=";", index=False, encoding="utf-8-sig")
            try:
                base = Path(annotations_path).with_suffix("")
                with pd.ExcelWriter(f"{base}.xlsx", engine="openpyxl") as xw:
                    annotations_df.to_excel(xw, index=False)
                st.info("📄 Export Excel mis à jour.")
            except Exception as e:
                st.warning(f"⚠️ Export Excel impossible : {e}")

            # Persister la rotation dans le CSV photos
            if "orientation_photo" in photos_df.columns:
                photos_df.at[i, "orientation_photo"] = int(st.session_state[f"orientation_{i}"])
                photo_dirty = True
            
            photos_df.at[i, "annotation_validee"] = 1
            photo_dirty = True


            # Progression (séquentiel / libre)
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
                photos_df.to_csv(
                    photos_csv,
                    sep=";",
                    encoding="utf-8-sig",
                    index=False
                )

            os.makedirs("data", exist_ok=True)
            with open("data/progression_annotation.json", "w", encoding="utf-8") as f:
                json.dump(progression, f, indent=2, ensure_ascii=False)

            st.success("💾 Annotation enregistrée et progression mise à jour.")
            

#            # Optionnel en séquentiel : passer automatiquement à la suivante
#            if st.session_state.get("edit_mode") == "Séquentiel (sécurisé)" and i + 1 < len(photos_df):
#                if st.button("➡️ Passer à la photo suivante"):
#                    st.session_state["photo_index_actuel"] = i + 1
#                    st.rerun() 
#           
        

            
