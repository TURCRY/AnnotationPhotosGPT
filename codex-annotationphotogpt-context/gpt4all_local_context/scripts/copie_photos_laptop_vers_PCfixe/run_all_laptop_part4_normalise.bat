@echo off
echo SCRIPT NORMALISATION infos_projet.json
setlocal

set "DST_INFOS=\\192.168.0.155\Affaires\2025-J37\AF_Expert_ASR\transcriptions\accedit-2025-09-02\infos_projet.json"

if not exist "%DST_INFOS%" (
  echo ERREUR: infos_projet.json introuvable:
  echo %DST_INFOS%
  pause
  exit /b 1
)

python -c "import json;from pathlib import Path;p=Path(r'%DST_INFOS%');d=json.load(p.open(encoding='utf-8'));keys=('fichier_photos','fichier_transcription','fichier_contexte_general','fichier_audio','fichier_audio_source','audio_compat_source','fichier_audio_compatible');[d.__setitem__(k,Path(d[k]).name) for k in keys if isinstance(d.get(k),str) and d.get(k).strip()];p.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding='utf-8')"

echo OK - normalisation terminee
pause
exit /b 0
