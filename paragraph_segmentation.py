"""Source paragraph inspection, independent of requirement extraction.

Document units reference existing block identities. Diagnostics and visual
suggestions never rewrite source text, section paths, or accepted review state.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import hashlib
import html
import json
from pathlib import Path
import re

SEGMENTATION_VERSION = "paragraph-segmentation-v1"
MODES = ("text_only", "layout", "vision_assisted")
FALLBACKS = ("keep_for_review", "text_fallback", "fail_closed")
_ACTIVE_MODE: ContextVar[str] = ContextVar("paragraph_mode", default="layout")


@dataclass(frozen=True)
class SegmentationOptions:
    mode: str = "layout"
    vision_capable: bool = False
    vision_model: str = ""
    vision_max_regions: int = 5
    vision_max_calls: int = 5
    vision_max_tokens: int = 100000
    fallback: str = "keep_for_review"
    semantic_mode: str = "deterministic"
    semantic_route: str = "openai_compatible"

    def __post_init__(self):
        if self.mode not in MODES or self.fallback not in FALLBACKS:
            raise ValueError("Invalid paragraph segmentation mode or fallback")
        from semantic_segmentation import SEMANTIC_MODES
        if self.semantic_mode not in SEMANTIC_MODES or self.semantic_route not in ("stub", "openai_compatible"):
            raise ValueError("Invalid semantic segmentation mode or route")
        if type(self.vision_capable) is not bool or not isinstance(self.vision_model, str):
            raise ValueError("vision_capable must be boolean and vision_model must be text")
        for name in ("vision_max_regions", "vision_max_calls", "vision_max_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def lineage(self) -> dict:
        result = {"version": SEGMENTATION_VERSION, **asdict(self)}
        if self.mode == "vision_assisted":
            from ai_extract import DEFAULT_PIPELINE_PATH, config_for_route
            from llm_client import llm_attempt_policy
            config = config_for_route("openai_compatible", DEFAULT_PIPELINE_PATH)
            result["vision_route"] = "openai_compatible"
            result["vision_endpoint"] = config.base_url if config else None
            result["vision_effective_model"] = self.vision_model or (config.model if config else None)
            result["attempt_policy"] = llm_attempt_policy()
        return result

    def initial_mode(self) -> str:
        if self.mode != "vision_assisted":
            return self.mode
        if not self.vision_capable:
            if self.fallback == "fail_closed":
                raise ValueError("视觉辅助需要使用者明确确认模型具备视觉能力")
            if self.fallback == "text_fallback":
                return "text_only"
        return "layout"


def options_from_args(args) -> SegmentationOptions:
    defaults = asdict(SegmentationOptions())
    values = {
        field: getattr(args, f"paragraph_{field}", default)
        for field, default in defaults.items()
        if field not in {"semantic_mode", "semantic_route"}
    }
    values["semantic_mode"] = getattr(args, "semantic_mode", defaults["semantic_mode"])
    values["semantic_route"] = getattr(args, "semantic_route", defaults["semantic_route"])
    return SegmentationOptions(**values)


def add_segmentation_arguments(parser) -> None:
    parser.add_argument("--paragraph-mode", choices=MODES, default="layout")
    parser.add_argument("--paragraph-vision-capable", action="store_true",
                        help="使用者确认所配置模型支持图片输入；不根据模型名推断")
    parser.add_argument("--paragraph-vision-model", default="")
    parser.add_argument("--paragraph-vision-max-regions", type=int, default=5)
    parser.add_argument("--paragraph-vision-max-calls", type=int, default=5)
    parser.add_argument("--paragraph-vision-max-tokens", type=int, default=100000)
    parser.add_argument("--paragraph-fallback", choices=FALLBACKS, default="keep_for_review")
    from semantic_segmentation import add_semantic_arguments
    add_semantic_arguments(parser)


@contextmanager
def segmentation_mode(mode: str):
    token = _ACTIVE_MODE.set(mode)
    try:
        yield
    finally:
        _ACTIVE_MODE.reset(token)


def text_only_mode() -> bool:
    return _ACTIVE_MODE.get() == "text_only"


def build_segmentation_report(blocks: list[dict], source: Path,
                              options: SegmentationOptions) -> dict:
    units = []
    for block in blocks:
        text = str(block.get("text") or "")
        raw = str(block.get("raw_text", text))
        kind = str(block.get("type") or "paragraph")
        if kind == "paragraph" and block.get("is_list_item"):
            kind = "list_item"
        flags = []
        if kind in ("paragraph", "list_item") and not block.get("noise"):
            if len(text) > 1800:
                flags.append("long_paragraph_check_boundary")
            if source.suffix.lower() == ".pdf" and text[:1].islower():
                flags.append("possible_continuation_fragment")
            if not block.get("section_path"):
                flags.append("section_unassigned")
        if kind == "heading" and len(text) > 160:
            flags.append("possible_heading_body_merge")
        if kind != "table" and len(re.findall(r"[\r\n]", raw)):
            flags.append("manual_line_breaks_preserved_in_source")
        if kind == "table" and block.get("geometry_kind") in ("none", "conflict"):
            flags.append("table_structure_needs_review")
        unit = {
            "unit_id": str(block["block_id"]), "type": kind,
            "text_original": raw, "text_normalized": text,
            "source_order": block.get("order"),
            "section_path": list(block.get("section_path") or []),
            "source_ref": {
                "format": source.suffix.lower().lstrip("."),
                "block_id": block["block_id"],
                "paragraph_index": block.get("source_paragraph_index"),
                "page": block.get("page_number"),
                "regions": block.get("pdf_regions") or [],
                "table_id": block.get("table_id"),
                "text_basis": "parser_raw_text" if "raw_text" in block else "parser_text",
            },
            "boundary_basis": "native_paragraph" if source.suffix.lower() == ".docx" and kind != "table"
                              else "table_structure" if kind == "table" else "parser_structure",
            "confidence": None,  # No human boundary truth: never invent probabilities.
            "review_flags": flags,
            "status": "needs_review" if flags else "not_reviewed",
        }
        units.append(unit)
    signature = json.dumps(units, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "schema": "paragraph-segmentation/v1", "version": SEGMENTATION_VERSION,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "units_fingerprint": hashlib.sha256(signature).hexdigest(),
        "configuration": options.lineage(), "effective_mode": options.initial_mode(),
        "quality_status": "not_evaluated", "confidence_basis": "human_boundary_truth_required",
        "counts": {"units": len(units), "needs_review": sum(bool(u["review_flags"]) for u in units)},
        "vision": {"status": "not_requested", "suggestions": [], "applied": False},
        "units": units,
    }


def render_segmentation_review(report: dict) -> str:
    """Offline, script-free inspection: preserve manual breaks and escape all source text."""
    esc = lambda value: html.escape(str(value), quote=True)
    rows = []
    for unit in report["units"]:
        flags = " / ".join(unit["review_flags"]) or "未发现规则提示；尚未人工确认"
        rows.append(f'<article id="{esc(unit["unit_id"])}"><h2>{esc(unit["unit_id"])} · '
                    f'{esc(unit["type"])}</h2><p>{esc(" / ".join(unit["section_path"]))}</p>'
                    f'<p>来源：{esc(json.dumps(unit["source_ref"], ensure_ascii=False))}</p>'
                    f'<p class="risk">{esc(flags)}</p><div class="columns"><section><h3>解析原文</h3>'
                    f'<pre>{esc(unit["text_original"])}</pre></section><section><h3>规范文本</h3>'
                    f'<pre>{esc(unit["text_normalized"])}</pre></section></div></article>')
    vision = esc(json.dumps(report["vision"], ensure_ascii=False, indent=2))
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>段落划分复核</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto;padding:0 20px;'
            'color:#233047;background:#f5f7fa}article{background:white;padding:20px;margin:16px 0;border:1px solid #dce1e8;'
            'border-radius:12px}h2{font-size:18px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}.risk{color:#805700}'
            '@media(max-width:700px){.columns{grid-template-columns:1fr}}</style>'
            '<h1>段落划分复核</h1><p>本页用于检查解析边界，规则提示不等于错误；无提示也不代表已确认。'
            'PDF 原文栏为解析器恢复的文字，不代表未经处理的原始 PDF 字符。</p>'
            f'<p>请求模式：{esc(report["configuration"]["mode"])} · 实际模式：{esc(report["effective_mode"])}</p>'
            f'<details><summary>视觉辅助运行记录（建议尚未应用）</summary><pre>{vision}</pre></details>'
            + "".join(rows) + '</html>')
