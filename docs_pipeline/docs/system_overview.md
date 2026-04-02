# 📄 system_overview.md

---

# 1. Objet

Ce document fournit une **vue d’ensemble du système GPT4All_Local étendu**, incluant :

* les machines impliquées ;
* les applications principales ;
* les pipelines métier ;
* les flux documentaires ;
* les dépendances critiques.

Il constitue un point d’entrée rapide pour comprendre le système sans entrer immédiatement dans le détail des implémentations.

---

# 2. Vue globale

Le système est une architecture **distribuée multi-machines** organisée autour de trois pôles :

* **Laptop (client expert)**
* **NAS (stockage central + orchestration future)**
* **PC fixe (serveur + calcul)**

Ces éléments coopèrent via :

* API HTTP (Flask)
* synchronisation de fichiers
* pipelines batch
* scripts automatisés

---

# 3. Rôle des machines

## 3.1 Laptop

Fonctions principales :

* interface utilisateur (`Streamlit`)
* pilotage des traitements
* saisie et validation expert
* production documentaire

Applications clés :

* `LLM_Assistant (app.py)`
* `AnnotationPhotoGPT (main.py)`

Contraintes :

* ne stocke pas durablement les fichiers volumineux
* agit comme client du PC fixe
* dépend du NAS pour la persistance

---

## 3.2 NAS

Fonctions principales :

* stockage central des affaires (`/volume1/Affaires`)
* point pivot des synchronisations
* exécution de scripts planifiés (`cron`)
* hébergement futur des workflows (`n8n`)

Particularités :

* pilotage actuel de `rsync`
* centralisation des logs
* conservation long terme

---

## 3.3 PC fixe

Fonctions principales :

* serveur Flask `GPT4All_Local`
* exécution des modèles IA (LLM, VLM, ASR)
* traitements batch intensifs
* hébergement des bases vectorielles

Entrée principale :

* `flask_server/gpt4all_flask.py`

Rôle critique :

* cœur de calcul du système

---

# 4. Applications principales

## 4.1 LLM_Assistant

* client Streamlit sur laptop
* orchestration des appels API
* gestion des affaires
* RAG, OCR, ASR, PDF

⚠️ dépend fortement des routes Flask

---

## 4.2 AnnotationPhotoGPT

Pipeline :

* photos → VLM → LLM → CSV → validation → Word

Composants :

* UI (laptop)
* batch (PC fixe)
* synchronisation audio/photo

---

## 4.3 Pipeline compte-rendu

Pipeline :

* ASR → segmentation → LLM (3 passes) → JSON → rendu DOCX

Composants :

* script PowerShell
* adapter LLM
* renderer Docker (`cr-render`)

---

## 4.4 Serveur GPT4All_Local

Rôle :

* hub central IA

Fonctions :

* LLM
* RAG
* OCR
* ASR
* VLM
* web scraping

Routes critiques :

* `/annoter`
* `/annoter_rag`
* `/asr_voxtral`
* `/ocr`
* `/upload_file`

---

# 5. Pipelines métier

## 5.1 Pipeline photo

1. sélection photos (UI)
2. génération CSV
3. batch VLM (description)
4. batch LLM (annotation)
5. validation expert
6. export Word

---

## 5.2 Pipeline compte-rendu

1. transcription ASR
2. segmentation
3. passe 1 (segments)
4. passe 2 (global)
5. passe 3 (final)
6. rendu DOCX

---

## 5.3 Pipeline documentaire (RAG)

1. ingestion documents (PDF)
2. OCR / parsing
3. indexation vectorielle
4. interrogation via LLM

---

# 6. Flux documentaires

Le système repose sur **5 types de flux distincts** :

## Flux 1 — pièces des parties

* PDF déposés via app.py
* ingestion documentaire
* synchronisation à implémenter (Syncthing)

## Flux 2 — gros fichiers

* photos / audio
* robocopy (Laptop → NAS)
* puis rsync (NAS ↔ PC fixe)

## Flux 3 — production expert

* documents produits sur laptop
* synchronisation bidirectionnelle (Syncthing à venir)

## Flux 4 — données projet (_DB, _Config)

* données sensibles (SQLite, config)
* synchronisation bidirectionnelle à maîtriser

## Flux 5 — données techniques

* embeddings / vector DB
* NAS ↔ PC fixe uniquement
* accès lecture depuis laptop

---

# 7. Mécanismes de synchronisation

## Actuels

* robocopy (Laptop → NAS)
* rsync (NAS ↔ PC fixe)
* scripts `.bat`, `.ps1`, `.py`

## Cibles

* Syncthing (Laptop ↔ NAS)
* orchestration via n8n
* unification des flux

---

# 8. Dépendances critiques

## Techniques

* Flask server
* Chroma / Qdrant
* Tesseract
* Voxtral
* ComfyUI
* SearXNG

## Structurelles

* arborescence des affaires
* chemins multi-machines
* conventions CSV
* schémas JSON

---

# 9. Contraintes majeures

* stabilité des routes API
* compatibilité multi-clients
* gestion des chemins Windows / UNC
* non-régression des pipelines
* protection des données validées

---

# 10. Risques principaux

* désynchronisation des fichiers
* conflits multi-machines
* perte de données CSV / JSON
* incohérence des chemins
* erreurs silencieuses LLM/VLM

---

# 11. Orientation d’évolution

Objectifs :

* unifier la synchronisation
* fiabiliser les pipelines
* améliorer la traçabilité
* préparer intégration n8n
* renforcer robustesse

---

# 12. Principe directeur

Le système doit privilégier :

→ robustesse
→ traçabilité
→ compatibilité
→ évolutions locales

avant toute optimisation ou refonte.

---

# 13. Lecture recommandée

Pour approfondir :

* `architecture.md`
* `SYSTEM_MAP.md`
* `PIPELINE_MAP.md`
* `architecture_flux_documentaires.md`
* `README_app.md`
* `pipeline_compte_rendu.md`

---

# Conclusion

Le système constitue une **plateforme distribuée d’expertise augmentée par IA**, structurée autour :

* d’un client expert (laptop)
* d’un serveur de calcul (PC fixe)
* d’un stockage central (NAS)

et reposant sur des pipelines spécialisés et des flux documentaires différenciés.

---
