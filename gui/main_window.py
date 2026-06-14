from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QModelIndex, QThread, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
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
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QStyle,
    QTableView,
    QHeaderView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from export_requirements import export_requirements
from gui import i18n
from gui.detail_panel import DetailPanel
from gui.pipeline_worker import LoadOutputWorker, PipelineWorker
from gui.requirements_model import (
    ConfidenceDelegate,
    HEADERS,
    RequirementsFilterProxyModel,
    RequirementsTableModel,
    StatusDelegate,
    TypeDelegate,
    load_output_bundle,
)
from gui.review_actions import apply_review_action


STATUS_FILTERS = [
    "candidate",
    "llm_reviewed",
    "expert_pending",
    "accepted",
    "rejected",
    "needs_discussion",
    "needs_rework",
    "flagged",
    "frozen",
]


def filter_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("filterLabel")
    return label


class StatCard(QFrame):
    def __init__(self, title: str, hint: str, clicked: Any) -> None:
        super().__init__()
        self.clicked = clicked
        self.setObjectName("statCard")
        self.setProperty("active", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(5)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("statTitle")
        self.value_label = QLabel("0")
        self.value_label.setObjectName("statValue")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("statHint")
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.value_label)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.hint_label, 0, Qt.AlignmentFlag.AlignTop)

    def set_value(self, value: int) -> None:
        self.value_label.setText(f"{value:,}")

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(i18n.APP_TITLE)
        self.resize(1500, 900)
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
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        side_nav = QFrame()
        side_nav.setObjectName("sideNav")
        side_nav.setFixedWidth(108)
        side_layout = QVBoxLayout(side_nav)
        side_layout.setContentsMargins(12, 18, 12, 12)
        side_layout.setSpacing(10)
        nav_mark = QLabel(i18n.UI["nav_mark"])
        nav_mark.setObjectName("navMark")
        nav_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(nav_mark, 0, Qt.AlignmentFlag.AlignHCenter)
        side_layout.addSpacing(16)
        self.nav_review_button = self._nav_button(i18n.UI["nav_review"], QStyle.StandardPixmap.SP_FileDialogContentsView)
        self.nav_review_button.setChecked(True)
        self.nav_document_button = self._nav_button(i18n.UI["nav_document"], QStyle.StandardPixmap.SP_DirOpenIcon)
        self.nav_export_button = self._nav_button(i18n.UI["nav_export"], QStyle.StandardPixmap.SP_DialogSaveButton)
        self.nav_settings_button = self._nav_button(i18n.UI["nav_settings"], QStyle.StandardPixmap.SP_FileDialogDetailedView)
        side_layout.addWidget(self.nav_review_button)
        side_layout.addWidget(self.nav_document_button)
        side_layout.addWidget(self.nav_export_button)
        side_layout.addWidget(self.nav_settings_button)
        side_layout.addStretch(1)
        root_layout.addWidget(side_nav)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        root_layout.addWidget(content, 1)

        app_bar = QFrame()
        app_bar.setObjectName("appBar")
        app_bar.setFixedHeight(78)
        app_bar_layout = QHBoxLayout(app_bar)
        app_bar_layout.setContentsMargins(26, 12, 18, 12)
        app_bar_layout.setSpacing(18)
        self.product_title = QLabel(i18n.APP_TITLE)
        self.product_title.setObjectName("productTitle")
        self.current_document_label = QLabel(f"{i18n.UI['current_document_prefix']}{i18n.UI['current_document_empty']}")
        self.current_document_label.setObjectName("currentDocument")
        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title_layout.addWidget(self.product_title)
        title_layout.addWidget(self.current_document_label)
        self.phase_label = QLabel(i18n.UI["phase"])
        self.phase_label.setObjectName("phasePill")
        self.phase_label.setFixedHeight(28)
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(16)
        brand_layout.addLayout(title_layout)
        brand_layout.addWidget(self.phase_label, 0, Qt.AlignmentFlag.AlignTop)
        brand_layout.addStretch(1)
        self.import_button = QPushButton(i18n.UI["import"])
        self.open_output_button = QPushButton(i18n.UI["open_output"])
        self.run_button = QPushButton(i18n.UI["run"])
        self.run_button.setObjectName("primaryButton")
        self.detail_toggle = QPushButton(i18n.UI["details"])
        self.detail_toggle.setCheckable(True)
        self.detail_toggle.setChecked(True)
        self.detail_toggle.setVisible(False)
        self.stage_label = QLabel(i18n.UI["ready"])
        self.stage_label.setObjectName("stageLabel")
        self.stage_label.setVisible(False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.export_menu_button = QToolButton()
        self.export_menu_button.setText(i18n.UI["export_menu"])
        self.export_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.export_menu_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.run_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.import_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.open_output_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.export_menu_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.detail_toggle.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        export_menu = QMenu(self.export_menu_button)
        self.export_csv_action = export_menu.addAction(i18n.UI["export_csv"])
        self.export_md_action = export_menu.addAction(i18n.UI["export_md"])
        self.export_menu_button.setMenu(export_menu)
        app_bar_layout.addLayout(brand_layout, 1)
        app_bar_layout.addWidget(self.stage_label)
        app_bar_layout.addWidget(self.progress)
        app_bar_layout.addWidget(self.run_button)
        app_bar_layout.addWidget(self.import_button)
        app_bar_layout.addWidget(self.open_output_button)
        app_bar_layout.addWidget(self.export_menu_button)
        app_bar_layout.addWidget(self.detail_toggle)
        content_layout.addWidget(app_bar)

        stat_strip = QFrame()
        stat_strip.setObjectName("statStrip")
        stat_strip.setFixedHeight(118)
        stat_layout = QHBoxLayout(stat_strip)
        stat_layout.setContentsMargins(26, 18, 14, 18)
        stat_layout.setSpacing(16)
        self.total_card = StatCard(i18n.UI["stat_total"], i18n.UI["stat_hint_all"], self.clear_stat_filter)
        self.accepted_card = StatCard(i18n.UI["stat_accepted"], i18n.UI["stat_hint_filter"], lambda: self.apply_status_card_filter("accepted"))
        self.expert_card = StatCard(i18n.UI["stat_expert"], i18n.UI["stat_hint_filter"], lambda: self.apply_status_card_filter("expert_pending"))
        self.ambiguous_card = StatCard(i18n.UI["stat_ambiguous"], i18n.UI["stat_hint_filter"], self.apply_ambiguous_card_filter)
        self.stat_cards = (self.total_card, self.accepted_card, self.expert_card, self.ambiguous_card)
        self.total_card.set_active(True)
        for card in self.stat_cards:
            stat_layout.addWidget(card, 1)
        content_layout.addWidget(stat_strip)

        filters = QFrame()
        filters.setObjectName("filterBar")
        filters.setFixedHeight(72)
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(26, 14, 24, 14)
        filter_layout.setSpacing(12)
        self.type_filter = QComboBox()
        self.type_filter.addItem(i18n.UI["filter_all"], "all")
        self.type_filter.setFixedWidth(150)
        self.status_filter = QComboBox()
        self.status_filter.addItem(i18n.UI["filter_all"], "all")
        self.status_filter.setFixedWidth(150)
        for status in STATUS_FILTERS:
            self.status_filter.addItem(i18n.status_label(status), status)
        self.confidence_filter = QDoubleSpinBox()
        self.confidence_filter.setRange(0.0, 1.0)
        self.confidence_filter.setSingleStep(0.05)
        self.confidence_filter.setDecimals(2)
        self.confidence_filter.setPrefix(i18n.UI["confidence_prefix"])
        self.confidence_filter.setValue(0.70)
        self.proxy.set_min_confidence(0.70)
        self.confidence_filter.setFixedWidth(138)
        self.ambiguity_filter = QCheckBox(i18n.UI["ambiguous_only"])
        self.search_filter = QLineEdit()
        self.search_filter.setPlaceholderText(i18n.UI["search_placeholder"])
        filter_layout.addWidget(filter_label(i18n.UI["filter_type"]))
        filter_layout.addWidget(self.type_filter)
        filter_layout.addWidget(filter_label(i18n.UI["filter_status"]))
        filter_layout.addWidget(self.status_filter)
        filter_layout.addWidget(self.confidence_filter)
        filter_layout.addWidget(self.ambiguity_filter)
        filter_layout.addWidget(self.search_filter, 1)
        content_layout.addWidget(filters)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setWordWrap(True)
        self.table.setObjectName("requirementsTable")
        self.table.setItemDelegateForColumn(HEADERS.index("type"), TypeDelegate(self.table))
        self.table.setItemDelegateForColumn(HEADERS.index("status"), StatusDelegate(self.table))
        self.table.setItemDelegateForColumn(HEADERS.index("confidence"), ConfidenceDelegate(self.table))
        self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(HEADERS.index("requirement"), QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setDefaultSectionSize(120)
        self.table.horizontalHeader().setMinimumSectionSize(70)
        self.table.setColumnWidth(0, 92)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 142)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 98)
        self.table.setColumnWidth(6, 70)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        self.detail_panel = DetailPanel()
        table_panel = QFrame()
        table_panel.setObjectName("tablePanel")
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_header = QFrame()
        table_header.setObjectName("panelHead")
        table_header.setFixedHeight(52)
        table_header_layout = QHBoxLayout(table_header)
        table_header_layout.setContentsMargins(20, 0, 20, 0)
        table_header_layout.setSpacing(12)
        table_title_layout = QVBoxLayout()
        table_title_layout.setSpacing(1)
        table_title = QLabel(i18n.UI["table_title"])
        table_title.setObjectName("panelTitle")
        table_subtitle = QLabel(i18n.UI["table_subtitle"])
        table_subtitle.setObjectName("panelSubtitle")
        table_title_layout.addWidget(table_title)
        table_title_layout.addWidget(table_subtitle)
        self.table_count_label = QLabel(i18n.UI["table_count"].format(visible=0, total=0))
        self.table_count_label.setObjectName("panelSubtitle")
        table_header_layout.addLayout(table_title_layout, 1)
        table_header_layout.addWidget(self.table_count_label)
        table_layout.addWidget(table_header)
        table_layout.addWidget(self.table, 1)

        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(table_panel)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([960, 430])
        content_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        self.output_label = QLabel("")
        self.shortcut_label = QLabel(i18n.UI["shortcuts"])
        status_bar = QStatusBar()
        status_bar.addWidget(self.output_label, 1)
        status_bar.addPermanentWidget(self.shortcut_label)
        self.setStatusBar(status_bar)

    def _connect_signals(self) -> None:
        self.open_output_button.clicked.connect(self.choose_output_dir)
        self.import_button.clicked.connect(self.choose_input_document)
        self.run_button.clicked.connect(self.run_current_document)
        self.detail_toggle.toggled.connect(self.detail_panel.setVisible)
        self.export_csv_action.triggered.connect(lambda: self.export_format("csv"))
        self.export_md_action.triggered.connect(lambda: self.export_format("md"))
        self.nav_review_button.clicked.connect(lambda: self.select_nav(self.nav_review_button))
        self.nav_document_button.clicked.connect(self.nav_import_document)
        self.nav_export_button.clicked.connect(self.nav_export_menu)
        self.nav_settings_button.clicked.connect(self.nav_settings_placeholder)
        self.type_filter.currentIndexChanged.connect(self.on_type_filter_changed)
        self.status_filter.currentIndexChanged.connect(self.on_status_filter_changed)
        self.confidence_filter.valueChanged.connect(self.on_confidence_filter_changed)
        self.ambiguity_filter.toggled.connect(self.on_ambiguity_filter_changed)
        self.search_filter.textChanged.connect(self.on_search_filter_changed)
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

    def _nav_button(self, text: str, icon: QStyle.StandardPixmap) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setIcon(self.style().standardIcon(icon))
        button.setCheckable(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setObjectName("navButton")
        return button

    def select_nav(self, selected: QToolButton) -> None:
        for button in (
            self.nav_review_button,
            self.nav_document_button,
            self.nav_export_button,
            self.nav_settings_button,
        ):
            button.setChecked(button is selected)

    def nav_import_document(self) -> None:
        self.select_nav(self.nav_document_button)
        self.choose_input_document()
        self.select_nav(self.nav_review_button)

    def nav_export_menu(self) -> None:
        self.select_nav(self.nav_export_button)
        position = self.nav_export_button.mapToGlobal(self.nav_export_button.rect().bottomRight())
        self.export_menu_button.menu().popup(position)
        self.select_nav(self.nav_review_button)

    def nav_settings_placeholder(self) -> None:
        self.select_nav(self.nav_settings_button)
        QMessageBox.information(self, i18n.UI["nav_settings"], i18n.UI["settings_placeholder"])
        self.select_nav(self.nav_review_button)

    def on_type_filter_changed(self, _index: int = 0) -> None:
        self.proxy.set_type_filter(str(self.type_filter.currentData() or "all"))
        self.update_table_count()

    def on_status_filter_changed(self, _index: int = 0) -> None:
        self.proxy.set_status_filter(str(self.status_filter.currentData() or "all"))
        self.update_table_count()

    def on_confidence_filter_changed(self, value: float) -> None:
        self.proxy.set_min_confidence(value)
        self.update_table_count()

    def on_ambiguity_filter_changed(self, checked: bool) -> None:
        self.proxy.set_ambiguous_only(checked)
        self.update_table_count()

    def on_search_filter_changed(self, text: str) -> None:
        self.proxy.set_text_filter(text)
        self.update_table_count()

    def set_combo_to_data(self, combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def choose_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, i18n.UI["dlg_open_output"], str(Path.cwd()))
        if path:
            self.open_output_dir(Path(path))

    def open_output_dir(self, out_dir: Path) -> None:
        self.load_output_dir_async(out_dir)

    def choose_input_document(self) -> None:
        input_path, _ = QFileDialog.getOpenFileName(
            self,
            i18n.UI["dlg_import"],
            str(Path.cwd()),
            i18n.UI["doc_filter"],
        )
        if not input_path:
            return
        out_path = QFileDialog.getExistingDirectory(self, i18n.UI["dlg_choose_output"], str(Path(input_path).parent))
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
        self.update_current_document_label()
        worker = PipelineWorker(input_path=input_path, out_dir=out_dir)
        self.start_worker(worker)

    def load_output_dir_async(self, out_dir: Path) -> None:
        self.start_worker(LoadOutputWorker(out_dir))

    def start_worker(self, worker: PipelineWorker | LoadOutputWorker) -> None:
        if self.current_thread is not None:
            QMessageBox.warning(self, i18n.UI["task_running_title"], i18n.UI["task_running_body"])
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
        self.stage_label.setText(i18n.UI["running"])
        self.stage_label.setToolTip(message)
        self.statusBar().showMessage(message, 3000)

    def on_worker_finished(self, payload: dict[str, Any]) -> None:
        bundle = payload.get("bundle")
        if bundle:
            self.apply_bundle(bundle)
        self.stage_label.setText(i18n.UI["ready"])
        self.stage_label.setToolTip("")

    def on_worker_failed(self, message: str) -> None:
        self.stage_label.setText(i18n.UI["failed"])
        self.stage_label.setToolTip(message)
        QMessageBox.critical(self, i18n.UI["task_failed_title"], message)

    def on_thread_finished(self) -> None:
        self.current_thread = None
        self.current_worker = None
        self.set_running(False)

    def set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.import_button.setEnabled(not running)
        self.open_output_button.setEnabled(not running)
        self.export_menu_button.setEnabled(not running)
        self.progress.setVisible(running)

    def apply_bundle(self, bundle: dict[str, Any]) -> None:
        self.model.set_bundle(bundle)
        self.current_out_dir = bundle.get("out_dir")
        self.output_label.setText(f"{i18n.UI['output_dir']}{self.current_out_dir or ''}")
        manifest = bundle.get("manifest") if isinstance(bundle.get("manifest"), dict) else {}
        manifest_input = str(manifest.get("input") or "")
        if manifest_input:
            self.current_input_path = Path(manifest_input)
        self.update_current_document_label()
        self.refresh_type_filter()
        self.refresh_status_summary()
        self.update_table_count()
        if self.proxy.rowCount() > 0:
            first_index = self.proxy.index(0, 0)
            selection_model = self.table.selectionModel()
            selection_model.blockSignals(True)
            self.table.setCurrentIndex(first_index)
            selection_model.blockSignals(False)
            self.show_proxy_row(first_index, pin=False)

    def refresh_type_filter(self) -> None:
        current = str(self.type_filter.currentData() or "all")
        types = sorted({str(row.get("requirement_type") or "") for row in self.model.rows if row.get("requirement_type")})
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem(i18n.UI["filter_all"], "all")
        for requirement_type in types:
            self.type_filter.addItem(i18n.type_label(requirement_type), requirement_type)
        self.set_combo_to_data(self.type_filter, current if current in {"all", *types} else "all")
        self.type_filter.blockSignals(False)
        self.proxy.set_type_filter(str(self.type_filter.currentData() or "all"))
        self.update_table_count()

    def refresh_status_summary(self) -> None:
        rows = self.model.rows
        accepted = sum(1 for row in rows if row.get("review_status") == "accepted")
        expert = sum(1 for row in rows if row.get("review_status") == "expert_pending")
        ambiguous = sum(1 for row in rows if row.get("ambiguity"))
        self.total_card.set_value(len(rows))
        self.accepted_card.set_value(accepted)
        self.expert_card.set_value(expert)
        self.ambiguous_card.set_value(ambiguous)

    def current_document_text(self) -> str:
        if self.current_input_path is not None:
            doc = self.current_input_path.stem
            if self.current_out_dir is not None:
                out_display = f"out/{self.current_out_dir.name}"
                return i18n.UI["current_document_loaded"].format(doc=doc, out_dir=out_display)
            return f"{i18n.UI['current_document_prefix']}{doc}"
        if self.current_out_dir is not None:
            return i18n.UI["current_document_from_output"].format(out_dir=f"out/{self.current_out_dir.name}")
        return f"{i18n.UI['current_document_prefix']}{i18n.UI['current_document_empty']}"

    def update_current_document_label(self) -> None:
        text = self.current_document_text()
        self.current_document_label.setText(text)
        self.current_document_label.setToolTip(text)

    def update_table_count(self) -> None:
        if not hasattr(self, "table_count_label"):
            return
        total = self.model.rowCount()
        visible = self.proxy.rowCount()
        self.table_count_label.setText(
            i18n.UI["table_count"].format(visible=f"{visible:,}", total=f"{total:,}")
        )

    def set_active_stat_card(self, active_card: StatCard) -> None:
        for card in self.stat_cards:
            card.set_active(card is active_card)

    def clear_stat_filter(self) -> None:
        self.set_active_stat_card(self.total_card)
        self.reset_filters()

    def apply_status_card_filter(self, status: str) -> None:
        self.set_active_stat_card(self.accepted_card if status == "accepted" else self.expert_card)
        self.reset_filters(status=status)

    def apply_ambiguous_card_filter(self) -> None:
        self.set_active_stat_card(self.ambiguous_card)
        self.reset_filters(ambiguous=True)

    def reset_filters(self, *, status: str = "all", ambiguous: bool = False, confidence: float = 0.0) -> None:
        widgets = (
            self.type_filter,
            self.status_filter,
            self.confidence_filter,
            self.ambiguity_filter,
            self.search_filter,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self.set_combo_to_data(self.type_filter, "all")
        self.set_combo_to_data(self.status_filter, status)
        self.confidence_filter.setValue(confidence)
        self.ambiguity_filter.setChecked(ambiguous)
        self.search_filter.clear()
        for widget in widgets:
            widget.blockSignals(False)
        self.proxy.set_filters(
            type_filter="all",
            status_filter=status,
            min_confidence=confidence,
            ambiguous_only=ambiguous,
            text_filter="",
        )
        self.update_table_count()

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
        target = current.row()
        before = self.proxy.rowCount()
        try:
            state = apply_review_action(self.current_out_dir, requirement_id, status, reason=f"set {status} from GUI")
        except ValueError as exc:
            QMessageBox.warning(self, i18n.UI["decision_failed_title"], str(exc))
            return
        self.model.replace_row_state(requirement_id, state)
        row["review_state"] = state
        row["review_status"] = state.get("status") or "candidate"
        self.detail_panel.set_requirement(row, self.model.source_index)
        self.refresh_status_summary()
        self.update_table_count()
        after = self.proxy.rowCount()
        if after <= 0:
            return
        next_row = min(target, after - 1) if after < before else min(target + 1, after - 1)
        self.table.selectRow(next_row)

    def export_format(self, fmt: str) -> None:
        if self.current_out_dir is None:
            return
        export_requirements(self.current_out_dir, formats=[fmt])
        self.statusBar().showMessage(i18n.UI["exported"].format(fmt=fmt.upper()), 4000)

    def closeEvent(self, event: Any) -> None:
        if self.current_thread is not None:
            response = QMessageBox.question(self, i18n.UI["close_running_title"], i18n.UI["close_running_body"])
            if response != QMessageBox.Yes:
                event.ignore()
                return
            self.current_thread.quit()
            self.current_thread.wait()
        event.accept()
