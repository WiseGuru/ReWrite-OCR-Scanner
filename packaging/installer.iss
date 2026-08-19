; Inno Setup script for the Windows installer.
; Build after PyInstaller has produced dist\rewrite-ocr:
;   iscc /DAppVersion=<version> packaging\installer.iss
; Output: dist\ReWrite-OCR-Scanner-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7E1D2C5A-52C4-4B7B-9A64-2C3F0E9B7A11}
AppName=ReWrite OCR Scanner
AppVersion={#AppVersion}
AppPublisher=WiseGuru
AppPublisherURL=https://github.com/WiseGuru/ReWrite-OCR-Scanner
DefaultDirName={autopf}\ReWrite OCR Scanner
DefaultGroupName=ReWrite OCR Scanner
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=ReWrite-OCR-Scanner-Setup-{#AppVersion}
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
  GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\rewrite-ocr\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ReWrite OCR Scanner"; Filename: "{app}\rewrite-ocr.exe"
Name: "{autodesktop}\ReWrite OCR Scanner"; Filename: "{app}\rewrite-ocr.exe"; \
  Tasks: desktopicon

[Run]
Filename: "{app}\rewrite-ocr.exe"; \
  Description: "{cm:LaunchProgram,ReWrite OCR Scanner}"; \
  Flags: nowait postinstall skipifsilent

; Per-user data (projects, models, settings) in %LOCALAPPDATA%\ReWriteOCR is
; deliberately left untouched by uninstall.
