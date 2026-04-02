# README - Windows

## Exécution de l'application Streamlit

1. Double-cliquez sur le fichier `run_app.bat`
2. Cela ouvre automatiquement votre navigateur à l’adresse locale (http://localhost:8501)

## Compilation du script `convert_transcription_docx.py`

Des fichiers `.bat` sont disponibles dans `scripts/` :

- `compile_convert_transcription_docx.bat` : génère un `.exe` à partir du script
- `run_convert_transcription_docx.bat` : exécute directement le `.exe`

## Conditions requises

- Windows 10 ou 11
- Python 3.13 installé depuis python.org
- PyInstaller installé dans ce même environnement (voir la procédure PDF dans `docs/`)


## Gestion de la clé OpenAI

- Le fichier `config/.env` contient votre clé API personnelle.
- Exemple fourni : `config/.env.exemple`
- Ne partagez jamais `config/.env` avec votre clé réelle.