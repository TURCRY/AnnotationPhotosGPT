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

### Appels OpenAI de l'interface d'annotation

Le modèle distant par défaut est `gpt-6-luna`. L'ordre de priorité est :

1. `config_llm.json` de l'affaire (`model`) ;
2. modèle choisi et enregistré dans l'interface (`openai_model` dans `infos_projet.json`) ;
3. valeur de `config/config.json`, avec repli sur `gpt-6-luna` si elle est absente ou vide.

L'interface utilise l'API Chat Completions. Pour les modèles de raisonnement
(`gpt-5*`, `gpt-6*`, `o1*`, `o3*`, `o4*`), elle transmet
`max_completion_tokens` et `reasoning_effort="none"`, sans `temperature`. Les
modèles historiques tels que `gpt-4o-mini` conservent `max_tokens` et
`temperature`. Les budgets par défaut sont configurables avec
`max_tokens_libelle` (120) et `max_tokens_commentaire` (500).

Une sortie vide ou terminée par `finish_reason=length` est rejetée et ne
remplace jamais l'annotation affichée ou enregistrée. Les traces techniques
indiquent le modèle demandé/retourné, les paramètres non sensibles, la raison
de fin et les compteurs de tokens, y compris les tokens de raisonnement quand
le SDK les fournit. Une erreur HTTP 400 n'est pas répétée ; seuls les incidents
transitoires (absence de statut, 429, 5xx) peuvent être retentés.

Les boutons de régénération d'un champ et de recalcul des deux champs passent
par le même client OpenAI. Ils conservent les prompts existants et n'écrivent
un libellé ou un commentaire qu'après obtention d'une réponse non vide.
- Un exemple est fourni : `config/.env.exemple`
- Ne versionnez jamais `config/.env` contenant votre clé réelle
