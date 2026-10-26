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
| API-03 | API-01/02 | Ye | Em execução | Entrada obrigatória e limites |
| API-04 | API-01..03 | Oliver | Pendente | Bearer e login |
| API-05 | API-01..04; Site para integração real | Ye | Pendente | Consumidor XML com fixtures permitido pelo plano |
| API-06 | API-01..05 | Ye | Pendente | Limpeza startup e replay |
| API-07 | API-01..06 | Oliver | Pendente | Configurador e instalador |
| API-08 | API-01..07 + SITE-05 | Oliver | Pendente | Documentação e compatibilidade |
| API-FV | API-08 + SITE-06 | Dan/Luda/Yorke | Pendente | Verificação final e integração |

As edições são sequenciais; o coordenador revisa diff e validação antes da próxima tarefa.
Integração real com o produtor Site e smoke nativo compilado precisam de evidência própria para serem declarados concluídos.

## API-02: limite operacional conhecido

Eventos de rejeição por lotação usam uma fila limitada e um único gravador auxiliar por servidor. A aceitação não espera o disco; fila cheia responde 503. Uma gravação de filesystem já iniciada não pode ser interrompida com segurança e pode permanecer no worker daemon até retornar, sem impedir o encerramento do servidor. O teste cobre log bloqueado, continuidade do atendimento, fila cheia e encerramento.
