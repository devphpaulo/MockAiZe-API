# API HTTP v1

Porta padrão: 6578. Saúde fica na raiz; catálogo e geração usam `/api/v1` e exigem `X-API-Key`. A v1 usa HTTP; configure origens confiáveis no firewall ao permitir rede. Não há CORS ou interface web.

| Método | Rota | Entrada | Sucesso |
|---|---|---|---|
| GET | `/health` | Pública | `200 {status:"ok",version}`; indisponível dá 503 |
| GET | `/api/v1/files` | `q?`, `limit?` 1–200 (padrão 100), `cursor?` | `{items:[{id,name,libraryPath,revision}],nextCursor}` |
| GET | `/api/v1/files/{fileId}/modes` | Arquivo ativo | `{fileId,fileName,items:[{id,name,ready,missingRequirements}]}` |
| GET | `/api/v1/files/{fileId}/returns` | Arquivo ativo | `{fileId,fileName,items:[{id,name,ready}]}` |
| POST | `/api/v1/new` | JSON | Um XML inline ou manifesto |
| POST | `/api/v1/return` | JSON | XML único inline ou manifesto de arquivos |

`fileId` identifica a variação da biblioteca, não um caminho físico. Exclusão de ancestral impede acesso ao descendente. O catálogo independe do modo ativo/seleção da interface. Arquivos são ordenados por nome sem distinção de caixa e ID; cursor pertence ao mesmo filtro.

## Requisições de geração

Novo:

```json
{"fileId":"file-1","recordCount":3,"delivery":"inline","expectedRevision":7}
```

`recordCount` é inteiro de 1 a 500, sem booleano/decimal, e substitui a quantidade salva para esta chamada. `expectedRevision` opcional causa 409 se diferir do snapshot salvo.

Retorno:

```json
{"fileId":"file-1","returnSelection":{"type":"ids","ids":["ret-a","ret-b"]},"composition":"apart","delivery":"directory"}
```

Seleção aceita IDs distintos do arquivo, na ordem solicitada, ou `{"type":"all"}`, na ordem salva. Todos os selecionados devem estar completos. `apart` (padrão) gera um XML por modelo. `mixed` exige envelope, cabeçalhos e estruturas compatíveis e intercala A1,B1,A2,B2; incompatibilidade dá 422 antes de publicar.

Sem origem explícita, usa `inputByMode.return.xml`. Acrescente apenas um de `inputXml` ou `inputFilePath`. O segundo é um caminho absoluto `.xml` no computador do serviço, dentro de `inputDirectory`; caminho canônico e handle aberto são conferidos. Ele nunca escolhe a saída. Origem ausente difere de null/vazia, que são inválidos; duas origens são rejeitadas.

A entrada precisa manter tags/atributos por nome expandido, ordem dos filhos, envelope e estrutura de cada registro. Valores e quantidade de registros podem variar. Prefixos equivalentes, ordem lexical de atributos, comentários e formatação são ignorados. Não há XSD; DTD e entidades declaradas são recusados.

`delivery=directory` (padrão) publica apenas na pasta configurada e retorna manifesto. Inline exige exatamente um XML: Novo, um Retorno separado ou um misto. Vários `apart` com inline dão `422 DELIVERY_INCOMPATIBLE`. Nenhum ZIP é gerado.

## Resultados

Manifesto: `requestId`, `fileId`, `sourceRevision`, `operation`, `files[]`. Cada arquivo informa nome relativo, `sha256`, `sizeBytes`, `sizeDisplay`, `records`; retornos separados têm `returnId`/`returnName`. Retorno inclui `composition` e `returnIds`; misto inclui `recordsPerReturn` e `totalRecords`.

Inline usa `application/xml; charset=utf-8`, `Content-Disposition`, `X-Mockaize-SHA256`, `X-Mockaize-Size-Bytes` e `X-Mockaize-Size-Display`. SHA-256 hexadecimal minúsculo e tamanho cobrem os bytes UTF-8 finais. KB=1.000, MB=1.000.000, duas casas com arredondamento decimal HALF_UP. Colisões recebem sufixo e `collisionRenamed:true`, sem sobrescrita.

Respostas têm `Cache-Control:no-store` e `X-Request-ID`. Sucesso de geração é 200. Publicação múltipla usa staging/hard links e limpeza compensatória; falha residual dá `OUTPUT_PARTIAL_FAILURE`, com nomes no log para reconciliação. Use volume com hard links, como NTFS; falta desse recurso falha explicitamente.

Problemas usam `application/problem+json` com `type,title,status,detail,code,requestId`. Divergência estrutural pode incluir `xmlPath` e `reason`. Não são expostos SQL, chave, XML, valores de fórmulas ou caminhos físicos.

| HTTP | Códigos típicos |
|---|---|
| 400 | `INVALID_REQUEST` |
| 401 | `UNAUTHORIZED` |
| 404 | `FILE_NOT_FOUND`, `RETURN_NOT_FOUND`, `INPUT_FILE_NOT_FOUND`, `ROUTE_NOT_FOUND` |
| 405 | `METHOD_NOT_ALLOWED`, com Allow |
| 409 | `REVISION_MISMATCH`, `IDEMPOTENCY_CONFLICT`, `IDEMPOTENCY_IN_PROGRESS` |
| 413 | `INPUT_TOO_LARGE`, `OUTPUT_LIMIT_EXCEEDED` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 422 | `INPUT_XML_INVALID`, `INPUT_XML_STRUCTURE_MISMATCH`, `RETURN_INPUT_TEMPLATE_NOT_READY`, `RETURN_MODELS_INCOMPATIBLE`, `DELIVERY_INCOMPATIBLE`, `INPUT_FILE_PATH_FORBIDDEN`, `CONFIGURATION_INVALID` |
| 429 | `RATE_LIMITED`, Retry-After 1 |
| 500 | `INTERNAL_ERROR`, `OUTPUT_PARTIAL_FAILURE` |
| 503 | `DEPENDENCY_UNAVAILABLE`, `GENERATION_TIMEOUT`, `SERVICE_STOPPING` |

Limites: entrada 2.000.000 bytes/128 níveis XML; Novo/entrada Retorno até 500 registros; 20 modelos; saída total 100.000.000 bytes. Corpo HTTP até 12 MiB para escapes JSON. Campos desconhecidos/duplicados e valores JSON não finitos são rejeitados.

`policy.json` ao lado do config é opcional: `requests_per_second` (5), `generation_timeout_seconds` (60), `generation_concurrency` (2), `maximum_connections` (16), `idempotency_retention_seconds` (86400), `logs_retention_days` (30). Alterações exigem reinício. Esses limites não são promessa de capacidade. Geração em processo separado é encerrada no timeout/parada; conexões abertas são interrompidas no encerramento.

## Estado e observabilidade

`Idempotency-Key` opcional: mesma operação/chave/corpo repete o resultado; corpo diferente dá 409. Lotação antes da geração não consome chave. Concluídos expiram após 24h por padrão. Interrompidos ficam pendentes e bloqueiam repetição para evitar duplicação; exigem diagnóstico administrativo antes de outra chave.

Contador começa em zero por variação, independente do estúdio; tentativa falha pode consumir índice. `api-state.sqlite3` versão 1 contém `sequences(file_id,next_index)` e `replays(operation,key,fingerprint,created,status,headers,body)`, unicidade por operação/chave, índice de expiração e transações BEGIN IMMEDIATE. Só esse banco é criado pela API.

Logs JSON Lines UTF-8: `mockaize-api-logs-ddmmaaaa.txt`, timestamp local com offset, requestId, rota padronizada, status/duração e metadados dos resultados. Chave, XML e valores são omitidos. Falha de log fica visível na saúde. Retenção remove somente logs próprios expirados; XMLs gerados não têm exclusão automática.
