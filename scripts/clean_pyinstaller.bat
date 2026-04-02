@echo off
REM Nettoyage des dossiers de compilation PyInstaller
cd /d %~dp0

echo [INFO] Suppression du dossier build...
rmdir /s /q ..\build

echo [INFO] Suppression des exécutables dans \exe...
del /q ..\exe\*.exe

echo [INFO] Suppression des éventuels répertoires de scripts internes dans \exe...
for /d %%i in ("..\exe\*") do rmdir /s /q "%%i"

echo [INFO] Suppression des fichiers temporaires (__pycache__)...
for /r %%i in (*) do (
    if "%%~nxi"=="__pycache__" rmdir /s /q "%%i"
)

echo [OK] Nettoyage terminé.
pause
