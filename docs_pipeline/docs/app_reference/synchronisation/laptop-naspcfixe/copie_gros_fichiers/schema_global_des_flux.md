Voici un **schéma global des flux**, rédigé pour être exploitable par Codex et cohérent avec vos deux pipelines.

---

# 📄 Schéma global des flux — Architecture AnnotationPhotosGPT

---

## 1. Vue d’ensemble

```text
[Laptop]
  ↓ (préparation + copie)
[NAS]
  ↓ (synchronisation)
[PC fixe]
  ↓ (traitements batch)
[Résultats]
```

---

## 2. Typologie des flux

Trois types de flux coexistent :

```text
1. Fichiers physiques   → JPG / WAV
2. Métadonnées CSV      → photos.csv / photos_batch.csv
3. Configuration JSON   → infos_projet.json
```

---

## 3. Flux détaillés

## 3.1 Laptop → NAS (pipeline copie)

### Entrées

```text
Photos/JPG/*.jpg
Audio/*.wav
Photos/*.csv (UI)
```

### Transformations

* génération `photos_batch.csv`
* enrichissement `photos.csv`
* génération `infos_projet.json`

### Sorties (copiées vers NAS)

```text
AE_Expert_captations/<id_captation>/
  ├── photos/
  │   ├── JPG/
  │   ├── JPG reduit/
  │   ├── photos.csv
  │   └── photos_batch.csv
  └── audio/

AF_Expert_ASR/transcriptions/<id_captation>/
  ├── contexte_general.json
  ├── transcription.csv (si existe)
  └── infos_projet.json
```

---

## 3.2 NAS → PC fixe (synchronisation)

### Nature

* synchronisation technique (rsync / robocopy / autre)
* aucune transformation métier

### Règle

```text
Le NAS est la source de vérité
```

---

## 3.3 PC fixe → traitements batch

### Entrées

```text
infos_projet.json
photos.csv
photos_batch.csv
JPG
WAV
```

### Flux logique

```text
photos.csv
     ↓
photos_batch.csv  ← enrichissement progressif
     ↓
résultats
```

---

## 4. Cycle de vie des données

```text
1. Création (Laptop)
2. Copie initiale (NAS)
3. Synchronisation (PC fixe)
4. Traitement batch
5. Enrichissement CSV
6. Production résultats
```

---

## 5. Rôle des fichiers clés

## 5.1 photos.csv (UI)

```text
Source utilisateur
→ jamais modifié par le batch
```

Contient :

* index des photos
* métadonnées initiales
* base de référence

---

## 5.2 photos_batch.csv

```text
Support des traitements
→ modifié uniquement par le batch
```

Contient :

* résultats VLM
* résultats LLM
* statuts
* erreurs

---

## 5.3 infos_projet.json

```text
Chef d’orchestre
```

Contient :

* tous les chemins
* configuration
* liens entre fichiers

⚠️ dépendance critique

---

## 6. Clé de jointure fondamentale

```text
photo_rel_native
```

Rôle :

```text
photos.csv  ←→ photos_batch.csv
```

⚠️ Ne jamais modifier sans audit global

---

## 7. Flux des traitements IA

```text
JPG
 ↓
VLM
 ↓
description_vlm_batch
 ↓
LLM
 ↓
libelle_propose_batch
commentaire_propose_batch
```

---

## 8. Gestion des états

Dans `photos_batch.csv` :

* `vlm_status`
* `batch_status`
* `vlm_err`
* `llm_err_*`

Permet :

* reprise partielle
* traçabilité
* debug

---

## 9. Flux des fichiers audio

```text
Audio source (WAV)
      ↓
audio mono16 (optionnel)
      ↓
ASR
      ↓
transcription.csv
      ↓
LLM (compte-rendu)
```

---

## 10. Points critiques du système

* cohérence des chemins
* validité de `infos_projet.json`
* présence réelle des fichiers
* synchronisation NAS → PC fixe
* unicité de `photo_rel_native`

---

## 11. Règles structurelles

### Séparation stricte

```text
Laptop  : préparation
NAS     : stockage
PC fixe : traitement
```

---

### Interdictions

* ❌ traitement sur le laptop
* ❌ modification des chemins côté PC fixe
* ❌ écriture batch dans photos.csv
* ❌ contournement de infos_projet.json

---

### Autorisations

* ✅ enrichissement photos_batch.csv
* ✅ relance partielle
* ✅ amélioration des logs
* ✅ optimisation des flux

---

## 12. Schéma synthétique final

```text
                +------------------+
                |     Laptop       |
                |------------------|
                | JPG / WAV        |
                | photos.csv       |
                +--------+---------+
                         |
                         | copie initiale
                         ↓
                +------------------+
                |       NAS        |
                |------------------|
                | Source centrale  |
                +--------+---------+
                         |
                         | sync
                         ↓
                +------------------+
                |     PC fixe      |
                |------------------|
                | batch VLM / LLM  |
                | photos_batch.csv |
                +--------+---------+
                         |
                         ↓
                +------------------+
                |    Résultats     |
                |------------------|
                | CSV enrichi      |
                | DOCX / exports   |
                +------------------+
```

---

## 13. Usage pour Codex

Ce document sert à :

* comprendre les flux réels
* éviter les modifications dangereuses
* garantir la cohérence globale
* guider les évolutions

---


