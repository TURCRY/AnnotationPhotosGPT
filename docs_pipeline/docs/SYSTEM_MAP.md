# SYSTEM_MAP -- GPT4All_Local

## 1. Point d'entrée principal

-   `flask_server/gpt4all_flask.py`
    -   point d'entrée principal du serveur Flask
    -   centralise les routes, le chargement de configuration,
        l'orchestration LLM/RAG/OCR/VLM/ASR

## Clients externes du serveur Flask

Le serveur Flask `GPT4All_Local` n’est pas uniquement utilisé en local.
Il est interrogé par plusieurs clients externes répartis sur d’autres machines du réseau.

### Clients externes du serveur

Plusieurs applications externes interrogent le serveur Flask GPT4All_Local.

#### Client principal sur laptop

- `LLM_Assistant`

Application Streamlit sur laptop utilisée pour piloter de nombreuses fonctionnalités du serveur Flask.

Fonctions couvertes :
- génération LLM
- RAG documentaire
- RAG vectoriel
- recherche web
- OCR
- ASR / Voxtral
- upload de fichiers
- gestion de prompts
- historique Q&A
- découpe PDF
- préparation de dépôts

Routes fréquemment utilisées :
- `/annoter`
- `/annoter_rag`
- `/annoter_rag_vecteur`
- `/annoter_web`
- `/search_web`
- `/ocr`
- `/ocr_auto`
- `/asr_voxtral`
- `/voxtral_chat`
- `/upload_file`
- `/prompts_structures`
- `/qa_logs`
- `/api/detect_piece_boundaries`
- `/api/split_pdf`
- `/api/split_pdf_batch`

#### Application spécifique laptop

- `AnnotationPhotoGPT`

Interface d’annotation de photos sur laptop.

Flux typique :
`AnnotationPhotoGPT (laptop) → batch Python → serveur Flask (PC fixe) → /annoter`

#### Via openai-adapter (NAS)

- `OpenWebUI`
- `AppFlowy`
- `Paperless`
- `Langfuse`
- `NocoDB`

Ces applications utilisent l’interface compatible OpenAI fournie par `openai-adapter`.

#### Automatisation

- `n8n` (NAS)

n8n appelle directement certaines routes HTTP du serveur pour automatiser des traitements.

#### Application spécifique

- `compte-rendu`

Utilise principalement la route :
`/annoter_segments`

Ces clients doivent être considérés comme des consommateurs externes de l’API.

Toute modification de payload, de schéma JSON ou de comportement des routes
doit être vérifiée au regard de leur compatibilité.


---

### Services externes utilisés par le serveur

Le serveur Flask agit également comme orchestrateur de plusieurs services externes.

Services connus :

- `SearXNG` (NAS) – recherche web
- `Chroma` REST – base vectorielle
- `Qdrant` REST – base vectorielle
- `ComfyUI` – génération d’images

Ces services sont appelés directement par le serveur Flask via HTTP.

### Clients externes du serveur

Plusieurs applications externes interrogent le serveur Flask GPT4All_Local.

#### Via openai-adapter (NAS)

- `OpenWebUI`
- `AppFlowy`
- `Paperless`
- `Langfuse`
- `NocoDB`

Ces applications utilisent l'interface compatible OpenAI fournie par `openai-adapter`.




#### SearXNG
Un container SearXNG sur le NAS peut être interrogé par le serveur Flask pour la recherche web.

Route concernée :
- `/search_web`
- indirectement `/annoter_web`

#### Chroma / Qdrant en REST
Les vector stores peuvent être accessibles à distance en mode REST.

Usages observés :
- RAG documentaire
- mémoire vectorielle
- enrichissement conversationnel


#### ComfyUI

ComfyUI est utilisé pour certains traitements de génération ou gestion d’images.
Le serveur Flask communique avec ComfyUI via HTTP et expose des routes proxy :
`/comfyui/prompt`, `/comfyui/history`, `/comfyui/image`.

------------------------------------------------------------------------

## 3. Lancement du serveur

### Automatisation Windows

-   `flask_autostart.xml`
-   `serveur_flask_task.bat`
-   `serveur_flask_auto.ps1`

### Lancement manuel

Depuis la racine du dépôt :

``` powershell
.\.venv\Scripts\Activate.ps1
cd flask_server
$env:PORT = "5050"
python -m waitress --listen 0.0.0.0:5050 --threads=4 gpt4all_flask:app
```

Le serveur écoute par défaut sur : http://localhost:5050

------------------------------------------------------------------------

## 4. Fichiers de configuration importants

### Configuration générale

- `config/config.json`
- `config/paths.json`
- `config/system_prompt.json`

### Configuration serveur locale

- `flask_server/config/diarization_config.json`
- `flask_server/config/llm_server_config.json`
- `flask_server/config/ocr_grid.json`
- `flask_server/config/voxtral_report_prompts.json`

### Modèles

Les modèles LLM ne sont **pas stockés dans le dépôt**.

Ils sont installés localement dans :

`C:\GPT4All_Models`

Le fichier décrivant les modèles disponibles est :

`C:\GPT4All_Models\models_index.json`

Ce fichier constitue **l’index des modèles LLM locaux** et sert de source de vérité pour la configuration des modèles.

Une copie de référence peut être présente dans le dépôt :

`config/models_index_reference.json`

Cette copie est **uniquement documentaire** et permet aux outils d’analyse (IA, Codex, développeurs) de comprendre la structure des modèles disponibles.

------------------------------------------------------------------------

## 5. Modules fonctionnels principaux

### Coeur Flask

-   `flask_server/gpt4all_flask.py`

### RAG

-   `flask_server/rag_utils.py`
-   `flask_server/rag_vector_utils.py`
-   `flask_server/rag_memoire_utils.py`

### OCR

-   `flask_server/ocr_utils.py`

### ASR / diarisation / Voxtral

-   `flask_server/voxtral_utils.py`
-   `flask_server/speaker_utils.py`

### Web

-   `flask_server/web_scraper.py`
-   `flask_server/web_scraper_premium.py`
-   `flask_server/web_search_utils.py`

### Pseudonymisation

-   `flask_server/pseudonymizer.py`

### Embeddings

-   `flask_server/embedding_factory.py`
-   `flask_server/helpers_embed.py`

### Utilitaires

-   `flask_server/helper_paths.py`
-   `flask_server/utils/config_loader.py`
-   `flask_server/utils/modele_loader.py`

------------------------------------------------------------------------

## 6. Routes API à considérer comme sensibles

Avant toute modification, analyser en priorité les usages et dépendances
de :

-   `/chat_llm`
-   `/annoter`
-   `/annoter_rag`
-   `/annoter_web`
-   routes liées aux embeddings
-   routes liées à la vision
-   routes liées aux exports
-   routes de pseudonymisation

Toute modification de ces routes doit être minimale et testable.

------------------------------------------------------------------------

## 7. Dépendances externes

### Vector stores

-   Chroma
-   Qdrant

### Couche vectorielle

Deux familles d'usage doivent être distinguées :

#### RAG documentaire

-   indexation de documents
-   recherche sémantique métier
-   export / import vers Chroma ou Qdrant

Routes associées probables :

-   `/annoter_rag`
-   `/annoter_rag_vecteur`
-   `/vector/search`
-   `/vector/upsert_csv_dir`
-   `/export_rag_to_chroma`
-   `/index_chroma_from_csv`

#### Mémoire sémantique / mémoire conversationnelle

-   mémoire de session ou mémoire enrichie
-   usage distinct du RAG documentaire

Module clé :

-   `rag_memoire_utils.py`

Indices observés au lancement :

-   `CHROMA_MODE='rest'`
-   `CHROMA_BASE='C:\\Chroma_DB'`
-   embeddings servis via `/embeddings`

### Modèles et moteurs

-   llama_cpp
-   GPT4All
-   Tesseract
-   Voxtral
-   ComfyUI

------------------------------------------------------------------------

## 8. Répertoires du dépôt

-   `flask_server/` : coeur applicatif
-   `config/` : configuration versionnée
-   `scripts/` : scripts métiers et batchs
-   `tests/` : tests ciblés
-   `docs/` : documentation technique et fonctionnelle

------------------------------------------------------------------------

## 9. Répertoires hors dépôt importants

-   `C:\GPT4All_Models` : modèles locaux
-   services Docker Chroma / Qdrant pouvant tourner sur une autre
    machine

------------------------------------------------------------------------

## 10. Pour modifier une fonctionnalité, où regarder ?

### Si la demande concerne

-   appel LLM → `gpt4all_flask.py`, config LLM, `modele_loader.py`
-   RAG → `rag_utils.py`, `rag_vector_utils.py`, `rag_memoire_utils.py`
-   OCR → `ocr_utils.py`
-   transcription / diarisation → `voxtral_utils.py`, `speaker_utils.py`
-   scraping web → `web_scraper.py`, `web_scraper_premium.py`,
    `web_search_utils.py`
-   chemins / fichiers → `helper_paths.py`, `config/paths.json`
-   modèles → `models_index.json`, config serveur, loaders
-   lancement serveur → `serveur_flask*.ps1`, `.bat`,
    `flask_autostart.xml`

------------------------------------------------------------------------

## 11. Règle de prudence

Ne pas partir du principe qu'une logique visible dans `gpt4all_flask.py`
est isolée.

Avant modification :

-   repérer les imports
-   repérer les fichiers de configuration appelés
-   repérer les scripts de lancement concernés
-   repérer les dépendances externes éventuelles
