@echo off
setlocal enabledelayedexpansion

echo [INFO] Compilation de launch_main...

REM Suppression de l’ancien dossier build pour une compilation propre
rmdir /s /q ..\build\launch_main 2>nul

REM Compilation du script en utilisant le fichier .spec
pyinstaller --clean ..\spec\launch_main_corrected.spec

echo [OK] Compilation terminée.
pause
