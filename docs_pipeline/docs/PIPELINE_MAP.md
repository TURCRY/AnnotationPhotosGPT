# PIPELINE_MAP – GPT4All_Local

Ce document résume les principaux pipelines fonctionnels du serveur.

Point d’entrée principal :
`flask_server/gpt4all_flask.py`

---

## 1. LLM direct

### Routes
- `/chat_llm`
- `/chat_orchestre`

### Clients connus
- `LLM_Assistant`
- clients via `openai-adapter` (OpenWebUI, AppFlowy, Paperless, etc.)

### Chaîne de traitement
requête
→ préparation du prompt
→ sélection / chargement du modèle
→ génération LLM
→ réponse JSON

### Fichiers à regarder
- `gpt4all_flask.py`
- `utils/modele_loader.py`
- `models_index.json`

---

## 2. Annotation simple

### Routes
- `/annoter`
- `/annoter_segments`
- `/annoter_stats`

### Chaîne de traitement
texte / transcription
→ préparation du prompt
→ appel LLM
→ structuration de la réponse

### Applications clientes probables
- `LLM_Assistant`
- `compte_rendu`
- `AnnotationPhotoGPT`

### Fichiers à regarder
- `gpt4all_flask.py`

---

## 3. RAG documentaire

### Routes
- `/annoter_rag`
- `/annoter_rag_vecteur`
- `/vector/search`
- `/vector/upsert_csv_dir`
- `/export_rag_to_chroma`
- `/index_chroma_from_csv`

### Clients connus
- `OpenWebUI` (via openai-adapter sur NAS)

### Chaîne de traitement
requête
→ embeddings
→ interrogation base vectorielle
→ récupération de contexte
→ enrichissement du prompt
→ appel LLM

### Backends
- Chroma
- Qdrant

### Fichiers à regarder
- `rag_utils.py`
- `rag_vector_utils.py`
- `helpers_embed.py`

---

## 4. Mémoire vectorielle

### Routes
- `/annoter_rag_memoire`
- `/rag/context`

### Chaîne de traitement
requête
→ récupération mémoire vectorielle
→ construction du contexte
→ enrichissement du prompt
→ appel LLM

### Backend observé
- Chroma

### Indices techniques connus
- `CHROMA_MODE='rest'`
- `CHROMA_BASE='C:\\Chroma_DB'`

### Fichiers à regarder
- `rag_memoire_utils.py`

## Pipeline mémoire conversationnelle (OpenWebUI)

La route `/annoter_rag_memoire` est utilisée par l'interface OpenWebUI.

Flux d'appel :

OpenWebUI (NAS)
→ openai-adapter
→ serveur GPT4All_Local
→ route `/annoter_rag_memoire`
→ récupération du contexte mémoire
→ génération LLM

Cette route est utilisée pour enrichir les réponses avec une mémoire
conversationnelle persistante.

### Vector store utilisé

Le stockage de mémoire utilise :

- Chroma
- Qdrant

Ces services peuvent être accessibles en **mode REST**.

Exemple observé au démarrage :
`Chroma REST : 172.18.94.101:8800`
`Qdrant REST : 172.18.94.101:6333`


Les embeddings sont générés via l'endpoint local :

`http://127.0.0.1:5050/embeddings`

---

## 5. OCR

### Routes
- `/ocr`
- `/ocr_auto`
- `/ocr_grid`
- `/ocr_history`

### Clients connus
- `LLM_Assistant`
- `n8n`

### Chaîne de traitement
image / document
→ OCR
→ structuration du texte
→ retour JSON / historique

### Dépendance principale
- Tesseract

### Fichiers à regarder
- `ocr_utils.py`

---

## 6. ASR / transcription

### Routes
- `/asr_voxtral`
- `/asr_models`
- `/voxtral_chat`

### Clients connus
- `LLM_Assistant`
- `n8n`

### Chaîne de traitement
audio
→ transcription
→ diarisation éventuelle
→ nettoyage / post-correction
→ export éventuel
→ enrichissement LLM possible

### Fichiers à regarder
- `voxtral_utils.py`
- `speaker_utils.py`

---
## 7. Recherche Web et scraping

### Routes
- `/search_web`
- `/annoter_web`


### Clients connus
- `LLM_Assistant`
- `n8n`

---

### 7.1 Recherche Web

Route :

`/search_web`

Cette route interroge plusieurs moteurs de recherche externes et
retourne une liste normalisée de résultats.

### Moteurs supportés

- **SearXNG** (par défaut, container sur NAS)
- **Brave Search API**
- **Tavily Search API**
- **Perplexity API**

### Logique de sélection

Le moteur est choisi via le champ :
`engine`

Exemples :
`engine = "searxng"`
`engine = "brave"`
`engine = "tavily"`
`engine = "perplexity"`


Si la clé API correspondante est absente, le serveur bascule automatiquement
vers **SearXNG**.

### Paramètres principaux

### Chaîne de traitement

requête client  
→ sélection du moteur  
→ appel API externe  
→ normalisation des résultats  
→ retour JSON

### Fichiers à regarder

- `gpt4all_flask.py`
- `web_search_utils.py`

### Dépendances externes possibles

- SearXNG (NAS)
- Brave Search API
- Tavily API
- Perplexity API

---

### 7.2 Annotation Web

Route :

`/annoter_web`

### Chaîne de traitement

requête  
→ recherche web (`/search_web`)  
→ scraping éventuel des pages  
→ nettoyage du contenu  
→ enrichissement du prompt  
→ appel LLM  
→ réponse synthétique

### Modes de scraping

- scraping standard (`web_scraper.py`)
- scraping premium (`web_scraper_premium.py`)

### Fichiers à regarder

- `web_scraper.py`
- `web_scraper_premium.py`
- `web_search_utils.py`

### Dépendances externes possibles

- SearXNG (NAS)
- sites web externes

## 8. Vision / image / génération

### Routes
- `/sd_generate`
- `/comfyui/prompt`
- `/comfyui/history`
- `/comfyui/image`

### Clients connus
- `LLM_Assistant`

### Chaîne de traitement

#### Génération via ComfyUI
client
→ `/comfyui/prompt`
→ préparation / remplacement de paramètres dans le workflow
→ appel HTTP à ComfyUI via `COMFY_URL`
→ récupération d’un `prompt_id`
→ attente optionnelle de l’historique
→ retour JSON

#### Consultation de l’historique
client
→ `/comfyui/history`
→ appel HTTP à ComfyUI
→ récupération des images produites
→ copie éventuelle dans un dossier projet ou global
→ retour JSON avec chemins et URLs

#### Visualisation d’image
client
→ `/comfyui/image`
→ proxy vers `/view` de ComfyUI
→ renvoi binaire de l’image

### Dépendance externe
- ComfyUI

### Fichiers à regarder
- `gpt4all_flask.py`

### Points d’attention
- dépend de `COMFY_URL`
- dépend de `COMFY_TIMEOUT`
- les routes Flask jouent un rôle de proxy applicatif
- les changements de format JSON peuvent casser les clients externes

---

## 9. Pseudonymisation

### Routes
- `/pseudonym_map`
- `/pseudonym_purge`
- `/anonymization_reports`

### Chaîne de traitement
texte / registre
→ lecture du registre
→ pseudonymisation ou purge
→ sauvegarde / retour JSON

### Fichiers à regarder
- `pseudonymizer.py`

---

## 10. Fichiers / PDF

### Routes
- `/upload_file`
- `/files`
- `/download_file`
- `/api/detect_piece_boundaries`
- `/api/split_pdf`
- `/api/split_pdf_batch`
- `/infer_piece_titles`
- `/convert_to_csv_batch`

### Clients connus
- `LLM_Assistant`

### Chaîne de traitement
fichier
→ lecture / upload
→ détection / découpage / conversion
→ export ou réutilisation

### Fichiers à regarder
- `gpt4all_flask.py`

---

## 11. Administration

### Routes
- `/ping`
- `/health`
- `/info`
- `/models`
- `/models_index`
- `/models_status`
- `/model_info`
- `/__routes`

### Chaîne de traitement
appel de diagnostic
→ lecture de l’état serveur / modèles
→ retour JSON

---

## 12. Règle pratique pour Codex

Avant toute modification :

1. identifier la route concernée ;
2. identifier le pipeline ;
3. identifier les fichiers à regarder ;
4. vérifier :
   - modèle local ;
   - backend vectoriel ;
   - dépendances externes ;
   - configuration ;
   - impacts sur les clients.