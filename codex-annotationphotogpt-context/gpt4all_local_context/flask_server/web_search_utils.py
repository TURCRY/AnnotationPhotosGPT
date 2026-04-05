# web_search_utils.py - Recherche DuckDuckGo et log des URLs (mode RAG)

import os
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
from pathlib import Path
import socket, ipaddress
from urllib.parse import urlparse
import urllib.robotparser as robotparser

LOG_DIR = Path("D:/GPT4All_Local/logs/sources_web")
LOG_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# --- Limites par défaut (surchargées via env) ---
WEB_MAX_HOSTS   = int(os.getenv("WEB_MAX_HOSTS", "10"))
WEB_MAX_PAGES   = int(os.getenv("WEB_MAX_PAGES", "30"))
WEB_TIMEOUT_S   = float(os.getenv("WEB_TIMEOUT_S", "20"))
WEB_RESPECT_ROBOTS = os.getenv("WEB_RESPECT_ROBOTS", "1") not in ("0","false","False","no","No")
WEB_USER_AGENT  = os.getenv("WEB_USER_AGENT", "NTU-WebAgent/1.0 (+https://ntu-consult.com)")

# --- Réseaux privés / boucles locales à interdire ---
BLOCKED_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

HEADERS = {
    "User-Agent": WEB_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}


# 🔍 Recherche DuckDuckGo HTML
def recherche_duckduckgo(query, max_results=5):
    url = f"https://html.duckduckgo.com/html/?kl=fr-fr&q={requests.utils.quote(query)}"
    response = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")

    results = []
    for result in soup.select(".result")[:max_results]:
        link = result.find("a", class_="result__a")
        snippet = result.find("a", class_="result__snippet")
        if link and snippet:
            results.append({
                "title": link.get_text(),
                "url": link["href"],
                "snippet": snippet.get_text(),
            })

    return results


# API attendue par /annoter_web (recherche seule, sans scraping)
def quick_search(query: str, user_agent: str = None, max_results: int = 5):
    hdr = HEADERS.copy()
    if user_agent:
        hdr["User-Agent"] = user_agent
    # simple délégation pour rester compatible
    return recherche_duckduckgo(query, max_results=max_results)

# 🧾 Enregistrement RGPD des sources
def log_sources(sources, projet="mon_projet"):
    log_path = LOG_DIR / f"sources_web_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "projet": projet,
        "horodatage": datetime.now().isoformat(),
        "sources": sources
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"✅ {len(sources)} source(s) loggée(s) : {log_path}")

def _host_is_private_or_local(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
        for family, *_rest, sockaddr in infos:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if any(ip_obj in net for net in BLOCKED_NETS):
                return True
    except Exception:
        # En cas d’échec DNS → prudence, on bloque
        return True
    return False

def url_blocked(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return _host_is_private_or_local(host)
    except Exception:
        return True

def robots_allows(url: str, ua: str) -> bool:
    if not WEB_RESPECT_ROBOTS:
        return True
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(ua, url)
    except Exception:
        # si robots.txt illisible → par défaut on autorise
        return True

def safe_fetch_sync(url: str, timeout: float | None = None) -> str:
    """Télécharge une page en respectant les garde-fous (réseaux privés, robots.txt, taille, content-type)."""
    if url_blocked(url):
        raise RuntimeError(f"Blocked (private/local) URL: {url}")
    if not robots_allows(url, WEB_USER_AGENT):
        raise RuntimeError(f"Disallowed by robots.txt: {url}")

    to = float(timeout or WEB_TIMEOUT_S)
    r = requests.get(url, headers=HEADERS, timeout=to, allow_redirects=True)
    r.raise_for_status()
    ctype = (r.headers.get("content-type") or "").lower()
    if "text/html" not in ctype and "application/xhtml" not in ctype:
        raise RuntimeError(f"Unsupported content-type: {ctype}")
    if len(r.content) > 3_000_000:  # ~3 Mo
        raise RuntimeError("Response too large")
    return r.text

def _extract_text(html: str) -> str:
    """Extrait un texte lisible depuis du HTML complet."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # Récupère titres et paragraphes
    parts = [p.get_text(" ", strip=True) for p in soup.find_all(["h1", "h2", "h3", "p", "li"])]
    text = "\n".join([t for t in parts if t])
    # Coupe à 20 000 caractères pour éviter d’inonder le modèle
    return text[:20000]


def crawl_search(
    query: str,
    max_hosts: int | None = None,
    max_pages: int | None = None,
    timeout_s: float | None = None,
    max_results_seed: int = 15,
) -> list[dict]:
    """
    1) Lance une recherche DDG (HTML) pour récupérer une liste d'URLs candidates.
    2) Visite quelques pages en respectant des limites globales.
    3) Retourne une liste normalisée: {title, url, snippet}.
    """
    # plafonds “hard” via env
    max_hosts = min(int(max_hosts or 0) or WEB_MAX_HOSTS, WEB_MAX_HOSTS)
    max_pages = min(int(max_pages or 0) or WEB_MAX_PAGES, WEB_MAX_PAGES)
    timeout_s = min(float(timeout_s or 0) or WEB_TIMEOUT_S, WEB_TIMEOUT_S)

    seeds = recherche_duckduckgo(query, max_results=max_results_seed)
    candidate_urls = [s["url"] for s in seeds if s.get("url")]

    seen_hosts: set[str] = set()
    pages_done = 0
    results: list[dict] = []

    for url in candidate_urls:
        host = urlparse(url).hostname or ""
        # limite de diversité d’hôtes
        if host not in seen_hosts and len(seen_hosts) >= max_hosts:
            continue
        if pages_done >= max_pages:
            break

        try:
            html = safe_fetch_sync(url, timeout=timeout_s)
        except Exception:
            continue

        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.string.strip() if soup.title and soup.title.string else url)
        text = _extract_text(html)
        snippet = text[:500]  # juste les premières lignes comme aperçu

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "text": text,       # 🆕 on garde le texte complet
        })
        seen_hosts.add(host)
        pages_done += 1

    return results

# Exemple CLI
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, required=True)
    parser.add_argument("--projet", type=str, default="mon_projet")
    args = parser.parse_args()

    resultats = recherche_duckduckgo(args.query)
    for i, r in enumerate(resultats, 1):
        print(f"[{i}] {r['title']}\n{r['url']}\n{r['snippet']}\n")

    log_sources(resultats, projet=args.projet)
