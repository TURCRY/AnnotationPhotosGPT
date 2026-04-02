@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ======================================================
REM Positionnement (PC fixe)
REM ======================================================
cd /d C:\GPT4All_Local\scripts

REM ======================================================
REM Paramètres de base (PC fixe)
REM ======================================================
set "ROOT_AFFAIRES=C:\Affaires"
set "FLASK_URL=http://127.0.0.1:5000"

REM Renseigner ici (ou dupliquer ce .bat par affaire/captation)
set "AFFAIRE=2025-J37"
set "CAPTATION=accedit-2025-09-02"

REM infos_projet.json doit avoir été copié par run_all_laptop.bat ici :
set "INFOS_PC=%ROOT_AFFAIRES%\%AFFAIRE%\AF_Expert_ASR\transcriptions\%CAPTATION%\infos_projet.json"

REM ======================================================
REM Contrôles
REM ======================================================
python --version >nul 2>&1 || (
  echo ERREUR: python non trouve sur le PC fixe
  exit /b 1
)

if not exist "%INFOS_PC%" (
  echo ERREUR: infos_projet.json introuvable cote PC fixe:
  echo         "%INFOS_PC%"
  exit /b 1
)

REM ======================================================
REM Lecture basenames depuis infos_projet.json (PC fixe)
REM ======================================================
for /f "usebackq delims=" %%i in (`
  python -c "import json; p=json.load(open(r'%INFOS_PC%',encoding='utf-8')); print((p.get('fichier_photos') or '').strip())"
`) do set "PHOTOS_BASENAME=%%i"

for /f "usebackq delims=" %%i in (`
  python -c "import json; p=json.load(open(r'%INFOS_PC%',encoding='utf-8')); print((p.get('fichier_transcription') or '').strip())"
`) do set "TRANSCRIPT_BASENAME=%%i"

if "%PHOTOS_BASENAME%"=="" (
  echo ERREUR: 'fichier_photos' absent ou vide dans infos_projet.json (PC fixe)
  exit /b 1
)

if "%TRANSCRIPT_BASENAME%"=="" (
  echo ERREUR: 'fichier_transcription' absent ou vide dans infos_projet.json (PC fixe)
  exit /b 1
)

REM ======================================================
REM Reconstruction des chemins PC fixe (avec NOM REEL)
REM ======================================================
set "PHOTOS_CSV=%ROOT_AFFAIRES%\%AFFAIRE%\AE_Expert_captations\%CAPTATION%\photos\%PHOTOS_BASENAME%"
set "TRANSCRIPT_DIR=%ROOT_AFFAIRES%\%AFFAIRE%\AF_Expert_ASR\transcriptions\%CAPTATION%"
set "TRANSCRIPT_CSV=%TRANSCRIPT_DIR%\%TRANSCRIPT_BASENAME%"

echo ----------------------------------------
echo AFFAIRE            = %AFFAIRE%
echo CAPTATION          = %CAPTATION%
echo INFOS_PC           = %INFOS_PC%
echo PHOTOS_BASENAME    = %PHOTOS_BASENAME%
echo TRANSCRIPT_BASENAME= %TRANSCRIPT_BASENAME%
echo PHOTOS_CSV         = %PHOTOS_CSV%
echo TRANSCRIPT_DIR     = %TRANSCRIPT_DIR%
echo TRANSCRIPT_CSV     = %TRANSCRIPT_CSV%
echo ----------------------------------------

if not exist "%PHOTOS_CSV%" (
  echo ERREUR: .csv des photos introuvable cote PC fixe:
  echo         "%PHOTOS_CSV%"
  exit /b 1
)

if not exist "%TRANSCRIPT_DIR%\" (
  echo ERREUR: dossier transcription introuvable:
  echo         "%TRANSCRIPT_DIR%"
  exit /b 1
)

if not exist "%TRANSCRIPT_CSV%" (
  echo ERREUR: fichier transcription introuvable:
  echo         "%TRANSCRIPT_CSV%"
  exit /b 1
)

REM ======================================================
REM Vérification serveur Flask (/ping)
REM ======================================================
python -c "import requests, sys; 
import os; 
u=os.environ.get('FLASK_URL','%FLASK_URL%'); 
r=requests.get(u+'/ping',timeout=3); 
sys.exit(0 if r.ok else 1)" >nul 2>&1

if errorlevel 1 (
  echo ERREUR: serveur Flask indisponible (%FLASK_URL%)
  exit /b 1
)

REM ======================================================
REM Lancement batch VLM + LLM
REM ======================================================
echo [1/1] Lancement batch VLM + LLM...

python batch_photos_vlm_llm.py ^
  --photos_csv "%PHOTOS_CSV%" ^
  --root_affaires "%ROOT_AFFAIRES%" ^
  --flask_url "%FLASK_URL%" ^
  --infos_projet_json "%INFOS_PC%" ^
  --transcript_dir "%TRANSCRIPT_DIR%" ^
  --only_missing

if errorlevel 1 (
  echo ERREUR: batch_photos_vlm_llm.py a echoue
  exit /b 2
)

echo ========================================
echo OK - run_all_pcfixe termine.
echo ========================================
endlocal
