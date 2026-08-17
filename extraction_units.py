"""ExtractionUnit 统一单元规划器（quality-first 方案 §6，M1）。

从现有解析产物（blocks.jsonl / table_items.jsonl / table_cell_items.jsonl /
table_cell_dispositions.jsonl）确定性构建 A/B 两轨共用的内容单元——单一事实源，
两轨不得各自重新切分原文（否则 source span、缓存 key、守恒单位会分叉）。

- 正文：按句切分（复用 functional_drilldown 句切分权威），带义务/结构信号的句子
  各自成单元（clause_segment），全块无信号的整块一个 narrative context 单元；
- 列表项：信号句成 clause_segment 单元并带 list_item 角色；
- 表格：跟随 leaf 规划——row leaf 生成 table_row 单元（covers_cell_ids 覆盖该行
  全部非空 canonical cell），cell leaf 逐格生成 table_cell 单元；**每个非空
  canonical cell 恰好被一个单元覆盖**（自身单元或所属行单元），规划器硬校验；
- 定义/引用：物化为 context 单元（definition/reference），永不做付费提取。

零 LLM、零执行变化（shadow 前置产物）。版本 bump 规则：任何影响单元边界/字段
的变化必须 bump EXTRACTION_UNIT_PLANNER_VERSION 并进入依赖它的 stage fingerprint。
"""
from __future__ import annotations

from typing import Any, Iterable

from artifact_store import ArtifactStore
from claim_artifacts import sha256_bytes
from extract_units import (
    _TERM_NAME_RE,
    _TERMS_HEADING_RE,
    assemble_sections,
    body_blocks,
    clean_block_text,
    resolve_section_refs,
)
from io_utils import read_jsonl

EXTRACTION_UNIT_SCHEMA = "extraction-unit/v1"
# v2（2026-08-17）：COSEM 行的格单元继承 cosem_structured 角色（表/行级语境下沉）。
EXTRACTION_UNIT_PLANNER_VERSION = "extraction-unit-planner-v2"
EXTRACTION_UNITS_FILENAME = "extraction_units.jsonl"
EXTRACTION_UNIT_PLAN_SCHEMA = "extraction-unit-plan/v1"

UNIT_KINDS = (
    "clause_segment",   # 正文/列表中带信号的规范性句段
    "narrative",        # 全块无信号 → 整块上下文单元
    "heading",          # 标题 → 上下文
    "table_row",        # row leaf（覆盖该行 canonical cells）
    "table_cell",       # cell leaf / context cell（逐格单元）
    "definition",       # 术语定义 → 上下文
    "reference",        # 被引用条款摘录 → 上下文
)

UNIT_ROLES = (
    "requirement_candidate",  # 有义务/结构信号或 disposition target/composite
    "review_candidate",       # 弱信号/歧义/disposition review——物化待审，不静默丢弃
    "context",                # 纯上下文，不产生付费提取
    "excluded",               # disposition excluded——保留可追溯性
    "list_item",              # 列表项标记（叠加角色）
    "cosem_structured",       # 行/格携带 cosem_object_context（叠加角色）
)

_KIND_RANK = {kind: index for index, kind in enumerate(UNIT_KINDS)}


def _text_hash(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def _sentence_split(text: str) -> list[str]:
    from functional_drilldown import _SENTENCE_SPLIT_RE

    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]


def _has_b_signal(sentence: str) -> bool:
    from atomize import is_requirement_like
    from functional_extract import _has_obligation_modal

    return _has_obligation_modal(sentence) or bool(is_requirement_like(sentence))


def _has_a_signal(sentence: str) -> bool:
    from atomize import extract_parameters

    parameters = extract_parameters(sentence)
    return any(parameters.get(key) for key in ("obis_codes", "class_ids", "sap_values"))


def _signal_role(sentence: str) -> list[str]:
    roles: list[str] = []
    if _has_b_signal(sentence) or _has_a_signal(sentence):
        roles.append("requirement_candidate")
    return roles


def _unit(unit_id: str, kind: str, text: str, *, block: dict[str, Any],
          roles: list[str], locator: dict[str, str],
          table_context: dict[str, Any] | None = None,
          context_refs: Iterable[str] = (),
          sentence_index: int | None = None,
          covers_cell_ids: Iterable[str] = (),
          sort_key: tuple[int, int, int] = (0, 0, 0)) -> dict[str, Any]:
    unit: dict[str, Any] = {
        "schema": EXTRACTION_UNIT_SCHEMA,
        "unit_id": unit_id,
        "unit_kind": kind,
        "source_text": text,
        "source_text_hash": _text_hash(text),
        "clause_path": [str(part) for part in (block.get("section_path") or [])],
        "source_block_ids": [str(block.get("block_id") or "")] if block.get("block_id") else [],
        "roles": sorted(set(roles) & set(UNIT_ROLES)) or ["context"],
        "context_refs": sorted(set(context_refs)),
        "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "locator": locator,
        "_sort_key": sort_key,
    }
    if table_context is not None:
        unit["table_context"] = table_context
    if sentence_index is not None:
        unit["sentence_index"] = sentence_index
    covers = sorted(set(covers_cell_ids))
    if covers:
        unit["covers_cell_ids"] = covers
    return unit


def _prose_units(blocks: list[dict[str, Any]], section_defs: dict[str, list[str]]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for block in body_blocks(blocks):
        if block.get("noise"):
            continue
        order = int(block.get("order") or 0)
        block_id = str(block.get("block_id") or "")
        if not block_id:
            continue
        context_refs = _context_refs_for(block, section_defs)
        if str(block.get("type") or "paragraph") == "table":
            continue  # 表格单元由 _table_units 生成（避免双份）
        text = clean_block_text(block)
        if not text:
            continue
        if str(block.get("type")) == "heading":
            units.append(_unit(
                f"UNIT-{block_id}", "heading", text, block=block, roles=["context"],
                locator={"source_type": "block", "source_id": block_id},
                context_refs=context_refs, sort_key=(order, 0, 0)))
            continue
        base_roles = ["list_item"] if block.get("is_list_item") else []
        signal_units: list[dict[str, Any]] = []
        for index, sentence in enumerate(_sentence_split(text)):
            roles = _signal_role(sentence)
            if not roles:
                continue
            signal_units.append(_unit(
                f"UNIT-{block_id}-S{index:03d}", "clause_segment", sentence,
                block=block, roles=roles + base_roles,
                locator={"source_type": "block_sentence", "source_id": f"{block_id}#{index}"},
                context_refs=context_refs, sentence_index=index,
                sort_key=(order, 1, index)))
        if signal_units:
            units.extend(signal_units)
        else:
            units.append(_unit(
                f"UNIT-{block_id}", "narrative", text, block=block, roles=["context"],
                locator={"source_type": "block", "source_id": block_id},
                context_refs=context_refs, sort_key=(order, 2, 0)))
    return units


def _table_units(blocks: list[dict[str, Any]], table_items: list[dict[str, Any]],
                 cell_items: list[dict[str, Any]],
                 dispositions: dict[str, dict[str, Any]],
                 section_defs: dict[str, list[str]]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    order_by_block = {
        str(block.get("block_id")): int(block.get("order") or 0)
        for block in blocks if block.get("block_id")
    }
    cells_by_row: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for cell in cell_items:
        cells_by_row.setdefault(
            (str(cell.get("table_block_id") or ""), int(cell.get("row_index") or 0)),
            []).append(cell)
    # v2：COSEM 语境下沉到表内全部格单元——它是表/行级属性（判定权威 atomize.
    # is_cosem_object_header/is_cosem_attribute_row 的表头形状 + 任一行携带
    # cosem_object_context）。Comment/Meaning 列的参数叙述格文本里没有 OBIS/class，
    # 且稀疏行（Object/CL 值为空）连行级 context 都没有——不看表级语境就会把这些
    # 说明格误判纯 B 义务（unit_router v2 依赖此角色把 COSEM 表整体归 A 轨权威）。
    cosem_tables: set[str] = set()
    for item in table_items:
        table_id = str(item.get("table_id") or "")
        if not table_id:
            continue
        if item.get("cosem_object_context"):
            cosem_tables.add(table_id)
            continue
        field_keys = {str(key) for key in (item.get("fields") or {})}
        if "Object/attribute name" in field_keys:
            cosem_tables.add(table_id)

    def _disposition_roles(cell_id: str, fallback: list[str]) -> list[str]:
        disposition = dispositions.get(cell_id, {})
        value = str(disposition.get("disposition") or "")
        if value in ("target", "composite"):
            return ["requirement_candidate"]
        if value == "review":
            return ["review_candidate"]
        if value == "excluded":
            return ["excluded"]
        if value == "context":
            return ["context"]
        return fallback

    for item in table_items:
        if str(item.get("leaf_role") or "") != "row":
            continue  # 容器行：其单元格由 cell leaf 或所属信号行覆盖
        block_id = str(item.get("table_block_id") or "")
        order = order_by_block.get(block_id, 0)
        row_index = int(item.get("row_index") or 0)
        row_cells = cells_by_row.get((block_id, row_index), [])
        roles = ["requirement_candidate"] if item.get("requirement_like") else ["context"]
        if item.get("cosem_object_context") or str(item.get("table_id") or "") in cosem_tables:
            # 行级 context 判定按行值（atomize），稀疏行（Object/CL 空、只剩 Meaning/
            # Comment 列）拿不到——表级语境兜底，行单元 headers 只含本行非空列。
            roles.append("cosem_structured")
        unit = _unit(
            f"UNIT-{item.get('item_id')}", "table_row", str(item.get("text") or ""),
            block={"block_id": block_id, "section_path": item.get("section_path") or []},
            roles=roles,
            locator={"source_type": "table_row", "source_id": str(item.get("item_id") or "")},
            table_context={
                "table_id": str(item.get("table_id") or ""),
                "item_id": str(item.get("item_id") or ""),
                "row_index": row_index,
                "column_index": None,
                "headers": [str(header) for header in (item.get("fields") or {}).keys()],
            },
            context_refs=_context_refs_for(
                {"section_path": item.get("section_path") or []}, section_defs),
            covers_cell_ids=[str(cell.get("cell_id")) for cell in row_cells],
            sort_key=(order, 3, row_index))
        units.append(unit)

    for cell in cell_items:
        leaf_kind = str(cell.get("leaf_kind") or "context")
        if leaf_kind == "row":
            continue  # 已由所属行单元覆盖
        block_id = str(cell.get("table_block_id") or "")
        order = order_by_block.get(block_id, 0)
        cell_id = str(cell.get("cell_id") or "")
        text = str(cell.get("text") or "")
        if not text:
            continue
        roles = _disposition_roles(cell_id, ["context"])
        if cell.get("requirement_like") and "context" in roles:
            roles = ["requirement_candidate"]
        if str(cell.get("table_id") or "") in cosem_tables:
            roles = sorted(set(roles) | {"cosem_structured"})
        unit = _unit(
            f"UNIT-{cell_id}", "table_cell", text,
            block={"block_id": block_id, "section_path": cell.get("section_path") or []},
            roles=roles,
            locator={"source_type": "table_cell", "source_id": cell_id},
            table_context={
                "table_id": str(cell.get("table_id") or ""),
                "cell_id": cell_id,
                "row_index": int(cell.get("row_index") or 0),
                "column_index": int(cell.get("column_index") or 0),
                "headers": [str(header) for header in (cell.get("header_path") or [])],
                "structural_role": str(cell.get("structural_role") or "data"),
                "disposition": (dispositions.get(cell_id, {}) or {}).get("disposition"),
            },
            context_refs=_context_refs_for(
                {"section_path": cell.get("section_path") or []}, section_defs),
            sort_key=(order, 4, int(cell.get("row_index") or 0) * 1000
                      + int(cell.get("column_index") or 0)))
        units.append(unit)
    return units


def _definition_and_reference_units(
        sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """物化定义/引用 context 单元。

    定义判定与 ``extract_units.collect_term_entries`` 同一权威口径（terms 路径 +
    编号子标题正则 + 短词/结构标题丢弃），但保留 section 归属以生成稳定 unit id；
    context_refs 沿用 ``attach_term_definitions`` 的"正文含术语"语义。
    """
    from extract_units import _TERM_NAME_RE, _TERMS_HEADING_RE

    units: list[dict[str, Any]] = []
    defs_by_term: dict[str, str] = {}  # term -> unit_id
    for section in sections:
        section_id = str(section.get("section_id") or "")
        block_ids = [str(bid) for bid in (section.get("block_ids") or [])]
        order = int(section.get("_first_block_order") or 0)
        base_block = {
            "block_id": block_ids[0] if block_ids else "",
            "section_path": section.get("section_path") or [],
        }
        path = " / ".join(
            [str(part) for part in (section.get("section_path") or [])]
            + [str(section.get("heading") or "")])
        heading = str(section.get("heading") or "").strip()
        match = _TERM_NAME_RE.match(heading) if _TERMS_HEADING_RE.search(path) else None
        if match:
            term = match.group(1).strip()
            if not (len(term) < 8 and " " not in term) and not _TERMS_HEADING_RE.search(term):
                digest = _text_hash(f"{section_id}|{term}")[len("sha256:"):][:16]
                unit = _unit(
                    f"UNIT-DEF-{digest}", "definition",
                    f"{term}: {str(section.get('text') or '')[:240]}",
                    block=base_block, roles=["context"],
                    locator={"source_type": "definition", "source_id": f"{section_id}:{term}"},
                    sort_key=(order, 5, 0))
                if block_ids:
                    unit["source_block_ids"] = block_ids
                units.append(unit)
                defs_by_term[term] = unit["unit_id"]
        for index, entry in enumerate(section.get("ref_texts") or []):
            clause = str(entry.get("clause") or "")
            text = str(entry.get("text") or "")
            if not clause:
                continue
            digest = _text_hash(f"{section_id}|{clause}")[len("sha256:"):][:16]
            unit = _unit(
                f"UNIT-REF-{digest}", "reference", f"{clause}: {text}",
                block=base_block, roles=["context"],
                locator={"source_type": "reference", "source_id": f"{section_id}:{clause}"},
                sort_key=(order, 6, index))
            if block_ids:
                unit["source_block_ids"] = block_ids
            units.append(unit)

    section_defs: dict[str, list[str]] = {}
    for section in sections:
        section_id = str(section.get("section_id") or "")
        path = " / ".join(str(part) for part in (section.get("section_path") or []))
        if _TERMS_HEADING_RE.search(path):
            continue  # 术语小节自身不注入（与 attach_term_definitions 一致）
        body = str(section.get("text") or "").casefold()
        refs = [unit_id for term, unit_id in sorted(defs_by_term.items())
                if term.casefold() in body]
        if refs:
            section_defs[section_id] = refs
    return units, section_defs


def _context_refs_for(block: dict[str, Any], section_defs: dict[str, list[str]]) -> list[str]:
    # assemble_sections 的 section_id = " / ".join(section_path)——同键直查
    key = " / ".join(str(part) for part in (block.get("section_path") or []))
    return list(section_defs.get(key, ()))


def _validate_cell_conservation(units: list[dict[str, Any]],
                                cell_items: list[dict[str, Any]]) -> dict[str, Any]:
    all_cells = {str(cell.get("cell_id")) for cell in cell_items if cell.get("cell_id")}
    own_cells = {str(unit.get("table_context", {}).get("cell_id"))
                 for unit in units if unit.get("unit_kind") == "table_cell"}
    covered = set()
    for unit in units:
        covered.update(str(cell_id) for cell_id in unit.get("covers_cell_ids") or [])
    missing = sorted(all_cells - own_cells - covered)
    extra = sorted((own_cells | covered) - all_cells)
    if missing or extra:
        raise ValueError(
            f"extraction unit cell 守恒破坏：missing={missing[:5]} extra={extra[:5]}")
    return {
        "cells_total": len(all_cells),
        "cells_own_units": len(own_cells),
        "cells_covered_by_row_units": len(covered - own_cells),
        "ok": True,
    }


def build_extraction_units(blocks: list[dict[str, Any]],
                           table_items: list[dict[str, Any]],
                           cell_items: list[dict[str, Any]],
                           dispositions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """纯函数构建全部单元（不落盘）。返回 (units, plan_summary)。"""
    sections = assemble_sections(blocks, table_items, cell_items, dispositions)
    resolve_section_refs(sections)
    order_by_block = {
        str(block.get("block_id")): int(block.get("order") or 0)
        for block in blocks if block.get("block_id")
    }
    for section in sections:
        section["_first_block_order"] = min(
            (order_by_block.get(str(bid), 0) for bid in (section.get("block_ids") or [""])),
            default=0)
    def_ref_units, section_defs = _definition_and_reference_units(sections)
    prose_units = _prose_units(blocks, section_defs)
    disposition_map = {
        str(row.get("cell_id")): row for row in dispositions if row.get("cell_id")}
    table_units = _table_units(blocks, table_items, cell_items,
                               disposition_map, section_defs)
    units = sorted(prose_units + table_units + def_ref_units,
                   key=lambda unit: unit["_sort_key"])
    for unit in units:
        unit.pop("_sort_key", None)
    conservation = _validate_cell_conservation(units, cell_items)
    counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for unit in units:
        counts[unit["unit_kind"]] = counts.get(unit["unit_kind"], 0) + 1
        for role in unit["roles"]:
            role_counts[role] = role_counts.get(role, 0) + 1
    summary = {
        "schema": EXTRACTION_UNIT_PLAN_SCHEMA,
        "planner_version": EXTRACTION_UNIT_PLANNER_VERSION,
        "unit_schema": EXTRACTION_UNIT_SCHEMA,
        "unit_count": len(units),
        "counts_by_kind": dict(sorted(counts.items())),
        "counts_by_role": dict(sorted(role_counts.items())),
        "cell_conservation": conservation,
        "sources": {
            "blocks": len(blocks),
            "table_row_items": len(table_items),
            "table_cell_items": len(cell_items),
            "table_cell_dispositions": len(dispositions),
        },
    }
    return units, summary


def load_planning_inputs(out_dir) -> tuple[list[dict[str, Any]], ...]:
    from result_package import governed_artifact_path

    def _read(name: str) -> list[dict[str, Any]]:
        path = governed_artifact_path(out_dir, name, category="pipeline", for_write=False)
        return read_jsonl(path) if path.is_file() else []

    return tuple(_read(name) for name in (
        "blocks.jsonl", "table_items.jsonl", "table_cell_items.jsonl",
        "table_cell_dispositions.jsonl"))


def plan_extraction_units(out_dir) -> dict[str, Any]:
    """从产物目录规划单元并写 governed artifact ``extraction_units.jsonl``。"""
    blocks, table_items, cell_items, dispositions = load_planning_inputs(out_dir)
    units, summary = build_extraction_units(blocks, table_items, cell_items, dispositions)
    store = ArtifactStore(out_dir, category="pipeline")
    store.write_jsonl(EXTRACTION_UNITS_FILENAME, units)
    summary["artifact"] = EXTRACTION_UNITS_FILENAME
    return summary


def load_extraction_units(out_dir) -> list[dict[str, Any]]:
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, EXTRACTION_UNITS_FILENAME,
                                  category="pipeline", for_write=False)
    return read_jsonl(path) if path.is_file() else []
