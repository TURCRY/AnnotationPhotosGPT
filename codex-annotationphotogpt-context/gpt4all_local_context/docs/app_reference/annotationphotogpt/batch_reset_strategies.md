# AnnotationPhotoGPT — Stratégies de reset du batch

## 1. Objet

Ce document décrit les stratégies de remise à zéro (partielle ou complète) du fichier :

`photos_batch.csv`

Objectif :
- relancer le batch de manière ciblée
- éviter les recalculs inutiles
- préserver les données pertinentes

---

## 2. Principe fondamental

Le batch décide de recalculer en fonction :
- des champs vides
- des statuts
- des erreurs

👉 Donc :
**reset = modification contrôlée des colonnes CSV**

---

## 3. Typologie des resets

| Type de reset        | Impact        | Risque | Usage recommandé |
|---------------------|--------------|--------|------------------|
| LLM uniquement      | faible       | faible | fréquent         |
| VLM + LLM           | moyen        | moyen  | ponctuel         |
| complet             | élevé        | fort   | exceptionnel     |

---

## 4. Reset LLM uniquement (cas principal)

### 4.1 Objectif

Relancer uniquement :
- libelle
- commentaire

---

### 4.2 Colonnes à vider

- libelle_propose_batch
- commentaire_propose_batch
- llm_err_lib
- llm_err_com
- llm_http_status_lib
- llm_http_status_com
- llm_trace_lib
- llm_trace_com

---

### 4.3 Colonnes à conserver

- description_vlm_batch
- vlm_status
- vlm_err
- vlm_batch_id
- vlm_batch_ts

---

### 4.4 Effet attendu

- VLM non relancé
- LLM relancé uniquement

---

### 4.5 Cas d’usage

- erreurs LLM
- prompt modifié
- amélioration de génération

---

## 5. Reset ciblé par type d’erreur

### 5.1 Cas : `llm_err_lib` uniquement

Colonnes à vider :
- libelle_propose_batch
- llm_err_lib
- llm_http_status_lib
- llm_trace_lib

---

### 5.2 Cas : `llm_err_com` uniquement

Colonnes à vider :
- commentaire_propose_batch
- llm_err_com
- llm_http_status_com
- llm_trace_com

---

### 5.3 Avantage

- relance ultra ciblée
- gain de temps important

---

## 6. Reset VLM + LLM

### 6.1 Objectif

Recalcul complet d’une photo

---

### 6.2 Colonnes à vider

- description_vlm_batch
- libelle_propose_batch
- commentaire_propose_batch

- vlm_err
- vlm_status

- llm_err_lib
- llm_err_com

---

### 6.3 Effet

- VLM relancé
- LLM relancé

---

### 6.4 Cas d’usage

- image incorrectement traitée
- problème VLM
- changement de modèle VLM

---

## 7. Reset complet

### 7.1 Objectif

Repartir de zéro

---

### 7.2 Colonnes à vider

Toutes les colonnes batch :

- description_vlm_batch
- libelle_propose_batch
- commentaire_propose_batch
- batch_status
- batch_id
- batch_ts
- vlm_status
- vlm_err
- llm_err_*

---

### 7.3 Risques

- perte totale des résultats
- coût de recalcul élevé

---

## 8. Reset basé sur filtres (très recommandé)

### 8.1 Par statut

Exemples :

- batch_status = ERR
- batch_status = EMPTY

---

### 8.2 Par contenu

- description vide
- libelle vide
- commentaire vide

---

### 8.3 Exemple logique

Relancer uniquement si :
- libelle vide
- OU llm_err non vide

---

## 9. Stratégies recommandées

### 9.1 Cas standard

→ Reset LLM uniquement

---

### 9.2 Cas erreurs mixtes

→ Reset ciblé par colonne

---

### 9.3 Cas doute global

→ Reset VLM + LLM

---

### 9.4 Cas extrême

→ Reset complet

---

## 10. Procédure sécurisée

Avant reset :

1. sauvegarder le CSV
2. vérifier le périmètre (nombre de lignes impactées)
3. appliquer le reset
4. relancer le batch

---

## 11. Erreurs fréquentes

- suppression de description_vlm_batch par erreur
- reset global non nécessaire
- modification manuelle des statuts

---

## 12. Recommandation clé

👉 Toujours privilégier :

**reset minimal suffisant**

---

## 13. Automatisation possible

À implémenter :

- script Python de reset automatique
- interface UI pour relance ciblée
- flags dans le .bat

---

## 14. Conclusion

Le reset est un outil puissant mais sensible.

Une bonne stratégie permet :
- gain de temps
- stabilité du pipeline
- qualité des annotations