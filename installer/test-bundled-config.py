#!/usr/bin/env python3
"""Static consistency check for the bundled-Python Inno Setup installer."""
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ISS = (HERE / "alexcollect-bundled.iss").read_text(encoding="utf-8")
BATCH = (HERE / "build-bundled.bat").read_text(encoding="utf-8-sig")
README = (HERE / "README.md").read_text(encoding="utf-8")
LAUNCHER = (HERE.parent / "app" / "Alex Collect.bat").read_text(
    encoding="utf-8-sig")
CORE = (HERE.parent / "app" / "gui.py").read_text(encoding="utf-8")
PYTHON_SETUP = (HERE / "alexcollect.iss").read_text(encoding="utf-8")

APP_VERSION = "3.13"
VERSION = "3.13.16"
INSTALLER = "python-3.13.16-amd64.exe"
SHA256 = "fb4f9f5d438b2396da0086dc70b935c530cb578e37adc6d354f7ad2037fee83b"

assert 'VERSION = "%s"' % APP_VERSION in CORE
assert '#define MyAppVersion "%s"' % APP_VERSION in ISS
assert '#define MyAppVersion "%s"' % APP_VERSION in PYTHON_SETUP
for setup in (ISS, PYTHON_SETUP):
    assert 'Name: "desktopicon";' in setup and 'Flags: checkedonce' in setup
    assert 'Name: "{userdesktop}\\Alex Collect";' in setup
    assert 'Tasks: desktopicon' in setup
assert 'AlexCollect-Setup-bundled-%s.exe' % APP_VERSION in BATCH
assert '#define PythonInstaller "%s"' % INSTALLER in ISS
assert 'Source: "{#PythonInstaller}"; DestDir: "{tmp}"' in ISS
assert 'Filename: "{tmp}\\{#PythonInstaller}"' in ISS
assert 'TargetDir=""{app}\\runtime\\python-embed""' in ISS
assert 'if exist "%~dp0..\\runtime\\python-embed\\pythonw.exe" goto bundled_parent_start' in LAUNCHER
assert 'start "Alex Collect" "%~dp0..\\runtime\\python-embed\\pythonw.exe" "%GUI%"' in LAUNCHER
assert 'set "PYVER=%s"' % VERSION in BATCH
assert 'set "PYEXE=python-%PYVER%-amd64.exe"' in BATCH
assert 'set "PYSHA=%s"' % SHA256 in BATCH
assert 'set "PYURL=https://www.python.org/ftp/python/%PYVER%/%PYEXE%"' in BATCH
assert 'https://www.python.org/downloads/release/python-31316/' in BATCH
assert VERSION in README
assert 'https://www.python.org/downloads/release/python-31316/' in README
assert not re.search(r"3\.14\.8|python-3148", ISS + BATCH + README)
print("PASS bundled installer pins Python %s x64" % VERSION)
print("PASS Inno Setup and download script agree on installer filename")
print("PASS build script verifies the official SHA-256")
print("PASS bundled runtime target and release documentation agree")
