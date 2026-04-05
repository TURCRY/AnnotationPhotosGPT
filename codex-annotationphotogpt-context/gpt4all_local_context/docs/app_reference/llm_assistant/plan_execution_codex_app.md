# Plan d’exécution Codex — évolution de `app.py`, `n8n` et `tools/sync`

## 1. Objet

Ce document complète `cahier_charges_app.md`.

Il a pour finalité de donner à Codex un **plan d’action opérationnel**, séquencé et directement exploitable, pour faire évoluer :

- `app.py` ;
- les scripts du dossier `C:\LLM_Assistant\tools\sync` ;
- leur articulation avec les workflows `n8n`.

La logique cible demeure :

- **n8n déclenche** ;
- les scripts Python **exécutent** ;
- `app.py` **contrôle, supervise et relance**.

---

## 2. Résultat attendu à l’issue du chantier

À l’issue du chantier, le système devra permettre :

1. de lancer les traitements automatiques hors laptop, via `n8n` ;
2. de normaliser tous les scripts `tools/sync` ;
3. de suivre chaque exécution par affaire ;
4. de contrôler les workflows depuis `app.py` ;
5. de diagnostiquer rapidement les erreurs ;
6. de relancer une étape de façon ciblée.

---

## 3. Ordre impératif des travaux

## Phase 1 — Audit technique et cartographie réelle

### Objectif
Établir l’état réel avant refactorisation.

### Tâches
- inventorier les appels actuels entre :
  - `app.py`,
  - serveur Flask,
  - `n8n`,
  - scripts `tools/sync` ;
- identifier quels scripts sont déjà appelés :
  - depuis `app.py`,
  - depuis une route HTTP,
  - depuis `n8n`,
  - manuellement ;
- documenter, pour chaque script :
  - arguments d’entrée ;
  - fichiers lus ;
  - fichiers écrits ;
  - dépendances externes ;
  - effets de bord ;
  - format de sortie ;
  - conditions d’échec ;
- relever les déclencheurs déjà en place dans `n8n` ;
- distinguer les traitements :
  - réellement batch,
  - réellement interactifs,
  - encore mal répartis.

### Livrables
- `audit_tools_sync.md`
- `cartographie_workflows_n8n.md`

### Critère de sortie
Aucune refactorisation ne commence avant cartographie explicite des flux réels.

---

## Phase 2 — Définition du contrat d’exécution commun

### Objectif
Imposer une interface homogène à tous les scripts `tools/sync`.

### Tâches
- définir un contrat unique pour tous les scripts :
  - arguments CLI ;
  - code de retour ;
  - JSON de sortie ;
  - format de logs ;
- figer les statuts autorisés :
  - `queued`
  - `running`
  - `success`
  - `warning`
  - `error`
  - `partial`
  - `cancelled`
- définir un identifiant unique d’exécution `run_id` ;
- définir les champs obligatoires du JSON de retour.

### JSON cible minimal
```json
{
  "status": "success|warning|error",
  "script": "create_affaire.py",
  "run_id": "uuid-ou-horodatage",
  "affaire_id": "2025-J38",
  "message": "résumé",
  "data": {},
  "artifacts": [],
  "warnings": [],
  "errors": []
}
```

### Livrable
- `workflow_contract.md`

### Critère de sortie
Le contrat doit être applicable à tous les scripts sans exception.

---

## Phase 3 — Création d’un socle commun Python

### Objectif
Éviter la duplication et rendre les scripts réutilisables.

### Tâches
Créer un module commun, par exemple :

- `sync_core.py`
ou
- `workflow_runtime.py`

Y centraliser :
- résolution des chemins ;
- lecture de configuration ;
- génération de `run_id` ;
- écriture des logs ;
- construction du JSON de sortie ;
- gestion normalisée des exceptions ;
- helpers CSV ;
- helpers fichiers ;
- helpers vérification des artefacts.

### Livrables
- module commun Python ;
- note de conventions de développement.

### Critère de sortie
Tout nouveau script doit utiliser ce socle.

---

## Phase 4 — Refactorisation script par script

### Objectif
Rendre chaque script appelable proprement par `n8n` et contrôlable par `app.py`.

## 4.1 `create_affaire.py`
### À vérifier
- création d’arborescence ;
- nommage ;
- contrôles d’existence ;
- idempotence ;
- sortie des chemins créés.

### À produire
- arguments CLI explicites ;
- JSON final ;
- liste des dossiers créés ;
- erreurs claires si affaire déjà existante ou structure incomplète.

## 4.2 `write_infos_projet.py`
### À vérifier
- source des métadonnées ;
- format d’écriture ;
- collisions éventuelles ;
- validation des champs.

### À produire
- validation en entrée ;
- sortie structurée des fichiers modifiés ;
- warning si mise à jour partielle.

## 4.3 `sync_activate.py`
### À vérifier
- règles de synchronisation ;
- exclusions ;
- chemins laptop / NAS ;
- dépendances réseau.

### À produire
- contrôle préalable des chemins ;
- journal détaillé des exclusions et activations ;
- distinction entre :
  - succès complet,
  - succès partiel,
  - échec.

## 4.4 `paperless_check.py`
### À vérifier
- mode de contrôle de dépôt ;
- conditions de succès ;
- preuves de traitement ;
- gestion des manquants.

### À produire
- compte rendu structuré ;
- liste des documents détectés / absents ;
- statut exploitable par `app.py`.

## 4.5 `select_photos_csv.py`
### À vérifier
- format CSV attendu ;
- robustesse si colonnes manquantes ;
- règles de sélection.

### À produire
- validation stricte ;
- messages d’erreur compréhensibles ;
- artefacts explicitement listés.

## 4.6 `mk_photos_batch_min.py`
### À vérifier
- logique batch ;
- volumétrie ;
- dépendances fichiers ;
- nommage des sorties.

### À produire
- mode dry-run ;
- sortie JSON ;
- comptage entrée / sortie ;
- warning en cas de traitement partiel.

## 4.7 `pick_ui_csv.py`
### À vérifier
- rôle précis dans la chaîne ;
- dépendance éventuelle à une interaction locale ;
- possibilité de conversion en tâche n8n-compatible.

### À produire
- si interaction indispensable : isoler le composant ;
- sinon : rendre le script complètement batchable.

## 4.8 `seed_captation.py`
### À vérifier
- point de départ de la captation ;
- dépendances audio ;
- structure des fichiers produits ;
- interaction éventuelle avec d’autres modules.

### À produire
- contrat d’entrée clair ;
- vérification des fichiers attendus ;
- retour JSON complet.

### Livrable
- série de scripts refactorisés et homogènes.

### Critère de sortie
Chaque script doit être testable seul, sans interface graphique.

---

## Phase 5 — Définition des workflows `n8n`

### Objectif
Déporter les traitements automatiques hors laptop.

### Tâches
Créer ou revoir des workflows `n8n` par famille de déclencheurs.

## 5.1 Workflows sur dépôt de fichiers
Déclenchement sur apparition d’un fichier dans :
- dossier inbox ;
- dossier photos ;
- dossier CSV ;
- dossier captation ;
- dossier d’attente Paperless.

## 5.2 Workflows sur événement métier
Déclenchement après :
- création d’affaire ;
- activation sync ;
- mise à jour d’infos projet.

## 5.3 Workflows périodiques
Déclenchement planifié pour :
- contrôles de cohérence ;
- détection des blocages ;
- surveillance des dossiers incomplets ;
- contrôles Paperless.

## 5.4 Workflows de reprise
Déclenchement si :
- erreur script ;
- timeout ;
- artefact manquant ;
- état incohérent.

### Exigences
Chaque workflow doit :
- recevoir des paramètres explicites ;
- produire un `run_id` ;
- enregistrer un statut final ;
- conserver les erreurs techniques utiles.

### Livrables
- `n8n_workflows_spec.md`
- `n8n_triggers_matrix.md`

### Critère de sortie
Chaque automatisation cible doit être associée à un workflow identifié.

---

## Phase 6 — Couche de supervision dans `app.py`

### Objectif
Faire de `app.py` un tableau de bord de contrôle des workflows.

### Tâches
Créer dans `app.py` une interface de supervision avec, par affaire :

- nom du workflow ;
- statut ;
- date/heure ;
- source du déclenchement ;
- durée ;
- run_id ;
- message résumé ;
- accès aux détails.

Prévoir des fonctions de contrôle :
- vérifier qu’un workflow a bien démarré ;
- vérifier qu’il cible la bonne affaire ;
- vérifier les fichiers attendus ;
- afficher warnings et erreurs ;
- relancer une étape autorisée.

Prévoir des filtres :
- par affaire ;
- par type de workflow ;
- par statut ;
- par date.

### Livrable
- écran ou module de supervision intégré dans `app.py`.

### Critère de sortie
L’utilisateur doit pouvoir comprendre l’état d’une affaire sans ouvrir les logs bruts.

---

## Phase 7 — Mode manuel dégradé

### Objectif
Permettre une continuité minimale si `n8n` est indisponible.

### Tâches
- définir la liste limitée des scripts autorisés en mode local manuel ;
- interdire les exécutions locales dangereuses ou lourdes ;
- afficher dans `app.py` que le mode utilisé est :
  - normal distant ;
  - dégradé local ;
- journaliser toute exécution locale exceptionnelle.

### Critère de sortie
Le mode local doit rester exceptionnel et traçable.

---

## Phase 8 — Tests et validation

### Objectif
Sécuriser le fonctionnement avant généralisation.

### Tâches
Prévoir des tests sur plusieurs scénarios :

1. création d’affaire complète ;
2. activation sync ;
3. dépôt d’un fichier déclenchant un workflow ;
4. absence d’un artefact attendu ;
5. CSV invalide ;
6. dossier manquant ;
7. relance après erreur ;
8. indisponibilité temporaire de `n8n`.

### Livrables
- `test_plan_workflows.md`
- jeux d’essai minimaux ;
- grille de validation.

### Critère de sortie
Tous les scénarios critiques doivent être rejouables.

---

## 4. Priorités pratiques pour Codex

## Lot 1 — immédiat
- cartographier les scripts `tools/sync` ;
- documenter les appels existants ;
- définir le contrat commun ;
- créer le socle `sync_core.py`.

## Lot 2 — ensuite
- refactoriser `create_affaire.py`, `sync_activate.py`, `paperless_check.py` ;
- ce sont les scripts les plus structurants pour le pilotage d’affaire.

## Lot 3 — ensuite
- refactoriser les scripts CSV / photos / captation ;
- formaliser les workflows `n8n`.

## Lot 4 — ensuite
- intégrer la supervision dans `app.py` ;
- ajouter la relance ciblée.

## Lot 5 — enfin
- tests croisés ;
- mode dégradé ;
- documentation finale.

---

## 5. Règles de développement à imposer à Codex

Codex devra respecter les règles suivantes :

- ne pas introduire de chemins codés en dur hors configuration ;
- ne pas mélanger logique UI et logique batch ;
- ne pas créer de dépendance implicite entre scripts ;
- ne pas masquer les erreurs ;
- toujours produire un statut exploitable ;
- conserver la compatibilité Windows ;
- préserver la lisibilité juridique et métier des noms d’affaires ;
- documenter chaque hypothèse.

---

## 6. Définition de done

Une tâche ne sera considérée comme terminée que si :

- le code est exécutable ;
- le comportement est documenté ;
- les entrées / sorties sont explicites ;
- les erreurs sont testées ;
- `app.py` peut lire ou contrôler le résultat ;
- le traitement est compatible avec une exécution `n8n`.

---

## 7. Conclusion

L’objectif n’est pas seulement de refactoriser quelques scripts.

L’objectif est de faire évoluer l’ensemble du pipeline vers une architecture plus robuste :

- **laptop = poste de pilotage** ;
- **n8n = orchestrateur des automatisations** ;
- **scripts Python = briques unitaires standardisées** ;
- **`app.py` = interface de supervision, contrôle et relance**.
