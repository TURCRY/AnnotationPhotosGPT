# SYSTEM_DEPENDENCY_GRAPH.generated.md

Cartographie générée automatiquement des dépendances internes de `gpt4all_flask.py`.

## Graphe simplifié

```text
gpt4all_flask.py
├─ helper_paths
├─ helpers_embed
├─ ocr_utils
├─ pseudonymizer
├─ rag_memoire_utils
├─ rag_utils
├─ rag_vector_utils
├─ voxtral_utils
├─ web_scraper
├─ web_scraper_premium
└─ web_search_utils
```

## Modules internes appelés

- `helper_paths`
- `helpers_embed`
- `ocr_utils`
- `pseudonymizer`
- `rag_memoire_utils`
- `rag_utils`
- `rag_vector_utils`
- `voxtral_utils`
- `web_scraper`
- `web_scraper_premium`
- `web_search_utils`


## Familles fonctionnelles

### Infrastructure
- helper_paths
- helpers_embed

### RAG
- rag_utils
- rag_vector_utils
- rag_memoire_utils

### OCR / documents
- ocr_utils
- pseudonymizer

### Audio / transcription
- voxtral_utils

### Web
- web_scraper
- web_scraper_premium
- web_search_utils

## Interprétation

Ces modules sont importés directement par `gpt4all_flask.py` et doivent être analysés avant toute modification significative du serveur principal.
