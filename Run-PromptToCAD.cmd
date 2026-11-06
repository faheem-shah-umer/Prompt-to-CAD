@echo off
rem The one Prompt to CAD launcher. Double-click it to open the app built in build\bin.
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo Python environment missing. Install CPython 3.11 x64, then run:
    echo   py -3.11 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    echo Follow README.md for SDK setup and the source build.
    set "result=1"
    goto finish
)
rem With no arguments (a double-click), start the app without keeping this console open.
rem Startup problems then appear in a message box. Arguments keep the console for automation.
if "%~1"=="" if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m tools.run_native
    set "result=0"
    goto finish
)
".venv\Scripts\python.exe" -m tools.run_native %*
set "result=%errorlevel%"
:finish
popd
if not "%result%"=="0" if not defined CI pause
exit /b %result%
