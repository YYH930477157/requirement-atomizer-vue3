"""Whole-document bilingual delivery backed by the annotation translation cache."""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

from api_server import ANNOTATION_TRANSLATION_GUARDS_VERSION, translation_key
from io_utils import read_jsonl
from process_file_lock import process_file_lock
from result_package import governed_artifact_path


FULL_TRANSLATION_VERSION = "full-translation-v2"
DOCUMENT_TRANSLATION_SCHEMA_VERSION = "document-translation/v2"
FULL_TRANSLATION_ENV = "RATOMIZER_FULL_TRANSLATION"
DOCUMENT_TRANSLATIONS = "document_translations.jsonl"
DOCUMENT_TRANSLATION_HTML = "document_translation.html"
CLARIFICATION_BILINGUAL_HTML = "clarification_questions_bilingual.html"
_REPLACE_ATTEMPTS = 5
_LATIN_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SYNTHETIC_HEADER_RE = re.compile(r"^column_\d+(?:_\d+)?$", re.IGNORECASE)
_LETTERED_HEADER_RE = re.compile(r"^\s*\([a-jA-J]\)\s*")


def full_translation_enabled(value: str | None = None) -> bool:
    raw = os.environ.get(FULL_TRANSLATION_ENV, "1") if value is None else value
    return str(raw or "").strip().lower() not in {"0", "false", "no", "off"}


def _block_text(block: dict[str, Any]) -> str:
    return str(block.get("text") or block.get("raw_text") or "").strip()


def _looks_translatable(text: str) -> bool:
    latin = len(_LATIN_RE.findall(text))
    return latin >= 3 and latin >= len(_CJK_RE.findall(text))


def _clarification_texts(report: dict[str, Any]) -> Iterable[str]:
    fields = ("source_text", "source_quote", "original_text", "evidence", "context")
    for entry in report.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for field in fields:
            value = str(entry.get(field) or "").strip()
            if value and _looks_translatable(value):
                yield value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt + 1 >= _REPLACE_ATTEMPTS:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)


def _clean_header(value: Any) -> str:
    text = str(value or "").strip()
    if _SYNTHETIC_HEADER_RE.fullmatch(text):
        return ""
    return _LETTERED_HEADER_RE.sub("", text).strip()


def _padded_cells(row: Any, width: int) -> list[str]:
    cells = [str(cell or "") for cell in (row if isinstance(row, (list, tuple)) else [row])]
    return (cells + [""] * max(0, width - len(cells)))[:width]


def _row_render_line(headers: list[str], row: Any) -> str:
    # Keep the same byte-level row rendering contract used by ai_extract/spot_extract.
    from ai_extract import _row_render_line as shared_row_render_line

    return shared_row_render_line(headers, list(row) if isinstance(row, (list, tuple)) else [row])


def _fallback_header(block: dict[str, Any], headers: list[str]) -> bool:
    status = str(block.get("header_detection_status") or "").lower()
    non_empty = [str(value or "").strip() for value in headers if str(value or "").strip()]
    return status == "fallback" or bool(
        non_empty and all(_SYNTHETIC_HEADER_RE.fullmatch(value) for value in non_empty)
    )


def _regular_table_plan(block: dict[str, Any]) -> dict[str, Any] | None:
    from table_structure import normalize_merge_ranges, physical_data_row_indexes

    if str(block.get("type") or block.get("block_type") or "") != "table":
        return None
    if block.get("nested_tables"):
        return None
    merge_ranges = normalize_merge_ranges(block.get("merge_ranges") or [])
    if any(min_row != max_row for min_row, _min_col, max_row, _max_col in merge_ranges):
        return None
    raw_headers = [str(value or "").strip() for value in (block.get("headers") or [])]
    raw_header_rows = [row for row in (block.get("header_rows") or []) if isinstance(row, (list, tuple))]
    data_rows = [row for row in (block.get("data_rows") or []) if isinstance(row, (list, tuple))]
    width = max(
        [len(raw_headers), *(len(row) for row in raw_header_rows), *(len(row) for row in data_rows)],
        default=0,
    )
    if width <= 0:
        return None
    headers = _padded_cells(raw_headers, width)
    display_headers = [_clean_header(value) for value in headers]
    fallback = _fallback_header(block, headers)
    units: list[dict[str, Any]] = []
    table_id = str(block.get("table_id") or "")
    block_id = str(block.get("block_id") or "")
    title = str(block.get("table_title") or "").strip()
    if title:
        units.append({
            "unit_id": f"{block_id}:title",
            "role": "title",
            "row_index": None,
            "source_cells": [title],
            "source_text": title,
        })
    header_indexes = list(block.get("header_row_indexes") or [])
    if not fallback:
        for offset, raw_row in enumerate(raw_header_rows, start=1):
            cells = [_clean_header(cell) for cell in _padded_cells(raw_row, width)]
            if not any(cells):
                continue
            units.append({
                "unit_id": f"{block_id}:header:{offset}",
                "role": "header",
                "row_index": int(header_indexes[offset - 1]) if offset <= len(header_indexes) else offset,
                "source_cells": cells,
                "source_text": _row_render_line(display_headers, cells),
            })
        if not raw_header_rows and any(display_headers):
            units.append({
                "unit_id": f"{block_id}:header:1",
                "role": "header",
                "row_index": 1,
                "source_cells": display_headers,
                "source_text": _row_render_line(display_headers, display_headers),
            })
    else:
        for offset, raw_row in enumerate(raw_header_rows, start=1):
            cells = _padded_cells(raw_row, width)
            if not any(cell.strip() for cell in cells):
                continue
            units.append({
                "unit_id": f"{block_id}:data:fallback-header:{offset}",
                "role": "data",
                "row_index": int(header_indexes[offset - 1]) if offset <= len(header_indexes) else offset,
                "source_cells": cells,
                "source_text": _row_render_line(display_headers, cells),
            })
    data_indexes = physical_data_row_indexes(block)
    for offset, raw_row in enumerate(data_rows, start=1):
        cells = _padded_cells(raw_row, width)
        units.append({
            "unit_id": f"{block_id}:data:{offset}",
            "role": "data",
            "row_index": int(data_indexes[offset - 1]) if offset <= len(data_indexes) else offset,
            "source_cells": cells,
            "source_text": _row_render_line(display_headers, cells),
        })
    return {
        "table_id": table_id,
        "title": title,
        "column_count": width,
        "headers": display_headers,
        "header_detection_status": str(block.get("header_detection_status") or ""),
        "header_fallback": fallback,
        "rebuilt": block.get("table_source") == "text_layout",
        "merge_ranges": [list(entry) for entry in merge_ranges],
        "units": units,
    }


def _unit_disposition(
    unit: dict[str, Any],
    *,
    enabled: bool,
    sidecar: dict[str, dict[str, Any]],
    translation_summary: dict[str, Any],
) -> dict[str, Any]:
    source = str(unit.get("source_text") or "").strip()
    key = translation_key(source) if source else ""
    entry = sidecar.get(key, {}) if key else {}
    translation = str(entry.get("translation") or "").strip()
    if not source:
        status, reason = "skipped", "empty_text"
    elif not enabled:
        status, reason = "skipped", "feature_disabled"
    elif translation and not entry.get("rejected"):
        status, reason = "translated", ""
    else:
        status = "failed"
        reason = str(entry.get("status") or entry.get("reason") or "")
        if not reason:
            reason = (
                "llm_unavailable"
                if translation_summary.get("route") == "stub"
                else "missing_cache_entry"
            )
    return {
        **unit,
        "status": status,
        "reason": reason,
        "translation": translation if status == "translated" else "",
        "translation_key": key,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "model": entry.get("model") or translation_summary.get("model") or "",
        "strategy_version": entry.get("strategy_version") or "",
    }


def _status_target(value: dict[str, Any]) -> str:
    translation = html.escape(str(value.get("translation") or ""))
    if translation:
        return translation
    status = html.escape(str(value.get("status") or ""))
    reason = html.escape(str(value.get("reason") or ""))
    return f'<span class="translation-failure">[{status}] {reason}</span>'


def _render_source_cells(
    unit: dict[str, Any],
    *,
    width: int,
    tag: str,
    merge_ranges: list[list[int]],
) -> str:
    cells = _padded_cells(unit.get("source_cells") or [], width)
    row_index = unit.get("row_index")
    spans = {
        int(min_col): int(max_col) - int(min_col) + 1
        for min_row, min_col, max_row, max_col in merge_ranges
        if row_index is not None and int(min_row) == int(row_index) == int(max_row)
    }
    rendered: list[str] = []
    column = 1
    while column <= width:
        span = max(1, spans.get(column, 1))
        colspan = f' colspan="{span}"' if span > 1 else ""
        rendered.append(f"<{tag}{colspan}>{html.escape(cells[column - 1])}</{tag}>")
        column += span
    return "".join(rendered)


def _render_table_html(row: dict[str, Any]) -> str:
    table = dict(row.get("table") or {})
    width = max(1, int(table.get("column_count") or 1))
    units = [unit for unit in (table.get("rows") or []) if isinstance(unit, dict)]
    title = next((unit for unit in units if unit.get("role") == "title"), None)
    headers = [unit for unit in units if unit.get("role") == "header"]
    data_rows = [unit for unit in units if unit.get("role") == "data"]
    merge_ranges = [
        list(entry) for entry in (table.get("merge_ranges") or [])
        if isinstance(entry, (list, tuple)) and len(entry) == 4
    ]
    caption_source = html.escape(str((title or {}).get("source_text") or table.get("title") or ""))
    caption_translation = _status_target(title) if title else ""
    badge = '<span class="table-badge">无画线重建</span>' if table.get("rebuilt") else ""
    fallback = '<span class="table-note">无表头（结构未识别）</span>' if table.get("header_fallback") else ""
    caption = (
        f"<figcaption><span>{caption_source}</span>"
        f"<span class=\"caption-translation\">{caption_translation}</span>{badge}{fallback}</figcaption>"
        if caption_source or badge or fallback else ""
    )
    head_parts: list[str] = []
    for unit in headers:
        head_parts.append(
            '<tr class="source-row">'
            + _render_source_cells(
                unit, width=width, tag="th", merge_ranges=merge_ranges
            )
            + "</tr>"
        )
        head_parts.append(
            f'<tr class="translation-row"><th colspan="{width}">{_status_target(unit)}</th></tr>'
        )
    body_parts: list[str] = []
    for unit in data_rows:
        body_parts.append(
            '<tr class="source-row">'
            + _render_source_cells(
                unit, width=width, tag="td", merge_ranges=merge_ranges
            )
            + "</tr>"
        )
        body_parts.append(
            f'<tr class="translation-row"><td colspan="{width}">{_status_target(unit)}</td></tr>'
        )
    anchor = html.escape(str(row.get("block_id") or ""), quote=True)
    thead = f"<thead>{''.join(head_parts)}</thead>" if head_parts else ""
    return (
        f'<section class="table-pair" id="pair-{anchor}"><header>{anchor} · 表格中英对照</header>'
        f'<figure class="doc-table">{caption}<div class="table-scroll"><table>{thead}'
        f"<tbody>{''.join(body_parts)}</tbody></table></div></figure></section>"
    )


def _render_document_html(rows: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for row in rows:
        if row.get("record_kind") == "table":
            sections.append(_render_table_html(row))
            continue
        block_id = str(row.get("block_id") or "")
        source = html.escape(str(row.get("source_text") or ""))
        target = _status_target(row)
        anchor = html.escape(block_id, quote=True)
        extra = ""
        if row.get("record_kind") == "complex_table":
            extra = '<div class="table-note">复杂表按原文展示</div>'
        sections.append(
            f'<section class="pair" id="pair-{anchor}">'
            f'<article id="src-{anchor}"><header>{anchor} · EN '
            f'<a href="#zh-{anchor}">中文</a></header>{extra}<p>{source}</p></article>'
            f'<article id="zh-{anchor}" class="translation"><header>{anchor} · 中文 '
            f'<a href="#src-{anchor}">EN</a></header><p>{target}</p></article></section>'
        )
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>全文中英对照</title>
<style>body{margin:0;font:15px/1.65 system-ui,sans-serif;color:#17202a;background:#f5f7f8}
main{max-width:1280px;margin:auto;padding:24px}.pair{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #cbd3d8;background:white}
article{padding:16px 20px;min-width:0}.translation{background:#f7fbf8;border-left:1px solid #d7dfdc}header{font-size:12px;color:#53636d}
p{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#176b4d}.table-pair{border-top:1px solid #cbd3d8;background:#fff;padding:16px 20px}
.doc-table{margin:8px 0 0}.doc-table figcaption{font-size:13px;font-weight:650;color:#344252;margin-bottom:8px}.caption-translation{display:block;color:#176b4d;font-weight:500}
.table-badge,.table-note{display:inline-block;margin-left:8px;color:#6b7280;font-size:11px;font-weight:500}.table-scroll{overflow-x:auto;border:1px solid #dfe5e8;border-radius:6px}
.doc-table table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.5}.doc-table th,.doc-table td{padding:8px 10px;border-right:1px solid #edf0f2;border-bottom:1px solid #e6eaed;text-align:left;vertical-align:top;overflow-wrap:anywhere}
.doc-table th:last-child,.doc-table td:last-child{border-right:0}.source-row:nth-of-type(4n+1) td{background:#fafbfd}.translation-row th,.translation-row td{background:#f3faf6;color:#176b4d;font-size:12px;padding-top:6px;padding-bottom:9px}.translation-failure{color:#9a3412}
@media(max-width:720px){main{padding:12px}.pair{grid-template-columns:1fr}.translation{border-left:0;border-top:1px solid #d7dfdc}.table-pair{padding:14px 12px}}</style>
</head><body><main><h1>全文中英对照</h1>""" + "".join(sections) + "</main></body></html>\n"


def _render_clarification_html(report: dict[str, Any], translations: dict[str, str]) -> str:
    entries = report.get("entries") or []
    items: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        question = html.escape(str(entry.get("question") or entry.get("text") or ""))
        source = next((str(entry.get(key) or "").strip() for key in
                       ("source_text", "source_quote", "original_text", "evidence", "context")
                       if str(entry.get(key) or "").strip()), "")
        translated = translations.get(translation_key(source), "") if source else ""
        items.append(
            f'<section><h2>{index}. {question}</h2><p class="source">{html.escape(source)}</p>'
            f'<p class="translation">{html.escape(translated)}</p></section>'
        )
    note = "" if entries else "<p>澄清报告尚未生成；运行澄清阶段后重跑全文翻译即可增量补齐。</p>"
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>双语澄清报告</title><style>body{max-width:960px;margin:auto;padding:24px;font:15px/1.65 system-ui,sans-serif;color:#17202a}
section{border-top:1px solid #ccd5da;padding:14px 0}.source{white-space:pre-wrap}.translation{white-space:pre-wrap;color:#176b4d}</style></head>
<body><h1>双语澄清报告</h1>""" + note + "".join(items) + "</body></html>\n"


def _update_quality_report(out_dir: Path, summary: dict[str, Any]) -> None:
    path = governed_artifact_path(out_dir, "quality_report.json", category="pipeline")
    lock = governed_artifact_path(out_dir, "full_translation.lock", category="state")
    with process_file_lock(lock, timeout_s=15.0, label="full translation quality report lock"):
        report = _read_json(path)
        report["full_translation"] = summary
        _atomic_write(path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def _aggregate_status(dispositions: list[dict[str, Any]]) -> tuple[str, str]:
    if not dispositions or all(row["status"] == "skipped" for row in dispositions):
        reason = next((str(row.get("reason") or "") for row in dispositions if row.get("reason")), "empty_table")
        return "skipped", reason
    failures = sum(row["status"] == "failed" for row in dispositions)
    if failures:
        return "failed", f"table_rows_failed:{failures}"
    return "translated", ""


def run_full_translation(
    out_dir: Path,
    *,
    route: str | None = "openai_compatible",
    chat: Any = None,
) -> dict[str, Any]:
    from doc_annotation_export import (
        _active_translation_strategy_version,
        _read_translation_sidecar,
        generate_annotation_translations,
    )

    root = Path(out_dir).expanduser().resolve()
    blocks_path = governed_artifact_path(root, "blocks.jsonl", category="pipeline", for_write=False)
    blocks = [row for row in read_jsonl(blocks_path) if isinstance(row, dict)]
    report_path = governed_artifact_path(root, "clarification_report.json", category="pipeline", for_write=False)
    clarification_report = _read_json(report_path)
    enabled = full_translation_enabled()
    plans: dict[str, dict[str, Any]] = {}
    texts: dict[str, tuple[str, str]] = {}
    for block in blocks:
        block_id = str(block.get("block_id") or "")
        plan = _regular_table_plan(block)
        if plan is not None:
            plans[block_id] = plan
            for unit in plan["units"]:
                text = str(unit.get("source_text") or "").strip()
                if text:
                    texts[translation_key(text)] = (f"table_{unit['role']}", text)
            continue
        text = _block_text(block)
        if text:
            texts[translation_key(text)] = (str(block.get("block_type") or "block"), text)
    for text in _clarification_texts(clarification_report):
        texts[translation_key(text)] = ("clarification", text)

    translation_summary: dict[str, Any] = {
        "route": "stub", "model": "", "cached": 0, "translated": 0,
        "rejected": 0, "unresolved": len(texts), "batch_calls": 0, "failed_calls": 0,
    }
    if enabled and texts:
        translation_summary = generate_annotation_translations(
            root, route=route, texts=texts, chat=chat
        )
    sidecar = _read_translation_sidecar(root)
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    strategy = _active_translation_strategy_version()
    rows: list[dict[str, Any]] = []
    block_counts = {"translated": 0, "failed": 0, "skipped": 0}
    table_row_counts = {"translated": 0, "failed": 0, "skipped": 0}
    fallback_tables = 0
    for index, block in enumerate(blocks):
        block_id = str(block.get("block_id") or f"block-{index + 1}")
        source = _block_text(block)
        plan = plans.get(block_id)
        record_kind = "block"
        table_payload: dict[str, Any] | None = None
        if plan is not None:
            dispositions = [
                _unit_disposition(
                    unit, enabled=enabled, sidecar=sidecar,
                    translation_summary=translation_summary,
                )
                for unit in plan["units"]
            ]
            status, reason = _aggregate_status(dispositions)
            if plan["header_fallback"]:
                fallback_tables += 1
            for disposition in dispositions:
                if disposition.get("role") in {"header", "data"}:
                    table_row_counts[disposition["status"]] += 1
            record_kind = "table"
            table_payload = {
                key: value for key, value in plan.items() if key != "units"
            }
            table_payload["rows"] = dispositions
            key = ""
            entry: dict[str, Any] = {}
            translation = ""
        else:
            key = translation_key(source) if source else ""
            entry = sidecar.get(key, {}) if key else {}
            translation = str(entry.get("translation") or "").strip()
            if not source:
                status, reason = "skipped", "empty_text"
            elif not enabled:
                status, reason = "skipped", "feature_disabled"
            elif translation and not entry.get("rejected"):
                status, reason = "translated", ""
            else:
                status = "failed"
                reason = str(entry.get("status") or entry.get("reason") or "")
                if not reason:
                    reason = "llm_unavailable" if translation_summary.get("route") == "stub" else "missing_cache_entry"
            if str(block.get("type") or block.get("block_type") or "") == "table":
                record_kind = "complex_table"
        block_counts[status] += 1
        record = {
            "schema_version": DOCUMENT_TRANSLATION_SCHEMA_VERSION,
            "record_kind": record_kind,
            "block_id": block_id,
            "block_index": index,
            "status": status,
            "reason": reason,
            "source_text": source,
            "translation": translation if status == "translated" and record_kind != "table" else "",
            "provenance": {
                "producer": FULL_TRANSLATION_VERSION,
                "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "translation_key": key,
                "route": translation_summary.get("route") or "stub",
                "model": entry.get("model") or translation_summary.get("model") or "",
                "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
                "strategy_version": entry.get("strategy_version") or strategy,
                "generated_at": generated_at,
            },
        }
        if table_payload is not None:
            record["table"] = table_payload
        rows.append(record)

    ledger_path = governed_artifact_path(root, DOCUMENT_TRANSLATIONS, category="pipeline")
    document_html_path = governed_artifact_path(root, DOCUMENT_TRANSLATION_HTML, category="pipeline")
    clarification_html_path = governed_artifact_path(root, CLARIFICATION_BILINGUAL_HTML, category="pipeline")
    _atomic_write(ledger_path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    _atomic_write(document_html_path, _render_document_html(rows))
    accepted = {
        key: str(entry.get("translation") or "").strip()
        for key, entry in sidecar.items()
        if str(entry.get("translation") or "").strip() and not entry.get("rejected")
    }
    _atomic_write(
        clarification_html_path,
        _render_clarification_html(clarification_report, accepted),
    )
    eligible = block_counts["translated"] + block_counts["failed"]
    coverage = round(block_counts["translated"] / eligible, 6) if eligible else 1.0
    table_eligible = table_row_counts["translated"] + table_row_counts["failed"]
    table_coverage = (
        round(table_row_counts["translated"] / table_eligible, 6)
        if table_eligible else 1.0
    )
    quality = {
        "version": FULL_TRANSLATION_VERSION,
        "enabled": enabled,
        "total_blocks": len(rows),
        "counts": block_counts,
        "eligible_blocks": eligible,
        "coverage": coverage,
        "coverage_percent": round(coverage * 100, 2),
        "meets_99_percent": coverage >= 0.99,
        "table_rows": {
            "counts": table_row_counts,
            "eligible_rows": table_eligible,
            "coverage": table_coverage,
            "coverage_percent": round(table_coverage * 100, 2),
            "header_fallback_tables": fallback_tables,
        },
        "translation_calls": {
            key: translation_summary.get(key, 0)
            for key in ("cached", "translated", "rejected", "unresolved", "batch_calls", "failed_calls")
        },
        "route": translation_summary.get("route") or "stub",
        "model": translation_summary.get("model") or "",
    }
    _update_quality_report(root, quality)
    return {
        "kind": "full_translation",
        "out_dir": str(root),
        "route": quality["route"],
        "quality": quality,
        "translations": translation_summary,
        "written": [str(ledger_path), str(document_html_path), str(clarification_html_path)],
    }
