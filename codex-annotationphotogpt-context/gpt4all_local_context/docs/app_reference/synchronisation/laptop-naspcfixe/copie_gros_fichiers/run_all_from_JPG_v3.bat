@echo off
setlocal EnableExtensions

echo SCRIPT EXECUTE : %~f0
echo CWD           : %CD%

REM ======================================================
REM USAGE:
REM   run_all_from_JPG_v2.bat <ID_AFFAIRE> [ROOT_DST] [MODE]
REM EX:
REM   run_all_from_JPG_v2.bat 2025-J46 \\192.168.1.20\volume1\Affaires
REM Où :
REM   ROOT_DST = partage UNC (NAS ou PC fixe)
REM   MODE = NAS ou PCFIXE (optionnel ; surtout utile pour logs)
REM ======================================================

set "AFFAIRE=%~1"
if "%AFFAIRE%"=="" (
  echo ERREUR: id_affaire requis. Ex: 2025-J46
  exit /b 1
)

set "ROOT_DST=%~2"
if "%ROOT_DST%"=="" set "ROOT_DST=\\192.168.1.20\volume1\Affaires"

set "MODE=%~3"
if "%MODE%"=="" set "MODE=NAS"

REM ======================================================
REM 1) Vérifier que l'on est dans ...\Photos\JPG
REM ======================================================
for %%I in ("%CD%") do set "CWD_NAME=%%~nxI"
if /I not "%CWD_NAME%"=="JPG" (
  echo ERREUR: lancer ce .bat depuis le dossier "...\\Photos\\JPG"
  echo Dossier courant: %CD%
  exit /b 1
)

REM Dossiers source
for %%I in ("%CD%") do set "SRC_JPG=%%~fI"
for %%I in ("%CD%\..") do set "SRC_PHOTOS=%%~fI"
for %%I in ("%CD%\..\..") do set "CAPT_EVENT_DIR=%%~fI"
for %%I in ("%CD%\..\..\Audio") do set "SRC_AUDIO=%%~fI"

REM ======================================================
REM 2) Déduire id_captation depuis le nom du dossier de captation
REM    Ex: "Accedit 06 11 2025" -> "accedit-2025-11-06"
REM ======================================================
for /f "usebackq delims=" %%i in (`python -c "import os,re; p=os.path.normpath(r'%CAPT_EVENT_DIR%'); n=os.path.basename(p); m=re.match(r'(?i)^\s*([a-z0-9]+)\s+(\d{2})\s+(\d{2})\s+(\d{4})\s*$', n); print('' if not m else f'{m.group(1).lower()}-{m.group(4)}-{m.group(3)}-{m.group(2)}')"` ) do set "CAPTATION=%%i"

if "%CAPTATION%"=="" (
  echo ERREUR: impossible de deduire id_captation depuis "%CAPT_EVENT_DIR%"
  echo Attendu: "Slug JJ MM AAAA" (ex: "Accedit 06 11 2025")
  exit /b 2
)

REM ======================================================
REM 3) Détecter PHOTOS_CSV (UI) dans Photos
REM ======================================================
for /f "usebackq delims=" %%i in (`python "C:\DevTools\Compression photo\pick_ui_csv.py" "%SRC_PHOTOS%"`) do set "PHOTOS_CSV=%%i"

if "%PHOTOS_CSV%"=="" (
  echo ERREUR: aucun CSV UI detecte dans "%SRC_PHOTOS%"
  exit /b 3
)

for %%I in ("%PHOTOS_CSV%") do set "PHOTOS_CSV_NAME=%%~nxI"

set "PHOTOS_BATCH=%SRC_PHOTOS%\photos_batch.csv"
if not exist "%PHOTOS_BATCH%" (
  echo INFO: photos_batch.csv absent -> creation minimale a partir de photos.csv
  python "C:\DevTools\Compression photo\mk_photos_batch_min.py" "%PHOTOS_CSV%" "%PHOTOS_BATCH%"
  if errorlevel 1 (
    echo ERREUR: creation photos_batch.csv echouee
    exit /b 11
  )
)

REM ======================================================
REM 4) Détecter transcription/audio/contexte dans Audio (si existe)
REM ======================================================
set "TRANSCRIPT_CSV="
set "WAV_MONO16="
set "WAV_SOURCE="
set "CTX_GENERAL="

if exist "%SRC_AUDIO%\" (
  for /f "usebackq delims=" %%i in (`python -c "from pathlib import Path; d=Path(r'%SRC_AUDIO%'); c=sorted(d.glob('*_mono16_16000Hz(wav).csv'), key=lambda p: p.stat().st_mtime, reverse=True); print(str(c[0]) if c else '')"` ) do set "TRANSCRIPT_CSV=%%i"

  for /f "usebackq delims=" %%i in (`python -c "from pathlib import Path; d=Path(r'%SRC_AUDIO%'); c=sorted(d.glob('*_mono16_16000Hz.wav'), key=lambda p: p.stat().st_mtime, reverse=True); print(str(c[0]) if c else '')"` ) do set "WAV_MONO16=%%i"

  for /f "usebackq delims=" %%i in (`python -c "from pathlib import Path; d=Path(r'%SRC_AUDIO%'); cand=[*d.glob('*.WAV'),*d.glob('*.wav')]; cand=[p for p in cand if 'mono16_16000Hz' not in p.name]; cand=sorted(cand, key=lambda p: p.stat().st_mtime, reverse=True); print(str(cand[0]) if cand else '')"` ) do set "WAV_SOURCE=%%i"

  if "%WAV_SOURCE%"=="" set "WAV_SOURCE=%WAV_MONO16%"

  for /f "usebackq delims=" %%i in (`python -c "from pathlib import Path; d=Path(r'%SRC_AUDIO%'); cand=sorted(d.glob('contexte_general*.json'), key=lambda p: p.stat().st_mtime, reverse=True); print(str(cand[0]) if cand else '')"` ) do set "CTX_GENERAL=%%i"

) else (
  echo ATTENTION: dossier Audio frere introuvable: "%SRC_AUDIO%"
)

REM ======================================================
REM 5) Cibles destination (architecture canonique)
REM ======================================================
set "DST_BASE=%ROOT_DST%\%AFFAIRE%\AE_Expert_captations\%CAPTATION%"
set "DST_PHOTOS=%DST_BASE%\photos"
set "DST_JPG=%DST_PHOTOS%\JPG"
set "DST_REDUIT=%DST_PHOTOS%\JPG reduit"
set "DST_AUDIO=%DST_BASE%\audio"
set "DST_TRANS=%ROOT_DST%\%AFFAIRE%\AF_Expert_ASR\transcriptions\%CAPTATION%"

mkdir "%DST_JPG%" >nul 2>&1
mkdir "%DST_REDUIT%" >nul 2>&1
mkdir "%DST_AUDIO%" >nul 2>&1
mkdir "%DST_TRANS%" >nul 2>&1

echo ----------------------------------------
echo AFFAIRE        = %AFFAIRE%
echo CAPTATION      = %CAPTATION%
echo ROOT_DST       = %ROOT_DST%
echo MODE           = %MODE%
echo SRC_PHOTOS     = %SRC_PHOTOS%
echo SRC_AUDIO      = %SRC_AUDIO%
echo PHOTOS_CSV     = %PHOTOS_CSV%
echo TRANSCRIPT_CSV = %TRANSCRIPT_CSV%
echo WAV_MONO16     = %WAV_MONO16%
echo WAV_SOURCE     = %WAV_SOURCE%
echo CTX_GENERAL    = %CTX_GENERAL%
echo ----------------------------------------

REM ======================================================
REM 6) Post-sync photos.csv (renseigne champs pcfixe / destination)
REM ======================================================
echo [1/7] Mise a jour photos.csv (champs destination)...
python "C:\DevTools\Compression photo\batch_photos_post_sync.py" ^
  --photos_csv "%PHOTOS_CSV%" ^
  --id_affaire "%AFFAIRE%" ^
  --id_captation "%CAPTATION%" ^
  --root_pcfixe "%ROOT_DST%"

if errorlevel 1 (
  echo ERREUR: batch_photos_post_sync.py a echoue
  exit /b 10
)

REM ======================================================
REM 7) Copies photos (Robocopy: echec si >=8)
REM ======================================================
echo [2/7] Copie JPG natifs...
robocopy "%SRC_JPG%" "%DST_JPG%" *.jpg *.jpeg *.JPG *.JPEG /E /COPY:DAT /DCOPY:T /R:1 /W:1
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERREUR robocopy code=%RC%
  echo SRC="%SRC_JPG%"
  echo DST="%DST_JPG%"
  exit /b %RC%
)

echo [3/7] Copie JPG reduit (si existe)...
if exist "%SRC_PHOTOS%\JPG reduit\" (
  robocopy "%SRC_PHOTOS%\JPG reduit" "%DST_REDUIT%" *.jpg *.jpeg *.JPG *.JPEG /E /COPY:DAT /DCOPY:T /R:1 /W:1
  set "RC=%ERRORLEVEL%"
  if %RC% GEQ 8 (
    echo ERREUR robocopy code=%RC%
    echo SRC="%SRC_PHOTOS%\JPG reduit"
    echo DST="%DST_REDUIT%"
    exit /b %RC%
  )
)

echo [4/7] Copie Photos (CSV/XLS/XLSX)...
robocopy "%SRC_PHOTOS%" "%DST_PHOTOS%" "*.csv" "*.xls" "*.xlsx" /R:1 /W:1
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERREUR robocopy code=%RC%
  echo SRC="%SRC_PHOTOS%"
  echo DST="%DST_PHOTOS%"
  exit /b %RC%
)

REM ======================================================
REM 8) Copies audio/transcriptions/contextes
REM ======================================================
echo [5/7] Copie audio/transcriptions depuis Audio...
if exist "%SRC_AUDIO%\" (
  robocopy "%SRC_AUDIO%" "%DST_AUDIO%" "*.wav" "*.WAV" /R:1 /W:1
  set "RC=%ERRORLEVEL%"
  if %RC% GEQ 8 (
    echo ERREUR robocopy code=%RC%
    echo SRC="%SRC_AUDIO%"
    echo DST="%DST_AUDIO%"
    exit /b %RC%
  )

  robocopy "%SRC_AUDIO%" "%DST_TRANS%" "*.csv" "*.srt" "*.vtt" "*.txt" "*.json" "*.xlsx" /R:1 /W:1
  set "RC=%ERRORLEVEL%"
  if %RC% GEQ 8 (
    echo ERREUR robocopy code=%RC%
    echo SRC="%SRC_AUDIO%"
    echo DST="%DST_TRANS%"
    exit /b %RC%
  )
)

REM ======================================================
REM 9) Dépôt prompts/config
REM ======================================================
echo [6/7] Depot prompts/config...
set "PROMPT_SRC=C:\AnnotationPhotosGPT\config\prompt_gpt.json"
if exist "%PROMPT_SRC%" copy /Y "%PROMPT_SRC%" "%DST_TRANS%\prompt_gpt.json" >nul

set "PROMPT_BATCH_SRC=C:\AnnotationPhotosGPT\config\prompt_gpt_batch_only.json"
if exist "%PROMPT_BATCH_SRC%" copy /Y "%PROMPT_BATCH_SRC%" "%DST_TRANS%\prompt_gpt_batch_only.json" >nul

set "CFG_SRC=C:\AnnotationPhotosGPT\config\config.json"
if exist "%CFG_SRC%" copy /Y "%CFG_SRC%" "%DST_TRANS%\config_llm.json" >nul

REM ======================================================
REM 9bis) Copier contextes + annexes depuis le dossier Audio -> DST_TRANS
REM ======================================================
echo [6bis/7] Copie contextes + annexes (Audio -> transcriptions)...

if not exist "%SRC_AUDIO%\" (
  echo ATTENTION: dossier Audio introuvable: "%SRC_AUDIO%"
) else (
  if exist "%SRC_AUDIO%\contexte_general*.json" (
    copy /Y "%SRC_AUDIO%\contexte_general*.json" "%DST_TRANS%\" >nul
  )

  if exist "%SRC_AUDIO%\*proper_names*.txt" (
    copy /Y "%SRC_AUDIO%\*proper_names*.txt" "%DST_TRANS%\" >nul
  )

  if exist "%SRC_AUDIO%\Participants.xls"  copy /Y "%SRC_AUDIO%\Participants.xls"  "%DST_TRANS%\" >nul
  if exist "%SRC_AUDIO%\Participants.xlsx" copy /Y "%SRC_AUDIO%\Participants.xlsx" "%DST_TRANS%\" >nul
  if exist "%SRC_AUDIO%\Sujets.xls"        copy /Y "%SRC_AUDIO%\Sujets.xls"        "%DST_TRANS%\" >nul
  if exist "%SRC_AUDIO%\Sujets.xlsx"       copy /Y "%SRC_AUDIO%\Sujets.xlsx"       "%DST_TRANS%\" >nul
)

REM ======================================================
REM 10) Génération infos_projet.json
REM ======================================================
echo [7/7] Generation infos_projet.json...

set "INFOS_LAPTOP=%SRC_AUDIO%\infos_projet.json"
if not exist "%SRC_AUDIO%\" set "INFOS_LAPTOP=%SRC_PHOTOS%\infos_projet.json"

python "C:\DevTools\Compression photo\write_infos_projet.py" ^
  "%AFFAIRE%" "%CAPTATION%" "%PHOTOS_CSV%" "%PHOTOS_BATCH%" ^
  "%TRANSCRIPT_CSV%" "%WAV_MONO16%" "%WAV_SOURCE%" "%CTX_GENERAL%" ^
  "%ROOT_DST%" "%DST_TRANS%" "%INFOS_LAPTOP%"

if errorlevel 1 (
  echo ERREUR: generation infos_projet.json echouee
  exit /b 12
)

REM Astuce pratique : si un wav mono16 existe, on le duplique aussi en audio_compatible.wav
if exist "%WAV_MONO16%" (
  copy /Y "%WAV_MONO16%" "%DST_AUDIO%\audio_compatible.wav" >nul
)

echo ========================================
echo OK - copie terminee
echo DST_BASE  = %DST_BASE%
echo DST_TRANS = %DST_TRANS%
echo INFOS     = %INFOS_LAPTOP%
echo ========================================
endlocal
exit /b 0