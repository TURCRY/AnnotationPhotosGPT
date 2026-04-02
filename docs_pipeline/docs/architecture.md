# Architecture – GPT4All_Local

## Point d’entrée principal
- `flask_server/gpt4all_flask.py`

Le serveur Flask est exposé via **Waitress**.

---

## Pipeline principal du serveur

Le serveur Flask agit comme un orchestrateur entre plusieurs capacités IA.

Le flux général est :

Client / UI  
→ Route Flask (`gpt4all_flask.py`)  
→ Chargement de configuration  
→ Appel des modules spécialisés  
→ Retour JSON au client

### Pipeline LLM

Client  
→ `/chat_llm`  
→ chargement du modèle via `modele_loader.py`  
→ génération via `llama_cpp`  
→ réponse JSON

### Pipeline RAG

Client  
→ `/annoter_rag`  
→ extraction du contexte via `rag_vector_utils.py`  
→ récupération des sources (Chroma / Qdrant)  
→ assemblage du prompt  
→ génération LLM

### Pipeline OCR

Client  
→ `/ocr` ou `/ocr_auto`  
→ `ocr_utils.py`  
→ Tesseract  
→ texte structuré

### Pipeline ASR

Client  
→ `/asr_voxtral`  
→ `voxtral_utils.py`  
→ transcription  
→ diarisation via `speaker_utils.py`

### Pipeline Web

Client  
→ `/annoter_web`  
→ `web_search_utils.py`  
→ `web_scraper.py`
→ enrichissement du prompt
→ génération LLM

## Lancement

Automatisation possible via :

- `flask_autostart.xml`
- `serveur_flask_task.bat`
- `serveur_flask_auto.ps1`

Lancement manuel :

activation de l’environnement virtuel :

.\.venv\Scripts\Activate.ps1

puis :

python -m waitress --listen 0.0.0.0:5050 --threads=4 gpt4all_flask:app

Le serveur écoute par défaut sur :

http://localhost:5050

---

## Composants

Le serveur orchestre plusieurs capacités :

- LLM local
- RAG (bases vectorielles)
- OCR
- ASR / diarisation
- VLM (vision)
- scraping web
- pseudonymisation

---

## Dépendances externes

Les modèles ne sont pas stockés dans le dépôt.

Ils sont installés dans :

C:\GPT4All_Models

Le fichier décrivant les modèles disponibles est :

C:\GPT4All_Models\models_index.json


Ce fichier constitue la **source de vérité pour la configuration des modèles**.

Une copie de référence peut être présente dans le dépôt :
config/models_index_reference.json

Cette copie est uniquement documentaire et permet aux outils d’analyse
(Codex, IA, développeurs) de comprendre la structure des modèles disponibles.
Le fichier réel utilisé par le serveur reste :

C:\GPT4All_Models\models_index.json

---

## Configuration des chemins

Le projet utilise un système centralisé de gestion des chemins.

Fichiers concernés :

config/paths.json  
flask_server/helper_paths.py

Ce mécanisme permet de localiser :

- les bases vectorielles
- les dossiers de données
- les répertoires temporaires
- les chemins vers certains services externes

Au démarrage du serveur, ces chemins sont chargés par `helper_paths.py`.

## Vector stores

Le serveur peut utiliser :

- Chroma
- Qdrant

Ces services peuvent être lancés via conteneurs Docker.

---

## Bases vectorielles

Le projet utilise des bases vectorielles selon plusieurs usages fonctionnels.

### 1. RAG documentaire / projet
Utilisé pour :
- indexation de documents
- recherche sémantique
- annotation enrichie
- corpus par dossier ou par projet

Backends possibles :
- Chroma
- Qdrant

### 2. Mémoire conversationnelle / mémoire applicative
Utilisée pour :
- mémoire des échanges
- contexte conversationnel enrichi
- stockage de mémoire sémantique

Backend observé :
- Chroma en mode REST

Référence observée au lancement :
- `CHROMA_MODE='rest'`
- `CHROMA_BASE='C:\\Chroma_DB'`

### Embeddings
Les embeddings peuvent être servis par le serveur Flask lui-même via un endpoint HTTP local, par exemple :

- `http://127.0.0.1:5050/embeddings`

Le modèle d'embeddings observé au lancement est :
- `BGE_M3`

## Dossiers principaux

- `flask_server/`
- `config/`
- `scripts/`
- `docs/`

---

## Remarques

- le projet fonctionne principalement sous Windows
- les scripts `.bat` et `.ps1` sont importants
- les modèles ne sont pas dans le dépôt