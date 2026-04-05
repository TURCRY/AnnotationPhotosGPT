import requests
import json
import time

# --- Configuration ---
API_KEY = "hy^wQ#4d3HpnEl4x1Mg&"
BASE_URL = "http://127.0.0.1:5051"   # ton serveur de test
ENDPOINT = f"{BASE_URL}/sd_generate"

def main():
    headers = {"x-api-key": API_KEY, "Content-Type": "application/json"}

    payload = {
        "prompt": "façade XIXe, lumière du matin",
        "negative_prompt": "flou, artefacts",
        "model_key": "sd15",
        "width": 512,
        "height": 512,
        "steps": 15,
        "cfg": 6.0,
        "n": 1,
        "seed": 1234,
        "project_id": "test_sd",
        "history_timeout_s": 30,      # ⏱ poll limité à 30 s max
        "ensure_comfy": False          # ⚙️ pas de démarrage automatique
    }

    print(f"→ Test de génération d'image sur {ENDPOINT}")
    start = time.time()

    try:
        r = requests.post(ENDPOINT, headers=headers, json=payload, timeout=90)
        elapsed = time.time() - start
        print(f"⏱ Durée: {elapsed:.1f}s")
        print("HTTP:", r.status_code)
        try:
            data = r.json()
            print(json.dumps(data, indent=2, ensure_ascii=False)[:600])
        except Exception:
            print(r.text[:600])
    except Exception as e:
        print("❌ Exception:", e)

if __name__ == "__main__":
    main()
