@echo off
setlocal
title Clinic Registry - Environment Check
cd /d "%~dp0"

echo.
echo ============================================================
echo    Clinic Registry - Environment Check
echo    This window only READS information, it changes nothing.
echo    If the system will not start, send me this output.
echo ============================================================
echo.

echo ---- [1] Where is this folder ----
echo %CD%
echo.

echo ---- [2] Folder contents ----
dir /b
echo.

echo ---- [3] Python launcher / python.exe ----
where py 2>nul
where python 2>nul
if errorlevel 1 echo    neither py nor python was found
echo.

echo ---- [4] Python version ----
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYCMD=python"
)
if defined PYCMD (
  %PYCMD% -c "import sys; print('    version:', sys.version); print('    executable:', sys.executable)"
) else (
  echo    Python NOT found
)
echo.

echo ---- [5] Virtual environment ----
if exist ".venv\Scripts\python.exe" (
  echo    .venv exists
  ".venv\Scripts\python.exe" -c "import sys; print('    venv version:', sys.version.split()[0])"
) else (
  echo    .venv NOT created
)
echo.

echo ---- [6] Required packages ----
if defined PYCMD (
  %PYCMD% -c "import flask; print('    flask', flask.__version__)" 2>nul || echo    flask MISSING
  %PYCMD% -c "import openpyxl; print('    openpyxl', openpyxl.__version__)" 2>nul || echo    openpyxl MISSING
  %PYCMD% -c "import flask_login; print('    flask_login OK')" 2>nul || echo    flask_login MISSING
  %PYCMD% -c "import flask_sqlalchemy; print('    flask_sqlalchemy OK')" 2>nul || echo    flask_sqlalchemy MISSING
)
echo.

echo ---- [7] Database file ----
if exist "data\registry.db" (
  echo    data\registry.db exists
  for %%A in ("data\registry.db") do echo    size: %%~zA bytes
) else (
  echo    No database yet - it will be created at first startup
)
echo.

echo ---- [8] Port 5000 ----
netstat -ano | findstr ":5000 " | findstr "LISTENING"
if errorlevel 1 echo    port 5000 is free
echo.

echo ---- [9] This computer IP address ----
ipconfig | findstr /i "IPv4"
echo.

echo ============================================================
echo    Check finished.
echo ============================================================
echo.
pause
