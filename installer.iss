; Inno Setup script for TX Controller.
;
; Inno Setup only runs on Windows (no Linux/Mac port) - install it from
; https://jrsoftware.org/isinfo.php, then either open this file in the
; Inno Setup Compiler GUI and click Compile, or from a command prompt:
;
;     iscc installer.iss
;
; Run build_exe.py FIRST - this script packages whatever's already in
; dist\TX Controller.exe, it doesn't build it. Output lands in
; installer_output\TX Controller Setup.exe - a real install wizard
; (destination folder, Start Menu group, optional desktop shortcut)
; with an uninstaller registered in Windows' "Add or Remove Programs".
;
; AppId below is a fixed, real GUID (generated once for this project) -
; it must NEVER change between releases, since Inno Setup uses it to
; recognize "this is an upgrade of the same app" vs. a fresh install
; that would leave the old version's registry entry orphaned.

#define MyAppName "TX Controller"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "TX Controller"
#define MyAppExeName "TX Controller.exe"

[Setup]
AppId={{FB6F3104-0D34-44B0-8E3F-9E985CC19246}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=TX Controller Setup
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
; Only the one file - build_exe.py already produces a single-file
; onefile .exe with everything (icon, assets/) bundled inside it, so
; there's nothing else to copy alongside it here.
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
