# Instalação no Windows

A distribuição usa Inno Setup e uma única cópia do runtime do serviço. Não usa Qt, navegador ou instalação externa de Python. Baixe o artefato **MockAiZe-API-Setup-Windows-x64** de uma execução bem-sucedida do [workflow Windows](https://github.com/devphpaulo/MockAiZe-API/actions/workflows/build.yml) e extraia os dois EXEs do ZIP.

## Primeiro setup

Abra `MockAiZe-API-Setup.exe` e autorize a solicitação padrão do Windows.

1. Confira o estado do serviço. Na primeira instalação, ele estará ausente.
2. Escolha uma pasta dedicada aos binários; o padrão é `Program Files\MockAiZe API`.
3. Selecione o SQLite existente e o local do JSON de configuração.
4. Escolha as pastas de entrada, saída e logs, a porta e o acesso local ou em rede.
5. Revise e instale. O sucesso depende de o serviço iniciar e responder HTTP 200 em `/health`.
6. Se uma chave foi criada, selecione seu campo na página final e copie com Ctrl+C. Ela é exibida somente nessa instalação; apenas o hash é salvo.

O padrão é porta 6578, `127.0.0.1`, sem regra de firewall. A opção de rede usa `0.0.0.0`, HTTP sem criptografia e a regra exclusiva `MockAiZe API HTTP`, limitada ao executável, porta, perfis privado/domínio e às origens informadas (`LocalSubnet` ou IPs/sub-redes específicos).

Use discos locais disponíveis antes do login. Rede/OneDrive são recusados. O banco do estúdio e seus arquivos WAL/SHM precisam estar disponíveis; não são criados nem migrados pelo instalador.

O serviço `MockAiZeApi` usa LocalService e início automático. As ACLs permitem leitura na entrada e no banco e escrita nas pastas operacionais. Configuração e credencial ficam numa pasta de dados restrita; o padrão é `Documentos\MockAíZé API`. Os caminhos salvos são absolutos.

Depois da confirmação, o setup baixado pode ser apagado. Os arquivos instalados incluem:

| Arquivo | Uso |
|---|---|
| `MockAiZeApiService.exe` e `_internal/` | Serviço e sua única cópia do runtime |
| `MockAiZeApiConfig.exe` | Configurador Inno nativo, sem Python/Qt próprios |
| `MockAiZeApiUninstall.exe` | Desinstalador Inno nativo |
| `installation.json` | Recibo para identificar a instalação após a remoção do serviço |
| `licenses/` | Licenças e avisos dos componentes distribuídos |

## Configuração, atualização e reparo

O atalho **MockAíZé API — Configurar** permite iniciar, parar e reiniciar o serviço e alterar os campos de configuração. Pare o serviço pelo botão e aguarde a confirmação antes de continuar. Ao salvar, a API verifica os valores e sua saúde após reiniciar. Falhas restauram a configuração anterior.

Para atualizar ou reparar binários, abra o novo setup. Ele lê a instalação e exige que o SCM confirme o serviço parado antes da troca. Configuração válida é preservada durante a atualização; use o configurador para alterá-la. Configuração ilegível pode ser substituída num reparo explícito, mantendo uma cópia de diagnóstico.

O setup prepara o pacote numa pasta temporária privada. O componente de instalação copia os binários para uma pasta `.staging` ao lado do destino e mantém `.rollback` durante a troca. Falhas restauram os binários anteriores. Se uma tentativa deixou essas pastas, preserve-as para diagnóstico antes de repetir.

## Desinstalação

Use Desinstalar no Windows ou abra `MockAiZeApiUninstall.exe`. O EXE separado distribuído encontra a instalação registrada; a cópia instalada também reconhece seu recibo local quando o serviço já foi removido.

1. Confirme a remoção do serviço.
2. O desinstalador para o serviço, remove o cadastro e a regra própria de firewall e espera sua ausência no SCM.
3. Somente após essa confirmação, pergunta se deseja limpar os binários. **Não** é o padrão.
4. Pergunta sobre cada pasta autorizada, mostrando os caminhos. Pastas aninhadas são agrupadas; a limpeza depende de cada escolha.
5. Executa a limpeza selecionada, mostra **OK** e finaliza. Arquivos em uso são agendados para remoção no reinício e isso é informado.

O SQLite do estúdio e qualquer pasta que o contenha não são oferecidos para exclusão. Raízes, pastas de sistema, perfil do usuário e árvores com links/junções são protegidos. Configuração ilegível faz os dados serem preservados. Se escolher manter os binários, o recibo permite executar a limpeza depois.

## Construir e verificar

```powershell
python -m pip install -e '.[windows,packaging]'
.\packaging\build.ps1
# Compilador em outro local:
.\packaging\build.ps1 -InnoCompiler 'C:\ferramentas\Inno Setup 6\ISCC.exe'
```

O script compila somente o serviço Python em modo diretório e os três frontends nativos Inno. Os ícones vêm do ICO versionado. O produto distribui as cinco rotas funcionais e `/health`; o runtime não depende do checkout ou dos scripts do estúdio.

O build recusa Qt/Pythonwin e OpenSSL opcional, runtimes duplicados, credenciais, bancos e planejamento no payload. SHA-256 e bytes dos EXEs aparecem no log e no resumo do Actions. O bootstrap Inno é x86 e instala somente em Windows x64 compatível; o serviço e seu runtime são x64. O Inno solicita elevação conforme `PrivilegesRequired=admin`.

`packaging/smoke.py` testa o serviço compilado sem registrá-lo. `packaging/smoke_native.py` testa instalação real, configuração, reparo, remoção e limpeza optativa; recusa executar fora do runner Windows descartável do GitHub ou quando já existe serviço homônimo.

O modo silencioso exige `/REQUEST=<INI UTF-16>` com os campos da seção `setup` do protocolo em `maintenance.py`. A criação inicial da chave exige a interface; automação silenciosa usa credenciais pré-provisionadas. Não exponha credenciais em linha de comando ou logs.

O teste do Actions não substitui reiniciar uma VM sem login nem a análise antimalware da distribuição. Assinatura Authenticode requer certificado de publicador próprio.
