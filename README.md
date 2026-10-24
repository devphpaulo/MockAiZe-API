# MockAíZé API para Windows

Serviço independente para consultar o SQLite do MockAíZé e gerar XML com o estúdio fechado. O banco de origem é somente leitura; contadores e idempotência ficam numa base própria.

**Instalação e configuração nativas com Inno Setup, sem Qt.** A distribuição contém `MockAiZe-API-Setup.exe` e `MockAiZeApiUninstall.exe`. O setup instala o serviço, o configurador e o desinstalador em uma pasta dedicada de Program Files, todos com o ícone do MockAíZé. Não é necessário instalar Python no computador de destino.

Uma única cópia do runtime Python executa o serviço HTTP/XML. Não inclui PySide/Qt, Shiboken, Pythonwin, TLS/OpenSSL opcional ou cópias de Python nos frontends. As rotas e o motor foram preservados. O setup fica próximo de 11 MB e o desinstalador próximo de 2,2 MB; bytes e hashes exatos aparecem no Actions.

Estado: `0.1.0.dev0`, em validação. O setup cria as pastas de trabalho ausentes, inclusive sob `C:\Users\<usuário>\OneDrive\Documentos`, mesmo quando o OneDrive não está instalado; nesse caso, o caminho é uma pasta local comum.

## Recursos

- `/health`; catálogo autenticado de arquivos, modos e modelos de retorno.
- Novo com 1 a 500 registros; Retorno separado ou misto, com comparação estrutural.
- Entrega inline ou em diretório, sem sobrescrita; SHA-256 e tamanho exato. Nenhum ZIP de XML é gerado.
- Chave `X-API-Key`, Problem Details, limites, idempotência e logs sanitizados.
- Serviço Windows de baixa permissão, com início automático e firewall opcional limitado às origens escolhidas.
- Atualização e reparo com parada verificada, troca de arquivos e rollback.
- Desinstalação: confirma a remoção do serviço, pergunta sobre binários e pastas, preserva dados por padrão, informa eventual reinício e termina com OK.

As pastas de banco, entrada, saída, logs e configuração também podem usar compartilhamentos de rede. Informe o caminho UNC completo, por exemplo `\\servidor\compartilhamento\MockAiZe`; letras mapeadas não ficam disponíveis para serviços Windows. O serviço acessa SMB como a conta do computador (`DOMÍNIO\NOME-DO-PC$`), então ela precisa de permissões de leitura/escrita no compartilhamento e no NTFS. Compartilhamentos NAS que exigem credenciais próprias ainda não são compatíveis. Os binários continuam instalados localmente em Program Files.

## Usar no Bruno

Importe a pasta [`bruno/`](bruno/) como collection e selecione o ambiente `local`. O guia explica onde configurar a chave da API e o identificador da variação.

## Download e build

[Baixar o setup corrigido](https://github.com/devphpaulo/MockAiZe-API/actions/runs/40059677643/artifacts/12547241307): setup de 10.709.295 bytes e desinstalador de 2.156.324 bytes. [Actions aprovado](https://github.com/devphpaulo/MockAiZe-API/actions/runs/40059677643), commit `f0bff9c`.

No [workflow Windows](https://github.com/devphpaulo/MockAiZe-API/actions/workflows/build.yml), abra uma execução nativa concluída com sucesso e baixe o artefato **MockAiZe-API-Setup-Windows-x64**. Extraia o ZIP do Actions para obter os dois EXEs. Os artefatos ficam disponíveis por 30 dias.

O Actions testa Python 3.11/3.14, instala o pacote fora do checkout e compila a distribuição. Depois verifica arquitetura, ícones, composição, licenças e tamanho; testa o serviço compilado com HTTP/XML reais; e instala, configura, repara e desinstala o produto no runner Windows descartável. Falhas impedem o upload.

Para desenvolver, use Python 3.11 ou superior. Para compilar, instale também Inno Setup 6.7 ou superior:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[windows,packaging]'
.\.venv\Scripts\python -W error::ResourceWarning -m unittest discover -s tests -v
.\packaging\build.ps1 -Python .\.venv\Scripts\python.exe
```

O build usa o ICO aprovado já versionado. `release/` contém somente os dois EXEs; `build/` e `dist/` são intermediários. `.pkg` não é entregue. O planejamento `initial-api-docs/` permanece local e ignorado pelo Git.

Para desenvolvimento em primeiro plano, copie `packaging/config.example.json` para um JSON local e ajuste caminhos absolutos. Use `mockaize-api --config <caminho> --check`, `--create-key` e `--serve`. A chave é exibida apenas na criação; somente seu hash fica em `credentials.json`. No produto instalado, use o configurador nativo no menu Iniciar.
