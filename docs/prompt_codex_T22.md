# PROMPT CODEX — T22 (CSV / états batch)

## 1. Objectif

Analyser et sécuriser la gestion des CSV et des états batch dans AnnotationPhotosGPT.

Le point critique est la conservation de la cohérence entre :

* `photos.csv`
* `photos_batch.csv`
* `infos_projet.json`

---

## 2. Périmètre

Fichiers et zones à analyser :

* `batch_pcfixe/batch_all_photos_pcfixe.py`
* `app/selection_fichiers_interface.py`
* `app/utils.py`
* `app/infos_projet.py`
* scripts associés dans `scripts/`

Documents à lire en priorité :

* `annotationphotogpt_pipeline.md`
* `batch_usage.md`
* `batch_reset_strategies.md`
* `README_data.md`
* `tache_codex_annotation_photo.md`

---

## 3. Contraintes critiques

### 3.1 Clé de jointure

La clé `photo_rel_native` est structurante.

Interdictions :

* ne pas la renommer
* ne pas la recalculer différemment sans audit
* ne pas casser son unicité

### 3.2 Source de vérité

* `photos.csv` = référence UI
* `photos_batch.csv` = enrichissement batch
* `infos_projet.json` = fichier pivot de configuration

### 3.3 Idempotence

* une ligne `ok` ne doit pas être retraitée
* une ligne en erreur doit pouvoir être relancée proprement
* aucune écriture ne doit corrompre le CSV

### 3.4 Écriture

* privilégier écriture atomique
* éviter toute perte de colonnes
* éviter toute mutation implicite des schémas

---

## 4. Problèmes à rechercher

### 4.1 Cohérence

* colonnes divergentes UI / batch
* collisions de `photo_rel_native`
* lignes dupliquées
* ordre de priorité mal appliqué

### 4.2 Robustesse

* CSV partiellement écrits
* erreurs silencieuses
* colonnes absentes ou instables
* dépendances fragiles à l’ordre des colonnes

### 4.3 Reprises

* reset trop large
* relance qui efface des données utiles
* statuts incohérents

---

## 5. Objectif de l’analyse

Identifier :

* les invariants réels des CSV
* les points où un bug pourrait détruire ou dupliquer des données
* les améliorations minimales pour sécuriser le système

---

## 6. Ce qui est attendu

Produire :

```text
ANALYSE
INVARIANTS CSV
RISQUES
PROPOSITION
DIFF
```

---

## 7. Interdictions

* pas de refonte globale
* pas de migration de format
* pas de changement de contrat implicite entre UI et batch
* pas d’ajout de complexité gratuite

---

## 8. Priorité

```text
INTÉGRITÉ DES DONNÉES > IDÉMPOTENCE > LISIBILITÉ
```
