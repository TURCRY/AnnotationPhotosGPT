# gpt4all_flask.py
from flask import (
    Flask,
    request,
    jsonify,
    current_app,
    Blueprint,
    send_file,
)

from llama_cpp import Llama
import datetime as dt
from datetime import datetime, timedelta
import json, time, os, uuid, threading, csv, glob, sys, math, re, mimetypes, importlib, platform, subprocess, shutil
import sqlite3
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
import inspect
from collections.abc import Sequence
from math import sqrt
from functools import lru_cache
from contextlib import contextmanager
import unicodedata
from urllib.parse import urlparse, urlunparse, quote
from hashlib import sha256
import threading
from threading import Lock
from helpers_embed import load_embedder
from flask_cors import CORS
import requests
import random
import socket
import html
import io
import pandas as pd, pdfplumber, docx
from langdetect import detect, DetectorFactory
import spacy
from collections import Counter
import uuid, time
from flask import current_app

import helpers_embed, sentence_transformers
# RAG / utils maison
from helper_paths import load_paths, debug_paths_snapshot
from rag_utils import extraire_contenu_rag
from rag_vector_utils import build_rag_context
from rag_vector_utils import build_rag_context_store, retrieve_sources
from rag_vector_utils import (
    upsert_csv_folder_into_store,
    retrieve_top_k_store
)
from rag_memoire_utils import build_context as build_mem_ctx
from rag_memoire_utils import build_memory_append
from ocr_utils import run_ocr, run_ocr_auto, OcrOptions
from voxtral_utils import (
    create_voxtral_pipeline,
    transcribe_audio,
    transcribe_with_diarization,
    post_correct_transcript,
    to_srt, 
    to_vtt, 
    voxtral_chat,
    _safe_stem, 
    _ext_tag, 
    _excel_serial_from_datetime, 
    _fmt_hms,
    _read_lines, 
    load_json_safe, 
    _label_speakers_from_rules
)
from pseudonymizer import pseudonymize_text
from web_search_utils import crawl_search, log_sources
from collections import defaultdict
import hashlib
from collections import OrderedDict
import re as _re
import gc

from difflib import SequenceMatcher



# PDF utils
import fitz  # PyMuPDF (pour compter pages)
from pypdf import PdfReader, PdfWriter  # ou PyPDF2
import numpy as np
import soundfile as sf
import logging
import threading
from logging.handlers import RotatingFileHandler
import base64
from llama_cpp.llama_chat_format import Llava15ChatHandler
from concurrent.futures import ThreadPoolExecutor, as_completed


from dotenv import load_dotenv
try:
    import dirtyjson    # facultatif mais recommandé : pip install dirtyjson
    HAS_DIRTYJSON = True
except Exception:
    HAS_DIRTYJSON = False

import datetime as _dt

log = logging.getLogger("gpt4all_flask")

# ===============================================================
# Vérification des backends Chroma et Qdrant au démarrage
# ===============================================================
from helper_paths import (
    chroma_client,
    qdrant,
    CHROMA_HOST,
    CHROMA_PORT,
    QDRANT_HOST,
    QDRANT_PORT,
)

def check_backends():
    print("\n=== Vérification des backends vectoriels ===")

    # --- Chroma via helper_paths.chroma_client ---
    try:
        if chroma_client is None:
            raise RuntimeError("chroma_client est None (pas initialisé)")
        hb = chroma_client.heartbeat()
        print(f"[OK] Chroma REST joignable ({CHROMA_HOST}:{CHROMA_PORT}) heartbeat={hb}")
    except Exception as e:
        print(f"[WARN] Chroma non joignable : {e}")

    # --- Qdrant via helper_paths.qdrant ---
    try:
        if qdrant is None:
            raise RuntimeError("qdrant est None (pas initialisé)")
        colls = qdrant.get_collections()
        nb = len(colls.collections)
        print(f"[OK] Qdrant REST joignable ({QDRANT_HOST}:{QDRANT_PORT}) ({nb} collections)")
    except Exception as e:
        print(f"[WARN] Qdrant non joignable : {e}")

    print("=== Vérification terminée ===\n")



load_dotenv(Path(__file__).resolve().parent / "config" / ".env")

def log_effective_params(
    logger,
    model_name: str,
    eff: dict,
    *,
    context: str = ""
) -> None:
    init_params = {k: eff[k] for k in INIT_KEYS if k in eff}
    gen_params  = {k: eff[k] for k in eff if k not in INIT_KEYS}

    logger.info(
        "🧠 LLM params%s model=%s | INIT=%s | GEN=%s",
        f" [{context}]" if context else "",
        model_name,
        init_params,
        gen_params
    )



# --- Exécuter la vérification au lancement ---
check_backends()


# gpt4all_flask.py (imports)

BASE_DIR = Path(__file__).resolve().parent.parent  # D:\GPT4All_Local
CONFIG_DIR = BASE_DIR / "config"

LLM_GEN_LOCK = threading.Lock()

# Rendre langdetect déterministe (important en contexte judiciaire)
# ============================================================
# HALLUCINATIONS ASR — v2 (hard / soft)
# ============================================================



# Rendre langdetect déterministe
DetectorFactory.seed = 0

NLP_FR = None
current_model_name: str | None = None

HALLU_HARD_SUBSTRINGS: list[str] = []
HALLU_SOFT_SUBSTRINGS: list[str] = []
HALLU_HARD_REGEX: list[re.Pattern] = []
HALLU_SOFT_REGEX: list[re.Pattern] = []

# Cache anti-doublons session serveur
HALLU_SEEN = OrderedDict()
HALLU_SEEN_MAX = 50000

# Hint générique (journalisation seulement)
HALLU_HINT_REGEX = re.compile(
    r"(je ne comprends pas|je n'ai pas compris|je ne saisis pas|"
    r"pouvez[- ]?vous (préciser|reformuler|répéter)|"
    r"veuillez (préciser|indiquer|reformuler)|"
    r"pour (que|afin de|afin que) (je|vous) (puisse|puissiez) (vous )?(aider|répondre)|"
    r"j'ai besoin de plus de contexte|il me faut plus de contexte|"
    r"il semble que vous|"
    r"voici (un )?exemple|note\s*:|"
    r"faites[- ]moi savoir|n'hésitez pas à)",
    re.IGNORECASE
)


def _hash_text(text: str) -> str:
    import hashlib
    return hashlib.sha1((text or "").encode("utf-8", errors="ignore")).hexdigest()


def _seen_add(h: str) -> bool:
    """
    Retourne True si déjà vu, sinon l'ajoute et retourne False.
    """
    if h in HALLU_SEEN:
        return True
    HALLU_SEEN[h] = 1
    if len(HALLU_SEEN) > HALLU_SEEN_MAX:
        HALLU_SEEN.popitem(last=False)
    return False


def _norm_hallu(s: str) -> str:
    if not s:
        return ""
    s = str(s)
    s = s.replace("’", "'")
    s = s.replace("–", "-").replace("—", "-")
    s = " ".join(s.split())
    return s.strip()


def load_hallu_patterns():
    """
    Charge hallu_patterns_v2.json :
      - hard_substrings
      - soft_substrings
      - hard_regex
      - soft_regex
    """
    global HALLU_HARD_SUBSTRINGS, HALLU_SOFT_SUBSTRINGS
    global HALLU_HARD_REGEX, HALLU_SOFT_REGEX

    try:
        with HALLU_PATTERNS_PATH.open("r", encoding="utf-8") as f:
            cfg = json.load(f)

        def _load_subs(key: str) -> list[str]:
            return sorted(set(
                str(s).lower().strip()
                for s in (cfg.get(key) or [])
                if str(s).strip()
            ))

        def _load_regex(key: str) -> list[re.Pattern]:
            out: list[re.Pattern] = []
            for rx in (cfg.get(key) or []):
                rx = str(rx).strip()
                if not rx:
                    continue
                try:
                    out.append(re.compile(rx, re.IGNORECASE))
                except re.error as e:
                    print(f"[ASR CLEAN] regex invalide ignorée: {rx} ({e})")
            return out

        HALLU_HARD_SUBSTRINGS = _load_subs("hard_substrings")
        HALLU_SOFT_SUBSTRINGS = _load_subs("soft_substrings")
        HALLU_HARD_REGEX = _load_regex("hard_regex")
        HALLU_SOFT_REGEX = _load_regex("soft_regex")

        print(
            "[ASR CLEAN] "
            f"{len(HALLU_HARD_SUBSTRINGS)} hard_substrings, "
            f"{len(HALLU_SOFT_SUBSTRINGS)} soft_substrings, "
            f"{len(HALLU_HARD_REGEX)} hard_regex, "
            f"{len(HALLU_SOFT_REGEX)} soft_regex chargés depuis {HALLU_PATTERNS_PATH}"
        )

    except Exception as e:
        print(f"[ASR CLEAN] ERREUR chargement hallu_patterns: {e}")
        HALLU_HARD_SUBSTRINGS = []
        HALLU_SOFT_SUBSTRINGS = []
        HALLU_HARD_REGEX = []
        HALLU_SOFT_REGEX = []


def _match_hallu_hard(sentence: str) -> str | None:
    s = _norm_hallu(sentence).lower()
    if not s:
        return None

    for sub in HALLU_HARD_SUBSTRINGS:
        if sub and sub in s:
            return f"hard_sub:{sub}"

    for rx in HALLU_HARD_REGEX:
        try:
            if rx.search(s):
                return f"hard_rx:{rx.pattern}"
        except Exception:
            continue

    return None


def _match_hallu_soft(sentence: str) -> str | None:
    s = _norm_hallu(sentence).lower()
    if not s:
        return None

    for sub in HALLU_SOFT_SUBSTRINGS:
        if sub and sub in s:
            return f"soft_sub:{sub}"

    for rx in HALLU_SOFT_REGEX:
        try:
            if rx.search(s):
                return f"soft_rx:{rx.pattern}"
        except Exception:
            continue

    return None


def _is_hallu_hard(sentence: str) -> bool:
    return _match_hallu_hard(sentence) is not None


def _is_hallu_candidate(sentence: str) -> bool:
    s = (sentence or "").strip()
    if not s:
        return False
    if _match_hallu_soft(s):
        return True
    return bool(HALLU_HINT_REGEX.search(s))

# --- Suppression renforcée des hallucinations soft / non-fr ---
SOFT_DELETE_SUBSTRINGS = {
    "what",
    "what's up",
    "what should i do",
    "what does that mean",
    "what do you mean",
    "what do you want",
    "what do you think",
    "what's the truth",
    "you know what i mean",
    "check what's here",
    "i don't know",
    "i'm sorry",
    "let's go",
    "salut",
    "allô ?",
    "allô",
    "n'ayez pas peur",
}

def _should_delete_soft(sentence: str) -> bool:
    s = (sentence or "").strip().lower()
    if not s:
        return False

    for sub in SOFT_DELETE_SUBSTRINGS:
        if sub in s:
            return True

    if s in {
        "what", "what?",
        "salut", "salut !", "salut.",
        "allô", "allô ?",
        "i'm sorry.", "i don't know.", "let's go."
    }:
        return True

    return False



def is_hallu_text(text: str) -> bool:
    """
    Compat ascendante : True si hard ou soft match.
    """
    t = (text or "").strip()
    if not t:
        return False
    return (_match_hallu_hard(t) is not None) or (_match_hallu_soft(t) is not None)


def _log_hallu_candidate(text: str, source: str = "asr_chunk", severity: str = "soft", reason: str = ""):
    """
    Enregistre une phrase suspecte dans hallu_candidates.jsonl
    pour analyse ultérieure.
    """
    try:
        txt = (text or "").strip()
        if not txt:
            return

        h = _hash_text(f"{source}||{severity}||{txt.lower()}")
        if _seen_add(h):
            return

        rec = {
            "text": txt,
            "source": source,
            "severity": severity,
            "reason": reason,
            "sha1": h,
        }

        HALLU_CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HALLU_CANDIDATES_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    except Exception:
        # Ne jamais faire planter l'ASR
        pass


def _maybe_log_hallu_candidate(text: str) -> None:
    """
    Journalisation opportuniste d'un texte suspect.
    N'altère pas le texte.
    """
    if not text:
        return

    try:
        m_hard = _match_hallu_hard(text)
        if m_hard:
            app.logger.warning("[ASR CLEAN][HALLU][HARD] %s texte='%s'", m_hard, text[:300])
            return

        m_soft = _match_hallu_soft(text)
        if m_soft:
            app.logger.warning("[ASR CLEAN][HALLU][SOFT] %s texte='%s'", m_soft, text[:300])
            return

        if HALLU_HINT_REGEX.search(text):
            app.logger.warning("[ASR CLEAN][HALLU][HINT] texte='%s'", text[:300])
            return

    except Exception as e:
        app.logger.debug(f"[ASR CLEAN] hallu check failed: {e}")


def _split_sentences_fr(text: str) -> list[str]:
    txt = (text or "").strip()
    if not txt:
        return []
    if NLP_FR is None:
        return [t.strip() for t in re.split(r"(?<=[\.\?\!])\s+", txt) if t.strip()]
    doc = NLP_FR(txt)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def _strip_hallu_sentences(text: str) -> str:
    """
    Supprime uniquement les phrases hard.
    Les soft restent dans le texte et sont seulement journalisées.
    """
    if not text:
        return ""
    parts = re.split(r'(?<=[\.\?\!])\s+', text)
    kept = []
    for sent in parts:
        s = sent.strip()
        if not s:
            continue
        if _is_hallu_hard(s):
            continue
        kept.append(s)
    return " ".join(kept).strip()


_FR_HINT_WORDS = {
    "le", "la", "les", "un", "une", "des", "du",
    "de", "dans", "sur", "avec", "pour", "pas",
    "oui", "non", "alors", "donc", "voilà", "ici",
    "est", "sont", "été", "avait", "avoir", "être"
}

def _english_marker_count(s: str) -> int:
    low = s.lower()
    markers = [
        "what", "why", "how", "sorry", "don't", "does", "mean",
        "think", "want", "truth", "let's", "check", "know"
    ]
    return sum(1 for m in markers if m in low)



def _looks_french_lexically(text: str) -> bool:
    toks = re.findall(r"[A-Za-zÀ-ÿ]+", (text or "").lower())
    if not toks:
        return False
    hits = sum(1 for t in toks if t in _FR_HINT_WORDS)
    return hits >= 2

def _enough_text_for_langcheck(text: str) -> bool:
    """
    Évite les faux positifs sur segments trop courts.
    """
    t = (text or "").strip()
    if not t:
        return False

    words = re.findall(r"[A-Za-zÀ-ÿ]+", t)
    words2 = [w for w in words if len(w) >= 2]
    letters = re.findall(r"[A-Za-zÀ-ÿ]", t)

    return len(words2) >= 3 and len(letters) >= 12


def is_french(text: str) -> bool:
    """
    Détection prudente :
    - sur texte court : on ne filtre pas
    - sur texte assez long : langdetect
    """
    try:
        t = (text or "").strip()
        if not t:
            return True

        if not _enough_text_for_langcheck(t):
            return True

        lang = detect(t)
        return lang == "fr"
    except Exception:
        return True


def _is_glitch_text(text: str) -> bool:
    """
    Détecte des textes manifestement aberrants.
    """
    if not text:
        return True
    t = str(text).strip()
    if not t:
        return True

    if len(t) > 2000:
        return True

    if re.search(r"(.)\1{10,}", t):
        return True

    words = t.split()
    if len(words) == 0:
        return True

    if len(words) > 30 and len(set(words)) <= 4:
        return True

    low = t.lower()
    if re.fullmatch(r"(ah|ha|euh|heu|oh|no|non|oui)[\s,;.!?]*( (ah|ha|euh|heu|oh|no|non|oui)[\s,;.!?]*){5,}", low):
        return True

    return False

def clean_hallu_in_chunks(chunks: list[dict], source: str = "asr_voxtral") -> list[dict]:
    """
    Nettoie chaque chunk :
    - supprime les phrases hard
    - supprime certains soft parasites
    - logue les phrases soft/hint
    - conserve le reste
    """
    out = []
    for ch in chunks or []:
        raw = (ch.get("text") or "").strip()
        if not raw:
            continue

        sents = _split_sentences_fr(raw)
        kept = []
        for s in sents:
            s = (s or "").strip()
            if not s:
                continue

            hard_reason = _match_hallu_hard(s)
            if hard_reason:
                _log_hallu_candidate(s, source=source, severity="hard", reason=hard_reason)
                continue

            soft_reason = _match_hallu_soft(s)
            if soft_reason:
                _log_hallu_candidate(s, source=source, severity="soft", reason=soft_reason)
                if _should_delete_soft(s):
                    continue
            elif HALLU_HINT_REGEX.search(s):
                _log_hallu_candidate(s, source=source, severity="soft", reason="hint_regex")

            kept.append(s)

        new_txt = " ".join(kept).strip()
        if not new_txt:
            continue

        ch2 = dict(ch)
        ch2["text"] = new_txt
        out.append(ch2)

    return out

def clean_asr_segments(segments: list[dict]) -> list[dict]:
    """
    Nettoie une liste de segments ASR :
    - segmentation en phrases
    - suppression des hard hallu
    - log des soft hallu
    - suppression prudente des segments non FR
    - suppression des glitches
    - normalisation / dédoublonnage / fusion
    """
    norm: list[dict] = []

    for seg in segments or []:
        try:
            start = float(seg.get("start") or 0.0)
            end = float(seg.get("end") or 0.0)
        except Exception:
            continue

        if end <= start:
            continue

        raw_txt = (seg.get("text") or "").replace("\r", " ").replace("\n", " ").strip()
        if not raw_txt:
            continue

        _maybe_log_hallu_candidate(raw_txt)

        if NLP_FR:
            try:
                doc = NLP_FR(raw_txt)
                sentences = [s.text.strip() for s in doc.sents if s.text.strip()]
            except Exception:
                sentences = [raw_txt]
        else:
            sentences = [raw_txt]

        cleaned_sentences: list[str] = []

        for sent in sentences:
            s = sent.strip()
            if not s:
                continue

            hard_reason = _match_hallu_hard(s)
            if hard_reason:
                app.logger.warning("[ASR CLEAN][DROP][HARD] %s texte=%r", hard_reason, s)
                _log_hallu_candidate(s, source="hallu_hard", severity="hard", reason=hard_reason)
                continue

            soft_reason = _match_hallu_soft(s)
            if soft_reason:
                _log_hallu_candidate(s, source="hallu_soft", severity="soft", reason=soft_reason)
                if _should_delete_soft(s):
                    app.logger.warning("[ASR CLEAN][DROP][SOFT] %s texte=%r", soft_reason, s)
                    continue
            elif HALLU_HINT_REGEX.search(s):
                _log_hallu_candidate(s, source="hallu_hint", severity="soft", reason="hint_regex")

            low = s.lower().strip(" .!?…,;:")
            if not _looks_french_lexically(s) and low in {
                "what", "what?", "what's up", "what's up?",
                "i'm sorry", "i'm sorry.",
                "i don't know", "i don't know.",
                "let's go", "let's go.",
                "allô", "allô ?", "salut", "salut !", "salut."
            }:
                app.logger.warning("[ASR CLEAN][DROP][SHORT] texte=%r", s)
                _log_hallu_candidate(s, source="lang_short_non_fr", severity="hard", reason="short_non_fr")
                continue

            if _enough_text_for_langcheck(s) and not is_french(s):
                if not _looks_french_lexically(s):
                    app.logger.warning("[ASR CLEAN][DROP][LANG] non-fr texte=%r", s)
                    _log_hallu_candidate(
                        s,
                        source="lang_non_fr",
                        severity="hard",
                        reason="langdetect_non_fr",
                    )
                    continue

            if _english_marker_count(s) >= 2 and not _looks_french_lexically(s):
                app.logger.warning("[ASR CLEAN][DROP][EN] texte=%r", s)
                _log_hallu_candidate(
                    s,
                    source="english_markers",
                    severity="hard",
                    reason="english_marker_count"
                )
                continue

            if _is_glitch_text(s):
                _log_hallu_candidate(s, source="glitch", severity="hard", reason="glitch_text")
                continue

            cleaned_sentences.append(s)

        txt = " ".join(cleaned_sentences).strip()
        if not txt:
            continue

        seg2 = dict(seg)
        seg2["start"] = start
        seg2["end"] = end
        seg2["text"] = txt
        seg2["speaker"] = seg.get("speaker") or "SPEAKER"
        norm.append(seg2)

    if not norm:
        return []

    norm.sort(key=lambda s: s["start"])

    # Suppression doublons stricts
    cleaned: list[dict] = []
    seen_keys = set()

    for seg in norm:
        key = (seg["start"], seg["end"], seg.get("speaker") or "", seg["text"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        cleaned.append(seg)

    # Fusion des quasi-doublons consécutifs
    final: list[dict] = []
    TIME_EPS = 0.05
    END_EPS = 0.20

    for seg in cleaned:
        if final:
            prev = final[-1]
            if (
                seg.get("speaker") == prev.get("speaker")
                and abs(seg["start"] - prev["start"]) <= TIME_EPS
                and abs(seg["end"] - prev["end"]) <= END_EPS
            ):
                prev_txt = prev["text"]
                txt = seg["text"]

                if (
                    txt == prev_txt
                    or txt.startswith(prev_txt.rstrip(" .,…"))
                    or prev_txt.startswith(txt.rstrip(" .,…"))
                ):
                    prev["start"] = min(prev["start"], seg["start"])
                    prev["end"] = max(prev["end"], seg["end"])
                    if len(txt) > len(prev_txt):
                        prev["text"] = txt
                    continue

        final.append(seg)

    return final


def load_spacy():
    """
    Charge spaCy français pour segmentation de phrases.
    """
    global NLP_FR
    try:
        NLP_FR = spacy.load("fr_core_news_sm")
        print("[ASR CLEAN] spaCy fr_core_news_sm chargé.")
    except Exception as e:
        print(f"[ASR CLEAN] spaCy FR non disponible: {e}")
        NLP_FR = None








# Expressions typiques d'hallucinations "assistant" (case-insensitive)




FORBIDDEN_SUBSTRINGS = [
    "assistant:", "as an ai", "je vais", "we must", "must not", "instructions",
    "réponds", "tu dois", "voici", "exemple", "note:", "analyse:",
    "json vide", "format de sortie", "phrase 1", "phrase 2", "strictement"
]

FORBIDDEN_SUBSTRINGS = [
    "assistant:", "as an ai", "je vais", "we must", "must not", "instructions",
    "réponds", "tu dois", "voici", "exemple", "note:", "analyse:"
]



def _count_sentences_fr(s: str) -> int:
    # Heuristique simple (OK pour 2–4 phrases)
    parts = [p.strip() for p in re.split(r"[.!?]+", s) if p.strip()]
    return len(parts)

def _is_clean_text_base(s: str) -> list[str]:
    errs = []
    if not s or not s.strip():
        return ["vide"]
    t = s.strip()
    if "```" in t or "<json>" in t.lower() or "</json>" in t.lower():
        errs.append("contient_markdown_ou_wrapper")
    low = t.lower()
    for bad in FORBIDDEN_SUBSTRINGS:
        if bad in low:
            errs.append("meta_discours")
            break
    return errs



_NORMATIVE_TERMS = re.compile(
    r"\b(devrait|doivent|doit|anormal|conforme|non conforme|"
    r"règles de l'art|responsabilité|responsable|défectueux|"
    r"non respect|malfaçon|désordre)\b",
    re.IGNORECASE
)


_REASONING_RE = re.compile(
    r"\b(afin de|dans le but de|pour respecter|conformément aux consignes|"
    r"comme demandé|il faut|on doit)\b",
    re.IGNORECASE
)

_MODALITES_RE = re.compile(
    r"\b(probablement|semble|paraît|visiblement|apparemment)\b",
    re.IGNORECASE
)


_CHAT_TOKENS_RE = re.compile(
    r"\b("
    r"we need|we have to|i will|let us|the content|produce json|"
    r"assistant|user|system prompt|instructions?|analysis|reasoning"
    r")\b",
    re.IGNORECASE
)

def _looks_english(text: str) -> bool:
    """
    Détecte un texte majoritairement anglais.
    Critère volontairement strict pour éviter les faux positifs.
    """
    if not text:
        return False

    t = text.lower()

    english_markers = [
        " the ", " and ", " or ", " to ", " of ",
        " with ", " without ", " need to ", " we ",
        " is ", " are ", " this ", " that "
    ]

    hits = sum(1 for m in english_markers if m in t)
    return hits >= 4



def normalize_text_soft(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


# Préfixes / méta-discours déjà visés par votre validation
_PREFIX_RE = re.compile(
    r"^\s*(libell[eé]|commentaire|titre|label|sortie|r[eé]ponse)\s*[:\-]",
    re.IGNORECASE
)

_META_RE = re.compile(
    r"\b("
    r"we need|must|should|json|strict|your answer|do not|no extraneous|"
    r"examples?|notes?|instruction|format|"
    r"assistant|réponse|reponse|explication|sortie|généré|genere"
    r")\b",
    re.IGNORECASE
)


# Boilerplates parasites observés
_LIBELLE_BOILERPLATES = [
    "répare la sortie s'il te plaît",
    "repare la sortie s'il te plait",
    "vérifie connexion internet puis redémarre appareil",
    "verifie connexion internet puis redemarre appareil",
    "réparation terminée vérifiez la sortie",
    "reparation terminee verifiez la sortie",
    "vérifiez la sortie",
    "verifiez la sortie",
    "répare la sortie",
    "repare la sortie",
]

# Mots typiques de support / dépannage
_SUPPORT_TERMS = {
    "connexion", "internet", "redemarre", "redémarre", "appareil",
    "reparation", "réparation", "sortie", "support", "depannage",
    "dépannage", "reseau", "réseau", "erreur", "probleme", "problème",
}


def _fuzzy_contains_boilerplate(text: str, patterns: list[str], threshold: float = 0.88) -> bool:
    s = normalize_text_soft(text)
    if not s:
        return False

    for pat in patterns:
        p = normalize_text_soft(pat)
        if p in s:
            return True

        # comparaison globale
        if SequenceMatcher(None, s, p).ratio() >= threshold:
            return True

        # comparaison glissante si le texte est plus long
        if len(s) > len(p) and len(p) >= 12:
            win = len(p)
            step = max(4, win // 6)
            for i in range(0, max(1, len(s) - win + 1), step):
                chunk = s[i:i + win]
                if SequenceMatcher(None, chunk, p).ratio() >= threshold:
                    return True

    return False


def validate_libelle_boilerplate(texte: str) -> list[str]:
    errs: list[str] = []
    s_norm = normalize_text_soft(texte)

    if _fuzzy_contains_boilerplate(s_norm, _LIBELLE_BOILERPLATES, threshold=0.88):
        errs.append("boilerplate_support")
        return errs

    words = set(re.findall(r"[a-zA-ZÀ-ÿ0-9\-]+", s_norm))
    _SUPPORT_TERMS_NORM = {normalize_text_soft(x) for x in _SUPPORT_TERMS}
    hit_terms = words.intersection(_SUPPORT_TERMS_NORM)
    if len(hit_terms) >= 3:
        errs.append("support_technique")
    return errs


def validate_libelle_anchor(texte: str, anchor_terms: list[str] | None = None) -> list[str]:
    """
    Vérifie qu'au moins un terme métier/contextuel apparaît dans le libellé.
    Contrôle souple mais utile contre les libellés hors contexte.
    """
    if not anchor_terms:
        return []

    s = normalize_text_soft(texte)
    if not s:
        return ["ancrage_absent"]

    norm_terms = []
    for x in anchor_terms:
        x = normalize_text_soft(x)
        if len(x) >= 4:
            norm_terms.append(x)

    norm_terms = list(dict.fromkeys(norm_terms))[:40]

    for term in norm_terms:
        if term in s:
            return []

    return ["ancrage_absent"]


def validate_libelle(texte: str, anchor_terms: list[str] | None = None) -> list[str]:
    errors: list[str] = []

    if not texte or not texte.strip():
        return ["vide"]

    t = texte.strip().rstrip(".;:").strip()

    # 1 ligne impérative
    if "\n" in t or "\r" in t:
        errors.append("multiligne")

    # souplesse longueur
    if len(t) > 150:
        errors.append("trop_long")

    if _PREFIX_RE.search(t):
        errors.append("prefixe_interdit")
    if _META_RE.search(t):
        errors.append("meta_discours")

    nwords = len(t.split())
    if not (5 <= nwords <= 17):
        errors.append("nombre_mots")

    errors += validate_libelle_boilerplate(t)
    errors += validate_libelle_anchor(t, anchor_terms=anchor_terms)

    return list(dict.fromkeys(errors))


def split_libelle_errors(errs: list[str]) -> tuple[list[str], list[str]]:
    """
    hard = erreurs bloquantes -> PASS2
    soft = avertissements -> on peut accepter en PASS1/PASS2
    """
    hard_codes = {
        "vide",
        "multiligne",
        "prefixe_interdit",
        "meta_discours",
        "boilerplate_fuzzy",
        "support_technique",
        "ancrage_absent",
    }
    hard = [e for e in errs if e in hard_codes]
    soft = [e for e in errs if e not in hard_codes]
    return hard, soft


def build_anchor_terms_for_libelle(data: dict) -> list[str]:
    """
    Extrait quelques termes d'ancrage depuis le prompt / transcription / VLM.
    Le but n'est pas la perfection linguistique, mais un garde-fou simple.
    """
    chunks = []

    for key in (
        "prompt",
        "transcription",
        "description_vlm",
        "dictee_asr_text",
    ):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            chunks.append(v)

    text = "\n".join(chunks)
    raw_terms = re.findall(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\-_']{3,}", text)

    stop = {
        "photo", "commentaire", "libelle", "libellé", "texte", "visible",
        "description", "transcription", "dictée", "dictee", "selon",
        "uniquement", "phrase", "phrases", "json", "strict"
    }

    out = []
    seen = set()
    for term in raw_terms:
        nt = normalize_text_soft(term)
        if nt in stop:
            continue
        if nt not in seen:
            seen.add(nt)
            out.append(term)

    return out[:40]

_LIBELLE_SUPPORT_RE = re.compile(
    r"\b("
    r"verifi(?:e|ez|er)|redemarr(?:e|ez|er)|repare(?:r|z)?|"
    r"connexion(?: internet)?|reseau|appareil|systeme|serveur|"
    r"essayez|cliquez|veuillez|svp|support|depannage"
    r")\b",
    re.IGNORECASE
)

_IMPERATIF_RE = re.compile(
    r"\b(verifie|verifiez|redemarre|redemarrez|repare|reperez|essayez|cliquez)\b",
    re.IGNORECASE
)


_STOPWORDS_MIN = {
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "et", "ou", "a", "à",
    "au", "aux", "en", "sur", "sous", "dans", "pour", "par", "avec", "sans",
    "ce", "cet", "cette", "ces", "il", "elle", "ils", "elles", "on", "ne", "pas",
    "plus", "moins", "tres", "très", "photo", "image", "visible", "visibles"
}


def _tokenize_anchor(text: str) -> set[str]:
    if not text:
        return set()
    toks = re.findall(r"[a-zA-ZÀ-ÿ0-9][a-zA-ZÀ-ÿ0-9_-]{2,}", text.lower())
    return {t for t in toks if t not in _STOPWORDS_MIN}


SOFT_ERRORS = {
    "trop_long_soft",
    "ponctuation_finale_absente",
    "guillemets_enveloppants",
    # salient en soft par défaut :
    # les erreurs commencent par "point_saillant_absent:"
}
SOFT_ERRORS.add("repetition_phrase")

def _normalize_sent_for_repeat(s: str) -> str:
    s = (s or "").strip().lower()
    # retire guillemets/ponctuation faible, compacte espaces
    s = re.sub(r"[«»\"'()\[\]{}]", " ", s)
    s = re.sub(r"[,;:]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _has_repeated_sentence(sents: list[str], *, ratio: float = 0.92, min_len: int = 35) -> bool:
    """
    True si au moins 2 phrases sont très similaires (répétition).
    - ratio ~0.92 : assez strict pour éviter les faux positifs
    - min_len : ignore les petites phrases (ex: "OK.", "D'accord.")
    """
    if not sents or len(sents) < 2:
        return False

    norm = [_normalize_sent_for_repeat(s) for s in sents if _normalize_sent_for_repeat(s)]
    for i in range(len(norm)):
        if len(norm[i]) < min_len:
            continue
        for j in range(i + 1, len(norm)):
            if len(norm[j]) < min_len:
                continue
            if SequenceMatcher(None, norm[i], norm[j]).ratio() >= ratio:
                return True
    return False


def split_errors(errs: list[str], salient_families: list[str] | None) -> tuple[list[str], list[str]]:
    salient_families = salient_families or []
    salient_is_hard = (len(salient_families) == 1)

    hard: list[str] = []
    soft: list[str] = []

    for e in (errs or []):
        if e in SOFT_ERRORS:
            soft.append(e)

        elif e.startswith("point_saillant_absent:"):
            # 1 salient => hard ; 2+ salients => soft
            (hard if salient_is_hard else soft).append(e)

        else:
            hard.append(e)

    # dédoublonnage stable
    def _dedup_stable(xs: list[str]) -> list[str]:
        seen = set()
        out = []
        for x in xs:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    return _dedup_stable(hard), _dedup_stable(soft)



def validate_commentaire(texte: str) -> list[str]:

    # Ordre volontaire :
    # 1) Propreté / sécurité (injection, méta)
    # 2) Langue
    # 3) Contraintes quantitatives
    # 4) Structure juridique stricte

    errs: list[str] = []
    t = (texte or "").strip()

    base = _is_clean_text_base(t)
    if base == ["vide"]:
        return base
    errs += base

    # contrôles généraux
    if _PREFIX_RE.search(t):
        errs.append("prefixe_interdit")
    if _CHAT_TOKENS_RE.search(t) or _META_RE.search(t):
        errs.append("meta_discours")
    if _NORMATIVE_TERMS.search(t):
        errs.append("normatif_interdit")

    if (t.startswith('"') and t.endswith('"')) or (t.startswith("«") and t.endswith("»")):
        errs.append("guillemets_enveloppants")

    if not re.search(r"[.!?]\s*$", t):
        errs.append("ponctuation_finale_absente")

    sents = _split_sentences_fr(t)
    if _has_repeated_sentence(sents):
        errs.append("repetition_phrase")

    # contraintes globales
    if len(t) > MAX_LEN_SOFT:
        errs.append("trop_long_soft")
    if "\n" in t:
        errs.append("retour_ligne")

    if _looks_english(t):
        errs.append("langue_non_fr")
    if _REASONING_RE.search(t):
        errs.append("raisonnement_explicite")

    app.logger.info("[VALIDATE_COM] len=%d", len(t))

    # dédoublonnage stable
    seen = set()
    out = []
    for e in errs:
        if e not in seen:
            out.append(e)
            seen.add(e)
    return out


MAX_LEN_SOFT = 650
MAX_LEN_HARD = 350  # seulement sur pass2


_ANCHOR_RE = re.compile(r"^\s*La\s+(transcription|dictée)\s+mentionne\b", re.IGNORECASE)


def validate_commentaire_structure(texte: str, prefer_dictee: bool = False) -> list[str]:
    t = (texte or "").strip()
    if not t:
        return ["vide"]

    errs: list[str] = []

    sents = _split_sentences_fr(t)
    n = len(sents)
    if n not in (3, 4):
        return ["nombre_phrases"]

    s1, s2, s3 = sents[0].strip(), sents[1].strip(), sents[2].strip()
    s4 = sents[3].strip() if n == 4 else None

    # Phrase 1 : interdits
    if re.search(r"\b(transcription|dictée)\b", s1, flags=re.IGNORECASE):
        errs.append("phrase1_mention_source_interdite")
    if _ANCHOR_RE.match(s1):
        errs.append("phrase1_ancrage_interdit")
    if _MODALITES_RE.search(s1):
        errs.append("phrase1_modalisation_interdite")

    # Phrase 2 : ancrage VLM requis
    if not re.match(r"^\s*Selon la description visuelle\b", s2, flags=re.IGNORECASE):
        errs.append("phrase2_ancrage_vlm_absent")
    if re.match(r"^\s*Selon la description visuelle\s*:", s2, flags=re.IGNORECASE):
        errs.append("phrase2_ancrage_vlm_avec_deuxpoints")
    if re.search(r"\b(transcription|dictée)\b", s2, flags=re.IGNORECASE):
        errs.append("phrase2_mention_source_interdite")
    if _MODALITES_RE.search(s2):
        errs.append("phrase2_modalisation_interdite")

    # Phrases 3 (+4) : ancrage transcription/dictée requis
    expected = "dictée" if prefer_dictee else "transcription"

    def _check_tr_sentence(s: str, idx: int) -> None:
        if not re.match(rf"^\s*La\s+{expected}\s+mentionne\b", s, flags=re.IGNORECASE):
            errs.append(f"phrase{idx}_ancrage_absent_ou_mauvaise_source")
        if re.match(rf"^\s*La\s+{expected}\s+mentionne\s*:", s, flags=re.IGNORECASE):
            errs.append(f"phrase{idx}_ancrage_avec_deuxpoints")
        if _MODALITES_RE.search(s):
            errs.append(f"phrase{idx}_modalisation_interdite")

    _check_tr_sentence(s3, 3)
    if s4 is not None:
        _check_tr_sentence(s4, 4)

    return errs


SALIENT_REGEX = {
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

ANNOTER_STATS_LOCK = Lock()

ANNOTER_STATS = {
    "calls": 0,
    "ok_pass1": 0,
    "ok_pass2": 0,
    "fail": 0,
    "errs_pass1": Counter(),
    "errs_pass2": Counter(),
    "lat_ms": [],
}
def validate_salient_presence(texte: str, salient_families: list[str]) -> list[str]:
    if not salient_families:
        return []

    sents = _split_sentences_fr(texte)
    if not sents:
        return ["vide"]

    full = " ".join(sents)  # toutes les phrases
    errors = []

    for fam in salient_families:
        regexes = SALIENT_REGEX.get(fam, [])
        if not any(re.search(rx, full, re.IGNORECASE) for rx in regexes):
            errors.append(f"point_saillant_absent:{fam}")

    return errors



def _infer_task(prompt_text: str) -> str:
    u = (prompt_text or "").upper()
    if "TÂCHE — LIBELLÉ" in u:
        return "libelle"
    if "TÂCHE — COMMENTAIRE" in u:
        return "commentaire"
    return ""

# ===== App =====



app = Flask(__name__)





LOG_PATH = "asr_voxtral.log"

# Configuration du logger racine (console)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Handler fichier (rotation)
handler = RotatingFileHandler(
    LOG_PATH,
    maxBytes=10_000_000,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s"
)
handler.setFormatter(formatter)

# Attacher le handler fichier au logger Flask
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)



# ===== Flags ENV =====

DISABLE_OCR = os.getenv("DISABLE_OCR", "0") == "1"
DISABLE_DIARIZATION = os.getenv("DISABLE_DIARIZATION", "0") == "1"
AUTO_CHUNK_SEC = int(os.getenv("AUTO_CHUNK_SEC", "900"))  # 15 min
OVERLAP_SEC    = int(os.getenv("OVERLAP_SEC", "10"))      # 10 s
MIN_SPK_SEG_S  = float(os.getenv("MIN_SPK_SEG_S", "2.0")) # pour embeddings
SPK_MATCH_THR  = float(os.getenv("SPK_MATCH_THR", "0.75"))# cosine threshold
AUTO_CHUNK_STRIDE_SEC = int(os.getenv("AUTO_CHUNK_STRIDE_SEC", "30"))


print(f">>> RUNNING FILE: {__file__}")
print(f">>> CWD: {os.getcwd()}")

# =========================
# Chemins & fichiers (nouvelle archi)
# =========================

# Racines/généraux

# --- 1) Chargement centralisé des chemins ---
PATHS = load_paths()

_APP_PATHS_FILE = os.getenv("APP_PATHS_FILE")
if _APP_PATHS_FILE and not Path(_APP_PATHS_FILE).exists():
    app.logger.error(
        "❌ paths.json introuvable via APP_PATHS_FILE=%s. Utilisation des valeurs par défaut.",
        _APP_PATHS_FILE,
    )
elif not _APP_PATHS_FILE and not Path("paths.json").exists():
    app.logger.warning(
        "⚠️ paths.json introuvable dans le dossier courant (%s). Utilisation des valeurs par défaut/ENV.",
        Path("paths.json").resolve(),
    )

# --- 2) Résolution propre des chemins ---

CONFIG_PATH        = Path(PATHS["APP_CONFIG_PATH"]).resolve()
SYSTEM_PROMPT_PATH = Path(PATHS["SYSTEM_PROMPT_PATH"]).resolve()
MODELS_PATH        = Path(PATHS["MODELS_PATH"]).resolve()
MODEL_INDEX_PATH   = MODELS_PATH / "models_index.json"
APP_CONFIG_DIR     = CONFIG_PATH.parent  # D:\GPT4All_Local\config

# Ancien défaut obsolète => on aligne sur APP_CONFIG_DIR
FLASK_CONFIG_DIR = Path(os.getenv("FLASK_CONFIG_DIR", str(APP_CONFIG_DIR))).resolve()


LOG_DIR = Path(PATHS.get("APP_LOG_DIR") or PATHS.get("LOG_DIR") or (BASE_DIR / "logs")).resolve()
LOG_DIR.mkdir(parents=True, exist_ok=True)


CHROMA_BASE        = PATHS["CHROMA_BASE"]
RAG_BASE           = PATHS["RAG_BASE"]
AFFAIRES_ROOT      = Path(PATHS.get("AFFAIRES_ROOT", r"C:\Affaires")).resolve()



CHROMA_HOST        = PATHS["CHROMA_HOST"]
CHROMA_PORT        = PATHS["CHROMA_PORT"]

if not MODEL_INDEX_PATH.exists():
    raise FileNotFoundError(f"models_index.json introuvable : {MODEL_INDEX_PATH}")

# Logs & OCR

LOG_DIR  = Path(os.getenv("APP_LOG_DIR", PATHS.get("LOG_DIR", str(BASE_DIR / "logs")))).resolve()
LOG_PATH = LOG_DIR / "annoter_log.jsonl"
GRIDS_DIR = FLASK_CONFIG_DIR
DEFAULT_GRID_NAME = "ocr_grid.json"
HISTORY_PATH = (GRIDS_DIR / "ocr_history.json").resolve()

HALLU_PATTERNS_PATH = APP_CONFIG_DIR / "hallu_patterns.json"
HALLU_CANDIDATES_PATH = APP_CONFIG_DIR / "hallu_candidates.jsonl"



load_hallu_patterns()
load_spacy()


# --- 4) Chargement des fichiers essentiels ---

# (facultatif) centraliser quelques alias pour compatibilite

_MODEL_ALIASES = {
    "bge_3": "BGE_M3",
    "bge-m3": "BGE_M3",
    "Bge_m3": "BGE_M3",
    "bge": "BGE",
    "e5_multilingual_large": "E5_multilingual_large",
    "nomic_embed": "Nomic_Embed",
    "minilm_l6_v2": "MiniLM_L6_v2",
    "jina_2": "Jina_2",
    "matryoshka": "Matryoshka",
}

def _canon_name(name: str) -> str:
    if not name:
        return "Nomic_Embed"
    key = name.strip()
    alias = _MODEL_ALIASES.get(key.lower())
    return alias or key


_EMBED_CACHE = {}
_EMBED_LOCK = Lock()

# JSON Les LLM ne produisent pas naturellement du JSON strict.

EMPTY_SEGMENT = {
    "actions": [],
    "problems": [],
    "resume_segment": "",
    "themes": [],
}

JSON_START_RE = re.compile(r"[{\[]")
JSON_END_RE = re.compile(r"[}\]]")
CHAT_TOKENS = (
    "<|end|>", "<|start|>", "<|assistant|>", "<|user|>", "<|system|>",
    "<|final|>", "<|message|>", "<|channel|>"
)


def extract_last_json_object(text: str) -> dict | None:
    """
    Extrait le dernier objet JSON (dict) présent dans text.
    Robuste aux textes avant/après, aux backticks, et aux tokens parasites.
    Ne dépend que de la stdlib.
    """
    if not text:
        return None

    t = text.strip()
    # nettoyage léger (optionnel)
    t = t.replace("<|start|>", "").replace("<|end|>", "").replace("<|assistant|>", "")
    t = t.replace("```json", "```")

    last_obj = None
    i = 0
    n = len(t)

    while i < n:
        if t[i] != "{":
            i += 1
            continue

        start = i
        depth = 0
        in_str = False
        esc = False

        while i < n:
            c = t[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        chunk = t[start:i+1]
                        try:
                            obj = json.loads(chunk)
                            if isinstance(obj, dict):
                                last_obj = obj
                        except Exception:
                            pass
                        break
            i += 1

        i += 1  # avance après la fin du chunk (ou continue)

    return last_obj







# ========================:contentReference[oaicite:5]{index=5}e
# VLM initialisation
# =========================
BACKEND_LOCK = threading.RLock()  # verrou global pour tout llama.cpp (VLM + LLM)

VLM_LOCK = threading.Lock()
VLM_ACTIVE = 0

def _vlm_acquire():
    global VLM_ACTIVE
    with VLM_LOCK:
        VLM_ACTIVE += 1

def _vlm_release():
    global VLM_ACTIVE
    with VLM_LOCK:
        VLM_ACTIVE -= 1



@app.post("/vision/purge_vlm")
def vision_purge_vlm():
    with BACKEND_LOCK:
        with VLM_LOCK:
            if VLM_ACTIVE != 0:
                return jsonify({"ok": False, "error": "VLM busy", "active": VLM_ACTIVE}), 409

            _VLM_CACHE.clear()
            _VLM_LOCKS.clear()
            _VLM_INFER_LOCKS.clear()

        gc.collect()
        return jsonify({"ok": True, "message": "VLM purged"})


# votre singleton VLM (ex: llama_cpp.Llama) + éventuellement mmproj/clip associés
VLM_INSTANCE = None


_VLM_CACHE: dict[str, Llama] = {}
_VLM_LOCKS: dict[str, threading.Lock] = {}
# Sérialisation des inférences par modèle (Llama n'est pas thread-safe)
_VLM_INFER_LOCKS: dict[str, threading.Lock] = {}

VISION_JSON_SYSTEM_PROMPT = """
Tu es un module d'observation visuelle pour une expertise technique.
Tu produis exclusivement un JSON valide.
Tu décris uniquement des faits matériels visibles sur l’image.
Tu n’infères jamais une cause, une responsabilité ou une qualification juridique.
En cas d’incertitude, tu la mentionnes explicitement.
Si un élément n’est pas visible, tu ne l’inventes pas.
"""

VLM_CHECK_KEYWORDS = [
    "gouttiere", "descente", "chenau",
    "tuyau", "tuyauterie", "conduit",
    "coude", "raccord", "raccordement", "collier", "emboitement", "joint", "jonction", "manchon",
    "pvc", "plastique", "metal", "zinc", "cuivre", "alu", "acier",
    "fuite", "goutte", "humidite", "trace",
    "fissure", "microfissure", "jointoiement",
]


def _matched_keyword(text: str) -> str | None:
    t = _norm_text(text)
    for kw in VLM_CHECK_KEYWORDS:
        if f" {kw} " in t:
            return kw
    return None

def _norm_text(s: str) -> str:
    if not s:
        return ""

    s = s.lower()

    # homogénéise apostrophes AVANT normalisation
    s = s.replace("’", "'").replace("`", "'")

    # retire les accents
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))

    # remplace tout ce qui n'est pas lettre/chiffre par espace
    s = re.sub(r"[^a-z0-9]+", " ", s)

    # espaces sentinelles pour tests " mot "
    return f" {s.strip()} "


def _contains_keywords(text: str) -> bool:
    t = _norm_text(text)
    # VLM_CHECK_KEYWORDS doit contenir des mots/expressions "normalisés" (sans accents)
    return any(f" {kw} " in t for kw in VLM_CHECK_KEYWORDS)

def _clip_context_around_keyword(text: str, max_chars: int = 1200) -> str:
    t = _norm_text(text)
    for kw in VLM_CHECK_KEYWORDS:
        pos = t.find(f" {kw} ")
        if pos >= 0:
            start = max(0, pos - max_chars // 2)
            end   = min(len(text), start + max_chars)
            return text[start:end]
    return _clip_context(text, max_chars)


def _clip_context(text: str, max_chars: int = 1200) -> str:
    """Évite les contextes trop longs (batch) : conserve la fin, souvent la plus utile."""
    if not text:
        return ""
    s = str(text).strip()
    if len(s) <= max_chars:
        return s
    return "… " + s[-max_chars:]


def _infer_with_lock(model_name: str, fn):
    if model_name not in _VLM_INFER_LOCKS:
        _VLM_INFER_LOCKS[model_name] = threading.Lock()
    with _VLM_INFER_LOCKS[model_name]:
        return fn()


def _is_vision_model(entry: dict) -> bool:
    caps = entry.get("capabilities") or {}
    return bool(caps.get("vision")) or bool(entry.get("mmproj"))

def _data_uri_from_image_bytes(img_bytes: bytes, mime: str = "image/jpeg") -> str:
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"

def _guess_mime(filename: str | None) -> str:
    fn = (filename or "").lower()
    if fn.endswith(".png"): return "image/png"
    if fn.endswith(".webp"): return "image/webp"
    return "image/jpeg"

def _get_vlm(model_name: str) -> Llama:
    """
    Charge (lazy) un modèle vision (GGUF + mmproj) à partir de models_index.json.
    """

    name = (model_name or "").strip()
    if not name:
        raise ValueError("model_name vide")

    entry = models_index.get(name)
    if not entry:
        raise ValueError(f"Modèle introuvable dans models_index.json: {name}")
    if not _is_vision_model(entry):
        raise ValueError(f"Modèle non 'vision': {name}")

    # cache direct
    if name in _VLM_CACHE:
        return _VLM_CACHE[name]

    # verrous par modèle
    if name not in _VLM_LOCKS:
        _VLM_LOCKS[name] = threading.Lock()

    if name not in _VLM_INFER_LOCKS:
        _VLM_INFER_LOCKS[name] = threading.Lock()

    with _VLM_LOCKS[name]:
        if name in _VLM_CACHE:
            return _VLM_CACHE[name]

        model_path = MODELS_PATH / entry["directory"] / entry["file"]
        if not model_path.exists():
            raise FileNotFoundError(f"GGUF introuvable: {model_path}")

        mmproj = entry.get("mmproj")
        if not mmproj:
            raise ValueError(f"mmproj manquant pour le modèle vision: {name}")
        mmproj_path = MODELS_PATH / entry["directory"] / mmproj
        if not mmproj_path.exists():
            raise FileNotFoundError(f"mmproj introuvable: {mmproj_path}")

        chat_handler = Llava15ChatHandler(clip_model_path=str(mmproj_path))

        eff = effective_params(name)
        n_ctx = max(int(eff.get("n_ctx", N_CTX)), 4096)

        vlm = Llama(
            model_path=str(model_path),
            chat_handler=chat_handler,
            n_ctx=n_ctx,
            logits_all=True,
            verbose=False,
            n_gpu_layers=int(eff.get("n_gpu_layers", 0)),
            n_threads=int(eff.get("n_threads", 8)),
            n_batch=int(eff.get("n_batch", 256)),
        )

        _VLM_CACHE[name] = vlm
        return vlm


STRONG_PATTERNS = [
    # coude + matériau -> déclenchement quasi certain
    r"\bcoude\b.*\b(plastique|pvc|metal|zinc|cuivre|alu|acier)\b",
    r"\b(plastique|pvc|metal|zinc|cuivre|alu|acier)\b.*\bcoude\b",

    # fuite/goutte + gouttière/descente
    r"\b(fuite|goutte|gouttes|trace)\b.*\b(gouttiere|descente|chenau|chenaux)\b",
    r"\b(gouttiere|descente|chenau|chenaux)\b.*\b(fuite|goutte|gouttes|trace)\b",

    # fissure
    r"\b(microfissure|fissure)\b",
]

def is_context_exploitable(text: str) -> bool:
    if not text:
        return False

    t = _norm_text(text)  # ✅ IMPORTANT: normalisation (accents -> sans accents, ponctuation, espaces)

    # 1) longueur minimale (moins stricte pour l’oral)
    if len(t) < 120:
        return False

    # 2) signaux forts (déclenche MODE B même si diversité faible)
    for rx in STRONG_PATTERNS:
        if re.search(rx, t):
            return True

    # 3) au moins 2 mots-clés distincts (avec détection "mot entier")
    hits = set()
    padded = f" {t} "
    for kw in VLM_CHECK_KEYWORDS:
        if f" {kw} " in padded:
            hits.add(kw)
    if len(hits) < 2:
        return False

    # 4) anti-bruit : ratio moins pénalisant + bypass si hits nombreux
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿñæœ'-]{2,}", t)
    if not words:
        return False

    if len(hits) >= 4:
        return True  # bypass: beaucoup de signaux, on accepte même si oral répétitif

    if len(set(words)) / max(1, len(words)) < 0.20:
        return False

    return True

def load_prompt_profile(profile: str) -> dict:
    if profile == "batch":
        path = Path(CONFIG_DIR) / "prompt_gpt_batch_only.json"
    else:
        path = Path(CONFIG_DIR) / "prompt_gpt.json"
    return json.loads(path.read_text(encoding="utf-8"))

# -------------------------------------------------
# Prompts VLM (COMMUNS) — version à copier/coller
# -------------------------------------------------

def build_vlm_prompts(raw_context: str, prompt: str = "") -> tuple[str, str, bool, str]:
    """
    Retourne:
      - system (str)
      - user_text (str)
      - use_mode_b (bool)
      - clipped_context_used (str)  # ce qui a réellement été injecté dans le prompt
    """
    raw_context = (raw_context or "").strip()
    prompt = (prompt or "").strip()

    # 🔑 Détection MODE B AVANT clipping
    # Remplacez par _contains_keywords(raw_context) si vous n'avez pas is_context_exploitable()
    use_mode_b = is_context_exploitable(raw_context)

    # ✂️ Clipping après décision
    ctx = _clip_context(raw_context, 1200)

    # SYSTEM (strict, non assistant)
    system = (
        "Tu es un module de perception visuelle.\n"
        "Tu décris uniquement ce qui est visible sur l’image, en français, de manière factuelle.\n"
        "Tu n’inventes rien.\n"
        "Tu ne déduis pas un matériau ou un défaut si l’indice visuel n’est pas visible.\n"
        "Si une information n’est pas certaine, tu l’indiques explicitement."
    )

    if not use_mode_b:
        # -------------------------
        # MODE A — description factuelle seule
        # -------------------------
        user_text = (
            "Décris l’image de manière factuelle et très précise, en français.\n"
            "Exigences :\n"
            "1) Décrire les éléments matériels visibles (façade, sol, seuil, conduites, raccords, etc.).\n"
            "2) Attention particulière aux conduites/tuyaux/gouttières : segments, coudes, raccords, colliers, changements d’aspect.\n"
            "3) Si un changement de matériau semble possible, le signaler avec un degré d’incertitude "
            "(certain / probable / incertain) et indiquer les indices visuels.\n"
            "4) Ne jamais inventer. Si la matière exacte n’est pas identifiable : « matière non certaine ».\n"
            "5) Sortie : 6 à 10 phrases courtes maximum, sans puces."
        )

        if ctx:
            user_text += "\n\nContexte (à utiliser seulement s'il aide sans inventer) :\n" + ctx

        # En MODE A, on peut ajouter une consigne sans casser un format “sections”
        if prompt:
            user_text += "\n\nConsigne spécifique (à respecter sans inventer) :\n" + prompt

        clipped_used = ctx

    else:
        # -----------------------------------------------
        # MODE B — description + vérification guidée texte
        # FORMAT STRICT 3 SECTIONS
        # -----------------------------------------------

        # ⚠️ Ne pas ajouter une 4e section.
        # On fusionne la consigne spécifique dans le contexte.
        ctx_b = ctx
        if prompt:
            if ctx_b:
                ctx_b = ctx_b + "\n\n[Consigne spécifique]\n" + prompt
            else:
                ctx_b = "[Consigne spécifique]\n" + prompt

        user_text = (
            "Tu décris UNIQUEMENT ce qui est visible sur la photo.\n"
            "Interdictions : ne pas inventer, ne pas conclure, ne pas qualifier (pas de défaut/malfaçon/conformité), "
            "ne pas déduire un matériau ou une cause sans indice visuel.\n\n"
            "Contexte (transcription / propos) :\n"
            f"{ctx_b if ctx_b else '(aucun)'}\n\n"
            "SORTIE OBLIGATOIRE (respecter exactement les 3 sections, dans cet ordre, sans ajout) :\n\n"
            "DESCRIPTION VISUELLE :\n"
            "- 6 à 10 phrases courtes, factuelles.\n"
            "- Décrire les éléments matériels visibles (façade, sol, conduites, raccords, colliers, coudes, etc.).\n"
            "- Si la matière n’est pas identifiable : écrire « matière non certaine ».\n\n"
            "ÉLÉMENTS MENTIONNÉS DANS LE CONTEXTE :\n"
            "- Lister uniquement les éléments explicitement mentionnés dans le contexte (max 6 lignes).\n"
            "- Format strict par ligne : <élément> : [VISIBLE|PROBABLE|INCERTAIN|NON VISIBLE] — <indice(s) visuel(s) ou 'aucun indice'>\n"
            "- Si statut [VISIBLE] ou [PROBABLE] : donner 1 à 2 indices visuels.\n"
            "- Si statut [NON VISIBLE] : écrire 'aucun indice'.\n\n"
            "POINTS À CONTRÔLER SUR LA PHOTO :\n"
            "- 2 à 4 lignes, factuelles, orientées prise de vue (gros plan, angle, éclairage, raccord/coude).\n"
        )

        clipped_used = ctx_b

    return system, user_text, use_mode_b, clipped_used


# -------------------------------------------------
# Batch: construit raw_context total (global + spécifique)
# -------------------------------------------------
def build_batch_raw_context(context_global: str, context_specific: str) -> str:
    cg = (context_global or "").strip()
    cs = (context_specific or "").strip()
    return "\n\n".join([x for x in (cg, cs) if x]).strip()

# -----------------------------------------------------------

def _get_embedder(name: str):
    """Retourne TOUJOURS une instance SentenceTransformer avec .encode(...)."""
    key = _canon_name(name)

    emb = _EMBED_CACHE.get(key)
    if emb is not None:
        return emb

    with _EMBED_LOCK:
        emb = _EMBED_CACHE.get(key)
        if emb is not None:
            return emb

        try:
            emb = load_embedder(key)
            app.logger.info("load_embedder(%s) -> %s", key, type(emb))
            app.logger.info("helpers_embed @ %s", getattr(helpers_embed, "__file__", "?"))
            app.logger.info("sentence_transformers @ %s", getattr(sentence_transformers, "__file__", "?"))
        except Exception:
            _EMBED_CACHE.pop(key, None)
            raise

        if not hasattr(emb, "encode"):
            raise TypeError(f"_get_embedder: objet invalide (pas d'attribut .encode): {type(emb)}")

        _EMBED_CACHE[key] = emb
        return emb


# OCR grids (conserve ton paramétrage)

# Sous-dossiers par défaut (utilisés pour RAG_PC/_QALogs uniquement)
DEFAULT_SUBDIRS = {
    "rag_pc_subdir": "RAG_PC"
}

# --- Index projets (Laptop tient ce fichier à jour ; le serveur doit savoir le lire) ---
# 1) si variable d'env fournie, on l'utilise ; sinon fallback sur voisin de CONFIG_PATH
def resolve_projets_index_path() -> Path:
    env_path = (os.getenv("PROJETS_INDEX_PATH") or "").strip()
    if env_path:
        resolved = Path(env_path).resolve()
        log.info("projets_index.json resolved from PROJETS_INDEX_PATH: %s", resolved)
        return resolved

    app_config_dir = (os.getenv("APP_CONFIG_DIR") or "").strip()
    if app_config_dir:
        resolved = (Path(app_config_dir) / "projets_index.json").resolve()
        log.info("projets_index.json resolved from APP_CONFIG_DIR: %s", resolved)
        return resolved

    resolved = (APP_CONFIG_DIR / "projets_index.json").resolve()
    log.info("projets_index.json resolved from default APP_CONFIG_DIR: %s", resolved)
    return resolved


PROJETS_INDEX_PATH = resolve_projets_index_path()

# === Nouveau schéma: project_config par affaire contient 'roots' + 'paths' relatifs ===
#    On garde une compat de lecture : si ancien schéma, on normalise.
# (Option) charge config applicative générale (indépendante des affaires)

def load_projets_index():
    if not PROJETS_INDEX_PATH.exists():
        log.warning("projets_index.json introuvable: %s; utilisation d'un registre vide", PROJETS_INDEX_PATH)
        return []

    idx = _load_json(PROJETS_INDEX_PATH, [])
    if not isinstance(idx, list):
        log.warning("projets_index.json invalide (liste attendue): %s", PROJETS_INDEX_PATH)
        return []

    normalized = []
    for it in idx or []:
        item = dict(it)
        if "id" not in item and "id_projet" in item:
            item["id"] = item["id_projet"]
        normalized.append(item)
    return normalized



APP_CONFIG = load_json_safe(str(CONFIG_PATH)) or {}

# =========================
# Config
# =========================


# =========================
# Llama.cpp init
# =========================

def load_json_loose(path):
    txt = Path(path).read_text(encoding="utf-8")
    # supprime commentaires // et /* ... */
    txt = re.sub(r"//.*?$|/\*.*?\*/", "", txt, flags=re.M|re.S)
    # supprime virgules traînantes
    txt = re.sub(r",\s*(\}|\])", r"\1", txt)
    return json.loads(txt)

def _load_app_config(path: Path) -> dict:
    if not path.exists():
        app.logger.error("❌ config.json introuvable: %s", path)
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        app.logger.warning(
            "⚠️ config.json invalide (%s). Tentative de chargement tolérant.",
            e,
        )
        try:
            return load_json_loose(path)
        except Exception as loose_err:
            app.logger.error(
                "❌ Impossible de charger config.json (%s): %s",
                path,
                loose_err,
            )
            return {}
    except Exception as e:
        app.logger.error("❌ Impossible de lire config.json (%s): %s", path, e)
        return {}


def _config_dict_section(raw_config: dict, key: str, *, path: Path) -> dict:
    value = raw_config.get(key)
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    app.logger.warning(
        "⚠️ Section config invalide '%s' dans %s (type=%s). Fallback sur {}.",
        key,
        path,
        type(value).__name__,
    )
    return {}


def _config_int(value, default: int, label: str, *, path: Path) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        app.logger.warning(
            "⚠️ Valeur invalide pour '%s' dans %s: %r. Fallback=%s.",
            label,
            path,
            value,
            default,
        )
        return default


def _config_float(value, default: float, label: str, *, path: Path) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        app.logger.warning(
            "⚠️ Valeur invalide pour '%s' dans %s: %r. Fallback=%s.",
            label,
            path,
            value,
            default,
        )
        return default


config = _load_app_config(CONFIG_PATH)


limits = _config_dict_section(config, "http_limits", path=CONFIG_PATH)
log.info("http_limits raw=%s", limits)
log.info("APP_ID(after config load)=%s", id(app))



# =========================
# models_index.json
# =========================

with open(MODEL_INDEX_PATH, "r", encoding="utf-8") as f:
    models_index = json.load(f)

# ⚠️ on utilise les nouvelles clés
DEFAULT_LLM   = config.get("default_llm",   "Qwen_2_5_14B")
DEFAULT_ASR   = config.get("default_asr",   "Voxtral_Mini_3B_Transformers")
DEFAULT_EMBED = config.get("default_embed", "Nomic_Embed")  # <-- aligne avec models_index.json
KNOWN_LLMS    = set(models_index.keys())
PARAMS        = _config_dict_section(config, "parameters", path=CONFIG_PATH)
PER_MODEL     = _config_dict_section(config, "per_model_parameters", path=CONFIG_PATH)  # nouveau (optionnel)
API_KEYS      = list(_config_dict_section(config, "api_keys", path=CONFIG_PATH).values())
PORT          = _config_int(config.get("port", 5050), 5050, "port", path=CONFIG_PATH)
DEFAULT_MODEL = config.get("default_model") or config.get("default_llm")
PARAMS = _config_dict_section(config, "parameters", path=CONFIG_PATH)
PER_MODEL = _config_dict_section(config, "per_model_parameters", path=CONFIG_PATH)


OVERR_KEYS = ["temperature", "top_p", "top_k", "repeat_penalty", "max_tokens", "presence_penalty", "frequency_penalty", "stop",
              "n_ctx", "marge","min_prompt_tokens", "n_threads", "n_gpu_layers", "n_batch"]
# --- après avoir chargé `config` et déterminé le chemin du modèle ---
_INT_KEYS = {"n_ctx", "n_threads", "n_gpu_layers", "n_batch", "max_tokens", "top_k"}
_FLOAT_KEYS = {"temperature", "top_p", "repeat_penalty", "presence_penalty","frequency_penalty"}
INIT_KEYS = {"n_ctx", "n_threads", "n_gpu_layers", "n_batch"}
#-----------------------------------------------


# Params spécifiques du modèle effectivement chargé
MODEL_PARAMS = PER_MODEL.get(DEFAULT_MODEL, {})
N_CTX = MODEL_PARAMS.get("n_ctx", PARAMS.get("n_ctx", 4096))
DEFAULT_LOCAL_MAX_TOKENS = MODEL_PARAMS.get("max_tokens", PARAMS.get("max_tokens", 1024))
DEFAULT_LOCAL_MARGE_TOKENS = int(os.getenv("local_marge_tokens", "128"))
DEFAULT_LOCAL_MIN_PROMPT_TOKENS = int(os.getenv("local_min_prompt_tokens", "512"))


# COMFYUI



_boot_lock = threading.Lock()


def comfy_healthy(timeout=0.8) -> bool:
    try:
        r = requests.get(COMFY_URL + "/", timeout=timeout)
        return r.ok
    except Exception:
        return False

def ensure_comfy_ui(want_boot: bool, max_wait_s: float = 45) -> bool:
    # Si déjà ok → rien à faire
    if comfy_healthy():
        return True
    # Si on ne veut pas booter → stop
    if not want_boot:
        return False
    # Boot protégé (à la demande)
    with _boot_lock:
        if comfy_healthy():
            return True
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        try:
            subprocess.Popen(
                [COMFY_CONF.get("python", r"D:\envs\sd\Scripts\python.exe"),
                 "main.py", "--listen", COMFY_HOST, "--port", str(COMFY_PORT)],
                cwd=COMFY_CONF.get("cwd", r"D:\Apps\ComfyUI"),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
        except Exception:
            return False
    # Attente de disponibilité
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        if comfy_healthy():
            return True
        time.sleep(1)
    return False


# --- ComfyUI: dossier output natif (fallback si non précisé en config)


COMFY_CONF = _config_dict_section(config, "comfyui", path=CONFIG_PATH)
COMFY_HOST = COMFY_CONF.get("host", "127.0.0.1")
COMFY_PORT = _config_int(COMFY_CONF.get("port", 8188), 8188, "comfyui.port", path=CONFIG_PATH)
COMFY_TIMEOUT = _config_float(COMFY_CONF.get("timeout_s", 120), 120.0, "comfyui.timeout_s", path=CONFIG_PATH)
COMFY_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"
COMFY_AUTO_BOOT = bool(COMFY_CONF.get("auto_boot", False))
COMFY_CWD = Path(COMFY_CONF.get("cwd", r"D:\Apps\ComfyUI"))
COMFY_OUTPUT = Path(COMFY_CONF.get("output_dir", COMFY_CWD / "output"))
COMFY_OUTPUT_DIR = Path((COMFY_CONF or {}).get("output_dir", r"D:\Apps\ComfyUI\output")).resolve()
# --- Sous-dossier images côté "affaire" (tu peux changer le nom)
AFFAIRE_SD_SUBDIR = PATHS.get("AFFAIRE_SD_SUBDIR", r"AD_Expert_Traitements\_SD_Images")



sd_bp = Blueprint("sd", __name__)
bp = Blueprint("search", __name__)



# CORS(app, resources={
#    r"/comfyui/*": {"origins": "*"},
#    r"/search_web": {"origins": "*"},
    
#})
CORS(app, resources={r"/*": {"origins": "*"}})


SEARXNG_BASE = os.getenv("SEARXNG_BASE", "http://10.0.1.1:8080") 
BRAVE_KEY    = os.getenv("BRAVE_API_KEY", "")
TAVILY_KEY   = os.getenv("TAVILY_API_KEY", "")
PERPLEX_KEY  = os.getenv("PERPLEXITY_API_KEY", "")


#-------------------------------------------------

def effective_params(model_name: str, overrides: dict | None = None) -> dict:
    # base globale
    eff = dict(PARAMS)

    # surcharge par modèle
    eff.update(PER_MODEL.get(model_name, {}))

    # overrides dynamiques (batch / UI / API)
    if overrides:
        for k in OVERR_KEYS:
            if k in overrides and overrides[k] is not None:
                eff[k] = overrides[k]

    # NORMALISATION UNIQUE ICI
    return _normalize_types(eff)




def make_gen_kwargs_from_effective(model_name: str, data: dict) -> dict:
    # récupère ce que le client a demandé dans le body (comme aujourd'hui)
    requested = {k: data.get(k, None) for k in OVERR_KEYS}
    eff = effective_params(model_name, requested)
    return make_gen_kwargs(eff)  # ta fonction existante

def clamp_max_tokens(eff: dict, prompt_tokens: int, safety: int = 256) -> dict:
    if not isinstance(eff, dict):
        fallback_max_tokens = DEFAULT_LOCAL_MIN_PROMPT_TOKENS
        try:
            fallback_max_tokens = int(eff)
        except Exception:
            pass
        app.logger.warning(
            "clamp_max_tokens: expected dict, got %s; rebuilding minimal effective params",
            type(eff).__name__,
        )
        eff = {"n_ctx": N_CTX, "max_tokens": fallback_max_tokens}

    n_ctx = int(eff.get("n_ctx", N_CTX))
    max_t = int(eff.get("max_tokens", DEFAULT_LOCAL_MIN_PROMPT_TOKENS))

    raw_budget = n_ctx - prompt_tokens - safety

    # Si le budget est négatif → erreur amont préférable
    if raw_budget <= 0:
        eff["max_tokens"] = DEFAULT_LOCAL_MARGE_TOKENS
        return eff

    if max_t > raw_budget:
        eff["max_tokens"] = raw_budget

    return eff


def _norm(items, source):
    out = []
    for it in items or []:
        out.append({
            "title": it.get("title") or it.get("name") or it.get("url"),
            "url": it.get("url") or it.get("link"),
            "snippet": it.get("content") or it.get("snippet") or it.get("description"),
            "source": source
        })
    return out

def _normalize_types(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if v is None: 
            continue
        if k in _INT_KEYS:
            try: out[k] = int(v)
            except: pass
        elif k in _FLOAT_KEYS:
            try: out[k] = float(v)
            except: pass
        else:
            out[k] = v
    return out

def make_llama(path: Path, model_name: str) -> Llama:
    eff = effective_params(model_name)

    init_kwargs = {}
    for k in INIT_KEYS:  # n_ctx, n_threads, n_gpu_layers, n_batch
        if k in eff:
            init_kwargs[k] = eff[k]

    # chat_format éventuel par modèle
    chat_format = (models_index.get(model_name) or {}).get("chat_format")
    if chat_format:
        init_kwargs["chat_format"] = chat_format

    return Llama(
        model_path=str(path),
        use_mlock=False,
        verbose=False,
        **init_kwargs
    )



# --- après avoir chargé le dict CONFIG depuis config.json ---




# Charge le LLM par défaut

llm_entry = models_index.get(DEFAULT_LLM)
if not llm_entry:
    raise ValueError(f"Modèle LLM par défaut introuvable dans models_index.json: {DEFAULT_LLM}")

llm_path = MODELS_PATH / llm_entry["directory"] / llm_entry["file"]
if not llm_path.exists():
    raise FileNotFoundError(f"Fichier modèle introuvable: {llm_path}")

print(f"✅ Chargement du modèle : {DEFAULT_LLM}")
print(f"📄 Fichier : {llm_path}")
start = time.time()
llm = make_llama(llm_path, DEFAULT_LLM)
LOADED_MODEL_NAME = DEFAULT_LLM
print(f"🕒 Modèle chargé en {time.time() - start:.2f} secondes.")
print("🧠 LLM prêt.")
DEFAULT_VISION = config.get("default_vision", "SmolVLM2_2B")


# 👉 instanciation Flask 



app.logger.info("🔧 CONFIG_PATH utilisé: %s", CONFIG_PATH)
app.logger.info("🔧 PARAMS: %s", PARAMS)

# Caches Voxtral
VOXTRAL_PIPELINES = {}
VOXTRAL_LOCKS = {}


# ---- Voxtral report prompts resolution & safe fallback ----
DEFAULT_REPORT_PROMPTS_BASENAME = "voxtral_report_prompts.json"



# =========================
# helpers  
# =========================

def _embedded_default_report_prompts() -> dict:
    # Minimal safe default; keep key name used by your code
    return {
        "expert_compte_rendu_v1": {
            "label": "Résumé expert (FR)",
            "role": "Tu es un·e expert·e qui synthétise une réunion en français.",
            "context": "Les lignes suivantes sont des tours de parole horodatés.",
            "task": [
                "Lister les points clés par thème",
                "Repérer décisions, TODOs, risques",
                "Conserver les noms propres si présents"
            ],
            "constraints": [
                "Style concis, puces",
                "Pas d'invention de faits"
            ],
            "format": [
                "Sections: Contexte, Décisions, Actions, Points ouverts"
            ],
            "fewshot": "- Ex: Décision: valider le lot carrelage avant vendredi."
        }
    }

def _resolve_report_prompts_path(arg_path: str | None) -> str | None:
    """
    Priority:
      1) explicit arg_path (from app.py CLI or /asr_voxtral payload)
      2) config dir next to CONFIG_PATH (…/config/voxtral_report_prompts.json)
      3) GRIDS_DIR/voxtral_report_prompts.json
    Returns a path string if the file exists, else None (to trigger fallback).
    """
    candidates: list[Path] = []
    if arg_path:
        candidates.append(Path(arg_path))

    # CONFIG_PATH usually like ...\config\app_config.json → try sibling in the same dir
    try:
        cfg_dir = Path(CONFIG_PATH).parent
        candidates.append(cfg_dir / DEFAULT_REPORT_PROMPTS_BASENAME)
    except Exception:
        pass

    # Also try GRIDS_DIR (you already use it for OCR grids/histories)
    try:
        candidates.append(GRIDS_DIR / DEFAULT_REPORT_PROMPTS_BASENAME)
    except Exception:
        pass

    for p in candidates:
        try:
            if p and p.exists() and p.is_file():
                return str(p.resolve())
        except Exception:
            continue
    return None


def extract_json_block(text: str) -> str:
    """
    Extrait le premier bloc JSON plausible (objet ou tableau) d'un texte.
    Hypothèse : le modèle peut renvoyer du texte avant/après, ou du markdown.
    """
    if not text:
        raise ValueError("Réponse LLM vide.")

    # 1) Chercher un éventuel wrapper <json>...</json>
    m = re.search(r"<json>(.+?)</json>", text, flags=re.S | re.I)
    if m:
        candidate = m.group(1).strip()
    else:
        candidate = text.strip()

    # 2) Prendre du premier { ou [ au dernier } ou ]
    start_match = JSON_START_RE.search(candidate)
    if not start_match:
        raise ValueError("Aucun début de JSON trouvé dans la réponse.")

    start = start_match.start()

    # on cherche le dernier } ou ] après start
    end_brace = candidate.rfind("}")
    end_bracket = candidate.rfind("]")
    end = max(end_brace, end_bracket)

    if end <= start:
        raise ValueError("Bornes JSON incohérentes dans la réponse.")

    return candidate[start:end + 1]

def try_parse_json_strict(payload: str) -> Any:
    """
    Essaie de parser le JSON en plusieurs passes de "réparation légère".
    On reste volontairement simple : pas de magie, juste les pannes fréquentes des LLM.
    """
    # PASS 1 : brut
    try:
        return json.loads(payload)
    except Exception:
        pass

    # PASS 2 : suppression de virgules finales avant } ou ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", payload)
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # PASS 3 : remplacement ' → " (dict Python)
    cleaned2 = cleaned.replace("'", '"')
    try:
        return json.loads(cleaned2)
    except Exception:
        pass

    raise ValueError("Impossible de parser la réponse comme JSON même après réparations légères.")
 
 # Helper pour imposer un schéma “Pass 1"

PASS1_EXPECTED_KEYS = {"resume_segment", "themes", "actions", "problems"}

def normalize_pass1_object(obj: Any) -> Dict[str, Any]:
    """
    Sécurise la structure pour la passe 1.
    Si le modèle renvoie des choses en plus, on les ignore.
    Si des champs manquent, on les complète par défaut.
    """
    if not isinstance(obj, dict):
        raise ValueError("La racine JSON doit être un objet pour la passe 1.")

    out = {}
    out["resume_segment"] = obj.get("resume_segment", "") or ""
    out["themes"] = obj.get("themes", []) or []
    out["actions"] = obj.get("actions", []) or []
    out["problems"] = obj.get("problems", []) or []

    return out




def _hash12(s: str) -> str:
    return sha256((s or "").encode("utf-8")).hexdigest()[:12]


_VALID = re.compile(r"[^a-zA-Z0-9._-]+")

def _sanitize(s: str, maxlen: int) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = _VALID.sub("_", s)
    s = s.strip("._-")
    return s[:maxlen]

def _get_mem_ids(data: dict, request):
    app_id = (
        request.headers.get("x-app-id")
        or data.get("app_id")
        or "default_app"
    )
    conv_id = (
        request.headers.get("x-conversation-id")
        or data.get("conversation_id")
        or data.get("memory_id")
        or data.get("chat_id")
        or data.get("thread_id")
        or ""
    )

    app_id = _sanitize(app_id, 64)
    conv_id = _sanitize(conv_id, 128)

    if not conv_id:
        return app_id, None  # sécurité : pas de mémoire implicite

    return app_id, conv_id

def _mem_collection_name(api_key: str, app_id: str, conv_id: str) -> str:
    h = sha256((api_key or "anon").encode("utf-8")).hexdigest()[:12]
    raw = f"memoire_chat_{h}_{app_id}_{conv_id}"
    return _safe_coll_name(raw)


# Helper générique : appel modèle + JSON

def generate_json_for_pass1(transcript_block: str) -> Dict[str, Any]:
    """
    Utilise le modèle local LLaMA_3_8B (ou autre) pour produire un JSON strict
    pour un segment (Pass 1).
    """
    system_prompt = (
        "Tu es un assistant d'analyse de réunions. "
        "À partir d'une transcription de ~20–30 minutes, "
        "tu produis une synthèse factuelle au format JSON STRICT.\n\n"
        "Schéma EXACT attendu :\n"
        "{\n"
        '  "resume_segment": "string",\n'
        '  "themes": [\n'
        '    { "titre": "string", "synthese": ["string", "..."], "timecodes": ["HH:MM:SS", "..."] }\n'
        "  ],\n"
        '  "actions": [\n'
        '    { "action": "string", "responsable": "string", "echeance": "YYYY-MM-DD | null" }\n'
        "  ],\n"
        '  "problems": [\n'
        '    { "probleme": "string", "solution": "string" }\n'
        "  ]\n"
        "}\n\n"
        "Aucune explication, aucun texte hors JSON.\n"
        "Ne renvoie que le JSON, encadré par les balises <json> et </json>."
    )

    user_prompt = (
        "Transcription du segment :\n\n"
        f"{transcript_block}\n\n"
        "RENVOIE UNIQUEMENT :\n"
        "<json>\n"
        "{ ... JSON STRICT ... }\n"
        "</json>"
    )

    full_prompt = f"<|system|>\n{system_prompt}\n<|user|>\n{user_prompt}\n<|assistant|>"

    # ⚠️ À adapter à votre API modèle réelle :
    raw_text = llm.generate(
        full_prompt,
        max_tokens=1024,
        temp=0.2,
        top_p=0.9,
        top_k=40,
        repeat_penalty=1.15,
    )

    # Extraction / parsing JSON
    json_str = extract_json_block(raw_text)
    obj = try_parse_json_strict(json_str)
    obj_norm = normalize_pass1_object(obj)
    return obj_norm




def _try_json_loads(s: str) -> Dict[str, Any] | None:
    """
    Essaie plusieurs variantes tolérantes pour charger un JSON.
    Retourne None en cas d'échec.
    """
    if not s:
        return None

    # 1) tentative brute
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) remplacement grossier des quotes simples par doubles
    s2 = s.replace("'", '"')
    try:
        return json.loads(s2)
    except Exception:
        pass

    # 3) suppression de backslashes superflus
    s3 = re.sub(r'\\(?!["\\/bfnrtu])', "", s2)
    try:
        return json.loads(s3)
    except Exception:
        return None

def _extract_json_block(text: str) -> str:
    """
    Extrait le premier bloc JSON plausible :
    - supporte du texte avant/après,
    - supporte un wrapper <json>...</json>.
    """
    if not text:
        raise ValueError("Réponse LLM vide.")

    t = text.strip()

    # 1) wrapper <json>...</json> s'il existe
    m = re.search(r"<json>(.+?)</json>", t, flags=re.S | re.I)
    if m:
        candidate = m.group(1).strip()
    else:
        candidate = t

    # 2) on prend du premier { ou [ au dernier } ou ]
    start_match = JSON_START_RE.search(candidate)
    if not start_match:
        raise ValueError("Aucun début de JSON trouvé dans la réponse.")

    start = start_match.start()
    end_brace = candidate.rfind("}")
    end_bracket = candidate.rfind("]")
    end = max(end_brace, end_bracket)

    if end <= start:
        # on laisse la main à la fonction de "réparation"
        raise ValueError("Bornes JSON incohérentes dans la réponse.")

    return candidate[start : end + 1]


def _try_parse_json_strict(payload: str):
    """
    Parsing JSON en plusieurs passes "légères".
    """
    # PASS 1 : brut
    try:
        return json.loads(payload)
    except Exception:
        pass

    # PASS 2 : suppression des virgules finales
    cleaned = re.sub(r",\s*([}\]])", r"\1", payload)
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # PASS 3 : remplacement ' → " (style dict Python)
    cleaned2 = cleaned.replace("'", '"')
    try:
        return json.loads(cleaned2)
    except Exception:
        pass

    raise ValueError("Impossible de parser la réponse comme JSON après réparations légères.")


def parse_annoter_segments_response(raw_text: str) -> Dict[str, Any]:
    """
    Transforme une réponse LLM en dict structuré pour un segment.
    Si tout échoue, renvoie EMPTY_SEGMENT.
    """
    if not raw_text or not raw_text.strip():
        return EMPTY_SEGMENT.copy()

    block = _extract_json_block(raw_text)
    if not block:
        return EMPTY_SEGMENT.copy()

    data = _try_json_loads(block)
    if not isinstance(data, dict):
        return EMPTY_SEGMENT.copy()

    # Normalisation/minimum de clés
    out = EMPTY_SEGMENT.copy()
    out["actions"]        = data.get("actions") or []
    out["problems"]       = data.get("problems") or []
    out["resume_segment"] = data.get("resume_segment") or ""
    out["themes"]         = data.get("themes") or []

    # Garde-fou : forcer les types attendus
    if not isinstance(out["actions"], list):
        out["actions"] = [str(out["actions"])]
    if not isinstance(out["problems"], list):
        out["problems"] = [str(out["problems"])]
    if not isinstance(out["themes"], list):
        out["themes"] = [str(out["themes"])]
    out["resume_segment"] = str(out["resume_segment"])

    return out


def extract_json_from_llm(raw_text: str) -> Any:
    """
    Version renforcée d'extraction JSON depuis une sortie LLM.
    Peut renvoyer dict ou list suivant le cas.
    """
    block = _extract_json_block(raw_text)
    return _try_parse_json_strict(block)


def normalize_segment_annotation(parsed: Any, raw_out: str = "") -> Dict[str, Any]:
    """
    Normalise la sortie pour la route /annoter_segments (Passe 1).
    - Si parsed est une liste, on prend le premier élément.
    - Si ce n'est pas un dict, on part d'un squelette vide.
    - On force la présence des 4 clés, avec les bons types.
    """
    # Si le modèle renvoie une liste de segments, on prend le premier
    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]

    if not isinstance(parsed, dict):
        parsed = {}

    out: Dict[str, Any] = {}

    # resume_segment : string
    val_res = parsed.get("resume_segment", "")
    if not isinstance(val_res, str):
        val_res = str(val_res) if val_res is not None else ""
    out["resume_segment"] = val_res.strip()

    # themes : liste
    val_themes = parsed.get("themes", [])
    if not isinstance(val_themes, list):
        val_themes = []
    out["themes"] = val_themes

    # actions : liste
    val_actions = parsed.get("actions", [])
    if not isinstance(val_actions, list):
        val_actions = []
    out["actions"] = val_actions

    # problems : liste
    val_problems = parsed.get("problems", [])
    if not isinstance(val_problems, list):
        val_problems = []
    out["problems"] = val_problems

    return out


def extract_json_texte_from_llm(raw_text: str) -> dict | None:
    t = _strip_chat_noise(raw_text)

    try:
        block = _extract_last_json_block(t)
        data = _try_parse_json_strict(block)
        if isinstance(data, dict) and "texte" in data:
            return data
    except Exception:
        pass

    try:
        data = extract_json_from_llm(t)
        if isinstance(data, dict) and "texte" in data:
            return data
    except Exception:
        pass

    # ✅ dernier recours robuste multi-JSON
    try:
        data = extract_json_texte(t)  # votre fonction
        if isinstance(data, dict) and "texte" in data:
            return data
    except Exception:
        pass

    return None


def extract_json_texte(s: str) -> dict | None:
    """
    Extrait le dernier objet JSON valide contenant la clé 'texte'
    depuis une sortie LLM bruitée.
    Compatible Python stdlib uniquement (pas de regex récursive).
    """
    if not s:
        return None

    # Nettoyage léger
    t = s.replace("<|end|>", "").replace("<|start|>", "").replace("<|assistant|>", "")
    t = t.replace("```json", "```").strip()

    last_valid = None
    i = 0
    n = len(t)

    while i < n:
        if t[i] != "{":
            i += 1
            continue

        start = i
        depth = 0
        in_str = False
        esc = False

        while i < n:
            c = t[i]

            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        chunk = t[start:i+1]
                        try:
                            d = json.loads(chunk)
                            if isinstance(d, dict) and "texte" in d:
                                last_valid = d
                        except Exception:
                            pass
                        break
            i += 1

        i += 1

    return last_valid


def _strip_chat_noise(s: str) -> str:
    if not s:
        return ""
    t = s
    for tok in CHAT_TOKENS:
        t = t.replace(tok, "")
    # enlever fences
    t = t.replace("```json", "```")
    return t.strip()

def _extract_last_json_block(text: str) -> str:
    if not text:
        raise ValueError("Réponse LLM vide.")
    t = text.strip()

    # wrapper <json>...</json>
    m = re.search(r"<json>(.+?)</json>", t, flags=re.S | re.I)
    if m:
        t = m.group(1).strip()

    # on prend le dernier '{' (ou '[') plausible
    starts = [m.start() for m in JSON_START_RE.finditer(t)]
    if not starts:
        raise ValueError("Aucun début de JSON trouvé dans la réponse.")
    start = starts[-1]

    end_brace = t.rfind("}")
    end_bracket = t.rfind("]")
    end = max(end_brace, end_bracket)
    if end <= start:
        raise ValueError("Bornes JSON incohérentes.")
    return t[start:end+1]

def _salvage_candidate_from_raw(cleaned: str) -> str | None:
    if not cleaned:
        return None

    # 1) retirer fences usuels sans toucher au contenu
    s = cleaned.replace("```json", "").replace("```", "").strip()

    # 2) s'il y a un objet JSON quelque part mais mal extrait, on peut tenter
    #    de récupérer un bloc entre { } (dernier bloc) via votre _extract_last_json_block
    #    mais ici on vise surtout le cas "texte brut sans JSON".
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return None

    # 3) conserver le texte tel quel (une ligne), sans reformulation
    candidate = " ".join(lines)
    candidate = " ".join(candidate.split())  # normalisation espaces uniquement
    return candidate

def _resolve_asr_out_dir(data: dict) -> tuple[str | None, str]:
    """
    Priorité :
    1) output_csv_dir explicite (dérogation client)
    2) project_config.paths.asr_transcriptions via project_id
    3) dossier parent de audio_path
    """
    override_dir = (data.get("output_csv_dir") or "").strip()
    if override_dir:
        return override_dir, "override:output_csv_dir"

    project_id = (data.get("project_id") or "").strip()
    if project_id:
        try:
            cfg = load_project_config(project_id)
            roots = cfg.get("roots", {}) or {}
            paths = cfg.get("paths", {}) or {}

            base = (
                roots.get("pcfixe")
                or roots.get("nas")
                or roots.get("laptop")
                or ""
            )
            rel = paths.get("asr_transcriptions") or r"AF_Expert_ASR\transcriptions"

            if base and rel:
                return str(Path(base) / rel), "project_config:asr_transcriptions"
        except Exception as e:
            app.logger.warning(
                "[ASR][OUT] résolution project_config impossible project_id=%s : %s",
                project_id, e
            )

    audio_path = (data.get("audio_path") or "").strip()
    if audio_path:
        return str(Path(audio_path).parent), "fallback:audio_parent"

    return None, "none"


def _resolve_asr_out_dir(data: dict) -> tuple[str | None, str]:
    """
    Priorité :
    1) output_csv_dir explicite (dérogation client)
    2) project_config.paths.asr_transcriptions via project_id
    3) dossier parent de audio_path
    """
    override_dir = (data.get("output_csv_dir") or "").strip()
    if override_dir:
        return override_dir, "override:output_csv_dir"

    project_id = (data.get("project_id") or "").strip()
    if project_id:
        try:
            cfg = load_project_config(project_id)
            roots = cfg.get("roots", {}) or {}
            paths = cfg.get("paths", {}) or {}

            base = (
                roots.get("pcfixe")
                or roots.get("nas")
                or roots.get("laptop")
                or ""
            )
            rel = paths.get("asr_transcriptions") or r"AF_Expert_ASR\transcriptions"

            if base and rel:
                return str(Path(base) / rel), "project_config:asr_transcriptions"
        except Exception as e:
            app.logger.warning(
                "[ASR][OUT] résolution project_config impossible project_id=%s : %s",
                project_id, e
            )

    audio_path = (data.get("audio_path") or "").strip()
    if audio_path:
        return str(Path(audio_path).parent), "fallback:audio_parent"

    return None, "none"



# =====================================================================
# Helpers internes
# =====================================================================

def _try_parse_json(txt: str):
    """Tentative simple de json.loads(txt).
    Retourne None si échec.
    """
    try:
        return json.loads(txt)
    except Exception:
        return None


def _repair_json_heuristics(txt: str) -> str:
    """Réparation légère inspirée de ai-json-fixer.
    - supprime les virgules finales avant } ou ]
    - remplace les quotes simples par doubles si le pattern est simple
    - supprime les backslashes inutiles
    """

    t = txt.strip()

    # 1) Supprimer virgules finales avant } ou ]
    t = re.sub(r",\s*([}\]])", r"\1", t)

    # 2) Remplacer guillemets simples → doubles (cas simple)
    # ⚠️ On n'applique que si le pattern ressemble à du JSON simple,
    #     pas s'il y a des apostrophes dans du texte libre
    if re.search(r"'\s*:", t):  # pattern d'objet JSON avec quotes simples
        t = re.sub(r"'", '"', t)

    # 3) Supprimer backslashes superflus
    t = t.replace("\\", "")

    # 4) Nettoyage caractères de contrôle
    t = t.replace("\x00", "")

    return t


# --- Auto-chunk constants & helpers ---



def _probe_audio_duration(path: str | Path) -> float | None:
    """Retourne la durée en secondes (float) ou None si échec."""
    try:
        info = sf.info(str(path))
        if info.samplerate and info.frames:
            return float(info.frames) / float(info.samplerate)
    except Exception as e:
        print(f"[WARN] _probe_audio_duration: {e}")
    return None


def _read_system_prompt_file(p: Path) -> str:
    txt = p.read_text(encoding="utf-8").strip()
    # si JSON: {"system": "..."}
    try:
        obj = json.loads(txt)
        if isinstance(obj, dict) and isinstance(obj.get("system"), str):
            return obj["system"].strip()
    except Exception:
        pass
    # sinon: fichier texte brut
    return txt

def get_system_prompt() -> str:
    """
    Ordre de recherche (premier trouvé, premier servi) :
      1) Variable d'env FLASK_SYSTEM_PROMPT (chemin fichier)
      2) SYSTEM_PROMPT_PATH issu de load_paths()
      3) Dossier config local du serveur (GRIDS_DIR/system_prompt.json)
      4) Fichier system_prompt.json à côté du script (…/flask_server/config/system_prompt.json)
      5) Chaîne par défaut intégrée (fallback)
    """
    candidates = []
    try:
        env_path = os.getenv("FLASK_SYSTEM_PROMPT")
        if env_path:
            candidates.append(Path(env_path))
    except Exception:
        pass

    try:
        if SYSTEM_PROMPT_PATH:
            candidates.append(Path(SYSTEM_PROMPT_PATH))
    except Exception:
        pass

    try:
        candidates.append((GRIDS_DIR / "system_prompt.json").resolve())
    except Exception:
        pass

    try:
        # config/ à côté de ce fichier
        candidates.append(Path(__file__).with_name("config").joinpath("system_prompt.json").resolve())
    except Exception:
        pass

    for p in candidates:
        try:
            if p and p.exists() and p.is_file():
                return _read_system_prompt_file(p)
        except Exception:
            continue


    # Fallback intégré si rien n'est trouvé
    return (
        "Tu es un assistant utile et concis. Réponds en français. "
        "Cite clairement tes hypothèses, évite d'inventer des faits."
    )


def generer_texte(
    prompt_final: str,
    model_name: str,
    system_prompt: str = "",
    generation_params: dict | None = None
) -> str:
    # switch model if needed
    model = model_name or LOADED_MODEL_NAME
    maybe_switch_model(model)

    # 1) paramètres effectifs (global -> per_model -> overrides)
    eff = effective_params(model, overrides=generation_params or {})

    gen = {
        "max_tokens": int(eff.get("max_tokens", 256)),
        "temperature": float(eff.get("temperature", 0.4)),
        "top_p": float(eff.get("top_p", 0.9)),
        "top_k": int(eff.get("top_k", 40)),
        "repeat_penalty": float(eff.get("repeat_penalty", 1.15)),
    }

    # 2) stop tokens : éviter [/INST] en dur (spécifique Llama-2)
    # gardez un stop neutre, ou laissez override via generation_params["stop"]
    stop = eff.get("stop", None)
    if stop is None:
        gen["stop"] = ["</s>"]
    else:
        gen["stop"] = stop

    # 3) si l’API chat existe, utiliser system/user proprement
    if hasattr(llm, "create_chat_completion"):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt_final})

        out = llm.create_chat_completion(
            messages=messages,
            temperature=gen["temperature"],
            top_p=gen["top_p"],
            max_tokens=gen["max_tokens"],
        )
        return (out.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()

    # 4) fallback texte brut (moins bon mais fonctionne)
    if system_prompt:
        prompt_final = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{prompt_final}\n\nASSISTANT:\n"

    with BACKEND_LOCK:
        out = llm(prompt_final, **gen)
    return (out.get("choices", [{}])[0].get("text") or "").strip()

def _safe_trim_to_ctx(text: str, max_new_tokens: int, model_name: str | None = None) -> str:
    model = model_name or LOADED_MODEL_NAME
    eff = effective_params(model, overrides={"max_tokens": max_new_tokens})

    n_ctx = int(eff.get("n_ctx", N_CTX))
    keep = max(DEFAULT_LOCAL_MARGE_TOKENS, n_ctx - int(max_new_tokens) - 64)

    toks = llm.tokenize(text.encode("utf-8", "ignore"))
    if len(toks) <= keep:
        return text
    toks = toks[-keep:]
    try:
        return llm.detokenize(toks).decode("utf-8", "ignore")
    except Exception:
        return text[-20000:]
    
def make_gen_kwargs(eff: dict) -> dict:
    """
    Construit les paramètres de génération à partir des paramètres effectifs.
    """
    return {
        "max_tokens": eff.get("max_tokens"),
        "temperature": eff.get("temperature"),
        "top_p": eff.get("top_p"),
        "top_k": eff.get("top_k"),
        "repeat_penalty": eff.get("repeat_penalty"),
        "stop": eff.get("stop"),  # ✅ essentiel
    }



def maybe_switch_model(model_name: str) -> bool:
    """Recharge le modèle si différent de LOADED_MODEL_NAME."""
    global llm, LOADED_MODEL_NAME
    model_name = (model_name or "").strip()
    if not model_name:
        return False

    if model_name == LOADED_MODEL_NAME:
        return False

    print(f"🔄 Changement de modèle : {LOADED_MODEL_NAME} → {model_name}")

    model_infos = models_index.get(model_name)
    if not model_infos:
        raise ValueError(f"Modèle '{model_name}' introuvable dans models_index.json")

    path_model = MODELS_PATH / model_infos["directory"] / model_infos["file"]
    if not path_model.exists():
        raise FileNotFoundError(f"Fichier modèle introuvable : {path_model}")

    try:
        del llm
    except Exception:
        pass

    llm = make_llama(path_model, model_name)
    LOADED_MODEL_NAME = model_name
    return True

def is_authorized(req) -> bool:
    raw = req.headers.get("x-api-key") or req.args.get("key") or ""
    key = raw.strip()

    # normalisation des clés connues
    keys_norm = [str(k or "").strip() for k in (API_KEYS or [])]

    ok = bool(key) and (key in keys_norm)

    if not ok:
        app.logger.warning(
            "AUTH FAIL path=%s has_x_api_key=%s raw_repr=%r raw_len=%d keys_lens=%s",
            req.path,
            ("x-api-key" in req.headers),
            raw,
            len(raw),
            [len(k) for k in keys_norm],
        )
    return ok


def _deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            _deep_update(d[k], v)
        else:
            d[k] = v
    return d

def _load_projects_index() -> list:
    return load_projets_index()


@lru_cache(maxsize=1)
def _load_create_affaire_callable():
    primary = (BASE_DIR / "flask_server" / "create_affaire.py").resolve()
    legacy = (BASE_DIR / "docs" / "app_reference" / "llm_assistant" / "sync" / "create_affaire.py").resolve()
    script_path = primary if primary.exists() else legacy
    app.logger.info("create_affaire.py chargé depuis : %s", script_path)
    script_path = (BASE_DIR / "docs" / "app_reference" / "llm_assistant" / "sync" / "create_affaire.py").resolve()
    spec = importlib.util.spec_from_file_location("gpt4all_create_affaire_bridge", script_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Impossible de charger create_affaire.py: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "create_affaire", None)
    if not callable(fn):
        raise RuntimeError(f"Fonction create_affaire introuvable dans {script_path}")
    return fn

def _find_project(ref: str, projects: list) -> dict | None:
    """ref = id (nouveau) ou ancien id_projet, puis 'nom' exact/startswith."""
    for p in projects:
        if p.get("id") == ref or p.get("id_projet") == ref:
            return p
    for p in projects:
        if p.get("nom") == ref:
            return p
    for p in projects:
        if str(p.get("nom", "")).startswith(ref):
            return p
    return None

def _load_project_config_for_server(proj: dict) -> dict:
    """
    Priorité: 'chemin_config' (nouveau schéma). Retours un dict normalisé.
    """
    paths = []
    if proj.get("chemin_config"):
        paths.append(proj["chemin_config"])
    if proj.get("chemin_config_pcfixe"):  # tolérance ancien
        paths.append(proj["chemin_config_pcfixe"])
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return normalize_project_config(raw)
        except Exception:
            continue
    return {}

def _effective_subdirs(cfg: dict) -> dict:
    """Fusionne les sous-dossiers du projet_config avec les défauts."""
    out = DEFAULT_SUBDIRS.copy()
    for k in DEFAULT_SUBDIRS.keys():
        if cfg.get(k):
            out[k] = cfg[k]
    return out

def _project_area_dir_from_index(project_id: str, area_key: str, subdir: str | None = None) -> Path:
    projects = _load_projects_index()
    proj = _find_project(project_id, projects)
    if not proj:
        raise ValueError(f"Projet introuvable: {project_id}")

    cfg = _load_project_config_for_server(proj) or {}
    subs = _effective_subdirs(cfg)

    area_map = {
        "rag_pc":  subs.get("rag_pc_subdir",  "RAG_PC"),
        "rag_vec": subs.get("rag_vec_subdir","RAG_Vectoriel"),
        "ocr_out": subs.get("ocr_out_subdir","OCR_Out"),
        # ⚠️ IMPORTANT : mettre "asr_in" si vous voulez ce nom exact
        "asr_in":  subs.get("asr_in_subdir", "asr_in"),
        "asr_out": subs.get("asr_out_subdir","asr_out"),
    }
    if area_key not in area_map:
        raise ValueError(f"area invalide: {area_key}")

    # ✅ CAS SPÉCIAL : ASR (dictées micro) sous C:\Affaires\<...>\<asr_in|asr_out>
    if area_key in ("asr_in", "asr_out") and subdir:
        base = _safe_join_under(AFFAIRES_ROOT, subdir)  # subdir = "2025-J37\AF_Expert_ASR\transcriptions\accedit-2025-09-02"
        target = (base / area_map[area_key]).resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target

    # 🔁 COMPORTEMENT EXISTANT (inchangé) pour rag/ocr
    root_pc = proj.get("rag_dossier_pcfixe")
    if not root_pc:
        raise ValueError("rag_dossier_pcfixe manquant dans projets_index.json")

    target = Path(root_pc) / area_map[area_key]
    if subdir:
        target = target / Path(subdir).name
    target.mkdir(parents=True, exist_ok=True)
    return target


def _safe_join_under(root: Path, rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        raise ValueError("subdir absolu interdit")
    full = (root / p).resolve()
    full.relative_to(root)  # lève ValueError si traversal
    return full



def _effective_paths_from_config(cfg: dict) -> dict:
    """
    Retourne les chemins effectifs côté PC fixe pour OCR/RAG/ASR,
    en appliquant des valeurs par défaut si ocr_output_pcfixe / csv_output_pcfixe sont vides.
    """
    root_pc = cfg.get("rag_dossier_pcfixe", "")
    subs = {
        "rag_pc":  cfg.get("rag_pc_subdir", "RAG_PC"),
        "rag_vec": cfg.get("rag_vec_subdir", "RAG_Vectoriel"),
        "ocr_out": cfg.get("ocr_out_subdir", "OCR_Out"),
        "asr_in":  cfg.get("asr_in_subdir", "ASR_In"),
        "asr_out": cfg.get("asr_out_subdir", "ASR_Out"),
    }
    def pj(*parts): 
        return os.path.join(*parts).replace("/", "\\")
    # défauts si vides
    ocr_output = cfg.get("ocr_output_pcfixe") or pj(root_pc, subs["ocr_out"])
    csv_output = cfg.get("csv_output_pcfixe") or pj(root_pc, subs["rag_vec"])
    # chemins dérivés utiles
    return {
        "root_pcfixe": root_pc,
        "rag_pc_dir":  pj(root_pc, subs["rag_pc"]),
        "rag_vec_dir": pj(root_pc, subs["rag_vec"]),
        "ocr_out_dir": ocr_output,
        "asr_in_dir":  pj(root_pc, subs["asr_in"]),
        "asr_out_dir": pj(root_pc, subs["asr_out"]),
        "csv_out_dir": csv_output,
        "subs": subs,
    }

def _normalize_prompts_structures(cfg: dict) -> dict:
    # Tolère "prompts_structurés" (accent) et crée l’alias ASCII "prompts_structures"
    if "prompts_structures" not in cfg and "prompts_structurés" in cfg:
        cfg["prompts_structures"] = cfg.get("prompts_structurés") or []
    # Toujours garantir une liste
    if not isinstance(cfg.get("prompts_structures", []), list):
        cfg["prompts_structures"] = []
    return cfg

def _resolve_project_root_from_payload(payload: dict) -> str | None:
    """
    1) Si 'rag' (rag_dossier_pcfixe) est fourni dans payload → prioritaire.
    2) Sinon, si 'project_id' est fourni, on résout via projets_index.json + projet_config.json.
    3) Sinon None (on ne logge pas sur disque projet).
    """
    # 1) RAG dossier direct
    rag = payload.get("rag") or payload.get("rag_dossier_pcfixe")
    if rag and Path(rag).exists():
        # racine projet = rag_dossier_pcfixe
        # vos routes annoter_rag passent déjà 'rag': dossier. :contentReference[oaicite:1]{index=1}
        return str(Path(rag).resolve().parent) if (Path(rag).name.upper() == "RAG_PC") else str(Path(rag).resolve())

    # 2) Depuis project_id -> projets_index.json -> projet_config
    proj_id = payload.get("project_id")
    if proj_id:
        projects = _load_projects_index()
        proj = _find_project(proj_id, projects)
        if proj:
            root_pc = proj.get("rag_dossier_pcfixe")
            if root_pc:
                return root_pc
    return None



def build_full_prompt(prompt: str, context: str | None = None, max_new_tokens: int | None = None) -> str:
    prompt = (prompt or "").strip()

    if context:
        # borne dure en chars (avant trim tokens)
        if len(context) > 15000:
            context = context[-15000:]

        full_prompt = (
            "[CONTEXTE]\n"
            f"{context}\n\n"
            "[TACHE]\n"
            f"{prompt}\n\n"
            "[CONSIGNES]\n"
            "- Utilise prioritairement les informations du CONTEXTE.\n"
            "- Si le CONTEXTE ne permet pas de répondre, indique-le explicitement et pose les questions nécessaires.\n"
            "- Ne fabrique pas de sources ni de faits.\n"
        )
    else:
        full_prompt = prompt

    # budget tokens pour le trim
    if max_new_tokens is None:
        max_new_tokens = int(PARAMS.get("max_tokens", DEFAULT_LOCAL_MIN_PROMPT_TOKENS))

    full_prompt = _safe_trim_to_ctx(full_prompt, int(max_new_tokens))

    try:
        token_count = len(llm.tokenize(full_prompt.encode("utf-8", "ignore")))
    except Exception:
        token_count = -1

    app.logger.debug("build_full_prompt: tokens=%d (max_new=%d, n_ctx=%s)",
                     token_count, int(max_new_tokens), PARAMS.get("n_ctx"))
    return full_prompt


def _normalize_domains(v):
    if not v:
        return []
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",")]
    return [d.strip().lower() for d in v if d and isinstance(d, str)]


def _host_allowed(host: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    host = (host or "").lower()
    for dom in allowed:
        dom = dom.lower()
        if host == dom or host.endswith("." + dom):
            return True
    return False

def _looks_like_url(s: str) -> bool:
    try:
        u = urlparse(s)
        return bool(u.scheme and u.netloc)
    except Exception:
        return False

def _apply_post_filters(pages, allowed_domains, disallow_patterns):

    pats = []
    for pat in (disallow_patterns or []):
        try:
            pats.append(re.compile(str(pat), re.I))
        except re.error:
            pass

    out = []
    for p in (pages or []):
        u = (p.get("url") or "").strip()
        host = (urlparse(u).hostname or "").lower()
        if allowed_domains:
            ok = any(host == d or host.endswith("." + d) for d in allowed_domains)
            if not ok:
                continue
        if pats and any(pt.search(u) for pt in pats):
            continue
        out.append(p)
    return out

def _qa_logs_dir(root_pcfixe: str, rag_pc_subdir: str = "RAG_PC") -> Path:
    base = Path(root_pcfixe) / rag_pc_subdir / "_QALogs"
    base.mkdir(parents=True, exist_ok=True)
    return base

def _save_web_context_to_rag_pc(
    project_id: str,
    query_or_url: str,
    web_context: str,
    pages: list[dict],
    sources: list[dict],
) -> dict:
    if not project_id:
        raise ValueError("project_id requis pour save_to_rag_pc")
    if not (web_context or "").strip():
        raise ValueError("Aucun contexte web exploitable a sauvegarder")

    cfg = load_project_config(project_id)
    rm = load_remote_map(project_id)
    root_pc = get_root_for_context(cfg, rm, context="pcfixe")
    if not root_pc:
        raise ValueError(f"Racine pcfixe introuvable pour le projet: {project_id}")
    subs = _effective_subdirs(cfg)
    target_dir = Path(root_pc) / subs.get("rag_pc_subdir", "RAG_PC") / "sources_web"
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    seed = (query_or_url or "web_context").strip() or "web_context"
    parsed = urlparse(seed if _looks_like_url(seed) else "")
    label = parsed.netloc or seed[:80]
    label = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("._") or "web_context"
    digest = hashlib.sha1((query_or_url or web_context[:500]).encode("utf-8", "ignore")).hexdigest()[:8]
    stem = f"web_{stamp}_{label[:48]}_{digest}"

    text_path = (target_dir / f"{stem}.txt").resolve()
    meta_path = (target_dir / f"{stem}.json").resolve()

    text_path.write_text(web_context, encoding="utf-8")
    meta_path.write_text(json.dumps({
        "saved_at": stamp,
        "project_id": project_id,
        "location": r"RAG_PC\\sources_web",
        "query_or_url": query_or_url,
        "pages_count": len(pages or []),
        "sources_count": len(sources or []),
        "sources": sources or [],
        "pages": [
            {
                "url": p.get("url"),
                "title": p.get("title") or p.get("og_title"),
                "txt_path": p.get("txt_path"),
                "md_path": p.get("md_path"),
            }
            for p in (pages or [])
        ],
        "context_text_path": str(text_path),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "saved": True,
        "location": r"RAG_PC\\sources_web",
        "dir": str(target_dir),
        "path": str(text_path),
        "meta_path": str(meta_path),
    }

def log_appel(payload: dict):
    """
    Journalise une requête LLM (prompt + réponse + méta) dans RAG_PC/_QALogs (par jour).
    payload attendu: keys habituelles déjà présentes dans vos routes:
      - route, prompt, reponse, model, gen, rag (optionnel), collection (optionnel), sources (optionnel), project_id (optionnel)
    """
    try:
        root = _resolve_project_root_from_payload(payload)
        if not root:
            return  # on ne force pas si on ne sait pas où logguer

        # déterminer sous-dossiers effectifs depuis projet_config (si accessible) pour connaître RAG_PC
        cfg = _load_project_config_for_server(_find_project(payload.get("project_id",""), _load_projects_index()) or {}) if payload.get("project_id") else {}
        subs = _effective_subdirs(cfg) if cfg else DEFAULT_SUBDIRS  # RAG_PC par défaut si cfg inaccessible
        rag_pc_name = subs.get("rag_pc_subdir", "RAG_PC")

        logs_dir = _qa_logs_dir(root, rag_pc_subdir=rag_pc_name)
        now = time.time()
        t = time.localtime(now)
        monthly = logs_dir / f"{t.tm_year:04d}-{t.tm_mon:02d}"
        monthly.mkdir(exist_ok=True)
        path = monthly / f"qa_{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}.jsonl"

        record = dict(payload)
        record["ts"] = int(now)
        # minimisation RGPD : tronquer contextes volumineux si besoin
        for k in ("rag_context", "web_context"):
            if k in record and isinstance(record[k], str) and len(record[k]) > 6000:
                record[k] = record[k][:6000] + "…"

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[WARN] log_appel: {e}")

def _sanitize_for_encoding(txt: str, encoding: str) -> str:
    try:
        return txt.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except Exception:
        return txt  # fallback

def pseudonymize_chunks(chunks: List[Dict], reg: Dict[str,str], key: bytes) -> List[Dict]:
    out = []
    for c in chunks or []:
        t = c.get("text") or ""
        c2 = dict(c)
        c2["text"] = pseudonymize_text(t, reg, key)
        out.append(c2)
    return out

def export_alias_table(reg: Dict[str,str], out_csv: Path) -> None:
    rows = [{"name": k, "alias": v} for k, v in sorted(reg.items())]
    import csv
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "alias"], delimiter=';')
        w.writeheader()
        w.writerows(rows)

def preload_aliases_from_vocab(vocab: list[str], reg: Dict[str,str], key: bytes) -> None:
    for term in vocab or []:
        term = " ".join(term.split()).strip()
        if len(term.split()) >= 2:
            # ensure_alias(term, reg, key)  # <- INDEFINI
            reg.setdefault(term, term)       # <- fallback simple



def _load_summary_config(json_path: str | Path) -> dict:
    """
    Lit voxtral_report_prompts.json et renvoie un dict de config.
    Clés supportées (toutes optionnelles):
      - system:       prompt system
      - user:         prompt user; on y remplace {text}
      - temperature:  float (ex: 0.7)
      - top_p:        float (ex: 0.9)
      - max_new_tokens: int (ex: 320)
      - chunk_chars:  int (ex: 3500)
    """
    cfg = {}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
    except Exception:
        pass
    # défauts sûrs
    cfg.setdefault("system", "Résume en français, concis, sous forme de puces.")
    cfg.setdefault("user", "Texte à résumer :\n{text}\n\nRéponse :")
    cfg.setdefault("temperature", 0.7)
    cfg.setdefault("top_p", 0.9)
    cfg.setdefault("max_new_tokens", 320)
    cfg.setdefault("chunk_chars", 3500)
    return cfg

def summarize_with_voxtral(
    text: str, 
    asr_pipeline: dict, 
    cfg: dict,
    names_hint: list[str] | None = None
) -> str:
    """
    Utilise le MÊME modèle Voxtral pour résumer du texte long sans OOM :
    - on découpe en chunks, 
    - on appelle voxtral_chat(...) pour chaque chunk,
    - on concatène.
    """
    text = (text or "").strip()
    if not text:
        return ""

    chunk_len = int(cfg.get("chunk_chars", 3500))
    sys_prompt = cfg.get("system", "")
    usr_tpl    = cfg.get("user", "Texte : {text}")
    temperature = float(cfg.get("temperature", 0.7))
    top_p       = float(cfg.get("top_p", 0.9))
    max_new     = int(cfg.get("max_new_tokens", 320))

    # Découpe "safe"
    chunks = [text[i:i+chunk_len] for i in range(0, len(text), chunk_len)]
    bullets = []

    for ch in chunks:
        # ⚠️ évite 2 messages "system" — fusionne le préambule avec le système
        if names_hint:
            prelude = "Noms propres à conserver : " + ", ".join(names_hint[:100])
            sys_msg = f"{prelude}\n\n{sys_prompt}" if sys_prompt else prelude
        else:
            sys_msg = sys_prompt

        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user",   "content": usr_tpl.replace("{text}", ch)}
        ]

        out = voxtral_chat(messages=messages, asr_pipeline=asr_pipeline, max_new_tokens=max_new)
        if out:
            bullets.append(out.strip())

    return "\n".join(bullets).strip()

def _asr_voxtral_auto_pipeline(
    *,
    audio_path: str,
    model_key: str,
    asr: dict,
    diar_options: dict | None,
    export_raw_csv: bool,
    export_photo_csv: bool,
    export_srt: bool,
    export_vtt: bool,
    out_dir: str,
    excel_encoding: str,
    csv_sep: str,
    lang: str | None,
    timestamps: bool,
    chunk_len_s: int,
    stride_s: int | None,
    temperature: float,
    top_p: float | None,
    max_new_tokens: int,
    batch_size: int,
) -> dict:
    """
    Découpe l'audio en tranches temporelles (chunk_len_s, chevauchement stride_s),
    appelle la diarisation sur chaque tranche, puis recolle, recale les timecodes et exporte.
    NOTE: les labels de locuteur sont suffixés par _c{idx} (pas de re-ID globale ici).
    """
    MAX_CHUNK_WALLTIME_S = int(os.getenv("MAX_CHUNK_WALLTIME_S", "21600"))  # 60 min/tranche
    
    stride_s = stride_s or AUTO_CHUNK_STRIDE_SEC
    dur = _probe_audio_duration(audio_path) or 0.0
    if dur <= 0:
        raise ValueError("Durée audio inconnue/0")

    # Préparer sorties
    outp = Path(out_dir); outp.mkdir(parents=True, exist_ok=True)
    wav_path = Path(audio_path)
    stem_tag = f"{_safe_stem(wav_path)}{_ext_tag(wav_path)}"

    # Découpe temporelle (avec chevauchement)
    starts = []
    pos = 0.0
    step = max(1, int(chunk_len_s - stride_s))
    while pos < dur:
        starts.append(int(pos))
        pos += step
    # Forcer dernier end à dur
    # (on recalcule end à chaque itération)

    merged_chunks = []
    texts = []

    tmp_root = Path(out_dir) / f"__tmp_{uuid.uuid4().hex[:8]}"
    tmp_root.mkdir(parents=True, exist_ok=True)

    progress_path = Path(out_dir) / f"{stem_tag}__progress.json"

    try:
        # Lire info audio
        info = sf.info(str(audio_path))
        sr = int(info.samplerate)
        total_frames = int(info.frames)

        resume_from = 1
        if progress_path.exists():
            try:
                prev = json.loads(progress_path.read_text(encoding="utf-8"))
                resume_from = int(prev.get("parts_done", 0)) + 1
            except Exception:
                resume_from = 1
        
        
        # Si toutes les tranches ont déjà été traitées,
        # éviter une exécution "vide"
        if resume_from > len(starts):
            app.logger.info(
                f"[AUTO] Toutes les tranches deja traitees "
                f"(resume_from={resume_from}, total={len(starts)}). "
                f"Reinitialisation du progress."
            )
            try:
                progress_path.unlink()
            except Exception:
                pass
            resume_from = 1

        last_i = 0
        last_start_sec = 0
        last_end_sec = 0.0

        for i, start_sec in enumerate(starts, 1):
            if i < resume_from:
                continue
        
        
            end_sec = min(dur, start_sec + chunk_len_s)
            if end_sec <= start_sec:
                continue

            # Charger la fenêtre de frames
            start_frame = int(start_sec * sr)
            end_frame = int(end_sec * sr)
            end_frame = min(end_frame, total_frames)

            # Lecture partielle
            data, _ = sf.read(str(audio_path), start=start_frame, stop=end_frame, dtype="float32", always_2d=False)
            # Force mono si nécessaire (pyannote/ASR s'en fichent en général, mais on reste safe)
         
            if isinstance(data, np.ndarray) and data.ndim == 2:
                data = data.mean(axis=1)
            if isinstance(data, np.ndarray):
                data = np.nan_to_num(data)  
            # Écrire wav temporaire
            part_wav = tmp_root / f"{wav_path.stem}__part{i:03d}.wav"
            sf.write(str(part_wav), data, sr)

            t_chunk0 = time.time()
            app.logger.info(f"[AUTO] part {i}/{len(starts)} window={start_sec}-{end_sec}s")

            kwargs = {}
            try:
                import inspect
                if "batch_size" in inspect.signature(transcribe_with_diarization).parameters:
                    kwargs["batch_size"] = batch_size
            except Exception:
                pass


            # Appel diarisation/ASR sur la tranche
            res_i = transcribe_with_diarization(
                audio_path=str(part_wav),
                model_key=model_key,
                asr_pipeline=asr,
                language=lang,
                hf_token=os.getenv("HF_TOKEN"),
                diar_options=diar_options or {},
                output_csv_dir=None,  # on exporte après fusion

                chunk=chunk_len_s,
                stride=stride_s,         

                timestamps=timestamps,

                # options diarisation
                max_speakers=(diar_options or {}).get("max_speakers"),
                min_speaker_duration=(diar_options or {}).get("min_speaker_duration"),
                min_duration_off=(diar_options or {}).get("min_duration_off"),
                collar=float((diar_options or {}).get("collar", 0.05)),
                allow_overlap=bool((diar_options or {}).get("allow_overlap", False)),

                # paramètres génération
                temperature=temperature,
                top_p=top_p,
                max_new_tokens=max_new_tokens, 

                **kwargs,
            )

            dt_chunk = time.time() - t_chunk0
            app.logger.info(f"[AUTO] part {i}/{len(starts)} {start_sec}-{end_sec}s terminé en {dt_chunk:.1f}s")

            if dt_chunk > MAX_CHUNK_WALLTIME_S:
                raise RuntimeError(f"Timeout tranche {i}: {dt_chunk:.1f}s > {MAX_CHUNK_WALLTIME_S}s")
            last_i = i
            last_start_sec = start_sec
            last_end_sec = float(end_sec)

            progress = {
                "audio_path": audio_path,
                "chunk_len_s": chunk_len_s,
                "stride_s": stride_s,
                "total_dur_s": float(dur),
                "parts_done": last_i,
                "parts_total": len(starts),
                "last_start_sec": int(last_start_sec),
                "last_end_sec": float(last_end_sec),
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")

            # Recalage temps + suffix locuteurs
            for ch in (res_i.get("chunks") or []):

                start = float(ch.get("start", 0.0))
                end   = float(ch.get("end", 0.0))

                # supprimer les segments du chevauchement
                if i > 1 and start < stride_s:
                    continue

                merged_chunks.append({
                    "start": start + start_sec,
                    "end": end + start_sec,
                    "speaker": f"{ch.get('speaker','Speaker')}_c{i}",
                    "text": ch.get("text","")
                })


            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

        # Tri final par start time
        merged_chunks.sort(key=lambda c: float(c.get("start", 0.0)))

        # Nettoyage segments (glitches / doublons)
        merged_chunks = clean_asr_segments(merged_chunks)

        # --- Exports fusionnés ---
        results = {
            "segments": len(merged_chunks),
        }


        # SRT/VTT
        if export_srt and merged_chunks:
            srt_text = to_srt(merged_chunks)
            srt_path = outp / f"{stem_tag}.srt"
            srt_path.write_text(srt_text, encoding="utf-8")
            results["srt_path"] = str(srt_path)

        if export_vtt and merged_chunks:
            vtt_text = to_vtt(merged_chunks)
            vtt_path = outp / f"{stem_tag}.vtt"
            vtt_path.write_text(vtt_text, encoding="utf-8")
            results["vtt_path"] = str(vtt_path)

        # CSV brut
        if export_raw_csv and merged_chunks:
            raw_csv = outp / f"{stem_tag}.csv"
            if raw_csv.exists():
                try: raw_csv.unlink()
                except Exception: pass
            with _open_csv_for_excel(raw_csv, encoding=excel_encoding) as (f, used_raw_csv):
                w = csv.writer(f, delimiter=csv_sep, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
                w.writerow(["start","end","speaker","text"])
                for ch in merged_chunks:
                    txt = (ch.get("text") or "").replace("\r"," ").replace("\n"," ").strip()
                    if excel_encoding == "cp1252":
                        txt = _sanitize_for_cp1252(txt)
                    else:
                        txt = _sanitize_for_encoding(txt, excel_encoding)
                    w.writerow([ch.get("start",""), ch.get("end",""), (ch.get("speaker") or "Speaker"), txt])
            results["csv_path"] = str(used_raw_csv)

        # CSV photo
        if export_photo_csv and merged_chunks:
            photo_csv = outp / f"{stem_tag}(photo).csv"
            if photo_csv.exists():
                try: photo_csv.unlink()
                except Exception: pass
            base_dt = _file_creation_datetime(wav_path)
            with _open_csv_for_excel(photo_csv, encoding=excel_encoding) as (f, used_photo_csv):
                w = csv.writer(f, delimiter=csv_sep, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
                w.writerow(["horodatage","locuteur","texte"])
                for ch in merged_chunks:
                    start_s = float(ch.get("start") or 0.0)
                    speaker = ch.get("speaker") or "SPEAKER"
                    text = (ch.get("text") or "").replace("\r"," ").replace("\n"," ").strip()
                    if excel_encoding == "cp1252":
                        text = _sanitize_for_cp1252(text)
                    else:
                        text = _sanitize_for_encoding(text, excel_encoding)
                    ts_dt = base_dt + dt.timedelta(seconds=start_s)
                    ts_cell = ts_dt.strftime("%d/%m/%Y %H:%M:%S")
                    w.writerow([ts_cell, speaker, text])
            results["photo_csv_path"] = str(used_photo_csv)

        if last_i > 0:
            progress["done"] = True
            progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")

        # Texte fusionné 
        results["text"] = "\n".join(
            (ch.get("text") or "").strip()
            for ch in merged_chunks
            if (ch.get("text") or "").strip()
        ).strip()

        results["chunks"] = merged_chunks

        return results

    finally:
        # Nettoyage des wavs temporaires
        try:          
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass

def _resolve_sd_outdir(project_id: str | None,
                       explicit_outdir: str | None,
                       global_mode: bool | None,
                       area: str | None = None) -> Path:
    """
    - Si 'explicit_outdir' est fourni → priorité absolue.
    - Sinon, si 'project_id' et pas global_mode → mode AFFAIRE (arbo dossiers affaire).
    - Sinon → mode GLOBAL (OpenWebUI/AppFlowy), range sous RAG_BASE/SD_Images.
    - 'area' est à dispo si tu veux ventiler plus finement (non obligatoire ici).
    """
    if explicit_outdir:
        return Path(explicit_outdir).resolve()

    pid = (project_id or "").strip()
    if pid and not global_mode:
        # --- Mode AFFAIRE
        # Ex: D:\Affaires\<projet>\AD_Expert_Traitements\_SD_Images
        base = Path(AFFAIRES_ROOT) / pid / AFFAIRE_SD_SUBDIR
        return base.resolve()

    # --- Mode GLOBAL
    # Ex: C:\Dossier_RAG\SD_Images
    return (Path(RAG_BASE) / "SD_Images").resolve()

def _copy_comfy_output_to(outdir: Path, images: list[dict]) -> list[str]:
    saved = []
    for img in images or []:
        fn = (img.get("filename") or "").strip()
        sub = (img.get("subfolder") or "").strip()
        if not fn:
            continue
        src = (COMFY_OUTPUT / sub / fn).resolve()
        if src.exists():
            dst = (outdir / fn).resolve()
            try:
                shutil.copy2(src, dst)
                saved.append(str(dst))
            except Exception:
                continue
    return saved

def _norm_url_for_dedupe(u: str) -> str:
    if not u:
        return ""
    try:
        p = urlparse(u.strip())
        scheme = "https" if p.scheme in ("http", "https") else p.scheme
        netloc = p.netloc.lower().rstrip(":80").rstrip(":443")
        path = p.path.rstrip("/")
        return urlunparse((scheme, netloc, path, "", "", ""))
    except Exception:
        return (u or "").strip()

def _take_top_k(pages, k=8):
    # pages items may have .score or .rank
    def _score(p, i):
        s = p.get("score")
        if s is None:
            s = p.get("rank")
        return float(s) if s is not None else 1.0 / (i + 1)
    scored = [(i, _score(p, i)) for i, p in enumerate(pages or []) if p.get("url")]
    scored.sort(key=lambda t: t[1], reverse=True)
    return [pages[i] for i, _ in scored[:k]]



def _is_garbage_text(txt: str) -> bool:
    """Filtre les textes manifestement erronés ou inutilisables."""
    if not txt:
        return True

    t = txt.strip()

    # très longues répétitions du même caractère
    if re.search(r'(.)\1{10,}', t):
        return True

    words = t.split()
    if not words:
        return True

    # séquence ultra-répétitive de quelques mots (« de de de… », « no no no… »)
    uniq = set(words)
    if len(words) > 30 and len(uniq) <= 4:
        return True

    # lignes ne contenant presque que des interjections / onomatopées
    if re.fullmatch(r"(ha|ah|eh|oh|heu|euh|no|non|oui)[\s,;.!?]*" +
                    r"( (ha|ah|eh|oh|heu|euh|no|non|oui)[\s,;.!?]*){5,}",
                    t.lower()):
        return True

    return False



def _is_probably_asr_csv(df: pd.DataFrame) -> bool:
    """
    Heuristique : CSV de diarisation ASR si au moins 4 colonnes
    et si les 2 premières sont numériques (start/end).
    """
    if df.shape[1] < 4:
        return False
    try:
        float(str(df.iloc[0, 0]).replace(",", "."))
        float(str(df.iloc[0, 1]).replace(",", "."))
    except Exception:
        return False
    return True


def _clean_asr_diar_csv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Nettoyage des CSV de diarisation :
    - supprime les lignes “glitch” (dé / no / ah répétés, textes monstrueusement longs)
    - supprime les doublons stricts
    - supprime les doublons quasi identiques brouillon / version corrigée
    """

    cols = list(df.columns)
    if len(cols) < 4:
        return df

    df = df.rename(columns={
        cols[0]: "start",
        cols[1]: "end",
        cols[2]: "speaker",
        cols[3]: "text",
    })

    df["start"] = pd.to_numeric(df["start"], errors="coerce")
    df["end"]   = pd.to_numeric(df["end"], errors="coerce")
    df["text"]  = df["text"].astype(str)

    df = df.dropna(subset=["start", "end"]).copy()
    df = df.sort_values(["start", "end"]).reset_index(drop=True)

    # 1) glitches
    def is_glitch(txt: str) -> bool:
        t = str(txt).strip()
        if len(t) > 2000:
            return True
        words = t.split()
        if len(words) > 30 and len(set(words)) <= 4:
            return True
        if re.search(r"(.)\1{10,}", t):
            return True
        return False

    df = df[~df["text"].map(is_glitch)].copy()

    # 2) doublons stricts
    df = df.drop_duplicates(subset=["start", "end", "speaker", "text"]).reset_index(drop=True)

    # 3) doublons “brouillon / version finale” consécutifs
    TIME_EPS = 0.05   # 50 ms sur le début
    END_EPS  = 0.20   # 200 ms sur la fin

    to_drop = []
    for i in range(len(df) - 1):
        r1 = df.iloc[i]
        r2 = df.iloc[i + 1]

        if r1["speaker"] != r2["speaker"]:
            continue
        if abs(r1["start"] - r2["start"]) > TIME_EPS:
            continue
        if not (r2["end"] >= r1["end"] or abs(r1["end"] - r2["end"]) < END_EPS):
            continue

        t1 = str(r1["text"]).strip()
        t2 = str(r2["text"]).strip()

        if t1 == t2 or t2.startswith(t1.rstrip(" .,…")):
            to_drop.append(df.index[i])

    if to_drop:
        df = df.drop(index=to_drop).reset_index(drop=True)

    # remettre les noms d’origine sur les 4 premières colonnes
    df = df.rename(columns={
        "start":   cols[0],
        "end":     cols[1],
        "speaker": cols[2],
        "text":    cols[3],
    })
    return df


def _merge_near_duplicates(segments, dt_sec=0.05):
    """
    Fusionne / nettoie les doublons très proches :
    - même locuteur
    - timestamps très proches
    - texte quasi identique (brouillon + version « rattrapée »).
    """
    cleaned = []
    for seg in segments:
        txt = (seg.get("text") or "").strip()
        if _is_garbage_text(txt):
            continue

        if cleaned:
            prev = cleaned[-1]
            # même speaker
            if seg.get("speaker") == prev.get("speaker"):
                # temps quasi identiques
                if (abs(seg["start"] - prev["start"]) <= dt_sec and
                    abs(seg["end"] - prev["end"]) <= 0.5):
                    prev_txt = (prev.get("text") or "").strip()

                    # si l’un est un préfixe de l’autre, on garde la version la plus longue
                    if (prev_txt and txt) and (
                        prev_txt.startswith(txt) or txt.startswith(prev_txt)
                    ):
                        prev["start"] = min(prev["start"], seg["start"])
                        prev["end"]   = max(prev["end"], seg["end"])
                        if len(txt) > len(prev_txt):
                            prev["text"] = txt
                        continue

        cleaned.append(seg)

    return cleaned




# --- Résumé "safe" : découpe + limite de tokens/texte, et no_sample pour VRAM ---

@lru_cache(maxsize=1)
def _load_voxtral_report_prompts(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)
    
def _format_ms(ms: float) -> str:
    # ms -> "[hh:mm:ss,mmm]"
    s, ms = divmod(int(round(ms)), 1000)
    h, s  = divmod(s, 3600)
    m, s  = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def _chunks_to_thematic_lines(chunks: list[dict]) -> str:
    # Le template dit : "Chaque ligne est au format: [hh:mm:ss,mmm] Locuteur: texte."
    # On reconstruit des lignes en respectant ce format.
    lines = []
    for c in chunks or []:
        start = float(c.get("start", 0.0))
        speaker = (c.get("speaker") or "Locuteur")
        text = (c.get("text") or "").strip()
        ts = _format_ms(start * 1000.0)
        if text:
            lines.append(f"[{ts}] {speaker}: {text}")
    return "\n".join(lines) 

def _build_voxtral_prompt_from_template(template: dict, transcript_lines: str) -> str:
    parts = []
    # Tout dans UN SEUL prompt (style « user »)
    if template.get("label"):
        parts.append(f"Titre du modèle: {template['label']}")
    if template.get("role"):
        parts.append(template["role"])
    if template.get("context"):
        parts.append(f"Contexte:\n{template['context']}")
    if template.get("task"):
        parts.append("Tâche:\n- " + "\n- ".join(template["task"]))
    if template.get("constraints"):
        parts.append("Contraintes:\n- " + "\n- ".join(template["constraints"]))
    if template.get("format"):
        parts.append("Format attendu:\n- " + "\n- ".join(template["format"]))
    if template.get("fewshot"):
        parts.append("Exemple:\n" + template["fewshot"])
    # On insère enfin la transcription
    parts.append("Transcription (à analyser):\n" + transcript_lines)
    return "\n\n".join(parts)

def summarize_text_safely_with_voxtral(
    *,
    res_text: str,
    res_chunks: list[dict],
    asr_pipeline: dict,
    prompts_json_path: str | None = None,
    template_key: str = "expert_compte_rendu_v1",
    names_hint: list[str] | None = None,
    chunk_chars: int = 6000,
    max_new_tokens: int = 700,
    temperature: float = 0.2,
    top_p: float | None = 0.9,
) -> str:
    # 0) Charger le template de manière robuste
    resolved = _resolve_report_prompts_path(prompts_json_path)
    templates = _load_voxtral_report_prompts_safe(resolved)
    if template_key not in templates:
        # fallback intégré + clé par défaut garantie
        templates = _embedded_default_report_prompts()
        if template_key not in templates:
            template_key = "expert_compte_rendu_v1"
    template = templates[template_key]

    transcript_lines = _chunks_to_thematic_lines(res_chunks) or (res_text or "")
    parts = []
    if len(transcript_lines) <= chunk_chars:
        parts = [transcript_lines]
    else:
        start = 0
        while start < len(transcript_lines):
            end = min(len(transcript_lines), start + chunk_chars)
            nl = transcript_lines.rfind("\n", start, end)
            if nl > start + 0.5 * chunk_chars:
                end = nl + 1
            parts.append(transcript_lines[start:end])
            start = end

    interim = []
    for chunk_text in parts:
        single_prompt = _build_voxtral_prompt_from_template(template, chunk_text)
        if names_hint:
            prelude = "Noms propres à conserver : " + ", ".join(names_hint[:100])
            sys_msg = prelude
            messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": single_prompt}]
        else:
            messages = [{"role": "user", "content": single_prompt}]

        out = voxtral_chat(messages=messages, asr_pipeline=asr_pipeline, max_new_tokens=max_new_tokens)
        interim.append((out or "").strip())

    if len(interim) == 1:
        return interim[0]

    joined = "\n\n---\n\n".join(interim)
    final_prompt = _build_voxtral_prompt_from_template(template, joined)
    if names_hint:
        prelude = "Noms propres à conserver : " + ", ".join(names_hint[:100])
        final_messages = [{"role": "system", "content": prelude}, {"role": "user", "content": final_prompt}]
    else:
        final_messages = [{"role": "user", "content": final_prompt}]

    final_out = voxtral_chat(messages=final_messages, asr_pipeline=asr_pipeline, max_new_tokens=max_new_tokens)
    return (final_out or "").strip()

# helper commun



def _fmt_hhmmss(t: float) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    return f"{h}:{m:02d}:{s:02d}"


def _file_creation_datetime(path: Path) -> dt.datetime:
    st = path.stat()
    # 1) vrai "birth" si dispo (macOS/BSD, parfois Windows)
    birth = getattr(st, "st_birthtime", None)
    if birth:
        return dt.datetime.fromtimestamp(birth)
    # 2) Windows: st_ctime = creation time
    if sys.platform.startswith("win"):
        return dt.datetime.fromtimestamp(st.st_ctime)
    # 3) Linux: pas de birth → fallback à mtime (meilleur proxy)
    return dt.datetime.fromtimestamp(st.st_mtime)

def _load_summary_prompt(json_path: str | Path) -> str:
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            j = json.load(f)
        # adapte la clé selon ton fichier (exemples:)
        # return j.get("summary_prompt") or j.get("prompt") or j.get("summary_user") or ""
        return j.get("summary_prompt", "")
    except Exception:
        return ""


def _sanitize_for_cp1252(s: str) -> str:
    if not s:
        return s
    s = unicodedata.normalize("NFKC", s)
    repl = {
        "\u2011": "-",   # no-break hyphen
        "\u2013": "-",   # en dash
        "\u2014": "-",   # em dash
        "\u2212": "-",   # minus sign
        "\u00A0": " ",   # no-break space
        "\u2026": "...", # ellipsis
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    try:
        # on force la mappabilité CP-1252 : remplace les non-mappables par '?'
        return s.encode("cp1252", "replace").decode("cp1252", "replace")
    except Exception:
        return s

@lru_cache(maxsize=1)
def _load_voxtral_report_prompts_safe(json_path: str | None) -> dict:
    try:
        if json_path:
            return _load_voxtral_report_prompts(json_path)
    except Exception as e:
        print(f"[WARN] _load_voxtral_report_prompts_safe: {e}")
    return _embedded_default_report_prompts()


@contextmanager
def _open_csv_for_excel(path: Path, *, encoding: str = "utf-8-sig"):
    """
    Ouvre path en écriture. Si le fichier est verrouillé (Excel ouvert),
    écrit dans un nouveau fichier suffixé par un timestamp.
    Retourne (file_handle, used_path).
    """
    p = Path(path)
    used = p
    try:
        f = p.open("w", encoding=encoding, newline="")
    except PermissionError:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        used = p.with_name(f"{p.stem}__{ts}{p.suffix}")
        print(f"[WARN] CSV verrouillé: {p.name} → écriture dans {used.name}")
        f = used.open("w", encoding=encoding, newline="")
    try:
        yield f, used
    finally:
        try:
            f.close()
        except Exception:
            pass


def _load_asr_csv_to_chunks(csv_path: str | Path) -> list[dict]:
    """
    Lit un CSV 'brut' produit par /asr_voxtral (colonnes: start;end;speaker;text)
    et renvoie une liste de dicts: {start, end, speaker, text}.

    Tente d'auto-détecter le séparateur (',' ou ';').
    """
    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"CSV introuvable: {csv_path}")

    sample = p.read_text(encoding="utf-8", errors="replace")[:2000]
    # détection basique du séparateur
    sep = ';' if sample.count(';') >= sample.count(',') else ','

    chunks = []
    with p.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f, delimiter=sep)
        # normaliser noms de colonnes
        cols = {k.strip().lower(): k for k in (r.fieldnames or [])}
        need = all(x in cols for x in ("start", "end", "speaker", "text"))
        if not need:
            raise ValueError(f"CSV inattendu (colonnes trouvées: {r.fieldnames}) ; attendu: start,end,speaker,text")
        for row in r:
            try:
                start = float(str(row[cols["start"]]).replace(",", "."))
            except Exception:
                start = 0.0
            try:
                end = float(str(row[cols["end"]]).replace(",", "."))
            except Exception:
                end = None
            chunks.append({
                "start": start,
                "end": end,
                "speaker": (row.get(cols["speaker"]) or "SPEAKER"),
                "text": (row.get(cols["text"]) or "").strip()
            })
    return chunks



def _sanitize_llm_output(txt: str, has_citations: bool = False) -> str:
    """
    Nettoyage minimal du texte renvoyé par le LLM.
    - supprime les blocs ```...``` et ```json
    - enlève quelques caractères parasites
    - normalise légèrement les espaces
    """
    if not txt:
        return ""

    t = str(txt).strip()

    # Retirer les fence code markdown en tête/fin
    if t.startswith("```"):
        # supprime le tag d’ouverture ```json / ```markdown etc.
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        # supprime le bloc de fermeture ```
        t = re.sub(r"\s*```$", "", t).strip()

    # Nettoyage de base
    t = t.replace("\x00", " ").replace("\ufeff", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)

    return t

def _safe_coll_name(s: str) -> str:
    # normalisation caractères autorisés
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    s = s.strip("._-")

    # garantir un nom minimal
    if len(s) < 3:
        s = f"mem_{s}"

    # troncature puis nettoyage final
    s = s[:512].strip("._-")

    # sécurité ultime
    if len(s) < 3:
        s = "mem_default"

    return s



def _norm(items, source):
    out = []
    for it in items or []:
        out.append({
            "title": it.get("title") or it.get("name") or it.get("url"),
            "url":   it.get("url")   or it.get("link"),
            "snippet": it.get("content") or it.get("snippet") or it.get("description"),
            "source": source
        })
    return out


# --- utils pdf ---

def _pdf_pages(path: str) -> int:
    with fitz.open(path) as doc:
        return doc.page_count

def _hash_file(path: str) -> str:
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1<<20), b""):
            h.update(chunk)
    return h.hexdigest()

def _sanitize_title(t: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in t).strip("-_")

def _build_piece_filename(numexp: str|None, idproj: str, code_partie: str,
                          numero_avocat_prefix: str, no: int, title: str, date_iso: str|None=None):
    # Ex: 2025-001-03-PIECE004-Devis-…-2024-05-14.pdf (numexp facultatif en tête si voulu)
    core = f"{idproj}-{code_partie}-{numero_avocat_prefix}{no:03d}-{_sanitize_title(title)}"
    if date_iso: core += f"-{date_iso}"
    if numexp:   core = f"{numexp}-{core}"
    return core + ".pdf"
#*************************************************

def _load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def repair_truncated_json(raw_text: str) -> str:
    """
    Essaie de "refermer" un JSON coupé :
    - complète </json> si la balise d'ouverture est présente,
    - complète les ']' ou '}' manquants en fin de texte.
    """
    if not raw_text:
        return raw_text

    txt = raw_text

    # Si on a <json> sans </json>, on ajoute la balise de fin
    if "<json>" in txt and "</json>" not in txt:
        txt = txt + "</json>"

    # On travaille sur le contenu potentiellement JSON
    try:
        candidate = _extract_json_block(txt)
    except Exception:
        # si même l'extraction échoue, on tente quand même sur le texte brut
        candidate = txt.strip()

    # Comptage simple des { } et [ ]
    open_brace  = candidate.count("{")
    close_brace = candidate.count("}")
    open_brack  = candidate.count("[")
    close_brack = candidate.count("]")

    # Ajout des '}' ou ']' manquants en fin de chaîne
    repaired = candidate + ("}" * max(0, open_brace - close_brace)) + ("]" * max(0, open_brack - close_brack))

    # Si on avait un wrapper <json>, on le remet autour
    if "<json>" in txt:
        repaired = f"<json>{repaired}</json>"

    return repaired


def _save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _join(root, rel):
    return os.path.normpath(os.path.join(root, rel)) if root and rel else None

def resolve_path(cfg: dict, remote_map: dict | None, rel_key: str, context: str = "pcfixe"):
    """
    Construit un chemin complet sécurisé.
    Empêche toute sortie de la racine (anti path traversal).
    """

    roots = (cfg.get("roots") or {})
    paths = (cfg.get("paths") or {})

    root = roots.get(context)
    if not root and remote_map:
        root = (remote_map.get("contexts") or {}).get(context, {}).get("root")

    if not root:
        raise ValueError(f"Racine introuvable pour contexte '{context}'")

    rel = paths.get(rel_key)
    if not rel and remote_map:
        rel = (remote_map.get("paths_rel") or {}).get(rel_key)

    if not rel:
        raise ValueError(f"Chemin relatif introuvable: {rel_key}")

    # Construction + normalisation
    abs_path = os.path.normpath(os.path.join(root, rel))
    root_norm = os.path.normpath(root)

    # 🔐 Sécurité : empêcher sortie de racine
    if not abs_path.startswith(root_norm):
        raise ValueError(f"Tentative de sortie de racine détectée: {rel_key}")

    return abs_path

def normalize_project_config(cfg: dict) -> dict:
    """
    Normalise un ancien project_config en nouveau schéma minimal.
    Vieux champs tolérés: rag_dossier_pcfixe/laptop, ocr_*_pcfixe, csv_output_pcfixe, etc.
    """
    cfg = dict(cfg or {})
    if "id" not in cfg and "id_projet" in cfg:
        cfg["id"] = cfg["id_projet"]

    # roots
    if not cfg.get("roots"):
        # heuristiques à partir des anciens champs si dispos
        aff_id = (cfg.get("id") or "AFFAIRE").replace(" ", "")
        # par défaut, tout sur C:\Affaires\{id}\ (sera OK si EZ-Sync/NAS monté ainsi)
        base = rf"C:\Affaires\{aff_id}\\"
        cfg["roots"] = {
            "pcfixe": cfg.get("rag_dossier_pcfixe") or base,
            "laptop": cfg.get("rag_dossier_laptop") or base,
            "nas":    base  # peut être remplacé par UNC réel dans _remote.map.json
        }

    # paths (structure relative de l’affaire)
    # paths (structure relative de l’affaire) — compat v3
    paths = cfg.get("paths") or {}

    # AA
    paths.setdefault("depot_initial",   r"AA_Expert_Admin\Depot_initial")
    paths.setdefault("paperless_inbox", r"AA_Expert_Admin\_Paperless_Inbox")
    paths.setdefault("logs",            r"AA_Expert_Admin\_Logs")

    # AD
    paths.setdefault("queue_ocr",  r"AD_Expert_Traitements\_Queue_OCR")
    paths.setdefault("ocr_text",   r"AD_Expert_Traitements\_OCR_Texte")
    paths.setdefault("splits",     r"AD_Expert_Traitements\_Splits")
    paths.setdefault("csv_rag",    r"AD_Expert_Traitements\_CSV_RAG")
    paths.setdefault("manifests",  r"AD_Expert_Traitements\_Manifests")

    # AF
    paths.setdefault("asr_transcriptions", r"AF_Expert_ASR\transcriptions")

    # Structure
    paths.setdefault("pieces_expert", r"BA_Pieces_de_expert")
    paths.setdefault("exports",       r"BD_Exports")
    paths.setdefault("cloture",       r"CZ_Cloture")

    # Système
    paths.setdefault("sqlite",        r"_DB\project.sqlite")

    cfg["paths"] = paths

    return cfg

def get_root_for_context(cfg: dict, remote_map: dict | None, context: str = "pcfixe") -> str:
    # 1) Priorité au remote_map (UNC/NAS réel)
    if remote_map:
        root = (remote_map.get("contexts") or {}).get(context, {}).get("root")
        if root:
            return root.strip()

    # 2) Fallback sur cfg["roots"]
    roots = (cfg.get("roots") or {})
    root = roots.get(context)
    return (root or "").strip()


def find_project_config_path(project_id: str) -> str | None:
    #"""
    #1) Cherche dans projets_index.json un item (id) et renvoie 'chemin_config' si présent.
    #2) Fallback conventionnel: C:\Affaires\{id}\_Config\project_config.json
    #"""
    
    for it in load_projets_index():
        if it.get("id") == project_id and it.get("chemin_config"):
            return it["chemin_config"]
    guess = Path(AFFAIRES_ROOT) / project_id / "_Config" / "project_config.json"
    if guess.exists():
        return str(guess)
    if project_id:
        log.warning(
            "Projet introuvable dans projets_index et fallback absent pour project_id=%s (index=%s)",
            project_id,
            PROJETS_INDEX_PATH,
        )
    return None

def load_project_config(project_id: str) -> dict:
    cfg_path = find_project_config_path(project_id)
    if not cfg_path:
        return {}
    return normalize_project_config(_load_json(cfg_path, {}))

def load_remote_map(project_id: str) -> dict:
    cfg_path = find_project_config_path(project_id)
    if not cfg_path:
        return {}
    root_dir = Path(cfg_path).parent.parent  # ...\{ID}\
    rm_path = root_dir / "_Config" / "_remote.map.json"
    return _load_json(str(rm_path), {})


_DOCUID_DB_LOCK = threading.Lock()


def _project_sqlite_path(project_id: str) -> Path:
    if not project_id:
        raise ValueError("project_id requis pour project.sqlite")

    cfg = load_project_config(project_id)
    rm = load_remote_map(project_id)
    if not cfg:
        raise ValueError(f"Configuration projet introuvable: {project_id}")

    rel = (
        ((cfg.get("paths") or {}).get("sqlite"))
        or ((rm.get("paths_rel") or {}).get("sqlite"))
        or r"_DB\project.sqlite"
    ).strip()

    cfg_path = find_project_config_path(project_id)
    if cfg_path:
        project_root = Path(cfg_path).parent.parent
        db_path = Path(os.path.normpath(os.path.join(str(project_root), rel)))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path

    try:
        sqlite_path = resolve_path(cfg, rm, "sqlite", context="pcfixe")
    except Exception:
        root_pc = get_root_for_context(cfg, rm, context="pcfixe")
        if not root_pc:
            raise ValueError(f"Racine pcfixe introuvable pour le projet: {project_id}")
        sqlite_path = os.path.normpath(os.path.join(root_pc, rel))

    db_path = Path(sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _ensure_project_doc_uid_db(project_id: str) -> Path:
    db_path = _project_sqlite_path(project_id)
    with _DOCUID_DB_LOCK:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    doc_uid TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    parent_doc_uid TEXT NULL,
                    source_kind TEXT NULL,
                    source_path TEXT NULL,
                    source_name TEXT NULL,
                    source_sha256 TEXT NULL,
                    source_id_legacy TEXT NULL,
                    piece_ref TEXT NULL,
                    doc_type TEXT NULL,
                    version_label TEXT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_uid TEXT PRIMARY KEY,
                    doc_uid TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    path TEXT NULL,
                    sha256 TEXT NULL,
                    external_ref TEXT NULL,
                    meta_json TEXT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(doc_uid) REFERENCES documents(doc_uid)
                );

                CREATE INDEX IF NOT EXISTS idx_documents_project_id
                    ON documents(project_id);
                CREATE INDEX IF NOT EXISTS idx_documents_project_source_path
                    ON documents(project_id, source_path);
                CREATE INDEX IF NOT EXISTS idx_documents_project_source_sha256
                    ON documents(project_id, source_sha256);
                CREATE INDEX IF NOT EXISTS idx_documents_project_source_legacy
                    ON documents(project_id, source_id_legacy);
                CREATE INDEX IF NOT EXISTS idx_artifacts_doc_uid
                    ON artifacts(doc_uid);
                CREATE INDEX IF NOT EXISTS idx_artifacts_type
                    ON artifacts(artifact_type);
                CREATE INDEX IF NOT EXISTS idx_artifacts_path
                    ON artifacts(path);
                """
            )
            conn.commit()
        finally:
            conn.close()
    return db_path


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _sha256_file_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _stable_doc_uid(project_id: str, source_path: str, source_sha256: str) -> str:
    raw = f"{project_id}|{source_path}|{source_sha256}"
    return sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _register_uploaded_file_doc(
    *,
    project_id: str,
    area: str,
    subdir: str | None,
    filename: str,
    dst_path: Path,
    file_sha256: str,
) -> None:
    db_path = _ensure_project_doc_uid_db(project_id)
    source_path = str(dst_path)
    source_name = Path(filename).name
    source_kind = "upload_file"
    legacy_source_id = sha256(source_path.encode("utf-8", errors="ignore")).hexdigest()[:16]
    doc_uid = _stable_doc_uid(project_id, source_path, file_sha256)
    artifact_uid = sha256(
        f"{doc_uid}|uploaded_file|{source_path}|{file_sha256}".encode("utf-8", errors="ignore")
    ).hexdigest()
    now_iso = _utc_now_iso()
    artifact_meta = json.dumps(
        {
            "area": area,
            "subdir": subdir,
            "filename": source_name,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    with _DOCUID_DB_LOCK:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                INSERT OR IGNORE INTO documents (
                    doc_uid, project_id, parent_doc_uid, source_kind, source_path,
                    source_name, source_sha256, source_id_legacy, piece_ref,
                    doc_type, version_label, status, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)
                """,
                (
                    doc_uid,
                    project_id,
                    source_kind,
                    source_path,
                    source_name,
                    file_sha256,
                    legacy_source_id,
                    "active",
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """
                UPDATE documents
                   SET source_kind = ?,
                       source_path = ?,
                       source_name = ?,
                       source_sha256 = ?,
                       source_id_legacy = ?,
                       status = ?,
                       updated_at = ?
                 WHERE doc_uid = ?
                """,
                (
                    source_kind,
                    source_path,
                    source_name,
                    file_sha256,
                    legacy_source_id,
                    "active",
                    now_iso,
                    doc_uid,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO artifacts (
                    artifact_uid, doc_uid, artifact_type, path, sha256,
                    external_ref, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_uid,
                    doc_uid,
                    "uploaded_file",
                    source_path,
                    file_sha256,
                    area or None,
                    artifact_meta,
                    now_iso,
                ),
            )
            conn.execute(
                """
                UPDATE artifacts
                   SET doc_uid = ?,
                       artifact_type = ?,
                       path = ?,
                       sha256 = ?,
                       external_ref = ?,
                       meta_json = ?,
                       created_at = ?
                 WHERE artifact_uid = ?
                """,
                (
                    doc_uid,
                    "uploaded_file",
                    source_path,
                    file_sha256,
                    area or None,
                    artifact_meta,
                    now_iso,
                    artifact_uid,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def _find_doc_uid_for_project_file(
    *,
    project_id: str,
    source_path: str,
    source_sha256: str | None = None,
) -> str | None:
    db_path = _ensure_project_doc_uid_db(project_id)
    with _DOCUID_DB_LOCK:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                """
                SELECT doc_uid
                  FROM documents
                 WHERE project_id = ? AND source_path = ?
                 ORDER BY updated_at DESC
                 LIMIT 1
                """,
                (project_id, source_path),
            ).fetchone()
            if row:
                return row[0]

            row = conn.execute(
                """
                SELECT d.doc_uid
                  FROM artifacts a
                  JOIN documents d ON d.doc_uid = a.doc_uid
                 WHERE d.project_id = ? AND a.path = ?
                 ORDER BY d.updated_at DESC
                 LIMIT 1
                """,
                (project_id, source_path),
            ).fetchone()
            if row:
                return row[0]

            if source_sha256:
                row = conn.execute(
                    """
                    SELECT doc_uid
                      FROM documents
                     WHERE project_id = ? AND source_sha256 = ?
                     ORDER BY updated_at DESC
                     LIMIT 1
                    """,
                    (project_id, source_sha256),
                ).fetchone()
                if row:
                    return row[0]
            return None
        finally:
            conn.close()


def _register_split_pdf_outputs(
    *,
    project_id: str,
    input_path: str,
    input_sha256: str | None,
    outputs: list[dict],
) -> tuple[list[dict], str | None]:
    db_path = _ensure_project_doc_uid_db(project_id)
    parent_doc_uid = _find_doc_uid_for_project_file(
        project_id=project_id,
        source_path=input_path,
        source_sha256=input_sha256,
    )
    if not parent_doc_uid:
        app.logger.warning("/api/split_pdf: parent doc_uid introuvable pour %s", input_path)

    now_iso = _utc_now_iso()
    enriched = []
    with _DOCUID_DB_LOCK:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            for item in outputs:
                out_path = str(item.get("out_path") or "")
                out_sha256 = item.get("sha256") or _sha256_file(out_path)
                source_name = Path(out_path).name
                legacy_source_id = sha256(out_path.encode("utf-8", errors="ignore")).hexdigest()[:16]
                child_doc_uid = _stable_doc_uid(project_id, out_path, out_sha256)
                artifact_uid = sha256(
                    f"{child_doc_uid}|split_pdf_output|{out_path}|{out_sha256}".encode("utf-8", errors="ignore")
                ).hexdigest()
                artifact_meta = json.dumps(
                    {
                        "input_path": input_path,
                        "piece": item.get("piece"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )

                conn.execute(
                    """
                    INSERT OR IGNORE INTO documents (
                        doc_uid, project_id, parent_doc_uid, source_kind, source_path,
                        source_name, source_sha256, source_id_legacy, piece_ref,
                        doc_type, version_label, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?)
                    """,
                    (
                        child_doc_uid,
                        project_id,
                        parent_doc_uid,
                        "split_pdf_child",
                        out_path,
                        source_name,
                        out_sha256,
                        legacy_source_id,
                        "active",
                        now_iso,
                        now_iso,
                    ),
                )
                conn.execute(
                    """
                    UPDATE documents
                       SET parent_doc_uid = ?,
                           source_kind = ?,
                           source_path = ?,
                           source_name = ?,
                           source_sha256 = ?,
                           source_id_legacy = ?,
                           status = ?,
                           updated_at = ?
                     WHERE doc_uid = ?
                    """,
                    (
                        parent_doc_uid,
                        "split_pdf_child",
                        out_path,
                        source_name,
                        out_sha256,
                        legacy_source_id,
                        "active",
                        now_iso,
                        child_doc_uid,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO artifacts (
                        artifact_uid, doc_uid, artifact_type, path, sha256,
                        external_ref, meta_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_uid,
                        child_doc_uid,
                        "split_pdf_output",
                        out_path,
                        out_sha256,
                        source_name,
                        artifact_meta,
                        now_iso,
                    ),
                )
                conn.execute(
                    """
                    UPDATE artifacts
                       SET doc_uid = ?,
                           artifact_type = ?,
                           path = ?,
                           sha256 = ?,
                           external_ref = ?,
                           meta_json = ?,
                           created_at = ?
                     WHERE artifact_uid = ?
                    """,
                    (
                        child_doc_uid,
                        "split_pdf_output",
                        out_path,
                        out_sha256,
                        source_name,
                        artifact_meta,
                        now_iso,
                        artifact_uid,
                    ),
                )

                enriched_item = dict(item)
                enriched_item["doc_uid"] = child_doc_uid
                if parent_doc_uid:
                    enriched_item["parent_doc_uid"] = parent_doc_uid
                enriched.append(enriched_item)

            conn.commit()
        finally:
            conn.close()

    return enriched, parent_doc_uid





def _sanitize_bullets(txt: str) -> str:
    if not isinstance(txt, str): 
        return txt
    # remplace '1. 🔍', '•', '–', '—', '→', '»', et emojis courants par '- '
    txt = re.sub(r'^\s*(\d+\.\s*|[•–—\-–—→»]\s*|[\u2190-\u21FF\u2700-\u27BF\u2600-\u26FF]\s*)', '- ', txt, flags=re.MULTILINE)
    # supprime les emojis restants
    txt = re.sub(r'[\U0001F300-\U0001FAFF]', '', txt)
    return txt.strip()

def _openai_models_list(models_index: dict, type_filter: str | None = None):
    data = []
    now = int(time.time())
    for key, meta in models_index.items():
        mtype = (meta.get("type") or "llm").lower()
        if type_filter and mtype != type_filter:
            continue
        data.append({
            "id": key,
            "object": "model",
            "created": meta.get("created", now),
            "owned_by": meta.get("owner", "local"),
            "type": mtype,  # "llm" | "embedding" | "asr" ...
            "backend": (meta.get("manifest") or {}).get("backend") or meta.get("backend"),
            "model_id": (meta.get("manifest") or {}).get("model_id"),
            "directory": meta.get("directory"),
            "dims": (meta.get("manifest") or {}).get("dims"),
            "source": (meta.get("manifest") or {}).get("source"),
            "enabled": meta.get("enabled", True),
        })
    data.sort(key=lambda x: (x.get("type"), x["id"]))
    return {"object": "list", "data": data}


def _safe_mkdir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p

def _mk_citation_list(sources: list[dict]) -> list[dict]:
    out = []
    for i, s in enumerate(sources, start=1):
        out.append({
            "idx": i,
            "title": (s.get("title") or s.get("url") or f"Source {i}")[:300],
            "url": s.get("url"),
            "published_at": s.get("published_at"),
            "author": s.get("author"),
            "site": s.get("site") or (urlparse(s.get("url") or "").netloc or "")[:120],
        })
    return out


def _inject_citation_instruction(sys_prompt: str, citations: list[dict]) -> str:
    lines = [
        "RÈGLE DE CITATION (OBLIGATOIRE) :",
        "- Quand tu relies un fait au contexte web, ajoute la référence entre crochets au bon endroit, p.ex. [1].",
        "- N’utilise que les indices listés ci-dessous. N’invente pas d’autres numéros.",
        "- Si une info ne vient pas d’une source listée, ne mets PAS de citation.",
        "- Réponds en français, clair et concis.",
        "",
        "Sources disponibles :"
    ]
    for c in citations:
        lines.append(f"[{c['idx']}] {c['title']} — {c['url']}")
    return (sys_prompt or "").rstrip() + "\n\n" + "\n".join(lines) + "\n"

def _postprocess_citations(answer: str, citations: list[dict]) -> str:
    nmax = len(citations)
    if not answer:
        return ""
    # normalise [ 1 ] -> [1]
    txt = re.sub(r"\[\s*(\d+)\s*\]", lambda m: f"[{m.group(1)}]", answer)
    # supprime indices hors plage
    def _keep(m):
        n = int(m.group(1))
        return f"[{n}]" if 1 <= n <= nmax else ""
    return re.sub(r"\[(\d+)\]", _keep, txt)

def _to_html_with_links(answer_txt: str, citations: list[dict]) -> str:
    idx_to_url = {c["idx"]: c["url"] for c in citations if c.get("url")}
    def _link(m):
        n = int(m.group(1))
        url = idx_to_url.get(n)
        if not url:
            return f"[{n}]"
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">[{n}]</a>'
    html_out = re.sub(r"\[(\d+)\]", _link, html.escape(answer_txt))
    return html_out.replace("\n", "<br/>")

# ---------- Styles d’affichage ----------
def _year_from(published_at: str | None) -> str | None:
    if not published_at:
        return None
    try:
        # accepte "2024-05-01", "2024/05/01", "2024"
        y = re.search(r"\d{4}", str(published_at))
        return y.group(0) if y else None
    except Exception:
        return None

def _short_label(c: dict) -> str:
    # auteur si dispo sinon site, sinon 1er mot du titre
    base = (c.get("author") or c.get("site") or (c.get("title") or "").split()[0] or "Source").strip(",.;: ")
    year = _year_from(c.get("published_at"))
    return f"{base}, {year}" if year else base

def _apply_inline_style(answer_txt: str, citations: list[dict], inline_style: str) -> str:
    """inline_style: 'numeric' (défaut) ou 'author-year'."""
    if inline_style not in {"author-year"}:
        return answer_txt
    labels = {c["idx"]: _short_label(c) for c in citations}
    def _swap(m):
        n = int(m.group(1))
        lab = labels.get(n)
        return f"({lab} [{n}])" if lab else f"[{n}]"
    return re.sub(r"\[(\d+)\]", _swap, answer_txt)

def _format_references(citations: list[dict], biblio_style: str = "numeric") -> tuple[str, str]:
    """biblio_style: 'numeric' (défaut) ou 'harvard' (très simple)."""
    items_txt, items_html = [], []
    for c in citations:
        url = c.get("url") or ""
        title = c.get("title") or url or f"Source {c['idx']}"
        year = _year_from(c.get("published_at"))
        author = c.get("author")
        site = c.get("site")

        if biblio_style == "harvard":
            # Auteur. (Année). Titre. Site. URL
            who = author or site or "s.n."
            when = year or "s.d."
            line = f"{who}. ({when}). {title}. {site or ''}. {url}"
        else:
            # [n] Titre — URL (Année si connue)
            when = f" ({year})" if year else ""
            line = f"[{c['idx']}] {title}{when} — {url}"

        items_txt.append(line.strip())
        items_html.append(f"<li>{html.escape(line)}</li>")

    biblio_txt = "\n".join(items_txt)
    biblio_html = "<ol>\n" + "\n".join(items_html) + "\n</ol>"
    return biblio_txt, biblio_html

def _postprocess_citations(answer: str, citations: list[dict]) -> tuple[str, str]:
    """
    Nettoie les citations : garde uniquement [n] avec 1<=n<=N.
    Retourne (answer_txt, answer_html_linkée).
    """

    nmax = len(citations)
    if not answer:
        return "", ""
    # Normalise les doubles crochets, espaces, etc.
    txt = re.sub(r"\[\s*(\d+)\s*\]", lambda m: f"[{m.group(1)}]", answer)

    # Supprime les citations hors plage
    def _keep(m):
        n = int(m.group(1))
        return f"[{n}]" if 1 <= n <= nmax else ""
    txt = re.sub(r"\[(\d+)\]", _keep, txt)

    # Version HTML linkée
    # Remplace [n] par <a href="url" ...>[n]</a>
    idx_to_url = {c["idx"]: c["url"] for c in citations if c.get("url")}
    def _to_link(m):
        n = int(m.group(1))
        url = idx_to_url.get(n)
        if not url:
            return f"[{n}]"
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">[{n}]</a>'
    html_out = re.sub(r"\[(\d+)\]", _to_link, html.escape(txt))
    html_out = html_out.replace("\n", "<br/>")
    return txt, html_out

def _resp(payload: dict, status: int, rid: str, retry_after: int | None = None):
    resp = jsonify({**payload, "request_id": rid})
    resp.headers["X-Request-Id"] = rid
    if retry_after is not None:
        resp.headers["Retry-After"] = str(retry_after)
    return resp, status


#*****************************************************

def _load_recent_qa_items(project_id: str, limit: int = 50, last_lines_per_file: int = 5):
    projects = _load_projects_index()
    proj = _find_project(project_id, projects)
    if not proj:
        return []

    cfg = load_project_config(project_id)
    root_pc = (cfg.get("roots") or {}).get("pcfixe")
    rag_pc_name = DEFAULT_SUBDIRS.get("rag_pc_subdir", "RAG_PC")
    logs_dir = _qa_logs_dir(root_pc, rag_pc_subdir=rag_pc_name)

    items = []
    for month_dir in sorted(logs_dir.glob("*"), reverse=True):
        for f in sorted(month_dir.glob("qa_*.jsonl"), reverse=True):
            items.append(f)

    out = []
    for fp in items:
        if len(out) >= limit:
            break
        try:
            with open(fp, "r", encoding="utf-8") as r:
                lines = r.readlines()[-last_lines_per_file:]
                out.extend([json.loads(x) for x in lines if x.strip()])
        except Exception:
            continue

    out = sorted(out, key=lambda x: x.get("ts", 0), reverse=True)[:limit]
    return out



def _fmt_ts(ts):
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return str(ts or "")

def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[:n].rstrip() + "…")

def build_qa_ctx(qa_items, *, clip_q=1200, clip_a=1800) -> str:
    blocks = []
    for it in qa_items or []:
        ts    = _fmt_ts(it.get("ts"))
        route = (it.get("route") or "").strip()
        model = (it.get("model_name") or it.get("model") or "").strip()

        q = _clip(it.get("prompt",""), clip_q)
        a = _clip(it.get("reponse",""), clip_a)
        if not (q or a):
            continue

        header = f"[QA_LOG ts={ts} route={route or '-'} model={model or '-'}]"
        blocks.append(
            "\n".join([
                header,
                f"Q: {q}",
                f"A: {a}",
                "---"
            ])
        )
    return "\n".join(blocks).strip()

def build_qa_ctx_professional(qa_items, limit=10, clip_len=800):
    from datetime import datetime

    def fmt_ts(ts):
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts or "")

    blocks = []
    for it in (qa_items or [])[:limit]:
        ts = fmt_ts(it.get("ts"))
        prompt = (it.get("prompt") or "").strip()
        reponse = (it.get("reponse") or "").strip()

        if len(prompt) > clip_len:
            prompt = prompt[:clip_len].rstrip() + "…"
        if len(reponse) > clip_len:
            reponse = reponse[:clip_len].rstrip() + "…"

        blocks.append(
            f"- Date : {ts}\n"
            f"  Objet : {prompt}\n"
            f"  Réponse antérieure : {reponse}\n"
        )

    if not blocks:
        return ""

    header = (
        "=== CONTEXTE INTERNE – HISTORIQUE DES ÉCHANGES (NON CITABLE) ===\n"
        "Les éléments suivants correspondent à un historique interne d’échanges.\n"
        "Ils sont fournis uniquement pour compréhension contextuelle.\n"
        "Ils ne constituent pas des sources documentaires.\n"
        "Ils ne doivent pas être cités ni reproduits dans la réponse.\n\n"
    )

    footer = "\n=== FIN CONTEXTE INTERNE ===\n"

    return header + "\n".join(blocks) + footer

# =========================
# Routes
# =========================
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({
        "status": "ok",
        "model_name": LOADED_MODEL_NAME,
        "port": PORT,
        "paths": {
            "MODELS_PATH": str(MODELS_PATH),
            "CHROMA_BASE": PATHS.get("CHROMA_BASE"),
            "RAG_BASE": PATHS.get("RAG_BASE"),
            "LOG_DIR": str(LOG_DIR),
            "SYSTEM_PROMPT_PATH": str(SYSTEM_PROMPT_PATH),
            "CONFIG_PATH": str(CONFIG_PATH)
        },
        "asr_quant": VOXTRAL_PIPELINES.get((DEFAULT_ASR, True, False), {}).get("quant", None)
    })



def _pick_api_key_from_config(cfg: dict) -> str | None:
    try:
        keys = cfg.get("api_keys") or {}
        for _, val in keys.items():
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass
    return None

@app.route("/info", methods=["GET"])
def info():
    return jsonify({
        "status": "ok",
        "config_path": str(CONFIG_PATH),
        "api_keys_loaded": len(API_KEYS),
        "has_api_keys": bool(API_KEYS),
        "loaded_model": globals().get("LOADED_MODEL_NAME"),
        "default_llm": globals().get("DEFAULT_LLM"),
    })



def _wait_listen(host: str, port: int, deadline_s: float = 45.0, sleep_s: float = 0.25) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=0.6):
                return True
        except OSError:
            time.sleep(sleep_s)
    return False

def warmup():
    """
    1) S'assure que le modèle par défaut est chargé (DEFAULT_LLM)
    2) Fait une courte génération locale pour "amorcer" le modèle (tokenizer + KV cache)
    3) Chauffe /annoter avec une clé de config, mais seulement quand Flask écoute
    """
    try:
        # 1) charge/switch vers le modèle par défaut
        maybe_switch_model(DEFAULT_LLM)

        # 2) mini-génération locale (évite 1ère réponse lente ou vide)
        _ = generer_texte(
            prompt_final="ok",
            model_name=DEFAULT_LLM,
            system_prompt="",
            generation_params={"max_tokens": 8, "temperature": 0.0}
        )
        app.logger.info("[Warmup] LLM '%s' amorcé par génération locale.", DEFAULT_LLM)


        # 2bis) attend que le serveur HTTP soit vraiment prêt
        if not _wait_listen("127.0.0.1", PORT, deadline_s=45.0):
            app.logger.warning("[Warmup] Port %s non joignable; skip chauffe HTTP.", PORT)
            return
        return
        
    except Exception as e:
        app.logger.warning("[Warmup] Échec warmup: %s", e)


def _pick_api_key_from_config(cfg: dict) -> str | None:
    try:
        keys = cfg.get("api_keys") or {}
        # on récupère la 1re clé (valeur) disponible
        for _, val in keys.items():
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass
    return None



def clean_csv_dataframe(df):
    """
    Nettoyage des segments ASR avant export des CSV.
    - supprime répétitions aberrantes (glitch)
    - supprime doublons stricts
    - supprime lignes brouillons : deux lignes consécutives quasi identiques
      avec le même speaker et un timestamp similaire, en gardant la seconde
    """

    # -------- 1. Suppression des glitches (répétitions massives) ----------
    def is_glitch(text):
        if not isinstance(text, str):
            return False
        if len(text) > 2000:
            return True
        if re.fullmatch(r'(de[ ,.\-…]*){10,}', text, re.I):
            return True
        if re.fullmatch(r'(no[ ,.\-…]*){10,}', text, re.I):
            return True
        if re.fullmatch(r'(ah[ ah!,.…]*){10,}', text, re.I):
            return True
        return False

    df = df[~df["text"].apply(is_glitch)].copy()

    # -------- 2. Suppression des doublons stricts ----------
    df = df.drop_duplicates(subset=["start", "end", "speaker", "text"]).reset_index(drop=True)

    # -------- 3. Suppression des lignes brouillon / correcte ----------
    TIME_EPS = 0.05  # 50 ms
    END_EPS  = 0.20  # 200 ms

    rows_to_drop = set()

    for i in range(len(df) - 1):
        if i in rows_to_drop:
            continue
        r1 = df.iloc[i]
        r2 = df.iloc[i + 1]

        # même speaker ?
        if r1["speaker"] != r2["speaker"]:
            continue

        # timestamps très proches ?
        if abs(r1["start"] - r2["start"]) > TIME_EPS:
            continue

        # la seconde est une extension ou correction de la première
        if not (r2["end"] >= r1["end"] or abs(r1["end"] - r2["end"]) < END_EPS):
            continue

        t1 = r1["text"].strip()
        t2 = r2["text"].strip()

        # même texte ou t1 est un préfixe de t2
        if t1 == t2 or t2.startswith(t1.rstrip(" .,…")):
            rows_to_drop.add(i)

    df = df.drop(index=list(rows_to_drop)).reset_index(drop=True)

    return df


@app.get("/v1/audio/transcriptions/models")
def v1_audio_transcription_models():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    try:
        return jsonify(_openai_models_list(models_index, "asr"))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/v1/models")
def v1_models():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    try:
        type_filter = request.args.get("type")
        if type_filter:
            type_filter = type_filter.lower()
            if type_filter not in ("llm", "embedding", "asr"):
                return jsonify({"error": "invalid type; expected 'llm' or 'embedding' or 'asr'"}), 400
        return jsonify(_openai_models_list(models_index, type_filter))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/vision/models")
def vision_models():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    out = []
    for k, v in (models_index or {}).items():
        if isinstance(v, dict) and _is_vision_model(v):
            out.append({
                "model": k,
                "directory": v.get("directory"),
                "file": v.get("file"),
                "mmproj": v.get("mmproj"),
                "backend": (v.get("manifest") or {}).get("backend") or v.get("backend"),
            })
    return jsonify({"models": out})



@app.route("/models_status", methods=["GET"])
def models_status():
    """
    Statut humainement lisible :
    - modèle actuellement chargé
    - modèles disponibles dans models_index.json
    """
    try:
        models = {
            "loaded_model": current_model_name,
            "available_models": list(models_index.keys()),
        }
        return jsonify(models)
    except Exception as e:
        app.logger.exception("models_status error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/models", methods=["GET"])
def models_list_route():
    """
    Route de compatibilité pour openai-adapter :
    retourne uniquement les identifiants de modèles (format OpenAI-like).
    Le JSON complet reste disponible sur /models_index.
    """
    try:
        from flask import jsonify
        data = [{"id": key, "type": value.get("type", "llm")}
                for key, value in models_index.items()]
        return jsonify({"object": "list", "data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------------------------------------------------------
# Route orchestre
# ----------------------------------------------------------------------------



@app.route("/chat_orchestre", methods=["POST"])
def chat_orchestre():
    if not is_authorized(request):
        return jsonify({"reponse": ""}), 401

    data = request.get_json(silent=True) or {}
    meta = data

    # Choix de la route cible
    if meta.get("photo") or meta.get("image"):
        subpath = "/annoter"
    elif meta.get("rag_vector") or meta.get("collection") or meta.get("vec_backend"):
        subpath = "/annoter_rag_vecteur"
    elif meta.get("rag_dossier_pcfixe"):
        subpath = "/annoter_rag"
    elif meta.get("memory_id") or meta.get("conversation_id") or request.headers.get("x-conversation-id"):
        subpath = "/annoter_rag_memoire"
    elif meta.get("url") or meta.get("web"):
        subpath = "/annoter_web"
    else:
        subpath = "/chat_llm"

    # Dispatch direct (sans HTTP)
    try:
        if subpath == "/annoter":
            return annoter()
        if subpath == "/annoter_rag_vecteur":
            return annoter_rag_vecteur()
        if subpath == "/annoter_rag":
            return annoter_rag()
        if subpath == "/annoter_rag_memoire":
            return annoter_rag_memoire()
        if subpath == "/annoter_web":
            return annoter_web()
        if subpath == "/chat_llm":
            return chat_llm()

        return jsonify({"reponse": "", "error": f"Route inconnue: {subpath}"}), 400

    except Exception as e:
        current_app.logger.exception("chat_orchestre error: %s", e)
        return jsonify({"reponse": f"Erreur interne: {e}"}), 500

    
@app.get("/Embedding_models")
def list_models():
    return jsonify(sorted([k for k, v in models_index.items() if v.get("type") == "embedding"]))


@app.route("/models_index", methods=["GET"])
def models_index_route():
    return jsonify(models_index)


@app.route("/asr_models", methods=["GET"])
def asr_models():
    """Liste les modèles ASR (type == 'asr') depuis models_index.json"""
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    try:
        asr_keys = [k for k, v in models_index.items() if v.get("type") == "asr"]
        details = {k: models_index[k] for k in asr_keys}
        return jsonify({"models": asr_keys, "details": details})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ocr_grid", methods=["GET"])
def ocr_grid_get():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    name = request.args.get("name", DEFAULT_GRID_NAME)
    grid_path = (GRIDS_DIR / name).resolve()
    if not grid_path.exists():
        return jsonify({"error": f"Grille introuvable: {name}"}), 404

    try:
        data = json.loads(grid_path.read_text(encoding="utf-8"))
        return jsonify({"name": name, "grid": data})
    except Exception as e:
        return jsonify({"error": f"Lecture grille impossible: {e}"}), 500

@app.route("/ocr_history", methods=["GET"])
def ocr_history_get():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    limit = int(request.args.get("limit", 50))
    grid_name = request.args.get("grid_name")
    doc_hash  = request.args.get("doc_hash")
    since_ts  = int(request.args.get("since", 0))

    try:
        hist = json.loads(HISTORY_PATH.read_text(encoding="utf-8")) if HISTORY_PATH.exists() else []
        # filtres
        if grid_name:
            hist = [h for h in hist if h.get("grid") == grid_name]
        if doc_hash:
            hist = [h for h in hist if h.get("doc_hash") == doc_hash]
        if since_ts:
            hist = [h for h in hist if int(h.get("timestamp", 0)) >= since_ts]
        # tri récents -> anciens + limite
        hist.sort(key=lambda x: int(x.get("timestamp", 0)), reverse=True)
        return jsonify({"items": hist[:limit], "count": len(hist[:limit])})
    except Exception as e:
        return jsonify({"error": f"Lecture history impossible: {e}"}), 500


# ------------------------------------------------------------
# GET /anonymization_reports
# Liste les rapports d’anonymisation produits lors des indexations CSV→Chroma
# ------------------------------------------------------------
@app.route("/anonymization_reports", methods=["GET"])
def list_anonymization_reports():
    try:
        # répertoire d’export = LOG_DIR/exports
        log_dir = Path(PATHS.get("LOG_DIR", ".")) / "exports"
        log_dir.mkdir(parents=True, exist_ok=True)

        # param collection optionnel pour filtrer
        collection = request.args.get("collection")

        files = sorted(log_dir.glob("anonymization_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        reports = []
        for f in files:
            if collection and collection not in f.name:
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_file"] = str(f)
                reports.append(data)
            except Exception as e:
                reports.append({"_file": str(f), "error": str(e)})

        return jsonify({"ok": True, "count": len(reports), "reports": reports})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/prompts_structures", methods=["GET"])
def get_prompts_structures():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    project_id = (request.args.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"error": "project_id manquant"}), 400
    try:
        projects = _load_projects_index()
        proj = _find_project(project_id, projects)
        if not proj:
            return jsonify({"error": f"Projet introuvable: {project_id}"}), 404
        cfg = _load_project_config_for_server(proj)
        cfg = _normalize_prompts_structures(cfg)
        return jsonify({"ok": True, "prompts_structures": cfg.get("prompts_structures", [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/prompts_structures", methods=["PUT"])
def put_prompts_structures():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    data = request.get_json(silent=True) or {}
    if not data:
        app.logger.warning("%s: JSON vide/non décodable", request.path)
    project_id = (data.get("project_id") or "").strip()
    prompts = data.get("prompts_structures")
    if not project_id or not isinstance(prompts, list):
        return jsonify({"error": "project_id ou prompts_structures invalide"}), 400
    try:
        projects = _load_projects_index()
        proj = _find_project(project_id, projects)
        if not proj:
            return jsonify({"error": f"Projet introuvable: {project_id}"}), 404
        # chemin config côté PC fixe prioritaire
        cfg_path = proj.get("chemin_config_pcfixe") or proj.get("chemin_config")
        if not cfg_path or (not os.path.exists(cfg_path)):
            return jsonify({"error": "chemin_config(_pcfixe) introuvable côté serveur"}), 404

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # normaliser + remplacer
        cfg = _normalize_prompts_structures(cfg)
        cfg["prompts_structures"] = prompts

        # écriture atomique
        tmp = cfg_path + ".part"
        with open(tmp, "w", encoding="utf-8") as w:
            json.dump(cfg, w, indent=2, ensure_ascii=False)
        os.replace(tmp, cfg_path)
        return jsonify({"ok": True, "count": len(prompts)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/prompts_structures/item", methods=["DELETE"])
def delete_prompts_structure_item():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    project_id = (request.args.get("project_id") or "").strip()
    nom = (request.args.get("nom") or "").strip()
    if not project_id or not nom:
        return jsonify({"error": "project_id/nom manquant"}), 400
    try:
        projects = _load_projects_index()
        proj = _find_project(project_id, projects)
        if not proj:
            return jsonify({"error": f"Projet introuvable: {project_id}"}), 404

        cfg_path = proj.get("chemin_config_pcfixe") or proj.get("chemin_config")
        if not cfg_path or (not os.path.exists(cfg_path)):
            return jsonify({"error": "chemin_config(_pcfixe) introuvable"}), 404

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg = _normalize_prompts_structures(cfg)
        lst = [p for p in cfg.get("prompts_structures", []) if p.get("nom") != nom]
        cfg["prompts_structures"] = lst

        tmp = cfg_path + ".part"
        with open(tmp, "w", encoding="utf-8") as w:
            json.dump(cfg, w, indent=2, ensure_ascii=False)
        os.replace(tmp, cfg_path)
        return jsonify({"ok": True, "count": len(lst)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


ANNOTER_BUSY_RETRY_AFTER = 3  # secondes (à ajuster)
LLM_BUSY = threading.Lock()
LLM_BUSY_SINCE = 0.0

@app.route("/annoter", methods=["POST"])
def annoter():
    """Traite une demande d'annotation LLM a partir du payload JSON recu.

    La route consomme notamment `prompt`, `task`, `model_name` et
    `expect_json`, applique les gardes d'autorisation et de concurrence
    existantes, puis renvoie la reponse d'annotation au format JSON.
    """
    global LLM_BUSY_SINCE
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:8]
    t0 = time.time()
    app.logger.info("[ANNOTER][%s] START", rid)
    busy_acquired = False
    busy_acquired = LLM_BUSY.acquire(blocking=False)
    if not busy_acquired:
        resp = jsonify({"error": "LLM busy", "request_id": rid})
        resp.headers["Retry-After"] = "2"
        resp.headers["X-Request-Id"] = rid
        return resp, 503

    LLM_BUSY_SINCE = time.time()

    try:
        if not is_authorized(request):
            resp = jsonify({"error": "Clé API invalide", "request_id": rid})
            resp.headers["X-Request-Id"] = rid
            return resp, 401

        data = request.get_json(silent=True) or {}
        if not data:
            app.logger.warning("%s: JSON vide/non décodable", request.path)
        prompt = (data.get("prompt") or "").strip()
        expect_json = bool(data.get("expect_json", False))

        # --- tâche ---
        tname = data.get("task") or data.get("tname")
        if not tname:
            tname = _infer_task(data.get("prompt") or "")

        # --- modèle ---
        model_name = data.get("model_name") or data.get("model") or DEFAULT_LLM
        if model_name not in KNOWN_LLMS:
            app.logger.warning(
                "⛔ Nom de modèle non reconnu '%s' -> DEFAULT_LLM='%s'",
                model_name, DEFAULT_LLM
            )
            model_name = DEFAULT_LLM

        maybe_switch_model(model_name)

        data = request.get_json(silent=True) or {}
        app.logger.info("[ANNOTER][%s] salient_families=%s", rid, data.get("salient_families"))

        # ======================================================
        # POLITIQUES PAR TÂCHE (STABLES)
        # ======================================================

        TASK_POLICIES = {
            "libelle": dict(
                temperature=0.25,
                max_tokens=120,
                repeat_penalty=1.15,
            ),
            "commentaire": dict(
                temperature=0.0,
                max_tokens=220,
                repeat_penalty=1.0,
            ),
        }


        policy = TASK_POLICIES.get(tname, {})
        overrides = dict(policy)

        with ANNOTER_STATS_LOCK:
            ANNOTER_STATS["calls"] += 1


        # ======================================================
        # PROMPT FINAL
        # ======================================================
        system_prompt = data.get("system", get_system_prompt())

        # --- historique ---
        history = data.get("history") or data.get("messages") or []
        history_text = ""
        try:
            if isinstance(history, list):
                parts = []
                for h in history:
                    if isinstance(h, dict):
                        parts.append(str(h.get("content", "")))
                    else:
                        parts.append(str(h))
                history_text = "\n".join([p for p in parts if p])
        except Exception:
            history_text = ""

        # --- construction du prompt final ---
        prompt_final = f"{system_prompt}\n"
        if history_text:
            prompt_final += f"{history_text}\n"
        prompt_final += prompt


        # paramètres effectifs du modèle

        tname = tname if tname else _infer_task(prompt)

        dictee_text = (data.get("dictee_asr_text") or "").strip()
        prefer_dictee = bool(data.get("prefer_dictee")) and bool(dictee_text)




        # ======================================================
        # OUTILS DE VALIDATION
        # ======================================================

        def validate_text(txt: str) -> list[str]:

            if tname == "libelle":
                anchor_terms = build_anchor_terms_for_libelle(data)
                return validate_libelle(txt, anchor_terms=anchor_terms)

            if tname == "commentaire":
                errs = validate_commentaire(txt) # les contrôles généraux
                errs += validate_commentaire_structure(txt, prefer_dictee=prefer_dictee)

                salient = data.get("salient_families") or []
                if salient:
                    errs += validate_salient_presence(txt, salient)
                return errs
            return []
        
        def salvage_json_and_validate(raw_text: str) -> tuple[str | None, list[str]]:
            obj = extract_last_json_object(raw_text)
            if not isinstance(obj, dict):
                return None, ["json_incomplet"]

            txt = (obj.get("texte") or "").strip()
            if not txt:
                return None, ["json_incomplet"]

            errs = validate_text(txt)
            return txt, errs


        def parse_json(raw_text: str) -> tuple[str | None, list[str]]:
            if not raw_text:
                return None, ["json_incomplet"]

            data = extract_json_texte_from_llm(raw_text)

            if not isinstance(data, dict):
                return None, ["json_incomplet"]

            txt = (data.get("texte") or "").strip()
            if not txt:
                return None, ["json_incomplet"]

            errs = validate_text(txt)
            return txt, errs

        def _return_ok(texte: str, rid: str, warnings: list[str] | None = None):
            warnings = warnings or []
            resp = jsonify({
                "reponse_json": {"texte": texte},
                "reponse": texte,
                "validation_errors": warnings,
                "request_id": rid,
            })
            resp.headers["X-Request-Id"] = rid
            return resp, 200

        def _return_fail(errs: list[str], rid: str, warnings: list[str] | None = None):
            warnings = warnings or []
            resp = jsonify({
                "reponse_json": {},
                "reponse": "",
                "validation_errors": errs + warnings,
                "request_id": rid,
            })
            resp.headers["X-Request-Id"] = rid
            return resp, 200



        def _stats_pass2(errs2: list[str], t0: float):
            ms = int((time.time() - t0) * 1000)
            with ANNOTER_STATS_LOCK:
                ANNOTER_STATS["lat_ms"].append(ms)
                if not errs2:
                    ANNOTER_STATS["ok_pass2"] += 1
                else:
                    ANNOTER_STATS["fail"] += 1
                    for e in errs2:
                        ANNOTER_STATS["errs_pass2"][e] += 1

        

        # ======================================================
        #      GESTION n_ctx / marge / min_prompt_tokens
        # ======================================================

        local_max_tokens = int(
            data.get("max_tokens")
            or PARAMS.get("max_tokens", DEFAULT_LOCAL_MAX_TOKENS)
        )
        local_marge = int(
            data.get("marge")
            or PARAMS.get("marge", DEFAULT_LOCAL_MARGE_TOKENS)
        )
        min_prompt_tokens = int(
            data.get("min_prompt_tokens")
            or PARAMS.get("min_prompt_tokens", DEFAULT_LOCAL_MIN_PROMPT_TOKENS)
        )

        # overrides explicites du client (batch/UI) priment
        if data.get("overrides"):
            overrides.update(data["overrides"])

        # =========================
        # 1) Harmonisation max_tokens
        # =========================
        eff = effective_params(model_name, overrides)
        eff = _normalize_types(eff)

        # Le max_tokens de référence doit être celui de eff (politique tâche, override, etc.)
        local_max_tokens = int(eff.get("max_tokens", local_max_tokens))
        local_marge = int(data.get("marge") or PARAMS.get("marge", DEFAULT_LOCAL_MARGE_TOKENS))
        min_prompt_tokens = int(data.get("min_prompt_tokens") or PARAMS.get("min_prompt_tokens", DEFAULT_LOCAL_MIN_PROMPT_TOKENS))

        n_ctx = int(eff.get("n_ctx", N_CTX))

        # =========================
        # 2) Comptage tokens prompt
        # =========================
        try:
            prompt_tokens = len(llm.tokenize(prompt_final.encode("utf-8", "ignore")))
        except Exception:
            prompt_tokens = max(1, len(prompt_final) // 4)

        orig_prompt_tokens = prompt_tokens

        # =========================
        # 3) Budget prompt (avec max_tokens harmonisé)
        # =========================
        available_for_prompt = n_ctx - local_max_tokens - local_marge
        available_for_prompt = max(available_for_prompt, min_prompt_tokens)

        # Troncature si dépassement
        if prompt_tokens > available_for_prompt:
            frac = available_for_prompt / float(prompt_tokens)
            keep_chars = max(int(len(prompt_final) * frac), 256)
            if keep_chars < len(prompt_final):
                prompt_final = prompt_final[-keep_chars:]

            try:
                prompt_tokens = len(llm.tokenize(prompt_final.encode("utf-8", "ignore")))
            except Exception:
                prompt_tokens = max(1, len(prompt_final) // 4)

            app.logger.warning(
                "[annoter] prompt tronqué: orig=%d → new=%d, budget=%d, n_ctx=%d, marge=%d, max_tokens(ref)=%d",
                orig_prompt_tokens, prompt_tokens, available_for_prompt, n_ctx, local_marge, local_max_tokens
            )

        # Garde-fou si prompt toujours trop long
        if prompt_tokens >= n_ctx:
            msg = f"Prompt trop long après troncature: tokens={prompt_tokens}, n_ctx={n_ctx}. Réduisez la transcription."
            app.logger.error("[annoter] " + msg)
            resp = jsonify({"error": msg, "request_id": rid})
            resp.headers["X-Request-Id"] = rid
            return resp, 400

        # =========================
        # 4) Clamp max_tokens (final, après troncature)
        # =========================
        def clamp_max_tokens(eff: dict, prompt_tokens: int, safety: int) -> dict:
            n_ctx = int(eff.get("n_ctx", N_CTX))
            max_t = int(eff.get("max_tokens", DEFAULT_LOCAL_MIN_PROMPT_TOKENS))

            raw_budget = n_ctx - prompt_tokens - safety  # tokens dispo pour la génération
            if raw_budget <= 0:
                eff["max_tokens"] = DEFAULT_LOCAL_MARGE_TOKENS  # minimal
                return eff

            if max_t > raw_budget:
                eff["max_tokens"] = raw_budget
            return eff

        eff_before = dict(eff)
        eff = clamp_max_tokens(eff, prompt_tokens=prompt_tokens, safety=local_marge)

        if int(eff_before.get("max_tokens", 0)) != int(eff.get("max_tokens", 0)):
            app.logger.info(
                "[annoter][%s] clamp_max_tokens: max_tokens %s -> %s (prompt_tokens=%d n_ctx=%d marge=%d)",
                rid,
                eff_before.get("max_tokens"),
                eff.get("max_tokens"),
                prompt_tokens,
                int(eff.get("n_ctx", n_ctx)),
                local_marge,
            )

        # --- budget disponible pour le prompt ---
        available_for_prompt = n_ctx - local_max_tokens - local_marge
        available_for_prompt = max(available_for_prompt, min_prompt_tokens)
        
        app.logger.info(
            "[annoter][%s] budgets: prompt_tokens=%d orig=%d available_for_prompt=%d n_ctx=%d max_tokens(ref)=%d marge=%d min_prompt_tokens=%d",
            rid, prompt_tokens, orig_prompt_tokens, available_for_prompt, n_ctx, local_max_tokens, local_marge, min_prompt_tokens
        )
        # --- troncature si dépassement ---
        if prompt_tokens > available_for_prompt:
            frac = available_for_prompt / float(prompt_tokens)
            keep_chars = int(len(prompt_final) * frac)
            keep_chars = max(keep_chars, 256)

            if keep_chars < len(prompt_final):
                prompt_final = prompt_final[-keep_chars:]

            try:
                prompt_tokens = len(llm.tokenize(prompt_final.encode("utf-8", "ignore")))
            except Exception:
                prompt_tokens = max(1, len(prompt_final) // 4)

            app.logger.warning(
                "[annoter] prompt tronqué: orig=%d → new=%d, budget=%d, n_ctx=%d, marge=%d",
                orig_prompt_tokens, prompt_tokens,
                available_for_prompt, n_ctx, local_marge
            )

            # garde-fou
            if prompt_tokens >= n_ctx:
                msg = (
                    f"Prompt trop long après troncature: tokens={prompt_tokens}, "
                    f"n_ctx={n_ctx}. Réduisez la transcription."
                )
                app.logger.error("[annoter] " + msg)

                resp = jsonify({
                    "error": msg,
                    "request_id": rid,
                })
                resp.headers["X-Request-Id"] = rid
                return resp, 400

            try:
                prompt_tokens = len(llm.tokenize(prompt_final.encode("utf-8", "ignore")))
            except Exception:
                prompt_tokens = max(1, len(prompt_final) // 4)

            app.logger.warning(
                "[annoter] prompt tronqué: orig=%d → new=%d, disponible=%d, n_ctx=%d, marge=%d",
                orig_prompt_tokens, prompt_tokens,
                available_for_prompt, n_ctx, local_marge
            )

        
        # ======================================================
        #         PARAMÈTRES DE GÉNÉRATION EFFECTIFS
        # ======================================================

        eff = clamp_max_tokens(eff, prompt_tokens=prompt_tokens, safety=local_marge)

        # 🔒 VERROU STRUCTUREL COMMENTAIRE (AU BON NIVEAU)
        if expect_json and tname == "commentaire":
            eff.update({
                "temperature": 0.0,
                "top_p": 1.0,
                "repeat_penalty": 1.0,
                "presence_penalty": 0.0,
                "frequency_penalty": 0.0,
                "max_tokens": 180,
            })

        gen = make_gen_kwargs(eff)

        # --- ne pas passer marge/min_prompt_tokens au modèle ---
        safe_gen = {k: v for k, v in gen.items()
                if k not in ("marge", "min_prompt_tokens") and v is not None}
        

        app.logger.info(
            "🎛️ params_effectifs tname=%s temp=%s pres=%s freq=%s",
            tname,
            eff.get("temperature"),
            eff.get("presence_penalty"),
            eff.get("frequency_penalty"),
        )

        log_effective_params(
            app.logger,
            model_name,
            eff,
            context=f"tname={tname} expect_json={expect_json}"
        )

        # ======================================================
        #       Reroutage automatique vers /annoter_rag
        # ======================================================
        rag_dir = data.get("rag_dossier_pcfixe")
        too_long_ctx = (
            prompt_tokens > int(eff.get("n_ctx", n_ctx)) * 0.75
            or len(history) > 8
        )

        if too_long_ctx and rag_dir and Path(rag_dir).exists():
            app.logger.info(
                "↪️ redirection /annoter_rag (ctx long) rag_dir=%s", rag_dir
            )
            data.setdefault("rag_dossier_pcfixe", rag_dir)
            with app.test_request_context(
                "/annoter_rag", method="POST", json=data, headers=request.headers
            ):
                return annoter_rag()



        # ======================================================
        # PASS 1
        # ======================================================



        if expect_json:
            anchor_add = ""
            if tname == "commentaire":

                prefer = bool(prefer_dictee)
                anchor_tr = "La dictée mentionne" if prefer else "La transcription mentionne"
                anchor_vlm = "Selon la description visuelle"

                anchor_add = (
                        "STRUCTURE STRICTE DU COMMENTAIRE\n"
                        "- 3 phrases EXACTEMENT, sur UNE seule ligne.\n"
                        "- Phrase 1 : éléments visibles sur la photo uniquement (interdit : transcription, dictée, VLM).\n"
                        f"- Phrase 2 : commence STRICTEMENT par \"{anchor_vlm}\" (sans deux-points).\n"
                        f"- Phrase 3 : commence STRICTEMENT par \"{anchor_tr}\" (sans deux-points).\n"
                        "- Interdit : modalisation (probablement, semble, paraît, peut, pourrait, etc.).\n"
                        "- Longueurs max : P1≤140, P2≤110, P3≤110 caractères.\n\n"
                        "CONTRAINTE POINTS SAILLANTS (si fournis)\n"
                        f"- Les termes exacts des points saillants doivent apparaître dans la Phrase 2.\n"
                        "- Ne pas les forcer dans la Phrase 1.\n"
                    )
        

            json_instr = (
                "FORMAT DE SORTIE OBLIGATOIRE\n"
                "Réponds avec EXACTEMENT UN SEUL objet JSON sur UNE SEULE LIGNE.\n"
                "Forme unique autorisée : {\"texte\":\"...\"}\n"
                "- Une seule clé : texte\n"
                "- Aucun texte avant ou après\n"
                "- Ne propose JAMAIS plusieurs versions\n"
                "- Ne répète JAMAIS l’objet JSON\n"
                "Si impossible : {}\n\n"
            )
        
            prompt_json = json_instr + anchor_add + prompt_final
        else:
            prompt_json = prompt_final
                
    

        app.logger.info("safe_gen_sent=%s", safe_gen)

        app.logger.info(
            "[annoter][%s] gen_final: task=%s expect_json=%s max_tokens=%s temp=%s top_p=%s repeat_penalty=%s prompt_tokens=%d",
            rid, tname, expect_json,
            safe_gen.get("max_tokens"), safe_gen.get("temperature"), safe_gen.get("top_p"), safe_gen.get("repeat_penalty"),
            prompt_tokens
        )

        # génération : verrou le plus court possible

        with LLM_GEN_LOCK:
            rep1 = llm(prompt_json, **safe_gen)

        raw1 = ((rep1["choices"][0]["text"]) or "").strip()

        if not expect_json:
            app.logger.info("[ANNOTER][%s] RETURN 200 ok=True", rid)
            return _return_ok(raw1, rid)
        

        texte1, errs1 = parse_json(raw1)

        # ------------------------------------------------
        # Phase 1.5 : salvage JSON si échec purement technique
        # ------------------------------------------------

        if errs1 and "json_incomplet" in errs1:
            obj1 = extract_last_json_object(raw1)

            if isinstance(obj1, dict):
                cand = (obj1.get("texte") or "").strip()

                if cand:
                    errs1b = validate_text(cand)

                    if not errs1b:
                        texte1, errs1 = cand, []
                    else:
                        errs1 = errs1b


        # ------------------------------------------------
        # logging si erreur
        # ------------------------------------------------

        if errs1:
            app.logger.warning(
                "[ANNOTER][%s] raw1_len=%d head=%r tail=%r",
                rid, len(raw1), raw1[:220], raw1[-220:]
            )

            try:
                p = Path("logs_bad_json")
                p.mkdir(exist_ok=True)
                (p / f"{rid}.txt").write_text(raw1, encoding="utf-8", errors="ignore")
            except Exception:
                pass


        # ------------------------------------------------
        # split hard / soft
        # ------------------------------------------------

        if tname == "libelle":
            hard1, soft1 = split_libelle_errors(errs1)
        else:
            salient = data.get("salient_families") or []
            hard1, soft1 = split_errors(errs1, salient)


        # ------------------------------------------------
        # PASS1 OK
        # ------------------------------------------------

        if not hard1:

            with ANNOTER_STATS_LOCK:
                ANNOTER_STATS["ok_pass1"] += 1
                ANNOTER_STATS["lat_ms"].append(int((time.time() - t0) * 1000))

            app.logger.info("[ANNOTER][%s] RETURN 200 ok=True (soft=%s)", rid, soft1)

            resp = jsonify({
                "reponse_json": {"texte": texte1},
                "reponse": texte1,
                "validation_errors": soft1,
                "request_id": rid,
            })

            resp.headers["X-Request-Id"] = rid
            return resp, 200


        # ------------------------------------------------
        # PASS2 nécessaire
        # ------------------------------------------------

        errs1 = hard1

        with ANNOTER_STATS_LOCK:
            for e in errs1:
                ANNOTER_STATS["errs_pass1"][e] += 1

        # ======================================================
        # PASS 2 — RETRY STRICT
        # ======================================================
        if tname == "libelle":
            safe_gen_retry = dict(safe_gen, temperature=0.1, top_p=0.9, repeat_penalty=1.1, max_tokens=80)
            source_label = "DICTÉE (ASR)" if prefer_dictee else "TRANSCRIPTION"
            retry_prompt = (
                prompt_final
                + "\n\nCORRECTION OBLIGATOIRE.\n"
                + "La sortie précédente est invalide.\n"
                + "Retourne UNIQUEMENT un seul JSON strict sur une seule ligne : {\"texte\":\"...\"}\n"
                + "Contraintes du libellé :\n"
                + "- libellé de photo factuel, concret, en une seule ligne ;\n"
                + "- 5 à 15 mots ;\n"
                + "- 120 caractères maximum ;\n"
                + "- aucun préambule ;\n"
                + "- aucun texte de support, dépannage, connexion internet, redémarrage, réparation, erreur technique ;\n"
                + "- ne pas reprendre de message système ou de consigne technique.\n"
                + "Sinon : {}"
            )

            # --- tokens du retry_prompt (PASS2) ---
            try:
                prompt_tokens2 = len(llm.tokenize(retry_prompt.encode("utf-8", "ignore")))
            except Exception:
                prompt_tokens2 = max(1, len(retry_prompt) // 4)

            n_ctx2 = int(eff.get("n_ctx", N_CTX))  # eff contient le n_ctx réel
            budget2 = max(n_ctx2 - prompt_tokens2 - local_marge, DEFAULT_LOCAL_MARGE_TOKENS)

            # clamp max_tokens PASS2 (évite tronquage JSON)
            mt_wanted = int(safe_gen_retry.get("max_tokens", 180))
            mt_final = min(mt_wanted, budget2)
            safe_gen_retry["max_tokens"] = mt_final

            app.logger.info(
                "[ANNOTER][%s] PASS2 budgets: prompt_tokens2=%d n_ctx=%d marge=%d budget2=%d max_tokens(wanted)=%d -> %d",
                rid, prompt_tokens2, n_ctx2, local_marge, budget2, mt_wanted, mt_final
            )
            app.logger.info(
                "[ANNOTER][%s] PASS2 gen: max_tokens=%s temp=%s top_p=%s repeat_penalty=%s",
                rid,
                safe_gen_retry.get("max_tokens"),
                safe_gen_retry.get("temperature"),
                safe_gen_retry.get("top_p"),
                safe_gen_retry.get("repeat_penalty"),
            )

            with LLM_GEN_LOCK:
                rep2 = llm(retry_prompt, **safe_gen_retry)
            raw2 = ((rep2["choices"][0]["text"]) or "").strip()
            texte2, errs2 = parse_json(raw2)
            hard2, soft2 = split_libelle_errors(errs2)
            errs2 = hard2

            # ✅ dump/log en cas d’échec PASS2 (équivalent PASS1)
            if errs2:
                app.logger.warning("[ANNOTER][%s] PASS2_FAIL raw2_len=%d head=%r tail=%r",
                                rid, len(raw2), raw2[:220], raw2[-220:])
                try:
                    p = Path("logs_bad_json"); p.mkdir(exist_ok=True)
                    (p / f"{rid}_pass2_libelle.txt").write_text(raw2, encoding="utf-8", errors="ignore")
                except Exception:
                    pass

            _stats_pass2(errs2, t0)

            ok = (not errs2)
            app.logger.info("[ANNOTER][%s] RETURN 200 ok=%s", rid, ok)
            
            return _return_ok(texte2, rid, warnings=soft2) if not errs2 else _return_fail(errs2, rid, warnings=soft2)
        

        if tname == "commentaire":
            safe_gen_retry = dict(safe_gen, temperature=0.0, top_p=1.0, repeat_penalty=1.08, max_tokens=220)

            anchor_tr = "La dictée mentionne" if prefer_dictee else "La transcription mentionne"
            anchor_vlm = "Selon la description visuelle"

            retry_prompt = (
                prompt_final
                + "\n\nCORRECTION OBLIGATOIRE.\n"
                + "La sortie précédente ne respectait pas la structure.\n"
                + "Produire UNIQUEMENT : {\"texte\":\"...\"}\n"
                + "3 phrases EXACTEMENT.\n"
                + "Phrase 1 : visible photo uniquement.\n"
                + f"Phrase 2 : commence STRICTEMENT par \"{anchor_vlm}\".\n"
                + f"Phrase 3 : commence STRICTEMENT par \"{anchor_tr}\".\n"
                + "Une seule ligne. ≤ 350 caractères.\n"
                + "Aucune explication.\n"
            )
        

            # --- tokens du retry_prompt (PASS2) ---
            try:
                prompt_tokens2 = len(llm.tokenize(retry_prompt.encode("utf-8", "ignore")))
            except Exception:
                prompt_tokens2 = max(1, len(retry_prompt) // 4)

            n_ctx2 = int(eff.get("n_ctx", N_CTX))  # eff contient le n_ctx réel
            budget2 = max(n_ctx2 - prompt_tokens2 - local_marge, DEFAULT_LOCAL_MARGE_TOKENS)

            # clamp max_tokens PASS2 (évite tronquage JSON)
            mt_wanted = int(safe_gen_retry.get("max_tokens", 180))
            mt_final = min(mt_wanted, budget2)
            safe_gen_retry["max_tokens"] = mt_final

            app.logger.info(
                "[ANNOTER][%s] PASS2 budgets: prompt_tokens2=%d n_ctx=%d marge=%d budget2=%d max_tokens(wanted)=%d -> %d",
                rid, prompt_tokens2, n_ctx2, local_marge, budget2, mt_wanted, mt_final
            )
            app.logger.info(
                "[ANNOTER][%s] PASS2 gen: max_tokens=%s temp=%s top_p=%s repeat_penalty=%s",
                rid,
                safe_gen_retry.get("max_tokens"),
                safe_gen_retry.get("temperature"),
                safe_gen_retry.get("top_p"),
                safe_gen_retry.get("repeat_penalty"),
            )

            with LLM_GEN_LOCK:
                rep2 = llm(retry_prompt, **safe_gen_retry)

            raw2 = ((rep2["choices"][0]["text"]) or "").strip()
            texte2, errs2 = parse_json(raw2)

            # ✅ ajout : dump/log si PASS2 échoue encore
            if errs2:
                app.logger.warning("[ANNOTER][%s] PASS2_COMMENTAIRE_FAIL raw2_len=%d head=%r tail=%r",
                                rid, len(raw2), raw2[:220], raw2[-220:])
                try:
                    p = Path("logs_bad_json"); p.mkdir(exist_ok=True)
                    (p / f"{rid}_pass2_commentaire.txt").write_text(raw2, encoding="utf-8", errors="ignore")
                except Exception:
                    pass

            # Phase 3 : salvage JSON uniquement si json_incomplet
            if errs2 and "json_incomplet" in errs2:
                obj2 = extract_last_json_object(raw2)
                if isinstance(obj2, dict):
                    cand = (obj2.get("texte") or "").strip()
                    if cand:
                        errs2b = validate_text(cand)   # <- votre fonction locale
                        if not errs2b:
                            texte2, errs2 = cand, []   # salvage accepté (métier OK)
            
            # --- fin PASS2 : hard/soft gating ---
            salient = data.get("salient_families") or []
            hard2, soft2 = split_errors(errs2, salient)

            if soft2:
                app.logger.info("[ANNOTER][%s] PASS2 soft_errors=%s", rid, soft2)

            errs2 = hard2  # hard décide OK/FAIL

            _stats_pass2(errs2, t0)
            ok = (not errs2)
            app.logger.info("[ANNOTER][%s] RETURN 200 ok=%s", rid, ok)

            return _return_ok(texte2, rid, warnings=soft2) if not errs2 else _return_fail(errs2, rid, warnings=soft2)
                        
        # si tâche inconnue
        return _return_fail(errs1)

    except Exception as e:
        app.logger.exception("/annoter: erreur: %s", e)
        resp = jsonify({"error": str(e), "request_id": rid})
        resp.headers["X-Request-Id"] = rid
        return resp, 500

    finally:
        if busy_acquired:
            try:
                LLM_BUSY.release()
            except Exception:
                pass
        app.logger.info("[ANNOTER][%s] END dt=%.2fs", rid, time.time() - t0)


   

@app.route("/annoter_stats", methods=["GET"])
def annoter_stats():
    with ANNOTER_STATS_LOCK:
        lat = ANNOTER_STATS["lat_ms"][-500:]  # fenêtre glissante

        lat_sorted = sorted(lat)
        p50 = lat_sorted[len(lat_sorted)//2] if lat_sorted else None
        p95 = (
            lat_sorted[int(len(lat_sorted)*0.95)]
            if len(lat_sorted) >= 20 else None
        )

        return jsonify({
            "calls": ANNOTER_STATS["calls"],
            "ok_pass1": ANNOTER_STATS["ok_pass1"],
            "ok_pass2": ANNOTER_STATS["ok_pass2"],
            "fail": ANNOTER_STATS["fail"],
            "errs_pass1": dict(ANNOTER_STATS["errs_pass1"]),
            "errs_pass2": dict(ANNOTER_STATS["errs_pass2"]),
            "lat_ms_p50": p50,
            "lat_ms_p95": p95,
        }), 200



@app.route("/model_info", methods=["GET"])
def model_info():
    return jsonify({
        "model": DEFAULT_MODEL,          # ou CURRENT_MODEL_NAME si c’est la même chose
        "n_ctx": N_CTX,                  # valeur déjà calculée à partir de per_model_parameters
        "max_tokens": DEFAULT_LOCAL_MAX_TOKENS # facultatif mais très utile pour l'adapter
    })


@app.route("/annoter_segments", methods=["POST"])
def annoter_segments():
    if not is_authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Champ 'prompt' manquant"}), 400

    model_name = data.get("model_name") or data.get("model") or DEFAULT_LLM
    if model_name not in KNOWN_LLMS:
        model_name = DEFAULT_LLM

    # system + éventuel historique (comme /annoter)
    system_prompt = data.get("system", get_system_prompt())
    history = data.get("history") or data.get("messages") or []
    history_text = ""
 
    try:
        if isinstance(history, list):
            parts = []
            for h in history:
                if isinstance(h, dict):
                    parts.append(str(h.get("content", "")))
                else:
                    parts.append(str(h))
            history_text = "\n".join([p for p in parts if p])
    except Exception:
        history_text = ""

    prompt_final = f"{system_prompt}\n"
    if history_text:
        prompt_final += f"{history_text}\n"
    prompt_final += prompt

    # --- Paramètres effectifs (comme /annoter) ---
    eff = effective_params(model_name, overrides=generation_params)
    try:
        prompt_tokens = len(llm.tokenize(prompt_final.encode("utf-8", "ignore")))
    except Exception:
        prompt_tokens = max(1, len(prompt_final) // 4)

    # marge & min_prompt_tokens : peuvent venir de la requête OU du config.json
    marge = int(data.get("marge") or eff.get("marge") or DEFAULT_LOCAL_MARGE_TOKENS)
    min_prompt_tokens = int(
        data.get("min_prompt_tokens")
        or eff.get("min_prompt_tokens")
        or DEFAULT_LOCAL_MIN_PROMPT_TOKENS
    )

    eff = clamp_max_tokens(eff, prompt_tokens=prompt_tokens, safety=marge)

    n_ctx      = int(eff.get("n_ctx", N_CTX))
    max_tokens = int(eff.get("max_tokens", DEFAULT_LOCAL_MAX_TOKENS))
    available  = max(n_ctx - max_tokens - marge, min_prompt_tokens)

    # --- TRONCATURE ROBUSTE ET PROPORTIONNELLE ---
    orig_prompt_tokens   = prompt_tokens
    budget_prompt_tokens = available

    if prompt_tokens > budget_prompt_tokens:
        # ratio à conserver
        frac = budget_prompt_tokens / float(prompt_tokens)

        # proportion de caractères correspondante
        keep_chars = int(len(prompt_final) * frac)
        keep_chars = max(keep_chars, 256)  # jamais moins de contexte

        if keep_chars < len(prompt_final):
            prompt_final = prompt_final[-keep_chars:]

        # recalcul sur le prompt tronqué
        try:
            prompt_tokens = len(llm.tokenize(prompt_final.encode("utf-8", "ignore")))
        except Exception:
            prompt_tokens = max(1, len(prompt_final) // 4)

        app.logger.warning(
            "[annoter_segments] prompt tronqué: orig=%d, new=%d, budget=%d, n_ctx=%d, marge=%d",
            orig_prompt_tokens, prompt_tokens, budget_prompt_tokens, n_ctx, marge
        )

        # garde-fou final : impossible de dépasser n_ctx
        if prompt_tokens >= n_ctx:
            msg = (
                f"Prompt trop long après troncature: tokens={prompt_tokens}, "
                f"n_ctx={n_ctx}. Réduisez la transcription."
            )
            app.logger.error("[annoter_segments] " + msg)
            return jsonify({"error": msg}), 400

    # kwargs réels passés au LLM (on NE PASSE PAS marge / min_prompt_tokens)
    # Ajout d'une contrainte JSON-only côté serveur
    prompt_final += (
        "\n\nTu dois répondre UNIQUEMENT par un JSON strict conforme au schéma "
        "décrit dans la demande, encadré entre <json> et </json>. "
        "Aucun texte explicatif, aucun exemple, aucun commentaire hors JSON."
    )
    gen = make_gen_kwargs(eff)           # ne contient que les clés supportées
    gen_for_llm = dict(gen)
    gen_for_llm.pop("marge", None)
    gen_for_llm.pop("min_prompt_tokens", None)

    #---------------------------------------------------------------
    try:
        maybe_switch_model(model_name)
        app.logger.info(
            "📨 /annoter_segments (%s) tokens_prompt=%d n_ctx=%s max_tokens=%s marge=%s",
            model_name, prompt_tokens, eff.get("n_ctx"), eff.get("max_tokens"), marge
        )

        # Appel LLM brut
        with BACKEND_LOCK:
            reponse = llm(prompt_final, **gen_for_llm)
        rep_str = reponse["choices"][0]["text"]
        raw_out = (rep_str or "").strip()

        # Protection en hauteur (évite les sorties monstrueuses)
        if len(raw_out) > 50000:
            raw_out = raw_out[:50000] + "…"


        # 1) Extraction + parsing JSON robustes, avec tentative de réparation
        parsed = None
        try:
            parsed = extract_json_from_llm(raw_out)
        except Exception:
            app.logger.warning("[annoter_segments] JSON invalide, tentative de réparation…")
            try:
                fixed_raw = repair_truncated_json(raw_out)
                parsed = extract_json_from_llm(fixed_raw)
                raw_out = fixed_raw  # optionnel : conserver la version réparée
            except Exception:
                app.logger.exception("[annoter_segments] Échec extraction JSON même après réparation")
                parsed = None


        # 2) Normalisation stricte du schéma Pass 1
        if parsed is not None:
            normalized = normalize_segment_annotation(parsed, raw_out=raw_out)
        else:
            # Fallback : JSON minimal, SANS injecter raw_out dans resume_segment
            normalized = {
                "resume_segment": "",
                "themes": [],
                "actions": [],
                "problems": [],
            }

        return jsonify(normalized)

    except Exception as e:
        app.logger.exception("/annoter_segments: erreur LLM / post-traitement: %s", e)
        return jsonify({"error": f"LLM error: {e}"}), 500


@app.route("/chat_llm", methods=["POST"])
def chat_llm():
    """Genere une reponse texte simple via le LLM local.

    Le payload peut fournir `prompt`, `model_name`, `system` et `lang`.
    La route construit le prompt final et retourne une reponse JSON de
    conversation compatible avec les clients existants.
    """
    if not is_authorized(request):
        return jsonify({"reponse": ""}), 401

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"reponse": ""})

    # --- modèle demandé ---
    model_name = data.get("model_name") or data.get("model") or DEFAULT_LLM

    # Optionnel mais fortement conseillé : éviter les noms inattendus
    # (tu as déjà ce pattern dans /annoter_rag) :contentReference[oaicite:2]{index=2}
    try:
        if "KNOWN_LLMS" in globals() and model_name not in KNOWN_LLMS:
            app.logger.warning(
                "⛔ Nom de modèle non reconnu '%s' -> DEFAULT_LLM='%s'",
                model_name, DEFAULT_LLM
            )
            model_name = DEFAULT_LLM
    except Exception:
        pass

    # --- system prompt ---
    # Priorité: payload -> fallback get_system_prompt() :contentReference[oaicite:3]{index=3}
    system_prompt = (
        (data.get("system") or data.get("system_prompt") or "").strip()
        or get_system_prompt()
    )

    # (Option) petite contrainte langue, sans écraser ton prompt principal
    # utile si certains SLM “dérivent”
    # --- langue cible (optionnelle) ---
    lang = (data.get("lang") or "").strip().lower()

    lang_rule = (
        f"Réponds en {lang}." if lang
        else "Réponds dans la langue du message utilisateur. Si tu ne peux pas l’identifier, réponds en français."
    )

    # Ajout de la règle sans écraser le prompt principal
    if lang_rule.lower() not in system_prompt.lower():
        system_prompt = system_prompt.rstrip() + "\n" + lang_rule


    # --- prompt final ---
    full_prompt = f"{system_prompt}\n\n{prompt}".strip()

    try:
        # 1) clamp max_tokens selon le budget de contexte (si helpers dispo)
        try:
            prompt_tokens = len(llm.tokenize(full_prompt.encode("utf-8", "ignore")))
        except Exception:
            prompt_tokens = max(1, len(full_prompt) // 4)

        requested_max_tokens = data.get("max_tokens")
        overrides = {}
        if requested_max_tokens is not None:
            try:
                overrides["max_tokens"] = int(requested_max_tokens)
            except Exception:
                app.logger.warning(
                    "chat_llm: max_tokens invalide (%r) ignore, fallback sur effective_params",
                    requested_max_tokens,
                )
        eff = effective_params(model_name, overrides=overrides or None)


        if "clamp_max_tokens" in globals():
            eff = clamp_max_tokens(eff, prompt_tokens=prompt_tokens, safety=256)



        # 2) kwargs de génération : ne garder que les clés supportées :contentReference[oaicite:5]{index=5}
        gen = make_gen_kwargs(eff)

        # stop tokens (cohérent avec generer_texte)
        gen.setdefault("stop", ["</s>", "[/INST]"])

        # 3) switch modèle + reset KV cache pour éviter l’effet “mémoire” inter-requêtes
        model_changed = maybe_switch_model(model_name)
        if model_changed:
            try:
                llm.reset()
            except Exception:
                pass

        # 4) génération
        with BACKEND_LOCK:
            answer_raw = llm(full_prompt, **gen)

        # Normalisation du retour
        if isinstance(answer_raw, dict):
            c0 = (answer_raw.get("choices") or [{}])[0]
            text = (c0.get("text") or c0.get("content") or "").strip()
        elif isinstance(answer_raw, str):
            text = answer_raw.strip()
        else:
            text = ""

        # Nettoyage minimal si tu as déjà ce helper
        if "_sanitize_llm_output" in globals():
            text = _sanitize_llm_output(text)


        if app.logger.isEnabledFor(logging.DEBUG):
            app.logger.debug(
                "chat_llm system_prompt (%d chars): %s",
                len(system_prompt),
                system_prompt[:200]
            )


        return jsonify({
            "reponse": text,
            "model": model_name,
            "used_params": {
                "temperature": gen.get("temperature"),
                "top_p": gen.get("top_p"),
                "top_k": gen.get("top_k"),
                "repeat_penalty": gen.get("repeat_penalty"),
                "max_tokens": gen.get("max_tokens"),
            }
        })


    except Exception as e:
        app.logger.exception("chat_llm error: %s", e)
        return jsonify({"reponse": f"Erreur: {e}"}), 500


@app.route("/annoter_rag", methods=["POST"])
def annoter_rag():
    """Produit une annotation enrichie par le contenu d'un dossier RAG.

    Le payload attend un `rag_dossier_pcfixe` et un `prompt`, avec les
    options de modele et de generation deja prises en charge. La route
    assemble le contexte documentaire avant de renvoyer la reponse JSON.
    """
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}
    if not data:
        app.logger.warning("%s: JSON vide/non décodable", request.path)
    dossier = data.get("rag_dossier_pcfixe")
    if not dossier:
        return jsonify({"error": "Champ 'rag_dossier_pcfixe' manquant"}), 400
    if not Path(dossier).exists():
        return jsonify({"error": f"Dossier RAG introuvable : {dossier}"}), 404

    prompt = data.get("prompt", "")
    model_name = data.get("model_name") or data.get("model") or DEFAULT_LLM
    # 🔒 Patch anti-switch accidentel
    if model_name not in KNOWN_LLMS:
        app.logger.warning("⛔ Nom de modèle non reconnu '%s' -> DEFAULT_LLM='%s'", model_name, DEFAULT_LLM)
        model_name = DEFAULT_LLM
    system_prompt = data.get("system", get_system_prompt())

    generation_params = {
        k: data.get(k, PARAMS.get(k))
        for k in ["temperature", "top_p", "top_k", "repeat_penalty", "max_tokens"]
    }
    eff = effective_params(model_name)
    prompt_final_preview = f"{system_prompt}\n{prompt}"  # preview courte si extraire_contenu_rag est lourd
    try:
        # si ton llm a .tokenize, on anticipe le budget
        ptok = len(llm.tokenize(prompt_final_preview.encode("utf-8", "ignore")))
    except Exception:
        ptok = max(1, len(prompt_final_preview)//4)

    eff = clamp_max_tokens(eff, prompt_tokens=ptok, safety=256)
    gen = make_gen_kwargs(eff)
    try:
        maybe_switch_model(model_name)
        contenu_rag = extraire_contenu_rag(dossier)
        include_qa = bool(data.get("include_qa_logs", False))
        qa_ctx = ""
        if include_qa:
            try:
                # réutilise la même résolution de projet
                root = str(Path(dossier).resolve())  # dossier RAG_PC
                proj_root = root if Path(root).name.upper() != "RAG_PC" else str(Path(root).parent)
                cfg = _load_project_config_for_server(_find_project(data.get("project_id",""), _load_projects_index()) or {})
                subs = _effective_subdirs(cfg) if cfg else DEFAULT_SUBDIRS
                logs_dir = _qa_logs_dir(proj_root, rag_pc_subdir=subs.get("rag_pc_subdir","RAG_PC"))
                recent = []
                for month_dir in sorted(logs_dir.glob("*"), reverse=True):
                    for f in sorted(month_dir.glob("qa_*.jsonl"), reverse=True):
                        with open(f, "r", encoding="utf-8") as r:
                            recent.extend([json.loads(x) for x in r.readlines()[-5:]])
                        if len(recent) >= 10:
                            break
                    if len(recent) >= 10:
                        break
                # formatage bref
                recent = sorted(recent, key=lambda x: x.get("ts", 0), reverse=True)[:10]
                qa_ctx = "\n\n".join([f"Q: {q.get('prompt','')}\nA: {q.get('reponse','')}" for q in recent])
            except Exception as e:
                qa_ctx = ""
        prompt_final = f"{system_prompt}\n{qa_ctx}\n{contenu_rag}\n{prompt}"
        app.logger.info("📨 /annoter_rag (%s) prompt[100]: %r", model_name, prompt[:100])
        with BACKEND_LOCK:
            reponse = llm(prompt_final, **gen)
        text = reponse["choices"][0]["text"]

        if not data.get("do_not_log", False):
            log_appel({
                "route": "annoter_rag",
                "prompt": prompt,
                "reponse": text,
                "model_name": model_name,
                "rag": dossier,
                "gen": gen
            })
        return jsonify({"reponse": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def _to_bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1","true","yes","y","on"): return True
        if s in ("0","false","no","n","off"): return False
    return default

@app.route("/annoter_rag_vecteur", methods=["POST"])
def annoter_rag_vecteur():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    data = request.get_json(silent=True) or {}

    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt vide"}), 400

    model_name = data.get("model_name") or data.get("model") or DEFAULT_LLM
    if model_name not in KNOWN_LLMS:
        model_name = DEFAULT_LLM

    k           = int(data.get("top_k", 5))
    vec_backend = (data.get("vec_backend") or "chroma").lower()
    chroma_dir  = data.get("chroma_dir")
    qdrant_url  = data.get("qdrant_url")
    qdrant_key  = data.get("qdrant_api_key")
    collection  = data.get("collection") or "default_collection"
    max_chars   = int(data.get("max_total_chars") or 6000)
    show_dist   = _to_bool(data.get("show_distances"), False)
    anonymize   = _to_bool(data.get("anonymize"), False)
    mode    = (data.get("mode") or "strict").lower()
    strict  = (mode != "fallback")
    filters = data.get("filters")

    include_qa = _to_bool(data.get("include_qa_logs"), False)
    qa_limit = int(data.get("qa_limit") or 30)
    qa_last_lines_per_file = int(data.get("qa_last_lines_per_file") or 5)
    project_id = (data.get("project_id") or "").strip()

    ctx, sources = build_rag_context_store(
        query=prompt,
        collection_name=collection,
        vec_backend=vec_backend,
        chroma_dir=chroma_dir,
        k=k,
        show_distances=show_dist,
        max_total_chars=max_chars,
        filters=filters,        # ✅ AJOUT
        strict=strict,          # ✅ AJOUT
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_key,
    )
    if include_qa and project_id:
        qa_items = _load_recent_qa_items(project_id, limit=qa_limit)
        qa_ctx = build_qa_ctx_professional(qa_items)

        if qa_ctx:
            ctx = qa_ctx + "\n\n" + ctx
   
    max_chars = int(data.get("max_total_chars") or 6000)
    if max_chars > 0 and len(ctx) > max_chars:
        ctx = ctx[:max_chars].rstrip() + "…"


    system_prompt = ((data.get("system") or data.get("system_prompt") or "").strip() or get_system_prompt())
    lang = (data.get("lang") or "").strip().lower()

    lang_rule = (
        f"Réponds en {lang}."
        if lang
        else "Réponds dans la langue du message utilisateur. Si tu ne peux pas l’identifier, réponds en français."
    )

    internal_rule = "Ne jamais reproduire textuellement les éléments marqués comme CONTEXTE INTERNE."

    if lang_rule.lower() not in system_prompt.lower():
        system_prompt = system_prompt.rstrip() + "\n" + lang_rule

    if internal_rule.lower() not in system_prompt.lower():
        system_prompt = system_prompt.rstrip() + "\n" + internal_rule

    try:
        model_changed = maybe_switch_model(model_name)
        if model_changed:
            try:
                llm.reset()
            except Exception:
                pass

        eff = effective_params(model_name, overrides=data)

        # IMPORTANT : build_full_prompt doit accepter max_new_tokens (voir § ci-dessous)
        core_prompt = build_full_prompt(prompt, ctx, max_new_tokens=eff.get("max_tokens"))
        full_prompt = f"{system_prompt}\n\n{core_prompt}".strip()

        try:
            prompt_tokens = len(llm.tokenize(full_prompt.encode("utf-8", "ignore")))
        except Exception:
            prompt_tokens = max(1, len(full_prompt) // 4)

        if "clamp_max_tokens" in globals():
            old_max = eff.get("max_tokens")
            eff2 = clamp_max_tokens(eff, prompt_tokens=prompt_tokens, safety=256)
            eff = eff2
            if eff.get("max_tokens") != old_max:
                core_prompt = build_full_prompt(prompt, ctx, max_new_tokens=eff.get("max_tokens"))
                full_prompt = f"{system_prompt}\n\n{core_prompt}".strip()

        gen = make_gen_kwargs(eff)
        gen.setdefault("stop", ["</s>", "[/INST]"])

        with BACKEND_LOCK:
            out = llm(full_prompt, **gen)
        c0 = (out.get("choices") or [{}])[0]
        text = (c0.get("text") or c0.get("content") or "").strip()

        return jsonify({
            "reponse": text,
            "model": model_name,
            "used_params": {
                "temperature": gen.get("temperature"),
                "top_p": gen.get("top_p"),
                "top_k": gen.get("top_k"),
                "repeat_penalty": gen.get("repeat_penalty"),
                "max_tokens": gen.get("max_tokens"),
            },
            "context_len": len(ctx),
            "sources": sources,
            "anonymized": anonymize
        })

    except Exception as e:
        app.logger.exception("annoter_rag_vecteur error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/vector/upsert_csv_dir", methods=["POST"])
def vector_upsert_csv_dir():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}

    collection  = (data.get("collection") or "").strip()
    csv_dir     = (data.get("csv_dir") or "").strip()
    vec_backend = (data.get("vec_backend") or data.get("backend") or "qdrant").lower()
    model_name  = data.get("embed_model") or data.get("model_name") or data.get("model") or "BGE-M3"
    project_id  = (data.get("project_id") or "").strip() or None

    # Qdrant
    qdrant_url = (data.get("qdrant_url") or "").strip()
    if not qdrant_url:
        qdrant_url = (os.getenv("QDRANT_URL") or "").strip()  # si vous l’avez
    qdrant_url = qdrant_url or None

    qdrant_key = (data.get("qdrant_api_key") or "").strip()
    if not qdrant_key:
        qdrant_key = (os.getenv("QDRANT_API_KEY") or "").strip()
    qdrant_key = qdrant_key or None

    if not collection:
        return jsonify({"error": "collection required"}), 400
    if not csv_dir:
        return jsonify({"error": "csv_dir required"}), 400
    if vec_backend != "qdrant":
        return jsonify({"error": "vec_backend must be 'qdrant'"}), 400

    try:
        # NB: si rag_vector_utils.py ne supporte pas encore qdrant_api_key,
        # il faudra l’ajouter à ses fonctions (paramètre transmis au client Qdrant).
        upsert_csv_folder_into_store(
            csv_dir=csv_dir,
            collection_name=collection,
            vec_backend="qdrant",
            model_name=model_name,
            project_id=project_id,
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_key,   # <- à supporter dans rag_vector_utils.py si pas déjà le cas
        )

        return jsonify({
            "status": "ok",
            "collection": collection,
            "vec_backend": "qdrant",
            "embed_model": model_name,
            "csv_dir": csv_dir
        })

    except Exception as e:
        app.logger.exception("vector_upsert_csv_dir error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route("/vector/search", methods=["POST"])
def vector_search():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}

    collection  = (data.get("collection") or "").strip()
    query_text  = (data.get("query_text") or data.get("query") or "").strip()
    k           = int(data.get("top_k") or data.get("k") or 10)

    vec_backend = (data.get("vec_backend") or data.get("backend") or "qdrant").lower()
    model_name  = data.get("embed_model") or data.get("model_name") or data.get("model") or "BGE-M3"

    qdrant_url = (data.get("qdrant_url") or "").strip()
    if not qdrant_url:
        qdrant_url = (os.getenv("QDRANT_URL") or "").strip()  # si vous l’avez
    qdrant_url = qdrant_url or None


    qdrant_key = (data.get("qdrant_api_key") or "").strip()
    if not qdrant_key:
        qdrant_key = (os.getenv("QDRANT_API_KEY") or "").strip()
    qdrant_key = qdrant_key or None

    filters     = data.get("filters")  # optionnel, si votre retrieve_top_k_store le supporte

    if not collection:
        return jsonify({"error": "collection required"}), 400
    if not query_text:
        return jsonify({"error": "query_text vide"}), 400
    if vec_backend != "qdrant":
        return jsonify({"error": "vec_backend must be 'qdrant'"}), 400

    try:
        docs, metas, scores = retrieve_top_k_store(
            query=query_text,
            collection_name=collection,
            vec_backend="qdrant",
            k=k,
            model_name=model_name,
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_key,  # <- à supporter dans rag_vector_utils.py si pas déjà le cas
            filters=filters,            # <- idem
        )

        results = []
        for i in range(min(len(docs), len(metas), len(scores))):
            # Convention : `line` porte le photo_id (ex. P1060264.JPG) dans vos CSV d’index.
            photo_id = None
            if isinstance(metas[i], dict):
                photo_id = metas[i].get("line") or metas[i].get("photo_id")

            results.append({
                "id": photo_id,
                "score": float(scores[i]),
                "metadata": metas[i]
            })

        return jsonify({
            "status": "ok",
            "collection": collection,
            "vec_backend": "qdrant",
            "embed_model": model_name,
            "top_k": k,
            "results": results
        })

    except Exception as e:
        app.logger.exception("vector_search error: %s", e)
        return jsonify({"error": str(e)}), 500



@app.route("/annoter_rag_memoire", methods=["POST"])
def annoter_rag_memoire():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}

    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt vide"}), 400

    # --- modèle demandé ---
    model_name = (data.get("model_name") or data.get("model") or DEFAULT_LLM).strip()
    if model_name not in KNOWN_LLMS:
        model_name = DEFAULT_LLM
#-------------------------------------------

    # --- Scoping mémoire strict : api_key + app_id + conversation_id ---
    api_key = request.headers.get("x-api-key", "anon")

    app_id = (
        request.headers.get("x-app-id")
        or data.get("app_id")
        or "default_app"
    )
    conversation_id = (
        request.headers.get("x-conversation-id")
        or request.headers.get("x-openwebui-chat-id")          # <-- AJOUT
        or request.headers.get("x-openwebui-conversation-id")  # <-- AJOUT (selon versions)
        or data.get("conversation_id")
        or data.get("chat_id")
        or data.get("thread_id")
        or ""
    ).strip()
    app.logger.info(
        "[memoire] x-app-id=%r x-conv-id=%r x-ow-chat-id=%r data_conv=%r",
        request.headers.get("x-app-id"),
        request.headers.get("x-conversation-id"),
        request.headers.get("x-openwebui-chat-id"),
        data.get("conversation_id") or data.get("chat_id") or data.get("thread_id"),
    )


    if not conversation_id:
        mem_coll = None  # mémoire désactivée (strict)
    else:
        scope = f"{api_key}|{app_id}|{conversation_id}"
        mem_hash = sha256(scope.encode("utf-8")).hexdigest()[:16]
        mem_coll = _safe_coll_name(f"memoire_chat_{mem_hash}")  # pas besoin de : (Chroma l'interdit)

    top_k_mem = int(data.get("top_k", 4))

    # --- Alimentation mémoire ---
    docs = []

    # 1) si un adapter fournit explicitement memory_append, on l'utilise
    memory_append = data.get("memory_append")
    if memory_append:
        docs.append(memory_append)

    # 2) sinon, si OpenWebUI envoie des messages, on fabrique un append
    if not docs:
        messages = data.get("messages") or []
        n_turns = int(data.get("memory_turns") or data.get("n_turns") or 8)
        if messages:
            mem = build_memory_append(messages, n_turns=n_turns)
            if mem:
                docs.append(mem)

    # --- Build context mémoire ---
    ctx = ""
    if mem_coll:
        ctx = build_mem_ctx(
            collection=mem_coll,
            documents=docs,
            query=prompt,
            top_k=top_k_mem,
        )

#-------------------------------------------

    # --- system prompt + règle de langue ---
    system_prompt = ((data.get("system") or data.get("system_prompt") or "").strip() or get_system_prompt())
    lang = (data.get("lang") or "").strip().lower()
    lang_rule = (
        f"Réponds en {lang}." if lang
        else "Réponds dans la langue du message utilisateur. Si tu ne peux pas l’identifier, réponds en français."
    )
    if lang_rule.lower() not in system_prompt.lower():
        system_prompt = system_prompt.rstrip() + "\n" + lang_rule

    try:
        app.logger.info(
            "annoter_rag_memoire model_name=%r data.model=%r data.model_name=%r conv=%r app_id=%r mem_coll=%r",
            model_name,
            data.get("model"),
            data.get("model_name"),
            conversation_id,
            app_id,
            mem_coll,
        )
                
        # --- switch modèle + endpoint stateless ---
        model_changed = maybe_switch_model(model_name)
        if model_changed:
            try:
                llm.reset()
            except Exception:
                pass

        # --- paramètres effectifs ---
        eff = effective_params(model_name, overrides=data)

        # prompt "métier" (mémoire + consignes RAG) sans règles système
        core_prompt = build_full_prompt(prompt, ctx, max_new_tokens=eff.get("max_tokens"))
        full_prompt = f"{system_prompt}\n\n{core_prompt}".strip()

        # clamp max_tokens selon budget de contexte (si helper dispo)
        try:
            prompt_tokens = len(llm.tokenize(full_prompt.encode("utf-8", "ignore")))
        except Exception:
            prompt_tokens = max(1, len(full_prompt) // 4)

        if "clamp_max_tokens" in globals():
            old_max = eff.get("max_tokens")
            eff = clamp_max_tokens(eff, prompt_tokens=prompt_tokens, safety=256)

            # si clamp a modifié max_tokens, rebuild prompt avec le nouveau budget
            if eff.get("max_tokens") != old_max:
                core_prompt = build_full_prompt(prompt, ctx, max_new_tokens=eff.get("max_tokens"))
                full_prompt = f"{system_prompt}\n\n{core_prompt}".strip()

        gen = make_gen_kwargs(eff)
        gen.setdefault("stop", ["</s>", "[/INST]"])
        with BACKEND_LOCK:
            out = llm(full_prompt, **gen)

        # normalisation du retour
        if isinstance(out, dict):
            c0 = (out.get("choices") or [{}])[0]
            text = (c0.get("text") or c0.get("content") or "").strip()
        elif isinstance(out, str):
            text = out.strip()
        else:
            text = ""

        if "_sanitize_llm_output" in globals():
            text = _sanitize_llm_output(text)

        return jsonify({
            "reponse": text,
            "model": model_name,
            "used_params": {
                "temperature": gen.get("temperature"),
                "top_p": gen.get("top_p"),
                "top_k": gen.get("top_k"),
                "repeat_penalty": gen.get("repeat_penalty"),
                "max_tokens": gen.get("max_tokens"),
            },
            "context_len": len(ctx),
            "memory_collection": mem_coll,
            "memory_scoping": ("api_key+app_id+conversation_id" if mem_coll else "disabled_no_conversation_id"),
        })

    except Exception as e:
        app.logger.exception("annoter_rag_memoire error: %s", e)
        return jsonify({"error": str(e)}), 500



#**************************************************************
@app.route("/annoter_web", methods=["POST"])
def annoter_web():
    """Produit une annotation enrichie par recherche ou scraping web.

    Le payload peut inclure `prompt`, `web` et `web_context`. Selon la
    configuration deja supportee, la route collecte le contexte web utile
    puis renvoie la synthese JSON sans changer le contrat existant.
    """
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    # -------- 1) Lecture + defaults robustes --------
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = {}

    prompt     = (data.get("prompt") or "").strip()
    model_name = data.get("model_name") or data.get("model") or DEFAULT_LLM
    if model_name not in KNOWN_LLMS:
        app.logger.warning("⛔ Nom de modèle non reconnu '%s' -> DEFAULT_LLM='%s'", model_name, DEFAULT_LLM)
        model_name = DEFAULT_LLM

    web_cfg     = data.get("web") or {}
    direct_ctx  = (data.get("web_context") or "").strip()

    scrape        = bool(web_cfg.get("scrape"))
    premium       = bool(web_cfg.get("premium"))
    max_depth     = int(web_cfg.get("max_depth") or 0)
    download_html = bool(web_cfg.get("download_html"))
    headers       = web_cfg.get("headers") if isinstance(web_cfg.get("headers"), dict) else {}
    cookies       = web_cfg.get("cookies")
    user_agent    = (headers.get("User-Agent") if headers else None) or web_cfg.get("user_agent") or "NTU-WebAgent/1.1"
    rate_limit    = web_cfg.get("rate_limit")
    try:
        rate_limit = int(rate_limit) if rate_limit is not None else 5
    except Exception:
        rate_limit = 5

    query_or_url  = web_cfg.get("query_or_url") or web_cfg.get("query")
    has_scrape    = bool(scrape and query_or_url)

    allowed_domains   = _normalize_domains(web_cfg.get("allowed_domains"))
    disallow_patterns = web_cfg.get("disallow_patterns") or []

    limit_sources     = int(web_cfg.get("limit_sources") or 8)
    dedupe_sources    = bool(web_cfg.get("dedupe_sources", True))
    return_web_context= bool(web_cfg.get("return_web_context", False))
    save_to_rag_pc    = bool(web_cfg.get("save_to_rag_pc", False))

    if not (prompt or direct_ctx or has_scrape):
        return jsonify({"error": "payload incomplet: fournir 'prompt' et/ou 'web' avec 'scrape' + 'query_or_url'."}), 400

    # -------- 2) Scrape (si demandé) --------
    pages = []
    if has_scrape:
        try:
            if premium:
                import web_scraper_premium as wsp
                if not query_or_url.startswith(("http://", "https://")):
                    return jsonify({"error": "premium=true nécessite une URL directe (http/https)"}), 400
                pages = wsp.scrape_url_premium(
                    url=query_or_url,
                    max_depth=max_depth,
                    rate_limit=rate_limit,
                    user_agent=user_agent,
                    allowed_domains=allowed_domains,
                    disallow_patterns=disallow_patterns,
                    cookies=cookies,
                    headers=headers,
                    download_html=download_html,
                    project=(data.get("project_id") or "default"),
                )
            else:
                import web_scraper as ws
                if not query_or_url.startswith(("http://", "https://")):
                    from web_search_utils import crawl_search
                    seeds = crawl_search(
                        query=query_or_url,
                        max_hosts=int(web_cfg.get("max_hosts") or 5),
                        max_pages=int(web_cfg.get("max_pages") or 10),
                        timeout_s=float(web_cfg.get("timeout_s") or 20),
                        max_results_seed=int(web_cfg.get("max_results_seed") or 15),
                    )
                    for seed in seeds[: min(len(seeds), 8)]:
                        try:
                            sub = ws.scrape_url(
                                url=seed["url"],
                                max_depth=0,
                                download_html=download_html,
                                user_agent=user_agent,
                                allowed_domains=allowed_domains or None,
                                disallow_patterns=disallow_patterns or None,
                                rate_limit=rate_limit or None
                            )
                            if isinstance(sub, list):
                                pages.extend(sub)
                        except Exception:
                            continue
                else:
                    pages = ws.scrape_url(
                        url=query_or_url,
                        max_depth=max_depth,
                        download_html=download_html,
                        user_agent=user_agent,
                        allowed_domains=allowed_domains or None,
                        disallow_patterns=disallow_patterns or None,
                        rate_limit=rate_limit or None
                    )
        except Exception as e:
            app.logger.exception("/annoter_web: échec scraping: %s", e)

    pages = pages or []
    if pages and (allowed_domains or disallow_patterns):
        pages = _apply_post_filters(pages, allowed_domains, disallow_patterns)

    # -------- 3) Normalisation / Dédoublonnage sources --------
    normed = []
    seen = set()
    for i, p in enumerate(pages):
        url = (p.get("url") or "").strip()
        if not url:
            continue
        key = _norm_url_for_dedupe(url) if dedupe_sources else url
        if dedupe_sources and key in seen:
            continue
        seen.add(key)
        title = (p.get("title") or p.get("og_title") or "").strip()[:300]
        snippet = (p.get("snippet") or p.get("text_preview") or (p.get("text") or "")[:300]).strip()
        published_at = p.get("published_at") or p.get("date")
        try:
            published_at = str(published_at) if published_at is not None else None
        except Exception:
            published_at = None
        score = p.get("score") or p.get("rank") or (1.0 / (i + 1))
        site  = ""
        try:
            site = urlparse(url).netloc.lower()
        except Exception:
            pass
        author = (p.get("author") or "").strip() or None
        normed.append({
            "url": url,
            "url_norm": key,
            "title": title,
            "snippet": snippet,
            "published_at": published_at,
            "score": float(score),
            "author": author,
            "site": site
        })
        

    # Expose: all sources (capped), and a compact top-k "used_sources"

    sources = normed[:limit_sources]
    # si _take_top_k ne trie pas, on sécurise:
    used_sources = sorted(sources, key=lambda s: s.get("score", 0.0), reverse=True)[:min(limit_sources, 5)]
    
    citations    = _mk_citation_list(used_sources)
    

    # -------- 4) Contexte web + prompt complet --------
    scraped_ctx = "\n\n---\n\n".join(
        (p.get("text") or p.get("snippet") or "").strip()
        for p in pages if (p.get("text") or p.get("snippet"))
    )
    web_context = f"{scraped_ctx}\n\n====\n\n{direct_ctx}" if (direct_ctx and scraped_ctx) else (scraped_ctx or direct_ctx)
    
    sys_prompt = get_system_prompt()
    sys_prompt = _inject_citation_instruction(sys_prompt, citations)
    full_prompt = f"{sys_prompt}\n\n{build_full_prompt(prompt, web_context)}".strip()


    # -------- 5) Génération robuste (stateless + budget) --------
    eff = effective_params(model_name, overrides=data)
    try:
        prompt_tokens = len(llm.tokenize(full_prompt.encode("utf-8", "ignore")))
    except Exception:
        prompt_tokens = max(1, len(full_prompt) // 4)
    eff = clamp_max_tokens(eff, prompt_tokens=prompt_tokens, safety=256)

    # 1) Construire les kwargs puis purger les clés non supportées
    gen = make_gen_kwargs(eff)

    UNSUPPORTED = {"cache_prompt", "prompt_cache", "use_cache"}
    for k in list(gen.keys()):
        if k in UNSUPPORTED:
            gen.pop(k, None)

    ALLOWED = {
        "max_tokens", "temperature", "top_p", "top_k",
        "repeat_penalty", "stop", "echo",
        "presence_penalty", "frequency_penalty",
    }
    gen = {k: v for k, v in gen.items() if k in ALLOWED}

    # 2) Ajuster température AVANT génération seulement si aucun contexte (ni web, ni direct, ni RAG)
    no_sources = (len(sources) == 0)
    rag_active = bool(data.get("rag_context") or data.get("rag_vector") or data.get("memoire_context"))
    has_any_context = (not no_sources) or bool(direct_ctx) or rag_active
    if not has_any_context:
        gen["temperature"] = min(0.2, float(gen.get("temperature", 0.4)))

    # 3) Reset KV-cache pour un mode stateless, puis génération (un seul appel)
    maybe_switch_model(model_name)
    try:
        llm.reset()
    except Exception:
        pass

    try:
        with BACKEND_LOCK:
           answer_raw = llm(full_prompt, **gen)

        # Normalisation du retour
        answer = ""
        if isinstance(answer_raw, dict):
            c0 = (answer_raw.get("choices") or [{}])[0]
            answer = (c0.get("text") or c0.get("content") or "").strip()
        elif isinstance(answer_raw, str):
            answer = answer_raw.strip()
        else:
            answer = ""

        # Nettoyage / garde-fous
        answer = _sanitize_llm_output(answer, has_citations=bool(citations))
        
        # --- tentative d'extraction JSON robuste, sans jamais faire planter la route ---
        parsed_json = None
        try:
            parsed_json = extract_json_from_llm(answer)
        except Exception:
            app.logger.exception("/annoter_web: échec extraction JSON")


        # Fallback #1 : extractif si trop court
        if not answer or len(answer) < 5:
            ctx_tail = (web_context or "")[-6000:]
            extractive_prompt = (
                "À partir UNIQUEMENT du CONTEXTE ci-dessous, fournis 5 puces factuelles et concises.\n"
                "Pas d'opinion. Cite des éléments concrets.\n"
                "[CONTEXTE]\n" + ctx_tail + "\n\n[INSTRUCTION]\n"
                "Donne 5 puces en français, 1 ligne chacune."
            )
            fp2 = f"{sys_prompt}\n\n{build_full_prompt(extractive_prompt, None)}".strip()
            with BACKEND_LOCK:
                ar2 = llm(fp2, **{**gen, "temperature": 0.2, "top_p": 0.9,
                                "max_tokens": min(400, gen.get("max_tokens", 256) + 144)})
            if isinstance(ar2, dict):
                c02 = (ar2.get("choices") or [{}])[0]
                answer = (c02.get("text") or c02.get("content") or "").strip()
            elif isinstance(ar2, str):
                answer = ar2.strip()

        # Fallback #2 : heuristique brute si toujours vide
        if not answer or len(answer) < 5:

            txt = (web_context or "")
            sentences = [_s.strip() for _s in _re.split(r"(?<=[\.\!\?])\s+", txt) if len(_s.strip()) > 40]
            head = sentences[:5] if sentences else [(txt or "")[:200]]
            answer = "- " + "\n- ".join([h[:240] for h in head if h])

        if not answer or not answer.strip():
            answer = "Je n’ai pas trouvé d’éléments exploitables dans le contexte fourni."

    except Exception as e:
        app.logger.exception("/annoter_web: génération LLM a échoué: %s", e)
        return jsonify({"error": f"génération échouée: {e}"}), 500
 

    # -------- 5bis) Mise en forme (citations / références) --------
    styles_req   = (data.get("citations") or {})
    inline_style = (styles_req.get("inline_style")  or "numeric").lower()   # 'numeric' | 'author-year'
    biblio_style = (styles_req.get("biblio_style")  or "numeric").lower()   # 'numeric' | 'harvard'
    add_section  = bool(styles_req.get("add_references_section", True))      # True par défaut

    if citations:  # ← seulement si on a des sources !
        answer_clean, _ = _postprocess_citations(answer, citations)
        answer_inline = _apply_inline_style(answer_clean, citations, inline_style)
        answer_html   = _to_html_with_links(answer_inline, citations)

        refs_txt, refs_html = _format_references(citations, biblio_style)
        section_title_txt   = "\n\nRéférences\n----------\n"
        section_title_html  = "<h3>Références</h3>"

        answer_with_refs_txt  = (answer_inline + section_title_txt + refs_txt) if add_section else answer_inline
        answer_with_refs_html = (answer_html  + section_title_html + refs_html) if add_section else answer_html
    else:
        # Pas de sources → on renvoie la réponse brute (pas de post-traitement)
        answer_inline        = answer or "(aucun contenu généré)"
        answer_html          = f"<p>{answer_inline}</p>"
        answer_with_refs_txt = answer_inline
        answer_with_refs_html= answer_html



    save_result = {
        "requested": save_to_rag_pc,
        "saved": False,
        "location": r"RAG_PC\\sources_web",
        "path": None,
        "dir": None,
        "meta_path": None,
    }
    if save_to_rag_pc:
        try:
            saved = _save_web_context_to_rag_pc(
                project_id=(data.get("project_id") or "").strip(),
                query_or_url=(query_or_url or ""),
                web_context=web_context,
                pages=pages,
                sources=sources,
            )
            save_result.update(saved)
        except Exception as e:
            save_result["error"] = str(e)
            app.logger.warning("/annoter_web: sauvegarde RAG_PC impossible: %s", e)

    # -------- 6) Logging + réponse --------
    try:
        log_appel({
            "route": "annoter_web",
            "prompt": prompt,
            "reponse": answer[:4000],
            "model_name": model_name,
            "gen": gen,
            "web_query": query_or_url,
            "pages_count": len(pages),
            "sources": [s["url"] for s in sources],
            "web_context": (web_context or "")[:6000],
        })
    except Exception:
        pass

    out = {
        "model": model_name,
        "gen": gen,
        "trace": {"prompt_tokens_est": prompt_tokens, "ctx_chars": len(web_context or "")},
        "pages_count": len(pages or []),
        "query_or_url": query_or_url,
        "sources": sources,            # liste complète (cappée)
        "used_sources": used_sources,  # sous-ensemble utilisé pour la numérotation
        "citations": citations,        # [{idx,title,url,author,site,published_at}]
        "reponse": answer_inline,                  # texte (avec citations inline)
        "reponse_html": answer_html,               # html (liens cliquables)
        "reponse_with_refs": answer_with_refs_txt, # texte + section Références
        "reponse_with_refs_html": answer_with_refs_html,
        "styles": {
            "inline_style": inline_style,
            "biblio_style": biblio_style,
            "add_references_section": add_section
        },
        "save_to_rag_pc": save_result,
    }
    # Si un JSON exploitable a été détecté, on l'expose en plus
    if isinstance(parsed_json, (dict, list)):
        out["reponse_json"] = parsed_json

    # option pour debogage / tests d’intégration (n8n, etc.)
    out["citations_map"] = { str(c.get("idx")): c.get("url") for c in (citations or []) }
    if return_web_context:
        out["web_context"] = web_context
    return jsonify(out), 200


def _fresh_to_time_range(freshness: str | None) -> str | None:
    """
    Convertit un indicateur de fraicheur (ex: '7d', '30d', '1y')
    en time_range compréhensible par SearXNG ('day', 'week', 'month', 'year').
    Retourne None si on ne sait pas convertir.
    """
    if not freshness:
        return None

    f = str(freshness).strip().lower()

    mapping = {
        "1d": "day",
        "24h": "day",
        "7d": "week",
        "14d": "week",
        "30d": "month",
        "1m": "month",
        "3m": "month",
        "90d": "month",
        "365d": "year",
        "1y": "year",
    }

    return mapping.get(f)


@bp.route("/search_web", methods=["POST"])
def search_web():
    data = request.get_json(force=True) or {}
    query = data.get("query") or ""
    engine = (data.get("engine") or "searxng").lower()
    lang = data.get("lang") or "fr"
    num = int(data.get("num") or 10)
    site = data.get("site")  # ex: "site:wikipedia.org"
    freshness = data.get("freshness")  # ex: "7d", "30d"

    if not query:
        return jsonify({"error":"missing query"}), 400
    if site and site not in query:
        query = f"{query} site:{site}"
    
    if engine == "brave" and not BRAVE_KEY:
        engine = "searxng"
    if engine == "tavily" and not TAVILY_KEY:
        engine = "searxng"
    if engine == "perplexity" and not PERPLEX_KEY:
        engine = "searxng"
 
    # SEARXNG par défaut
    if engine in ("searxng", "searx", "sxng"):
        params = {
            "q": query,
            "format": "json",
            "language": lang,
            "safesearch": 1,
            "categories": "general",
            "timeout": 5.0,
        }
        tr = _fresh_to_time_range(freshness)
        if tr:
            params["time_range"] = tr

        try:
            r = requests.get(f"{SEARXNG_BASE}/search", params=params, timeout=10)
            if r.status_code >= 400:
                return jsonify({"engine":"searxng","error": r.text, "status": r.status_code}), r.status_code
            j = r.json()
        except requests.RequestException as e:
            return jsonify({"engine":"searxng","error": str(e)}), 502

        results = (j.get("results") or [])[:num]
        return jsonify({"engine":"searxng","results": _norm(results, "searxng")})

    # BRAVE
    if engine == "brave":
        headers = {"X-Subscription-Token": BRAVE_KEY}
        params  = {"q": query, "count": num, "freshness": freshness or "month", "country": "FR", "safesearch": "moderate"}
        r = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=10)
        r.raise_for_status()
        j = r.json()
        results = (j.get("web") or {}).get("results") or []
        return jsonify({"engine":"brave","results": _norm(results, "brave")})

    # TAVILY
    if engine == "tavily":
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": TAVILY_KEY,
            "query": query,
            "search_depth": "advanced",
            "max_results": num,
            "include_domains": [site] if site else None,
            "include_answer": False,
        }, timeout=10)
        r.raise_for_status()
        j = r.json()
        results = j.get("results") or []
        return jsonify({"engine":"tavily","results": _norm(results, "tavily")})

    # PERPLEXITY (API “answer”), ici on retourne surtout les sources
    if engine == "perplexity":
        headers = {"Authorization": f"Bearer {PERPLEX_KEY}", "Content-Type":"application/json"}
        payload = {
            "model": "sonar-pro",  # ou autre
            "messages": [{"role":"user","content": query}],
            "return_images": False
        }
        r = requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload, timeout=20)
        r.raise_for_status()
        j = r.json()
        # extraire des citations si présentes :
        citations = (j.get("choices") or [{}])[0].get("message", {}).get("citations") or []
        results = [{"title": c.get("title"), "url": c.get("url"), "snippet": None} for c in citations]
        return jsonify({"engine":"perplexity","results": _norm(results[:num], "perplexity")})

    return jsonify({"error":"unknown engine"}), 400

#****************************************************************
# vision VLM
#****************************************************************

def select_vision_model(
    mode: str | None,
    batch_size: int = 1
) -> str:
    """
    Sélection déterministe du VLM selon un mode logique.
    Aucun appel système, aucune métrique instable.
    """

    mode = (mode or config.get("default_vision_mode") or "auto").lower()
    profiles = config.get("vision_profiles", {})

    # Sécurité
    def _safe(name: str, fallback: str) -> str:
        return name if name in models_index else fallback

    default_fast = profiles.get("fast", "SmolVLM2_2B")
    default_quality = profiles.get("quality", "Mistral_7B_Instruct_v0_3")
    default_quality_plus = profiles.get("quality_plus", "Pixtral_12B")

    if mode == "fast":
        return _safe(default_fast, DEFAULT_VISION)

    if mode == "quality":
        return _safe(default_quality, DEFAULT_VISION)

    if mode == "quality_plus":
        return _safe(default_quality_plus, DEFAULT_VISION)

    # --- mode auto (règle volontairement simple et explicable)
    if batch_size >= 6:
        # lots importants → stabilité / débit
        return _safe(default_fast, DEFAULT_VISION)

    # image unique ou petit lot → meilleure description
    return _safe(default_quality, DEFAULT_VISION)

# ============================================================
# ROUTE 1 — /vision/describe (version complète recalée)
# ============================================================

@app.post("/vision/describe")
def vision_describe():
    _vlm_acquire()


    try:
        try:
            if not is_authorized(request):
                return jsonify({"error": "Clé API invalide"}), 401

            import base64

            # -------------------------------------------------
            # 1) Paramètres
            # -------------------------------------------------
            mode = request.form.get("mode")
            model_name = (request.form.get("model_name") or "").strip()

            context = request.form.get("context")
            prompt  = request.form.get("prompt")

            img_bytes = None
            mime = "image/jpeg"
            filename = "unknown"

            # --- multipart
            if request.files and "file" in request.files:
                f = request.files["file"]
                filename = f.filename
                img_bytes = f.read()
                mime = _guess_mime(f.filename)

            # --- JSON base64
            else:
                data = request.get_json(silent=True) or {}
                model_name = model_name or data.get("model_name") or data.get("model")
                context = context or data.get("context")
                prompt  = prompt  or data.get("prompt")

                b64 = data.get("image_b64")
                if b64:
                    if b64.startswith("data:"):
                        header, payload = b64.split(",", 1)
                        img_bytes = base64.b64decode(payload)
                        try:
                            mime = header.split(";")[0].split(":", 1)[1]
                        except Exception:
                            pass
                    else:
                        img_bytes = base64.b64decode(b64)

            if not img_bytes:
                return jsonify({"error": "image manquante"}), 400

            if not model_name:
                model_name = select_vision_model(mode=mode, batch_size=1)

            app.logger.info("[VISION] start file=%s mode=%s model=%s", filename, mode, model_name)

            # -------------------------------------------------
            # 2) Prompts
            # -------------------------------------------------
            raw_context = (context or "").strip()
            system, user_text, use_mode_b, clipped_ctx = build_vlm_prompts(
                raw_context, prompt=(prompt or "")
            )

            # -------------------------------------------------
            # 3) Appel VLM
            # -------------------------------------------------
            vlm = _get_vlm(model_name)
            eff = effective_params(model_name)

            data_uri = _data_uri_from_image_bytes(img_bytes, mime=mime)

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ]}
            ]
            with BACKEND_LOCK:
                out = vlm.create_chat_completion(
                    messages=messages,
                    temperature=float(eff.get("temperature", 0.2)),
                    top_p=float(eff.get("top_p", 0.9)),
                    max_tokens=int(eff.get("max_tokens", 512)),
                )


            content = (
                (out.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "") or ""
            ).strip()

            app.logger.info("[VISION] ok file=%s chars=%s", filename, len(content))

            return jsonify({
                "model": model_name,
                "description": content,
                "trace": {
                    "mode": "B" if use_mode_b else "A",
                    "mime": mime,
                    "context_chars": len(clipped_ctx or ""),
                }
            }), 200

        except Exception as e:
            app.logger.exception("❌ /vision/describe erreur")
            return jsonify({"error": str(e)}), 500
    finally:
        _vlm_release()

# ============================================================
# ROUTE 2 — /vision/describe_batch (version complète recalée)
# ============================================================

@app.post("/vision/describe_batch")
def vision_describe_batch():
    _vlm_acquire()
    try:
        rid = uuid.uuid4().hex[:8]
        t0 = time.time()
        print(f"[VLM][{rid}] START /vision/describe_batch")
        if not is_authorized(request):
            return jsonify({"error": "Clé API invalide"}), 401

        # -------------------------------------------------
        # 1) Paramètres batch
        # -------------------------------------------------
        mode = request.form.get("mode")  # fast | quality | quality_plus | auto
        model_name = (request.form.get("model_name") or "").strip()
        if not model_name:
            # batch_size utilisé pour aider la sélection (si votre select_vision_model en tient compte)
            # (on le fixera plus bas après lecture des files si besoin)
            model_name = select_vision_model(mode=mode, batch_size=1)

        prompt = (request.form.get("prompt") or "").strip()
        context_global = (request.form.get("context") or "").strip()

        # Limites
        MAX_FILES = 32
        MAX_TOTAL_BYTES = 25 * 1024 * 1024
        MAX_PER_FILE_BYTES = 8 * 1024 * 1024

        files = request.files.getlist("files")
        print(f"[VLM][{rid}] files={len(files)}")
        if not files:
            return jsonify({"error": "Aucun fichier: fournir multipart 'files' (répété)"}), 400
        if len(files) > MAX_FILES:
            return jsonify({"error": f"Trop de fichiers: {len(files)} > {MAX_FILES}"}), 400

        # Si vous voulez vraiment sélectionner un modèle selon batch_size :
        # (optionnel, mais cohérent)
        if not (request.form.get("model_name") or "").strip():
            model_name = select_vision_model(mode=mode, batch_size=len(files))

        model_name = (model_name or DEFAULT_VISION).strip()

        # -------------------------------------------------
        # 2) Contextes spécifiques: contexts_json
        # -------------------------------------------------
        contexts_raw = (request.form.get("contexts_json") or "").strip()
        contexts_map = {}
        if contexts_raw:
            try:
                contexts_map = json.loads(contexts_raw)
                if not isinstance(contexts_map, dict):
                    return jsonify({"error": "contexts_json doit être un objet JSON (dict)"}), 400
            except Exception as e:
                return jsonify({"error": f"contexts_json invalide: {e}"}), 400

        # -------------------------------------------------
        # 3) Lecture + contrôles
        # -------------------------------------------------
        items = []
        total = 0

        for idx, f in enumerate(files):
            b = f.read()
            sz = len(b)

            if sz == 0:
                items.append({"idx": idx, "filename": f.filename, "error": "fichier vide"})
                continue
            if sz > MAX_PER_FILE_BYTES:
                items.append({"idx": idx, "filename": f.filename, "error": f"fichier trop volumineux: {sz} octets"})
                continue

            total += sz
            if total > MAX_TOTAL_BYTES:
                items.append({"idx": idx, "filename": f.filename, "error": "taille totale batch dépassée"})
                continue

            mime = _guess_mime(f.filename)

            # contexte spécifique: filename prioritaire, sinon index
            ctx_specific = ""
            if f.filename and f.filename in contexts_map:
                ctx_specific = str(contexts_map.get(f.filename) or "")
            elif str(idx) in contexts_map:
                ctx_specific = str(contexts_map.get(str(idx)) or "")

            items.append({
                "idx": idx,
                "filename": f.filename,
                "mime": mime,
                "bytes": b,
                "context_specific": (ctx_specific or "").strip(),
            })

        work = [it for it in items if it.get("bytes")]
        if not work:
            return jsonify({"error": "Aucun fichier exploitable", "results": items}), 400

        # -------------------------------------------------
        # 4) Prépare VLM (params + modèle)
        # -------------------------------------------------
        try:
            vlm = _get_vlm(model_name)
            eff = effective_params(model_name)
            temperature = float(eff.get("temperature", 0.2))
            top_p = float(eff.get("top_p", 0.9))
            max_tokens = int(eff.get("max_tokens", 512))
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        # -------------------------------------------------
        # 5) Traitement par item (prompts MODE A/B par item)
        # -------------------------------------------------
        MAX_WORKERS = min(1, len(work))
    


        def process_one(it: dict) -> dict:
            try:
                # raw_context total = global + spécifique
                raw_total = build_batch_raw_context(context_global, it.get("context_specific", ""))

                system, user_text, use_mode_b, clipped_ctx = build_vlm_prompts(raw_total, prompt=prompt)

                data_uri = _data_uri_from_image_bytes(it["bytes"], mime=it["mime"])

                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ]}
                ]

                def _do_infer():
                    return vlm.create_chat_completion(
                        messages=messages,
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                    )

                # sérialisation par modèle si vous avez un verrou
                out = _infer_with_lock(model_name, _do_infer)

                content = (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                return {
                    "idx": it["idx"],
                    "filename": it.get("filename"),
                    "description": content.strip(),
                    "trace": {
                        "mode": "B" if use_mode_b else "A",
                        "context_chars": len(clipped_ctx or ""),
                        "mime": it.get("mime"),
                    }
                }

            except Exception as e:
                return {
                    "idx": it.get("idx"),
                    "filename": it.get("filename"),
                    "error": str(e),
                }

        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = [ex.submit(process_one, it) for it in work]
            for f in as_completed(futs):
                results.append(f.result())

        results_sorted = sorted(results, key=lambda x: x.get("idx", 10**9))

        # erreurs de lecture/taille déjà dans `items`
        invalids = [it for it in items if ("error" in it and not it.get("bytes"))]
        invalids_norm = [{"idx": it["idx"], "filename": it.get("filename"), "error": it["error"]} for it in invalids]

        print("\n[DEBUG VLM RETURN SAMPLE]")
        if results_sorted:
            print(json.dumps(results_sorted[0], ensure_ascii=False, indent=2)[:1500])
        else:
            print("(no results)")
        print("[END DEBUG]\n")


        all_results = results_sorted + invalids_norm
        all_results = sorted(all_results, key=lambda x: x.get("idx", 10**9))
        # juste avant return
        dt = time.time() - t0
        print(f"[VLM][{rid}] END ok processed={len(work)} dt={dt:.1f}s")

        return jsonify({
            "model": model_name,
            "count_requested": len(files),
            "count_processed": len(work),
            "results": all_results,
        })
    finally:
        _vlm_release()

@app.post("/vision/describe_batch_csv")
def vision_describe_batch_csv():
    _vlm_acquire()
    try:
        if not is_authorized(request):
            return jsonify({"error": "Clé API invalide"}), 401

        if "file" not in request.files:
            return jsonify({"error": "CSV manquant (champ 'file')"}), 400

        mode = request.form.get("mode")  # fast | quality | quality_plus | auto
        model_name = request.form.get("model_name")

        if model_name:
            model_name = model_name.strip()
        else:
            model_name = select_vision_model(
                mode=mode,
                batch_size=1  # ou len(files) en batch
            )


        prompt = (request.form.get("prompt") or "").strip()
        context_global = (request.form.get("context") or "").strip()

        csv_file = request.files["file"]
        try:
            content = csv_file.read().decode("utf-8")
        except Exception:
            return jsonify({"error": "CSV non lisible (UTF-8 requis)"}), 400

        reader = csv.DictReader(io.StringIO(content), delimiter=";")
        if "image_path" not in reader.fieldnames:
            return jsonify({"error": "Colonne 'image_path' absente du CSV"}), 400

        try:
            vlm = _get_vlm(model_name)
            eff = effective_params(model_name)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        system = (
            "Tu es un module de perception visuelle. "
            "Tu décris l'image de façon factuelle, neutre et précise, en français. "
            "Tu n'inventes aucun élément non visible. "
            "En cas d'incertitude, tu l'indiques explicitement."
        )

        results = []

        for idx, row in enumerate(reader):
            path = (row.get("image_path") or "").strip()
            ctx_specific = (row.get("context") or "").strip()

            if not path:
                results.append({"idx": idx, "error": "image_path vide"})
                continue

            if not os.path.isfile(path):
                results.append({
                    "idx": idx,
                    "image_path": path,
                    "error": "fichier inaccessible depuis le serveur"
                })
                continue

            try:
                with open(path, "rb") as f:
                    img_bytes = f.read()

                mime = _guess_mime(path)
                data_uri = _data_uri_from_image_bytes(img_bytes, mime)

                user_text = "Décris précisément l'image."
                if context_global:
                    user_text += "\n\nContexte global :\n" + context_global
                if ctx_specific:
                    user_text += "\n\nContexte spécifique :\n" + ctx_specific
                if prompt:
                    user_text += "\n\nConsigne spécifique :\n" + prompt

                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ]}
                ]

                def _infer():
                    return vlm.create_chat_completion(
                        messages=messages,
                        temperature=float(eff.get("temperature", 0.2)),
                        top_p=float(eff.get("top_p", 0.9)),
                        max_tokens=int(eff.get("max_tokens", 512)),
                    )

                out = _infer_with_lock(model_name, _infer)
                desc = (out.get("choices") or [{}])[0].get("message", {}).get("content", "")

                results.append({
                    "idx": idx,
                    "image_path": path,
                    "description": desc.strip()
                })

            except Exception as e:
                results.append({
                    "idx": idx,
                    "image_path": path,
                    "error": str(e)
                })

        return jsonify({
            "model": model_name,
            "count": len(results),
            "results": results
        })
    finally:
        _vlm_release()

@app.post("/vision/describe_structured")
def vision_describe_structured():
    _vlm_acquire()
    try:
        if not is_authorized(request):
            return jsonify({"error": "Clé API invalide"}), 401


        mode = request.form.get("mode")  # fast | quality | quality_plus | auto
        model_name = request.form.get("model_name")

        if model_name:
            model_name = model_name.strip()
        else:
            model_name = select_vision_model(
                mode=mode,
                batch_size=1  # ou len(files) en batch
            )

        context = (request.form.get("context") or "").strip()

        if "file" not in request.files:
            return jsonify({"error": "Image manquante (file)"}), 400

        f = request.files["file"]
        img_bytes = f.read()
        mime = _guess_mime(f.filename)

        try:
            vlm = _get_vlm(model_name)
            eff = effective_params(model_name)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        data_uri = _data_uri_from_image_bytes(img_bytes, mime)

        user_prompt = f"""
    Analyse l’image et produis exclusivement un JSON conforme au schéma suivant :

    {{
    "image_id": "{f.filename}",
    "observations": [
        {{
        "fait": "",
        "categorie": "",
        "localisation": "",
        "indices_visuels": [],
        "certitude": "",
        "commentaire": ""
        }}
    ],
    "elements_absents_remarquables": [],
    "limites_analyse": []
    }}

    Contexte éventuel (ne pas extrapoler au-delà) :
    {context}
    """

        messages = [
            {"role": "system", "content": VISION_JSON_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}
        ]

        def _infer():
            return vlm.create_chat_completion(
                messages=messages,
                temperature=0.1,   # très bas pour stabilité JSON
                top_p=0.9,
                max_tokens=800,
            )

        out = _infer_with_lock(model_name, _infer)
        raw = (out.get("choices") or [{}])[0].get("message", {}).get("content", "")

        return jsonify({
            "model": model_name,
            "raw_json": raw.strip()
        })
    finally:
        _vlm_release()



def _safe_json_load(raw: str) -> dict:
    """
    Tente de charger un JSON. Si le modèle a encapsulé dans ```json ... ```, on nettoie.
    """
    if not raw:
        raise ValueError("raw_json vide")
    s = raw.strip()
    s = re.sub(r"^```json\s*|\s*```$", "", s, flags=re.IGNORECASE | re.MULTILINE).strip()
    return json.loads(s)

def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _obs_key(obs: dict) -> str:
    # Clé de dé-doublonnage "prudente" : fait + localisation + categorie
    return " | ".join([
        _norm_text(obs.get("categorie")),
        _norm_text(obs.get("fait")),
        _norm_text(obs.get("localisation")),
    ])

@app.post("/vision/merge_structured")
def vision_merge_structured():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    payload = request.get_json(silent=True) or {}
    group_by = (payload.get("group_by") or "group").strip()
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"error": "items doit être une liste non vide"}), 400

    grouped = defaultdict(list)
    errors = []

    for i, it in enumerate(items):
        try:
            image_id = (it.get("image_id") or f"item_{i}").strip()
            group = (it.get("group") or "Sans_groupe").strip()
            raw = it.get("raw_json") or ""
            doc = _safe_json_load(raw)

            grouped[group].append({
                "image_id": image_id,
                "doc": doc
            })
        except Exception as e:
            errors.append({"idx": i, "error": str(e), "image_id": it.get("image_id")})

    syntheses = []

    for group, arr in grouped.items():
        # Consolidation des observations
        obs_map = {}  # key -> merged obs
        absents = set()
        limites = set()
        sources = []

        for entry in arr:
            image_id = entry["image_id"]
            doc = entry["doc"]
            sources.append(image_id)

            for lim in (doc.get("limites_analyse") or []):
                limites.add(str(lim).strip())

            for ab in (doc.get("elements_absents_remarquables") or []):
                absents.add(str(ab).strip())

            for obs in (doc.get("observations") or []):
                if not isinstance(obs, dict):
                    continue
                k = _obs_key(obs)
                if not k.strip():
                    continue

                if k not in obs_map:
                    obs_map[k] = {
                        "fait": obs.get("fait", ""),
                        "categorie": obs.get("categorie", ""),
                        "localisation": obs.get("localisation", ""),
                        "indices_visuels": list(obs.get("indices_visuels") or []),
                        "certitude": obs.get("certitude", ""),
                        "commentaire": obs.get("commentaire", ""),
                        "sources_images": [image_id],
                    }
                else:
                    # fusion douce : on garde l’existant, on enrichit les listes + sources
                    obs_map[k]["sources_images"].append(image_id)

                    # indices_visuels union
                    existing = set(map(str, obs_map[k].get("indices_visuels") or []))
                    for ind in (obs.get("indices_visuels") or []):
                        existing.add(str(ind))
                    obs_map[k]["indices_visuels"] = sorted(existing)

                    # certitude : on garde la plus prudente (faible < moyenne < élevée)
                    order = {"faible": 0, "moyenne": 1, "élevée": 2}
                    cur = _norm_text(obs_map[k].get("certitude"))
                    new = _norm_text(obs.get("certitude"))
                    if cur in order and new in order:
                        obs_map[k]["certitude"] = cur if order[cur] <= order[new] else new
                    elif new and not cur:
                        obs_map[k]["certitude"] = obs.get("certitude")

        syntheses.append({
            "group": group,
            "group_by": group_by,
            "sources_images": sources,
            "observations_consolidees": list(obs_map.values()),
            "elements_absents_remarquables_consolides": sorted(x for x in absents if x),
            "limites_analyse_consolidees": sorted(x for x in limites if x),
        })

    return jsonify({
        "count_groups": len(syntheses),
        "syntheses": syntheses,
        "errors": errors
    })

@app.post("/vision/merge_structured_report")
def vision_merge_structured_report():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"error": "items doit être une liste non vide"}), 400

    # 1) Fusion déterministe (réutilise ta route merge si tu l’as ajoutée)
    # Ici, on appelle directement la fonction vision_merge_structured() via un context interne
    # pour éviter un aller-retour HTTP.
    with app.test_request_context(
        "/vision/merge_structured",
        method="POST",
        json={"group_by": data.get("group_by") or "group", "items": items},
        headers=request.headers
    ):
        merged_resp = vision_merge_structured()
        # merged_resp peut être (json, status) ou Response
        if isinstance(merged_resp, tuple):
            merged_json, status = merged_resp
            if status != 200:
                return merged_json, status
            merged = merged_json.get_json()
        else:
            merged = merged_resp.get_json()

    syntheses = merged.get("syntheses") or []
    errors = merged.get("errors") or []

    # 2) Construction d’un prompt de constat (factuel, neutre, traçable)
    style = (data.get("style") or "court").strip().lower()
    llm_model_name = (data.get("llm_model_name") or data.get("model_name") or "").strip()

    # Règles rédactionnelles : constat matériel, pas de causalité / responsabilité
    system_constat = (
        "Tu es un rédacteur technique. "
        "Tu produis un constat factuel à partir d’observations visuelles consolidées. "
        "Interdictions: (1) inférer une cause, (2) qualifier juridiquement, (3) attribuer une responsabilité, "
        "(4) inventer des éléments non listés. "
        "Si une information est incertaine, mentionne-la comme telle. "
        "Chaque point doit citer les images sources entre crochets (ex: [img001.jpg, img002.jpg]). "
        "Style: phrases courtes, vocabulaire neutre."
    )

    # Mise en forme des données consolidées (sans gonfler inutilement)
    parts = []
    for g in syntheses:
        group = g.get("group") or "Sans_groupe"
        obs = g.get("observations_consolidees") or []
        lim = g.get("limites_analyse_consolidees") or []
        absn = g.get("elements_absents_remarquables_consolides") or []

        parts.append(f"### Groupe: {group}")
        if obs:
            parts.append("Observations consolidées :")
            for o in obs:
                fait = (o.get("fait") or "").strip()
                cat = (o.get("categorie") or "").strip()
                loc = (o.get("localisation") or "").strip()
                cert = (o.get("certitude") or "").strip()
                srcs = o.get("sources_images") or []
                src_txt = ", ".join([s for s in srcs if s]) if srcs else ""
                line = f"- [{cat}] {fait}"
                if loc:
                    line += f" (Localisation: {loc})"
                if cert:
                    line += f" (Certitude: {cert})"
                if src_txt:
                    line += f" [{src_txt}]"
                parts.append(line)

        if absn:
            parts.append("Absences notables (si explicitement mentionnées) :")
            for a in absn:
                parts.append(f"- {a}")

        if lim:
            parts.append("Limites d’analyse :")
            for l in lim:
                parts.append(f"- {l}")

        parts.append("")  # séparation

    fused_text = "\n".join(parts).strip()
    if not fused_text:
        return jsonify({"error": "Fusion vide/inexploitable", "errors": errors}), 400

    # Prompt utilisateur selon niveau de détail
    if style == "detaille":
        user_prompt = (
            "Rédige un constat structuré par groupe.\n"
            "Pour chaque groupe, produis :\n"
            "1) une liste de constats numérotés (faits matériels),\n"
            "2) une section 'Limites' si nécessaire.\n\n"
            "Données consolidées :\n"
            f"{fused_text}"
        )
    else:
        user_prompt = (
            "Rédige un constat bref, structuré par groupe, sous forme de puces.\n"
            "Conserve uniquement les faits matériels.\n\n"
            "Données consolidées :\n"
            f"{fused_text}"
        )

    # 3) Appel de /annoter (dispatch interne sans HTTP), pour bénéficier de ta logique n_ctx/marge/log
    payload_annoter = {
        "prompt": user_prompt,
        "system": system_constat,
        "lang": "fr",
    }
    if llm_model_name:
        payload_annoter["model_name"] = llm_model_name

    with app.test_request_context(
        "/annoter",
        method="POST",
        json=payload_annoter,
        headers=request.headers
    ):
        annot_resp = annoter()
        if isinstance(annot_resp, tuple):
            annot_json, status = annot_resp
            if status != 200:
                return annot_json, status
            annot_out = annot_json.get_json()
        else:
            annot_out = annot_resp.get_json()

    return jsonify({
        "merge": merged,                       # JSON consolidé (traçable)
        "constat": annot_out.get("reponse",""), # texte rédigé
        "errors": errors
    })


#****************************************************************
# embedding
#****************************************************************

@app.post("/embeddings")
def embeddings():
    """
    Corps attendu (JSON):
    {
      "texts": ["...", "..."],
      "model": "Nomic_Embed" | "E5_multilingual_large" | "BGE_3" | ...
    }
    Réponse:
    { "embeddings": [[...], [...], ...] }
    """
    data = request.get_json(silent=True) or {}
    texts = data.get("texts") or []
    model = data.get("model") or "Nomic_Embed"

    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        return jsonify({"error": "texts must be a list of strings"}), 400

    if not texts:
        return jsonify({"embeddings": []})
    
    try:
        try:
            embedder = _get_embedder(model)
        except KeyError as e:
            return jsonify({"error": f"Unknown model '{model}'"}), 400

        # Logs utiles pour diagnostiquer si ça replante

        app.logger.info("Embedder type for %s: %s", model, type(embedder))
        app.logger.info("helpers_embed @ %s", getattr(helpers_embed, "__file__", "?"))
        app.logger.info("sentence_transformers @ %s", getattr(sentence_transformers, "__file__", "?"))

        # Ceinture + bretelles: refuser si pas .encode
        if not hasattr(embedder, "encode"):
            return jsonify({"error": f"Bad embedder for {model}: {type(embedder)} has no .encode"}), 500

        # ✅ Toujours utiliser .encode(...) (jamais embedder(...))
        vecs = embedder.encode(texts, normalize_embeddings=True, batch_size=32).tolist()
        return jsonify({"embeddings": vecs})
    except Exception as e:
        app.logger.exception("/embeddings error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/rag/context", methods=["POST"])
def rag_context():
    """Renvoie uniquement le contexte RAG (vectoriel, mémoire ou dossier)."""
    if not is_authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query requis"}), 400

    # --- RAG vectoriel (Chroma / Qdrant) ---
    if data.get("rag_vector"):
        rv = data["rag_vector"]
        mode = (rv.get("mode") or "strict").lower()
        strict = (mode != "fallback")
        filters = rv.get("filters")  # dict attendu

        ctx, sources = build_rag_context_store(
            query=query,
            collection_name=rv.get("collection", "default_collection"),
            vec_backend=(rv.get("backend") or "chroma").lower(),
            chroma_dir=rv.get("chroma_dir"),
            k=int(rv.get("k", 4)),
            show_distances=bool(rv.get("show_distances", False)),
            max_total_chars=int(rv.get("max_total_chars", 6000)),
            filters=filters,                 # ✅ AJOUT
            strict=strict,                   # ✅ AJOUT
            qdrant_url=rv.get("qdrant_url"),
            qdrant_api_key=rv.get("qdrant_api_key"),
        )
        return jsonify({"context": ctx, "sources": sources})

    # --- RAG mémoire (conversation courte) ---
    if data.get("rag_memoire"):
        rm = data["rag_memoire"]
        api_key = request.headers.get("x-api-key", "anon")
        coll = rm.get("collection") or f"memoire_chat:{hash(api_key) & 0xFFFFFF:x}"
        docs = rm.get("documents") or []
        ctx = build_mem_ctx(coll, docs, query, top_k=int(rm.get("top_k", 4)))
        return jsonify({"context": ctx, "sources": []})

    # --- RAG fichiers / dossier ---
    if data.get("rag_dossier"):
        dossier = data["rag_dossier"]
        contenu = extraire_contenu_rag(dossier)
        return jsonify({"context": contenu, "sources": []})

    return jsonify({"context": "", "sources": []})



# ---------- Routes de consultation / purge ----------
@app.route("/qa_logs", methods=["GET"])
def qa_logs_list():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    project_id = (request.args.get("project_id") or "").strip()
    try:
        limit = int(request.args.get("limit", "100"))
        projects = _load_projects_index()
        proj = _find_project(project_id, projects)
        if not proj:
            return jsonify({"ok": False, "error": f"Projet introuvable: {project_id}"}), 404     
        cfg = load_project_config(project_id)
        root_pc = (cfg.get("roots") or {}).get("pcfixe")
        rag_pc_name = DEFAULT_SUBDIRS.get("rag_pc_subdir", "RAG_PC")
        logs_dir = _qa_logs_dir(root_pc, rag_pc_subdir=rag_pc_name)

        items = []
        # on lit en sens inverse (les plus récents d'abord)
        for month_dir in sorted(logs_dir.glob("*"), reverse=True):
            for f in sorted(month_dir.glob("qa_*.jsonl"), reverse=True):
                items.append(str(f))
        out = []
        for fp in items:
            if len(out) >= limit:
                break
            try:
                with open(fp, "r", encoding="utf-8") as r:
                    # on prend les 5 dernières lignes du fichier
                    lines = r.readlines()[-5:]
                    out.extend([json.loads(x) for x in lines])
            except Exception:
                continue
        # les plus récents en tête
        out = sorted(out, key=lambda x: x.get("ts", 0), reverse=True)[:limit]
        return jsonify({"ok": True, "count": len(out), "items": out})
    except ValueError:
        return jsonify({"ok": False, "error": "Parametre 'limit' invalide"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/qa_logs/purge", methods=["POST"])
def qa_logs_purge():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    data = request.get_json(silent=True) or {}
    if not data:
        app.logger.warning("%s: JSON vide/non décodable", request.path)
    project_id = (data.get("project_id") or "").strip()
    try:
        older_than_days = int(data.get("older_than_days", 90))
        projects = _load_projects_index()
        proj = _find_project(project_id, projects)
        if not proj:
            return jsonify({"ok": False, "error": f"Projet introuvable: {project_id}"}), 404

        cfg = load_project_config(project_id)
        root_pc = (cfg.get("roots") or {}).get("pcfixe")
        rag_pc_name = DEFAULT_SUBDIRS.get("rag_pc_subdir", "RAG_PC")
        logs_dir = _qa_logs_dir(root_pc, rag_pc_subdir=rag_pc_name)
        cutoff = time.time() - older_than_days*24*3600
        removed = 0
        for month_dir in logs_dir.glob("*"):
            for f in month_dir.glob("qa_*.jsonl"):
                if f.stat().st_mtime < cutoff:
                    try:
                        f.unlink(); removed += 1
                    except Exception:
                        pass
        return jsonify({"ok": True, "removed": removed})
    except ValueError:
        return jsonify({"ok": False, "error": "Parametre 'older_than_days' invalide"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# --- DEBUG : lister les routes chargées ---
@app.route("/__routes", methods=["GET"])
def __routes():
    from flask import jsonify
    return jsonify(sorted([str(r) for r in app.url_map.iter_rules()]))

#=======================================================================

##========================================================================
@app.route("/asr_voxtral", methods=["POST"])
def asr_voxtral():
    if not is_authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        data = request.get_json(silent=True) or {}
        # Ne warn que si le client a explicitement tenté du JSON
        app.logger.info(
            "[ASR][REQ] output_csv_dir=%s auto_chunk=%s chunk=%s stride=%s audio_path=%s client_tag=%s",
            data.get("output_csv_dir"),
            data.get("auto_chunk"),
            data.get("chunk"),
            data.get("stride"),
            data.get("audio_path"),
            data.get("client_tag"),
        )

        if request.is_json and not data:
            app.logger.warning("%s: JSON vide/non décodable (Content-Type JSON)", request.path)

        t0 = time.perf_counter()
        start_total = time.time()

        # --- alias rétro-compat ---
        if "language" in data and "lang" not in data:
            data["lang"] = data.pop("language")
        if "return_timestamps" in data and "timestamps" not in data:
            data["timestamps"] = bool(data.pop("return_timestamps"))
        if "chunk_length_s" in data and "chunk" not in data:
            data["chunk"] = int(data.pop("chunk_length_s"))
        if "stride_length_s" in data and "stride" not in data:
            data["stride"] = int(data.pop("stride_length_s"))

        # --- lecture payload principal ---
        audio_path = data.get("audio_path")
        model_key  = data.get("model_key", DEFAULT_ASR)
        timestamps = bool(data.get("timestamps", False))
        lang       = data.get("lang") or None
        chunk      = int(data.get("chunk", 30))
        stride     = (int(data["stride"]) if str(data.get("stride", "")).strip() != "" else None)
        force_cpu  = bool(data.get("cpu", False))
        use4bit    = not bool(data.get("no4bit", False))

        temperature    = float(data.get("temperature", 0.0))
        top_p          = (float(data["top_p"]) if data.get("top_p") is not None else None)
        max_new_tokens = int(data.get("max_new_tokens", 2048))
        batch_size     = int(data.get("batch_size", 1))
        t_prep = time.perf_counter()

        # Découpe par silences (ASR sans diarisation)
        silence_split  = bool(data.get("silence_split", False))
        silence_top_db = int(data.get("silence_top_db", 30))
        silence_min_ms = int(data.get("silence_min_ms", 250))

        # diarisation
        diarize        = bool(data.get("diarize", False))
        hf_token       = data.get("hf_token") or os.getenv("HF_TOKEN")
        diar_opt       = data.get("diar_options") or {}
        max_speakers   = diar_opt.get("max_speakers")
        min_spk_dur    = diar_opt.get("min_speaker_duration")
        collar         = float(diar_opt.get("collar", 0.05))
        allow_overlap  = bool(diar_opt.get("allow_overlap", diar_opt.get("overlap", False)))

        # glossaire
        vocab_hint     = data.get("vocab_hint")
        glossary_path  = data.get("glossary_path")
        proper_names_path    = (GRIDS_DIR / "proper_names.txt")
        proper_gloss_path    = (GRIDS_DIR / "proper_names_glossary.json")
        speaker_aliases_path = (GRIDS_DIR / "speaker_aliases.json")

        if not vocab_hint and proper_names_path.exists():
            vocab_hint = _read_lines(proper_names_path)

        if not glossary_path and proper_gloss_path.exists():
            glossary_path = str(proper_gloss_path)

        # sous-titres
        want_srt = bool(data.get("export_srt", False))
        want_vtt = bool(data.get("export_vtt", False))

        # sorties fichiers + préférences Excel
        out_dir, out_dir_rule = _resolve_asr_out_dir(data)
        export_raw_csv    = bool(data.get("export_raw_csv",   True))
        export_photo_csv  = bool(data.get("export_photo_csv", True))
        export_chat_csv   = bool(data.get("export_chat_csv",  True))
        export_chat_docx  = bool(data.get("export_chat_docx", False))
        excel_encoding    = (data.get("excel_encoding") or "utf-8-sig").lower()  # "utf-8-sig" | "cp1252"
        csv_sep           = ';' if (data.get("excel_decimal") or "comma") == "comma" else ','


        # ---- validations
        if not audio_path or not Path(audio_path).exists():
            return jsonify({"error": f"Fichier introuvable: {audio_path}"}), 400
        if model_key not in models_index or models_index[model_key].get("type") != "asr":
            return jsonify({"error": f"model_key invalide: {model_key}"}), 400

        app.logger.info(f"[ASR] Début traitement {audio_path}")
        app.logger.info(
            "[ASR][OUT] resolved out_dir=%s rule=%s project_id=%s",
            out_dir, out_dir_rule, data.get("project_id")
        )

        # Token HF (si fourni) dispo pour la diarisation/embeddings
        if hf_token:
            os.environ["HF_TOKEN"] = str(hf_token)

        # ---- pipeline (cache + lock)
        key = (model_key, use4bit, force_cpu)
        if key not in VOXTRAL_LOCKS:
            VOXTRAL_LOCKS[key] = threading.Lock()
        with VOXTRAL_LOCKS[key]:
            if key not in VOXTRAL_PIPELINES:
                VOXTRAL_PIPELINES[key], _ = create_voxtral_pipeline(
                    model_key=model_key, load_in_4bit=use4bit, force_cpu=force_cpu
                )
            asr = VOXTRAL_PIPELINES[key]

        # ============================================================
        #            Aiguillage : Auto-chunk long fichier
        # ============================================================

        effective_chunk = AUTO_CHUNK_SEC
        default_stride  = AUTO_CHUNK_STRIDE_SEC

        if diarize:
            effective_chunk = int(os.getenv("AUTO_CHUNK_SEC_DIAR", "480"))          # 8 min
            default_stride  = int(os.getenv("AUTO_CHUNK_STRIDE_SEC_DIAR", "10"))    # 10 s

        chunk = int(data.get("chunk_len_s") or data.get("chunk") or effective_chunk)

        stride_val = data.get("stride_s")
        if stride_val is None or str(stride_val).strip() == "":
            stride_val = data.get("stride")
        stride = int(stride_val) if (stride_val is not None and str(stride_val).strip() != "") else default_stride

        if stride is None:
            stride = AUTO_CHUNK_STRIDE_SEC

        if diarize:
            chunk = min(chunk, effective_chunk)

        audio_dur_s  = _probe_audio_duration(audio_path)
        auto_chunk   = bool(data.get("auto_chunk", True))

        # long fichier : durée si connue, sinon fallback taille
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)

        if audio_dur_s is not None:
            wants_long = audio_dur_s >= (effective_chunk + 30)
        else:
            wants_long = file_size_mb >= 200

        if auto_chunk:
            app.logger.info(f"[ASR][AUTO] long={wants_long} diarize={diarize} chunk={chunk}s stride={stride}s dur={audio_dur_s}")

        app.logger.warning(
            f"[SENTINEL] auto_chunk={auto_chunk} diarize={diarize} "
            f"dur={audio_dur_s} eff_chunk={effective_chunk}"
        )


        if auto_chunk and wants_long:
            res_auto = _asr_voxtral_auto_pipeline(
                audio_path=audio_path,
                model_key=model_key,
                asr=asr,
                diar_options=diar_opt,
                export_raw_csv=export_raw_csv,
                export_photo_csv=export_photo_csv,
                export_srt=want_srt,
                export_vtt=want_vtt,
                out_dir=out_dir,
                excel_encoding=excel_encoding,
                csv_sep=csv_sep,
                lang=lang,
                timestamps=timestamps,
                chunk_len_s=chunk,
                stride_s=stride,
                temperature=temperature,
                top_p=top_p,
                max_new_tokens=max_new_tokens,
                batch_size=batch_size,
            )

            payload = {
                "text": "",
                "chunks": [],
                "model_key": model_key,
                "audio_path": audio_path,
                "csv_path": res_auto.get("csv_path"),
                "photo_csv_path": res_auto.get("photo_csv_path"),
                "srt_path": res_auto.get("srt_path"),
                "vtt_path": res_auto.get("vtt_path"),
                "quant": asr.get("quant", "unknown"),
                "auto_chunk_used": True,
                "auto_chunk_chunk_len_s": chunk,
                "auto_chunk_stride_s": stride,
                "segments_merged": res_auto.get("segments", 0),
                "output_dir": out_dir,
                "output_dir_rule": out_dir_rule,
            }

            file_size_bytes = os.path.getsize(audio_path)
            t_total = time.perf_counter() - t0
            rtf = (audio_dur_s / t_total) if (audio_dur_s and t_total > 0) else None
            kbps = (file_size_bytes / 1024.0) / t_total if t_total > 0 else None

            payload["timing"] = {
                "total_s": round(t_total, 3),
                "audio_duration_s": (round(audio_dur_s, 3) if audio_dur_s else None),
                "rtf": (round(rtf, 3) if rtf else None),
                "throughput_kBps": (round(kbps, 1) if kbps else None),
            }
            payload["timing_detail"] = {
                "prep_s": round(t_prep - t0, 3),
                "asr_s": None,
                "exports_s": None,
            }

            log_appel({
                "route": "asr_voxtral",
                "audio_path": audio_path,
                "model_key": model_key,
                "auto_chunk_used": True,
                "csv_path": payload.get("csv_path"),
                "photo_csv_path": payload.get("photo_csv_path"),
                "output_dir": out_dir,
                "output_dir_rule": out_dir_rule,
            })

            return jsonify(payload)

        # ============================================================
        #             Chemin standard (fichier non long)
        # ============================================================
        t_asr_start = time.perf_counter()

        if diarize:
            t_diar_start = time.perf_counter()
            app.logger.info(f"[ASR] Diarisation (standard) chunk={chunk}s stride={stride}s")
            res = transcribe_with_diarization(
                audio_path=audio_path,
                model_key=model_key,
                asr_pipeline=asr,
                language=lang,
                hf_token=hf_token,
                diar_options=diar_opt,
                output_csv_dir=out_dir,
                chunk=chunk,
                stride=stride,
                timestamps=bool(data.get("timestamps", True)),
                max_speakers=max_speakers,
                min_speaker_duration=min_spk_dur,
                collar=collar,
                allow_overlap=allow_overlap,
                temperature=temperature,
                top_p=top_p,
                max_new_tokens=max_new_tokens,
            )
            app.logger.info(f"[ASR] Diarisation terminée en {time.perf_counter() - t_diar_start:.1f} sec")
        else:
            t_asr_only_start = time.perf_counter()
            res = transcribe_audio(
                audio_path=audio_path,
                asr_pipeline=asr,
                chunk_length_s=chunk,
                stride_length_s=stride,
                return_timestamps=timestamps,
                language=lang,
                batch_size=batch_size,
                temperature=temperature,
                top_p=top_p,
                max_new_tokens=max_new_tokens,
                silence_split=silence_split,
                silence_top_db=silence_top_db,
                silence_min_ms=silence_min_ms,
            )
            app.logger.info(f"[ASR] Transcription ASR seule terminée en {time.perf_counter() - t_asr_only_start:.1f} sec")

        # ---- post-correction (dans tous les cas)
        res = post_correct_transcript(res, vocab_hint=vocab_hint, glossary_path=glossary_path)
        # ---- nettoyage segments (glitches / doublons)
        res["chunks"] = clean_asr_segments(res.get("chunks") or [])
        res["text"] = "\n".join((ch.get("text") or "").strip() for ch in res["chunks"] if (ch.get("text") or "").strip())


        # ---- règles de nommage speaker (avant payload et exports)
        speaker_rules_path = data.get("speaker_rules_path")

        if speaker_rules_path:
            rules = load_json_safe(speaker_rules_path)
            res["chunks"] = _label_speakers_from_rules(res.get("chunks"), rules)

        elif diarize and speaker_aliases_path.exists():
            aliases_cfg = load_json_safe(speaker_aliases_path)
            res["chunks"] = _label_speakers_from_rules(res.get("chunks"), aliases_cfg)

        # Recomposer le texte après éventuelle modification des chunks
        res["text"] = "\n".join(
            (ch.get("text") or "").strip()
            for ch in (res.get("chunks") or [])
            if (ch.get("text") or "").strip()
        )

        t_after_asr = time.perf_counter()
        app.logger.info(f"[ASR] Durée totale transcription (ASR+diar éventuellement) : {t_after_asr - t_asr_start:.1f} sec")



        # ---- payload de base
        payload = {
            "text": res.get("text", ""),
            "chunks": res.get("chunks", []),
            "model_key": model_key,
            "audio_path": audio_path,
            "quant": asr.get("quant", "unknown"),
            "chunks_preview": (res.get("chunks") or [])[:10],
            "output_dir": out_dir,
            "output_dir_rule": out_dir_rule,
        }

        # ---- sous-titres inline
        if want_srt and res.get("chunks"):
            payload["srt"] = to_srt(res["chunks"])
        if want_vtt and res.get("chunks"):
            payload["vtt"] = to_vtt(res["chunks"])



        # ---- exports fichiers
        if out_dir:
            outp = Path(out_dir)
            outp.mkdir(parents=True, exist_ok=True)
            wav_path = Path(audio_path)
            stem_tag = f"{_safe_stem(wav_path)}{_ext_tag(wav_path)}"

            raw_csv   = outp / f"{stem_tag}.csv"
            photo_csv = outp / f"{stem_tag}(photo).csv"
            chat_csv  = outp / f"{stem_tag}(chat).csv"

            # 1) CSV brut
            if export_raw_csv:
                if raw_csv.exists():
                    try:
                        raw_csv.unlink()
                    except Exception:
                        pass
                with _open_csv_for_excel(raw_csv, encoding=excel_encoding) as (f, used_raw_csv):
                    w = csv.writer(f, delimiter=csv_sep, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
                    w.writerow(["start","end","speaker","text"])
                    for ch in (res.get("chunks") or []):
                        txt = (ch.get("text") or "").replace("\r"," ").replace("\n"," ").strip()
                        txt = _sanitize_for_cp1252(txt) if excel_encoding == "cp1252" else _sanitize_for_encoding(txt, excel_encoding)
                        w.writerow([ch.get("start",""), ch.get("end",""), (ch.get("speaker") or "Speaker"), txt])
                payload["csv_path"] = str(used_raw_csv)

            # 2) CSV photo
            if export_photo_csv:
                if photo_csv.exists():
                    try:
                        photo_csv.unlink()
                    except Exception:
                        pass
                with _open_csv_for_excel(photo_csv, encoding=excel_encoding) as (f, used_photo_csv):
                    w = csv.writer(
                        f,
                        delimiter=csv_sep,
                        quoting=csv.QUOTE_MINIMAL,
                        lineterminator="\r\n",
                    )
                    w.writerow(["horodatage", "locuteur", "texte"])
                    for ch in (res.get("chunks") or []):
                        start_s = float(ch.get("start") or 0.0)
                        speaker = ch.get("speaker") or "SPEAKER"
                        text = (ch.get("text") or "").replace("\r", " ").replace("\n", " ").strip()
                        if excel_encoding == "cp1252":
                            text = _sanitize_for_cp1252(text)
                        else:
                            text = _sanitize_for_encoding(text, excel_encoding)
                        ts_cell = _fmt_hms(start_s)
                        w.writerow([ts_cell, speaker, text])
                payload["photo_csv_path"] = str(used_photo_csv)
            
            if want_srt and res.get("chunks"):
                srt_text = to_srt(res["chunks"])
                payload["srt"] = srt_text

                srt_path = outp / f"{stem_tag}.srt"
                srt_path.write_text(srt_text, encoding="utf-8")
                payload["srt_path"] = str(srt_path)


            if want_vtt and res.get("chunks"):
                vtt_text = to_vtt(res["chunks"])
                payload["vtt"] = vtt_text

                vtt_path = outp / f"{stem_tag}.vtt"
                vtt_path.write_text(vtt_text, encoding="utf-8")
                payload["vtt_path"] = str(vtt_path)

            # 3) Résumé (chat) éventuel
            summary_text = ""
            if (export_chat_csv or export_chat_docx):
                report_prompts_path = data.get("report_prompts_path")
                try:
                    summary_text = summarize_text_safely_with_voxtral(
                        res_text=res.get("text",""),
                        res_chunks=res.get("chunks") or [],
                        asr_pipeline=asr,
                        prompts_json_path=report_prompts_path,
                        template_key="expert_compte_rendu_v1",
                        chunk_chars=6000,
                        max_new_tokens=700,
                        temperature=0.4,
                        top_p=0.9,
                    )
                except Exception as e:
                    print(f"[WARN] résumé_safe voxtral échoué: {e}")
                    summary_text = ""
                payload["chat_summary"] = summary_text

                if summary_text and export_chat_csv:
                    if chat_csv.exists():
                        try:
                            chat_csv.unlink()
                        except Exception:
                            pass
                    with _open_csv_for_excel(chat_csv, encoding=excel_encoding) as (f, used_chat_csv):
                        f.write(f"sep={csv_sep}\r\n")
                        w = csv.writer(f, delimiter=csv_sep, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
                        w.writerow(["type","contenu"])
                        for line in summary_text.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            safe_line = _sanitize_for_cp1252(line) if excel_encoding == "cp1252" else _sanitize_for_encoding(line, excel_encoding)
                            w.writerow(["bullet", safe_line])
                    payload["chat_csv_path"] = str(used_chat_csv)

                if summary_text and export_chat_docx:
                    try:
                        from docx import Document
                        chat_docx = outp / f"{stem_tag}(chat).docx"
                        if chat_docx.exists():
                            try:
                                chat_docx.unlink()
                            except Exception:
                                pass
                        doc = Document()
                        doc.add_heading(f"Résumé - {wav_path.name}", level=1)
                        for line in summary_text.splitlines():
                            if line.strip():
                                doc.add_paragraph(line.strip())
                        doc.save(str(chat_docx))
                        payload["chat_docx_path"] = str(chat_docx)
                    except Exception as e:
                        print(f"[WARN] DOCX non écrit: {e} (pip install python-docx)")



        # ---- logs + timing (chemin standard)
        t_after_exports = time.perf_counter()
        file_size_bytes = os.path.getsize(audio_path)

        if not audio_dur_s:
            try:
                data_probe, sr_probe = sf.read(audio_path, always_2d=False)
                if isinstance(data_probe, np.ndarray) and data_probe.ndim == 2:
                    data_probe = data_probe.mean(axis=1)
                audio_dur_s = float(len(np.asarray(data_probe))) / float(sr_probe)
            except Exception:
                audio_dur_s = None

        t_total = time.perf_counter() - t0
        rtf = (audio_dur_s / t_total) if (audio_dur_s and t_total > 0) else None
        kbps = (file_size_bytes / 1024.0) / t_total if t_total > 0 else None
        seg_rate = (len(res.get("chunks") or []) / t_total) if t_total > 0 else None

        payload["timing"] = {
            "total_s": round(t_total, 3),
            "audio_duration_s": (round(audio_dur_s, 3) if audio_dur_s else None),
            "rtf": (round(rtf, 3) if rtf else None),
            "throughput_kBps": (round(kbps, 1) if kbps else None),
            "segments_per_s": (round(seg_rate, 3) if seg_rate else None),
        }
        payload["timing_detail"] = {
            "prep_s": round(t_prep - t0, 3),
            "asr_s": round(t_after_asr - t_prep, 3),
            "exports_s": round(t_after_exports - t_after_asr, 3),
        }
        app.logger.info(f"[ASR] Durée totale = {time.time() - start_total:.1f} sec")

        log_appel({
            "route": "asr_voxtral",
            "audio_path": audio_path,
            "model_key": model_key,
            "timestamps": timestamps,
            "lang": lang,
            "chunk": chunk,
            "stride": stride,
            "cpu": force_cpu,
            "no4bit": not use4bit,
            "diarize": diarize,
            "text_len": len(payload.get("text","")),
            "export_srt": want_srt,
            "export_vtt": want_vtt,
            "temperature": temperature,
            "top_p": top_p,
            "max_new_tokens": max_new_tokens,
            "silence_split": silence_split,
            "auto_chunk_used": False,
            "output_dir": out_dir,
            "output_dir_rule": out_dir_rule,            

        })

        return jsonify(payload)

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500






@app.route("/voxtral_chat", methods=["POST"])
def voxtral_chat_route():
    if not is_authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        data = request.get_json(silent=True) or {}
        if not data:
            app.logger.warning("%s: JSON vide/non décodable", request.path)

        # Sélection modèle ASR / pipeline (GPU si non forcé CPU)
        model_key      = data.get("model_key", DEFAULT_ASR)
        max_new_tokens = int(data.get("max_new_tokens", 600))
        force_cpu      = bool(data.get("cpu", False))
        use4bit        = not bool(data.get("no4bit", False))

        if model_key not in models_index or models_index[model_key].get("type") != "asr":
            return jsonify({"error": f"model_key invalide: {model_key}"}), 400

        # Exports optionnels
        out_dir          = data.get("output_csv_dir")
        audio_path_hint  = data.get("audio_path")  # pour nommage éventuel
        export_chat_csv  = bool(data.get("export_chat_csv",  False))
        export_chat_docx = bool(data.get("export_chat_docx", False))

        # ---- Pipeline (cache + lock)
        key = (model_key, use4bit, force_cpu)
        if key not in VOXTRAL_LOCKS:
            VOXTRAL_LOCKS[key] = threading.Lock()
        with VOXTRAL_LOCKS[key]:
            if key not in VOXTRAL_PIPELINES:
                VOXTRAL_PIPELINES[key], _ = create_voxtral_pipeline(
                    model_key=model_key, load_in_4bit=use4bit, force_cpu=force_cpu
                )
            asr = VOXTRAL_PIPELINES[key]

        # ------------------------------
        # MODES D’UTILISATION
        # ------------------------------
        mode       = (data.get("mode") or "chat").lower()
        csv_path   = data.get("csv_path")  # NEW
        raw_text   = data.get("text")      # option: résumé d’un texte brut
        template_k = data.get("template_key") or data.get("report_prompts_template_key") or "expert_compte_rendu_v1"
        prompts_p  = data.get("report_prompts_path")  # peut être None (fallback auto)

        # Paramètres « long text summarize »
        chunk_chars     = int(data.get("chunk_chars", 6000))
        summary_tokens  = int(data.get("summary_max_new_tokens", 700))

        # ------------------------------
        #  A) MODE RÉSUMÉ depuis CSV
        # ------------------------------
        if mode == "summarize" and csv_path:
            chunks = _load_asr_csv_to_chunks(csv_path)
            summary = summarize_text_safely_with_voxtral(
                res_text="",
                res_chunks=chunks,
                asr_pipeline=asr,
                prompts_json_path=prompts_p,
                template_key=template_k,
                chunk_chars=chunk_chars,
                max_new_tokens=summary_tokens,
                temperature=0.4,
                top_p=0.9,
            ).strip()

            payload = {"text": summary, "model_key": model_key}
            payload["quant"] = asr.get("quant", "unknown")

            # Exports (CSV / DOCX) — nommage basé sur le CSV source
            if out_dir and (export_chat_csv or export_chat_docx):
                try:
                    outp = Path(out_dir); outp.mkdir(parents=True, exist_ok=True)
                    stem_tag = Path(csv_path).stem  # ex: "Nom(wav)"
                    chat_csv = outp / f"{stem_tag}(chat).csv"

                    # CSV
                    if export_chat_csv:
                        if chat_csv.exists():
                            try: chat_csv.unlink()
                            except Exception: pass
                        excel_encoding = (data.get("excel_encoding") or "utf-8-sig").lower()
                        csv_sep = ';' if (data.get("excel_decimal") or "comma") == "comma" else ','
                        with _open_csv_for_excel(chat_csv, encoding=excel_encoding) as (f, used_chat_csv):
                            f.write(f"sep={csv_sep}\r\n")
                            w = csv.writer(f, delimiter=csv_sep, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
                            w.writerow(["type","contenu"])
                            for line in (summary or "").splitlines():
                                line=line.strip()
                                if not line: continue
                                safe = _sanitize_for_cp1252(line) if excel_encoding=="cp1252" else _sanitize_for_encoding(line, excel_encoding)
                                w.writerow(["bullet", safe])
                        payload["chat_csv_path"] = str(used_chat_csv)

                    # DOCX
                    if export_chat_docx and summary:
                        try:
                            from docx import Document
                            chat_docx = outp / f"{stem_tag}(chat).docx"
                            if chat_docx.exists():
                                try: chat_docx.unlink()
                                except Exception: pass
                            doc = Document()
                            doc.add_heading(f"Résumé - {stem_tag}", level=1)
                            for line in summary.splitlines():
                                if line.strip():
                                    doc.add_paragraph(line.strip())
                            doc.save(str(chat_docx))
                            payload["chat_docx_path"] = str(chat_docx)
                        except Exception as e:
                            print(f"[WARN] DOCX non écrit: {e} (pip install python-docx)")

                except Exception as e:
                    print(f"[WARN] Export chat (CSV/DOCX) échoué: {e}")

            log_appel({"route": "voxtral_chat", "mode": "summarize_csv", "model_key": model_key, "text_len": len(summary)})
            return jsonify(payload)

        # ------------------------------
        #  B) MODE RÉSUMÉ depuis TEXTE brut
        # ------------------------------
        if mode == "summarize" and (raw_text and not csv_path):
            summary = summarize_text_safely_with_voxtral(
                res_text=raw_text,
                res_chunks=[],
                asr_pipeline=asr,
                prompts_json_path=prompts_p,
                template_key=template_k,
                chunk_chars=chunk_chars,
                max_new_tokens=summary_tokens,
                temperature=0.4,
                top_p=0.9,
            ).strip()

            payload = {"text": summary, "model_key": model_key}
            payload["quant"] = asr.get("quant", "unknown")

            # Exports éventuels (nommage générique)
            if out_dir and (export_chat_csv or export_chat_docx):
                try:
                    outp = Path(out_dir); outp.mkdir(parents=True, exist_ok=True)
                    stem_tag = "chat_summary"
                    if audio_path_hint:
                        wav_path = Path(audio_path_hint)
                        stem_tag = f"{_safe_stem(wav_path)}{_ext_tag(wav_path)}"

                    if export_chat_csv:
                        chat_csv = outp / f"{stem_tag}(chat).csv"
                        if chat_csv.exists():
                            try: chat_csv.unlink()
                            except Exception: pass
                        excel_encoding = (data.get("excel_encoding") or "utf-8-sig").lower()
                        csv_sep = ';' if (data.get("excel_decimal") or "comma") == "comma" else ','
                        with _open_csv_for_excel(chat_csv, encoding=excel_encoding) as (f, used_chat_csv):
                            f.write(f"sep={csv_sep}\r\n")
                            w = csv.writer(f, delimiter=csv_sep, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
                            w.writerow(["type","contenu"])
                            for line in (summary or "").splitlines():
                                line=line.strip()
                                if not line: continue
                                safe = _sanitize_for_cp1252(line) if excel_encoding=="cp1252" else _sanitize_for_encoding(line, excel_encoding)
                                w.writerow(["bullet", safe])
                        payload["chat_csv_path"] = str(used_chat_csv)

                    if export_chat_docx and summary:
                        try:
                            from docx import Document
                            chat_docx = outp / f"{stem_tag}(chat).docx"
                            if chat_docx.exists():
                                try: chat_docx.unlink()
                                except Exception: pass
                            doc = Document()
                            doc.add_heading("Résumé", level=1)
                            for line in summary.splitlines():
                                if line.strip(): doc.add_paragraph(line.strip())
                            doc.save(str(chat_docx))
                            payload["chat_docx_path"] = str(chat_docx)
                        except Exception as e:
                            print(f"[WARN] DOCX non écrit: {e}")

                except Exception as e:
                    print(f"[WARN] Export chat (texte) échoué: {e}")

            log_appel({"route": "voxtral_chat", "mode": "summarize_text", "model_key": model_key, "text_len": len(summary)})
            return jsonify(payload)

        # ------------------------------
        #  C) MODE CHAT (COMPORTEMENT EXISTANT)
        # ------------------------------
        messages = data.get("messages") or []
        if not messages:
            return jsonify({"error": "Champ 'messages' manquant pour mode 'chat'. Utilise 'mode':'summarize' avec 'csv_path' ou 'text'."}), 400

        names_hint = data.get("names_hint") or _read_lines(GRIDS_DIR/"proper_names.txt")
        if names_hint:
            prelude = "Noms propres à conserver : " + ", ".join(names_hint[:100])
            messages = [{"role":"system","content": prelude}] + messages

        out = voxtral_chat(messages, asr, max_new_tokens=max_new_tokens).strip()
        payload = {"text": out, "model_key": model_key, "quant": asr.get("quant", "unknown")}
        
        # Exports éventuels (comme avant)
        if out_dir and (export_chat_csv or export_chat_docx):
            try:
                outp = Path(out_dir); outp.mkdir(parents=True, exist_ok=True)
                stem_tag = "chat_summary"
                if audio_path_hint:
                    wav_path = Path(audio_path_hint)
                    stem_tag = f"{_safe_stem(wav_path)}{_ext_tag(wav_path)}"

                if export_chat_csv:
                    chat_csv = outp / f"{stem_tag}(chat).csv"
                    if chat_csv.exists():
                        try: chat_csv.unlink()
                        except Exception: pass
                    with chat_csv.open("w", encoding="utf-8", newline="") as f:
                        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
                        w.writerow(["type", "contenu"])
                        for line in out.splitlines():
                            line = line.strip()
                            if line:
                                w.writerow(["bullet", line])
                    payload["chat_csv_path"] = str(chat_csv)

                if export_chat_docx:
                    try:
                        from docx import Document
                        doc = Document()
                        doc.add_heading("Résumé", level=1)
                        for line in out.splitlines():
                            if line.strip():
                                doc.add_paragraph(line.strip())
                        chat_docx = outp / f"{stem_tag}(chat).docx"
                        if chat_docx.exists():
                            try: chat_docx.unlink()
                            except Exception: pass
                        doc.save(str(chat_docx))
                        payload["chat_docx_path"] = str(chat_docx)
                    except Exception as e:
                        print(f"[WARN] DOCX non écrit: {e}")

            except Exception as e:
                print(f"[WARN] Export chat échoué: {e}")

        log_appel({"route": "voxtral_chat", "mode": "chat", "model_key": model_key, "messages_count": len(messages), "text_len": len(out)})
        return jsonify(payload)

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ===================================================
#           Récap des champs JSON acceptés (ASR)
# ===================================================
#
#  Basique: audio_path, model_key, timestamps, lang, chunk, stride, cpu, no4bit
#  Génération: temperature, top_p, max_new_tokens, batch_size
#  Silences: silence_split, silence_top_db, silence_min_ms
#  Diarisation: diarize, hf_token, diar_options → { "max_speakers", "min_speaker_duration", "collar", "allow_overlap" }
#  Vocabulaire: vocab_hint (list[str]), glossary_path (str)
#  Exports: export_srt, export_vtt
#
# ===================================================
# gpt4all_flask.py — AJOUTS

# -------------------------------------------------------------
# Inférence des intitulés de pièces (depuis OCR CSV / texte)
# -------------------------------------------------------------

PIECE_REGEX = re.compile(
    r"(?:pi[eè]ce|p\.?|n[°o])\s*([0-9]{1,3})\s*[:\-\.,]?\s*(.+)",
    re.IGNORECASE
)

DATE_REGEX = re.compile(r"\b([0-3]?\d[/\-][0-1]?\d[/\-][12]\d{3})\b")
CODE_PARTIE_REGEX = re.compile(r"(?:partie|code)\s*[:\-]?\s*([0-9]{1,3})", re.IGNORECASE)


def _read_ocr_csv_text(csv_path: str) -> str:
    p = Path(csv_path)
    if not p.exists():
        return ""

    lines = []
    with p.open("r", encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter=";")
        next(r, None)  # header
        for row in r:
            if len(row) >= 3 and row[2].strip():
                lines.append(row[2].strip())
    return "\n".join(lines)


def _extract_pieces(text: str) -> dict[int, str]:
    pieces: dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip()
        m = PIECE_REGEX.search(line)
        if not m:
            continue

        no = int(m.group(1))
        titre = re.sub(r"\s+", " ", m.group(2)).strip()

        # filtrage titres trop vides
        if len(titre) < 3:
            continue

        # garder le premier titre trouvé, ou remplacer si nouveau plus informatif
        if no not in pieces or len(titre) > len(pieces[no]):
            pieces[no] = titre[:240]
    return pieces

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _extract_first_date(text: str) -> str | None:
    m = DATE_REGEX.search(text)
    return m.group(1) if m else None


def _extract_code_partie(text: str) -> str | None:
    m = CODE_PARTIE_REGEX.search(text)
    return m.group(1) if m else None


@app.route("/infer_piece_titles", methods=["POST"])
def infer_piece_titles():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}
    sources = data.get("sources") or []
    max_piece_no = int(data.get("max_piece_no") or 200)

    full_text = ""
    used = []
    for s in sources:
        csv_path = (s or {}).get("csv_path")
        text_path = (s or {}).get("text_path")

        chunk = ""
        if text_path:
            p = Path(text_path)
            if p.exists():
                chunk = p.read_text(encoding="utf-8", errors="ignore")
                used.append({"text_path": str(p)})
        elif csv_path:
            chunk = _read_ocr_csv_text(csv_path)
            if chunk.strip():
                used.append({"csv_path": str(Path(csv_path))})

        if chunk.strip():
            full_text += "\n" + chunk

    if not full_text.strip():
        return jsonify({"ok": False, "error": "Aucun texte exploitable depuis les sources fournies."}), 400

    pieces = _extract_pieces(full_text)
    date = _extract_first_date(full_text)
    code_partie = _extract_code_partie(full_text)

    pieces = {k: v for k, v in pieces.items() if 1 <= k <= max_piece_no}

    return jsonify({
        "ok": True,
        "pieces": pieces,
        "date": date,
        "code_partie": code_partie,
        "used_sources": used,
    })


@app.route("/ocr", methods=["POST"])
def ocr_route():
    if DISABLE_OCR:
        return jsonify({"error": "OCR indisponible sur ce serveur (dépendances manquantes)."}), 503
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}
    if request.is_json and not data:
        app.logger.warning("%s: JSON vide/non décodable (Content-Type JSON)", request.path)

    project = (data.get("project_id") or "").strip()
    cfg = rm = None
    if project:
        cfg = load_project_config(project)
        rm  = load_remote_map(project)

    # Chemins (absolus, ou relatifs via project_id)
    input_path = data.get("input_path")
    output_dir = data.get("output_dir")

    if project:
        if not input_path and data.get("rel_input"):
            input_path = resolve_path(cfg, rm, data["rel_input"], context="pcfixe")
        if not output_dir and data.get("rel_output"):
            output_dir = resolve_path(cfg, rm, data["rel_output"], context="pcfixe")

    if not input_path or not output_dir:
        return jsonify({"error": "input_path et output_dir sont requis (ou rel_input/rel_output + project_id)"}), 400

    # 🔐 Interdiction de sortir de la racine projet (pcfixe) si project_id fourni
    if project:
        root = get_root_for_context(cfg or {}, rm or {}, context="pcfixe")
        if not root:
            return jsonify({"error": "Racine pcfixe introuvable (roots/remote_map)"}), 400

        root_norm = os.path.normcase(os.path.normpath(root.rstrip("\\/") + "\\"))
        for p in [input_path, output_dir]:
            p_norm = os.path.normcase(os.path.normpath(p))
            if not p_norm.startswith(root_norm):
                return jsonify({"error": "Chemin hors racine projet interdit"}), 400

    # Options OCR
    opts = OcrOptions(
        lang = data.get("lang", "fra"),
        psm  = data.get("psm"),
        oem  = data.get("oem"),
        dpi  = data.get("dpi", 300),
        denoise   = bool(data.get("denoise", True)),
        threshold = bool(data.get("threshold", True)),
        deskew    = bool(data.get("deskew", True)),
        return_hocr = bool(data.get("return_hocr", False)),
        threshold_method=data.get("threshold_method","adaptive")
    )

    # (optionnel) post-traitement LLM
    post_llm = bool(data.get("postprocess_with_llm", False))
    model_name = data.get("model_name") or DEFAULT_LLM
    system_prompt = get_system_prompt()
    generation_params = {
        k: data.get(k, PARAMS.get(k))
        for k in ["temperature", "top_p", "top_k", "repeat_penalty", "max_tokens"]
    }
    gen = make_gen_kwargs(generation_params)

    try:
        # 1) OCR
        res = run_ocr(input_path=input_path, out_dir=output_dir, opts=opts)

        # 2) Post-traitement LLM (facultatif)
        llm_text_path = None
        if post_llm:
            maybe_switch_model(model_name)

            csv_path = Path(res["csv_path"])
            lines = []
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                r = csv.reader(f, delimiter=";")
                next(r, None)  # header
                for row in r:
                    if len(row) >= 3:
                        lines.append(row[2])
            raw_text = "\n".join(lines).strip()

            gloss = load_json_safe(GRIDS_DIR / "proper_names_glossary.json")

            def _apply_gloss(s: str) -> str:
                if not gloss:
                    return s
                for src, tgt in gloss.items():
                    s = re.sub(r"\b" + re.escape(src) + r"\b", tgt, s, flags=re.IGNORECASE)
                return s

            raw_text = _apply_gloss(raw_text)

            prompt = data.get("postprocess_prompt") or (
                "Nettoie le texte OCR (orthographe minimale, fusion des césures), "
                "restitue des paragraphes cohérents sans inventer de contenu."
            )
            prompt_final = f"{system_prompt}\n{prompt}\n\n=== TEXTE OCR ===\n{raw_text}"

            with BACKEND_LOCK:
                resp = llm(prompt_final, **gen)

            c0 = (resp.get("choices") or [{}])[0]
            clean_text = (c0.get("text") or c0.get("content") or "").strip()
            clean_text = _apply_gloss(clean_text)

            llm_text_path = str(Path(output_dir) / (Path(input_path).stem + "_postLLM.txt"))
            Path(llm_text_path).write_text(clean_text, encoding="utf-8")

        payload = {
            "ok": True,
            "docx_path": res["docx_path"],
            "csv_path": res["csv_path"],
            "hocr_paths": res.get("hocr_paths", []),
            "pages": res["pages"]
        }
        if post_llm:
            payload["post_llm_text_path"] = llm_text_path

        # Log minimal
        log_appel({
            "route": "ocr",
            "input": input_path,
            "output": output_dir,
            "pages": res["pages"],
            "with_llm": post_llm
        })

        return jsonify(payload)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/ocr_auto", methods=["POST"])
def ocr_auto_route():
    if DISABLE_OCR:
        return jsonify({"error": "OCR indisponible sur ce serveur (dépendances manquantes)."}), 503
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}
    # Ne warn que si le client a explicitement tenté du JSON
    if request.is_json and not data:
        app.logger.warning("%s: JSON vide/non décodable (Content-Type JSON)", request.path)
    input_path = data.get("input_path")
    output_dir = data.get("output_dir")
    grid_name  = data.get("grid_name", DEFAULT_GRID_NAME)
    lang = data.get("lang", "fra")
    return_hocr = bool(data.get("return_hocr", False))
    overrides = data.get("overrides", {}) or {}

    if not input_path or not output_dir:
        return jsonify({"error": "input_path et output_dir sont requis"}), 400

    grid_path = (GRIDS_DIR / grid_name).resolve()
    if not grid_path.exists():
        return jsonify({"error": f"Grille introuvable: {grid_name}"}), 404

    try:
        # 1) charger la grille baseline
        grid = json.loads(grid_path.read_text(encoding="utf-8"))

        # 2) appliquer les overrides en mémoire (sans toucher au fichier baseline)
        for topkey in ("sampling", "scoring"):
            if topkey in overrides and isinstance(overrides[topkey], dict):
                base = grid.get(topkey, {})
                grid[topkey] = _deep_update(base, overrides[topkey])

        variants = grid.get("variants", [])
        vu = overrides.get("variants_update", [])
        for op in vu:
            if "append" in op and isinstance(op["append"], dict):
                variants.append(op["append"])
            if "match" in op and "set" in op and isinstance(op["match"], dict) and isinstance(op["set"], dict):
                for v in variants:
                    if all(v.get(k) == val for k, val in op["match"].items()):
                        v.update(op["set"])
        grid["variants"] = variants

        # 3) exécuter avec une grille temporaire
        tmp_grid_path = (GRIDS_DIR / f"__runtime_{int(time.time())}.json")
        tmp_grid_path.write_text(json.dumps(grid, ensure_ascii=False, indent=2), encoding="utf-8")

        res = run_ocr_auto(
            input_path=input_path,
            out_dir=output_dir,
            grid_path=str(tmp_grid_path),
            lang=lang,
            return_hocr=return_hocr
        )

        res["grid_name"] = grid_name
        res["overrides_used"] = overrides

        try:
            tmp_grid_path.unlink(missing_ok=True)
        except Exception:
            pass

        log_appel({
            "route": "ocr_auto",
            "input": input_path,
            "output": output_dir,
            "selected_variant": res.get("selected_variant", {}),
            "pages": res.get("pages", 0),
            "grid_name": grid_name,
            "with_overrides": bool(overrides)
        })
        return jsonify(res)

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


 # remarque choix voxtral ===========================================================
 # Si contrôle fin souhaité de max_speakers, min_speaker_duration, etc., il faudra compléter  
 # transcribe_with_diarization(...) dans voxtral_utils.py pour passer ces options au pipeline
 # transcribe_with_diarization(...) dans voxtral_utils.py pour passer ces options au pipeline
 # token HF pourrait suffir.
 # ================================================================================
 # Valeurs conseillées (stables)
 # Transcription pure : timestamps=True, chunk=30s, stride=5s, lang="fr" (ou auto), température 0 coté serveur
 # Diarisation : commencer avec max_speakers=8, min_speaker_duration=0.35, overlap=False.
 # Vocabulaire :
 # vocab_hint = 1 terme par ligne (noms propres, sigles BTP, sociétés, etc.).
 # glossary_path = JSON de corrections canoniques (ex: {"DTU": "DTU", "polyane": "polyane", "SikaTop": "SikaTop"}).
 # ==================================================================================

@app.route("/convert_to_csv_batch", methods=["POST"])
def convert_to_csv_batch():
    if not is_authorized(request): return jsonify({"error":"unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    if not data:
        app.logger.warning("%s: JSON vide/non décodable", request.path)
    src = Path(data.get("src_dir","")); dst = Path(data.get("dst_dir",""))
    if not src.exists(): return jsonify({"error": f"src_dir introuvable: {src}"}), 400
    dst.mkdir(parents=True, exist_ok=True)


    converted = []; errors = []
    for f in src.rglob("*"):
        try:
            if f.suffix.lower() in {".xlsx", ".xls"}:
                df = pd.read_excel(f); df.to_csv(dst/f"{f.stem}.csv", index=False)
                converted.append(f.name)

#-----------------------------------------------
            elif f.suffix.lower() in {".csv"}:
                try:
                    # on laisse pandas deviner le séparateur (tab, ;, , …)
                    df = pd.read_csv(f, sep=None, engine="python")

                    if _is_probably_asr_csv(df):
                        # CSV de diarisation ASR → nettoyage
                        df_clean = _clean_asr_diar_csv(df)
                        # on force le TSV, cohérent avec vos fichiers ASR
                        df_clean.to_csv(dst / f.name, sep="\t", index=False)
                    else:
                        # autre type de CSV → copie sans toucher
                        (dst / f.name).write_bytes(f.read_bytes())

                    converted.append(f.name)
                except Exception as e:
                    # en cas de souci, on retombe sur une copie brute
                    (dst / f.name).write_bytes(f.read_bytes())
                    converted.append(f.name)
                    errors.append(f"{f.name}: nettoyage ASR échoué ({e})")

#-------------------------------------------------

            elif f.suffix.lower() in {".docx"}:
                doc = docx.Document(str(f))
                text = "\n".join(p.text for p in doc.paragraphs)
                pd.DataFrame({"text":[text]}).to_csv(dst/f"{f.stem}.csv", index=False)
                converted.append(f.name)
            elif f.suffix.lower() in {".pdf"}:
                # PDF natifs (texte), pas de scan → OCR le traite ailleurs
                rows = []
                with pdfplumber.open(str(f)) as pdf:
                    for p in pdf.pages:
                        t = p.extract_text() or ""
                        if t.strip():
                            rows.append({"page": p.page_number, "text": t})
                if rows:
                    pd.DataFrame(rows).to_csv(dst/f"{f.stem}.csv", index=False)
                    converted.append(f.name)
        except Exception as e:
            errors.append(f"{f.name}: {e}")
    return jsonify({"ok": True, "converted": converted, "errors": errors})

@app.route("/health", methods=["GET"])
def health():

    def check_mod(name: str, attr: str = "__version__"):
        """Retourne {ok, version?, ...} pour un module Python."""
        try:
            m = importlib.import_module(name)
            ver = getattr(m, attr, "ok")
            info = {"ok": True, "version": str(ver)}
            if name == "torch":
                try:
                    cuda_ok = bool(getattr(m.cuda, "is_available")())
                    devs = int(getattr(m.cuda, "device_count")()) if cuda_ok else 0
                    info.update({"cuda": cuda_ok, "cuda_device_count": devs})
                except Exception:
                    pass
            return info
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Flags (si tu les exportes depuis le .bat) ; sinon lus directement de l'env.
    DISABLE_OCR = os.getenv("DISABLE_OCR", "0") == "1"
    DISABLE_DIARIZATION = os.getenv("DISABLE_DIARIZATION", "0") == "1"

    # Modules
    mods = {
        "flask":    check_mod("flask"),
        "chromadb": check_mod("chromadb"),
        "numpy":    check_mod("numpy"),
        "cv2":      check_mod("cv2"),
        "torch":    check_mod("torch"),
    }

    # Pyannote (diarisation) est optionnel
    try:
        mods["pyannote.audio"] = check_mod("pyannote.audio")
    except Exception as e:
        mods["pyannote.audio"] = {"ok": False, "error": str(e)}

    # Binaire Tesseract
    tess_bin = shutil.which("tesseract")
    tess = {
        "ok": bool(tess_bin),
        "path": tess_bin or None,
        "TESSDATA_PREFIX": os.environ.get("TESSDATA_PREFIX"),
    }

    out = {
        "ok": True,  # sera éventuellement dégradé ci-dessous
        "app": "gpt4all_flask",
        "python": sys.version,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "flags": {
            "DISABLE_OCR": DISABLE_OCR,
            "DISABLE_DIARIZATION": DISABLE_DIARIZATION,
        },
        "modules": mods,
        "binaries": {"tesseract": tess},
    }

    # Agrégation du statut "ok"
    # 1) Modules de base
    if not all(info.get("ok", False) for k, info in mods.items() if k in ("flask", "chromadb", "numpy", "torch")):
        out["ok"] = False

    # 2) OCR : requis seulement si non désactivé
    if not DISABLE_OCR:
        if not mods["cv2"]["ok"] or not tess["ok"]:
            out["ok"] = False

    # 3) Diarisation : requis seulement si non désactivé
    if not DISABLE_DIARIZATION:
        if not mods.get("pyannote.audio", {}).get("ok", False):
            out["ok"] = False

    return jsonify(out)



@app.route("/index_chroma_from_csv", methods=["POST"])
def index_chroma_from_csv():
    if not is_authorized(request): return jsonify({"error":"unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    if not data:
        app.logger.warning("%s: JSON vide/non décodable", request.path)
    csv_dir = data.get("csv_dir"); collection = data.get("collection")
    chroma_dir = data.get("chroma_dir")
    project_id = (data.get("project_id") or "").strip() or None
    if not csv_dir or not collection:
        return jsonify({"error":"csv_dir et collection requis"}), 400
    enable_pseudonym = bool(data.get("enable_pseudonym", False))
    from rag_vector_utils import upsert_csv_folder_into_chroma
    res = upsert_csv_folder_into_chroma(
        csv_dir=csv_dir,
        collection_name=collection,
        chroma_dir=chroma_dir,
        enable_pseudonym=enable_pseudonym,
        project_id=project_id,
    )
    out = {"ok": True}
    out.update(res)  # upserted, pseudonymized, aliases_created, report_path, collection
    return jsonify(out)

@app.route("/export_rag_to_chroma", methods=["POST"])
def export_rag_to_chroma():
    if not is_authorized(request): return jsonify({"error":"unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    if not data:
        app.logger.warning("%s: JSON vide/non décodable", request.path)

    project = data.get("project")
    if not project: return jsonify({"error":"project requis"}), 400

    # Appel programmatique du script export_to_chroma.py
    import subprocess, sys
    script = Path(__file__).with_name("scripts").joinpath("export_to_chroma.py")
    cmd = [sys.executable, str(script), "--project", project]
    if data.get("use_v1"): cmd += ["--use_v1"]
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=3600)
        # essaye UTF-8 sinon replis CP-1252, sans planter:
        try:
            out = raw.decode("utf-8", errors="replace")
        except Exception:
            out = raw.decode("cp1252", errors="replace")
        return jsonify({"ok": True, "log": out})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": e.output}), 500

@app.route("/pseudonym_map", methods=["GET"])
def pseudonym_map():
    if not is_authorized(request): return jsonify({"error":"unauthorized"}), 401
    alias = request.args.get("alias")
    if not alias: return jsonify({"error":"alias manquant"}), 400
    from pseudonymizer import load_registry, depseudonymize
    reg = load_registry()
    name = depseudonymize(alias, reg)
    return jsonify({"found": bool(name), "name": name})

@app.route("/pseudonym_purge", methods=["POST"])
def pseudonym_purge():
    if not is_authorized(request): return jsonify({"error":"unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    if not data:
        app.logger.warning("%s: JSON vide/non décodable", request.path)    
    name = data.get("name")
    if not name: return jsonify({"error":"name manquant"}), 400
    from pseudonymizer import load_registry, save_registry, purge_person
    reg = load_registry()
    ok = purge_person(name, reg)
    save_registry(reg)
    # (option) déclencher ici une purge ciblée dans Chroma selon vos métadonnées
    return jsonify({"ok": ok})




@app.route("/upload_file", methods=["POST"])
def upload_file():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    try:
        f = request.files.get("file")
        if f is None:
            return jsonify({"error": "Aucun fichier (champ 'file')."}), 400

        project_id = (request.form.get("project_id") or "").strip()
        area = (request.form.get("area") or "").strip().lower()  # ex: asr_in, ocr_out, rag_pc, rag_vec
        subdir = (request.form.get("subdir") or "").strip() or None
        filename = (request.form.get("filename") or "").strip() or f.filename
        overwrite = (str(request.form.get("overwrite") or "false").lower() == "true")

        if not project_id:
            return jsonify({"error": "project_id obligatoire."}), 400
        if not filename:
            return jsonify({"error": "filename obligatoire."}), 400

        # Résoudre le dossier cible depuis projets_index.json + projet_config.json
        out_dir = _project_area_dir_from_index(project_id, area, subdir=subdir)
        dst_path = (out_dir / Path(filename).name).resolve()

        if (not overwrite) and dst_path.exists():
            return jsonify({"error": "Fichier existe déjà (overwrite=false).", "path": str(dst_path)}), 409

        # Écriture atomique
        file_bytes = f.read()
        tmp_path = dst_path.with_suffix(dst_path.suffix + ".part")
        with open(tmp_path, "wb") as w:
            w.write(file_bytes)
        os.replace(tmp_path, dst_path)
        file_sha256 = _sha256_file_bytes(file_bytes)

        try:
            _register_uploaded_file_doc(
                project_id=project_id,
                area=area,
                subdir=subdir,
                filename=Path(filename).name,
                dst_path=dst_path,
                file_sha256=file_sha256,
            )
        except Exception as e:
            app.logger.warning("/upload_file: trace doc_uid non ecrite: %s", e)

        return jsonify({
            "ok": True,
            "project_id": project_id,
            "area": area,
            "subdir": subdir,
            "filename": Path(filename).name,
            "path": str(dst_path),
            "size": len(file_bytes)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/files", methods=["POST"])
def files_alias_upload():
    # proxy local vers upload_file (mêmes règles d’auth)
    if not is_authorized(request): return jsonify({"error": "Clé API invalide"}), 401
    return upload_file()


@app.route("/download_file", methods=["GET"])
def download_file():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    path = request.args.get("path")
    if not path:
        return jsonify({"error": "path manquant"}), 400

    try:
        p = Path(path).resolve()

        # Construire la liste des racines autorisées (résolues)
        projects = _load_projects_index()
        allowed_roots = []
        for proj in projects:
            root_pc = (proj or {}).get("rag_dossier_pcfixe")
            if not root_pc:
                continue
            cfg = _load_project_config_for_server(proj) or {}
            subs = _effective_subdirs(cfg)
            for sub in (
                subs.get("rag_pc_subdir",  "RAG_PC"),
                subs.get("rag_vec_subdir", "RAG_Vectoriel"),
                subs.get("ocr_out_subdir","OCR_Out"),
                subs.get("asr_in_subdir", "ASR_In"),
                subs.get("asr_out_subdir","ASR_Out")
            ):
                allowed_roots.append((Path(root_pc) / sub).resolve())

        # p doit être sous l'une des racines
        try:
            allowed = any(p.is_relative_to(ar) for ar in allowed_roots)  # Python 3.9+
        except AttributeError:
            # Compat <3.9
            def _rel_ok(a, b):
                try:
                    p.relative_to(a); return True
                except Exception:
                    return False
            allowed = any(_rel_ok(ar, p) for ar in allowed_roots)

        if not allowed:
            return jsonify({"error": "Path en dehors des répertoires autorisés"}), 403
        if not p.exists() or not p.is_file():
            return jsonify({"error": "Fichier introuvable"}), 404

        mt, _ = mimetypes.guess_type(str(p))
        return send_file(
            str(p),
            as_attachment=True,
            download_name=p.name,
            mimetype=mt or "application/octet-stream",
            conditional=True
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/scaffold_project_dirs", methods=["POST"])
def scaffold_project_dirs():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id requis"}), 400

    try:
        # Charger project_config.json
        config_path = os.path.join(AFFAIRES_ROOT, project_id, "_Config", "project_config.json")
        if not os.path.exists(config_path):
            return jsonify({"error": "project_config.json introuvable"}), 404

        with open(config_path, "r", encoding="utf-8") as f:
            project_config = json.load(f)

        paths = project_config.get("paths", {})
        root = paths.get("root")

        if not root:
            return jsonify({"error": "Racine absente dans config"}), 400

        created = {}

        for key, rel in paths.items():

            if key == "root":
                continue

            # ignorer les fichiers (sqlite)
            if rel.lower().endswith(".sqlite"):
                continue

            abs_path = os.path.normpath(os.path.join(root, rel))

            # Sécurité : empêcher sortie de la racine
            if not abs_path.startswith(os.path.normpath(root)):
                return jsonify({"error": f"Chemin hors racine interdit: {rel}"}), 400

            os.makedirs(abs_path, exist_ok=True)
            created[key] = abs_path

        return jsonify({
            "ok": True,
            "paths": created
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/create_affaire", methods=["POST"])
def create_affaire_route():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    data = request.get_json(silent=True) or {}
    project_id = (data.get("project_id") or "").strip()
    nom = (data.get("nom") or "").strip()
    _commentaire = data.get("commentaire")

    if not project_id:
        return jsonify({"ok": False, "error": "project_id requis"}), 400

    try:
        create_affaire_fn = _load_create_affaire_callable()
        payload = create_affaire_fn(
            project_id=project_id,
            nom=nom,
            affaires_root=Path(AFFAIRES_ROOT),
        )
        if not isinstance(payload, dict):
            raise RuntimeError("create_affaire.py a renvoyé un format inattendu")
        return jsonify(payload)
    except Exception as e:
        app.logger.error("/create_affaire: echec pour project_id=%s: %s", project_id, e)
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/detect_piece_boundaries", methods=["POST"])
def detect_piece_boundaries():
    if not is_authorized(request):
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    csv_path = data.get("csv_path")
    project  = (data.get("project_id") or "").strip()

    if not csv_path:
        return jsonify({"error": "csv_path requis"}), 400

    # Sécurité racine si project_id fourni
    if project:
        cfg = load_project_config(project)
        rm  = load_remote_map(project)
        root = get_root_for_context(cfg, rm, context="pcfixe")
        if not root:
            return jsonify({"error": "Racine pcfixe introuvable"}), 400

        root_norm = os.path.normcase(os.path.normpath(root.rstrip("\\/") + "\\"))
        p_norm = os.path.normcase(os.path.normpath(csv_path))
        if not p_norm.startswith(root_norm):
            return jsonify({"error": "Chemin hors racine projet interdit"}), 400

    if not Path(csv_path).exists():
        return jsonify({"error": "csv introuvable"}), 404

    piece_regex = re.compile(
        r"^\s*(?:pi[eè]ce|p\.?|n[°o])\s*([0-9]{1,3})\b",
        re.IGNORECASE
    )

    anti_context_regex = re.compile(r"\b(?:voir|cf|annexe|réf)\b", re.IGNORECASE)

    page_lines = {}  # page -> list of lines
    last_page = 0

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        r = csv.reader(f, delimiter=";")
        next(r, None)
        for row in r:
            if len(row) < 3:
                continue
            try:
                page = int(row[0])
            except Exception:
                continue
            text = row[2].strip()
            last_page = max(last_page, page)
            if not text:
                continue
            page_lines.setdefault(page, []).append(text)

    boundaries = {}

    for page in sorted(page_lines.keys()):
        lines = page_lines[page]

        # On ne regarde que les 5 premières lignes
        for line in lines[:5]:

            if len(line) > 120:
                continue

            if anti_context_regex.search(line):
                continue

            m = piece_regex.search(line)
            if m:
                numero = int(m.group(1))

                # sécurité : ignorer si ligne trop longue (probablement phrase normale)
                if len(line.split()) > 15:
                    continue

                if numero not in boundaries:
                    boundaries[numero] = page
                break
    if not boundaries:
        return jsonify({"ok": True, "pieces": []})

    # Tri par page de début
    sorted_items = sorted(boundaries.items(), key=lambda x: x[1])

    pieces = []
    for i, (numero, start_page) in enumerate(sorted_items):
        if i + 1 < len(sorted_items):
            end_page = sorted_items[i + 1][1] - 1
        else:
            end_page = last_page

        pieces.append({
            "numero": numero,
            "start_page": start_page,
            "end_page": end_page
        })

    return jsonify({"ok": True, "pieces": pieces})


@app.route("/api/split_pdf", methods=["POST"])
def split_pdf():
    if not is_authorized(request):
        return jsonify({"error":"unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    inp     = data.get("input_path")
    outdir  = data.get("output_dir")
    project = (data.get("project_id") or "").strip()

    cfg = rm = None
    if (not inp or not outdir) and project:
        cfg = load_project_config(project)
        rm  = load_remote_map(project)
        if not inp and data.get("rel_input"):
            inp = resolve_path(cfg, rm, data["rel_input"], context="pcfixe")
        if not outdir and data.get("rel_output"):
            outdir = resolve_path(cfg, rm, data["rel_output"], context="pcfixe")

    # 🔐 Si project_id est fourni : charger cfg/rm et interdire tout chemin hors racine (pcfixe)
    root = None
    root_norm = None
    if project:
        if cfg is None:
            cfg = load_project_config(project)
        if rm is None:
            rm = load_remote_map(project)

        root = get_root_for_context(cfg, rm, context="pcfixe")
        if not root:
            return jsonify({"ok": False, "error": "Racine pcfixe introuvable (roots/remote_map)"}), 400

        root_norm = os.path.normcase(os.path.normpath(root.rstrip("\\/") + "\\"))

        for p in [inp, outdir]:
            if p:
                p_norm = os.path.normcase(os.path.normpath(p))
                if not p_norm.startswith(root_norm):
                    return jsonify({"ok": False, "error": "Chemin hors racine projet interdit"}), 400

    pieces = data.get("pieces") or data.get("segments") or []
    dry_run = bool(data.get("dry_run", False))
    overwrite = bool(data.get("overwrite", False))

    # ✅ validations indispensables
    if not inp or not outdir:
        return jsonify({"ok": False, "error": "input_path et output_dir requis"}), 400
    if not pieces:
        return jsonify({"ok": False, "error": "pieces requis"}), 400

    p_in = Path(inp)
    if not p_in.exists():
        return jsonify({"ok": False, "error": f"input_path introuvable: {inp}"}), 404

    os.makedirs(outdir, exist_ok=True)

    reader = PdfReader(str(p_in))
    n_pages = len(reader.pages)
    in_sha = _sha256_file(str(p_in))

    for i, pc in enumerate(pieces, start=1):
        try:
            sp = int(pc["start_page"])
            ep = int(pc["end_page"])
        except Exception:
            return jsonify({"ok": False, "error": f"piece #{i}: start_page/end_page requis"}), 400
        if sp < 1 or ep < sp:
            return jsonify({"ok": False, "error": f"piece #{i}: bornes incohérentes"}), 400
        if ep > n_pages:
            return jsonify({"ok": False, "error": f"piece #{i}: end_page({ep}) > nb_pages({n_pages})"}), 400
        if not str(pc.get("filename", "")).strip():
            return jsonify({"ok": False, "error": f"piece #{i}: filename requis"}), 400

    planned = []
    for pc in pieces:
        out_path = str(Path(outdir) / pc["filename"])
        planned.append({"piece": pc, "out_path": out_path, "exists": Path(out_path).exists()})

    manifest_dir = data.get("manifest_dir")
    if not manifest_dir and project:
        if cfg is None or rm is None:
            cfg = load_project_config(project)
            rm  = load_remote_map(project)
        try:
            manifest_dir = resolve_path(cfg, rm, "manifests", context="pcfixe")
        except Exception:
            manifest_dir = None

    if project and manifest_dir:
        p_norm = os.path.normcase(os.path.normpath(manifest_dir))
        # root_norm a déjà un "\" final
        if not p_norm.startswith(root_norm):
            return jsonify({"ok": False, "error": "Chemin manifest_dir hors racine projet interdit"}), 400

    if dry_run:
        return jsonify({
            "ok": True,
            "dry_run": True,
            "input": {"path": str(p_in), "sha256": in_sha, "pages": n_pages},
            "outputs": planned
        })

    created = []
    for pc in pieces:
        out_path = Path(outdir) / pc["filename"]
        if out_path.exists() and not overwrite:
            return jsonify({"ok": False, "error": f"Fichier existe déjà: {out_path} (overwrite=false)"}), 409

        w = PdfWriter()
        start = int(pc["start_page"]) - 1
        end = int(pc["end_page"]) - 1
        for pno in range(start, end + 1):
            w.add_page(reader.pages[pno])

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            w.write(f)

        created.append({
            "piece": pc,
            "out_path": str(out_path),
            "sha256": _sha256_file(str(out_path)),
            "pages": (end - start + 1),
        })

    if project:
        try:
            created, _ = _register_split_pdf_outputs(
                project_id=project,
                input_path=str(p_in),
                input_sha256=in_sha,
                outputs=created,
            )
        except Exception as e:
            app.logger.warning("/api/split_pdf: trace doc_uid non ecrite: %s", e)

    manifest = {
        "ok": True,
        "dry_run": False,
        "input": {"path": str(p_in), "sha256": in_sha, "pages": n_pages},
        "outputs": created,
        "ts": _now_stamp(),
    }


    if manifest_dir:
        os.makedirs(manifest_dir, exist_ok=True)
        mpath = Path(manifest_dir) / f"manifest_split_{p_in.stem}_{manifest['ts']}.json"
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        manifest["manifest_path"] = str(mpath)

    return jsonify(manifest)

@app.route("/api/split_pdf_batch", methods=["POST"])
def split_pdf_batch():
    if not is_authorized(request): return jsonify({"error":"unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    jobs = data.get("jobs") or []
    stop_on_error = bool(data.get("stop_on_error", False))
    out = {"ok": True, "results": []}
    for j in jobs:
        try:
            with app.test_request_context(json=j, headers=request.headers):
                resp = split_pdf()
                if isinstance(resp, tuple): resp, code = resp
                else: code = 200
                res_json = resp.get_json() if hasattr(resp, "get_json") else {}
                out["results"].append(res_json | {"http_status": code, "input": j.get("input_path")})
                if code != 200 and stop_on_error:
                    out["ok"] = False; break
        except Exception as e:
            out["ok"] = False
            out["results"].append({"ok": False, "error": str(e), "input": j.get("input_path")})
            if stop_on_error: break
    return jsonify(out)

@app.route("/debug_paths", methods=["GET"])
def debug_paths():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    project_id = (request.args.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"error": "project_id manquant"}), 400
    cfg = load_project_config(project_id)
    rm  = load_remote_map(project_id)
    keys = ["paperless_inbox","queue_ocr","splits","csv_rag","manifests","sqlite"]
    out = {"pcfixe": {}, "laptop": {}, "nas": {}}
    for ctx in out.keys():
        for k in keys:
            out[ctx][k] = resolve_path(cfg, rm, k, context=ctx)
    return jsonify({"ok": True, "paths": out})


# **************************************************************
# COMFYUI 
# **************************************************************



@sd_bp.route("/sd_generate", methods=["POST"])
def sd_generate():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    p = request.get_json(silent=True) or {}


    # Décide si on tente un boot : paramètre > config > défaut False
    ensure_flag = p.get("ensure_comfy", None)
    want_boot = bool(ensure_flag) if ensure_flag is not None else COMFY_AUTO_BOOT

    if not ensure_comfy_ui(want_boot=want_boot, max_wait_s=45):
        return jsonify({
            "error": "ComfyUI non disponible",
            "hint": "Lance ComfyUI ou rappelle avec \"ensure_comfy\": true",
            "auto_boot": COMFY_AUTO_BOOT
        }), 503

    # (optionnel) démarrage à la demande
 
    prompt   = p.get("prompt","")
    negative = p.get("negative_prompt","")
    model_key= p.get("model_key","sd15")     # "sd15" | "sdxl_base" | "sdxl_refiner"
    width  = max(64, int(p.get("width", 768)))
    height = max(64, int(p.get("height", 768)))
    steps    = int(p.get("steps",28))
    cfg      = float(p.get("cfg",6.5))
    n_images = int(p.get("n",1))
    project  = p.get("project_id","default")
    seed_raw = p.get("seed", -1)
    try:
        seed = int(seed_raw)
    except Exception:
        seed = -1
    # En interne, on convertit -1 (seed aléatoire) en seed valide pour ComfyUI
    if seed < 0:
        # au choix : seed déterministe = 0, ou aléatoire :
        seed = random.randrange(0, 2**32 - 1)
  
    if model_key == "sdxl_base":
        ckpt = r"sdxl\sd_xl_base_1.0.safetensors"
    elif model_key == "sdxl_refiner":
        ckpt = r"sdxl\sd_xl_refiner_1.0.safetensors"
    else:
        ckpt = r"sd15\v1-5-pruned.safetensors"

    # ---- Choix du mode et du dossier de sortie ----
    # global_mode=True force le mode "global" (OpenWebUI/AppFlowy) même si project_id est renseigné
    global_mode = bool(p.get("global_mode", False))
    area = p.get("area")  # optionnel si tu veux router par table d’aires

    # Si le client fournit 'output_dir', on le respecte en priorité
    explicit_outdir = p.get("output_dir")

    outdir = _resolve_sd_outdir(
        project_id=project,
        explicit_outdir=explicit_outdir,
        global_mode=global_mode,
        area=area
    )
    outdir.mkdir(parents=True, exist_ok=True)

    # ----- Workflow ComfyUI conforme (ids numériques + liens ["id", slot]) -----
    # Nodes:
    # 1: CheckpointLoaderSimple -> outputs: [MODEL, CLIP, VAE] => slots 0,1,2
    # 2: CLIPTextEncode(positive)  (clip: ["1", 1])
    # 3: CLIPTextEncode(negative)  (clip: ["1", 1])
    # 4: EmptyLatentImage
    # 5: KSampler (model: ["1",0], positive: ["2",0], negative: ["3",0], latent_image: ["4",0])
    # 6: VAEDecode (samples: ["5",0], vae: ["1",2])
    # 7: SaveImage (images: ["6",0])

    graph = {
        "1": { "class_type": "CheckpointLoaderSimple",
               "inputs": { "ckpt_name": ckpt } },
        "2": { "class_type": "CLIPTextEncode",
               "inputs": { "text": prompt, "clip": ["1", 1] } },
        "3": { "class_type": "CLIPTextEncode",
               "inputs": { "text": negative, "clip": ["1", 1] } },
        "4": { "class_type": "EmptyLatentImage",
               "inputs": { "width": width, "height": height, "batch_size": n_images } },
        "5": { "class_type": "KSampler",
               "inputs": {
                   "seed": seed, "steps": steps, "cfg": cfg,
                   "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                   "model": ["1", 0], "positive": ["2", 0],
                   "negative": ["3", 0], "latent_image": ["4", 0]
               } },
        "6": { "class_type": "VAEDecode",
               "inputs": { "samples": ["5", 0], "vae": ["1", 2] } },
        "7": { "class_type": "SaveImage",
               "inputs": { "images": ["6", 0], "filename_prefix": f"{project}_" } }
    }

    payload = {
        "prompt": graph,
        "client_id": project  # optionnel: identifie le client
    }

    # ----- Soumission -----
    try:
        r = requests.post(f"{COMFY_URL}/prompt", json=payload, timeout=COMFY_TIMEOUT)
        # En cas d’erreur 400, logge le détail Comfy pour debug rapide
        if not r.ok:
            try:
                err_txt = r.text[:500]
            except Exception:
                err_txt = "no body"
            return jsonify({"error": f"Soumission ComfyUI échouée (HTTP {r.status_code})",
                            "body": err_txt}), 502
        resp_json = r.json() or {}
        prompt_id = resp_json.get("prompt_id")
        if not prompt_id:
            return jsonify({"error": "ComfyUI n'a pas renvoyé de prompt_id", "resp": resp_json}), 502
    except requests.HTTPError as e:
        return jsonify({"error": f"Soumission ComfyUI échouée: {e}",
                        "body": getattr(e.response, 'text', '')[:500]}), 502
    except Exception as e:
        return jsonify({"error": f"Soumission ComfyUI échouée: {e}"}), 502


    # ----- Poll /history -----
    deadline = time.time() + float(p.get("history_timeout_s", 90))
    images = []
    while time.time() < deadline:
        try:
            h = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=15)
            if h.ok and h.headers.get("Content-Type","").startswith("application/json"):
                hist = h.json() or {}
                entry = hist.get(prompt_id) or hist  # tolérant
                outputs = (entry.get("outputs") if isinstance(entry, dict) else {}) or {}
                for node_out in outputs.values():
                    for img in node_out.get("images", []) or []:
                        fn = img.get("filename")
                        if fn:
                            images.append({
                                "filename": fn,
                                "subfolder": img.get("subfolder", ""),
                                "type": img.get("type", "output")
                            })
                if images:
                    break
        except Exception:
            pass
        time.sleep(1)


    # Option: lien proxifié via /comfyui/image (si tu as ajouté cette route)
    # Sinon, on renvoie les infos pour que le client récupère via /view
    resp = {
        "project_id": project,
        "params": {"model_key": model_key, "width": width, "height": height, "steps": steps, "cfg": cfg, "n": n_images, "seed": seed},
        "prompt_id": prompt_id,
        "images": images,
        "view_urls": [
            f"{COMFY_URL}/view?filename={quote(i['filename'] or '')}&subfolder={quote(i.get('subfolder',''))}&type={quote(i.get('type','output'))}"
            for i in images if i.get("filename")
        ]
    }
    resp["proxied_urls"] = [
        f"/comfyui/image?filename={quote(i['filename'] or '')}&subfolder={quote(i.get('subfolder',''))}&type={quote(i.get('type','output'))}"
        for i in images if i.get("filename")
    ]
    base = request.host_url.rstrip("/")
    resp["proxied_urls_abs"] = [
        f"{base}/comfyui/image?filename={quote(i['filename'] or '')}"
        f"&subfolder={quote(i.get('subfolder',''))}&type={quote(i.get('type','output'))}"
        for i in images if i.get("filename")
    ]

    # Log (optionnel)
    try:
        log_appel({
            "route": "sd_generate",
            "project_id": project,
            "prompt": prompt,
            "params": resp["params"],
            "prompt_id": prompt_id,
            "images": images[:10],
        })
    except Exception:
        pass

    return jsonify(resp), 200


@app.route("/comfyui/prompt", methods=["POST"])
def comfyui_prompt():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    """
    Corps attendu:
    {
      "workflow": {...}  # graph ComfyUI complet
      "replacements": {"<PROMPT>":"ma description", "<SEED>": 1234},  # optionnel
      "wait": false,     # si true, on poll /history pour 1 image
      "history_timeout_s": 60
    }
    """
    try:
        data = request.get_json(silent=True) or {}
        workflow = data.get("workflow")
        if not isinstance(workflow, dict):
            return jsonify({"error": "workflow (dict) requis"}), 400
        wait = bool(data.get("wait"))
        hto = float(data.get("history_timeout_s", 60))
        # remplacements simples dans le JSON (prompt/seed etc.)
        repl = data.get("replacements") or {}
        def _replace_in_obj(o):
            if isinstance(o, dict):
                return {k: _replace_in_obj(v) for k,v in o.items()}
            if isinstance(o, list):
                return [_replace_in_obj(x) for x in o]
            if isinstance(o, str):
                for k,v in repl.items():
                    o = o.replace(str(k), str(v))
                return o
            return o
        wf = _replace_in_obj(workflow)

        # soumission à ComfyUI
        r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": wf}, timeout=COMFY_TIMEOUT)
        r.raise_for_status()
        resp = r.json()
        prompt_id = resp.get("prompt_id") or resp.get("promptId") or None

        out = {"ok": True, "prompt_id": prompt_id, "raw": resp, "wait": wait, "history_timeout_s": hto}

        # Attente (simple) si demandé
        if data.get("wait"):
            deadline = time.time() + float(data.get("history_timeout_s", 60))
            found = None
            while time.time() < deadline:
                h = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=COMFY_TIMEOUT)
                if h.status_code == 200 and h.json():
                    found = h.json()
                    break
                time.sleep(1.0)
            out["history"] = found
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": f"ComfyUI prompt échec: {e}"}), 500


@app.route("/comfyui/image", methods=["GET"])
def comfyui_image():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401
    """
    Query: ?filename=XXX&subfolder=&type=output
    Re-proxy vers /view
    """
    try:
        filename = request.args.get("filename")
        subfolder = request.args.get("subfolder", "")
        typ = request.args.get("type", "output")
        if not filename:
            return jsonify({"error": "filename requis"}), 400
        prox = requests.get(f"{COMFY_URL}/view", params={"filename": filename, "subfolder": subfolder, "type": typ}, timeout=COMFY_TIMEOUT)
        if prox.status_code != 200:
            return jsonify({"error": f"ComfyUI view status {prox.status_code}"}), 502
        # renvoi binaire
        return send_file(
            io.BytesIO(prox.content),
            mimetype=prox.headers.get("Content-Type") or "image/png",
            download_name=filename,
            as_attachment=False
        )
    except Exception as e:
        return jsonify({"error": f"ComfyUI image échec: {e}"}), 500

#************************************************************
@app.route("/comfyui/history", methods=["GET"])
def comfyui_history():
    if not is_authorized(request):
        return jsonify({"error": "Clé API invalide"}), 401

    pid = request.args.get("prompt_id")
    if not pid:
        return jsonify({"error": "prompt_id requis"}), 400

    # 1) Récupère l’historique natif ComfyUI
    try:
        r = requests.get(f"{COMFY_URL}/history/{pid}", timeout=COMFY_TIMEOUT)
        r.raise_for_status()
        hist = r.json() or {}
    except Exception as e:
        return jsonify({"error": f"ComfyUI history échec: {e}"}), 500

    # Format Comfy: { "<pid>": { "outputs": { node: { "images":[{filename,subfolder,type}] } }, "status": {...} } }
    entry   = hist.get(pid) or hist
    outputs = (entry.get("outputs") or {}) if isinstance(entry, dict) else {}
    status  = (entry.get("status") or {}) if isinstance(entry, dict) else {}

    images = []
    for node_out in outputs.values():
        for img in (node_out.get("images") or []):
            images.append({
                "filename": img.get("filename"),
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output")
            })

    # Si rien encore, on renvoie l’état (pending / running)
    if not images:
        return jsonify({
            "prompt_id": pid,
            "status": status or {"status_str": "pending"},
            "images": [],
            "message": "Aucune image prête pour le moment."
        }), 200

    # 2) Choix du dossier de sortie
    explicit_outdir = request.args.get("outdir")  # ex: C:\AI_Data\sd_outputs\projet_X
    project         = request.args.get("project_id", "default")
    date_dir        = dt.datetime.utcnow().strftime("%Y-%m-%d")

    if explicit_outdir:
        outdir = Path(explicit_outdir)
        mode   = "explicit"
    elif project and project != "default":
        outdir = Path(AFFAIRES_ROOT) / project / "AI_Gen" / date_dir
        mode   = "affaire"
    else:
        outdir = Path(RAG_BASE) / "AI_Gen" / date_dir
        mode   = "global"

    _safe_mkdir(outdir)

    # 3) Copie depuis ComfyUI/output -> outdir choisi
    saved_paths = _copy_comfy_output_to(outdir, images)

    # 4) URLs de visualisation
    base = request.host_url.rstrip("/")
    view_urls = [
        f"{COMFY_URL}/view?filename={quote(i['filename'] or '')}&subfolder={quote(i.get('subfolder',''))}&type={quote(i.get('type','output'))}"
        for i in images if i.get("filename")
    ]
    proxied_urls = [
        f"/comfyui/image?filename={quote(i['filename'] or '')}&subfolder={quote(i.get('subfolder',''))}&type={quote(i.get('type','output'))}"
        for i in images if i.get("filename")
    ]
    proxied_urls_abs = [f"{base}{u}" for u in proxied_urls]

    return jsonify({
        "prompt_id": pid,
        "status": status or {"status_str": "success"},
        "mode": mode,
        "project_id": project,
        "outdir": str(outdir),
        "images": images,
        "saved_paths": saved_paths,
        "view_urls": view_urls,
        "proxied_urls": proxied_urls,
        "proxied_urls_abs": proxied_urls_abs
    }), 200


# =========================
# Démarrage
# =========================
# --- Démarrage de l'application Flask ---
if __name__ == "__main__":
    threading.Thread(target=warmup, daemon=True).start()
    print("🔗 Routes Flask disponibles :")
    app.register_blueprint(sd_bp)  # Enregistrer le blueprint 'sd'
    app.register_blueprint(bp)     # Enregistrer le blueprint 'search'


    for r in app.url_map.iter_rules():
        print("  ", r)

    
    limits = _config_dict_section(config, "http_limits", path=CONFIG_PATH)

    app.config.update(
        MAX_CONTENT_LENGTH   = _config_int(limits.get("max_content_length", 200 * 1024 * 1024), 200 * 1024 * 1024, "http_limits.max_content_length", path=CONFIG_PATH),
        MAX_FORM_MEMORY_SIZE = _config_int(limits.get("max_form_memory_size", 50 * 1024 * 1024), 50 * 1024 * 1024, "http_limits.max_form_memory_size", path=CONFIG_PATH),
        MAX_FORM_PARTS       = _config_int(limits.get("max_form_parts", 10_000), 10_000, "http_limits.max_form_parts", path=CONFIG_PATH),
    )

    log.info("FINAL_HTTP_LIMITS: MAX_FORM_MEMORY_SIZE=%s MAX_CONTENT_LENGTH=%s MAX_FORM_PARTS=%s",
            app.config.get("MAX_FORM_MEMORY_SIZE"),
            app.config.get("MAX_CONTENT_LENGTH"),
            app.config.get("MAX_FORM_PARTS"))

    from waitress import serve
    serve(app, host="0.0.0.0", port=PORT, threads=1)

