# 📄 tache_codex_annotation_photo.md

## 1. Objet

Stabiliser, fiabiliser et préparer l’industrialisation du pipeline **AnnotationPhotoGPT**, en respectant :

* l’architecture actuelle (UI laptop / batch PC fixe / NAS)
* la dépendance au serveur Flask (`/annoter`)
* la logique métier (neutralité, non-régression, traçabilité)

---

## 2. Règles impératives pour Codex

Avant toute modification :

* ne pas modifier `/annoter` sans vérifier le pipeline batch
* ne pas casser la structure des dossiers affaire
* ne pas modifier les clés CSV existantes sans audit
* ne pas écraser une annotation validée (`annotation_validee`)
* privilégier des modifications locales, testables et réversibles

---

## 3. Priorité P1 — Fiabilité des données

* [ ] garantir unicité de `photo_rel_native`
* [ ] sécuriser le merge UI / batch
* [ ] empêcher toute régression sur annotations validées
* [ ] vérifier cohérence des timestamps (audio / photo)
* [ ] normaliser les colonnes obligatoires CSV
* [ ] ajouter un versionning léger des CSV

---

## 4. Priorité P2 — Robustesse du batch

* [ ] améliorer gestion erreurs VLM
* [ ] améliorer gestion erreurs LLM
* [ ] isoler clairement PASS VLM / PASS LLM
* [ ] implémenter retry robuste (backoff + limites)
* [ ] garantir idempotence du batch
* [ ] améliorer statuts : OK / ERR / SKIP / EMPTY

---

## 5. Priorité P3 — Stratégie de relance

* [ ] fiabiliser relance LLM uniquement
* [ ] fiabiliser reset ciblé par colonne
* [ ] éviter tout recalcul VLM inutile
* [ ] ajouter outils de relance semi-automatique
* [ ] journaliser les relances

---

## 6. Priorité P4 — Synchronisation multi-machines

* [ ] fiabiliser synchronisation NAS ↔ PC fixe ↔ laptop
* [ ] centraliser gestion des chemins (UNC / local)
* [ ] détecter conflits de fichiers
* [ ] vérifier cohérence des fichiers après sync
* [ ] journaliser les opérations de synchronisation

---

## 7. Priorité P5 — Audio et synchronisation temporelle

* [ ] vérifier systématiquement la compatibilité WAV
* [ ] optimiser cache audio (éviter reconversion)
* [ ] améliorer détection des décalages audio/photo
* [ ] ajouter recalibrage automatique
* [ ] gérer proprement les erreurs ffmpeg

---

## 8. Priorité P6 — Qualité LLM / VLM

* [ ] harmoniser prompts interactif / batch
* [ ] renforcer validation automatique des sorties
* [ ] améliorer détection des réponses parasites (boilerplate)
* [ ] améliorer heuristiques anti-hallucination
* [ ] ajouter logs détaillés VLM / LLM

---

## 9. Priorité P7 — Données et CSV

* [ ] normaliser structure CSV UI / batch
* [ ] documenter toutes les colonnes
* [ ] sécuriser écriture (atomic write)
* [ ] éviter incohérences UI / batch
* [ ] ajouter contrôles de cohérence avant traitement

---

## 10. Priorité P8 — Interface utilisateur

* [ ] renforcer verrouillage des annotations validées
* [ ] afficher différences UI vs batch
* [ ] ajouter indicateurs de statut par photo
* [ ] améliorer outils de correction rapide
* [ ] ajouter historique des modifications

---

## 11. Priorité P9 — Export et livrables

* [ ] stabiliser génération Word
* [ ] fiabiliser insertion images et légendes
* [ ] structurer les sorties documentaires
* [ ] préparer export PDF (optionnel)

---

## 12. Priorité P10 — Logs et traçabilité

* [ ] logs structurés (format JSON recommandé)
* [ ] traçabilité par photo et par batch
* [ ] journal des erreurs exploitable
* [ ] suivi des traitements (timestamps)

---

## 13. Priorité P11 — Performance

* [ ] optimiser traitement batch images
* [ ] améliorer parallélisme (contrôlé)
* [ ] réduire latence LLM
* [ ] mettre en cache les résultats stables

---

## 14. Priorité P12 — Qualité logicielle

* [ ] ajouter tests unitaires (CSV, merge, batch)
* [ ] isoler logique métier / UI / batch
* [ ] introduire couches :

  * DataManager
  * SyncManager
  * BatchClient
* [ ] documenter API interne

---

## 15. Priorité P13 — Industrialisation

* [ ] script de déploiement
* [ ] préparation dockerisation
* [ ] monitoring (logs + alertes)
* [ ] préparation intégration n8n (à terme)

---

## 16. Dépendances critiques

Ce pipeline dépend de :

* serveur Flask GPT4All_Local
* route `/annoter`
* structure des dossiers affaire
* synchronisation NAS / PC fixe / laptop

Toute modification de ces éléments doit être validée.

---

## 17. Risques principaux

* écrasement d’annotations validées
* désynchronisation UI / batch
* incohérence des chemins
* erreurs silencieuses LLM/VLM
* perte de données CSV

---

## 18. Livrables attendus Codex

* refactor minimal non régressif
* amélioration de la robustesse batch
* amélioration de la traçabilité
* documentation mise à jour
* compatibilité maintenue avec l’existant

---

## 19. Définition de terminé (Definition of Done)

Une tâche est terminée si :

* le code est exécutable
* les entrées / sorties sont explicites
* les erreurs sont gérées
* les logs sont exploitables
* le pipeline complet reste fonctionnel
* aucune régression métier n’est introduite

---

## 20. Principe directeur

Le système doit privilégier :

→ **la robustesse et la traçabilité avant la performance**

→ **la relance minimale nécessaire plutôt que le recalcul complet**

→ **la protection des données validées avant toute optimisation**
