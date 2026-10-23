# Componentes de terceiros

Build Windows contém Python, PySide6 Essentials/Qt, Shiboken, pywin32 e tzdata,
e usa PyInstaller. `packaging/collect_licenses.py` copia as licenças/metadados
fornecidos pelas distribuições instaladas para `licenses/` do payload.
Os termos em `packaging/licenses/` também acompanham o pacote.
Este documento não escolhe uma licença para o código próprio do projeto.

- Python: https://docs.python.org/3/license.html
- Qt/PySide/Shiboken: https://doc.qt.io/qtforpython-6/licenses.html
- LGPL3: https://www.gnu.org/licenses/lgpl-3.0.html
- GPL3 referenciada pela LGPL: https://www.gnu.org/licenses/gpl-3.0.html
- Fontes PySide: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Fontes Qt: https://code.qt.io/cgit/qt/
- pywin32: https://github.com/mhammond/pywin32
- tzdata: https://github.com/python/tzdata
- PyInstaller: https://pyinstaller.org/en/stable/license.html

O código e os scripts públicos permitem reconstruir o programa com bibliotecas
Qt modificadas; não há restrição adicional à engenharia reversa necessária para
depurar essas alterações. As versões e licenças efetivas ficam nos metadados
coletados. As wheels Qt desta validação fornecem texto comercial e declaram
alternativas LGPL/GPL; o coletor não trata esse texto como licença selecionada.
Conferir termos livres e avisos correspondentes antes da distribuição pública.
