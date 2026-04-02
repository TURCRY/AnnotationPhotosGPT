# Cahier des charges — évolution de `app.py` et des workflows `tools/sync`

## 1. Objet

Le présent document définit les tâches à confier à Codex pour faire évoluer :

- `app.py`, client **Streamlit** exécuté sur le laptop ;
- les scripts Python du répertoire `C:\LLM_Assistant\tools\sync` ;
- leur intégration dans des **workflows n8n** afin de déporter du laptop les traitements batch et les automatisations.

Le principe cible est le suivant :

- le **laptop** conserve un rôle de **pilotage, contrôle, visualisation et relance** ;
- les **traitements automatisés** sont exécutés prioritairement via **n8n** ;
- `app.py` doit permettre de **suivre le bon déroulement** des workflows, d’en lire les états, d’identifier les erreurs et, selon les cas, de lancer une relance contrôlée.

---

## 2. Contexte d’architecture

La documentation projet décrit déjà :

- `app.py` comme client Streamlit côté laptop ;
- un serveur Flask exposant des routes JSON ;
- `n8n` comme consommateur de routes HTTP du serveur pour automatiser des traitements. fileciteturn0file0 fileciteturn0file15 fileciteturn0file17

En conséquence, le cahier des charges doit reposer sur une séparation plus nette :

### 2.1 Rôle de `app.py`
`app.py` ne doit pas être le lieu principal d’exécution des traitements lourds ou des automatisations répétitives.  
Son rôle doit être :

- préparer les paramètres métier ;
- déclencher, quand nécessaire, un workflow distant ;
- afficher les états d’avancement ;
- contrôler la conformité du résultat ;
- proposer une relance ou une reprise ciblée.

### 2.2 Rôle de n8n
`n8n` doit devenir l’orchestrateur principal des tâches de fond, notamment lorsqu’un déclencheur objectif existe :

- dépôt de fichier ;
- arrivée d’un CSV ;
- création d’une affaire ;
- alimentation d’un répertoire surveillé ;
- contrôle périodique ;
- relance sur erreur.

### 2.3 Rôle des scripts `tools/sync`
Les scripts Python du dossier `tools/sync` doivent être considérés comme des **briques d’exécution unitaires**, appelables :

- soit par `n8n` ;
- soit exceptionnellement par `app.py` en mode manuel ou dépannage ;
- soit par un orchestrateur Python commun.

---

## 3. Scripts concernés

Répertoire : `C:\LLM_Assistant\tools\sync`

- `create_affaire.py`
- `mk_photos_batch_min.py`
- `paperless_check.py`
- `pick_ui_csv.py`
- `seed_captation.py`
- `select_photos_csv.py`
- `sync_activate.py`
- `write_infos_projet.py`

Ces scripts doivent être revus en tenant compte du fait qu’ils sont susceptibles d’être appelés par un workflow externe et non seulement par le laptop.

---

## 4. Problématiques à corriger

### 4.1 Mauvaise répartition des rôles
Le précédent cadrage donnait trop de poids à `app.py` dans l’orchestration opérationnelle.  
La cible doit être inverse :

- **n8n exécute** ;
- **app.py contrôle**.

### 4.2 Absence de contrat d’exécution homogène
Les scripts doivent exposer un comportement stable, exploitable par n8n et par l’interface :

- arguments explicites ;
- code de retour fiable ;
- sortie JSON ;
- logs lisibles ;
- statut final non ambigu.

### 4.3 Contrôle insuffisant depuis `app.py`
`app.py` doit pouvoir vérifier :

- qu’un workflow a bien démarré ;
- qu’il traite la bonne affaire ;
- qu’il a terminé sans erreur ;
- que les fichiers attendus existent ;
- que les exclusions de synchronisation sont respectées ;
- que les résultats ont été écrits dans les bons emplacements.

Dans `app.py`, la gestion de création d’affaire, de chemins et de règles de synchronisation est déjà sensible et structurante, notamment autour de `create_affaire` et de `sync_activate`. fileciteturn0file0

### 4.4 Faible traçabilité
Il faut pouvoir reconstituer, pour une affaire donnée :

- quel workflow a tourné ;
- quand ;
- avec quels paramètres ;
- sur quels fichiers ;
- avec quel résultat ;
- et quelle relance éventuelle a été effectuée.

---

## 5. Architecture cible

## 5.1 Principe général

### Pilotage métier
`app.py`

### Exécution automatisée
`n8n`

### Exécution unitaire
scripts Python (`tools/sync`)

### Services backend
serveur Flask + autres services du pipeline

Le serveur Flask est déjà conçu comme point d’entrée pour plusieurs clients, dont `LLM_Assistant` et `n8n`. fileciteturn0file11 fileciteturn0file15

## 5.2 Chaîne cible

1. un **événement** survient ;
2. **n8n** déclenche le workflow adapté ;
3. n8n appelle soit :
   - un script Python,
   - une route HTTP,
   - ou une combinaison des deux ;
4. le workflow produit :
   - logs,
   - statut,
   - artefacts,
   - éventuelles erreurs ;
5. `app.py` lit et contrôle ces informations ;
6. l’utilisateur peut :
   - constater le succès,
   - analyser l’erreur,
   - relancer une étape,
   - ou lancer une exécution manuelle contrôlée.

---

## 6. Déclencheurs n8n à prévoir ou à préciser

Les déclencheurs exacts devront être confirmés lors de l’audit, mais le cahier des charges doit prévoir au minimum les familles suivantes.

### 6.1 Dépôt de fichiers
Déclenchement lorsqu’un fichier apparaît dans un dossier surveillé, par exemple :

- dépôt initial ;
- inbox Paperless ;
- dossier photos ;
- dossier captation ;
- dossier CSV de préparation.

### 6.2 Création ou activation d’affaire
Déclenchement après :

- création d’une nouvelle affaire ;
- activation de la synchronisation ;
- écriture des métadonnées projet.

### 6.3 Contrôle périodique
Déclenchement planifié pour :

- vérifier les répertoires en attente ;
- détecter les traitements incomplets ;
- détecter les écarts entre laptop, NAS et dossiers projet ;
- vérifier les retours Paperless ou OCR.

### 6.4 Relance sur échec
Déclenchement conditionnel si :

- un script retourne une erreur ;
- un fichier attendu n’est pas produit ;
- un état bloqué persiste au-delà d’un délai défini.

---

## 7. Exigences fonctionnelles

## 7.1 Pour les scripts `tools/sync`

Chaque script doit :

- accepter des arguments CLI explicites ;
- pouvoir être lancé sans interface graphique ;
- retourner un JSON standard ;
- produire un code de retour non ambigu ;
- journaliser ses opérations ;
- pouvoir être appelé proprement depuis n8n.

### Format minimal du JSON
```json
{
  "status": "success|error|warning",
  "script": "nom_du_script",
  "affaire_id": "2025-J38",
  "message": "résumé court",
  "data": {},
  "artifacts": [],
  "warnings": [],
  "errors": []
}
```

## 7.2 Pour `app.py`

`app.py` doit offrir une fonction de **tour de contrôle**.

Fonctions attendues :

- voir les workflows disponibles ;
- déclencher manuellement un workflow autorisé ;
- afficher l’état du dernier passage ;
- afficher les erreurs et warnings ;
- vérifier la présence des artefacts attendus ;
- proposer une relance ciblée ;
- distinguer :
  - exécution locale,
  - exécution distante,
  - exécution n8n en attente,
  - exécution n8n terminée,
  - exécution n8n en erreur.

## 7.3 Pour n8n

Chaque workflow doit :

- recevoir des entrées structurées ;
- appeler des scripts ou routes avec paramètres explicites ;
- enregistrer un identifiant de run ;
- persister un état exploitable par `app.py` ;
- remonter les erreurs de manière lisible.

---

## 8. Exigences de contrôle dans `app.py`

`app.py` doit pouvoir contrôler les workflows sans nécessairement les exécuter lui-même.

### 8.1 Tableau de bord des workflows
Prévoir dans l’interface une vue listant, par affaire :

- workflow ;
- date/heure de lancement ;
- source du déclenchement ;
- statut ;
- durée ;
- résultat ;
- lien vers logs ou détails.

### 8.2 Vérifications de cohérence
Pour chaque workflow, `app.py` doit pouvoir tester :

- existence du dossier affaire ;
- existence des fichiers d’entrée ;
- conformité des chemins attendus ;
- existence des fichiers de sortie ;
- cohérence des exclusions de synchronisation ;
- cohérence Paperless / OCR / photos / captation selon le cas.

### 8.3 Journal de reprise
`app.py` doit garder une trace des relances manuelles :

- utilisateur ;
- date ;
- affaire ;
- workflow ;
- motif ;
- résultat.

---

## 9. Exigences techniques

## 9.1 Standardisation d’exécution
Créer un socle commun, par exemple :

- `sync_core.py`
- ou `workflow_runtime.py`

Ce socle doit centraliser :

- résolution des chemins ;
- logs ;
- lecture/écriture JSON ;
- gestion des erreurs ;
- code de retour ;
- identifiant d’exécution ;
- fonctions utilitaires CSV et fichiers.

## 9.2 Logs
Format minimal :

```text
[DATE][MODULE][LEVEL][RUN_ID] message
```

Les logs doivent être exploitables par :

- lecture humaine ;
- n8n ;
- `app.py`.

## 9.3 États normalisés
Définir un référentiel d’états :

- `queued`
- `running`
- `success`
- `warning`
- `error`
- `partial`
- `cancelled`

## 9.4 Mode dégradé
Si n8n est indisponible, `app.py` peut, pour certains traitements seulement, proposer un **mode manuel local** clairement identifié comme exceptionnel.

---

## 10. Répartition des responsabilités

### 10.1 Ce qui doit sortir du laptop
À orienter vers n8n en priorité :

- surveillance de dossiers ;
- déclenchements automatiques ;
- contrôles périodiques ;
- batch photos ;
- vérifications Paperless ;
- traitements répétitifs à faible valeur interactive.

### 10.2 Ce qui reste dans `app.py`
À conserver côté interface :

- création et lecture des paramètres métier ;
- validation humaine ;
- contrôle des workflows ;
- visualisation des résultats ;
- relance manuelle sélective ;
- diagnostic.

### 10.3 Ce qui doit rester neutre et réutilisable
Dans les scripts Python :

- logique unitaire ;
- transformation des fichiers ;
- contrôles techniques ;
- production des résultats.

---

## 11. Tâches à confier à Codex

## 11.1 Priorité haute
- [ ] Revoir le cahier des rôles entre `app.py`, n8n et `tools/sync`
- [ ] Standardiser tous les scripts en CLI + JSON + code retour
- [ ] Créer un module commun d’exécution
- [ ] Définir un format unique de logs
- [ ] Définir les états workflow lisibles par `app.py`
- [ ] Ajouter dans `app.py` une couche de contrôle des workflows
- [ ] Prévoir les déclencheurs n8n par type d’événement

## 11.2 Priorité moyenne
- [ ] Créer un écran de supervision dans `app.py`
- [ ] Ajouter un système de relance contrôlée
- [ ] Prévoir un mode dry-run
- [ ] Centraliser la configuration des chemins et dossiers surveillés

## 11.3 Priorité basse
- [ ] Historiser les exécutions par affaire
- [ ] Ajouter des métriques de durée et volumétrie
- [ ] Préparer une reprise partielle après erreur
- [ ] Étudier une file d’attente plus robuste si le volume augmente

---

## 12. Critères d’acceptation

Le chantier sera considéré comme satisfaisant si :

- les scripts peuvent être lancés proprement par n8n ;
- `app.py` peut contrôler l’état d’un workflow sans exécuter lui-même tout le traitement ;
- les erreurs sont visibles et exploitables ;
- les logs permettent un diagnostic rapide ;
- les déclencheurs sont documentés ;
- une relance ciblée est possible ;
- la charge opérationnelle du laptop diminue réellement.

---

## 13. Points à auditer explicitement par Codex

Codex devra documenter, script par script :

- les entrées ;
- les sorties ;
- les dépendances ;
- les chemins utilisés ;
- les effets de bord ;
- l’aptitude à être appelé par n8n ;
- les contrôles que `app.py` devra exposer.

Codex devra aussi cartographier :

- les déclencheurs réels déjà en place ;
- les déclencheurs manquants ;
- les étapes encore exécutées localement sur le laptop alors qu’elles devraient être déportées.

---

## 14. Conclusion opérationnelle

La cible n’est pas de faire de `app.py` un orchestrateur batch central.  
La cible est de faire de `app.py` une **interface de contrôle métier et technique**, tandis que **n8n** exécute les workflows automatisés et que les scripts Python deviennent des composants unitaires standardisés.

Autrement dit :

- `n8n` déclenche ;
- les scripts exécutent ;
- `app.py` surveille, contrôle et relance.
