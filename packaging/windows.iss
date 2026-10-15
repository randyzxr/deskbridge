#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef ProjectRoot
  #error ProjectRoot is required
#endif

[Setup]
AppId={{353672EC-5376-4B55-9B05-D7C52A06B6F2}
AppName=DeskBridge
AppVersion={#AppVersion}
AppPublisher=DeskBridge
DefaultDirName={localappdata}\Programs\DeskBridge
DefaultGroupName=DeskBridge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=DeskBridge-{#AppVersion}-windows-x64-setup
SetupIconFile={#ProjectRoot}\assets\deskbridge.ico
UninstallDisplayIcon={app}\DeskBridge.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
LicenseFile={#ProjectRoot}\LICENSE
CloseApplications=no
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#ProjectRoot}\dist\{#AppVersion}\DeskBridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\DeskBridge"; Filename: "{app}\DeskBridge.exe"
Name: "{group}\Quick start"; Filename: "{app}\docs\quick-start.md"
Name: "{autodesktop}\DeskBridge"; Filename: "{app}\DeskBridge.exe"; Tasks: desktopicon

; No automatic sharing, service installation, firewall or startup changes.
; Profiles belong to the user and are deliberately absent from uninstall rules.

[Code]
function InitializeSetup(): Boolean;
var
  Value: Cardinal;
begin
  Result := not RegQueryDWordValue(HKLM, 'SYSTEM\CurrentControlSet\Services\DeskBridgeLockReceiver', 'Start', Value);
  if not Result then
    MsgBox('Uninstall the experimental DeskBridge lock receiver service before updating DeskBridge. See docs/lock-screen.md.', mbError, MB_OK);
end;
