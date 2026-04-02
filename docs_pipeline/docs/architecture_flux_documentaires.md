## architecture_flux_documentaires.md




| Flux | Source      | Nature        | Outil amont         | Outil aval  | Source de vérité | Cible sync    | Statut    |
| ---- | ----------- | ------------- | ------------------- | ----------- | ---------------- | ------------- | --------- |
| 1    | Laptop      | PDF parties   | app.py              | rsync/n8n   | NAS              | NAS + PC fixe | à faire   |
| 2    | Laptop      | audio/photos  | scripts + Syncthing | rsync       | NAS              | NAS + PC fixe | partiel   |
| 3    | Laptop      | pièces expert | app / outils métier | rsync       | NAS              | NAS + PC fixe | à faire   |
| 4    | Laptop/NAS  | SQLite/config | n8n/app             | rsync       | à définir        | NAS + PC fixe | à faire   |
| 5    | PC fixe/NAS | vector DB     | backend             | sync dédiée | à définir        | 3 machines ?  | à définir |



### Flux 1 — pièces des parties

* source : laptop via `LLM_Assistant/app.py`
* nature : surtout PDF à ingérer
* cible : NAS puis PC fixe
* état : pas encore synchronisé
* cible technique :

  * laptop ↔ NAS : **Syncthing** à construire
  * NAS ↔ PC fixe : **rsync** existant, à revisiter

### Flux 2 — gros fichiers de captation / photos / audio

* source : laptop
* nature : fichiers lourds
* état actuel :

  * **laptop → NAS déjà construit**
  * via **robocopy**, pas Syncthing
* ensuite :

  * NAS ↔ PC fixe via **rsync**
* état cible :

  * revoir la chaîne **robocopy + rsync**
* point clé :

  * ce flux existe déjà partiellement, mais avec une logique spécifique

### Flux 3 — pièces produites par l’expert sur le laptop

* source : laptop
* nature : documents expert
* cible : NAS + PC fixe
* état : à construire
* cible technique :

  * laptop ↔ NAS : **Syncthing**
  * NAS ↔ PC fixe : **rsync** à revisiter

### Flux 4 — données structurées projet

* source : laptop ou NAS via `app.py` / `n8n`
* nature : `_DB`, `_Config`, SQLite, métadonnées projet
* cible : **les 3 machines**
* état : à construire
* cible technique :

  * laptop ↔ NAS : **Syncthing**
  * NAS ↔ PC fixe : **rsync** à revisiter
* point clé :

  * flux très sensible, surtout pour `_DB`


## Flux 5 — Données projet non répliquées sur le laptop

Ce flux concerne les données techniques du projet qui :

- ne sont pas destinées à être stockées localement sur le laptop ;
- sont produites et exploitées principalement sur le NAS et le PC fixe.

### Nature

- bases vectorielles (Chroma, Qdrant)
- index
- caches
- données dérivées

Ces données sont situées dans des répertoires non `NN_*`.

### Synchronisation

- synchronisation uniquement entre :
  - NAS
  - PC fixe

- mécanisme :
  - `rsync` (à revisiter)

### Accès côté laptop

Le laptop n’accède pas à ces données par synchronisation locale.

Il y accède :

- en lecture directe via le NAS ;
- ou via des mécanismes de type manifest.

### Conséquence

Le laptop ne doit pas être considéré comme :

- une copie complète des données projet ;
- ni comme une cible de synchronisation pour ces éléments.

### Point d’attention

Toute tentative de synchronisation de ces données vers le laptop :

- augmenterait fortement le volume de données ;
- introduirait des risques de cohérence ;
- n’est pas prévue dans l’architecture cible.



### 1. Construire le flux **Syncthing** laptop ↔ NAS

Pour les flux :

* 1
* 3
* 4

### 2. Revoir les procédures **robocopy**

Pour le flux :

* 2

### 3. Revoir les procédures **rsync**

Pour les flux :

* 1
* 2
* 3
* 4
* 5

## Point important

Votre architecture n’est pas “une synchronisation générale”, mais un ensemble de **politiques de propagation différentes selon le type de pièce**.

C’est cela qu’il faut faire apparaître dans la documentation.

## Ce que je vous recommande

Créer maintenant un document unique, par exemple :

`docs/architecture_flux_documentaires.md`

avec pour chaque flux :

* source
* nature
* destinations
* outil actuel
* outil cible
* état actuel
* points de vigilance

Et ajouter dans `taches_codex.md` une tâche dédiée du type :

### Tâche — cartographie et stratégie des flux documentaires inter-machines

Objectif :

* formaliser les 5 flux
* distinguer `Syncthing`, `robocopy`, `rsync`
* préciser ce qui existe, ce qui doit être construit, ce qui doit être revisité

## Flux 5 — Données projet non répliquées sur le laptop

Ce flux concerne les données techniques du projet qui :

- ne sont pas destinées à être stockées localement sur le laptop ;
- sont produites et exploitées principalement sur le NAS et le PC fixe.

### Nature

- bases vectorielles (Chroma, Qdrant)
- index
- caches
- données dérivées

Ces données sont situées dans des répertoires non `NN_*`.

### Synchronisation

- synchronisation uniquement entre :
  - NAS
  - PC fixe

- mécanisme :
  - `rsync` (à revisiter)

### Accès côté laptop

Le laptop n’accède pas à ces données par synchronisation locale.

Il y accède :

- en lecture directe via le NAS ;
- ou via des mécanismes de type manifest.

### Conséquence

Le laptop ne doit pas être considéré comme :

- une copie complète des données projet ;
- ni comme une cible de synchronisation pour ces éléments.

### Point d’attention

Toute tentative de synchronisation de ces données vers le laptop :

- augmenterait fortement le volume de données ;
- introduirait des risques de cohérence ;
- n’est pas prévue dans l’architecture cible.


# 📄 Architecture des flux documentaires inter-machines

## 1. Objet

Ce document décrit les flux documentaires entre :

* Laptop (poste expert)
* NAS (stockage central)
* PC fixe (traitement)

Il distingue les flux selon :

* leur nature
* leur sens
* leur mécanisme technique
* leur état (actuel / cible)

---

## 2. Tableau des flux

| Flux | Nature                                       | Source          | Destinations             | Laptop impliqué         | Mécanisme amont          | Mécanisme aval   | Sens                           | Statut           |
| ---- | -------------------------------------------- | --------------- | ------------------------ | ----------------------- | ------------------------ | ---------------- | ------------------------------ | ---------------- |
| 1    | Pièces des parties (PDF, ingestion)          | Laptop (app.py) | NAS → PC fixe            | Oui                     | Syncthing (à construire) | rsync (à revoir) | Bidirectionnel cible           | ❌ Non implémenté |
| 2    | Gros fichiers (photos, audio)                | Laptop          | NAS → PC fixe            | Oui (source uniquement) | robocopy                 | rsync (existant) | Unidirectionnel (Laptop → NAS) | ⚠️ Partiel       |
| 3    | Pièces expert                                | Laptop          | NAS → PC fixe            | Oui                     | Syncthing (à construire) | rsync (à revoir) | Bidirectionnel cible           | ❌ Non implémenté |
| 4    | Données projet (_DB, _Config, SQLite)        | Laptop / NAS    | NAS ↔ PC fixe (+ laptop) | Oui                     | Syncthing (à construire) | rsync (à revoir) | Bidirectionnel cible           | ❌ Non implémenté |
| 5    | Données techniques projet (vector DB, index) | NAS / PC fixe   | NAS ↔ PC fixe            | Non (lecture indirecte) | —                        | rsync (à revoir) | Bidirectionnel                 | ⚠️ À formaliser  |

---

## 3. Lecture synthétique

### 3.1 Trois mécanismes distincts

#### 1. Déport de fichiers lourds

* outil : `robocopy`
* flux : 2
* sens : Laptop → NAS uniquement
* objectif : libérer le laptop

---

#### 2. Synchronisation bidirectionnelle (cible)

* outil : `Syncthing`
* flux : 1, 3, 4
* sens : Laptop ↔ NAS
* objectif : cohérence documentaire

---

#### 3. Synchronisation NAS ↔ PC fixe

* outil : `rsync` (`sync_affaires.sh`)
* flux : 1 à 5
* sens : bidirectionnel asymétrique
* objectif : alimenter les traitements

---

## 4. Rôle du laptop

Le laptop est :

* un poste de pilotage
* un poste de production
* un point d’entrée des données

Mais :

* ce n’est pas un stockage principal
* certaines données ne doivent pas y être répliquées (flux 5)

---

## 5. Points critiques

* distinction stricte :

  * synchronisation vs déport
* non-confusion :

  * Syncthing ≠ robocopy ≠ rsync
* cohérence des chemins (NAS / PC fixe)
* absence actuelle de Syncthing (flux 1, 3, 4)
* rsync à revisiter pour tous les flux

---

## 6. Priorités techniques

### P1 — Construire Syncthing

* flux 1, 3, 4
* synchronisation laptop ↔ NAS

### P2 — Revoir rsync

* adapter aux 5 flux
* intégrer futurs besoins (_DB, vector DB)

### P3 — Fiabiliser robocopy

* garantir complétude
* journaliser
* éviter duplications

---

## 7. Principe directeur

→ **tous les flux ne sont pas des synchronisations**

→ **certains sont des transferts unidirectionnels**

→ **le NAS est le pivot central**

→ **le laptop reste un client et un point d’entrée, pas un stockage global**

---
