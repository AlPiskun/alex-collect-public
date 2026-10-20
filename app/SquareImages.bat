@echo off
REM ===========================================================================
REM  SquareImages.bat - square up card photos for CanadianShopper uploads
REM ===========================================================================
REM  THREE WAYS TO RUN IT (any of them works)
REM    A) Put the photos in a "to-square" folder next to this file and
REM       double-click this file.        <- most reliable, no drag & drop
REM    B) DRAG the photo file(s) onto this file (or drag a whole folder on).
REM    C) From a Command Prompt:   SquareImages.bat "C:\path\to\photo.jpg"
REM
REM  It writes the square copies into a "square" subfolder beside your photos.
REM  No internet, no cookie, nothing is uploaded, nothing is deleted.
REM
REM  THEN, on canadianshopper.ca:  Products -> that card -> Edit
REM    <name>-square.jpg       -> main product image
REM    <name>-back-square.jpg  -> add as a second image (the back / gallery)
REM    Inventory               -> what you actually have left
REM
REM  Every run writes a log to square-log.txt beside this file. If anything
REM  goes wrong, that file says which step failed and why.
REM ===========================================================================
setlocal
title Square card photos for CanadianShopper
cd /d "%~dp0"

set "LOG=%~dp0square-log.txt"
set "OUT=%~dp0square-output.txt"
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

>"%LOG%" echo SquareImages.bat
>>"%LOG%" echo Started: %DATE% %TIME%
>>"%LOG%" echo Running from: %HERE%
>>"%LOG%" echo Command line arguments: [%*]
>>"%LOG%" echo First argument: [%~1]

echo.
echo ============================================================
echo   Square card photos for CanadianShopper
echo ============================================================
echo.

REM --------------------------------------------------------------------------
REM  1. What should we process?
REM --------------------------------------------------------------------------
set "TARGETS=%*"
if not "%~1"=="" goto have_targets

dir /b "%HERE%\to-square\*" >nul 2>&1
if not errorlevel 1 (
  echo   Using every image in the "to-square" folder.
  set "TARGETS=%HERE%\to-square"
  goto have_targets
)

echo   Nothing to square up yet. Any of these works:
echo.
echo     A^) Put your photo^(s^) in a folder called "to-square" next to this
echo        file, then double-click this file again.
echo     B^) Drag the photo file^(s^) - or a folder - onto this file.
echo     C^) From a Command Prompt:
echo          SquareImages.bat "C:\path\to\photo.jpg"
echo.
echo   No files were dropped this time, so there was nothing to do.
>>"%LOG%" echo No arguments and no to-square folder - nothing to do.
echo.
pause
exit /b 2

:have_targets
>>"%LOG%" echo Targets: [%TARGETS%]

REM --------------------------------------------------------------------------
REM  2. Find Python
REM --------------------------------------------------------------------------
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto have_python

echo   ERROR: Python 3 was not found.
echo     Install it from https://www.python.org/downloads/ and tick
echo     "Add python.exe to PATH" during setup, then run this again.
>>"%LOG%" echo FAIL: no python found on PATH
echo.
pause
exit /b 1

:have_python
echo   Python: %PY%
>>"%LOG%" echo Python: %PY%
%PY% -c "import sys;print(sys.version)" >>"%LOG%" 2>&1
REM ---- reminder: cards that sold and are still advertised elsewhere ------
if not exist "%HERE%\canadianshopper\tools\sold-everywhere.py" goto no_sync_note
%PY% -u "%HERE%\canadianshopper\tools\sold-everywhere.py" --banner --checklist "%HERE%\canadianshopper\tools\sold-cards-checklist.csv" 2>nul
:no_sync_note

REM --------------------------------------------------------------------------
REM  3. Pillow (installed once)
REM --------------------------------------------------------------------------
%PY% -c "import PIL" >nul 2>&1
if not errorlevel 1 goto have_pillow

echo   Installing Pillow ^(one time only^)...
>>"%LOG%" echo Installing Pillow...
%PY% -m pip install --quiet Pillow >>"%LOG%" 2>&1
%PY% -c "import PIL" >nul 2>&1
if not errorlevel 1 goto have_pillow

echo   ERROR: Could not install Pillow. Try this by hand to see the reason:
echo       %PY% -m pip install Pillow
>>"%LOG%" echo FAIL: Pillow install failed
echo.
pause
exit /b 1

:have_pillow

REM --------------------------------------------------------------------------
REM  4. Find the tool
REM --------------------------------------------------------------------------
set "TOOL=%HERE%\make-square.py"
if exist "%TOOL%" goto have_tool
set "TOOL=%HERE%\canadianshopper\tools\make-square.py"
if exist "%TOOL%" goto have_tool

echo   ERROR: make-square.py was not found. It must sit next to this file, or in
echo     a "canadianshopper\tools" subfolder beside it. Looked in:
echo       %HERE%\make-square.py
echo       %HERE%\canadianshopper\tools\make-square.py
>>"%LOG%" echo FAIL: make-square.py not found
echo.
pause
exit /b 1

:have_tool
echo   Tool  : %TOOL%
>>"%LOG%" echo Tool: %TOOL%

REM --------------------------------------------------------------------------
REM  5. Run it (output goes to the screen AND to square-output.txt)
REM --------------------------------------------------------------------------
echo   Command: %PY% -u "%TOOL%" %TARGETS% --open
>>"%LOG%" echo Running: %PY% -u "%TOOL%" %TARGETS% --open
echo.

%PY% -u "%TOOL%" %TARGETS% --open > "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"

type "%OUT%"
>>"%LOG%" echo ---- tool output ----
type "%OUT%" >>"%LOG%"
>>"%LOG%" echo ---- exit code: %RC% ----

echo.
if not "%RC%"=="0" goto failed

echo   Done. The square files are in the "square" subfolder beside your photos.
echo   Upload those ^(not the originals^) in the CanadianShopper dashboard:
echo     front file -^> main product image
echo     back file  -^> add as a second image
>>"%LOG%" echo RESULT: success
echo.
pause
exit /b 0

:failed
echo   The tool finished with errors ^(code %RC%^). The lines above name each
echo   file it could not read. Full details: square-log.txt
>>"%LOG%" echo RESULT: errors
echo.
pause
exit /b %RC%
