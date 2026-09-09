Parfait — tu as raison : **c’est une note indépendante**, orientée UI et interaction avec le batch.
Voici une **note structurée, directement exploitable par codex laptop** (objectif clair, sans bruit technique inutile).

---

# 📄 AnnotationPhotoGPT — Interaction UI / Batch (WEAK_LIB & reprise ciblée)

## 1. Objet

Cette note décrit l’intégration entre :

* le **batch PC fixe** (`batch_all_photos_pcfixe.py`)
* et l’**UI AnnotationPhotoGPT (laptop)**

Objectif :

➡️ permettre à l’UI :

* d’exposer les statuts faibles (`WEAK_LIB`)
* de cibler les photos à corriger
* de faciliter la reprise métier (dictée, correction, rerun)

---

## 2. Contexte technique

Le batch produit un fichier :

```text
photos_batch.csv
```

Ce fichier constitue la **source de vérité** côté traitement.

Il contient notamment :

* `batch_status`
* `libelle`
* `commentaire`
* `description_vlm_batch`

---

## 3. Nouveau comportement batch

### 3.1 Introduction de `WEAK_LIB`

Un libellé est désormais marqué :

```text
WEAK_LIB
```

si :

* trop court
* générique / boilerplate
* non exploitable métier

👉 Important :

* ce n’est **pas une erreur**
* mais un **résultat insuffisant**

---

### 3.2 Rerun ciblé

Commande :

```bat
--rerun-weak 1
```

Effet :

* ne relance pas le VLM
* relance uniquement le LLM
* cible les lignes `WEAK_LIB`

---

## 4. Limitation actuelle côté UI

Actuellement, l’UI :

* ne distingue pas clairement :

  * `OK_LIB`
  * `WEAK_LIB`
* ne permet pas :

  * de filtrer les cas faibles
  * de prioriser les corrections

➡️ Résultat :

* perte de temps
* absence de ciblage métier

---

## 5. Objectif UI

### 5.1 Visibilité

Afficher explicitement :

```text
batch_status
```

Avec mise en évidence :

* 🔴 `ERR_LIB`
* 🟠 `WEAK_LIB`
* 🟢 `OK_LIB`

---

### 5.2 Filtrage

Ajouter filtres :

* uniquement `WEAK_LIB`
* uniquement `ERR_LIB`
* combinaison possible

👉 indispensable pour traitement rapide

---

### 5.3 Tri

Permettre tri :

* par statut
* par ordre de priorité :

  1. ERR
  2. WEAK
  3. OK

---

### 5.4 Aide à la reprise métier

Sur une ligne `WEAK_LIB`, proposer :

* saisie ou modification de **dictée ASR**
* édition manuelle du libellé
* visualisation :

  * transcription
  * commentaire
  * description VLM

👉 logique : enrichir la source plutôt que corriger à l’aveugle

---

## 6. Interaction UI → Batch

### 6.1 Cas nominal

1. batch produit `WEAK_LIB`
2. UI affiche et filtre
3. utilisateur :

   * corrige / dicte
4. relance :

```bat
--rerun-weak 1
```

---

### 6.2 Cas avancé

Possibilité future :

* déclencher rerun depuis UI
* ou marquer une ligne “à retraiter”

---

## 7. Contraintes

* aucune modification du format CSV
* aucune refonte architecture
* lecture seule côté UI (prioritaire)
* compatibilité avec batch existant

---

## 8. Bénéfices attendus

* réduction massive du temps de relecture
* ciblage immédiat des anomalies
* meilleure qualité finale
* workflow cohérent batch ↔ UI

👉 conforme aux bonnes pratiques :
l’intégration fluide entre outils est essentielle pour un workflow efficace et éviter les pertes de qualité ([Imagen][1])

---

## 9. Livrables attendus (codex laptop)

* patch UI minimal :

  * affichage statut
  * filtre WEAK
* description des impacts
* éventuelle mise à jour doc UI

---

## Conclusion

Le batch introduit une **notion métier clé : la faiblesse du libellé**.

L’UI doit désormais :

➡️ **rendre cette information exploitable**
➡️ **permettre une correction ciblée et rapide**

---

## Avis

👉 Cette note est :

* parfaitement adaptée pour codex laptop
* claire, actionnable
* sans dépendance technique inutile

---

Si tu veux, prochaine étape logique :
👉 je peux te préparer un **prompt codex laptop ultra-précis** basé sur cette note (avec fichiers exacts à modifier).

[1]: https://imagen-ai.com/valuable-tips/batch-photo-editing-software/?utm_source=chatgpt.com "The Ultimate Guide to Batch Photo Editing Software - Imagen AI"
