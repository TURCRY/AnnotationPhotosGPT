Param(
  [Parameter(Mandatory=$true)]
  [string]$SujetsXlsx,              # Sujets.xlsx

  [Parameter(Mandatory=$true)]
  [string]$SujetsJsonDir,           # dossier contenant sujet_0nn.json

  [Parameter(Mandatory=$false)]
  [string]$SujetsSyntheseDir,       # dossier contenant sujet_0nn_synthese.json (3E)

  [Parameter(Mandatory=$true)]
  [string]$OutCsv,

  [string]$Delimiter = ";",
  [int]$MaxInterventions = 15       # limite verbatims pour ne pas exploser le texte
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function NormText([string]$s) {
  if ($null -eq $s) { return "" }
  $t = $s.ToString().Trim()
  if ($t.Length -eq 0) { return "" }
  $t = $t -replace "\r\n", "`n"
  $t = $t -replace "[ \t]+", " "
  $t = $t -replace "\n{3,}", "`n`n"
  return $t.Trim()
}

function AddBlock([System.Collections.Generic.List[string]]$blocks, [string]$label, [string]$value) {
  $v = NormText $value
  if ($v.Length -gt 0) {
    $blocks.Add("$label: $v") | Out-Null
  }
}

# ------------------------------------
# 1) Lecture Sujets.xlsx
# ------------------------------------
# Nécessite module ImportExcel (Install-Module ImportExcel si besoin)
if (-not (Get-Module -ListAvailable -Name ImportExcel)) {
  throw "Module ImportExcel requis (Install-Module ImportExcel)"
}

$sujets = Import-Excel -Path $SujetsXlsx
if (-not $sujets -or $sujets.Count -eq 0) {
  throw "Sujets.xlsx vide"
}

$outRows = New-Object System.Collections.Generic.List[object]

foreach ($s in $sujets) {

  $numero = NormText $s.numero
  if ($numero.Length -eq 0) { continue }

  $titre        = NormText $s.titre
  $localisation = NormText $s.localisation
  $description  = NormText $s.description

  # ------------------------------------
  # 2) Charger sujet_0nn.json
  # ------------------------------------
  $jsonFile = Join-Path $SujetsJsonDir ("sujet_{0:D3}.json" -f [int]$numero)
  $interventions = @()
  $hasEvidence = $false

  if (Test-Path $jsonFile) {
    $json = Get-Content $jsonFile -Raw | ConvertFrom-Json
    if ($json.interventions) {
      $interventions = $json.interventions
      if ($interventions.Count -gt 0) { $hasEvidence = $true }
    }
  }

  # ------------------------------------
  # 3) Charger synthèse 3E si dispo
  # ------------------------------------
  $syntheseText = ""
  $conclusionText = ""
  $synthFile = $null

  if ($SujetsSyntheseDir) {
    $synthFile = Join-Path $SujetsSyntheseDir ("sujet_{0:D3}_synthese.json" -f [int]$numero)
    if (Test-Path $synthFile) {
      $syn = Get-Content $synthFile -Raw | ConvertFrom-Json
      $syntheseText  = NormText $syn.synthese_echanges
      $conclusionText = NormText $syn.conclusion_expert
    }
  }

  # ------------------------------------
  # 4) Construction champ text
  # ------------------------------------
  $blocks = New-Object System.Collections.Generic.List[string]

  AddBlock $blocks "SUJET" "Sujet $numero"
  AddBlock $blocks "TITRE" $titre
  AddBlock $blocks "LOCALISATION" $localisation
  AddBlock $blocks "DESCRIPTION" $description
  AddBlock $blocks "SYNTHESE" $syntheseText
  AddBlock $blocks "CONCLUSION" $conclusionText

  # Ajouter verbatims limités
  if ($interventions.Count -gt 0) {
    $count = 0
    foreach ($iv in $interventions) {
      if ($count -ge $MaxInterventions) { break }
      $txt = NormText $iv.texte
      if ($txt.Length -gt 0) {
        AddBlock $blocks "VERBATIM" $txt
        $count++
      }
    }
  }

  $text = ($blocks -join "`n")

  # ------------------------------------
  # 5) Statistiques timecodes
  # ------------------------------------
  $countOk = 0
  $countMissing = 0

  foreach ($iv in $interventions) {
    if ($null -eq $iv.timecode -or (NormText $iv.timecode).Length -eq 0) {
      $countMissing++
    } else {
      $countOk++
    }
  }

  $subject_timecode_quality = "missing"
  if ($countOk -gt 0 -and $countMissing -eq 0) {
    $subject_timecode_quality = "ok"
  } elseif ($countOk -gt 0 -and $countMissing -gt 0) {
    $subject_timecode_quality = "mixed"
  }

  $row = [PSCustomObject]@{
    text                     = $text
    doc_type                 = "sujet"
    line                     = $numero
    parent_doc_path          = $jsonFile
    has_evidence             = $hasEvidence
    total_interventions      = $interventions.Count
    count_timecode_ok        = $countOk
    count_timecode_missing   = $countMissing
    subject_timecode_quality = $subject_timecode_quality
  }

  $outRows.Add($row) | Out-Null
}

# ------------------------------------
# 6) Écriture CSV
# ------------------------------------
$dir = Split-Path -Parent $OutCsv
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

$outRows | Export-Csv -Path $OutCsv -Delimiter $Delimiter -NoTypeInformation -Encoding UTF8
Write-Host "OK: écrit $($outRows.Count) sujets -> $OutCsv"
