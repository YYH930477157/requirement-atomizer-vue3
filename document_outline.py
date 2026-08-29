"""确定性文档大纲权威（Phase 2 shadow，零 LLM，零消费者接线）。

解析器的 heading / section_path 已被实证四类病理：正文义务句升格、块流吞下一章
heading、section_path 撞名、chunk 无自身标题。本模块只读 blocks，产出可审计的
大纲验证报告，供 Phase 2b 接线前量化；不改 extract_units / functional_extract /
atomize 行为，不 bump 既有版本常量。

宁漏勿错：编号序列断裂只作 suspect 证据，不单独降格；全大写短标题永不降格；
判据不确定时保持 confirmed 或标 suspect，绝不猜成 demoted/toc。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from artifact_store import ArtifactStore
from functional_drilldown import _SENTENCE_SPLIT_RE
from unit_router import _SUBJECT_MODAL_RE

DOCUMENT_OUTLINE_VERSION = "document-outline-v1"
DOCUMENT_OUTLINE_SCHEMA = "document-outline/v1"
DOCUMENT_OUTLINE_FILENAME = "document_outline.json"

VERDICTS = ("confirmed", "demoted_body_sentence", "toc_entry", "suspect")

# Phase 2b 条款装配层接线（第一片）：重切器自身的版本身份。
# 刻意独立于 DOCUMENT_OUTLINE_VERSION（不 bump 后者）——后者钉住的是**报告构造器**
# （verdict 判据）的行为身份，本片不改判据，bump 会让 flag 关时的 document_outline.json
# 产物字节漂移，违反"默认关逐字节零变化"红线；重切是新增消费者，自立身份。
OUTLINE_AUTHORITY_VERSION = "outline-authority-v1"
OUTLINE_AUTHORITY_ENV = "RATOMIZER_OUTLINE_AUTHORITY"

# 剥编号后的义务句最短长度。组合夹具升格句约 73 字；短标题（The meter shall.）不降格。
BODY_SENTENCE_MIN_CHARS = 60
# 同一 section_path 末段被超过该数量的 heading 复用才报撞名（>3）。
SECTION_ID_COLLISION_MIN = 4

# 只认条款编号：点号层级，或编号后紧跟字母标题。拒绝 "2 20 Control of" 这类断行残片。
_CLAUSE_NUM_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)*)(?:[.)]\s+|\s+(?=[A-Za-z\u00c0-\u024f]))"
)
_TOC_TAIL_RE = re.compile(
    r"(?:[.\u00b7\u2024\u2027]{2,}|\.(?:\s*\.){2,}|\t+)\s*\d{1,4}\s*$"
)
_SENTENCE_END_RE = re.compile(r"[。.!?！？]\s*$")


def _is_heading(block: dict[str, Any]) -> bool:
    return str(block.get("type") or "").strip().lower() == "heading"


def _block_text(block: dict[str, Any]) -> str:
    return str(block.get("text") or block.get("raw_text") or "").strip()


def _section_path(block: dict[str, Any]) -> list[str]:
    raw = block.get("section_path") or []
    if not isinstance(raw, list):
        return []
    return [str(part) for part in raw]


def _split_clause_number(text: str) -> tuple[tuple[int, ...] | None, str]:
    match = _CLAUSE_NUM_RE.match(text)
    if not match:
        return None, text.strip()
    parts = tuple(int(p) for p in match.group(1).split("."))
    return parts, text[match.end():].strip()


def _is_all_caps_title(body: str) -> bool:
    letters = [ch for ch in body if ch.isalpha()]
    if len(letters) < 3:
        return False
    return all(ch.isupper() for ch in letters)


def _has_modal(text: str) -> bool:
    return _SUBJECT_MODAL_RE.search(text) is not None


def _looks_complete_obligation_sentence(body: str) -> bool:
    """完整义务句：情态 + 句号结尾 + 超长。全大写标题由调用方先排除。

    标题被解析器截断、整块不以句号结尾时，只要切出的某一句自身过门也算
    （result3 OEM 升格句尾部是换行残片 ``Change of OEM at``）。
    """
    if not body or not _has_modal(body):
        return False
    pieces = [part.strip() for part in _SENTENCE_SPLIT_RE.split(body) if part.strip()]
    if not pieces:
        pieces = [body.strip()]
    for piece in pieces:
        if len(piece) < BODY_SENTENCE_MIN_CHARS:
            continue
        if not _SENTENCE_END_RE.search(piece):
            continue
        if _has_modal(piece):
            return True
    return False


def _has_toc_tail(text: str) -> bool:
    return bool(_TOC_TAIL_RE.search(text))


def _normalize_title_key(text: str) -> str:
    _number, body = _split_clause_number(text)
    body = _TOC_TAIL_RE.sub("", body).strip()
    return re.sub(r"\s+", " ", body).casefold()


def _number_transition(
    previous: tuple[int, ...], current: tuple[int, ...]
) -> str | None:
    """返回 break / regression，合法递进返回 None。"""
    if current == previous:
        return "regression"
    if len(current) == len(previous) + 1 and current[:-1] == previous:
        return None
    if len(current) == len(previous) and current[:-1] == previous[:-1]:
        if current[-1] == previous[-1] + 1:
            return None
        if current[-1] > previous[-1] + 1:
            return "break"
        return "regression"
    for depth in range(len(previous) - 1, 0, -1):
        ancestor = previous[:depth]
        if len(current) == depth and current[:-1] == ancestor[:-1]:
            if current[-1] == ancestor[-1] + 1:
                return None
            if current[-1] > ancestor[-1] + 1:
                return "break"
            return "regression"
    if len(current) == 1 and len(previous) >= 1:
        if current[0] == previous[0] + 1:
            return None
        if current[0] > previous[0] + 1:
            return "break"
        if current[0] < previous[0]:
            return "regression"
    if current < previous:
        return "regression"
    return "break"


def _heading_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [block for block in blocks if _is_heading(block) and _block_text(block)]


def _section_block_ids(section: dict[str, Any]) -> list[str]:
    """与审核脚本同口径：source_block_ids → block_ids → source_blocks.block_id。"""
    for key in ("source_block_ids", "block_ids"):
        raw = section.get(key)
        if isinstance(raw, list) and raw:
            return [str(item) for item in raw if str(item)]
    source_blocks = section.get("source_blocks") or []
    ids: list[str] = []
    for row in source_blocks:
        if not isinstance(row, dict):
            continue
        block_id = str(row.get("block_id") or "")
        if block_id:
            ids.append(block_id)
    return ids


def _section_identity(section: dict[str, Any]) -> str:
    section_id = str(section.get("section_id") or "").strip()
    if section_id:
        return section_id
    path = section.get("section_path") or []
    if isinstance(path, list) and path:
        return " / ".join(str(part) for part in path)
    return str(section.get("chunk_id") or "")


def _swallowed_headings_from_paths(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        groups[tuple(_section_path(block))].append(block)
    swallowed: list[dict[str, Any]] = []
    for path, group in groups.items():
        for index, block in enumerate(group):
            if not _is_heading(block) or not _block_text(block):
                continue
            if index == 0:
                continue
            swallowed.append({
                "block_id": str(block.get("block_id") or ""),
                "index": index,
                "section_path": list(path),
                "section": " / ".join(path),
                "text": _block_text(block),
            })
    return swallowed


def _swallowed_headings_from_sections(
    blocks: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(block.get("block_id") or ""): block for block in blocks}
    swallowed: list[dict[str, Any]] = []
    for section in sections:
        ids = _section_block_ids(section)
        section_id = _section_identity(section)
        for index, block_id in enumerate(ids):
            block = by_id.get(block_id)
            if block is None or not _is_heading(block) or not _block_text(block):
                continue
            if index == 0:
                continue
            swallowed.append({
                "section_id": section_id,
                "index": index,
                "block_id": block_id,
                "text": _block_text(block),
            })
    return swallowed


def _resolve_swallowed(
    blocks: list[dict[str, Any]],
    sections: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], str]:
    if sections is not None:
        return _swallowed_headings_from_sections(blocks, sections), "sections"
    return _swallowed_headings_from_paths(blocks), "block_section_path"


def _try_load_sections(out_dir: Path) -> list[dict[str, Any]] | None:
    """惰性装配条款；失败或没有可用 block 序列时返回 None（调用方回退）。

    刻意取**未经大纲权威重切**的原始条款——报告要在原始边界上检测吞并；
    flag 开时若在此读重切后条款，吞并已被切开、报告会谎报 0。
    """
    try:
        from functional_extract import load_clauses

        sections = load_clauses(out_dir, outline_authority=False)
    except Exception:
        return None
    if not isinstance(sections, list) or not sections:
        return None
    if not any(_section_block_ids(section) for section in sections):
        return None
    return sections


def _section_id_collisions(heading_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tail: dict[str, list[str]] = defaultdict(list)
    for row in heading_rows:
        path = row["section_path"]
        tail = str(path[-1]).strip() if path else ""
        if not tail:
            continue
        by_tail[tail].append(str(row["block_id"]))
    collisions: list[dict[str, Any]] = []
    for tail, block_ids in sorted(by_tail.items()):
        if len(block_ids) < SECTION_ID_COLLISION_MIN:
            continue
        collisions.append({
            "last_segment": tail,
            "section_count": len(block_ids),
            "heading_block_ids": block_ids,
        })
    return collisions


def build_outline_report(
    blocks: list[dict[str, Any]],
    *,
    sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """对 heading 块做确定性裁决，并报告吞并 heading 与 section 撞名。

    ``sections`` 为 ``load_clauses`` 同形条款列表时，吞并按条款 block 序列检测；
    缺席则回退 blocks 的 ``section_path`` 分组。
    """
    headings = _heading_blocks(blocks)
    swallowed, swallow_basis = _resolve_swallowed(blocks, sections)
    swallowed_ids = {item["block_id"] for item in swallowed if item.get("block_id")}

    first_toc_keys: dict[str, str] = {}
    seen_keys: dict[str, list[str]] = defaultdict(list)
    for block in headings:
        text = _block_text(block)
        key = _normalize_title_key(text)
        if not key:
            continue
        seen_keys[key].append(str(block.get("block_id") or ""))
        if key not in first_toc_keys and _has_toc_tail(text):
            first_toc_keys[key] = str(block.get("block_id") or "")

    heading_rows: list[dict[str, Any]] = []
    previous_number: tuple[int, ...] | None = None
    for block in headings:
        text = _block_text(block)
        number, body = _split_clause_number(text)
        evidence: list[dict[str, str]] = []
        verdict = "confirmed"

        toc_tail = _has_toc_tail(text)
        title_key = _normalize_title_key(text)
        duplicate_toc = (
            bool(title_key)
            and first_toc_keys.get(title_key) == str(block.get("block_id") or "")
            and len(seen_keys.get(title_key) or []) >= 2
        )
        if toc_tail:
            evidence.append({
                "kind": "toc_leader_page",
                "detail": "heading ends with leader dots or tab plus a page number",
            })
        if duplicate_toc:
            evidence.append({
                "kind": "toc_duplicate_title",
                "detail": "first occurrence has a page-number tail and the same title recurs",
            })
        if toc_tail or duplicate_toc:
            verdict = "toc_entry"

        all_caps = _is_all_caps_title(body)
        if all_caps:
            evidence.append({
                "kind": "all_caps_title",
                "detail": "uppercase title body is never demoted",
            })
        elif verdict != "toc_entry" and _looks_complete_obligation_sentence(body):
            evidence.append({
                "kind": "obligation_sentence",
                "detail": (
                    f"modal + sentence end + length>={BODY_SENTENCE_MIN_CHARS}"
                ),
            })
            verdict = "demoted_body_sentence"

        block_id = str(block.get("block_id") or "")
        if number is not None:
            if previous_number is not None:
                fault = _number_transition(previous_number, number)
                if fault == "break":
                    evidence.append({
                        "kind": "number_sequence_break",
                        "detail": f"{'.'.join(map(str, previous_number))} -> {'.'.join(map(str, number))}",
                    })
                    if verdict == "confirmed":
                        verdict = "suspect"
                elif fault == "regression":
                    evidence.append({
                        "kind": "number_sequence_regression",
                        "detail": f"{'.'.join(map(str, previous_number))} -> {'.'.join(map(str, number))}",
                    })
                    if verdict == "confirmed":
                        verdict = "suspect"
            # 只有非法大纲节点不进编号基线。被吞并 heading 仍是文档真实标题，
            # 编号属于真实序列；剔除会人为制造断裂、冤枉下游为 suspect。
            if verdict not in {"demoted_body_sentence", "toc_entry"}:
                previous_number = number

        if block_id in swallowed_ids:
            detail = (
                "heading is not first in its section block sequence"
                if swallow_basis == "sections"
                else "heading is not first in its section_path block sequence"
            )
            evidence.append({
                "kind": "swallowed_heading",
                "detail": detail,
            })

        heading_rows.append({
            "block_id": block_id,
            "text": text,
            "section_path": _section_path(block),
            "clause_number": list(number) if number is not None else None,
            "verdict": verdict,
            "evidence": evidence,
        })

    collisions = _section_id_collisions(heading_rows)
    counts = Counter(row["verdict"] for row in heading_rows)
    summary = {
        "heading_count": len(heading_rows),
        "confirmed": int(counts.get("confirmed", 0)),
        "demoted_body_sentence": int(counts.get("demoted_body_sentence", 0)),
        "toc_entry": int(counts.get("toc_entry", 0)),
        "suspect": int(counts.get("suspect", 0)),
        "swallowed_heading_count": len(swallowed),
        "section_id_collision_count": len(collisions),
        "swallow_detection_basis": swallow_basis,
    }
    return {
        "schema": DOCUMENT_OUTLINE_SCHEMA,
        "version": DOCUMENT_OUTLINE_VERSION,
        "headings": heading_rows,
        "swallowed_headings": swallowed,
        "section_id_collisions": collisions,
        "summary": summary,
    }


def load_blocks(out_dir: Path | str) -> list[dict[str, Any]]:
    from atomize import AtomizerInputError
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    path = governed_artifact_path(
        Path(out_dir), "blocks.jsonl", category="pipeline", for_write=False,
    )
    if not path.is_file():
        raise AtomizerInputError(f"missing blocks.jsonl under {out_dir}")
    rows = read_jsonl(path)
    return [row for row in rows if isinstance(row, dict)]


def write_outline_report(
    out_dir: Path | str,
    blocks: list[dict[str, Any]] | None = None,
    *,
    sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """写 governed ``document_outline.json``（package_v1: pipeline/；legacy: 根文件）。

    未显式传入 ``sections`` 时惰性 ``load_clauses``；装配失败或条款没有 block 序列
    则回退 blocks-only，并在 summary 里如实标注 basis。
    """
    resolved = Path(out_dir)
    payload_blocks = list(blocks) if blocks is not None else load_blocks(resolved)
    payload_sections = sections if sections is not None else _try_load_sections(resolved)
    report = build_outline_report(payload_blocks, sections=payload_sections)
    store = ArtifactStore(resolved, category="pipeline")
    store.write_json(DOCUMENT_OUTLINE_FILENAME, report)
    report = dict(report)
    report["artifact"] = DOCUMENT_OUTLINE_FILENAME
    return report


# ---------------------------------------------------------------------------
# Phase 2b 第一片：条款装配层按大纲裁决重切（flag 门控，默认关）
# ---------------------------------------------------------------------------

class OutlineAuthorityError(RuntimeError):
    """重切块守恒被破坏——重切器自身缺陷（不是文档问题），立即响亮失败。"""


def outline_authority_enabled(value: str | None = None) -> bool:
    """RATOMIZER_OUTLINE_AUTHORITY 是否开启（默认关；单源默认值在 config.ENV_REGISTRY）。"""
    from config import get_env_bool

    return get_env_bool(OUTLINE_AUTHORITY_ENV, override=value)


def outline_authority_lineage() -> dict[str, str]:
    """大纲接线血统（照抄 routing_lineage_versions 的消费模式）。

    flag 开 → 携带版本身份（进抽取缓存指纹与 chain 阶段 producer）；
    flag 关 → 空 dict（两处指纹/戳逐字节不变）。
    """
    if outline_authority_enabled():
        return {"outline_authority": OUTLINE_AUTHORITY_VERSION}
    return {}


def _chunk_block_text(block: dict[str, Any]) -> str:
    """``atomize.build_chunks`` 的逐块文本配方（确定性复刻，不 import atomize）。

    chunks.jsonl 的 ``text`` 即按此配方以 ``"\\n\\n"`` 连接；重切切块时用同一配方
    重建分片文本，对 build_chunks 产物逐字节一致（result3 207/207 实证）。
    """
    block_type = str(block.get("type") or "")
    if block_type == "heading":
        return f"# {block.get('text') or ''}"
    if block_type == "table":
        return f"[{block.get('table_id')}] {block.get('table_title')}\n{block.get('text') or ''}"
    return str(block.get("text") or "")


def _table_header_candidate(block: dict[str, Any]) -> str:
    """复刻 ``_structured_table_source`` 的 repeat_header_line 判定（parameter 表才有）。"""
    try:  # 延迟 import：ai_extract 重依赖，报告/重切路径不必背上
        from ai_extract import classify_table_kind
    except ImportError:  # pragma: no cover - ai_extract 始终在场
        return ""
    headers = [str(value or "") for value in (block.get("headers") or [])]
    if classify_table_kind(block) == "parameter":
        return " | ".join(headers)
    return ""


def _decompose_section(
    section: dict[str, Any],
    blocks_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """把条款拆成有序块单元（逐块文本贡献 + 溯源条目），供重切分段/重建。

    返回 ``(units, decomposable)``；``decomposable=False`` 表示块序列无法逐块
    对齐（不应发生的形态）——调用方对该条款整段不切（宁漏勿错），仍可整体并入。

    两种输入形态：
    - assemble 形态（``source_blocks`` 列表在场，``extract_units.assemble_sections``
      产物）：block_ids 与 source_blocks 同序对齐——非表块恰一条、表块 0..n 条
      （无结构叶的表块不产 source 但占 block_ids 位）；
    - chunks 形态（``load_clauses`` 从 chunks.jsonl 构造）：无逐块溯源，按
      build_chunks 配方从 blocks 重建文本贡献；块缺席（旧产物）即不可分解。
    """
    block_ids = [str(item) for item in (section.get("block_ids") or [])]
    units: list[dict[str, Any]] = []
    source_blocks = section.get("source_blocks")
    if isinstance(source_blocks, list):
        entries = [row for row in source_blocks if isinstance(row, dict)]
        cursor = 0
        for block_id in block_ids:
            own: list[dict[str, Any]] = []
            while (
                cursor < len(entries)
                and str(entries[cursor].get("block_id") or "") == block_id
            ):
                own.append(entries[cursor])
                cursor += 1
            if not own:
                units.append({
                    "block_id": block_id, "text": "", "sb": None,
                    "header_candidate": False, "structured": False,
                })
                continue
            for entry in own:
                units.append({
                    "block_id": block_id,
                    "text": str(entry.get("text") or ""),
                    "sb": entry,
                    "header_candidate": False,
                    "structured": str(entry.get("table_input_mode") or "")
                    == "structured_leaves",
                })
        if cursor != len(entries):
            return units, False
        # 表头渲染行候选：只有表块可能持有（用于把原 _table_header_lines 按序落回分片）
        block_kind_cache: dict[str, bool] = {}
        for unit in units:
            block = blocks_by_id.get(unit["block_id"])
            if block is None or str(block.get("type") or "") != "table":
                continue
            is_candidate = block_kind_cache.get(unit["block_id"])
            if is_candidate is None:
                is_candidate = bool(_table_header_candidate(block))
                block_kind_cache[unit["block_id"]] = is_candidate
            unit["header_candidate"] = bool(is_candidate)
        return units, True
    for block_id in block_ids:
        block = blocks_by_id.get(block_id)
        if block is None:
            return units, False
        units.append({
            "block_id": block_id,
            "text": _chunk_block_text(block),
            "sb": None,
            "header_candidate": False,
            "structured": False,
        })
    return units, True


def _section_shape(section: dict[str, Any]) -> str:
    return "assemble" if isinstance(section.get("source_blocks"), list) else "chunks"


def _join_unit_texts(units: list[dict[str, Any]], shape: str) -> str:
    if shape == "assemble":
        # assemble 契约：只拼非空贡献、"\n" 连接、整体 strip（assemble_sections 同款）
        return "\n".join(unit["text"] for unit in units if unit["text"]).strip()
    # chunks 契约：build_chunks 全量部件 "\n\n" 连接、不 strip
    return "\n\n".join(unit["text"] for unit in units)


def _assign_header_lines(
    units: list[dict[str, Any]],
    header_queue: list[str],
) -> dict[str, list[str]]:
    """把原条款的 ``_table_header_lines`` 按序落回块单元（assemble 形态分片用）。

    候选位 = 表块且 repeat 判定非空；**就地消费** ``header_queue``（跨分段连续，
    不重复分配）；剩余原行（嵌套表等罕见形态对不齐）由调用方保守挂回本条款
    末段——表头行宁多挂不丢失（只影响超长分片的续 chunk 表头注入，不影响守恒）。
    """
    assigned: dict[int, list[str]] = {}
    for index, unit in enumerate(units):
        if not header_queue:
            break
        if not unit.get("header_candidate"):
            continue
        assigned.setdefault(index, []).append(header_queue.pop(0))
    return {str(index): lines for index, lines in assigned.items()}


def _build_clause(
    shape: str,
    identity: tuple[str, list[str], str],
    units: list[dict[str, Any]],
    header_lines_by_unit: dict[str, list[str]],
) -> dict[str, Any]:
    section_id, section_path, heading = identity
    clause: dict[str, Any] = {
        "section_id": section_id,
        "section_path": list(section_path),
        "heading": heading,
        "text": _join_unit_texts(units, shape),
        "block_ids": [unit["block_id"] for unit in units],
    }
    if shape == "assemble":
        clause["source_blocks"] = [
            unit["sb"] for unit in units if unit.get("sb") is not None
        ]
        headers: list[str] = []
        for index in range(len(units)):
            headers.extend(header_lines_by_unit.get(str(index)) or [])
        clause["_table_header_lines"] = headers
        clause["table_input_mode"] = (
            "structured_leaves"
            if any(unit.get("structured") for unit in units)
            else "plain_text"
        )
    return clause


def _merge_units_into(
    clause: dict[str, Any],
    units: list[dict[str, Any]],
    shape: str,
    header_lines_by_unit: dict[str, list[str]],
) -> dict[str, Any]:
    """把 demoted 升格句领起的分段并入前一条款（作为正文块，不自立条款）。"""
    merged = dict(clause)
    piece_text = _join_unit_texts(units, shape)
    previous_text = str(merged.get("text") or "")
    separator = "\n" if shape == "assemble" else "\n\n"
    if piece_text:
        merged["text"] = (
            previous_text + separator + piece_text if previous_text else piece_text
        )
    merged["block_ids"] = list(merged.get("block_ids") or []) + [
        unit["block_id"] for unit in units
    ]
    if shape == "assemble":
        merged["source_blocks"] = list(merged.get("source_blocks") or []) + [
            unit["sb"] for unit in units if unit.get("sb") is not None
        ]
        headers = list(merged.get("_table_header_lines") or [])
        for index in range(len(units)):
            headers.extend(header_lines_by_unit.get(str(index)) or [])
        merged["_table_header_lines"] = headers
        merged["table_input_mode"] = (
            "structured_leaves"
            if str(merged.get("table_input_mode")) == "structured_leaves"
            or any(unit.get("structured") for unit in units)
            else "plain_text"
        )
    return merged


def _verify_block_conservation(
    input_sections: list[dict[str, Any]],
    output_clauses: list[dict[str, Any]],
    excluded_block_ids: list[str],
) -> None:
    """硬校验：输入条款的每个块恰好归属一个输出条款或登记排除（toc/空段）。"""
    expected = Counter(
        str(block_id)
        for section in input_sections
        for block_id in (section.get("block_ids") or [])
    )
    actual = Counter(
        str(block_id)
        for clause in output_clauses
        for block_id in (clause.get("block_ids") or [])
    )
    actual.update(str(block_id) for block_id in excluded_block_ids)
    if expected != actual:
        missing = sorted((expected - actual).elements())
        extra = sorted((actual - expected).elements())
        raise OutlineAuthorityError(
            "大纲权威重切块守恒被破坏："
            f"输入块 {sum(expected.values())} 个 / 输出+排除 {sum(actual.values())} 个；"
            f"缺失样例 {missing[:5]}；多余样例 {extra[:5]}"
        )


def recut_clauses(
    blocks: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    report: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按大纲裁决重切条款边界（纯函数，Phase 2b 单一事实源）。

    输入 blocks+sections+report，输出 ``(重切后条款, 审计)``。裁决语义：

    - ``demoted_body_sentence``：升格正文句不再是切分点——其领起的分段并入
      前一条款作为正文块（首条款无前者则如实保留并审计）；
    - 被吞并 heading（报告 swallowed 集内且 verdict=confirmed）：在该块处切开，
      heading 及其后块成新条款；新条款身份**从 heading 文本派生**
      （section_path=[剥离后全文]，编号+标题天然随文）——刻意不继承被吞并
      所在条款的父链：该父链本身是病理的一部分（result3 实证 "2.3 STATEMENT
      OF REQUIREMENTS" 会错挂 "3 Any conflict of interest..." 为父）；
    - ``toc_entry``：不作切分点也不进条款正文基线（从 block_ids/source_blocks/
      text 剔除并登记审计；blocks.jsonl 原样保留，不删块）；
    - ``suspect``：宁漏勿错——只作审计证据，不改切分。

    未受影响的条款**原对象原样透传**（逐字节稳定）；只有被切/并/剔的分段按
    各自形态的文本契约（assemble=非空贡献 "\\n" 连接、chunks=build_chunks
    配方 "\\n\\n" 连接）重建。块守恒硬校验失败即抛 :class:`OutlineAuthorityError`。
    """
    blocks_list = [block for block in blocks if isinstance(block, dict)]
    blocks_by_id = {
        str(block.get("block_id") or ""): block for block in blocks_list
    }
    verdicts: dict[str, str] = {
        str(row.get("block_id") or ""): str(row.get("verdict") or "")
        for row in (report.get("headings") or [])
        if isinstance(row, dict) and row.get("block_id")
    }
    swallowed_ids = {
        str(item.get("block_id") or "")
        for item in (report.get("swallowed_headings") or [])
        if isinstance(item, dict) and item.get("block_id")
    }
    # 只有 confirmed 的被吞并 heading 才切开；suspect/demoted/toc 的吞并不动
    # （宁漏勿错：suspect 可能是真标题，demoted 是正文句，toc 是目录）。
    cut_ids = {
        block_id for block_id in swallowed_ids
        if verdicts.get(block_id) == "confirmed"
    }
    suspect_ids = {
        block_id for block_id, verdict in verdicts.items() if verdict == "suspect"
    }

    audit: dict[str, Any] = {
        "version": OUTLINE_AUTHORITY_VERSION,
        "status": "applied",
        "swallow_detection_basis": str(
            (report.get("summary") or {}).get("swallow_detection_basis") or ""
        ),
        "input_clause_count": len(sections),
        "output_clause_count": 0,
        "swallowed_heading_count": len(swallowed_ids),
        "swallowed_cut_block_ids": [],
        "demoted_merged_block_ids": [],
        "demoted_leading_without_predecessor_block_ids": [],
        "toc_excluded_block_ids": [],
        "dropped_empty_clause_count": 0,
        "non_decomposable_section_ids": [],
        "suspect_headings_in_clauses": 0,
    }

    output: list[dict[str, Any]] = []
    for section in sections:
        if not (section.get("block_ids") or []):
            output.append(section)  # 无块序列——无从重切，原样保留
            continue
        units, decomposable = _decompose_section(section, blocks_by_id)
        shape = _section_shape(section)

        pieces: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for unit in units:
            if unit["block_id"] in cut_ids and current:
                pieces.append(current)
                current = [unit]
                continue
            current.append(unit)
        if current:
            pieces.append(current)
        if not decomposable and len(pieces) > 1:
            # 块序列对不齐（不应发生）：整段不切，如实审计
            audit["non_decomposable_section_ids"].append(
                str(section.get("section_id") or "")
            )
            pieces = [units]

        original_headers = [
            str(line) for line in (section.get("_table_header_lines") or [])
        ]
        header_queue = list(original_headers)
        changed = len(pieces) > 1
        section_touched_output = False
        for piece_index, piece in enumerate(pieces):
            kept = [
                unit for unit in piece
                if verdicts.get(unit["block_id"]) != "toc_entry"
            ]
            toc_units = [
                unit for unit in piece
                if verdicts.get(unit["block_id"]) == "toc_entry"
            ]
            if toc_units:
                changed = True
                audit["toc_excluded_block_ids"].extend(
                    unit["block_id"] for unit in toc_units
                )
            if not kept:
                # 整段只剩 toc 块：条款消失。这些块已在 toc_excluded_block_ids
                # 登记排除（守恒口径唯一），此处只记条款消失事件，不重复登记。
                changed = True
                audit["dropped_empty_clause_count"] = (
                    audit.get("dropped_empty_clause_count", 0) + 1
                )
                continue
            header_map = (
                _assign_header_lines(kept, header_queue)
                if shape == "assemble" else {}
            )
            first_block_id = kept[0]["block_id"]
            if verdicts.get(first_block_id) == "demoted_body_sentence":
                if output:
                    audit["demoted_merged_block_ids"].append(first_block_id)
                    output[-1] = _merge_units_into(
                        output[-1], kept, shape, header_map)
                    changed = True
                    section_touched_output = True
                    continue
                audit["demoted_leading_without_predecessor_block_ids"].append(
                    first_block_id
                )
            if not changed and piece_index == 0:
                # 未被切/并/剔：原对象透传（未受影响条款逐字节稳定）
                output.append(section)
                section_touched_output = True
                continue
            if piece_index == 0:
                identity = (
                    str(section.get("section_id") or ""),
                    [str(part) for part in (section.get("section_path") or [])],
                    str(section.get("heading") or ""),
                )
            else:
                heading_text = _block_text(blocks_by_id.get(first_block_id) or {})
                identity = (heading_text, [heading_text], heading_text)
                audit["swallowed_cut_block_ids"].append(first_block_id)
            output.append(_build_clause(shape, identity, kept, header_map))
            section_touched_output = True
        if header_queue and changed and section_touched_output and shape == "assemble":
            # 嵌套表等罕见形态的落单表头行：保守挂回本条款末段（宁多挂不丢失）。
            # 仅对被重建的条款生效——原样透传的条款自身已带全量表头行，再挂会重复。
            output[-1]["_table_header_lines"] = list(
                output[-1].get("_table_header_lines") or []
            ) + header_queue
        audit["suspect_headings_in_clauses"] += sum(
            1 for unit in units if unit["block_id"] in suspect_ids
        )

    excluded = list(audit["toc_excluded_block_ids"])
    _verify_block_conservation(sections, output, excluded)
    audit["output_clause_count"] = len(output)
    return output, audit


def apply_outline_authority(
    blocks: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    *,
    enabled: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """大纲权威重切的唯一 flag 检查点（两个消费点共用，不各自实现）。

    - flag 关（默认）：``(原 sections, None)``——零行为变化；
    - flag 开：现算报告（确定性纯函数，杜绝读旧产物 的
      陈旧性错切）并重切；blocks/块序列不可得时**如实回退全量旧切分**，
      审计记 ``unavailable:<reason>``，绝不静默假装重切过。
    """
    if enabled is None:
        enabled = outline_authority_enabled()
    if not enabled:
        return sections, None
    blocks_list = [block for block in blocks if isinstance(block, dict)]
    if not blocks_list:
        return sections, {
            "version": OUTLINE_AUTHORITY_VERSION,
            "status": "unavailable:blocks_missing",
        }
    if not any(_section_block_ids(section) for section in sections):
        return sections, {
            "version": OUTLINE_AUTHORITY_VERSION,
            "status": "unavailable:no_block_sequences",
        }
    report = build_outline_report(blocks_list, sections=sections)
    return recut_clauses(blocks_list, sections, report)
