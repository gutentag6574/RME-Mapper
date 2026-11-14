; Inno Setup Script for GeoPoint Mapper
; Tested with Inno Setup 6/7

#define MyAppName "GeoPoint Mapper"
#ifndef MyAppVersion
#define MyAppVersion "1.1.0"
#endif
#define MyAppPublisher "Кульдеев Вадим Алексеевич"
#define MyAppURL "https://github.com/gutentag6574/RME-Mapper"
#define MyAppExeName "GeoPointMapper.exe"

[Setup]
; Unique application GUID for GeoPoint Mapper
AppId={{5E9A8874-C35A-4DF8-8DA1-68F485B891A4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user installation does not require administrator privileges
PrivilegesRequired=lowest
OutputDir=..\release\installer
OutputBaseFilename=GeoPointMapper-{#MyAppVersion}-Setup-x64
SetupIconFile=..\src\rme_mapper\resources\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\GeoPointMapper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove the incompatible runtime left by an earlier installation.
Type: files; Name: "{app}\_internal\icuuc.dll"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; File association for *.gpmap and *.rmeproject
Root: HKCU; Subkey: "Software\Classes\.gpmap"; ValueType: string; ValueName: ""; ValueData: "GeoPointMapper.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.rmeproject"; ValueType: string; ValueName: ""; ValueData: "GeoPointMapper.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\GeoPointMapper.Project"; ValueType: string; ValueName: ""; ValueData: "GeoPoint Mapper Project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\GeoPointMapper.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\GeoPointMapper.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
