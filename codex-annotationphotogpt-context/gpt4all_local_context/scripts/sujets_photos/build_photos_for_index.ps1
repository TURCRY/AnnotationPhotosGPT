Param(
  [Parameter(Mandatory=$true)]
  [string]$UiCsv,                              # ex: ...\J37 Touzeau photos 02 09 2025.csv

  [Parameter(Mandatory=$false)]
  [string]$GtpCsv,                             # ex: ...\*_GTP_*.csv (facultatif)

  [Parameter(Mandatory=$false)]
  [string]$BatchCsv,                           # ex: ...\photos_batch.csv (facultatif)

  [Parameter(Mandatory=$true)]
  [string]$OutCsv,                             # ex: ...\_vector\photos\photos_for_index.csv

  [string]$Delimiter = ";"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function NormText([string]$s) {
  if ($null -eq $s) { return "" }
  $t = $s.ToString().Trim()
  if ($t.Length -eq 0) { return "" }
  # normalisation légère : espaces multiples, retours ligne
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

function GetFileNameFromPhotoRelNative([string]$rel) {
  if ([string]::IsNullOrWhiteSpace($rel)) { return "" }
  # ex: AE_Expert_captations/.../P1060264.JPG
  return [System.IO.Path]::GetFileName($rel.Replace("/", "\"))
}

# ----------------------
# 1) Lecture UI (base)
# ----------------------
$ui = Import-Csv -Path $UiCsv -Delimiter $Delimiter
if (-not $ui -or $ui.Count -eq 0) { throw "UI CSV vide: $UiCsv" }

# index UI par nom_fichier_image, sinon dérive depuis photo_rel_native
$uiByName = @{}
foreach ($r in $ui) {
  $name = NormText $r.nom_fichier_image
  if ($name.Length -eq 0) {
    $name = GetFileNameFromPhotoRelNative (NormText $r.photo_rel_native)
  }
  if ($name.Length -eq 0) { continue }
  $uiByName[$name] = $r
}

# ----------------------
# 2) Lecture GTP (enrich.)
# ----------------------
$gtpByName = @{}
if ($GtpCsv -and (Test-Path $GtpCsv)) {
  $gtp = Import-Csv -Path $GtpCsv -Delimiter $Delimiter
  foreach ($r in $gtp) {
    $name = NormText $r.nom_fichier_image
    if ($name.Length -eq 0) { continue }
    $gtpByName[$name] = $r
  }
}

# ----------------------
# 3) Lecture Batch (fallback VLM)
# ----------------------
$batchByName = @{}
if ($BatchCsv -and (Test-Path $BatchCsv)) {
  $batch = Import-Csv -Path $BatchCsv -Delimiter $Delimiter
  foreach ($r in $batch) {
    # batch_header ne contient pas forcément nom_fichier_image -> on dérive depuis photo_rel_native
    $name = GetFileNameFromPhotoRelNative (NormText $r.photo_rel_native)
    if ($name.Length -eq 0) { continue }
    $batchByName[$name] = $r
  }
}

# ----------------------
# 4) Construction lignes output
# ----------------------
$outRows = New-Object System.Collections.Generic.List[object]

foreach ($kv in $uiByName.GetEnumerator()) {
  $name = $kv.Key
  $u = $kv.Value
  $g = $null
  $b = $null
  if ($gtpByName.ContainsKey($name)) { $g = $gtpByName[$name] }
  if ($batchByName.ContainsKey($name)) { $b = $batchByName[$name] }

  # Sources (libellé/commentaire)
  $libelle = ""
  $libelle_source = "none"
  if ($g -and (NormText $g.libelle).Length -gt 0) {
    $libelle = $g.libelle; $libelle_source = "gtp"
  } elseif ((NormText $u.libelle_propose_ui).Length -gt 0) {
    $libelle = $u.libelle_propose_ui; $libelle_source = "ui"
  }

  $commentaire = ""
  $commentaire_source = "none"
  if ($g -and (NormText $g.commentaire).Length -gt 0) {
    $commentaire = $g.commentaire; $commentaire_source = "gtp"
  } elseif ((NormText $u.commentaire_propose_ui).Length -gt 0) {
    $commentaire = $u.commentaire_propose_ui; $commentaire_source = "ui"
  }

  # Transcriptions (GTP) + dictée (UI si OK)
  $trans_lib = if ($g) { $g.transcription_libelle } else { "" }
  $trans_com = if ($g) { $g.transcription_commentaire } else { "" }

  $dictee = ""
  $dictee_status = NormText $u.dictee_asr_status
  if ((NormText $u.dictee_asr_text).Length -gt 0 -and ($dictee_status.Length -eq 0 -or $dictee_status -match "OK|ok|Ok")) {
    $dictee = $u.dictee_asr_text
  }

  # VLM (UI puis batch)
  $vlm = ""
  $vlm_source = "none"
  if ((NormText $u.description_vlm_ui).Length -gt 0) {
    $vlm = $u.description_vlm_ui; $vlm_source = "ui"
  } elseif ($b -and (NormText $b.description_vlm_batch).Length -gt 0) {
    $vlm = $b.description_vlm_batch; $vlm_source = "batch"
  }

  # parent_doc_path
  $chemin_reduite = NormText $u.chemin_photo_reduite
  $chemin_native  = NormText $u.chemin_photo_native
  $parent_doc_path = ""
  if ($chemin_reduite.Length -gt 0) {
    # si chemin_photo_reduite pointe sur un dossier, on combine
    if (Test-Path $chemin_reduite -PathType Container) {
      $parent_doc_path = Join-Path $chemin_reduite $name
    } else {
      # sinon on prend tel quel (ou join si déjà complet)
      $parent_doc_path = $chemin_reduite
    }
  } elseif ($chemin_native.Length -gt 0) {
    if (Test-Path $chemin_native -PathType Container) {
      $parent_doc_path = Join-Path $chemin_native $name
    } else {
      $parent_doc_path = $chemin_native
    }
  }

  # Build text blocks
  $blocks = New-Object System.Collections.Generic.List[string]
  AddBlock $blocks "LIBELLE" $libelle
  AddBlock $blocks "COMMENTAIRE" $commentaire
  AddBlock $blocks "TRANS_LIBELLE" $trans_lib
  AddBlock $blocks "TRANS_COMMENTAIRE" $trans_com
  AddBlock $blocks "DICTEE" $dictee
  AddBlock $blocks "VLM" $vlm
  $text = ($blocks -join "`n")

  # id_affaire / id_captation depuis UI
  $id_affaire  = NormText $u.id_affaire
  $id_captation = NormText $u.id_captation

  # annotation_validee : si GTP a un champ, vous pouvez le préférer, sinon UI
  $annotation_validee = ""
  if ($g -and $g.PSObject.Properties.Name -contains "annotation_validee") {
    $annotation_validee = NormText $g.annotation_validee
  } elseif ($u.PSObject.Properties.Name -contains "annotation_validee") {
    $annotation_validee = NormText $u.annotation_validee
  }

  $row = [PSCustomObject]@{
    text               = $text
    doc_type           = "photo"
    id_affaire         = $id_affaire
    id_captation       = $id_captation
    line               = $name
    parent_doc_path    = $parent_doc_path
    photo_rel_native   = NormText $u.photo_rel_native
    libelle_source     = $libelle_source
    commentaire_source = $commentaire_source
    vlm_source         = $vlm_source
    annotation_validee = $annotation_validee
    horodatage_photo   = NormText $u.horodatage_photo
    horodatage_secondes= NormText $u.horodatage_secondes
    orientation_photo  = NormText $u.orientation_photo
    retenue            = NormText $u.retenue
  }

  $outRows.Add($row) | Out-Null
}

# ----------------------
# 5) Écriture CSV output
# ----------------------
$dir = Split-Path -Parent $OutCsv
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

$outRows | Export-Csv -Path $OutCsv -Delimiter $Delimiter -NoTypeInformation -Encoding UTF8
Write-Host "OK: écrit $($outRows.Count) lignes -> $OutCsv"
