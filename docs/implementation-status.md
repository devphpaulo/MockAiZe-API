# Implementação — primeira entrega

Data: 22/10/2026. Base: história v1, os dois protótipos e os quatro documentos em `initial-api-docs/docs/refino/`. O pedido de começar a implementação autoriza esta primeira entrega; as propostas ainda abertas permanecem pendentes.

## Recorte e critérios

Owner: agente principal, execução sequencial.

| Card | Entrega | Aceite desta etapa | Estado |
|---|---|---|---|
| COD-00 | Pacote `src`, entrypoints, dependências, README, testes, build e CI próprios | Testes passam e wheel instala fora do checkout | Implementado; pipeline remoto ainda depende de publicação |
| COD-01 | Parser fechado e verificação preliminar | Config inválida falha; banco ausente não é criado; porta ocupada falha; salvamento preserva original em erro | Parcial: infraestrutura de configuração pronta; integração ao startup do serviço pendente |
| COD-02 | Leitor de formato SQLite do estúdio | Snapshot/WAL, versão, exclusão lógica e fixtures versionadas | Próximo |

Nenhuma operação instala serviço, altera firewall ou muda o aplicativo visual. GitHub remoto criado privado como `devphpaulo/MockAiZe-API`. Repositório local e publicação inicial são tratados separadamente da criação remota.

## Decisões locais reversíveis

- Python >=3.11; testes com `unittest`; runtime inicial sem dependências externas.
- Build com Hatchling, distribuições Python preliminares e CI Windows. Não equivale ao build do instalador COD-16.
- Caminho da configuração explícito no CLI de desenvolvimento; pasta Documentos da conta de instalação será resolvida pelo futuro configurador.
- Preflight verifica acesso SQLite genérico. Não declara compatibilidade de schema nem estado HTTP saudável.
- Configuração comum não contém token. Geração, proteção, verificação por hash e rotação de credenciais pertencem à fronteira HTTP/configurador.

## Pendências preservadas do refino

Conta Windows e ACLs, origens autorizadas no firewall, escolha WPF versus Qt, retenção de logs/idempotência, contadores próprios, modelos reais para `mixed` e limites medidos. Nenhuma dessas decisões foi presumida implementada. AD-01 não foi iniciado.

## Validação

Testes cobrem JSON inválido/duplicado/grande, campos extras e segredo, tipos estritos, caminhos Unicode, coerência rede/host, troca atômica e falha de substituição; preflight com SQLite intacto, WAL ativo, banco/pasta ausentes, arquivo inválido, falta de permissão de escrita e porta ocupada; CLI com códigos de saída e diagnóstico seguro.

Execução local: Python 3.14 no Windows, 18 testes com avisos de recursos tratados como erro. Build isolado de sdist e wheel concluído. O CI inclui Python 3.11; essa versão não está instalada localmente. As primeiras execuções restritas encontraram bloqueio de acesso ao diretório temporário do sandbox; a validação local foi executada fora dessa restrição. Durante a implementação, os testes detectaram conexões SQLite não fechadas nas próprias fixtures, corrigidas com fechamento explícito.

Revisão desta etapa: sem achados bloqueantes no recorte; aprovação com risco restrita à base de desenvolvimento. Não constitui aprovação do serviço Windows, schema do estúdio, HTTP ou instalador. Verificação de build remoto e Python 3.11 permanece para o CI após o envio.
