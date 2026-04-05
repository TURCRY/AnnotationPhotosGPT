# test_annoter_rag.py - Test de l'API Flask /annoter_rag

import requests
import json

# === Paramètres ===
IP_SERVEUR = "192.168.0.155"
PORT = 5050
CLE_API = "hy^wQ#4d3HpnEl4x1Mg&"
RAG_DOSSIER_PC_FIXE = "C:/Dossier_rag/mon_projet"  # à adapter

prompt = "Quels sont les risques techniques signalés dans ce dossier ?"

payload = {
    "prompt": prompt,
    "rag_dossier_pcfixe": RAG_DOSSIER_PC_FIXE,
    "system": "Vous êtes un assistant juridique analysant un dossier technique.",
    "temperature": 0.6,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "max_tokens": 512
}

headers = {
    "x-api-key": CLE_API,
    "Content-Type": "application/json"
}

url = f"http://{IP_SERVEUR}:{PORT}/annoter_rag"

try:
    print("\n📤 Envoi du prompt vers /annoter_rag ...")
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()
    print("\n✅ Réponse du serveur :")
    print(json.dumps(result, indent=2, ensure_ascii=False))
except requests.exceptions.HTTPError as err:
    print(f"\n❌ Erreur HTTP : {err.response.status_code}")
    print(err.response.text)
except Exception as e:
    print(f"\n❌ Erreur : {str(e)}")
