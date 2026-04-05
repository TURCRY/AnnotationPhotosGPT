---

# 📄 Pipeline — Traitements batch PC fixe (NAS → PC fixe → résultats)

---

## 1. Objet

Ce pipeline assure :

* l’exploitation des données copiées depuis le laptop ;
* l’exécution des traitements batch :

  * VLM (analyse images)
  * LLM (génération libellés / commentaires)
  * ASR / compte-rendu (le cas échéant) ;
* la production des résultats exploitables (CSV enrichis, documents).

---

## 2. Position dans l’architecture

```text
Laptop (préparation)
    ↓
Copie initiale
    ↓
NAS (source de vérité)
    ↓
Synchronisation
    ↓
PC fixe (pipeline présent)
    ↓
Résultats (CSV / DOCX / JSON)
```

---

## 3. Principe directeur

```text
Le PC fixe traite les données, il ne les prépare pas.
```

Conséquences :

* aucune reconstruction métier des données sources ;
* utilisation exclusive des fichiers issus du pipeline laptop ;
* dépendance stricte à `infos_projet.json`.

---

## 4. Point d’entrée du pipeline

### Script principal

* `run_all_photos_pcfixe.bat`

### Script cœur

* `batch_all_photos_pcfixe.py`

---

## 5. Entrées obligatoires

Le pipeline suppose la présence des fichiers suivants :

### 5.1 Fichier central

```text
infos_projet.json
```

Contient :

* chemins vers :

  * `photos.csv`
  * `photos_batch.csv`
  * audio
  * contexte
* configuration d’exécution

---

### 5.2 CSV photos

* `photos.csv` (UI)
* `photos_batch.csv` (batch)

Clé commune obligatoire :

```text
photo_rel_native
```

---

### 5.3 Fichiers physiques

* photos (JPG)
* audio (WAV)
* fichiers contexte

---

## 6. Logique du pipeline

### 6.1 Chargement du projet

* lecture de `infos_projet.json`
* validation des chemins
* vérification minimale de présence des fichiers

---

### 6.2 Fusion logique des CSV

* jointure implicite via :

  ```text
  photo_rel_native
  ```

* règles :

  * `photos.csv` = référence utilisateur
  * `photos_batch.csv` = enrichissement batch

---

### 6.3 Traitement VLM

* génération :

  * `description_vlm_batch`
* mise à jour :

  * `vlm_status`
  * `vlm_batch_ts`
  * `vlm_err`

---

### 6.4 Traitement LLM

* génération :

  * `libelle_propose_batch`
  * `commentaire_propose_batch`

* dépend de :

  * description VLM
  * contexte
  * prompts

---

### 6.5 Gestion des erreurs

Colonnes :

* `vlm_err`
* `llm_err_*`

Règles :

* une ligne en erreur ne bloque pas le batch global
* traçabilité ligne par ligne

---

### 6.6 Écriture des résultats

* mise à jour de `photos_batch.csv`
* conservation de l’historique logique
* écriture atomique recommandée

---

## 7. Artefacts produits

* `photos_batch.csv` enrichi
* fichiers logs
* éventuellement :

  * documents Word (`generate_word_report.py`)
  * exports JSON

---

## 8. Clés de cohérence (à ne pas modifier)

Champs critiques :

* `photo_rel_native`
* `id_affaire`
* `id_captation`
* `description_vlm_batch`
* `libelle_propose_batch`
* `commentaire_propose_batch`

Statuts :

* `vlm_status`
* `batch_status`

---

## 9. Règles pour Codex

### Interdictions

* ❌ modifier la structure de `photos_batch.csv`
* ❌ casser la clé `photo_rel_native`
* ❌ réécrire `photos.csv` depuis le batch
* ❌ recalculer les chemins métier

---

### Autorisations

* ✅ optimiser les performances batch
* ✅ améliorer la gestion d’erreurs
* ✅ ajouter logs détaillés
* ✅ permettre relance partielle

---

## 10. Points critiques

* cohérence entre `photos.csv` et `photos_batch.csv`
* qualité des chemins issus de `infos_projet.json`
* dépendance aux fichiers réellement présents
* gestion des reprises (idempotence)

---

## 11. Limites actuelles

* dépendance forte au CSV
* absence de base transactionnelle
* gestion des erreurs perfectible
* reprise partielle encore fragile

---

## 12. Évolutions attendues

* meilleure gestion des statuts batch
* reprise automatique sur erreurs
* intégration avec orchestration globale
* découplage VLM / LLM

---

## 13. Interaction avec le pipeline amont

Le pipeline PC fixe :

* **ne doit jamais corriger les erreurs amont**
* suppose que :

  * les fichiers sont présents
  * les chemins sont corrects
  * `infos_projet.json` est valide

---

## 14. Synthèse

```text
Laptop : prépare
NAS    : centralise
PC fixe: traite
```

Le pipeline PC fixe est **consommateur strict** des données produites en amont.

