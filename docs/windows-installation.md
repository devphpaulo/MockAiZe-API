# Instalação no Windows

Na [página do workflow Windows](https://github.com/devphpaulo/MockAiZe-API/actions/workflows/build.yml),
abra uma execução concluída com sucesso e baixe o artefato **MockAiZe-API-Setup-Windows-x64**.
Extraia o ZIP do Actions: ele contém `MockAiZe-API-Setup.exe` e `MockAiZeApiUninstall.exe`.
O pacote inclui o runtime Python,
serviço, configurador e desinstalador; não depende da instalação do aplicativo visual. Execute o
setup e autorize a solicitação do Windows. A janela desktop preta e verde usa Qt
Widgets locais, sem navegador ou servidor do assistente.

Escolha o SQLite existente, as três pastas e a porta (padrão 6578). A API precisa
do banco e de eventuais arquivos WAL/SHM disponíveis antes do login. Utilize discos
locais; pastas de rede e OneDrive são recusadas pelo assistente. O banco é somente
leitura: o instalador nunca cria nem migra o banco do estúdio.

O padrão é `127.0.0.1`, sem regra de firewall. Ao habilitar rede, informe as origens
confiáveis: `LocalSubnet` ou IPs/sub-redes separados por vírgula. A regra exclusiva
`MockAiZe API HTTP` permite apenas o executável/porta do produto em perfis privado
e domínio. A chave e os XMLs trafegam por HTTP sem criptografia.

Revise e instale. Os binários ficam em `Program Files\MockAiZe API`. Configuração,
hash da chave e estado ficam na pasta de dados `Documentos\MockAíZé API`; caminhos
absolutos independem do perfil da conta do serviço. O serviço `MockAiZeApi` usa
`LocalService`, início automático e tentativas de recuperação. As ACLs concedem
leitura na entrada/banco e escrita nas pastas operacionais; a pasta de dados é
restrita a administradores, SYSTEM e LocalService. O sucesso exige HTTP 200 em
`/health` na porta configurada. Guarde a chave mostrada uma única vez.

Depois da confirmação é seguro apagar o setup baixado. Não apague os executáveis
instalados. O atalho **MockAíZé API — Configurar** permite iniciar, parar, reiniciar,
alterar configuração, abrir logs e desinstalar. Alterações param o serviço, validam
a nova configuração e verificam a saúde após reiniciar; falhas restauram o JSON.

## Atualização e recuperação

Abra o novo setup. Ele detecta automaticamente instalação nova, atualização ou
reparo. Na atualização, os campos existentes permanecem salvos. Pare o serviço e
clique **Já pausei; verificar novamente**. O instalador consulta o SCM novamente
antes de substituir arquivos; o clique sozinho não desbloqueia a atualização.

O pacote é preparado num diretório temporário ao lado da instalação. Os binários
antigos são renomeados para `.rollback` e restaurados se a troca ou saúde falhar.
Configuração, credenciais, estado, XMLs e logs permanecem no diretório de dados.
Se uma tentativa deixou `.rollback`/`.staging`, preserve essas cópias para
diagnóstico antes de nova tentativa. Para reparar binários a partir do configurador,
abra o setup da release desejada. O próprio configurador instalado não substitui o
executável em que está rodando.

## Desinstalação

Abra `MockAiZeApiUninstall.exe`, instalado em Program Files, ou use Desinstalar
no Windows/configurador. O configurador abre esse executável separado e se fecha.
O desinstalador usa o ícone do MockAíZé e solicita a elevação padrão do Windows.

1. Para o serviço e confirma sua parada.
2. Remove o serviço, a regra própria do firewall e o cadastro do aplicativo.
3. Espera o Windows confirmar que o serviço deixou de existir. Se continuar
   marcado para exclusão por algum console aberto, informa o problema e não
   inicia a limpeza nem mostra sucesso.
4. Pergunta se deseja apagar os binários da pasta específica do produto em
   Program Files. **Não** é o padrão.
5. Pergunta quais pastas da API deseja limpar, mostrando os caminhos e avisando
   que seu conteúdo será apagado. Pastas aninhadas aparecem como uma única
   opção da pasta principal; pastas externas configuradas aparecem separadamente.
6. Executa somente a limpeza escolhida, mostra **OK** e finaliza. Quando o
   próprio executável estiver em uso, informa que a remoção será concluída no
   próximo reinício; não afirma que os arquivos bloqueados já foram apagados.

O SQLite de origem do estúdio e qualquer pasta que o contenha não são oferecidos
para exclusão. Raízes do disco, pastas de sistema, perfil do usuário e destinos
com links/junções são recusados. Se a configuração estiver ilegível, as pastas de
dados são preservadas. Caso escolha manter os binários, o comprovante local
`installation.json` permite reconhecer a instalação para limpeza posterior, mesmo
após a remoção do serviço e de seu cadastro no Windows.

## Falha ao carregar QtCore

O erro `DLL load failed while importing QtCore: Não foi possível encontrar o
procedimento especificado` foi diagnosticado nos binários locais antigos. O build
capturou `icuuc.dll` de uma ferramenta auxiliar Poppler presente no PATH do
ambiente de desenvolvimento. O Qt 6.12 espera as funções ICU do Windows, como
`ucnv_close`; a DLL capturada fornece nomes diferentes, como `ucnv_close_78`.

A correção do commit `325830b` isola os caminhos de busca durante a compilação e
rejeita bibliotecas nativas coletadas fora do projeto, do Python/ambiente virtual
e do Windows. O diagnóstico compilado passou no mesmo computador com o ambiente
normal e com os caminhos de desenvolvimento removidos; a ICU externa deixou de
ser incluída. Os EXEs antigos precisam ser substituídos pelo novo build.

O Actions também executa os três EXEs gráficos com `--diagnose-ui <relatorio.json>`
antes do upload. Esse modo carrega QtCore/Gui/Widgets, o plugin nativo Windows e
o ícone, renderiza uma janela de teste e termina com resultado JSON. Não entra no
assistente e não registra, para ou remove serviços. A elevação do manifesto dos
EXEs permanece necessária; no CI essa verificação roda no runner com elevação.
Falha no carregamento ou na renderização impede a publicação do artefato.

Essa correção funcional não resolve nem classifica a detecção do Kaspersky.
Consulte a [análise do antivírus](antivirus-analysis.md) para essa investigação.

## Construir a distribuição

Em um Windows com Python e dependências de desenvolvimento instaladas:

```powershell
python -m pip install -e '.[packaging,windows]'
./packaging/build.ps1
```

Os arquivos de entrega são `release\MockAiZe-API-Setup.exe` e
`release\MockAiZeApiUninstall.exe`. O primeiro também instala uma cópia do segundo
em Program Files. O SHA-256 aparece no resultado do build. As quatro especificações
PyInstaller produzem serviço sem janela, configurador, desinstalador e setup completo.
Todos os executáveis usam o ícone fornecido do MockAíZé, convertido em ICO com
tamanhos de 16 a 256 pixels. O PNG/ICO é mantido neste próprio repositório; o
build não depende de acessar o diretório do estúdio.
O Actions repete o build em pushes, pull requests ou acionamento manual. Antes de
publicar os dois EXEs, valida os quatro binários internos (Windows x64, ícones e
elevação), origem das bibliotecas, runtime e licenças, e executa saúde, catálogo e
geração XML no serviço compilado. Também testa o carregamento do Qt e a renderização
nos três EXEs gráficos. Os hashes ficam no resumo da execução; o artefato é mantido por 30 dias.
Nenhum arquivo de planejamento nem checkout do estúdio entra no pacote.
`python -m mockaize_api.setup_ui --preview` permite verificar a interface sem
instalar serviço ou alterar firewall. Testes unitários não realizam operações
privilegiadas. Instalação, reinício do Windows, conta LocalService e firewall devem
ser homologados em VM Windows antes de distribuição; compilar não comprova esses
comportamentos. Assinatura Authenticode requer certificado de distribuição próprio.
