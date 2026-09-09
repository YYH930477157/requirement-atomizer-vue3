"""Optional OfficeCLI structure hints for DOCX/XLSX parsing.

OfficeCLI is an accelerator, never the source of truth: parser text, source
spans, and table extraction remain owned by Requirement Atomizer.  A missing,
timed-out, or malformed binary therefore produces an honest unavailable status
and leaves the existing parser untouched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from config import get_env

# 默认只发现项目内置版本；系统 PATH 需显式 auto，off 始终优先。
OFFICECLI_ADAPTER_VERSION = "officecli-adapter-v3"
OFFICECLI_ENV = "RATOMIZER_OFFICECLI"
OFFICECLI_PATH_ENV = "RATOMIZER_OFFICECLI_PATH"
_BUNDLED_ROOT = Path(__file__).resolve().parent / "vendor" / "officecli"
_PARAGRAPH_RE = re.compile(r"\[/body/p\[(\d+)\]\] (?:[•·]\s*)?(?:「(?P<quoted>.*?)」|(?P<plain>.*?)) ← (?P<style>[^|\n]+)", re.S)
_LIST_STYLE_RE = re.compile(r"list|bullet|number", re.I)
_DISABLED_MODES = frozenset({"0", "false", "off", "disabled"})
_PATH_MODES = frozenset({"auto", "1", "true", "yes", "on"})


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


def enrich_docx_blocks(blocks: list[dict[str, Any]], input_path: Path, *, timeout_s: float = 20.0) -> dict[str, Any]:
    """Apply external DOCX style/path hints to parser-owned blocks in place."""
    executable = officecli_path()
    if executable is None:
        return {"status": "unavailable", "reason": officecli_unavailable_reason(), "blocks_enriched": 0}
    try:
        completed = subprocess.run(
            [executable, "view", str(input_path), "annotated", "--json"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
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
    try:
        completed = subprocess.run(
            [executable, "view", str(input_path), "text", "--json"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
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
