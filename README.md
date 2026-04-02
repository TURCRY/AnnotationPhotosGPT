# AnnotationPhotosGPT

Application de synchronisation audio/photo avec génération assistée de libellés et commentaires à partir de transcriptions audio.

## Fonctionnalités principales

- Chargement de photos avec métadonnées EXIF
- Affichage photo par photo avec navigation
- Lecture synchronisée d'extraits audio
- Génération automatique de libellés et commentaires via GPT
- Annotation manuelle et validation
- Export des résultats en .csv et en document Word structuré
- Gestion des décalages audio/photo par point de synchronisation

## Structure du projet

```
AnnotationPhotosGPT/
├── app/                       # Modules principaux de l'application Streamlit
├── config/                    # Fichiers de configuration (config.json, .env, prompts)
├── data/                      # Données projet (transcriptions, photos, audio, jsons)
├── exe/                       # Fichiers exécutables générés (convert_transcription_docx.exe)
├── scripts/                   # Scripts Python + .bat de gestion/compilation
├── spec/                      # Fichiers .spec de PyInstaller
├── docs/                      # Documentation PDF et markdown
```

## Démarrage de l'application

Lancer :

```bash
streamlit run app/main.py
```

## Fichiers importants

- `config/config.json` : paramètres généraux (modèle GPT, délais, etc.)
- `data/transcription.csv` : texte issu de la bande son
- `data/photos.csv` : liste des photos avec horodatage et orientation
- `data/prise_de_son.wav` : enregistrement complet
- `data/annotations.csv` : résultats des validations manuelles

## Compilation d'un script externe

Voir `docs/Compilation_PyInstaller_Procedure.pdf` ou `docs/README_compilation.md` pour les scripts `.exe` générés via PyInstaller.


## Configuration API

- La clé API OpenAI est lue depuis `config/.env`
- Un exemple est fourni : `config/.env.exemple`
- Ne versionnez jamais `config/.env` contenant votre clé réelle