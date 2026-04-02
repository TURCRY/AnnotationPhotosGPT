@echo off
setlocal

REM === Paramètres à adapter ===
set AFFAIRE=2025-J37
set CAPTATION=2025-09-02-accedit
set ROOT_PC=\\192.168.0.155\Affaires

REM Chemin vers photos.csv (sur laptop)
set PHOTOS_CSV=D:\Affaires\2025-J37\AE_Expert_captations\%CAPTATION%\photos\photos.csv

REM Où sont physiquement les JPG réduits sur laptop
set SRC_REDUIT=D:\Affaires\2025-J37\AE_Expert_captations\%CAPTATION%\photos\JPG reduit

REM Destination PC fixe (chemin miroir)
set DST_REDUIT=%ROOT_PC%\%AFFAIRE%\AE_Expert_captations\%CAPTATION%\photos\JPG reduit

REM 1) Copie en conservant les timestamps (LastWriteTime)
robocopy "%SRC_REDUIT%" "%DST_REDUIT%" *.jpg *.jpeg /E /COPY:DAT /DCOPY:T /R:1 /W:1

REM 2) Mise à jour photos.csv (colonnes + chemins pcfixe + relpaths + flags)
python batch_photos_post_sync.py ^
  --photos_csv "%PHOTOS_CSV%" ^
  --id_affaire "%AFFAIRE%" ^
  --id_captation "%CAPTATION%" ^
  --root_pcfixe "%ROOT_PC%"

endlocal
