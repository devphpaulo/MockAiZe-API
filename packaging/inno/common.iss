#ifndef RepositoryRoot
  #error "Compile with /DRepositoryRoot=<absolute repository path>"
#endif

[Setup]
AppId=MockAiZeApiNative{#Frontend}
AppName=MockAiZe API
AppVersion=0.2.0
VersionInfoVersion=0.2.0.0
AppPublisher=MockAiZe
AppPublisherURL=https://github.com/devphpaulo/MockAiZe-API
AppSupportURL=https://github.com/devphpaulo/MockAiZe-API/issues
VersionInfoProductName=MockAiZe API
VersionInfoDescription=MockAiZe API - {#Frontend}
DefaultDirName={autopf64}\MockAiZe API
CreateAppDir=no
Uninstallable=no
CreateUninstallRegKey=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
SetupIconFile={#RepositoryRoot}\src\mockaize_api\assets\mockaize.ico
WizardStyle=modern
WizardSizePercent=120
Compression=lzma2/ultra64
InternalCompressLevel=ultra64
SolidCompression=yes
CloseApplications=no
RestartApplications=no
DisableReadyMemo=no
AlwaysShowDirOnReadyPage=no
AlwaysShowGroupOnReadyPage=no
AllowCancelDuringInstall=no
#if Frontend == "setup"
OutputDir={#RepositoryRoot}\release
OutputBaseFilename=MockAiZe-API-Setup
#elif Frontend == "config"
OutputDir={#RepositoryRoot}\build\native
OutputBaseFilename=MockAiZeApiConfig
#else
OutputDir={#RepositoryRoot}\build\native
OutputBaseFilename=MockAiZeApiUninstall
DisableFinishedPage=yes
#endif

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
