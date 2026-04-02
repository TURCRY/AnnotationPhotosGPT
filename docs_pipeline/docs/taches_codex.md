# Tâches Codex

Les modifications doivent respecter les règles définies dans `AGENTS.md`.

Les changements doivent être locaux, prudents et limiter les risques de régression.

## Règles générales

- ne modifier que les fichiers explicitement utiles à la tâche ;
- ne pas refactoriser globalement le serveur ;
- ne pas changer une route, un payload JSON ou un nom de champ sans nécessité explicite ;
- ne pas modifier les scripts `.bat` ou `.ps1` sauf demande expresse ;
- privilégier des modifications minimales, testables et réversibles ;
- en cas d’ambiguïté, conserver le comportement existant.

## Cohérence client / adapter / serveur

Pour toute tâche touchant un contrat d’appel API client/serveur, vérifier la cohérence entre :

- `docs/app_reference/app.py`
- `docs/app_reference/adapter.py`
- `flask_server/gpt4all_flask.py`

Ne pas modifier `app.py` seul si `adapter.py` applique ou transforme les mêmes champs.

`adapter.py` est la couche de normalisation des appels API.

Toute évolution de contrat côté Flask doit être répercutée dans `adapter.py`.

Ne jamais modifier `app.py` sans vérifier `adapter.py`.

---

# Tâche 1 – sécuriser le chargement des configurations

## Statut
- réalisée

## Objectif

Sécuriser le chargement de :

- `config.json`
- `paths.json`

## Fichiers concernés

- `flask_server/gpt4all_flask.py`

## Contraintes

- ne pas modifier les scripts batch ;
- conserver la compatibilité Windows.

## Critères de validation

- message d’erreur clair si fichier absent ;
- serveur ne plante pas brutalement.

---

# Tâche 2 – uniformiser les erreurs JSON

## Statut
- réalisée

## Objectif

Uniformiser les réponses d’erreur des routes Flask.

## Format recommandé



## Fichiers concernés

* routes dans `flask_server`

---

# Tâche 3 – documenter les routes principales

## Statut

* réalisée

## Objectif

Ajouter des docstrings aux routes Flask principales.

## Routes prioritaires

* `/chat_llm`
* `/annoter`
* `/annoter_rag`
* `/annoter_web`

---

# Tâche 4 – réduire les chemins codés en dur

## Statut

* partiellement réalisée (fallbacks locaux sécurisés)

## Objectif

Identifier et réduire les chemins absolus présents dans le code.

## Actions

* utiliser les helpers existants ;
* privilégier les chemins configurables.

---

# Tâche 5 – fiabiliser le chargement des configurations Flask

## Statut

* réalisée

## Objectif

Améliorer la robustesse du chargement des paramètres serveur.

## Critères

* message d’erreur explicite ;
* logs clairs.

---

# Tâche 6 – moderniser le README

## Statut

* réalisée

## Objectif

Mettre à jour `README.md` afin qu'il reflète l’architecture actuelle.

## Actions attendues

* décrire le rôle du serveur ;
* documenter l'emplacement des modèles ;
* expliquer le lancement du serveur ;
* expliquer l'utilisation des vector stores.

## Contraintes

* ne pas inventer de fonctionnalités ;
* se baser uniquement sur le code présent ;
* rester synthétique.

---

# Tâche 7 – ajouter des tests légers sur les routes critiques

## Statut

* réalisée

## Objectif

Ajouter quelques tests simples pour vérifier que les routes principales répondent avec un format cohérent dans les cas de base ou d’erreur simple.

## Routes prioritaires

* `/annoter`
* `/annoter_rag`
* `/annoter_web`
* `/ocr_grid`
* `/prompts_structures`

## Contraintes

* ne pas refactoriser le serveur ;
* ne pas dépendre d’un environnement complet ;
* privilégier des tests ciblés, robustes et simples.

## Critères de validation

* tests exécutables ;
* périmètre limité ;
* aucune modification du comportement métier.

---

# Tâche 8 – aligner `/annoter_rag_vecteur` côté client

## Statut

* réalisée

## Objectif

Aligner les noms de champs entre `app.py`, `adapter.py` et Flask pour `/annoter_rag_vecteur`.

---

# Tâche 9 – corriger l’exploitation du retour `/upload_file` dans `app.py`

## Statut

* réalisée

## Objectif

Faire consommer par le client les champs réellement renvoyés par Flask.

---

# Tâche 10 – corriger `/annoter_rag` sur les paramètres de génération

## Statut

* réalisée

## Objectif

Faire en sorte que `/annoter_rag` applique réellement les paramètres de génération envoyés lorsqu’ils sont présents.

---

# Tâche 11 – harmoniser les erreurs JSON sur les routes consommées par `app.py`

## Statut

* réalisée

## Objectif

Harmoniser de façon ciblée les réponses d’erreur sur les routes réellement utilisées par `app.py`.

---

# Tâche 12 – mettre à jour `docs/API_MAP.md`

## Statut

* réalisée

## Objectif

Documenter le contrat réellement supporté pour les routes utilisées par `app.py`.

---

# Bloc — Pipeline affaire et traçabilité documentaire (`doc_uid`)

---

# Tâche 13 – audit de la persistance projet

## Statut

* réalisée

## Objectif

Établir un état des lieux précis de la persistance des données par affaire, sans modifier le code.

## Périmètre d’analyse

* `flask_server/gpt4all_flask.py`
* `flask_server/helper_paths.py`
* `flask_server/rag_vector_utils.py`
* `docs/app_reference/app.py`
* `docs/app_reference/adapter.py`
* structure des dossiers projet (`_AI`, `_DB`, `_CSV_RAG`, etc.)

## Travail attendu

Identifier de manière factuelle :

* les fichiers réellement écrits par affaire ;
* l’usage de `_DB/project.sqlite` ;
* les outputs OCR / ASR / RAG ;
* les CSV générés ;
* les manifests éventuels ;
* les identifiants existants (noms, chemins, JSON) ;
* les mécanismes implicites de traçabilité.

## Contraintes

* ne modifier aucun code ;
* ne proposer aucune implémentation ;
* rester descriptif.

## Livrable attendu

* existant ;
* manques ;
* incohérences ;
* points de greffe possibles.

---

# Tâche 14 – schéma SQLite minimal

## Statut

* réalisée

## Objectif

Définir un noyau de base projet minimal compatible avec l’existant.

## Contraintes

* pas d’implémentation ;
* rester minimal ;
* compatibilité CSV / RAG / dossiers.

## Livrable attendu

* description des tables ;
* rôle ;
* index utiles ;
* justification.

---

# Tâche 15 – point d’injection de `doc_uid`

## Statut

* réalisée

## Objectif

Identifier le moment optimal de création de `doc_uid`.

## Points à analyser

* `/upload_file`
* `/api/split_pdf`
* `/convert_to_csv_batch`
* `/index_chroma_from_csv`

## Travail attendu

Pour chaque point :

* avantages ;
* inconvénients ;
* impacts ;
* risques.

## Attendu final

* point recommandé ;
* justification ;
* impacts minimaux.

## Contraintes

* aucune implémentation ;
* analyse concise.

---

# Tâche 16 – implémentation progressive de `doc_uid`

## Statut

* en cours (découpage progressif)

## Objectif

Introduire `doc_uid` sans casser les flux existants.

## Étapes prévues

1. génération ;
2. SQLite ;
3. propagation ;
4. RAG ;
5. exposition API facultative.

## Critères de réussite

* aucun flux cassé ;
* `doc_uid` présent dans une entrée, dans SQLite et dans au moins un output ;
* traçabilité minimale fonctionnelle.

## Contraintes

* pas de refonte ;
* incrémental ;
* réversible.

---
Oui. Le retour T13 à T16 est cohérent et suffisamment mûr pour passer à une suite de tâches Codex.

À mon avis, il ne faut pas lancer tout de suite la T17 au sens large. Il vaut mieux **découper très finement** la mise en œuvre pour éviter de casser `app.py`, `adapter.py` ou les flux serveur existants.

Je vous proposerais l’ordre suivant.

## Bloc immédiat à confier à Codex

### T16A — socle SQLite minimal pour `doc_uid`

C’est la prochaine tâche logique et la plus sûre.

**Objet**

* créer le helper de résolution de `project.sqlite` côté serveur ;
* initialiser paresseusement le schéma minimal ;
* ne modifier aucun contrat client.

## Statut

* réalisée

**Périmètre**

* `flask_server/gpt4all_flask.py`
* éventuellement un helper local très léger si strictement nécessaire

**À exiger**

* réutiliser la résolution existante de `project_id` ;
* respecter `paths["sqlite"]` si disponible ;
* créer uniquement les tables `documents` et `artifacts` + index ;
* ne rien changer aux réponses JSON existantes ;
* compatibilité Windows stricte ;
* aucune dépendance lourde.

**Critère de réussite**

* pour une affaire configurée, le serveur sait localiser ou créer `project.sqlite` ;
* la base est initialisée sans effet visible côté client ;
* aucun flux existant n’est cassé.

---

### T16B — injection minimale de `doc_uid` dans `/upload_file`

Une fois le socle SQLite en place, c’est le premier vrai usage métier.

**Objet**

* créer un `doc_uid` canonique au moment de l’upload ;
* insérer la source dans `documents` ;
* rattacher l’artefact fichier dans `artifacts`.

## Statut

* réalisée

**Contraintes**

* ne pas modifier `app.py` ;
* ne pas modifier `adapter.py` ;
* conserver le JSON de retour actuel ;
* tolérer l’absence de SQLite sans crash brutal ;
* comportement idempotent autant que possible.

**À préciser à Codex**

* hash SHA-256 du fichier ;
* `doc_uid` stable ou au minimum déterministe ;
* pas d’obligation d’exposer `doc_uid` à l’API à ce stade ;
* journalisation discrète, pas bavarde.

**Critère de réussite**

* un upload crée une trace exploitable dans SQLite ;
* aucun changement visible côté UI ;
* pas de régression sur `/upload_file`.

---

### T16C — tests légers ciblés sur le socle `doc_uid`

Il faut sécuriser tout de suite.

**Objet**

* ajouter quelques tests minimaux sur :

  * résolution `project.sqlite`
  * création paresseuse du schéma
  * insertion lors de `/upload_file`

## Statut

* réalisée

**Contraintes**

* tests simples ;
* pas d’environnement complet requis ;
* pas de refactor global ;
* mocks/fichiers temporaires autorisés.

**Critère**

* vérifier qu’aucune régression évidente n’est introduite ;
* vérifier la présence des enregistrements SQLite.

---

## Bloc suivant, une fois T16A–T16C validées

### T16D — extension à `/api/split_pdf`

C’est l’étape logique suivante.

**Objet**

* créer des `doc_uid` enfants pour les pièces découpées ;
* renseigner `parent_doc_uid` ;
* enrichir le manifest JSON sans casser son format actuel.

## Statut

* réalisée

**Important**

* ajout incrémental uniquement ;
* ne pas imposer `doc_uid` comme champ obligatoire pour les anciens manifests.

---

### T16E — lecture de `doc_uid` dans `rag_vector_utils.py`

À faire après stabilisation upload + split.

**Objet**

* lire `doc_uid` depuis le CSV si présent ;
* sinon tenter une résolution via SQLite à partir de `source_path` / `parent_doc_path` ;
* conserver `source_id` pour compatibilité.

**Pourquoi après**

* sinon on complique trop tôt la couche vectorielle.

---

## Ce que je ne lancerais pas encore

### Pas encore T17 en bloc complet

T17 est trop large pour être sûre en une seule fois.

### Pas encore Paperless

Le retour Codex est correct : sans base factuelle suffisante, il ne faut pas inventer l’intégration.

### Pas encore exposition API de `doc_uid`

Je repousserais cela après stabilisation serveur interne.


---

T17A — Centralisation de `projets_index.json`

Objectif :
Permettre au serveur Flask et aux scripts d’utiliser un chemin cohérent et configurable.

Travail attendu :

1. Introduire une fonction helper unique (ex: `resolve_projets_index_path()`):
   - priorité 1 : variable d’environnement `PROJETS_INDEX_PATH`
   - priorité 2 : fichier dans `APP_CONFIG_DIR`
   - priorité 3 : fallback existant (ne pas casser)

2. Journaliser clairement le chemin utilisé (info log).

3. Ne pas casser :
   - `load_projets_index()`
   - les usages existants côté app.py

Contraintes :
- aucune dépendance externe
- compatibilité Windows stricte

---

T17B — Fiabilisation de `create_affaire.py`

Objectif :
Faire de ce script le point d’entrée unique de création d’affaire.

Travail attendu :

1. Charger `projets_index.json` via le helper centralisé.

2. Vérifier si `project_id` existe déjà :
   - si oui → retourner proprement (idempotence, pas d’erreur)

3. Si absent :
   - ajouter une entrée dans `projets_index.json` avec :
     - id
     - nom (si fourni)
     - chemin_config
     - date_creation (ISO)
   - écrire le fichier de façon atomique (éviter corruption)

4. Créer l’arborescence minimale :
   - `C:\Affaires\<project_id>\`
   - `_Config\project_config.json`
   - `_DB\project.sqlite` (placeholder vide si non existant)

5. Générer un `project_config.json` minimal cohérent avec :
   - roots (laptop, pcfixe, nas si possible)
   - paths (sqlite, manifests, csv_rag, etc.)

6. Ne pas écraser :
   - un project_config existant
   - un sqlite existant

7. Journaliser toutes les actions (création vs déjà existant)

Contraintes :
- aucune suppression de fichiers existants
- pas de logique NAS complexe
- pas de dépendance à Syncthing

---

T17C — Robustesse lecture côté serveur

Objectif :
Éviter les erreurs silencieuses si le registre est absent ou incohérent.

Travail attendu dans Flask :

1. Si `projets_index.json` introuvable :
   - log warning explicite
   - fallback sur comportement existant

2. Si `project_id` inconnu :
   - ne pas planter brutalement
   - log clair : "projet non trouvé dans index"

3. Ne pas modifier les routes existantes (pas de changement de contrat JSON)

---



# Tâche 18 – socle SQLite minimal pour `doc_uid`

## Statut

* à faire

## Objectif

Mettre en place le socle SQLite minimal par affaire, sans encore injecter `doc_uid` dans les routes métier.

## Périmètre

* `flask_server/gpt4all_flask.py`
* éventuellement un helper local si strictement nécessaire dans le même fichier

## Exclusions

* ne pas modifier `app.py`
* ne pas modifier `adapter.py`
* ne pas modifier `rag_vector_utils.py`

## Travail attendu

1. ajouter un helper de résolution de `project.sqlite` à partir de `project_id`, en réutilisant la logique existante de résolution projet :

   * `load_project_config(...)`
   * `load_remote_map(...)`
   * `paths["sqlite"]` si disponible

2. initialiser paresseusement un schéma SQLite minimal au premier accès, avec uniquement :

   * table `documents`
   * table `artifacts`

3. garantir que l’initialisation :

   * ne casse pas si la base existe déjà ;
   * ne modifie aucun flux client existant ;
   * reste compatible Windows.

## Schéma minimal attendu

### Table `documents`

* `doc_uid TEXT PRIMARY KEY`
* `project_id TEXT NOT NULL`
* `parent_doc_uid TEXT NULL`
* `source_kind TEXT NULL`
* `source_path TEXT NULL`
* `source_name TEXT NULL`
* `source_sha256 TEXT NULL`
* `source_id_legacy TEXT NULL`
* `piece_ref TEXT NULL`
* `doc_type TEXT NULL`
* `version_label TEXT NULL`
* `status TEXT NOT NULL`
* `created_at TEXT NOT NULL`
* `updated_at TEXT NOT NULL`

### Table `artifacts`

* `artifact_uid TEXT PRIMARY KEY`
* `doc_uid TEXT NOT NULL`
* `artifact_type TEXT NOT NULL`
* `path TEXT NULL`
* `sha256 TEXT NULL`
* `external_ref TEXT NULL`
* `meta_json TEXT NULL`
* `created_at TEXT NOT NULL`

## Index attendus

* `idx_documents_project_id`
* `idx_documents_project_source_path`
* `idx_documents_project_source_sha256`
* `idx_documents_project_source_legacy`
* `idx_artifacts_doc_uid`
* `idx_artifacts_type`
* `idx_artifacts_path`

## Contraintes

* ne pas injecter encore `doc_uid` dans `/upload_file` ;
* ne pas modifier les réponses JSON existantes ;
* ne pas refactoriser globalement ;
* modifications minimales, locales et réversibles.

## Critères de réussite

* résolution fiable de `project.sqlite` pour une affaire configurée ;
* schéma SQLite créé automatiquement si absent ;
* aucune régression au démarrage serveur ;
* aucun changement visible côté client.

---

# Tâche 19 – exploitation de `doc_uid`

## Statut

* à faire

## Objectif

Rendre `doc_uid` utile pour la traçabilité documentaire.

## Travail attendu

* lecture de `doc_uid` dans JSON / CSV / RAG / SQLite ;
* lookup minimal ;
* exposition API lorsque pertinent ;
* traçabilité RAG ;
* validation sur une affaire test.

## Critères de réussite

* traçabilité opérationnelle ;
* aucune régression ;
* compatibilité maintenue.

## Contraintes

* pas de refonte globale ;
* UI inchangée ou minimale ;
* approche incrémentale.

---

# Règle générale

Aucune implémentation globale de `doc_uid` ne doit être réalisée avant validation des Tâches 13 à 15.

Les Tâches 16 et 18 doivent rester progressives, testables et réversibles.

---

# Bloc — Exploitation métier et intégration GED (`doc_uid`)

---

# Tâche 20 – exploitation métier de `doc_uid` pour l’expertise

## Statut

* à faire

## Objectif

Utiliser `doc_uid` comme support de traçabilité documentaire dans le cadre d’une expertise judiciaire.

## Livrable attendu

Note structurée :

* liaison pièce ;
* chronologie ;
* typologie ;
* transformations ;
* usages.

## Critère de réussite

Pouvoir expliquer clairement l’utilité de `doc_uid` dans une expertise.

## Contraintes

* pas d’implémentation ;
* rester pragmatique et analytique.

---

# Tâche 21 – articulation `doc_uid` / Paperless / n8n

## Statut

* à faire

## Objectif

Organiser la circulation de `doc_uid` entre :

* affaire (source canonique) ;
* Paperless (GED) ;
* n8n (orchestration).

## Livrable attendu

Note précisant :

* rôles systèmes ;
* mapping ;
* circulation ;
* règles.

## Critère de réussite

Pouvoir décrire clairement comment un document circule entre affaire, Paperless et n8n via `doc_uid`.

## Contraintes

* strictement analytique ;
* aucune implémentation à ce stade.

---

# Tâche 22 – première exploitation opérationnelle dans une affaire réelle

## Statut

* à faire

## Objectif

Valider concrètement l’apport de `doc_uid` sur une affaire avec un cas d’usage simple et utile.

## Cas d’usage retenu

Retrouver une source documentaire depuis un contenu RAG ou OCR.

## Livrable attendu

Note courte :

* cas testé ;
* résultats ;
* limites ;
* améliorations nécessaires.

## Critère de réussite

Pouvoir affirmer que `doc_uid` améliore réellement la traçabilité et la justification documentaire dans une affaire.

## Contraintes

* ne pas généraliser ;
* ne pas refactorer ;
* rester sur un test localisé.

---

# Tâche 23 – généralisation contrôlée de `doc_uid` à une affaire

## Statut

* à faire

## Objectif

Étendre l’usage de `doc_uid` à une affaire complète, sans dégrader les flux existants.

## Travail attendu

* définir le périmètre couvert ;
* vérifier la couverture ;
* tester la robustesse des flux ;
* traiter les cas limites ;
* formaliser des règles simples.

## Livrable attendu

Note synthétique :

* périmètre testé ;
* couverture réelle ;
* incidents rencontrés ;
* décisions prises ;
* points à améliorer.

---

# Tâche 24 – exploitation opérationnelle de `doc_uid` pour la rédaction d’expertise

## Statut

* à faire

## Objectif

Utiliser `doc_uid` pour sécuriser, accélérer et fiabiliser la rédaction des notes et rapports.

## Travail attendu

* définir un format de citation interne ;
* retrouver la source depuis un extrait ;
* assister la génération de notes ;
* vérifier la cohérence documentaire ;
* tester sur une note réelle.

## Livrable attendu

Note courte :

* exemple concret avant / après ;
* bénéfices observés ;
* limites ;
* améliorations possibles.

---

# Tâche 25 – génération de synthèses juridiques sourcées

## Statut

* à faire

## Objectif

Produire des synthèses exploitables dans un rapport, avec références documentaires traçables via `doc_uid`.

## Travail attendu

* définir un format de synthèse standard ;
* extraire les sources utiles ;
* injecter les références ;
* distinguer les niveaux de preuve ;
* tester sur un cas réel.

## Livrable attendu

* 1 ou 2 synthèses rédigées ;
* avec références `doc_uid` ;
* courte analyse critique.

---

# Tâche 26 – structuration assistée d’un rapport judiciaire avec sources

## Statut

* à faire

## Objectif

Permettre la production d’un rapport structuré intégrant des synthèses sourcées et une traçabilité vérifiable.

## Travail attendu

* définir un format standard de sections ;
* structurer la section “Pièces analysées” ;
* intégrer les sources dans les sections ;
* vérifier la cohérence des références ;
* produire un extrait de rapport.

## Livrable attendu

* un extrait structuré de rapport ;
* avec références `doc_uid` ;
* analyse critique.

---

# Tâche 27 – contrôle de cohérence documentaire automatique (`doc_uid`)

## Statut

* à faire

## Objectif

Vérifier qu’un projet de note ou de rapport repose sur des sources documentaires traçables et cohérentes.

## Travail attendu

* définir les contrôles minimaux ;
* relire automatiquement un texte ;
* croiser avec la persistance projet ;
* classer les anomalies ;
* définir la sortie ;
* tester sur un texte réel.

## Livrable attendu

Note courte précisant :

* les contrôles retenus ;
* leur priorité ;
* le format de sortie ;
* les difficultés constatées ;
* la valeur pratique.

---

# Tâche 28 – implémentation d’un contrôle documentaire minimal (`doc_uid`)

## Statut

* à faire

## Objectif

Mettre en place un premier outil opérationnel de contrôle des références `doc_uid`, utilisable avant remise d’une note ou d’un rapport.

## Périmètre

* une fonction Python ou module léger ;
* sans dépendance lourde ;
* utilisable en local (CLI ou appel interne).

## Travail attendu

1. extraire les `doc_uid` depuis un texte ;
2. vérifier SQLite ;
3. vérifier le fichier source ;
4. construire un rapport de contrôle ;
5. proposer une interface minimale ;
6. tester sur un cas réel.

## Livrable attendu

* code fonctionnel minimal ;
* exemple d’appel ;
* exemple de sortie ;
* retour d’expérience court.

## Critères de réussite

* détection fiable des `doc_uid` ;
* vérification effective des sources ;
* utilité immédiate avant remise.

## Contraintes

* pas de refactoring global ;
* pas de dépendances lourdes ;
* pas de complexité inutile ;
* rester robuste et lisible.

---

# Tâche 29 – suite du contrôle documentaire

## Statut

* à définir

## Options possibles

### Option A — intégration dans le workflow réel

* Streamlit ;
* API ;
* flux de génération de note ou synthèse.

### Option B — enrichissement du contrôle

* cohérence des citations ;
* typologie ;
* contrôles supplémentaires.

## Remarque

La Tâche 29 ne doit être engagée qu’après validation de la Tâche 27.

```

