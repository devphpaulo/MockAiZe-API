# MockAíZé API para Windows

Serviço independente para consultar configurações salvas do MockAíZé e gerar XML. O estúdio pode ficar fechado. A API lê seu SQLite somente para consulta e mantém contadores e idempotência em uma base própria.

**Entrega Windows x64: `MockAiZe-API-Setup.exe` e `MockAiZeApiUninstall.exe`.** O assistente instala serviço, configurador e desinstalador em Program Files. Os executáveis usam o ícone do MockAíZé. Não é necessário instalar Python ou operar um terminal. `.pkg` é intermediário interno de build e nunca é entregue.

**Estado: implementação em validação, `0.1.0.dev0`.** O [build Windows do Actions](https://github.com/devphpaulo/MockAiZe-API/actions/runs/39901224467) passou e disponibilizou [setup e desinstalador](https://github.com/devphpaulo/MockAiZe-API/actions/runs/39901224467/artifacts/12478518212). Catálogo, motor XML, HTTP, estado, logs e ciclo de vida Windows têm testes automatizados; o serviço compilado passou no smoke local e no Actions. O setup local deixou de existir após a compilação, consistente com o bloqueio anterior do Kaspersky; a detecção ainda requer análise. O sucesso do CI não resolve essa detecção. Boot, ACLs e firewall precisam de homologação em VM antes da release estável.

## Recursos

- Saúde em `/health`; catálogo de arquivos, modos e modelos de retorno autenticado.
- Novo: um XML com 1 a 500 registros solicitados.
- Retorno: entrada salva, enviada ou arquivo autorizado; comparação estrutural antes da geração.
- `apart` gera arquivos separados; `mixed` intercala modelos compatíveis em um XML.
- Saída inline ou em diretório, sem sobrescrita; SHA-256 e tamanho exato.
- `X-API-Key`, Problem Details, limites operacionais, idempotência e logs sanitizados.
- Assistente Qt desktop; serviço automático separado; atualização com parada verificada e rollback. Desinstalador separado remove o serviço, pergunta sobre limpeza dos binários/pastas, mostra OK e fecha; preserva dados por padrão.

Documentação: [API](docs/api.md), [Windows](docs/windows-installation.md), [SQLite](docs/sqlite-format.md), [motor XML](docs/engine-compatibility.md), [evidências e pendências](docs/implementation-status.md).

## Desenvolvimento Windows

Python 3.11 ou superior. O CI testa Windows com Python 3.11 e 3.14. Dependências: tzdata para fusos, PySide6 Essentials para a janela e pywin32 para integração Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[windows,packaging]'
.\.venv\Scripts\python -W error::ResourceWarning -m unittest discover -s tests -v
```

Copie `packaging/config.example.json` para um `config.json` local e ajuste os caminhos absolutos para banco e pastas existentes. Para desenvolvimento em primeiro plano:

```powershell
.\.venv\Scripts\mockaize-api --config 'C:\caminho\config.json' --check
.\.venv\Scripts\mockaize-api --config 'C:\caminho\config.json' --create-key
.\.venv\Scripts\mockaize-api --config 'C:\caminho\config.json' --serve
```

Guarde a chave mostrada uma única vez; somente seu hash é persistido em `credentials.json`, fora do JSON comum e dos logs. `--rotate-key` invalida a chave anterior. `--check` verifica JSON, SQLite genérico, pastas e porta; o startup também verifica schema, credencial e estado. Nada abre navegador ou inicia o estúdio. `python -m mockaize_api.setup_ui --preview` mostra a janela sem instalar serviço.

## Build e entrega

```powershell
.\packaging\build.ps1 -Python .\.venv\Scripts\python.exe
```

Os executáveis finais ficam em `release/`; os hashes SHA-256 aparecem no resultado do build e no resumo do Actions. O build verifica arquitetura Windows x64, ícones, elevação, runtime, licenças e conteúdo do instalador antes de preparar a entrega. `build/` e `dist/` contêm intermediários. Arquivos `.pkg` conhecidos são removidos após sucesso, mas isso não evita uma detecção durante sua criação. Não desative o antivírus nem distribua resultado incompleto.

O [workflow Windows](https://github.com/devphpaulo/MockAiZe-API/actions/workflows/build.yml) executa automaticamente em pushes e pull requests, e também aceita acionamento manual. Primeiro testa Python 3.11/3.14 e a instalação do pacote fora do checkout; depois compila os quatro executáveis, confere seu conteúdo e exercita o serviço compilado com HTTP/XML reais. Somente após sucesso disponibiliza o artefato **MockAiZe-API-Setup-Windows-x64** por 30 dias. O download é um ZIP do Actions contendo apenas o setup e o desinstalador `.exe`; extraia antes de executar. Wheels e `.pkg` não são publicados.

O build e o runtime não dependem de checkout, módulos, JavaScript ou scripts do estúdio. A única integração operacional é o SQLite v2; formatos desconhecidos são rejeitados, nunca migrados. Planejamento interno permanece apenas na cópia local e fora do GitHub/pacote.
