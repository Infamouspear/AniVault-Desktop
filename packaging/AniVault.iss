#define AppVersion "1.5.0"
[Setup]
AppId={{07D7C4E3-91BF-448A-AB6F-8439F86DA015}
AppName=AniVault
AppVersion={#AppVersion}
VersionInfoVersion=1.5.0.0
VersionInfoProductVersion=1.5.0.0
VersionInfoProductTextVersion={#AppVersion}
AppPublisher=AniVault
AppComments=Your anime, your library.
DefaultDirName={localappdata}\Programs\AniVault
DefaultGroupName=AniVault
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\anivault.ico
UninstallDisplayIcon={app}\AniVault.exe
OutputDir=..\dist\installer
OutputBaseFilename=AniVault-1.5.0-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
UninstallDisplayName=AniVault
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "..\dist\AniVault\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\AniVault"; Filename: "{app}\AniVault.exe"; AppUserModelID: "AniVault.Desktop.0.7"
Name: "{userdesktop}\AniVault"; Filename: "{app}\AniVault.exe"; Tasks: desktopicon; AppUserModelID: "AniVault.Desktop.0.7"
[Run]
Filename: "{app}\AniVault.exe"; Description: "Launch AniVault"; Flags: nowait postinstall skipifsilent
; Intentionally no UninstallDelete entries for %LOCALAPPDATA%\AnimeHub.
; User state is retained on uninstall and upgrade, never bundled here.
