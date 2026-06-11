from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui import fluent


class DetailPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("detailPanel")
        self.setMinimumWidth(320)
        self.pinned_label = QLabel("")
        self.status_label = QLabel("candidate")
        self.requirement_text = QTextEdit()
        self.requirement_text.setReadOnly(True)
        self.requirement_text.setMinimumHeight(120)
        self.metadata_grid = QGridLayout()
        self.metadata_grid.setVerticalSpacing(8)
        self.metadata_grid.setHorizontalSpacing(10)
        self.source_text = QTextEdit()
        self.source_text.setReadOnly(True)
        self.kb_widget = QWidget()
        self.kb_layout = QHBoxLayout(self.kb_widget)
        self.kb_layout.setAlignment(Qt.AlignLeft)
        self.review_text = QTextEdit()
        self.review_text.setReadOnly(True)
        self.accept_button = QPushButton("Accept")
        self.reject_button = QPushButton("Reject")
        self.discuss_button = QPushButton("Discuss")

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("Details"))
        header.addStretch(1)
        header.addWidget(self.pinned_label)
        layout.addLayout(header)
        layout.addWidget(section_title("Requirement"))
        layout.addWidget(self.requirement_text)
        layout.addWidget(section_title("Metadata"))
        self.metadata_widget = QWidget()
        self.metadata_widget.setMinimumHeight(170)
        self.metadata_widget.setLayout(self.metadata_grid)
        layout.addWidget(self.metadata_widget)
        layout.addWidget(section_title("Source"))
        layout.addWidget(self.source_text)
        layout.addWidget(section_title("KB Matches"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(76)
        scroll.setWidget(self.kb_widget)
        layout.addWidget(scroll)
        layout.addWidget(section_title("Review"))
        layout.addWidget(self.status_label)
        layout.addWidget(self.review_text)
        buttons = QHBoxLayout()
        buttons.addWidget(self.accept_button)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.discuss_button)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def set_pinned(self, pinned: bool) -> None:
        self.pinned_label.setText("Pinned" if pinned else "")

    def set_requirement(self, row: dict[str, Any] | None, source_index: dict[str, dict[str, Any]] | None = None) -> None:
        if row is None:
            self.requirement_text.clear()
            self.status_label.setText("candidate")
            self.source_text.clear()
            self.review_text.clear()
            self._clear_metadata()
            self._clear_kb_matches()
            return
        self.requirement_text.setPlainText(requirement_body(row))
        self._set_metadata(row)
        self._set_source(row, source_index or {})
        self._set_kb_matches(row.get("kb_matches", []))
        self.status_label.setText(str(row.get("review_status") or "candidate"))
        self.review_text.setPlainText(review_body(row.get("review") or {}))

    def _clear_metadata(self) -> None:
        while self.metadata_grid.count():
            item = self.metadata_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_metadata(self, row: dict[str, Any]) -> None:
        self._clear_metadata()
        metadata = [
            ("req_id", row.get("req_id")),
            ("stable_req_id", row.get("stable_req_id")),
            ("type", row.get("requirement_type")),
            ("object", row.get("object")),
            ("confidence", row.get("confidence")),
            ("ambiguity", row.get("ambiguity")),
        ]
        for index, (key, value) in enumerate(metadata):
            key_label = QLabel(f"{key}:")
            key_label.setMinimumHeight(22)
            value_label = QLabel("" if value is None else str(value))
            value_label.setMinimumHeight(22)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.metadata_grid.addWidget(key_label, index, 0, Qt.AlignTop)
            self.metadata_grid.addWidget(value_label, index, 1, Qt.AlignTop)

    def _set_source(self, row: dict[str, Any], source_index: dict[str, dict[str, Any]]) -> None:
        lines: list[str] = []
        for ref in row.get("source_refs", []):
            source = source_index.get(str(ref), {})
            lines.append(f"[{ref}]")
            if "fields" in source and isinstance(source["fields"], dict):
                for key, value in source["fields"].items():
                    lines.append(f"{key}: {value}")
            else:
                lines.append(str(source.get("text") or source.get("paragraph_text") or ""))
            lines.append("")
        self.source_text.setPlainText("\n".join(lines).strip())

    def _clear_kb_matches(self) -> None:
        while self.kb_layout.count():
            item = self.kb_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_kb_matches(self, matches: list[dict[str, Any]]) -> None:
        self._clear_kb_matches()
        for match in matches:
            label = QLabel(str(match.get("name") or match.get("id") or "term"))
            label.setToolTip(str(match.get("definition") or ""))
            label.setStyleSheet(
                f"background: {fluent.TOKENS['row_hover']}; border-radius: 10px; padding: 3px 8px;"
            )
            self.kb_layout.addWidget(label)
        self.kb_layout.addStretch(1)


def requirement_body(row: dict[str, Any]) -> str:
    text = str(row.get("requirement") or "")
    context = row.get("source_context") if isinstance(row.get("source_context"), dict) else {}
    paragraph = context.get("paragraph_text")
    if paragraph and paragraph != text:
        return f"{text}\n\nContext:\n{paragraph}"
    return text


def review_body(review: dict[str, Any]) -> str:
    if not review:
        return ""
    lines = []
    for key in ("decision", "risk", "confidence"):
        if key in review:
            lines.append(f"{key}: {review[key]}")
    for note in review.get("review_notes", []):
        lines.append(f"- {note}")
    return "\n".join(lines)


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-weight: 600; color: {fluent.TOKENS['text_secondary']};")
    return label
