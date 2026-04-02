
---

# 📄 Matrice des dépendances — fichiers / scripts / colonnes CSV

---

## 1. Principe

Chaque donnée du système est définie par :

```text
Fichier source → Script → Fichier cible → Colonnes impactées
```

---

## 2. Vue synthétique globale

```text id="8y6n4o"
photos.csv ───────────────┐
                          ├──→ photos_batch.csv ───→ résultats LLM/VLM
infos_projet.json ────────┘

JPG ─────────→ VLM ───────→ description_vlm_batch
Audio ───────→ ASR ───────→ transcription.csv
```

---

## 3. Matrice détaillée

## 3.1 Préparation (Laptop)

| Source             | Script                      | Cible              | Colonnes / effets                                                                  |
| ------------------ | --------------------------- | ------------------ | ---------------------------------------------------------------------------------- |
| JPG                | `gen_tout_depuis_jpg.py`    | `photos.csv`       | `nom_fichier_image`, `horodatage_photo`, etc.                                      |
| photos.csv         | `mk_photos_batch_min.py`    | photos_batch.csv   | `photo_rel_native`                                                                 |
| photos.csv         | `batch_photos_post_sync.py` | photos.csv         | `id_affaire`, `id_captation`, `photo_rel_*`, `*_pcfixe`, `photo_disponible_pcfixe` |
| structure dossiers | `run_all_from_JPG_v3.bat`   | arborescence cible | création dossiers                                                                  |

---

## 3.2 Fichier pivot : photos.csv

| Colonne                     | Origine  | Script                 | Utilisation         |
| --------------------------- | -------- | ---------------------- | ------------------- |
| nom_fichier_image           | JPG      | gen_tout_depuis_jpg    | base de nommage     |
| photo_rel_native            | calcul   | batch_photos_post_sync | clé de jointure     |
| photo_rel_reduite           | calcul   | batch_photos_post_sync | accès image réduite |
| id_affaire                  | argument | batch_photos_post_sync | cohérence projet    |
| id_captation                | dossier  | batch_photos_post_sync | structuration       |
| chemin_photo_native_pcfixe  | calcul   | batch_photos_post_sync | accès PC fixe       |
| chemin_photo_reduite_pcfixe | calcul   | batch_photos_post_sync | accès réduit        |
| photo_disponible_pcfixe     | FS       | batch_photos_post_sync | validation copie    |

---

## 3.3 Fichier pivot : photos_batch.csv

| Colonne                   | Origine    | Script                     | Rôle              |
| ------------------------- | ---------- | -------------------------- | ----------------- |
| photo_rel_native          | photos.csv | mk_photos_batch_min        | clé primaire      |
| description_vlm_batch     | VLM        | batch_all_photos_pcfixe.py | description image |
| libelle_propose_batch     | LLM        | batch_all_photos_pcfixe.py | libellé           |
| commentaire_propose_batch | LLM        | batch_all_photos_pcfixe.py | commentaire       |
| vlm_status                | VLM        | batch_all_photos_pcfixe.py | état              |
| vlm_err                   | VLM        | batch_all_photos_pcfixe.py | erreurs           |
| batch_status              | batch      | batch_all_photos_pcfixe.py | suivi global      |
| sujets_ids                | RAG        | rag_vector_utils.py        | indexation        |
| sujets_scores             | RAG        | rag_vector_utils.py        | pertinence        |

---

## 3.4 Fichier pivot : infos_projet.json

| Champ                    | Origine         | Script                | Utilisation      |
| ------------------------ | --------------- | --------------------- | ---------------- |
| fichier_photos           | pipeline laptop | write_infos_projet.py | entrée UI        |
| fichier_photos_batch     | pipeline laptop | write_infos_projet.py | entrée batch     |
| fichier_audio_source     | Audio           | write_infos_projet.py | ASR              |
| fichier_audio_compatible | conversion      | write_infos_projet.py | ASR              |
| fichier_transcription    | ASR             | write_infos_projet.py | LLM              |
| fichier_contexte_general | Audio           | write_infos_projet.py | contexte         |
| pcfixe.*                 | calcul          | write_infos_projet.py | chemins distants |

---

## 3.5 Flux VLM

| Entrée | Script                     | Sortie           | Colonnes              |
| ------ | -------------------------- | ---------------- | --------------------- |
| JPG    | batch_all_photos_pcfixe.py | photos_batch.csv | description_vlm_batch |
| JPG    | batch_all_photos_pcfixe.py | photos_batch.csv | vlm_status, vlm_err   |

---

## 3.6 Flux LLM

| Entrée                | Script                     | Sortie           | Colonnes                  |
| --------------------- | -------------------------- | ---------------- | ------------------------- |
| description_vlm_batch | batch_all_photos_pcfixe.py | photos_batch.csv | libelle_propose_batch     |
| transcription         | batch_all_photos_pcfixe.py | photos_batch.csv | commentaire_propose_batch |
| contexte              | batch_all_photos_pcfixe.py | photos_batch.csv | enrichissement            |

---

## 3.7 Flux ASR

| Entrée | Script              | Sortie        | Fichier                  |
| ------ | ------------------- | ------------- | ------------------------ |
| WAV    | traitement_audio.py | WAV mono16    | fichier_audio_compatible |
| WAV    | audio_server.py     | transcription | transcription.csv        |

---

## 4. Dépendances critiques

### 4.1 Clé unique

```text id="2x3m3k"
photo_rel_native
```

Dépendances :

* photos.csv
* photos_batch.csv
* batch_all_photos_pcfixe.py

---

### 4.2 Fichier central

```text id="x8j7qz"
infos_projet.json
```

Dépendances :

* tous les scripts batch
* chemins fichiers
* configuration LLM / ASR

---

## 5. Dépendances croisées (risques)

| Élément                      | Risque                |
| ---------------------------- | --------------------- |
| photo_rel_native modifié     | perte de jointure     |
| photos_batch.csv recréé      | perte historique      |
| infos_projet.json incohérent | pipeline inutilisable |
| chemins PC fixe faux         | batch inopérant       |

---

## 6. Règles pour Codex

### Interdictions

* ❌ modifier `photo_rel_native`
* ❌ changer structure CSV
* ❌ écrire dans photos.csv côté batch
* ❌ casser `infos_projet.json`

---

### Autorisations

* ✅ enrichir photos_batch.csv
* ✅ ajouter colonnes batch
* ✅ améliorer robustesse
* ✅ ajouter logs

---

## 7. Usage en debug

Cette matrice permet :

### 7.1 Identifier l’origine d’un bug

Exemple :

```text id="h0hl12"
description_vlm_batch vide
→ vérifier JPG
→ vérifier VLM
→ vérifier batch_all_photos_pcfixe.py
```

---

### 7.2 Vérifier une incohérence

```text id="pnrqcg"
photo absente PC fixe
→ vérifier photo_rel_native
→ vérifier batch_photos_post_sync.py
→ vérifier copie robocopy
```

---

### 7.3 Relancer partiellement

```text id="7sr09p"
vider colonnes LLM
→ relancer batch LLM uniquement
```

---

## 8. Synthèse

```text id="a3x8w4"
Données → CSV → Batch → Enrichissement → Résultats
```

---

## Verdict

👉 Cette matrice est :

* directement exploitable pour debug
* adaptée à Codex
* structurante pour les évolutions

---
