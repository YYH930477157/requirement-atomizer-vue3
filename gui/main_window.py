from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QModelIndex, QThread, QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableView,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from export_requirements import export_requirements
from gui.detail_panel import DetailPanel
from gui.pipeline_worker import LoadOutputWorker, PipelineWorker
from gui.requirements_model import (
    ConfidenceDelegate,
    HEADERS,
    RequirementsFilterProxyModel,
    RequirementsTableModel,
    StatusDelegate,
    load_output_bundle,
)
from gui.review_actions import apply_review_action


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Requirement Atomizer Review Workbench")
        self.resize(1280, 760)
        self.model = RequirementsTableModel()
        self.proxy = RequirementsFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.current_out_dir: Path | None = None
        self.current_input_path: Path | None = None
        self.current_thread: QThread | None = None
        self.current_worker: PipelineWorker | LoadOutputWorker | None = None
        self.pinned_source_row: int | None = None
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self.apply_hover_row)
        self.pending_hover_index: QModelIndex | None = None
        self._build_ui()
        self._connect_signals()
        self._install_shortcuts()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 8)
        root_layout.setSpacing(8)

        toolbar = QFrame()
        toolbar.setObjectName("toolbarCard")
        toolbar_layout = QHBoxLayout(toolbar)
        self.import_button = QPushButton("Import Document")
        self.open_output_button = QPushButton("Open Output Directory")
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("primaryButton")
        self.detail_toggle = QPushButton("Details")
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.setChecked(True)
        self.stage_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.export_csv_button = QPushButton("Export CSV")
        self.export_md_button = QPushButton("Export MD")
        toolbar_layout.addWidget(self.import_button)
        toolbar_layout.addWidget(self.open_output_button)
        toolbar_layout.addSpacing(12)
        toolbar_layout.addWidget(self.run_button)
        toolbar_layout.addWidget(self.progress)
        toolbar_layout.addWidget(self.stage_label, 1)
        toolbar_layout.addWidget(self.detail_toggle)
        toolbar_layout.addWidget(self.export_csv_button)
        toolbar_layout.addWidget(self.export_md_button)
        root_layout.addWidget(toolbar)

        filters = QFrame()
        filters.setObjectName("filterCard")
        filter_layout = QHBoxLayout(filters)
        self.type_filter = QComboBox()
        self.type_filter.addItem("all")
        self.status_filter = QComboBox()
        self.status_filter.addItems(["all", "candidate", "llm_reviewed", "expert_pending", "accepted", "rejected", "needs_discussion"])
        self.confidence_filter = QDoubleSpinBox()
        self.confidence_filter.setRange(0.0, 1.0)
        self.confidence_filter.setSingleStep(0.05)
        self.confidence_filter.setPrefix("confidence >= ")
        self.ambiguity_filter = QCheckBox("ambiguous only")
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText("Search")
        filter_layout.addWidget(QLabel("Type"))
        filter_layout.addWidget(self.type_filter)
        filter_layout.addWidget(QLabel("Status"))
        filter_layout.addWidget(self.status_filter)
        filter_layout.addWidget(self.confidence_filter)
        filter_layout.addWidget(self.ambiguity_filter)
        filter_layout.addWidget(self.search_filter, 1)
        root_layout.addWidget(filters)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setItemDelegateForColumn(HEADERS.index("status"), StatusDelegate(self.table))
        self.table.setItemDelegateForColumn(HEADERS.index("confidence"), ConfidenceDelegate(self.table))
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(HEADERS.index("requirement"), QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 105)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(4, 95)
        self.table.setColumnWidth(5, 145)
        self.table.setColumnWidth(6, 72)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        self.detail_panel = DetailPanel()
        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([860, 400])
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        self.status_summary_label = QLabel("Total 0 | Accepted 0 | Expert 0 | Ambiguous 0")
        self.output_label = QLabel("")
        status_bar = QStatusBar()
        status_bar.addWidget(self.status_summary_label)
        status_bar.addPermanentWidget(self.output_label, 1)
        self.setStatusBar(status_bar)

    def _connect_signals(self) -> None:
        self.open_output_button.clicked.connect(self.choose_output_dir)
        self.import_button.clicked.connect(self.choose_input_document)
        self.run_button.clicked.connect(self.run_current_document)
        self.detail_toggle.toggled.connect(self.detail_panel.setVisible)
        self.export_csv_button.clicked.connect(lambda: self.export_format("csv"))
        self.export_md_button.clicked.connect(lambda: self.export_format("md"))
        self.type_filter.currentTextChanged.connect(self.proxy.set_type_filter)
        self.status_filter.currentTextChanged.connect(self.proxy.set_status_filter)
        self.confidence_filter.valueChanged.connect(self.proxy.set_min_confidence)
        self.ambiguity_filter.toggled.connect(self.proxy.set_ambiguous_only)
        self.search_filter.textChanged.connect(self.proxy.set_text_filter)
        self.table.selectionModel().currentRowChanged.connect(self.on_current_row_changed)
        self.table.clicked.connect(self.on_table_clicked)
        self.table.viewport().installEventFilter(self)
        self.detail_panel.accept_button.clicked.connect(lambda: self.apply_decision("accepted"))
        self.detail_panel.reject_button.clicked.connect(lambda: self.apply_decision("rejected"))
        self.detail_panel.discuss_button.clicked.connect(lambda: self.apply_decision("needs_discussion"))

    def _install_shortcuts(self) -> None:
        for key, status in (("A", "accepted"), ("R", "rejected"), ("D", "needs_discussion"), ("P", "expert_pending")):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda status=status: self.apply_decision(status))
        escape = QShortcut(QKeySequence(Qt.Key_Escape), self)
        escape.activated.connect(self.clear_pin)

    def choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open output directory", str(Path.cwd()))
        if path:
            self.open_output_dir(Path(path))

    def open_output_dir(self, out_dir: Path) -> None:
        self.load_output_dir_async(out_dir)

    def choose_input_document(self) -> None:
        input_path, _ = QFileDialog.getOpenFileName(self, "Import Document", str(Path.cwd()), "Documents (*.docx *.xlsx *.pdf)")
        if not input_path:
            return
        out_path = QFileDialog.getExistingDirectory(self, "Choose output directory", str(Path(input_path).parent))
        if out_path:
            self.run_pipeline(Path(input_path), Path(out_path))

    def load_output_dir(self, out_dir: Path) -> None:
        bundle = load_output_bundle(out_dir)
        self.apply_bundle(bundle)

    def run_current_document(self) -> None:
        if self.current_input_path is None or self.current_out_dir is None:
            self.choose_input_document()
            return
        self.run_pipeline(self.current_input_path, self.current_out_dir)

    def run_pipeline(self, input_path: Path, out_dir: Path) -> None:
        self.current_input_path = input_path
        self.current_out_dir = out_dir
        worker = PipelineWorker(input_path=input_path, out_dir=out_dir)
        self.start_worker(worker)

    def load_output_dir_async(self, out_dir: Path) -> None:
        self.start_worker(LoadOutputWorker(out_dir))

    def start_worker(self, worker: PipelineWorker | LoadOutputWorker) -> None:
        if self.current_thread is not None:
            QMessageBox.warning(self, "Pipeline running", "A background task is already running.")
            return
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.stage.connect(self.on_stage)
        worker.finished.connect(self.on_worker_finished)
        worker.failed.connect(self.on_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self.on_thread_finished)
        self.current_thread = thread
        self.current_worker = worker
        self.set_running(True)
        thread.start()

    def on_stage(self, message: str) -> None:
        self.stage_label.setText(message)

    def on_worker_finished(self, payload: dict[str, Any]) -> None:
        bundle = payload.get("bundle")
        if bundle:
            self.apply_bundle(bundle)
        self.stage_label.setText("Ready")

    def on_worker_failed(self, message: str) -> None:
        self.stage_label.setText("Failed")
        QMessageBox.critical(self, "Background task failed", message)

    def on_thread_finished(self) -> None:
        self.current_thread = None
        self.current_worker = None
        self.set_running(False)

    def set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.import_button.setEnabled(not running)
        self.open_output_button.setEnabled(not running)
        self.progress.setVisible(running)

    def apply_bundle(self, bundle: dict[str, Any]) -> None:
        self.model.set_bundle(bundle)
        self.current_out_dir = bundle.get("out_dir")
        self.output_label.setText(str(self.current_out_dir or ""))
        self.refresh_type_filter()
        self.refresh_status_summary()
        if self.proxy.rowCount() > 0:
            first_index = self.proxy.index(0, 0)
            selection_model = self.table.selectionModel()
            selection_model.blockSignals(True)
            self.table.setCurrentIndex(first_index)
            selection_model.blockSignals(False)
            self.show_proxy_row(first_index, pin=False)

    def refresh_type_filter(self) -> None:
        current = self.type_filter.currentText()
        types = sorted({str(row.get("requirement_type") or "") for row in self.model.rows if row.get("requirement_type")})
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem("all")
        self.type_filter.addItems(types)
        self.type_filter.setCurrentText(current if current in {"all", *types} else "all")
        self.type_filter.blockSignals(False)

    def refresh_status_summary(self) -> None:
        rows = self.model.rows
        accepted = sum(1 for row in rows if row.get("review_status") == "accepted")
        expert = sum(1 for row in rows if row.get("review_status") == "expert_pending")
        ambiguous = sum(1 for row in rows if row.get("ambiguity"))
        self.status_summary_label.setText(f"Total {len(rows)} | Accepted {accepted} | Expert {expert} | Ambiguous {ambiguous}")

    def on_current_row_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if current.isValid():
            self.show_proxy_row(current, pin=True)

    def on_table_clicked(self, index: QModelIndex) -> None:
        source_index = self.proxy.mapToSource(index)
        source_row = source_index.row()
        if self.pinned_source_row == source_row:
            self.clear_pin()
        else:
            self.show_proxy_row(index, pin=True)

    def eventFilter(self, watched: object, event: object) -> bool:
        if watched is self.table.viewport() and event.type() == QEvent.Type.MouseMove and self.pinned_source_row is None:
            position = event.position().toPoint() if hasattr(event, "position") else event.pos()
            index = self.table.indexAt(position)
            if index.isValid():
                self.pending_hover_index = index
                self.hover_timer.start(150)
        return super().eventFilter(watched, event)

    def apply_hover_row(self) -> None:
        if self.pending_hover_index is not None and self.pending_hover_index.isValid() and self.pinned_source_row is None:
            self.show_proxy_row(self.pending_hover_index, pin=False)

    def show_proxy_row(self, index: QModelIndex, *, pin: bool) -> None:
        source_index = self.proxy.mapToSource(index)
        if not source_index.isValid():
            return
        row = self.model.row_at(source_index.row())
        self.detail_panel.set_requirement(row, self.model.source_index)
        self.pinned_source_row = source_index.row() if pin else None
        self.detail_panel.set_pinned(pin)

    def clear_pin(self) -> None:
        self.pinned_source_row = None
        self.detail_panel.set_pinned(False)

    def apply_decision(self, status: str) -> None:
        if self.current_out_dir is None:
            return
        current = self.table.currentIndex()
        if not current.isValid():
            return
        source_index = self.proxy.mapToSource(current)
        row = self.model.row_at(source_index.row())
        requirement_id = str(row.get("stable_req_id") or row.get("req_id") or "")
        if not requirement_id:
            return
        try:
            state = apply_review_action(self.current_out_dir, requirement_id, status, reason=f"set {status} from GUI")
        except ValueError as exc:
            self.stage_label.setText(str(exc))
            return
        self.model.replace_row_state(requirement_id, state)
        row["review_state"] = state
        row["review_status"] = state.get("status") or "candidate"
        self.detail_panel.set_requirement(row, self.model.source_index)
        self.refresh_status_summary()
        self.move_to_next_row()

    def move_to_next_row(self) -> None:
        current = self.table.currentIndex()
        next_row = min(current.row() + 1, self.proxy.rowCount() - 1)
        if next_row >= 0:
            self.table.selectRow(next_row)

    def export_format(self, fmt: str) -> None:
        if self.current_out_dir is None:
            return
        export_requirements(self.current_out_dir, formats=[fmt])
        self.stage_label.setText(f"Exported {fmt}")

    def closeEvent(self, event: Any) -> None:
        if self.current_thread is not None:
            response = QMessageBox.question(self, "Background task running", "Close while a background task is running?")
            if response != QMessageBox.Yes:
                event.ignore()
                return
            self.current_thread.quit()
            self.current_thread.wait()
        event.accept()
