# pipeline_affaires_codex.md

## Objet

Ce document définit le cadre opératoire du **pipeline affaires** et les
actions à confier à Codex.

Il constitue la **référence unique** pour :

-   l'audit du contrat `app.py` ↔ `gpt4all_flask.py` ;
-   la normalisation des données documentaires ;
-   l'intégration du RAG vectoriel par affaire ;
-   l'articulation avec Paperless ;
-   la priorisation des travaux serveur et n8n.

------------------------------------------------------------------------

## 1. Architecture cible

Trois environnements :

-   **Laptop** : saisie et orchestration via `app.py`
-   **NAS** : stockage canonique des affaires
-   **PC fixe** : serveur Flask (`gpt4all_flask.py`) et traitements

Principe :

1.  création sur laptop\
2.  synchronisation NAS\
3.  traitement PC fixe\
4.  réintégration dans l'affaire

👉 Le NAS est la **source canonique métier**.

------------------------------------------------------------------------

## 2. Sources de vérité

Codex doit travailler à partir de :

-   `app.py`
-   `flask_server/gpt4all_flask.py`
-   `flask_server/helper_paths.py`
-   `flask_server/rag_vector_utils.py`
-   `docs/architecture.md`
-   `docs/SYSTEM_MAP.md`
-   `docs/PIPELINE_MAP.md`
-   `docs/API_MAP.md`
-   `README.md`
-   `arborescence_version 4.txt`
-   ce document

### Règles impératives

-   ne pas casser `app.py`
-   ne pas refactoriser globalement
-   rester compatible Windows + UNC
-   compléter l'existant

------------------------------------------------------------------------

## 3. Constat principal

Le serveur dispose déjà des routes nécessaires.

👉 Le problème n'est plus l'API mais :

1.  incohérence des payloads
2.  hétérogénéité des réponses JSON
3.  absence de modèle documentaire canonique
4.  absence de clé pivot stable
5.  faible intégration RAG affaire

------------------------------------------------------------------------

## 4. Décisions structurantes

### 4.1 Clé pivot

👉 **`doc_uid` est la clé centrale du pipeline**

Elle doit être présente partout :

-   SQLite
-   CSV RAG
-   embeddings
-   OCR / ASR
-   Paperless

------------------------------------------------------------------------

## 12. Instruction initiale à Codex

> Ne rien modifier. Produire uniquement un audit complet du contrat
> app.py ↔ serveur.
