# Instalação no Windows

Baixe `MockAiZe-API-Setup.exe` na release da API. O pacote inclui o runtime Python,
serviço e configurador; não depende da instalação do aplicativo visual. Execute o
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

Desinstale pelo Windows ou pelo configurador. A remoção preserva todos os dados por
padrão; sua exclusão posterior é manual e explícita. Binários bloqueados pelo
configurador em execução são agendados para remoção no próximo reinício. Não
remova pastas de dados sem fazer backup dos arquivos necessários.

## Construir a distribuição

Em um Windows com Python e dependências de desenvolvimento instaladas:

```powershell
python -m pip install -e '.[packaging,windows]'
./packaging/build.ps1
```

O único arquivo de entrega é `release\MockAiZe-API-Setup.exe`. O SHA-256 aparece
no resultado do build, sem acrescentar outro arquivo à entrega. As três especificações
PyInstaller produzem serviço sem janela, configurador e setup com payload completo.
Nenhum arquivo de planejamento nem checkout do estúdio entra no pacote.
`python -m mockaize_api.setup_ui --preview` permite verificar a interface sem
instalar serviço ou alterar firewall. Testes unitários não realizam operações
privilegiadas. Instalação, reinício do Windows, conta LocalService e firewall devem
ser homologados em VM Windows antes de distribuição; compilar não comprova esses
comportamentos. Assinatura Authenticode requer certificado de distribuição próprio.
