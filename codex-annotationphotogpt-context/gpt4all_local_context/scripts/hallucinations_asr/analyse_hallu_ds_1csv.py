#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Analyse offline d'un CSV ASR pour proposer des ajouts à hallu_patterns.json
et produire une shortlist de candidats (assistant-like) à valider.

Usage (exemples) :
  python analyse_hallu_csv.py --csv "D:\\...\\J37 Touzeau ... (wav).csv" --patterns "D:\\GPT4All_Local\\config\\hallu_patterns.json" --out "D:\\GPT4All_Local\\config\\_hallu_out"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Dict, List, Tuple, Optional


# Heuristique "assistant-like" (à ajuster au besoin)
HALLU_HINT_REGEX = re.compile(
    r"(je ne comprends pas|je n'ai pas compris|je ne saisis pas|"
    r"pouvez[- ]?vous (préciser|reformuler|répéter)|"
    r"veuillez (préciser|indiquer|reformuler)|"
    r"pour (que|pouvoir|afin de) (je|vous) (puisse|puissiez) (vous )?(aider|répondre)|"
    r"j'ai besoin de plus de contexte|il me faut plus de contexte|"
    r"il semble que vous|"
    r"voici (un )?exemple|note\s*:|"
    r"faites[- ]moi savoir|n'hésitez pas à)",
    re.IGNORECASE
)

# Segmentation simple en phrases (robuste sans spaCy)
SENT_SPLIT_RE = re.compile(r"(?<=[\.\?\!])\s+|[\r\n]+")


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def load_patterns(patterns_path: Path) -> List[str]:
    with patterns_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    subs = cfg.get("substrings", []) or []
    return [str(x).lower().strip() for x in subs if str(x).strip()]


def detect_delimiter(sample: str) -> str:
    # Essai simple ; puis ,
    if sample.count(";") >= sample.count(","):
        return ";"
    return ","


def read_csv_rows(csv_path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    # Lire un petit échantillon pour deviner séparateur
    with csv_path.open("r", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(8192)
    delim = detect_delimiter(sample)

    rows: List[Dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        fieldnames = reader.fieldnames or []
        for r in reader:
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
    return fieldnames, rows


def pick_text_field(fieldnames: List[str]) -> str:
    # Heuristique : vos CSV ont souvent "text" ou "texte"
    lowered = [f.lower().strip() for f in fieldnames]
    for candidate in ("text", "texte", "transcript", "utterance"):
        if candidate in lowered:
            return fieldnames[lowered.index(candidate)]
    # fallback : dernière colonne
    return fieldnames[-1] if fieldnames else "text"


def split_sentences(text: str) -> List[str]:
    txt = (text or "").strip()
    if not txt:
        return []
    parts = [p.strip() for p in SENT_SPLIT_RE.split(txt) if p and p.strip()]
    # réduire micro-fragments
    return [p for p in parts if len(p) >= 8]


def is_covered_by_substrings(sentence: str, substrings: List[str]) -> bool:
    s = sentence.lower()
    return any(sub in s for sub in substrings)


def normalize_sentence(s: str) -> str:
    # normalisation légère (sans déformer le sens)
    t = " ".join((s or "").strip().split())
    return t


def propose_substrings_from_sentence(sentence: str) -> List[str]:
    """
    Propose quelques "substrings" utiles à partir d'une phrase assistant-like.
    On limite volontairement à des fragments assez caractéristiques.
    """
    s = sentence.lower()

    # Fragments prioritaires (stable)
    seeds = [
        "je ne comprends pas",
        "je n'ai pas compris",
        "je ne saisis pas",
        "pouvez-vous préciser",
        "pouvez-vous reformuler",
        "pouvez-vous répéter",
        "veuillez préciser",
        "veuillez reformuler",
        "pour que je puisse vous aider",
        "pour pouvoir vous répondre",
        "j'ai besoin de plus de contexte",
        "il me faut plus de contexte",
        "il semble que vous",
        "faites-moi savoir",
        "n'hésitez pas à"
    ]

    out = []
    for seed in seeds:
        if seed in s:
            out.append(seed)

    # Si rien, tenter quelques patterns génériques prudents
    if not out:
        if "pouvez" in s and ("préciser" in s or "reformuler" in s or "répéter" in s):
            out.append("pouvez-vous")
        if "veuillez" in s and ("préciser" in s or "indiquer" in s or "reformuler" in s):
            out.append("veuillez")
        if "contexte" in s and ("besoin" in s or "faut" in s):
            out.append("besoin de plus de contexte")

    # dédup + limites
    seen = set()
    final = []
    for x in out:
        x = x.strip()
        if x and x not in seen:
            seen.add(x)
            final.append(x)
    return final[:3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Chemin du CSV ASR à analyser")
    ap.add_argument("--patterns", required=True, help="Chemin hallu_patterns.json")
    ap.add_argument("--out", required=True, help="Dossier de sortie")
    ap.add_argument("--max_examples", type=int, default=3, help="Nb d'exemples par candidat dans le rapport")
    args = ap.parse_args()

    csv_path = Path(args.csv).resolve()
    patterns_path = Path(args.patterns).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    if not patterns_path.exists():
        raise FileNotFoundError(patterns_path)

    substrings = load_patterns(patterns_path)

    fieldnames, rows = read_csv_rows(csv_path)
    if not rows:
        raise RuntimeError("CSV vide ou illisible.")

    text_field = pick_text_field(fieldnames)

    # Collecte candidates
    cand_counter = Counter()
    cand_examples: Dict[str, List[str]] = defaultdict(list)
    cand_sha1 = {}

    for r in rows:
        raw_text = (r.get(text_field) or "").strip()
        if not raw_text:
            continue
        for sent in split_sentences(raw_text):
            s = normalize_sentence(sent)
            if not s:
                continue

            # Heuristique assistant-like
            if not HALLU_HINT_REGEX.search(s):
                continue

            # Si déjà couvert par hard substrings -> pas besoin de proposer
            if is_covered_by_substrings(s, substrings):
                continue

            key = s.lower()
            cand_counter[key] += 1
            if len(cand_examples[key]) < args.max_examples:
                cand_examples[key].append(s)
            if key not in cand_sha1:
                cand_sha1[key] = sha1(key)

    # Écrire jsonl candidats suggérés (dédup)
    jsonl_path = out_dir / "hallu_candidates_suggested.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for key, count in cand_counter.most_common():
            rec = {
                "text": cand_examples[key][0],
                "source": "csv_scan",
                "count": count,
                "sha1": cand_sha1[key],
                "csv": str(csv_path),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Proposer des substrings à ajouter
    proposed = Counter()
    provenance = defaultdict(list)

    for key, count in cand_counter.most_common():
        # on propose à partir de la première forme exemple
        example = cand_examples[key][0]
        props = propose_substrings_from_sentence(example)
        for p in props:
            if p not in substrings:
                proposed[p] += count
                if len(provenance[p]) < args.max_examples:
                    provenance[p].append(example)

    suggestions_path = out_dir / "hallu_patterns_suggestions.json"
    with suggestions_path.open("w", encoding="utf-8") as f:
        payload = {
            "suggested_substrings": [
                {"substring": s, "score": int(sc), "examples": provenance[s]}
                for s, sc in proposed.most_common()
            ]
        }
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Rapport MD
    report_path = out_dir / "rapport_hallu.md"
    with report_path.open("w", encoding="utf-8") as f:
        f.write(f"# Rapport candidates hallu (scan CSV)\n\n")
        f.write(f"- CSV analysé : `{csv_path}`\n")
        f.write(f"- Patterns : `{patterns_path}`\n")
        f.write(f"- Champ texte utilisé : `{text_field}`\n")
        f.write(f"- Candidats détectés (phrases assistant-like non couvertes) : **{len(cand_counter)}**\n\n")

        f.write("## Top phrases candidates (fréquences)\n\n")
        for key, count in cand_counter.most_common(50):
            f.write(f"- **{count}** × {cand_examples[key][0]}\n")
        f.write("\n")

        f.write("## Suggestions d’ajouts (substrings) à valider\n\n")
        for s, sc in proposed.most_common(50):
            f.write(f"- **{sc}** × `{s}`\n")
            for ex in provenance[s]:
                f.write(f"  - ex: {ex}\n")
        f.write("\n")

        f.write("## Fichiers générés\n\n")
        f.write(f"- `{jsonl_path.name}` (candidats dédupliqués + fréquence)\n")
        f.write(f"- `{suggestions_path.name}` (proposition substrings)\n")
        f.write(f"- `{report_path.name}` (ce rapport)\n")

    print(f"[OK] Écrit: {report_path}")
    print(f"[OK] Écrit: {suggestions_path}")
    print(f"[OK] Écrit: {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
