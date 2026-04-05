#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = s.replace("’", "'")
    s = re.sub(r"[!?.,;:]+$", "", s)
    s = " ".join(s.split())
    return s.strip()


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def load_patterns(path: Path):

    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    hard_sub = [normalize_text(x) for x in cfg.get("hard_substrings", [])]
    soft_sub = [normalize_text(x) for x in cfg.get("soft_substrings", [])]

    hard_rx = [re.compile(x, re.IGNORECASE) for x in cfg.get("hard_regex", [])]
    soft_rx = [re.compile(x, re.IGNORECASE) for x in cfg.get("soft_regex", [])]

    return hard_sub, soft_sub, hard_rx, soft_rx


def is_covered(text, hard_sub, soft_sub, hard_rx, soft_rx):

    t = normalize_text(text)

    for s in hard_sub:
        if s in t:
            return True, "hard_substring"

    for s in soft_sub:
        if s in t:
            return True, "soft_substring"

    for rx in hard_rx:
        if rx.search(t):
            return True, "hard_regex"

    for rx in soft_rx:
        if rx.search(t):
            return True, "soft_regex"

    return False, ""


def classify_candidate(text):

    t = normalize_text(text)

    assistant_patterns = [
        "comment puis-je vous aider",
        "je peux vous aider",
        "veuillez préciser",
        "pouvez-vous",
        "je ne comprends pas",
        "je n'ai pas compris",
        "j'ai besoin de plus de contexte",
        "please provide more context",
        "how can i help you"
    ]

    if any(p in t for p in assistant_patterns):
        return "hard"

    if len(t) <= 10:
        return "soft"

    return "soft"


def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--patterns", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min_count", type=int, default=3)

    args = ap.parse_args()

    jsonl_path = Path(args.jsonl)
    patterns_path = Path(args.patterns)
    out_dir = Path(args.out)

    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_jsonl(jsonl_path)

    hard_sub, soft_sub, hard_rx, soft_rx = load_patterns(patterns_path)

    counts = Counter()
    examples = defaultdict(list)

    for r in rows:

        text = r.get("text") or r.get("texte")

        if not text:
            continue

        text_norm = normalize_text(text)

        counts[text_norm] += 1

        if len(examples[text_norm]) < 3:
            examples[text_norm].append(text)

    review_rows = []

    for text, count in counts.most_common():

        if count < args.min_count:
            continue

        covered, covered_by = is_covered(
            text,
            hard_sub,
            soft_sub,
            hard_rx,
            soft_rx
        )

        severity = classify_candidate(text)

        review_rows.append({

            "keep": "",
            "severity": severity,
            "count": count,
            "covered": covered,
            "covered_by": covered_by,
            "text": text,
            "examples": " | ".join(examples[text])
        })

    csv_path = out_dir / "hallu_candidates_review_short.csv"

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "keep",
                "severity",
                "count",
                "covered",
                "covered_by",
                "text",
                "examples"
            ],
            delimiter=";"
        )

        writer.writeheader()
        writer.writerows(review_rows)

    print(f"[OK] candidats agrégés : {len(counts)}")
    print(f"[OK] candidats retenus (count >= {args.min_count}) : {len(review_rows)}")
    print(f"[OK] écrit : {csv_path}")


if __name__ == "__main__":
    main()