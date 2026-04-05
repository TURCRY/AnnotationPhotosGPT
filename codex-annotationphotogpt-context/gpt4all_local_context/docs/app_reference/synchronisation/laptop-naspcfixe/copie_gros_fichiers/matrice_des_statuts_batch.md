
---

# 📄 Matrice des statuts batch & stratégie de reprise

---

## 1. Objectif

Garantir que le pipeline :

```text
peut être relancé à tout moment sans incohérence ni duplication
```

---

## 2. Principe d’idempotence

```text
Une ligne déjà traitée correctement ne doit jamais être retraitée inutilement.
```

Donc :

* traitement **conditionné par les statuts**
* aucune régression sur données valides
* possibilité de reprise partielle

---

## 3. Statuts principaux (photos_batch.csv)

## 3.1 VLM

| Colonne    | Valeurs | Signification         |
| ---------- | ------- | --------------------- |
| vlm_status | empty   | non traité            |
| vlm_status | ok      | succès                |
| vlm_status | err     | erreur                |
| vlm_status | skip    | ignoré volontairement |

---

## 3.2 LLM

| Colonne      | Valeurs | Signification |
| ------------ | ------- | ------------- |
| batch_status | empty   | non traité    |
| batch_status | ok      | succès        |
| batch_status | err     | erreur        |
| batch_status | partial | incomplet     |

---

## 3.3 Erreurs

| Colonne   | Contenu     |
| --------- | ----------- |
| vlm_err   | message VLM |
| llm_err_* | message LLM |

---

## 4. Matrice de décision (traitement)

## 4.1 VLM

| Condition        | Action    |
| ---------------- | --------- |
| vlm_status empty | traiter   |
| vlm_status err   | retraiter |
| vlm_status ok    | ignorer   |
| vlm_status skip  | ignorer   |

---

## 4.2 LLM

| Condition            | Action    |
| -------------------- | --------- |
| batch_status empty   | traiter   |
| batch_status err     | retraiter |
| batch_status partial | retraiter |
| batch_status ok      | ignorer   |

---

## 5. Règles de priorité

```text
LLM dépend toujours du VLM
```

Donc :

* si VLM non OK → LLM interdit
* si VLM OK → LLM autorisé

---

## 6. Stratégies de reprise

## 6.1 Reprise automatique

Cas standard :

```text
Relancer le batch complet
→ seules les lignes non OK sont traitées
```

---

## 6.2 Reprise VLM seule

Action :

```text
vider :
- vlm_status
- vlm_err
```

Effet :

* recalcul VLM uniquement
* LLM sera relancé ensuite si dépendance

---

## 6.3 Reprise LLM seule

Action :

```text
vider :
- batch_status
- libelle_propose_batch
- commentaire_propose_batch
- llm_err_*
```

Effet :

* VLM conservé
* recalcul LLM uniquement

---

## 6.4 Reprise forcée complète

Action :

```text
vider :
- vlm_status
- batch_status
- toutes colonnes batch
```

Effet :

* recalcul total

---

## 7. Gestion des erreurs

## 7.1 Principe

```text
Une erreur ne bloque jamais le batch global
```

Chaque ligne est indépendante.

---

## 7.2 Typologie

| Type | Exemple          |
| ---- | ---------------- |
| VLM  | image illisible  |
| LLM  | prompt trop long |
| FS   | fichier absent   |

---

## 7.3 Traitement

* statut → `err`
* message → colonne `*_err`
* ligne → retraitable

---

## 8. Sécurité des écritures

### Règle

```text
écriture atomique obligatoire
```

Exemple :

* écrire dans fichier temporaire
* remplacer fichier final

---

## 9. Anti-corruption des données

### Interdictions

* ❌ écraser une ligne `ok`
* ❌ supprimer `photo_rel_native`
* ❌ modifier les chemins

---

### Autorisations

* ✅ enrichir lignes
* ✅ corriger erreurs
* ✅ ajouter colonnes

---

## 10. Cas particuliers

### 10.1 Fichier manquant

```text
→ vlm_status = err
→ message explicite
```

---

### 10.2 Image modifiée

Option (avancé) :

* recalcul hash image
* si hash différent → retraitement

---

### 10.3 Changement de prompt

```text
→ invalide LLM
→ relancer LLM uniquement
```

---

## 11. Optimisation possible

* traitement parallèle
* batch par paquets
* cache VLM
* cache embeddings

---

## 12. Synthèse opérationnelle

```text
VLM ok → LLM autorisé
VLM err → VLM à refaire
LLM err → LLM à refaire
OK → ne jamais retraiter
```

---

## 13. Règles pour Codex

### Interdictions

* ❌ retraiter lignes OK
* ❌ casser dépendance VLM → LLM
* ❌ supprimer statuts

---

### Autorisations

* ✅ améliorer logique de reprise
* ✅ ajouter statuts intermédiaires
* ✅ optimiser conditions

---

## 14. Résultat attendu

Un pipeline :

* **relançable à tout moment**
* **sans duplication**
* **sans corruption**
* **avec traçabilité complète**

---

