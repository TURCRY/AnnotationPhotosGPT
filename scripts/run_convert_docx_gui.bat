@echo off
chcp 65001 >nul
cd /d "%~dp0"
cd ..\exe
convert_docx_gui.exe
echo.
pause

