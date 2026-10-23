"""Exercise Qt's native libraries/platform and the product icon without SCM mutations."""
import json
from pathlib import Path
import sys
import traceback


def check_ui(report: Path) -> int:
    result = {'status': 'failed', 'installationChanged': False}
    try:
        from PySide6 import __version__
        from PySide6.QtCore import qVersion
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QLabel
        app = QApplication.instance() or QApplication([])
        icon = QIcon(str(Path(__file__).parent / 'assets' / 'mockaize-favicon.png'))
        if icon.isNull() or icon.pixmap(32, 32).isNull():
            raise RuntimeError('Ícone do MockAíZé não carregou.')
        window = QLabel('MockAíZé API · diagnóstico de interface')
        window.setWindowIcon(icon)
        window.resize(360, 100)
        window.show()
        app.processEvents()
        if window.grab().isNull():
            raise RuntimeError('A janela Qt não foi renderizada.')
        window.close()
        app.processEvents()
        result.update(status='passed', pysideVersion=__version__, qtVersion=qVersion(),
                      platform=app.platformName(), iconLoaded=True)
    except Exception:
        result['error'] = traceback.format_exc()
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['status'] == 'passed' else 1


def dispatch(main):
    if len(sys.argv) > 1 and sys.argv[1] == '--diagnose-ui':
        if len(sys.argv) != 3:
            raise SystemExit(2)
        raise SystemExit(check_ui(Path(sys.argv[2])))
    main()


if __name__ == '__main__':
    raise SystemExit(check_ui(Path(sys.argv[1])))
