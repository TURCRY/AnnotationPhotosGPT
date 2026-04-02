@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo SCRIPT EXECUTE : %~f0
echo CWD           : %CD%

REM ======================================================
REM USAGE:
REM   run_all_from_JPG_v2.bat <ID_AFFAIRE> [ROOT_PC]
REM EX:
REM   run_all_from_JPG_v2.bat 2025-J46 \\192.168.0.155\Affaires
REM ======================================================

set "AFFAIRE=%~1"
if "%AFFAIRE%"=="" (
  echo ERREUR: id_affaire requis. Ex: 2025-J46
  exit /b 1
)

set "ROOT_PC=%~2"
if "%ROOT_PC%"=="" set "ROOT_PC=\\192.168.0.155\Affaires"

REM ======================================================
REM 1) Vérifier que l'on est dans ...\Photos\JPG
REM ======================================================
for %%I in ("%CD%") do set "CWD_NAME=%%~nxI"
if /I not "%CWD_NAME%"=="JPG" (
  echo ERREUR: lancer ce .bat depuis le dossier "...\\Photos\\JPG"
  echo Dossier courant: %CD%
  exit /b 1
)

REM Dossiers source
for %%I in ("%CD%") do set "SRC_JPG=%%~fI"
for %%I in ("%CD%\..") do set "SRC_PHOTOS=%%~fI"
for %%I in ("%CD%\..\..") do set "CAPT_EVENT_DIR=%%~fI"
for %%I in ("%CD%\..\..\Audio") do set "SRC_AUDIO=%%~fI"

REM ======================================================
REM 2) Déduire id_captation depuis le nom du dossier de captation
REM    Ex: "Accedit 06 11 2025" -> "accedit-2025-11-06"
REM ======================================================
echo CAPT_EVENT_DIR=%CAPT_EVENT_DIR%

where python >nul 2>&1
if errorlevel 1 (
  echo ERREUR: python introuvable dans le PATH
  exit /b 90
)
python --version

for /f "usebackq delims=" %%i in (`python -c "import os,re; p=os.path.normpath(r'%CAPT_EVENT_DIR%'); n=os.path.basename(p); m=re.match(r'(?i)^\s*([a-z0-9]+)\s+(\d{2})\s+(\d{2})\s+(\d{4})\s*$', n); print('' if not m else f'{m.group(1).lower()}-{m.group(4)}-{m.group(3)}-{m.group(2)}')"` ) do set "CAPTATION=%%i"

if "%CAPTATION%"=="" (
  echo ERREUR: impossible de deduire id_captation depuis "%CAPT_EVENT_DIR%"
  echo Attendu: "Slug JJ MM AAAA" (ex: "Accedit 06 11 2025")
  exit /b 2
)

REM ======================================================
REM 3) Détecter PHOTOS_CSV (UI) dans Photos
REM ======================================================
for /f "usebackq delims=" %%i in (`
  python -c ^
"from pathlib import Path; d=Path(r'%SRC_PHOTOS%'); ^
c=[p for p in d.glob('*.csv') if ('_GTP_' not in p.name and '_batch' not in p.stem.lower())]; ^
c=sorted(c, key=lambda p: p.stat().st_mtime, reverse=True); print(str(c[0]) if c else '')"`) do set "PHOTOS_CSV=%%i"

if "%PHOTOS_CSV%"=="" (
  echo ERREUR: aucun CSV UI detecte dans "%SRC_PHOTOS%"
  exit /b 3
)

for /f "usebackq delims=" %%i in (`python -c "from pathlib import Path; p=Path(r'%PHOTOS_CSV%'); print(p.name)"`) do set "PHOTOS_CSV_NAME=%%i"

set "PHOTOS_BATCH=%SRC_PHOTOS%\photos_batch.csv"
if not exist "%PHOTOS_BATCH%" (
  echo INFO: photos_batch.csv absent -> creation minimale a partir de photos.csv
  python -c ^
"import csv; from pathlib import Path; ui=Path(r'%PHOTOS_CSV%'); out=Path(r'%PHOTOS_BATCH%'); ^
rows=list(csv.DictReader(ui.open('r',encoding='utf-8-sig'), delimiter=';')); ^
hdr=['photo_rel_native','chemin_photo_native_pcfixe','chemin_photo_reduite_pcfixe','photo_disponible_pcfixe','date_copie_pcfixe', ^
'description_vlm_batch','libelle_propose_batch','commentaire_propose_batch','batch_status','batch_id','batch_ts', ^
'vlm_batch_ts','vlm_status','vlm_batch_id','vlm_err','vlm_prompt_ctx_len','vlm_img_bytes','vlm_mode','vlm_call_id', ^
'sujets_ids','sujets_scores','sujets_method','sujets_justif']; ^
with out.open('w',encoding='utf-8-sig',newline='') as f: ^
 w=csv.DictWriter(f, fieldnames=hdr, delimiter=';'); w.writeheader(); ^
 for r in rows: w.writerow({**{h:'' for h in hdr}, 'photo_rel_native': r.get('photo_rel_native','')})"
)

REM ======================================================
REM 4) Détecter transcription/audio/contexte dans Audio (si existe)
REM ======================================================
set "TRANSCRIPT_CSV="
set "WAV_MONO16="
set "WAV_SOURCE="
set "CTX_GENERAL="

if exist "%SRC_AUDIO%\" (
  for /f "usebackq delims=" %%i in (`
    python -c ^
"from pathlib import Path; d=Path(r'%SRC_AUDIO%'); ^
c=sorted(d.glob('*_mono16_16000Hz(wav).csv'), key=lambda p: p.stat().st_mtime, reverse=True); ^
print(str(c[0]) if c else '')"`) do set "TRANSCRIPT_CSV=%%i"

  for /f "usebackq delims=" %%i in (`
    python -c ^
"from pathlib import Path; d=Path(r'%SRC_AUDIO%'); ^
c=sorted(d.glob('*_mono16_16000Hz.wav'), key=lambda p: p.stat().st_mtime, reverse=True); ^
print(str(c[0]) if c else '')"`) do set "WAV_MONO16=%%i"

  REM WAV source : si vous avez aussi un gros WAV "original", on le prend ; sinon on retombe sur mono16
  for /f "usebackq delims=" %%i in (`
    python -c ^
"from pathlib import Path; d=Path(r'%SRC_AUDIO%'); ^
cand=[p for p in d.glob('*.WAV')] + [p for p in d.glob('*.wav')]; ^
cand=[p for p in cand if 'mono16_16000Hz' not in p.name]; ^
cand=sorted(cand, key=lambda p: p.stat().st_mtime, reverse=True); ^
print(str(cand[0]) if cand else '')"`) do set "WAV_SOURCE=%%i"

  if "%WAV_SOURCE%"=="" set "WAV_SOURCE=%WAV_MONO16%"

  for /f "usebackq delims=" %%i in (`
    python -c ^
"from pathlib import Path; d=Path(r'%SRC_AUDIO%'); ^
cand=sorted(d.glob('contexte_general*.json'), key=lambda p: p.stat().st_mtime, reverse=True); ^
print(str(cand[0]) if cand else '')"`) do set "CTX_GENERAL=%%i"
) else (
  echo ATTENTION: dossier Audio frere introuvable: "%SRC_AUDIO%"
)

REM ======================================================
REM 5) Cibles PC fixe (architecture canonique)
REM ======================================================
set "DST_BASE=%ROOT_PC%\%AFFAIRE%\AE_Expert_captations\%CAPTATION%"
set "DST_PHOTOS=%DST_BASE%\photos"
set "DST_JPG=%DST_PHOTOS%\JPG"
set "DST_REDUIT=%DST_PHOTOS%\JPG reduit"
set "DST_AUDIO=%DST_BASE%\audio"
set "DST_TRANS=%ROOT_PC%\%AFFAIRE%\AF_Expert_ASR\transcriptions\%CAPTATION%"

mkdir "%DST_JPG%" >nul 2>&1
mkdir "%DST_REDUIT%" >nul 2>&1
mkdir "%DST_AUDIO%" >nul 2>&1
mkdir "%DST_TRANS%" >nul 2>&1

echo ----------------------------------------
echo AFFAIRE        = %AFFAIRE%
echo CAPTATION      = %CAPTATION%
echo ROOT_PC        = %ROOT_PC%
echo SRC_PHOTOS     = %SRC_PHOTOS%
echo SRC_AUDIO      = %SRC_AUDIO%
echo PHOTOS_CSV     = %PHOTOS_CSV%
echo TRANSCRIPT_CSV = %TRANSCRIPT_CSV%
echo WAV_MONO16     = %WAV_MONO16%
echo WAV_SOURCE     = %WAV_SOURCE%
echo CTX_GENERAL    = %CTX_GENERAL%
echo ----------------------------------------

REM ======================================================
REM 6) Post-sync photos.csv (renseigne champs pcfixe)
REM ======================================================
echo [1/7] Mise a jour photos.csv (champs pcfixe)...
python "C:\AnnotationPhotosGPT\scripts\batch_photos_post_sync.py" ^
  --photos_csv "%PHOTOS_CSV%" ^
  --id_affaire "%AFFAIRE%" ^
  --id_captation "%CAPTATION%" ^
  --root_pcfixe "%ROOT_PC%"

if errorlevel 1 (
  echo ERREUR: batch_photos_post_sync.py a echoue
  exit /b 10
)

REM ======================================================
REM 7) Copies photos (Robocopy: echec si >=8)
REM ======================================================
echo [2/7] Copie JPG natifs...
robocopy "%SRC_JPG%" "%DST_JPG%" *.jpg *.jpeg *.JPG *.JPEG /E /COPY:DAT /DCOPY:T /R:1 /W:1
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERREUR robocopy code=%RC%
  echo SRC="%SRC_JPG%"
  echo DST="%DST_JPG%"
  exit /b %RC%
)
if %RC% GEQ 8 exit /b %RC%


echo [3/7] Copie JPG reduit (si existe)...
if exist "%SRC_PHOTOS%\JPG reduit\" (
  robocopy "%SRC_PHOTOS%\JPG reduit" "%DST_REDUIT%" *.jpg *.jpeg *.JPG *.JPEG /E /COPY:DAT /DCOPY:T /R:1 /W:1
  set "RC=%ERRORLEVEL%"
  if %RC% GEQ 8 (
    echo ERREUR robocopy code=%RC%
    echo SRC="%SRC_JPG%"
    echo DST="%DST_JPG%"
    exit /b %RC%
    )
  if %RC% GEQ 8 exit /b %RC%
)

echo [4/7] Copie Photos (CSV/XLS/XLSX)...
robocopy "%SRC_PHOTOS%" "%DST_PHOTOS%" "*.csv" "*.xls" "*.xlsx" /R:1 /W:1
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo ERREUR robocopy code=%RC%
  echo SRC="%SRC_JPG%"
  echo DST="%DST_JPG%"
  exit /b %RC%
)

if %RC% GEQ 8 exit /b %RC%

REM ======================================================
REM 8) Copies audio/transcriptions/contextes
REM ======================================================
echo [5/7] Copie audio/transcriptions depuis Audio...
if exist "%SRC_AUDIO%\" (
  robocopy "%SRC_AUDIO%" "%DST_AUDIO%" "*.wav" "*.WAV" /R:1 /W:1
  set "RC=%ERRORLEVEL%"
  if %RC% GEQ 8 (
    echo ERREUR robocopy code=%RC%
    echo SRC="%SRC_JPG%"
    echo DST="%DST_JPG%"
    exit /b %RC%
  )
  if %RC% GEQ 8 exit /b %RC%

  robocopy "%SRC_AUDIO%" "%DST_TRANS%" "*.csv" "*.srt" "*.vtt" "*.txt" "*.json" "*.xlsx" /R:1 /W:1
  set "RC=%ERRORLEVEL%"
  if %RC% GEQ 8 (
    echo ERREUR robocopy code=%RC%
    echo SRC="%SRC_JPG%"
    echo DST="%DST_JPG%"
    exit /b %RC%
    )

  if %RC% GEQ 8 exit /b %RC%
)

REM ======================================================
REM 9) Dépôt prompts/config
REM ======================================================
echo [6/7] Depot prompts/config...
set "PROMPT_SRC=C:\AnnotationPhotosGPT\config\prompt_gpt.json"
if exist "%PROMPT_SRC%" copy /Y "%PROMPT_SRC%" "%DST_TRANS%\prompt_gpt.json" >nul

set "PROMPT_BATCH_SRC=C:\AnnotationPhotosGPT\config\prompt_gpt_batch_only.json"
if exist "%PROMPT_BATCH_SRC%" copy /Y "%PROMPT_BATCH_SRC%" "%DST_TRANS%\prompt_gpt_batch_only.json" >nul

set "CFG_SRC=C:\AnnotationPhotosGPT\config\config.json"
if exist "%CFG_SRC%" copy /Y "%CFG_SRC%" "%DST_TRANS%\config_llm.json" >nul

REM ======================================================
REM 9bis) Copier contextes + annexes depuis le dossier Audio -> DST_TRANS
REM ======================================================
echo [6bis/7] Copie contextes + annexes (Audio -> transcriptions)...

if not exist "%SRC_AUDIO%\" (
  echo ATTENTION: dossier Audio introuvable: "%SRC_AUDIO%"
) else (
  REM contextes
  if exist "%SRC_AUDIO%\contexte_general*.json" (
    copy /Y "%SRC_AUDIO%\contexte_general*.json" "%DST_TRANS%\" >nul
  )

  REM proper names (on copie tout ce qui matche)
  if exist "%SRC_AUDIO%\*proper_names*.txt" (
    copy /Y "%SRC_AUDIO%\*proper_names*.txt" "%DST_TRANS%\" >nul
  )

  REM tableurs
  if exist "%SRC_AUDIO%\Participants.xls"  copy /Y "%SRC_AUDIO%\Participants.xls"  "%DST_TRANS%\" >nul
  if exist "%SRC_AUDIO%\Participants.xlsx" copy /Y "%SRC_AUDIO%\Participants.xlsx" "%DST_TRANS%\" >nul
  if exist "%SRC_AUDIO%\Sujets.xls"        copy /Y "%SRC_AUDIO%\Sujets.xls"        "%DST_TRANS%\" >nul
  if exist "%SRC_AUDIO%\Sujets.xlsx"       copy /Y "%SRC_AUDIO%\Sujets.xlsx"       "%DST_TRANS%\" >nul
)


REM ======================================================
REM 10) Génération infos_projet.json (même structure que J37)
REM     - sur le laptop : dans ...\Audio\infos_projet.json (si Audio existe), sinon dans ...\Photos\infos_projet.json
REM     - sur le PC fixe : dans %DST_TRANS%\infos_projet.json
REM     NOTE : on évite d'inventer des fichiers ; si un élément est introuvable => "".
REM ======================================================
echo [7/7] Generation infos_projet.json...

set "INFOS_LAPTOP=%SRC_AUDIO%\infos_projet.json"
if not exist "%SRC_AUDIO%\" set "INFOS_LAPTOP=%SRC_PHOTOS%\infos_projet.json"
python -c ^
"import json; from pathlib import Path; ^
aff=r'%AFFAIRE%'; capt=r'%CAPTATION%'; ^
photos_csv=Path(r'%PHOTOS_CSV%'); photos_batch=Path(r'%PHOTOS_BATCH%'); ^
tr_csv=Path(r'%TRANSCRIPT_CSV%') if r'%TRANSCRIPT_CSV%' else Path(''); ^
wav_mono=Path(r'%WAV_MONO16%') if r'%WAV_MONO16%' else Path(''); ^
wav_src=Path(r'%WAV_SOURCE%') if r'%WAV_SOURCE%' else Path(''); ^
ctx=Path(r'%CTX_GENERAL%') if r'%CTX_GENERAL%' else Path(''); ^
root_pc=Path(r'%ROOT_PC%'); ^
dst_base=root_pc/aff/'AE_Expert_captations'/capt; dst_ph=dst_base/'photos'; dst_au=dst_base/'audio'; ^
dst_tr=root_pc/aff/'AF_Expert_ASR'/'transcriptions'/capt; ^
pn=''; cand=sorted(Path(r'%DST_TRANS%').glob('*proper_names*.txt')); pn=str(cand[0]) if cand else ''; ^
d={ ^
 'fichier_transcription': str(tr_csv) if tr_csv and tr_csv.exists() else '', ^
 'fichier_photos': str(photos_csv) if photos_csv.exists() else '', ^
 'fichier_photos_batch': str(photos_batch) if photos_batch.exists() else '', ^
 'fichier_audio': r'C:\\AnnotationPhotosGPT\\data\\temp\\audio_compatible.wav', ^
 'audio_compat_source': str(wav_mono) if wav_mono and wav_mono.exists() else '', ^
 'fichier_audio_source': str(wav_src) if wav_src and wav_src.exists() else '', ^
 'fichier_audio_compatible': r'C:\\AnnotationPhotosGPT\\data\\temp\\audio_compatible.wav', ^
 'fichier_contexte_general': str(ctx) if ctx and ctx.exists() else '', ^
 'pcfixe': { ^
   'fichier_transcription': str(dst_tr/(tr_csv.name if tr_csv.name else '')), ^
   'fichier_photos': str(dst_ph/photos_csv.name), ^
   'fichier_photos_batch': str(dst_ph/(photos_batch.name if photos_batch.name else 'photos_batch.csv')), ^
   'fichier_audio': str(dst_au/'audio_compatible.wav'), ^
   'audio_compat_source': str(dst_au/(wav_mono.name if wav_mono.name else '')), ^
   'fichier_audio_source': str(dst_au/(wav_src.name if wav_src.name else '')), ^
   'fichier_audio_compatible': str(dst_au/'audio_compatible.wav'), ^
   'fichier_contexte_general': str(dst_tr/(ctx.name if ctx.name else '')), ^
   'config_llm': str(dst_tr/'config_llm.json'), ^
   'out_dir': str(dst_au/'out'), ^
   'boost_file': r'D:\\GPT4All_Local\\config\\boost_vocab.txt', ^
   'max_speakers': 6, ^
   'proper_names_file': pn ^
 }, ^
 'profil_execution':'pcfixe', 'id_affaire': aff, 'id_captation': capt ^
}; ^
Path(r'%INFOS_LAPTOP%').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); ^
Path(r'%DST_TRANS%\\infos_projet.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')"


REM Astuce pratique : si un wav mono16 existe, on le duplique aussi en audio_compatible.wav (fichier réel, pas “inventé”)
if exist "%WAV_MONO16%" (
  copy /Y "%WAV_MONO16%" "%DST_AUDIO%\audio_compatible.wav" >nul
)


echo ========================================
echo OK - copie terminee
echo DST_BASE  = %DST_BASE%
echo DST_TRANS = %DST_TRANS%
echo INFOS     = %INFOS_LAPTOP%
echo ========================================
endlocal
exit /b 0
