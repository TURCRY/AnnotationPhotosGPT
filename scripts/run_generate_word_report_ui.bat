@echo off
setlocal EnableExtensions

cd /d "%~dp0.."
if errorlevel 1 (
  echo [ERR] Impossible de se placer a la racine du projet.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
  echo [ERR] Environnement virtuel introuvable : .venv\Scripts\activate.bat
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"

set "INFOS_PATH=%CD%\data\infos_projet.json"
set "MODE_METIER="
set "RETENUE_METIER="

:parse_args
if "%~1"=="" goto after_parse

if /I "%~1"=="--infos" (
  set "INFOS_PATH=%~2"
  shift
  shift
  goto parse_args
)

if /I "%~1"=="--mode" (
  set "MODE_METIER=%~2"
  shift
  shift
  goto parse_args
)

if /I "%~1"=="--retenue" (
  set "RETENUE_METIER=%~2"
  shift
  shift
  goto parse_args
)

echo [ERR] Argument inconnu : %~1
pause
exit /b 1

:after_parse

echo ==========================================
echo Generation du rapport Word - laptop
echo ==========================================
echo.

if not exist "%INFOS_PATH%" (
  echo [ERR] Fichier infos_projet.json introuvable :
  echo %INFOS_PATH%
  pause
  exit /b 1
)

if "%MODE_METIER%"=="" (
  echo Choix des donnees :
  echo 1^) donnees provisoires
  echo 2^) donnees validees
  set /p "CHOICE_MODE=Choisir (1/2) puis Entree : "
  if "%CHOICE_MODE%"=="2" (
    set "MODE_METIER=valide"
  ) else (
    set "MODE_METIER=provisoire"
  )
)

if "%RETENUE_METIER%"=="" (
  echo.
  echo Filtre retenue :
  echo 1^) oui  - seulement les photos retenues
  echo 2^) non  - toutes les photos
  set /p "CHOICE_RET=Choisir (1/2) puis Entree : "
  if "%CHOICE_RET%"=="2" (
    set "RETENUE_METIER=non"
  ) else (
    set "RETENUE_METIER=oui"
  )
)

set "REPORT_MODE="
if /I "%MODE_METIER%"=="provisoire" set "REPORT_MODE=UI"
if /I "%MODE_METIER%"=="valide" set "REPORT_MODE=GTP"

if "%REPORT_MODE%"=="" (
  echo [ERR] Valeur invalide pour --mode : %MODE_METIER%
  echo Valeurs attendues : provisoire ^| valide
  pause
  exit /b 1
)

set "REPORT_ONLY_RETENUE="
if /I "%RETENUE_METIER%"=="oui" set "REPORT_ONLY_RETENUE=1"
if /I "%RETENUE_METIER%"=="non" set "REPORT_ONLY_RETENUE=0"

if "%REPORT_ONLY_RETENUE%"=="" (
  echo [ERR] Valeur invalide pour --retenue : %RETENUE_METIER%
  echo Valeurs attendues : oui ^| non
  pause
  exit /b 1
)

echo.
echo [INFO] INFOS_PATH=%INFOS_PATH%
echo [INFO] MODE_METIER=%MODE_METIER%
echo [INFO] RETENUE_METIER=%RETENUE_METIER%
echo [INFO] REPORT_MODE=%REPORT_MODE%
echo [INFO] REPORT_ONLY_RETENUE=%REPORT_ONLY_RETENUE%
echo.

python "scripts\generate_word_report.py" --infos "%INFOS_PATH%"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo [ERR] Python exited with code %RC%
) else (
  echo [OK] Rapport genere avec succes.
)
pause
exit /b %RC%