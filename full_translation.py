"""Whole-document translation stage backed by the annotation translation cache."""
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


FULL_TRANSLATION_VERSION = "full-translation-v1"
DOCUMENT_TRANSLATION_SCHEMA_VERSION = "document-translation/v1"
FULL_TRANSLATION_ENV = "RATOMIZER_FULL_TRANSLATION"
DOCUMENT_TRANSLATIONS = "document_translations.jsonl"
DOCUMENT_TRANSLATION_HTML = "document_translation.html"
CLARIFICATION_BILINGUAL_HTML = "clarification_questions_bilingual.html"
_REPLACE_ATTEMPTS = 5
_LATIN_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


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


def _render_document_html(rows: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for row in rows:
        block_id = str(row.get("block_id") or "")
        source = html.escape(str(row.get("source_text") or ""))
        translation = html.escape(str(row.get("translation") or ""))
        status = str(row.get("status") or "")
        reason = html.escape(str(row.get("reason") or ""))
        target = translation if translation else f"[{status}] {reason}".strip()
        anchor = html.escape(block_id, quote=True)
        sections.append(
            f'<section class="pair" id="pair-{anchor}">'
            f'<article id="src-{anchor}"><header>{anchor} · EN '
            f'<a href="#zh-{anchor}">中文</a></header><p>{source}</p></article>'
            f'<article id="zh-{anchor}" class="translation"><header>{anchor} · 中文 '
            f'<a href="#src-{anchor}">EN</a></header><p>{target}</p></article></section>'
        )
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>全文中英对照</title>
<style>body{margin:0;font:15px/1.65 system-ui,sans-serif;color:#17202a;background:#f5f7f8}
main{max-width:1180px;margin:auto;padding:24px}.pair{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #cbd3d8;background:white}
article{padding:16px 20px;min-width:0}.translation{background:#f7fbf8;border-left:1px solid #d7dfdc}header{font-size:12px;color:#53636d}
p{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#176b4d}@media(max-width:720px){.pair{grid-template-columns:1fr}.translation{border-left:0;border-top:1px solid #d7dfdc}}</style>
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
    texts: dict[str, tuple[str, str]] = {}
    for block in blocks:
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
    counts = {"translated": 0, "failed": 0, "skipped": 0}
    for index, block in enumerate(blocks):
        block_id = str(block.get("block_id") or f"block-{index + 1}")
        source = _block_text(block)
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
        counts[status] += 1
        rows.append({
            "schema_version": DOCUMENT_TRANSLATION_SCHEMA_VERSION,
            "block_id": block_id,
            "block_index": index,
            "status": status,
            "reason": reason,
            "source_text": source,
            "translation": translation if status == "translated" else "",
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
        })

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
    eligible = counts["translated"] + counts["failed"]
    coverage = round(counts["translated"] / eligible, 6) if eligible else 1.0
    quality = {
        "version": FULL_TRANSLATION_VERSION,
        "enabled": enabled,
        "total_blocks": len(rows),
        "counts": counts,
        "eligible_blocks": eligible,
        "coverage": coverage,
        "coverage_percent": round(coverage * 100, 2),
        "meets_99_percent": coverage >= 0.99,
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
