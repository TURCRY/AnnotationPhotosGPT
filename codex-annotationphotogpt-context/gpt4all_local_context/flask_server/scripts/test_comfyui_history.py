import requests
import json

# --- Configuration ---
API_KEY = "hy^wQ#4d3HpnEl4x1Mg&"
BASE_URL = "http://127.0.0.1:5050"
ENDPOINT = f"{BASE_URL}/comfyui/history"

def main():
    headers = {"x-api-key": API_KEY}
    params = {"prompt_id": "test"}

    print(f"→ Test de la route: {ENDPOINT}")
    try:
        r = requests.get(ENDPOINT, headers=headers, params=params, timeout=15)
        print("Status HTTP :", r.status_code)
        try:
            # Si JSON valide, affichage formaté
            print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:600])
        except Exception:
            # Sinon affichage brut
            print(r.text[:600])
    except Exception as e:
        print("❌ Exception :", e)

if __name__ == "__main__":
    main()
