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

:: 始终用源代码目录中的最新 config.json 覆盖 dist 中的副本
copy /Y "config.json" "dist\config.json" >nul
:: 复制图标资源文件夹
if exist "dist\assets" rmdir /S /Q "dist\assets"
xcopy /E /Y /I "assets" "dist\assets" >nul

echo.
echo Done: dist\DeltaResolutionSwitcher.exe
echo       dist\config.json
echo       dist\assets\
echo.
pause
endlocal
