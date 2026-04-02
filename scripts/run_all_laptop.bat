@echo off
echo SCRIPT EXECUTE : %~f0

setlocal EnableExtensions EnableDelayedExpansion

REM ======================================================
REM 0) PARAMETRES A RENSEIGNER (CANONIQUES)
REM ======================================================
set "AFFAIRE=2025-J37"
set "CAPTATION=accedit-2025-09-02"

REM Racine des affaires sur le PC fixe (partage)
set "ROOT_PC=\\192.168.0.155\Affaires"

REM Chemin local des scripts sur le laptop
cd /d C:\AnnotationPhotosGPT\scripts

REM Fichier projet (laptop)
set "INFOS_PROJET=C:\AnnotationPhotosGPT\data\infos_projet.json"

REM ======================================================
REM 1) LECTURE DU .CSV DES PHOTOS (source de v??rit??)
REM ======================================================
for /f "usebackq delims=" %%i in (`
  python -c "import json; p=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); print(p.get('fichier_photos',''))"
`) do set "PHOTOS_CSV=%%i"

if "%PHOTOS_CSV%"=="" (
  echo ERREUR: 'fichier_photos' absent de infos_projet.json
  exit /b 1
)

if not exist "%PHOTOS_CSV%" (
  echo ERREUR: .csv des photos introuvable: "%PHOTOS_CSV%"
  exit /b 1
)

REM Dossier et base_name du .csv des photos (pour retrouver xlsx + annotations)
for /f "usebackq delims=" %%i in (`
  python -c "from pathlib import Path; p=Path(r'%PHOTOS_CSV%'); print(str(p.parent))"
`) do set "PHOTOS_DIR=%%i"

for /f "usebackq delims=" %%i in (`
  python -c "from pathlib import Path; p=Path(r'%PHOTOS_CSV%'); print(p.stem)"
`) do set "BASE_NAME=%%i"

REM ======================================================
REM 2) LECTURE DES DOSSIERS SOURCE JPG (NATIFS + REDUITS) DEPUIS LE .CSV
REM ======================================================
for /f "usebackq delims=" %%i in (`python get_photo_dirs.py "%PHOTOS_CSV%"`) do (
  if not defined SRC_NATIVE (
    set "SRC_NATIVE=%%i"
  ) else (
    set "SRC_REDUIT=%%i"
  )
)

echo DEBUG SRC_NATIVE=[%SRC_NATIVE%]
echo DEBUG SRC_REDUIT=[%SRC_REDUIT%]

if "%SRC_NATIVE%"=="" (
  echo ERREUR: chemin_photo_native absent dans le .csv des photos
  exit /b 1
)
if "%SRC_REDUIT%"=="" (
  echo ERREUR: chemin_photo_reduite absent dans le .csv des photos
  exit /b 1
)

if not exist "%SRC_NATIVE%" (
  echo ERREUR: dossier source JPG natifs introuvable: "%SRC_NATIVE%"
  exit /b 1
)
if not exist "%SRC_REDUIT%" (
  echo ERREUR: dossier source JPG reduits introuvable: "%SRC_REDUIT%"
  exit /b 1
)

echo ----------------------------------------
echo AFFAIRE     = %AFFAIRE%
echo CAPTATION   = %CAPTATION%
echo PHOTOS_CSV  = %PHOTOS_CSV%
echo PHOTOS_DIR  = %PHOTOS_DIR%
echo BASE_NAME   = %BASE_NAME%
echo SRC_NATIVE  = %SRC_NATIVE%
echo SRC_REDUIT  = %SRC_REDUIT%
echo ROOT_PC     = %ROOT_PC%
echo ----------------------------------------

REM ======================================================
REM 2bis) Dossier AUDIO (pour trouver contexte_general_photos.json)
REM ======================================================
for /f "usebackq delims=" %%i in (`
  python -c "import json; from pathlib import Path; p=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); v=p.get('fichier_audio',''); print(str(Path(v).parent) if v else '')"
`) do set "AUDIO_DIR=%%i"

REM ======================================================
REM 2ter) Dossier TRANSCRIPTIONS (source) + WAV source/compatible depuis infos_projet.json
REM ======================================================
for /f "usebackq delims=" %%i in (`
  python -c "import json; from pathlib import Path; d=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); v=d.get('fichier_transcription',''); print(str(Path(v).parent) if v else '')"
`) do set "TRANSCRIPT_SRC_DIR=%%i"

for /f "usebackq delims=" %%i in (`
  python -c "import json; d=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); print(d.get('fichier_audio_source','') or d.get('audio_compat_source','') or '')"
`) do set "WAV_SRC=%%i"

for /f "usebackq delims=" %%i in (`
  python -c "import json; d=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); print(d.get('fichier_audio_compatible','') or d.get('fichier_audio','') or '')"
`) do set "WAV_COMPAT=%%i"

echo DEBUG AUDIO_DIR=[%AUDIO_DIR%]
echo DEBUG TRANSCRIPT_SRC_DIR=[%TRANSCRIPT_SRC_DIR%]
echo DEBUG WAV_SRC=[%WAV_SRC%]
echo DEBUG WAV_COMPAT=[%WAV_COMPAT%]

REM ======================================================
REM 3) CONSTRUCTION DES CIBLES PC FIXE (architecture canonique)
REM ======================================================
set "DST_BASE=%ROOT_PC%\%AFFAIRE%\AE_Expert_captations\%CAPTATION%"
set "DST_PHOTOS=%DST_BASE%\photos"
set "DST_NATIVE=%DST_PHOTOS%\JPG"
set "DST_REDUIT=%DST_PHOTOS%\JPG reduit"
set "DST_AUDIO=%DST_BASE%\audio"

REM Dossier transcription PC fixe
set "DST_TRANSCRIPT_DIR=%ROOT_PC%\%AFFAIRE%\AF_Expert_ASR\transcriptions\%CAPTATION%"

if not exist "%ROOT_PC%\%AFFAIRE%\" (
  echo ERREUR: affaire absente sur le PC fixe: "%ROOT_PC%\%AFFAIRE%"
  exit /b 1
)

mkdir "%DST_PHOTOS%" >nul 2>&1
mkdir "%DST_NATIVE%" >nul 2>&1
mkdir "%DST_REDUIT%" >nul 2>&1
mkdir "%DST_AUDIO%" >nul 2>&1
mkdir "%DST_TRANSCRIPT_DIR%" >nul 2>&1

REM ======================================================
REM 4) POST-SYNCHRONISATION DU .CSV DES PHOTOS (AVANT copie)
REM ======================================================
echo [1/6] Mise a jour du .csv des photos (chemins PC fixe, flags)...
python batch_photos_post_sync.py ^
  --photos_csv "%PHOTOS_CSV%" ^
  --id_affaire "%AFFAIRE%" ^
  --id_captation "%CAPTATION%" ^
  --root_pcfixe "%ROOT_PC%"

if errorlevel 1 (
  echo ERREUR: batch_photos_post_sync.py a echoue
  exit /b 2
)

echo DEBUG APRES post_sync, PHOTOS_CSV=[%PHOTOS_CSV%]
dir /-c "%PHOTOS_CSV%"

REM ======================================================
REM 5) COPIE DES JPG NATIFS + REDUITS
REM ======================================================
echo [2/6] Copie des JPG natifs + reduits vers le PC fixe...

REM Normalisation: robocopy n'aime pas les chemins entre guillemets qui finissent par "\"
if "%SRC_NATIVE:~-1%"=="\" set "SRC_NATIVE=%SRC_NATIVE:~0,-1%"
if "%SRC_REDUIT:~-1%"=="\" set "SRC_REDUIT=%SRC_REDUIT:~0,-1%"

REM Robocopy NATIFS
robocopy "%SRC_NATIVE%" "%DST_NATIVE%" *.jpg *.jpeg *.JPG *.JPEG /E /COPY:DAT /DCOPY:T /R:1 /W:1
set "RC=%ERRORLEVEL%"
echo DEBUG robocopy natifs RC=%RC%
echo DEBUG APRES NATIFS - ON CONTINUE (ligne 999)
if %RC% GEQ 8 (
  echo ERREUR: robocopy natifs a echoue (code=%RC%)
  exit /b %RC%
)

echo DEBUG AVANT REDUITS (ligne 1000)

REM Robocopy REDUITS
robocopy "%SRC_REDUIT%" "%DST_REDUIT%" *.jpg *.jpeg *.JPG *.JPEG /E /COPY:DAT /DCOPY:T /R:1 /W:1
set "RC=%ERRORLEVEL%"
echo DEBUG robocopy reduits RC=%RC%
if %RC% GEQ 8 (
  echo ERREUR: robocopy reduits a echoue (code=%RC%)
  exit /b %RC%
)

REM ======================================================
REM 5bis) COPIE DES WAV
REM ======================================================
echo [3/6] Copie des WAV vers le PC fixe...

if not "%WAV_SRC%"=="" if exist "%WAV_SRC%" (
  copy /Y "%WAV_SRC%" "%DST_AUDIO%\" >nul
) else (
  echo ATTENTION: WAV source introuvable: "%WAV_SRC%"
)

if not "%WAV_COMPAT%"=="" if exist "%WAV_COMPAT%" (
  copy /Y "%WAV_COMPAT%" "%DST_AUDIO%\" >nul
) else (
  echo ATTENTION: WAV compatible introuvable: "%WAV_COMPAT%"
)

REM ======================================================
REM 6) COPIE CSV/XLS/XLSX + ANNOTATIONS
REM ======================================================
echo [4/6] Copie CSV + xls/xlsx + annotations vers le PC fixe...

robocopy "%PHOTOS_DIR%" "%DST_PHOTOS%" "%BASE_NAME%.csv" /R:1 /W:1
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERREUR: robocopy CSV a echoue (code=%RC%)
  exit /b %RC%
)

robocopy "%PHOTOS_DIR%" "%DST_PHOTOS%" "%BASE_NAME%.xlsx" "%BASE_NAME%.xls" /R:1 /W:1
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERREUR: robocopy XLS/XLSX a echoue (code=%RC%)
  exit /b %RC%
)

echo [5/6] Copie des fichiers d'annotation (_GTP_) vers le PC fixe...
robocopy "%PHOTOS_DIR%" "%DST_PHOTOS%" "%BASE_NAME%_GTP_*.csv" "%BASE_NAME%_GTP_*.xlsx" /R:1 /W:1
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERREUR: robocopy GTP a echoue (code=%RC%)
  exit /b %RC%
)

REM ======================================================
REM 7) DEPOT prompts + infos_projet.json + config + contextes
REM ======================================================
echo [6/6] Depot prompts + infos_projet.json (normalise) + config_llm + contextes...

set "PROMPT_SRC=C:\AnnotationPhotosGPT\config\prompt_gpt.json"
if exist "%PROMPT_SRC%" (
  copy /Y "%PROMPT_SRC%" "%DST_TRANSCRIPT_DIR%\prompt_gpt.json" >nul
) else (
  echo ATTENTION: prompt_gpt.json introuvable sur le laptop : "%PROMPT_SRC%"
)

set "PROMPT_BATCH_SRC=C:\AnnotationPhotosGPT\config\prompt_gpt_batch_only.json"
if exist "%PROMPT_BATCH_SRC%" (
  copy /Y "%PROMPT_BATCH_SRC%" "%DST_TRANSCRIPT_DIR%\prompt_gpt_batch_only.json" >nul
) else (
  echo ATTENTION: prompt_gpt_batch_only.json introuvable sur le laptop : "%PROMPT_BATCH_SRC%"
)

set "DST_INFOS=%DST_TRANSCRIPT_DIR%\infos_projet.json"
copy /Y "%INFOS_PROJET%" "%DST_INFOS%" >nul

set "CFG_SRC=C:\AnnotationPhotosGPT\config\config.json"
set "CFG_DST=%DST_TRANSCRIPT_DIR%\config_llm.json"
if exist "%CFG_SRC%" (
  copy /Y "%CFG_SRC%" "%CFG_DST%" >nul
) else (
  echo ATTENTION: config.json introuvable sur le laptop : "%CFG_SRC%"
)

if not "%TRANSCRIPT_SRC_DIR%"=="" if exist "%TRANSCRIPT_SRC_DIR%\contexte_general_photos.json" (
  copy /Y "%TRANSCRIPT_SRC_DIR%\contexte_general_photos.json" "%DST_TRANSCRIPT_DIR%\contexte_general_photos.json" >nul
) else if exist "%AUDIO_DIR%\contexte_general_photos.json" (
  copy /Y "%AUDIO_DIR%\contexte_general_photos.json" "%DST_TRANSCRIPT_DIR%\contexte_general_photos.json" >nul
) else (
  echo ATTENTION: contexte_general_photos.json introuvable (TRANSCRIPT_SRC_DIR ou AUDIO_DIR)
)

if not "%TRANSCRIPT_SRC_DIR%"=="" if exist "%TRANSCRIPT_SRC_DIR%\contexte_general_compte_rendu.json" (
  copy /Y "%TRANSCRIPT_SRC_DIR%\contexte_general_compte_rendu.json" "%DST_TRANSCRIPT_DIR%\contexte_general_compte_rendu.json" >nul
) else (
  echo ATTENTION: contexte_general_compte_rendu.json introuvable dans "%TRANSCRIPT_SRC_DIR%"
)

REM ======================================================
REM 7bis) COPIE TRANSCRIPTIONS ET ANNEXES
REM ======================================================
if "%TRANSCRIPT_SRC_DIR%"=="" (
  echo ATTENTION: TRANSCRIPT_SRC_DIR vide (fichier_transcription non defini ?)
) else (
  if not exist "%TRANSCRIPT_SRC_DIR%" (
    echo ATTENTION: dossier transcription source introuvable: "%TRANSCRIPT_SRC_DIR%"
  ) else (
    robocopy "%TRANSCRIPT_SRC_DIR%" "%DST_TRANSCRIPT_DIR%" *.csv *.srt *.vtt *.txt *.json *.xlsx /R:1 /W:1
    set "RC=%ERRORLEVEL%"
    if %RC% GEQ 8 (
      echo ERREUR: robocopy transcriptions a echoue (code=%RC%)
      exit /b %RC%
    )
  )
)

REM ======================================================
REM Normalisation des chemins -> basenames (pour batch PC fixe)
REM ======================================================
python -c "import json; from pathlib import Path; p=Path(r'%DST_INFOS%'); d=json.load(p.open(encoding='utf-8')); \
for k in ('fichier_photos','fichier_transcription','fichier_contexte_general','fichier_audio','fichier_audio_source','audio_compat_source','fichier_audio_compatible'): \
    v=d.get(k); \
    if isinstance(v,str) and v.strip(): d[k]=Path(v).name; \
p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')"

echo ========================================
echo OK - run_all_laptop termine avec succes
echo ========================================

endlocal
echo FIN DU SCRIPT - ERRORLEVEL=%ERRORLEVEL%
pause
exit /b 0

