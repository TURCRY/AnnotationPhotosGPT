Oui, il vaut mieux abandonner `UI` et `GTP` dans l’interface utilisateur des `.bat`.

Ces termes peuvent rester **internes au code**, puisque `generate_word_report.py` attend encore `REPORT_MODE=UI` ou `REPORT_MODE=GTP`. Mais côté usage, il est plus clair d’exposer :

* **données provisoires**
* **données validées**

Et, puisque vous envisagez un déclenchement via n8n, vous avez raison de préférer un mode **paramétrable par arguments** plutôt qu’un mode purement interactif.

Le bon schéma est donc :

* un batch qui **accepte des paramètres CLI**
* et qui, **si les paramètres sont absents**, bascule en interactif

Ainsi, vous avez les deux usages :

* manuel
* automatisable

## 1. Correspondance des termes

Il faut documenter la correspondance ainsi :

* **données provisoires** ⟶ `REPORT_MODE=UI`
* **données validées** ⟶ `REPORT_MODE=GTP`

et :

* **retenue seulement** ⟶ `REPORT_ONLY_RETENUE=1`
* **toutes les photos** ⟶ `REPORT_ONLY_RETENUE=0`

Autrement dit, le batch traduit des termes métier clairs vers les variables techniques du script Python. Le script, lui, n’a pas besoin d’être modifié immédiatement.

## 2. Paramètres conseillés

Je vous propose des paramètres lisibles :

* `--infos`
* `--mode`
* `--retenue`

avec les valeurs :

* `--mode provisoire`
* `--mode valide`
* `--retenue oui`
* `--retenue non`

C’est lisible pour l’humain, et exploitable depuis n8n.

## 3. Batch laptop : `run_generate_word_report_ui.bat`

À placer dans :

```text
C:\AnnotationPhotosGPT\scripts\
```

Ce batch :

* accepte `--infos`, `--mode`, `--retenue`
* sinon demande ces valeurs en interactif
* traduit ensuite en `REPORT_MODE` / `REPORT_ONLY_RETENUE`



## 4. Batch PC fixe : `run_generate_word_report_gtp.bat`

Même logique, mais en visant le `infos_projet.json` canonique du couple `id_affaire / id_captation`.

À placer dans :

```text
\\192.168.0.155\GPT4All_Local\scripts\projet_photos\scripts\
```

## 5. Exemples pour n8n

### Laptop, données provisoires

```bat
run_generate_word_report_ui.bat --infos "C:\AnnotationPhotosGPT\data\infos_projet.json" --mode provisoire --retenue oui
```

### Laptop, données validées

```bat
run_generate_word_report_ui.bat --infos "C:\AnnotationPhotosGPT\data\infos_projet.json" --mode valide --retenue oui
```

### PC fixe, par identifiants

```bat
run_generate_word_report_gtp.bat --affaire 2025-J46 --captation accedit-2025-11-06 --mode valide --retenue oui
```

### PC fixe, par chemin complet

```bat
run_generate_word_report_gtp.bat --infos "\\192.168.0.155\Affaires\2025-J46\AF_Expert_ASR\transcriptions\accedit-2025-11-06\infos_projet.json" --mode valide --retenue oui
```

