from flask import Flask, request, jsonify
from llama_cpp import Llama
from pathlib import Path
import json
import time

# === Configuration ===
CONFIG_PATH = Path("D:/GPT4All_Local/flask_server/config/config.json")
MODELS_PATH = Path("C:/GPT4All_Models")
MODEL_INDEX_PATH = MODELS_PATH / "models_index.json"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

DEFAULT_MODEL = config["default_model"]
PARAMS = config["parameters"]
API_KEYS = list(config["api_keys"].values())
PORT = config.get("port", 5050)

with open(MODEL_INDEX_PATH, "r", encoding="utf-8") as f:
    model_index = json.load(f)

model_infos = model_index[DEFAULT_MODEL]
model_path = MODELS_PATH / model_infos["directory"] / model_infos["file"]

if not model_path.exists():
    raise FileNotFoundError(f"Modèle introuvable : {model_path}")

print(f"✅ Chargement du modèle : {DEFAULT_MODEL}")
print(f"📄 Fichier : {model_path}")

start = time.time()
llm = Llama(
    model_path=str(model_path),
    n_ctx=16384,
    n_threads=12,
    n_batch=512,
    n_gpu_layers=-1,
    use_mlock=False,
    verbose=True
)
print(f"🕒 Modèle chargé en {time.time() - start:.2f} secondes.")
print("🧠 Configuration Llama prête.")

# === Flask app ===
app = Flask(__name__)

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "model": DEFAULT_MODEL, "port": PORT})

@app.route("/test", methods=["GET"])
def test():
    return "Test OK - le serveur fonctionne."

@app.route("/annoter", methods=["POST"])
def annoter():
    print("\n📡 /annoter appelé")
    try:
        raw = request.data
        print("Données brutes:", raw)

        try:
            data = json.loads(raw)
        except Exception as e:
            print("❌ JSON invalide:", str(e))
            return jsonify({"error": "JSON invalide", "detail": str(e)}), 400

        print("JSON décodé:", json.dumps(data, indent=2))

        api_key = request.headers.get("x-api-key")
        if api_key not in API_KEYS:
            return jsonify({"error": "Clé API invalide."}), 403

        prompt = data.get("prompt", "").strip()
        if not prompt:
            return jsonify({"error": "Champ 'prompt' manquant"}), 400

        system = data.get("system", "")
        temperature = float(data.get("temperature", 0.7))
        top_p = float(data.get("top_p", 0.95))
        top_k = int(data.get("top_k", 40))
        repeat_penalty = float(data.get("repeat_penalty", 1.1))
        max_tokens = min(int(data.get("max_tokens", 512)), 4096)

        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        print("📢 Prompt:", full_prompt[:300], "...")

        result = llm(
            full_prompt,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
            max_tokens=max_tokens
        )

        texte = result["choices"][0]["text"].strip()
        print("👌 Réponse OK")
        return jsonify({"reponse": texte})

    except Exception as e:
        print("❌ ERREUR GLOBALE :", str(e))
        return jsonify({"error": "Erreur serveur : " + str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)