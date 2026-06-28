"""AI 主导需求抽取（杠杆②，Phase 1 骨架）。

LLM 逐章节读已解析文本 → 直接产出功能级结构化需求（标题/自包含描述/类型/优先级/标签/
原文引用/验收）。面向"通用文档解读"：DLMS 结构化与通用标准文档统一一套流程。

防幻觉（数字双引擎）：LLM 只负责"读懂与叙述"。它输出里出现的 OBIS 码 / 数字 / 十六进制 /
事件号，必须能在所在**章节原文**里找到——找不到即判定编造（漂移），该条降级为 draft 并记
note，不当作已确认。结构字段最终仍以确定性抽取为准（Phase 2 合并）。

可复现（稳定）：温度 0 + **章节内容指纹缓存**（同章节文本 + 同模型 → 同结果，重跑零花费）。

route 体系（复用 review_pipeline.yaml）：默认 **stub**（零 LLM，不产 AI 需求）；
仅 route=openai_compatible 才真调（本地 Ollama / deepseek-v4-flash 等）。

用法：python -m ai_extract --out <atomizer 输出目录> [--route openai_compatible]

Phase 1 = 章节聚合 + 抽取/归一 + 漂移护栏 + 指纹缓存 + stub + CLI + 单测（不依赖 endpoint）。
Phase 2 = prompt 调优 + 与确定性结构字段双引擎合并 + 在真实文档上跑通（需 Ollama）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from cosem_behavior_spec import extract_codes, extract_ints
from llm_client import LLMClientConfig, chat_json
from llm_pipeline import (
    DEFAULT_PIPELINE_PATH,
    llm_config_from_route,
    load_review_pipeline,
    read_jsonl,
    resolve_route_name,
)

LOGGER = logging.getLogger("requirement_atomizer")

AI_EXTRACT_PROMPT_VERSION = "ai-extract-v1"
AI_EXTRACT_CACHE = "ai_extract_cache.jsonl"
AI_REQUIREMENTS = "ai_requirements.jsonl"

# chat 抽象：输入 (system_prompt, user_prompt)，输出已解析 JSON dict。
# 真实 = 包 llm_client.chat_json；stub/单测 = 注入假实现。
ChatFn = Callable[[str, str], dict[str, Any]]

VALID_TYPES = {"functional", "non_functional", "constraint", "business_rule"}
VALID_PRIORITIES = {"P0", "P1", "P2"}

SYSTEM_PROMPT = (
    "你是表计行业（电表/水表/气表）需求分析师。读给定的标准/规范章节，抽取其中的"
    "需求条目。把同一功能的零散语句**合并成一条功能需求**，不要逐句拆。每条需求输出："
    "title（不超过 80 字）、description（自包含中文叙述：背景+具体要求+适用条件+参数）、"
    "type（functional/non_functional/constraint/business_rule）、priority（P0/P1/P2）、"
    "labels（表计领域标签，至少一个）、source_quote（原文逐字引用，不可改写）、"
    "acceptance_criteria（可测试的验收点数组）。"
    "严禁编造原文没有的 OBIS 码、数字、十六进制、事件号——这些只能原样引用或不出现。"
    "只输出 JSON：{\"requirements\": [ {…}, … ]}。"
)


def assemble_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把已解析 blocks 按 section_path 聚合成章节单元（章节文本 + 溯源 block 列表）。"""
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


def section_fingerprint(section: dict[str, Any], model: str) -> str:
    digest = hashlib.sha256(
        f"{section.get('text', '')}\n{model}\n{AI_EXTRACT_PROMPT_VERSION}".encode("utf-8")
    ).hexdigest()
    return digest[:24]


def build_section_prompt(section: dict[str, Any]) -> str:
    payload = {
        "section": section.get("section_id"),
        "heading": section.get("heading"),
        "text": section.get("text", "")[:8000],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def extract_drift(requirement: dict[str, Any], source_text: str) -> list[str]:
    """返回漂移项：需求里出现、但章节原文没有的 编码/数字。空 = 通过。"""
    produced = " ".join([
        str(requirement.get("title") or ""),
        str(requirement.get("description") or ""),
        str(requirement.get("source_quote") or ""),
        " ".join(str(a) for a in requirement.get("acceptance_criteria") or []),
    ])
    base_codes, base_ints = extract_codes(source_text), extract_ints(source_text)
    drift = (extract_codes(produced) - base_codes) | (extract_ints(produced) - base_ints)
    return sorted(drift)


def normalize_requirement(raw: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    """把 LLM 产出的单条需求归一为统一字段（id 由后续 make_doc 重编号）。"""
    rtype = str(raw.get("type") or "functional")
    if rtype not in VALID_TYPES:
        rtype = "functional"
    priority = str(raw.get("priority") or "P2")
    if priority not in VALID_PRIORITIES:
        priority = "P2"
    labels = [str(x) for x in (raw.get("labels") or []) if str(x).strip()]
    acceptance = [str(x) for x in (raw.get("acceptance_criteria") or []) if str(x).strip()]
    source_quote = str(raw.get("source_quote") or "").strip()
    return {
        "title": str(raw.get("title") or "").strip()[:80],
        "description": str(raw.get("description") or "").strip(),
        "type": rtype,
        "priority": priority,
        "status": "draft",
        "source_section": section.get("heading") or section.get("section_id") or "",
        "source_quote": source_quote,
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
    """对一个章节调 chat 抽取需求，归一 + 过漂移护栏。"""
    payload = chat(SYSTEM_PROMPT, build_section_prompt(section))
    raw_reqs = payload.get("requirements") if isinstance(payload, dict) else None
    if not isinstance(raw_reqs, list):
        return []
    results: list[dict[str, Any]] = []
    for raw in raw_reqs:
        if not isinstance(raw, dict):
            continue
        req = normalize_requirement(raw, section)
        if not req["description"] and not req["source_quote"]:
            continue
        drift = extract_drift(req, section.get("text", ""))
        if drift:
            req["status"] = "draft"
            req["notes"] = f"结构漂移已拦截（原文未见）：{', '.join(drift[:8])}；需人工/确定性核对"
        results.append(req)
    return results


# --- 缓存 ----------------------------------------------------------------

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
) -> list[dict[str, Any]]:
    """逐章节抽取（缓存优先）。返回扁平需求列表。可复现：同章节文本 → 命中缓存。"""
    cache = read_cache(cache_path)
    out: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    for section in sections:
        fp = section_fingerprint(section, model)
        hit = cache.get(fp)
        if hit is not None:
            out.extend(hit)
            continue
        reqs = extract_section(section, chat)
        out.extend(reqs)
        new_rows.append({"fingerprint": fp, "model": model,
                         "prompt_version": AI_EXTRACT_PROMPT_VERSION,
                         "section_id": section.get("section_id"), "requirements": reqs})
    append_cache(cache_path, new_rows)
    return out


def config_for_route(route: str | None, pipeline_path: Path = DEFAULT_PIPELINE_PATH) -> LLMClientConfig | None:
    """stub/未配 → None（不调 LLM）；openai_compatible → LLMClientConfig。"""
    pipeline = load_review_pipeline(pipeline_path)
    route_name = resolve_route_name(pipeline, route)
    if route_name != "openai_compatible":
        return None
    return llm_config_from_route(dict(pipeline.model_routes.get("openai_compatible") or {}))


def run_ai_extract(out_dir: Path, *, route: str | None,
                   pipeline_path: Path = DEFAULT_PIPELINE_PATH) -> dict[str, Any]:
    """主入口：读 blocks → 章节 → AI 抽取 → 写 ai_requirements.jsonl。stub 时零产出。"""
    out_dir = out_dir.expanduser().resolve()
    blocks = read_jsonl(out_dir / "blocks.jsonl")
    sections = assemble_sections(blocks)

    config = config_for_route(route, pipeline_path)
    if config is None:
        return {"route": "stub", "sections": len(sections), "requirements": 0,
                "note": "stub 路由：未调 LLM，未产 AI 需求（配置 --route openai_compatible 启用）"}

    def chat(system: str, user: str) -> dict[str, Any]:
        return chat_json(config, system, user)

    cache_path = out_dir / AI_EXTRACT_CACHE
    requirements = extract_all(sections, chat, model=config.model, cache_path=cache_path)
    flagged = sum(1 for r in requirements if "结构漂移已拦截" in (r.get("notes") or ""))

    target = out_dir / AI_REQUIREMENTS
    with target.open("w", encoding="utf-8", newline="\n") as f:
        for req in requirements:
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    return {"route": "openai_compatible", "model": config.model, "sections": len(sections),
            "requirements": len(requirements), "drift_flagged": flagged, "written": [target.name]}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI-first requirement extraction (Phase 1 skeleton).")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory (含 blocks.jsonl)")
    parser.add_argument("--route", default=None, help="stub | openai_compatible")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_ai_extract(args.out, route=args.route)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
