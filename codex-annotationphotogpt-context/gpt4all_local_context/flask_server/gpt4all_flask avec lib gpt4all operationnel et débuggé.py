import os
import json
import time
from pathlib import Path
from flask import Flask, request, jsonify
from gpt4all import GPT4All
from dotenv import load_dotenv
from rag_utils import extraire_contenu_rag

# === Chargement .env ===
load_dotenv()

# === Configuration ===
CONFIG_PATH = Path("D:/GPT4All_Local/flask_server/config/config.json")
MODELS_PATH = Path("C:/GPT4All_Models")
MODEL_INDEX_PATH = MODELS_PATH / "models_index.json"
SYSTEM_PROMPT_PATH = Path("D:/GPT4All_Local/flask_server/config/system_prompt.json")
LOG_PATH = Path("D:/GPT4All_Local/logs/annoter_log.jsonl")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

DEFAULT_MODEL = config["default_model"]
PARAMS = config["parameters"]
API_KEYS = list(config["api_keys"].values())
PORT = config.get("port", 5050)

# === Chargement des modèles disponibles ===
with open(MODEL_INDEX_PATH, "r", encoding="utf-8") as f:
    model_index = json.load(f)

model_infos = model_index[DEFAULT_MODEL]
model_path = MODELS_PATH / model_infos["directory"] / model_infos["file"]

if not model_path.exists():
    raise FileNotFoundError(f"Modèle introuvable : {model_path}")

print(f"✅ Chargement du modèle : {DEFAULT_MODEL}")
print(f"📄 Fichier : {model_path}")

start = time.time()
llm = GPT4All(model_name=str(model_path), allow_download=False)
LOADED_MODEL_NAME = DEFAULT_MODEL
print(f"🕒 Modèle chargé en {time.time() - start:.2f} secondes.")
print("🧠 LLM prêt.")

# === Initialisation Flask ===
app = Flask(__name__)

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "port": PORT, "model": LOADED_MODEL_NAME})

@app.route("/models_index", methods=["GET"])
def get_models_index():
    return jsonify(model_index)

@app.route("/annoter", methods=["POST"])
def annoter():
    global llm, LOADED_MODEL_NAME

    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Prompt manquant"}), 400

    if request.headers.get("x-api-key") not in API_KEYS:
        return jsonify({"error": "Clé API invalide"}), 403

    prompt = data["prompt"]
    system = data.get("system", "")
    model_name_req = data.get("model_name", DEFAULT_MODEL)

    if model_name_req != LOADED_MODEL_NAME:
        print(f"🔄 Changement de modèle : {LOADED_MODEL_NAME} → {model_name_req}")
        del llm
        model_infos = model_index.get(model_name_req)
        if not model_infos:
            return jsonify({"error": f"Modèle '{model_name_req}' introuvable"}), 400
        path_model = MODELS_PATH / model_infos["directory"] / model_infos["file"]
        llm = GPT4All(model_name=str(path_model), allow_download=False)
        LOADED_MODEL_NAME = model_name_req

    try:
        full_prompt = f"{system.strip()}\n\n{prompt.strip()}"
        print(f"📨 Prompt reçu ({len(full_prompt)} caractères)")
        reponse = llm.generate(prompt=full_prompt, **PARAMS)
        log_appel("annoter", prompt, reponse, model_name_req)
        return jsonify({"reponse": reponse})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/annoter_rag", methods=["POST"])
def annoter_rag():
    global llm, LOADED_MODEL_NAME

    data = request.get_json()
    if not data or "prompt" not in data or "rag_dossier_pcfixe" not in data:
        return jsonify({"error": "Données manquantes"}), 400

    if request.headers.get("x-api-key") not in API_KEYS:
        return jsonify({"error": "Clé API invalide"}), 403

    prompt = data["prompt"]
    rag_dossier = data["rag_dossier_pcfixe"]
    system = data.get("system", "")
    model_name_req = data.get("model_name", DEFAULT_MODEL)

    if model_name_req != LOADED_MODEL_NAME:
        print(f"🔄 Changement de modèle : {LOADED_MODEL_NAME} → {model_name_req}")
        del llm
        model_infos = model_index.get(model_name_req)
        if not model_infos:
            return jsonify({"error": f"Modèle '{model_name_req}' introuvable"}), 400
        path_model = MODELS_PATH / model_infos["directory"] / model_infos["file"]
        llm = GPT4All(model_name=str(path_model), allow_download=False)
        LOADED_MODEL_NAME = model_name_req

    try:
        contenu_rag = extraire_contenu_rag(rag_dossier)
        full_prompt = f"{system.strip()}\n\n{contenu_rag}\n\n{prompt.strip()}"
        reponse = llm.generate(prompt=full_prompt, **PARAMS)
        log_appel("annoter_rag", full_prompt, reponse, model_name_req, rag_dossier)
        return jsonify({"reponse": reponse})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/annoter_web", methods=["POST"])
def annoter_web():
    global llm, LOADED_MODEL_NAME

    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "Prompt manquant"}), 400

    if request.headers.get("x-api-key") not in API_KEYS:
        return jsonify({"error": "Clé API invalide"}), 403

    prompt = data["prompt"]
    system = data.get("system", "")
    model_name_req = data.get("model_name", DEFAULT_MODEL)

    if model_name_req != LOADED_MODEL_NAME:
        print(f"🔄 Changement de modèle : {LOADED_MODEL_NAME} → {model_name_req}")
        del llm
        model_infos = model_index.get(model_name_req)
        if not model_infos:
            return jsonify({"error": f"Modèle '{model_name_req}' introuvable"}), 400
        path_model = MODELS_PATH / model_infos["directory"] / model_infos["file"]
        llm = GPT4All(model_name=str(path_model), allow_download=False)
        LOADED_MODEL_NAME = model_name_req

    try:
        # TODO : Ajouter la recherche web + résumé
        full_prompt = f"{system.strip()}\n\n{prompt.strip()}"
        reponse = llm.generate(prompt=full_prompt, **PARAMS)
        log_appel("annoter_web", prompt, reponse, model_name_req)
        return jsonify({"reponse": reponse})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def log_appel(route, prompt, reponse, modele, rag_path=None):
    entree = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "route": route,
        "modele": modele,
        "prompt": prompt,
        "reponse": reponse,
    }
    if rag_path:
        entree["rag_dossier"] = rag_path
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
