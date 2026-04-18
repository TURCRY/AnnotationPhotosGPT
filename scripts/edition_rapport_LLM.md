

* **`generate_word_report.py`** peut être lancé depuis le **laptop** avec un `--infos` pointant vers le `infos_projet.json` de la captation ; il résout les données d’entrée puis écrit le `.docx` dans le dossier canonique de l’affaire. Votre dernière validation métier précise que ce dossier canonique visé est bien `BE_Traitement_captations\<id_captation>\compte_rendu_LLM`. Le script de rapport photo prend bien `--infos` en paramètre et produit un DOCX dans le dossier de sortie canonique dérivé de `id_affaire`, `id_captation` et `root_affaires`. 
* **`render_compte_rendu_from_infos.py`** est lancé côté **PC fixe** avec un `--infos` analogue ; il génère le compte-rendu principal à partir du pipeline JSON puis écrit le `.docx` final dans le même dossier canonique. 

## 1. Exemple pour l’annexe photos, lancée sur le laptop

Cas le plus simple, si le laptop voit le partage réseau :

```powershell
python "C:\AnnotationPhotosGPT\scripts\generate_word_report.py" `
  --infos "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json"
```

Variante avec overrides explicites si vous voulez forcer certains fichiers :

```powershell
python "C:\AnnotationPhotosGPT\scripts\generate_word_report.py" `
  --infos "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" `
  --photos "\\192.168.0.153\Affaires\2025-J38\AE_Expert_captations\accedit-2025-07-03\photos\photos.csv" `
  --batch "\\192.168.0.155\Affaires\2025-J38\AE_Expert_captations\accedit-2025-07-03\photos\batch_photos.csv" `
  --gtp "\\192.168.0.153\Affaires\2025-J38\AE_Expert_captations\accedit-2025-07-03\photos\annotations_GTP_2025-07-03.csv"
```

## 2. Exemple pour le compte-rendu principal, lancé sur le PC fixe

```powershell
python "\\192.168.0.155\GPT4All_Local\scripts\compte-rendu\render_compte_rendu_from_infos.py" `
  --infos "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" `
  --docx-only
```

Variante avec un `render-url` explicite :

```powershell
python "\\192.168.0.155\GPT4All_Local\scripts\compte-rendu\render_compte_rendu_from_infos.py" `
  --infos "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptionsaccedit-2025-07-03\infos_projet.json" `
  --render-url "http://192.168.1.20:8081/render?format=docx" `
  --docx-only
```

Variante plus complète avec overrides :

```powershell
python "\\192.168.0.155\GPT4All_Local\scripts\compte-rendu\render_compte_rendu_from_infos.py" `
  --infos "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\infos_projet.json" `
  --csv "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\transcription.csv" `
  --context "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\contexte_general_compte_rendu.json" `
  --sujets "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\Sujets.xlsx" `
  --participants "\\192.168.0.155\Affaires\2025-J38\AF_Expert_ASR\transcriptions\accedit-2025-07-03\Participants.xlsx" `
  --docx-only
```

## 3. Ce que cela implique concrètement

Oui, le schéma d’exploitation est bien celui-ci :

* **Laptop** : fabrication de l’**annexe photos** via `generate_word_report.py`
* **PC fixe** : fabrication du **compte-rendu principal** via `render_compte_rendu_from_infos.py`
* **Point commun** : les deux scripts partent du même `infos_projet.json`
* **Sortie commune** : les deux `.docx` sont déposés dans le même dossier canonique de captation, pour permettre leur fusion documentaire ensuite

## 4. Point pratique important

Pour que cela marche depuis le laptop, il faut que :

* le chemin `--infos` soit accessible depuis le laptop ;
* le `root_affaires` visé dans `infos_projet.json` soit lui aussi accessible en écriture depuis le laptop ;
* sinon, le script s’exécutera, mais échouera au moment d’écrire le `.docx` dans le dossier canonique.

## 5. Forme canonique que vous pouvez retenir

Vous pouvez retenir cette règle simple :

```text
Même infos_projet.json
→ script photos sur laptop
→ script compte-rendu sur PC fixe
→ deux DOCX rangés dans
<root_affaires>\<id_affaire>\BE_Traitement_captations\<id_captation>\compte_rendu_LLM
```

Sources : paramètres et logique d’orchestration du compte-rendu principal dans `render_compte_rendu_from_infos.py` et rendu DOCX via le service `/render`.

