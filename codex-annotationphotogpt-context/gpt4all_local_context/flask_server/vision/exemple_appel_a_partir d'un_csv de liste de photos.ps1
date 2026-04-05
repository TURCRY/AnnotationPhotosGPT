curl.exe -X POST http://PCFIXE_LAN2:4891/vision/describe_batch_csv `
  -H "Authorization: Bearer VOTRE_CLE" `
  -F "model_name=SmolVLM2_2B" `
  -F "context=Constat visuel – expertise bâtiment" `
  -F "prompt=Décrire uniquement les éléments matériels visibles." `
  -F "file=@C:\Exports\photos.csv"
