from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.fluent import render_stylesheet
from gui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(render_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
