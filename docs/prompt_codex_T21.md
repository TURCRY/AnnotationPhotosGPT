# PROMPT CODEX — T21 (Architecture distribuée)

## 1. Objectif

Analyser et stabiliser l’architecture globale :

* Laptop
* NAS
* PC fixe

---

## 2. Architecture réelle

```text
Laptop (UI)
    ↓
NAS (stockage / synchro)
    ↓
PC fixe (batch VLM / LLM)
```

---

## 3. Composants

### Laptop

* `app/`
* `scripts/`

### PC fixe

* `batch_pcfixe/`

### NAS

* dossiers partagés
* fichiers CSV
* photos
* audio

---

## 4. Flux principaux

### Pipeline photo

```text
photo → NAS → PC fixe → VLM → LLM → CSV → Laptop
```

---

### Pipeline audio

```text
audio → transcription → CSV → LLM
```

---

## 5. Problèmes typiques à analyser

### Synchronisation

* fichiers non synchronisés
* conflits de version CSV
* latence NAS

---

### Cohérence

* divergence laptop / PC fixe
* double traitement
* états incohérents

---

### Robustesse

* crash batch
* interruption réseau
* traitement partiel

---

## 6. Contraintes critiques

### 6.1 Idempotence globale

* une photo ne doit être traitée qu’une fois
* un CSV ne doit pas être corrompu

---

### 6.2 Résilience

* reprise après crash
* reprise partielle
* gestion des états intermédiaires

---

### 6.3 Traçabilité

* logs exploitables
* statut clair des traitements

---

## 7. batch_pcfixe (CRITIQUE)

Rappel :

* code de production réel
* référence du pipeline

Interdictions :

* modification sans analyse
* divergence avec `app/`

---

## 8. Objectifs Codex

Identifier :

* points de fragilité
* incohérences architecturelles
* risques de désynchronisation

Proposer :

* améliorations simples
* sécurisation
* meilleure séparation des responsabilités

---

## 9. Améliorations attendues

* meilleure gestion des états
* clarification des rôles
* robustesse réseau
* logs centralisés

---

## 10. Interdictions

* refonte complète
* modification brutale architecture
* suppression de composants

---

## 11. Format attendu

```text
ANALYSE
RISQUES
PROPOSITION
DIFF (si applicable)
```

---

## 12. Priorité

```text
COHÉRENCE > ROBUSTESSE > SIMPLICITÉ
```
