---

# 📄 Pipeline — Copie et préparation des fichiers volumineux (Laptop → NAS / PC fixe)

---

## 1. Objet

Ce pipeline organise :

* la préparation des données issues des captations (photos / audio) ;
* la génération des fichiers de métadonnées nécessaires ;
* la copie des fichiers volumineux vers une destination cible (NAS ou PC fixe).

Il constitue une **étape préalable obligatoire** aux traitements :

* AnnotationPhotoGPT
* pipeline ASR / compte-rendu

---

## 2. Position dans l’architecture

```text
Laptop (préparation)
    ↓
Copie initiale (pipeline présent)
    ↓
NAS (stockage central)
    ↓
Synchronisation (rsync / autre)
    ↓
PC fixe (traitements batch)
```

⚠️ Ce pipeline **ne réalise pas la synchronisation NAS ↔ PC fixe**.

---

## 3. Principe directeur

```text
Le laptop prépare les données, mais ne stocke pas les fichiers volumineux.
```

Conséquences :

* les photos et audio doivent être copiés vers une destination externe ;
* le laptop ne conserve que les métadonnées et fichiers légers.

---

## 4. Point d’entrée du pipeline

### Script principal

* `run_all_from_JPG_v3.bat`

### Conditions d’exécution

* le script doit être lancé depuis :

  ```text
  ...\Photos\JPG
  ```

### Arguments

```text
run_all_from_JPG_v3.bat <ID_AFFAIRE> [ROOT_DST] [MODE]
```

* `ID_AFFAIRE` : ex. `2025-J46`
* `ROOT_DST` : racine cible (NAS ou PC fixe)
* `MODE` : informatif (NAS / PCFIXE)

---

## 5. Hypothèses de structure locale (obligatoires)

Le pipeline suppose :

```text
Captation/
├── Photos/
│   ├── JPG/          ← point d’exécution
│   ├── JPG reduit/
│   └── *.csv
└── Audio/
```

### Nom du dossier de captation

Format obligatoire :

```text
<Slug> JJ MM AAAA
Ex : Accedit 06 11 2025
```

Permet de générer :

```text
id_captation = accedit-2025-11-06
```

---

## 6. Scripts utilisés

### Orchestration

* `run_all_from_JPG_v3.bat`

### Scripts Python (chemin stable)

```text
C:\DevTools\Compression photo\
```

* `pick_ui_csv.py` → sélection du CSV UI
* `mk_photos_batch_min.py` → création du batch minimal
* `batch_photos_post_sync.py` → enrichissement du CSV
* `write_infos_projet.py` → génération `infos_projet.json`

---

## 7. Logique du pipeline

### 7.1 Détection des entrées

* déduction de `id_captation`
* sélection du `photos.csv` (UI)
* exclusion stricte :

  * `photos_batch.csv`
  * fichiers `_batch`
  * fichiers `_GTP_`

---

### 7.2 Préparation des CSV

#### `photos.csv`

* enrichi avec :

  * `id_affaire`
  * `id_captation`
  * chemins relatifs (`photo_rel_*`)
  * chemins destination (`*_pcfixe`)
  * statut de disponibilité

#### `photos_batch.csv`

* créé si absent
* contient les colonnes batch minimales

---

### 7.3 Mise à jour post-synchronisation

Script :

```text
batch_photos_post_sync.py
```

Rôle :

* calcul des chemins destination
* vérification de présence des fichiers
* mise à jour des flags de disponibilité

---

### 7.4 Copie des fichiers volumineux

#### Photos

* JPG natifs
* JPG réduits (si présents)
* CSV / XLS associés

#### Audio

* WAV (source et mono16)
* transcriptions
* contextes
* annexes

---

### 7.5 Génération `infos_projet.json`

Script :

```text
write_infos_projet.py
```

Produit :

* version laptop
* version destination

Contient notamment :

* chemins sources
* chemins destination
* configuration LLM
* fichiers audio
* fichiers CSV

---

## 8. Structure cible (destination)

```text
<ROOT_DST>/<ID_AFFAIRE>/

├── AE_Expert_captations/<ID_CAPTATION>/
│   ├── photos/
│   │   ├── JPG/
│   │   └── JPG reduit/
│   └── audio/
│
└── AF_Expert_ASR/transcriptions/<ID_CAPTATION>/
```

---

## 9. Artefacts obligatoires en sortie

Après exécution, doivent exister :

* `photos.csv`
* `photos_batch.csv`
* `infos_projet.json`
* fichiers photos copiés
* fichiers audio copiés

---

## 10. Clés de cohérence (à ne pas modifier)

Les champs suivants sont structurants :

* `id_affaire`
* `id_captation`
* `photo_rel_native`
* `photo_rel_reduite`
* `fichier_photos`
* `fichier_photos_batch`
* `fichier_audio_source`
* `fichier_audio_compatible`

Structure critique :

```json
pcfixe: {
  ...
}
```

⚠️ Toute modification de ces champs nécessite un audit global.

---

## 11. Règles pour Codex

### Interdictions

* ❌ considérer le laptop comme stockage principal
* ❌ modifier la structure des chemins
* ❌ altérer `infos_projet.json` sans analyse globale
* ❌ fusionner copie et synchronisation NAS

---

### Autorisations

* ✅ améliorer robustesse des scripts
* ✅ ajouter logs
* ✅ sécuriser les copies (robocopy, retries)
* ✅ externaliser la logique Python

---

## 12. Points critiques

* cohérence des chemins relatifs
* exactitude de `id_captation`
* sélection correcte du CSV UI
* duplication de fichiers
* complétude des copies
* dépendance à la structure locale

---

## 13. Limites actuelles

* dépendance à des scripts `.bat`
* absence de vérification automatique de complétude
* absence de contrôle d’intégrité (hash)
* traçabilité partielle

---

## 14. Évolutions attendues

* unification des scripts Python (moins de logique inline)
* vérification automatique post-copie
* centralisation des logs
* intégration avec orchestration (ex : n8n)

---

## 15. Synthèse

```text
Laptop : prépare
NAS    : centralise
PC fixe: traite
```

Ce pipeline assure le passage **du monde local vers l’infrastructure de traitement**, sans ambiguïté sur les responsabilités.

---