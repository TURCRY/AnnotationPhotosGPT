# API_MAP - GPT4All_Local

Sous-ensemble documente ici : routes effectivement utilisees par [app.py](D:/GPT4All_Local/docs/app_reference/app.py) et stables au regard du code actuel de [gpt4all_flask.py](D:/GPT4All_Local/flask_server/gpt4all_flask.py).

Point d'entree principal :
`flask_server/gpt4all_flask.py`

Principe :
- ne sont listes que les champs reellement lus par la route ou utiles cote client
- les reponses de succes sont volontairement reduites au noyau utile
- les erreurs mentionnent uniquement le noyau observable et stable

---

# 1. Routes LLM / RAG / Web

## /annoter

Usage cote client :
- generation standard depuis `app.py`

Payload effectivement lu :
- `prompt`
- `task` ou `tname`
- `model_name` ou `model`
- `system`
- `history` ou `messages`
- `expect_json`
- `dictee_asr_text`
- `prefer_dictee`
- `salient_families`
- `max_tokens`
- `marge`
- `min_prompt_tokens`
- `overrides`
- `do_not_log`

Reponse utile :
- `reponse`
- `reponse_json`
- `validation_errors`
- `request_id`

Compatibilite utile :
- en erreur de verrou, la route peut renvoyer `error` et `request_id`
- en succes, `app.py` exploite surtout le JSON brut affiche a l'ecran

## /annoter_rag

Usage cote client :
- mode "RAG (PC fixe)" dans `app.py`

Payload effectivement lu :
- `prompt`
- `rag_dossier_pcfixe`
- `model_name` ou `model`
- `system`
- `include_qa_logs`
- `project_id`
- `do_not_log`
- champs de generation lus : `temperature`, `top_p`, `top_k`, `repeat_penalty`, `max_tokens`

Reponse utile :
- `reponse`

Erreurs observables :
- `error`

Compatibilite utile :
- `rag_dossier_pcfixe` est obligatoire
- le code lit des champs de generation, mais le contrat stable a documenter ici reste surtout `prompt` + `rag_dossier_pcfixe` + `model_name` + `system`

## /annoter_rag_vecteur

Usage cote client :
- page dediee RAG vectoriel dans `app.py`

Payload effectivement lu :
- `prompt`
- `model_name` ou `model`
- `system` ou `system_prompt`
- `project_id`
- `collection`
- `top_k`
- `show_distances`
- `max_total_chars`
- `vec_backend`
- `qdrant_url`
- `qdrant_api_key`
- `chroma_dir`
- `mode`
- `filters`
- `anonymize`
- `include_qa_logs`
- `qa_limit`
- `qa_last_lines_per_file`
- `lang`

Reponse utile :
- `reponse`
- `model`
- `used_params`
- `context_len`
- `sources`
- `anonymized`

Erreurs observables :
- `error`

Compatibilite utile :
- le contrat client/serveur aligne utilise `top_k`, `show_distances`, `max_total_chars`
- les anciens noms `k`, `show_scores`, `max_ctx_chars` ne font pas partie du contrat cible documente

## /annoter_web

Usage cote client :
- page "Web / Recherche" dans `app.py`

Payload de premier niveau effectivement lu :
- `prompt`
- `model_name` ou `model`
- `project_id`
- `web_context`
- `citations`

Payload `web` effectivement lu :
- `query_or_url` ou `query`
- `scrape`
- `premium`
- `max_depth`
- `download_html`
- `headers`
- `cookies`
- `user_agent`
- `rate_limit`
- `allowed_domains`
- `disallow_patterns`
- `limit_sources`
- `dedupe_sources`
- `return_web_context`
- `save_to_rag_pc`
- `max_hosts`
- `max_pages`
- `timeout_s`
- `max_results_seed`

Reponse utile :
- `reponse`
- `reponse_html`
- `reponse_with_refs`
- `reponse_with_refs_html`
- `sources`
- `used_sources`
- `citations`
- `model`
- `gen`
- `trace`
- `pages_count`
- `query_or_url`
- `styles`
- `save_to_rag_pc`
- `reponse_json` si un JSON exploitable a ete detecte
- `web_context` seulement si `web.return_web_context == true`

Compatibilite utile :
- `system` n'est pas consomme par la route dans son flux actuel
- `save_to_rag_pc` est effectivement supporte et la reponse retourne un objet `save_to_rag_pc` avec au minimum :
  - `requested`
  - `saved`
  - `location`
  - `path`
  - `dir`
  - `meta_path`
  - `error` si echec

---

# 2. Routes fichiers et historique

## /upload_file

Usage cote client :
- upload de ressources vers le projet courant dans `app.py`

Type de requete :
- `multipart/form-data`

Champs effectivement lus :
- fichier `file`
- `project_id`
- `area`
- `subdir`
- `filename`
- `overwrite`

Reponse utile en succes :
- `ok`
- `project_id`
- `area`
- `subdir`
- `filename`
- `path`
- `size`

Erreurs observables :
- `error`
- `path` peut etre present sur conflit `overwrite=false`

Compatibilite utile :
- le client ne doit pas dependre d'un champ `message`

## /qa_logs

Usage cote client :
- chargement de l'historique Q&A du projet courant

Type de requete :
- `GET`

Parametres effectivement lus :
- `project_id`
- `limit`

Reponse utile en succes :
- `ok`
- `count`
- `items`

Reponse d'erreur minimale actuelle :
- `ok: false` sur les erreurs metier / validation / serveur
- `error`

Compatibilite utile :
- `app.py` lit `items` seulement si `ok` est vrai

## /qa_logs/purge

Usage cote client :
- purge des anciens journaux Q&A du projet courant

Type de requete :
- `POST`

Payload effectivement lu :
- `project_id`
- `older_than_days`

Reponse utile en succes :
- `ok`
- `removed`

Reponse d'erreur minimale actuelle :
- `ok: false` sur les erreurs metier / validation / serveur
- `error`

Compatibilite utile :
- le succes ne change pas de format
- le client peut afficher brut le JSON de retour

---

# 3. Notes de compatibilite

- Les routes ci-dessus restent sensibles car elles sont appelees directement par `app.py`.
- `adapter.py` aligne deja `/annoter_rag_vecteur` sur `top_k`, `show_distances`, `max_total_chars`.
- Pour `/upload_file`, le contrat stable cote client repose sur `ok`, `filename`, `path`, `size`.
- Pour `/qa_logs` et `/qa_logs/purge`, le noyau minimal d'erreur cote client est `error`, avec `ok: false` sur les erreurs harmonisees de ces routes.
