from __future__ import annotations


APP_TITLE = "标准需求抽取与审查平台"

UI = {
    "import": "导入文档",
    "open_output": "打开输出目录",
    "run": "运行",
    "details": "详情",
    "export": "导出",
    "export_csv": "导出 CSV",
    "export_md": "导出 MD",
    "export_menu": "导出 v",
    "ready": "就绪",
    "failed": "失败",
    "running": "运行中",
    "nav_review": "审查",
    "nav_document": "文档",
    "nav_export": "导出",
    "nav_settings": "设置",
    "filter_type": "类型",
    "filter_status": "状态",
    "filter_all": "全部",
    "confidence_prefix": "置信度 ≥ ",
    "ambiguous_only": "仅歧义",
    "search": "搜索",
    "search_placeholder": "搜索需求、对象或编号",
    "phase": "GUI Phase 1",
    "nav_mark": "标",
    "current_document_prefix": "当前文档：",
    "current_document_loaded": "当前文档：{doc} · {out_dir}",
    "current_document_from_output": "当前文档：{out_dir}",
    "table_title": "需求表格",
    "table_subtitle": "中文表头与显示映射，底层 row 值保持英文",
    "table_count": "显示 {start}-{end} / {total}",
    "stat_hint_all": "全部",
    "stat_hint_filter": "筛选",
    "output_dir": "输出目录：",
    "shortcuts": "快捷键 A 接受 · R 拒绝 · D 讨论 · P 钉住",
    "review_workspace": "{req_id} · 审查工作区",
    "sec_requirement_src": "① 原始需求",
    "sec_requirement_zh": "② 中文翻译",
    "sec_requirement_ai": "③ AI 理解的需求",
    "sec_metadata": "元数据",
    "sec_source": "溯源原文",
    "sec_kb": "知识库匹配",
    "sec_review": "评审",
    "accept": "接受",
    "reject": "拒绝",
    "discuss": "讨论",
    "pinned": "已钉住",
    "stat_total": "总数",
    "stat_accepted": "已接受",
    "stat_expert": "待专家",
    "stat_ambiguous": "歧义",
    "not_translated": "（尚未翻译，将在后续版本接入）",
    "not_reviewed": "（尚未经 LLM 审查）",
    "translate": "翻译",
    "translate_tip": "后续版本接入",
    "settings_placeholder": "设置将在后续版本接入。",
    "dlg_open_output": "打开输出目录",
    "dlg_import": "导入文档",
    "dlg_choose_output": "选择输出目录",
    "doc_filter": "文档 (*.docx *.xlsx *.pdf)",
    "task_running_title": "任务进行中",
    "task_running_body": "已有后台任务在运行。",
    "task_failed_title": "后台任务失败",
    "close_running_title": "后台任务运行中",
    "close_running_body": "后台任务仍在运行，确定关闭？",
    "exported": "已导出 {fmt}",
    "current_document_empty": "未选择文档",
}

COLUMN_LABELS = {
    "req_id": "编号",
    "type": "类型",
    "object": "对象",
    "requirement": "需求",
    "confidence": "置信度",
    "status": "状态",
    "ambiguity": "歧义",
}

TYPE_LABELS = {
    "cosem_attribute_access": "COSEM 属性访问",
    "cosem_object_instance": "COSEM 对象实例",
    "cosem_object": "COSEM 对象",
    "table_value_matrix": "表值矩阵",
    "measurement_quantity_unit": "计量量纲单位",
    "event_definition": "事件定义",
    "event_group_retention": "事件组留存",
    "event": "事件",
    "access_control": "访问控制",
    "association_security_matrix": "关联安全矩阵",
    "security": "安全",
    "security_policy_bit": "安全策略位",
    "security_policy_state": "安全策略状态",
    "security_suite_definition": "安全套件定义",
    "flag_definition": "标志位定义",
    "capability_matrix": "能力矩阵",
    "communication": "通信",
    "functional": "功能性",
}

STATUS_LABELS = {
    "candidate": "候选",
    "llm_reviewed": "已机审",
    "expert_pending": "待专家",
    "accepted": "已接受",
    "rejected": "已拒绝",
    "needs_discussion": "待讨论",
    "needs_rework": "待返工",
    "flagged": "已标记",
    "frozen": "已冻结",
}

RISK_LABELS = {
    "low_risk": "低风险",
    "medium_risk": "中风险",
    "high_risk": "高风险",
}

DECISION_LABELS = {
    "accept": "接受",
    "accepted": "接受",
    "reject": "拒绝",
    "rejected": "拒绝",
    "needs_expert": "需要专家",
    "needs_discussion": "需要讨论",
    "revise": "需要修订",
}


def type_label(value: object) -> str:
    text = str(value or "")
    return TYPE_LABELS.get(text, text)


def status_label(value: object) -> str:
    text = str(value or "")
    return STATUS_LABELS.get(text, text)


def column_label(value: object) -> str:
    text = str(value or "")
    return COLUMN_LABELS.get(text, text)


def risk_label(value: object) -> str:
    text = str(value or "")
    return RISK_LABELS.get(text, text)


def decision_label(value: object) -> str:
    text = str(value or "")
    return DECISION_LABELS.get(text, text)
