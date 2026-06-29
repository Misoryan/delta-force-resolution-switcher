@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Close running instance if any...
taskkill /IM DeltaResolutionSwitcher.exe /F >nul 2>&1

echo Installing build dependencies...
python -m pip install -r requirements.txt pyinstaller -q
if errorlevel 1 exit /b 1

echo Building DeltaResolutionSwitcher.exe ...
python -m PyInstaller DeltaResolutionSwitcher.spec --noconfirm --clean
if errorlevel 1 exit /b 1

if not exist "dist\config.json" copy /Y "config.json" "dist\config.json" >nul

echo.
echo Done: dist\DeltaResolutionSwitcher.exe
echo       dist\config.json
echo.
pause
endlocal
