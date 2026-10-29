var
  ServicePage: TOutputMsgWizardPage;
  LocationPage: TInputDirWizardPage;
  FilesPage: TInputFileWizardPage;
  FoldersPage: TInputDirWizardPage;
  NetworkPage: TInputQueryWizardPage;
  AccessPage: TInputOptionWizardPage;
  AuthenticationPage: TInputOptionWizardPage;
  LimitsPage, CleanupPage: TOutputMsgWizardPage;
  InputLimitMode, RecordsLimitMode, CleanupInputsMode, CleanupOutputsMode, CleanupLogsMode: TNewComboBox;
  InputLimitValue, RecordsLimitValue, CleanupInputsDays, CleanupOutputsDays, CleanupLogsDays: TNewEdit;
  StopButton, StartButton, RestartButton: TNewButton;
  ServiceState: String;
  ServiceLabel: TNewStaticText;
  FinishedText: String;
  ApiKeyValue: String;
  ApiKeyEdit: TNewEdit;

function PolicyMode(Page: TWizardPage; TopPosition: Integer; const CaptionText: String;
  IsLimit: Boolean): TNewComboBox;
var
  LabelControl: TNewStaticText;
begin
  LabelControl := TNewStaticText.Create(WizardForm);
  LabelControl.Parent := Page.Surface;
  LabelControl.Left := 0;
  LabelControl.Top := ScaleY(TopPosition + 4);
  LabelControl.Caption := CaptionText;
  LabelControl.AutoSize := True;
  Result := TNewComboBox.Create(WizardForm);
  Result.Parent := Page.Surface;
  Result.Left := ScaleX(155);
  Result.Top := ScaleY(TopPosition);
  Result.Width := ScaleX(145);
  Result.Style := csDropDownList;
  if IsLimit then begin
    Result.Items.Add('Padrão');
    Result.Items.Add('Personalizado');
    Result.Items.Add('Desabilitado');
  end else begin
    Result.Items.Add('Desativada');
    Result.Items.Add('Por idade');
  end;
  Result.ItemIndex := 0;
end;

function PolicyNumber(Page: TWizardPage; TopPosition: Integer): TNewEdit;
begin
  Result := TNewEdit.Create(WizardForm);
  Result.Parent := Page.Surface;
  Result.Left := ScaleX(315);
  Result.Top := ScaleY(TopPosition);
  Result.Width := ScaleX(100);
end;

procedure PolicyModeChanged(Sender: TObject);
begin
  if InputLimitMode.ItemIndex = 0 then InputLimitValue.Text := '2000000';
  if RecordsLimitMode.ItemIndex = 0 then RecordsLimitValue.Text := '500';
  InputLimitValue.Enabled := InputLimitMode.Enabled and (InputLimitMode.ItemIndex = 1);
  RecordsLimitValue.Enabled := RecordsLimitMode.Enabled and (RecordsLimitMode.ItemIndex = 1);
  CleanupInputsDays.Enabled := CleanupInputsMode.Enabled and (CleanupInputsMode.ItemIndex = 1);
  CleanupOutputsDays.Enabled := CleanupOutputsMode.Enabled and (CleanupOutputsMode.ItemIndex = 1);
  CleanupLogsDays.Enabled := CleanupLogsMode.Enabled and (CleanupLogsMode.ItemIndex = 1);
end;

function LimitSummary(Mode: TNewComboBox; Number: TNewEdit; const UnitText: String): String;
begin
  Result := Mode.Text;
  if Mode.ItemIndex <> 2 then Result := Result + ' (' + Number.Text + UnitText + ')';
end;

function CleanupSummary(Mode: TNewComboBox; Number: TNewEdit): String;
begin
  Result := Mode.Text;
  if Mode.ItemIndex = 1 then Result := Result + ' (' + Number.Text + ' dias)';
end;

function LimitModeValue(Control: TNewComboBox): String;
begin
  if Control.ItemIndex = 1 then Result := 'custom'
  else if Control.ItemIndex = 2 then Result := 'disabled'
  else Result := 'default';
end;

function CleanupModeValue(Control: TNewComboBox): String;
begin
  if Control.ItemIndex = 1 then Result := 'age' else Result := 'disabled';
end;

function PolicyField(const Key, DefaultValue, OverrideFile: String): String;
begin
  if OverrideFile = '' then Result := ResultValue(Key, DefaultValue)
  else Result := GetIniString('setup', Key, DefaultValue, OverrideFile);
end;

procedure LoadLimitMode(Control: TNewComboBox; const Value: String);
begin
  if Value = 'default' then Control.ItemIndex := 0
  else if Value = 'custom' then Control.ItemIndex := 1
  else if Value = 'disabled' then Control.ItemIndex := 2
  else RaiseException('Modo de limite inválido. Use default, custom ou disabled.');
end;

procedure LoadCleanupMode(Control: TNewComboBox; const Value: String);
begin
  if Value = 'disabled' then Control.ItemIndex := 0
  else if Value = 'age' then Control.ItemIndex := 1
  else RaiseException('Modo de limpeza inválido. Use disabled ou age.');
end;

procedure LoadPolicyFields(const OverrideFile: String);
var
  Required: String;
begin
  if AuthenticationPage.SelectedValueIndex = 1 then Required := 'false' else Required := 'true';
  Required := PolicyField('authenticationRequired', Required, OverrideFile);
  if Required = 'true' then AuthenticationPage.SelectedValueIndex := 0
  else if Required = 'false' then AuthenticationPage.SelectedValueIndex := 1
  else RaiseException('Autenticação deve ser true ou false.');
  LoadLimitMode(InputLimitMode, PolicyField('inputXmlMode', LimitModeValue(InputLimitMode), OverrideFile));
  LoadLimitMode(RecordsLimitMode, PolicyField('recordsMode', LimitModeValue(RecordsLimitMode), OverrideFile));
  InputLimitValue.Text := PolicyField('inputXmlBytes', InputLimitValue.Text, OverrideFile);
  RecordsLimitValue.Text := PolicyField('recordsCount', RecordsLimitValue.Text, OverrideFile);
  LoadCleanupMode(CleanupInputsMode, PolicyField('cleanupInputsMode', CleanupModeValue(CleanupInputsMode), OverrideFile));
  LoadCleanupMode(CleanupOutputsMode, PolicyField('cleanupOutputsMode', CleanupModeValue(CleanupOutputsMode), OverrideFile));
  LoadCleanupMode(CleanupLogsMode, PolicyField('cleanupLogsMode', CleanupModeValue(CleanupLogsMode), OverrideFile));
  CleanupInputsDays.Text := PolicyField('cleanupInputsDays', CleanupInputsDays.Text, OverrideFile);
  CleanupOutputsDays.Text := PolicyField('cleanupOutputsDays', CleanupOutputsDays.Text, OverrideFile);
  CleanupLogsDays.Text := PolicyField('cleanupLogsDays', CleanupLogsDays.Text, OverrideFile);
  PolicyModeChanged(nil);
end;

procedure CreatePolicyPages(AfterPageID: Integer);
begin
  AuthenticationPage := CreateInputOptionPage(AfterPageID, 'Autenticação',
    'Escolha se as chamadas exigem credencial.',
    'O login por API key emite um Bearer de 30 minutos. Credenciais inválidas são sempre recusadas.', True, False);
  AuthenticationPage.Add('Obrigatória: API key ou Bearer');
  AuthenticationPage.Add('Opcional: permitir chamadas sem credencial');
  AuthenticationPage.SelectedValueIndex := 0;
  LimitsPage := CreateOutputMsgPage(AuthenticationPage.ID, 'Limites de geração',
    'Escolha o limite de entrada e a quantidade de registros.',
    'Padrão: XML de entrada de 2.000.000 bytes e 500 registros. A saída não tem teto global de bytes.');
  InputLimitMode := PolicyMode(LimitsPage, 70, 'Entrada XML (bytes):', True);
  InputLimitValue := PolicyNumber(LimitsPage, 70);
  InputLimitValue.Text := '2000000';
  RecordsLimitMode := PolicyMode(LimitsPage, 115, 'Registros:', True);
  RecordsLimitValue := PolicyNumber(LimitsPage, 115);
  RecordsLimitValue.Text := '500';
  CleanupPage := CreateOutputMsgPage(LimitsPage.ID, 'Limpeza ao iniciar',
    'Escolha a retenção de cada pasta.',
    'Uma rodada ao iniciar remove arquivos antigos de qualquer origem e extensão, inclusive em subpastas. Entradas exige ativação explícita. O valor à direita é a idade em dias.');
  CleanupInputsMode := PolicyMode(CleanupPage, 85, 'Entradas (dias):', False);
  CleanupInputsDays := PolicyNumber(CleanupPage, 85);
  CleanupOutputsMode := PolicyMode(CleanupPage, 130, 'Saídas (dias):', False);
  CleanupOutputsDays := PolicyNumber(CleanupPage, 130);
  CleanupLogsMode := PolicyMode(CleanupPage, 175, 'Logs (dias):', False);
  CleanupLogsDays := PolicyNumber(CleanupPage, 175);
  CleanupLogsMode.ItemIndex := 1;
  CleanupInputsDays.Text := '30';
  CleanupOutputsDays.Text := '30';
  CleanupLogsDays.Text := '30';
  InputLimitMode.OnChange := @PolicyModeChanged;
  RecordsLimitMode.OnChange := @PolicyModeChanged;
  CleanupInputsMode.OnChange := @PolicyModeChanged;
  CleanupOutputsMode.OnChange := @PolicyModeChanged;
  CleanupLogsMode.OnChange := @PolicyModeChanged;
  LoadPolicyFields('');
end;

procedure WritePolicyRequest;
begin
  if AuthenticationPage.SelectedValueIndex = 1 then SetRequestValue('authenticationRequired', 'false')
  else SetRequestValue('authenticationRequired', 'true');
  SetRequestValue('inputXmlMode', LimitModeValue(InputLimitMode));
  if InputLimitMode.ItemIndex = 1 then SetRequestValue('inputXmlBytes', Trim(InputLimitValue.Text));
  SetRequestValue('recordsMode', LimitModeValue(RecordsLimitMode));
  if RecordsLimitMode.ItemIndex = 1 then SetRequestValue('recordsCount', Trim(RecordsLimitValue.Text));
  SetRequestValue('cleanupInputsMode', CleanupModeValue(CleanupInputsMode));
  if CleanupInputsMode.ItemIndex = 1 then SetRequestValue('cleanupInputsDays', Trim(CleanupInputsDays.Text));
  SetRequestValue('cleanupOutputsMode', CleanupModeValue(CleanupOutputsMode));
  if CleanupOutputsMode.ItemIndex = 1 then SetRequestValue('cleanupOutputsDays', Trim(CleanupOutputsDays.Text));
  SetRequestValue('cleanupLogsMode', CleanupModeValue(CleanupLogsMode));
  if CleanupLogsMode.ItemIndex = 1 then SetRequestValue('cleanupLogsDays', Trim(CleanupLogsDays.Text));
end;

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
  WritePolicyRequest;
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
    'Escolha as pastas de trabalho.',
    'Pastas locais, inclusive sem sincronização OneDrive, serão criadas se necessário. Para rede, use o caminho UNC completo; o serviço acessa o compartilhamento como a conta do computador.',
    False, 'MockAiZe API');
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
  CreatePolicyPages(NetworkPage.ID);
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
    LoadPolicyFields(OverrideFile);
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
    AuthenticationPage.CheckListBox.Enabled := False;
    InputLimitMode.Enabled := False;
    RecordsLimitMode.Enabled := False;
    CleanupInputsMode.Enabled := False;
    CleanupOutputsMode.Enabled := False;
    CleanupLogsMode.Enabled := False;
    PolicyModeChanged(nil);
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
  end else if CurPageID = CleanupPage.ID then begin
    WriteConfigurationRequest;
    Result := CallBridge('validate', 'Validando banco, pastas, porta e políticas...');
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
    'Porta: ' + NetworkPage.Values[0] + NewLine +
    'Limites: entrada ' + LimitSummary(InputLimitMode, InputLimitValue, ' bytes') + '; registros ' +
    LimitSummary(RecordsLimitMode, RecordsLimitValue, '') + NewLine +
    'Limpeza: entradas ' + CleanupSummary(CleanupInputsMode, CleanupInputsDays) + '; saídas ' +
    CleanupSummary(CleanupOutputsMode, CleanupOutputsDays) + '; logs ' +
    CleanupSummary(CleanupLogsMode, CleanupLogsDays) + NewLine;
  if AuthenticationPage.SelectedValueIndex = 0 then
    Result := Result + 'Autenticação obrigatória (API key ou Bearer).' + NewLine
  else Result := Result + 'Autenticação opcional.' + NewLine;
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
  ShowBridgeErrors := False;
  try
    Success := CallBridge('install', 'Instalando o serviço e verificando a saúde da API...');
  finally
    ShowBridgeErrors := True;
  end;
#else
  ShowBridgeErrors := False;
  try
    Success := CallBridge('configure', 'Salvando configuração e verificando a saúde da API...');
  finally
    ShowBridgeErrors := True;
  end;
#endif
  if not Success then begin
    Result := BridgeLastError;
    if Result = '' then Result := 'A operação falhou. Confira os caminhos e permissões selecionados.';
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
