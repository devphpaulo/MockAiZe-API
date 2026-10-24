var
  RemovePage: TOutputMsgWizardPage;
  FinishedText: String;

procedure InitializeWizard;
begin
  InitializeBridge;
  FindInstalledBridge;
  if not FileExists(BridgeExe) then begin
    MsgBox('O componente de manutenção não foi encontrado. Execute este desinstalador na pasta dos binários instalados, ou repare a instalação primeiro.', mbError, MB_OK);
    Abort;
  end;
  if not InspectInstallation then Abort;
  RemovePage := CreateOutputMsgPage(wpWelcome, 'Desinstalar MockAiZe API',
    'O serviço será parado e removido da listagem do Windows.',
    'Após confirmar a remoção do serviço, você poderá escolher separadamente se deseja limpar os binários e cada pasta da API.' + #13#10#13#10 +
    'O banco SQLite do estúdio será preservado.' + #13#10#13#10 +
    'Binários: ' + InstallDirectory);
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := 'Parar e remover o serviço MockAiZe API, a regra de firewall e o registro do produto.' +
    NewLine + 'Depois disso, perguntar quais binários e pastas você deseja remover.';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Count, I, SelectedCount: Integer;
  Folders: TArrayOfString;
  CleanBinaries, RestartRequired: Boolean;
begin
  Result := '';
  if OperationComplete then Exit;
  NewRequest;
  if not CallBridge('detach', 'Parando e removendo o serviço da listagem do Windows...') then begin
    Result := 'A remoção do serviço não foi confirmada. Nenhum arquivo foi limpo.';
    Exit;
  end;

  { Capture all allowed paths before NewRequest deletes the detach result. }
  Count := GetIniInt('result', 'folderCount', 0, 0, 1000, ResultFile);
  SetArrayLength(Folders, Count);
  for I := 0 to Count - 1 do
    Folders[I] := ResultValue('folder' + IntToStr(I), '');
  CleanBinaries := SuppressibleMsgBox('O serviço foi removido da listagem.' + #13#10#13#10 +
    'Deseja também remover os binários desta pasta?' + #13#10 + InstallDirectory,
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;

  NewRequest;
  if CleanBinaries then SetRequestValue('cleanBinaries', '1')
  else SetRequestValue('cleanBinaries', '0');
  SelectedCount := 0;
  for I := 0 to Count - 1 do begin
    if (Folders[I] <> '') and
      (SuppressibleMsgBox('Deseja remover esta pasta e os arquivos contidos nela?' +
      '' + #13#10#13#10 + Folders[I], mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES) then begin
      SetRequestValue('folder' + IntToStr(SelectedCount), Folders[I]);
      SelectedCount := SelectedCount + 1;
    end;
  end;
  SetRequestValue('folderCount', IntToStr(SelectedCount));
  if not CallBridge('cleanup', 'Concluindo apenas a limpeza escolhida...') then begin
    Result := 'O serviço foi removido, mas a limpeza selecionada não foi concluída. Os detalhes aparecem na mensagem anterior.';
    Exit;
  end;
  RestartRequired := ResultValue('restartRequired', '0') = '1';
  OperationComplete := True;
  FinishedText := 'OK. O serviço MockAiZe API foi removido. A limpeza escolhida foi concluída.';
  if RestartRequired then
    FinishedText := FinishedText + #13#10#13#10 +
      'Alguns binários estavam em uso e serão removidos após reiniciar o Windows.';
  SuppressibleMsgBox(FinishedText, mbInformation, MB_OK, IDOK);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpReady then WizardForm.NextButton.Caption := 'Remover serviço';
  if CurPageID = wpFinished then begin
    WizardForm.FinishedLabel.Caption := FinishedText;
    WizardForm.FinishedHeadingLabel.Caption := 'Desinstalação concluída';
  end;
end;
