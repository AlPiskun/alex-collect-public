@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYVER=3.14.8"
set "PYEXE=python-%PYVER%-amd64.exe"
set "PYSHA=759be887b96e736a3ca886daf8d575f18fcae1a09efab6902f42d59e8999f8ef"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/%PYEXE%"

if not exist "%PYEXE%" goto download
goto verify

:download
echo Downloading the official Python %PYVER% 64-bit installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%PYURL%' -OutFile '%CD%\%PYEXE%'"
if errorlevel 1 goto failed
if not exist "%PYEXE%" goto failed

:verify
echo Verifying SHA-256 against python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$h=(Get-FileHash -Algorithm SHA256 '%CD%\%PYEXE%').Hash.ToLowerInvariant(); if ($h -ne '%PYSHA%') { Write-Error ('SHA-256 mismatch: ' + $h); exit 1 }; Write-Host 'SHA-256 verified.'"
if errorlevel 1 goto badhash

echo.
echo READY. Open alexcollect-bundled.iss in Inno Setup Compiler and press Compile.
echo Output: Output\AlexCollect-Setup-bundled-2.21.exe
echo The final installer needs internet on the target PC to fetch pip packages.
echo.
pause
exit /b 0

:badhash
echo.
echo SHA-256 did not match the official value. Do not compile or use this file.
echo Delete "%PYEXE%" and run this script again.
pause
exit /b 1

:failed
echo.
echo Download failed. Check the connection and run this script again.
echo Official release page: https://www.python.org/downloads/release/python-3148/
pause
exit /b 1
