# Componentes de terceiros

A distribuição Windows contém Python, SQLite da distribuição Python, pywin32,
tzdata e o bootloader PyInstaller. Instalação, configuração e desinstalação usam
Inno Setup. Qt/PySide e Shiboken foram retirados do produto.

`packaging/collect_licenses.py` copia para `licenses/` os avisos e metadados
fornecidos pelas distribuições utilizadas, o texto da licença Python e a licença
do compilador Inno utilizado. Os textos são preservados sem modificações.
Este documento não escolhe uma licença para o código próprio do projeto.

- Python: https://docs.python.org/3/license.html
- SQLite: https://sqlite.org/copyright.html
- pywin32: https://github.com/mhammond/pywin32
- tzdata: https://github.com/python/tzdata
- PyInstaller e exceção para distribuição: https://pyinstaller.org/en/stable/license.html
- Inno Setup: https://jrsoftware.org/isinfo.php
- Swagger UI 5.33.1 (Apache-2.0): https://github.com/swagger-api/swagger-ui/releases/tag/v5.33.1

A interface Swagger usa JavaScript e CSS oficiais versionados localmente, sem CDN.
As fontes e hashes estão em `assets/swagger/UPSTREAM.json` no pacote Python;
os avisos originais do bundle e a licença estão também em `licenses/swagger-ui/`
na instalação Windows.

As versões efetivas ficam nos metadados e nos logs do build. O serviço usa HTTP
e os algoritmos de hash nativos do Python; não distribui o backend TLS opcional/
OpenSSL. O runtime é distribuído uma única vez junto do serviço, sem cópias dentro
do configurador ou desinstalador.
