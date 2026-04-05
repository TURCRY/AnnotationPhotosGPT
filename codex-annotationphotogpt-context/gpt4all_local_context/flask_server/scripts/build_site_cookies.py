# -*- coding: utf-8 -*-
"""
Normalise des exports bruts de cookies (EditThisCookie/Cookie-Editor, 700+ lignes)
vers des JSON prêts pour web_scraper_premium.py.

Entrée  : \\192.168.0.155\GPT4All_Local\flask_server\cookies\cookies_brut\*.json
Sorties : \\192.168.0.155\GPT4All_Local\flask_server\cookies\<domaine>.json        (dict simple)
          \\192.168.0.155\GPT4All_Local\flask_server\cookies\<domaine>_list.json  (liste d'objets)

Usage (Windows) :
    py build_site_cookies.py
    py build_site_cookies.py --in "\\...\\cookies\\cookies_brut" --out "\\...\\cookies"

Notes :
- Agrège tous les .json de `cookies_brut` et regroupe par domaine (ex: lemonde.fr, lesechos.fr).
- Supporte deux formats d'entrée : liste d'objets (EditThisCookie) OU dict {name:value}.
- Ignore les cookies expirés s'il y a un champ expirationDate < maintenant.
- Dé-duplique par (domaine,cookie name) en gardant la dernière valeur rencontrée.
- Crée les deux formats de sortie (dict + list) pour compat maximale.
"""

from __future__ import annotations
import argparse, json, time, re
from pathlib import Path
from typing import Dict, List, Any

# --- Répertoires par défaut (adapter si besoin) ---
DEFAULT_IN  = r"\\192.168.0.155\GPT4All_Local\flask_server\cookies\cookies_brut"
DEFAULT_OUT = r"\\192.168.0.155\GPT4All_Local\flask_server\cookies"

DOMAIN_RE = re.compile(r"(^|\.)((?:[a-z0-9-]+\.)+[a-z]{2,})$", re.IGNORECASE)

def norm_domain(raw: str) -> str:
    if not raw:
        return ""
    d = raw.strip().lstrip(".").lower()
    d = d.replace("www.", "")
    m = DOMAIN_RE.search(d)
    return m.group(2) if m else d

def infer_domain_from_filename(p: Path) -> str:
    # ex: lemonde.json -> lemonde.json (pas idéal). On laisse la normalisation tenter mieux sur cookies.
    name = p.stem.lower()
    name = name.replace("cookies_", "").replace("_cookies", "").replace("-cookies", "")
    return name

def is_expired(obj: dict) -> bool:
    # EditThisCookie: expirationDate = epoch seconds (float/int)
    exp = obj.get("expirationDate")
    if exp is None:
        return False
    try:
        return float(exp) < time.time()
    except Exception:
        return False

def load_raw_json(p: Path) -> Any:
    txt = p.read_text(encoding="utf-8")
    # tolérance BOM/encoding
    try:
        return json.loads(txt)
    except Exception:
        # petit fallback : retirer caractères non imprimables
        txt2 = "".join(ch for ch in txt if ch.isprintable() or ch in "\r\n\t")
        return json.loads(txt2)

def to_list_of_cookie_objs(obj: Any, fallback_domain: str) -> List[dict]:
    """
    Retourne une liste d'objets cookies normalisés :
    {"name","value","domain","path","secure","httpOnly","sameSite","expirationDate"}
    """
    out: List[dict] = []
    if isinstance(obj, dict):
        # format dict {name:value}
        for k, v in obj.items():
            out.append({
                "name": k,
                "value": v,
                "domain": "." + fallback_domain if fallback_domain else "",
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "sameSite": "Lax"
            })
        return out

    if isinstance(obj, list):
        for c in obj:
            if not isinstance(c, dict):  # on ignore les formes exotiques
                continue
            name = c.get("name")
            value = c.get("value")
            if not name or value is None:
                continue
            dom = norm_domain(c.get("domain") or fallback_domain)
            if not dom:
                # si rien dans le cookie et fallback vide, on ignore
                continue
            item = {
                "name": name,
                "value": value,
                "domain": "." + dom,
                "path": c.get("path", "/") or "/",
                "secure": bool(c.get("secure", True)),
                "httpOnly": bool(c.get("httpOnly", False)),
                "sameSite": c.get("sameSite", "Lax") or "Lax"
            }
            # on copie expirationDate si présent
            if "expirationDate" in c:
                item["expirationDate"] = c["expirationDate"]
            out.append(item)
        return out

    # format inconnu -> rien
    return out

def group_by_domain(cookies: List[dict]) -> Dict[str, List[dict]]:
    g: Dict[str, List[dict]] = {}
    for c in cookies:
        dom = norm_domain(c.get("domain", ""))
        # c["domain"] peut commencer par ".", on normalise
        dom = dom.lstrip(".")
        if not dom:
            continue
        g.setdefault(dom, []).append(c)
    return g

def dedupe_and_filter(cookies: List[dict]) -> List[dict]:
    """
    - enlève expirés
    - garde la dernière valeur rencontrée pour un couple (domain,name)
    """
    keep: Dict[tuple, dict] = {}
    for c in cookies:
        if is_expired(c):
            continue
        dom = norm_domain(c.get("domain", ""))
        dom = dom.lstrip(".")
        name = c.get("name")
        if not (dom and name):
            continue
        keep[(dom, name)] = c  # la dernière gagne
    return list(keep.values())

def write_outputs(per_domain: Dict[str, List[dict]], out_dir: Path) -> Dict[str, dict]:
    """
    Ecrit deux fichiers par domaine :
      - <domain>.json       : dict simple {name:value}
      - <domain>_list.json  : liste d'objets cookies
    Retourne un résumé par domaine (counts).
    """
    summary: Dict[str, dict] = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for dom, lst in per_domain.items():
        # tri simple pour lisibilité (session en dernier…)
        lst_sorted = sorted(lst, key=lambda x: (x.get("name","").lower()))
        # dict simple
        as_dict = {c["name"]: c["value"] for c in lst_sorted if "name" in c and "value" in c}
        p_dict  = out_dir / f"{dom}.json"
        p_list  = out_dir / f"{dom}_list.json"
        p_dict.write_text(json.dumps(as_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        p_list.write_text(json.dumps(lst_sorted, ensure_ascii=False, indent=2), encoding="utf-8")
        summary[dom] = {"count": len(lst_sorted), "dict_path": str(p_dict), "list_path": str(p_list)}
    return summary

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="in_dir",  default=DEFAULT_IN,  help="Répertoire des cookies bruts (.json)")
    ap.add_argument("--out", dest="out_dir", default=DEFAULT_OUT, help="Répertoire de sortie normalisée")
    args = ap.parse_args()

    in_dir  = Path(args.in_dir)
    out_dir = Path(args.out_dir)
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_items: List[dict] = []
    for p in sorted(in_dir.glob("*.json")):
        try:
            raw = load_raw_json(p)
        except Exception as e:
            print(f"⚠️  Ignoré (JSON invalide): {p} · {e}")
            continue

        # Domaine inféré par nom de fichier (fallback)
        fallback = infer_domain_from_filename(p)

        lst = to_list_of_cookie_objs(raw, fallback_domain=fallback)
        if not lst:
            print(f"⚠️  Aucun cookie parsé dans: {p.name}")
            continue

        all_items.extend(lst)

    if not all_items:
        print("Aucun cookie chargé.")
        return

    clean = dedupe_and_filter(all_items)
    grouped = group_by_domain(clean)
    if not grouped:
        print("Aucun domaine détecté.")
        return

    summary = write_outputs(grouped, out_dir)

    print("\n✅ Normalisation terminée.")
    for dom, info in summary.items():
        print(f"  - {dom}: {info['count']} cookies → {info['dict_path']} / {info['list_path']}")

if __name__ == "__main__":
    main()
