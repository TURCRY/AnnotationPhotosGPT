@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo Lancement de la conversion .docx → .csv
echo ==========================================

cd ..\exe
convert_transcription_docx.exe
echo.
pause

