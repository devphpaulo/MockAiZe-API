# Estado da implementação Windows

Atualizado em 23/10/2026. Repositório público; planejamento interno fora do Git e preservado localmente. Nenhum arquivo do estúdio foi alterado.

| Cards | Entrega | Evidência / limite |
|---|---|---|
| COD-00/01 | Pacote/configuração/entrada/preflight | Testes de JSON, arquivos, permissões e porta; startup valida dependências |
| COD-02/03 | SQLite v2, snapshot/WAL, catálogo | Fixtures versionadas, exclusão de ancestrais, revisão concorrente e fonte somente leitura |
| COD-04–10 | Motor Python, 20 fórmulas, estrutura, Novo/Retorno | Testes de namespaces, atributos, segundo registro, 500 registros, ciclos/políticas/datas e composição |
| COD-11–13 / AD-01 | Publicação, HTTP, autenticação, estado/logs | HTTP real, hashes, entrada isolada, replay/conflito, falha parcial e logs sanitizados |
| COD-14/15/17–20 | SCM, assistente Qt, atualização/reparo/configuração/remoção | Testes Windows com driver simulado e renderização Qt; sem instalar no computador do usuário |
| COD-16 | Build Windows, setup e desinstalador | Quatro EXEs verificados no Actions; dois EXEs publicados como artefato |
| CT-01/02 / TES-01 | Cenários executáveis em tests | 124 testes aprovados no CI Windows com Python 3.11/3.14 |
| TES-02 | Instalação elevada, boot, ACLs e rede | Pendente em VM; teste simulado não substitui essa evidência |
| DOC-01 | Guia de uso e evidências | Disponível; release estável ainda não aprovada |

## Decisões implementadas

Windows x64; assistente Qt Widgets nativo com tema preto/verde e serviço sem UI separado. Conta LocalService, credencial de alta entropia com hash fora do JSON, estado próprio v1, rede HTTP com origens configuráveis (LocalSubnet padrão), replay 24h e logs 30 dias. Padrões operacionais estão documentados e podem ser ajustados; não são apresentados como decisões anteriores do usuário.

Entrega em EXE: `MockAiZe-API-Setup.exe` e o desinstalador solicitado `MockAiZeApiUninstall.exe`, ambos com ícone do MockAíZé. `.pkg` é intermediário interno, removido após build bem-sucedido e nunca publicado. Pipeline automático em pushes/pull requests e acionamento manual; o artefato do Actions contém somente os dois EXEs e expira em 30 dias. Planejamento interno não entra no pacote ou repositório.

Desinstalação atualizada: parada/exclusão do serviço confirmadas antes de perguntar sobre binários e pastas; nenhuma limpeza automática por padrão. Destinos são conferidos antes de excluir, com proteção do SQLite do estúdio e rejeição de links/junções. O fluxo termina com OK e avisa quando arquivos em uso exigirem reinício. O executável foi compilado e verificado; a homologação privilegiada em VM permanece pendente.

## Evidências

Python 3.14 no Windows local: **124 testes executados, 123 aprovados e um ignorado** (a conta local não permite criar symlink). A rejeição de reparse points também tem um caso determinístico aprovado. A suíte usa avisos de recursos como erro, HTTP real, subprocessos de geração e janelas Qt com serviço/limpeza simulados. No [Actions 39901224467](https://github.com/devphpaulo/MockAiZe-API/actions/runs/39901224467), os 124 testes passaram em Python 3.11 e 3.14, incluindo Qt/pywin32 e verificação do pacote instalado fora do checkout.

O teste do novo desinstalador encontrou uma falha no encaminhamento dos sinais entre threads; a interface agora recebe conclusão/erro através de slots QObject na thread principal. Casos aprovados cobrem tanto confirmação de remoção antes das perguntas e fechamento com OK quanto falha do serviço sem oferecer limpeza.

Smoke do serviço recém-compilado sem registrar SCM/firewall passou localmente e no Actions: saúde, catálogo, Novo com 500 registros inline/hash, dois arquivos apart e dois registros mixed. Novo levou cerca de 0,50 s localmente e 0,78 s no runner em fixture simples, sem representar carga real.

O build verificou arquitetura x64, os frames do ícone original em cada PE, elevação dos três executáveis gráficos e a inclusão do runtime, dos executáveis, do ícone da janela e das licenças. O payload foi conferido para excluir planejamento, configuração, credenciais e SQLite. O [artefato de desenvolvimento](https://github.com/devphpaulo/MockAiZe-API/actions/runs/39901224467/artifacts/12478518212) contém setup (158.639.912 bytes) e desinstalador (48.966.938 bytes). SHA-256:

| Arquivo | SHA-256 |
|---|---|
| MockAiZe-API-Setup.exe | `9c40c0edb8360ce15f56cab3f69abe4b513c702944b1126484e295bc766fde4e` |
| MockAiZeApiUninstall.exe | `4a8d6743ca5c8c98aa766ae8e977dad6df530fbdf9cec49abb484c52556d2d90` |

Quatro etapas da janela Qt foram renderizadas e conferidas. Revisões independentes corrigiram: idempotência ativa expirando, cache permanente de 429, cliente lento bloqueando parada, vazamento de fórmulas em erros, namespaces no misto, status de limites e rollback de configuração/origens/registro Windows. Nove diretórios temporários de testes interrompidos foram conferidos e removidos.

## Bloqueio e liberação

A detecção também foi reportada para o EXE baixado do Actions. A [inspeção 39902707680](https://github.com/devphpaulo/MockAiZe-API/actions/runs/39902707680) confirmou o MD5 informado e o SHA-256 do build, os hashes dos executáveis internos e a ausência de assinatura Authenticode. Não há conclusão de falso positivo ou malware. A [análise detalhada](antivirus-analysis.md) explica a duplicação dos runtimes, a recomendação de instalador nativo com runtime compartilhado e as validações ainda necessárias. Essa migração ainda não foi implementada. A inspeção não executou os EXEs e o novo workflow publica somente relatórios JSON.

Kaspersky informou anteriormente HEUR:Trojan.Win32.Generic e excluiu MockAiZe-API-Setup.pkg durante o build. Na nova tentativa local solicitada, PyInstaller concluiu o setup, a validação recebeu acesso negado e depois o EXE deixou de existir. O build no runner do GitHub concluiu e publicou os dois EXEs. Isso não confirma malware nem falso positivo e não encerra a análise da detecção local. Nenhuma proteção foi desativada, exclusão criada ou amostra enviada a terceiros.

Para liberar uma versão estável: concluir análise da detecção; homologar em VM boot sem login, ACLs LocalService, rede autorizada, falsa confirmação de pausa, rollback/reparo/remoção; validar modelos reais e equivalência funcional do motor. Licenças/hash/smoke do build atual foram conferidos no CI. Assinatura depende de certificado de distribuição. Estado atual: implementação em validação, não release estável concluída.
