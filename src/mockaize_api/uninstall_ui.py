"""Janela dedicada do desinstalador Windows; nenhuma operação ao importar."""
from pathlib import Path
import sys

from .uninstall import UninstallSession, discover_uninstall_target, finish_uninstall


def main():
    from PySide6.QtCore import QObject, QThread, Signal, Slot, QTimer, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('MockAíZé API — Desinstalar')
    app.setWindowIcon(QIcon(str(Path(__file__).parent / 'assets' / 'mockaize-favicon.png')))
    app.setQuitOnLastWindowClosed(False)
    try:
        installation = discover_uninstall_target(Path(sys.executable))
        if installation is None:
            QMessageBox.information(None, 'MockAíZé API', 'OK. Nenhuma instalação foi encontrada.')
            return
        session = UninstallSession(installation)
    except Exception as error:
        QMessageBox.critical(None, 'Não foi possível desinstalar', str(error))
        return

    class Worker(QObject):
        done = Signal()
        failed = Signal(str)

        @Slot()
        def run(self):
            initialized = False
            try:
                import pythoncom
                pythoncom.CoInitialize()
                initialized = True
                session.detach()
                self.done.emit()
            except Exception as error:
                self.failed.emit(str(error))
            finally:
                if initialized:
                    pythoncom.CoUninitialize()

    progress = QProgressDialog('Parando e removendo o serviço do Windows…', None, 0, 0)
    progress.setWindowTitle('Desinstalar MockAíZé API')
    progress.setMinimumDuration(0)
    worker_thread, worker = QThread(), Worker()
    worker.moveToThread(worker_thread)
    worker_thread.started.connect(worker.run)

    def ask(kind, path):
        message = (f'O serviço foi removido. Deseja apagar os binários instalados?\n\n{path}'
                   if kind == 'binaries' else
                   f'Deseja apagar esta pasta e todo o seu conteúdo?\n\n{path}\n\nEscolha Não para preservar os arquivos.')
        return QMessageBox.question(None, 'Limpeza opcional', message,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def complete():
        worker_thread.quit()
        progress.close()
        try:
            result = finish_uninstall(session, ask)
            message = 'OK. Serviço removido da listagem do Windows. Desinstalação concluída.'
            if result['restartRequired']:
                message += '\nArquivos em uso serão removidos no próximo reinício do Windows.'
            QMessageBox.information(None, 'MockAíZé API', message)
        except Exception as error:
            QMessageBox.critical(None, 'Limpeza não concluída',
                                 'O serviço foi removido, mas a limpeza não terminou.\n' + str(error))
        app.quit()

    def failed(message):
        worker_thread.quit()
        progress.close()
        QMessageBox.critical(None, 'Desinstalação não concluída', message)
        app.quit()

    class Controller(QObject):
        @Slot()
        def completed(self):
            complete()

        @Slot(str)
        def error(self, message):
            failed(message)

    controller = Controller()
    worker.done.connect(controller.completed, Qt.QueuedConnection)
    worker.failed.connect(controller.error, Qt.QueuedConnection)
    worker_thread.finished.connect(worker.deleteLater)
    progress.show()
    QTimer.singleShot(0, worker_thread.start)
    app.exec()
    worker_thread.quit()
    worker_thread.wait()


if __name__ == '__main__':
    main()
