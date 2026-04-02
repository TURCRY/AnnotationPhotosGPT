@echo off
cd /d %~dp0

set LOGDIR=..\logs
if not exist %LOGDIR% mkdir %LOGDIR%

echo === Compilation convert_docx_gui ===
call compile_convert_docx_gui.bat > %LOGDIR%\convert_docx_gui.log 2>&1

echo === Compilation convert_transcription ===
call compile_convert_transcription.bat > %LOGDIR%\convert_transcription.log 2>&1

echo === Compilation settings_interface ===
call compile_settings_interface.bat > %LOGDIR%\settings_interface.log 2>&1

echo.
echo Tous les journaux ont été enregistrés dans %LOGDIR%
pause
