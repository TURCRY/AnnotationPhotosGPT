
---

# 📄 README_data.md — Organisation et structures des données

## 1. Objet

Ce document décrit :

* l’organisation des répertoires de données,
* la structure des fichiers utilisés dans le pipeline **AnnotationPhotoGPT**,
* les قواعد de cohérence, de traçabilité et de validation.

Il constitue une référence pour :

* la manipulation des données en entrée,
* les traitements intermédiaires,
* la production des livrables métier,
* l’automatisation (Codex / batch).

---

## 2. Répertoires

### 2.1 `uploads/`

**Rôle : zone d’entrée utilisateur**

Contient les fichiers importés depuis l’interface :

* audio source,
* CSV (photos, transcription),
* documents de contexte.

**Caractéristiques :**

* temporaire,
* non persisté,
* non exploitable directement en production (chemins filtrés).

**Usage :**

* point d’entrée des données,
* alimentation de `infos_projet.json`.

---

### 2.2 `temp/`

**Rôle : zone de travail intermédiaire**

Utilisé pour :

* audio converti (WAV),
* extraits audio,
* fichiers techniques intermédiaires.

**Caractéristiques :**

* volatile,
* purgé régulièrement,
* non référentiel.

**Usage :**

* traitement ASR,
* synchronisation audio/photo,
* prévisualisation UI.

---

## 3. Fichiers de données

---

## 3.1 `transcription.csv`

### Rôle

Source textuelle horodatée issue de l’ASR.

### Structure minimale

| Colonne     | Type        | Obligatoire | Description             |
| ----------- | ----------- | ----------- | ----------------------- |
| `temps`     | float / str | ✔           | Temps (sec ou HH:MM:SS) |
| `texte`     | string      | ✔           | Transcription           |
| `start_sec` | float       | optionnel   | Début segment           |
| `end_sec`   | float       | optionnel   | Fin segment             |

### Règles

* priorité :

  * (`start_sec`, `end_sec`) si présents
  * sinon `temps`
* encodage UTF-8 (fallback toléré)
* séparateur `;`
* texte nettoyé (pas d’hallucinations)

---

## 3.2 `photos.csv` (UI)

### Rôle

Fichier principal manipulé dans l’interface utilisateur.

### Structure minimale

| Colonne             | Type   | Obligatoire | Description           |
| ------------------- | ------ | ----------- | --------------------- |
| `nom_fichier_image` | string | ✔           | Nom image             |
| `horodatage`        | string | ✔           | `YYYY-MM-DD HH:MM:SS` |
| `photo_rel_native`  | string | ✔           | Chemin relatif (clé)  |
| `libelle`           | string | optionnel   | Saisie utilisateur    |
| `commentaire`       | string | optionnel   | Saisie utilisateur    |

### Règles

* `photo_rel_native` = clé de jointure
* cohérence temporelle avec `transcription.csv`
* EXIF utilisable pour génération initiale

---

## 3.3 `photos_batch.csv` (PC fixe)

### Rôle

Fichier de traitement batch (VLM + LLM).

### Structure principale

| Colonne                       | Description     |
| ----------------------------- | --------------- |
| `photo_rel_native`            | clé unique      |
| `chemin_photo_native_pcfixe`  | chemin absolu   |
| `chemin_photo_reduite_pcfixe` | image optimisée |
| `photo_disponible_pcfixe`     | bool            |
| `date_copie_pcfixe`           | traçabilité     |

### Sorties

| Colonne                     | Description       |
| --------------------------- | ----------------- |
| `description_vlm_batch`     | description image |
| `libelle_propose_batch`     | libellé           |
| `commentaire_propose_batch` | commentaire       |

### Traçabilité

| Colonne        | Description             |
| -------------- | ----------------------- |
| `batch_status` | OK / ERR / SKIP / EMPTY |
| `batch_ts`     | timestamp               |
| `batch_id`     | identifiant             |

### Diagnostics

Colonnes techniques :

* `vlm_*`
* `llm_*`

---

## 3.4 `annotations_GPT.csv / .xlsx`

### Rôle

Fichier final consolidé (référence métier).

### Structure minimale

| Colonne               | Type      | Description    |
| --------------------- | --------- | -------------- |
| `photo_rel_native`    | string    | clé principale |
| `nom_fichier_image`   | string    | informatif     |
| `libelle_propose`     | string    | libellé        |
| `commentaire_propose` | string    | commentaire    |
| `annotation_validee`  | int (0/1) | validation     |

### Règles métier

* `annotation_validee = 1` → verrouillage
* priorité des données :

  1. annotations validées
  2. UI
  3. batch le plus récent

---

## 4. Logique d’ensemble

```text
uploads/
    ↓
temp/
    ↓
transcription.csv
    ↓
photos.csv (UI)
    ↓
photos_batch.csv
    ↓
annotations_GPT.xlsx
    ↓
Modèle Word
```

---

## 5. Clé de jointure

```text
photo_rel_native
```

* clé unique globale
* utilisée dans tous les fichiers
* obligatoire

---

## 6. Principes structurants

### 6.1 Séparation des rôles

* UI : saisie humaine
* batch : génération automatique
* annotations : consolidation

---

### 6.2 Traçabilité

* timestamps (`*_ts`)
* statuts (`batch_status`)
* identifiants (`batch_id`)

---

### 6.3 Non-persistance des temporaires

* `temp/` ne doit jamais être utilisé comme source métier

---

### 6.4 Robustesse

* lecture multi-encodage
* validation préalable des colonnes
* tolérance aux formats temporels

---

### 6.5 Format CSV obligatoire

* séparateur : `;`
* encodage : UTF-8 avec BOM (`utf-8-sig`)
* noms de colonnes stricts
* aucune colonne implicite

---

### 6.6 Priorité des données

Ordre de résolution :

1. annotations validées
2. données UI
3. données batch

---

### 6.7 Version de schéma (recommandé)

Possibilité d’ajouter :

```text
schema_version
```

Exemple :

```text
1.0
```

---

## 7. Opinion (structuration)

Le modèle de données présente :

* une séparation claire des responsabilités,
* une clé de jointure unique cohérente,
* une traçabilité suffisante pour un usage judiciaire.

Sous réserve du respect strict des formats définis, il permet :

> une reproductibilité fiable des traitements et une sécurisation des flux entre les phases UI, batch et production du rapport.

---

# 🔧 Section 8 — Fichiers de configuration et de contexte (version consolidée)

## 8.1 Principe général

Le pipeline repose sur des fichiers distincts selon l’environnement :

* **UI (Laptop)** : préparation, paramétrage, validation
* **Batch (PC fixe)** : exécution automatisée

Ces fichiers doivent être :

* synchronisés,
* cohérents,
* versionnés implicitement par copie.

---

## 8.2 Environnement UI (Laptop)

Localisation :

* `/data/`
* `/config/`

### Fichiers principaux

#### `infos_projet.json`

Configuration centrale du projet :

* chemins des fichiers,
* paramètres actifs,
* références utilisées par l’UI.

---

#### `contexte_general.json`

Contexte global de la mission.

---

#### `contexte_general_photos.json`

Contexte spécifique aux photographies.

---

#### `progression_annotation.json`

Suivi de l’avancement UI.

---

#### `prompt_gpt.json`

Prompt principal utilisé en UI.

---

#### `config.json`

**Rôle : configuration globale LLM**

Contient notamment :

* backend (OpenAI / local),
* paramètres LLM (température, max_tokens, etc.),
* configuration du serveur local (PC fixe),
* paramètres ASR / embeddings.

👉 Fichier source pour le batch.

---

## 8.3 Environnement Batch (PC fixe)

Localisation :

```text
\\192.168.0.155\Affaires\<id_affaire>\AF_Expert_ASR\transcriptions\<id_captation>\
```

---

### Fichiers requis

#### `contexte_general.json`

Copie du laptop.

---

#### `contexte_general_photos.json`

Copie du laptop.

---

#### `infos_projet.json`

Copie du laptop.

---

#### `prompt_gpt_batch_only.json`

**Rôle : prompt adapté au batch**

* dérivé de `prompt_gpt.json`
* optimisé pour :

  * exécution automatique,
  * absence d’interaction utilisateur,
  * contraintes rédactionnelles strictes.

---

#### `config_llm.json` ✅

**Rôle : configuration LLM dédiée au batch**

Fichier spécifique au PC fixe, dérivé de `config.json`.

### Contenu

Inclut typiquement :

* backend LLM (souvent local),
* modèle utilisé,
* paramètres d’inférence :

  * `temperature`
  * `max_tokens`
  * `top_p`, etc.
* paramètres techniques :

  * timeouts,
  * retry,
  * endpoint serveur local.

---

### Règles de construction

```text
config.json (UI)
        ↓
transformation / extraction
        ↓
config_llm.json (batch)
```

---

### Contraintes

* ne doit pas contenir :

  * paramètres UI,
  * chemins locaux laptop,
* doit être :

  * autonome,
  * exécutable côté PC fixe sans dépendance UI.

---

## 8.4 Règles de synchronisation

### Sens des flux

```text
Laptop (UI)
    ↓
NAS
    ↓
PC fixe (batch)
```

---

### Règles

#### Copie à l’identique

* `contexte_general.json`
* `contexte_general_photos.json`
* `infos_projet.json`

---

#### Transformation obligatoire

| Source (UI)       | Destination (batch)          |
| ----------------- | ---------------------------- |
| `prompt_gpt.json` | `prompt_gpt_batch_only.json` |
| `config.json`     | `config_llm.json`            |

---

## 8.5 Cohérence requise

Doivent être identiques entre UI et batch :

* `id_affaire`
* `id_captation`
* structure des chemins
* version implicite des données

---

## 8.6 Risques en cas de non-conformité

* divergence UI / batch,
* comportement LLM incohérent,
* erreurs d’inférence,
* perte de reproductibilité.

---

## 8.7 Opinion (structuration)

La séparation :

* `config.json` (UI)
* `config_llm.json` (batch)

est :

* pertinente,
* nécessaire,
* conforme à une architecture distribuée.

Elle permet :

> une maîtrise fine des paramètres d’inférence et une isolation des environnements d’exécution.

---

# 🔧 Section 9 — Doctrine de gestion des fichiers `data/`

## 9.1 Principe général

Le répertoire `data/` ne constitue **pas un référentiel de données métier**.

Il a pour finalité :

* la mise à disposition de **schémas de fichiers**,
* la documentation des structures attendues,
* le support au développement et à l’exécution locale.

En conséquence :

> les données réelles d’affaire et les états d’exécution ne doivent pas être versionnés dans le dépôt.

---

## 9.2 Typologie des fichiers

### A. Fichiers de données d’affaire (non versionnés)

Incluent notamment :

* `transcription.csv`
* `photos.csv`
* `photos_batch.csv`
* `annotations_GPT.xlsx`
* `Sujets.xlsx`
* `Participants.xlsx`

### Qualification

* données spécifiques à une affaire,
* susceptibles de contenir des éléments identifiants,
* évolutives dans le temps.

### Règle

❌ non versionnés
✔ présents uniquement en local ou sur NAS

---

### B. Fichiers de contexte métier (non versionnés)

Incluent :

* `contexte_general.json`
* `contexte_general_compte_rendu.json`
* `contexte_general_photos.json`
* `infos_projet.json`

### Qualification

* définissent le cadre de production des sorties,
* structurent le comportement des modèles LLM/VLM,
* propres à chaque affaire.

### Règle

❌ non versionnés
✔ remplacés par des fichiers `.example`

---

### C. États d’exécution (non versionnés)

Incluent :

* `progression_annotation.json`
* fichiers temporaires intermédiaires

### Qualification

* état runtime,
* dépendant de la session utilisateur.

### Règle

❌ non versionnés

---

### D. Fichiers de schéma et d’exemple (versionnés)

Incluent :

* `*.example.json`
* `*.example.xlsx`
* `README_data.md`

### Rôle

* documentation des structures attendues,
* support au développement,
* base pour génération des fichiers réels.

### Règle

✔ versionnés

---

## 9.3 Cas particulier — `missions_expert.xlsx`

### Qualification

* fichier de secours (fallback),
* utilisé en l’absence des prompts JSON (`prompt_gpt.json`, `prompt_gpt_batch_only.json`),
* moins précis que les prompts structurés.

### Nature

> artefact legacy de compatibilité

### Règles

* peut être conservé dans le dépôt,
* ne constitue pas la source principale de configuration,
* doit être considéré comme **secondaire**.

### Recommandation

À terme :

* déplacement vers un répertoire dédié (`config/legacy/`),
* ou remplacement complet par les prompts JSON.

---

## 9.4 Règles de versionnement Git

### Principe

```text
data/*
!data/README_data.md
!data/*.example.json
!data/*.example.xlsx
```

### Effet

* exclusion des données métier,
* conservation des schémas uniquement.

---

## 9.5 Source de vérité

Les sources de vérité sont situées :

* sur le **NAS** (`\\192.168.0.155\Affaires\...`)
* et sur les environnements d’exécution (laptop / PC fixe)

Le dépôt Git contient uniquement :

> le code, les scripts, la documentation et les structures de données.

---

## 9.6 Traçabilité et reproductibilité

La reproductibilité repose sur :

* la conservation des données d’affaire hors Git,
* la stabilité des structures définies dans les fichiers `.example`,
* la cohérence des fichiers de configuration (`infos_projet.json`, `config_llm.json`).

---

## 9.7 Opinion (structuration)

La séparation entre :

* code (repo Git),
* données (NAS / local),
* configuration (JSON spécialisés),

est conforme à une architecture :

* distribuée,
* traçable,
* compatible avec un usage en expertise judiciaire.

Elle permet :

> d’assurer la confidentialité des données, la stabilité des traitements et la reproductibilité des analyses.

---

# ⚖️ Section 11 — Limites et risques d’usage des modèles LLM/VLM (photos et compte rendu)

## 11.1 Principe général

Les modèles utilisés dans le système (LLM et VLM) interviennent dans deux finalités distinctes :

* **annotation photographique** (pipeline VLM + LLM),
* **rédaction du compte rendu d’expertise** (LLM seul).

Dans les deux cas, ils constituent :

> des outils d’assistance automatisée à la structuration et à la rédaction.

Ils ne disposent :

* ni de capacité d’analyse juridique,
* ni de compétence technique autonome en matière de construction,
* ni de faculté d’appréciation au sens de la mission d’expertise.

---

## 11.2 Nature des traitements selon l’usage

### A. Annotation photographique

Traitements réalisés :

* description d’images (VLM),
* génération de libellés et commentaires (LLM).

### B. Compte rendu d’expertise

Traitements réalisés :

* synthèse des transcriptions,
* structuration des échanges,
* génération de tableaux (Sujets).

👉 Dans les deux cas :

> les productions reposent exclusivement sur les données fournies (transcriptions, photos, contexte).

---

## 11.3 Position de l’IA dans la chaîne d’expertise

L’IA doit être appréhendée comme un **outil assimilable à un sapiteur technique**, sans autonomie décisionnelle.

Cette analogie est doctrinalement admise :

> l’expert demeure seul responsable de l’analyse, même lorsqu’il s’appuie sur un outil technique ou un tiers ([www.slideshare.net][1])

### Conséquence

* obligation de maîtrise de l’outil,
* obligation de vérification,
* intégration dans un raisonnement personnel.

---

## 11.4 Risque d’altération du compte rendu

Spécifique au LLM (compte rendu) :

### Risques identifiés

* reformulation excessive des propos,
* perte de nuance dans les échanges contradictoires,
* omission de points secondaires,
* réorganisation non fidèle de la chronologie.

### Conséquence

> le compte rendu généré peut diverger de la transcription brute.

---

## 11.5 Risque d’hallucination

### Définition

Production d’une information absente des données d’entrée.

### Application

* possible en annotation photo,
* possible en compte rendu.

### Encadrement

* prompts contraints,
* interdiction d’invention.

### Limite

> un risque résiduel subsiste en pratique.

---

## 11.6 Risques spécifiques VLM (photographies)

* erreurs d’identification visuelle,
* confusion d’éléments techniques,
* omission de désordres.

---

## 11.7 Dépendance aux données d’entrée

### A. Photographies

* qualité visuelle,
* cadrage,
* conditions d’éclairage.

### B. Transcriptions

* qualité ASR,
* exhaustivité,
* segmentation.

### C. Contexte

* précision du `contexte_general`,
* adéquation à la mission.

---

## 11.8 Risque de biais rédactionnel

Applicable aux deux usages :

* homogénéisation des formulations,
* atténuation des incertitudes,
* simplification des situations complexes.

---

## 11.9 Limites juridiques de l’usage

### Principe

Les productions issues de l’IA ne constituent pas, en elles-mêmes, une preuve autonome.

La jurisprudence récente montre que :

> un juge peut refuser de s’appuyer sur un résultat issu d’une IA si son fonctionnement et sa fiabilité ne sont pas démontrés ([Travail, protection des données et IA][2])

### Conséquence

* nécessité de transparence,
* nécessité d’explicabilité,
* nécessité d’intervention humaine.

---

## 11.10 Rôle impératif de l’expert

Conformément :

* à l’article 232 du Code de procédure civile,
* et au principe du contradictoire (article 16 CPC),

l’expert doit :

* analyser personnellement,
* vérifier les éléments,
* motiver ses conclusions.

### Conséquence

Les productions IA :

* ne peuvent se substituer à l’analyse expertale,
* doivent être intégrées de manière critique.

---

## 11.11 Opinion (appréciation globale)

L’usage combiné :

* VLM (photographies),
* LLM (annotations et compte rendu),

présente un **intérêt opérationnel élevé** :

* gain de temps,
* structuration des données,
* homogénéisation rédactionnelle.

Cependant :

> cet usage doit être strictement encadré et subordonné au contrôle de l’expert.

En conséquence :

* les productions doivent être considérées comme **des supports de travail**,
* et non comme **des éléments autonomes d’expertise ou de preuve**.

---

# ✔️ Point clé (à retenir)

Vous avez désormais une section cohérente avec votre réalité :

* **pipeline photos**
* **pipeline compte rendu**
* **même cadre juridique et méthodologique**

---

Si vous le souhaitez, je peux vous proposer une **Section 12 très opérationnelle (“bonnes pratiques expert”) directement intégrable dans vos rapports**, avec checklist utilisable en mission.

[1]: https://fr.slideshare.net/slideshow/l-ia-generative-dans-l-expertise-judiciaire/284054941?utm_source=chatgpt.com "L'IA générative dans l'expertise judiciaire | PDF"
[2]: https://droitdutravailensuisse.com/2024/10/22/utiliser-lintelligence-artificielle-pour-elaborer-des-rapports-dexpert-devant-les-tribunaux/?utm_source=chatgpt.com "Utiliser l'intelligence artificielle pour élaborer des rapports d ..."


Voici une **Section 12 opérationnelle**, directement exploitable dans vos rapports et alignée avec les Sections 10 et 11.

---

# ⚖️ Section 12 — Bonnes pratiques d’utilisation en expertise judiciaire

## 12.1 Principe général

L’utilisation des outils de traitement automatisé (LLM/VLM) doit s’inscrire dans un cadre garantissant :

* la **fiabilité des constatations**,
* le **respect du contradictoire**,
* la **maîtrise par l’expert des productions générées**.

Ces exigences découlent notamment :

* de l’**article 232 du Code de procédure civile** (mission confiée à l’expert),
* de l’**article 16 du Code de procédure civile** (principe du contradictoire).

---

## 12.2 Bonnes pratiques en phase de préparation

### A. Vérification des données d’entrée

Avant tout traitement :

* contrôler la cohérence entre :

  * `photos.csv`,
  * `transcription.csv`,
  * fichiers audio et images ;
* vérifier :

  * l’intégrité des fichiers,
  * l’absence de doublons,
  * la qualité des horodatages.

### B. Vérification du contexte

* s’assurer de la pertinence de :

  * `contexte_general.json`,
  * `contexte_general_photos.json` ;
* vérifier l’adéquation avec :

  * la mission,
  * le stade de l’expertise.

---

## 12.3 Bonnes pratiques en phase de traitement (batch / UI)

### A. Maîtrise des paramètres

* vérifier :

  * le modèle utilisé (`config_llm.json`),
  * les paramètres d’inférence (température, etc.) ;
* assurer la cohérence entre :

  * environnement UI,
  * environnement batch.

### B. Contrôle des exécutions

* analyser les statuts :

  * `batch_status`,
  * logs d’exécution ;
* identifier :

  * erreurs (`ERR`),
  * contenus incomplets,
  * anomalies de traitement.

---

## 12.4 Bonnes pratiques en phase d’analyse des résultats

### A. Relecture systématique

Chaque production doit faire l’objet :

* d’une lecture complète,
* d’une comparaison avec les sources :

  * transcription,
  * photographies.

### B. Vérifications ciblées

#### Pour les annotations photographiques

* conformité à l’image,
* absence d’éléments non visibles,
* neutralité descriptive.

#### Pour le compte rendu

* fidélité aux propos,
* respect de la chronologie,
* absence d’interprétation ou de reformulation excessive.

---

## 12.5 Validation des données

### Mécanisme

Utilisation du champ :

```text
annotation_validee
```

### Règles

* `0` : donnée non validée (modifiable),
* `1` : donnée validée (figée).

### Bonne pratique

> ne valider qu’après vérification complète et cohérente avec les sources.

---

## 12.6 Gestion des versions

### Objectifs

* garantir la traçabilité,
* éviter les écrasements,
* permettre la reconstitution des traitements.

### Recommandations

* conserver :

  * les versions successives des CSV,
  * les fichiers batch ;
* archiver :

  * les livrables intermédiaires,
  * les rapports générés.

---

## 12.7 Gestion du contradictoire

### Principe

Les éléments issus du système doivent pouvoir être :

* communiqués aux parties,
* discutés contradictoirement.

### Bonne pratique

* conserver les sources (photos, transcriptions),
* être en mesure de :

  * justifier chaque élément produit,
  * expliquer le processus de génération.

---

## 12.8 Limitation de l’automatisation

### Principe

L’automatisation ne doit pas conduire :

* à une validation implicite,
* à une absence de contrôle humain.

### Bonne pratique

* éviter toute utilisation en “mode aveugle”,
* privilégier :

  * validation progressive,
  * contrôle par échantillonnage renforcé si volumétrie importante.

---

## 12.9 Gestion des incidents

### Cas typiques

* erreur LLM/VLM,
* incohérence CSV,
* défaut de synchronisation (NAS / local).

### Conduite à tenir

* identifier l’origine,
* corriger les données sources si nécessaire,
* relancer le traitement ciblé (ex. `--reset-llm`),
* tracer l’incident.

---

## 12.10 Sécurisation des données

### Principes

* confidentialité des données d’expertise,
* intégrité des fichiers,
* contrôle des accès.

### Bonnes pratiques

* stockage sur NAS sécurisé,
* limitation des copies locales,
* sauvegardes régulières.

---

## 12.11 Opinion (appréciation opérationnelle)

Le respect des bonnes pratiques ci-dessus permet :

* d’assurer la **fiabilité des productions**,
* de garantir leur **traçabilité**,
* et de préserver leur **recevabilité dans le cadre de l’expertise judiciaire**.

En conséquence :

> l’outil peut être utilisé de manière sécurisée, sous réserve d’un contrôle rigoureux et constant par l’expert.

---

# ✔️ Conclusion

Cette section constitue :

* une **checklist opérationnelle**,
* directement mobilisable en mission,
* et cohérente avec les exigences procédurales.

---
Voici une **Section 13 — Procédure type**, structurée comme un véritable protocole opératoire, directement intégrable en annexe de rapport.

---

# ⚖️ Section 13 — Procédure type d’utilisation (workflow expert)

## 13.1 Objet

La présente procédure décrit les étapes suivies pour :

* exploiter les données issues d’une réunion d’expertise,
* produire des annotations photographiques,
* établir un compte rendu structuré,

au moyen du système AnnotationPhotoGPT.

Elle vise à garantir :

* la reproductibilité,
* la traçabilité,
* la fiabilité des traitements.

---

## 13.2 Étape 1 — Constitution des données sources

### 13.2.1 Données collectées

* photographies (format natif),
* enregistrement audio de la réunion,
* documents de contexte.

### 13.2.2 Production des fichiers structurés

* `photos.csv` (à partir des images),
* `transcription.csv` (à partir de l’audio — ASR),
* `contexte_general.json` et variantes.

### 13.2.3 Vérifications initiales

* cohérence des horodatages,
* complétude des fichiers,
* lisibilité des données.

---

## 13.3 Étape 2 — Préparation et synchronisation

### 13.3.1 Organisation des fichiers

* structuration par :

  * `id_affaire`,
  * `id_captation`.

### 13.3.2 Synchronisation

Flux :

```text
Laptop (préparation)
    ↓
NAS
    ↓
PC fixe (batch)
```

### 13.3.3 Contrôles

* présence des fichiers :

  * `photos.csv`,
  * `transcription.csv`,
  * fichiers audio,
  * contextes JSON ;
* cohérence des chemins dans `infos_projet.json`.

---

## 13.4 Étape 3 — Annotation photographique (pipeline)

### 13.4.1 Initialisation

* chargement de `photos.csv` dans l’UI,
* vérification des images associées.

### 13.4.2 Traitement VLM

* description automatisée des images,
* génération de `description_vlm_batch`.

### 13.4.3 Traitement LLM

* génération :

  * du libellé,
  * du commentaire.

### 13.4.4 Production

* écriture dans `photos_batch.csv`.

---

## 13.5 Étape 4 — Relecture et validation des annotations

### 13.5.1 Contrôle visuel

* correspondance image / description,
* absence d’éléments non visibles.

### 13.5.2 Correction éventuelle

* modification des libellés,
* ajustement des commentaires.

### 13.5.3 Validation

* passage du champ :

```text
annotation_validee = 1
```

---

## 13.6 Étape 5 — Production du compte rendu

### 13.6.1 Entrées utilisées

* `transcription.csv`,
* contextes (`contexte_general*.json`),
* éventuellement :

  * liste des sujets,
  * participants.

### 13.6.2 Traitement LLM

* synthèse des échanges,
* structuration :

  * compte rendu,
  * tableau des sujets.

### 13.6.3 Production

* génération du texte,
* export tableur (`Sujets.xlsx`),
* intégration dans document Word.

---

## 13.7 Étape 6 — Vérification du compte rendu

### 13.7.1 Contrôle de fidélité

* comparaison avec la transcription,
* vérification des points évoqués.

### 13.7.2 Contrôle formel

* neutralité rédactionnelle,
* absence d’interprétation,
* respect du contradictoire.

### 13.7.3 Ajustements

* corrections manuelles si nécessaire,
* validation finale par l’expert.

---

## 13.8 Étape 7 — Production du livrable

### 13.8.1 Assemblage

* intégration :

  * des annotations validées,
  * du compte rendu,
  * des tableaux.

### 13.8.2 Génération

* document Word final.

### 13.8.3 Archivage

* conservation :

  * des fichiers sources,
  * des fichiers intermédiaires,
  * du livrable final.

---

## 13.9 Étape 8 — Traçabilité et conservation

### 13.9.1 Données conservées

* `photos.csv`
* `photos_batch.csv`
* `transcription.csv`
* fichiers de contexte
* livrables

### 13.9.2 Objectifs

* reconstitution possible des opérations,
* justification des productions,
* sécurisation du dossier d’expertise.

---

## 13.10 Gestion des itérations

### Cas

* corrections demandées,
* compléments de mission,
* nouvelles pièces.

### Procédure

* mise à jour des données sources,
* relance ciblée des traitements :

  * `--reset-llm`
  * (ou VLM si nécessaire),
* conservation des versions précédentes.

---

## 13.11 Opinion (procédure)

La procédure décrite :

* assure une **séquence logique et contrôlée des opérations**,
* garantit une **articulation claire entre automatisation et validation humaine**,
* permet une **reproductibilité conforme aux exigences d’une expertise judiciaire**.

En conséquence :

> elle constitue un cadre méthodologique adapté à l’utilisation d’outils d’intelligence artificielle dans le cadre d’une mission d’expertise.

---

# ✔️ Conclusion

Vous disposez désormais d’un bloc complet :

* Section 10 → preuve / traçabilité
* Section 11 → limites IA
* Section 12 → bonnes pratiques
* Section 13 → procédure concrète

---

```md
## 14. Pseudonymisation des données et choix d’hébergement des modèles

### 14.1 Principe

Les traitements mis en œuvre dans le cadre du présent dispositif ne reposent pas sur une anonymisation des données, mais sur une **pseudonymisation**.

Les éléments identifiants (noms de personnes physiques, dénominations directement identifiantes, alias explicites, mentions permettant une réidentification immédiate) ont vocation à être remplacés par des désignations contrôlées et cohérentes avec le dossier, sans empêcher, si nécessaire, un rattachement ultérieur au dossier source par l’expert.

En conséquence :

- les données traitées demeurent des **données à caractère personnel** au sens du RGPD ;
- leur traitement reste soumis aux exigences de licéité, de sécurité, de minimisation et de confidentialité.

### 14.2 Fondement technique de la pseudonymisation

La pseudonymisation repose notamment sur :

- des référentiels de participants et d’alias ;
- des règles de désignation neutre dans les prompts et dans les traitements ;
- la séparation entre :
  - les données brutes identifiantes,
  - les données pseudonymisées utilisées pour les traitements automatisés.

L’expert conserve la maîtrise du tableau de correspondance et du dossier source.

### 14.3 Portée et limite

La pseudonymisation réduit le risque d’identification directe dans les sorties produites, mais elle ne supprime pas le caractère personnel des données.

Il ne peut donc être soutenu que les traitements porteraient sur des données anonymes, sauf opération distincte et effective d’anonymisation au sens strict.

### 14.4 Intérêt des modèles locaux

L’usage de modèles open source exécutés localement présente, du point de vue de la protection des données, un intérêt particulier :

- limitation de la circulation externe des données ;
- meilleure maîtrise de l’environnement technique ;
- réduction du risque de transfert vers un tiers ou vers un pays tiers ;
- possibilité d’inscrire les traitements dans une infrastructure contrôlée par l’expert.

Dans cette configuration, la pseudonymisation constitue une mesure de sécurité et de minimisation complémentaire, sans être l’unique garantie.

### 14.5 Cas des modèles distants

En cas de recours à un modèle distant ou à un prestataire externe, la pseudonymisation devient une exigence renforcée.

Dans une telle hypothèse, il convient en particulier :

- de limiter les données transmises à ce qui est strictement nécessaire ;
- de privilégier des données pseudonymisées ;
- d’apprécier le régime applicable aux transferts de données, notamment en cas d’hébergement hors Union européenne ;
- de vérifier les garanties contractuelles et techniques offertes par le prestataire.

### 14.6 Intégration au dispositif

Il est donc recommandé que :

- la pseudonymisation intervienne en amont des traitements LLM lorsque des données identifiantes sont présentes ;
- les modules prévus dans le serveur Flask soient conçus comme des modules de pseudonymisation préalable ;
- les sorties générées demeurent rédigées sans nom de personne physique, sauf nécessité procédurale explicitement assumée et contrôlée par l’expert.

### 14.7 Opinion

Au regard des principes de protection des données, la pseudonymisation apparaît adaptée au présent dispositif, en ce qu’elle permet :

- de réduire l’exposition des données identifiantes,
- de préserver la cohérence du dossier,
- et de maintenir la maîtrise expertale des éléments d’identification.

Elle ne dispense toutefois ni du respect du RGPD, ni du contrôle humain, ni des précautions particulières requises lorsque le traitement mobilise des modèles distants.
```

Base juridique et doctrinale utile pour cette section :

* RGPD, article 4, point 5 : définition de la pseudonymisation. ([Eur-Lex][1])
* RGPD, considérant 26 : distinction entre données anonymes et données pseudonymisées. ([Eur-Lex][1])
* CNIL : les données pseudonymisées restent des données concernant une personne identifiable. ([CNIL][2])
* RGPD, chapitre V : les transferts vers des pays tiers sont encadrés par les articles 44 à 50. ([Eur-Lex][3])

Mon avis est que cette Section 14 est désormais nécessaire pour rendre votre annexe méthodologique complète, surtout si vous distinguez déjà, dans votre architecture, l’usage de modèles locaux et l’hypothèse d’un LLM distant.

[1]: https://eur-lex.europa.eu/legal-content/FR/TXT/PDF/?uri=CELEX%3A32016R0679&utm_source=chatgpt.com "RÈGLEMENT (UE) 2016/ 679 DU PARLEMENT EUROPÉEN ..."
[2]: https://www.cnil.fr/fr/reglement-europeen-protection-donnees?utm_source=chatgpt.com "Le règlement général sur la protection des données - RGPD"
[3]: https://eur-lex.europa.eu/legal-content/FR/TXT/HTML/?qid=1774474848715&uri=OJ%3AL_202600179&utm_source=chatgpt.com "L_202600179FR.000101.fmx.xml - EUR-Lex"

