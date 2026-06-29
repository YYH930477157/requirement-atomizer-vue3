"""AI 主导需求抽取（杠杆②）。

LLM 逐章节读已解析文本 → 直接产出功能级结构化需求（标题/自包含描述/类型/优先级/标签/
原文引用/验收）。面向"通用文档解读"：DLMS 结构化与通用标准文档统一一套流程。

防幻觉（数字双引擎，分严/松级）：
- 受保护编码（OBIS / 事件号 / 十六进制，extract_codes）只能来自源文/确定性层。LLM 输出里
  冒出原文没有的这类编码 → **严格拦**：该条降级 draft + 记 note，不当已确认。
- 普通整数（extract_ints）漂移 → **软标**：可能是 LLM 合理展开（如"RS-485"），记 note 待核，保留。

可复现（稳定）：温度 0 + 章节内容指纹缓存（同文本 + 同模型 → 命中、零再调，重跑逐字一致）。
成本：相邻小章节合并到目标字数再调（少调用）+ 并发；失败按章节降级、不崩。

route（复用 review_pipeline.yaml）：默认 stub（零 LLM）；openai_compatible 才真调
（DeepSeek / Ollama 等，OpenAI 兼容）。

用法：python -m ai_extract --out <atomizer 输出目录> [--route openai_compatible] [--doc]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from cosem_behavior_spec import extract_codes, extract_ints
from llm_client import LLMClientConfig, LLMError, chat_json
from llm_pipeline import (
    DEFAULT_PIPELINE_PATH,
    apply_llm_environment_overrides,
    llm_config_from_route,
    load_review_pipeline,
    read_jsonl,
    resolve_route_name,
)

LOGGER = logging.getLogger("requirement_atomizer")

AI_EXTRACT_PROMPT_VERSION = "ai-extract-v1"
AI_EXTRACT_CACHE = "ai_extract_cache.jsonl"
AI_REQUIREMENTS = "ai_requirements.jsonl"
DEFAULT_MERGE_CHARS = 2800

ChatFn = Callable[[str, str], dict[str, Any]]

VALID_TYPES = {"functional", "non_functional", "constraint", "business_rule"}
VALID_PRIORITIES = {"P0", "P1", "P2"}

SYSTEM_PROMPT = (
    "你是表计行业（电表/水表/气表）需求分析师。读给定的标准/规范文本，抽取其中的需求条目。"
    "把同一功能的零散语句**合并成一条功能需求**，不要逐句拆；表格类规范化为一条带说明的需求。"
    "每条需求输出：title（不超过 80 字）、description（自包含中文叙述：背景+具体要求+适用条件+参数）、"
    "type（functional/non_functional/constraint/business_rule）、priority（P0/P1/P2，按重要性区分）、"
    "labels（表计领域标签，至少一个）、source_quote（原文逐字引用，不可改写）、"
    "source_section（该需求所属的章节号/标题，从文本里的小节标题判断）、"
    "acceptance_criteria（可测试的验收点数组）。"
    "严禁编造原文没有的 OBIS 码、事件号、十六进制、数字——这些只能原样引用或不出现。"
    "只输出 JSON：{\"requirements\": [ {…}, … ]}。"
)


# --- 章节聚合与合并 -------------------------------------------------------

def assemble_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把已解析 blocks 按 section_path 聚合成章节单元（章节文本 + 溯源 block）。"""
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for block in blocks:
        section_path = [str(s) for s in (block.get("section_path") or [])]
        key = " / ".join(section_path) or "(root)"
        unit = groups.get(key)
        if unit is None:
            unit = {"section_id": key, "section_path": section_path,
                    "heading": section_path[-1] if section_path else "",
                    "texts": [], "block_ids": []}
            groups[key] = unit
        text = str(block.get("text") or "").strip()
        if text:
            unit["texts"].append(text)
        if block.get("block_id"):
            unit["block_ids"].append(block["block_id"])

    sections: list[dict[str, Any]] = []
    for unit in groups.values():
        body = "\n".join(unit["texts"]).strip()
        if not body:
            continue
        sections.append({"section_id": unit["section_id"], "section_path": unit["section_path"],
                         "heading": unit["heading"], "text": body, "block_ids": unit["block_ids"]})
    return sections


def merge_sections(sections: list[dict[str, Any]], *, target_chars: int = DEFAULT_MERGE_CHARS) -> list[dict[str, Any]]:
    """把相邻小章节合并到目标字数，减少 LLM 调用。文本里保留各小节标题供 LLM 归属。"""
    merged: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for sec in sections:
        piece = f"## {sec['heading']}\n{sec['text']}" if sec.get("heading") else sec["text"]
        if cur is None:
            cur = {"section_id": sec["section_id"], "heading": sec.get("heading", ""),
                   "texts": [piece], "block_ids": list(sec.get("block_ids") or []), "len": len(piece)}
            continue
        if cur["len"] + len(piece) > target_chars and cur["texts"]:
            merged.append(_finalize_merged(cur))
            cur = {"section_id": sec["section_id"], "heading": sec.get("heading", ""),
                   "texts": [piece], "block_ids": list(sec.get("block_ids") or []), "len": len(piece)}
        else:
            cur["texts"].append(piece)
            cur["block_ids"].extend(sec.get("block_ids") or [])
            cur["len"] += len(piece)
    if cur is not None and cur["texts"]:
        merged.append(_finalize_merged(cur))
    return merged


def _finalize_merged(cur: dict[str, Any]) -> dict[str, Any]:
    return {"section_id": cur["section_id"], "heading": cur["heading"],
            "section_path": [cur["heading"]] if cur["heading"] else [],
            "text": "\n\n".join(cur["texts"]).strip(), "block_ids": cur["block_ids"]}


# --- 抽取与防幻觉护栏 -----------------------------------------------------

def section_fingerprint(section: dict[str, Any], model: str) -> str:
    digest = hashlib.sha256(
        f"{section.get('text', '')}\n{model}\n{AI_EXTRACT_PROMPT_VERSION}".encode("utf-8")
    ).hexdigest()
    return digest[:24]


def build_section_prompt(section: dict[str, Any]) -> str:
    payload = {"heading": section.get("heading"), "text": section.get("text", "")[:12000]}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _produced_text(requirement: dict[str, Any]) -> str:
    return " ".join([
        str(requirement.get("title") or ""),
        str(requirement.get("description") or ""),
        str(requirement.get("source_quote") or ""),
        " ".join(str(a) for a in requirement.get("acceptance_criteria") or []),
    ])


def code_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """受保护编码漂移：需求里出现、源文没有的 OBIS/事件号/十六进制（严格）。"""
    return sorted(extract_codes(_produced_text(requirement)) - extract_codes(source_text))


def int_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """普通整数漂移：需求里出现、源文没有的数字（软标）。"""
    return sorted(extract_ints(_produced_text(requirement)) - extract_ints(source_text))


def extract_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """编码 + 整数漂移合并（保留以兼容外部调用）。"""
    return sorted(set(code_drift(requirement, source_text)) | set(int_drift(requirement, source_text)))


def normalize_requirement(raw: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    rtype = str(raw.get("type") or "functional")
    if rtype not in VALID_TYPES:
        rtype = "functional"
    priority = str(raw.get("priority") or "P2")
    if priority not in VALID_PRIORITIES:
        priority = "P2"
    labels = [str(x) for x in (raw.get("labels") or []) if str(x).strip()]
    acceptance = [str(x) for x in (raw.get("acceptance_criteria") or []) if str(x).strip()]
    return {
        "title": str(raw.get("title") or "").strip()[:80],
        "description": str(raw.get("description") or "").strip(),
        "type": rtype,
        "priority": priority,
        "status": "draft",
        "source_section": str(raw.get("source_section") or section.get("heading") or section.get("section_id") or "").strip(),
        "source_quote": str(raw.get("source_quote") or "").strip(),
        "threshold_table": raw.get("threshold_table") if isinstance(raw.get("threshold_table"), dict) else None,
        "acceptance_criteria": acceptance,
        "dependencies": [],
        "parent": None,
        "children": [],
        "labels": labels,
        "notes": "",
        "extracted_by": "ai_extract",
        "source_block_ids": list(section.get("block_ids") or []),
    }


def extract_section(section: dict[str, Any], chat: ChatFn) -> list[dict[str, Any]]:
    """对一个章节调 chat 抽取需求，归一 + 分级漂移护栏。"""
    payload = chat(SYSTEM_PROMPT, build_section_prompt(section))
    raw_reqs = payload.get("requirements") if isinstance(payload, dict) else None
    if not isinstance(raw_reqs, list):
        return []
    source = section.get("text", "")
    results: list[dict[str, Any]] = []
    for raw in raw_reqs:
        if not isinstance(raw, dict):
            continue
        req = normalize_requirement(raw, section)
        if not req["description"] and not req["source_quote"]:
            continue
        codes = code_drift(req, source)
        ints = int_drift(req, source)
        notes = []
        if codes:  # 受保护编码漂移 → 严格：降级 draft 待核
            req["status"] = "draft"
            notes.append(f"结构漂移已拦截（编码，原文未见）：{', '.join(codes[:8])}")
        if ints:  # 普通整数漂移 → 软标：保留，待核
            notes.append(f"数字漂移（待核）：{', '.join(ints[:8])}")
        if not codes:
            # 无编码漂移：若模型给了状态信号则尊重，否则默认 draft（AI 抽取一律待审）
            req["status"] = "draft"
        req["notes"] = "；".join(notes)
        results.append(req)
    return results


# --- 缓存 + 批处理 --------------------------------------------------------

def read_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    cache: dict[str, list[dict[str, Any]]] = {}
    if not path.exists():
        return cache
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            key = str(row.get("fingerprint") or "")
            if key:
                cache[key] = row.get("requirements") or []
    return cache


def append_cache(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def extract_all(
    sections: list[dict[str, Any]],
    chat: ChatFn,
    *,
    model: str,
    cache_path: Path,
    concurrency: int = 1,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """逐章节抽取（缓存优先 + 并发 + 失败降级）。返回扁平需求列表，可复现。

    progress_callback：每完成一章节回调一次（GUI 进度条用，否则界面看着像卡死）。
    逐章节增量写缓存：长跑中途被中断也不丢已完成章节。
    stats：可选 out-dict，回填 total_sections / cached_sections / failed_sections。
    """
    cache = read_cache(cache_path)
    results: list[list[dict[str, Any]] | None] = [None] * len(sections)
    pending: list[tuple[int, dict[str, Any], str]] = []
    for i, section in enumerate(sections):
        fp = section_fingerprint(section, model)
        hit = cache.get(fp)
        if hit is not None:
            results[i] = hit
        else:
            pending.append((i, section, fp))

    total = len(sections)
    cached = total - len(pending)
    completed = cached
    failed = 0

    def emit() -> None:
        if progress_callback is not None and total:
            progress_callback({
                "stage": "ai_extract",
                "completed": completed,
                "total": total,
                "percent": int(round(completed * 100 / total)),
                "model": model,
            })

    emit()  # 初始进度（含缓存命中数），让界面立刻有反馈

    def work(item: tuple[int, dict[str, Any], str]) -> tuple[int, str, list[dict[str, Any]], bool]:
        idx, section, fp = item
        try:
            return idx, fp, extract_section(section, chat), True
        except LLMError as exc:  # 最佳努力：该章节降级、不崩、不缓存（留待重跑）
            LOGGER.warning("AI 抽取章节失败：%s", exc)
            return idx, fp, [], False

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            futures = [executor.submit(work, item) for item in pending]
            for future in as_completed(futures):
                idx, fp, reqs, ok = future.result()
                results[idx] = reqs
                if ok:
                    # 逐章节增量缓存：中途中断不丢已完成章节
                    append_cache(cache_path, [{"fingerprint": fp, "model": model,
                                               "prompt_version": AI_EXTRACT_PROMPT_VERSION,
                                               "requirements": reqs}])
                else:
                    failed += 1
                completed += 1
                emit()

    if stats is not None:
        stats["total_sections"] = total
        stats["cached_sections"] = cached
        stats["failed_sections"] = failed

    flat: list[dict[str, Any]] = []
    for reqs in results:
        flat.extend(reqs or [])
    return flat


# --- skill 格式 doc / Excel ----------------------------------------------

def ensure_domain_labels(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确定性后处理：保证每条需求至少带一个 21 领域标签（否则按域 Excel 全塌进"未分类"）。

    LLM 的自由标签（AFD/测试/Firmware upgrade…）保留为补充；领域标签由 requirement_schema.map_labels
    从文本确定性派生并置于前。对缓存结果也生效、不需重调 LLM。
    """
    import requirement_schema as rs
    from spec_excel import METERING_DOMAINS
    domain_set = set(METERING_DOMAINS)
    for req in requirements:
        existing = [str(x) for x in (req.get("labels") or [])]
        if any(label in domain_set for label in existing):
            continue
        text = f"{req.get('title', '')} {req.get('description', '')} {req.get('source_quote', '')}"
        domains = [d for d in rs.map_labels(text) if d in domain_set]
        req["labels"] = domains + [label for label in existing if label not in domains]
    return requirements


def build_skill_doc(requirements: list[dict[str, Any]], *, source: str, extracted_at: str,
                    meter_type: str = "multi") -> dict[str, Any]:
    """把 AI 抽取的需求装配成公司 skill 格式 doc（REQ-NNN 重编号 + analysis）。"""
    import requirement_schema as rs
    return rs.make_doc(requirements, source=source, extracted_at=extracted_at, meter_type=meter_type)


# --- 双引擎合并 -----------------------------------------------------------

def merge_requirements(deterministic: list[dict[str, Any]],
                       ai_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """双引擎合并：确定性的**结构**需求（有属性/访问表，OBIS 权威）+ AI 的**行为**需求。

    丢掉确定性里纯散文模板需求（无 threshold_table）——这部分由 AI 行为需求替代，避免模板与
    AI 叙述重复。确定性结构需求逐字保留（OBIS/数字一位不动）。
    """
    structural: list[dict[str, Any]] = []
    for req in deterministic:
        tt = req.get("threshold_table")
        if isinstance(tt, dict) and tt.get("rows"):
            req.setdefault("extracted_by", "deterministic")
            structural.append(req)
    return structural + list(ai_requirements)


def load_or_build_deterministic(out_dir: Path, *, source: str, extracted_at: str) -> list[dict[str, Any]]:
    """取确定性装配需求：优先读已有 dlms_cosem_spec_requirements.json，否则现装配。"""
    doc_path = out_dir / "dlms_cosem_spec_requirements.json"
    if doc_path.exists():
        return json.loads(doc_path.read_text(encoding="utf-8")).get("requirements", [])
    from assemble_spec import assemble
    reviews = out_dir / "llm_review_results.jsonl"
    doc, _ = assemble(out_dir, reviews if reviews.exists() else None,
                      source=source, extracted_at=extracted_at)
    return doc.get("requirements", [])


def build_merged_doc(out_dir: Path, ai_requirements: list[dict[str, Any]],
                     *, source: str, extracted_at: str) -> dict[str, Any]:
    """合并 AI 行为需求 + 确定性结构需求 → skill 格式 doc。"""
    deterministic = load_or_build_deterministic(out_dir, source=source, extracted_at=extracted_at)
    merged = merge_requirements(deterministic, ai_requirements)
    return build_skill_doc(merged, source=source, extracted_at=extracted_at)


# --- 主入口 ---------------------------------------------------------------

def config_for_route(route: str | None, pipeline_path: Path = DEFAULT_PIPELINE_PATH) -> LLMClientConfig | None:
    pipeline = load_review_pipeline(pipeline_path)
    route_name = resolve_route_name(pipeline, route)
    if route_name != "openai_compatible":
        return None
    # 复用 review 同一套 env 覆盖：GUI 在设置面板配的端点经 RATOMIZER_LLM_* 覆盖 yaml
    payload = apply_llm_environment_overrides(dict(pipeline.model_routes.get("openai_compatible") or {}))
    return llm_config_from_route(payload)


def run_ai_extract(out_dir: Path, *, route: str | None, merge_chars: int = DEFAULT_MERGE_CHARS,
                   write_doc: bool = False, merge_deterministic: bool = False,
                   pipeline_path: Path = DEFAULT_PIPELINE_PATH,
                   progress_callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """读 blocks → 章节合并 → AI 抽取 → 写 ai_requirements.jsonl（可选 skill doc + Excel + 双引擎合并）。"""
    out_dir = out_dir.expanduser().resolve()
    blocks = read_jsonl(out_dir / "blocks.jsonl")
    sections = merge_sections(assemble_sections(blocks), target_chars=merge_chars)

    config = config_for_route(route, pipeline_path)
    written: list[str] = []
    code_flagged = 0
    int_flagged = 0
    failed_sections = 0
    model: str | None = None

    if config is None:
        # stub 路由：不调 LLM，AI 行为需求为空——但确定性引擎（双引擎之一）仍照常
        # 产出结构规格，所以不在此 early-return，继续走 write_doc / merge_deterministic。
        requirements: list[dict[str, Any]] = []
        route_label = "stub"
    else:
        def chat(system: str, user: str) -> dict[str, Any]:
            return chat_json(config, system, user)

        extract_stats: dict[str, Any] = {}
        requirements = extract_all(sections, chat, model=config.model,
                                   cache_path=out_dir / AI_EXTRACT_CACHE,
                                   concurrency=4,
                                   progress_callback=progress_callback,
                                   stats=extract_stats)
        ensure_domain_labels(requirements)  # 确定性补领域标签，保证按域 Excel 不塌进未分类
        code_flagged = sum(1 for r in requirements if "结构漂移已拦截" in (r.get("notes") or ""))
        int_flagged = sum(1 for r in requirements if "数字漂移" in (r.get("notes") or ""))
        failed_sections = int(extract_stats.get("failed_sections", 0))
        model = config.model
        route_label = "openai_compatible"

        target = out_dir / AI_REQUIREMENTS
        with target.open("w", encoding="utf-8", newline="\n") as f:
            for req in requirements:
                f.write(json.dumps(req, ensure_ascii=False) + "\n")
        written.append(target.name)

    result: dict[str, Any] = {"route": route_label, "sections": len(sections),
              "requirements": len(requirements), "code_drift_flagged": code_flagged,
              "int_drift_flagged": int_flagged, "failed_sections": failed_sections,
              "written": written}
    if model:
        result["model"] = model
    if config is None:
        result["note"] = "stub 路由：未调 LLM（AI 行为需求为空，仅产确定性结构规格）"
    elif failed_sections:
        result["note"] = (f"{failed_sections} 个章节 LLM 调用失败（端点/Key/超时）——"
                          "已按可用结果产出，请用「测试连接」确认配置后重跑")

    if write_doc:
        doc = build_skill_doc(requirements, source=out_dir.name,
                              extracted_at=datetime.datetime.now().isoformat(timespec="seconds"))
        doc_path = out_dir / "ai_requirements_doc.json"
        doc_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(doc_path.name)
        try:
            from spec_excel import write_xlsx
            xlsx_path = out_dir / "ai_requirements.xlsx"
            write_xlsx(doc, xlsx_path)
            written.append(xlsx_path.name)
        except Exception as exc:  # Excel 失败不阻断 JSON 产出
            LOGGER.warning("AI 需求 Excel 生成失败：%s", exc)
        result["analysis"] = doc.get("analysis", {}).get("by_priority", {})

    if merge_deterministic:
        merged = build_merged_doc(out_dir, requirements, source=out_dir.name,
                                  extracted_at=datetime.datetime.now().isoformat(timespec="seconds"))
        merged_json = out_dir / "merged_spec_requirements.json"
        merged_json.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(merged_json.name)
        try:
            from spec_excel import write_xlsx
            merged_xlsx = out_dir / "merged_spec.xlsx"
            write_xlsx(merged, merged_xlsx)
            written.append(merged_xlsx.name)
        except Exception as exc:
            LOGGER.warning("合并 Excel 生成失败：%s", exc)
        result["merged"] = {"total": merged["analysis"]["total_count"],
                            "ai_behavioral": len(requirements),
                            "deterministic_structural": merged["analysis"]["total_count"] - len(requirements)}

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI-first requirement extraction.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory (含 blocks.jsonl)")
    parser.add_argument("--route", default=None, help="stub | openai_compatible")
    parser.add_argument("--merge-chars", type=int, default=DEFAULT_MERGE_CHARS, help="章节合并目标字数")
    parser.add_argument("--doc", action="store_true", help="同时产 skill 格式 doc + Excel（仅 AI 需求）")
    parser.add_argument("--merge", action="store_true", help="双引擎合并：AI 行为 + 确定性结构 → merged_spec")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_ai_extract(args.out, route=args.route, merge_chars=args.merge_chars,
                            write_doc=args.doc, merge_deterministic=args.merge)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
