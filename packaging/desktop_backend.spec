# -*- mode: python ; coding: utf-8 -*-
# Electron 桌面端后端：desktop_backend.py → onefile ratomizer-desktop.exe
# 复用 ratomizer.spec 的 hiddenimports（生成器/AI 抽取/io_utils 等惰性 import 模块），
# 否则 onefile 冻结环境会 ModuleNotFoundError。
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
DIST_DIR = ROOT / "dist-backend"

datas = [
    (str(ROOT / "llm_agents" / "*.yaml"), "llm_agents"),
    (str(ROOT / "domain_packs"), "domain_packs"),
    (str(ROOT / "knowledge_bases" / "*.json"), "knowledge_bases"),
    (str(ROOT / "schemas" / "*.json"), "schemas"),
    (str(ROOT / "golden_sets" / "claim_ledger_v1"), "golden_sets/claim_ledger_v1"),
    (str(ROOT / "parsers" / "data"), "parsers/data"),
]

spec_generator_modules = [
    "assemble_spec",
    "blue_book_ingest",
    "blue_book_lookup",
    "spec_export",
    "spec_excel",
    "spec_enrich",
    "engineering_composer",
    "cosem_object_model",
    "cosem_access_security",
    "cosem_behavior_spec",
    "cosem_external_refs",
    "requirement_schema",
    "text_normalize",
    "io_utils",
    "ai_extract",
    "merged_consistency",
    "review_insights",
    "template_writer",
    "corpus_eval",
    "clarification_report",
    "compliance",
    "xlsx_io",
    "requirement_record",
    "adjudication_bank",
    "extract_units",
    "extract_guards",
    "config",
    "claim_artifacts",
    "claim_acceptance",
    "claim_catalog",
    "claim_held_out",
    "claim_ledger",
    "claim_review_import",
    "claim_review_packet",
    "normative_framing",
    "source_spans",
    "ai_review_actions",
    "doc_annotation_export",
    "desktop_tasks",
    "meter_profile",
    "requirements_analysis",
    "requirements_analysis_agent",
    "requirements_analysis_excel",
    "requirements_analysis_rules",
    "requirements_analysis_schema",
    "requirements_analysis_template",
    # 影印支路/点解析（函数内惰性 import,静态分析看不到——缺了冻结包里 COM/点解析静默死亡）
    "doc_facsimile",
    "spot_extract",
    # Office COM 影印转换（pywin32 晚绑定 Dispatch,无需 makepy 生成层）
    "pythoncom",
    "win32com",
    "win32com.client",
]

hiddenimports = (
    collect_submodules("docx")
    + collect_submodules("yaml")
    + collect_submodules("openpyxl")
    + collect_submodules("pdfplumber")
    + collect_submodules("requirement_kb")
    + spec_generator_modules
)

a = Analysis(
    [str(ROOT / "desktop_backend.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ratomizer-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
