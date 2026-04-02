# Intégration n8n → GPT4All_Local

Cette note décrit comment interroger le serveur Flask GPT4All_Local depuis **n8n**.

Le container **n8n est hébergé sur le NAS** et agit comme client HTTP du serveur.

---

# 1. Préparation côté serveur (PC fixe)

## Adresse d’accès

Le serveur Flask est accessible sur le réseau local :

`http://192.168.0.155:5050`

Le port doit être autorisé dans le pare-feu Windows.

## Clé API

La clé API est définie dans :

`.env`

Exemple :

`API_KEY=...`

Chaque requête doit inclure l’en-tête :

`x-api-key: <clé>`

---

# 2. Routes utilisables depuis n8n

## Génération LLM

- `/annoter`
- `/annoter_rag`
- `/annoter_rag_vecteur`
- `/annoter_web`

## OCR

- `/ocr`
- `/ocr_auto`

## ASR

- `/asr_voxtral`
- `/asr_models`

## RAG / indexation

- `/index_chroma_from_csv`
- `/anonymization_reports`

## Upload

- `/upload_file`

## Historique

- `/qa_logs`
- `/qa_logs/purge`

## Administration

- `/ping`
- `/wol`
- `/scaffold_project_dirs`

---

# 3. Configuration n8n

Créer des credentials de type **HTTP Header Auth**.

Nom :

`gpt4all_flask_key`

Header :

`x-api-key`

Valeur :

`<secret>`

Ces credentials doivent être utilisés dans tous les nœuds HTTP Request.

---

# 4. Exemples de payload

## A. Génération standard

Route : `/annoter`

```json
{
  "prompt": "Rédige un résumé en 5 points.",
  "system": "Tu es un assistant concis.",
  "model_name": "Meta-Llama-3-8B-Instruct.Q4",
  "project_id": "projet_X",
  "do_not_log": false
}
```

## B. RAG

Route : `/annoter_rag`

```json
{
  "prompt": "Quels sont les points clés du dossier X ?",
  "system": "Assistant RAG.",
  "model_name": "Meta-Llama-3-8B-Instruct.Q4",
  "project_id": "projet_X",
  "include_qa_logs": true
}
```

## C. RAG vectoriel

Route : `/annoter_rag_vecteur`

```json
{
  "prompt": "Synthétise les risques cités.",
  "system": "Assistant RAG vectoriel.",
  "model_name": "Meta-Llama-3-8B-Instruct.Q4",
  "project_id": "projet_X",
  "collection": "projet_X",
  "k": 5,
  "include_qa_logs": true,
  "show_scores": false,
  "max_ctx_chars": 12000
}
```

---

# 5. Recherche Web

Route : `/annoter_web`

Le serveur peut interroger **SearXNG sur le NAS**.

## Sans scraping

```json
{
  "prompt": "Fais un point d'actualité sur …",
  "system": "Assistant Web.",
  "model_name": "Meta-Llama-3-8B-Instruct.Q4",
  "project_id": "projet_X",
  "web": {
    "query_or_url": "inflation europe dernier rapport",
    "scrape": false,
    "premium": false
  }
}
```

## Avec scraping standard

```json
{
  "prompt": "Synthèse de la page + 5 bullets actionnables.",
  "system": "Assistant Web.",
  "model_name": "Meta-Llama-3-8B-Instruct.Q4",
  "project_id": "projet_X",
  "web": {
    "query_or_url": "https://exemple.com/article.html",
    "scrape": true,
    "premium": false,
    "max_depth": 0,
    "rate_limit": 5,
    "user_agent": "Mozilla/5.0",
    "allowed_domains": ["exemple.com"],
    "disallow_patterns": ["?utm_", "#comments"],
    "cookies": null,
    "headers": null,
    "download_html": true,
    "save_to_rag_pc": false
  }
}
```

## Avec scraping premium

```json
{
  "prompt": "Résume et liste les points litigieux.",
  "system": "Assistant Web.",
  "model_name": "Meta-Llama-3-8B-Instruct.Q4",
  "project_id": "projet_X",
  "web": {
    "query_or_url": "https://site-paywall.com/actu",
    "scrape": true,
    "premium": true,
    "max_depth": 0,
    "rate_limit": 5,
    "user_agent": "Mozilla/5.0",
    "allowed_domains": ["site-paywall.com"],
    "disallow_patterns": null,
    "cookies": [{"name": "session", "value": "..."}],
    "headers": {"Authorization": "Bearer ..."},
    "download_html": true,
    "save_to_rag_pc": true
  }
}
```

Remarques :

- Les champs `allowed_domains`, `disallow_patterns`, `rate_limit`, `max_depth`, `user_agent`, `cookies`, `headers`, `download_html` sont transmis par `/annoter_web` à `web_scraper.py` / `web_scraper_premium.py`.
- À `depth=0`, le traitement porte sur une seule page.
- `download_html=true` permet une trace brute `.html` en plus du `.txt` / `.md`.

---

# 6. Upload de fichiers

Route : `/upload_file`

Form Data attendue :

- `file`
- `project_id`
- `area`
- `subdir`
- `filename`
- `overwrite`

Exemple :

```text
file: <binaire>
project_id: projet_X
area: rag_pc
subdir: Config_ASR
filename: monfichier.json
overwrite: true
```

Important : les workflows doivent utiliser **`area + subdir`** et non plus `zone`.

---

# 7. OCR

Routes :

- `/ocr`
- `/ocr_auto`

Utilisation :

- extraction de texte depuis image ou PDF ;
- grille d’essais OCR pour `/ocr_auto` ;
- possibilité d’enchaîner avec une notification ou un post-traitement.

---

# 8. ASR Voxtral

Route : `/asr_voxtral`

Exemple :

```json
{
  "audio_path": "ASR_In/reunion.wav",
  "model_key": "Voxtral_Mini_3B_Transformers",
  "timestamps": true,
  "lang": "fr",
  "chunk": 30,
  "stride": 5,
  "output_csv_dir": "ASR_Out",
  "auto_chunk": true,
  "batch_size": 1,
  "excel_encoding": "utf-8-sig",
  "excel_decimal": "comma",
  "silence_split": false,
  "silence_top_db": 30,
  "silence_min_ms": 800,
  "diarize": false
}
```

Le pipeline peut aussi produire des exports CSV / SRT / VTT / DOCX selon la configuration du serveur.

---

# 9. Indexation CSV → Chroma

Route : `/index_chroma_from_csv`

```json
{
  "csv_dir": "\\\\NAS\\Projets\\ProjetX\\RAG_Vectoriel\\csv",
  "collection": "projet_X",
  "chroma_dir": "D:\\Work\\ProjetX\\chroma",
  "enable_pseudonym": true
}
```

Ensuite, consulter `/anonymization_reports` si besoin.

---

# 10. Pipeline “Ensure Ready”

Workflow recommandé dans n8n :

1. `GET /ping`
2. si échec → `POST /wol`
3. attendre 30–60 s
4. retester `/ping`
5. lancer le traitement

---

# 11. Timeouts

Certains traitements sont longs :

- OCR
- ASR
- génération LLM

Configurer les nœuds HTTP n8n avec un timeout élevé, par exemple :

`600 à 1200 secondes`

---

# 12. Bonnes pratiques

- toujours fournir `project_id` ;
- garder le serveur sur le LAN ;
- stocker la clé API uniquement dans les credentials n8n ;
- éviter les traitements en double sur les mêmes fichiers ;
- journaliser proprement les appels.

---

# 13. Dépendances externes

Le pipeline peut impliquer :

- `n8n` sur le NAS
- `SearXNG` sur le NAS
- `Chroma REST`
- `Qdrant REST`
- `OpenWebUI`

Le serveur Flask agit comme **orchestrateur IA central**.

