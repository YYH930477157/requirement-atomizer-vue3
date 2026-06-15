from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui import i18n
from spec_export import group_by_domain


class SpecBrowserDialog(QDialog):
    """整段实现规格浏览器：左侧按 21 领域分段（复用 spec_export.group_by_domain，
    与 Word/MD 导出同一套分组），右侧把选中段的需求渲染成可读的整段文档卡片。"""

    def __init__(self, doc: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.groups = group_by_domain(doc.get("requirements", []))
        self.setWindowTitle(i18n.UI["spec_view_title"])
        self.resize(1180, 780)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        meta = doc.get("meta", {}) or {}
        total = (doc.get("analysis", {}) or {}).get("total_count") or len(doc.get("requirements", []))
        header = QLabel(i18n.UI["spec_view_header"].format(total=total, source=meta.get("source", "")))
        header.setObjectName("productTitle")
        outer.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        self.section_list = QListWidget()
        self.section_list.setObjectName("sideNav")
        self.section_list.setFixedWidth(232)
        for domain, reqs in self.groups:
            QListWidgetItem(f"{domain}    {len(reqs)}", self.section_list)
        body.addWidget(self.section_list)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("tablePanel")
        body.addWidget(self.scroll, 1)

        self.section_list.currentRowChanged.connect(self.show_section)
        if self.groups:
            self.section_list.setCurrentRow(0)

    def show_section(self, row: int) -> None:
        if row < 0 or row >= len(self.groups):
            return
        _domain, reqs = self.groups[row]
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(14)
        if not reqs:
            layout.addWidget(QLabel(i18n.UI["spec_view_empty"]))
        for req in reqs:
            layout.addWidget(self._requirement_card(req))
        layout.addStretch(1)
        self.scroll.setWidget(container)

    def _requirement_card(self, req: dict[str, Any]) -> QFrame:
        card = QFrame()
        card.setObjectName("statCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)

        title = QLabel(f"{req.get('id', '')}  {req.get('title', '')}")
        title.setObjectName("panelTitle")
        title.setWordWrap(True)
        box.addWidget(title)

        labels = " / ".join(req.get("labels") or [])
        meta_bits = [str(req.get("priority", "")), labels, str(req.get("source_section", ""))]
        meta = QLabel(i18n.UI["source_separator"].join(b for b in meta_bits if b))
        meta.setObjectName("panelSubtitle")
        meta.setWordWrap(True)
        box.addWidget(meta)

        description = QLabel(str(req.get("description", "")))
        description.setWordWrap(True)
        description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(description)

        threshold = req.get("threshold_table")
        if isinstance(threshold, dict) and threshold.get("rows"):
            box.addWidget(self._threshold_table(threshold))

        acceptance = req.get("acceptance_criteria") or []
        if acceptance:
            text = i18n.UI["spec_view_acceptance"] + i18n.UI["label_separator"] + "\n" + "\n".join(
                f"· {item}" for item in acceptance
            )
            ac = QLabel(text)
            ac.setWordWrap(True)
            box.addWidget(ac)

        source_quote = str(req.get("source_quote") or "")
        if source_quote:
            src = QLabel(i18n.UI["spec_view_source"] + i18n.UI["label_separator"] + source_quote)
            src.setObjectName("panelSubtitle")
            src.setWordWrap(True)
            box.addWidget(src)

        return card

    def _threshold_table(self, threshold: dict[str, Any]) -> QTableWidget:
        columns = [str(c) for c in (threshold.get("columns") or [])]
        rows = threshold.get("rows") or []
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        for r, row in enumerate(rows):
            for c in range(len(columns)):
                value = row[c] if c < len(row) else ""
                table.setItem(r, c, QTableWidgetItem(str(value)))
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMaximumHeight(min(36 + 30 * len(rows), 340))
        if threshold.get("description"):
            table.setToolTip(str(threshold["description"]))
        return table
