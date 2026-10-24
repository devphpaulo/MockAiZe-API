const
  ProductRegistry = 'SOFTWARE\MockAiZe\API';
  ServiceName = 'MockAiZeApiService.exe';

var
  BridgeExe, RequestFile, ResultFile, InstallDirectory, ConfigPath: String;
  BusyPage: TOutputProgressWizardPage;
  DiagnosticMode, OperationComplete: Boolean;

function InitializeSetup: Boolean;
begin
  { /DIAGNOSE never extracts the payload or invokes the service. It is safe for
    CI and uses Inno's ordinary cancelled-before-install exit code (2). }
  DiagnosticMode := ExpandConstant('{param:DIAGNOSE|0}') = '1';
  Result := not DiagnosticMode;
end;

procedure InitializeBridge;
begin
  RequestFile := ExpandConstant('{tmp}\maintenance-request.ini');
  ResultFile := ExpandConstant('{tmp}\maintenance-result.ini');
  BusyPage := CreateOutputProgressPage('MockAiZe API', 'Aguarde a conclusão da operação.');
end;

procedure SetRequestValue(const Key, Value: String);
begin
  if (Pos(#13, Value) > 0) or (Pos(#10, Value) > 0) then
    RaiseException('O campo contém uma quebra de linha inválida.');
  if not SetIniString('setup', Key, Value, RequestFile) then
    RaiseException('Não foi possível preparar os dados temporários da operação.');
end;

procedure NewRequest;
begin
  DeleteFile(RequestFile);
  DeleteFile(ResultFile);
  { A UTF-16 BOM makes the Windows INI API write Unicode without losing paths
    such as Saídas and MockAíZé. Result files use the same encoding. }
  if not SaveStringToFile(RequestFile, #$FF#$FE, False) then
    RaiseException('Não foi possível criar o arquivo temporário da operação.');
  SetRequestValue('installDir', InstallDirectory);
  SetRequestValue('configPath', ConfigPath);
end;

function ResultValue(const Key, Default: String): String;
begin
  Result := GetIniString('result', Key, Default, ResultFile);
end;

function CallBridge(const Operation, Description: String): Boolean;
var
  Code: Integer;
  MessageText: String;
begin
  Result := False;
  if not FileExists(BridgeExe) then begin
    MsgBox('O serviço do MockAiZe API não foi encontrado. Execute novamente o instalador para reparar os binários.', mbError, MB_OK);
    Exit;
  end;
  BusyPage.SetText(Description, '');
  BusyPage.SetProgress(0, 1);
  BusyPage.Show;
  try
    if not Exec(BridgeExe, '--maintenance ' + Operation + ' --request ' +
      AddQuotes(RequestFile) + ' --result ' + AddQuotes(ResultFile),
      ExtractFileDir(BridgeExe), SW_HIDE, ewWaitUntilTerminated, Code) then begin
      MessageText := 'Não foi possível iniciar o componente de manutenção: ' + SysErrorMessage(Code);
    end else if (Code <> 0) or (ResultValue('ok', '0') <> '1') then begin
      MessageText := ResultValue('message', 'A operação não foi concluída. Consulte os logs do MockAiZe API.');
    end else begin
      Result := True;
      BusyPage.SetProgress(1, 1);
    end;
  finally
    BusyPage.Hide;
  end;
  if not Result then
    MsgBox(MessageText, mbError, MB_OK);
end;

procedure FindInstalledBridge;
begin
  InstallDirectory := '';
  ConfigPath := '';
  RegQueryStringValue(HKLM64, ProductRegistry, 'InstallDir', InstallDirectory);
  RegQueryStringValue(HKLM64, ProductRegistry, 'ConfigPath', ConfigPath);
  if InstallDirectory = '' then
    InstallDirectory := ExtractFileDir(ExpandConstant('{srcexe}'));
  BridgeExe := AddBackslash(InstallDirectory) + ServiceName;
end;

function InspectInstallation: Boolean;
begin
  NewRequest;
  Result := CallBridge('inspect', 'Lendo a instalação e o estado do serviço...');
  if Result then begin
    InstallDirectory := ResultValue('installDir', InstallDirectory);
    ConfigPath := ResultValue('configPath', ConfigPath);
  end;
end;

procedure DeinitializeSetup;
begin
  { The API key is never written to logs. Remove both secret-bearing files on
    success, errors and cancellation; Inno also removes its protected temp directory. }
  if RequestFile <> '' then DeleteFile(RequestFile);
  if ResultFile <> '' then DeleteFile(ResultFile);
end;
