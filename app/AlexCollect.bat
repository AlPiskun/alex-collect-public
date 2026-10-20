@echo off
REM ===========================================================================
REM  Alex Collect - Control Panel (GUI launcher, Windows)
REM ===========================================================================
REM  WHAT IT DOES
REM    Opens the one window for every tool: the card pipeline, combining,
REM    staging, the import checklist, wiring the photos, marking a sale on
REM    all four channels, the tick-off checklist, squaring photos and the
REM    logs. Every button in it runs the same tested tool the other .bat
REM    files run - this launcher only picks the window up.
REM
REM    The console-less Python (pythonw) is used when available so you get
REM    just the window. Anything the tools print also lands in
REM    canadianshopper\tools\gui-log.txt, so nothing is ever lost.
REM ===========================================================================
setlocal enableextensions
title Alex Collect - Control Panel
cd /d "%~dp0"

REM ---- 1. find the GUI -----------------------------------------------------
set "GUI="
if exist "gui.py" set "GUI=gui.py"
if not exist "gui.py" if exist "canadianshopper\tools\gui.py" set "GUI=canadianshopper\tools\gui.py"
if not defined GUI (
  echo ERROR: gui.py not found.
  echo   Keep this .bat in the folder that contains canadianshopper\tools\,
  echo   or drop gui.py next to it.
  goto stopped_by_user
)

REM ---- 2. find Python ------------------------------------------------------
set "PY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
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
  goto stopped_by_user
)

REM ---- 3. launch (console-less when possible) ------------------------------
where pythonw >nul 2>&1
if not errorlevel 1 (
  start "Alex Collect" pythonw "%GUI%"
  exit /b 0
)
%PY% "%GUI%"
if errorlevel 1 goto stopped_by_user
exit /b 0

:stopped_by_user
echo.
echo   The window was closed or could not start - see canadianshopper\tools\gui-log.txt
pause
exit /b 1
