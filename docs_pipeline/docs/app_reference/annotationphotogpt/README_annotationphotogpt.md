# AnnotationPhotoGPT

## 1. Objet

AnnotationPhotoGPT est une application d’annotation automatisée de photographies dans le cadre d’expertises.

À partir :

* de photographies,
* d’une transcription audio horodatée,
* d’un contexte de mission,

l’application produit :

* un libellé descriptif court,
* un commentaire factuel,

dans un cadre strictement neutre.

---

## 2. Architecture

### 2.1 UI (poste expert)

* Interface Streamlit (`main.py`)
* Annotation interactive
* Validation des clichés
* Génération CSV UI

### 2.2 Batch (PC fixe)

* Script : `batch_all_photos_pcfixe.py`
* Traitement :

  * PASS 1 : VLM (description image)
  * PASS 2 : LLM (libellé + commentaire)

### 2.3 Sortie documentaire

* Script : `generate_word_report.py`
* Génération du rapport Word des clichés

---

## 3. Pipeline

Photos
↓
CSV photos (UI)
↓
Synchronisation audio / photos
↓
Batch (VLM + LLM)
↓
Validation expert (UI)
↓
CSV GTP
↓
Rapport Word

---

## 4. Composant audio (WaveSurfer)

Localisation :
C:\WaveComponent\streamlit_wavesurfer\frontend\src

Technologies :

* Vite
* TypeScript
* React

Fonctions :

* affichage waveform
* navigation temporelle
* synchronisation avec photos

---

## 5. Données

### CSV photos (UI)

* source de vérité

### CSV batch

* résultats automatiques

### CSV GTP

* annotations validées

### Configuration

* `infos_projet.json`

---

## 6. Lancement

### 6.1 UI

Via script recommandé :

```
gestion_projet.bat
```

Ou directement :

```
python main.py
```

---

### 6.2 Batch

Via script recommandé :

```
run_all_photos_pcfixe.bat
```

Ce script permet :

* exécution complète
* reprise sur erreurs
* relance partielle (ex : LLM)

---

### 6.3 Rapport Word

```
python generate_word_report.py
```

Variables possibles :

```
REPORT_MODE=UI | GTP
REPORT_ONLY_RETENUE=1
```

---

## 7. Règles métier

Priorité des textes :
**GTP > UI > Batch**

Contraintes :

* description factuelle
* pas d’interprétation
* neutralité stricte

---

## 8. Points critiques

* synchronisation audio/photo
* cohérence des chemins (NAS / PC fixe)
* gestion des erreurs batch
* dépendance au composant WaveSurfer

---

## 9. Documentation

* `annotationPhotoGPT_pipeline.md`
* `batch_usage.md`
* `batch_reset_strategies.md`
* `liste_taches_annotationphotogpt.md`

---

## 10. Bonnes pratiques

* valider en UI avant rapport
* utiliser les scripts `.bat`
* éviter les reset complets
* privilégier les relances ciblées
