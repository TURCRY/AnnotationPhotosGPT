# README — Lancements de `run_all_photos_pcfixe.bat`

## Objet

Cette note rappelle les commandes usuelles de lancement du batch photos sur PC fixe.

Script principal :

```text
D:\GPT4All_Local\scripts\projet_photos\run_all_photos_pcfixe.bat
```

Script Python appelé :

```text
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

Préflight uniquement :

* aucune requête serveur envoyée ;
* aucune écriture CSV ;
* affiche ce qui serait traité.

### `--limit N`

Limite le traitement à `N` lignes sélectionnées.

### `--vlm-strict 1`

Force un fonctionnement VLM plus strict :

* flush unitaire ou plus conservateur selon la logique du script.

---

## Cas usuels

### 1. Préflight simple

```bat
run_all_photos_pcfixe.bat "C:\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" --dry-run 1 --vlm-strict 1
```

### 2. Batch réel limité

```bat
run_all_photos_pcfixe.bat "C:\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" --vlm-strict 1 --limit 10
```

---

## Resets disponibles

### `--reset-llm 1`

Relance uniquement le PASS 2 (LLM) sur la sélection :

* conserve `description_vlm_batch`
* conserve le VLM
* vide les sorties LLM et relance libellé/commentaire

Exemple :

```bat
run_all_photos_pcfixe.bat "C:\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" --reset-llm 1 --limit 10
```

Préflight :

```bat
run_all_photos_pcfixe.bat "C:\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" --reset-llm 1 --dry-run 1 --limit 10
```

### `--reset-vlm 1`

Relance le PASS 1 (VLM) sur la sélection :

* remet à blanc la description VLM ciblée ;
* le PASS 2 pourra ensuite rejouer.

Exemple :

```bat
run_all_photos_pcfixe.bat "C:\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" --reset-vlm 1 --limit 10
```

### `--reset-vlm-plus 1`

Remise à blanc plus large des sorties VLM/LLM sur le batch chargé :

* usage exceptionnel ;
* sans combinaison avec les autres resets.

Exemple :

```bat
run_all_photos_pcfixe.bat "C:\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" --reset-vlm-plus 1
```

---

## Règle d’incompatibilité

Ne jamais combiner entre elles les options :

* `--reset-vlm`
* `--reset-llm`
* `--reset-vlm-plus`

Le script refuse ces combinaisons.

---

## Recommandations pratiques

### Pour tester un comportement

Toujours commencer par :

```bat
--dry-run 1
```

### Pour un dossier déjà batché

Travailler de préférence :

* sur une copie du `photos_batch.csv`,
* ou avec un `--limit` réduit,
* avant un rerun plus large.

### Pour vérifier une reprise LLM seule

Utiliser en priorité :

```bat
--reset-llm 1
```

---

## Point technique

La lecture de `infos_projet.json` est désormais tolérante :

* UTF-8 sans BOM
* UTF-8 avec BOM

Aucune adaptation manuelle d’encodage ne doit être nécessaire en usage normal.

---
