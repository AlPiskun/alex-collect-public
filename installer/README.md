# Windows setup packages (Inno Setup 6)

This directory contains two Windows installers for the **public core only**.
Neither installer includes the private CanadianShopper plugin or any live
credentials, cookie, or user-generated runtime data. The plugin remains a
separate ZIP installed from the app's Plugins menu item.

Install Inno Setup 6 from [jrsoftware.org/isdl.php](https://jrsoftware.org/isdl.php).
Open the selected `.iss` file in Inno Setup Compiler and press **Compile**.
The executable is written under `installer\Output\`; do not commit that
output directory or send a public installer to the private-plugin audience.

## A. `alexcollect.iss` — Python is already installed

This is the smaller setup. It requires a working Python 3 installation with
Tcl/Tk. Setup checks for `py -3` or `python`; if neither can import tkinter,
it stops and explains that Python is required. The wizard offers a checked
by-default task to install the packages in the repository's
`requirements.txt` using pip (internet required). Uncheck it only if those
packages are already installed.

Compile it on a Windows machine with Inno Setup 6. Output:
`Output\AlexCollect-Setup-2.86.exe`.

## B. `alexcollect-bundled.iss` — install a private Python runtime

This is the easier-to-share option for a Windows PC without Python. The
installer includes Python 3.13.16 x64 at
`%LOCALAPPDATA%\\AlexCollect\\runtime\\python-embed`, beside the app folder.
The launcher prefers this private runtime, so it does not alter the system PATH
or another Python installation. It also
installs this project's dependencies from `requirements.txt` during setup.
Internet is required on the target PC for pip to download those packages.

1. Run `build-bundled.bat`. It downloads the official Python 3.13.16 Windows
   installer from python.org and verifies its SHA-256 before continuing.
2. Run `python test-bundled-config.py` to check the version/filename/checksum pins.
3. Open `alexcollect-bundled.iss` and compile it with Inno Setup 6.
4. Output: `Output\AlexCollect-Setup-bundled-2.79.exe`.

The downloaded Python installer is intentionally not stored in Git. It is
ignored by `.gitignore`; rerun `build-bundled.bat` when needed. The pinned
release and checksum are documented at
[python.org](https://www.python.org/downloads/release/python-31316/).

## Upgrade and uninstall behavior

Both scripts use the existing Alex Collect AppId and install to
`%LOCALAPPDATA%\AlexCollect`, so Inno Setup can upgrade an existing install
in place. The uninstaller removes installed program files; it deliberately
leaves app-created state (settings, checklists, reports, cookies, ledgers,
customer quotes, and the per-user `plugins` directory) in place. The bundled
variant removes only its own `runtime\python-embed` directory.

The installer source list explicitly excludes runtime credentials/state,
Python caches, generated history, tests, the `app\quotes` folder (customer
names, addresses and prices), and any legacy `app\addons\canadianshopper`
tree. To verify the package boundary, run the core test suites from the
repository and inspect the compiled package before publishing a release.

## Build note

This workspace does not include the Windows Inno Setup compiler, so the
`.iss` files are source templates and the final `.exe` must be compiled on
Windows with Inno Setup 6. Compile and smoke-test the installer on a clean
Windows user account before release.
