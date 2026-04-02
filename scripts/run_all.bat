@echo off
setlocal EnableExtensions

REM ==========================
REM PARAMETRES (A ADAPTER)
REM ==========================
set AFFAIRE=2025-J37
set CAPTATION=2025-09-02-accedit

REM Racine Affaires sur PCfixe (partage UNC)
set ROOT_PC=\\192.168.0.155\Affaires

REM URL Flask sur PCfixe
set FLASK_URL=http://192.168.0.155:5000

REM photos.csv sur laptop (post-synchronisation)
set PHOTOS_CSV=D:\Affaires\%AFFAIRE%\AE_Expert_captations\%CAPTATION%\photos\photos.csv

REM source images réduites sur laptop
set SRC_REDUIT=D:\Affaires\%AFFAIRE%\AE_Expert_captations\%CAPTATION%\photos\JPG reduit

REM destination images réduites sur PCfixe
set DST_REDUIT=%ROOT_PC%\%AFFAIRE%\AE_Expert_captations\%CAPTATION%\photos\JPG reduit

REM transcription ASR (sur laptop)
set TRANSCRIPT_CSV=D:\Affaires\%AFFAIRE%\AE_Expert_ASR\transcriptions\XXmono16_16000Hz(wav).csv

REM fichiers contexte (sur laptop) - adaptez si vos chemins diffèrent
set MISSION_FILE=D:\Affaires\%AFFAIRE%\_Config\mission.txt
set CONTEXTE_FILE=D:\Affaires\%AFFAIRE%\_Config\contexte_general.txt

REM ==========================
REM CONTROLES
REM ==========================
if not exist "%PHOTOS_CSV%" (
  echo ERREUR: photos.csv introuvable: "%PHOTOS_CSV%"
  exit /b 1
)

if not exist "%SRC_REDUIT%" (
  echo ERREUR: dossier source JPG reduit introuvable: "%SRC_REDUIT%"
  exit /b 1
)

REM ==========================
REM 1) COPIE DES JPG REDUITS
REM ==========================
echo [1/3] Copie JPG reduits vers PCfixe...
robocopy "%SRC_REDUIT%" "%DST_REDUIT%" *.jpg *.jpeg /E /COPY:DAT /DCOPY:T /R:1 /W:1
set RC=%ERRORLEVEL%

REM Robocopy: 0-7 = OK (avec ou sans copies). >=8 = erreur.
if %RC% GEQ 8 (
  echo ERREUR: robocopy a echoue (code=%RC%)
  exit /b %RC%
)

REM ==========================
REM 2) POST-SYNC CSV
REM ==========================
echo [2/3] Mise a jour photos.csv (chemins pcfixe + relpaths)...
python batch_photos_post_sync.py ^
  --photos_csv "%PHOTOS_CSV%" ^
  --id_affaire "%AFFAIRE%" ^
  --id_captation "%CAPTATION%" ^
  --root_pcfixe "%ROOT_PC%"

if errorlevel 1 (
  echo ERREUR: batch_photos_post_sync.py a echoue
  exit /b 2
)

REM ==========================
REM 3) VLM + LLM
REM ==========================
echo [3/3] VLM + LLM (batch)...
python batch_photos_vlm_llm.py ^
  --photos_csv "%PHOTOS_CSV%" ^
  --root_pcfixe "%ROOT_PC%" ^
  --flask_url "%FLASK_URL%" ^
  --transcript_csv "%TRANSCRIPT_CSV%" ^
  --mission_file "%MISSION_FILE%" ^
  --contexte_file "%CONTEXTE_FILE%" ^
  --only_missing

if errorlevel 1 (
  echo ERREUR: batch_photos_vlm_llm.py a echoue
  exit /b 3
)

echo OK - run_all termine.
endlocal
