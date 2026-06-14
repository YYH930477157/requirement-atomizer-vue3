from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.fluent import render_stylesheet
from gui.main_window import MainWindow


def place_on_primary_screen(app: QApplication, window: MainWindow) -> None:
    """把窗口放到主屏可视区内并居中。

    修复多显示器 + 高 DPI 下 Qt 默认把窗口丢到负坐标/看不见的显示器导致「打开什么都不显示」的问题。
    """
    screen = app.primaryScreen()
    if screen is None:
        return
    avail = screen.availableGeometry()
    # 高分屏/缩放下窗口可能比屏幕还大，先裁进可视区（留 80px 余量）
    width = min(window.width(), max(640, avail.width() - 80))
    height = min(window.height(), max(480, avail.height() - 80))
    window.resize(width, height)
    # 居中后把左上角夹进可视区，确保整窗在屏内（杜绝负坐标）
    x = avail.left() + max(0, (avail.width() - width) // 2)
    y = avail.top() + max(0, (avail.height() - height) // 2)
    window.move(x, y)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv)
    smoke = "--smoke" in argv
    qt_argv = [arg for arg in argv if arg != "--smoke"]
    app = QApplication.instance() or QApplication(qt_argv)
    app.setStyleSheet(render_stylesheet())
    window = MainWindow()
    place_on_primary_screen(app, window)
    window.show()
    if smoke:
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
