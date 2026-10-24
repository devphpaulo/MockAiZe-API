var
  ServicePage: TOutputMsgWizardPage;
  LocationPage: TInputDirWizardPage;
  FilesPage: TInputFileWizardPage;
  FoldersPage: TInputDirWizardPage;
  NetworkPage: TInputQueryWizardPage;
  AccessPage: TInputOptionWizardPage;
  StopButton, StartButton, RestartButton: TNewButton;
  ServiceState: String;
  ServiceLabel: TNewStaticText;
  FinishedText: String;
  ApiKeyValue: String;
  ApiKeyEdit: TNewEdit;

procedure RefreshServiceLabel;
begin
  ServiceLabel.Caption := 'Estado do serviço: ' + ServiceState;
  StopButton.Enabled := (ServiceState <> 'absent') and (ServiceState <> 'stopped');
#if Frontend == "config"
  StartButton.Enabled := ServiceState = 'stopped';
  RestartButton.Enabled := ServiceState = 'running';
#endif
end;

procedure ServiceAction(Sender: TObject);
var
  Action: String;
begin
  if Sender = StopButton then Action := 'stop'
#if Frontend == "config"
  else if Sender = StartButton then Action := 'start'
  else Action := 'restart';
#else
  else Action := 'stop';
#endif
  NewRequest;
  if CallBridge(Action, 'Alterando o estado do serviço...') then begin
    NewRequest;
    if CallBridge('inspect', 'Confirmando o estado do serviço...') then begin
      ServiceState := ResultValue('state', 'unknown');
      RefreshServiceLabel;
    end;
  end;
end;

function ServiceButton(const CaptionText: String; const LeftPosition: Integer): TNewButton;
begin
  Result := TNewButton.Create(WizardForm);
  Result.Parent := ServicePage.Surface;
  Result.Left := ScaleX(LeftPosition);
  Result.Top := ScaleY(85);
  Result.Width := ScaleX(125);
  Result.Height := ScaleY(30);
  Result.Caption := CaptionText;
  Result.OnClick := @ServiceAction;
end;

procedure WriteConfigurationRequest;
begin
  InstallDirectory := Trim(LocationPage.Values[0]);
  ConfigPath := Trim(FilesPage.Values[1]);
  NewRequest;
  SetRequestValue('databasePath', Trim(FilesPage.Values[0]));
  SetRequestValue('inputDirectory', Trim(FoldersPage.Values[0]));
  SetRequestValue('outputDirectory', Trim(FoldersPage.Values[1]));
  SetRequestValue('logsDirectory', Trim(FoldersPage.Values[2]));
  SetRequestValue('port', Trim(NetworkPage.Values[0]));
  SetRequestValue('origins', Trim(NetworkPage.Values[1]));
  if AccessPage.SelectedValueIndex = 1 then begin
    SetRequestValue('host', '0.0.0.0');
    SetRequestValue('firewallAccess', 'Y');
  end else begin
    SetRequestValue('host', '127.0.0.1');
    SetRequestValue('firewallAccess', 'N');
  end;
#if Frontend == "setup"
  SetRequestValue('payloadDirectory', ExpandConstant('{tmp}\payload'));
#endif
end;

procedure InitializeWizard;
var
  Root, OverrideFile: String;
  SavedTarget, SavedConfig: Boolean;
begin
  InitializeBridge;
  ApiKeyEdit := TNewEdit.Create(WizardForm);
  ApiKeyEdit.Parent := WizardForm.FinishedPage;
  ApiKeyEdit.Left := WizardForm.FinishedLabel.Left;
  ApiKeyEdit.Top := WizardForm.FinishedLabel.Top + ScaleY(105);
  ApiKeyEdit.Width := WizardForm.FinishedLabel.Width;
  ApiKeyEdit.ReadOnly := True;
  ApiKeyEdit.Visible := False;
#if Frontend == "setup"
  InstallDirectory := ExpandConstant('{autopf64}\MockAiZe API');
  ConfigPath := ExpandConstant('{userdocs}\MockAíZé API\config.json');
  BusyPage.SetText('Preparando os componentes da instalação...', '');
  BusyPage.Show;
  try
    ExtractTemporaryFiles('{tmp}\payload\*');
  finally
    BusyPage.Hide;
  end;
  BridgeExe := ExpandConstant('{tmp}\payload\MockAiZeApiService.exe');
#else
  FindInstalledBridge;
#endif
  if not InspectInstallation then Abort;
  ServiceState := ResultValue('state', 'absent');
  SavedTarget := ResultValue('configPath', '') <> '';
  SavedConfig := ResultValue('configValid', '0') = '1';
#if Frontend == "config"
  if ServiceState = 'absent' then begin
    MsgBox('Não há um serviço instalado para configurar. Execute o instalador do MockAiZe API.', mbInformation, MB_OK);
    Abort;
  end;
#endif
  Root := ExpandConstant('{userdocs}\MockAíZé API');
  ServicePage := CreateOutputMsgPage(wpWelcome, 'Serviço MockAiZe API',
    'Confira o serviço antes de continuar.',
    'Para substituir os binários ou salvar configurações, primeiro pare o serviço pelo botão abaixo.');
  ServiceLabel := TNewStaticText.Create(WizardForm);
  ServiceLabel.Parent := ServicePage.Surface;
  ServiceLabel.Left := 0;
  ServiceLabel.Top := ScaleY(55);
  ServiceLabel.AutoSize := True;
  StopButton := ServiceButton('Parar serviço', 0);
#if Frontend == "config"
  StartButton := ServiceButton('Iniciar serviço', 140);
  RestartButton := ServiceButton('Reiniciar serviço', 280);
#endif
  RefreshServiceLabel;

  LocationPage := CreateInputDirPage(ServicePage.ID, 'Binários do MockAiZe API',
    'Onde os componentes serão instalados?', 'Escolha uma pasta dedicada ao MockAiZe API.', False, 'MockAiZe API');
  LocationPage.Add('Pasta dos binários:');
  LocationPage.Values[0] := InstallDirectory;
  { Registered paths cannot be moved as an accidental side effect of an update. }
  LocationPage.Edits[0].Enabled := not SavedTarget;
  LocationPage.Buttons[0].Enabled := not SavedTarget;

  FilesPage := CreateInputFilePage(LocationPage.ID, 'Banco e configuração',
    'Selecione o banco existente do MockAiZe.', 'O banco do estúdio será aberto somente para leitura.');
  FilesPage.Add('Banco SQLite do MockAiZe:', 'Banco SQLite|*.sqlite3;*.sqlite;*.db|Todos os arquivos|*.*', '.sqlite3');
  FilesPage.Add('Arquivo de configuração da API:', 'Configuração JSON|*.json|Todos os arquivos|*.*', '.json');
  FilesPage.IsSaveButton[1] := True;
  FilesPage.Values[0] := ResultValue('databasePath', ExpandConstant('{userdocs}\MockAíZé\mockaize.sqlite3'));
  FilesPage.Values[1] := ConfigPath;
  FilesPage.Edits[1].Enabled := not SavedTarget;
  FilesPage.Buttons[1].Enabled := not SavedTarget;

  FoldersPage := CreateInputDirPage(FilesPage.ID, 'Pastas da API',
    'Escolha as pastas de trabalho.', 'Use pastas dedicadas às entradas, saídas e logs da API.', False, 'MockAiZe API');
  FoldersPage.Add('Entradas:');
  FoldersPage.Add('Saídas:');
  FoldersPage.Add('Logs:');
  FoldersPage.Values[0] := ResultValue('inputDirectory', Root + '\Entradas');
  FoldersPage.Values[1] := ResultValue('outputDirectory', Root + '\Saídas');
  FoldersPage.Values[2] := ResultValue('logsDirectory', Root + '\Logs');

  AccessPage := CreateInputOptionPage(FoldersPage.ID, 'Acesso à API',
    'Escolha quem poderá conectar.', 'A API usa HTTP. Autorize acesso em rede apenas em redes confiáveis.', True, False);
  AccessPage.Add('Somente neste computador (localhost), sem regra de firewall');
  AccessPage.Add('Rede local, com regra de firewall limitada às origens informadas');
  if ResultValue('firewallAccess', 'N') = 'Y' then AccessPage.SelectedValueIndex := 1
  else AccessPage.SelectedValueIndex := 0;

  NetworkPage := CreateInputQueryPage(AccessPage.ID, 'Porta e origens',
    'Configure a conexão com a API.',
    'LocalSubnet permite somente a sub-rede local. Você também pode informar IPs ou sub-redes separados por vírgula.');
  NetworkPage.Add('Porta (1 a 65535):', False);
  NetworkPage.Add('Origens confiáveis para acesso em rede:', False);
  NetworkPage.Values[0] := ResultValue('port', '6578');
  NetworkPage.Values[1] := ResultValue('origins', 'LocalSubnet');
  OverrideFile := ExpandConstant('{param:REQUEST|}');
  if OverrideFile <> '' then begin
    if not FileExists(OverrideFile) then RaiseException('Arquivo de configuração solicitado não encontrado.');
#if Frontend == "setup"
    if not SavedConfig then begin
#endif
    LocationPage.Values[0] := GetIniString('setup', 'installDir', LocationPage.Values[0], OverrideFile);
    FilesPage.Values[0] := GetIniString('setup', 'databasePath', FilesPage.Values[0], OverrideFile);
    FilesPage.Values[1] := GetIniString('setup', 'configPath', FilesPage.Values[1], OverrideFile);
    FoldersPage.Values[0] := GetIniString('setup', 'inputDirectory', FoldersPage.Values[0], OverrideFile);
    FoldersPage.Values[1] := GetIniString('setup', 'outputDirectory', FoldersPage.Values[1], OverrideFile);
    FoldersPage.Values[2] := GetIniString('setup', 'logsDirectory', FoldersPage.Values[2], OverrideFile);
    NetworkPage.Values[0] := GetIniString('setup', 'port', NetworkPage.Values[0], OverrideFile);
    NetworkPage.Values[1] := GetIniString('setup', 'origins', NetworkPage.Values[1], OverrideFile);
    if GetIniString('setup', 'firewallAccess', 'N', OverrideFile) = 'Y' then AccessPage.SelectedValueIndex := 1
    else AccessPage.SelectedValueIndex := 0;
#if Frontend == "setup"
    end;
#endif
  end else if WizardSilent then
    RaiseException('A instalação silenciosa exige /REQUEST com configuração explícita.');
#if Frontend == "setup"
  if SavedConfig then begin
    FilesPage.Edits[0].Enabled := False;
    FilesPage.Buttons[0].Enabled := False;
    FoldersPage.Edits[0].Enabled := False;
    FoldersPage.Edits[1].Enabled := False;
    FoldersPage.Edits[2].Enabled := False;
    FoldersPage.Buttons[0].Enabled := False;
    FoldersPage.Buttons[1].Enabled := False;
    FoldersPage.Buttons[2].Enabled := False;
    AccessPage.CheckListBox.Enabled := False;
    NetworkPage.Edits[0].Enabled := False;
    NetworkPage.Edits[1].Enabled := False;
  end;
#endif
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  PortNumber: Integer;
begin
  Result := True;
  if CurPageID = ServicePage.ID then begin
    NewRequest;
    Result := CallBridge('inspect', 'Confirmando que o serviço está parado...');
    if not Result then Exit;
    ServiceState := ResultValue('state', 'unknown');
    RefreshServiceLabel;
    Result := (ServiceState = 'absent') or (ServiceState = 'stopped');
    if not Result then
      MsgBox('Pare o serviço pelo botão e aguarde a confirmação antes de continuar.', mbInformation, MB_OK);
  end else if CurPageID = NetworkPage.ID then begin
    PortNumber := StrToIntDef(Trim(NetworkPage.Values[0]), 0);
    if (PortNumber < 1) or (PortNumber > 65535) then begin
      MsgBox('Informe uma porta entre 1 e 65535.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    WriteConfigurationRequest;
    Result := CallBridge('validate', 'Validando banco, pastas, porta e configuração...');
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := 'Binários: ' + LocationPage.Values[0] + NewLine +
    'Configuração: ' + FilesPage.Values[1] + NewLine +
    'Banco (somente leitura): ' + FilesPage.Values[0] + NewLine +
    'Entradas: ' + FoldersPage.Values[0] + NewLine +
    'Saídas: ' + FoldersPage.Values[1] + NewLine +
    'Logs: ' + FoldersPage.Values[2] + NewLine +
    'Porta: ' + NetworkPage.Values[0] + NewLine;
  if AccessPage.SelectedValueIndex = 1 then
    Result := Result + 'Rede local; origens: ' + NetworkPage.Values[1]
  else Result := Result + 'Acesso somente neste computador (127.0.0.1).';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Success: Boolean;
begin
  Result := '';
  if OperationComplete then Exit;
  WriteConfigurationRequest;
  if WizardSilent and not FileExists(AddBackslash(ExtractFileDir(ConfigPath)) + 'credentials.json') then begin
    Result := 'A instalação inicial deve exibir a chave pela interface. Automação exige credenciais pré-provisionadas.';
    Exit;
  end;
#if Frontend == "setup"
  Success := CallBridge('install', 'Instalando o serviço e verificando a saúde da API...');
#else
  Success := CallBridge('configure', 'Salvando configuração e verificando a saúde da API...');
#endif
  if not Success then begin
    Result := 'A operação falhou. Confira os dados e os logs antes de tentar novamente.';
    Exit;
  end;
  OperationComplete := True;
  FinishedText := 'OK. O serviço MockAiZe API está configurado e funcionando.';
  ApiKeyValue := ResultValue('apiKey', '');
  if ApiKeyValue <> '' then
    FinishedText := FinishedText + #13#10#13#10 +
      'Selecione a chave abaixo e copie com Ctrl+C. Guarde em local seguro; será exibida apenas agora.';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then begin
    WizardForm.FinishedLabel.Caption := FinishedText;
    WizardForm.FinishedLabel.Height := ScaleY(90);
    WizardForm.FinishedHeadingLabel.Caption := 'MockAiZe API pronto';
    if ApiKeyValue <> '' then begin
      ApiKeyEdit.Text := ApiKeyValue;
      ApiKeyEdit.Visible := True;
      ApiKeyEdit.SelectAll;
    end;
  end;
end;
