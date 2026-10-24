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

As versões efetivas ficam nos metadados e nos logs do build. O serviço usa HTTP
e os algoritmos de hash nativos do Python; não distribui o backend TLS opcional/
OpenSSL. O runtime é distribuído uma única vez junto do serviço, sem cópias dentro
do configurador ou desinstalador.
