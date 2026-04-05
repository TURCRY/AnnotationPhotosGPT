# test_sd_generate.ps1 -- appel simple a /sd_generate + telechargement de l'image
$ErrorActionPreference = "Stop"

# === CONFIG ===
$BaseUrl = "http://127.0.0.1:5051"
$ApiKey  = "hy^wQ#4d3HpnEl4x1Mg&"
$OutPng  = ".\sd_out.png"

# Corps JSON (on garde les accents mais c'est optionnel)
$bodyObj = @{
  prompt           = "facade XIXe, lumiere du matin"
  negative_prompt  = "flou, artefacts"
  model_key        = "sd15"
  width            = 768
  height           = 768
  n                = 1
  steps            = 20
  cfg              = 6.5
  seed             = 1234
}
$bodyJson = $bodyObj | ConvertTo-Json -Depth 5

$headers = @{
  "x-api-key"   = $ApiKey
  "Content-Type" = "application/json; charset=utf-8"
}

Write-Host "POST $BaseUrl/sd_generate"
$response = Invoke-RestMethod -Uri "$BaseUrl/sd_generate" -Method POST -Headers $headers -Body $bodyJson

$response | ConvertTo-Json -Depth 6 | Write-Output

# Telechargement via le proxy Flask si present
if ($null -ne $response.proxied_urls_abs -and $response.proxied_urls_abs.Count -gt 0) {
  $imgUrl = $response.proxied_urls_abs[0]
  Write-Host "Telechargement: $imgUrl"
  Invoke-WebRequest -Uri $imgUrl -Headers @{ "x-api-key" = $ApiKey } -OutFile $OutPng
  Write-Host "Image enregistree: $OutPng"
}
elseif ($null -ne $response.view_urls -and $response.view_urls.Count -gt 0) {
  Write-Warning ("Pas de proxy Flask. Ouvrir dans le navigateur: " + $response.view_urls[0])
}
else {
  Write-Warning "Aucun lien d'image dans la reponse."
}
