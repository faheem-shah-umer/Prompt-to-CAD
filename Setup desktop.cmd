@echo off
setlocal
cd /d "%~dp0"
set "CAD_PYTHON=python"
if exist "C:\Program Files\Python311\python.exe" set "CAD_PYTHON=C:\Program Files\Python311\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set "CAD_PYTHON=%~dp0.venv\Scripts\python.exe"
"%CAD_PYTHON%" -B -m pip install --upgrade --target "%~dp0.desktop-runtime" --no-cache-dir -r requirements-desktop.txt
if errorlevel 1 goto failed
pushd frontend
call npm.cmd run build
set "BUILD_STATUS=%ERRORLEVEL%"
popd
if not "%BUILD_STATUS%"=="0" goto failed
echo Desktop setup complete. Double-click Prompt to CAD.vbs to open the app.
pause
exit /b 0
:failed
echo Desktop setup failed. Check the error above.
pause
exit /b 1
