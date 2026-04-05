# README_app.md

## Objet

`app.py` est l’interface **Streamlit** exécutée sur le **laptop**.  
Elle sert de **client riche** pour piloter le serveur Flask `GPT4All_Local` hébergé sur le PC fixe, et centralise des usages métier autour de :

- génération LLM ;
- RAG dossier et RAG vectoriel ;
- OCR et conversions ;
- transcription / diarisation / compte-rendu Voxtral ;
- préparation de dépôts PDF et découpe de pièces ;
- gestion des prompts structurés ;
- historique Q&A ;
- administration et réveil du serveur.

Le rôle de cette application est donc celui d’un **poste de pilotage** côté laptop, pas d’un serveur autonome.

---

## Positionnement dans le système

### Architecture générale

Flux principal :

`Laptop / app.py (Streamlit)`  
→ appels HTTP vers `GPT4All_Local` sur le PC fixe  
→ modules spécialisés côté serveur  
→ réponse JSON affichée dans l’UI.

Le serveur distant expose notamment des routes LLM, RAG, OCR, ASR, web, PDF et administration. Le point d’entrée serveur documenté est `flask_server/gpt4all_flask.py`.

### Pourquoi ce fichier est sensible

`app.py` concentre :

- la sélection de l’affaire ;
- la résolution des chemins laptop / NAS / PC fixe ;
- le réveil et la vérification du serveur ;
- la préparation des payloads JSON envoyés au serveur ;
- une large part des conventions métier sur les dossiers d’affaire.

Une modification locale apparemment mineure peut donc casser :
- l’interface Streamlit ;
- la compatibilité des payloads attendus par le serveur ;
- la logique de synchronisation laptop / NAS / PC fixe ;
- les conventions de nommage et d’arborescence des affaires.

---

## Responsabilités principales de `app.py`

### 1. Initialisation d’environnement

Au démarrage, `app.py` :

- charge un `.env` avec une priorité explicite ;
- lit les variables de connexion (`PORT`, `SERVER_IP`, `API_KEY`) ;
- détermine si l’exécution se fait sur le PC fixe ou sur le laptop ;
- peut basculer automatiquement sur une IP VPN si un adaptateur compatible est détecté ;
- construit `SERVER_URL` ;
- prépare des constantes de timeout et des chemins racine.

### 2. Gestion des affaires

L’application :

- liste les affaires présentes sous `C:\Affaires` ;
- permet d’en créer de nouvelles ;
- génère `project_config.json` ;
- crée l’arborescence locale ;
- maintient une distinction entre :
  - `roots.laptop`
  - `roots.pcfixe`
  - `roots.nas`

La structure d’affaire suit l’architecture métier v4, avec des dossiers comme :

- `AA_Expert_Admin`
- `AD_Expert_Traitements`
- `AE_Expert_captations`
- `AF_Expert_ASR`
- `BA_Pieces_de_expert`
- `BB_Préparation_livrables`
- `BD_Exports`
- `_Config`
- `_DB`

### 3. Résolution des chemins multi-contexte

Le fichier contient plusieurs helpers de chemins :

- `path_pc`
- `path_pc_key`
- `path_lp_key`
- `resolve_path`
- `canon_dir_pcfixe`
- `pj`

Ces fonctions sont centrales.  
Elles permettent de calculer un chemin selon le contexte d’exécution et d’éviter les erreurs entre :

- chemin local laptop ;
- chemin vu par le PC fixe ;
- chemin UNC NAS.

### 4. Vérification / réveil du serveur

Avant toute action distante, l’application :

- teste `/ping` et `/health` ;
- peut envoyer un Wake-on-LAN via webhook ;
- attend l’ouverture TCP puis la disponibilité HTTP ;
- expose un état détaillé dans la sidebar.

### 5. UI métier multi-pages

L’application Streamlit expose plusieurs familles de fonctionnalités :

- **Génération standard**
- **Web / Recherche**
- **RAG (PC fixe)**
- **RAG vectoriel (Chroma / Qdrant)**
- **OCR & Conversions**
- **Pré-traitement dépôt PDF**
- **Voxtral (ASR / CR)**
- **Prompts & Bibliothèque**
- **Historique Q&A**
- **Administration**

### 6. Construction de payloads pour le serveur

`app.py` prépare les requêtes JSON vers les routes serveur, notamment :

- `/annoter`
- `/annoter_rag`
- `/annoter_rag_vecteur`
- `/annoter_web`
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
- `/infer_piece_titles`
- `/convert_to_csv_batch`
- `/scaffold_project_dirs`

La stabilité de ces payloads est essentielle.

---

## Dépendances fonctionnelles côté serveur

Même si `app.py` tourne sur le laptop, il dépend fortement du serveur distant et de ses sous-systèmes :

- LLM local ;
- RAG documentaire ;
- RAG vectoriel ;
- OCR Tesseract ;
- ASR / diarisation ;
- scraping web ;
- indexation vectorielle ;
- upload / découpe de PDF.

Le serveur s’appuie lui-même sur des modules comme :

- `rag_utils.py`
- `rag_vector_utils.py`
- `rag_memoire_utils.py`
- `ocr_utils.py`
- `voxtral_utils.py`
- `speaker_utils.py`
- `web_scraper.py`
- `web_scraper_premium.py`
- `web_search_utils.py`
- `embedding_factory.py`
- `helpers_embed.py`

---

## Variables d’environnement importantes

Les variables suivantes sont particulièrement structurantes pour `app.py` :

- `PORT`
- `SERVER_IP`
- `API_KEY`
- `MAC_ADRESSE_PCFIXE` ou `MAC_PCFIXE`
- `ON_PCFIXE`
- `ENFORCE_SERVER_IP`
- `DISABLE_VPN_AUTODETECT`
- `WAIT_SERVER_SECS`
- `CONNECT_TIMEOUT`
- `READ_TIMEOUT`
- `TIMEOUT`
- `AFFAIRES_ROOT`
- `PROJETS_INDEX_PATH`
- `HF_TOKEN`
- `URL_HAY_PUBLIQUE`
- `WEBHOOK_WAKE_PCFIXE`

### Ordre de recherche du `.env`

Priorité observée :

1. `LLM_ASSISTANT_ENV`
2. `C:\LLM_Assistant\config\.env`
3. `.env` à côté de `app.py`
4. `.env` dans le dossier courant

---

## Fichiers de configuration utilisés par le client

Le client lit localement plusieurs fichiers :

- `config.json`
- `llm_scenarios.json`
- `system_prompt.json`
- `prompt_tooltips.json`

Au niveau affaire, il lit ou génère :

- `_Config/project_config.json`
- `_Config/_remote.map.json`
- `_Config/_remote.url`
- `_Config/parties.json`
- `_Config/asr_lexique.json`

---

## Démarrage local

Exemple minimal :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

> Adapter le nom réel du fichier si le dépôt conserve encore une variante du type `app_v1_1.py`.

---

## Logique métier importante

### Gestion des parties

Le client permet :

- d’éditer les parties via `st.data_editor` ;
- de créer les dossiers de parties ;
- de renommer les dossiers si le nom change ;
- d’exporter un fichier Excel de synthèse ;
- de journaliser les opérations dans `AA_Expert_Admin\_Logs`.

### Pré-traitement PDF

Le client permet :

- OCR d’un dire ou bordereau ;
- détection automatique des limites de pièces ;
- préparation des métadonnées ;
- découpe unitaire ou batch ;
- génération de JSON de batch depuis un dossier.

### ASR / Voxtral

Le client gère :

- dépôt de média depuis le laptop ;
- copie éventuelle vers partage UNC ;
- lancement de `/asr_voxtral` ;
- génération de compte-rendu via `/voxtral_chat` ;
- options de diarisation ;
- glossaires et alias locuteurs ;
- récupération des résultats vers le laptop.

### RAG vectoriel

Le client permet :

- indexation CSV vers Chroma ;
- interrogation documentaire ;
- choix du backend `qdrant` ou `chroma` ;
- injection facultative des derniers Q&A dans le prompt système.

---

## Règles de modification pour Codex

### 1. Ne pas traiter `app.py` comme un simple front

Ce fichier contient une part importante de logique métier et d’orchestration.

### 2. Préserver les conventions de chemins Windows

Ne pas casser :

- les chemins UNC ;
- les séparateurs Windows ;
- les conventions `roots / paths`;
- la coexistence laptop / pcfixe / nas.

### 3. Ne pas modifier légèrement les payloads serveur sans vérifier la route cible

Avant de toucher un appel HTTP :

- identifier la route cible ;
- vérifier son schéma attendu côté serveur ;
- vérifier les autres clients éventuels ;
- conserver la rétrocompatibilité.

### 4. Préserver les clés de configuration existantes

Exemples sensibles :

- `project_id`
- `collection`
- `rel_input`
- `rel_output`
- `rag_dossier_pcfixe`
- `output_csv_dir`
- `model_name`

### 5. Éviter les refontes globales

Les évolutions doivent être :

- locales ;
- testables ;
- réversibles ;
- compatibles avec l’architecture actuelle.

### 6. Se méfier des doublons et héritages

Le fichier contient des traces d’évolution incrémentale :

- aliases rétrocompatibles ;
- anciennes clés encore supportées ;
- répétitions ou variantes de constantes ;
- dépendance à des conventions externes non centralisées.

Avant suppression d’un morceau de code, vérifier qu’il n’est pas encore utilisé par :
- un projet existant ;
- une route serveur ;
- un workflow batch ;
- une configuration plus ancienne.

---

## Zones les plus sensibles dans `app.py`

Priorité de prudence :

1. chargement `.env` et résolution de `SERVER_URL` ;
2. fonctions de chemins (`pj`, `path_pc`, `canon_dir_pcfixe`, etc.) ;
3. création d’affaire et génération de `project_config.json` ;
4. appels à `/annoter*`, `/ocr*`, `/asr_*`, `/voxtral_chat`, `/upload_file`, `/api/split_pdf*` ;
5. logique de batch PDF ;
6. gestion des copies laptop / UNC / PC fixe ;
7. logique de réveil du serveur.

---

## Check-list avant modification

Avant toute modification de `app.py` :

1. identifier la page Streamlit concernée ;
2. identifier la ou les routes serveur appelées ;
3. vérifier les helpers de chemins utilisés ;
4. vérifier les clés attendues dans `project_config.json` ;
5. vérifier si la logique dépend d’un partage UNC ou d’un chemin local ;
6. vérifier l’impact sur les workflows existants ;
7. privilégier un changement minimal.

---

## Check-list de test après modification

Tester au minimum :

- démarrage Streamlit sans erreur ;
- chargement du `.env` ;
- affichage de la sidebar connexion ;
- sélection d’une affaire existante ;
- création d’une affaire ;
- requête `/models_index` ;
- une action LLM simple ;
- une action RAG ;
- une action OCR ou PDF ;
- une action ASR si la zone touchée y est liée.

---

## Endpoints serveur les plus utilisés par `app.py`

Liste prioritaire à connaître :

- `GET /ping`
- `GET /health`
- `GET /models_index`
- `GET /asr_models`
- `POST /annoter`
- `POST /annoter_rag`
- `POST /annoter_rag_vecteur`
- `POST /annoter_web`
- `POST /ocr`
- `POST /ocr_auto`
- `GET /ocr_grid`
- `POST /asr_voxtral`
- `POST /voxtral_chat`
- `POST /index_chroma_from_csv`
- `GET /anonymization_reports`
- `GET /prompts_structures`
- `PUT /prompts_structures`
- `DELETE /prompts_structures/item`
- `GET /qa_logs`
- `POST /qa_logs/purge`
- `POST /upload_file`
- `POST /convert_to_csv_batch`
- `POST /infer_piece_titles`
- `POST /api/detect_piece_boundaries`
- `POST /api/split_pdf`
- `POST /api/split_pdf_batch`
- `POST /scaffold_project_dirs`

---

## Ce que Codex doit retenir en priorité

- `app.py` est un **client Streamlit métier**, pas un back-end.
- Il dépend fortement de `GPT4All_Local`.
- Il fonctionne dans un environnement **Windows multi-machines**.
- Les chemins et payloads sont aussi importants que l’UI.
- Il faut privilégier des **changements locaux, prudents et rétrocompatibles**.

---

## Sources internes à consulter en complément

- `app.py`
- `README.md`
- `API_MAP.md`
- `API_MAP.generated.md`
- `PIPELINE_MAP.md`
- `SYSTEM_MAP.md`
- `architecture.md`
- `cahier_des_charges.md`
- documentation d’arborescence d’affaire


## Références locales copiées dans ce dossier

Les fichiers suivants sont fournis comme références de compréhension pour Codex :

- `app.py`
- `ocr_utils.py`
- `wol_util.py`
- `sync/`
- `cahier_charges_app.md`
- `plan_execution_codex_app.md`

Ils ne doivent pas tous être présumés testés ou homogènes sans audit préalable.




Le dossier sync/ contient des scripts en cours d’étude pour une standardisation orientée n8n. Leur comportement actuel ne doit pas être présumé homogène ni validé sans audit.