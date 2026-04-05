# 📄 `pipeline_compte_rendu.md`

---

# 1. Objet

Le pipeline `cr_reunion_point_numerotes_pipeline_json.ps1` constitue :

👉 **la chaîne complète de transformation d’une transcription ASR en compte-rendu structuré JSON**

Il orchestre :

* segmentation du verbatim
* enrichissement par LLM (3 passes successives)
* agrégation globale
* structuration finale exploitable (JSON strict)

⚠️ Le script **ne produit pas directement du Markdown ou DOCX**, mais un JSON final destiné au renderer Flask.

---

# 2. Entrées

## 2.1 Donnée principale

* Fichier CSV ASR :

  * colonnes typiques : timecode / speaker / texte
  * constitue la **source de vérité**

## 2.2 Paramètres

* `OutDir` : dossier de sortie
* `Provider` : local / remote
* `Model` : modèle LLM utilisé
* `Preset` : réglage d’équilibre

## 2.3 Contraintes

* horodatage = référence absolue (non modifiable)
* texte = brut ASR (non interprété à ce stade)

---

# 3. Étapes du pipeline

---

## Étape 1 — Segmentation

### Objectif

Découper la transcription en segments cohérents.

### Logique

* regroupement par continuité temporelle / thématique
* taille contrôlée (éviter dépassement tokens)

### Sortie

* `segments/segment_XX.json`

Structure :

```json
{
  "segment_id": "...",
  "interventions": [
    {
      "timecode": "...",
      "auteur": "...",
      "texte": "..."
    }
  ]
}
```

---

## Étape 2 — Passe 1 (annotation segmentaire)

### Route utilisée

👉 via adapter :

* modèle : `annoter_segments_local` ou `annoter_segments_remote`
* route réelle Flask : `/annoter_segments` 

### Objectif

Transformer chaque segment en :

* résumé
* thèmes
* actions
* problèmes

### Format attendu (STRICT)

```json
{
  "resume_segment": "",
  "themes": [],
  "actions": [],
  "problems": []
}
```

### Points critiques

* JSON obligatoire (mode forcé côté adapter)
* normalisation automatique si sortie imparfaite
* fallback JSON si erreur LLM 

---

## Étape 3 — Passe 2 (agrégation globale)

### Objectif

Fusionner les segments annotés en vision globale :

* résumé global
* consolidation thèmes
* actions globales
* problèmes

### Modèles utilisés

* `report_remote` (+ fallback)

Routes associées (via adapter) :
- report
- pass3

### Format attendu

```json
{
  "resume_global": "",
  "themes": [],
  "themes_abordes": [],
  "actions": [],
  "perspectives": [],
  "demandes_documents_globales": [],
  "problems": []
}
```

### Particularité

* dépendance directe de la qualité de la passe 1
* aucune reconstruction du texte source

---

## Étape 4 — Passe 3 (finalisation)

### Objectif

Structurer le rapport final exploitable :

* hiérarchisation
* enrichissement logique
* mise en cohérence

### Modèle

* `pass3_remote`

Routes associées (via adapter) :
- report
- pass3

### Contraintes fortes

* JSON strict obligatoire
* extraction forcée du bloc JSON côté adapter
* rejet si sortie invalide 

---

## Étape 5 — (optionnelle) Découpage par sujets

Script :

* `split_by_sujet.py` 

### Objectif

* regrouper les interventions par sujet
* produire fichiers exploitables pour analyse fine

---

# 4. Sorties

## 4.1 Fichiers intermédiaires

* `segments/segment_XX.json`
* `global.json`

## 4.2 Sortie finale

* `global_final.json`

### Destination

* rendu via Flask `/render` (Markdown ou DOCX) 

---

# 5. Dépendances

## 5.1 Adapter FastAPI

Rôle :

* abstraction LLM
* fallback automatique
* normalisation JSON

Éléments clés :

* `MODEL_REGISTRY`
* `LOCAL_ROUTE_MAP`
* `_remote_chat_with_retry` 

---

## 5.2 Route critique

### `/annoter_segments`

* cœur de la passe 1
* impose structure JSON segmentaire

---

## 5.3 Backend Flask

* `/render` :

  * validation JSON
  * génération Markdown / DOCX 

---

# 6. Gestion des erreurs

## 6.1 Niveau adapter

* retry automatique (timeouts, 5xx)
* fallback multi-modèles
* détection sortie vide
* réparation JSON partielle

## 6.2 Fallback structuré

Exemple passe 1 :

```json
{
  "resume_segment": "",
  "themes": [],
  "actions": [],
  "problems": []
}
```

## 6.3 Cas critiques

* JSON invalide → rejet / retry
* sortie vide → fallback
* modèle indisponible → cascade fallback

---

# 7. Points sensibles

## 7.1 JSON strict

* aucune tolérance côté pipeline
* parsing renforcé côté adapter

## 7.2 Ordre des passes

⚠️ impératif :

1 → 2 → 3

Toute inversion casse :

* cohérence globale
* agrégation

## 7.3 Dépendances implicites

* Passe 2 dépend **structure** passe 1
* Passe 3 dépend **complétude** passe 2

---

## 7.4 Horodatage

* ne doit jamais être modifié
* sert de référence probatoire

---

# 8. Règles pour Codex

## Interdictions

* ❌ modifier l’ordre des passes
* ❌ changer les schémas JSON sans audit global
* ❌ supprimer une clé obligatoire
* ❌ modifier la logique de fallback

## Autorisations contrôlées

* ✅ amélioration des prompts
* ✅ optimisation segmentation
* ✅ ajout champs (si rétrocompatibles)

## Bonnes pratiques

* toujours valider JSON en sortie
* conserver compatibilité adapter
* tester chaque passe isolément

---

# 9. Point d’extension futur

## doc_uid / traçabilité

Prévu pour :

* rattachement aux pièces
* audit juridique
* reconstruction des sources

À injecter :

* niveau segment
* niveau sujet
* niveau global

---

# Conclusion

Le pipeline constitue :

👉 **une chaîne déterministe assistée par LLM, sous contrainte JSON stricte**

Son bon fonctionnement repose sur :

* stabilité des schémas
* robustesse du fallback
* séparation stricte des passes

---

👉 chaîne déterministe dans sa structure,
mais non déterministe dans son contenu (LLM),
contrainte par des schémas JSON stricts

Le JSON final doit rester strictement compatible avec le renderer (cr-render).
Toute modification de structure doit être validée des deux côtés.

Le pipeline doit pouvoir être relancé sans produire d’incohérences majeures.