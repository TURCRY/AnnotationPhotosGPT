# web_scraper.py - Scraping de pages publiques issues des logs sources_web

import requests
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime
import json
import os
from typing import List, Dict, Optional
import re, time
from urllib.parse import urlparse, urljoin, urldefrag
from collections import deque



# === Config ===

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DEST_BASE = Path("D:/GPT4All_Local/flask_server/rag_sources")
DEST_BASE.mkdir(parents=True, exist_ok=True)

# ---------- Utils ----------

def _host_allowed(host: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    host = (host or "").lower()
    for dom in allowed:
        d = (dom or "").lower().strip()
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
    return False

def _extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    out = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        abs_url = urljoin(base_url, href)
        abs_url, _ = urldefrag(abs_url)  # enlève #anchors
        p = urlparse(abs_url)
        if p.scheme in ("http", "https"):
            out.add(abs_url)
    return list(out)


def nettoyer_texte(html):
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()
    return soup.get_text(separator=" ", strip=True)


def telecharger_et_sauver(url, dossier_dest, index):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            texte = nettoyer_texte(resp.text)
            if len(texte) > 500:
                fichier = dossier_dest / f"source_{index:02d}.txt"
                with open(fichier, "w", encoding="utf-8") as f:
                    f.write(texte)
                print(f"✅ Contenu sauvegardé : {fichier}")
            else:
                print(f"⚠️ Contenu trop court pour : {url}")
        else:
            print(f"❌ Échec {resp.status_code} pour : {url}")
    except Exception as e:
        print(f"❌ Erreur lors de la récupération de {url} : {e}")


def scraper_sources_publiques(fichier_json):
    with open(fichier_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    projet = data.get("projet", "inconnu")
    dossier_dest = DEST_BASE / projet / "sources_web"
    dossier_dest.mkdir(parents=True, exist_ok=True)

    sources = data.get("sources", [])
    for i, source in enumerate(sources, 1):
        url = source.get("url")
        if url:
            telecharger_et_sauver(url, dossier_dest, i)

# Nouvelle API attendue par /annoter_web (version "standard")
def scrape_url(
    url: str,
    max_depth: int = 0,
    rate_limit: Optional[int] = 5,
    user_agent: Optional[str] = None,
    allowed_domains: Optional[list] = None,
    disallow_patterns: Optional[list] = None,
    download_html: bool = False,
) -> List[Dict]:
    """
    Retourne [{"url","text"}]. max_depth=0 => page unique.
    - allowed_domains: liste blanche (ex: ["gouv.fr", "example.com"])
    - disallow_patterns: motifs regex d'URL à exclure (ex: [r"/login", r"\\?utm_"])
    - rate_limit: requêtes max / seconde (None ou <=0 = sans limite)
    """
    hdrs = HEADERS.copy()
    if user_agent:
        hdrs["User-Agent"] = user_agent

    # Normalisation entrées
    start_host = (urlparse(url).hostname or "").lower()
    allowed = [h.strip().lower() for h in (allowed_domains or []) if str(h).strip()]
    if not allowed:
        # Par défaut: on reste sur le domaine de départ (sécurisant)
        allowed = [start_host] if start_host else []

    pats = []
    for pat in (disallow_patterns or []):
        try:
            pats.append(re.compile(str(pat), re.I))
        except re.error:
            pass

    gap = 1.0 / float(rate_limit) if rate_limit and rate_limit > 0 else 0.0
    last_fetch = 0.0

    def throttle():
        nonlocal last_fetch
        if gap <= 0:
            return
        now = time.time()
        wait = (last_fetch + gap) - now
        if wait > 0:
            time.sleep(wait)
        last_fetch = max(now, last_fetch + gap)

    pages: List[Dict] = []
    seen: set[str] = set()
    q: deque[tuple[str, int]] = deque([(url, 0)])

    while q:
        cur, depth = q.popleft()
        if cur in seen:
            continue
        seen.add(cur)

        # Filtrage domaine / patterns (avant requête)
        h = (urlparse(cur).hostname or "").lower()
        if allowed and not _host_allowed(h, allowed):
            continue
        if pats and any(pt.search(cur) for pt in pats):
            continue

        try:
            throttle()
            resp = requests.get(cur, headers=hdrs, timeout=15)
            if resp.status_code != 200:
                continue
            html = resp.text
            text = nettoyer_texte(html)
            if text:
                pages.append({"url": cur, "text": text})
                if download_html:
                    (DEST_BASE / "web_raw").mkdir(parents=True, exist_ok=True)
                    fname = f"{h or 'page'}_{int(time.time()*1000)}.html"
                    (DEST_BASE / "web_raw" / fname).write_text(html, encoding="utf-8")

            # Crawl si on n'a pas atteint la profondeur max
            if depth < int(max_depth):
                for link in _extract_links(html, cur):
                    # Filtrage pré-queue pour limiter l'explosion
                    lh = (urlparse(link).hostname or "").lower()
                    if allowed and not _host_allowed(lh, allowed):
                        continue
                    if pats and any(pt.search(link) for pt in pats):
                        continue
                    if link not in seen:
                        q.append((link, depth + 1))

        except Exception as e:
            print(f"❌ Erreur pour {cur}: {e}")

    return pages

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=str, required=True, help="Chemin vers le fichier sources_web.json")
    args = parser.parse_args()

    scraper_sources_publiques(args.log)