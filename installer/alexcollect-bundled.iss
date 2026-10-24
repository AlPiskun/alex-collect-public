; Alex Collect Control Panel - Inno Setup installer with a private Python runtime.
; Run build-bundled.bat first to download and verify the official Python
; installer into this folder. That 30+ MB installer is intentionally not
; checked into Git. Package installation needs internet on the target PC.

#define MyAppName "Alex Collect Control Panel"
#define MyAppVersion "2.31"
#define MyAppPublisher "Alex Collect"
#define MyAppExe "START Alex Collect.bat"
#define PythonInstaller "python-3.13.16-amd64.exe"

[Setup]
AppId={{F81B763F-808E-41D3-94F6-C405593B33DF}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\AlexCollect
DefaultGroupName=Alex Collect
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\app\alexcollect.ico
OutputDir=Output
OutputBaseFilename=AlexCollect-Setup-bundled-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=..\app\alexcollect.ico
ArchitecturesAllowed=x64

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "{#PythonInstaller}"; DestDir: "{tmp}"; Flags: ignoreversion
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc,test-*.py,cookie.txt,woo-keys.txt,gui-settings.json,gui-log.txt,sold-cards-checklist.csv,sold-cards-ledger.json,facebook_history.xlsx,addons\canadianshopper\*"
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\MANIFEST.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\START Alex Collect.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Alex Collect"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\app\alexcollect.ico"
Name: "{group}\Uninstall Alex Collect"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Alex Collect"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\app\alexcollect.ico"; Tasks: desktopicon

[Run]
Filename: "{tmp}\{#PythonInstaller}"; Parameters: "/quiet InstallAllUsers=0 TargetDir=""{app}\runtime\python-embed"" Include_launcher=0 Include_tcltk=1 Include_pip=1 Include_test=0 PrependPath=0"; StatusMsg: "Installing Alex Collect's private Python runtime..."; Flags: waituntilterminated
Filename: "{app}\runtime\python-embed\python.exe"; Parameters: "-m pip install --disable-pip-version-check -r ""{app}\requirements.txt"""; StatusMsg: "Installing Alex Collect Python packages..."; Flags: waituntilterminated
Filename: "{app}\{#MyAppExe}"; Description: "Launch Alex Collect"; Flags: postinstall skipifsilent nowait

[UninstallDelete]
; Remove only the private runtime installed by this package. Keep app-created
; settings, reports, checklists, cookies, ledgers, and per-user plugins.
Type: filesandordirs; Name: "{app}\runtime\python-embed"
