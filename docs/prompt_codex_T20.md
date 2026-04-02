# PROMPT CODEX — T20 (Pipeline audio / transcription)

## 1. Objectif

Analyser et sécuriser le pipeline de transcription audio utilisé dans AnnotationPhotosGPT.

Ce pipeline alimente indirectement :

* le VLM (contexte)
* le LLM (libellé + commentaire)

---

## 2. Périmètre

Fichiers à analyser :

* `app/traitement_audio.py`
* `app/transcription_utils.py`
* `app/audio_server.py`
* scripts associés dans `scripts/`

---

## 3. Rôle du pipeline audio

```text
audio → transcription → texte → VLM/LLM
```

Le texte produit est une **entrée critique** du système.

---

## 4. Contraintes métier

### 4.1 Fidélité

* ne jamais transformer le sens
* ne pas corriger ou interpréter
* conserver :

  * hésitations
  * incertitudes
  * formulations

---

### 4.2 Neutralité

Le texte doit rester brut :

* pas d’analyse
* pas de reformulation métier
* pas d’inférence

---

### 4.3 Complétude

* ne pas tronquer
* ne pas perdre de segments audio

---

## 5. Problèmes à rechercher

### 5.1 Techniques

* pertes audio
* erreurs de découpage
* problèmes d’encodage
* latence excessive

---

### 5.2 Fonctionnels

* transcription vide
* transcription incohérente
* mauvaise synchronisation audio/photo

---

### 5.3 Pipeline

* dépendance fragile avec LLM
* absence de fallback
* absence de validation

---

## 6. Points critiques à vérifier

* gestion des erreurs ASR
* gestion des timeouts
* cohérence avec CSV
* compatibilité batch / UI

---

## 7. Méthode attendue

1. analyser le pipeline actuel
2. identifier les fragilités
3. proposer :

   * sécurisation
   * fallback
   * logs utiles

---

## 8. Interdictions

* ne pas modifier le format des sorties sans justification
* ne pas casser la compatibilité avec le batch
* ne pas introduire de logique métier dans la transcription

---

## 9. Tâche

Produire :

```text
ANALYSE
PROBLÈMES
PROPOSITION
DIFF
```

---

## 10. Priorité

```text
FIABILITÉ > FIDÉLITÉ > PERFORMANCE
```
