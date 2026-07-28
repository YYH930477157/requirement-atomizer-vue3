"""点解析（spot extract，WP-B）：批注视图任意行/块单独触发定向解析，结果进澄清待确认。

口径（冻结规格 docs/facsimile-spotextract-spec.md）：
- 表格块 + row_index 且该行是需求型参数表行 → 复用 guards-v16 确定性行展开逻辑
  （判定/渲染函数直接 import ai_extract，不复制）；否则把该行/该块文本单独送 LLM
  抽取（复用 targeted_reextract 的调用方式：config_for_route + chat_json +
  critique_section 护栏，范围限定单段文本）；
- 产出追加进 ai_requirements.jsonl（extraction_operation_lock 串行化 + 原子重写）：
  status=draft、source_mapping="spot_extract"、suspicion_reasons 含「用户定点解析」、
  ai_req_id="SPOT-<block_id>[-R<row>]"（冲突加序号）；
- 结果只进 draft + 澄清待确认，不直接转正；LLM 不可用响亮报错，绝不伪造 stub 抽取结果。
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from omission_actions import OmissionConflictError, extraction_operation_lock

SPOT_EXTRACT_VERSION = "spot-extract-v1"
SPOT_SOURCE_MAPPING = "spot_extract"
SPOT_SUSPICION = "用户定点解析"
# critique_section 会给补入条目打自检标签——点解析不是自检补充，发布前如实摘除
_SELF_CHECK_TAGS = {"自检补充（初抽遗漏）", "自检补充转独立（原目标未匹配,请核归属）"}

LOGGER = logging.getLogger("requirement_atomizer")


class SpotExtractUnavailableError(RuntimeError):
    """LLM 路由未配置/不可用——响亮失败，绝不退化成 stub 抽取。"""


def _block_by_id(out_dir: Path, block_id: str) -> dict[str, Any]:
    for block in read_jsonl(Path(out_dir) / "blocks.jsonl"):
        if str(block.get("block_id") or "") == block_id:
            return block
    raise ValueError(f"unknown block_id: {block_id}")


def _row_text(block: dict[str, Any], row_index: int) -> str:
    from ai_extract import _row_render_line

    headers = [str(h or "") for h in (block.get("headers") or [])]
    data_rows = block.get("data_rows") or []
    if not 1 <= row_index <= len(data_rows):
        raise ValueError(f"row_index out of range: {row_index}（数据行共 {len(data_rows)} 行）")
    return _row_render_line(headers, data_rows[row_index - 1])


def _deterministic_row_requirement(block: dict[str, Any], row_index: int,
                                   covered_text: str) -> dict[str, Any] | None:
    """guards-v16 单行等价展开：需求型参数表的该行 → 一条 draft 需求。

    不合格的行（稀疏行/分组标题行/非需求型参数表）返回 None 走 LLM 路径；
    已被现有需求覆盖的行返回 "covered" 标记（与 _supplement_parameter_table_rows
    同口径：已覆盖不重复补）。"""
    from ai_extract import (
        _PARAM_ROW_MIN_CELLS,
        _is_parameter_table,
        _row_name_cell,
        _row_render_line,
    )
    from merged_consistency import compact_source_text

    if not _is_parameter_table(block):
        return None
    data_rows = block.get("data_rows") or []
    row = data_rows[row_index - 1]   # row_index 界内由 _row_text 先行校验
    cells = [str(cell or "").strip() for cell in row]
    non_empty = [cell for cell in cells if cell]
    if len(non_empty) < _PARAM_ROW_MIN_CELLS:
        return None
    if len(set(non_empty)) == 1:
        return None   # 分组标题行（合并单元格展开成全同值）不是需求行
    headers = [str(h or "") for h in (block.get("headers") or [])]
    quote = _row_render_line(headers, row)
    if not quote.strip():
        return None
    # 覆盖判定同 guards-v16：最长实质单元格（≥16 字符）已在引用本块的任一需求文本中出现
    substantive = sorted((compact_source_text(cell) for cell in non_empty), key=len, reverse=True)
    key_cell = next((cell for cell in substantive if len(cell) >= 16), "")
    if key_cell and key_cell in covered_text:
        return {"covered": True}
    name = _row_name_cell(headers, row)
    title = name[:120] if name else quote[:120]
    section_path = [str(s) for s in (block.get("section_path") or []) if str(s).strip()]
    block_id = str(block.get("block_id") or "")
    return {
        "ai_req_id": "",   # 发布前统一指派 SPOT- id
        "title": title,
        "description": quote,
        "type": "functional",
        "priority": "P1",
        "status": "draft",
        "labels": ["参数表"],
        "source_section": section_path[-1] if section_path else "",
        "source_quote": quote,
        "source_block_ids": [block_id],
        "anchor_block_id": block_id,
        "source_mapping": SPOT_SOURCE_MAPPING,
        "suspicion_reasons": [SPOT_SUSPICION],
        "notes": "用户定点解析：参数表行由确定性规则展开（同 guards-v16 逐行口径），"
                 "引句逐字来自原文表格渲染行，请人工审核后确认",
    }


def _covered_text_for_block(requirements: list[dict[str, Any]], block_id: str) -> str:
    from merged_consistency import compact_source_text

    haystack = ""
    for req in requirements:
        if block_id not in {str(value) for value in (req.get("source_block_ids") or [])}:
            continue
        haystack += " " + compact_source_text(
            f"{req.get('source_quote') or ''} {req.get('description') or ''} {req.get('title') or ''}"
        )
    return haystack


def _llm_spot_rows(out_dir: Path, *, block: dict[str, Any], text: str,
                   existing: list[dict[str, Any]], route: str) -> list[dict[str, Any]]:
    """单段文本 LLM 抽取：复用 targeted_reextract 的调用方式（chat_json + critique_section
    护栏），范围限定该段文本——合成只含本段的单块 section，prompt 看不见其他内容。"""
    import ai_extract
    from llm_client import apply_min_tokens, chat_json

    if route != "openai_compatible":
        raise SpotExtractUnavailableError("spot extract requires openai_compatible route")
    config = ai_extract.config_for_route(route)
    if config is None:
        raise SpotExtractUnavailableError("openai_compatible route is not configured")
    config = apply_min_tokens(config, "extract")

    def chat(system: str, user: str) -> dict[str, Any]:
        return chat_json(config, system, user)

    root = Path(out_dir)
    block_id = str(block.get("block_id") or "")
    section_path = [str(s) for s in (block.get("section_path") or []) if str(s).strip()]
    section = {
        "section_id": f"spot:{block_id}",
        "heading": section_path[-1] if section_path else "",
        "text": text,
        "block_ids": [block_id],
        "source_blocks": [block],
    }
    blocks = read_jsonl(root / "blocks.jsonl")
    doc_context = ai_extract.build_doc_context(root, blocks)
    context_ints = frozenset(ai_extract.extract_ints(doc_context)) if doc_context else frozenset()
    # existing 深拷贝进自检：supplements 落账是 targeted_reextract 的语义，点解析只产新 draft
    extra, _supplements = ai_extract.critique_section(
        section, copy.deepcopy(existing), chat, doc_context, context_ints,
        focus_lines=[text],
    )
    rows: list[dict[str, Any]] = []
    for row in extra:
        suspicions = [str(s) for s in (row.get("suspicion_reasons") or [])
                      if str(s) not in _SELF_CHECK_TAGS]
        row["suspicion_reasons"] = [SPOT_SUSPICION] + suspicions
        row.pop("self_check_added", None)
        row["status"] = "draft"
        row["source_mapping"] = SPOT_SOURCE_MAPPING
        row["source_block_ids"] = [block_id]
        row["anchor_block_id"] = block_id
        if section_path:
            row["source_section"] = section_path[-1]
        note = "用户定点解析：单段文本 LLM 抽取（同 targeted_reextract 护栏），请人工审核后确认"
        row["notes"] = f"{row.get('notes') or ''}；{note}".strip("；")
        rows.append(row)
    return rows


def _assign_spot_ids(rows: list[dict[str, Any]], *, block_id: str, row_index: int | None,
                     existing_ids: set[str]) -> None:
    base = f"SPOT-{block_id}" + (f"-R{row_index}" if row_index is not None else "")
    for position, row in enumerate(rows):
        candidate = base if position == 0 else f"{base}-{position + 1}"
        serial = 2
        while candidate in existing_ids:
            candidate = f"{base}-{serial}"
            serial += 1
        existing_ids.add(candidate)
        row["ai_req_id"] = candidate


def spot_extract(out_dir: Path, *, block_id: str, row_index: int | None = None,
                 route: str = "openai_compatible", actor: str | None = None,
                 reason: str = "") -> dict[str, Any]:
    """对单个块/表格行做点解析，产出 draft 需求追加进 ai_requirements.jsonl。

    返回 {"schema", "block_id", "row_index", "strategy", "drafts", "draft_ids",
    "already_covered", "written"}；LLM 不可用抛 SpotExtractUnavailableError（响亮失败）。
    """
    import ai_extract

    root = Path(out_dir).expanduser().resolve()
    block_id = str(block_id or "").strip()
    if not block_id:
        raise ValueError("block_id is required")
    if row_index is not None:
        row_index = int(row_index)
    with extraction_operation_lock(root, operation="spot-extract"):
        from api_server import final_ai_requirements_are_stale

        if final_ai_requirements_are_stale(root):
            raise OmissionConflictError(
                "AI extraction belongs to an older parsed document; rerun full extraction first"
            )
        block = _block_by_id(root, block_id)
        is_table = str(block.get("type") or "") == "table"
        if row_index is not None and not is_table:
            raise ValueError("row_index 仅适用于表格块")
        text = _row_text(block, row_index) if (is_table and row_index is not None) \
            else str(block.get("text") or "")
        if not text.strip():
            raise ValueError("目标行/块没有可解析文本")

        requirements_path = root / ai_extract.AI_REQUIREMENTS
        current = read_jsonl(requirements_path) if requirements_path.exists() else []
        block_existing = [
            row for row in current
            if block_id in {str(value) for value in (row.get("source_block_ids") or [])}
        ]

        strategy = "llm"
        rows: list[dict[str, Any]] = []
        already_covered = False
        if is_table and row_index is not None:
            deterministic = _deterministic_row_requirement(
                block, row_index, _covered_text_for_block(current, block_id))
            if deterministic is not None and deterministic.get("covered"):
                already_covered = True
                strategy = "deterministic_param_row"
            elif deterministic is not None:
                rows = [deterministic]
                strategy = "deterministic_param_row"
        if not already_covered and not rows:
            rows = _llm_spot_rows(root, block=block, text=text,
                                  existing=block_existing, route=route)
            if not rows:
                already_covered = True   # LLM 判定该段已被现有需求覆盖/无可抽需求

        draft_ids: list[str] = []
        written: list[str] = []
        if rows:
            existing_ids = {
                str(row.get("ai_req_id") or "") for row in current if row.get("ai_req_id")
            }
            _assign_spot_ids(rows, block_id=block_id, row_index=row_index,
                             existing_ids=existing_ids)
            # _prepare_requirement_rows 做受控标签 + 身份指纹；显式 SPOT- id 显式优先保留
            prepared = ai_extract._prepare_requirement_rows(
                rows, f"spot-extract:{SPOT_EXTRACT_VERSION}")
            for row in prepared:
                row["spot_extract"] = {
                    "version": SPOT_EXTRACT_VERSION,
                    "strategy": strategy,
                    "actor": actor,
                    "reason": str(reason or ""),
                }
            draft_ids = [str(row["ai_req_id"]) for row in prepared]
            effective = current + prepared
            ai_extract.atomic_write_jsonl(requirements_path, effective)
            ai_extract.write_compliance_requirements(root, effective)
            ai_extract.refresh_ai_extract_quality(root, effective)
            rebuilt = ai_extract.rebuild_merged_spec(root)
            written = [ai_extract.AI_REQUIREMENTS, ai_extract.COMPLIANCE_REQUIREMENTS,
                       "ai_extract_quality.json"]
            written.extend(str(value) for value in (rebuilt.get("written") or []))
            LOGGER.info("点解析：%s %s → %d 条 draft 需求进澄清（%s）",
                        block_id, f"R{row_index}" if row_index is not None else "",
                        len(prepared), strategy)

        return {
            "schema": "spot-extract/v1",
            "block_id": block_id,
            "row_index": row_index,
            "strategy": strategy,
            "drafts": len(draft_ids),
            "draft_ids": draft_ids,
            "already_covered": already_covered,
            "written": list(dict.fromkeys(written)),
        }
