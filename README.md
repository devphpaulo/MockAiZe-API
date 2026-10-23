# MockAíZé API

API standalone em Python para consultar a biblioteca do MockAíZé e gerar XML com as configurações salvas pelo estúdio.

**Estado atual: em implementação, versão `0.1.0.dev0`.** Acompanhe os recursos disponíveis e as validações em `docs/implementation-status.md`.

## Desenvolvimento

Python 3.11 ou superior. O runtime desta primeira etapa usa somente a biblioteca padrão. Os comandos abaixo são para desenvolvedores; o produto final será instalado pelo assistente desktop.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\mockaize-api --version
```

Também é possível executar os testes sem instalar o pacote:

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

## Configuração e diagnóstico preliminar

Copie `packaging/config.example.json` para um `config.json` local e ajuste os caminhos absolutos para arquivos e pastas existentes. O exemplo usa acesso local e porta 6578. O futuro setup gravará a configuração em `Documentos\MockAíZé API`; por enquanto o caminho deve ser informado explicitamente, sem inferir o perfil da conta do serviço.

```powershell
.\.venv\Scripts\mockaize-api --config 'C:\caminho\config.json' --check
```

O comando verifica campos, tipos, caminhos absolutos, SQLite legível em modo read-only, acesso às pastas de entrada/saída/log e disponibilidade momentânea da porta. Faz uma pequena escrita temporária, removida ao fechar, nas pastas de saída e logs para verificar a permissão efetiva. Não cria pastas nem banco ausentes. Retorna zero com `preflight-passed` ou um com diagnóstico JSON seguro em stderr. Argumentos inválidos retornam dois.

Campos desconhecidos, duplicados, ausentes e chaves de API no JSON são rejeitados. Porta aceita somente inteiro de 1 a 65535. `host`/`firewallAccess` aceitam somente `127.0.0.1`/`N` ou `0.0.0.0`/`Y`. Saída e logs devem ter diretórios distintos. Leitura limitada a 64 KiB, UTF-8 com BOM opcional. A função de persistência prepara arquivo temporário no mesmo diretório e usa troca atômica; o futuro configurador deve chamar essa função apenas com o serviço parado.

Esse diagnóstico não valida ainda o schema do estúdio, não reserva a porta, não configura firewall e não comprova ACLs de outra conta Windows. A configuração será lida novamente no início do futuro serviço. Segredos, caminhos e valores recebidos não são ecoados nos erros.

## Independência e compatibilidade

O pacote não importa módulos, executa JavaScript ou usa scripts de build do aplicativo visual. A integração de runtime será exclusivamente por SQLite configurado, sem migração ou escrita no banco de origem.

| Fonte | Compatibilidade nesta etapa |
|---|---|
| SQLite sintético, inclusive WAL | Abertura preliminar somente leitura testada |
| Formato MockAíZé `staging` / `a3156fc` | Referência documental; leitor e fixtures versionadas pendentes no COD-02 |
| Outras versões do formato do estúdio | Sem suporte declarado |

## Build e integração contínua

```powershell
.\.venv\Scripts\python -m pip install build
.\.venv\Scripts\python -m build
```

O build produz wheel e distribuição de fontes em `dist/`, usando [o fluxo de empacotamento da PyPA](https://packaging.python.org/en/latest/tutorials/packaging-projects/). Esses são artefatos preliminares Python, não instaladores Windows. O workflow próprio testa em Windows com Python 3.11 e 3.14, constrói as distribuições e verifica a instalação do wheel em ambiente limpo. Não precisa de checkout do estúdio e não publica em PyPI nem cria release automaticamente.

Versões preliminares usam sufixo de desenvolvimento. A versão estável v1 depende da implementação, QA e validação Windows dos cards restantes; build/release do instalador ficará no COD-16.

## Próximas etapas

O progresso e as pendências estão em [docs/implementation-status.md](docs/implementation-status.md). Os documentos internos de planejamento são mantidos somente na cópia local.
