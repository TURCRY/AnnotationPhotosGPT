@echo off
SETLOCAL

echo [INFO] Lancement de l'application principale "main.py" via launch_main.exe...
cd /d "%~dp0"
cd ..\exe

if exist "launch_main.exe" (
    start "" "launch_main.exe"
) else (
    echo [ERREUR] Le fichier launch_main.exe est introuvable dans le dossier \exe\
    pause
)

ENDLOCAL
