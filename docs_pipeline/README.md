# GPT4All_Local

`GPT4All_Local` est un serveur Flask local d'orchestration IA. Il expose une
API HTTP utilisee par plusieurs clients et centralise des traitements LLM,
RAG, OCR, ASR, VLM, recherche web, pseudonymisation et export.

Le point d'entree principal est `flask_server/gpt4all_flask.py`.

## Role du serveur

Le serveur agit comme un hub applicatif entre :

- des modeles locaux charges dynamiquement
- des bases vectorielles pour le RAG et la memoire
- des services externes comme SearXNG, Chroma, Qdrant ou ComfyUI
- des clients HTTP comme `LLM_Assistant`, `openai-adapter`, `n8n` ou des outils internes

Routes particulierement sensibles :

- `/chat_llm`
- `/annoter`
- `/annoter_rag`
- `/annoter_web`
- `/annoter_rag_memoire`
- routes `/vision/*`
- routes `/v1/*`

## Architecture resumee

Le serveur orchestre plusieurs pipelines principaux :

- LLM direct via `/chat_llm`
- annotation simple via `/annoter`
- annotation enrichie par RAG via `/annoter_rag`
- annotation enrichie par web via `/annoter_web`
- OCR via `ocr_utils.py`
- ASR / diarisation via `voxtral_utils.py`
- vision et generation d'images via les routes dediees et ComfyUI

Documentation utile :

- `docs/architecture.md`
- `docs/SYSTEM_MAP.md`
- `docs/PIPELINE_MAP.md`
- `docs/API_MAP.md`

## Organisation du depot

- `flask_server/` : coeur du serveur Flask et modules fonctionnels
- `config/` : configuration versionnee
- `docs/` : documentation technique
- `scripts/` : scripts utilitaires et batch
- `tests/` : tests cibles

## Modeles

Les modeles IA ne sont pas stockes dans ce depot Git.

Emplacement local attendu :

- `C:\GPT4All_Models`

Source de verite des modeles :

- `C:\GPT4All_Models\models_index.json`

Copie de reference eventuelle dans le depot :

- `config/models_index_reference.json`

Regles pratiques :

- ne pas coder en dur un chemin de modele
- utiliser les helpers de configuration existants
- considerer le fichier hors depot comme la source de verite

## Configuration

Fichiers de configuration courants :

- `config/config.json`
- `config/paths.json`
- `config/system_prompt.json`

Le chargement des chemins passe par `flask_server/helper_paths.py`.

## Vector stores

Le serveur peut utiliser :

- Chroma
- Qdrant

Usages principaux :

- RAG documentaire
- memoire conversationnelle ou memoire semantique
- indexation et recherche vectorielle

Selon la configuration, ces backends peuvent etre locaux, exposes en REST ou
heberges sur une autre machine. Le serveur verifie leur disponibilite au
demarrage.

## Prerequis

- Python 3.10+
- environnement virtuel Python
- dependances Python installees
- modeles locaux disponibles sur la machine
- services externes necessaires disponibles selon les usages

Services externes possibles selon les parcours :

- Chroma
- Qdrant
- ComfyUI
- Tesseract
- SearXNG

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Lancement du serveur

Lancement manuel depuis la racine du depot :

```powershell
.\.venv\Scripts\Activate.ps1
cd flask_server
$env:PORT = "5050"
python -m waitress --listen 0.0.0.0:5050 --threads=4 gpt4all_flask:app
```

Par defaut, le serveur ecoute sur `http://localhost:5050`.

Automatisation Windows disponible dans le depot :

- `flask_autostart.xml`
- `serveur_flask_task.bat`
- `serveur_flask_auto.ps1`

## Capacites exposees

- generation LLM locale
- annotation de texte ou transcription
- annotation RAG sur dossiers ou stores vectoriels
- recherche web et scraping
- OCR de documents et images
- transcription audio et diarisation
- vision / analyse d'images
- proxy ComfyUI

## Securite et compatibilite

L'authentification peut s'appuyer sur une cle API transmise via `x-api-key`,
selon la configuration serveur.

Le projet est pense en priorite pour Windows et doit conserver :

- la compatibilite avec les scripts `.bat` et `.ps1`
- les chemins et conventions existants
- la compatibilite des routes utilisees par les clients externes

## Notes

- certaines donnees et certains modeles volumineux restent hors depot
- les clients externes attendent une forte stabilite des routes et des payloads JSON
- toute modification du serveur doit privilegier des changements locaux et reversibles
