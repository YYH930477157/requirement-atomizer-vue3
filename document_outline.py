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
    """惰性装配条款；失败或没有可用 block 序列时返回 None（调用方回退）。"""
    try:
        from functional_extract import load_clauses

        sections = load_clauses(out_dir)
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
            # 降格句 / 目录项 / 被吞并 heading 不进入大纲编号基线（它们不是合法大纲节点）。
            if verdict not in {"demoted_body_sentence", "toc_entry"} and block_id not in swallowed_ids:
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
