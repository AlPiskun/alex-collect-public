@echo off
REM ===========================================================================
REM  START Alex Collect - open the Control Panel from the repo root
REM ===========================================================================
REM  Double-click: opens the Control Panel.
REM  Drop one or two 9-card sheet scans on this icon: the pipeline dialog
REM  opens with the scans already filled in.
REM
REM  (Same as app\Alex Collect.bat - this one just sits at the top so you
REM   can find it. Make a Desktop shortcut of THIS file: right-click ->
REM   Send to -> Desktop, then Properties -> Change Icon -> alexcollect.ico
REM   in the app folder.)
REM ===========================================================================
setlocal enableextensions
set "LAUNCHER=%~dp0app\Alex Collect.bat"
if not exist "%LAUNCHER%" (
  echo ERROR: app\Alex Collect.bat was not found.
  echo   Re-download the repo zip - the app folder must be intact.
  pause
  exit /b 1
)
call "%LAUNCHER%" %*
exit /b 0
