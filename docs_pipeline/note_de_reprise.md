# 📄 NOTE DE REPRISE — Projet GPT4All_Local / LLM_Assistant / AnnotationPhotoGPT

---

# 1. Objet

Cette note permet à un nouveau GPT de :

* reprendre efficacement le contexte du projet ;
* comprendre l’architecture globale ;
* identifier les enjeux techniques ;
* prendre en main Codex de manière sécurisée ;
* s’appuyer sur les fichiers `.md` fournis comme base de référence.

---

# 2. Nature du projet

Le projet est un **système distribué multi-machines** dédié à l’expertise judiciaire, comprenant :

* un **poste laptop (pilotage / UI / production)** ;
* un **NAS (stockage central et synchronisation)** ;
* un **PC fixe (traitement intensif + serveurs)**.

Il repose sur plusieurs pipelines spécialisés :

* AnnotationPhotoGPT (photos)
* Pipeline compte-rendu (ASR → JSON → DOCX)
* LLM_Assistant (pilotage global, RAG, OCR, ASR, etc.)

---

# 3. Architecture globale

## 3.1 Rôles des machines

### Laptop

* interface Streamlit (`app.py`)
* point d’entrée des données
* production expert
* client des services distants

### NAS

* stockage central
* pivot de synchronisation
* support des workflows (n8n à venir)

### PC fixe

* serveur Flask GPT4All_Local
* traitements lourds (LLM, VLM, ASR, batch)
* bases vectorielles

---

## 3.2 Pipelines principaux

### 1. AnnotationPhotoGPT

* pipeline photo (VLM + LLM)
* UI + batch
* CSV comme pivot

### 2. Pipeline compte-rendu

* ASR → segmentation → LLM (3 passes)
* production JSON structuré
* rendu via `cr-render` (DOCX)

### 3. LLM_Assistant

* client Streamlit central
* orchestration des appels serveur
* gestion des affaires
* RAG, OCR, ASR, PDF

---

# 4. Enjeu principal actuel

👉 **La maîtrise des flux documentaires inter-machines**

Le système comporte **5 flux distincts**, chacun avec :

* une logique propre
* des outils différents
* un état d’avancement différent

---

# 5. Les 5 flux documentaires

## Flux 1 — pièces des parties

* PDF déposés via app.py
* ingestion documentaire
* synchronisation à construire (Syncthing)

## Flux 2 — gros fichiers

* photos / audio
* robocopy (Laptop → NAS, unidirectionnel)
* puis rsync NAS ↔ PC fixe

## Flux 3 — pièces expert

* documents produits sur laptop
* synchronisation bidirectionnelle cible (Syncthing)

## Flux 4 — données projet (_DB, _Config, SQLite)

* flux bidirectionnel à construire
* très sensible (conflits)

## Flux 5 — données techniques (vector DB, index)

* NAS ↔ PC fixe uniquement
* pas de réplication laptop
* accès via lecture distante

---

# 6. Mécanismes techniques

## Actuels

* robocopy (Laptop → NAS)
* rsync (NAS ↔ PC fixe, script `sync_affaires.sh`)
* scripts Python / .bat / .sh
* containers Docker

## Cibles

* Syncthing (Laptop ↔ NAS)
* n8n (orchestration)
* révision rsync
* unification des flux

---

# 7. Problématique actuelle

Le système est :

* partiellement implémenté
* hétérogène
* non unifié

Les questions ouvertes sont :

* les flux sont-ils correctement couverts ?
* les périmètres rsync sont-ils corrects ?
* robocopy est-il suffisant ?
* comment intégrer Syncthing ?
* comment gérer `_DB` et `_Config` ?
* comment éviter les conflits ?

---

# 8. Rôle attendu de Codex

Codex ne doit pas :

* modifier aveuglément les scripts
* unifier artificiellement les flux
* casser les conventions existantes

Codex doit :

* comprendre l’architecture complète
* raisonner par type de flux
* respecter les contraintes métier
* proposer des évolutions ciblées
* préserver la rétrocompatibilité

---

# 9. Tâches prioritaires pour Codex

## P1 — Audit des flux

* cartographier les flux existants
* comparer avec le cahier des charges
* identifier les écarts

## P2 — Syncthing

* définir le périmètre laptop ↔ NAS
* intégrer flux 1, 3, 4

## P3 — rsync

* revoir filtres A/B
* intégrer nouveaux flux (_DB, vector)

## P4 — robocopy

* vérifier complétude
* améliorer robustesse

## P5 — gouvernance des données

* source de vérité
* stratégie de conflit
* journalisation

---

# 10. Principe directeur

→ tous les flux ne sont pas des synchronisations
→ certains sont unidirectionnels
→ le NAS est le pivot
→ le laptop est un client, pas un stockage global

---

# 11. Liste des fichiers `.md` à fournir au GPT

⚠️ IMPORTANT : renommer si nécessaire pour éviter collisions (README, etc.)

## 11.1 Architecture globale

* `architecture_flux_documentaires.md`
* `synchronisation_affaires_NAS_pcfixe.md`

## 11.2 LLM_Assistant

* `README_app.md`
* `cahier_charges_app.md`
* `plan_execution_codex_app.md`

## 11.3 AnnotationPhotoGPT

* `annotationphotogpt_readme.md`
* `annotationphotogpt_pipeline.md`
* `batch_usage.md`
* `batch_reset_strategies.md`
* `liste_taches_annotationphotogpt.md`
* `tache_codex_annotation_photo.md`

## 11.4 Pipeline compte-rendu

* `pipeline_compte_rendu.md`
* `cr_render_readme.md`

## 11.5 Synchronisation et fichiers lourds

* `pipeline_copie_gros_fichiers.md`

## 11.6 (optionnel mais recommandé)

* `taches_codex_global.md`
* `system_overview.md` (si créé)

---

# 12. Consigne au nouveau GPT

Avant toute action :

1. lire les `.md`
2. identifier les flux concernés
3. vérifier le périmètre (machine / dossier / outil)
4. vérifier l’impact sur :

   * pipelines
   * synchronisation
   * données métier

Ne jamais :

* simplifier l’architecture
* fusionner des flux différents
* modifier un mécanisme sans vérifier les autres

---

# 13. Conclusion

Le projet est déjà structuré mais :

* la synchronisation est incomplète
* les flux ne sont pas encore unifiés
* l’architecture cible est définie mais non finalisée

Le rôle de Codex est d’aider à :

→ **passer d’un système fonctionnel partiel à une architecture cohérente, robuste et maîtrisée**

---
