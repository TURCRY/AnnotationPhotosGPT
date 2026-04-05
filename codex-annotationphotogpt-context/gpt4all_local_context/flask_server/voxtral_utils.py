# voxtral_utils.py
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import importlib.util
import inspect
import torch
import tempfile
import logging
from pyannote.audio import Pipeline
import numpy as np
import soundfile as sf
from transformers import VoxtralProcessor, VoxtralForConditionalGeneration
# ⬇️ ajouter cet import en haut du fichier
try:
    from transformers import BitsAndBytesConfig
    _HAS_BNB = True
except Exception:
    _HAS_BNB = False
    BitsAndBytesConfig = None


from rapidfuzz import fuzz, process
try:
    import librosa
except Exception:
    librosa = None

import re, os, csv, datetime as dt
try:
    from scipy.signal import resample_poly
except Exception:
    resample_poly = None
from contextlib import contextmanager
from typing import Dict, List, Optional, Any
__all__ = [
    # ... tes fonctions existantes ...
    "_read_lines",
    "load_json_safe",
    "_label_speakers_from_rules",
]
import io
import threading
from functools import lru_cache

_PYANNOTE_PIPELINES: dict[tuple, Pipeline] = {}
_PYANNOTE_LOCKS: dict[tuple, threading.Lock] = {}
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=UserWarning)

# --- Intégration chemins locaux (utilise helper_paths comme le serveur Flask) ---
try:
    from helper_paths import load_paths  # fourni dans ton repo
except Exception:
    load_paths = None


def _load_paths() -> Dict[str, str]:
    # Valeurs par défaut si helper_paths indispo
    defaults = {"MODELS_PATH": r"C:\GPT4All_Models"}
    if load_paths is None:
        return defaults
    try:
        return load_paths()
    except Exception:
        return defaults

def _read_models_index(models_path: Path) -> Dict[str, Any]:
    index_path = (models_path / "models_index.json").resolve()
    if not index_path.exists():
        raise FileNotFoundError(f"models_index.json introuvable : {index_path}")
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)



def _resolve_local_dir(model_key: str, model_index: Dict[str, Any], models_path: Path) -> Tuple[Path, Dict[str, Any]]:
    if model_key not in model_index:
        raise ValueError(f"model_key inconnu : {model_key}")
    entry = model_index[model_key]
    directory = entry.get("directory")
    if not directory:
        raise ValueError(f"Champ 'directory' manquant pour {model_key} dans models_index.json")
    local_dir = (models_path / directory).resolve()
    if not local_dir.exists():
        raise FileNotFoundError(f"Dossier modèle introuvable pour {model_key} : {local_dir}")
    return local_dir, entry


def _infer_hub_id(local_dir: Path, manifest: Dict[str, Any] | None) -> str:
    # 1) si présent dans models_index.json -> manifest.hub_id / model_id
    if manifest:
        hub_id = manifest.get("hub_id") or manifest.get("model_id")
        if hub_id:
            return str(hub_id)

    # 2) heuristique depuis le nom du dossier modèle
    name = local_dir.name
    if "Voxtral-Mini-3B-2507" in name:
        return "mistralai/Voxtral-Mini-3B-2507"
    if "Voxtral-Small-24B-2507" in name:
        return "mistralai/Voxtral-Small-24B-2507"

    # 3) fallback
    return "mistralai/Voxtral-Mini-3B-2507"


def normalize_asr_pipeline(asr):
    # Déjà un dict normalisé ?
    if isinstance(asr, dict):
        return asr
    # Ancien format tuple/list (processor, model, device, torch_dtype, hub_id)
    if isinstance(asr, (tuple, list)) and len(asr) >= 5:
        processor, model, device, torch_dtype, hub_id = asr[:5]
        return {
            "processor": processor,
            "model": model,
            "device": device,
            "torch_dtype": torch_dtype,
            "hub_id": hub_id,
        }
    
    raise TypeError(f"ASR pipeline inattendu: {type(asr)}")




def get_pyannote_pipeline_cached(
    *,
    hf_token: str | None,
    device: str = "cuda",
    diar_model_id: str = "pyannote/speaker-diarization-3.1",
) -> Pipeline:
    # clé de cache : modèle + device + token présent/absent
    # (ne mettez pas le token en clair dans la clé/les logs)
    key = (diar_model_id, device, bool(hf_token))

    if key not in _PYANNOTE_LOCKS:
        _PYANNOTE_LOCKS[key] = threading.Lock()

    with _PYANNOTE_LOCKS[key]:
        if key in _PYANNOTE_PIPELINES:
            return _PYANNOTE_PIPELINES[key]

        # 1) Chargement 1 seule fois
        pipe = Pipeline.from_pretrained(diar_model_id, use_auth_token=hf_token)

        # 2) Déplacement 1 seule fois
        try:
            pipe.to(device)
        except Exception:
            # si jamais .to() n'existe pas selon versions
            pass

        _PYANNOTE_PIPELINES[key] = pipe
        return pipe

from functools import lru_cache

@lru_cache(maxsize=2)
def _get_pyannote_pipeline(use_cuda: bool) -> Pipeline:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN manquant pour pyannote.")

    pipe = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=token,
    )  # type: ignore

    if use_cuda and torch.cuda.is_available():
        try:
            pipe.to(torch.device("cuda"))
            logger.info("[DIAR] Pipeline pyannote déplacé sur CUDA (cache)")
        except Exception as e:
            logger.warning(f"[DIAR] Échec passage CUDA ({e}), utilisation CPU (cache).")
            pipe.to(torch.device("cpu"))
    else:
        pipe.to(torch.device("cpu"))

    return pipe


# --- DIARISATION (pyannote) ---
def diarize_segments(
    audio_path: str | Path,
    *,
    hf_token: str | None = None,
    max_speakers: int | None = None,
    min_speaker_duration: float | None = None,
    min_duration_on: float | None = None,
    collar: float = 0.05,
    allow_overlap: bool = False,
    min_duration_off: float | None = None,
    use_cuda: bool = True,
) -> list[dict]:

    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(f"Fichier audio introuvable : {p}")

    token = hf_token or os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN manquant pour pyannote.")

    device = "cuda" if (use_cuda and torch.cuda.is_available()) else "cpu"
    logger.info(f"[DIAR] Utilisation pyannote (cache) sur device = {device}")

    # ✅ pipeline pyannote en cache
    pipeline = _get_pyannote_pipeline(use_cuda=(device == "cuda"))

    # Map alias → native
    _min_on = min_duration_on if min_duration_on is not None else min_speaker_duration

    # Candidate kwargs (on filtre plus bas selon la version)
    candidate_kwargs: dict[str, Any] = {
        "num_speakers": max_speakers,
        "min_duration_on": float(_min_on) if _min_on is not None else None,
        "min_duration_off": float(min_duration_off) if min_duration_off is not None else None,
        "collar": float(collar) if collar is not None else None,
        "allow_overlap": bool(allow_overlap),
        "skip_overlap": (not allow_overlap),
    }
    candidate_kwargs = {k: v for k, v in candidate_kwargs.items() if v is not None}

    # Garder uniquement les kwargs supportés par cette version de pyannote
    try:
        allowed = set(inspect.signature(pipeline.apply).parameters.keys())
        kwargs = {k: v for k, v in candidate_kwargs.items() if k in allowed}
    except Exception:
        kwargs = {k: v for k, v in candidate_kwargs.items()
                  if k in {"num_speakers", "min_duration_on", "collar"}}

    # 3) Inférence avec gestion d’erreur CUDA + retry CPU
    try:
        diarization = pipeline(str(p), **kwargs)
    except RuntimeError as e:
        if device == "cuda" and "CUDA" in str(e).upper():
            logger.warning(f"[DIAR] Erreur CUDA, retry CPU : {e}")
            pipeline.to(torch.device("cpu"))
            diarization = pipeline(str(p), **kwargs)
        else:
            raise



    # 4) Conversion en liste de segments
    segments: list[dict] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "start": round(float(turn.start), 3),
            "end":   round(float(turn.end), 3),
            "speaker": speaker,
        })

    segments.sort(key=lambda s: (s["start"], s["end"]))
    return segments


def transcribe_with_diarization(
    audio_path: str | Path,
    asr_pipeline: dict,   # dict normalisé
    *,
    language: str | None = None,
    model_key: str,
    timestamps: bool = True,   # conservé pour compat
    hf_token: str | None = None,
    chunk: int = 30,
    stride: int = 5,
    diar_options: dict | None = None,
    output_csv_dir: str | None = None,
    max_speakers: int | None = None,
    min_speaker_duration: float | None = None,
    min_duration_on: float | None = None,
    collar: float = 0.05,
    allow_overlap: bool = False,
    min_duration_off: float | None = None,
    temperature: float = 0.0,   # ignoré → do_sample=False
    top_p: float | None = None,
    max_new_tokens: int = 256,
) -> dict:
    # 0) Pipeline (unique normalisation)
    asr = normalize_asr_pipeline(asr_pipeline)
    processor   = asr["processor"]
    model       = asr["model"]
    device      = asr.get("device", "cpu")
    torch_dtype = asr.get("torch_dtype", None)
    hub_id      = asr.get("hub_id") or asr.get("model_key")

    # 1) Diarisation (indépendante du pipeline)
    diar = diarize_segments(
        audio_path=audio_path,
        hf_token=hf_token,
        max_speakers=max_speakers,
        min_speaker_duration=min_speaker_duration,
        min_duration_on=min_duration_on,
        min_duration_off=min_duration_off,
        collar=collar,
        allow_overlap=allow_overlap,
    )

    # 2) Sampling rate attendu par le processor
    proc_sr = (
        getattr(processor, "sampling_rate", None)
        or getattr(getattr(processor, "feature_extractor", None), "sampling_rate", None)
        or 16000
    )
    proc_sr = int(proc_sr)

    # 3) Lire et resampler l’audio UNE SEULE FOIS vers proc_sr
    data, sr = sf.read(str(audio_path), always_2d=False)
    data, sr = _ensure_mono_16k(data, sr, target_sr=proc_sr)  # renvoie float32 mono
    sr = proc_sr

    def _lang_ok(x: Optional[str]) -> str:
        x = (x or "").strip().lower()
        return "fr" if x in ("", "auto", "autodetect", "auto-detect") else x
    lang = _lang_ok(language)

    chunks: list[dict] = []
    parts: list[str] = []

    for seg in diar:
        s = max(0, int(seg["start"] * sr))
        e = max(0, int(seg["end"]   * sr))
        if e <= s or (e - s) < int(0.08 * sr):   # < 80 ms → ignorer
            continue

        cut = data[s:e]
        if getattr(cut, "ndim", 1) > 1:
            cut = cut.mean(axis=1)
        if cut.size == 0:
            continue
        if cut.dtype != np.float32:
            cut = cut.astype(np.float32, copy=False)

        # 4) Appel processor — via helper (LISTES 1:1)
        inputs = _apply_voxtral_request(
            processor,
            audio=cut,
            sr=sr,
            lang=lang,
            hub_id=hub_id,
        )

        # 5) Mise sur device/dtype sans casser les indices
        if isinstance(inputs, dict):
            for k, v in list(inputs.items()):
                if hasattr(v, "to"):
                    if k == "input_ids":
                        if v.dtype not in (torch.long, torch.int32, torch.int64):
                            v = v.to(dtype=torch.long)
                        inputs[k] = v.to(device)
                    else:
                        inputs[k] = v.to(device, dtype=torch_dtype) if torch_dtype is not None else v.to(device)
        elif hasattr(inputs, "to"):
            inputs = inputs.to(device)

        # 6) Génération (déterministe)
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )

        # 7) Décodage (ignore le prompt)
        cut_tok = inputs["input_ids"].shape[1] if "input_ids" in inputs else 0
        decoded = processor.batch_decode(outputs[:, cut_tok:], skip_special_tokens=True)
        text = (decoded[0] if decoded else "").strip()

        if text:
            parts.append(text)

        chunks.append({
            "start":   float(seg["start"]),
            "end":     float(seg["end"]),
            "speaker": seg.get("speaker"),
            "text":    text,
        })

    return {"text": " ".join(parts).strip(), "chunks": chunks}


def _apply_voxtral_request(
    processor,
    *,
    audio,
    sr=None,
    lang=None,
    hub_id=None,
    sampling_rate=None,
    language=None,
    model_id=None,
):
    """
    Normalise les paramètres pour appeler processor.apply_transcription_request.

    Accepte les deux syntaxes :
      - (sr, lang, hub_id)
      - (sampling_rate, language, model_id)

    et renvoie le dict d'inputs prêt pour model.generate().
    """
    import numpy as np

    # Harmonisation des alias
    if sampling_rate is not None:
        sr = sampling_rate
    if language is not None:
        lang = language
    if model_id is not None:
        hub_id = model_id

    if sr is None:
        raise ValueError("sampling_rate / sr manquant dans _apply_voxtral_request")
    if not lang:
        lang = "fr"

    sr_scalar = int(sr)

    # Ndarray float32 mono
    if not isinstance(audio, np.ndarray):
        audio = np.asarray(audio, dtype=np.float32)
    else:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32, copy=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    audio_list    = [audio]
    format_list   = ["WAV"]
    language_list = [lang]

    # 1) Tentative avec sampling_rate scalaire
    try:
        return processor.apply_transcription_request(
            audio=audio_list,
            format=format_list,
            language=language_list,
            sampling_rate=sr_scalar,
            model_id=hub_id,
        )
    except Exception as e:
        # 2) Fallback: sampling_rate en liste (certaines versions le veulent comme ça)
        try:
            return processor.apply_transcription_request(
                audio=audio_list,
                format=format_list,
                language=language_list,
                sampling_rate=[sr_scalar],
                model_id=hub_id,
            )
        except Exception:
            # On relance l’erreur d’origine pour debug
            raise e


def _load_glossary(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
    
def to_srt(chunks: List[Dict[str, Any]]) -> str:
    def fmt(t):  # seconds -> SRT timestamp
        h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int(round((t - int(t)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines = []
    for i, c in enumerate(chunks, 1):
        lines += [str(i), f"{fmt(c['start'])} --> {fmt(c['end'])}", (c.get('text') or '').strip(), ""]
    return "\n".join(lines)

def to_vtt(chunks: List[Dict[str, Any]]) -> str:
    def fmt(t):
        h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int(round((t - int(t)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    lines = ["WEBVTT", ""]
    for c in chunks:
        lines += [f"{fmt(c['start'])} --> {fmt(c['end'])}", (c.get('text') or '').strip(), ""]
    return "\n".join(lines)

def _normalize_token(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch in "-_./ ")


def apply_glossary_correction(text: str, glossary: dict, *, threshold: int = 90) -> str:
    if not text or not glossary:
        return text
    targets = list(glossary.keys())
    targets_norm = {t: _normalize_token(t) for t in targets}
    tokens = text.split()
    for i, tok in enumerate(tokens):
        norm = _normalize_token(tok)
        if not norm:
            continue
        best = process.extractOne(norm, targets_norm.values(), scorer=fuzz.token_sort_ratio)
        if best and best[1] >= threshold:
            for k, v in targets_norm.items():
                if v == best[0]:
                    tokens[i] = glossary.get(k, tok)
                    break
    return " ".join(tokens)

# voxtral_utils.py

import re
from typing import Dict, List, Optional

# --- helpers ---

def _normalize_token(s: str) -> str:
    # Ta version existante (garde-la si elle gère accents/casse).
    # Ici un exemple minimal :
    return (s or "").strip().lower()

def _load_glossary(path: str) -> Dict[str, str]:
    import json, io
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        # on force str->str
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}

def _preserve_case(src: str, tgt: str) -> str:
    """Applique la casse du 'src' au 'tgt' (simple et robuste)."""
    if not src or not tgt:
        return tgt
    if src.isupper():
        return tgt.upper()
    if src.islower():
        return tgt.lower()
    # Capitalisation type 'Polyane' si src est Capitalized
    if src[0].isupper() and src[1:].islower():
        return tgt[0].upper() + tgt[1:]
    # Sinon on rend la cible telle quelle (casse canonique du glossaire)
    return tgt

def _build_word_regex_from_keys(keys: List[str]) -> re.Pattern:
    """
    Construit une regex 'mot entier' insensible à la casse, 
    en triant par longueur (évite qu'un petit mot capture avant un plus long).
    """
    keys = [k for k in keys if k]  # filtre vides
    if not keys:
        # un pattern qui ne matche rien
        return re.compile(r"(?!x)x")
    # tri long -> court pour éviter les chevauchements
    keys_sorted = sorted(set(keys), key=len, reverse=True)
    pattern = r"\b(" + "|".join(re.escape(k) for k in keys_sorted) + r")\b"
    return re.compile(pattern, flags=re.IGNORECASE)

def _read_lines(path: str) -> List[str]:
    """Lit un fichier texte (UTF-8) et renvoie les lignes non vides, stripées."""
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f.readlines() if ln.strip()]
    except Exception:
        return []
    

def load_json_safe(path: str) -> Dict[str, Any]:
    """Charge un JSON (UTF-8). Renvoie {} si échec."""
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _label_speakers_from_rules(chunks: List[Dict[str, Any]], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Applique des règles de nommage speaker sur les chunks:
      rules = {
        "map": { "SPEAKER_00": "EXPERT", "SPEAKER_01": "MAÎTRE DUPONT" },
        "regex": [
          {"if_text": "(?i)maître dupont|Me\\.?\\s*dupont", "label": "MAÎTRE DUPONT"},
          {"if_text": "(?i)expert\\b", "label": "EXPERT"}
        ]
      }
    - 'map' remappe les noms de locuteurs existants
    - 'regex' renomme selon le texte du segment si cohérent
    """
    if not chunks:
        return chunks

    m = rules.get("map", {}) if isinstance(rules, dict) else {}
    rxs = rules.get("regex", []) if isinstance(rules, dict) else []

    # pré-compile regex
    compiled = []
    for r in rxs:
        pat = r.get("if_text")
        lab = r.get("label")
        if pat and lab:
            try:
                compiled.append((re.compile(pat), str(lab)))
            except re.error:
                continue

    out = []
    for c in chunks:
        spk = c.get("speaker") or ""
        txt = c.get("text") or ""
        new_spk = m.get(spk, spk)  # remap direct si présent

        # sinon, tenter les regex sur le texte
        if new_spk == spk and compiled and txt:
            for (rx, lbl) in compiled:
                if rx.search(txt):
                    new_spk = lbl
                    break

        cc = dict(c)
        cc["speaker"] = new_spk
        out.append(cc)
    return out


# --- ta fonction revue ---

def post_correct_transcript(
    result: dict,
    vocab_hint: Optional[List[str]],
    glossary_path: Optional[str],
    *,
    threshold: int = 88,          # même défaut que chez toi
) -> dict:
    """
    Étapes :
      1) fusionne vocab_hint + glossaire JSON → dict canonique {norm_key: target}
      2) passe 1 : remplacements exacts 'mot-entier' insensibles à la casse (+préservation de casse)
      3) passe 2 : ta correction floue existante (apply_glossary_correction) pour les restes
    """
    # 1) fusion
    canon: Dict[str, str] = {}
    if vocab_hint:
        for term in vocab_hint:
            nk = _normalize_token(term)
            if nk and nk not in canon:
                canon[nk] = term  # cible = forme "canonique" telle que donnée dans la liste
    if glossary_path:
        ext = _load_glossary(glossary_path)
        for k, v in ext.items():
            nk = _normalize_token(k)
            if nk:
                canon[nk] = v  # le JSON "gagne" (souvent plus précis)

    if not canon:
        return result

    # 2) regex 'mot-entier' pour la passe exacte
    rx = _build_word_regex_from_keys(list(canon.keys()))

    def _exact_pass(s: str) -> str:
        if not s:
            return s
        def repl(m: re.Match) -> str:
            src = m.group(0)
            tgt = canon.get(_normalize_token(src), src)
            return _preserve_case(src, tgt)
        return rx.sub(repl, s)

    # 3) appliquer exact, puis flou
    txt = result.get("text", "")
    txt = _exact_pass(txt)
    txt = apply_glossary_correction(txt, canon, threshold=threshold)

    chunks = result.get("chunks") or []
    for c in chunks:
        t = c.get("text", "")
        t = _exact_pass(t)
        t = apply_glossary_correction(t, canon, threshold=threshold)
        c["text"] = t

    result["text"] = txt
    return result


def _normalize_lang(lang: Optional[str]) -> Optional[str]:
    """Retourne un code alpha-2 en minuscules, ou None pour auto-détection.
       On ne passe jamais la chaîne 'auto' à Voxtral/Mistral."""
    if not lang:
        return None
    lang = str(lang).strip().lower()
    return None if lang in ("auto", "auto-detect", "autodetect") else lang



# --- Résumé "chat" robuste (CPU fallback + extractif) ---
def safe_make_summary(transcript_text: str, asr_pipeline: dict, *, max_new_tokens: int = 400) -> str:
    text = (transcript_text or "").strip()
    if not text:
        return ""

    # 1) Tentative avec le modèle (sur CPU pour éviter le CUDA OOM)
    try:
        asr = normalize_asr_pipeline(asr_pipeline)
        processor = asr["processor"]
        model     = asr["model"]

        import torch
        was_cuda = next(model.parameters()).is_cuda if any(p.is_cuda for p in model.parameters()) else False
        try:
            model_cpu = model.to("cpu")
            inputs = processor.apply_chat_template([
                {"role":"system","content":"Résume le dialogue en puces, concis, français."},
                {"role":"user","content": text}
            ])
            # .to('cpu') sans dtype flottant spécifique
            if hasattr(inputs, "to"):
                inputs = inputs.to("cpu")
            with torch.no_grad():
                out = model_cpu.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
            cut = inputs.input_ids.shape[1]
            dec = processor.batch_decode(out[:, cut:], skip_special_tokens=True)
            summ = (dec[0] if dec else "").strip()
            if summ:
                return summ
        finally:
            # On remet le modèle où il était
            if was_cuda:
                model.to("cuda")
            # libère la RAM au cas où
            try:
                import gc, torch
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
    except Exception:
        pass

    # 2) Fallback extractif (rapide CPU)
    #   - coupe en phrases, enlève doublons, prend ~10 meilleures (longueur/variété)
    try:
        import re
        sents = re.split(r'(?<=[\.\?\!])\s+', text)
        sents = [s.strip() for s in sents if s.strip()]
        # dédoublonnage simple
        seen, uniq = set(), []
        for s in sents:
            k = s.lower()
            if k not in seen:
                uniq.append(s)
                seen.add(k)
        # prends ~10 phrases “informatives” (longueur médiane)
        uniq.sort(key=lambda s: (-min(len(s), 220), s))  # heuristique
        pick = uniq[:10]
        if not pick:
            return ""
        bullets = "\n".join(f"- {p}" for p in pick)
        return bullets
    except Exception:
        return ""


# --------------------------------------------------------------------------------------
#                                Création du "pipeline"
# --------------------------------------------------------------------------------------
def create_voxtral_pipeline(
        model_key: str, 
        load_in_4bit: bool=False, 
        force_cpu: bool=False, 
        hub_id_override: str | None=None
    ):
    paths = _load_paths()
    models_path = Path(paths["MODELS_PATH"])
    model_index = _read_models_index(models_path)
    local_dir, entry = _resolve_local_dir(model_key, model_index, models_path)

    use_cuda = torch.cuda.is_available() and (not force_cpu)
    dev   = "cuda" if use_cuda else "cpu"

    # dtype de calcul par défaut
    # - sur GPU: bfloat16 (meilleur perf/stabilité récentes) sinon float16
    # - sur CPU: float32
    if dev == "cuda":
        torch_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    else:
        torch_dtype = torch.float32

    torch.set_float32_matmul_precision("medium")
    if dev == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True

    processor = VoxtralProcessor.from_pretrained(str(local_dir))

    model = None
    quant = "none"

    # ====== ESSAI 4-BIT (si demandé + GPU + bitsandbytes présent) ======
    if dev == "cuda" and load_in_4bit and _HAS_BNB:
        try:
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch_dtype,  # calcul en bf16/fp16
            )
            # device_map="auto" peut offloader une partie en CPU si VRAM courte
            model = VoxtralForConditionalGeneration.from_pretrained(
                str(local_dir),
                quantization_config=bnb_config,
                device_map="auto",               # shard si nécessaire
                low_cpu_mem_usage=True,
                trust_remote_code=True
            )
            quant = "4bit-nf4"
        except Exception as e:
            print(f"[WARN] 4-bit indisponible, fallback en {torch_dtype}: {e}")
            model = None

    # ====== FALLBACK: demi/précision standard sur GPU ou CPU ======
    if model is None:
        model = VoxtralForConditionalGeneration.from_pretrained(
            str(local_dir),
            dtype=torch_dtype,
            low_cpu_mem_usage=True,
            trust_remote_code=True
        )
        model = model.to(dev).eval()

    hub_id = hub_id_override or _infer_hub_id(local_dir, entry.get("manifest"))

    asr_pipeline = {
        "processor":   processor,
        "model":       model,
        "device":      dev,
        "torch_dtype": torch_dtype,
        "hub_id":      hub_id,
        "local_dir":   str(local_dir),
        "model_key":   model_key,
        "quant":       quant,   # <- utile pour debug
    }
    return asr_pipeline, str(local_dir)

def unload_pipeline(asr_pipeline):
    asr = normalize_asr_pipeline(asr_pipeline)
    try:
        del asr["processor"], asr["model"]
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# --- Helpers de nommage / fichiers ---


def _safe_stem(p: Path) -> str:
    # Windows-safe : on remplace les caractères interdits
    return re.sub(r'[<>:"/\\|?*]+', '_', p.stem)

def _ext_tag(p: Path) -> str:
    # "(wav)" "(mp3)" "(m4a)" …
    return f"({p.suffix.lstrip('.').lower()})" if p.suffix else "(audio)"

def _excel_serial_from_datetime(d: dt.datetime) -> float:
    excel_epoch = dt.datetime(1899, 12, 30)  # Excel (Windows)
    delta = d - excel_epoch
    return delta.days + (delta.seconds + delta.microseconds / 1e6) / 86400.0

def _fmt_hms(t: float) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    return f"{h}:{m:02d}:{s:02d}"


# --------------------------------------------------------------------------------------
#                                  Utilitaires audio
# --------------------------------------------------------------------------------------
def _ensure_mono_16k(wave: np.ndarray, sr: int, *, target_sr: int = 16000) -> Tuple[np.ndarray, int]:
    # mono + dtype
    if isinstance(wave, np.ndarray) and wave.ndim == 2:
        wave = wave.mean(axis=1)
    if not isinstance(wave, np.ndarray):
        wave = np.asarray(wave)
    if wave.dtype != np.float32:
        wave = wave.astype(np.float32, copy=False)

    if int(sr) == target_sr:
        return wave, target_sr

    # 1) priorité : SciPy (pas de dépendance resampy)
    if resample_poly is not None:
        up, down = target_sr, int(sr)
        g = np.gcd(up, down)
        up //= g; down //= g
        wave = resample_poly(wave, up, down).astype(np.float32, copy=False)
        return wave, target_sr

    # 2) fallback : essayer librosa SEULEMENT si resampy est vraiment dispo
    if librosa is not None:
        try:
            import resampy  # si absent → on saute
            wave = librosa.resample(y=wave, orig_sr=int(sr), target_sr=target_sr, res_type="kaiser_best").astype(np.float32, copy=False)
            return wave, target_sr
        except Exception:
            pass

    # 3) dernier recours : interpolation linéaire
    dur = len(wave) / float(sr)
    new_len = int(round(dur * target_sr))
    if new_len <= 1:
        return np.zeros((1,), dtype=np.float32), target_sr
    x_old = np.linspace(0.0, 1.0, num=len(wave), dtype=np.float32)
    x_new = np.linspace(0.0, 1.0, num=new_len,    dtype=np.float32)
    wave = np.interp(x_new, x_old, wave).astype(np.float32, copy=False)
    return wave, target_sr


def _load_audio_any(path: Path) -> Tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), always_2d=False)
    if isinstance(data, np.ndarray) and data.dtype != np.float32:
        data = data.astype(np.float32, copy=False)
    return data, int(sr)


def _segment_indices(total_samples: int, sr: int, chunk_s: int, stride_s: Optional[int]) -> List[Tuple[int, int]]:
    if chunk_s <= 0:
        return [(0, total_samples)]
    chunk = int(chunk_s * sr)
    if stride_s is None or stride_s <= 0:
        starts = list(range(0, total_samples, chunk))
        return [(s, min(s + chunk, total_samples)) for s in starts]
    step = int((chunk_s - stride_s) * sr)
    if step <= 0:
        step = max(1, chunk)
    segments = []
    s = 0
    while s < total_samples:
        e = min(s + chunk, total_samples)
        segments.append((s, e))
        if e == total_samples:
            break
        s += step
    return segments

def _split_on_silence(
    wave: np.ndarray,
    sr: int,
    *,
    top_db: int = 30,
    min_silence_len_ms: int = 250,
) -> list[tuple[int, int]]:
    """
    Retourne une liste de (start_idx, end_idx) en échantillons.
    - top_db : seuil d’énergie (relatif) pour considérer un segment comme “voix”
    - min_silence_len_ms : on FUSIONNE deux segments si la pause entre eux est < cette durée
    """
    wave = np.asarray(wave, dtype=np.float32)
    if wave.ndim == 2:  # sécurité
        wave = wave.mean(axis=1)

    min_gap = int(round(sr * (min_silence_len_ms / 1000.0)))

    segments: list[tuple[int, int]] = []

    # 1) Première passe : détection brute
    if librosa is not None:
        try:
            # intervals: array [[start_sample, end_sample], ...]
            intervals = librosa.effects.split(wave, top_db=float(top_db), frame_length=2048, hop_length=512)
            segments = [(int(s), int(e)) for (s, e) in intervals]
        except Exception:
            segments = []
    if not segments:
        # Fallback RMS simple (sans librosa)
        frame = 1024
        hop = 512
        n = len(wave)
        if n <= frame:
            rms = np.array([np.sqrt(np.mean(wave ** 2))], dtype=np.float32)
        else:
            # calcul RMS fenêtre glissante
            frames = 1 + (n - frame) // hop
            rms = np.empty(frames, dtype=np.float32)
            for i in range(frames):
                s = i * hop
                e = s + frame
                rms[i] = float(np.sqrt(np.mean(wave[s:e] ** 2) + 1e-12))
        # seuil basé sur top_db (relatif au max)
        ref = float(rms.max() + 1e-12)
        thr = ref * (10.0 ** (-top_db / 20.0))
        voiced = rms > thr

        # convertit les frames “voix” en intervalles d’échantillons
        segments_raw: list[tuple[int, int]] = []
        i = 0
        while i < len(voiced):
            if voiced[i]:
                j = i + 1
                while j < len(voiced) and voiced[j]:
                    j += 1
                s = i * hop
                e = min(n, j * hop + frame)
                segments_raw.append((s, e))
                i = j
            else:
                i += 1
        segments = segments_raw

    if not segments:
        # rien détecté → tout le fichier
        return [(0, len(wave))]

    # 2) Fusion des segments séparés par une pause courte (< min_gap)
    merged: list[tuple[int, int]] = []
    cur_s, cur_e = segments[0]
    for (s, e) in segments[1:]:
        gap = s - cur_e
        if gap < min_gap:
            # fusionne
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))

    # 3) filtre micro-segments (optionnel) : ici on laisse ASR filtrer <80 ms
    return merged

def _infer_audio_format(path: str) -> str:
    ext = (os.path.splitext(path)[1] or "").lower().lstrip(".")
    # normaliser pour Voxtral
    if ext in ("wav", "wave"): return "WAV"
    if ext in ("mp3",):        return "MP3"
    if ext in ("flac",):       return "FLAC"
    if ext in ("m4a", "mp4", "aac"): return "M4A"
    if ext in ("ogg", "oga"):  return "OGG"
    # fallback générique
    return "WAV"


# --------------------------------------------------------------------------------------
#                                   Transcription
# --------------------------------------------------------------------------------------

def transcribe_audio(
    audio_path: str | Path,
    asr_pipeline: Tuple[Any, Any, str, torch.dtype, str],
    *,
    chunk_length_s: int = 30,
    stride_length_s: Optional[int] = None,
    return_timestamps: bool = False,
    language: Optional[str] = None,
    batch_size: int = 1,          # gardé pour compat, on force 1 pour la stabilité
    temperature: float = 0.0,
    top_p: Optional[float] = None,
    max_new_tokens: int = 1024,
    silence_split: bool = False,
    silence_top_db: int = 30,
    silence_min_ms: int = 250,
    diarize: bool = False,        # ignoré ici (géré par transcribe_with_diarization)
    diar_options: Optional[dict] = None,
) -> Dict[str, Any]:

    # --- pipeline normalisé
    asr = normalize_asr_pipeline(asr_pipeline)
    processor   = asr["processor"]
    model       = asr["model"]
    device      = asr.get("device", "cpu")
    torch_dtype = asr.get("torch_dtype")
    hub_id      = asr.get("hub_id")

    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(f"Fichier audio introuvable : {p}")

    # charge + normalise audio en mono 16 kHz
    wave, sr = _load_audio_any(p)
    wave, sr = _ensure_mono_16k(wave, sr)

    def _lang_ok(x: Optional[str]) -> str:
        x = (x or "").strip().lower()
        return "fr" if x in ("", "auto", "autodetect", "auto-detect") else x

    lang = _lang_ok(language)

    # =========================
    #    MODE SANS TIMESTAMPS
    # =========================
    if not return_timestamps:
        inputs =  _apply_voxtral_request(
            processor,
            audio=wave,                 # listes alignées
            sampling_rate=int(sr),
            language=lang,
            model_id=hub_id,
        )
        # déplacer vers device/dtype sans casser les dtypes entiers
        for k, v in list(inputs.items()):
            if hasattr(v, "to"):
                if k == "input_ids":
                    inputs[k] = v.to(device)  # garder dtype entier (long/int)
                else:
                    inputs[k] = v.to(device, dtype=torch_dtype) if torch_dtype is not None else v.to(device)

        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,              # temperature/top_p souvent ignorés de toute façon
        )
        cut = inputs["input_ids"].shape[1] if "input_ids" in inputs else 0
        dec = processor.batch_decode(outputs[:, cut:], skip_special_tokens=True)
        return {"text": (dec[0].strip() if dec else "")}

    # =========================
    #    MODE AVEC TIMESTAMPS
    # =========================
    if silence_split:
        segs = _split_on_silence(
            wave, sr, top_db=silence_top_db, min_silence_len_ms=silence_min_ms
        )
    else:
        segs = _segment_indices(
            len(wave), sr,
            chunk_length_s if chunk_length_s > 0 else 30,
            stride_length_s
        )

    results: list[dict] = []
    full_text: list[str] = []

    for (s, e) in segs:
        audio_chunk = wave[s:e].astype(np.float32, copy=False)
        # skip micro-chunks (< 80 ms)
        if e <= s or (e - s) < int(0.08 * sr):
            continue
        if audio_chunk.dtype != np.float32:
            audio_chunk = audio_chunk.astype(np.float32, copy=False)

        inputs = _apply_voxtral_request(
            processor,
            audio=audio_chunk,
            sampling_rate=int(sr),
            language=lang,
            model_id=hub_id,
            # selon ta version de processor, ces flags peuvent être ignorés;
            # ils ne cassent pas si non supportés.
            # timestamps=True  # ← la plupart des builds Voxtral n'utilisent pas ce flag ici
        )
        proc_sr = (getattr(processor, "sampling_rate", None)
           or getattr(getattr(processor, "feature_extractor", None), "sampling_rate", None)
           or 16000)
        print(f"[voxtral] processor.sampling_rate = {proc_sr}")

        # move to device / dtype correctement
        for k, v in list(inputs.items()):
            if hasattr(v, "to"):
                if k == "input_ids":
                    inputs[k] = v.to(device)
                else:
                    inputs[k] = v.to(device, dtype=torch_dtype) if torch_dtype is not None else v.to(device)

        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
        cut_tok = inputs["input_ids"].shape[1] if "input_ids" in inputs else 0
        decoded = processor.batch_decode(outputs[:, cut_tok:], skip_special_tokens=True)
        text = (decoded[0] if decoded else "").strip()

        results.append({"start": round(s / sr, 3), "end": round(e / sr, 3), "text": text})
        if text:
            full_text.append(text)

    return {"text": " ".join(full_text).strip(), "chunks": results}


# --------------------------------------------------------------------------------------
#                                   Audio + Text (chat)
# --------------------------------------------------------------------------------------
def voxtral_chat(
    messages: List[Dict[str, Any]],
    asr_pipeline: Tuple[Any, Any, str, torch.dtype, str],
    *,
    max_new_tokens: int = 500,
) -> str:
    asr_pipeline = normalize_asr_pipeline(asr_pipeline)
    processor   = asr_pipeline["processor"]
    model       = asr_pipeline["model"]
    device      = asr_pipeline.get("device", "cpu")
    torch_dtype = asr_pipeline.get("torch_dtype")
    hub_id      = asr_pipeline.get("hub_id")
    # processor, model, device, torch_dtype, _hub_id = asr_pipeline
    inputs = processor.apply_chat_template(messages)
    inputs = inputs.to(device, dtype=torch_dtype)
    outputs = model.generate(**inputs, max_new_tokens=max_new_tokens)
    decoded = processor.batch_decode(outputs[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)
    return decoded[0] if decoded else ""

# --------------------------------------------------------------------------------------
#                                   Intégration côté serveur
#
#   Dans /asr_voxtral, propager simplement les nouveaux champs (optionnels) du JSON à transcribe_audio :
#       temperature, top_p, max_new_tokens, silence_split, silence_top_db, silence_min_ms, batch_size.
#
#  Dans /diarize et /asr_align, exposer hf_token, max_speakers, min_speaker_duration, collar, allow_overlap.
#   Si tu veux un endpoint “SRT/VTT” :
# après la transcription avec timestamps, fais srt = to_srt(res["chunks"]) et renvoie-le (ou en pièce jointe).
#
# --------------------------------------------------------------------------------------
