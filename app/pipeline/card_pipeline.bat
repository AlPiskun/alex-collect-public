@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Alex Collect — Card Pipeline

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║           Alex Collect  —  Card Listing Pipeline            ║
echo ╠══════════════════════════════════════════════════════════════╣
echo ║                                                              ║
echo ║  1. Copy your AI listing text to the clipboard               ║
echo ║  2. Drag-and-drop FRONT and BACK scans onto this .bat        ║
echo ║  3. Review proposed renames — approve or reject              ║
echo ║  4. WooCommerce CSV generated                                ║
echo ║  5. Upload to WooCommerce when prompted                      ║
echo ║  6. Facebook feed refreshed + Marketplace XLSX built         ║
echo ║                                                              ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

set "SCRIPT_DIR=%~dp0"
set "PIPELINE=%SCRIPT_DIR%card_pipeline.py"
set "INPUT_FILE=%SCRIPT_DIR%_card_input.txt"

rem ════════════════════════════════════════════════════════════════
rem  Require drag-and-drop of at least the FRONT scan
rem ════════════════════════════════════════════════════════════════
if "%~1"=="" (
    echo ❌ No images provided.
    echo    Drag-and-drop your FRONT and BACK scan images onto this .bat file.
    echo.
    pause
    exit /b 1
)

echo Received scan files:
echo   FRONT: %~nx1
if not "%~2"=="" echo   BACK:  %~nx2
echo.

rem ════════════════════════════════════════════════════════════════
rem  PHASE 1: Split the scans
rem ════════════════════════════════════════════════════════════════
echo ══════════════════════════════════════════════════════════════
echo  PHASE 1 — Splitting scans into individual card images
echo ══════════════════════════════════════════════════════════════
echo.

if not "%~2"=="" (
    python "%PIPELINE%" split --front "%~1" --back "%~2"
) else (
    python "%PIPELINE%" split --front "%~1"
)

if errorlevel 1 (
    echo.
    echo ❌ Split failed. See error above.
    pause
    exit /b 1
)

echo.

rem ════════════════════════════════════════════════════════════════
rem  PHASE 2: Check clipboard for AI listing text
rem ════════════════════════════════════════════════════════════════
echo ══════════════════════════════════════════════════════════════
echo  PHASE 2 — Reading AI listing text from clipboard
echo ══════════════════════════════════════════════════════════════
echo.

:CLIPBOARD_CHECK
echo Checking clipboard...
powershell -NoProfile -Command "Get-Clipboard | Out-File -FilePath '%INPUT_FILE%' -Encoding utf8"

rem ── Check that the file exists and has meaningful content ──
set "CLIPBOARD_OK=0"
if exist "%INPUT_FILE%" (
    for %%A in ("%INPUT_FILE%") do (
        if %%~zA GEQ 200 set "CLIPBOARD_OK=1"
    )
)

if "!CLIPBOARD_OK!"=="0" (
    echo.
    echo ╔══════════════════════════════════════════════════════════════╗
    echo ║  ⚠  No listing text found on the clipboard.                ║
    echo ║                                                              ║
    echo ║  Copy the full AI listing output to your clipboard now,     ║
    echo ║  then press Enter to continue.                              ║
    echo ║                                                              ║
    echo ║  Type Q and press Enter to quit without generating CSV.     ║
    echo ╚══════════════════════════════════════════════════════════════╝
    echo.
    set "RETRY="
    set /p "RETRY=Ready? (Enter = retry / Q = quit): "
    if /i "!RETRY!"=="Q" (
        echo.
        echo ✅ Scans were split successfully. Images are in the output folder.
        echo    Re-run this .bat later to finish with the listing text.
        pause
        exit /b 0
    )
    goto CLIPBOARD_CHECK
)

echo ✔ Clipboard text captured (%INPUT_FILE%)
echo.

rem ════════════════════════════════════════════════════════════════
rem  PHASE 3: Parse, rename, generate CSV, upload, Facebook feed
rem ════════════════════════════════════════════════════════════════
echo ══════════════════════════════════════════════════════════════
echo  PHASE 3 — Parse listings, rename images, generate CSV
echo ══════════════════════════════════════════════════════════════
echo.

python "%PIPELINE%" listing --input "%INPUT_FILE%" --facebook

if errorlevel 1 (
    echo.
    echo ❌ Something went wrong. See error above.
    pause
    exit /b 1
)

echo.
echo ✅ Pipeline complete.
pause