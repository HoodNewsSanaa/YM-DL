@echo off
setlocal
cd /d "%~dp0"
if exist "dist\YM-DL.exe" (
    start "" "dist\YM-DL.exe"
    exit /b 0
)
echo First build the program by double-clicking Build-Windows.cmd.
echo You can also run the source with: python app.py
pause
