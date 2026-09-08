@echo off
setlocal
title Clinic Registry - Server
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=5000"

echo.
echo ============================================================
echo    Clinic Registry - Starting the server
echo ============================================================
echo.

REM ---------- Find a Python interpreter ----------
set "VENV_PY=.venv\Scripts\python.exe"
set "PYCMD="

if exist "%VENV_PY%" goto HAVE_PY

where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
  if not errorlevel 1 set "PYCMD=py -3"
)
if defined PYCMD goto HAVE_PY

where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
  if not errorlevel 1 set "PYCMD=python"
)
if defined PYCMD goto HAVE_PY

echo    [ERROR] Python 3.9 or newer was not found.
echo    Please double-click  install.bat  first.
echo.
pause
exit /b 1

:HAVE_PY
if not defined PYCMD (
  set "PYCMD=%VENV_PY%"
  echo    Using the local virtual environment.
) else (
  echo    Using system Python: %PYCMD%
)
echo.

REM ---------- Make sure the packages are installed ----------
echo    Checking packages ...
%PYCMD% -c "import flask, openpyxl" >nul 2>nul
if not errorlevel 1 goto PACKAGES_OK

echo    Packages are missing. Installing them now - please wait ...
%PYCMD% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --disable-pip-version-check
if errorlevel 1 %PYCMD% -m pip install -r requirements.txt --disable-pip-version-check
%PYCMD% -c "import flask, openpyxl" >nul 2>nul
if errorlevel 1 goto PKG_FAIL

:PACKAGES_OK
echo    Packages OK.
echo.

REM ---------- Check the port ----------
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul 2>nul
if errorlevel 1 goto STARTING
echo    [WARNING] Port %PORT% is already in use by another program.
echo    Trying port 5001 instead ...
set "PORT=5001"
echo.

:STARTING
echo ============================================================
echo    The server is starting. KEEP THIS WINDOW OPEN.
echo    Closing this window will stop the system.
echo ============================================================
echo.

start "" http://127.0.0.1:%PORT%
%PYCMD% run.py --port %PORT% --open

echo.
echo    The server has stopped.
pause
exit /b 0

:PKG_FAIL
echo.
echo    [ERROR] Could not install the required packages.
echo    Please run  install.bat  or  check.bat  to see details.
echo.
pause
exit /b 1
