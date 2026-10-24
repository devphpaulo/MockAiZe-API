# Estado da implementação Windows

Atualizado em 24/10/2026. Repositório público; `initial-api-docs` permanece somente local e ignorado pelo Git.

## Distribuição atual

Instalador, configurador e desinstalador nativos em Inno Setup. O serviço HTTP/XML mantém um único runtime Python em `onedir`; Qt/PySide, Shiboken, Pythonwin e OpenSSL opcional foram removidos da distribuição. As cinco rotas funcionais e `/health` permanecem.

O setup local mede 10.627.232 bytes, contra 138.593.152 bytes da distribuição Qt anterior (redução de aproximadamente 92%). O desinstalador mede 2.156.292 bytes; o executável do serviço, 3.187.573 bytes. Esses números identificam o build local; o Actions registra seus próprios tamanhos e hashes.

| Entrega | Evidência / limite |
|---|---|
| Configuração, SQLite e catálogo | Validação, snapshots, concorrência e fonte somente leitura |
| Motor XML, Novo e Retorno | Fórmulas, namespaces, políticas, datas, composição e até 500 registros |
| HTTP, autenticação e publicação | HTTP real, hashes, replay/conflito, limites e logs sanitizados |
| Windows e manutenção | Serviço LocalService, ACLs, configuração, reparo, rollback e limpeza protegida |
| Distribuição | Dois EXEs publicados; ícones, arquitetura, licenças e único runtime conferidos |

## Validação

A suíte atual possui 145 testes. A execução local ignora o caso que exige permissão de criação de symlink; há também teste determinístico de rejeição de reparse points. O Actions executa a suíte em Windows com Python 3.11 e 3.14 e verifica a instalação do wheel fora do checkout.

O smoke do serviço compilado verifica saúde, catálogo, autenticação, geração de 500 registros, Retorno separado/misto e hashes. Não registra serviço na máquina do usuário.

O teste nativo roda exclusivamente em runner Windows descartável do GitHub e recusa serviço homônimo preexistente. Instala o produto real, gera XML como LocalService, altera porta e firewall pelo configurador, repara, desinstala e confirma a remoção do serviço e da regra de firewall. Confere dados preservados por padrão, limpeza explicitamente selecionada e SQLite de origem inalterado. O upload depende de todos os testes passarem.

A desinstalação confirma a remoção no SCM antes de perguntar sobre binários e pastas. Nenhuma limpeza é selecionada por padrão. Os destinos passam por conferência de allowlist, proteção do banco de origem e rejeição de links/junções. O fluxo termina com OK e informa reinício quando há binários em uso.

## Limites de liberação

Estado: `0.1.0.dev0`, em validação. O teste real no runner cobre o ciclo de vida acima, mas não comprova boot sem login em outra máquina, conectividade de outra estação, equivalência com todos os modelos reais ou aprovação pelo antivírus.

A detecção Kaspersky reportada se refere às amostras antigas documentadas na [análise do antivírus](antivirus-analysis.md). A migração foi implementada e medida; não há parecer do fabricante sobre os novos EXEs. Nenhuma proteção foi desativada ou exclusão criada. Assinatura Authenticode depende de certificado de publicador. A migração não permite classificar a detecção antiga como falso positivo.

## Build validado no Actions

[Execução 40057766206](https://github.com/devphpaulo/MockAiZe-API/actions/runs/40057766206), commit `c5679de21d06bc16caefc39a4fe0af3147b9dbf5`: todos os jobs aprovados, incluindo os 145 testes em Python 3.11/3.14, smoke da API compilada e ciclo nativo completo. A execução local final teve 144 aprovados e um ignorado em 10,4 segundos.

[Artefato com os dois EXEs](https://github.com/devphpaulo/MockAiZe-API/actions/runs/40057766206/artifacts/12546072062), disponível por 30 dias:

| Arquivo | Bytes | SHA-256 |
|---|---:|---|
| MockAiZe-API-Setup.exe | 10.675.694 | `145eb44d5663cf09ee422f079b1c8c246f5fcb5ab47874b6cfe7a29b8366c22d` |
| MockAiZeApiUninstall.exe | 2.156.292 | `ea0392abe662737499e110c4b2fe1ec219be8758ac6b369db98d5bc8eee917ea` |

O teste da API compilada gerou 500 registros em aproximadamente 0,6 segundo numa fixture simples, além de Retorno separado e misto. O ciclo nativo confirmou geração como LocalService, mudança real de porta/firewall, reparo, serviço e regra removidos, dados preservados por padrão, limpeza explícita e fonte inalterada. A verificação de firewall consulta uma nova instância COM após cada alteração para evitar uma coleção antiga no próprio teste.
