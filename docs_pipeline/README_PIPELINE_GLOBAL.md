Voici une note synthétique et exploitable pour figer l’architecture globale.

---

# 📄 README_pipeline_global.md — AnnotationPhotoGPT

## 1. Objet

Le présent document décrit le pipeline complet de traitement des captations :

* préparation des données (laptop) ;
* synchronisation des fichiers lourds (NAS) ;
* traitements batch (PC fixe) ;
* génération des livrables (rapport Word).

L’objectif est d’assurer :

* reproductibilité ;
* robustesse multi-machines ;
* séparation claire des responsabilités.

---

## 2. Architecture générale

```text
Laptop (UI / préparation)
    ↓
NAS (stockage central + n8n)
    ↓
PC fixe (batch / LLM / traitement)
    ↓
NAS (résultats)
    ↓
Laptop (contrôle / rapport)
```

---

## 3. Rôles des environnements

### 3.1 Laptop (Windows)

Rôle :

* création de l’affaire et de la captation ;
* import des photos ;
* génération initiale :

  * `photos.csv`
  * `photos_batch.csv` (structure)
* annotation UI (libellé / commentaire) ;
* génération du rapport Word.

Chemins typiques :

```text
C:\AnnotationPhotosGPT\
C:\Users\<profil>\Documents\...\C - Captations\...
```

---

### 3.2 NAS

Rôle :

* stockage central des données ;
* point de passage entre laptop et PC fixe ;
* exécution de n8n (orchestration).

Chemin pivot :

```text
\\192.168.0.155\Affaires\
```

---

### 3.3 PC fixe

Rôle :

* traitements batch :

  * analyse LLM des photos ;
  * enrichissement du CSV ;
* exécution des scripts Python lourds.

Environnement :

```text
\\192.168.0.155\GPT4All_Local\.venv
```

---

## 4. Fichier pivot : `infos_projet.json`

### 4.1 Rôle

Point d’entrée unique du pipeline.

Contient :

* `id_affaire`
* `id_captation`
* chemins sources (photos, audio, transcription)
* configuration LLM
* racine NAS (`pcfixe.root_affaires`)

### 4.2 Localisation canonique

```text
\\192.168.0.155\Affaires\<id_affaire>\AF_Expert_ASR\transcriptions\<id_captation>\infos_projet.json
```

---

## 5. Données photos

### 5.1 Fichiers principaux

* `photos.csv` (source UI)
* `photos_batch.csv` (batch PC fixe)
* `*_GTP_*.csv` (données validées)

### 5.2 Règle essentielle

Deux niveaux de chemins :

1. chemin vers `photos.csv` (dans `infos_projet.json`)
2. chemins images dans le CSV

⚠️ Les chemins absolus laptop peuvent devenir obsolètes (changement de profil Windows).

### 5.3 Robustesse

* `generate_word_report.py` inclut désormais des fallbacks :

  * correction de profil Windows ;
  * reconstruction depuis le dossier `photos.csv`.

---

## 6. Pipeline détaillé

### 6.1 Étape 1 — Laptop

* import photos
* génération `photos.csv`
* génération `infos_projet.json`
* copie vers NAS

---

### 6.2 Étape 2 — Synchronisation

* copie vers :

  ```text
  \\192.168.0.155\Affaires\<id_affaire>\...
  ```

---

### 6.3 Étape 3 — Batch PC fixe

Script principal :

```text
run_all_photos_pcfixe.bat
```

Fonctions :

* lecture `photos_batch.csv`
* résolution des chemins PC fixe
* appel LLM
* mise à jour des colonnes :

  * `libelle_propose_batch`
  * `commentaire_propose_batch`

---

### 6.4 Étape 4 — Validation (GTP)

* production d’un fichier :

  ```text
  *_GTP_*.csv
  ```
* contient :

  * annotations validées
  * filtre `annotation_validee`

---

### 6.5 Étape 5 — Rapport Word

Script :

```text
generate_word_report.py
```

Lancé via :

* laptop : `run_generate_word_report_ui.bat`
* n8n / PC fixe : `run_generate_word_report_n8n.bat`

---

## 7. Modes de génération du rapport

### 7.1 Paramètre métier `--mode`

| Mode         | Description             |
| ------------ | ----------------------- |
| `provisoire` | données UI non validées |
| `valide`     | données GTP validées    |

### 7.2 Paramètre `--retenue`

| Valeur | Effet                |
| ------ | -------------------- |
| `oui`  | filtre retenue actif |
| `non`  | toutes les photos    |

---

## 8. Sortie

Dossier canonique :

```text
\\192.168.0.155\Affaires\<id_affaire>\BE_Traitement_captations\<id_captation>\compte_rendu_LLM\
```

Nom du fichier :

```text
annotation_photos_<id_affaire>_<id_captation>_V_<timestamp>.docx
```

---

## 9. Gouvernance du code

### 9.1 Référentiel serveur (lecture seule)

```text
C:\CodexWorkspace\_codex_context\gpt4all_local_context\scripts\projet_photos
```

Interdictions :

* modification directe
* remplacement de fichiers
* validation implicite

---

### 9.2 Propositions

Toutes les modifications doivent être :

```text
PROPOSITION NON VALIDÉE
```

Dans :

```text
...\proposed_changes\...
```

Avec :

* diff
* justification
* impact
* niveau de risque

---

### 9.3 Fichiers critiques

* `utils.py`
* `local_llm_client.py`

Règle :

* jamais modifiés directement
* uniquement propositions explicites

---

## 10. Points de vigilance

* chemins absolus dépendants du profil Windows ;
* cohérence entre laptop / NAS / PC fixe ;
* présence du modèle Word ;
* dépendances Python alignées entre environnements ;
* absence de blocage (`pause`) pour n8n.

---

## 11. Synthèse

| Étape         | Machine          | Script                      |
| ------------- | ---------------- | --------------------------- |
| Préparation   | Laptop           | UI                          |
| Batch         | PC fixe          | `run_all_photos_pcfixe.bat` |
| Rapport       | Laptop / PC fixe | `generate_word_report.py`   |
| Orchestration | NAS              | n8n                         |

---

