@echo off
cd /d %~dp0..
if not exist ".venv\Scripts\python.exe" (
  echo ERREUR: environnement virtuel introuvable : .venv\Scripts\python.exe
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m streamlit run app/main.py
pause

