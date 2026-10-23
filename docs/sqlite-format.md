# Compatibilidade com o SQLite do estúdio

O adaptador suporta o formato **2**: `app_meta.schema_version=2` e
`schema_meta.version=2`. Os dois marcadores e as colunas consumidas de
`library_nodes`, `variations`, `app_meta` e `schema_meta` são obrigatórios.
Versões desconhecidas, formato incompleto, banco inacessível e configuração
ilegível retornam `503 DEPENDENCY_UNAVAILABLE`, sem detalhes de SQL ou caminhos.
O serviço nunca inicializa nem migra o banco do estúdio.

Cada consulta abre uma conexão SQLite por URI com `mode=ro`, habilita
`query_only` e usa uma transação de leitura. A configuração, revisão, índice,
nome e caminho vêm do mesmo snapshot. Alterações já confirmadas no WAL ficam
visíveis na próxima consulta. A conta do serviço precisa conseguir ler o banco
e seus arquivos auxiliares de WAL; não use uma cópia isolada do arquivo principal
enquanto o estúdio estiver gravando.

O ID público é `variations.id`. Nome, localização e exclusão vêm de
`library_nodes`; um ancestral excluído, ausente ou cíclico oculta o arquivo.
`libraryPath` é o caminho de nomes desde o workspace até o arquivo, separados
por ` / `, sem caminhos do sistema de arquivos.

`new` usa exclusivamente `inputByMode.new`; `return` usa
`inputByMode.return` e os modelos de `returnModels` na ordem salva (máximo 20).
O indicador de prontidão exige XML seguro e bem formado e um grupo de registro
existente com elementos filhos. Os caminhos de grupo são arrays JSON de
`{ns,name,index}`, conforme o formato persistido; nomes expandidos distinguem
namespaces. Seleção de modelos e modo ativo da interface são ignorados.
A geração executa suas próprias validações de regras, estruturas e limites.

A listagem filtra nomes com `casefold`, ordena por nome normalizado e ID e usa
cursor opaco vinculado ao filtro. Limite padrão: 100; máximo: 200. A paginação
reflete o catálogo salvo a cada chamada, sem manter uma transação entre páginas.

Os testes usam somente fixtures sintéticas, sem dependência do checkout ou do
runtime do aplicativo visual. Cobrem WAL, consistência de snapshot, ausência de
escrita, exclusão de ancestrais, versões e colunas, paginação e prontidão.
