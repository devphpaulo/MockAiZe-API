# MockAíZé API

![Tamanho do repositório](https://img.shields.io/github/repo-size/devphpaulo/MockAiZe-API?style=for-the-badge)
![Linguagens](https://img.shields.io/github/languages/count/devphpaulo/MockAiZe-API?style=for-the-badge)
![Último commit](https://img.shields.io/github/last-commit/devphpaulo/MockAiZe-API?style=for-the-badge)
![Build Windows](https://github.com/devphpaulo/MockAiZe-API/actions/workflows/build.yml/badge.svg)

<p align="center">
  <img src="src/mockaize_api/assets/mockaize-favicon.png" alt="Logo MockAíZé" width="128">
</p>

**MockAíZé API** é um serviço independente para consultar as configurações XML criadas no [MockAíZé](https://github.com/devphpaulo/MockAiZe) e gerar arquivos por requisições HTTP, **sem precisar manter o estúdio aberto**.

O MockAíZé continua responsável pela configuração visual dos arquivos, mapeamentos e fórmulas. A API reutiliza essas regras por meio de uma leitura **somente leitura** do SQLite do estúdio e mantém seus próprios controles de geração, contadores e idempotência em uma base separada.

> **Escopo atual:** catálogo e geração de **XML**. A API não substitui a interface do MockAíZé, não altera as configurações originais e ainda não implementa os motores de CSV, JSON ou CNAB.

## Por que usar

- **Reutilizar configurações:** prepare as regras uma vez no MockAíZé e execute novas gerações por HTTP.
- **Automatizar testes:** solicite novos registros e arquivos de retorno a partir de clientes HTTP, scripts e fluxos de QA.
- **Executar independentemente:** serviço Windows com inicialização automática, sem abrir o estúdio e sem instalar Python na máquina de destino.
- **Integrar com facilidade:** Swagger UI e OpenAPI locais, além de uma coleção pronta para o Bruno.
- **Controlar as entregas:** grave os XMLs no servidor, receba o conteúdo em JSON ou obtenha um XML diretamente na resposta.
- **Restringir o acesso:** chave de API, limites operacionais, idempotência, logs sanitizados e configuração de rede.

## Como funciona

O fluxo começa no **MockAíZé**, onde os arquivos e suas regras são preparados. Depois, a **MockAíZé API** usa essas configurações para atender às solicitações de geração.

1. **Configure no MockAíZé:** crie ou importe um XML, defina seus campos, fórmulas e, quando necessário, os modelos de retorno. Salve a variação.
2. **Instale e configure a API:** indique o banco SQLite do estúdio, as pastas de trabalho e a chave de acesso.
3. **Consulte o catálogo:** localize a variação e copie seu `fileId`.
4. **Confira os modos:** verifique se a geração de novos registros ou os modelos de retorno estão prontos.
5. **Gere e consuma:** envie uma requisição HTTP e receba o XML no formato de entrega escolhido.

**Exemplo de uso:** depois de mapear um arquivo de retorno bancário no estúdio, uma automação pode enviar seu XML de entrada para a API e receber o retorno conforme as regras salvas, sem refazer o mapeamento.

## Requisitos

- **Instalador:** Windows x64, com permissão para instalar e configurar um serviço do Windows.
- **Uso da API:** um banco SQLite compatível, criado pelo [MockAíZé](https://github.com/devphpaulo/MockAiZe), com variações XML configuradas.
- **Desenvolvimento:** Python 3.11 ou mais recente.
- **Build local do instalador:** Inno Setup 6.7 ou mais recente.

A distribuição usa **Inno Setup** e um runtime Python empacotado. Não depende de PySide/Qt, não exige Python instalado no destino e inclui Swagger UI local.

## Instalação no Windows

1. Acesse o [workflow de build](https://github.com/devphpaulo/MockAiZe-API/actions/workflows/build.yml).
2. Abra uma execução concluída com sucesso e baixe o artefato **MockAiZe-API-Setup-Windows-x64**.
3. Extraia o ZIP e execute `MockAiZe-API-Setup.exe`.
4. No assistente, configure o caminho do SQLite do MockAíZé, os diretórios de entrada/saída/logs e o acesso ao serviço.
5. Guarde a chave de API exibida na configuração; ela será necessária para as requisições autenticadas.

O pacote também contém `MockAiZeApiUninstall.exe`. O instalador registra o serviço **MockAíZé API** e disponibiliza o configurador `MockAiZeApiConfig.exe`. Para iniciá-lo ou pará-lo, abra **Serviços do Windows** (`services.msc`).

O artefato do Actions fica disponível por **30 dias** após cada execução. Prefira o build mais recente aprovado em vez de links para artefatos de execuções antigas.

### Abrir Swagger e testar a conexão

Com a configuração padrão, abra:

- **Swagger UI:** [http://127.0.0.1:6578/](http://127.0.0.1:6578/) (também em `/swagger/`).
- **Health:** [http://127.0.0.1:6578/health](http://127.0.0.1:6578/health).
- **OpenAPI:** [http://127.0.0.1:6578/openapi.json](http://127.0.0.1:6578/openapi.json) (também em `/swagger/v1/swagger.json`).

O Swagger funciona **sem internet**. Clique em **Authorize** e informe a chave de `X-API-Key`. A operação `GET /health` dispensa autenticação; as rotas de catálogo e geração exigem a chave.

## Recursos e rotas

| Método | Rota | O que faz |
| --- | --- | --- |
| GET | `/health` | Verifica a saúde do serviço. |
| GET | `/api/v1/files/xml` | Lista variações XML, com filtro `q`, `limit` e paginação por `cursor`. |
| GET | `/api/v1/files/xml/{fileId}` | Consulta os metadados de uma variação. |
| GET | `/api/v1/files/xml/{fileId}/modes` | Verifica modos disponíveis e requisitos pendentes. |
| GET | `/api/v1/files/xml/{fileId}/returns` | Lista os modelos de retorno e seu estado de preparação. |
| POST | `/api/v1/files/xml/{fileId}/new` | Gera de **1 a 500 novos registros** usando as regras salvas. |
| POST | `/api/v1/files/xml/{fileId}/return` | Gera um ou mais retornos XML usando os modelos configurados. |

O `fileId` vem do catálogo e deve ser informado **somente na URL**, nunca no corpo das requisições. Nas versões anteriores à série 0.2, as rotas não usavam `/files/xml`; essas rotas antigas foram removidas.

### Gerar novos registros

Use `POST /api/v1/files/xml/{fileId}/new`, com `Content-Type: application/json` e `X-API-Key`:

~~~json
{
  "recordCount": 100,
  "delivery": "content"
}
~~~

A API aplica as regras de geração da variação selecionada e devolve o resultado conforme `delivery`. Neste exemplo, o XML completo aparece em `files[].content` no JSON, sem gravar arquivos em Saídas.

### Gerar arquivos de retorno

Use `POST /api/v1/files/xml/{fileId}/return`:

~~~json
{
  "returnSelection": {
    "type": "all"
  },
  "inputRecords": "all",
  "composition": "apart",
  "delivery": "content"
}
~~~

Sem `inputXml` e sem `inputFilePath`, a API utiliza o XML de exemplo salvo na configuração. Você também pode enviar seu próprio XML em `inputXml`, ou indicar em `inputFilePath` um arquivo dentro da pasta **Entradas** autorizada. Essas duas opções são mutuamente exclusivas.

O XML fornecido deve seguir a **estrutura configurada no estúdio**; os valores podem mudar. Regras de cópia e cálculos de entrada utilizam os valores recebidos, enquanto os demais geradores continuam usando as configurações salvas.

As opções são independentes:

- `inputRecords: "all"` usa todos os registros de entrada; `"first"` usa apenas o primeiro.
- `returnSelection: {"type":"all"}` seleciona todos os modelos prontos; `{"type":"ids","ids":[...]}` permite escolher modelos específicos.
- `composition: "apart"` gera um XML por modelo; `"mixed"` intercala os registros em um XML, quando os modelos são compatíveis.

**Exemplo:** com 10 registros de entrada e 2 modelos selecionados, `apart` produz 2 XMLs com 10 registros cada; `mixed` produz 1 XML com 20 registros. Com `inputRecords: "first"`, o resultado usa apenas o primeiro registro de entrada para cada modelo.

### Escolher como receber o XML

| `delivery` | Resposta HTTP | Grava no servidor? |
| --- | --- | --- |
| `directory` (padrão) | JSON com arquivos e metadados | **Sim**, na pasta Saídas configurada. |
| `content` | JSON com `files[].fileName` e `files[].content` | Não. |
| `inline` | Um único XML diretamente no corpo HTTP | Não. Exige apenas um documento final. |

Os resultados incluem metadados como **SHA-256** e **tamanho em bytes**. Os limites incluem entrada XML de até **2 MB**, saída de até **100 MB** e até **20 modelos de retorno** selecionados. A API não gera ZIP de XMLs.

## Integrar com o Bruno

A pasta [`bruno/`](bruno/) contém uma coleção com consultas ao catálogo, geração de novos registros e cenários de retorno.

Importe-a no Bruno, selecione o ambiente `local` e configure `apiKey`, `baseUrl` e `fileId`. Consulte o [guia da coleção](bruno/README.md) para exemplos de requisições e opções de entrega.

Para evitar repetir uma geração após uma falha de rede, use opcionalmente o cabeçalho `Idempotency-Key`. Repetir a mesma operação com a mesma chave reaproveita a resposta; reutilizá-la com outra operação provoca conflito.

## Configuração, dados e segurança

Por padrão, a API atende em `127.0.0.1:6578`, acessível somente na própria máquina. Para acesso pela rede, a configuração admite `0.0.0.0` com `firewallAccess: "Y"` e regras de firewall limitadas às origens escolhidas. **Não publique o serviço diretamente na internet:** ele não fornece TLS nativo.

O SQLite do MockAíZé é aberto em **somente leitura**, sem alterar as variações. A API mantém estado operacional, contadores, idempotência e credenciais separados; a chave é exibida somente ao criar ou rotacionar, e o arquivo de credenciais armazena apenas seu hash.

Os diretórios de banco, Entradas, Saídas e Logs podem apontar para caminhos locais ou **UNC** (`\\servidor\compartilhamento\MockAiZe`). No Windows, serviços não enxergam letras de unidades de rede mapeadas. Em compartilhamentos SMB, conceda permissões à conta do computador (`DOMÍNIO\NOME-DO-PC$`) no compartilhamento e no NTFS; NAS que exigem credenciais próprias não são compatíveis nesta versão.

O instalador também aceita pastas de trabalho em `Documentos` redirecionado pelo OneDrive. A configuração pode ser alterada pelo `MockAiZeApiConfig.exe`. Reparos e atualizações verificam a parada do serviço e incluem procedimento de rollback; a desinstalação **preserva os dados por padrão** e permite escolher o que remover.

## Desenvolvimento e testes

Clone o repositório, crie o ambiente e execute os testes:

~~~powershell
git clone https://github.com/devphpaulo/MockAiZe-API.git
cd MockAiZe-API

py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[windows,packaging]'
.\.venv\Scripts\python.exe -W error::ResourceWarning -m unittest discover -s tests -v
~~~

Para executar a API em primeiro plano, copie [`packaging/config.example.json`](packaging/config.example.json) para um arquivo de configuração local, ajuste os **caminhos absolutos** e execute:

~~~powershell
.\.venv\Scripts\mockaize-api.exe --config .\config.local.json --check
.\.venv\Scripts\mockaize-api.exe --config .\config.local.json --create-key
.\.venv\Scripts\mockaize-api.exe --config .\config.local.json --serve
~~~

Para substituir uma chave existente, use `--rotate-key` em vez de `--create-key`. O comando de desenvolvimento **não instala nem registra** um serviço do Windows.

### Build do instalador

~~~powershell
.\packaging\build.ps1 -Python .\.venv\Scripts\python.exe
~~~

O build produz `release/MockAiZe-API-Setup.exe` e `release/MockAiZeApiUninstall.exe`. As pastas `build/` e `dist/` são intermediárias. O [workflow Windows](.github/workflows/build.yml) testa Python 3.11 e 3.14, valida o pacote instalado, verifica os binários e exercita a instalação, o serviço, o reparo e a remoção em um runner descartável.

## Estrutura do projeto

- `src/mockaize_api/` — servidor HTTP, catálogo, regras XML, segurança, configuração e serviço Windows.
- `src/mockaize_api/assets/swagger/` — OpenAPI e Swagger UI empacotados para uso offline.
- `bruno/` — coleção de requisições e ambiente local.
- `packaging/` — scripts de build, empacotamento, instalador e verificações.
- `tests/` — testes automatizados dos contratos e operações.
- `.github/workflows/` — build e inspeção dos artefatos.

## Contribuição

Contribuições são bem-vindas. Abra uma issue descrevendo a necessidade ou envie um pull request com escopo definido e testes. Mudanças no contrato HTTP devem considerar o OpenAPI, a coleção Bruno e a compatibilidade com as configurações do MockAíZé.

## Autor

**Paulo Henrique** — [@devphpaulo](https://github.com/devphpaulo)

## Avisos de terceiros

As licenças e os avisos dos componentes distribuídos estão em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). A licença do projeto principal está documentada no [repositório MockAíZé](https://github.com/devphpaulo/MockAiZe).
