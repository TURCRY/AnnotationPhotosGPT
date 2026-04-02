# Cahier des charges – GPT4All_Local

## 1. Objectif du projet

GPT4All_Local est un serveur local basé sur Flask permettant
d’orchestrer plusieurs capacités d'intelligence artificielle sur une
machine personnelle.

Le système vise à fournir une API locale permettant :

- interrogation de modèles LLM
- recherche augmentée (RAG)
- analyse d’images (VLM)
- OCR
- transcription audio / diarisation
- scraping web
- génération d’images
- pseudonymisation de documents

Le serveur agit comme un **hub IA local**.

---

## 2. Composants principaux

Le point d’entrée principal est :

flask_server/gpt4all_flask.py


Ce module orchestre :

- chargement des modèles LLM
- gestion des embeddings
- RAG sur bases vectorielles
- gestion mémoire conversationnelle
- routes API Flask
- interaction avec les modules spécialisés

Modules principaux :

rag_utils.py
rag_vector_utils.py
rag_memoire_utils.py
ocr_utils.py
voxtral_utils.py
web_scraper.py
web_search_utils.py
pseudonymizer.py


---

## 3. Backends et dépendances

Le serveur peut utiliser :

Vector stores :

- Chroma
- Qdrant

LLM :

- llama_cpp
- GPT4All

Autres composants :

- Tesseract (OCR)
- Voxtral / Whisper
- ComfyUI
- outils de scraping web

---

## 4. Organisation des données

Le système repose sur plusieurs structures :

config/
docs/
flask_server/
scripts/


Configuration :

config/config.json
config/paths.json
models_index.json


---

## 5. Contraintes techniques

Le projet doit :

- fonctionner principalement sous Windows
- rester compatible avec les scripts `.bat`
- supporter plusieurs machines (pc fixe / laptop)
- rester fonctionnel hors connexion internet
- éviter les dépendances lourdes non nécessaires

---

---

## 5. API

Le serveur expose plusieurs routes HTTP permettant
d'interagir avec les capacités IA.

Exemples de routes :

- `/chat_llm`
- `/annoter`
- `/annoter_rag`
- `/annoter_web`

Les routes permettent notamment :

- interrogation de modèles
- annotation de contenus
- recherche augmentée (RAG)
- intégration de données web


## 6. Contraintes de développement

Les évolutions doivent :

- rester compatibles avec l’architecture existante
- éviter les refontes globales
- privilégier des modifications locales
- conserver les routes API existantes

---

## 7. Objectifs d’évolution

Les évolutions prioritaires sont :

- amélioration de la robustesse du serveur
- meilleure gestion des erreurs
- amélioration du RAG
- amélioration du traitement JSON des LLM
- amélioration des pipelines OCR / ASR
- amélioration de la journalisation

---

## 8. Hors périmètre

Ne sont pas prioritaires :

- refonte complète du serveur
- changement d’architecture radical
- migration vers un autre framework web