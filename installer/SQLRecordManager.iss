#define MyAppName "SQL Record Manager"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "N4ko01"
#define MyAppExeName "SQLRecordManager.exe"

[Setup]
AppId={{B3A86552-2B7B-4DA0-8AA4-DB5D7F0A0A01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\SQL Record Manager
DefaultGroupName={#MyAppName}
OutputDir=..\dist\installer
OutputBaseFilename=SQLRecordManager-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\RP-DB\assets\app_window_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\SQLRecordManager.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
