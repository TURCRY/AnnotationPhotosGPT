PROPOSITION NON VALIDÉE

- fichiers concernés : `C:\AnnotationPhotosGPT\batch_pcfixe\batch_all_photos_pcfixe.py`
- objectif : rejeter les sorties VLM manifestement transcriptionnelles avant écriture dans `description_vlm_batch`
- impact : patch minimal sur le PASS 1 VLM, sans changement de CSV ni de pipeline global
- niveau de risque : faible

## Diff proposé

```diff
--- a/C:\AnnotationPhotosGPT\batch_pcfixe\batch_all_photos_pcfixe.py
+++ b/C:\AnnotationPhotosGPT\batch_pcfixe\batch_all_photos_pcfixe.py
@@
+_VLM_BAD_CONTENT_PATTERNS = (
+    r"CONTEXTE\s+TEXTE",
+    r"TRANSCRIPTION\s*\(extrait\)",
+    r"\bSPEAKER_[A-Z0-9_]+\b",
+)
+
+
+def is_bad_vlm_content(desc: str) -> bool:
+    text = str(desc or "").strip()
+    if not text:
+        return False
+    upper_text = text.upper()
+    for pattern in _VLM_BAD_CONTENT_PATTERNS:
+        if re.search(pattern, upper_text, flags=re.IGNORECASE):
+            return True
+    return False
@@
             desc = str(r.get("description") or "").strip()
             if not desc:
                 mark_vlm_err_batch(b, "ERR_VLM_EMPTY", batch_id=current_batch_id)
                 err += 1
                 continue
+            if is_bad_vlm_content(desc):
+                mark_vlm_err_batch(b, "ERR_VLM_BAD_CONTENT", batch_id=current_batch_id)
+                err += 1
+                continue
             ts = now_ts()
             b["description_vlm_batch"] = desc
             b["vlm_status"] = "OK"
@@
         desc = str(r.get("description") or "").strip()
         if not desc:
             mark_vlm_err_batch(b, "ERR_VLM_EMPTY", batch_id=current_batch_id)
             err += 1
             continue
+        if is_bad_vlm_content(desc):
+            mark_vlm_err_batch(b, "ERR_VLM_BAD_CONTENT", batch_id=current_batch_id)
+            err += 1
+            continue
         ts = now_ts()
         b["description_vlm_batch"] = desc
         b["vlm_status"] = "OK"
```

## Justification technique

- Le contrôle est placé exactement au point où `r["description"]` devient `description_vlm_batch`.
- On évite ainsi d'écrire une mauvaise valeur dans le CSV batch.
- `mark_vlm_err_batch(...)` vide déjà `description_vlm_batch` pour les raisons `ERR_VLM*`, donc le comportement reste cohérent.

## Pourquoi ce patch est minimal

- aucune modification du contrat CSV ;
- aucune modification des structures de données ;
- aucune refonte du contexte VLM ;
- aucune dépendance UI ;
- un seul nouveau statut métier/technique : `ERR_VLM_BAD_CONTENT`

## Limites

- Ce patch ne corrige pas la cause amont si le serveur VLM mélange parfois contexte et description ;
- il empêche seulement que cette sortie corrompe `description_vlm_batch`.

## Message de commit recommandé

`Reject transcription-like content in batch VLM descriptions`
