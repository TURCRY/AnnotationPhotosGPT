
---

# 📄 README_data.md — Organisation et structures des données

## 1. Objet

Ce document décrit :

* l’organisation des répertoires de données,
* la structure des fichiers utilisés dans le pipeline **AnnotationPhotoGPT**,
* les قواعد de cohérence, de traçabilité et de validation.

Il constitue une référence pour :

* la manipulation des données en entrée,
* les traitements intermédiaires,
* la production des livrables métier,
* l’automatisation (Codex / batch).

---

## 2. Répertoires

### 2.1 `uploads/`

**Rôle : zone d’entrée utilisateur**

Contient les fichiers importés depuis l’interface :

* audio source,
* CSV (photos, transcription),
* documents de contexte.

**Caractéristiques :**

* temporaire,
* non persisté,
* non exploitable directement en production (chemins filtrés).

**Usage :**

* point d’entrée des données,
* alimentation de `infos_projet.json`.

---

### 2.2 `temp/`

**Rôle : zone de travail intermédiaire**

Utilisé pour :

* audio converti (WAV),
* extraits audio,
* fichiers techniques intermédiaires.

**Caractéristiques :**

* volatile,
* purgé régulièrement,
* non référentiel.

**Usage :**

* traitement ASR,
* synchronisation audio/photo,
* prévisualisation UI.

---

## 3. Fichiers de données

---

## 3.1 `transcription.csv`

### Rôle

Source textuelle horodatée issue de l’ASR.

### Structure minimale

| Colonne     | Type        | Obligatoire | Description             |
| ----------- | ----------- | ----------- | ----------------------- |
| `temps`     | float / str | ✔           | Temps (sec ou HH:MM:SS) |
| `texte`     | string      | ✔           | Transcription           |
| `start_sec` | float       | optionnel   | Début segment           |
| `end_sec`   | float       | optionnel   | Fin segment             |

### Règles

* priorité :

  * (`start_sec`, `end_sec`) si présents
  * sinon `temps`
* encodage UTF-8 (fallback toléré)
* séparateur `;`
* texte nettoyé (pas d’hallucinations)

---

## 3.2 `photos.csv` (UI)

### Rôle

Fichier principal manipulé dans l’interface utilisateur.

### Structure minimale

| Colonne             | Type   | Obligatoire | Description           |
| ------------------- | ------ | ----------- | --------------------- |
| `nom_fichier_image` | string | ✔           | Nom image             |
| `horodatage`        | string | ✔           | `YYYY-MM-DD HH:MM:SS` |
| `photo_rel_native`  | string | ✔           | Chemin relatif (clé)  |
| `libelle`           | string | optionnel   | Saisie utilisateur    |
| `commentaire`       | string | optionnel   | Saisie utilisateur    |

### Règles

* `photo_rel_native` = clé de jointure
* cohérence temporelle avec `transcription.csv`
* EXIF utilisable pour génération initiale

---

## 3.3 `photos_batch.csv` (PC fixe)

### Rôle

Fichier de traitement batch (VLM + LLM).

### Structure principale

| Colonne                       | Description     |
| ----------------------------- | --------------- |
| `photo_rel_native`            | clé unique      |
| `chemin_photo_native_pcfixe`  | chemin absolu   |
| `chemin_photo_reduite_pcfixe` | image optimisée |
| `photo_disponible_pcfixe`     | bool            |
| `date_copie_pcfixe`           | traçabilité     |

### Sorties

| Colonne                     | Description       |
| --------------------------- | ----------------- |
| `description_vlm_batch`     | description image |
| `libelle_propose_batch`     | libellé           |
| `commentaire_propose_batch` | commentaire       |

### Traçabilité

| Colonne        | Description             |
| -------------- | ----------------------- |
| `batch_status` | OK / ERR / SKIP / EMPTY |
| `batch_ts`     | timestamp               |
| `batch_id`     | identifiant             |

### Diagnostics

Colonnes techniques :

* `vlm_*`
* `llm_*`

---

## 3.4 `annotations_GPT.csv / .xlsx`

### Rôle

Fichier final consolidé (référence métier).

### Structure minimale

| Colonne               | Type      | Description    |
| --------------------- | --------- | -------------- |
| `photo_rel_native`    | string    | clé principale |
| `nom_fichier_image`   | string    | informatif     |
| `libelle_propose`     | string    | libellé        |
| `commentaire_propose` | string    | commentaire    |
| `annotation_validee`  | int (0/1) | validation     |

### Règles métier

* `annotation_validee = 1` → verrouillage
* priorité des données :

  1. annotations validées
  2. UI
  3. batch le plus récent

---

## 4. Logique d’ensemble

```text
uploads/
    ↓
temp/
    ↓
transcription.csv
    ↓
photos.csv (UI)
    ↓
photos_batch.csv
    ↓
annotations_GPT.xlsx
    ↓
Modèle Word
```

---

## 5. Clé de jointure

```text
photo_rel_native
```

* clé unique globale
* utilisée dans tous les fichiers
* obligatoire

---

## 6. Principes structurants

### 6.1 Séparation des rôles

* UI : saisie humaine
* batch : génération automatique
* annotations : consolidation

---

### 6.2 Traçabilité

* timestamps (`*_ts`)
* statuts (`batch_status`)
* identifiants (`batch_id`)

---

### 6.3 Non-persistance des temporaires

* `temp/` ne doit jamais être utilisé comme source métier

---

### 6.4 Robustesse

* lecture multi-encodage
* validation préalable des colonnes
* tolérance aux formats temporels

---

### 6.5 Format CSV obligatoire

* séparateur : `;`
* encodage : UTF-8 avec BOM (`utf-8-sig`)
* noms de colonnes stricts
* aucune colonne implicite

---

### 6.6 Priorité des données

Ordre de résolution :

1. annotations validées
2. données UI
3. données batch

---

### 6.7 Version de schéma (recommandé)

Possibilité d’ajouter :

```text
schema_version
```

Exemple :

```text
1.0
```

---

## 7. Opinion (structuration)

Le modèle de données présente :

* une séparation claire des responsabilités,
* une clé de jointure unique cohérente,
* une traçabilité suffisante pour un usage judiciaire.

Sous réserve du respect strict des formats définis, il permet :

> une reproductibilité fiable des traitements et une sécurisation des flux entre les phases UI, batch et production du rapport.

---


