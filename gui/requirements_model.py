from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from gui import fluent, i18n


HEADERS = ["req_id", "type", "object", "requirement", "confidence", "status", "ambiguity"]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_output_bundle(out_dir: Path) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    states = read_jsonl(out_dir / "review_states.jsonl")
    reviews = read_jsonl(out_dir / "llm_review_results.jsonl")
    blocks = read_jsonl(out_dir / "blocks.jsonl")
    table_items = read_jsonl(out_dir / "table_items.jsonl")
    return {
        "out_dir": out_dir,
        "manifest": read_json(out_dir / "manifest.json"),
        "requirements": enrich_requirements(requirements, states, reviews),
        "source_index": build_source_index(blocks, table_items),
    }


def enrich_requirements(
    requirements: list[dict[str, Any]],
    states: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    states_by_id = index_by_requirement_id(states)
    reviews_by_id = index_by_requirement_id(reviews)
    enriched = []
    for row in requirements:
        item = dict(row)
        identity_values = [str(row.get("stable_req_id") or ""), str(row.get("req_id") or "")]
        item["review_state"] = next((states_by_id[value] for value in identity_values if value in states_by_id), {})
        item["review"] = next((reviews_by_id[value] for value in identity_values if value in reviews_by_id), {})
        item["review_status"] = item["review_state"].get("status") or "candidate"
        enriched.append(item)
    return enriched


def index_by_requirement_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in ("requirement_id", "stable_req_id", "req_id"):
            value = str(row.get(key) or "")
            if value:
                by_id[value] = row
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        for key in ("stable_req_id", "req_id"):
            value = str(metadata.get(key) or "")
            if value:
                by_id[value] = row
    return by_id


def build_source_index(blocks: list[dict[str, Any]], table_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for block in blocks:
        block_id = str(block.get("block_id") or "")
        if block_id:
            index[block_id] = block
    for item in table_items:
        item_id = str(item.get("item_id") or "")
        if item_id:
            index[item_id] = item
    return index


class RequirementsTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []
        self.source_index: dict[str, dict[str, Any]] = {}
        self.out_dir: Path | None = None

    def set_bundle(self, bundle: dict[str, Any]) -> None:
        self.beginResetModel()
        self.rows = list(bundle.get("requirements", []))
        self.source_index = dict(bundle.get("source_index", {}))
        self.out_dir = bundle.get("out_dir")
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        column = HEADERS[index.column()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return display_value(row, column)
        if role == Qt.UserRole:
            return row
        if role == Qt.ToolTipRole and column == "requirement":
            return str(row.get("requirement") or "")
        if role == Qt.TextAlignmentRole and column in {"confidence", "status", "ambiguity"}:
            return Qt.AlignCenter
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return i18n.column_label(HEADERS[section])
        return section + 1

    def row_at(self, row: int) -> dict[str, Any]:
        return self.rows[row]

    def replace_row_state(self, requirement_id: str, state: dict[str, Any]) -> None:
        for row_index, row in enumerate(self.rows):
            if requirement_id in {str(row.get("stable_req_id") or ""), str(row.get("req_id") or "")}:
                row["review_state"] = state
                row["review_status"] = state.get("status") or "candidate"
                left = self.index(row_index, 0)
                right = self.index(row_index, self.columnCount() - 1)
                self.dataChanged.emit(left, right, [Qt.DisplayRole, Qt.UserRole])
                return


def display_value(row: dict[str, Any], column: str) -> str:
    if column == "type":
        return i18n.type_label(row.get("requirement_type"))
    if column == "status":
        return str(row.get("review_status") or "candidate")
    if column == "ambiguity":
        return i18n.UI["yes"] if row.get("ambiguity") else i18n.UI["no"]
    value = row.get(column)
    if column == "confidence":
        return fluent.format_confidence(value)
    return "" if value is None else str(value)


class RequirementsFilterProxyModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.type_filter = "all"
        self.status_filter = "all"
        self.min_confidence = 0.0
        self.ambiguous_only = False
        self.text_filter = ""
        self.setDynamicSortFilter(True)

    def set_type_filter(self, value: str) -> None:
        self.type_filter = value
        self.refresh_filter()

    def set_status_filter(self, value: str) -> None:
        self.status_filter = value
        self.refresh_filter()

    def set_min_confidence(self, value: float) -> None:
        self.min_confidence = value
        self.refresh_filter()

    def set_ambiguous_only(self, value: bool) -> None:
        self.ambiguous_only = value
        self.refresh_filter()

    def set_text_filter(self, value: str) -> None:
        self.text_filter = value.casefold()
        self.refresh_filter()

    def set_filters(
        self,
        *,
        type_filter: str,
        status_filter: str,
        min_confidence: float,
        ambiguous_only: bool,
        text_filter: str,
    ) -> None:
        self.type_filter = type_filter
        self.status_filter = status_filter
        self.min_confidence = min_confidence
        self.ambiguous_only = ambiguous_only
        self.text_filter = text_filter.casefold()
        self.refresh_filter()

    def refresh_filter(self) -> None:
        self.beginFilterChange()
        self.endFilterChange()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, RequirementsTableModel):
            return False
        row = model.row_at(source_row)
        if self.type_filter != "all" and row.get("requirement_type") != self.type_filter:
            return False
        if self.status_filter != "all" and row.get("review_status") != self.status_filter:
            return False
        try:
            if float(row.get("confidence") or 0) < self.min_confidence:
                return False
        except (TypeError, ValueError):
            return False
        if self.ambiguous_only and not row.get("ambiguity"):
            return False
        if self.text_filter:
            haystack = " ".join(
                str(row.get(key) or "")
                for key in ("req_id", "stable_req_id", "requirement_type", "object", "requirement", "domain")
            ).casefold()
            if self.text_filter not in haystack:
                return False
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        if HEADERS[left.column()] == "confidence":
            return float(left.data() or 0) < float(right.data() or 0)
        return str(left.data() or "") < str(right.data() or "")


def pill_rect(option: QStyleOptionViewItem, text: str) -> QRect:
    height = min(26, max(20, option.rect.height() - 18))
    width = min(option.rect.width() - 12, max(54, option.fontMetrics.horizontalAdvance(text) + 22))
    rect = QRect(0, 0, width, height)
    rect.moveCenter(option.rect.center())
    return rect


def paint_cell_background(painter: QPainter, option: QStyleOptionViewItem) -> None:
    if option.state & QStyle.StateFlag.State_Selected:
        painter.fillRect(option.rect, QColor(fluent.TOKENS["row_selected"]))


class TypeDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if HEADERS[index.column()] != "type":
            super().paint(painter, option, index)
            return
        text = str(index.data() or "")
        row = index.data(Qt.ItemDataRole.UserRole)
        raw_type = str(row.get("requirement_type") or "") if isinstance(row, dict) else ""
        text_color, bg_color = fluent.type_colors(raw_type)
        painter.save()
        paint_cell_background(painter, option)
        rect = pill_rect(option, text)
        shown = option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, max(1, rect.width() - 12))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg_color))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(QPen(QColor(text_color)))
        painter.drawText(rect, Qt.AlignCenter, shown)
        painter.restore()


class StatusDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if HEADERS[index.column()] != "status":
            super().paint(painter, option, index)
            return
        status = str(index.data() or "candidate")
        label = i18n.status_label(status)
        text_color, bg_color = fluent.status_colors(status)
        painter.save()
        paint_cell_background(painter, option)
        rect = pill_rect(option, label)
        shown = option.fontMetrics.elidedText(label, Qt.TextElideMode.ElideRight, max(1, rect.width() - 12))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg_color))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(QPen(QColor(text_color)))
        painter.drawText(rect, Qt.AlignCenter, shown)
        painter.restore()


class ConfidenceDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if HEADERS[index.column()] != "confidence":
            super().paint(painter, option, index)
            return
        try:
            confidence = float(index.data() or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        painter.save()
        paint_cell_background(painter, option)
        dot_rect = QRect(option.rect.left() + 12, option.rect.center().y() - 4, 9, 9)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fluent.confidence_color(confidence)))
        painter.drawEllipse(dot_rect)
        painter.setPen(QPen(QColor(fluent.TOKENS["text_primary"])))
        painter.drawText(option.rect.adjusted(24, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, fluent.format_confidence(confidence))
        painter.restore()
