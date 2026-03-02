; NetMonitor Agent — Inno Setup 安装脚本
; 生成: NetMonitor-Agent-Setup.exe
; 安装位置: Program Files\NetMonitor
; 自动创建桌面快捷方式 & 开始菜单项

#define AppName      "NetMonitor Agent"
#define AppVersion   "2.0.2"
#define AppPublisher "NetMonitor"
#define AppExe       "NetMonitor-Agent.exe"

[Setup]
AppId={{8B3A4C1D-2E5F-4A6B-9C7D-0E1F2A3B4C5D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\NetMonitor
DefaultGroupName=NetMonitor
AllowNoIcons=no
OutputBaseFilename=NetMonitor-Agent-Setup
OutputDir=installer_out
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=
; 不需要管理员权限（安装到用户目录时可改为 lowest）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName={#AppName}
; 显示安装后启动选项
DisableFinishedPage=no

[Languages]
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; 默认勾选：创建桌面快捷方式
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce
; 可选：开机自启
Name: "startup"; Description: "开机时自动启动"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 桌面快捷方式
Name: "{autodesktop}\{#AppName}";   Filename: "{app}\{#AppExe}"; Tasks: desktopicon
; 开始菜单
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}";    Filename: "{uninstallexe}"

[Registry]
; 开机自启（勾选时写注册表）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "NetMonitor-Agent"; \
  ValueData: """{app}\{#AppExe}"""; \
  Flags: uninsdeletevalue; Tasks: startup

[Run]
; 安装完成后启动
Filename: "{app}\{#AppExe}"; \
  Description: "立即启动 {#AppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载时先关闭正在运行的 agent
Filename: "taskkill"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden waituntilterminated
