# MODULE_MAP.generated.md

Cartographie générée automatiquement depuis `flask_server/gpt4all_flask.py`.

Nombre d'imports détectés : **147**

## Répartition par catégorie

- **Interne** : 47 import(s)
- **Standard library** : 67 import(s)
- **Tiers** : 33 import(s)

| Catégorie | Type | Module | Élément importé | Ligne |
|---|---|---|---|---:|
| Interne | `from` | `helper_paths` | `CHROMA_HOST` | 109 |
| Interne | `from` | `helper_paths` | `CHROMA_PORT` | 109 |
| Interne | `from` | `helper_paths` | `QDRANT_HOST` | 109 |
| Interne | `from` | `helper_paths` | `QDRANT_PORT` | 109 |
| Interne | `from` | `helper_paths` | `chroma_client` | 109 |
| Interne | `from` | `helper_paths` | `debug_paths_snapshot` | 43 |
| Interne | `from` | `helper_paths` | `load_paths` | 43 |
| Interne | `from` | `helper_paths` | `qdrant` | 109 |
| Interne | `import` | `helpers_embed` | `` | 41 |
| Interne | `from` | `helpers_embed` | `load_embedder` | 27 |
| Interne | `from` | `ocr_utils` | `OcrOptions` | 53 |
| Interne | `from` | `ocr_utils` | `run_ocr` | 53 |
| Interne | `from` | `ocr_utils` | `run_ocr_auto` | 53 |
| Interne | `from` | `pseudonymizer` | `depseudonymize` | 9770 |
| Interne | `from` | `pseudonymizer` | `load_registry` | 9770 |
| Interne | `from` | `pseudonymizer` | `load_registry` | 9783 |
| Interne | `from` | `pseudonymizer` | `pseudonymize_text` | 70 |
| Interne | `from` | `pseudonymizer` | `purge_person` | 9783 |
| Interne | `from` | `pseudonymizer` | `save_registry` | 9783 |
| Interne | `from` | `rag_memoire_utils` | `build_context` | 51 |
| Interne | `from` | `rag_memoire_utils` | `build_memory_append` | 52 |
| Interne | `from` | `rag_utils` | `extraire_contenu_rag` | 44 |
| Interne | `from` | `rag_vector_utils` | `build_rag_context` | 45 |
| Interne | `from` | `rag_vector_utils` | `build_rag_context_store` | 46 |
| Interne | `from` | `rag_vector_utils` | `retrieve_sources` | 46 |
| Interne | `from` | `rag_vector_utils` | `retrieve_top_k_store` | 47 |
| Interne | `from` | `rag_vector_utils` | `upsert_csv_folder_into_chroma` | 9728 |
| Interne | `from` | `rag_vector_utils` | `upsert_csv_folder_into_store` | 47 |
| Interne | `from` | `voxtral_utils` | `_excel_serial_from_datetime` | 54 |
| Interne | `from` | `voxtral_utils` | `_ext_tag` | 54 |
| Interne | `from` | `voxtral_utils` | `_fmt_hms` | 54 |
| Interne | `from` | `voxtral_utils` | `_label_speakers_from_rules` | 54 |
| Interne | `from` | `voxtral_utils` | `_read_lines` | 54 |
| Interne | `from` | `voxtral_utils` | `_safe_stem` | 54 |
| Interne | `from` | `voxtral_utils` | `create_voxtral_pipeline` | 54 |
| Interne | `from` | `voxtral_utils` | `load_json_safe` | 54 |
| Interne | `from` | `voxtral_utils` | `post_correct_transcript` | 54 |
| Interne | `from` | `voxtral_utils` | `to_srt` | 54 |
| Interne | `from` | `voxtral_utils` | `to_vtt` | 54 |
| Interne | `from` | `voxtral_utils` | `transcribe_audio` | 54 |
| Interne | `from` | `voxtral_utils` | `transcribe_with_diarization` | 54 |
| Interne | `from` | `voxtral_utils` | `voxtral_chat` | 54 |
| Interne | `import` | `web_scraper` | `` | 7031 |
| Interne | `import` | `web_scraper_premium` | `` | 7015 |
| Interne | `from` | `web_search_utils` | `crawl_search` | 71 |
| Interne | `from` | `web_search_utils` | `crawl_search` | 7033 |
| Interne | `from` | `web_search_utils` | `log_sources` | 71 |
| Standard library | `import` | `base64` | `` | 90 |
| Standard library | `import` | `base64` | `` | 7472 |
| Standard library | `from` | `collections` | `Counter` | 37 |
| Standard library | `from` | `collections` | `OrderedDict` | 74 |
| Standard library | `from` | `collections` | `defaultdict` | 72 |
| Standard library | `from` | `collections.abc` | `Sequence` | 18 |
| Standard library | `from` | `concurrent.futures` | `ThreadPoolExecutor` | 92 |
| Standard library | `from` | `concurrent.futures` | `as_completed` | 92 |
| Standard library | `from` | `contextlib` | `contextmanager` | 21 |
| Standard library | `import` | `csv` | `` | 14 |
| Standard library | `import` | `csv` | `` | 3495 |
| Standard library | `import` | `datetime` | `` | 12 |
| Standard library | `import` | `datetime` | `` | 102 |
| Standard library | `from` | `datetime` | `datetime` | 13 |
| Standard library | `from` | `datetime` | `datetime` | 4862 |
| Standard library | `from` | `datetime` | `timedelta` | 13 |
| Standard library | `from` | `difflib` | `SequenceMatcher` | 78 |
| Standard library | `from` | `functools` | `lru_cache` | 20 |
| Standard library | `import` | `gc` | `` | 76 |
| Standard library | `import` | `glob` | `` | 14 |
| Standard library | `import` | `hashlib` | `` | 73 |
| Standard library | `import` | `hashlib` | `` | 214 |
| Standard library | `from` | `hashlib` | `sha256` | 24 |
| Standard library | `import` | `html` | `` | 32 |
| Standard library | `import` | `importlib` | `` | 14 |
| Standard library | `import` | `inspect` | `` | 17 |
| Standard library | `import` | `inspect` | `` | 3704 |
| Standard library | `import` | `io` | `` | 33 |
| Standard library | `import` | `json` | `` | 14 |
| Standard library | `import` | `logging` | `` | 87 |
| Standard library | `from` | `logging.handlers` | `RotatingFileHandler` | 89 |
| Standard library | `import` | `math` | `` | 14 |
| Standard library | `from` | `math` | `sqrt` | 19 |
| Standard library | `import` | `mimetypes` | `` | 14 |
| Standard library | `import` | `os` | `` | 14 |
| Standard library | `from` | `pathlib` | `Path` | 15 |
| Standard library | `import` | `platform` | `` | 14 |
| Standard library | `import` | `random` | `` | 30 |
| Standard library | `import` | `re` | `` | 14 |
| Standard library | `import` | `re` | `` | 75 |
| Standard library | `import` | `shutil` | `` | 14 |
| Standard library | `import` | `socket` | `` | 31 |
| Standard library | `import` | `subprocess` | `` | 14 |
| Standard library | `import` | `subprocess` | `` | 9750 |
| Standard library | `import` | `sys` | `` | 14 |
| Standard library | `import` | `sys` | `` | 9750 |
| Standard library | `import` | `threading` | `` | 14 |
| Standard library | `import` | `threading` | `` | 25 |
| Standard library | `import` | `threading` | `` | 88 |
| Standard library | `from` | `threading` | `Lock` | 26 |
| Standard library | `import` | `time` | `` | 14 |
| Standard library | `import` | `time` | `` | 38 |
| Standard library | `import` | `traceback` | `` | 8950 |
| Standard library | `import` | `traceback` | `` | 9206 |
| Standard library | `import` | `traceback` | `` | 9472 |
| Standard library | `import` | `traceback` | `` | 9554 |
| Standard library | `from` | `typing` | `Any` | 16 |
| Standard library | `from` | `typing` | `Dict` | 16 |
| Standard library | `from` | `typing` | `List` | 16 |
| Standard library | `from` | `typing` | `Optional` | 16 |
| Standard library | `from` | `typing` | `Tuple` | 16 |
| Standard library | `import` | `unicodedata` | `` | 22 |
| Standard library | `from` | `urllib.parse` | `quote` | 23 |
| Standard library | `from` | `urllib.parse` | `urlparse` | 23 |
| Standard library | `from` | `urllib.parse` | `urlunparse` | 23 |
| Standard library | `import` | `uuid` | `` | 14 |
| Standard library | `import` | `uuid` | `` | 38 |
| Tiers | `import` | `dirtyjson` | `` | 97 |
| Tiers | `import` | `docx` | `` | 34 |
| Tiers | `from` | `docx` | `Document` | 8872 |
| Tiers | `from` | `docx` | `Document` | 9184 |
| Tiers | `from` | `docx` | `Document` | 9055 |
| Tiers | `from` | `docx` | `Document` | 9124 |
| Tiers | `from` | `dotenv` | `load_dotenv` | 95 |
| Tiers | `import` | `fitz` | `` | 83 |
| Tiers | `from` | `flask` | `Blueprint` | 2 |
| Tiers | `from` | `flask` | `Flask` | 2 |
| Tiers | `from` | `flask` | `current_app` | 2 |
| Tiers | `from` | `flask` | `current_app` | 39 |
| Tiers | `from` | `flask` | `jsonify` | 2 |
| Tiers | `from` | `flask` | `jsonify` | 8424 |
| Tiers | `from` | `flask` | `jsonify` | 5133 |
| Tiers | `from` | `flask` | `request` | 2 |
| Tiers | `from` | `flask` | `send_file` | 2 |
| Tiers | `from` | `flask_cors` | `CORS` | 28 |
| Tiers | `from` | `langdetect` | `DetectorFactory` | 35 |
| Tiers | `from` | `langdetect` | `detect` | 35 |
| Tiers | `from` | `llama_cpp` | `Llama` | 11 |
| Tiers | `from` | `llama_cpp.llama_chat_format` | `Llava15ChatHandler` | 91 |
| Tiers | `import` | `numpy` | `` | 85 |
| Tiers | `import` | `pandas` | `` | 34 |
| Tiers | `import` | `pdfplumber` | `` | 34 |
| Tiers | `from` | `pypdf` | `PdfReader` | 84 |
| Tiers | `from` | `pypdf` | `PdfWriter` | 84 |
| Tiers | `import` | `requests` | `` | 29 |
| Tiers | `import` | `sentence_transformers` | `` | 41 |
| Tiers | `import` | `soundfile` | `` | 86 |
| Tiers | `import` | `spacy` | `` | 36 |
| Tiers | `import` | `torch` | `` | 3782 |
| Tiers | `from` | `waitress` | `serve` | 10637 |

## Modules internes utilisés

### `helper_paths`

Éléments importés :
- `CHROMA_HOST`
- `CHROMA_PORT`
- `QDRANT_HOST`
- `QDRANT_PORT`
- `chroma_client`
- `debug_paths_snapshot`
- `load_paths`
- `qdrant`

### `helpers_embed`

Éléments importés :
- `load_embedder`

### `ocr_utils`

Éléments importés :
- `OcrOptions`
- `run_ocr`
- `run_ocr_auto`

### `pseudonymizer`

Éléments importés :
- `depseudonymize`
- `load_registry`
- `pseudonymize_text`
- `purge_person`
- `save_registry`

### `rag_memoire_utils`

Éléments importés :
- `build_context`
- `build_memory_append`

### `rag_utils`

Éléments importés :
- `extraire_contenu_rag`

### `rag_vector_utils`

Éléments importés :
- `build_rag_context`
- `build_rag_context_store`
- `retrieve_sources`
- `retrieve_top_k_store`
- `upsert_csv_folder_into_chroma`
- `upsert_csv_folder_into_store`

### `voxtral_utils`

Éléments importés :
- `_excel_serial_from_datetime`
- `_ext_tag`
- `_fmt_hms`
- `_label_speakers_from_rules`
- `_read_lines`
- `_safe_stem`
- `create_voxtral_pipeline`
- `load_json_safe`
- `post_correct_transcript`
- `to_srt`
- `to_vtt`
- `transcribe_audio`
- `transcribe_with_diarization`
- `voxtral_chat`

### `web_scraper`

- import direct du module

### `web_scraper_premium`

- import direct du module

### `web_search_utils`

Éléments importés :
- `crawl_search`
- `log_sources`
