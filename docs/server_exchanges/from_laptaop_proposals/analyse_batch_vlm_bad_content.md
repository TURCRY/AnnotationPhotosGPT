PROPOSITION NON VALIDÉE

- fichiers concernés : `C:\AnnotationPhotosGPT\batch_pcfixe\batch_all_photos_pcfixe.py`
- objectif : analyser pourquoi certaines réponses VLM textuelles/transcriptionnelles sont acceptées puis stockées dans `description_vlm_batch`
- impact : aucune modification appliquée ; analyse et patch proposés uniquement
- niveau de risque : faible pour le correctif proposé

## 1. Réponse serveur VLM : où elle est reçue

La réponse serveur du PASS 1 VLM est reçue dans :

- `post_vision_describe_batch(...)`
- puis exploitée dans `flush_vlm_batch(...)`

Chemin exact :

1. `post_vision_describe_batch(...)` fait le `POST` vers `/vision/describe_batch` et retourne `payload["results"]` ou une liste brute.
2. `flush_vlm_batch(...)` récupère cette liste dans `results`.

Points de code repérés :

- appel HTTP VLM batch : autour de `869-909`
- consommation des résultats : autour de `985-1091`

## 2. Où la valeur est stockée dans `description_vlm_batch`

Dans `flush_vlm_batch(...)`, la valeur `r.get("description")` est convertie en chaîne puis écrite telle quelle dans :

- `b["description_vlm_batch"] = desc`

Cela se produit dans les deux branches :

- fallback par ordre : lignes autour de `1048-1055`
- mapping complet par nom : lignes autour de `1075-1082`

Il n'y a aujourd'hui aucun contrôle sémantique sur le contenu avant l'écriture.

## 3. Garde-fous actuellement présents

Les garde-fous existants vérifient seulement :

- forme de la réponse (`ERR_VLM_BAD_RESPONSE_SHAPE`)
- exception batch (`ERR_VLM_BATCH`)
- erreur par item (`ERR_VLM_RESULT`)
- description vide (`ERR_VLM_EMPTY`)

En revanche, il manque un garde-fou de contenu pour rejeter une sortie qui :

- contient `SPEAKER_`
- contient `CONTEXTE TEXTE`
- ressemble à de la transcription orale ou à du prompt/context retourné
- n'est donc manifestement pas une description image

## 4. Origine probable du bug

Le PASS 1 VLM construit un contexte spécifique à partir de la transcription :

- `transcript_excerpt = extract_transcript_window(...)`
- `ctx = build_vlm_specific_context(transcript_excerpt)`

Puis ce contexte est envoyé au VLM batch.

Le problème n'est pas l'existence de ce contexte en soi, mais le fait qu'aucune validation ne filtre une réponse serveur qui recopie ou mélange ce contexte textuel dans le champ `description`.

Autrement dit :

- la réponse serveur est reçue ;
- `desc` est non vide ;
- elle est donc acceptée automatiquement ;
- puis stockée dans `description_vlm_batch` même si son contenu est en réalité transcriptionnel.

## 5. Correctif minimal recommandé

Ajouter un validateur de contenu juste avant l'écriture de `description_vlm_batch`.

### Principe

Rejeter `desc` si au moins un des signaux suivants est présent :

- `CONTEXTE TEXTE`
- `TRANSCRIPTION (extrait)`
- au moins un tag `SPEAKER_`
- très forte densité de marqueurs oraux / prose longue incompatible avec une description image

### Comportement recommandé

Si le contenu est invalide :

- `mark_vlm_err_batch(b, "ERR_VLM_BAD_CONTENT", batch_id=current_batch_id)`
- ne pas écrire `description_vlm_batch`
- conserver `vlm_status = "ERR"`

Ce correctif :

- ne change pas le contrat CSV ;
- ne change pas le pipeline global ;
- ne touche pas aux prompts ;
- sécurise seulement le point d'acceptation de la sortie VLM.

## 6. Message de commit recommandé

`Reject transcription-like VLM outputs before writing description_vlm_batch`
