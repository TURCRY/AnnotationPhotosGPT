import json
import os

from compat_affaire_captation import normalize_infos_aliases


def charger_infos_projet():
    """Charge l'etat local de travail de l'application depuis infos_projet.json."""
    chemin_json = os.path.join("data", "infos_projet.json")
    if os.path.exists(chemin_json):
        with open(chemin_json, "r", encoding="utf-8") as f:
            return normalize_infos_aliases(json.load(f))
    else:
        return {}

def sauvegarder_infos_projet(infos):
    """Persiste l'etat local de travail; ce fichier n'est pas une source de verite serveur."""
    chemin_json = os.path.join("data", "infos_projet.json")
    with open(chemin_json, "w", encoding="utf-8") as f:
        json.dump(normalize_infos_aliases(infos), f, ensure_ascii=False, indent=2)
