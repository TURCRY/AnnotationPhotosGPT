import json, requests
from pathlib import Path

def load_cookies(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return {k:v for k,v in data.items()}
    # liste d'objets
    return {c["name"]: c["value"] for c in data if "name" in c and "value" in c}

cookies = load_cookies(r"\\192.168.0.155\GPT4All_Local\flask_server\cookies\lemonde.fr.json")
ua = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
r = requests.get("https://www.lemonde.fr/…URL_d_un_article_abonne…", headers=ua, cookies=cookies, timeout=15)
print(r.status_code, len(r.text))
print(r.text[:1000])
