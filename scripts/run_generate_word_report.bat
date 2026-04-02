@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Go to project root (parent of scripts)
cd /d "%~dp0.."
if errorlevel 1 (
  echo [ERR] Cannot cd to project root: "%~dp0.."
  pause
  exit /b 1
)

REM Activate venv
if not exist ".venv\Scripts\activate.bat" (
  echo [ERR] venv not found: ".venv\Scripts\activate.bat"
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"

REM Choose report mode
echo ==========================================
echo Generate Word report
echo ==========================================
echo 1) UI  (all photos from UI CSV)
echo 2) GTP (validated photos only)
set "REPORT_MODE=UI"
set /p "CHOICE=Choose (1/2) then Enter: "
if "%CHOICE%"=="2" set "REPORT_MODE=GTP"

REM Choose retenue filter
echo.
echo Filter "retenue" ?
echo 1) Yes (only retenue=true/1/oui)
echo 2) No  (keep all)
set "REPORT_ONLY_RETENUE=1"
set /p "CHOICE2=Choose (1/2) then Enter: "
if "%CHOICE2%"=="2" set "REPORT_ONLY_RETENUE=0"

echo.
echo [INFO] REPORT_MODE=%REPORT_MODE%
echo [INFO] REPORT_ONLY_RETENUE=%REPORT_ONLY_RETENUE%
echo.

REM Pass env vars to python
set "REPORT_MODE=%REPORT_MODE%"
set "REPORT_ONLY_RETENUE=%REPORT_ONLY_RETENUE%"

python "scripts\generate_word_report.py"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo [ERR] Python exited with code %RC%
) else (
  echo [OK] Done.
)
pause
exit /b %RC%