# README `generate_word_report.py`

## Résumé rapide

`generate_word_report.py` génère un rapport Word d'annotations photos à partir de `infos_projet.json` et des sources de données disponibles autour de la captation.

Le script :

- lit `id_affaire` et `id_captation` depuis `infos_projet.json` ;
- résout le fichier photos UI, le batch et le CSV GTP à partir de `infos_projet.json` et/ou d'overrides CLI ;
- fabrique un `.docx` à partir du modèle Word du projet ;
- écrit le document dans le dossier canonique :
  `<root_affaires>\<id_affaire>\BE_Traitement_captations\<id_captation>\compte_rendu_LLM\`
  avec `root_affaires = infos["pcfixe"]["root_affaires"]` si cette valeur est une UNC, sinon fallback vers `\\192.168.0.155\Affaires`.

## Objet du script

Le script [generate_word_report.py](C:\CodexWorkspace\AnnotationPhotosGPT\scripts\generate_word_report.py) produit le rapport Word des annotations photos.

La logique réelle est la suivante :

- la base de travail est toujours le fichier UI `fichier_photos` ;
- les textes GTP sont utilisés si un `*_GTP_*.csv` est fourni ou découvert ;
- les textes batch sont utilisés si `fichier_photos_batch` est disponible ;
- les commentaires et libellés finaux sont choisis selon la priorité `GTP > UI > BATCH`.

`infos_projet.json` joue le rôle de point d'entrée canonique :

- il fournit `id_affaire` et `id_captation` ;
- il fournit les chemins principaux déjà validés côté application ;
- il permet de retrouver le dossier de sortie canonique via `pcfixe.root_affaires`.

## Paramètres CLI réels

Le script accepte exactement les paramètres suivants :

- `--infos`
  Chemin vers `infos_projet.json`.
  Valeur par défaut : `<racine_projet>\data\infos_projet.json`
- `--photos`
  Override explicite de `fichier_photos`
- `--batch`
  Override explicite de `fichier_photos_batch`
- `--gtp`
  Override explicite du CSV GTP

Il n'y a pas d'autre paramètre CLI dans le script.

## Résolution des entrées

### Point d'entrée `--infos`

Le script résout d'abord `--infos` :

- si le chemin est absolu, il est utilisé tel quel ;
- s'il est relatif, il est résolu par rapport à la racine du projet `AnnotationPhotosGPT` ;
- le fichier doit exister, sinon le script échoue immédiatement.

Le JSON est ensuite chargé sans normalisation supplémentaire.

### Clés effectivement exploitées dans `infos_projet.json`

Les clés réellement lues par le script sont :

- `id_affaire`
- `id_captation`
- `fichier_photos`
- `fichier_photos_batch`
- `fichier_contexte_general`
- `pcfixe.root_affaires`
- `user`
- `model`
- `mission`

Le script n'exige pas explicitement que `id_affaire` et `id_captation` soient non vides, mais ils sont utilisés tels quels dans le nom du DOCX et le chemin de sortie.

### Résolution du fichier photos

Ordre réel de résolution :

1. `--photos` si fourni
2. `infos["fichier_photos"]`

Règles :

- le chemin est résolu relativement au dossier contenant `infos_projet.json` si besoin ;
- le fichier est obligatoire ;
- le script accepte `.csv` ou `.xlsx`.

### Résolution du fichier batch

Ordre réel de résolution :

1. `--batch` si fourni
2. `infos["fichier_photos_batch"]`

Règles :

- le chemin est résolu relativement au dossier contenant `infos_projet.json` si besoin ;
- la source batch est optionnelle ;
- le fichier n'est chargé que s'il existe réellement ;
- la lecture batch est faite via `pandas.read_csv(..., encoding="utf-8-sig")` sans fallback d'encodage.

### Résolution du CSV GTP

Ordre réel de résolution :

1. `--gtp` si fourni
2. recherche automatique du fichier le plus récent correspondant à `*_GTP_*.csv` dans le dossier du fichier photos

Règles :

- si `--gtp` est fourni, le chemin est résolu relativement au dossier du fichier photos ;
- si aucun GTP n'est trouvé, le script continue avec `annotations_df = None` ;
- la découverte automatique ne regarde que le dossier du fichier photos, pas d'autres emplacements.

### Résolution du contexte JSON

Le contexte n'est pas piloté par un paramètre CLI dédié.

Ordre réel de résolution :

1. `infos["fichier_contexte_general"]`
2. fallback texte `contexte_general.json`

Règles :

- si le chemin n'est pas absolu, il est résolu relativement à la racine du projet ;
- si le fichier n'existe pas, le script continue avec un contexte vide `{}` ;
- ce contexte sert uniquement à enrichir l'en-tête du document.

## Logique de fusion et comportement réel

### Source de vérité principale

Le CSV / XLSX de photos UI est la base de la liste des clichés :

- il définit la population de photos ;
- il porte les chemins image ;
- il sert de support au filtrage `retenue`.

### Mode GTP

Le comportement dépend de la variable d'environnement `REPORT_MODE` :

- valeur par défaut : `UI`
- autre valeur prévue par le code : `GTP`

En mode `GTP` :

- le script exige un CSV GTP chargé et non vide ;
- il filtre les photos sur les `nom_fichier_image` présents dans le GTP ;
- si la colonne `annotation_validee` existe, seules les lignes avec `annotation_validee == 1` sont retenues ;
- sinon toutes les lignes GTP sont prises en compte.

### Filtre retenue

Le comportement dépend de la variable d'environnement `REPORT_ONLY_RETENUE` :

- valeur par défaut : active (`1`)

Si la colonne `retenue` existe dans la source UI :

- elle est normalisée en booléen ;
- seules les photos retenues sont gardées quand `REPORT_ONLY_RETENUE` est actif.

Si la colonne est absente :

- toutes les photos sont considérées retenues.

### Priorité des textes

Le code construit :

- `libelle_final`
- `commentaire_final`
- `source_texte`

Priorité réelle :

1. `GTP`
2. `UI`
3. `BATCH`

Les colonnes exploitées sont :

- GTP : `libelle`, `commentaire`, `retenue`
- UI : `libelle_propose_ui`, `commentaire_propose_ui`
- batch : `libelle_propose_batch`, `commentaire_propose_batch`, `batch_status`, `batch_ts`

## Emplacement de sortie réel

Le script écrit toujours le DOCX dans le dossier canonique :

`<root_affaires>\<id_affaire>\BE_Traitement_captations\<id_captation>\compte_rendu_LLM\`

où :

- `id_affaire = infos["id_affaire"]`
- `id_captation = infos["id_captation"]`
- `root_affaires = infos["pcfixe"]["root_affaires"]` si cette valeur commence par `\\`
- sinon fallback forcé vers `\\192.168.0.155\Affaires`

Exemple canonique :

```text
\\192.168.0.155\Affaires\2025-J38\BE_Traitement_captations\accedit-2025-07-03\compte_rendu_LLM\
```

Point important :

- le nom canonique exact est `BE_Traitement_captations` ;
- le DOCX final est rangé sous `compte_rendu_LLM` ;
- `AE_Expert_captations` reste la zone source des photos, pas le dossier de sortie du rapport.

## Nommage du DOCX

Le nom de fichier produit est exactement :

```text
annotation_photos_<id_affaire>_<id_captation>_V_<YYYY-MM-DD_HH-MM>.docx
```

Exemple :

```text
annotation_photos_2025-J38_accedit-2025-07-03_V_2026-04-14_09-42.docx
```

## Exemples de commande

### Exemple minimal avec `--infos`

```powershell
python C:\CodexWorkspace\AnnotationPhotosGPT\scripts\generate_word_report.py `
  --infos "C:\CodexWorkspace\AnnotationPhotosGPT\data\infos_projet.json"
```

### Exemple avec overrides `--photos`, `--batch`, `--gtp`

```powershell
python C:\CodexWorkspace\AnnotationPhotosGPT\scripts\generate_word_report.py `
  --infos "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" `
  --photos "\\192.168.0.155\Affaires\2025-J38\AE_Expert_captations\accedit-2025-07-03\photos\photos.csv" `
  --batch "\\192.168.0.155\Affaires\2025-J38\AE_Expert_captations\accedit-2025-07-03\photos\photos_batch.csv" `
  --gtp "\\192.168.0.155\Affaires\2025-J38\AE_Expert_captations\accedit-2025-07-03\photos\photos_GTP_2026-04-14.csv"
```

## Pré-requis

### Dépendances Python utilisées

Le script importe au minimum :

- `python-docx`
- `pandas`
- `Pillow`
- `openpyxl`

### Modèle Word requis

Le modèle attendu est :

```text
<racine_projet>\data\Modele word rapport ver 15 05 2025.docx
```

Ce fichier doit exister, sinon le script échoue.

### Structure de données attendue

Côté source UI, le script suppose notamment la présence des colonnes utiles à l'insertion des images et des textes, en particulier :

- `nom_fichier_image`
- `chemin_photo_reduite` ou `chemin_photo_native`
- `orientation_photo`

Pour les fusions optionnelles :

- GTP : `nom_fichier_image`
- batch : `photo_rel_native`

## Notes de robustesse

Comportement réel en cas d'absence partielle des fichiers :

- si `infos_projet.json` est absent : échec immédiat ;
- si `fichier_photos` est absent : échec immédiat ;
- si le GTP est absent : le script continue sans GTP ;
- si le batch est absent : le script continue sans batch ;
- si le contexte JSON est absent : le script continue avec un contexte vide ;
- si une image est introuvable : le DOCX est généré avec la mention `[Image introuvable]` pour la photo concernée ;
- si une image pose erreur à l'ouverture : le DOCX est généré avec la mention `[Erreur image]`.

## Points de vigilance

- le fallback `root_affaires` n'accepte pas une racine locale non UNC : si `pcfixe.root_affaires` ne commence pas par `\\`, le script bascule vers `\\192.168.0.155\Affaires` ;
- le GTP auto-découvert est le plus récent par date de modification dans le dossier du fichier photos ;
- la lecture batch n'a pas le fallback d'encodage latin-1 utilisé ailleurs dans le script ;
- `id_affaire` et `id_captation` sont utilisés tels quels pour nommer le document et construire le répertoire de sortie ;
- le rapport est généré à partir du comportement réel du code, pas d'une convention documentaire externe.
