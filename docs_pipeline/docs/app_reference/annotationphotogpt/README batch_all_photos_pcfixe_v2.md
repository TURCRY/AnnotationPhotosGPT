

---

# README — Lancements de `run_all_photos_pcfixe.bat`

## Objet

Cette note décrit les commandes usuelles de lancement du batch photos sur PC fixe, ainsi que les statuts et comportements du pipeline.

Scripts principaux :

```text
D:\GPT4All_Local\scripts\projet_photos\run_all_photos_pcfixe.bat
D:\GPT4All_Local\scripts\projet_photos\batch_all_photos_pcfixe.py
```

---

## Syntaxe générale

```bat
run_all_photos_pcfixe.bat "C:\...\infos_projet.json" [options]
```

Exemple :

```bat
run_all_photos_pcfixe.bat "C:\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" --vlm-strict 1 --limit 10
```

---

## Options principales

### `--dry-run 1`

Mode préflight :

* aucune requête serveur envoyée ;
* aucune écriture CSV ;
* affiche la sélection et les actions prévues.

---

### `--limit N`

Limite le traitement à `N` lignes sélectionnées.

---

### `--vlm-strict 1`

Mode VLM plus strict :

* gestion plus conservatrice des appels VLM.

---

### `--only-new-dictee 1`

Sélectionne uniquement les photos avec dictée ASR exploitable récente :

* `dictee_asr_status == "OK"`
* texte non vide
* timestamp valide et postérieur au dernier batch

---

### `--rerun-weak 1`

Relance ciblée sur les lignes faibles du `photos_batch.csv`.

Comportement :

* ne recalcule jamais le VLM (PASS 1) ;
* relance le PASS 2 texte :

  * libellé systématiquement ;
  * commentaire si nécessaire ;
* cible uniquement les statuts faibles.

Statuts concernés :

* `WEAK_LIB`
* `OK_LIB_COM_WEAK` (si présent)

---

### `--rerun-weak-backend same|local|remote`

Force le backend LLM pour le rerun weak :

* `same` : configuration actuelle
* `local` : backend local
* `remote` : backend distant (ex : OpenAI)

---

## Statuts batch

### Statuts principaux

* `OK_LIB` : libellé exploitable
* `WEAK_LIB` : libellé produit mais insuffisant
* `ERR_LIB` : échec de génération du libellé

### Statuts combinés

* `OK_LIB_COM` : libellé + commentaire OK
* `OK_LIB_COM_WEAK` : commentaire faible
* `OK_LIB_ERR_COM` : échec commentaire

---

## Détection des libellés faibles

Un libellé est marqué `WEAK_LIB` si :

* trop court ;
* formulation générique (boilerplate) ;
* expressions typiques :

  * « vue générale »
  * « élément non précisé »

Traçabilité :

```text
[LIB][WEAK] idx=... reason=...
```

---

## Cas usuels

### Préflight

```bat
run_all_photos_pcfixe.bat "...infos_projet.json" --dry-run 1
```

---

### Batch réel limité

```bat
run_all_photos_pcfixe.bat "...infos_projet.json" --limit 10
```

---

### Rerun weak

```bat
run_all_photos_pcfixe.bat "...infos_projet.json" --rerun-weak 1
```

Avec backend distant :

```bat
run_all_photos_pcfixe.bat "...infos_projet.json" --rerun-weak 1 --rerun-weak-backend remote
```

---

## Resets

### `--reset-llm 1`

Relance le PASS 2 uniquement :

* conserve le VLM
* régénère libellé + commentaire

---

### `--reset-vlm 1`

Relance le PASS 1 :

* recalcul VLM
* le PASS 2 pourra suivre

---

### `--reset-vlm-plus 1`

Remise à blanc large (usage exceptionnel).

---

## Règle d’incompatibilité

Ne pas combiner :

* `--reset-vlm`
* `--reset-llm`
* `--reset-vlm-plus`

---

## Workflow recommandé

### 1. Run complet

```bat
run_all_photos_pcfixe.bat "...infos_projet.json"
```

### 2. Analyse

Surveiller :

* `WEAK_LIB`
* `OK_LIB_COM_WEAK`
* `ERR_LIB`
* `OK_LIB_ERR_COM`

---

### 3. Rerun ciblé

```bat
run_all_photos_pcfixe.bat "...infos_projet.json" --rerun-weak 1
```

---

### 4. Reprise métier

Selon le cas :

* correction UI
* ajout de dictée
* rerun local / distant
* reset ciblé

---

## Recommandations pratiques

### Tests

Toujours commencer par :

```bat
--dry-run 1
```

---

### Dossiers déjà batchés

* travailler avec `--limit` si besoin ;
* le `photos_batch.csv` est la référence ;
* une copie peut être utile pour tests, mais non obligatoire.

---

### Reprise LLM seule

```bat
--reset-llm 1
```

---

## Point technique

Lecture de `infos_projet.json` compatible :

* UTF-8
* UTF-8 BOM

---

## Conclusion

Ce script permet :

* un traitement batch complet
* un ciblage fin des cas faibles (`WEAK_LIB`)
* une reprise maîtrisée sans recalcul VLM
* une itération rapide entre batch et correction métier

---
