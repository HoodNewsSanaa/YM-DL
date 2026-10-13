@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    set "YM_DL_PYTHON=py -3"
) else (
    set "YM_DL_PYTHON=python"
)
%YM_DL_PYTHON% -c "import sys; assert sys.version_info >= (3, 11), 'Install Python 3.11 or newer'"
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" %YM_DL_PYTHON% -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements-release.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" build_windows.py
if errorlevel 1 goto failed
echo.
echo Finished. The dist folder contains the Windows release ZIP, Sources ZIP and checksums.
start "" explorer.exe "%~dp0dist"
pause
exit /b 0
:failed
echo.
echo Build failed. The error is shown above. Install 64-bit Python 3.11 or newer if needed.
pause
exit /b 1
