# Estado da implementação Windows

Atualizado em 23/10/2026. Repositório público; planejamento interno fora do Git e preservado localmente. Nenhum arquivo do estúdio foi alterado.

| Cards | Entrega | Evidência / limite |
|---|---|---|
| COD-00/01 | Pacote/configuração/entrada/preflight | Testes de JSON, arquivos, permissões e porta; startup valida dependências |
| COD-02/03 | SQLite v2, snapshot/WAL, catálogo | Fixtures versionadas, exclusão de ancestrais, revisão concorrente e fonte somente leitura |
| COD-04–10 | Motor Python, 20 fórmulas, estrutura, Novo/Retorno | Testes de namespaces, atributos, segundo registro, 500 registros, ciclos/políticas/datas e composição |
| COD-11–13 / AD-01 | Publicação, HTTP, autenticação, estado/logs | HTTP real, hashes, entrada isolada, replay/conflito, falha parcial e logs sanitizados |
| COD-14/15/17–20 | SCM, assistente Qt, atualização/reparo/configuração/remoção | Testes Windows com driver simulado e renderização Qt; sem instalar no computador do usuário |
| COD-16 | Build Windows e setup único | Serviço/configurador construídos; setup bloqueado pelo Kaspersky |
| CT-01/02 / TES-01 | Cenários executáveis em tests | Suíte local integrada; CI ampliado pendente |
| TES-02 | Instalação elevada, boot, ACLs e rede | Pendente em VM; teste simulado não substitui essa evidência |
| DOC-01 | Guia de uso e evidências | Disponível; release estável ainda não aprovada |

## Decisões implementadas

Windows x64; assistente Qt Widgets nativo com tema preto/verde e serviço sem UI separado. Conta LocalService, credencial de alta entropia com hash fora do JSON, estado próprio v1, rede HTTP com origens configuráveis (LocalSubnet padrão), replay 24h e logs 30 dias. Padrões operacionais estão documentados e podem ser ajustados; não são apresentados como decisões anteriores do usuário.

Entrega em EXE: `MockAiZe-API-Setup.exe` e o desinstalador solicitado `MockAiZeApiUninstall.exe`, ambos com ícone do MockAíZé. `.pkg` é intermediário interno; pipeline de instalador manual enquanto a detecção estiver em análise. Planejamento interno não entra no pacote ou repositório.

Desinstalação atualizada: parada/exclusão do serviço confirmadas antes de perguntar sobre binários e pastas; nenhuma limpeza automática por padrão. Destinos são conferidos antes de excluir, com proteção do SQLite do estúdio e rejeição de links/junções. O fluxo termina com OK e avisa quando arquivos em uso exigirem reinício. O novo executável ainda precisa do build final e da homologação privilegiada em VM.

## Evidências

Python 3.14 no Windows: **120 testes executados, 119 aprovados e um ignorado** (a conta local não permite criar symlink). A rejeição de reparse points também tem um caso determinístico aprovado. A suíte usa avisos de recursos como erro, HTTP real, subprocessos de geração e janelas Qt com serviço/limpeza simulados. O CI Windows inclui dependências Qt/pywin32 em 3.11 e 3.14.

O teste do novo desinstalador encontrou uma falha no encaminhamento dos sinais entre threads; a interface agora recebe conclusão/erro através de slots QObject na thread principal. Casos aprovados cobrem tanto confirmação de remoção antes das perguntas e fechamento com OK quanto falha do serviço sem oferecer limpeza.

Smoke do serviço empacotado sem registrar SCM/firewall passou: saúde, catálogo, Novo com 500 registros inline/hash, dois arquivos apart e dois registros mixed. Novo levou cerca de 0,49 s em fixture simples, sem representar carga real. O binário inicial antecede correções finais e exige rebuild antes de distribuição.

Quatro etapas da janela Qt foram renderizadas e conferidas. Revisões independentes corrigiram: idempotência ativa expirando, cache permanente de 429, cliente lento bloqueando parada, vazamento de fórmulas em erros, namespaces no misto, status de limites e rollback de configuração/origens/registro Windows. Nove diretórios temporários de testes interrompidos foram conferidos e removidos.

## Bloqueio e liberação

Kaspersky informou HEUR:Trojan.Win32.Generic e excluiu MockAiZe-API-Setup.pkg durante o build. O setup final não ficou disponível; não há artefato aprovado. Não foi confirmado malware nem falso positivo. Nenhuma proteção foi desativada, exclusão criada ou amostra enviada a terceiros.

Para liberar: concluir análise da detecção; reconstruir código final e conferir licenças/hash/smoke; homologar em VM boot sem login, ACLs LocalService, rede autorizada, falsa confirmação de pausa, rollback/reparo/remoção; validar modelos reais e equivalência funcional do motor. Assinatura depende de certificado de distribuição. Estado atual: implementação em validação, não release estável concluída.
