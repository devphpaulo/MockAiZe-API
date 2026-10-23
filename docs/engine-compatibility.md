# Compatibilidade do motor Python

O serviço interpreta a configuração persistida do estúdio diretamente em Python. Não carrega JavaScript nem executa expressões, scripts ou `eval`. O contrato de referência é o motor `app/mockaize/web/engine.js`, a normalização de configuração em `app/mockaize/storage.py` e a seleção de modelos em `app/mockaize/web/return-models.js` do estúdio.

## Documentos e configuração

`inputByMode.new` e `inputByMode.return` fornecem `xml` e `group` próprios de cada operação. Novo aplica `rulesByMode.new`, `presenceByMode.new`, `headersByMode.new` e `filenameByMode.new`. Cada retorno aplica seu próprio `outputXml`, `outputGroup`, `rules`, `presence`, `headers` e `filename`. A cópia em memória da revisão consultada é usada durante toda a geração.

Caminhos são arrays JSON de segmentos `{ns, name, index}`; atributos encerram o caminho com `{ns, name, attribute: true}`. Nomes expandidos usam URI do namespace e nome local, não o prefixo escrito no XML. Índices começam em 1 e contam somente irmãos do mesmo nome expandido. Declarações `xmlns` não são campos de dados.

O motor preserva atributos, namespaces, comentários, conteúdo misto e CDATA. Um valor que contém `]]>` substitui CDATA por texto XML escapado. A saída inclui declaração UTF-8 e termina com nova linha. A indentação original é preservada; a formatação visual não precisa coincidir byte a byte com o serializador do navegador. Hashes e tamanhos devem sempre ser calculados sobre os bytes finais entregues.

Novo replica a primeira unidade de registro na quantidade solicitada (1 a 500), mantendo o envelope. Se a própria raiz for a unidade e houver vários registros, usa o envelope `MockRegistros`, como o estúdio. O contador persistido de nomes é contexto de fórmula `fileIndex`, separado da quantidade solicitada.

## Fórmulas

Todos os 20 tipos aceitos pelo estúdio estão implementados:

| Tipo | Comportamento |
| --- | --- |
| `literal` | Texto constante. |
| `copy` | Campo de entrada do registro correspondente. |
| `field` | Campo de entrada ou saída; dependências de saída são avaliadas sob demanda. |
| `groupSum` | Soma decimal por grupo, por registro ou sobre todos os registros. |
| `config` | Nome da configuração sem espaços. |
| `count` | Quantidade dos registros da geração individual. |
| `cpf` | CPF com dígitos verificadores, com ou sem máscara. |
| `cnpj` | CNPJ numérico ou alfanumérico, estabelecimento e máscara. |
| `list` | Item fixo por índice ou item aleatório; 1 a 1.000 itens. |
| `hash` | Caracteres hexadecimais minúsculos/maiúsculos ou alfanuméricos. |
| `person` | Nome, primeiro nome, sobrenome e e-mail coerentes por perfil. |
| `company` | Razão social, nome fantasia e e-mail coerentes por perfil. |
| `address` | Endereço coerente, com UF fixa ou aleatória. |
| `zeros` | De 1 a 1.000 zeros. |
| `sequence` | Início, passo, largura e escopo de registro ou arquivo. |
| `date` | Data específica, deslocamento ou próximo dia útil; formatos prontos e personalizados, fuso e milissegundos. |
| `alpha` | Caracteres aleatórios do alfabeto informado. |
| `random` | Decimal aleatório no intervalo, com precisão de 0 a 6 casas. |
| `id` | Identificador com prefixo/comprimento ou UUID v4. |
| `compose` | Concatenação ou soma exata, até 100 partes e seis níveis de composição. |

A soma usa aritmética decimal exata, aceita até 12 casas por parcela e evita erros de ponto flutuante. Os perfis são compartilhados por tipo/grupo/UF dentro do mesmo registro. Campos de saída podem referenciar campos posteriores; ciclos e referências a campos omitidos geram erro controlado. A quantidade de caracteres considera pontos de código Unicode, inclusive emoji, como `Array.from` no estúdio.

`lengthTarget=validate` exige tamanho exato; `output` trunca antes de exigir o tamanho; `input` limita valores lidos da entrada antes da fórmula. Valores menores que o limite não são completados artificialmente. Presença opcional pode omitir sempre ou alternar por registro (omitir segundo, quarto etc.). Campos obrigatórios presentes não podem ficar vazios. Raiz e caminho da unidade não podem ser omitidos. Cabeçalhos ficam fora da unidade e devem permanecer únicos.

A referência de data/hora é capturada uma vez por documento. Os componentes de hora vêm dessa referência no fuso da configuração; a data vem da data-base, do deslocamento ou da data específica. O pacote `tzdata` fornece os fusos no Windows.

## Validação de Retorno

Antes de gerar qualquer modelo, a entrada é comparada com o XML salvo de Retorno. São comparados nomes expandidos, conjuntos de atributos e ordem de filhos. Valores, comentários e espaços de formatação são ignorados. Somente a multiplicidade da unidade de registro pode variar; cada registro, inclusive o segundo e os posteriores, deve manter a mesma assinatura estrutural. Registros não podem atravessar a posição de um cabeçalho ou rodapé.

Entrada inválida usa `INPUT_XML_INVALID`; referência ausente/inválida usa `RETURN_INPUT_TEMPLATE_NOT_READY`; divergência usa `INPUT_XML_STRUCTURE_MISMATCH`. DTD e declarações de entidades são rejeitados. XML de entrada fica limitado a 2.000.000 bytes e 128 níveis; excesso de bytes responde `413 INPUT_TOO_LARGE`; Retorno aceita até 500 registros de entrada.

Seleção por IDs preserva a ordem solicitada; `all` preserva a ordem salva. IDs duplicados, desconhecidos ou modelos incompletos interrompem a operação. Todos os modelos recebem a mesma entrada validada. `apart` retorna um documento por modelo.

`mixed` exige o mesmo caminho de unidade, envelope e valores externos à unidade (incluindo cabeçalhos). A assinatura de cada registro de um modelo deve coincidir com a do registro correspondente nos outros modelos. Assim, políticas opcionais alternadas idênticas são preservadas. A intercalação é A1, B1, A2, B2. Ausência de envelope para intercalar, cabeçalhos divergentes ou assinaturas diferentes geram `RETURN_MODELS_INCOMPATIBLE`. O nome do documento composto vem do primeiro modelo selecionado; o publicador resolve colisões. A contagem do resultado é K × N; fórmulas individuais recebem N.

O limite de saída é 100.000.000 bytes no total, inclusive no modo `apart`; excesso responde `413 OUTPUT_LIMIT_EXCEEDED`. Há verificação estimada antes da replicação, orçamento durante a avaliação de valores/composições e conferência dos bytes finais. Nenhuma função do motor escreve arquivos ou altera SQLite.

## Diferenças deliberadas e limites da evidência

Aleatoriedade usa `secrets` e UUID da biblioteca Python; os valores concretos não são reproduzíveis nem iguais aos sorteados pelo navegador, mas os formatos, limites, verificadores e vínculos dos perfis são preservados. Os dados dos perfis mantêm os mesmos conjuntos de nomes, cidades e componentes usados na referência.

O Python corrige um caso do motor JavaScript: somatório `allRecords` em um grupo aninhado, avaliado a partir do segundo registro, precisa normalizar o índice do registro antes de percorrer todos os registros. Cada saída recebe o total completo, conforme o escopo solicitado, em vez de repetir apenas o segundo registro.

A compatibilidade de `mixed` é conservadora: não inventa envelopes e rejeita valores diferentes em cabeçalhos. A aceitação com modelos reais do ambiente e comparação ponta a ponta com o navegador permanece uma validação operacional; os testes locais usam documentos sintéticos representativos e a leitura do código de referência, sem afirmar equivalência byte a byte ou sorteios iguais.

## Evidência automatizada

Executar com o pacote instalado ou `PYTHONPATH=src`:

```text
python -m unittest discover -s tests -p test_formulas.py
python -m unittest discover -s tests -p test_xml_engine.py
```

Resultado em 23/10/2026: 5 testes de fórmulas e 27 testes de XML aprovados. Cobertura inclui os 20 tipos, verificadores de CPF/CNPJ, data/fuso/UTC/dia útil, soma exata, limites de fórmulas e nome; 500 registros, índices/atributos/namespaces/CDATA, estrutura de todos os registros, ordem, DTD/limite/profundidade de entrada, dependências e ciclos, somatórios globais/aninhados, presença/tamanho/cabeçalho, limite de saída, seleção ordenada e composição compatível/incompatível.

Erros de configuração retornam mensagem pública estática, sem reproduzir valores de fórmulas nem caminhos internos. Ao compor modelos com prefixos XML diferentes, as declarações de namespace herdadas de cada envelope são materializadas na unidade importada; atributos e descendentes conservam seus nomes expandidos.
