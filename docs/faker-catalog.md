# Catálogo Faker v1 na API

O núcleo `src/mockaize_api/faker_catalog.py` é uma cópia versionada do site
`dev` no commit c5410a30ba1b1b426842bbd099b739e3591f8d15, sob a licença MIT
incluída ao lado do módulo. A API não importa o site em execução. Ao atualizar o
catálogo, sincronize o núcleo e regenere o manifesto a partir do site com Faker
40.44.0; compare `tests/fixtures/faker-manifest-v1.json` e execute os testes de
catálogo e integração antes de publicar ambos os produtos.

A fórmula usa `type=faker`, `catalogVersion=1` numérico, `catalogId`, `params`
e `group`; `category` é opcional. Os IDs legados continuam reconhecidos, inclusive
`currency`, sem expô-los como novas opções. As fórmulas antigas de pessoa,
empresa e endereço são adaptadas em memória depois da leitura do preset.

Cada modelo mantém seus próprios perfis por registro, família, grupo e UF.
Cabeçalhos usam o perfil do primeiro registro do respectivo modelo; o nome do
arquivo usa o mesmo perfil. No retorno misto, cada modelo continua independente:
os envelopes e cabeçalhos gerados precisam coincidir, como no contrato existente;
o resultado utiliza o nome do primeiro modelo. Não há garantia de igualdade entre
gerações aleatórias independentes.
