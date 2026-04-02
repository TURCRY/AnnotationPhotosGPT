@echo off
REM Compilation du script generate_word_report.py avec PyInstaller
cd /d %~dp0
pyinstaller --noconfirm ..\spec\generate_word_report.spec --distpath ..\exe
pause

