# AnnotationPhotoGPT — Utilisation du batch PC fixe

## 1. Objet

Ce document décrit l’utilisation du batch :

`batch_all_photos_pcfixe.py`

ainsi que du script de lancement associé (.bat), dans le cadre du traitement massif des photographies.

---

## 2. Principe général

Le batch fonctionne en deux passes :

### PASS 1 — VLM
- Génère : `description_vlm_batch`
- Source : image

### PASS 2 — LLM
- Génère :
  - `libelle_propose_batch`
  - `commentaire_propose_batch`
- Sources :
  - description VLM
  - transcription audio

---

## 3. Fichier central : CSV batch

Le batch repose sur un fichier :

`photos_batch.csv`

Ce fichier :
- est créé automatiquement s’il n’existe pas
- est mis à jour à chaque exécution

### 3.1 Colonnes principales

#### Données métier
- description_vlm_batch
- libelle_propose_batch
- commentaire_propose_batch

#### Statuts
- batch_status (OK / ERR / SKIP / EMPTY)
- vlm_status

#### Diagnostics
- vlm_err
- llm_err_lib
- llm_err_com

#### Traçabilité
- batch_id
- batch_ts

---

## 4. Règles de fonctionnement

### 4.1 Idempotence

Le batch :
- ne doit pas recalculer inutilement
- s’appuie sur l’état des colonnes pour décider

### 4.2 Source de vérité

Le CSV batch est :
- indépendant du CSV UI
- synchronisé régulièrement

---

## 5. Modes d’exécution (via .bat)

Le script `.bat` permet plusieurs usages.

---

## 6. Cas d’usage principaux

### 6.1 Batch complet

Objectif :
- traiter toutes les photos

Effet :
- remplit toutes les colonnes batch

---

### 6.2 Reprise sur erreurs

Objectif :
- ne traiter que les lignes en échec

Critères typiques :
- batch_status = ERR
- ou champs vides

Effet :
- évite de retraiter les lignes OK

---

### 6.3 Relance LLM uniquement (cas critique)

Objectif :
- recalculer uniquement :
  - libelle
  - commentaire

Sans relancer VLM.

---

#### Colonnes à vider (strict minimum)

- libelle_propose_batch
- commentaire_propose_batch
- llm_err_lib
- llm_err_com

---

#### Colonnes à conserver impérativement

- description_vlm_batch
- vlm_status
- vlm_err

---

#### Risque si mal appliqué

- perte des descriptions VLM
- recalcul inutile et coûteux
- incohérence des résultats

---

### 6.4 Reset complet (cas exceptionnel)

Objectif :
- repartir de zéro

Colonnes à vider :
- toutes les colonnes batch

Risque :
- perte complète du travail

---

## 7. Logique interne du batch

Le traitement repose sur :

- présence / absence de valeurs
- statuts existants
- erreurs précédentes

Exemple :
- si description_vlm_batch vide → VLM relancé
- si libelle vide → LLM relancé

---

## 8. Gestion des erreurs

### 8.1 VLM

- vlm_status = ERR
- vlm_err renseigné

### 8.2 LLM

- llm_err_lib
- llm_err_com

---

## 9. Bonnes pratiques

- ne jamais modifier manuellement :
  - batch_status
  - vlm_status

- toujours sauvegarder le CSV avant reset

- privilégier les relances ciblées (LLM uniquement)

---

## 10. Points critiques

### 10.1 Cohérence des données

Une mauvaise manipulation peut :
- désynchroniser VLM / LLM
- produire des résultats incohérents

---

### 10.2 Synchronisation avec UI

Le CSV batch :
- est indépendant
- mais ses résultats sont exploités dans l’UI et le rapport

---

### 10.3 Performance

- VLM coûteux → éviter recalcul
- LLM plus léger → relance possible

---

## 11. Recommandations

### Priorité d’usage

1. Reprise sur erreurs
2. Relance LLM uniquement
3. Batch complet
4. Reset complet (exceptionnel)

---

## 12. Améliorations possibles

- automatiser relance LLM
- ajout flags explicites dans le .bat
- validation cohérence CSV avant exécution
- journalisation détaillée des décisions

---

## 13. Conclusion

Le batch est un composant critique.

Sa bonne utilisation repose sur :
- la compréhension des colonnes CSV
- la maîtrise des modes de relance
- la limitation des recalculs inutiles