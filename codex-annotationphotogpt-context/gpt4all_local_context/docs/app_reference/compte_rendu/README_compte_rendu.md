# 📄 README_compte_rendu.md

## 1. Objet

Le pipeline **compte-rendu** permet de transformer une transcription audio brute (CSV ASR) en compte rendu structuré d’expertise, puis en document Word.

---

## 2. Architecture

Le système repose sur deux composants principaux :

### 2.1 Pipeline de traitement (`cr-pipeline`)

* segmentation de la transcription
* passes LLM (annotation → agrégation → consolidation)
* production de JSON structurés

Scripts principaux :

* `cr_reunion_point_mumerotes_pipeline_json.ps1`
* `split_by_sujet.py`

---

### 2.2 Rendu documentaire (`cr-render`)

* transformation JSON → Markdown / DOCX
* insertion structurée dans modèle Word

Fichiers :

* `app.py`
* `renderer.py`

---

## 3. Pipeline global

```
CSV transcription
→ segmentation
→ PASS 1 (segments)
→ PASS 2 (global)
→ PASS 3 (final)
→ JSON final
→ split_by_sujet
→ rendu (MD / DOCX)
```

---

## 4. Dépendances critiques

Le pipeline dépend de :

* serveur Flask GPT4All_Local
* routes LLM :

  * `/annoter_segments_*`
  * `/report_*`
* modèles LLM (local ou distant)

Toute modification de ces routes ou des formats JSON doit être validée.

---

## 5. Contraintes métier

* neutralité rédactionnelle
* absence d’interprétation
* respect des propos retranscrits
* traçabilité via timecodes

---

## 6. Points critiques

* hallucination des timecodes
* JSON invalide en sortie LLM
* perte d’information lors des agrégations
* cohérence entre passes 1 / 2 / 3

---

## 7. Données manipulées

Entrée :

* CSV ASR (`timecode`, `speaker`, `texte`)

Sorties :

* `segment_XX.json`
* `global.json`
* `global_final.json`
* fichiers par sujet
* Markdown
* DOCX

---

## 8. Règles pour Codex

* ne pas modifier les schémas JSON sans audit
* ne pas casser la compatibilité entre passes LLM
* ne pas modifier les routes serveur sans vérification
* préserver la structure des sorties utilisées par le rendu

---

## 9. Positionnement dans le système global

Ce pipeline est indépendant d’AnnotationPhotoGPT mais partage :

* le serveur Flask
* les modèles LLM
* les dossiers affaire

Toute modification transverse doit être vérifiée sur les deux pipelines.

---

## 10. Principe directeur

→ **garantir un JSON structuré fiable avant toute génération documentaire**

→ **priorité à la cohérence des données sur la qualité rédactionnelle brute**

---
