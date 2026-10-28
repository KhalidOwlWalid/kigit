; Windows installer for kigit (Inno Setup 6). Built by .github/workflows/release.yml:
;   iscc /DAppVersion=0.1.0 /DStageDir=<cmake --install prefix> /DOutputDir=dist kigit.iss
; StageDir holds bin\kigit.exe, bin\uv.exe and share\kigit\gui\ (what `kigit gui` runs).
;
; Installs for the current user only (no admin needed) into
; %LOCALAPPDATA%\Programs\kigit, adds its bin folder to the user's PATH, and
; adds a Start menu entry that opens the GUI. Uninstalling undoes all three.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\..\stage"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
AppId={{D1D029D2-C040-433D-9206-3B3C27407D73}
AppName=kigit
AppVersion={#AppVersion}
AppPublisher=KhalidOwlWalid
AppPublisherURL=https://github.com/KhalidOwlWalid/kigit
AppSupportURL=https://github.com/KhalidOwlWalid/kigit/issues
DefaultDirName={autopf}\kigit
DefaultGroupName=kigit
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ChangesEnvironment=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=kigit-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=kigit {#AppVersion}
UninstallDisplayIcon={app}\bin\kigit.exe

[Tasks]
Name: "addtopath"; Description: "Add kigit to PATH (so you can run kigit from a terminal)"
Name: "desktopicon"; Description: "Create a desktop shortcut for the GUI"; Flags: unchecked

[InstallDelete]
; An upgrade replaces the GUI's files instead of mixing old and new ones.
Type: filesandordirs; Name: "{app}\share\kigit\gui"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\kigit"; Filename: "{app}\bin\kigit.exe"; Parameters: "gui"; WorkingDir: "{userdocs}"; Comment: "KiCad + git diff viewer"
Name: "{autodesktop}\kigit"; Filename: "{app}\bin\kigit.exe"; Parameters: "gui"; WorkingDir: "{userdocs}"; Tasks: desktopicon

[Run]
Filename: "{app}\bin\kigit.exe"; Parameters: "gui"; WorkingDir: "{userdocs}"; Description: "Start kigit now"; Flags: postinstall nowait skipifsilent

[Code]
const
  EnvKey = 'Environment';

function BinDir(): string;
begin
  Result := ExpandConstant('{app}\bin');
end;

// Is `dir` one of the entries of the ;-separated `path`? (case-insensitive)
function PathHas(path, dir: string): Boolean;
begin
  Result := Pos(';' + Uppercase(dir) + ';', ';' + Uppercase(path) + ';') > 0;
end;

procedure AddToPath();
var
  path: string;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', path) then path := '';
  if PathHas(path, BinDir()) then exit;
  if (path <> '') and (path[Length(path)] <> ';') then path := path + ';';
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', path + BinDir());
end;

procedure RemoveFromPath();
var
  path, dir: string;
  p: Integer;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', path) then exit;
  dir := BinDir();
  path := ';' + path + ';';
  p := Pos(';' + Uppercase(dir) + ';', Uppercase(path));
  if p = 0 then exit;
  Delete(path, p, Length(dir) + 1);
  // Drop the separators added above.
  if (Length(path) > 0) and (path[1] = ';') then Delete(path, 1, 1);
  if (Length(path) > 0) and (path[Length(path)] = ';') then Delete(path, Length(path), 1);
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', path);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then AddToPath();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then RemoveFromPath();
end;

// kigit reads boards out of git, so it needs git on PATH. Say so up front.
function InitializeSetup(): Boolean;
var
  code: Integer;
begin
  Result := True;
  if not Exec(ExpandConstant('{cmd}'), '/C git --version', '', SW_HIDE, ewWaitUntilTerminated, code) or (code <> 0) then
    Result := MsgBox('Git was not found on this computer.' + #13#10#13#10 +
                     'kigit compares KiCad files between git commits, so it needs Git for Windows ' +
                     '(https://git-scm.com/download/win). Without it, only "Compare folders" works.' + #13#10#13#10 +
                     'Install kigit anyway?', mbConfirmation, MB_YESNO) = IDYES;
end;
