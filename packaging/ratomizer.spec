# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"

datas = [
    (str(ROOT / "llm_agents" / "*.yaml"), "llm_agents"),
    (str(ROOT / "domain_packs"), "domain_packs"),
    (str(ROOT / "knowledge_bases" / "*.json"), "knowledge_bases"),
    (str(ROOT / "schemas" / "*.json"), "schemas"),
    (str(ROOT / "gui" / "theme.qss.template"), "gui"),
]

# 装配实现规格生成器 + AI 抽取/批注：被 GUI 的 AssembleSpecWorker / desktop_tasks 惰性
# import（函数体内），且这些是仓库根的顶层模块（未注册进 pyproject py-modules）。显式列出，
# 确保打包收集，否则点「装配实现规格」/「AI 抽取」会在冻结环境里 ModuleNotFoundError。
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
    "desktop_backend",
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
excludes = [
    "tests",
    "tkinter",
    "PySide6.QtNetwork",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]

cli_analysis = Analysis(
    [str(ROOT / "cli.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
cli_pyz = PYZ(cli_analysis.pure)
cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="ratomizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    contents_directory=".",
)

gui_analysis = Analysis(
    [str(ROOT / "gui" / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
gui_pyz = PYZ(gui_analysis.pure)
gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="RequirementAtomizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    contents_directory=".",
)

coll = COLLECT(
    cli_exe,
    gui_exe,
    cli_analysis.binaries,
    cli_analysis.datas,
    gui_analysis.binaries,
    gui_analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RequirementAtomizer",
)
