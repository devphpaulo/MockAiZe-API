# MockAiZe API no Bruno

Importe a pasta `bruno` no Bruno como uma collection e selecione o ambiente `local`.

Edite `environments/local.bru` no Bruno e preencha `apiKey` com a chave configurada na instalação. Em `fileId`, informe o identificador de uma variação retornado por **Catalog - Arquivos**. A URL padrão aponta para `http://127.0.0.1:6578`; altere `baseUrl` se a API estiver em outra máquina ou porta.

`Health` não exige chave. As outras requisições enviam `X-API-Key`. As rotas agora incluem o formato e o ID: `POST /api/v1/files/xml/{{fileId}}/new` e `POST /api/v1/files/xml/{{fileId}}/return`. Não envie `fileId` no corpo.

Os exemplos com `delivery: directory` gravam arquivos em Saídas, no servidor. Os exemplos com `delivery: content` devolvem JSON com `files[].fileName` e `files[].content`, contendo o XML completo, sem gravar. `inline` devolve o XML bruto e aceita somente um documento final.

No retorno, envie seu XML em `inputXml` no body JSON. Substitua os XMLs ilustrativos dos exemplos por documentos compatíveis com a estrutura da configuração. Sem `inputXml` e sem `inputFilePath`, usa o modelo salvo no banco. As regras de cópia/cálculos usam os valores dessa entrada; os outros geradores seguem a configuração salva.

`inputRecords: all` (padrão) usa todos os registros da entrada; `first` usa somente o primeiro. `returnSelection` escolhe os modelos de retorno, enquanto `composition` define arquivos separados (`apart`) ou um XML intercalado (`mixed`). Com 10 registros e 2 modelos, apart produz 2 XMLs de 10 registros e mixed produz 1 XML de 20. Com first, são 2 XMLs de 1 registro ou 1 XML de 2, respectivamente.

A documentação completa e executável está em `http://127.0.0.1:6578/`, também disponível em `/swagger/`. O contrato para importação está em `/openapi.json`.

Se quiser evitar a repetição de uma geração após uma falha de rede, a API aceita o cabeçalho opcional `Idempotency-Key`. Use uma chave nova para cada operação lógica.
