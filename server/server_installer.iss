; NetMonitor Server — Inno Setup 安装脚本
; 生成: NetMonitor-Server-Setup.exe

#define AppName      "NetMonitor Server"
#define AppVersion   "1.6"
#define AppPublisher "NetMonitor"
#define AppExe       "NetMonitor-Server.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\NetMonitor\Server
DefaultGroupName=NetMonitor
OutputBaseFilename=NetMonitor-Server-Setup
OutputDir=installer_out
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName={#AppName}

[Languages]
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce
Name: "startup";     Description: "开机时自动启动";  GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{group}\{#AppName}";         Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}";   Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "NetMonitor-Server"; \
  ValueData: """{app}\{#AppExe}"""; \
  Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; \
  Description: "立即启动 {#AppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden waituntilterminated
