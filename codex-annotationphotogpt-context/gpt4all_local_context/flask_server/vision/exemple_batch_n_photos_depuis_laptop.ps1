$api="http://PCFIXE_LAN2:4891/vision/describe_batch"
$headers=@{ "Authorization"="Bearer VOTRE_CLE" }

$form = @{
  model_name   = "SmolVLM2_2B"
  context      = "Inspection chantier - lot plomberie. Rechercher anomalies visibles."
  prompt       = "Précise les éléments matériels (fuites, corrosion, traces, appareils)."
  contexts_json = '{"0":"Photo cuisine","1":"Photo SDB"}'
}

curl.exe -X POST $api `
  -H "Authorization: Bearer VOTRE_CLE" `
  -F "model_name=$($form.model_name)" `
  -F "context=$($form.context)" `
  -F "prompt=$($form.prompt)" `
  -F "contexts_json=$($form.contexts_json)" `
  -F "files=@C:\Photos\img0.jpg" `
  -F "files=@C:\Photos\img1.jpg"
