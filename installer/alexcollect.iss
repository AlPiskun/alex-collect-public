; Alex Collect Control Panel - Windows Inno Setup installer
; Python-prerequisite variant. Requires Python 3 with Tcl/Tk and internet
; for pip packages. For a setup that installs its own Python, build
; alexcollect-bundled.iss instead.

#define MyAppName "Alex Collect Control Panel"
#define MyAppVersion "2.70"
#define MyAppPublisher "Alex Collect"
#define MyAppExe "START Alex Collect.bat"

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
OutputBaseFilename=AlexCollect-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=..\app\alexcollect.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce
Name: "installdeps"; Description: "Install or update the Python packages (requires internet)"; GroupDescription: "Python packages:"; Flags: checkedonce

[Files]
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

[Code]
function CommandSucceeds(const Params: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), Params, '', SW_HIDE,
                 ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function HasPyLauncher(): Boolean;
begin
  Result := CommandSucceeds('/C py -3 -c "import sys, tkinter; assert sys.version_info[0] == 3"');
end;

function HasPythonCommand(): Boolean;
begin
  Result := CommandSucceeds('/C python -c "import sys, tkinter; assert sys.version_info[0] == 3"');
end;

function UsePythonCommand(): Boolean;
begin
  Result := (not HasPyLauncher()) and HasPythonCommand();
end;

function InitializeSetup(): Boolean;
var
  NL: String;
begin
  NL := Chr(13) + Chr(10);
  if not (HasPyLauncher() or HasPythonCommand()) then
  begin
    MsgBox('Python 3 with Tcl/Tk was not detected.' + NL + NL +
      'Install Python 3 from python.org, including Tcl/Tk, then run this setup again.' + NL +
      'Or build/use AlexCollect-Setup-bundled, which installs its own Python.',
      mbError, MB_OK);
    Result := False;
    Exit;
  end;
  Result := True;
end;

[Run]
Filename: "{cmd}"; Parameters: "/C py -3 -m pip install --user --disable-pip-version-check -r ""{app}\requirements.txt"""; Description: "Install Alex Collect Python packages"; StatusMsg: "Installing Python packages..."; Flags: waituntilterminated; Tasks: installdeps; Check: HasPyLauncher
Filename: "{cmd}"; Parameters: "/C python -m pip install --user --disable-pip-version-check -r ""{app}\requirements.txt"""; Description: "Install Alex Collect Python packages"; StatusMsg: "Installing Python packages..."; Flags: waituntilterminated; Tasks: installdeps; Check: UsePythonCommand
Filename: "{app}\{#MyAppExe}"; Description: "Launch Alex Collect"; Flags: postinstall skipifsilent nowait

[UninstallDelete]
; Deliberately do not remove app-created files such as settings, reports,
; checklists, cookies, ledgers, or the per-user plugins folder on uninstall.
