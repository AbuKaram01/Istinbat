; SPDX-FileCopyrightText: 2026 AbuKaram01
; SPDX-License-Identifier: AGPL-3.0-or-later
;
; Inno Setup script for the Windows installer. Build it with packaging\build-windows.ps1.
;
; Like the Linux packages, the installer ships only Istinbat's own files. After copying them it runs
; scripts\install-windows.ps1, which downloads the GTK runtime and creates the Python environment
; (internet access is needed at install time, not afterwards). Everything is per user: no administrator
; rights are required.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Istinbat"
#define AppId "io.github.AbuKaram01.Istinbat"

[Setup]
AppId={{7B6C2D0E-5E0B-4C57-9B64-1F5A3D2A9C41}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AbuKaram01
AppPublisherURL=https://github.com/AbuKaram01/istinbat
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
SetupIconFile=..\..\data\windows\istinbat.ico
UninstallDisplayIcon={app}\data\windows\istinbat.ico
OutputDir=..\dist
OutputBaseFilename=istinbat-{#AppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "cuda"; Description: "NVIDIA GPU support (CUDA). Compiles llama.cpp; needs the CUDA Toolkit and the Visual Studio Build Tools"; Flags: unchecked
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "..\..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__,*.pyc,*.egg-info"; Flags: recursesubdirs ignoreversion
Source: "..\..\data\*"; DestDir: "{app}\data"; Flags: recursesubdirs ignoreversion
Source: "..\..\scripts\install-windows.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\..\scripts\uninstall-windows.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m istinbat"; WorkingDir: "{app}"; IconFilename: "{app}\data\windows\istinbat.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m istinbat"; WorkingDir: "{app}"; IconFilename: "{app}\data\windows\istinbat.ico"; Tasks: desktopicon

[Registry]
; The application registers its notification identity here at run time; this makes the uninstaller remove it.
Root: HKCU; Subkey: "Software\Classes\AppUserModelId\{#AppId}"; Flags: uninsdeletekey

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\build"
; The GTK runtime the installer downloaded. Books, models, the index and conversations are never removed.
Type: filesandordirs; Name: "{localappdata}\istinbat\gtk"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  Parameters: String;
  ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;
  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\install-windows.ps1') + '" -NoShortcut';
  if WizardIsTaskSelected('cuda') then
    Parameters := Parameters + ' -Cuda';
  WizardForm.StatusLabel.Caption := 'Setting up GTK, Python and the dependencies (several hundred megabytes are downloaded)...';
  if (not Exec('powershell.exe', Parameters, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
    MsgBox('Istinbat was copied, but its components could not be set up.' + #13#10 + #13#10 +
           'Check your internet connection and run this again from a PowerShell window:' + #13#10 +
           'powershell -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\install-windows.ps1') + '"',
           mbError, MB_OK);
end;
