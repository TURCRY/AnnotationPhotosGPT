# PROMPT CODEX — T23 (Génération Word / livrable)

## 1. Objectif

Analyser et sécuriser la génération du rapport Word dans AnnotationPhotosGPT.

Le but est de fiabiliser la fabrication du document final sans casser les usages existants.

---

## 2. Périmètre

Fichiers à analyser :

* `scripts/generate_word_report.py`
* `app/export_interface.py`
* fichiers de configuration ou scripts liés à l’export

Documents à lire en priorité :

* `annotationphotogpt_pipeline.md`
* `README_data.md`
* `batch_usage.md`
* `pipeline_compte_rendu.md` si utile pour la logique documentaire

---

## 3. Contraintes métier

### 3.1 Priorité des contenus

La logique de priorité doit être respectée :

```text
GTP > UI > Batch
```

Ne jamais inverser cette hiérarchie sans justification explicite.

### 3.2 Neutralité rédactionnelle

Le document final ne doit pas introduire :

* d’interprétation
* d’affirmation non présente dans les sources
* de reformulation dénaturante

### 3.3 Structure documentaire

Le rapport doit rester stable :

* ordre des clichés
* insertion image + légende
* cohérence des titres
* cohérence des sources textuelles

---

## 4. Problèmes à rechercher

### 4.1 Données

* mauvais choix de texte source
* perte de commentaires validés
* mélange entre UI / batch / GTP
* dépendance fragile aux colonnes CSV

### 4.2 Document

* insertion image défaillante
* légendes incohérentes
* tri incorrect des clichés
* comportement imprévisible si champs manquants

### 4.3 Robustesse

* absence de contrôle sur les fichiers d’entrée
* erreurs silencieuses
* modèle Word mal géré
* manque de traçabilité du document généré

---

## 5. Attendu

Identifier :

* la logique réelle de sélection des données
* les points de fragilité
* les sécurisations minimales possibles

Produire :

```text
ANALYSE
LOGIQUE DE PRIORITÉ
RISQUES
PROPOSITION
DIFF
```

---

## 6. Interdictions

* ne pas changer le format final du livrable sans nécessité
* ne pas casser les scripts `.bat` existants
* ne pas introduire de dépendance lourde
* ne pas modifier la logique métier de priorité sans audit

---

## 7. Priorité

```text
FIDÉLITÉ DU LIVRABLE > STABILITÉ > QUALITÉ DE FORME
```
