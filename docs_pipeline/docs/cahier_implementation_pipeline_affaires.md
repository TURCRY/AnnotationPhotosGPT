# cahier_implementation_pipeline_affaires.md

## Statut du document

Ce document décrit principalement la cible d’architecture et de mise en œuvre attendue pour Codex.
Il ne doit pas être lu comme une photographie exacte de l’existant.
En cas d’écart, distinguer :
- existant opérationnel ;
- existant partiel ;
- cible à implémenter.

## Objet

Ce document fixe, pour Codex, le périmètre fonctionnel et technique à implémenter pour finaliser la **gestion documentaire des affaires RN d’expertise judiciaire** sur trois machines :

- **Laptop** : point d’entrée utilisateur, saisie et pilotage via `app.py`
- **NAS** : stockage canonique des dossiers d’affaires et synchronisation intermédiaire
- **PC fixe** : exécution serveur Flask (`gpt4all_flask.py`) et traitements lourds

Le principe directeur est le suivant :

1. la donnée est **initiée sur le laptop** ;
2. elle est **propagée automatiquement** vers le NAS et/ou le PC fixe selon la nature du flux ;
3. les traitements lourds, l’OCR, l’ASR, l’indexation RAG, la génération de documents et les automatisations sont **centralisés côté PC fixe** ;
4. les résultats utiles reviennent vers les emplacements projet prévus par l’arborescence v4.

---

## Sources de vérité à respecter

Codex doit travailler en prenant pour références prioritaires :

1. `app.py` : l’interface Streamlit décrit déjà le **contrat fonctionnel attendu côté serveur** ;
2. `arborescence_version_4.txt` : l’architecture documentaire de référence ;
3. le code déjà présent dans `gpt4all_flask.py` et ses modules associés ;
4. les scripts utilitaires existants du serveur Flask, à réutiliser plutôt qu’à réécrire.

Règle impérative :

- **ne pas casser les endpoints déjà utilisés par `app.py`** ;
- compléter les routes manquantes et harmoniser les payloads si nécessaire ;
- privilégier les correctifs de compatibilité et les ajouts incrémentaux.

---

## Architecture cible

## 1. Rôles par machine

### Laptop

Rôle :

- création et sélection d’une affaire ;
- alimentation initiale des pièces, dire, bordereaux, prompts, métadonnées ;
- gestion des parties ;
- dépôt de captations et fichiers légers ;
- pilotage des traitements ;
- récupération de résultats légers.

Le laptop ne doit **pas** porter les zones lourdes.

### NAS

Rôle :

- stockage canonique des affaires ;
- partage UNC de référence ;
- zone commune entre laptop et PC fixe ;
- conservation des dossiers métier ;
- transport documentaire entre les deux autres machines.

### PC fixe

Rôle :

- serveur Flask ;
- OCR, ASR, RAG, web, génération LLM ;
- découpage PDF ;
- conversion CSV ;
- préparation de livrables ;
- journaux techniques ;
- automatisations n8n.

---

## 2. Principe de stockage

### Canonique

Le **NAS** est la racine documentaire de référence pour l’affaire.

### Local laptop

Le laptop conserve :

- les zones légères ;
- les fichiers de travail nécessaires à la saisie ;
- les copies locales utiles à l’IHM.

### Local PC fixe

Le PC fixe travaille :

- soit directement sur l’UNC NAS ;
- soit sur des chemins projet vus côté `roots.pcfixe` dans `project_config.json`.

Codex doit respecter la logique déjà présente dans `app.py` :

- `roots.pcfixe`
- `roots.nas`
- `roots.laptop`
- `paths[...]`

et éviter toute duplication de conventions de chemin.

---

## Arborescence métier à respecter

Codex doit aligner les automatisations et routes sur l’arborescence v4 suivante :

- `AA_Expert_Admin/Depot_initial`
- `AA_Expert_Admin/_Paperless_Inbox`
- `AA_Expert_Admin/_Logs`
- `AB_Organisation_expertise`
- `AC_Journaux`
- `AD_Expert_Traitements/_Queue_OCR`
- `AD_Expert_Traitements/_OCR_Texte`
- `AD_Expert_Traitements/_Splits`
- `AD_Expert_Traitements/_CSV_RAG`
- `AD_Expert_Traitements/_Manifests`
- `AE_Expert_captations/...`
- `AF_Expert_ASR/transcriptions/...`
- `BA_Pieces_de_expert`
- `BB_Préparation_livrables`
- `BC_Traitement_automatise_livrables/{PCfixe,NAS,Laptop}`
- `BD_Etudes_diveres_Expert`
- `BE_Traitement_captations/...`
- `BF_Prefabrication_livrables/...`
- `BD_Exports`
- `CZ_Cloture`
- `_DB/project.sqlite`
- `_Config/project_config.json`
- `_Config/asr_lexique.json`
- `_Manifests`

---

## Contrat général à déduire de `app.py`

`app.py` constitue déjà un quasi-cahier des charges exécutable. Codex doit partir du principe que les routes appelées par cette IHM doivent exister et répondre dans un format JSON stable.

### Endpoints explicitement attendus par l’IHM

Au minimum, l’application appelle ou prévoit :

- `GET /ping`
- `GET /health`
- `GET /models_index`
- `POST /scaffold_project_dirs`
- `POST /annoter`
- `POST /annoter_rag`
- `POST /annoter_rag_vecteur`
- `POST /annoter_web`
- `POST /ocr`
- `POST /ocr_auto`
- `GET /ocr_grid`
- `POST /convert_to_csv_batch`
- `GET /asr_models`
- `POST /asr_voxtral`
- `POST /voxtral_chat`
- `POST /upload_file`
- `GET /prompts_structures`
- `PUT /prompts_structures`
- `DELETE /prompts_structures/item`
- `GET /qa_logs`
- `POST /qa_logs/purge`
- `POST /index_chroma_from_csv`
- `GET /anonymization_reports`
- `POST /infer_piece_titles`
- `POST /api/detect_piece_boundaries`
- `POST /api/split_pdf`
- `POST /api/split_pdf_batch`

Codex doit :

1. vérifier lesquels existent déjà ;
2. recenser les divergences de payload ;
3. créer les routes manquantes ;
4. ajouter des wrappers de compatibilité si les noms de champs ont dérivé.

---

## Objectif central

Le système doit permettre, pour une affaire judiciaire donnée :

- de créer l’affaire et son arborescence ;
- de gérer les parties ;
- de déposer des documents ;
- de détecter, découper, renommer et classer les pièces ;
- de générer les sorties OCR et CSV ;
- d’alimenter Paperless et le RAG ;
- de traiter les captations audio/photo ;
- de produire transcriptions, comptes rendus et livrables ;
- de journaliser les opérations ;
- d’orchestrer les flux via n8n entre laptop, NAS et PC fixe.

---

## Ce que Codex doit produire

Codex doit préparer deux catégories de livrables.

## A. Routes Flask manquantes ou incomplètes

Codex doit compléter `gpt4all_flask.py` et, si nécessaire, ses modules associés pour que tous les appels de `app.py` soient réellement supportés.

## B. Workflows n8n

Codex doit concevoir les workflows n8n qui automatisent la circulation des fichiers, l’enchaînement des traitements et les retours de résultats.

---

## Spécification fonctionnelle détaillée

## 1. Création d’affaire

### Entrée

Depuis `app.py`, une affaire est créée avec :

- `aff_id`
- `titre`
- `nas_root_unc`

### Attendus

Codex doit garantir que :

- l’arborescence est créée côté laptop pour les zones légères ;
- l’arborescence canonique est disponible côté NAS / PC fixe ;
- `_Config/project_config.json` est cohérent ;
- `_Config/_remote.url` est écrit ;
- `_Config/_remote.map.json` est écrit si la logique serveur l’utilise ;
- `_DB/project.sqlite` existe au moins comme base projet initiale ;
- `scaffold_project_dirs` sait recréer les dossiers manquants côté serveur.

### À vérifier côté Flask

- la route `/scaffold_project_dirs` doit résoudre `project_id` vers `project_config.json` ;
- elle doit créer les dossiers déclarés dans `paths` ;
- elle doit ignorer les templates avec `{Nom}` et autres placeholders non instanciés ;
- elle doit renvoyer une réponse structurée :
  - `ok`
  - `project_id`
  - `paths_created`
  - `paths_skipped`
  - `errors`

---

## 2. Gestion des parties

La logique métier est déjà largement portée par `app.py` côté laptop.

### Attendus serveur / automatisation

Codex doit prévoir :

- la consolidation éventuelle de `parties.json` dans SQLite si cela simplifie les requêtes ;
- une synchronisation fiable de :
  - `_Config/parties.json`
  - `AB_Organisation_expertise/Id_affaire_en_tete_dossier.xlsx`
  - `AA_Expert_Admin/_Logs/parties_update_*.json`

### n8n

Créer un workflow qui :

- surveille les modifications de `parties.json` ou du log de mise à jour ;
- pousse vers NAS si la modification a été initiée sur laptop ;
- notifie les traitements dépendants si besoin ;
- archive l’événement dans `BC_Traitement_automatise_livrables/NAS` ou `PCfixe` selon la convention retenue.

---

## 3. Dépôt initial des documents d’affaire

### Source

`AA_Expert_Admin/Depot_initial`

### Typologie

- dire
- bordereau
- pièces adverses
- documents entrants

### Objectif

Transformer un dépôt brut en flux documentaire exploitable.

### Automatisations n8n à prévoir

#### Workflow N8N-01 — Dépôt initial → qualification

Déclenchement :

- arrivée d’un fichier dans `AA_Expert_Admin/Depot_initial` côté NAS ou PC fixe.

Actions :

1. identifier l’affaire ;
2. journaliser l’arrivée du fichier ;
3. copier ou déplacer selon règle vers :
   - `_Queue_OCR` si PDF à traiter ;
   - `_Paperless_Inbox` si simple dépôt GED ;
   - `BA_Pieces_de_expert` pour les pièces émises par l’expert ;
4. lancer un webhook Flask si un traitement immédiat est attendu.

Résultat :

- événement tracé ;
- fichier rangé dans la bonne filière.

---

## 4. OCR et conversion documentaire

### Objectif

Transformer les documents déposés en sorties texte et CSV utilisables par le RAG et les traitements aval.

### Zones

Entrée :

- `AD_Expert_Traitements/_Queue_OCR`

Sorties :

- `AD_Expert_Traitements/_OCR_Texte`
- `AD_Expert_Traitements/_CSV_RAG`
- `AD_Expert_Traitements/_Manifests`

### Routes à vérifier / compléter

#### `POST /ocr`

Doit accepter au minimum :

- `input_path`
- `output_dir`
- `lang`
- `dpi`
- options OCR annexes
- `project_id`
- idéalement `rel_input` / `rel_output` pour résolution via config projet

Doit produire :

- texte OCR ;
- CSV ;
- éventuellement DOCX / HOCR selon options ;
- manifest JSON avec SHA256, pages, horodatage, statut.

#### `POST /ocr_auto`

Doit appliquer une grille OCR paramétrable.

#### `POST /convert_to_csv_batch`

Doit convertir un dossier de sorties en CSV normalisés pour RAG.

### Automatisations n8n à prévoir

#### Workflow N8N-02 — Queue OCR → OCR → CSV → indexation locale

Déclenchement :

- fichier entrant dans `_Queue_OCR`

Chaîne :

1. appeler `/ocr` ;
2. vérifier la présence des sorties ;
3. pousser les CSV vers `_CSV_RAG` si besoin séparé ;
4. écrire ou compléter le manifest ;
5. journaliser en cas d’échec.

Option :

- si succès, déclencher ensuite l’indexation vectorielle.

---

## 5. Détection de pièces et découpage PDF

Le pré-traitement dépôt PDF dans `app.py` révèle plusieurs besoins distincts.

### A. Détection des bornes de pièces

Route attendue : `POST /api/detect_piece_boundaries`

Entrée :

- `project_id`
- `csv_path`

Sortie :

- `ok`
- `pieces`: liste ordonnée contenant au moins
  - `numero`
  - `start_page`
  - `end_page`
  - éventuellement `title`

### B. Inférence de titres de pièces

Route attendue : `POST /infer_piece_titles`

Entrée :

- `sources` : CSV OCR issus du dire et/ou bordereau
- `max_piece_no`

Sortie :

- mapping `numero -> titre`
- `code_partie` si détectable
- `date_transmission` si détectable
- `used_sources`
- `notes`

### C. Découpage effectif

Routes attendues :

- `POST /api/split_pdf`
- `POST /api/split_pdf_batch`

Chaque route doit :

- résoudre les chemins projet ;
- effectuer un dry-run fiable ;
- découper le PDF ;
- renommer selon le schéma attendu ;
- écrire les PDF découpés dans `_Splits` ;
- produire un manifest ;
- retourner une réponse détaillée exploitable par l’IHM.

### Schéma minimal d’un job de split

- `project_id`
- `input_path` ou (`rel_input` + nom de fichier)
- `output_dir` ou `rel_output`
- `pieces[]` avec
  - `numero`
  - `start_page`
  - `end_page`
  - `filename`
  - `title`
- `dry_run`
- `overwrite`

### Automatisation n8n à prévoir

#### Workflow N8N-03 — Split validé → classement documentaire

Après split :

1. envoyer les PDF découpés vers :
   - `_Splits` en technique ;
   - `_Paperless_Inbox` si GED attendue ;
   - éventuellement `01..40_Partie_xx_...` si classement partie décidé ;
2. produire un CSV ou manifest de suivi ;
3. alimenter `_CSV_RAG` si conversion requise ;
4. archiver le rapport de découpe.

---

## 6. RAG local et RAG vectoriel

## A. RAG local PC fixe

Route : `POST /annoter_rag`

Le dossier RAG doit être dérivé de la config projet, pas codé en dur.

À prévoir :

- résolution sûre du dossier `RAG_PC` ;
- indexation ou lecture locale ;
- support de l’injection des Q&A récents.

## B. RAG vectoriel

Routes :

- `POST /index_chroma_from_csv`
- `POST /annoter_rag_vecteur`
- `GET /anonymization_reports`

### Attendus

- indexation d’un dossier CSV projet ;
- choix backend `chroma` ou `qdrant` ;
- pseudonymisation optionnelle ;
- conservation d’un rapport d’anonymisation ;
- restitution des distances si demandé ;
- limitation de taille de contexte.

### Automatisation n8n à prévoir

#### Workflow N8N-04 — CSV RAG → indexation vectorielle

Déclenchement :

- création ou modification dans `_CSV_RAG`

Chaîne :

1. appeler `/index_chroma_from_csv` ;
2. écrire un log d’indexation ;
3. éventuellement déplacer les CSV traités dans un sous-état logique ;
4. notifier l’utilisateur en cas d’échec critique.

---

## 7. Historique Q&A et bibliothèque de prompts

### Routes à stabiliser

- `GET /qa_logs`
- `POST /qa_logs/purge`
- `GET /prompts_structures`
- `PUT /prompts_structures`
- `DELETE /prompts_structures/item`

### Attendus

#### Q&A

- journalisation par `project_id` ;
- stockage exploitable par l’injection de mémoire glissante ;
- purge par ancienneté.

#### Prompts structurés

- stockage projet ;
- lecture / écriture idempotente ;
- suppression par nom.

### Recommandation d’implémentation

Codex peut centraliser ces données dans :

- `project.sqlite`
- ou des JSON sous `_Config`

mais doit choisir un **seul mode canonique** et prévoir une compatibilité avec l’existant.

---

## 8. Upload générique de fichiers

Route : `POST /upload_file`

Cette route est centrale. Elle doit être rendue robuste.

### Attendus

Entrées possibles :

- `project_id`
- `area`
- `subdir`
- `filename`
- `overwrite`
- fichier multipart

### Règles

- résoudre le chemin cible à partir du projet ;
- interdire les traversées de répertoires ;
- créer les dossiers si nécessaires ;
- renvoyer le chemin final ;
- journaliser ;
- pouvoir servir pour :
  - dépôt initial ;
  - ressources ASR ;
  - prompts ;
  - fichiers annexes.

### Workflow n8n

#### N8N-05 — Upload terminé → post-traitement par type

Après tout upload :

- classifier le fichier par extension / dossier / zone métier ;
- déclencher la suite appropriée.

---

## 9. Captations photo / audio

L’arborescence prévoit des captations riches dans `AE_Expert_captations` et des traitements dans `BE_Traitement_captations`.

## A. Captations source

Chaque `id_captation` peut contenir :

- audio WAV
- photos JPG
- photos réduites
- RAW2
- CSV de photos
- CSV validés et versions tableur

## B. ASR et transcriptions

Routes attendues :

- `GET /asr_models`
- `POST /asr_voxtral`
- `POST /voxtral_chat`

### Attendus de `/asr_voxtral`

Supporter :

- transcription simple ;
- timestamps ;
- diarisation optionnelle ;
- vocabulaire métier ;
- glossaire ;
- alias locuteurs ;
- export CSV/SRT/VTT ;
- génération de comptes rendus si prompt fourni ;
- sortie vers dossier projet.

### Attendus de `/voxtral_chat`

Supporter :

- génération de CR à partir d’un CSV de transcription existant ;
- usage de templates ;
- export DOCX/CSV ;
- stockage dans l’arborescence projet.

### Automatisations n8n à prévoir

#### Workflow N8N-06 — Captation audio → transcription

Déclenchement :

- fichier audio dans un dossier surveillé ou dépôt via upload.

Actions :

1. copier l’audio vers le dossier attendu par le PC fixe ;
2. appeler `/asr_voxtral` ;
3. ranger les sorties dans `AF_Expert_ASR/transcriptions/id_captation` et/ou `BE_Traitement_captations/id_captation` selon type de sortie ;
4. journaliser le run.

#### Workflow N8N-07 — CSV transcription → compte rendu LLM

Déclenchement :

- présence d’un CSV validé ou d’une demande explicite.

Actions :

1. appeler `/voxtral_chat` ;
2. ranger le DOCX dans `BE_Traitement_captations/id_captation/compte_rendu_LLM` ;
3. ranger logs et intermédiaires dans `out/`.

#### Workflow N8N-08 — Photos → batch annotation / consolidation

Déclenchement :

- modification du CSV de photos ou arrivée des JPG réduits.

Actions possibles :

- normaliser les CSV ;
- déclencher un traitement batch photo ;
- produire annotation et fichiers consolidés ;
- écrire dans `BE_Traitement_captations/id_captation`.

---

## 10. Livrables et exports

Les zones aval sont :

- `BB_Préparation_livrables`
- `BC_Traitement_automatise_livrables`
- `BF_Prefabrication_livrables`
- `BD_Exports`

### Attendus

Codex doit prévoir une mécanique simple :

- un dossier de travail automatisé par machine ;
- une convention claire sur ce qui est transitoire et ce qui est final ;
- une route ou un flux n8n pour passer un document de l’état “brouillon” à l’état “export”.

### Workflow n8n

#### N8N-09 — Livrable prêt → export final

Déclenchement :

- DOCX/PDF finalisé dans un dossier de préparation.

Actions :

1. contrôles de présence de métadonnées ;
2. renommage standardisé ;
3. copie vers `BD_Exports` ;
4. log de diffusion / version.

---

## 11. GED / Paperless

Le dossier `_Paperless_Inbox` doit être exploitable automatiquement.

### Workflow n8n

#### N8N-10 — Envoi vers GED

Déclenchement :

- arrivée d’un document qualifié dans `_Paperless_Inbox`

Actions :

- laisser Paperless consommer le fichier ;
- ou appeler une API dédiée si vous en avez une ;
- écrire un statut de prise en charge.

---

## 12. Santé serveur et réveil PC fixe

L’IHM laptop dépend fortement de :

- `/ping`
- `/health`
- logique WOL déjà présente.

### Attendus Flask

- `/ping` doit être ultra léger ;
- `/health` doit renvoyer un JSON synthétique ;
- ne pas bloquer sur des tests lourds ;
- exposer au moins :
  - `ok`
  - `hostname`
  - `time`
  - `models_loaded` ou équivalent
  - `storage` minimal si facile à obtenir

### Attendus n8n

Éventuellement prévoir un watchdog :

#### N8N-11 — Watchdog technique

- surveiller la disponibilité du partage NAS ;
- surveiller le serveur Flask ;
- produire une alerte locale ou un log technique.

---

## Exigences techniques de mise en œuvre

## 1. Résolution de chemins

Codex doit créer un utilitaire unique côté serveur pour résoudre les chemins projet.

### Objectif

Éviter la multiplication de concaténations hasardeuses.

### Fonctions cibles recommandées

- `load_project_config(project_id)`
- `resolve_project_root(project_id, context="pcfixe")`
- `resolve_rel_path(project_id, rel_key, context="pcfixe")`
- `safe_join_project_path(...)`

### Règles

- toujours partir de `project_config.json` ;
- privilégier `roots.pcfixe` côté serveur ;
- accepter `rel_input` / `rel_output` dans les endpoints ;
- valider que le chemin final reste sous la racine projet ;
- interdire les chemins arbitraires non autorisés, sauf cas explicitement assumé.

---

## 2. Journalisation

Chaque route ajoutée ou complétée doit journaliser proprement.

### Minimum attendu

- timestamp
- route
- project_id
- statut
- fichiers entrants
- fichiers produits
- erreur structurée si échec

### Emplacements recommandés

- `AA_Expert_Admin/_Logs`
- `AD_Expert_Traitements/_Manifests`
- `BE_Traitement_captations/.../out/logs`

---

## 3. Réponses JSON homogènes

Toutes les routes nouvelles ou corrigées doivent respecter un schéma cohérent :

```json
{
  "ok": true,
  "project_id": "2025-J25",
  "message": "...",
  "data": {},
  "warnings": [],
  "errors": []
}
```

Et en cas d’échec :

```json
{
  "ok": false,
  "project_id": "2025-J25",
  "error": "message synthétique",
  "details": {}
}
```

L’IHM actuelle supporte parfois des retours plus libres ; Codex peut conserver les champs historiques, mais doit tendre vers une forme stable.

---

## 4. Compatibilité avec l’existant

Codex ne doit pas procéder à une réécriture globale sans nécessité.

### Règle

Faire :

- des utilitaires communs ;
- des wrappers ;
- des corrections ciblées ;
- des tests par endpoint.

Éviter :

- de modifier brutalement les noms de payload attendus par `app.py` ;
- de déplacer des fichiers sans maintenir la compatibilité ;
- de fusionner plusieurs concepts métier sans nécessité.

---

## Liste priorisée des travaux à faire par Codex

## Priorité 1 — Audit du contrat IHM ↔ Flask

1. inventorier tous les appels HTTP de `app.py` ;
2. comparer avec les routes réellement présentes dans `gpt4all_flask.py` ;
3. dresser la matrice :
   - route existante / absente
   - payload conforme / divergent
   - réponse conforme / divergente

## Priorité 2 — Utilitaires de projet

4. factoriser le chargement de `project_config.json` ;
5. factoriser la résolution de chemins projet ;
6. factoriser la journalisation technique.

## Priorité 3 — Compléter les routes critiques

7. `scaffold_project_dirs`
8. `upload_file`
9. `infer_piece_titles`
10. `api/detect_piece_boundaries`
11. `api/split_pdf`
12. `api/split_pdf_batch`
13. `index_chroma_from_csv`
14. `prompts_structures`
15. `qa_logs`
16. `asr_models`
17. `asr_voxtral`
18. `voxtral_chat`

## Priorité 4 — Automatisations n8n

19. dépôt initial ;
20. OCR ;
21. split + classement ;
22. indexation RAG ;
23. transcription ASR ;
24. CR LLM ;
25. export final ;
26. watchdog technique.

---

## Livrables attendus de Codex

Codex doit produire :

### 1. Un rapport d’audit

Fichier conseillé : `AUDIT_ROUTES_APP_FLASK.md`

Contenu :

- tableau des routes appelées par `app.py` ;
- statut d’existence ;
- écarts de payload ;
- écarts de réponses ;
- correctifs prévus.

### 2. Les correctifs Flask

- modifications de `gpt4all_flask.py`
- modifications éventuelles des modules utilitaires associés
- ajout de helpers si utile

### 3. Les workflows n8n

Fichiers conseillés :

- `n8n_01_depot_initial.json`
- `n8n_02_ocr_queue.json`
- `n8n_03_split_classement.json`
- `n8n_04_indexation_rag.json`
- `n8n_05_upload_dispatch.json`
- `n8n_06_asr_transcription.json`
- `n8n_07_voxtral_compte_rendu.json`
- `n8n_08_photos_batch.json`
- `n8n_09_export_final.json`
- `n8n_10_paperless.json`
- `n8n_11_watchdog.json`

### 4. Un README technique d’intégration

Fichier conseillé : `README_pipeline_affaires_implementation.md`

Contenu :

- variables d’environnement nécessaires ;
- ordre de déploiement ;
- prérequis ;
- points d’attention NAS/UNC/Windows ;
- stratégie de tests.

---

## Contraintes impératives

1. **Windows first** : tous les chemins et traitements doivent rester compatibles Windows.
2. **UNC first** côté documentaire canonique.
3. **Pas de hardcode sauvage** des chemins d’affaire.
4. **Pas de rupture du contrat `app.py`** sans wrapper de compatibilité.
5. **Journalisation obligatoire** des actions importantes.
6. **Sécurité minimale** sur l’upload et la résolution de chemins.
7. **Idempotence** autant que possible pour les workflows n8n.
8. **Dry-run réel** pour les opérations destructives ou de découpe.
9. **Réponses JSON stables** pour les appels de l’IHM.
10. **Réutiliser l’existant** avant d’ajouter de nouvelles conventions.

---

## Hypothèses de travail que Codex doit vérifier dans le code serveur

Codex doit explicitement vérifier :

- où est chargé `projets_index.json` ;
- si le serveur sait déjà résoudre `project_id -> project_config.json` ;
- si les routes OCR/ASR utilisent déjà des helpers chemin ;
- si les retours JSON sont homogènes ;
- si Chroma/Qdrant sont déjà correctement encapsulés ;
- si des routes appelées par `app.py` ne sont que partiellement implémentées ;
- si l’upload multipart est déjà sécurisé ;
- si le découpage PDF et la détection de bornes existent déjà sous d’autres noms.

---

## Critère de réussite

Le chantier sera considéré comme réussi lorsque :

1. `app.py` peut être utilisé sans erreur 404/500 sur ses fonctionnalités principales ;
2. une affaire peut être créée et rechargée ;
3. un dépôt PDF peut être OCRisé, analysé et découpé ;
4. les sorties sont classées dans l’arborescence v4 ;
5. les CSV alimentent le RAG ;
6. une captation audio peut être transcrite puis résumée ;
7. les workflows n8n enchaînent les tâches sans manipulation manuelle lourde ;
8. les logs permettent d’expliquer chaque action et chaque échec.

---

## 13. Intégration Paperless (GED)

### Positionnement

Paperless est une **GED annexe**. La source canonique métier demeure l’arborescence d’affaire sur NAS.

### Ingestion

Deux modes possibles :

1. Dépôt dans `AA_Expert_Admin/_Paperless_Inbox` puis consommation par Paperless (`consume`) ;
2. Appel API Paperless (`/api/documents/post_document/`) pour poser les métadonnées dès l’entrée.

Recommandation : privilégier l’API pour garantir la cohérence des métadonnées.

### Métadonnées Paperless à exploiter

- `title`
- `created`
- `correspondent`
- `document_type`
- `tags`
- `custom_fields`
- `archive_serial_number`

### Clés personnalisées (custom_fields) à imposer

- `project_id`
- `doc_uid`
- `piece_no`
- `party_code`
- `source_sha256`

### Post-consume

Mettre en place un script post-consommation Paperless pour récupérer :

- `DOCUMENT_ID`
- `DOCUMENT_ARCHIVE_PATH`
- `DOCUMENT_ORIGINAL_FILENAME`
- `DOCUMENT_TAGS`

et alimenter la base projet (table `paperless_links`).

---

## 14. Modèle de données canonique

### A. Base projet (SQLite)

#### Table `documents`

- `doc_uid` (PK)
- `project_id`
- `piece_no`
- `title`
- `doc_type`
- `party_code`
- `document_date`
- `source_filename`
- `source_sha256`
- `nas_path`
- `pcfixe_path`
- `ocr_text_path`
- `csv_rag_path`
- `status`
- `created_at`
- `updated_at`

#### Table `document_pages`

- `doc_uid`
- `page_no`
- `ocr_text`
- `ocr_confidence`

#### Table `document_chunks`

- `chunk_uid` (PK)
- `doc_uid`
- `project_id`
- `chunk_index`
- `page_start`
- `page_end`
- `text`
- `token_count`
- `embedding_model`
- `vector_backend`
- `indexed_at`

#### Table `paperless_links`

- `doc_uid`
- `paperless_document_id`
- `paperless_task_id`
- `paperless_original_filename`
- `paperless_archive_path`
- `paperless_download_url`
- `paperless_created`
- `paperless_added`
- `paperless_correspondent`
- `paperless_tags_json`

---

## 15. Métadonnées minimales pour le RAG vectoriel

Chaque chunk indexé doit contenir au minimum :

- `project_id`
- `doc_uid`
- `chunk_uid`
- `title`
- `doc_type`
- `party_code`
- `document_date`
- `page_start`
- `page_end`
- `source_sha256`
- `nas_path`
- `paperless_document_id`
- `paperless_original_filename`

Principe : **le RAG doit pointer vers un document métier stable (doc_uid), jamais uniquement vers Paperless**.

---

## 16. Mapping global des identifiants

- `project_id` : identifiant affaire
- `doc_uid` : identifiant interne document (canonique)
- `piece_no` : logique judiciaire
- `paperless_document_id` : identifiant GED externe
- `source_sha256` : clé de contrôle et de rapprochement

Relation :

- `doc_uid` → clé centrale du pipeline
- `paperless_document_id` → lien secondaire

---

## 17. Règles d’intégration Paperless ↔ Pipeline

1. Aucun traitement métier critique ne dépend exclusivement de Paperless.
2. Toute ingestion Paperless doit être tracée dans `project.sqlite`.
3. Toute indexation RAG doit référencer `doc_uid`.
4. Les fichiers restent stockés et accessibles sur NAS.
5. Paperless sert à :
   - consultation
   - recherche documentaire secondaire
   - diffusion éventuelle

---

## 18. Décision d’architecture OCR

Deux stratégies possibles :

### Option A (recommandée)

- OCR réalisé exclusivement sur PC fixe
- Paperless utilisé sans OCR (`PAPERLESS_OCR_MODE=skip`)

### Option B

- OCR délégué partiellement à Paperless (Tika/Gotenberg)

Codex doit prévoir les deux mais implémenter par défaut l’option A.

---

## Instruction finale à Codex

À partir de ce document, du contenu de `app.py`, de `arborescence_version_4.txt`, du code serveur et de la configuration Paperless :

1. auditer le contrat exact entre l’IHM et le serveur ;
2. identifier les routes manquantes, incomplètes ou divergentes ;
3. implémenter les correctifs minimaux mais robustes ;
4. intégrer le modèle de données défini ci-dessus ;
5. produire les workflows n8n nécessaires ;
6. assurer la cohérence entre pipeline, base projet, RAG et Paperless ;
7. livrer un plan de tests complet ;
8. documenter tout écart.

En cas d’ambiguïté, suivre la logique métier de `app.py` et de l’arborescence v4.

