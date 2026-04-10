# README `generate_word_report.py`

## Finalite

`generate_word_report.py` produit le document Word de synthese des photographies pour `AnnotationPhotosGPT`.

Le script fabrique un fichier `.docx` a partir :

- de la liste des photos issue du CSV UI ;
- des textes d'annotation issus du CSV GTP si disponible ;
- des textes batch si disponibles ;
- du contexte projet pour enrichir l'en-tete du document.

Le rapport genere contient notamment :

- un en-tete d'informations generales ;
- une table des cliches ;
- une entree par photographie avec :
  - le commentaire retenu ;
  - l'image ;
  - la legende Word de type `Cliche X - ...` ;
  - la source du texte retenu (`GTP`, `UI`, `BATCH`).

## Entrees du script

### Entree canonique

L'entree principale est `infos_projet.json`, passe de preference via `--infos`.

Depuis ce fichier, le script lit notamment :

- `id_affaire`
- `id_captation`
- `fichier_photos`
- `fichier_photos_batch`
- `fichier_contexte_general`

### Sources de donnees exploitees

- `photos.csv` ou `photos.xlsx` : source UI, utilisee comme base de la liste des photos
- `photos_batch.csv` : source batch, utilisee en complement si presente
- `*_GTP_*.csv` : source GTP, utilisee si presente

### Overrides optionnels

Le script accepte aussi des overrides explicites :

- `--photos`
- `--batch`
- `--gtp`

Ces overrides remplacent la valeur issue de `infos_projet.json` pour la source concernee.

## Mode d'appel

### Usage canonique

```powershell
python C:\AnnotationPhotosGPT\scripts\generate_word_report.py --infos "C:\chemin\vers\infos_projet.json"
```

### Usage avec overrides

```powershell
python C:\AnnotationPhotosGPT\scripts\generate_word_report.py `
  --infos "\\192.168.0.155\Affaires\2026-J1\AF_Expert_ASR\transcriptions\cap-2026-04-10\infos_projet.json" `
  --photos "\\192.168.0.155\Affaires\2026-J1\AE_Expert_captations\cap-2026-04-10\photos\photos.csv" `
  --batch "\\192.168.0.155\Affaires\2026-J1\AE_Expert_captations\cap-2026-04-10\photos\photos_batch.csv"
```

### Usage legacy

Sans argument, le script conserve un mode legacy :

```powershell
python C:\AnnotationPhotosGPT\scripts\generate_word_report.py
```

Dans ce cas, il utilise par defaut :

- `C:\AnnotationPhotosGPT\data\infos_projet.json`

## Resolution des chemins

### `infos_projet.json`

- si `--infos` est fourni, ce chemin est utilise ;
- sinon, le script utilise `data\infos_projet.json` sous la racine du projet ;
- un chemin relatif est resolu relativement a la racine du projet.

### `fichier_photos`

- le script prend d'abord `--photos` si fourni ;
- sinon il prend `infos["fichier_photos"]` ;
- si le chemin est relatif, il est resolu relativement au dossier contenant `infos_projet.json`.

Ce fichier est obligatoire.

### `fichier_photos_batch`

- le script prend d'abord `--batch` si fourni ;
- sinon il prend `infos["fichier_photos_batch"]` ;
- si le chemin est relatif, il est resolu relativement au dossier contenant `infos_projet.json`.

Cette source est optionnelle. Si le fichier est absent, le rapport reste generable sans donnees batch.

### CSV GTP

- le script prend `--gtp` si fourni ;
- sinon il cherche le fichier GTP le plus recent dans le dossier du fichier photos ;
- ce fallback repose sur le motif `*_GTP_*.csv`.

Le fallback actuel GTP est donc base sur le "dernier fichier modifie" dans le dossier des photos.

## Logique metier de rapprochement

## Base de travail

La base du rapport est toujours le CSV photos UI :

- il definit la liste des photos ;
- il porte les chemins image ;
- il porte aussi les champs UI eventuellement proposes.

## Role des sources

### UI

La source UI sert de socle :

- liste des photos ;
- champs `libelle_propose_ui` et `commentaire_propose_ui` si presents ;
- colonnes techniques comme `chemin_photo_reduite`, `chemin_photo_native`, `orientation_photo`, `nom_fichier_image`.

### GTP

La source GTP peut enrichir ou remplacer les textes via :

- `libelle`
- `commentaire`
- `retenue`

En mode `REPORT_MODE=GTP`, le script filtre la liste des photos pour ne garder que celles presentes dans le GTP, avec prise en compte de `annotation_validee` si cette colonne existe.

### Batch

La source batch est mergee si disponible, principalement sur `photo_rel_native`, avec lecture de :

- `libelle_propose_batch`
- `commentaire_propose_batch`
- `batch_status`
- `batch_ts`

## Priorite des textes

La priorite actuelle est :

1. `GTP`
2. `UI`
3. `BATCH`

Concretement :

- `libelle_final` prend d'abord `libelle` GTP ;
- sinon `libelle_propose_ui` ;
- sinon `libelle_propose_batch`.

Et de meme pour `commentaire_final`.

Le script renseigne aussi une colonne de provenance :

- `GTP`
- `UI`
- `BATCH`
- `VIDE`

## Si une source est absente

- si le batch est absent : le rapport continue avec UI et/ou GTP ;
- si le GTP est absent : le rapport continue avec UI et/ou batch ;
- si les deux sont absents : le rapport peut toujours etre genere a partir du CSV UI, avec des textes eventuellement vides.

## Sortie produite

Le fichier genere est un `.docx` nomme selon le schema :

```text
annotation_photos_<id_affaire>_<id_captation>_V_<YYYY-MM-DD_HH-MM>.docx
```

`id_affaire` et `id_captation` sont lus depuis `infos_projet.json`.

Le document est ecrit dans le meme dossier que le fichier photos utilise comme base.

## Limites actuelles et points de vigilance

- le GTP repose encore, par defaut, sur une recherche du fichier `*_GTP_*.csv` le plus recent dans le dossier des photos ;
- si plusieurs exports GTP coexistent, le script peut donc prendre le plus recent sans autre validation metier ;
- la sortie Word depend de la presence du modele `data\Modele word rapport ver 15 05 2025.docx` ;
- le script suppose que les colonnes de merge attendues existent dans les sources quand celles-ci sont presentes ;
- il ne refond pas les donnees : il applique la priorite metier existante sans arbitrage supplementaire ;
- les chemins d'images doivent etre coherents dans le CSV UI pour que les photos soient inserees correctement ;
- le rapport est tolerant a l'absence de certaines sources, mais pas a l'absence du CSV photos principal.

## Conseils d'usage dans le pipeline global

- utiliser `--infos` comme point d'entree standard pour bien cibler un couple `id_affaire` / `id_captation` ;
- preferer des chemins absolus ou UNC dans `infos_projet.json` quand le script doit fonctionner en contexte reseau ;
- n'utiliser les overrides `--photos`, `--batch`, `--gtp` que pour du controle ponctuel ou du diagnostic ;
- pour un usage stable en multi-affaires / multi-captations, verifier que `fichier_photos` et `fichier_photos_batch` pointent bien vers la captation attendue ;
- si plusieurs CSV GTP sont presents, utiliser `--gtp` pour lever toute ambiguite ;
- conserver la logique de priorite `GTP > UI > BATCH` comme reference documentaire du script.
