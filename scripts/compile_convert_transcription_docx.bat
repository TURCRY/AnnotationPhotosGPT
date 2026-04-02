@echo off
title Compilation de convert_transcription_docx.py
echo [INFO] Compilation de convert_transcription_docx.py...

REM Compilation du script convert_transcription_docx.py avec PyInstaller
cd /d %~dp0
REM Compilation avec log console
pyinstaller --clean --noconfirm --distpath ..\exe ..\spec\convert_transcription_docx.spec

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERREUR] La compilation a échoué. Appuyez sur une touche pour quitter...
    pause >nul
    exit /b 1
) ELSE (
    echo.
    echo [OK] Compilation réussie. Appuyez sur une touche pour quitter...
    pause >nul
)