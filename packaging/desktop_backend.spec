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
]

spec_generator_modules = [
    "assemble_spec",
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
    "ai_review_actions",
    "doc_annotation_export",
    "desktop_tasks",
    "meter_profile",
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
