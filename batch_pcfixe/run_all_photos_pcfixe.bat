@echo off
setlocal enabledelayedexpansion

REM ==========================================================
REM  run_all_photos_pcfixe.bat
REM  Usage:
REM    run_all_photos_pcfixe.bat "C:\...\infos_projet.json" [--dry-run 1] [--limit 10]
REM ==========================================================

REM Se placer dans le dossier du .bat
cd /d "%~dp0"

REM activer le venv
call "%~dp0..\..\.venv\Scripts\activate"

if "%~1"=="" (
  echo ERREUR: chemin infos_projet.json manquant.
  echo Usage: run_all_photos_pcfixe.bat "C:\...\infos_projet.json" [--dry-run 1] [--limit 10]
  exit /b 2
)

python -u "%~dp0batch_all_photos_pcfixe.py" --infos "%~1" %2 %3 %4 %5 %6 %7 %8 %9

exit /b %ERRORLEVEL%
