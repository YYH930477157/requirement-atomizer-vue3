"""Optional OfficeCLI structure hints for DOCX/XLSX parsing.

OfficeCLI is an accelerator, never the source of truth: parser text, source
spans, and table extraction remain owned by Requirement Atomizer.  A missing,
timed-out, or malformed binary therefore produces an honest unavailable status
and leaves the existing parser untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from config import get_env

# v3（bed36f8）：默认 bundled——只发现项目内置二进制，PATH 需显式 auto，off 最优先。
# v4（2026-09-09 Windows 打包验证）：①subprocess 显式 encoding="utf-8"——officecli
# 输出 UTF-8（含 「」），中文 Windows 默认 GBK 解码在 reader 线程抛
# UnicodeDecodeError（被 ValueError 分支吞掉）→ 内置 OfficeCLI 在 zh-CN 机器上
# 永远静默降级 unavailable；②onefile 冻结环境下按内容哈希复制二进制到稳定缓存
# 再执行——officecli 常驻进程锁住被执行的 exe，PyInstaller 退出时删不掉 _MEI*
# 临时解包目录（每次运行泄漏一个完整解包目录）。
# v5：③输入文件同样走稳定副本——officecli 常驻进程对被查看文件**永不释放句柄**
# （实测 30s+ 仍锁），直接查看会把用户的源文档永久锁死（不能移动/删除/改名），
# 测试临时目录也因此清理失败（WinError 32）。副本按 源路径+大小+mtime 哈希落
# 稳定缓存，同一文档版本只复制一次、跨解析复用。
OFFICECLI_ADAPTER_VERSION = "officecli-adapter-v5"
OFFICECLI_ENV = "RATOMIZER_OFFICECLI"
OFFICECLI_PATH_ENV = "RATOMIZER_OFFICECLI_PATH"
_BUNDLED_ROOT = Path(__file__).resolve().parent / "vendor" / "officecli"
_PARAGRAPH_RE = re.compile(r"\[/body/p\[(\d+)\]\] (?:[•·]\s*)?(?:「(?P<quoted>.*?)」|(?P<plain>.*?)) ← (?P<style>[^|\n]+)", re.S)
_LIST_STYLE_RE = re.compile(r"list|bullet|number", re.I)
_DISABLED_MODES = frozenset({"0", "false", "off", "disabled"})
_PATH_MODES = frozenset({"auto", "1", "true", "yes", "on"})
# officecli 的 JSON/标注输出是 UTF-8；绝不能随 Windows locale（zh-CN=GBK）解码。
# cwd 固定为系统临时目录：officecli 常驻进程继承调用方工作目录并持有其句柄，
# 调用方目录（测试临时目录/用户目录）会因此删不掉/被锁。
_SUBPROCESS_KWARGS = {
    "encoding": "utf-8", "errors": "replace",
    "cwd": str(Path(tempfile.gettempdir())),
}


def officecli_mode() -> str:
    return get_env(OFFICECLI_ENV).strip().lower()


def officecli_path() -> str | None:
    setting = officecli_mode()
    if setting in _DISABLED_MODES or setting not in _PATH_MODES | {"bundled"}:
        return None
    configured = os.environ.get(OFFICECLI_PATH_ENV, "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate.resolve()) if candidate.is_file() else None
    bundled = _BUNDLED_ROOT / ("officecli.exe" if sys.platform == "win32" else "officecli")
    if sys.platform in {"darwin", "win32"} and bundled.is_file():
        return str(bundled.resolve())
    candidate = shutil.which("officecli") if setting in _PATH_MODES else None
    if candidate and Path(candidate).is_file():
        return candidate
    return None


def officecli_unavailable_reason() -> str:
    """与路径选择相同优先级的不可用原因，写入 manifest。"""
    setting = officecli_mode()
    if setting in _DISABLED_MODES:
        return "officecli_disabled"
    if setting not in _PATH_MODES | {"bundled"}:
        return "officecli_invalid_mode"
    configured = os.environ.get(OFFICECLI_PATH_ENV, "").strip()
    if configured:
        return "officecli_path_not_a_file"
    return "officecli_not_found"


def _executable_for_invocation(executable: str) -> str:
    """onefile 冻结环境下返回稳定缓存副本的路径；其余场景原样返回。

    onefile 打包把二进制解包进每次运行唯一的 ``_MEI*`` 临时目录，而 officecli
    常驻进程会锁住被执行的 exe——PyInstaller 退出清理 ``_MEI`` 时删不掉，每次
    运行泄漏一个完整解包目录。按内容哈希复制到稳定缓存后，daemon 锁的是缓存
    副本（同一二进制只复制一次）；失败时回退原路径（解析仍可用，泄漏照旧）。
    """
    if not getattr(sys, "frozen", False):
        return executable
    return str(_stable_copy(Path(executable), "ratomizer-officecli", "officecli"))


def _invocation_input(input_path: Path) -> Path:
    """返回输入文档的稳定副本路径；officecli 只被允许查看副本。

    officecli 常驻进程对被查看文件**永不释放句柄**（实测 30s+ 仍锁）——直接查看
    会把用户源文档永久锁死（不能移动/删除/改名），测试临时目录也因此清理失败。
    副本按 源路径+大小+mtime_ns 哈希命名，同一文档版本只复制一次、跨解析复用；
    复制失败时回退原路径（宁可冒锁定风险也不让解析失败）。
    """
    return _stable_copy(input_path, "ratomizer-officecli-inputs", "doc")


def _stable_copy(source: Path, cache_dir_name: str, stem: str) -> Path:
    """按 (路径, 大小, mtime_ns) 哈希把 source 复制到稳定缓存并返回副本路径。

    daemon 长期持有副本句柄（Windows 下删不掉），所以**不做**用后清理——缓存
    增长与"解析过的不同文档/二进制版本数"成正比，有界。
    """
    try:
        stat = source.stat()
        key = hashlib.sha256(
            f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
        ).hexdigest()[:16]
    except OSError:
        return source
    staged = (Path(tempfile.gettempdir()) / cache_dir_name
              / f"{stem}-{key}{source.suffix}")
    if not staged.is_file():
        tmp: Path | None = None
        try:
            staged.parent.mkdir(parents=True, exist_ok=True)
            tmp = staged.with_name(f"{staged.name}.{os.getpid()}.tmp")
            shutil.copy2(source, tmp)
            os.replace(tmp, staged)
        except OSError:
            # 并发竞争/被锁时：另一进程可能已放好同内容副本，存在即复用。
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
            if not staged.is_file():
                return source
    return staged


def enrich_docx_blocks(blocks: list[dict[str, Any]], input_path: Path, *, timeout_s: float = 20.0) -> dict[str, Any]:
    """Apply external DOCX style/path hints to parser-owned blocks in place."""
    executable = officecli_path()
    if executable is None:
        return {"status": "unavailable", "reason": officecli_unavailable_reason(), "blocks_enriched": 0}
    executable = _executable_for_invocation(executable)
    try:
        view_input = _invocation_input(input_path)
        completed = subprocess.run(
            [executable, "view", str(view_input), "annotated", "--json"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
            **_SUBPROCESS_KWARGS,
        )
        if completed.returncode != 0:
            return {"status": "unavailable", "reason": "officecli_nonzero_exit", "blocks_enriched": 0}
        envelope = json.loads(completed.stdout)
        content = str((envelope.get("data") or {}).get("content") or "")
        entries = []
        for match in _PARAGRAPH_RE.finditer(content):
            text = match.group("quoted") if match.group("quoted") is not None else match.group("plain")
            if not (text or "").strip():
                continue
            entries.append({"path": f"/body/p[{match.group(1)}]", "text": text or "", "style": match.group("style").strip()})
        paragraph_blocks = [b for b in blocks if str(b.get("type") or "paragraph") != "table"]
        enriched = 0
        current_path: list[str] = []
        for block, entry in zip(paragraph_blocks, entries):
            if str(block.get("text") or "").strip() != entry["text"].strip():
                continue
            style = entry["style"]
            block["officecli_path"] = entry["path"]
            block["officecli_style"] = style
            block["officecli_is_list_item"] = bool(_LIST_STYLE_RE.search(style))
            if block.get("officecli_is_list_item"):
                block["is_list_item"] = True
            style_is_heading = style.lower().startswith(("heading", "title"))
            if style_is_heading:
                current_path = list(block.get("section_path") or current_path)
            if not style_is_heading and (
                str(block.get("type")) == "heading" and
                (re.search(r"\b(?:shall|must|required|should)\b", str(block.get("text") or ""), re.I)
                 or str(block.get("text") or "").rstrip().endswith((".", ":", ";")))
            ):
                block["type"] = "paragraph"
                block["section_path"] = list(current_path)
            enriched += 1
        # Reclassification can invalidate section paths that were computed while
        # the built-in parser still considered a numbered sentence a heading.
        # Rebuild paths from the enriched style stream, including table blocks.
        current_path = []
        for block in blocks:
            style = str(block.get("officecli_style") or "")
            if style.lower().startswith(("heading", "title")) and str(block.get("type")) == "heading":
                current_path = list(block.get("section_path") or current_path)
            elif current_path:
                block["section_path"] = list(current_path)
        return {"status": "applied", "reason": None, "blocks_enriched": enriched,
                "paragraphs_seen": len(entries), "version": OFFICECLI_ADAPTER_VERSION}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError, ValueError):
        return {"status": "unavailable", "reason": "officecli_read_failed", "blocks_enriched": 0}


def enrich_xlsx_artifacts(blocks: list[dict[str, Any]], table_items: list[dict[str, Any]],
                          table_cell_items: list[dict[str, Any]], input_path: Path,
                          *, timeout_s: float = 20.0) -> dict[str, Any]:
    """Attach OfficeCLI worksheet/cell paths while keeping openpyxl values authoritative."""
    executable = officecli_path()
    if executable is None:
        return {"status": "unavailable", "reason": officecli_unavailable_reason(), "cells_enriched": 0}
    executable = _executable_for_invocation(executable)
    try:
        view_input = _invocation_input(input_path)
        completed = subprocess.run(
            [executable, "view", str(view_input), "text", "--json"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
            **_SUBPROCESS_KWARGS,
        )
        if completed.returncode != 0:
            return {"status": "unavailable", "reason": "officecli_nonzero_exit", "cells_enriched": 0}
        envelope = json.loads(completed.stdout)
        sheets = (envelope.get("data") or {}).get("sheets") or []
        values: dict[tuple[str, str], str] = {}
        for sheet in sheets:
            name = str(sheet.get("name") or "")
            for row in sheet.get("rows") or []:
                for address, value in (row.get("cells") or {}).items():
                    values[(name, str(address))] = str(value)
        enriched = 0
        for cell in table_cell_items:
            key = (str(cell.get("sheet_name") or ""), str(cell.get("a1_address") or ""))
            if key not in values:
                continue
            cell["officecli_path"] = f"/{key[0]}/{key[1]}"
            cell["officecli_value"] = values[key]
            enriched += 1
        for row in table_items:
            sheet = str(row.get("sheet_name") or "")
            row_index = row.get("row_index")
            if sheet and row_index is not None:
                row["officecli_path"] = f"/{sheet}/row[{row_index}]"
        return {"status": "applied", "reason": None, "cells_enriched": enriched,
                "sheets_seen": len(sheets), "version": OFFICECLI_ADAPTER_VERSION}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError, ValueError):
        return {"status": "unavailable", "reason": "officecli_read_failed", "cells_enriched": 0}
