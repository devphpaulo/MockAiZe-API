# MockAíZé API

![Tamanho do repositório](https://img.shields.io/github/repo-size/devphpaulo/MockAiZe-API?style=for-the-badge)
![Linguagens](https://img.shields.io/github/languages/count/devphpaulo/MockAiZe-API?style=for-the-badge)
![Último commit](https://img.shields.io/github/last-commit/devphpaulo/MockAiZe-API?style=for-the-badge)
![Build Windows](https://github.com/devphpaulo/MockAiZe-API/actions/workflows/build.yml/badge.svg)

<p align="center">
  <img src="src/mockaize_api/assets/mockaize-favicon.png" alt="Logo MockAíZé" width="128">
</p>

**MockAíZé API** é um serviço independente para consultar as configurações XML criadas no [MockAíZé](https://github.com/devphpaulo/MockAiZe) e gerar arquivos por requisições HTTP, **sem precisar manter o estúdio aberto**.

O MockAíZé continua responsável pela configuração visual dos arquivos, mapeamentos e fórmulas. A API prefere os presets XML locais do estúdio e usa o SQLite em **somente leitura** como fallback para variações sem preset acessível. Os controles de geração, contadores e idempotência ficam em uma base operacional separada.

> **Escopo atual:** catálogo e geração de **XML**. A API não substitui a interface do MockAíZé, não altera as configurações originais e ainda não implementa os motores de CSV, JSON ou CNAB.

## Por que usar

- **Reutilizar configurações:** prepare as regras uma vez no MockAíZé e execute novas gerações por HTTP.
- **Automatizar testes:** solicite novos registros e arquivos de retorno a partir de clientes HTTP, scripts e fluxos de QA.
- **Executar independentemente:** serviço Windows com inicialização automática, sem abrir o estúdio e sem instalar Python na máquina de destino.
- **Integrar com facilidade:** Swagger UI e OpenAPI locais, além de uma coleção pronta para o Bruno.
- **Controlar as entregas:** grave os XMLs no servidor, receba o conteúdo em JSON ou obtenha um XML diretamente na resposta.
- **Restringir o acesso:** API key ou Bearer temporário, autenticação configurável, limites operacionais, idempotência e logs sanitizados.

## Como funciona

O fluxo começa no **MockAíZé**, onde os arquivos e suas regras são preparados. Depois, a **MockAíZé API** usa essas configurações para atender às solicitações de geração.

1. **Configure no MockAíZé:** crie ou importe um XML, defina seus campos, fórmulas e, quando necessário, os modelos de retorno. Salve a variação.
2. **Instale e configure a API:** indique o banco SQLite do estúdio, a pasta local de presets e as pastas de trabalho. O banco pode ficar indisponível quando houver XML íntegro para atender à chamada.
3. **Consulte o catálogo:** localize a variação e copie seu `fileId`.
4. **Confira os modos:** verifique se a geração de novos registros ou os modelos de retorno estão prontos.
5. **Gere e consuma:** envie uma requisição HTTP e receba o XML no formato de entrega escolhido.

**Exemplo de uso:** depois de mapear um arquivo de retorno bancário no estúdio, uma automação pode enviar seu XML de entrada para a API e receber o retorno conforme as regras salvas, sem refazer o mapeamento.

## Requisitos

- **Instalador:** Windows x64, com permissão para instalar e configurar um serviço do Windows.
- **Uso da API:** presets XML C-PRESET-1 em uma pasta local, ou um banco SQLite compatível criado pelo [MockAíZé](https://github.com/devphpaulo/MockAiZe) como fallback.
- **Desenvolvimento:** Python 3.11 ou mais recente.
- **Build local do instalador:** Inno Setup 6.7 ou mais recente.

A distribuição usa **Inno Setup** e um runtime Python empacotado. Não depende de PySide/Qt, não exige Python instalado no destino e inclui Swagger UI local.

## Instalação no Windows

1. Acesse o [workflow de build](https://github.com/devphpaulo/MockAiZe-API/actions/workflows/build.yml).
2. Abra uma execução concluída com sucesso e baixe o artefato **MockAiZe-API-Setup-Windows-x64**.
3. Extraia o ZIP e execute `MockAiZe-API-Setup.exe`.
4. No assistente, configure o caminho do SQLite do MockAíZé, os diretórios de entrada/saída/logs e o acesso ao serviço. Por padrão, a API procura `Presets` ao lado do banco, que é a pasta padrão do Desktop.
5. Guarde a chave de API exibida na configuração; ela será necessária para as requisições autenticadas.

O pacote também contém `MockAiZeApiUninstall.exe`. O instalador registra o serviço **MockAíZé API** e disponibiliza o configurador `MockAiZeApiConfig.exe`. Para iniciá-lo ou pará-lo, abra **Serviços do Windows** (`services.msc`).

O artefato do Actions fica disponível por **30 dias** após cada execução. Prefira o build mais recente aprovado em vez de links para artefatos de execuções antigas.

### Abrir Swagger e testar a conexão

Com a configuração padrão, abra:

- **Swagger UI:** [http://127.0.0.1:6578/](http://127.0.0.1:6578/) (também em `/swagger/`).
- **Health:** [http://127.0.0.1:6578/health](http://127.0.0.1:6578/health).
- **OpenAPI:** [http://127.0.0.1:6578/openapi.json](http://127.0.0.1:6578/openapi.json) (também em `/swagger/v1/swagger.json`).

O Swagger funciona **sem internet**. Em **Authorize**, escolha uma alternativa: a chave de `X-API-Key` ou o Bearer obtido no login. No campo Bearer, cole somente o token, sem prefixo. Não autorize as duas alternativas simultaneamente: a API retorna 400. Health e documentação são públicos; catálogo e geração exigem credencial por padrão.

### Login por Bearer

Envie `POST /api/v1/auth/token` com `X-API-Key` válido, `Content-Type: application/json` e corpo `{}`. A resposta contém `access_token`, `token_type: "Bearer"` e `expires_in: 1800`. Use `Authorization: Bearer <token>` nas chamadas seguintes, como alternativa à API key.

O token é opaco, dura 30 minutos e fica em memória. Reiniciar o serviço ou rotacionar a chave invalida os tokens. Não há refresh, usuários ou senhas. A API key continua válida até sua rotação. O login sempre exige essa chave, inclusive com `authentication.required: false`; o corpo de login é limitado a 4 KiB.

Com autenticação opcional, chamadas sem credencial são aceitas, mas uma credencial fornecida inválida ou expirada retorna 401. Headers duplicados, malformados ou simultâneos são recusados com 400. Logs registram `LOGIN_SUCCESS` na emissão e `authenticated/authMethod` nas operações, sem credenciais ou identidade de pessoa.

## Recursos e rotas

| Método | Rota | O que faz |
| --- | --- | --- |
| GET | `/health` | Verifica a saúde do serviço. |
| POST | `/api/v1/auth/token` | Emite Bearer de 30 minutos mediante API key válida. |
| GET | `/api/v1/files/xml` | Lista variações XML, com filtro `q`, `limit` e paginação por `cursor`. |
| GET | `/api/v1/files/xml/{fileId}` | Consulta os metadados de uma variação. |
| GET | `/api/v1/files/xml/{fileId}/modes` | Verifica modos disponíveis e requisitos pendentes. |
| GET | `/api/v1/files/xml/{fileId}/returns` | Lista os modelos de retorno e seu estado de preparação. |
| POST | `/api/v1/files/xml/{fileId}/new` | Gera novos registros com quantidade positiva e limite configurável, **500 por padrão**. |
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
  "inputXml": "<Document><Record><Value>valor-1</Value></Record><Record><Value>valor-2</Value></Record></Document>",
  "returnSelection": {
    "type": "all"
  },
  "inputRecords": "all",
  "composition": "apart",
  "delivery": "content"
}
~~~

`inputXml` é obrigatório e deve ser uma string não vazia. Substitua o exemplo por XML compatível com sua variação. `inputFilePath` é rejeitado e a API não completa a requisição com a entrada salva. `new` continua rejeitando `inputXml` e outros campos de entrada de retorno.

O XML fornecido deve seguir a **estrutura configurada no estúdio**; os valores podem mudar. Regras de cópia e cálculos de entrada utilizam os valores recebidos, enquanto os demais geradores continuam usando as configurações salvas.

As opções são independentes:

- `inputRecords: "all"` usa todos os registros; `"first"` usa apenas o primeiro, depois de validar a estrutura e aplicar o limite de registros à **fonte inteira**.
- `returnSelection: {"type":"all"}` seleciona todos os modelos salvos e falha se algum não estiver pronto; `{"type":"ids","ids":[...]}` escolhe modelos específicos. Modelos não prontos não são descartados silenciosamente.
- `composition: "apart"` gera um XML por modelo; `"mixed"` intercala os registros em um XML, quando os modelos são compatíveis.

**Exemplo:** com 10 registros de entrada e 2 modelos selecionados, `apart` produz 2 XMLs com 10 registros cada; `mixed` produz 1 XML com 20 registros. Com `inputRecords: "first"`, o resultado usa apenas o primeiro registro de entrada para cada modelo.

### Escolher como receber o XML

| `delivery` | Resposta HTTP | Grava no servidor? |
| --- | --- | --- |
| `directory` (padrão) | JSON com arquivos e metadados | **Sim**, na pasta Saídas configurada. |
| `content` | JSON com `files[].fileName` e `files[].content` | Não. |
| `inline` | Um único XML diretamente no corpo HTTP | Não. Exige apenas um documento final. |

Os resultados incluem **SHA-256** e **tamanho em bytes**. Entrada XML e quantidade aceitam políticas `default/custom/disabled`, com padrões de **2.000.000 bytes UTF-8 decodificados** e **500 registros**. O escaping do JSON não conta como bytes do XML; não há teto oculto de 12 MiB no body de geração. Não há teto funcional global de bytes de saída. Continuam até **20 modelos**, parser seguro, limites semânticos de fórmulas, timeout, taxa e concorrência. `mixed` pode multiplicar a quantidade pelo número de modelos, sem novo teto agregado. A API não gera ZIP.

### Erros e compatibilidade de clientes

Erros novos usam `application/json; charset=utf-8`:

~~~json
{
  "error": {
    "code": "INPUT_XML_STRUCTURE_MISMATCH",
    "message": "A estrutura de entrada diverge do modelo salvo.",
    "traceId": "id-da-requisicao"
  },
  "xmlPath": "Document/Record",
  "reason": "namespace-divergente"
}
~~~

O status numérico existe somente no HTTP. `error` contém exatamente `code`, `message` e `traceId`; extensões públicas documentadas ficam na raiz. `traceId` corresponde ao `X-Request-ID` e ao log. `/health` conserva `status` textual `ok/unavailable` e `version`.

Esta reformulação muda intencionalmente dois contratos: retorno exige `inputXml` e os erros deixam o formato antigo. Atualize seus clientes. Na exceção de replay de erro já persistido, o corpo e o trace originais são preservados, inclusive se forem legados; o log correlaciona a tentativa atual sem alterar os bytes salvos.

## Integrar com o Bruno

A pasta [`bruno/`](bruno/) contém uma coleção com consultas ao catálogo, geração de novos registros e cenários de retorno.

Importe-a no Bruno, selecione o ambiente `local` e configure `apiKey`, `baseUrl` e `fileId`. Consulte o [guia da coleção](bruno/README.md) para exemplos de requisições e opções de entrega.

Para evitar repetir uma geração após falha de rede, use `Idempotency-Key`. Mesma operação, chave e corpo reaproveitam a resposta. A chave possui escopo por operação (`new` ou `return`): dentro da mesma operação, outro corpo ou `fileId` retorna 409. A mesma chave em outra operação possui registro separado.

Replay de entrega `directory` verifica existência, tamanho e hash da saída. Arquivo removido ou substituído retorna **410 `OUTPUT_EXPIRED`**, sem regenerar, avançar sequencial ou substituir o registro de replay. Falha temporária de acesso retorna 503. Respostas `content` e `inline` persistidas continuam disponíveis sem depender dos arquivos em Saídas.

## Configuração, dados e segurança

Por padrão, a API atende em `127.0.0.1:6578`, acessível somente na própria máquina. Para acesso pela rede, a configuração admite `0.0.0.0` com `firewallAccess: "Y"` e regras de firewall limitadas às origens escolhidas. **Não publique o serviço diretamente na internet:** ele não fornece TLS nativo.

O preset atual é lido e validado em cada chamada. A API ignora arquivos `OLD` e temporários, respeita tombstones e bloqueia leituras cobertas por journals publicados. XML válido é suficiente para listar, consultar e gerar mesmo se o SQLite estiver ausente. Se o XML atual estiver ausente ou inacessível, a API usa o SQLite compatível em **somente leitura**; XML inválido retorna `503 PRESET_INVALID`, sem esconder o problema com fallback. Nenhuma escrita é feita nos presets ou no banco do estúdio. Por padrão, `presetsDirectory` é `<databasePath.parent>/Presets`, igual ao diretório padrão do Desktop. Para outro caminho local, configure `presetsDirectory` no JSON do serviço e reaplique/reinicie a configuração; o configurador concede leitura ao serviço, sem escrita. Em UNC, a leitura depende das permissões do compartilhamento e do NTFS. A API mantém estado operacional, contadores, idempotência e credenciais separados; a chave é exibida somente ao criar ou rotacionar, e o arquivo de credenciais armazena apenas seu hash.

Os diretórios de banco, Entradas, Saídas e Logs podem apontar para caminhos locais ou **UNC** (`\\servidor\compartilhamento\MockAiZe`). No Windows, serviços não enxergam letras de unidades de rede mapeadas. Em compartilhamentos SMB, conceda permissões à conta do computador (`DOMÍNIO\NOME-DO-PC$`) no compartilhamento e no NTFS; NAS que exigem credenciais próprias não são compatíveis nesta versão.

O instalador também aceita pastas de trabalho em `Documentos` redirecionado pelo OneDrive. A configuração pode ser alterada pelo `MockAiZeApiConfig.exe`. Reparos e atualizações verificam a parada do serviço e incluem procedimento de rollback; a desinstalação **preserva os dados por padrão** e permite escolher o que remover.

### Políticas no JSON e no configurador

Os sete campos legados continuam válidos. O [exemplo completo](packaging/config.example.json) inclui as opções operacionais. Estes grupos opcionais usam a mesma validação no JSON, no instalador e no configurador:

~~~json
{
  "authentication": {"required": true},
  "limits": {
    "inputXml": {"mode": "default"},
    "records": {"mode": "custom", "count": 1000}
  },
  "cleanup": {
    "inputs": {"mode": "disabled"},
    "outputs": {"mode": "disabled"},
    "logs": {"mode": "age", "days": 30}
  }
}
~~~

Nos limites, `default` usa os padrões; `custom` exige `bytes` ou `count` inteiro positivo; `disabled` remove o respectivo limite. Não existe opção de teto de saída. Os demais controles de taxa, timeout, concorrência, conexões e retenção de idempotência continuam em `policy.json`. Quando `cleanup.logs` não está explícito, `logs_retention_days` legado fornece a retenção efetiva, com padrão de 30 dias; uma opção explícita prevalece.

Políticas são carregadas no startup. Pare o serviço pelo configurador e aplique as alterações; a ferramenta salva e reinicia de forma controlada. Paths existentes e campos novos são preservados em reparos. Se o rollback não conseguir restaurar JSON/configuração do serviço, ele permanece parado com diagnóstico de recuperação incompleta.

### Limpeza somente ao iniciar

Cada pasta admite `disabled` ou `age` com `days` inteiro >= 1. Entradas e Saídas vêm desativadas; Logs usa a retenção efetiva acima. Uma única rodada inicia em worker separado por execução do serviço, com retentativas canceláveis; não há agenda diária nem limpeza disparada ao gravar logs ou gerar arquivos.

O corte é congelado ao iniciar: remove quando a **data local de modificação** é estritamente anterior à data inicial menos N dias. Arquivos na data exata do corte são preservados. A rodada percorre arquivos regulares de qualquer origem/extensão e subpastas, sem remover diretórios nem seguir links, junções ou reparse points. Raízes sobrepostas, volume/perfil inteiro e caminhos que incluam configuração, credenciais, estado, bancos, binários ou o diretório reservado de presets são recusados.

Limpeza de Entradas exige opt-in e concede exclusão de arquivos ao serviço, sem escrita/criação; desativá-la revoga esse grant e preserva os direitos do usuário. A API não reconfigura permissões SMB remotamente. Arquivo bloqueado, rede ou permissão indisponível entra em retentativa da mesma rodada. A varredura não bloqueia chamadas normais; I/O já iniciado não pode ser interrompido à força e a espera no encerramento é limitada. Indisponibilidade de uma dependência utilizada pela própria requisição ainda pode afetar health/operações.

### Pendência do Site: XML/OLD

O consumidor C-PRESET-1 está implementado. A pasta configurada em `presetsDirectory` é consultada novamente a cada requisição, sem cache persistente. O arquivo atual é `<id>.mockaize.xml`; `<id>.OLD.mockaize.xml` é apenas backup e nunca é escolhido automaticamente. A ausência do atual permite fallback ao SQLite; tombstone inativo impede que o mesmo ID reapareça pelo banco. Durante sincronização, o journal publicado bloqueia a listagem e as variações afetadas. XML inválido ou journal inválido resulta em indisponibilidade explícita. O produtor do Desktop e o contrato de sincronização usam o mesmo C-PRESET-1, sem dependência de código compartilhado em runtime.

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
