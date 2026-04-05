# poll_history.ps1
$promptId = "196e5978-712d-48a3-a011-d394c53f352a"
$apiKey   = "hy^wQ#4d3HpnEl4x1Mg&"      # si tu passes par le proxy Flask
$flask    = "http://127.0.0.1:5051"     # ton Flask (port de test)
$outFile  = ".\sd_out.png"

for ($i = 0; $i -lt 60; $i++) {
  $raw = curl.exe -s "http://127.0.0.1:8188/history/$promptId"
  if ($raw -and $raw -ne "{}") {
    try { $j = $raw | ConvertFrom-Json } catch { $j = $null }
    if ($j -and $j.$promptId -and $j.$promptId.outputs) {
      # Récupère la 1ère image quelle que soit la clé de nœud (7, 12, etc.)
      $img = $null
      foreach ($node in $j.$promptId.outputs.PSObject.Properties.Value) {
        if ($node.images -and $node.images.Count -gt 0) { $img = $node.images[0]; break }
      }
      if ($img) {
        Write-Host "Image trouvée:" ($img | ConvertTo-Json -Depth 5)
        # Essaie d'abord via le proxy Flask (x-api-key)
        $proxyUrl = "$flask/comfyui/image?filename=$($img.filename)&subfolder=$($img.subfolder)&type=$($img.type)"
        try {
          Invoke-WebRequest -Uri $proxyUrl -Headers @{ "x-api-key" = $apiKey } -OutFile $outFile
          Write-Host "✅ Image téléchargée via Flask -> $outFile"
        } catch {
          # Repli : endpoint natif ComfyUI (pas d’auth)
          $view = "http://127.0.0.1:8188/view?filename=$($img.filename)&subfolder=$($img.subfolder)&type=$($img.type)"
          Invoke-WebRequest -Uri $view -OutFile $outFile
          Write-Host "✅ Image téléchargée via ComfyUI -> $outFile"
        }
        break
      }
    }
  }
  Start-Sleep -Seconds 1
}
