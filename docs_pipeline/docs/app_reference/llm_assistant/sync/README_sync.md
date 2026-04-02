# sync — références de scripts à auditer

Ce dossier contient des scripts Python liés à la création d’affaire, à la préparation de traitements et à la synchronisation.

## Statut

Ces scripts sont fournis à Codex comme **références de travail** dans le cadre du chantier de standardisation des workflows `n8n`.

Ils ne doivent pas être considérés d’emblée comme :
- homogènes ;
- testés ;
- prêts pour la production ;
- déjà alignés sur un contrat CLI/JSON commun.

## Rôle attendu de Codex

Pour chaque script, Codex doit distinguer :
- s’il est réellement utilisé en production ;
- s’il s’agit d’un utilitaire ponctuel ;
- s’il crée des dossiers ;
- s’il écrit des métadonnées projet ;
- s’il active ou contrôle une synchronisation ;
- s’il est compatible avec une exécution batch/n8n.

## Scripts présents

- `create_affaire.py` : création d’affaire / arborescence
- `mk_photos_batch_min.py` : préparation batch photo minimale
- `paperless_check.py` : contrôle lié à Paperless
- `pick_ui_csv.py` : sélection / préparation CSV
- `seed_captation.py` : préparation captation
- `select_photos_csv.py` : sélection photo depuis CSV
- `sync_activate.py` : activation / contrôle de synchronisation
- `write_infos_projet.py` : écriture d’informations projet

## Important

Ces scripts doivent être interprétés à la lumière de :
- `cahier_charges_app.md`
- `plan_execution_codex_app.md`

Leur présence dans ce dossier n’implique pas qu’ils soient déjà validés ou intégrés dans un workflow `n8n` en production.