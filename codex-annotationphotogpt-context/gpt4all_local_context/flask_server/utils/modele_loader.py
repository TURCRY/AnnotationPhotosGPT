# modele_loader.py

import os
import json
from gpt4all import GPT4All
from .config_loader import get_model_path, get_default_model

def get_model():
    model_name = get_default_model()  # Ex: "Mistral_7B"
    base_dir = get_model_path()       # Ex: "C:/GPT4All_Models"
    index_path = os.path.join(base_dir, "models_index.json")

    if not os.path.exists(index_path):
        raise FileNotFoundError(f"models_index.json introuvable dans {base_dir}")

    with open(index_path, "r", encoding="utf-8") as f:
        models_index = json.load(f)

    if model_name not in models_index:
        raise ValueError(f"Modèle {model_name} introuvable dans models_index.json")

    model_info = models_index[model_name]
    model_file = os.path.join(base_dir, model_info["directory"], model_info["file"])

    if not os.path.exists(model_file):
        raise FileNotFoundError(f"Fichier modèle non trouvé : {model_file}")

    print(f"🧠 Chargement du modèle : {model_name}")
    print(f"📄 Chemin complet : {model_file}")

    return GPT4All(model_name=model_name, model_path=model_file, allow_download=False)
