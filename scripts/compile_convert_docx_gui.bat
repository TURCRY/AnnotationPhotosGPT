@echo off
REM Compilation du script convert_docx_gui.py avec PyInstaller
cd /d %~dp0
pyinstaller ..\spec\convert_docx_gui.spec
