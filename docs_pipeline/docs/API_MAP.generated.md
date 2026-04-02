# API_MAP.generated.md

Cartographie générée automatiquement depuis `flask_server/gpt4all_flask.py`.

Nombre de routes détectées : **52**

## Répartition par catégorie

- **ASR** : 3 route(s)
- **Administration** : 8 route(s)
- **Autre** : 8 route(s)
- **Fichiers** : 3 route(s)
- **LLM** : 2 route(s)
- **OCR** : 4 route(s)
- **PDF** : 4 route(s)
- **Prompts** : 3 route(s)
- **Pseudonymisation** : 3 route(s)
- **RAG** : 8 route(s)
- **Vision** : 4 route(s)
- **Web** : 2 route(s)

| Catégorie | Méthodes | Route | Fonction | Ligne |
|---|---|---|---|---:|
| Administration | `GET` | `/__routes` | `__routes` | 8423 |
| Autre | `POST` | `/annoter` | `annoter` | 5380 |
| RAG | `POST` | `/annoter_rag` | `annoter_rag` | 6443 |
| RAG | `POST` | `/annoter_rag_memoire` | `annoter_rag_memoire` | 6794 |
| RAG | `POST` | `/annoter_rag_vecteur` | `annoter_rag_vecteur` | 6538 |
| Autre | `POST` | `/annoter_segments` | `annoter_segments` | 6159 |
| Autre | `GET` | `/annoter_stats` | `annoter_stats` | 6125 |
| Web | `POST` | `/annoter_web` | `annoter_web` | 6965 |
| Pseudonymisation | `GET` | `/anonymization_reports` | `list_anonymization_reports` | 5262 |
| PDF | `POST` | `/api/detect_piece_boundaries` | `detect_piece_boundaries` | 9959 |
| PDF | `POST` | `/api/split_pdf` | `split_pdf` | 10061 |
| PDF | `POST` | `/api/split_pdf_batch` | `split_pdf_batch` | 10205 |
| ASR | `GET` | `/asr_models` | `asr_models` | 5204 |
| ASR | `POST` | `/asr_voxtral` | `asr_voxtral` | 8431 |
| LLM | `POST` | `/chat_llm` | `chat_llm` | 6316 |
| LLM | `POST` | `/chat_orchestre` | `chat_orchestre` | 5148 |
| Vision | `GET` | `/comfyui/history` | `comfyui_history` | 10524 |
| Vision | `GET` | `/comfyui/image` | `comfyui_image` | 10496 |
| Vision | `POST` | `/comfyui/prompt` | `comfyui_prompt` | 10437 |
| Autre | `POST` | `/convert_to_csv_batch` | `convert_to_csv_batch` | 9573 |
| Autre | `GET` | `/debug_paths` | `debug_paths` | 10228 |
| Fichiers | `GET` | `/download_file` | `download_file` | 9848 |
| RAG | `POST` | `/export_rag_to_chroma` | `export_rag_to_chroma` | 9740 |
| Fichiers | `POST` | `/files` | `files_alias_upload` | 9841 |
| Administration | `GET` | `/health` | `health` | 9635 |
| RAG | `POST` | `/index_chroma_from_csv` | `index_chroma_from_csv` | 9718 |
| PDF | `POST` | `/infer_piece_titles` | `infer_piece_titles` | 9294 |
| Administration | `GET` | `/info` | `info` | 4935 |
| Administration | `GET` | `/model_info` | `model_info` | 6150 |
| Administration | `GET` | `/models` | `models_list_route` | 5126 |
| Administration | `GET` | `/models_index` | `models_index_route` | 5197 |
| Administration | `GET` | `/models_status` | `models_status` | 5108 |
| OCR | `POST` | `/ocr` | `ocr_route` | 9341 |
| OCR | `POST` | `/ocr_auto` | `ocr_auto_route` | 9477 |
| OCR | `GET` | `/ocr_grid` | `ocr_grid_get` | 5216 |
| OCR | `GET` | `/ocr_history` | `ocr_history_get` | 5232 |
| Administration | `GET` | `/ping` | `ping` | 4906 |
| Prompts | `GET` | `/prompts_structures` | `get_prompts_structures` | 5288 |
| Prompts | `PUT` | `/prompts_structures` | `put_prompts_structures` | 5307 |
| Prompts | `DELETE` | `/prompts_structures/item` | `delete_prompts_structure_item` | 5343 |
| Pseudonymisation | `GET` | `/pseudonym_map` | `pseudonym_map` | 9766 |
| Pseudonymisation | `POST` | `/pseudonym_purge` | `pseudonym_purge` | 9776 |
| Autre | `GET` | `/qa_logs` | `qa_logs_list` | 8352 |
| Autre | `POST` | `/qa_logs/purge` | `qa_logs_purge` | 8390 |
| RAG | `POST` | `/rag/context` | `rag_context` | 8299 |
| Autre | `POST` | `/scaffold_project_dirs` | `scaffold_project_dirs` | 9906 |
| Vision | `POST` | `/sd_generate` | `sd_generate` | 10251 |
| Web | `POST` | `/search_web` | `search_web` | 7328 |
| Fichiers | `POST` | `/upload_file` | `upload_file` | 9794 |
| RAG | `POST` | `/vector/search` | `vector_search` | 6720 |
| RAG | `POST` | `/vector/upsert_csv_dir` | `vector_upsert_csv_dir` | 6666 |
| ASR | `POST` | `/voxtral_chat` | `voxtral_chat_route` | 8959 |

## Détail par route

### `/__routes`

- **Méthodes** : `GET`
- **Fonction** : `__routes`
- **Ligne** : `8423`

### `/annoter`

- **Méthodes** : `POST`
- **Fonction** : `annoter`
- **Ligne** : `5380`

### `/annoter_rag`

- **Méthodes** : `POST`
- **Fonction** : `annoter_rag`
- **Ligne** : `6443`

### `/annoter_rag_memoire`

- **Méthodes** : `POST`
- **Fonction** : `annoter_rag_memoire`
- **Ligne** : `6794`

### `/annoter_rag_vecteur`

- **Méthodes** : `POST`
- **Fonction** : `annoter_rag_vecteur`
- **Ligne** : `6538`

### `/annoter_segments`

- **Méthodes** : `POST`
- **Fonction** : `annoter_segments`
- **Ligne** : `6159`

### `/annoter_stats`

- **Méthodes** : `GET`
- **Fonction** : `annoter_stats`
- **Ligne** : `6125`

### `/annoter_web`

- **Méthodes** : `POST`
- **Fonction** : `annoter_web`
- **Ligne** : `6965`

### `/anonymization_reports`

- **Méthodes** : `GET`
- **Fonction** : `list_anonymization_reports`
- **Ligne** : `5262`

### `/api/detect_piece_boundaries`

- **Méthodes** : `POST`
- **Fonction** : `detect_piece_boundaries`
- **Ligne** : `9959`

### `/api/split_pdf`

- **Méthodes** : `POST`
- **Fonction** : `split_pdf`
- **Ligne** : `10061`

### `/api/split_pdf_batch`

- **Méthodes** : `POST`
- **Fonction** : `split_pdf_batch`
- **Ligne** : `10205`

### `/asr_models`

- **Méthodes** : `GET`
- **Fonction** : `asr_models`
- **Ligne** : `5204`

### `/asr_voxtral`

- **Méthodes** : `POST`
- **Fonction** : `asr_voxtral`
- **Ligne** : `8431`

### `/chat_llm`

- **Méthodes** : `POST`
- **Fonction** : `chat_llm`
- **Ligne** : `6316`

### `/chat_orchestre`

- **Méthodes** : `POST`
- **Fonction** : `chat_orchestre`
- **Ligne** : `5148`

### `/comfyui/history`

- **Méthodes** : `GET`
- **Fonction** : `comfyui_history`
- **Ligne** : `10524`

### `/comfyui/image`

- **Méthodes** : `GET`
- **Fonction** : `comfyui_image`
- **Ligne** : `10496`

### `/comfyui/prompt`

- **Méthodes** : `POST`
- **Fonction** : `comfyui_prompt`
- **Ligne** : `10437`

### `/convert_to_csv_batch`

- **Méthodes** : `POST`
- **Fonction** : `convert_to_csv_batch`
- **Ligne** : `9573`

### `/debug_paths`

- **Méthodes** : `GET`
- **Fonction** : `debug_paths`
- **Ligne** : `10228`

### `/download_file`

- **Méthodes** : `GET`
- **Fonction** : `download_file`
- **Ligne** : `9848`

### `/export_rag_to_chroma`

- **Méthodes** : `POST`
- **Fonction** : `export_rag_to_chroma`
- **Ligne** : `9740`

### `/files`

- **Méthodes** : `POST`
- **Fonction** : `files_alias_upload`
- **Ligne** : `9841`

### `/health`

- **Méthodes** : `GET`
- **Fonction** : `health`
- **Ligne** : `9635`

### `/index_chroma_from_csv`

- **Méthodes** : `POST`
- **Fonction** : `index_chroma_from_csv`
- **Ligne** : `9718`

### `/infer_piece_titles`

- **Méthodes** : `POST`
- **Fonction** : `infer_piece_titles`
- **Ligne** : `9294`

### `/info`

- **Méthodes** : `GET`
- **Fonction** : `info`
- **Ligne** : `4935`

### `/model_info`

- **Méthodes** : `GET`
- **Fonction** : `model_info`
- **Ligne** : `6150`

### `/models`

- **Méthodes** : `GET`
- **Fonction** : `models_list_route`
- **Ligne** : `5126`

### `/models_index`

- **Méthodes** : `GET`
- **Fonction** : `models_index_route`
- **Ligne** : `5197`

### `/models_status`

- **Méthodes** : `GET`
- **Fonction** : `models_status`
- **Ligne** : `5108`

### `/ocr`

- **Méthodes** : `POST`
- **Fonction** : `ocr_route`
- **Ligne** : `9341`

### `/ocr_auto`

- **Méthodes** : `POST`
- **Fonction** : `ocr_auto_route`
- **Ligne** : `9477`

### `/ocr_grid`

- **Méthodes** : `GET`
- **Fonction** : `ocr_grid_get`
- **Ligne** : `5216`

### `/ocr_history`

- **Méthodes** : `GET`
- **Fonction** : `ocr_history_get`
- **Ligne** : `5232`

### `/ping`

- **Méthodes** : `GET`
- **Fonction** : `ping`
- **Ligne** : `4906`

### `/prompts_structures`

- **Méthodes** : `GET`
- **Fonction** : `get_prompts_structures`
- **Ligne** : `5288`

### `/prompts_structures`

- **Méthodes** : `PUT`
- **Fonction** : `put_prompts_structures`
- **Ligne** : `5307`

### `/prompts_structures/item`

- **Méthodes** : `DELETE`
- **Fonction** : `delete_prompts_structure_item`
- **Ligne** : `5343`

### `/pseudonym_map`

- **Méthodes** : `GET`
- **Fonction** : `pseudonym_map`
- **Ligne** : `9766`

### `/pseudonym_purge`

- **Méthodes** : `POST`
- **Fonction** : `pseudonym_purge`
- **Ligne** : `9776`

### `/qa_logs`

- **Méthodes** : `GET`
- **Fonction** : `qa_logs_list`
- **Ligne** : `8352`

### `/qa_logs/purge`

- **Méthodes** : `POST`
- **Fonction** : `qa_logs_purge`
- **Ligne** : `8390`

### `/rag/context`

- **Méthodes** : `POST`
- **Fonction** : `rag_context`
- **Ligne** : `8299`

### `/scaffold_project_dirs`

- **Méthodes** : `POST`
- **Fonction** : `scaffold_project_dirs`
- **Ligne** : `9906`

### `/sd_generate`

- **Méthodes** : `POST`
- **Fonction** : `sd_generate`
- **Ligne** : `10251`

### `/search_web`

- **Méthodes** : `POST`
- **Fonction** : `search_web`
- **Ligne** : `7328`

### `/upload_file`

- **Méthodes** : `POST`
- **Fonction** : `upload_file`
- **Ligne** : `9794`

### `/vector/search`

- **Méthodes** : `POST`
- **Fonction** : `vector_search`
- **Ligne** : `6720`

### `/vector/upsert_csv_dir`

- **Méthodes** : `POST`
- **Fonction** : `vector_upsert_csv_dir`
- **Ligne** : `6666`

### `/voxtral_chat`

- **Méthodes** : `POST`
- **Fonction** : `voxtral_chat_route`
- **Ligne** : `8959`
