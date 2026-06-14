from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui import i18n, llm_settings


class SettingsDialog(QDialog):
    """API / LLM 配置面板。读写 review_pipeline.yaml；密钥只进环境变量。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.UI["settings_title"])
        self.setMinimumWidth(520)
        self.settings = llm_settings.load_llm_settings()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        # --- 接入与鉴权（合并为一组；密钥只进环境变量）---
        self.enable_check = QCheckBox(i18n.UI["settings_enable"])
        self.enable_check.setChecked(self.settings.enabled)
        self.base_url_edit = QLineEdit(self.settings.base_url)
        self.model_edit = QLineEdit(self.settings.model)
        self.api_key_env_edit = QLineEdit(self.settings.api_key_env)
        self.key_status_label = QLabel()
        self.session_key_edit = QLineEdit()
        self.session_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.session_key_edit.setPlaceholderText("sk-…")
        apply_key_button = QPushButton(i18n.UI["settings_apply_session"])
        apply_key_button.clicked.connect(self.apply_session_key)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.addWidget(self.session_key_edit, 1)
        key_row.addWidget(apply_key_button)
        key_row_widget = QWidget()
        key_row_widget.setLayout(key_row)
        note = QLabel(i18n.UI["settings_key_note"])
        note.setWordWrap(True)
        note.setObjectName("panelSubtitle")
        access = QGroupBox(i18n.UI["settings_group_access_auth"])
        access_form = QFormLayout(access)
        access_form.addRow(self.enable_check)
        access_form.addRow(i18n.UI["settings_base_url"], self.base_url_edit)
        access_form.addRow(i18n.UI["settings_model"], self.model_edit)
        access_form.addRow(i18n.UI["settings_api_key_env"], self.api_key_env_edit)
        access_form.addRow(i18n.UI["settings_key_set"], self.key_status_label)
        access_form.addRow(i18n.UI["settings_session_key"], key_row_widget)
        access_form.addRow(note)
        layout.addWidget(access)

        # --- 高级 ---
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setValue(self.settings.temperature)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1, 32768)
        self.max_tokens_spin.setValue(self.settings.max_tokens)
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1.0, 600.0)
        self.timeout_spin.setSingleStep(5.0)
        self.timeout_spin.setValue(self.settings.timeout_s)
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(0, 10)
        self.max_retries_spin.setValue(self.settings.max_retries)
        advanced = QGroupBox(i18n.UI["settings_group_advanced"])
        advanced_form = QFormLayout(advanced)
        advanced_form.addRow(i18n.UI["settings_temperature"], self.temperature_spin)
        advanced_form.addRow(i18n.UI["settings_max_tokens"], self.max_tokens_spin)
        advanced_form.addRow(i18n.UI["settings_timeout"], self.timeout_spin)
        advanced_form.addRow(i18n.UI["settings_max_retries"], self.max_retries_spin)
        layout.addWidget(advanced)

        # --- 审查范围 ---
        self.review_mode_combo = QComboBox()
        for mode in llm_settings.REVIEW_MODES:
            self.review_mode_combo.addItem(mode, mode)
        self.review_mode_combo.setCurrentIndex(max(0, list(llm_settings.REVIEW_MODES).index(self.settings.review_mode)))
        self.confidence_spin = QDoubleSpinBox()
        self.confidence_spin.setRange(0.0, 1.0)
        self.confidence_spin.setSingleStep(0.05)
        self.confidence_spin.setDecimals(2)
        self.confidence_spin.setValue(self.settings.confidence_below)
        scope = QGroupBox(i18n.UI["settings_group_scope"])
        scope_form = QFormLayout(scope)
        scope_form.addRow(i18n.UI["settings_review_mode"], self.review_mode_combo)
        scope_form.addRow(i18n.UI["settings_confidence_below"], self.confidence_spin)
        layout.addWidget(scope)

        # --- 测试调用（真发一次 chat，一次验 连通 + 鉴权 + 模型）---
        self.test_button = QPushButton(i18n.UI["settings_test"])
        self.test_button.clicked.connect(self.run_test)
        self.test_result_label = QLabel("")
        self.test_result_label.setWordWrap(True)
        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.addWidget(self.test_button)
        test_row.addWidget(self.test_result_label, 1)
        layout.addLayout(test_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.UI["settings_save"])
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.UI["settings_cancel"])
        buttons.accepted.connect(self.save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh_key_status()

    def refresh_key_status(self) -> None:
        env_name = self.api_key_env_edit.text().strip() or llm_settings.DEFAULT_API_KEY_ENV
        if llm_settings.api_key_is_set(env_name):
            self.key_status_label.setText(f"{i18n.UI['settings_key_set']}（{llm_settings.masked_api_key(env_name)}）")
        else:
            self.key_status_label.setText(i18n.UI["settings_key_unset"])

    def apply_session_key(self) -> None:
        env_name = self.api_key_env_edit.text().strip() or llm_settings.DEFAULT_API_KEY_ENV
        value = self.session_key_edit.text().strip()
        if value:
            llm_settings.set_session_api_key(env_name, value)
            self.session_key_edit.clear()
        self.refresh_key_status()

    def run_test(self) -> None:
        # 测试前先把密钥框内容应用到本会话 env，这样输入 key 后可直接点测试
        if self.session_key_edit.text().strip():
            self.apply_session_key()
        self.test_button.setEnabled(False)
        self.test_result_label.setText("测试中…")
        try:
            ok, message = llm_settings.test_chat(
                self.base_url_edit.text().strip(),
                self.model_edit.text().strip(),
                self.api_key_env_edit.text().strip() or llm_settings.DEFAULT_API_KEY_ENV,
            )
        finally:
            self.test_button.setEnabled(True)
        color = "#148451" if ok else "#B42318"
        self.test_result_label.setStyleSheet(f"color: {color}; font-weight: 700;")
        self.test_result_label.setText(message)

    def collect(self) -> llm_settings.LlmSettings:
        return llm_settings.LlmSettings(
            enabled=self.enable_check.isChecked(),
            base_url=self.base_url_edit.text(),
            model=self.model_edit.text(),
            api_key_env=self.api_key_env_edit.text(),
            temperature=self.temperature_spin.value(),
            max_tokens=self.max_tokens_spin.value(),
            timeout_s=self.timeout_spin.value(),
            max_retries=self.max_retries_spin.value(),
            review_mode=str(self.review_mode_combo.currentData() or "targeted"),
            confidence_below=self.confidence_spin.value(),
        )

    def save_and_close(self) -> None:
        # 若用户在密钥框输入了但没点「应用」，保存时一并设进本会话 env（仍不落盘）。
        if self.session_key_edit.text().strip():
            self.apply_session_key()
        llm_settings.save_llm_settings(self.collect())
        self.accept()
