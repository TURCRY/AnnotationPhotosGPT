# utils/config_loader.py

import json
from pathlib import Path

CONFIG_PATH = Path("D:/GPT4All_Local/flask_server/config/config.json")

def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def get_api_keys():
    config = load_config()
    return config.get("api_keys", {})

def get_models():
    config = load_config()
    return config.get("models", {})

def get_model_path():
    config = load_config()
    return config.get("model_path", "C:/GPT4All_Models")

def get_default_model():
    config = load_config()
    return config.get("default_model", "Mistral_7B")

def get_generation_params():
    config = load_config()
    return config.get("parameters", {})

def get_port():
    config = load_config()
    return config.get("port", 5050)
