# MockAiZe API no Bruno

Importe a pasta `bruno` no Bruno como uma collection e selecione o ambiente `local`.

Edite `environments/local.bru` no Bruno e preencha `apiKey` com a chave configurada na instalação. Em `fileId`, informe o identificador de uma variação retornado por **Catalog - Arquivos**. A URL padrão aponta para `http://127.0.0.1:6578`; altere `baseUrl` se a API estiver em outra máquina ou porta.

`Health` não exige chave. As outras requisições enviam `X-API-Key`. As duas requisições de geração criam arquivos no diretório de saída da API; verifique a configuração antes de executá-las.

Se quiser evitar a repetição de uma geração após uma falha de rede, a API aceita o cabeçalho opcional `Idempotency-Key`. Use uma chave nova para cada operação lógica.
