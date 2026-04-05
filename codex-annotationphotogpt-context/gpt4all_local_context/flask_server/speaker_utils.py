def _read_lines(path: str | Path) -> list[str]:
    try:
        return [x.strip() for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    except Exception:
        return []

def _load_json_safe(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}

def _label_speakers_from_rules(chunks: list[dict], aliases_cfg: dict) -> dict:
"""Retourne un dict { 'SPEAKER_00': 'EXPERT', ... }"""
from collections import defaultdict, Counter
rules = aliases_cfg.get("rules", [])
map_cluster = aliases_cfg.get("map_cluster", {})
bag = defaultdict(list)
for ch in chunks or []:
    spk = ch.get("speaker") or ""
    txt = (ch.get("text") or "").lower()
    bag[spk].append(txt)

labels = {}
for spk, texts in bag.items():
    if spk in map_cluster:
        labels[spk] = map_cluster[spk]; continue
    joined = " ".join(texts)
    score = Counter()
    for r in rules:
        for kw in r.get("match_any", []):
            if kw.lower() in joined:
                score[r.get("label","ROLE")] += 1
    if score:
        labels[spk] = score.most_common(1)[0][0]
return labels