# CONVENTIONS.md

Ce fichier décrit les conventions utilisées dans le projet AnnotationPhotosGPT.

## 1. Fichiers de configuration
- `config/config.json` : paramètres de l'application (modèle GPT, température, etc.)
- `config/contexte_general.json` : contient deux champs :
  - `system` : rôle attribué à GPT (ex. : expert judiciaire)
  - `user` : description de la situation (chantier, infiltration, etc.)
- `config/prompt_gpt.json` : contient les prompts GPT structurés (libellé et commentaire)

## 2. Variables de contexte
- Le champ `system` est inséré dans le prompt `system` de GPT.
- Le champ `user` est injecté dans `{contexte}` dans le prompt `user`.

## 3. Organisation des données
- Les fichiers sont chargés et enregistrés dans `data/`.
- Les chemins sont saisis via l’interface, puis mémorisés dans `infos_projet.json`.

## 4. Exécution
- Utilisation par interface Streamlit (`run_app.py`)
- Export Word déclenché manuellement ou via `make export`