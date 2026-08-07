"""V3 WS-A A1：整篇地图（doc_map，LLM 一遍，默认关闭）。

输入 atomize/extract_units 产物（blocks/chunks 条款单元），LLM 单遍产出文档级地图：
章节骨架、条款→块映射、表格族分布（复用 ``table_family_templates`` 确定性表头匹配）、
需求密度热区。结构层（scaffold）全部确定性计算；LLM 只贡献语义注释层
（document_type / domains / hotspot_rationale / notes），两层分账，LLM 注释绝不改写
结构层字段。

纪律（与 functional_extract 同源）：

* **预算走文档预算单**：真实路由经 ``llm_client.chat_json`` 自动扣减；调用包在
  ``structure_hypothesis`` 子预算环节（``LLMBudgetLedger.enter_stage``）。耗尽抛
  ``LLMBudgetExceeded`` → 如实 ``unavailable:budget_exhausted`` 并 ``mark_degraded``，
  绝不伪造地图。
* **按内容指纹缓存**：指纹含 ``DOC_MAP_VERSION`` + prompt 版本 + route 维度 + 内容指纹
  （S1-7 教训：stub/LLM 产物不共键）。同一文档二次调用缓存命中零 LLM。
* **stub/无 key 如实 unavailable**：``status="unavailable:llm_unavailable"``，不写
  ``doc_map.json``，调用方（A2 上下文包等）退回无地图路径。
* **幻觉编码硬拦**：LLM 注释里出现但来源全文没有的 OBIS/hex/class_id/标准号一律剔除
  并记 ``rejected_codes``（复用 ``cosem_behavior_spec.extract_codes``）。
* **封闭 schema**：产物校验 ``schemas/doc_map.schema.json``（additionalProperties 全闭）。

入口开关 ``RATOMIZER_DOC_MAP``（默认 ``0``）。产物路径走
``result_package.governed_artifact_path``。测试中禁止真实 LLM 调用。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

from cosem_behavior_spec import extract_codes
from requirement_record import provenance

DOC_MAP_VERSION = "doc-map-v1"
DOC_MAP_PROMPT_VERSION = "doc-map-prompt-v1"
DOC_MAP_SCHEMA = "doc-map/v1"
DOC_MAP_FILENAME = "doc_map.json"
DOC_MAP_CACHE = "doc_map_cache.jsonl"

LOGGER = logging.getLogger("requirement_atomizer")

# 入口开关（config.ENV_REGISTRY 登记）：默认 0=不生成整篇地图，调用方走无地图路径。
ENTRY_SWITCH_ENV = "RATOMIZER_DOC_MAP"

ExtractChat = Callable[[str, str], dict[str, Any]]

_SYSTEM_PROMPT = (
    "你是技术标准文档的整篇结构分析师。输入是确定性预处理出的文档脚手架：章节骨架"
    "（条款号/标题/字符量/块溯源）、条款→块映射、表格族分布、需求密度热区。"
    "你只产出语义注释，不重述结构数据：\n"
    "①document_type：文档类型一句话（如 metering profile / tender specification）；"
    "②domains：按功能域归纳，每个域给出 name、覆盖的 section_ids（必须取自输入骨架）、"
    "一句 summary；③hotspot_rationale：对每个需求密度热区给一句理由（chapter 必须取自输入）；"
    "④notes：其他整篇观察。\n"
    "硬约束：只能引用输入中出现的章节号/块 ID/编码（OBIS/hex/class_id/标准号），禁止臆造；"
    "拿不准的域不要编造，宁缺勿猜。\n"
    "输出 JSON：{\"document_type\": str, \"domains\": [{\"name\", \"section_ids\": [], "
    "\"summary\"}], \"hotspot_rationale\": [{\"chapter\", \"rationale\"}], \"notes\": str}。"
)

# LLM 注释层允许的顶层键（封闭契约；多键/缺键均判 invalid）
_LLM_KEYS = {"document_type", "domains", "hotspot_rationale", "notes"}


# ---------------------------------------------------------------------------
# 入口开关
# ---------------------------------------------------------------------------

def doc_map_enabled(value: str | None = None) -> bool:
    """RATOMIZER_DOC_MAP 是否开启（默认关）。"""
    raw = os.environ.get(ENTRY_SWITCH_ENV) if value is None else value
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# 确定性 scaffold（零 LLM）
# ---------------------------------------------------------------------------

def _chapter_of(section: dict[str, Any]) -> str:
    path = [str(s) for s in (section.get("section_path") or []) if str(s).strip()]
    return path[0] if path else str(section.get("section_id") or "(root)")


def build_scaffold(
    sections: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """确定性文档脚手架：章节骨架 + 条款→块映射 + 表格族分布 + 需求密度热区。

    纯函数：同输入同输出（测试钉死）。表格族分布复用 ``table_family_templates`` 的
    确定性表头打分（score 仅为建议性，绝不签署结构决定）；族库缺失时全部 unmatched。
    """
    skeleton: list[dict[str, Any]] = []
    clause_block_map: list[dict[str, Any]] = []
    for section in sections:
        block_ids = [str(b) for b in (section.get("block_ids") or []) if str(b)]
        heading = str(section.get("heading") or "")
        from extract_units import clause_key  # 复用条款族键（两级）

        skeleton.append({
            "section_id": str(section.get("section_id") or ""),
            "heading": heading,
            "section_path": [str(s) for s in (section.get("section_path") or [])],
            "clause_family": clause_key(section),
            "char_count": len(str(section.get("text") or "")),
            "block_count": len(block_ids),
        })
        clause_block_map.append({
            "section_id": str(section.get("section_id") or ""),
            "block_ids": block_ids,
        })

    table_families: list[dict[str, Any]] = []
    density: dict[str, dict[str, int]] = {}
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        chapter = _first_path_element(block)
        if chapter:
            slot = density.setdefault(chapter, {"total": 0, "requirement_like": 0})
            slot["total"] += 1
            if block.get("requirement_like") and not block.get("noise"):
                slot["requirement_like"] += 1
        if str(block.get("type") or "") != "table":
            continue
        headers = [str(h or "") for h in (block.get("headers") or [])]
        family_id, score = _match_table_family(headers)
        table_families.append({
            "block_id": str(block.get("block_id") or ""),
            "table_id": str(block.get("table_id") or block.get("block_id") or ""),
            "headers": headers,
            "family_id": family_id,
            "match_score": score,
        })

    density_hotspots = [
        {
            "chapter": chapter,
            "requirement_like_blocks": slot["requirement_like"],
            "total_blocks": slot["total"],
            "density": round(slot["requirement_like"] / slot["total"], 4) if slot["total"] else 0.0,
        }
        for chapter, slot in sorted(density.items())
    ]
    return {
        "skeleton": skeleton,
        "clause_block_map": clause_block_map,
        "table_families": table_families,
        "density_hotspots": density_hotspots,
    }


def _first_path_element(block: dict[str, Any]) -> str:
    path = [str(s) for s in (block.get("section_path") or []) if str(s).strip()]
    return path[0] if path else ""


def _match_table_family(headers: list[str]) -> tuple[str, int]:
    """表头 → 最佳匹配族（确定性打分；无命中/族库缺失 → unmatched）。"""
    try:
        from table_family_templates import load_table_family_templates
        library = load_table_family_templates()
    except Exception:  # noqa: BLE001 — 族库缺失不阻断 scaffold
        return "unmatched", 0
    best_id, best_score = "unmatched", 0
    for family in library.families:
        score = family.detection_hints.header_score(headers)
        if score > best_score:
            best_id, best_score = family.family_id, score
    return best_id, best_score


# ---------------------------------------------------------------------------
# 内容指纹 / 缓存键
# ---------------------------------------------------------------------------

def _content_fingerprint(
    sections: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]] | None,
) -> str:
    """输入内容指纹：条款指纹 + 表格块结构哈希（表头/表型/行数）。"""
    from functional_extract import clause_fingerprint

    table_rows: list[dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict) or str(block.get("type") or "") != "table":
            continue
        table_rows.append({
            "block_id": str(block.get("block_id") or ""),
            "headers": [str(h or "") for h in (block.get("headers") or [])],
            "rows": len(block.get("data_rows") or []),
        })
    encoded = json.dumps(
        {
            "clauses": [clause_fingerprint(s) for s in sections],
            "tables": table_rows,
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def doc_map_fingerprint(
    sections: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]] | None,
    *,
    route_key: str = "",
) -> str:
    """缓存键：版本 + prompt + route 维度 + 内容指纹（S1-7：stub/LLM 不共键）。"""
    canonical = {
        "version": DOC_MAP_VERSION,
        "prompt": DOC_MAP_PROMPT_VERSION,
        "route_key": str(route_key or ""),
        "content": _content_fingerprint(sections, blocks),
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# LLM 注释层校验 + 幻觉编码硬拦
# ---------------------------------------------------------------------------

def _validate_llm_annotations(payload: Any) -> dict[str, Any] | None:
    """封闭校验 LLM 返回；非法返回 None（调用方标 unavailable，不伪造）。"""
    if not isinstance(payload, dict):
        return None
    if not set(payload.keys()).issubset(_LLM_KEYS):
        return None
    document_type = str(payload.get("document_type") or "").strip()
    if not document_type:
        return None
    domains: list[dict[str, Any]] = []
    for entry in payload.get("domains") or []:
        if not isinstance(entry, dict):
            return None
        name = str(entry.get("name") or "").strip()
        if not name:
            return None
        domains.append({
            "name": name,
            "section_ids": [str(s) for s in (entry.get("section_ids") or []) if str(s).strip()],
            "summary": str(entry.get("summary") or "").strip(),
        })
    rationales: list[dict[str, Any]] = []
    for entry in payload.get("hotspot_rationale") or []:
        if not isinstance(entry, dict):
            return None
        chapter = str(entry.get("chapter") or "").strip()
        if not chapter:
            return None
        rationales.append({
            "chapter": chapter,
            "rationale": str(entry.get("rationale") or "").strip(),
        })
    return {
        "document_type": document_type,
        "domains": domains,
        "hotspot_rationale": rationales,
        "notes": str(payload.get("notes") or "").strip(),
    }


def _source_corpus(sections: Sequence[dict[str, Any]]) -> str:
    return "\n".join(str(s.get("text") or "") for s in sections)


def _reject_drifted_codes(annotations: dict[str, Any], source_text: str) -> dict[str, Any]:
    """LLM 注释层幻觉编码硬拦：来源全文没有的 OBIS/hex/class_id/标准号逐字段剔除。"""
    allowed = extract_codes(source_text)
    rejected: set[str] = set()

    def _clean(text: str) -> str:
        cleaned = text
        for code in sorted(extract_codes(text) - allowed):
            rejected.add(code)
            cleaned = cleaned.replace(code, "")
        return cleaned

    annotations = dict(annotations)
    annotations["document_type"] = _clean(annotations["document_type"])
    annotations["notes"] = _clean(annotations["notes"])
    annotations["domains"] = [
        {**d, "summary": _clean(d["summary"])} for d in annotations["domains"]
    ]
    annotations["hotspot_rationale"] = [
        {**r, "rationale": _clean(r["rationale"])} for r in annotations["hotspot_rationale"]
    ]
    annotations["rejected_codes"] = sorted(rejected)
    return annotations


# ---------------------------------------------------------------------------
# 预算通知（S1-1 同款：降级即文档级 NEEDS WORK）
# ---------------------------------------------------------------------------

def _notify_budget_degraded(reason: str) -> None:
    try:
        import llm_client
        from llm_budget import STAGE_STRUCTURE_HYPOTHESIS

        hook = llm_client.get_document_budget_hook()
    except Exception:  # noqa: BLE001 — 预算通知失败不得影响主流程
        return
    if hook is None:
        return
    try:
        hook.mark_degraded(STAGE_STRUCTURE_HYPOTHESIS, str(reason))
    except Exception:  # noqa: BLE001 — 同上
        pass


# ---------------------------------------------------------------------------
# 缓存（与 functional_extract 同款：指纹命中放行，跨进程锁 + 原子替换）
# ---------------------------------------------------------------------------

def _read_cache(out_dir: Path) -> dict[str, dict[str, Any]]:
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, DOC_MAP_CACHE, category="cache", for_write=False)
    if not path.is_file():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            fp = str(row.get("fingerprint") or "")
            if fp:
                cache[fp] = row
    except (OSError, json.JSONDecodeError):
        return {}
    return cache


def _write_cache_entry(out_dir: Path, fingerprint: str, payload: dict[str, Any]) -> None:
    from process_file_lock import process_file_lock
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, DOC_MAP_CACHE, category="cache", for_write=True)
    lock_path = governed_artifact_path(
        out_dir, "doc_map_cache.lock", category="cache", for_write=True
    )
    entry = {"fingerprint": fingerprint, "payload": payload}
    tmp: Path | None = None
    try:
        with process_file_lock(lock_path, timeout_s=10.0, label="doc_map_cache"):
            existing = []
            if path.is_file():
                existing = [
                    line for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and json.loads(line).get("fingerprint") != fingerprint
                ]
            with tempfile.NamedTemporaryFile(
                mode="w", dir=path.parent, prefix=".doc_map_cache.",
                suffix=".tmp", delete=False, encoding="utf-8", newline="\n",
            ) as handle:
                tmp = Path(handle.name)
                for line in existing:
                    handle.write(line + "\n")
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            _replace_with_retry(tmp, path)
            tmp = None
    except Exception as exc:  # 缓存写失败不阻断主流程，只记日志
        LOGGER.warning("doc_map 缓存写入失败：%s", exc)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= 5:
                raise
            import time
            time.sleep(0.02 * (attempt + 1))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _build_user_prompt(scaffold: dict[str, Any]) -> str:
    """脚手架压缩进 prompt（骨架不含正文全文，密度/族分布为确定性预计算）。"""
    compact_skeleton = [
        {
            "section_id": row["section_id"],
            "heading": row["heading"],
            "clause_family": row["clause_family"],
            "char_count": row["char_count"],
        }
        for row in scaffold["skeleton"]
    ]
    return json.dumps(
        {
            "skeleton": compact_skeleton,
            "table_families": scaffold["table_families"],
            "density_hotspots": scaffold["density_hotspots"],
        },
        ensure_ascii=False,
    )


def run_doc_map(
    out_dir: Path | str,
    *,
    sections: Sequence[dict[str, Any]] | None = None,
    blocks: Sequence[dict[str, Any]] | None = None,
    route: str | None = "stub",
    chat: ExtractChat | None = None,
) -> dict[str, Any]:
    """运行整篇地图；成功写 ``doc_map.json``，不可用如实 unavailable 不写产物。

    ``sections``/``blocks`` 缺省时从 governed ``chunks.jsonl``/``blocks.jsonl`` 惰性加载
    （复用 functional_extract.load_clauses，不改 extract_units/atomize）。
    """
    import llm_client
    from functional_extract import _resolve_extract_chat, load_clauses

    out_dir = Path(out_dir).expanduser().resolve()
    if sections is None:
        sections = load_clauses(out_dir)
    sections = list(sections)
    if blocks is None:
        blocks = _load_blocks(out_dir)
    blocks = list(blocks or [])

    active_chat, executed_route = _resolve_extract_chat(route, chat)
    fingerprint = doc_map_fingerprint(sections, blocks, route_key=executed_route)

    if active_chat is None:
        # stub / 无 key：如实 unavailable，调用方退回无地图路径；不写产物、不留缓存。
        return {
            "kind": "doc_map",
            "status": "unavailable:llm_unavailable",
            "route_requested": route or "stub",
            "route": "stub",
            "fingerprint": fingerprint,
            "written": [],
        }

    # 缓存命中零 LLM（指纹含版本/prompt/route/内容）
    cached = _read_cache(out_dir).get(fingerprint)
    if cached is not None and isinstance(cached.get("payload"), dict):
        payload = dict(cached["payload"])
        return _result_summary(payload, out_dir, route, written=False)

    scaffold = build_scaffold(sections, blocks)

    # 预算：真实路由经 llm_client.chat_json 自动扣减；这里把调用包进
    # structure_hypothesis 子预算环节（无活动预算单时 enter_stage 空操作）。
    from llm_budget import STAGE_STRUCTURE_HYPOTHESIS

    hook = llm_client.get_document_budget_hook()
    enter_stage = getattr(hook, "enter_stage", None)
    try:
        if callable(enter_stage):
            with enter_stage(STAGE_STRUCTURE_HYPOTHESIS):
                raw = active_chat(_SYSTEM_PROMPT, _build_user_prompt(scaffold))
        else:
            raw = active_chat(_SYSTEM_PROMPT, _build_user_prompt(scaffold))
    except llm_client.LLMBudgetExceeded as exc:
        # 预算耗尽：诚实降级，不伪造地图；文档预算单记 degraded（S1-1 同款）
        LOGGER.warning("doc_map 预算耗尽，如实降级 unavailable：%s", exc)
        _notify_budget_degraded("doc_map_budget_exhausted")
        return {
            "kind": "doc_map",
            "status": "unavailable:budget_exhausted",
            "route_requested": route or "stub",
            "route": executed_route,
            "fingerprint": fingerprint,
            "written": [],
        }
    except Exception as exc:
        LOGGER.warning("doc_map LLM 调用失败，如实降级 unavailable：%s", exc)
        return {
            "kind": "doc_map",
            "status": "unavailable:llm_call_failed",
            "route_requested": route or "stub",
            "route": executed_route,
            "fingerprint": fingerprint,
            "written": [],
        }

    annotations = _validate_llm_annotations(raw)
    if annotations is None:
        LOGGER.warning("doc_map LLM 返回非法，如实降级 unavailable")
        return {
            "kind": "doc_map",
            "status": "unavailable:invalid_llm_payload",
            "route_requested": route or "stub",
            "route": executed_route,
            "fingerprint": fingerprint,
            "written": [],
        }
    annotations = _reject_drifted_codes(annotations, _source_corpus(sections))

    payload: dict[str, Any] = {
        "schema_version": DOC_MAP_SCHEMA,
        "producer": DOC_MAP_VERSION,
        "prompt_version": DOC_MAP_PROMPT_VERSION,
        "provenance": provenance("doc_map", DOC_MAP_VERSION),
        "status": "ok",
        "route_requested": route or "stub",
        "route": executed_route,
        "fingerprint": fingerprint,
        "content_fingerprint": _content_fingerprint(sections, blocks),
        "clause_count": len(sections),
        "scaffold": scaffold,
        "llm_annotations": annotations,
    }
    _write_cache_entry(out_dir, fingerprint, payload)
    return _result_summary(payload, out_dir, route, written=True)


def _result_summary(
    payload: dict[str, Any],
    out_dir: Path,
    route: str | None,
    *,
    written: bool,
) -> dict[str, Any]:
    from input_completeness import attach_input_completeness

    attach_input_completeness(payload, out_dir)
    if written:
        from result_package import governed_artifact_path

        target = governed_artifact_path(out_dir, DOC_MAP_FILENAME, category="pipeline")
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _replace_with_retry(tmp, target)
    return {
        "kind": "doc_map",
        "status": payload.get("status", "ok"),
        "route_requested": route or "stub",
        "route": payload.get("route", "stub"),
        "fingerprint": payload.get("fingerprint", ""),
        "clause_count": payload.get("clause_count", 0),
        "written": [DOC_MAP_FILENAME] if written else [],
    }


def _load_blocks(out_dir: Path) -> list[dict[str, Any]]:
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, "blocks.jsonl", category="pipeline", for_write=False)
    return read_jsonl(path) if path.is_file() else []


def load_doc_map(out_dir: Path | str) -> dict[str, Any] | None:
    """只读加载已产出的 doc_map.json（不存在/损坏返回 None，调用方退回无地图路径）。"""
    from result_package import governed_artifact_path

    out_dir = Path(out_dir).expanduser().resolve()
    path = governed_artifact_path(out_dir, DOC_MAP_FILENAME, category="pipeline", for_write=False)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != DOC_MAP_SCHEMA:
        return None
    if payload.get("status") != "ok":
        return None
    return payload
