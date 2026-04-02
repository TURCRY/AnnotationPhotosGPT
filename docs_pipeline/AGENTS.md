# AGENTS.md

Les modifications doivent être minimales et localisées.
Éviter toute refactorisation globale du serveur sans justification explicite.

## 1. Rôle du projet

`GPT4All_Local` est un serveur local Flask d’orchestration IA.
Le point d’entrée principal est `flask_server/gpt4all_flask.py`.

Le projet agrège plusieurs fonctions :

- génération LLM locale via `llama_cpp`
- RAG sur dossiers et stores vectoriels
- mémoire conversationnelle
- OCR
- ASR / diarisation via Voxtral
- VLM / analyse d’images
- scraping et recherche web
- génération d’images via ComfyUI
- pseudonymisation
- exports CSV / SRT / VTT / logs

Les modifications doivent donc être prudentes, locales et compatibles avec l’existant.

---

## 2. Fichier central à analyser en priorité

Avant toute modification, lire en priorité :

- `flask_server/gpt4all_flask.py`
- `helper_paths.py`
- `rag_utils.py`
- `rag_vector_utils.py`
- `rag_memoire_utils.py`
- `ocr_utils.py`
- `voxtral_utils.py`
- `web_search_utils.py`
- `config/config.json`
- `config/paths.json`
- `models_index.json`
- `README.md`
- `architecture.txt`

Si une demande touche une route Flask, un flux métier, un modèle, ou un export, partir d’abord de `gpt4all_flask.py`.

---

## 3. Architecture fonctionnelle constatée

Le script principal n’est pas un simple serveur Flask.
C’est un orchestrateur multi-domaines.

Il comprend notamment :

- chargement centralisé des chemins via `load_paths()`
- lecture des paramètres globaux et par modèle
- gestion dynamique des modèles LLM
- vérification des backends Chroma et Qdrant au démarrage
- résolution de configurations projet / affaire
- règles de nettoyage ASR et d’anti-hallucination
- génération texte, RAG, mémoire, OCR, VLM, scraping web
- gestion des exports et journaux techniques

Les agents doivent considérer que ce fichier a une forte densité fonctionnelle et plusieurs responsabilités transversales.

---

## 4. Routes sensibles

Les routes suivantes sont structurantes et ne doivent pas être modifiées sans analyse d’impact :

- `/chat_llm`
- `/annoter`
- `/annoter_rag`
- `/annoter_rag_vecteur`
- `/annoter_rag_memoire`
- `/annoter_web`
- `/chat_orchestre`
- routes `/vision/*`
- routes `/v1/*`
- routes liées aux embeddings / vectorisation / export
- routes d’upload, pseudonymisation et ASR

Toute modification sur ces routes doit rester minimale, explicite et testable.

---

## 5. Contraintes de modification

Les agents doivent :

- privilégier les changements minimaux ;
- conserver les noms de fichiers, routes et paramètres existants sauf nécessité ;
- éviter les refontes globales ;
- ne pas casser la compatibilité avec les scripts Windows ;
- ne pas modifier les chemins absolus existants sans raison claire ;
- ne pas supprimer une logique de garde-fou, de verrouillage ou de validation sans justification ;
- ne pas introduire de dépendance nouvelle sans nécessité démontrée.

---

## 6. Risques connus à garder en tête

Le projet contient plusieurs zones sensibles :

- gestion du contexte LLM et du budget de tokens ;
- changement dynamique de modèle ;
- concurrence et verrous (`BACKEND_LOCK`, verrous VLM, verrous LLM) ;
- traitement de sorties JSON imparfaites des modèles ;
- pipelines ASR longs et exports ;
- gestion de fichiers sur différents emplacements ;
- compatibilité entre contextes `pcfixe`, `laptop`, `nas` ;
- dépendances à Chroma, Qdrant, ComfyUI, Tesseract et modèles locaux.

Les agents doivent donc éviter les simplifications brutales.

---

## 7. Politique de travail recommandée

Pour toute demande non triviale :

1. identifier les fonctions, routes et helpers concernés ;
2. résumer brièvement le plan d’intervention ;
3. proposer un changement local plutôt qu’une réécriture ;
4. indiquer les impacts potentiels sur :
   - configuration,
   - modèles,
   - chemins,
   - exports,
   - routes appelantes ;
5. vérifier la cohérence des imports et appels existants.

---

## 8. Ce qui est encouragé

- correction locale d’un bug ;
- réduction d’un doublon clairement identifié ;
- amélioration de robustesse ;
- amélioration des messages d’erreur ;
- clarification de noms ou commentaires dans une zone limitée ;
- ajout de validation ciblée ;
- ajout de tests ciblés ;
- meilleure journalisation technique.

---

## 9. Ce qui doit rester exceptionnel

- découpage massif de `gpt4all_flask.py` en plusieurs modules ;
- changement du contrat JSON des routes ;
- changement de structure des payloads ;
- modification de la logique de résolution des chemins projets ;
- remplacement des verrous existants ;
- refonte du pipeline ASR / VLM / RAG ;
- changement global des paramètres de génération.

---

## 10. Configuration et secrets

Les agents ne doivent pas :

- modifier les fichiers `.env` ;
- inventer de clés, secrets ou chemins ;
- exposer de données sensibles dans le code ;
- forcer des chemins spécifiques à une autre machine sans demande expresse.

Ils doivent distinguer :

- configuration versionnée ;
- configuration locale ;
- secrets ;
- chemins dépendant du poste ou du contexte.

---

## 11. Compatibilité système

Le projet est manifestement pensé pour un environnement Windows local avec scripts `.bat` et `.ps1`, mais certains comportements tiennent aussi compte d’autres plateformes.

Toute modification doit préserver en priorité :

- la compatibilité Windows ;
- les lancements existants ;
- les exports CSV compatibles Excel ;
- les conventions de chemins déjà en place.

---

## 12. Style attendu des modifications

- modifications courtes et ciblées ;
- pas de code mort ajouté ;
- pas de commentaires verbeux inutiles ;
- conserver le style local du fichier modifié ;
- expliquer les changements structurants en quelques lignes ;
- signaler explicitement ce qui n’a pas pu être testé.

---

## 13. Règle spéciale sur `gpt4all_flask.py`

Ce fichier est un point névralgique.

Les agents doivent éviter d’y faire simultanément :

- refactorisation,
- correction fonctionnelle,
- changement de comportement,
- ajout de fonctionnalité.

Sauf demande explicite, une intervention dans ce fichier doit viser **un seul objectif principal par itération**.

---

## 14. Sortie attendue des agents

Les agents doivent répondre de manière :

- précise ;
- sobre ;
- prudente ;
- structurée ;
- honnête sur les vérifications réellement faites.

Ils doivent indiquer clairement :

- les fichiers touchés ;
- le risque de régression ;
- les tests recommandés ;
- les points à valider avant fusion.

---

## 15. Principe final

Toute modification doit rester :

- proportionnée à la demande ;
- compréhensible ;
- réversible ;
- localement testable ;
- compatible avec l’architecture actuelle.

## Emplacement des modèles

Les modèles IA **ne sont pas stockés dans ce dépôt Git**.

Ils sont installés localement sur la machine hôte dans :

`C:\GPT4All_Models`

Le fichier décrivant les modèles disponibles est :

`C:\GPT4All_Models\models_index.json`

Ce fichier constitue la **source de vérité** pour la configuration des modèles.

Il décrit notamment :

- les modèles LLM
- les modèles VLM
- les modèles d'embeddings
- les autres modèles locaux
- leurs alias
- leurs chemins

Ce fichier **n’est pas versionné dans le dépôt**.

Une copie de référence peut être présente dans le dépôt :

`config/models_index_reference.json`

Cette copie est uniquement documentaire et permet aux outils d’analyse
(agents IA, Codex, développeurs) de comprendre la structure des modèles.

### Règles pour les agents

Les agents doivent respecter les règles suivantes :

- ne pas supposer que les fichiers de modèles sont présents dans le dépôt ;
- ne jamais proposer de commit contenant des modèles ;
- ne pas coder en dur un chemin vers un modèle ;
- utiliser les helpers de configuration existants pour accéder aux modèles ;
- considérer `models_index.json` comme la source de vérité.



## Cartographie du système

Avant toute modification importante du serveur Flask, consulter :

docs/API_MAP.md
docs/API_MAP.generated.md
docs/MODULE_MAP.generated.md
docs/SYSTEM_DEPENDENCY_GRAPH.generated.md

Ces fichiers décrivent :
- les routes API
- les modules utilisés
- les dépendances internes

## Client externe majeur : LLM_Assistant

Le client `LLM_Assistant` sur laptop appelle directement de nombreuses routes du serveur Flask.

Les routes liées à :
- LLM
- RAG
- Web
- OCR
- ASR
- upload
- prompts
- historique
- PDF

doivent être considérées comme sensibles.

Toute modification doit préserver la compatibilité avec `LLM_Assistant`.

## Clients externes à préserver

Le serveur Flask est appelé par plusieurs clients externes hors dépôt :

- UI d’annotation de photos sur laptop
- OpenWebUI via `openai-adapter` sur NAS
- n8n sur NAS
- AppFlowy via `openai-adapter`
- Paperless via `openai-adapter`
- Langfuse via `openai-adapter`
- NocoDB via `openai-adapter`
- compte-rendu via `openai-adapter`

Services externes utilisés par le serveur :
- SearXNG sur NAS
- Chroma REST
- Qdrant REST
- ComfyUI 



Règles :
- ne pas modifier légèrement ou implicitement le format JSON d’une route exposée ;
- ne pas renommer une route sans justification explicite ;
- préserver la compatibilité des clients externes ;
- documenter toute rupture de compatibilité éventuelle.
- préserver la compatibilité des routes `/comfyui/prompt`, `/comfyui/history`, `/comfyui/image` ;
- considérer ComfyUI comme un service externe dépendant de `COMFY_URL` ;
- éviter toute modification implicite du format de réponse JSON ou des paramètres attendus.