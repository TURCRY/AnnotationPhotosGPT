import json
import os

def charger_infos_projet():
    chemin_json = os.path.join("data", "infos_projet.json")
    if os.path.exists(chemin_json):
        with open(chemin_json, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return {}

def sauvegarder_infos_projet(infos):
    chemin_json = os.path.join("data", "infos_projet.json")
    with open(chemin_json, "w", encoding="utf-8") as f:
        json.dump(infos, f, ensure_ascii=False, indent=2)
