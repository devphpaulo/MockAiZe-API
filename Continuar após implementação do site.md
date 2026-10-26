# Continuar após implementação do site:

Em 26/10/2026, o usuário pediu para manter a configuração e a integração XML/OLD como pendência do Site. A API continua usando o catálogo SQLite até a retomada deste trabalho. A existência de `presetsDirectory` na configuração não significa que o consumidor XML esteja implementado.

## Dependências a concluir no Site

- SITE-01: codec C-PRESET-1 e fixtures versionadas, com configuração completa, metadados, contexto de fuso e hash.
- SITE-02: produção recuperável de current/OLD e journal, sem anunciar sucesso antes da sincronização completa.
- SITE-03/04: atualizar presets em save, geração de artefato, rename/move/copy/delete, importação, backfill e restore; preservar visibilidade e tombstones.
- SITE-05: feedback de salvar e sincronização pendente coerente com a revisão conhecida.
- Fixar nomes, localização e schema dos journals/marcadores, incluindo a representação dos IDs afetados e o marcador de commit no banco. O contrato atual descreve seu comportamento, mas ainda não seu formato físico.

## Retomar na API

- API-05: consumidor XML-first autônomo, com snapshot por chamada e reload na próxima chamada.
- XML ausente/inacessível permite fallback SQLite; XML inválido retorna PRESET_INVALID/503, sem usar banco ou OLD para esconder o problema.
- Tombstones bloqueiam fallback; pending impede leitura parcial de um ID e visão parcial de uma operação em lote.
- Startup, health, catálogo e geração devem funcionar com XML íntegro mesmo sem banco disponível.
- Usar timeZone do contexto do preset e capturar o relógio uma única vez por geração, compartilhando entre modelos.
- Revisar configuração/instalador e permissões de leitura de presets com o produtor real; manter presets, OLD e journals fora da limpeza.
- Ajustar README, Swagger, Bruno e smoke somente quando o comportamento estiver implementado e validado.

## Validação conjunta obrigatória

1. Usar fixtures idênticas nos dois repositórios e comparar seus hashes.
2. Três salvamentos verificam current e OLD anterior; nova chamada usa a edição sem restart e geração iniciada mantém seu snapshot.
3. Geração de artefato e mudanças de metadados não rotacionam OLD.
4. Cobrir XML-only, DB-only, híbrido, fallback por ausência/inacessibilidade, erro por XML inválido, pending, tombstones e expectedRevision.
5. Exclusão e restore não ressuscitam IDs; XML íntegro funciona com DB indisponível.
6. Completar SITE-06/API-FV com evidência real do produtor e consumidor, sem declarar integração a partir apenas de fixtures próprias da API.

## Continuação das demais tarefas da API

Por orientação do usuário, a pendência XML/OLD não impede implementar e validar os recortes independentes de entrada/limites, autenticação, limpeza startup, replay expirado e ferramentas de configuração. A proteção do diretório reservado de presets continua obrigatória. A integração XML e a verificação conjunta permanecem pendentes, sem serem anunciadas como disponíveis.
