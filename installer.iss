; Inno Setup script for Pseudo Random Noise Controller.
;
; Inno Setup only runs on Windows (no Linux/Mac port) - install it from
; https://jrsoftware.org/isinfo.php, then either open this file in the
; Inno Setup Compiler GUI and click Compile, or from a command prompt:
;
;     iscc installer.iss
;
; Run build_exe.py FIRST - this script packages whatever's already in
; dist\Pseudo Random Noise Controller\ (a --onedir folder build, not a
; single .exe - see build_exe.py for why), it doesn't build it. Output
; lands in installer_output\Pseudo Random Noise Controller Setup.exe - a real install wizard
; (destination folder, Start Menu group, optional desktop shortcut)
; with an uninstaller registered in Windows' "Add or Remove Programs".
;
; AppId below is a fixed, real GUID (generated once for this project) -
; it must NEVER change between releases, since Inno Setup uses it to
; recognize "this is an upgrade of the same app" vs. a fresh install
; that would leave the old version's registry entry orphaned.

#define MyAppName "Pseudo Random Noise Controller"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Pseudo Random Noise Controller"
#define MyAppExeName "Pseudo Random Noise Controller.exe"

[Setup]
AppId={{FB6F3104-0D34-44B0-8E3F-9E985CC19246}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=Pseudo Random Noise Controller Setup
SetupIconFile=assets\icons\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Per-user install by default (no admin prompt) - {autopf} adapts
; automatically alongside this (per-user Program Files equivalent
; instead of the real, admin-only one) rather than conflicting with
; it. PrivilegesRequiredOverridesAllowed lets whoever's installing
; opt into an all-users/admin install via a checkbox instead, if they
; want one.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; --onedir build: dist\Pseudo Random Noise Controller\ is a whole folder (the exe plus
; its Python/Qt runtime and assets/), not a single file, so this
; copies everything in it recursively. Transit.dll below is a real,
; separate file though, not something PyInstaller bundles:
; services/middleware.py loads it via ctypes.WinDLL from dll\Transit.dll
; next to the running .exe (sys.executable's own directory once frozen
; - see _DLL_PATH there), so it has to actually exist on disk at that
; path, not be embedded inside the app folder PyInstaller produces.
;
; skipifsourcedoesntexist: dll\Transit.dll is gitignored (proprietary
; vendor DLL - see .gitignore) and never present on a fresh checkout,
; including the CI runner's. Without this flag Inno Setup hard-fails
; the whole compile the moment that file is missing, which is every
; automated build. With it, a local build that has a real copy in
; dll\ still bundles it normally; a CI build produces a working
; installer minus that one DLL, and whoever installs it drops their
; own licensed copy into "<install dir>\dll\Transit.dll" afterward -
; the same "you supply your own copy" model this repo already uses
; for a dev checkout, just applied one step later.
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dll\Transit.dll"; DestDir: "{app}\dll"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
