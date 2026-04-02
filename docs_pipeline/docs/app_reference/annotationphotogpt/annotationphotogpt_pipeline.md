# AnnotationPhotoGPT — Pipeline applicatif

## 1. Objet de l’application

AnnotationPhotoGPT est une application destinée à l’annotation automatisée de photographies d’expertise judiciaire.

Elle permet, à partir :
- de photographies,
- d’une transcription audio horodatée,
- d’un contexte de mission,

de produire :
- un libellé court,
- un commentaire descriptif factuel,

dans un cadre strictement neutre (sans interprétation ni conclusion).

Les règles rédactionnelles sont imposées via des prompts structurés (cf. prompt_gpt.json)

---

## 2. Architecture générale

### 2.1 Vue d’ensemble

Pipeline en 4 couches :

1. **Entrées**
   - CSV photos
   - CSV transcription
   - audio source
   - contexte JSON
   - configuration projet (infos_projet.json) :contentReference[oaicite:1]{index=1}

2. **Prétraitement**
   - synchronisation temporelle audio/photo
   - conversion audio en WAV PCM (ffmpeg)
   - extraction segments audio

3. **Production IA**
   - VLM : description d’image
   - LLM : génération libellé + commentaire

4. **Sorties**
   - CSV enrichi
   - Excel annotations
   - export Word (optionnel)

---

## 3. Modules principaux

### 3.1 Interface principale

**main.py** :contentReference[oaicite:2]{index=2}

Orchestration Streamlit :
- sélection des fichiers
- synchronisation
- annotation

Sous-modules appelés :
- `selection_fichiers_interface.py`
- `synchronisation_interface.py`
- `annotation_interface_gpt.py`

---

### 3.2 Gestion des fichiers

**selection_fichiers_interface.py** :contentReference[oaicite:3]{index=3}

Fonctions :
- sélection CSV photos / transcription
- détection automatique audio
- validation identifiants (affaire / captation)
- normalisation chemins

Points importants :
- génération de `photo_rel_native`
- gestion environnement PC fixe (chemins UNC → local)

---

### 3.3 Composant audio interactif (WaveSurfer)

L’application utilise un composant frontend dédié basé sur WaveSurfer.js, intégré à Streamlit :

- Répertoire :
  `C:\WaveComponent\streamlit_wavesurfer\frontend\src`

- Fichiers principaux :
  - `index.tsx`
  - `MyComponent.tsx`
  - `vite-env.d.ts`

#### Rôle

Ce composant permet :
- la visualisation de la forme d’onde audio,
- la navigation temporelle précise,
- la synchronisation avec les photos,
- l’aide à la validation des annotations.

#### Intégration

- Composant intégré via `streamlit.components.v1`
- Utilisé dans :
  - synchronisation audio (`synchronisation_interface.py`)
  - annotation (`annotation_interface_gpt.py`)

#### Environnement technique

- Frontend : Vite + TypeScript
- Backend : Streamlit

#### Point critique

La synchronisation audio/photo dépend directement :
- de la précision du composant WaveSurfer,
- de la cohérence des horodatages.

Toute modification de ce composant peut impacter :
- la qualité de synchronisation,
- la pertinence des annotations.


### 3.4 Synchronisation audio / photos

- alignement temporel via horodatage
- extraction segments audio (utils.py) :contentReference[oaicite:4]{index=4}
- conversion audio (ffmpeg)

Fonctions clés :
- `extraire_audio`
- `convertir_horodatage_en_secondes`

---

### 3.5 Traitement audio

**traitement_audio.py** :contentReference[oaicite:5]{index=5}

Fonctions :
- conversion en WAV PCM
- gestion cache audio compatible
- vérification intégrité (hash partiel)

Objectif :
→ garantir compatibilité ASR et serveur audio

---

### 3.6 Client LLM local

**local_llm_client.py** :contentReference[oaicite:6]{index=6}

- communication HTTP avec serveur Flask (`/annoter`)
- gestion JSON / texte
- support des tâches :
  - libellé
  - commentaire

Paramètres clés :
- temperature
- max_tokens
- expect_json

---

### 3.7 Prompts LLM

- Mode interactif : `prompt_gpt.json` :contentReference[oaicite:7]{index=7}
- Mode batch : `prompt_gpt_batch_only.json` :contentReference[oaicite:8]{index=8}

Contraintes majeures :
- interdiction d’invention
- neutralité stricte
- ancrage aux données visibles

---

### 3.8 Batch PC fixe

**batch_all_photos_pcfixe.py** :contentReference[oaicite:9]{index=9}

Pipeline en 2 passes :

#### PASS 1 — VLM
- appel `/vision/describe_batch`
- production : `description_vlm_batch`

#### PASS 2 — LLM
- génération :
  - `libelle_propose_batch`
  - `commentaire_propose_batch`

Fonctionnalités :
- retry HTTP
- throttling
- traçabilité (batch_id, timestamps)
- gestion erreurs VLM / LLM

Structure CSV enrichi :
- colonnes batch_status, vlm_status, llm_err, etc.

---

### 3.9 RAG (optionnel)

**rag_vector_utils.py** :contentReference[oaicite:10]{index=10}

- stockage embeddings (Chroma / Qdrant)
- recherche contextuelle
- pseudonymisation possible

Usage :
→ enrichissement contextuel (non critique pour pipeline principal)

---


### 3.10 Génération du rapport Word

**generate_word_report.py** fabrique la partie du compte rendu concernant les annotations de photographies. :contentReference[oaicite:1]{index=1}

#### Rôle
Ce module produit un document Word final à partir d’un modèle `.docx`, en insérant :
- les commentaires de clichés,
- les images,
- les légendes de type `Cliché X - ...`,
- une table des clichés,
- les informations générales du dossier.

#### Sources de données
Le script utilise plusieurs sources :

1. **CSV photos UI**  
   - source de vérité pour la liste des photos ;
   - contient notamment les chemins, l’ordre des clichés, la colonne `retenue`.

2. **CSV GTP** (`*_GTP_*.csv`)  
   - utilisé en mode `GTP` ;
   - permet de récupérer `libelle`, `commentaire`, `annotation_validee`.

3. **CSV batch**  
   - utilisé si disponible ;
   - permet de récupérer `libelle_propose_batch`, `commentaire_propose_batch`, `batch_status`, `batch_ts`.

4. **infos_projet.json**  
   - fournit les chemins de travail, le contexte de mission, les identifiants d’affaire et de captation. :contentReference[oaicite:2]{index=2}

#### Logique de priorité des textes
Le script reconstitue deux champs finaux :
- `libelle_final`
- `commentaire_final`

avec la priorité suivante :

**GTP > UI > Batch**

Cette règle est importante car elle garantit que :
- la version validée ou consolidée par l’interface prime ;
- le batch ne sert que de repli si les champs UI ou GTP sont vides. :contentReference[oaicite:3]{index=3}

#### Modes de génération
Le script supporte deux modes via variable d’environnement :

- `REPORT_MODE=UI`
- `REPORT_MODE=GTP`

et un filtrage complémentaire :
- `REPORT_ONLY_RETENUE=1`

#### Contenu produit
Le document Word généré comprend :
- un en-tête d’informations générales,
- une table des clichés,
- une succession de blocs par photo :
  - commentaire,
  - image,
  - légende Word native `Cliché X - libellé`,
  - mention éventuelle de provenance (`GTP`, `UI`, `BATCH`). :contentReference[oaicite:4]{index=4}

#### Particularités techniques
- utilisation d’un **modèle Word** ;
- insertion via marqueur `[[RAPPORT_PHOTOS]]` ;
- création de champs Word natifs (`SEQ Cliché`, `TOC`) ;
- rotation de l’image selon `orientation_photo` ;
- tri des photos par `horodatage_photo` ou `photo_rel_native`. :contentReference[oaicite:5]{index=5}

#### Sortie
Le rapport est enregistré dans le dossier de base des photos, avec un nom du type :

`annotation_photos_<id_affaire>_<id_captation>_V_<timestamp>.docx`

### 3.11 Chaînage des prompts et logique LLM/VLM

Le système repose sur un enchaînement structuré de deux passes distinctes, avec des contraintes fortes sur les entrées et sorties.



---

#### 3.11.1 Principe général

Le pipeline de génération est séquentiel :

1. **PASS 1 — VLM (Vision Language Model)**
   - Entrée : image
   - Sortie : description factuelle (`description_vlm_batch`)
   - Objectif : produire une base descriptive neutre

2. **PASS 2 — LLM (Language Model)**
   - Entrées :
     - description VLM
     - transcription audio (fenêtre temporelle)
     - contexte projet
   - Sorties :
     - libellé
     - commentaire

---

#### 3.11.2 Rôle du serveur Flask (`/annoter`)

Le serveur LLM constitue le point d’entrée réel des générations.

Fonctions principales :
- construction des prompts (system + user)
- injection du contexte (audio, VLM, mission)
- appel modèle (local ou distant)
- post-traitement de la réponse

Le client (`local_llm_client.py`) agit uniquement comme transport HTTP.

---

#### 3.11.3 Cadrage des prompts

Les prompts sont fortement contraints afin de garantir :

- neutralité descriptive
- absence d’interprétation
- absence de causalité
- ancrage strict dans les données

Les règles sont définies dans :
- `prompt_gpt.json` (mode interactif)
- `prompt_gpt_batch_only.json` (mode batch)

---

#### 3.11.4 Structuration des réponses

Les sorties attendues sont :

- soit du texte brut structuré
- soit du JSON (selon configuration)

Contraintes :
- format court
- vocabulaire factuel
- absence de spéculation
- filtrage des réponses parasites (boilerplate)

Tout écart (texte vide, incohérent) est traité comme erreur.

---

#### 3.11.5 Différence modèles locaux / distants

Le système peut utiliser :

- un modèle local (via serveur Flask)
- ou un modèle distant (type OpenAI)

Différences principales :

- latence
- robustesse
- conformité aux contraintes

Le mode batch privilégie généralement :
→ modèle local (contrôle + coût)

---

#### 3.11.6 Dépendance entre PASS 1 et PASS 2

La qualité du LLM dépend directement de :

- la qualité de `description_vlm_batch`
- la cohérence de la transcription audio

Une description VLM incorrecte entraîne :
- une dégradation du libellé
- une perte de pertinence du commentaire

---

#### 3.11.7 Stratégie d’erreur

- erreur VLM → empêche LLM
- erreur LLM → relance possible (cf. batch_reset_strategies.md)
- erreur LLM → relance automatique + possibilité de relance manuelle ciblée

Le système privilégie :
→ la relance LLM sans recalcul VLM

#### 3.11.8 Stratégie de protection contre les réponses parasites (anti-boilerplate)

Le système intègre une stratégie spécifique de détection et d’élimination des réponses parasites générées par les modèles.

---

##### a) Problématique

Les modèles LLM peuvent produire des réponses non pertinentes ou génériques, typiquement :

- phrases techniques hors contexte (ex : « vérifier la connexion internet »)
- messages de type support ou diagnostic
- répétitions ou artefacts de génération

Ces éléments sont incompatibles avec l’objectif :
→ produire un contenu descriptif strictement lié à la photographie.

---

##### b) Mécanisme de détection

Une détection automatique est mise en œuvre côté serveur Flask, basée sur :

- une liste de motifs connus (boilerplates)
- une normalisation du texte (minuscules, accents supprimés)
- une comparaison floue (fuzzy matching)

Exemples de motifs détectés :
- « répare la sortie »
- « vérifie connexion internet »
- « réparation terminée »

---

##### c) Traitement

Lorsqu’un boilerplate est détecté :

- la réponse est considérée comme invalide
- elle peut être :
  - rejetée
  - ou relancée (retry LLM)
- une erreur est tracée dans :
  - `llm_err_lib`
  - `llm_err_com`

---

##### d) Objectif

Garantir que :

- toutes les sorties sont pertinentes
- aucun texte parasite n’est conservé
- les annotations restent exploitables dans un cadre expertal

---

##### e) Limites

- détection basée sur motifs → non exhaustive
- nécessite enrichissement progressif

---

##### f) Interaction avec la stratégie anti-hallucination

La protection contre les boilerplates complète :

- le cadrage strict des prompts
- les contraintes de génération

Elle constitue un second niveau de sécurité :
→ filtrage a posteriori des réponses générées

### 3.12 Logique de gestion des erreurs et des relances

Le système intègre une gestion structurée des erreurs à plusieurs niveaux, afin de garantir la robustesse du pipeline et la qualité des résultats.

---

#### 3.12.1 Typologie des erreurs

Les erreurs sont distinguées selon leur origine :

##### a) Erreurs VLM
- image non accessible
- erreur API vision
- réponse vide ou invalide

Indicateurs :
- `vlm_status = ERR`
- `vlm_err` renseigné

---

##### b) Erreurs LLM

Deux types distincts :

- `llm_err_lib` → erreur sur le libellé
- `llm_err_com` → erreur sur le commentaire

Causes possibles :
- timeout
- erreur HTTP
- réponse vide
- réponse incohérente
- détection de boilerplate

---

##### c) Erreurs de contenu

- texte vide
- texte hors format attendu
- contenu non conforme aux contraintes métier

Ces erreurs sont traitées comme des erreurs LLM.

---

#### 3.12.2 Stratégie de retry

Le système implémente une stratégie de relance automatique côté batch.

##### a) Retry LLM

- relance en cas de :
  - erreur HTTP (timeout, 5xx, 429)
  - réponse vide
  - réponse filtrée (boilerplate)

- mécanisme :
  - retry avec backoff exponentiel
  - limitation du nombre de tentatives

---

##### b) Retry VLM

- plus limité (coût plus élevé)
- déclenché uniquement en cas d’erreur explicite

---

#### 3.12.3 Logique de dépendance

Le pipeline respecte les dépendances suivantes :

- VLM requis pour LLM
- si VLM en erreur → LLM non exécuté

Conséquence :
- priorité à la stabilisation VLM
- relance LLM privilégiée sans recalcul VLM

---

#### 3.12.4 Traçabilité des erreurs

Toutes les erreurs sont persistées dans le CSV batch :

- `vlm_err`
- `llm_err_lib`
- `llm_err_com`
- `llm_http_status_*`
- `llm_trace_*`

Ces champs permettent :
- diagnostic
- relance ciblée
- audit du traitement

---

#### 3.12.5 Interaction avec le filtrage anti-boilerplate

Le filtrage des réponses parasites est intégré dans la logique d’erreur :

- réponse détectée comme boilerplate → rejet
- conversion en erreur LLM
- possibilité de retry automatique

---

#### 3.12.6 Stratégie de relance manuelle

Le système est conçu pour permettre des relances ciblées via modification du CSV :

- relance LLM uniquement :
  - suppression des champs LLM
  - conservation des données VLM

- relance complète :
  - suppression VLM + LLM

Voir :
→ `batch_reset_strategies.md`

---

#### 3.12.7 Objectifs de la stratégie

Cette architecture permet :

- minimiser les recalculs coûteux (VLM)
- isoler les erreurs LLM
- garantir la qualité des sorties
- permettre des corrections rapides en production

---

#### 3.12.8 Limites

- dépendance à la qualité du modèle
- détection partielle des erreurs sémantiques
- nécessité de supervision humaine (validation UI)

---

#### 3.12.9 Principe directeur

Le système privilégie :

→ **la relance minimale nécessaire pour corriger l’erreur**

afin de garantir :
- performance
- stabilité
- cohérence des données


## 4. Flux de données

### Étapes

1. Chargement projet (infos_projet.json)
2. Sélection fichiers
3. Préparation audio
4. Synchronisation transcription ↔ photos
5. Annotation :
   - VLM → description image
   - LLM → texte final
6. Sauvegarde :
   - CSV
   - Excel
   - Word

---
## 5. Structure du CSV batch

Le CSV batch constitue le support principal de suivi du traitement des photographies.

Il est :
- généré automatiquement par le batch
- enrichi à chaque étape
- utilisé pour les relances et le diagnostic

---

### 5.1 Colonnes principales

#### Identification
- `nom_fichier_image`
- `photo_rel_native`
- `id_affaire`
- `id_captation`

---

#### Données VLM
- `description_vlm_batch`
- `vlm_status`
- `vlm_err`

---

#### Données LLM
- `libelle_propose_batch`
- `commentaire_propose_batch`

---

#### Erreurs LLM
- `llm_err_lib`
- `llm_err_com`
- `llm_http_status_lib`
- `llm_http_status_com`

---

#### Statut global
- `batch_status`
- `batch_ts`

---

### 5.2 Logique de dépendance

Le traitement suit les dépendances suivantes :

- VLM → alimente LLM
- LLM dépend de VLM

Conséquences :

- si `vlm_status = ERR` → LLM non exécuté
- si LLM en erreur → VLM conservé

---

### 5.3 États typiques

| Situation | VLM | LLM | Interprétation |
|----------|-----|-----|----------------|
| OK complet | OK | OK | traitement terminé |
| Erreur VLM | ERR | — | blocage en entrée |
| Erreur LLM | OK | ERR | relance possible |
| Vide | — | — | non traité |

---

### 5.4 Stratégie de relance

Le CSV permet des relances ciblées :

#### Relance LLM uniquement
- conserver `description_vlm_batch`
- vider :
  - `libelle_propose_batch`
  - `commentaire_propose_batch`
  - `llm_err_*`

#### Relance complète
- vider VLM + LLM

---

### 5.5 Rôle dans le pipeline

Le CSV batch permet :

- traçabilité complète du traitement
- reprise après erreur
- diagnostic des anomalies
- contrôle qualité

---

### 5.6 Point critique

Toute modification manuelle du CSV doit être maîtrisée :

- risque de désynchronisation
- risque d’écrasement de données valides

---

### 5.7 Principe directeur

Le CSV batch est conçu comme :

→ **un journal d’exécution persistant du pipeline**


### 5.8 Schéma des dépendances VLM / LLM / CSV

Le traitement des données dans le CSV batch suit une logique séquentielle avec dépendances :

```

[PHOTO]
↓
[VLM]
(description_vlm_batch)
↓
[LLM]
(libelle_propose_batch + commentaire_propose_batch)
↓
[VALIDATION / EXPORT]

```

---

### Détail des flux

```

nom_fichier_image
↓
┌─────────────────────────────┐
│ PASS 1 — VLM               │
│ description_vlm_batch      │
│ vlm_status / vlm_err       │
└──────────────┬──────────────┘
│
│ (si OK)
▼
┌─────────────────────────────┐
│ PASS 2 — LLM               │
│ libelle_propose_batch      │
│ commentaire_propose_batch  │
│ llm_err_*                  │
└──────────────┬──────────────┘
│
▼
batch_status

```

---

### Logique conditionnelle

```

SI vlm_status = ERR
→ LLM NON exécuté

SI LLM erreur
→ VLM conservé
→ relance LLM possible

SI boilerplate détecté
→ rejet réponse
→ erreur LLM
→ retry possible

```

---

### Stratégie de relance

```

RELANCE LLM :
[description_vlm_batch] conservé
→ recalcul LLM uniquement

RELANCE COMPLETE :
→ recalcul VLM + LLM

```

---

### Principe global

```

MINIMISER :

* les recalculs VLM (coûteux)

MAXIMISER :

* la réutilisation des données valides

ISOLER :

* les erreurs LLM

```

---

### Lecture rapide

```

PHOTO → VLM → LLM → CSV → VALIDATION

```
Parfait — voici le **schéma des flux inter-machines (Laptop / NAS / PC fixe)**, structuré pour votre architecture réelle.

👉 À intégrer idéalement dans le `pipeline.md` en nouvelle section :

```markdown
## 6. Architecture distribuée et flux inter-machines
```

---

# 🔧 Bloc prêt à intégrer

```markdown id="d4f9k2"
### 6.1 Vue d’ensemble des flux

Le système repose sur une architecture distribuée entre trois environnements :

- **Laptop (poste expert)**
- **NAS (stockage + synchronisation)**
- **PC fixe (batch intensif)**

---

### 6.2 Schéma global

```

[LAPTOP — UI Streamlit]
│
│ (CSV photos UI + annotations)
▼
[NAS — stockage central]
│
│ (synchronisation fichiers)
▼
[PC FIXE — Batch]
│
│ (CSV batch enrichi)
▼
[NAS]
│
│ (retour données enrichies)
▼
[LAPTOP — validation + export Word]

---

### 6.3 Détail des échanges

#### 1. Laptop → NAS

Données envoyées :

- CSV photos (UI)
- fichiers audio
- photos (si nécessaires)
- configuration projet (`infos_projet.json`)

Objectif :
→ centralisation des données sources

---

#### 2. NAS → PC fixe

Données synchronisées :

- CSV photos
- arborescence photos
- fichiers audio

Mécanisme :
- synchronisation périodique
- scripts type robocopy / tâches planifiées

---

#### 3. PC fixe (batch)

Traitement :

- lecture CSV photos
- génération CSV batch :
  - VLM
  - LLM
- enrichissement des données

Sorties :

- CSV batch mis à jour
- logs batch

---

#### 4. PC fixe → NAS

Retour :

- CSV batch enrichi
- fichiers intermédiaires éventuels

---

#### 5. NAS → Laptop

Données récupérées :

- CSV batch
- CSV GTP (si généré)
- ressources synchronisées

---

#### 6. Laptop (finalisation)

Actions :

- validation expert (UI)
- production CSV GTP
- génération rapport Word (`generate_word_report.py`)

---

### 6.4 Règles de cohérence

- le **CSV photos UI** reste la source de vérité
- le **CSV batch** est un enrichissement technique
- le **CSV GTP** contient les données validées

Priorité finale :

→ **GTP > UI > Batch**

---

### 6.5 Points critiques

- cohérence des chemins :
  - NAS vs local PC fixe
- synchronisation différée (latence possible)
- gestion des conflits de version CSV
- disponibilité des fichiers (photos/audio)

---

### 6.6 Risques identifiés

- désynchronisation CSV UI / batch
- écrasement de données validées
- chemins invalides après copie
- divergence des environnements (Python, dépendances)

---

### 6.7 Bonnes pratiques

- ne jamais modifier manuellement plusieurs CSV en parallèle
- vérifier la synchronisation avant batch
- relancer le batch uniquement sur lignes nécessaires
- contrôler les chemins après synchronisation

---

### 6.8 Principe directeur

L’architecture repose sur :

→ **une séparation claire entre interaction humaine (Laptop) et traitement massif (PC fixe)**

avec un point central :

→ **le NAS comme pivot de synchronisation**

```
## 7. Spécificités métier

- domaine : expertise judiciaire bâtiment
- contraintes fortes :
  - neutralité
  - absence de qualification juridique
  - absence de causalité

Ces contraintes sont codées dans les prompts.

---



## 8. Environnement d’exécution

### Local expert
- Streamlit
- LLM local (Flask)
- ffmpeg

### PC fixe (batch)
- accès réseau (Affaires)
- traitement massif CSV

---

## 9. Points critiques

- synchronisation audio/photo (décalage)
- robustesse des prompts
- gestion des erreurs batch
- cohérence des chemins (local vs réseau)

---

## 10. Évolutions possibles

- amélioration VLM
- intégration OCR
- automatisation complète pipeline
- interface validation expert


## Dépendance au serveur Flask

Le pipeline batch dépend du serveur GPT4All_Local, notamment via la route :

- `/annoter`

Toute modification de :
- `/annoter`
- ses payloads
- ses formats de sortie
- la résolution des chemins affaire

doit être vérifiée au regard de ce pipeline.

## Intégration dans les dossiers affaire

Le pipeline lit et écrit dans les dossiers d’une affaire selon l’organisation documentaire en vigueur.

Les fichiers produits ou mis à jour incluent notamment :
- `photos.csv`
- `photos_batch.csv`
- exports Excel
- rapport Word

Toute modification de structure de dossiers ou de conventions de chemins peut impacter ce pipeline.