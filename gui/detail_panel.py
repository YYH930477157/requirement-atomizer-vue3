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

from gui import fluent, i18n


class DetailPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("detailPanel")
        self.setMinimumWidth(408)
        self.pinned_label = QLabel("")
        self.detail_subtitle = QLabel(i18n.UI["review_workspace"].format(req_id=i18n.UI["unselected"]))
        self.detail_subtitle.setObjectName("detailSubtitle")
        self.status_label = QLabel(i18n.status_label("candidate"))
        self.status_label.setObjectName("statusBadge")
        self.status_label.setFixedHeight(26)
        self.requirement_text = read_only_text(minimum_height=66)
        self.translation_text = read_only_text(minimum_height=36)
        self.ai_requirement_text = read_only_text(minimum_height=72)
        self.translate_button = QPushButton(i18n.UI["translate"])
        self.translate_button.setEnabled(False)
        self.translate_button.setToolTip(i18n.UI["translate_tip"])
        self.metadata_grid = QGridLayout()
        self.metadata_grid.setContentsMargins(12, 10, 12, 10)
        self.metadata_grid.setVerticalSpacing(8)
        self.metadata_grid.setHorizontalSpacing(12)
        self.source_text = read_only_text(minimum_height=44)
        self.kb_widget = QWidget()
        self.kb_layout = QHBoxLayout(self.kb_widget)
        self.kb_layout.setContentsMargins(0, 0, 0, 0)
        self.kb_layout.setSpacing(6)
        self.kb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.review_text = read_only_text(minimum_height=72)
        self.accept_button = QPushButton(i18n.UI["accept"])
        self.reject_button = QPushButton(i18n.UI["reject"])
        self.discuss_button = QPushButton(i18n.UI["discuss"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("panelHead")
        header.setFixedHeight(52)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 18, 0)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(1)
        title = QLabel(i18n.UI["details"])
        title.setObjectName("detailTitle")
        title_layout.addWidget(title)
        title_layout.addWidget(self.detail_subtitle)
        header_layout.addLayout(title_layout, 1)
        header_layout.addWidget(self.pinned_label)
        header_layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QFrame()
        content.setObjectName("detailContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 12, 18, 8)
        content_layout.setSpacing(8)
        content_layout.addWidget(readonly_card(i18n.UI["sec_requirement_src"], self.requirement_text))
        content_layout.addWidget(readonly_card(i18n.UI["sec_requirement_zh"], self.translation_text, self.translate_button))
        content_layout.addWidget(readonly_card(i18n.UI["sec_requirement_ai"], self.ai_requirement_text))

        self.metadata_widget = QFrame()
        self.metadata_widget.setObjectName("metadataCard")
        self.metadata_widget.setMinimumHeight(170)
        self.metadata_widget.setLayout(self.metadata_grid)
        content_layout.addWidget(self.metadata_widget)

        content_layout.addWidget(readonly_card(i18n.UI["sec_source"], self.source_text, compact=True))
        content_layout.addWidget(kb_card(i18n.UI["sec_kb"], self.kb_widget))
        content_layout.addWidget(readonly_card(i18n.UI["sec_review"], self.review_text, compact=True))

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 2, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        buttons.addWidget(self.accept_button)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.discuss_button)
        content_layout.addLayout(buttons)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self._set_status_badge("candidate")

    def set_pinned(self, pinned: bool) -> None:
        self.pinned_label.setText(i18n.UI["pinned"] if pinned else "")

    def set_requirement(self, row: dict[str, Any] | None, source_index: dict[str, dict[str, Any]] | None = None) -> None:
        if row is None:
            self.detail_subtitle.setText(i18n.UI["review_workspace"].format(req_id=i18n.UI["unselected"]))
            self.requirement_text.clear()
            self.translation_text.clear()
            self.ai_requirement_text.clear()
            self.source_text.clear()
            self.review_text.clear()
            self._clear_metadata()
            self._clear_kb_matches()
            self._set_status_badge("candidate")
            return
        review = row.get("review") if isinstance(row.get("review"), dict) else {}
        req_id = str(row.get("stable_req_id") or row.get("req_id") or "REQ")
        self.detail_subtitle.setText(i18n.UI["review_workspace"].format(req_id=req_id))
        self.requirement_text.setPlainText(str(row.get("requirement") or ""))
        self.translation_text.setPlainText(str(row.get("requirement_zh") or i18n.UI["not_translated"]))
        self.ai_requirement_text.setPlainText(str(review.get("revised_requirement") or i18n.UI["not_reviewed"]))
        self._set_metadata(row, review)
        self._set_source(row, source_index or {})
        self._set_kb_matches(row.get("kb_matches", []))
        self._set_status_badge(str(row.get("review_status") or "candidate"))
        self.review_text.setPlainText(review_body(review))

    def _set_status_badge(self, status: str) -> None:
        text_color, bg_color = fluent.status_colors(status)
        self.status_label.setText(i18n.status_label(status))
        self.status_label.setStyleSheet(
            f"color: {text_color}; background: {bg_color}; border: 0; "
            "border-radius: 999px; padding: 4px 10px; font-weight: 800;"
        )

    def _clear_metadata(self) -> None:
        while self.metadata_grid.count():
            item = self.metadata_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_metadata(self, row: dict[str, Any], review: dict[str, Any]) -> None:
        self._clear_metadata()
        metadata = [
            (i18n.column_label("req_id"), row.get("stable_req_id") or row.get("req_id")),
            (i18n.column_label("type"), i18n.type_label(row.get("requirement_type"))),
            (i18n.column_label("object"), row.get("object")),
            (i18n.column_label("confidence"), fluent.format_confidence(row.get("confidence"))),
            (i18n.column_label("ambiguity"), i18n.UI["yes"] if row.get("ambiguity") else i18n.UI["no"]),
            (i18n.UI["risk"], i18n.risk_label(review.get("risk")) if review.get("risk") else ""),
        ]
        for index, (key, value) in enumerate(metadata):
            row_index = index // 2
            key_column = 0 if index % 2 == 0 else 2
            value_column = key_column + 1
            key_label = QLabel(str(key))
            key_label.setObjectName("metadataKey")
            value_label = QLabel("" if value is None else str(value))
            value_label.setObjectName("metadataValue")
            value_label.setWordWrap(False)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.metadata_grid.addWidget(key_label, row_index, key_column, Qt.AlignmentFlag.AlignTop)
            self.metadata_grid.addWidget(value_label, row_index, value_column, Qt.AlignmentFlag.AlignTop)
        self.metadata_grid.setColumnStretch(1, 1)
        self.metadata_grid.setColumnStretch(3, 1)

    def _set_source(self, row: dict[str, Any], source_index: dict[str, dict[str, Any]]) -> None:
        lines: list[str] = []
        for ref in row.get("source_refs", []):
            source = source_index.get(str(ref), {})
            if "fields" in source and isinstance(source["fields"], dict):
                field_text = i18n.UI["list_separator"].join(f"{key}: {value}" for key, value in source["fields"].items())
                lines.append(f"{ref}{i18n.UI['source_separator']}{field_text}")
            else:
                text = str(source.get("text") or source.get("paragraph_text") or "")
                lines.append(f"{ref}{i18n.UI['source_separator']}{text}" if text else str(ref))
        context = row.get("source_context") if isinstance(row.get("source_context"), dict) else {}
        paragraph = context.get("paragraph_text")
        if paragraph:
            lines.append(str(paragraph))
        self.source_text.setPlainText("\n".join(line for line in lines if line).strip())

    def _clear_kb_matches(self) -> None:
        while self.kb_layout.count():
            item = self.kb_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_kb_matches(self, matches: list[dict[str, Any]]) -> None:
        self._clear_kb_matches()
        if not matches:
            label = chip(i18n.UI["not_reviewed"])
            self.kb_layout.addWidget(label)
        for match in matches[:4]:
            label = chip(str(match.get("name") or match.get("id") or "term"))
            label.setToolTip(str(match.get("definition") or ""))
            self.kb_layout.addWidget(label)
        self.kb_layout.addStretch(1)


def read_only_text(*, minimum_height: int) -> QTextEdit:
    widget = QTextEdit()
    widget.setReadOnly(True)
    widget.setMinimumHeight(minimum_height)
    widget.setObjectName("readOnlyBox")
    widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return widget


def readonly_card(title: str, body: QTextEdit, action: QWidget | None = None, *, compact: bool = False) -> QFrame:
    frame = QFrame()
    frame.setObjectName("readonlyCard" if not compact else "miniCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    head = QFrame()
    head.setObjectName("readonlyHead" if not compact else "miniHead")
    head_layout = QHBoxLayout(head)
    head_layout.setContentsMargins(12, 6, 10, 5)
    title_label = QLabel(title)
    title_label.setObjectName("sectionTitle")
    head_layout.addWidget(title_label)
    head_layout.addStretch(1)
    if action is not None:
        head_layout.addWidget(action)
    layout.addWidget(head)
    layout.addWidget(body)
    return frame


def kb_card(title: str, body: QWidget) -> QFrame:
    frame = QFrame()
    frame.setObjectName("miniCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    head = QFrame()
    head.setObjectName("miniHead")
    head_layout = QHBoxLayout(head)
    head_layout.setContentsMargins(12, 6, 10, 5)
    title_label = QLabel(title)
    title_label.setObjectName("sectionTitle")
    head_layout.addWidget(title_label)
    layout.addWidget(head)
    body_wrap = QWidget()
    body_layout = QHBoxLayout(body_wrap)
    body_layout.setContentsMargins(10, 8, 10, 8)
    body_layout.addWidget(body)
    layout.addWidget(body_wrap)
    return frame


def chip(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("chip")
    return label


def review_body(review: dict[str, Any]) -> str:
    if not review:
        return i18n.UI["not_reviewed"]
    lines = []
    separator = i18n.UI["label_separator"]
    if "decision" in review:
        lines.append(f"{i18n.UI['decision']}{separator}{i18n.decision_label(review['decision'])}")
    if "confidence" in review:
        lines.append(f"{i18n.UI['confidence']}{separator}{review['confidence']}")
    if review.get("review_notes"):
        lines.append(f"{i18n.UI['notes']}{separator}" + i18n.UI["list_separator"].join(str(note) for note in review.get("review_notes", [])))
    if review.get("expert_questions"):
        lines.append(f"{i18n.UI['questions']}{separator}" + i18n.UI["list_separator"].join(str(question) for question in review.get("expert_questions", [])))
    return "\n".join(lines) if lines else i18n.UI["not_reviewed"]
