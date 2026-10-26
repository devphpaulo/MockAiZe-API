# Execução da reformulação da API

Início: 26/10/2026. Branch: `staging`, criada de `main` atualizada em `d6f7b91`.
Autorização: pedido explícito do usuário para implementar `01_PLANO_API.md`, tarefa a tarefa.
Referência: pacote `tasks/refinamento/planos-api-site-reformulations`, lido integralmente.

## Baseline

- Alteração preexistente preservada: `bruno/Gerar - Retorno primeiro registro.bru` (seletor de XML local).
- Testes antes de editar: `python -m unittest discover -s tests -q`: 157 testes, OK, 1 ignorado.
- A execução restrita inicialmente apresentou falhas de acesso à pasta temporária e às operações Windows de proteção/publicação. A execução autorizada sem essa restrição passou; essas falhas não são regressões do produto.
- Nenhum serviço instalado, dado real, credencial, estado operacional ou arquivo do Site foi alterado.

## Tarefas

| Tarefa | Dependências | Responsável | Estado | Evidência |
|---|---|---|---|---|
| API-01 | Contrato autorizado | Oliver | Concluída | 168 testes OK, 1 ignorado; Dan sem achados bloqueantes; Luda APROVADO |
| API-02 | API-01 | Oliver | Concluída | 176 testes OK, 1 ignorado; Dan sem bloqueantes; Luda APROVADO |
| API-03 | API-01/02 | Ye | Concluída | 190 testes, 189 aprovados e 1 ignorado; ResourceWarning como erro; Dan sem bloqueantes; Luda APROVADO |
| API-04 | API-01..03 | Oliver | Concluída | 201 testes, 200 aprovados e 1 ignorado; Dan sem bloqueantes; Luda APROVADO |
| API-05 | API-01..04; Site para integração real | Ye | Adiada por orientação do usuário | Ver `Continuar após implementação do site.md` |
| API-06 | API-01..04; XML/OLD adiado pelo usuário | Ye | Em execução | Limpeza startup e replay; proteção do diretório reservado de presets |
| API-07 | API-01..06 | Oliver | Pendente | Configurador e instalador |
| API-08 | API-01..07 + SITE-05 | Oliver | Pendente | Documentação e compatibilidade |
| API-FV | API-08 + SITE-06 | Dan/Luda/Yorke | Pendente | Verificação final e integração |

As edições são sequenciais; o coordenador revisa diff e validação antes da próxima tarefa.
Integração real com o produtor Site e smoke nativo compilado precisam de evidência própria para serem declarados concluídos.

## API-02: limite operacional conhecido

Eventos de rejeição por lotação usam uma fila limitada e um único gravador auxiliar por servidor. A aceitação não espera o disco; fila cheia responde 503. Uma gravação de filesystem já iniciada não pode ser interrompida com segurança e pode permanecer no worker daemon até retornar, sem impedir o encerramento do servidor. O teste cobre log bloqueado, continuidade do atendimento, fila cheia e encerramento.

## Dependências do Site verificadas

Discovery somente leitura: Site na branch `staging`, commit `a3156fc`, sem alterações locais. SITE-01..05 ainda não existem nesse checkout: não há codec/store, corpus preset-v1, current/OLD, tombstones ou protocolo pending.

O contrato define o comportamento de journal/pending, mas ainda não especifica nomes, localização, schema físico dos arquivos/tabelas ou representação dos IDs afetados. A API não pode reconhecer com segurança uma sincronização em andamento inventando um protocolo diferente do produtor. O desenvolvimento do codec com fixtures é permitido pela API-05; a integração completa e seu gate dependem do produtor e desse formato compartilhado. Isso não bloqueia API-03/04.

Orientação posterior do usuário em 26/10/2026: manter a configuração/integração XML/OLD como pendência do Site, documentada em `Continuar após implementação do site.md`. Os recortes independentes das tarefas posteriores seguem sem anunciar XML-first ou integração conjunta concluídos. Essa orientação atualiza a dependência de execução do plano original somente para os recortes que não precisam do produtor.

## API-03: evidência e limites da validação

Os testes verificam política customizada/desabilitada com 1.000 registros, retorno mixed com 2.000 e validação da fonte completa antes de first. Um teste HTTP envia XML UTF-8 real de 4,4 MB em JSON com escaping acima de 12 MiB. Os tetos globais de saída foram removidos e testados por simulação direcionada de tamanho e inspeção, sem gerar arquivos reais acima de 100 MB. Parser seguro, profundidade e limites semânticos das fórmulas permanecem. A função legada de leitura de arquivo em `inputs.py` não integra mais o fluxo HTTP de retorno.
