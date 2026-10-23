"""Native desktop setup/configurator. No browser, local web server or resident UI."""
import ctypes
from importlib.metadata import version, PackageNotFoundError
import os
from pathlib import Path
import sys

from .config import ApiConfig, ConfigurationError, load_config
from .windows_ops import (CONFIG_EXE, SERVICE_EXE, UNINSTALL_EXE, Installation, Installer, WindowsDriver,
                          discover_installation, validate_origins, wait_health)


STYLE = '''
QWidget { background:#0d0f0e; color:#f3f6f3; font:14px "Segoe UI"; }
QFrame#rail { background:#0b0e0c; border-right:1px solid #242a26; }
QLabel#brand { font-size:23px; font-weight:700; color:#18d365; }
QLabel#heading { font-size:32px; font-weight:650; }
QLabel#eyebrow { color:#18d365; font-size:11px; font-weight:700; }
QLabel#muted { color:#a1aaa4; }
QLabel#step { padding:13px; color:#77827b; }
QLabel#activeStep { padding:13px; color:#18d365; background:#18241c; border-radius:7px; }
QLineEdit,QSpinBox,QPlainTextEdit { background:#222624; border:1px solid #454b47;
 border-radius:7px; padding:11px; selection-background-color:#0fae52; }
QLineEdit:focus,QSpinBox:focus { border-color:#18d365; }
QPushButton { background:#222624; border:1px solid #454b47; border-radius:7px; padding:11px 17px; }
QPushButton:hover { border-color:#18d365; }
QPushButton:disabled { color:#77827b; border-color:#303632; background:#151a17; }
QPushButton#primary { background:#18d365; color:#05190d; border-color:#18d365; font-weight:700; }
QPushButton#danger { background:#382021; color:#ffc6c6; border-color:#823e43; }
QPlainTextEdit { background:#090c0a; font:12px "Consolas"; }
QProgressBar { background:#28302a; border:0; border-radius:4px; height:8px; }
QProgressBar::chunk { background:#18d365; }
QRadioButton { padding:12px; }
QMessageBox QLabel { min-width:360px; }
'''


def documents_directory() -> Path:
    if os.name == 'nt':
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:
            return Path(buffer.value)
    return Path.home() / 'Documents'


def default_database() -> str:
    candidates = [documents_directory() / 'MockAíZé' / 'mockaize.sqlite3',
                  Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MockAiZe' / 'mockaize.sqlite3']
    return str(next((path for path in candidates if path.is_file()), candidates[0]))


def detect_mode(installation, driver) -> str:
    if installation is None:
        return 'new'
    if (installation.config_path.is_file()
            and (installation.directory / SERVICE_EXE).is_file()
            and (installation.directory / CONFIG_EXE).is_file()
            and (installation.directory / UNINSTALL_EXE).is_file()
            and driver.status() != 'absent'):
        return 'update'
    return 'repair'


def payload_directory() -> Path:
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent.parent)) / 'payload'


def main() -> None:
    from PySide6.QtCore import QObject, QThread, Signal, QUrl, Qt
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
        QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
        QSpinBox, QVBoxLayout, QWidget, QFileDialog, QScrollArea)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('MockAíZé API')
    app.setWindowIcon(QIcon(str(Path(__file__).parent / 'assets' / 'mockaize-favicon.png')))
    app.setStyleSheet(STYLE)

    class Worker(QObject):
        message = Signal(str)
        done = Signal(object)
        failed = Signal(str)

        def __init__(self, action):
            super().__init__()
            self.action = action

        def run(self):
            if os.name == 'nt':
                import pythoncom
                pythoncom.CoInitialize()
            try:
                self.done.emit(self.action(self.message.emit))
            except Exception as error:
                # Exception messages originate from safe local validation/operations;
                # subprocess stderr/stdout (which may contain paths) are not displayed.
                self.failed.emit(str(error))
            finally:
                if os.name == 'nt':
                    pythoncom.CoUninitialize()

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('MockAíZé API · Assistente de instalação')
            self.resize(1120, 790)
            self.setMinimumSize(900, 700)
            self.preview = '--preview' in sys.argv
            self.driver = WindowsDriver()
            self.existing = None if self.preview else discover_installation()
            self.mode = 'new' if self.preview else detect_mode(self.existing, self.driver)
            self.installed_ui = bool(self.existing and Path(sys.executable).resolve() ==
                                     (self.existing.directory / CONFIG_EXE).resolve())
            self.editing = False
            self.busy = False
            self.uninstalled = False
            self.token = None
            self.step = 0
            self.config = None
            self.repairing_config = False
            if self.existing and self.existing.config_path.is_file():
                try:
                    self.config = load_config(self.existing.config_path)
                except ConfigurationError:
                    self.mode = 'repair'
                    self.repairing_config = True
            root = documents_directory() / 'MockAíZé API'
            self.values = self.config.to_mapping() if self.config else {
                'databasePath': default_database(), 'inputDirectory': str(root / 'Entradas'),
                'outputDirectory': str(root / 'Saídas'), 'logsDirectory': str(root / 'Logs'),
                'port': 6578, 'host': '127.0.0.1', 'firewallAccess': 'N'}
            self.origins = self.existing.origins if self.existing else 'LocalSubnet'
            self.installation = self.existing or Installation(
                Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'MockAiZe API', root / 'config.json')
            shell = QWidget()
            self.setCentralWidget(shell)
            layout = QHBoxLayout(shell)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            rail = QFrame()
            rail.setObjectName('rail')
            rail.setFixedWidth(270)
            self.rail = QVBoxLayout(rail)
            self.rail.setContentsMargins(24, 32, 24, 32)
            layout.addWidget(rail)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            pane = QWidget()
            self.body = QVBoxLayout(pane)
            self.body.setContentsMargins(44, 32, 44, 32)
            self.body.setSpacing(17)
            scroll.setWidget(pane)
            layout.addWidget(scroll)
            self.render()
            if '--uninstall' in sys.argv:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self.ask_uninstall)

        def clear(self, layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    self.clear(item.layout())

        def label(self, text, name=None, layout=None):
            label = QLabel(text)
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            if name:
                label.setObjectName(name)
            (layout or self.body).addWidget(label)
            return label

        def button(self, text, callback, primary=False, layout=None):
            button = QPushButton(text)
            if primary:
                button.setObjectName('primary')
            button.clicked.connect(callback)
            (layout or self.body).addWidget(button)
            return button

        def render(self):
            self.clear(self.body)
            self.clear(self.rail)
            self.label('⌁  MockAíZé\n       API · SETUP', 'brand', self.rail)
            self.rail.addSpacing(35)
            self.label({'new': 'PRIMEIRA INSTALAÇÃO', 'update': 'ATUALIZAÇÃO',
                        'repair': 'REPARO'}[self.mode], 'muted', self.rail)
            steps = ['Verificação', 'Banco de dados', 'Diretórios', 'Acesso e porta', 'Revisão', 'Instalação', 'Concluído']
            for index, title in enumerate(steps):
                self.label(f'{index + 1:02}   {title}', 'activeStep' if self.step == index else 'step', self.rail)
            self.rail.addStretch()
            self.label('Produto independente\nServiço em segundo plano.\nInicia automaticamente com o Windows.', 'muted', self.rail)
            self.label('ASSISTENTE DE INSTALAÇÃO / MOCKAÍZÉ API', 'eyebrow')
            if self.step == 0:
                self.intro()
            elif self.step in (1, 2, 3):
                self.fields()
            elif self.step == 4:
                self.review()
            elif self.step == 5:
                self.label('Preparando a API.', 'heading')
                self.progress = QProgressBar()
                self.progress.setRange(0, 0)
                self.body.addWidget(self.progress)
                self.terminal = QPlainTextEdit()
                self.terminal.setReadOnly(True)
                self.body.addWidget(self.terminal, 1)
                self.label('Aguarde a confirmação de saúde do serviço.', 'muted')
            else:
                self.done()

        def intro(self):
            self.label('Sua API, pronta para trabalhar.', 'heading')
            if self.existing:
                state = self.driver.status()
                self.label(f'Instalação detectada: {self.mode}. Serviço: {state}.', 'muted')
                self.label(f'Configuração: {self.installation.config_path}\nBinários: {self.installation.directory}')
                if self.repairing_config:
                    self.label('Configuração inválida: informe os dados novamente. O original será preservado em config.invalid-backup.json.', 'muted')
                if self.config:
                    self.label(f'Endereço local: http://127.0.0.1:{self.config.port}')
                if self.installed_ui:
                    self.button('Iniciar', lambda: self.run_action(lambda emit: self.start_service()))
                    self.button('Parar', lambda: self.run_action(lambda emit: self.driver.stop(), False))
                    self.button('Reiniciar', lambda: self.run_action(lambda emit: self.restart_service()))
                    self.button('Alterar configuração', self.edit)
                    self.button('Reparar / atualizar', self.repair_help)
                    self.button('Abrir pasta de logs', self.open_logs)
                    self.button('Desinstalar', self.ask_uninstall)
                else:
                    self.label('Pare o serviço antes de trocar os binários. Configuração, chave e arquivos serão preservados.', 'muted')
                    self.button('Parar serviço', lambda: self.run_action(lambda emit: self.driver.stop(), False))
                    self.button('Já pausei; verificar novamente', self.verify_pause, True)
            else:
                self.label('Instale o serviço Windows com banco SQLite, pastas e acesso próprios. O site MockAíZé pode ficar fechado.', 'muted')
                self.label('O Windows solicitará permissão para registrar serviço, permissões e a regra de rede escolhida. Nenhuma instalação é feita antes da revisão.', 'muted')
                self.button('Começar configuração →', lambda: self.go(1), True)
            self.body.addStretch()

        def repair_help(self):
            QMessageBox.information(self, 'Reparar ou atualizar',
                'Abra o instalador MockAiZe-API-Setup.exe da versão desejada. Ele detectará esta instalação e preservará seus dados. Pare o serviço e confirme novamente no instalador antes da troca.')

        def edit(self):
            self.editing = True
            self.go(1)

        def verify_pause(self):
            try:
                Installer(self.installation, self.driver).require_stopped()
                self.go(4 if self.config else 1)
            except Exception as error:
                QMessageBox.warning(self, 'Serviço em execução', str(error))

        def go(self, step):
            self.step = step
            self.render()

        def field(self, label, key, directory=False):
            self.label(label)
            row = QHBoxLayout()
            edit = QLineEdit(str(self.values[key]))
            edit.setAccessibleName(label)
            row.addWidget(edit, 1)
            def browse():
                value = (QFileDialog.getExistingDirectory(self, label, edit.text()) if directory else
                         QFileDialog.getOpenFileName(self, label, edit.text(), 'SQLite (*.sqlite3 *.sqlite *.db);;Todos (*)')[0])
                if value:
                    edit.setText(value)
            self.button('Alterar' if directory else 'Procurar', browse, layout=row)
            self.body.addLayout(row)
            edit.textChanged.connect(lambda text: self.values.__setitem__(key, text))

        def fields(self):
            if self.step == 1:
                self.label('Conecte suas configurações.', 'heading')
                self.label('Selecione o banco do MockAíZé. A API apenas lê a biblioteca; não cria nem migra o banco.', 'muted')
                self.field('Banco de configurações', 'databasePath')
            elif self.step == 2:
                self.label('Cada arquivo no seu lugar.', 'heading')
                self.field('XMLs de entrada permitidos', 'inputDirectory', True)
                self.field('XMLs gerados', 'outputDirectory', True)
                self.field('Logs', 'logsDirectory', True)
                self.label('Use discos locais disponíveis antes do login. Caminhos de rede e pastas sincronizadas dependentes do usuário não permitem início automático confiável.', 'muted')
            else:
                self.label('Defina quem pode acessar.', 'heading')
                self.label('Porta HTTP')
                port = QSpinBox()
                port.setRange(1, 65535)
                port.setValue(int(self.values['port']))
                port.valueChanged.connect(lambda value: self.values.__setitem__('port', value))
                self.body.addWidget(port)
                local = QRadioButton('Somente neste computador · recomendado')
                network = QRadioButton('Permitir na rede · HTTP sem criptografia')
                local.setChecked(self.values['firewallAccess'] == 'N')
                network.setChecked(not local.isChecked())
                self.body.addWidget(local)
                self.body.addWidget(network)
                def access(checked):
                    self.values['host'] = '0.0.0.0' if checked else '127.0.0.1'
                    self.values['firewallAccess'] = 'Y' if checked else 'N'
                network.toggled.connect(access)
                self.label('Origens confiáveis (LocalSubnet ou IPs/sub-redes separados por vírgula)')
                origins = QLineEdit(self.origins)
                origins.textChanged.connect(lambda text: setattr(self, 'origins', text))
                self.body.addWidget(origins)
                self.label('Na rede, a chave e os XMLs trafegam sem criptografia. Somente a regra MockAiZe API HTTP será criada, em redes privadas/domínio, limitada às origens informadas.', 'muted')
            self.body.addStretch()
            row = QHBoxLayout()
            self.button('← Voltar', lambda: self.go(self.step - 1), layout=row)
            self.button('Continuar →', self.next_step, True, row)
            self.body.addLayout(row)

        def next_step(self):
            try:
                # Full validation on review; early path/file errors keep the relevant page.
                if self.step == 1 and not Path(self.values['databasePath']).is_file():
                    raise ValueError('Localize um banco SQLite existente.')
                if self.step == 3:
                    self.config = ApiConfig.from_mapping(self.values)
                    self.origins = validate_origins(self.origins)
                    for path in (self.config.database_path, self.config.input_directory,
                                 self.config.output_directory, self.config.logs_directory,
                                 self.installation.config_path):
                        if str(path).startswith('\\\\') or 'onedrive' in str(path).lower():
                            raise ValueError('Escolha caminhos locais disponíveis antes do login, fora de pastas de rede/OneDrive.')
                self.go(self.step + 1)
            except Exception as error:
                QMessageBox.warning(self, 'Verifique a configuração', str(error))

        def review(self):
            self.label('Tudo pronto para continuar.', 'heading')
            self.label('Configuração inválida será reparada; original preservado em config.invalid-backup.json.' if self.repairing_config else
                       'Configuração existente preservada.' if self.existing and not self.editing else
                       'Confira os caminhos e o acesso antes de instalar.', 'muted')
            for label, key in [('Banco', 'databasePath'), ('Entrada', 'inputDirectory'),
                               ('Saída', 'outputDirectory'), ('Logs', 'logsDirectory'), ('Porta', 'port')]:
                self.label(f'{label}: {self.values[key]}')
            self.label('Rede: ' + ('local, sem regra de firewall' if self.values['firewallAccess'] == 'N' else
                       f'HTTP sem criptografia · origens {self.origins}'))
            self.label(f'Binários: {self.installation.directory}\nInício automático · conta LocalService', 'muted')
            self.body.addStretch()
            self.button('← Voltar', lambda: self.go(3 if self.editing or not self.existing or
                        not self.existing.config_path.is_file() else 0))
            self.button('Salvar e reiniciar' if self.editing else 'Instalar / atualizar e iniciar →', self.execute, True)

        def execute(self):
            if self.preview:
                QMessageBox.information(self, 'Prévia', 'Prévia visual. Nenhuma instalação é feita neste modo.')
                return
            installation = Installation(self.installation.directory, self.installation.config_path, self.origins)
            def action(emit):
                if self.editing:
                    installer = Installer(self.installation, self.driver, emit)
                    installer.change_config(self.config, self.origins)
                    return None
                installer = Installer(installation, self.driver, emit)
                return installer.install(payload_directory(), self.config)
            self.run_action(action)

        def run_action(self, action, success=True):
            if self.busy:
                return
            self.busy = True
            self.go(5)
            self.worker_thread = QThread(self)
            self.worker = Worker(action)
            self.worker.moveToThread(self.worker_thread)
            self.worker_thread.started.connect(self.worker.run)
            self.worker.message.connect(self.terminal.appendPlainText)
            def finished(token):
                self.busy = False
                self.token = token
                self.uninstalled = success == 'uninstall'
                self.go(6 if success else 0)
                self.worker_thread.quit()
            def failed(message):
                self.busy = False
                self.progress.setRange(0, 1)
                self.progress.setValue(0)
                self.terminal.appendPlainText('FALHA · ' + message)
                self.label('A operação não foi concluída. Preserve os dados e consulte o diagnóstico.', 'muted')
                self.button('Voltar e corrigir', lambda: self.go(0), True)
                self.worker_thread.quit()
            self.worker.done.connect(finished)
            self.worker.failed.connect(failed)
            self.worker_thread.finished.connect(self.worker.deleteLater)
            self.worker_thread.start()

        def start_service(self):
            self.driver.start()
            wait_health(load_config(self.installation.config_path))

        def restart_service(self):
            self.driver.stop()
            self.start_service()

        def done(self):
            if self.uninstalled:
                self.label('API desinstalada.', 'heading')
                self.label('Serviço, registro e regra de firewall removidos. Binários bloqueados serão removidos no próximo reinício.', 'muted')
                self.label(f'Dados preservados: {self.installation.config_path.parent}')
                self.body.addStretch()
                self.button('Fechar', self.close, True)
                return
            self.label('API em execução e respondendo.', 'heading')
            self.label('✓ Serviço Windows ativo · GET /health HTTP 200', 'eyebrow')
            config = load_config(self.installation.config_path)
            url = f'http://127.0.0.1:{config.port}'
            self.label(url)
            self.button('Copiar URL', lambda: app.clipboard().setText(url))
            if config.firewall_access == 'Y':
                self.label(f'Rede: http://IP-do-servidor:{config.port} · origens {self.origins}', 'muted')
            if self.token:
                self.label('Chave de acesso · exibida somente nesta instalação. Guarde-a em local seguro.', 'muted')
                token = QLineEdit(self.token)
                token.setReadOnly(True)
                self.body.addWidget(token)
                self.button('Copiar token', lambda: app.clipboard().setText(self.token))
            self.button('Abrir pasta de logs', self.open_logs)
            self.label('O setup baixado pode ser excluído. Mantenha os executáveis instalados em Program Files.', 'muted')
            self.body.addStretch()
            self.button('Concluir', self.close, True)

        def open_logs(self):
            if self.config:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config.logs_directory)))

        def ask_uninstall(self):
            if not self.existing or self.preview:
                return
            try:
                self.driver.launch_uninstaller(self.installation)
                self.close()
            except Exception as error:
                QMessageBox.warning(self, 'Não foi possível abrir o desinstalador', str(error))

        def closeEvent(self, event):
            if self.busy:
                event.ignore()
                return
            if getattr(self, 'worker_thread', None) and self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait(2000)
            self.token = None
            event.accept()

    try:
        window = Window()
    except Exception as error:
        QMessageBox.critical(None, 'Instalação não pode continuar', str(error))
        return
    window.show()
    app.exec()


if __name__ == '__main__':
    main()
