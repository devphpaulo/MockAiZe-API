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
| API-05 | API-01..04; SITE-01..04 | Ye | Concluída nesta retomada | Codec/fixtures compartilhados, XML-first/fallback, journals e integração Site/API em pasta descartável; detalhes abaixo |
| API-06 | API-01..04; XML/OLD adiado pelo usuário | Ye | Concluída no recorte independente | 223 testes, 222 aprovados e 1 ignorado; Dan sem bloqueantes; Luda APROVADO COM RISCO |
| API-07 | Tarefas API anteriores, exceto XML/OLD adiado | Oliver | Concluída no recorte independente | 238 testes, 237 aprovados e 1 ignorado; Config/Setup compilados; Dan sem bloqueantes; Luda APROVADO COM RISCO |
| API-08 | Tarefas API implementadas; integração Site adiada pelo usuário | Oliver | Concluída no recorte disponível | 243 testes, 242 aprovados e 1 ignorado; build/pacotes/smoke reais aprovados; Dan sem bloqueantes; Luda APROVADO COM RISCO |
| API-FV | API-08; SITE-06 para integração conjunta | Dan/Luda; smoke funcional | Cenário integrado local aprovado; gate visual do Site permanece parcial | Smoke sintético Site→API passou; runner DOM no browser não executado por bloqueio da política local |

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

## Fontes oficiais consultadas para API-06

Pesquisa Felicity, 26/10/2026, sobre exclusão/verificação por handle no Windows:

- [SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle): a disposição de exclusão exige acesso DELETE no handle.
- [FILE_DISPOSITION_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_disposition_info): estrutura com BOOLEAN e exclusão após fechamento; não abrir com DELETE_ON_CLOSE antes de validar.
- [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew): respeitar conflitos de compartilhamento e permissões, sem forçar exclusão.
- [GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew): conferir o destino final do handle; em SMB, falta de acesso a componentes pode impedir normalização. Essa falha deve preservar o arquivo e ser tratada como indisponibilidade/retentativa.

A consulta sustenta as chamadas de plataforma; somente testes executados sustentam a validação do produto.

## API-06: validação e riscos aceitos neste recorte

- Exclusão por handle, arquivo bloqueado, junções e troca de junção foram testados de fato no Windows, sempre em diretórios descartáveis. A sentinela externa permaneceu intacta.
- Corte estrito por data, recursão, retentativas, encerramento, atendimento durante scan bloqueado e replay sem avanço de contador estão cobertos.
- Expansão localizada de ownership: `config.py` e `test_config.py` receberam a proteção de perfis Windows registrados, independente da conta NetworkService. Valores de perfil vazios, relativos ou com variável não resolvida falham antes da exclusão.
- SMB real não verificado. Operações de filesystem já iniciadas não podem ser interrompidas à força; o worker é único e daemon, com espera limitada no encerramento. Esse risco não impede continuar a implementação, mas não equivale a validar rede/instalação nativa.
- Um reset Windows em resposta HTTP 405 foi observado em uma execução focada; não se reproduziu no teste dirigido ou nas suítes completas. A causalidade permanece inconclusiva, e o parser HTTP não foi alterado nesta tarefa.

## API-07: configuração nativa e permissões

Concluída em 27/10/2026. O assistente existente recebeu autenticação, limites e limpeza; campos de presets permanecem reservados no JSON, preservados e sem interface nesta etapa.

- INI plano e validado, compatível com pedidos antigos/parciais; retenção legada de 17 dias preservada em teste.
- Políticas são verificadas antes de alterar configuração, diretórios, permissões e serviço, incluindo proteção dos binários instalados e do helper em execução.
- Teste de ACL real somente em pasta temporária comprovou herança e remoção de DELETE nos arquivos existentes, preservando as permissões do usuário. A mudança de pasta e o rollback revogam o grant correspondente.
- A falha de revogação não impede restaurar a configuração anterior; falha ao restaurar JSON ou configuração do serviço impede o reinício e produz diagnóstico sanitizado. Não iniciar com uma configuração nova que deveria ter sido revertida.
- Config e Setup compilados pelo Inno. O runner de instalação/reparo/desinstalação foi atualizado, mas não executado nesta máquina. Instalação nativa completa e SMB continuam para ambiente descartável apropriado.

## API-08: documentação e validação final da API

Evidências de 27/10/2026:

- README, OpenAPI e coleção Bruno atualizados para o comportamento implementado: inputXml obrigatório, autenticação alternativa, erro aninhado, políticas configuráveis, limpeza startup e replay expirado. XML/OLD e sua configuração permanecem explicitamente pendentes do Site.
- Ambiente de exemplo Bruno sobrescrito com modelo sem credencial; nenhum valor anterior foi necessário para essa alteração. O request personalizado `Gerar - Retorno primeiro registro.bru` permaneceu byte a byte idêntico ao hash capturado antes da API-08 e fora dos commits da implementação.
- Suíte Python 3.14 com ResourceWarning como erro: 243 testes, 242 aprovados e 1 ignorado. O caso ignorado depende da permissão de criar symlink no teste legado de desinstalação; os testes reais de junction da limpeza foram executados.
- Cinco testes novos de contrato verificam referências locais do OpenAPI, autenticação, schemas, erros e exemplos executados no motor com dados sintéticos. Não foi utilizado validador OpenAPI externo.
- Build completo aprovado: serviço, Config, Setup e desinstalador; inventário de binários, arquitetura, ícones, recursos Swagger offline, licenças e limites de tamanho conferidos pelo verificador existente. Instalador gerado em `release/MockAiZe-API-Setup.exe`.
- Sdist e wheel gerados em ambiente isolado com as dependências declaradas. Wheel instalado em venv temporário fora do checkout, com CLI e importação do pacote aprovados.
- Smoke do executável real aprovado, sem instalar serviço: login Bearer/1800 segundos, 1.000 registros com política customizada, entrada acima do default com teto customizado de 3 MB, apart/mixed/content/inline, inputXml obrigatório, erro/trace, limpeza somente no startup com fronteira de data e inputs desativados, replay 410 sem avanço do sequencial e replay content preservado.

Logs locais: `build/api08-validation.txt`, `build/api08-build.txt`, `build/api08-package-build.txt`, `build/api08-wheel-install.txt` e `build/api08-frozen-smoke.txt`.

Limites remanescentes: somente Python 3.14 disponível localmente; Python 3.11 segue no workflow existente. Não executados nesta máquina: ciclo completo de instalação nativa/SCM, SMB real, interface Bruno, validador OpenAPI externo e integração com o Site. O build foi local; não houve publicação de release.

Parecer final independente: Dan SEM ACHADOS BLOQUEANTES; Luda APROVADO COM RISCO para API-08 e API-FV no recorte implementado. O parecer conferiu testes, build, pacotes e smoke; não executou testes adicionais. A integração conjunta continua registrada em `Continuar após implementação do site.md`.

## Retomada API-05 / API-FV — 28/10/2026

O usuário retomou a execução depois de SITE-01..05, pediu a branch da API `staging2` baseada na `staging` existente e dispensou Arrowverse/Arrowhead. A comparação registrada antes da edição confirmou `staging`, `origin/staging` e `staging2` no mesmo commit-base `68bed40f1bbf040cb375d71a65cd953fb4654d8d`. O arquivo Bruno de primeiro registro preexistente permaneceu preservado. Nenhum dado real, serviço instalado, release ou credencial foi usado.

### API-05 — implementação e decisões

- `preset_codec.py` e `preset_repository.py` foram implementados no próprio consumidor Python. Não existe dependência de runtime do repositório do Desktop. O codec valida envelope/versão, hash, ID/arquivo, fuso IANA, posições de fórmula, schema das propriedades dos 20 geradores e caminhos XML estruturais conforme o produtor. A comparação com `storage.validate_formula` do Site identificou e fechou uma lacuna inicial de validação de propriedades/caminhos; os testes cobrem propriedade desconhecida e caminho de cópia inválido.
- Os seis arquivos do corpus (`minimal` e `complete`: JSON, XML e SHA) foram comparados diretamente com `code/app/tests/fixtures/preset-v1`; todos são idênticos byte a byte. Os testes API também recalculam os hashes canônicos e conferem decode/encode exatos.
- O repositório lê current novamente por chamada, ignora OLD e snapshots temporários, bloqueia `.sync/<UUID>.pending.json`, rejeita ID/arquivo divergente e nunca repara nem escreve nos dados do Site. XML inválido é `503 PRESET_INVALID`; ausência/inacessibilidade usa DB somente leitura; tombstone não permite ressuscitar o mesmo ID por fallback. A listagem mantém ordenação e cursor existentes e mescla IDs com precedência por current.
- A revisão do journal real do Site revelou que um save pode listar current e OLD para o mesmo ID. O validador API inicialmente tratava essa dupla como duplicidade; foi corrigido para detectar duplicação do nome final completo, igual ao produtor, e coberto por fixture de journal current+OLD.
- Preflight/startup aceita a pasta XML íntegra mesmo com DB de catálogo ausente. Health, catálogo, metadados e geração XML-only foram exercitados pela API HTTP; o caso inválido mantém o health textual `unavailable` e devolve `PRESET_INVALID` na rota do catálogo. Atualizar current/revision fica visível na próxima chamada; `expectedRevision` rejeita a revisão anterior.
- `generate_new` e `generate_return` transportam o fuso do `Context` e capturam `referenceDateTime` uma vez por geração. Teste com dois modelos fixa um relógio sintético e prova o mesmo horário local/fuso nos resultados, sem nova opção HTTP.
- O diretório padrão de presets coincide com `<databasePath.parent>/Presets`; no Desktop atual isso coincide com `Documents/MockAíZé/Presets`. A permissão existente já cobre esse diretório-padrão junto do pai do DB. Um `presetsDirectory` local customizado agora recebe `RX` para `NetworkService` durante configuração, sem `M`; UNC continua dependente da ACL SMB do administrador, como as demais pastas de origem. Teste Windows direcionado valida a ACL emitida.

### API-FV — cenário Site→API

Foi executado um smoke integrado sem fixtures inventadas para o produtor: diretório `Documents` temporário, DB vazio criado pelo `storage.initialize` do Site, workspace/pasta/variação sintéticos e saves pelo `storage.save_variation`/`preset_store.run_operation` real. A API usou `Catalog` e `generate_new` reais sobre os arquivos publicados. Resultado: **PASS** nos casos seguintes:

1. Três saves publicados produziram a revisão atual e mantiveram em `OLD` a configuração imediatamente anterior.
2. A API leu e gerou o valor do terceiro save; após o quarto save, o snapshot já carregado ainda gerou a configuração anterior, e a chamada seguinte viu a nova revisão.
3. Save só de metadados/rename avançou a revisão sem alterar os bytes do OLD.
4. O current ausente caiu para a revisão do SQLite; o mesmo XML atual funcionou usando um caminho de DB inexistente.
5. Current inválido falhou com `PRESET_INVALID`; journal publicado após falha sintética bloqueou snapshot com `PRESET_SYNC_PENDING`; `recover()` do produtor convergiu e removeu a pendência.
6. Exclusão da árvore publicou tombstone; a listagem API omitiu a variação e a consulta por ID retornou `FILE_NOT_FOUND`, sem ressuscitar a linha ainda existente no DB.

O smoke foi executado com diretórios descartáveis; o primeiro script de verificação parou numa asserção escrita incorretamente sobre um valor que já era string. A asserção foi corrigida e a execução completa passou. Não permaneceu arquivo sintético no checkout.

### Validação e limites

- Suíte API final: `python -W error::ResourceWarning -m unittest discover -s tests -q` — **262 testes, 261 aprovados e 1 ignorado**, todos sem ResourceWarning. O caso ignorado preexistente depende de privilégio de symlink no teste de desinstalação. A suíte de `test_windows_ops.py` também foi executada isoladamente após a mudança de ACL: 28 testes PASS.
- O OpenAPI embarcado, README API e README Bruno foram atualizados para remover a alegação DB-only/“XML aguarda o Site”; o teste de documentação da suíte confirmou a superfície OpenAPI local.
- Não houve build/release nativo novo nesta retomada. A ACL foi verificada por chamada simulada do configurador e por teste de ACL já existente, não por instalação nova do serviço com diretório customizado. A integração smoke usou `Catalog` e motor reais, enquanto o fluxo HTTP XML-only foi coberto separadamente em teste HTTP; não se instalou nem reiniciou o serviço Windows.
- SITE-06/FV ainda não recebe gate visual completo: `parity_smoke.html` com `DOMParser`/`XMLSerializer` não foi aberto em browser, conforme o bloqueio local já documentado; `node --check` sozinho não substitui esse smoke. A continuação agora comprova consumidor e produtor em cenário sintético real, mas não reescreve nem executa o runner de browser.
- Não foi usado Arrowverse/Arrowhead nem validador OpenAPI externo. Não houve commit ou push nesta etapa.


## Revisão corretiva Desktop/API — 28/10/2026

Revisão direta dos diffs e módulos novos sem Arrowverse/Arrowhead ou agentes adicionais. Mantida a premissa de desktop local para equipe pequena. Correções do produtor, frontend e handlers HTTP estão detalhadas em code/docs/reformulation-execution.md no Desktop.

### Bugs corrigidos

1. Concorrência no fallback: um escritor podia publicar journal/commitar DB depois da checagem inicial. snapshot agora verifica novamente current e pendência após ler SQLite. Um current ou tombstone publicado durante a leitura resulta em PRESET_SYNC_PENDING para nova tentativa, impedindo retorno de linha do banco por cima de exclusão. Duas regressões simulam journal ainda pendente e tombstone já concluído durante a leitura.
2. Concorrência na listagem: a dupla coleta inicial de XML não cobria a consulta posterior do DB. verify_scan confirma fingerprint e disponibilidade após ler o fallback, incluindo journals pendentes. Uma publicação nesse intervalo gera PRESET_SYNC_PENDING; teste determinístico publica exclusão durante a composição.
3. Fuso fixo: o fallback forçava America/Fortaleza mesmo com outra preferência salva. Agora lê user_settings.timeZone na mesma transação do snapshot e valida com ZoneInfo. O padrão é preservado se preferência/tabela estiver ausente; preferência inválida gera indisponibilidade explícita. Regressão usa Asia/Tokyo.
4. libraryPath variava por origem: SQLite incluía o nome da variação e espaços entre barras, enquanto o produtor fornece apenas ancestrais e name separado. O fallback agora retorna Workspace/Examples conforme C-PRESET-1. A expectativa antiga do teste foi atualizada; muda o texto de apresentação para manter equivalência, sem mudar IDs.
5. Temporário Windows: o reconhecimento de .pending.json.tmp agora ignora caixa, alinhado ao produtor. A suíte Desktop revelou UUID/sufixo em maiúsculas num temporário não publicado. Regressão API confirma que esse arquivo incompleto não bloqueia e permanece intacto, pois o consumidor não escreve. Journals publicados continuam integralmente validados.

### Melhorias pontuais e decisões

Removido try/except que apenas relançava ApiError em pending. O conjunto de IDs do fallback é calculado uma vez por listagem, em vez de reconstruído para cada arquivo inacessível. As verificações de estabilidade pertencem a PresetRepository, sem acesso a seus métodos privados no Catalog. Codecs separados foram mantidos para preservar versões/empacotamento independentes, com fixtures compartilhadas como prova de compatibilidade. Sem cache persistente, novo framework ou pacote compartilhado.

### Validação final e limites

API: 267 testes, 266 PASS e 1 skip legado de symlink, com ResourceWarning tratado como erro. Desktop: 55 PASS. Testes Node de recuperação/retornos/datas/alerts PASS; sintaxe JavaScript PASS. Diff --check passou excluindo o arquivo Bruno preexistente, cujo hash Git continua fa05a33f58b8f9a270f185d9f6c82fb64c8ebbee.

O smoke visual DOM continua bloqueado pela política do navegador. Sem build/release ou instalação nativa do serviço nesta revisão. Branch staging2 preservada, sem commit/push e sem alteração do Bruno preexistente.
