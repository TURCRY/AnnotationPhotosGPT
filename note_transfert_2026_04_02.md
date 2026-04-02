# Note de transfert — AnnotationPhotosGPT / Codex (T19)

## 1. Contexte

Le dépôt `AnnotationPhotosGPT` a été reconstruit et nettoyé :

* suppression des fichiers lourds et artefacts
* suppression des secrets
* restauration complète du code fonctionnel
* ajout du pipeline batch réel (`batch_pcfixe`)

Branches :

* `main` → baseline propre et stable
* `codex-t19` → branche de travail Codex

---

## 2. Architecture réelle du système

Le projet fonctionne selon une architecture distribuée :

* **Laptop**

  * interface utilisateur (`app/`)
  * orchestration (`scripts/`)

* **PC fixe**

  * traitements batch lourds
  * VLM + LLM
  * scripts contenus dans `batch_pcfixe/`

* **NAS**

  * stockage central
  * synchronisation

---

## 3. Structure du dépôt

```text
app/                → application principale (UI)
scripts/            → orchestration
batch_pcfixe/       → pipeline batch réel (production)
config/             → configuration
data/               → données légères (hors métier lourd)
docs/               → documentation
```

---

## 4. Dossier critique : batch_pcfixe

Contenu :

* `batch_all_photos_pcfixe.py`
* `local_llm_client.py`
* `utils.py`
* `run_all_photos_pcfixe.bat`

### Statut

* code **réel de production**
* utilisé sur le PC fixe
* représente la vérité du pipeline batch

### Règles

* ne pas modifier sans analyse complète
* toute modification doit rester compatible
* ne jamais casser :

  * logique VLM → LLM
  * logique CSV
  * logique d’idempotence

---

## 5. Documentation à utiliser (PRIORITAIRE)

### Noyau dur

```text
annotationphotogpt_pipeline.md
batch_usage.md
batch_reset_strategies.md
README_annotationphotogpt.md
```

### Compléments

```text
tache_codex_annotation_photo.md
README_data.md
```

---

## 6. Ordre de lecture imposé

```text
1. annotationphotogpt_pipeline.md
2. batch_usage.md
3. batch_reset_strategies.md
4. README_annotationphotogpt.md
5. tache_codex_annotation_photo.md
```

Ces documents décrivent l’état réel du système et prévalent sur toute hypothèse.

---

## 7. Règles métier critiques

### 7.1 Idempotence (fondamentale)

Le système repose sur un CSV batch.

Interdictions :

* retraiter une ligne déjà traitée
* écraser des données existantes
* modifier les statuts sans logique

---

### 7.2 Pipeline VLM → LLM

Ordre strict :

```text
image → VLM → description → LLM → libellé + commentaire
```

Interdiction :

* lancer LLM sans VLM
* recalculer VLM inutilement

---

### 7.3 Données

* ne jamais supprimer de données existantes
* ne jamais modifier la structure CSV sans justification
* ne jamais casser la compatibilité UI / batch

---

## 8. Relations entre les composants

### app/

* interface utilisateur
* dépend des résultats batch

### scripts/

* orchestration
* déclenche batch + export

### batch_pcfixe/

* exécution réelle du traitement
* doit rester cohérent avec `app/`

---

## 9. Contraintes de développement

### Non-régression

* ne pas casser l’existant
* modifications minimales uniquement

### Cohérence multi-environnement

* laptop ≠ PC fixe
* mais pipeline unique

### Sécurité

* aucune clé API en dur
* utilisation `.env`

---

## 10. Problèmes historiques à éviter

* inclusion de fichiers lourds
* inclusion de secrets
* duplication de logique batch
* perte d’idempotence
* désynchronisation VLM / LLM

---

## 11. Méthode attendue de Codex

Toujours :

1. analyser le code existant
2. comprendre les dépendances
3. identifier les risques
4. proposer une modification minimale
5. fournir un diff clair

---

## 12. Tâche initiale (T19)

Analyser :

* `batch_pcfixe/batch_all_photos_pcfixe.py`
* interaction avec :

  * `app/`
  * `scripts/`

Vérifier :

* logique VLM → LLM
* gestion des statuts CSV
* conditions de relance
* risques de recalcul

---

## 13. Instruction finale

```text
Priorité absolue :
STABILITÉ > COMPRÉHENSION > MODIFICATION > OPTIMISATION
```

Le système est déjà fonctionnel.
Toute intervention doit être prudente, incrémentale et justifiée.
