from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.fluent import render_stylesheet
from gui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv)
    smoke = "--smoke" in argv
    qt_argv = [arg for arg in argv if arg != "--smoke"]
    app = QApplication.instance() or QApplication(qt_argv)
    app.setStyleSheet(render_stylesheet())
    window = MainWindow()
    window.show()
    if smoke:
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
