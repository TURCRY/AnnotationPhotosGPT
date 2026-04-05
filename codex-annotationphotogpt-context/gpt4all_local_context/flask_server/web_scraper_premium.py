# web_scraper_premium.py — version nettoyée & robuste
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from typing import Optional, List, Dict
import re, time
from urllib.parse import urlparse, urljoin, urldefrag
from collections import deque
import random


# === Config ===
COOKIES_DIR = Path("D:/GPT4All_Local/flask_server/cookies")
OUTPUT_DIR  = Path("D:/GPT4All_Local/flask_server/rag_sources")
LOG_FILE    = Path("D:/GPT4All_Local/logs/premium_log.jsonl")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# ---------- Utils ----------
def _find_cookies_file(cookies_dir: Path, domain: str) -> Optional[Path]:
    """
    Accepte plusieurs conventions de nommage :
      - cookies_<domain>.json
      - <domain>.json
      - cookies_<domain>_list.json
      - <domain>_list.json
    Retourne le 1er fichier trouvé, sinon None.
    """
    candidates = [
        f"cookies_{domain}.json",
        f"{domain}.json",
        f"cookies_{domain}_list.json",
        f"{domain}_list.json",
    ]
    for name in candidates:
        p = cookies_dir / name
        if p.exists():
            return p
    return None

def _load_cookies(cookies_dir: Path, domain: str, cookies_obj=None) -> Optional[dict]:
    """
    Renvoie un dict {name: value} de cookies.
    - Si cookies_obj (list[{'name','value'}] ou dict) est fourni, on le normalise et le renvoie.
    - Sinon on tente de charger depuis le fichier trouvé par _find_cookies_file.
    - Si fichier = LISTE -> converti en dict ; si fichier = DICT -> renvoyé tel quel ;
      si dict possède clé "cookies" (liste), on normalise depuis cette liste.
    """
    # 1) From caller
    if cookies_obj:
        if isinstance(cookies_obj, list):
            return {c.get("name"): c.get("value") for c in cookies_obj if isinstance(c, dict) and c.get("name")}
        if isinstance(cookies_obj, dict):
            return cookies_obj
        return None

    # 2) From disk
    f = _find_cookies_file(cookies_dir, domain)
    if not f:
        return None

    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {c.get("name"): c.get("value") for c in data if isinstance(c, dict) and c.get("name")}
        if isinstance(data, dict):
            # certains exports mettent les cookies dans data["cookies"]
            if "cookies" in data and isinstance(data["cookies"], list):
                return {c.get("name"): c.get("value") for c in data["cookies"] if isinstance(c, dict) and c.get("name")}
            return data
    except Exception as e:
        print(f"[premium] échec lecture cookies {f}: {e}")
    return None

def nettoyer_html(html: str) -> str:
    """Extrait le texte utile d'une page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    texte = soup.get_text(separator="\n")
    lignes = [l.strip() for l in texte.splitlines() if l.strip()]
    return "\n".join(lignes)

def _host_allowed(host: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    host = (host or "").lower()
    for d in allowed:
        dom = (d or "").lower().strip()
        if not dom:
            continue
        if host == dom or host.endswith("." + dom):
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
        abs_url, _ = urldefrag(abs_url)  # enlève #anchor
        p = urlparse(abs_url)
        if p.scheme in ("http", "https"):
            out.add(abs_url)
    return list(out)

def _sanitize_name_for_file(url: str) -> str:
    p = urlparse(url)
    base = (p.netloc + p.path).replace("/", "_").replace("\\", "_").strip("_")
    return base or "page"


def enregistrer_fichiers(contenu: str, projet: str, nom: str, url: str):
    dossier = OUTPUT_DIR / projet / "sources_web"
    dossier.mkdir(parents=True, exist_ok=True)

    chemin_txt = dossier / f"{nom}.txt"
    chemin_md  = dossier / f"{nom}.md"

    chemin_txt.write_text(contenu, encoding="utf-8")
    chemin_md.write_text(f"# Source Web : {url}\n\n{contenu}", encoding="utf-8")

    return str(chemin_txt), str(chemin_md)

def logger_rgpd(info: dict):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(info, ensure_ascii=False) + "\n")

# ---------- API principale ----------
def scrape_url_premium(
    url: str,
    max_depth: int = 0,
    rate_limit: int = 5,
    user_agent: Optional[str] = None,
    allowed_domains: Optional[list] = None,
    disallow_patterns: Optional[list] = None,
    cookies: Optional[dict] = None,
    headers: Optional[dict] = None,
    download_html: bool = False,
    project: Optional[str] = None,
) -> List[Dict]:
    """
    Retourne une liste de pages: [{"url","text","txt_path","md_path"}]
    - max_depth=0 : ne scrape que l'URL de départ.
    - allowed_domains: liste blanche (["exemple.com", "gouv.fr"]). Si None/[], on restreint par défaut au domaine de départ.
    - disallow_patterns: liste de regex pour exclure des URLs (ex: [r"/login", r"\\?utm_"]).
    - rate_limit: nb max de requêtes par seconde (<=0 = illimité).
    - project: nom du projet pour classer la sortie dans OUTPUT_DIR/<project>.
    """
    project = (project or "default").strip() or "default"

    # Session + cookies/headers
    session = requests.Session()

    # Cookies: utiliser ceux passés en param, sinon chercher sur disque
    start_host = urlparse(url).netloc.replace("www.", "")
    try:
        jar = _load_cookies(COOKIES_DIR, start_host, cookies_obj=cookies)
        if isinstance(jar, dict):
            session.cookies.update(jar)
    except Exception as e:
        print(f"[premium] cookies ignorés ({e})")

    # Headers / UA
    final_headers = dict(headers or {})
    if not user_agent:
        user_agent = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) "
                    "Gecko/20100101 Firefox/143.0")

    final_headers.setdefault("User-Agent", user_agent)
    final_headers.setdefault("Accept-Language", "fr-FR,fr;q=0.9,en;q=0.8")
    final_headers.setdefault("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
    # Le Referer peut aider sur certains parcours
    if "Referer" not in final_headers:
        try:
            final_headers["Referer"] = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
        except Exception:
            pass

    # Whitelist domaines: défaut = domaine de départ
    allowed = [d.strip().lower() for d in (allowed_domains or []) if str(d).strip()]
    if not allowed:
        base_dom = (urlparse(url).hostname or "").lower()
        if base_dom:
            allowed = [base_dom]

    # Regex d'exclusion
    pats = []
    for pat in (disallow_patterns or []):
        try:
            pats.append(re.compile(str(pat), re.I))
        except re.error:
            pass



    # Throttle
    gap = 1.0 / float(rate_limit) if rate_limit and rate_limit > 0 else 0.0
    last_fetch = 0.0

    def throttle():
        nonlocal last_fetch
        if gap <= 0:
            return
        now = time.time()
        wait = (last_fetch + gap) - now
        if wait > 0:
            # petit jitter aléatoire (10–30% du gap)
            wait += random.uniform(0.1, 0.3) * gap
            time.sleep(wait)
        last_fetch = max(now, last_fetch + gap)
    
    def _fetch_with_retries(session, url, headers, timeout=20, max_retries=2):
        backoff = 1.5
        for attempt in range(max_retries + 1):
            try:
                r = session.get(url, headers=headers or None, timeout=timeout, allow_redirects=True)
                # si anti-bot/ratelimiting
                if r.status_code in (429, 503):
                    raise requests.HTTPError(f"retryable {r.status_code}", response=r)
                r.raise_for_status()
                return r
            except requests.HTTPError as e:
                if attempt < max_retries and getattr(e, "response", None) and e.response.status_code in (429, 500, 502, 503, 504):
                    time.sleep(backoff ** (attempt + 1))
                    continue
                raise


    # BFS crawl
    pages: List[Dict] = []
    seen: set[str] = set()
    q: deque[tuple[str, int]] = deque([(url, 0)])
    idx = 0

    while q:
        cur, depth = q.popleft()
        if cur in seen:
            continue
        seen.add(cur)

        host = (urlparse(cur).hostname or "").lower()
        if allowed and not _host_allowed(host, allowed):
            continue
        if pats and any(pt.search(cur) for pt in pats):
            continue


        try:
            throttle()
            r = _fetch_with_retries(session, cur, final_headers, timeout=20, max_retries=2)
            html = r.text
            text = nettoyer_html(html)
            
            idx += 1
            name = f"{_sanitize_name_for_file(cur)}_{idx:02d}"

            # fichiers .txt/.md (rangés par projet)
            txt_path, md_path = enregistrer_fichiers(text, project, name, cur)

            # html brut optionnel
            if download_html:
                raw_dir = OUTPUT_DIR / project / "web_raw"
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{name}.html").write_text(html, encoding="utf-8")

            # log RGPD (déjà fourni)
            logger_rgpd({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "url": cur,
                "domaine": host,
                "projet": project,
                "fichier_txt": txt_path,
                "fichier_md": md_path
            })

            pages.append({
                "url": cur,
                "text": text,
                "txt_path": txt_path,
                "md_path": md_path
            })

            # Enqueue liens si profondeur non atteinte
            if depth < int(max_depth):
                for link in _extract_links(html, cur):
                    lhost = (urlparse(link).hostname or "").lower()
                    if allowed and not _host_allowed(lhost, allowed):
                        continue
                    if pats and any(pt.search(link) for pt in pats):
                        continue
                    if link not in seen:
                        q.append((link, depth + 1))

        except Exception as e:
            print(f"❌ Échec premium pour {cur}: {e}")

    return pages

# ---------- (facultatif) compat héritée ----------
def scraper_url(url: str, projet: str, index: int = 1):
    """Version legacy : conserve le comportement historique en s'appuyant sur _load_cookies."""
    print(f"\n🔐 Scraping premium : {url}")
    domaine = urlparse(url).netloc.replace("www.", "")
    jar = _load_cookies(COOKIES_DIR, domaine)

    session = requests.Session()
    if isinstance(jar, dict):
        session.cookies.update(jar)

    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        contenu = nettoyer_html(r.text)
        nom_base = f"source_premium_{index:02d}"
        chemin_txt, chemin_md = enregistrer_fichiers(contenu, projet, nom_base, url)
        logger_rgpd({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "url": url,
            "domaine": domaine,
            "projet": projet,
            "fichier_txt": chemin_txt,
            "fichier_md": chemin_md
        })
        print(f"✅ Enregistré : {chemin_md}")
    except Exception as e:
        print(f"❌ Échec scraping {url} : {e}")
