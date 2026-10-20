@echo off
REM ===========================================================================
REM  SoldEverywhere.bat - one card sold: clear it from every site
REM ===========================================================================
REM  DOUBLE-CLICK THIS FILE and pick a number.
REM
REM  A card is advertised in up to four places: your website, CanadianShopper,
REM  eBay and Facebook Marketplace. Whichever one sells, the other three keep
REM  offering the card until someone changes them - and that is a double sale
REM  waiting to happen.
REM
REM    * CanadianShopper can be changed FOR you (the tool does it).
REM    * eBay and Facebook have no bulk tools for a personal account, so this
REM      tool keeps a tick-off checklist and keeps reminding you, with a link
REM      straight to the listing pages.
REM
REM  It never touches eBay or Facebook by itself. The only thing it can change
REM  on a website is the CanadianShopper stock number, and only if you answer
REM  yes when it asks.
REM
REM  Every run is logged to sold-everywhere-log.txt beside this file.
REM ===========================================================================
setlocal
title SoldEverywhere - a sold card, off every site
cd /d "%~dp0"

set "LOG=%~dp0sold-everywhere-log.txt"
set "OUT=%~dp0sold-everywhere-output.txt"
set "TOOLS=canadianshopper\tools"
set "EVERY=%TOOLS%\sold-everywhere.py"
set "SOLD=%TOOLS%\sold-cards.py"
set "CHECK=%TOOLS%\sold-cards-checklist.csv"
set "LISTTXT=%TOOLS%\sold-cards.txt"
set "PHOTOS=%TOOLS%\needs-photos.txt"
set "KEYS=%TOOLS%\woo-keys.txt"
set "COOKIE=%TOOLS%\cookie.txt"
set "SCANDIR=C:\Users\Owner\Pictures\ControlCenter4\Scan"

>"%LOG%" echo SoldEverywhere.bat
>>"%LOG%" echo Started: %DATE% %TIME%
>>"%LOG%" echo Arguments: [%*]

REM ---- python first, so the pending note can be shown before the menu --------
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto have_python
echo   ERROR: Python 3 was not found. Install it from
echo       https://www.python.org/downloads/
>>"%LOG%" echo FAIL: python not found
echo.
pause
exit /b 1

:have_python
if not exist "%EVERY%" goto no_tool
%PY% -u "%EVERY%" --banner --checklist "%CHECK%" 2>nul

if "%~1"=="" goto menu
goto direct

REM ==========================================================================
REM  MENU
REM ==========================================================================
:menu
echo.
echo ============================================================
echo   A card sold - clear it from everywhere
echo ============================================================
echo.
echo   1  It sold on MY WEBSITE      ^(type it / orders CSV / API key^)
echo   2  It sold SOMEWHERE ELSE     ^(Facebook, eBay, in person^)
echo   3  What is still outstanding  ^(the checklist^)
echo   4  I did some of them - tick them off
echo   5  A card needs new photos    ^(scan reminder^)
echo   6  CanadianShopper: archive every listing already at 0
echo.
set "CHOICE="
set /p "CHOICE=  Type 1-6 and press Enter: "
if "%CHOICE%"=="1" goto mode_site
if "%CHOICE%"=="2" goto mode_else
if "%CHOICE%"=="3" goto mode_status
if "%CHOICE%"=="4" goto mode_done
if "%CHOICE%"=="5" goto mode_photos
if "%CHOICE%"=="6" goto mode_zero
echo   Not one of the numbers - nothing done.
echo.
pause
exit /b 1

REM ==========================================================================
REM  1 - sold on your website
REM ==========================================================================
:mode_site
echo.
echo   How do you want to give it the sale?
echo.
echo     a  I will type the cards in         ^(opens Notepad^)
echo     b  Orders CSV exported from my site
echo     c  My website's API key              ^(woo-keys.txt - automatic^)
echo.
set "SUB="
set /p "SUB=  Type a, b or c: "
if /i "%SUB%"=="a" goto site_list
if /i "%SUB%"=="b" goto site_csv
if /i "%SUB%"=="c" goto site_api
echo   Not one of the letters - nothing done.
echo.
pause
exit /b 1

:site_list
call :make_list_file
echo.
echo   Opening the list file - type ONE CARD PER LINE, then add ", 2" if two
echo   copies sold. Add ", last" when you know none are left anywhere.
echo   Save it and close Notepad; the checklist is built next.
echo.
start /wait notepad "%LISTTXT%"
set "ARGS=--list "%LISTTXT%""
set "LABEL=cards you typed"
goto ask_cs

:site_csv
echo.
echo   On your website: WooCommerce ^> Orders ^> Export ^(top of the list^),
echo   choose the orders, CSV, download. Then drag the file into this window.
echo.
set "CSVPATH="
set /p "CSVPATH=  Drag the CSV here and press Enter: "
if "%CSVPATH%"=="" goto nothing_given
set "CSVPATH=%CSVPATH:"=%"
if not exist "%CSVPATH%" goto csv_missing
set "ARGS=--woo-orders-csv "%CSVPATH%""
set "LABEL=orders CSV %~nx1"
goto ask_cs

:site_api
call :need_keys
if errorlevel 1 goto stopped_by_user
set "ARGS=--woo-keys "%KEYS%""
set "LABEL=your website's orders (API key)"
goto ask_cs

REM ==========================================================================
REM  2 - sold somewhere else
REM ==========================================================================
:mode_else
echo.
echo   Where did it sell?
echo.
echo     a  Facebook Marketplace
echo     b  eBay
echo     c  In person / somewhere else
echo.
set "SUB="
set /p "SUB=  Type a, b or c: "
if /i "%SUB%"=="a" set "SOLDON=facebook"
if /i "%SUB%"=="b" set "SOLDON=ebay"
if /i "%SUB%"=="c" set "SOLDON=inperson"
if not defined SOLDON goto else_bad
call :make_list_file
echo.
echo   Opening the list file - one card per line ^(that is what changed hands^).
echo   Save and close Notepad; the checklist is built next.
echo.
start /wait notepad "%LISTTXT%"
set "ARGS=--list "%LISTTXT%" --sold-on %SOLDON%"
set "LABEL=sold on %SOLDON%"
goto ask_cs

:else_bad
echo   Not one of the letters - nothing done.
echo.
pause
exit /b 1

REM ==========================================================================
REM  ask about the CanadianShopper leg, then run
REM ==========================================================================
:ask_cs
echo.
echo   Note: building the checklist writes nothing to any website. The only
echo   website this can change is CanadianShopper - its stock numbers - and
echo   only if you say yes now.
echo.
set "DOCS="
set /p "DOCS=  Update CanadianShopper too? (y/N): "
if /i "%DOCS%"=="y" goto ask_cs_yes
set "ARGS=%ARGS%"
goto run_common

:ask_cs_yes
call :need_cookie
if errorlevel 1 goto stopped_by_user
set "ARGS=%ARGS% --cs"
goto run_common

:run_common
echo.
echo ------------------------------------------------------------
echo   source: %LABEL%
echo ------------------------------------------------------------
%PY% -u "%EVERY%" %ARGS% --checklist "%CHECK%" --cookie-file "%COOKIE%" --scan-dir "%SCANDIR%" > "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%"
>>"%LOG%" echo ---- run (%LABEL%) exit %RC% ----
type "%OUT%" >>"%LOG%"
if not "%RC%"=="0" goto failed
echo.
pause
exit /b 0

REM ==========================================================================
REM  3 - what is still outstanding
REM ==========================================================================
:mode_status
%PY% -u "%EVERY%" --status --checklist "%CHECK%" > "%OUT%" 2>&1
type "%OUT%"
>>"%LOG%" echo ---- status ----
type "%OUT%" >>"%LOG%"
if not exist "%CHECK%" goto nothing_yet
echo.
echo   Opening the checklist in Notepad. Put an x in the "done" column next to
echo   anything you have finished, SAVE, then close it. Rows without an x keep
echo   being reported every time you run any of the tools.
echo.
start /wait notepad "%CHECK%"
%PY% -u "%EVERY%" --status --checklist "%CHECK%"
echo.
pause
exit /b 0

:nothing_yet
echo   No checklist yet - that is what a sale creates ^(menu 1 or 2^).
echo.
pause
exit /b 0

REM ==========================================================================
REM  4 - tick off what you finished
REM ==========================================================================
:mode_done
if not exist "%CHECK%" goto nothing_yet
%PY% -u "%EVERY%" --status --checklist "%CHECK%"
echo.
set "NUMS="
set /p "NUMS=  Which numbers did you finish? (e.g. 2,5 - or type  all ): "
if "%NUMS%"=="" goto nothing_given
%PY% -u "%EVERY%" --done "%NUMS%" --checklist "%CHECK%" > "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%"
>>"%LOG%" echo ---- done %NUMS% exit %RC% ----
type "%OUT%" >>"%LOG%"
echo.
pause
exit /b %RC%

REM ==========================================================================
REM  5 - a card needs new photos
REM ==========================================================================
:mode_photos
if exist "%PHOTOS%" goto photos_edit
>"%PHOTOS%" echo # Cards that need new photos. One per line, spelled as on the sites.
>>"%PHOTOS%" echo # Save, close Notepad, and the reminder rows are made for you.
>>"%PHOTOS%" echo.
:photos_edit
echo.
echo   Opening the photo list. Type the card^(s^) that need new scans, save and
echo   close Notepad.
echo.
start /wait notepad "%PHOTOS%"
%PY% -u "%EVERY%" --images-file "%PHOTOS%" --scan-dir "%SCANDIR%" --checklist "%CHECK%" > "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%"
>>"%LOG%" echo ---- photos run exit %RC% ----
type "%OUT%" >>"%LOG%"
echo   Scan the new photos with your normal scanner software - the files land in
echo   the folder being opened now. Then run the usual pipeline ^(rerun.bat^) and
echo   re-upload to the sites.
echo.
if not exist "%SCANDIR%" goto no_scandir
start "" explorer "%SCANDIR%"
echo.
pause
exit /b 0

:no_scandir
echo   NOTE: that folder was not found:  %SCANDIR%
echo   Edit the SCANDIR line at the top of this file if your scans go somewhere
echo   else.
echo.
pause
exit /b 0

REM ==========================================================================
REM  6 - archive everything at 0 on CanadianShopper
REM ==========================================================================
:mode_zero
call :need_cookie
if errorlevel 1 goto stopped_by_user
echo.
echo ------------------------------------------------------------
echo   PREVIEW - nothing is written yet
echo ------------------------------------------------------------
%PY% -u "%SOLD%" --zero-stock --cookie-file "%COOKIE%" > "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%"
>>"%LOG%" echo ---- zero-stock preview exit %RC% ----
type "%OUT%" >>"%LOG%"
if not "%RC%"=="0" goto failed
echo.
echo   Nothing has been changed yet.
set "GO="
set /p "GO=  Apply this on CanadianShopper? Type y then Enter: "
if /i not "%GO%"=="y" goto zero_skipped
%PY% -u "%SOLD%" --zero-stock --apply --cookie-file "%COOKIE%" > "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%"
>>"%LOG%" echo ---- zero-stock apply exit %RC% ----
type "%OUT%" >>"%LOG%"
if not "%RC%"=="0" goto failed
echo.
pause
exit /b 0

:zero_skipped
echo   Left everything as it was.
echo.
pause
exit /b 0

REM ==========================================================================
REM  shared helpers
REM ==========================================================================
:direct
%PY% -u "%EVERY%" %* --checklist "%CHECK%" --cookie-file "%COOKIE%" --scan-dir "%SCANDIR%" > "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"
type "%OUT%"
>>"%LOG%" echo ---- direct exit %RC% ----
type "%OUT%" >>"%LOG%"
echo.
pause
exit /b %RC%

:make_list_file
if exist "%LISTTXT%" goto make_list_done
if exist "%TOOLS%" goto make_list_tools
mkdir "%TOOLS%"
:make_list_tools
>"%LISTTXT%" echo # One card per line - exactly as the title reads on the sites.
>>"%LISTTXT%" echo # Put ", 2" after the title if two copies sold.
>>"%LISTTXT%" echo # Put ", last" when you know no copies are left anywhere.
>>"%LISTTXT%" echo.
:make_list_done
exit /b 0

:need_keys
if exist "%KEYS%" goto need_keys_check
echo.
echo   One-time setup for the automatic mode. On your website:
echo       WooCommerce ^> Settings ^> Advanced ^> REST API ^> Add key
echo       Permissions: Read   ^(Read is enough - this never writes to your site^)
echo   Copy the ck_... and cs_... values ^(the secret shows once^) into the file
echo   being opened now, on their own lines, save it.
echo.
>"%KEYS%" echo https://store.piskun.ca
>>"%KEYS%" echo ck_PASTE_THE_CONSUMER_KEY_HERE
>>"%KEYS%" echo cs_PASTE_THE_CONSUMER_SECRET_HERE
start /wait notepad "%KEYS%"
:need_keys_check
findstr /c:"PASTE_THE" "%KEYS%" >nul 2>&1
if not errorlevel 1 goto keys_placeholder
exit /b 0

:keys_placeholder
echo.
echo   The keys file still has the placeholders in it:
echo       %KEYS%
echo   Put your real ck_... and cs_... values on their lines and run this again.
>>"%LOG%" echo FAIL: keys placeholders untouched
echo.
pause
exit /b 1

:need_cookie
if exist "%COOKIE%" goto need_cookie_done
echo.
echo   The CanadianShopper session cookie is missing. It is needed once, then
echo   reused by all the tools in this folder.
echo.
echo    1. Sign in at https://canadianshopper.ca as the vendor account.
echo    2. Press F12 for DevTools:
echo         Edge / Chrome : Application ^> Storage ^> Cookies ^> canadianshopper.ca
echo    3. Find the row named  __Secure-better-auth.session_token
echo       and copy ONLY its VALUE cell ^(about 93 characters^).
echo    4. Paste it below and press Enter.
echo.
set "CVALUE="
set /p "CVALUE=  Cookie value: "
if "%CVALUE%"=="" goto cookie_missing
if not exist "%TOOLS%" mkdir "%TOOLS%"
> "%COOKIE%" echo(%CVALUE%
echo   Saved to %COOKIE%
>>"%LOG%" echo Cookie saved by prompt
:need_cookie_done
exit /b 0

:cookie_missing
echo   Nothing pasted - stopping. The other menu entries still work.
>>"%LOG%" echo FAIL: no cookie pasted
echo.
pause
exit /b 1

:no_tool
echo   ERROR: %EVERY% was not found.
echo   This file must sit beside card_pipeline.py, with the tools in:
echo       %CD%\%TOOLS%
echo   Copy sold-everywhere.py, sold-cards.py, cs-image-sync.py and
echo   pad-and-upload.py there, then run this again.
>>"%LOG%" echo FAIL: %EVERY% not found
echo.
pause
exit /b 1

:stopped_by_user
exit /b 1

:nothing_given
echo   Nothing given - stopping.
echo.
pause
exit /b 1

:csv_missing
echo   That file was not found: %CSVPATH%
>>"%LOG%" echo FAIL: csv not found: %CSVPATH%
echo.
pause
exit /b 1

:failed
echo.
echo   The tool stopped with exit code %RC%. The lines above name the cause.
echo   The usual one: CanadianShopper did not accept the cookie ^(it lasts about
echo   a week^). Delete  %COOKIE%  and run this again - it will ask for a fresh
echo   one. Nothing is half-done: run the same menu entry again when ready.
>>"%LOG%" echo RESULT: errors
echo.
pause
exit /b %RC%
