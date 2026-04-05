# pseudonymizer.py
from __future__ import annotations
import json, hmac, hashlib, os, re
from pathlib import Path
from typing import Dict, Optional

# en tête du fichier
REG_PATH = os.getenv("PSEUDO_REGISTRY", r"D:\GPT4All_Local\rgpd\pseudonyms.json")
KEY_PATH = os.getenv("PSEUDO_KEY",      r"D:\GPT4All_Local\rgpd\pseudonyms.key")

DEFAULT_REGISTRY = Path(REG_PATH)
SECRET_KEY_PATH  = Path(KEY_PATH)


DEFAULT_REGISTRY = Path("D:/GPT4All_Local/rgpd/pseudonyms.json")
SECRET_KEY_PATH = Path("D:/GPT4All_Local/rgpd/pseudonyms.key")

# Remplace NAME_PAT :
NAME_PAT = re.compile(
    r"""
    \b
    (?:
      (?:M(?:me|lle|e)?\.?\s+|Dr\.?\s+|Me\.?\s+)?     # titres facultatifs
    )
    ([A-ZÉÈÊÀÂÎÔÛÇ][A-Za-zÉÈÊÀÂÎÔÛÇïëüöä\-\'’]+)     # prénom (composé accepté)
    \s+
    (?:de\s+|du\s+|d’|d'\s+)?                        # particule facultative
    ([A-ZÉÈÊÀÂÎÔÛÇ][A-Za-zÉÈÊÀÂÎÔÛÇïëüöä\-\'’]+)     # nom (composé accepté)
    \b
    """,
    re.VERBOSE
)

ALIAS_TAG = re.compile(r"⟦PERS_[0-9a-f]{8}⟧")
SRT_TS    = re.compile(r"\d{2}:\d{2}:\d{2}(?:[.,]\d{3})?")
SPEAKER_TAG = re.compile(r"\bSPEAKER[_\-]?\d+\b", re.IGNORECASE)

def _should_skip(segment: str) -> bool:
    # on évite pseudonymisation sur une « zone technique »
    return bool(ALIAS_TAG.search(segment) or SPEAKER_TAG.search(segment))


def _load_secret_key() -> bytes:
    SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SECRET_KEY_PATH.exists():
        SECRET_KEY_PATH.write_bytes(os.urandom(32))  # clé locale non exportée
    return SECRET_KEY_PATH.read_bytes()

def _alias_for(name: str, key: bytes) -> str:
    digest = hmac.new(key, name.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    return f"⟦PERS_{digest}⟧"

def load_registry(path: Path = DEFAULT_REGISTRY) -> Dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}

def save_registry(reg: Dict[str,str], path: Path = DEFAULT_REGISTRY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomique sur NTFS


def ensure_alias(name: str, reg: Dict[str,str], key: bytes) -> str:
    name = " ".join(name.split()).strip()
    if not name: return name
    if name not in reg:
        reg[name] = _alias_for(name, key)
    return reg[name]

def pseudonymize_text(text: str, reg: Dict[str,str], key: bytes) -> str:
    out_lines = []
    for line in text.splitlines():
        if _should_skip(line):
            out_lines.append(line)
            continue
        # éviter de toucher les timestamps bruts
        line_wo_ts = line if not SRT_TS.fullmatch(line.strip()) else line
        def _sub(m):
            full = f"{m.group(1)} {m.group(2)}"
            return ensure_alias(full, reg, key)
        out_lines.append(NAME_PAT.sub(_sub, line_wo_ts))
    return "\n".join(out_lines)


def depseudonymize(alias: str, reg: Dict[str,str]) -> Optional[str]:
    # recherche inverse (usage ponctuel pour vos rapports)
    for k,v in reg.items():
        if v == alias:
            return k
    return None

def purge_person(name: str, reg: Dict[str,str]) -> bool:
    return reg.pop(name, None) is not None
