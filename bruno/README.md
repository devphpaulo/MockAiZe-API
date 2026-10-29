# MockAiZe API no Bruno

Importe a pasta `bruno` no Bruno como uma collection e selecione o ambiente `local`.

Edite `environments/local.bru` no Bruno e preencha `apiKey` com a chave configurada na instalação. Em `fileId`, informe o identificador de uma variação retornado por **Catalog - Arquivos**. A URL padrão aponta para `http://127.0.0.1:6578`; altere `baseUrl` se a API estiver em outra máquina ou porta.

`Health` é público. As requisições existentes enviam `X-API-Key`. Para usar a alternativa Bearer, execute **Auth - Login** com a chave e JSON `{}`; a resposta preenche apenas a variável de execução `accessToken`, usada em **Catalog - Arquivos Bearer**. Ela não é gravada no ambiente e desaparece ao reiniciar o cliente Bruno. Não envie as duas credenciais juntas: isso retorna 400. O Bearer dura 1.800 segundos e é invalidado no reinício do serviço ou rotação da chave, sem refresh. Login sempre exige API key válida. Com autenticação opcional, ausência de credencial é aceita, mas uma credencial fornecida inválida/expirada retorna 401.

As rotas incluem o formato e o ID: `POST /api/v1/files/xml/{{fileId}}/new` e `POST /api/v1/files/xml/{{fileId}}/return`. Não envie `fileId` no corpo.

Os exemplos com `delivery: directory` gravam arquivos em Saídas, no servidor. Os exemplos com `delivery: content` devolvem JSON com `files[].fileName` e `files[].content`, contendo o XML completo, sem gravar. `inline` devolve o XML bruto e aceita somente um documento final.

No retorno, `inputXml` é obrigatório no body JSON. Substitua os exemplos por documentos compatíveis com a estrutura da configuração. `inputFilePath` é rejeitado e não existe substituição pela entrada salva. As regras de cópia/cálculos usam os valores recebidos; os outros geradores seguem a configuração salva. O exemplo de primeiro registro mantém o seletor de arquivo local já existente: ele lê no cliente e envia `inputXml`, sem enviar caminho de servidor.

`inputRecords: all` (padrão) usa todos os registros; `first` usa somente o primeiro, depois de validar a estrutura e limitar a fonte inteira. `returnSelection` escolhe modelos: `all` inclui todos os salvos e falha se algum não estiver pronto. `composition` define arquivos separados (`apart`) ou um XML intercalado (`mixed`). Com 10 registros e 2 modelos, apart produz 2 XMLs de 10 e mixed 1 XML de 20, sem novo teto agregado. Com first, são 2 XMLs de 1 ou 1 XML de 2.

Entrada XML e quantidade têm políticas default/custom/disabled, com padrões de 2.000.000 bytes UTF-8 e 500 registros. A medição ocorre após decodificar o JSON. Não há teto global de bytes de saída ou teto de 12 MiB no JSON de geração. Permanecem parser seguro, limites semânticos e operacionais.

A documentação completa e executável está em `http://127.0.0.1:6578/`, também disponível em `/swagger/`. O contrato para importação está em `/openapi.json`.

Use `Idempotency-Key` para repetir a mesma operação/chave/corpo sem nova geração. A chave tem escopo por operação (`new`/`return`); dentro da mesma operação, outro corpo ou fileId retorna 409. Replay directory de arquivo removido ou substituído retorna 410 `OUTPUT_EXPIRED`, sem regenerar/avançar contador; acesso indisponível retorna 503. Content/inline persistidos não dependem de arquivos em Saídas.

Erros novos são JSON com `error.code`, `error.message` e `error.traceId`, status numérico somente no HTTP e extensões públicas na raiz. O traceId corresponde ao header `X-Request-ID`; replay de erro conserva o identificador e corpo originais. A API lê o preset atual C-PRESET-1 por requisição e usa o SQLite em somente leitura quando o XML está ausente ou inacessível. XML inválido retorna `503 PRESET_INVALID`, sem fallback; OLD é ignorado e tombstone impede reexpor o ID.

O ambiente versionado contém apenas valores de exemplo e `apiKey` vazia. Preencha sua chave localmente e não a inclua em commits. Nunca persista `accessToken` no ambiente.
