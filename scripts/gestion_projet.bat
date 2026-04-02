@echo off
REM ==========================================
REM Script de gestion du projet AnnotationPhotosGPT
REM ==========================================

REM Se positionner dans le dossier du script, même si lecteur différent
cd /d "%~dp0"

echo ==========================================
echo [DEBUG] Répertoire de travail : %cd%
echo ==========================================
pause

REM === Étape 1 : Conversion .docx → .csv (optionnelle) ===
set /p CHOIX="Souhaitez-vous convertir un fichier .docx en .csv ? (O/N) "
if /I "%CHOIX%"=="O" (
    echo.
    echo Lancement de la sélection de fichier .docx...
    call ..\scripts\run_convert_transcription.bat
    echo.
    echo [DEBUG] Fin de la conversion .docx en .csv
    pause
)

REM === Étape 2 : Lancement du programme principal avec Streamlit ===
echo.
echo ==========================================
echo === Lancement du programme principal main.py ===
echo ==========================================

REM Se placer dans le dossier parent de scripts (racine du projet)
cd /d "%~dp0.."

rem Activation de l'environnement virtuel
call ".venv\Scripts\activate.bat"

set PYTHONPATH=%cd%

REM Démarrage dans une nouvelle console cmd
start cmd /k "cd /d %cd% && .venv\Scripts\python.exe -m streamlit run app/main.py"

REM Retour dans le dossier initial des scripts
cd /d "%~dp0"

pause
