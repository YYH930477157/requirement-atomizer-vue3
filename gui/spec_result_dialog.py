from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui import i18n


def _count(value: Any) -> int:
    """gaps / conflicts 在 analysis 里可能是列表，也可能直接是计数。"""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, int):
        return value
    return 0


class SpecResultDialog(QDialog):
    """装配完成后的结果摘要：条数 / 按域分布 / 缺口冲突 / 写出文件，
    并提供打开输出目录与打开 Word 的入口。"""

    def __init__(self, payload: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.out_dir = Path(str(payload.get("out_dir") or ""))
        self.written = [Path(p) for p in payload.get("written", [])]
        analysis = payload.get("analysis") or {}
        count = payload.get("count") or analysis.get("total_count") or 0

        self.setWindowTitle(i18n.UI["assemble_done_title"])
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        headline = QLabel(i18n.UI["assemble_count"].format(count=f"{int(count):,}"))
        headline.setObjectName("statValue")
        layout.addWidget(headline)

        layout.addWidget(self._issues_label(analysis))

        by_domain = analysis.get("by_domain")
        if isinstance(by_domain, dict) and by_domain:
            layout.addWidget(self._section_title(i18n.UI["assemble_by_domain"]))
            layout.addWidget(self._domain_block(by_domain))

        if self.written:
            layout.addWidget(self._section_title(i18n.UI["assemble_files"]))
            layout.addWidget(self._files_block())

        layout.addStretch(1)
        layout.addLayout(self._button_row())

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("panelTitle")
        return label

    def _issues_label(self, analysis: dict[str, Any]) -> QLabel:
        gaps = _count(analysis.get("gaps"))
        conflicts = _count(analysis.get("conflicts"))
        parts: list[str] = []
        if gaps:
            parts.append(i18n.UI["assemble_gaps"].format(n=gaps))
        if conflicts:
            parts.append(i18n.UI["assemble_conflicts"].format(n=conflicts))
        text = i18n.UI["source_separator"].join(parts) if parts else i18n.UI["assemble_no_issues"]
        return QLabel(text)

    def _domain_block(self, by_domain: dict[str, Any]) -> QFrame:
        frame = QFrame()
        frame.setObjectName("statCard")
        block = QVBoxLayout(frame)
        block.setContentsMargins(16, 12, 16, 12)
        block.setSpacing(4)
        for domain, value in sorted(by_domain.items(), key=lambda kv: _count(kv[1]), reverse=True):
            row = QLabel(f"{domain}{i18n.UI['label_separator']}{_count(value):,}")
            block.addWidget(row)
        return frame

    def _files_block(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("statCard")
        block = QVBoxLayout(frame)
        block.setContentsMargins(16, 12, 16, 12)
        block.setSpacing(4)
        for path in self.written:
            label = QLabel(path.name)
            label.setToolTip(str(path))
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            block.addWidget(label)
        return frame

    def _button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        open_dir = QPushButton(i18n.UI["assemble_open_dir"])
        open_dir.clicked.connect(self._open_output_dir)
        row.addWidget(open_dir)
        xlsx = next((p for p in self.written if p.suffix.lower() == ".xlsx"), None)
        if xlsx is not None:
            open_excel = QPushButton(i18n.UI["assemble_open_excel"])
            open_excel.clicked.connect(lambda: self._open_path(xlsx))
            row.addWidget(open_excel)
        docx = next((p for p in self.written if p.suffix.lower() == ".docx"), None)
        if docx is not None:
            open_word = QPushButton(i18n.UI["assemble_open_word"])
            open_word.clicked.connect(lambda: self._open_path(docx))
            row.addWidget(open_word)
        json_path = next((p for p in self.written if p.suffix.lower() == ".json"), None)
        if json_path is not None:
            browse = QPushButton(i18n.UI["spec_view_browse"])
            browse.clicked.connect(lambda: self._browse_spec(json_path))
            row.addWidget(browse)
        row.addStretch(1)
        close = QPushButton(i18n.UI["assemble_close"])
        close.setObjectName("primaryButton")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        return row

    def _browse_spec(self, json_path: Path) -> None:
        import json

        from gui.spec_view import SpecBrowserDialog

        try:
            doc = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        SpecBrowserDialog(doc, self).exec()

    def _open_output_dir(self) -> None:
        if self.out_dir:
            self._open_path(self.out_dir)

    @staticmethod
    def _open_path(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
