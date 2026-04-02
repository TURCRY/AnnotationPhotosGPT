import openai
import json
import os

CONFIG_PATH = "./config/config.json"

def load_api_key():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("openai_api_key")
    return None

def save_config(api_key, model):
    config = {
        "openai_api_key": api_key,
        "model": model,
        "temperature": 0.4,
        "max_tokens": 500,
        "retries": 3,
        "timeout": 30
    }
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
    print(f"Configuration enregistrée dans {CONFIG_PATH}")

def main():
    print("🔑 Configuration du modèle GPT pour AnnotationPhotosGPT")
    api_key = load_api_key() or input("Entrez votre clé API OpenAI : ").strip()
    openai.api_key = api_key

    try:
        print("📡 Récupération de la liste des modèles disponibles...")
        models = openai.Model.list()["data"]
        model_ids = sorted(set([m["id"] for m in models if m["id"].startswith("gpt")]))
        if not model_ids:
            print("Aucun modèle GPT trouvé.")
            return

        print("\n📋 Modèles GPT disponibles :")
        for i, mid in enumerate(model_ids):
            print(f"{i + 1}. {mid}")

        index = int(input("\nEntrez le numéro du modèle à utiliser : ")) - 1
        if 0 <= index < len(model_ids):
            chosen_model = model_ids[index]
            save_config(api_key, chosen_model)
        else:
            print("Indice invalide.")
    except Exception as e:
        print("❌ Erreur lors de la récupération des modèles :", str(e))

if __name__ == "__main__":
    main()