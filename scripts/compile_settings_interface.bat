@echo off
call clean_build_dirs.bat
pyinstaller --noconfirm --clean --distpath ..\exe ..\spec\settings_interface.spec
pause
