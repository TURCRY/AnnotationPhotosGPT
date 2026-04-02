@echo off
REM Suppression des répertoires de compilation
echo Suppression des répertoires de compilation...

REM Dossier principal \build\
if exist build (
    rmdir /s /q build
    echo Dossier \build\ supprimé.
)

REM Dossier secondaire \scripts\build\
if exist scripts\build (
    rmdir /s /q scripts\build
    echo Dossier \scripts\build\ supprimé.
)

echo Nettoyage terminé.
pause
