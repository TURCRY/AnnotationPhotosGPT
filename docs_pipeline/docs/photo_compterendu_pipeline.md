Voici un fichier **`photo_compterendu_pipeline.md`** structuré, destiné à un usage par Codex (compréhension technique du pipeline).

---

````markdown
# 📄 photo_compterendu_pipeline.md

## 1. Objet

Ce pipeline permet de transformer une transcription brute (CSV issu d’ASR) en compte rendu structuré d’expertise, via plusieurs passes LLM, puis de générer des livrables (JSON, Markdown, DOCX).

---

## 2. Architecture générale

Le pipeline repose sur 4 briques principales :

1. **Pré-traitement**
2. **Pipeline LLM (Passes 1 → 3)**
3. **Post-traitement par sujets**
4. **Rendu (Markdown / DOCX)**

---

## 3. Étape 1 — Entrée

### Input principal
- Fichier CSV de transcription :
  - colonnes typiques : `timecode`, `speaker`, `texte`

### Contrainte critique
- Les horodatages servent de **référence de vérification anti-hallucination**

---

## 4. Étape 2 — Segmentation

Script principal :
- `cr_reunion_pipeline_fulljson.ps1`

Fonction :
- découper la transcription en segments exploitables

Sorties :
- `out/segments/segment_XX.json`
- `out/global.json`

---

## 5. Étape 3 — Pipeline LLM

### 5.1 Vue d’ensemble

Pipeline en 3 passes :

| Passe | Objectif | Sortie |
|------|---------|--------|
| Passe 1 | Annotation par segment | JSON segment |
| Passe 2 | Agrégation globale | JSON global |
| Passe 3 | Consolidation finale | JSON final |

---

### 5.2 Passe 1 — Annotation segment

Route :
- `annoter_segments_local` ou `annoter_segments_remote`

Schéma attendu :
```json
{
  "resume_segment": "",
  "themes": [],
  "actions": [],
  "problems": []
}
````

Normalisation :

* via `normalize_segment_annotation()` 

Points clés :

* JSON strict
* fallback si sortie vide
* détection des réponses incomplètes

---

### 5.3 Passe 2 — Agrégation globale

Objectif :

* fusionner tous les segments

Schéma attendu :

```json
{
  "resume_global": "",
  "themes": [],
  "themes_abordes": [],
  "actions": [],
  "perspectives": [],
  "demandes_documents_globales": [],
  "problems": []
}
```

Normalisation :

* `normalize_report_annotation()` 

---

### 5.4 Passe 3 — Consolidation finale

Objectif :

* produire un JSON final exploitable pour rendu

Contraintes :

* JSON valide obligatoire
* extraction stricte via `_extract_first_json_object()` 

Fallback :

* JSON minimal si échec LLM

---

## 6. Gestion des modèles (Adapter)

Fichier :

* `adapter.py`

Fonctions principales :

* routage local / remote
* fallback multi-modèles
* gestion JSON strict
* retry automatique

Registry modèles :

```python
MODEL_REGISTRY = {
  "annoter_segments_remote": {...},
  "report_remote": {...},
  "pass3_remote": {...}
}
```



---

## 7. Étape 4 — Structuration par sujets

Script :

* `split_by_sujet.py`

Entrées :

* `global.json`
* `sujets_ref.json`

Sorties :

* fichiers `sujet_XXX.json`
* `split_index.json`

Fonctions :

* regroupement par sujet
* déduplication
* découpage par taille (chunking)



---

## 8. Étape 5 — Rendu

### API Flask

Fichier :

* `app.py`

Routes :

* `/render?format=md`
* `/render?format=docx`



---

### 8.1 Markdown

Fonction :

* `render_markdown()`

Structure :

* résumé
* thèmes
* actions
* perspectives



---

### 8.2 DOCX

Fonction :

* `render_docx()`

Contenu enrichi :

* informations générales
* thèmes + citations (timecode)
* analyse par sujet
* actions
* annexes



---

## 9. Gestion des erreurs

### Cas couverts

* JSON invalide
* sortie LLM vide
* dépassement tokens
* modèle indisponible

Mécanismes :

* retry exponentiel
* fallback multi-modèles
* réparation JSON
* JSON minimal garanti



---

## 10. Sécurité / RGPD

* embeddings locaux privilégiés
* fallback remote contrôlé
* RAG désactivé par défaut

Configuration :

* `.env` 

---

## 11. Points critiques du pipeline

### 11.1 Risque principal

* hallucination des timecodes

### 11.2 Contrôle

* comparaison avec transcription source
* structuration par segments

### 11.3 Robustesse

* JSON strict à chaque étape
* fallback systématique

---

## 12. Sorties finales

* `global_final.json`
* fichiers par sujet
* Markdown
* DOCX

---

## 13. Résumé technique

Pipeline =

```
CSV → Segments → Passe 1 → Passe 2 → Passe 3
     → global_final.json
     → split_by_sujet
     → rendu (MD / DOCX)
```

---

## 14. Évolutions possibles

* validation automatique des timecodes
* scoring de fiabilité LLM
* enrichissement RAG
* contrôle juridique automatisé

---

