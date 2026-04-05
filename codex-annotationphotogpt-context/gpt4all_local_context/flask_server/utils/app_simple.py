# app.py - serveur Flask principal

from flask import Flask, request, jsonify
from utils.config_loader import (
    get_api_keys,
    get_models,
    get_default_model,
    get_model_path,
    get_generation_params,
    get_port
)
from gpt4all import GPT4All
import os
from flask import render_template

app = Flask(__name__)

# Chargement config
API_KEYS = get_api_keys()
MODELS = get_models()
DEFAULT_MODEL = get_default_model()
MODEL_PATH = get_model_path()
PARAMS = get_generation_params()
PORT = get_port()

# Préparation du modèle par défaut
MODEL_FILE = os.path.join(MODEL_PATH, MODELS[DEFAULT_MODEL])

if not os.path.isfile(MODEL_FILE):
    print("❌ FICHIER NON TROUVÉ :", MODEL_FILE)
else:
    print("✅ Fichier modèle trouvé :", MODEL_FILE)

model = GPT4All(model_name=DEFAULT_MODEL, model_path=MODEL_FILE, allow_download=False)

print("MODEL_PATH =", MODEL_PATH)
print("DEFAULT_MODEL =", DEFAULT_MODEL)
print("MODELS =", MODELS)
print("MODEL_FILE =", MODEL_FILE)


# Vérification clé API
def check_api_key(headers):
    api_key = headers.get("x-api-key")
    return api_key in API_KEYS.values()

@app.route("/annoter", methods=["POST"])
def annoter():
    if not check_api_key(request.headers):
        return jsonify({"error": "Clé API invalide"}), 403

    data = request.get_json()
    question = data.get("question", "")
    contexte = data.get("context", "")

    prompt = f"""
Contexte :
{contexte}

Question :
{question}

Réponds de façon claire et concise.
"""
    with model:
        reponse = model.generate(prompt, **PARAMS)

    return jsonify({"reponse": reponse.strip()})


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", model=DEFAULT_MODEL, port=PORT)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

