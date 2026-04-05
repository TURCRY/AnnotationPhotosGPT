# test_api_embeddings.py
import requests, json

API = "http://10.0.1.10:5050/embeddings"
headers = {"Content-Type": "application/json", "x-api-key": "hy^wQ#4d3HpnEl4x1Mg&"}

for model in ["Nomic_Embed", "E5_multilingual_large", "MiniLM_L6_v2", "BGE_3"]:
    payload = {"texts": ["Bonjour le monde"], "model": model}
    r = requests.post(API, headers=headers, data=json.dumps(payload))
    data = r.json()
    if "embeddings" in data and data["embeddings"]:
        print(f"{model}: dimension = {len(data['embeddings'][0])}")
    else:
        print(f"{model}: erreur -> {data}")
