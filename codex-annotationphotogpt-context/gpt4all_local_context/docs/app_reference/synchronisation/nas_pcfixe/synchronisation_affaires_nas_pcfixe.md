# Note — synchronisation des affaires entre le NAS et le PC fixe

## Statut

Ce document décrit un mécanisme de synchronisation en production.

→ Il constitue un CONTRAT D’ARCHITECTURE.

Toute modification doit être validée globalement (NAS + PC fixe + applications).

## Objet

Cette note décrit le mécanisme réellement en place pour la synchronisation **NAS ↔ PC fixe** des dossiers d’affaires, sur la base :

- d’une **planification `crontab` sur le NAS** ;
- d’un script shell **`/volume1/Web/Pilote_Affaires/scripts/sync_affaires.sh`** ;
- d’échanges **`rsync` via `ssh`** avec le PC fixe Windows.

L’objectif est de donner à Codex une vue opérationnelle exacte du dispositif, des chemins utilisés, des filtres appliqués et des fichiers métier impactés.

---

## 1. Planification effective sur le NAS

La synchronisation des affaires est déclenchée par la ligne suivante de la `crontab` du NAS :

```cron
10 */2 * * * flock -n /var/lock/sync_affaires.lock su -s /bin/sh - nicolas -c '/volume1/Web/Pilote_Affaires/scripts/sync_affaires.sh' >> /volume1/Web/logs/sync_affaires.log 2>&1
```

### Conséquences pratiques

- exécution **toutes les 2 heures**, à **H:10** ;
- exécution protégée par un **verrou** : `/var/lock/sync_affaires.lock` ;
- exécution sous l’utilisateur **`nicolas`** ;
- journalisation standard vers :
  - `/volume1/Web/logs/sync_affaires.log`

Ce point est important : il ne s’agit pas d’un déclenchement côté PC fixe, mais bien d’un **pilotage centralisé depuis le NAS**.

---

## 2. Script maître de synchronisation

Le script exécuté est :

```text
/volume1/Web/Pilote_Affaires/scripts/sync_affaires.sh
```

Il s’agit du script de référence à préserver en cas de modification du dispositif.

### 2.1. Environnement fixé par le script

Le script pose explicitement :

```sh
export HOME=/volume1/home/nicolas
export USER=nicolas
export PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
```

Il fonctionne donc dans un environnement volontairement stabilisé.

---

## 3. Journalisation et traces

Le script crée un journal mensuel dédié :

```text
/volume1/Web/logs/sync_affaires.YYYY-MM.log
```

Exemple de variable utilisée :

```sh
LOG_FILE="/volume1/Web/logs/sync_affaires.$(date '+%Y-%m').log"
```

### Traces associées

- journal courant `crontab` :
  - `/volume1/Web/logs/sync_affaires.log`
- journal mensuel détaillé :
  - `/volume1/Web/logs/sync_affaires.YYYY-MM.log`
- indicateur d’échec :
  - `/volume1/Web/logs/sync_affaires.FAIL`

### Rétention

Le script purge automatiquement les journaux `sync_affaires.*.log` de plus de 90 jours.

---

## 4. Gestion des alertes

Le script prévoit un envoi d’alerte SMTP si le fichier suivant est lisible :

```text
/volume1/Web/secrets/smtp_lws.env
```

Ce fichier peut contenir notamment :

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `MAIL_FROM`
- `MAIL_TO`

En cas d’échec d’un `rsync`, le script :

1. écrit l’erreur dans le log ;
2. tente un envoi de mail ;
3. crée le flag :
   - `/volume1/Web/logs/sync_affaires.FAIL`

---

## 5. Connexion du NAS vers le PC fixe

Le script cible le PC fixe au moyen des paramètres suivants :

```sh
PC_HOST="10.0.1.10"
PC_PORT="2222"
PC_USER="sshsync"
SSH_KEY="/volume1/home/nicolas/.ssh/id_ed25519"
```

### Fichiers SSH impliqués

- clé privée :
  - `/volume1/home/nicolas/.ssh/id_ed25519`
- known hosts :
  - `/volume1/home/nicolas/.ssh/known_hosts`

### Options SSH utilisées

Le script impose notamment :

- `BatchMode=yes`
- `PasswordAuthentication=no`
- `KbdInteractiveAuthentication=no`
- `StrictHostKeyChecking=accept-new`

Il s’agit donc d’une synchronisation **non interactive**, conçue pour l’automatisation.

---

## 6. Racines synchronisées

### Côté NAS

La racine source/destination NAS est :

```text
/volume1/Affaires/
```

### Côté PC fixe

La racine vue à travers `rsync` côté Windows est :

```text
/c/Affaires/
```

Le binaire `rsync` distant explicitement appelé sur Windows est :

```text
C:\msys64\usr\bin\rsync.exe
```

Ce point est essentiel : le PC fixe expose son disque `C:` au format de chemin MSYS/rsync, et non au format natif `C:\Affaires\...` dans la commande `rsync`.

---

## 7. Options rsync communes

Le script utilise :

```sh
COMMON_OPTS="--old-args -avz --info=progress2 --partial --update --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r"
```

### Effets attendus

- `-a` : mode archive ;
- `-v` : verbosité ;
- `-z` : compression ;
- `--partial` : conservation partielle en cas d’interruption ;
- `--update` : évite d’écraser un fichier plus récent en face ;
- `--chmod=...` : normalisation des droits.

Le paramètre `--update` est particulièrement important : il réduit le risque d’écrasement d’un fichier plus récent, mais ne remplace pas une vraie gestion transactionnelle.

---

## 8. Logique réelle de synchronisation : deux flux asymétriques

Le dispositif n’est pas une copie miroir totale. Il s’agit de **deux synchronisations distinctes**, avec **deux jeux de filtres différents**.

### 8.1. Flux 1 — NAS vers PC fixe

Le flux 1 est noté dans le script :

```text
NAS → PC (type A)
```

Il utilise le filtre :

```text
$RUN_TMP/rsync_filter_A.rules
```

### Règles du filtre A

```text
+ */
+ **/BE_*/
+ **/BE_*/**
+ **/[0-9][0-9]_*/
+ **/[0-9][0-9]_*/**
- **/_DB/***
- **/_Config/***
- **/[A-Z][A-Z]_*/***
- **
```

### Interprétation

Ce flux pousse vers le PC fixe :

- les répertoires intermédiaires ;
- les dossiers `BE_*` ;
- les sous-dossiers de type **numérique** : `00_*`, `01_*`, `02_*`, etc. ;
- tout leur contenu.

Sont exclus :

- `_DB`
- `_Config`
- les dossiers de type **alphabétique** `AA_*`, `AB_*`, etc.

### Lecture fonctionnelle

Le NAS alimente donc le PC fixe avec les zones de travail de type **numérique** et les dossiers `BE_*`.

---

### 8.2. Flux 2 — PC fixe vers NAS

Le flux 2 est noté dans le script :

```text
PC → NAS (type B)
```

Il utilise le filtre :

```text
$RUN_TMP/rsync_filter_B.rules
```

### Règles du filtre B

```text
+ */
+ **/BE_*/
+ **/BE_*/**
+ **/[A-Z][A-Z]_*/
+ **/[A-Z][A-Z]_*/**
- **/_DB/***
- **/_Config/***
- **/[0-9][0-9]_*/***
- **
```

### Interprétation

Ce flux remonte du PC fixe vers le NAS :

- les répertoires intermédiaires ;
- les dossiers `BE_*` ;
- les sous-dossiers de type **alphabétique** : `AA_*`, `AB_*`, etc. ;
- tout leur contenu.

Sont exclus :

- `_DB`
- `_Config`
- les dossiers de type **numérique** `00_*`, `01_*`, etc.

### Lecture fonctionnelle

Le PC fixe remonte donc vers le NAS les zones de travail de type **alphabétique**, en plus des dossiers `BE_*`.

---

## 9. Structure logique à retenir

Le mécanisme est donc volontairement dissymétrique :

- **NAS → PC** : dossiers `BE_*` + dossiers `NN_*` ;
- **PC → NAS** : dossiers `BE_*` + dossiers `AA_*`.

Autrement dit :

- les dossiers **numériques** sont considérés comme alimentés depuis le NAS ;
- les dossiers **alphabétiques** sont considérés comme remontés depuis le PC fixe ;
- les dossiers **`BE_*`** sont échangés dans les deux sens ;
- `_DB` et `_Config` sont exclus des deux flux.

C’est un point de doctrine important pour Codex : il ne faut pas transformer cela en miroir global sans revoir toute la logique métier.

---

## 10. Répertoires explicitement exclus

Les exclusions communes sont :

```text
**/_DB/***
**/_Config/***
```

### Conséquence

Les zones `_DB` et `_Config` présentes sous `/volume1/Affaires/` ne doivent pas être supposées synchronisées par ce mécanisme.

Si un traitement dépend de leur contenu côté PC fixe ou côté NAS, il faut le vérifier séparément.

---

## 11. Répertoires temporaires utilisés par le script

Le script crée un répertoire temporaire d’exécution :

```text
/volume1/Web/tmp/sync_affaires.<pid>.<timestamp>
```

Il y écrit notamment :

- `rsync_filter_A.rules`
- `rsync_filter_B.rules`
- des fichiers temporaires SMTP

Ce répertoire est supprimé à la fin via `trap`.

---

## 12. Fichiers métier impactés par la synchronisation

Au niveau de l’application, la synchronisation touche indirectement tous les fichiers d’affaires contenus sous les branches synchronisées.

Les plus sensibles, au vu du projet, sont notamment :

### 12.1. Fichiers de contexte et de pilotage

- `infos_projet.json` ;
- `contexte_general_photos.json` ;
- `config_llm.json` ;
- `proper_names.txt`.

Le fichier `infos_projet.json` contient les chemins de travail du projet, y compris côté PC fixe (`fichier_transcription`, `fichier_photos`, `fichier_audio`, `fichier_contexte_general`, `config_llm`, `out_dir`, etc.). fileciteturn93file17

### 12.2. Fichiers photo

- CSV principal des photos ;
- `photos_batch.csv` ;
- dossiers `photos/JPG/` et éventuels dérivés.

Le batch photo exploite explicitement des colonnes comme `photo_rel_native`, `chemin_photo_native_pcfixe`, `chemin_photo_reduite_pcfixe`, `date_copie_pcfixe`, `description_vlm_batch`, `libelle_propose_batch`, `commentaire_propose_batch`. fileciteturn93file4

### 12.3. Fichiers ASR / transcription

- transcription CSV ;
- dossiers `asr_in/` et `asr_out/` ;
- audio source ;
- audio compatible.

L’application reconstruit ces chemins à partir de l’arborescence affaire/captation. fileciteturn94file13

---

## 13. Arborescence métier concernée

Les chemins visibles dans `infos_projet.json` montrent que l’arborescence métier côté PC fixe est au moins de la forme :

```text
C:\Affaires\<id_affaire>\AF_Expert_ASR\transcriptions\<id_captation>\...
C:\Affaires\<id_affaire>\AE_Expert_captations\<id_captation>\...
```

Exemple observé :

- `C:\Affaires\2025-J37\AF_Expert_ASR\transcriptions\accedit-2025-09-02\...`
- `C:\Affaires\2025-J37\AE_Expert_captations\accedit-2025-09-02\...` fileciteturn93file17

Codex doit considérer que la synchronisation rsync alimente ou remonte des sous-répertoires de cette arborescence selon la logique des filtres A/B.

---

## 14. Fichiers applicatifs à connaître pour ne pas casser la synchronisation

### `selection_fichiers_interface.py`

Ce fichier construit des chemins relatifs stables de photos, notamment via `photo_rel_native`, selon une convention structurée par affaire/captation. fileciteturn93file7

### `main.py`

Le fichier attend des colonnes batch synchronisées côté UI, notamment pour la description VLM, le libellé, le commentaire et les statuts batch. fileciteturn93file14

### `batch_all_photos_pcfixe.py`

Ce script dépend fortement des chemins côté PC fixe et des CSV synchronisés. Il révèle aussi le rôle de `photos_batch.csv`. fileciteturn94file14

### `annotation_interface_gpt.py`

Ce fichier reconstruit les sous-répertoires `asr_in` et `asr_out` à partir de l’arborescence métier. fileciteturn94file13

### `gpt4all_flask.py`

Le serveur travaille avec `C:\Affaires` comme racine logique locale de référence. fileciteturn94file18turn93file12

---

## 15. Points d’attention pour Codex

### 15.1. Ne pas modifier la logique A/B sans précaution

Le système actuel ne copie pas tout dans les deux sens. Toute modification des filtres :

- peut casser les conventions de propriété implicite des dossiers ;
- peut provoquer des recouvrements inattendus ;
- peut faire remonter des répertoires exclus jusque-là (`_DB`, `_Config`).

### 15.2. Ne pas changer les racines sans revoir les chemins métier

Les traitements applicatifs supposent la racine locale :

```text
C:\Affaires
```

et, côté `rsync`, la racine distante :

```text
/c/Affaires/
```

### 15.3. Conserver la logique `ssh + rsync.exe` côté Windows

Le script suppose explicitement la présence de :

```text
C:\msys64\usr\bin\rsync.exe
```

Un changement de localisation, de shell Windows ou d’environnement MSYS invaliderait la synchronisation.

### 15.4. Respecter les fichiers d’état et de log

Les fichiers suivants ont un rôle opérationnel :

- `/volume1/Web/logs/sync_affaires.log`
- `/volume1/Web/logs/sync_affaires.YYYY-MM.log`
- `/volume1/Web/logs/sync_affaires.FAIL`

---

## 16. Résumé exécutable

### Déclenchement

- `crontab` NAS, toutes les 2 heures à H:10.

### Script

- `/volume1/Web/Pilote_Affaires/scripts/sync_affaires.sh`

### Sens 1

- NAS → PC
- source : `/volume1/Affaires/`
- destination : `sshsync@10.0.1.10:/c/Affaires/`
- contenu : `BE_*` + `NN_*`

### Sens 2

- PC → NAS
- source : `sshsync@10.0.1.10:/c/Affaires/`
- destination : `/volume1/Affaires/`
- contenu : `BE_*` + `AA_*`

### Exclus dans les deux sens

- `_DB`
- `_Config`

### Verrou

- `/var/lock/sync_affaires.lock`

### Logs

- `/volume1/Web/logs/sync_affaires.log`
- `/volume1/Web/logs/sync_affaires.YYYY-MM.log`
- `/volume1/Web/logs/sync_affaires.FAIL`

### Dépendances sensibles

- clé SSH : `/volume1/home/nicolas/.ssh/id_ed25519`
- known hosts : `/volume1/home/nicolas/.ssh/known_hosts`
- SMTP éventuel : `/volume1/Web/secrets/smtp_lws.env`
- rsync distant Windows : `C:\msys64\usr\bin\rsync.exe`

---

## 17. Conclusion pour Codex

Le mécanisme en place est un **pilotage NAS**, non un miroir bidirectionnel pur. Il repose sur une distinction métier implicite entre :

- dossiers `NN_*` poussés du NAS vers le PC ;
- dossiers `AA_*` remontés du PC vers le NAS ;
- dossiers `BE_*` échangés dans les deux sens.

Les fichiers d’affaires synchronisés alimentent directement les composants applicatifs de traitement photo, ASR et interface, notamment via `infos_projet.json`, les CSV photo, `photos_batch.csv`, les transcriptions et les répertoires `asr_in/asr_out`. fileciteturn93file17turn93file4turn94file13


## Schéma simplifié

NAS (/volume1/Affaires)
   ├── NN_*  ───────────────► PC fixe (/c/Affaires)
   ├── BE_*  ◄──────────────► PC fixe
   └── AA_*  ◄────────────── PC fixe

Exclus :
- _DB
- _Config


## Statut des répertoires `_DB` et `_Config`

Actuellement, les répertoires suivants sont exclus de la synchronisation en place :

- `_DB`
- `_Config`

### Situation actuelle

Ils ne sont donc pas synchronisés entre le NAS et le PC fixe par le mécanisme rsync actuel.

### Cible d’évolution

Le cahier des charges prévoit leur intégration future dans la synchronisation, a priori en mode bidirectionnel.

### Conséquences

À ce stade :

- leur contenu peut diverger selon les environnements ;
- ils ne doivent pas être supposés cohérents entre NAS et PC fixe ;
- toute logique applicative dépendant de ces dossiers doit être analysée avec prudence.

### Point d’attention

L’intégration de `_DB` et `_Config` dans une synchronisation bidirectionnelle nécessitera un cadrage explicite, notamment sur :

- la stratégie de conflit ;
- la priorité en cas de divergence ;
- la sensibilité différente des fichiers de configuration et des données dynamiques ;
- les risques d’écrasement silencieux.

⚠️ Il s’agit d’un point d’amélioration indispensable, mais non encore réalisé dans le dispositif actuel.
