# 📄 CR Render (compte-rendu DOCX)

## 1. Objet

Ce module correspond au container Docker `cr-render`.

Il transforme les JSON produits par le pipeline compte-rendu en livrables :

* Markdown
* DOCX

---

## 2. Rôle dans l’architecture

Le renderer constitue la **dernière étape du pipeline compte-rendu** :

```
JSON structuré → rendu documentaire (MD / DOCX)
```

Il ne produit pas de contenu métier, mais met en forme des données déjà structurées.

---

## 3. Entrées

* `global_final.json`
* fichiers `sujet_XXX.json`

Ces fichiers doivent respecter strictement le schéma attendu.

---

## 4. Sorties

* document Markdown
* document DOCX final

---

## 5. Routes principales

* `/render?format=md`
* `/render?format=docx`

---

## 6. Contrat JSON (point critique)

Le renderer définit le **schéma JSON attendu en sortie du pipeline compte-rendu**.

👉 Ce schéma est **contractuel**.

Toute modification de :

* structure
* noms de champs
* hiérarchie
* types de données

doit être validée simultanément sur :

* le pipeline (`cr-pipeline`)
* le renderer (`cr-render`)

---

## 7. Points sensibles

* absence de validation tolérante : JSON doit être correct
* dépendance aux clés attendues (resume, themes, actions, etc.)
* cohérence entre `global_final.json` et fichiers par sujet
* ordre logique des sections dans le document final

---

## 8. Règles pour Codex

Interdictions :

* ❌ modifier le schéma JSON sans audit complet
* ❌ supprimer ou renommer des champs utilisés
* ❌ introduire des structures non prévues

Autorisations contrôlées :

* ✅ amélioration du rendu (mise en forme)
* ✅ ajout de champs optionnels rétrocompatibles

---

## 9. Dépendances

* pipeline compte-rendu (`cr-pipeline`)
* structure JSON produite par les passes LLM
* environnement Docker

---

## 10. Principe directeur

→ **le renderer est strictement dépendant du JSON amont**

→ **la stabilité du schéma prime sur l’évolution du rendu**
