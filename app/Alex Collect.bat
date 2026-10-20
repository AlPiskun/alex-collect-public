@echo off
REM ===========================================================================
REM  Alex Collect Control Panel - click to open, or DROP scans on it
REM ===========================================================================
REM  Double-click:  opens the Control Panel window.
REM
REM  Drop files on this icon: one or two 9-card sheet scans (FRONT, and BACK
REM  if you have one) - the pipeline dialog opens with the scans already
REM  filled in. That is the drag-and-drop from the old card_pipeline .bat,
REM  now living inside the app.
REM
REM  This file is intentionally named with spaces - it is the desktop icon.
REM  AlexCollect.bat (no spaces) is the plain launcher and stays as it is.
REM ===========================================================================
setlocal enableextensions
cd /d "%~dp0"

set "GUI="
if exist "AlexCollect-gui.py" set "GUI=AlexCollect-gui.py"
if not defined GUI if exist "gui.py" set "GUI=gui.py"
if not defined GUI if exist "canadianshopper\tools\gui.py" set "GUI=canadianshopper\tools\gui.py"
if not defined GUI goto no_gui

REM ---- the bundled runtime (zero-prerequisite install) wins when present ----
if exist "%~dp0runtime\python-embed\pythonw.exe" goto bundled_start

REM ---- 1. is there a REAL Python here? (the Store alias is not one) ----
set "PY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto no_python

REM ---- 2. a pythonw that actually runs (the Store alias would fail) ----
set "PYW="
where pythonw >nul 2>&1
if errorlevel 1 goto plain_start
pythonw -c "import sys" >nul 2>&1
if errorlevel 1 goto plain_start
set "PYW=pythonw"
if defined PYW (
  if "%~1"=="" (
    start "Alex Collect" "%PYW%" "%GUI%"
  ) else (
    start "Alex Collect" "%PYW%" "%GUI%" %*
  )
  exit /b 0
)
if "%~1"=="" (
    start "Alex Collect" python "%GUI%"
) else (
    start "Alex Collect" python "%GUI%" %*
)
exit /b 0

:bundled_start
if "%~1"=="" (
    start "Alex Collect" "%~dp0runtime\python-embed\pythonw.exe" "%GUI%"
) else (
    start "Alex Collect" "%~dp0runtime\python-embed\pythonw.exe" "%GUI%" %*
)
exit /b 0

:plain_start
if "%~1"=="" (
    start "Alex Collect" %PY% "%GUI%"
) else (
    start "Alex Collect" %PY% "%GUI%" %*
)
exit /b 0

:no_python
echo ERROR: Python 3 was not found on this PC.
echo.
echo   OPTION A - install Python from www.python.org/downloads and tick
echo     "Add python.exe to PATH" during setup, then run this again.
echo   OPTION B - no Python needed: install the BUNDLED Alex Collect setup
echo     instead - it carries its own Python (installer\README.md).
echo.
echo   NOTE: if a Microsoft Store window opened instead, that is the Store
echo     alias, not Python. OPTION A fixes it; the alias can be switched
echo     off under Settings ^> Apps ^> Advanced app settings ^> App
echo     execution aliases.
pause
exit /b 1

:no_gui
echo ERROR: gui.py was not found next to this file, nor in canadianshopper\tools\.
echo   Keep this .bat in the Scan folder, or drop gui.py next to it.
pause
exit /b 1
