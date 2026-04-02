@echo off
REM Compilation forcée avec nettoyage et chemins explicites
cd /d %~dp0

echo [INFO] Compilation de convert_transcription_docx...
pyinstaller --clean --distpath ..\exe --workpath ..\build ..\spec\convert_transcription_docx.spec

echo [INFO] Compilation de convert_docx_gui...
pyinstaller --clean --distpath ..\exe --workpath ..\build ..\spec\convert_docx_gui.spec

echo [INFO] Compilation de generate_word_report...
pyinstaller --clean --distpath ..\exe --workpath ..\build ..\spec\generate_word_report.spec

echo [OK] Compilation terminée.
pause
