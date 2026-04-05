@echo off
echo SCRIPT EXECUTE : %~f0
setlocal EnableExtensions EnableDelayedExpansion

set "AFFAIRE=2025-J37"
set "CAPTATION=accedit-2025-09-02"
set "ROOT_PC=\\192.168.0.155\Affaires"
cd /d C:\AnnotationPhotosGPT\scripts
set "INFOS_PROJET=C:\AnnotationPhotosGPT\data\infos_projet.json"

for /f "usebackq delims=" %%i in (`python -c "import json; p=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); print(p.get('fichier_photos',''))"`) do set "PHOTOS_CSV=%%i"
if "%PHOTOS_CSV%"=="" goto :FAIL_PHOTOS
if not exist "%PHOTOS_CSV%" goto :FAIL_PHOTOS_EXIST

for /f "usebackq delims=" %%i in (`python -c "from pathlib import Path; p=Path(r'%PHOTOS_CSV%'); print(str(p.parent))"`) do set "PHOTOS_DIR=%%i"
for /f "usebackq delims=" %%i in (`python -c "from pathlib import Path; p=Path(r'%PHOTOS_CSV%'); print(p.stem)"`) do set "BASE_NAME=%%i"

for /f "usebackq delims=" %%i in (`python -c "import json; from pathlib import Path; d=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); v=d.get('fichier_transcription',''); print(str(Path(v).parent) if v else '')"`) do set "TRANSCRIPT_SRC_DIR=%%i"
for /f "usebackq delims=" %%i in (`python -c "import json; d=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); print(d.get('fichier_audio_source','') or d.get('audio_compat_source','') or '')"`) do set "WAV_SRC=%%i"
for /f "usebackq delims=" %%i in (`python -c "import json; d=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); print(d.get('fichier_audio_compatible','') or d.get('fichier_audio','') or '')"`) do set "WAV_COMPAT=%%i"
for /f "usebackq delims=" %%i in (`python -c "import json; from pathlib import Path; d=json.load(open(r'%INFOS_PROJET%',encoding='utf-8')); v=d.get('fichier_audio',''); print(str(Path(v).parent) if v else '')"`) do set "AUDIO_DIR=%%i"

set "DST_BASE=%ROOT_PC%\%AFFAIRE%\AE_Expert_captations\%CAPTATION%"
set "DST_PHOTOS=%DST_BASE%\photos"
set "DST_AUDIO=%DST_BASE%\audio"
set "DST_TRANSCRIPT_DIR=%ROOT_PC%\%AFFAIRE%\AF_Expert_ASR\transcriptions\%CAPTATION%"

if not exist "%ROOT_PC%\%AFFAIRE%\" goto :FAIL_AFFAIRE

mkdir "%DST_PHOTOS%" >nul 2>&1
mkdir "%DST_AUDIO%" >nul 2>&1
mkdir "%DST_TRANSCRIPT_DIR%" >nul 2>&1

echo [B] Copie WAV...
if not "%WAV_SRC%"=="" if exist "%WAV_SRC%" (copy /Y "%WAV_SRC%" "%DST_AUDIO%\" >nul) else (echo ATTENTION: WAV source introuvable "%WAV_SRC%")
if not "%WAV_COMPAT%"=="" if exist "%WAV_COMPAT%" (copy /Y "%WAV_COMPAT%" "%DST_AUDIO%\" >nul) else (echo ATTENTION: WAV compatible introuvable "%WAV_COMPAT%")

echo [C] Copie CSV/XLS/XLSX + GTP...
robocopy "%PHOTOS_DIR%" "%DST_PHOTOS%" "%BASE_NAME%.csv" /R:1 /W:1
set "RC=%ERRORLEVEL%"
echo DEBUG robocopy CSV RC=!RC!
if !RC! GEQ 8 goto :FAIL_RC

robocopy "%PHOTOS_DIR%" "%DST_PHOTOS%" "%BASE_NAME%.xlsx" "%BASE_NAME%.xls" /R:1 /W:1
set "RC=%ERRORLEVEL%"
echo DEBUG robocopy XLS/XLSX RC=!RC!
if !RC! GEQ 8 goto :FAIL_RC

robocopy "%PHOTOS_DIR%" "%DST_PHOTOS%" "%BASE_NAME%_GTP_*.csv" "%BASE_NAME%_GTP_*.xlsx" /R:1 /W:1
set "RC=%ERRORLEVEL%"
echo DEBUG robocopy GTP RC=!RC!
if !RC! GEQ 8 goto :FAIL_RC

echo [D] Depot prompts + infos + config + contextes...
set "PROMPT_SRC=C:\AnnotationPhotosGPT\config\prompt_gpt.json"
if exist "%PROMPT_SRC%" (copy /Y "%PROMPT_SRC%" "%DST_TRANSCRIPT_DIR%\prompt_gpt.json" >nul) else (echo ATTENTION: prompt_gpt.json introuvable "%PROMPT_SRC%")

set "PROMPT_BATCH_SRC=C:\AnnotationPhotosGPT\config\prompt_gpt_batch_only.json"
if exist "%PROMPT_BATCH_SRC%" (copy /Y "%PROMPT_BATCH_SRC%" "%DST_TRANSCRIPT_DIR%\prompt_gpt_batch_only.json" >nul) else (echo ATTENTION: prompt_gpt_batch_only.json introuvable "%PROMPT_BATCH_SRC%")

set "DST_INFOS=%DST_TRANSCRIPT_DIR%\infos_projet.json"
copy /Y "%INFOS_PROJET%" "%DST_INFOS%" >nul

set "CFG_SRC=C:\AnnotationPhotosGPT\config\config.json"
set "CFG_DST=%DST_TRANSCRIPT_DIR%\config_llm.json"
if exist "%CFG_SRC%" (copy /Y "%CFG_SRC%" "%CFG_DST%" >nul) else (echo ATTENTION: config.json introuvable "%CFG_SRC%")

if not "%TRANSCRIPT_SRC_DIR%"=="" if exist "%TRANSCRIPT_SRC_DIR%\contexte_general_photos.json" (copy /Y "%TRANSCRIPT_SRC_DIR%\contexte_general_photos.json" "%DST_TRANSCRIPT_DIR%\contexte_general_photos.json" >nul) else if exist "%AUDIO_DIR%\contexte_general_photos.json" (copy /Y "%AUDIO_DIR%\contexte_general_photos.json" "%DST_TRANSCRIPT_DIR%\contexte_general_photos.json" >nul) else (echo ATTENTION: contexte_general_photos.json introuvable)

if not "%TRANSCRIPT_SRC_DIR%"=="" if exist "%TRANSCRIPT_SRC_DIR%\contexte_general_compte_rendu.json" (copy /Y "%TRANSCRIPT_SRC_DIR%\contexte_general_compte_rendu.json" "%DST_TRANSCRIPT_DIR%\contexte_general_compte_rendu.json" >nul) else (echo ATTENTION: contexte_general_compte_rendu.json introuvable)

echo [E] Copie transcriptions + annexes...
if "%TRANSCRIPT_SRC_DIR%"=="" goto :WARN_TRANSCRIPT
if not exist "%TRANSCRIPT_SRC_DIR%" goto :WARN_TRANSCRIPT_EXIST
robocopy "%TRANSCRIPT_SRC_DIR%" "%DST_TRANSCRIPT_DIR%" *.csv *.srt *.vtt *.txt *.json *.xlsx /R:1 /W:1
set "RC=%ERRORLEVEL%"
echo DEBUG robocopy transcriptions RC=!RC!
if !RC! GEQ 8 goto :FAIL_RC
goto :NORM

:WARN_TRANSCRIPT
echo ATTENTION: TRANSCRIPT_SRC_DIR vide
goto :NORM

:WARN_TRANSCRIPT_EXIST
echo ATTENTION: dossier transcription source introuvable "%TRANSCRIPT_SRC_DIR%"
goto :NORM

:NORM
echo [F] Normalisation infos_projet.json (basenames)...
python -c "import json; from pathlib import Path; p=Path(r'%DST_INFOS%'); d=json.load(p.open(encoding='utf-8')); \
for k in ('fichier_photos','fichier_transcription','fichier_contexte_general','fichier_audio','fichier_audio_source','audio_compat_source','fichier_audio_compatible'): \
    v=d.get(k); \
    if isinstance(v,str) and v.strip(): d[k]=Path(v).name; \
p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')"

echo ========================================
echo OK - run_all_laptop_part3 termine avec succes
echo ========================================
endlocal
pause
exit /b 0

:FAIL_PHOTOS
echo ERREUR: fichier_photos absent dans infos_projet.json
endlocal
pause
exit /b 1

:FAIL_PHOTOS_EXIST
echo ERREUR: PHOTOS_CSV introuvable "%PHOTOS_CSV%"
endlocal
pause
exit /b 1

:FAIL_AFFAIRE
echo ERREUR: affaire absente sur le PC fixe "%ROOT_PC%\%AFFAIRE%"
endlocal
pause
exit /b 1

:FAIL_RC
echo ERREUR: robocopy a echoue (RC=!RC!)
endlocal
pause
exit /b 2
