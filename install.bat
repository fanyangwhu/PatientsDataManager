@echo off
setlocal
title Clinic Registry - First-time Setup
cd /d "%~dp0"

echo.
echo ============================================================
echo    Clinic Registry - First-time Setup
echo    Run this ONCE, on the computer that will host the data.
echo ============================================================
echo.

echo [Step 1 of 4] Detecting Python 3.9 or newer ...
set "PYCMD="
set "VENV_PY="

where py >nul 2>nul
if not errorlevel 1 goto TRY_PY
goto TRY_PYTHON

:TRY_PY
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto FOUND_PY

:TRY_PYTHON
where python >nul 2>nul
if errorlevel 1 goto NO_PYTHON
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if defined PYCMD goto FOUND_PY

:NO_PYTHON
echo.
echo    [ERROR] Python 3.9 or newer was not found on this computer.
echo.
echo    What to do:
echo      1. The Python download page will open in your browser now.
echo      2. Download Python 3.12 (or any 3.9+ version).
echo      3. Run the installer. On the FIRST screen you MUST tick the
echo         box "Add python.exe to PATH" at the bottom,
echo         then click "Install Now".
echo      4. When it finishes, double-click this file again.
echo.
echo    Opening https://www.python.org/downloads/ ...
start "" https://www.python.org/downloads/
echo.
echo    If your hospital PC has no internet, copy the Python
echo    installer from another PC and install it manually.
echo.
pause
exit /b 1

:FOUND_PY
echo    Found: %PYCMD%
%PYCMD% -c "import sys; print('    Version:', sys.version.split()[0])"
echo.

echo [Step 2 of 4] Creating a local virtual environment ...
if exist ".venv\Scripts\python.exe" goto VENV_OK
if exist ".venv" (
  echo    Found an incomplete .venv folder, removing it ...
  rmdir /s /q ".venv"
)
%PYCMD% -m venv .venv
if errorlevel 1 goto VENV_FAILED
if not exist ".venv\Scripts\python.exe" goto VENV_FAILED

:VENV_OK
set "VENV_PY=.venv\Scripts\python.exe"
echo    Virtual environment ready.
echo.
goto INSTALL

:VENV_FAILED
echo    [WARNING] Could not create a virtual environment.
echo    Will install the packages into your system Python instead.
echo    This still works fine.
set "VENV_PY=%PYCMD%"
echo.

:INSTALL
echo [Step 3 of 4] Installing packages - this can take 2-5 minutes.
echo               Please wait, do NOT close this window.
echo.

"%VENV_PY%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --disable-pip-version-check
if errorlevel 1 "%VENV_PY%" -m pip install --upgrade pip --disable-pip-version-check

echo.
echo    Installing Flask and openpyxl ...
"%VENV_PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --disable-pip-version-check
if errorlevel 1 (
  echo    Tsinghua mirror failed, trying the official source ...
  "%VENV_PY%" -m pip install -r requirements.txt --disable-pip-version-check
)

echo.
echo [Step 4 of 4] Verifying the installation ...
"%VENV_PY%" -c "import flask, flask_sqlalchemy, flask_login, openpyxl; print('    All packages are installed correctly.')"
if errorlevel 1 goto INSTALL_FAILED

echo.
echo ============================================================
echo    Setup completed successfully!
echo.
echo    From now on, just double-click  start.bat  to run the
echo    system. You do not need to run this file again.
echo ============================================================
echo.
pause
exit /b 0

:INSTALL_FAILED
echo.
echo    [ERROR] Package installation failed.
echo    Common causes:
echo      - No internet connection, or a proxy blocks pip
echo      - Company antivirus intercepts the download
echo.
echo    Try again. If it keeps failing, run  check.bat  and send
echo    me the output, or install manually with:
echo        python -m pip install -r requirements.txt
echo.
pause
exit /b 1
