"""描述 LLM 富化：把 P3 行为需求的 description 模板改写成更丰富的中文叙述（仅行为层，P1 数据层不动）。

铁律（防幻觉）：LLM 只改写散文；绝不新增/改动 OBIS 码、类 ID、访问位、数字、十六进制、
事件号。改写结果过编码/数字漂移护栏（复用 cosem_behavior_spec.extract_codes/extract_ints），
漂移即拒绝、回退确定性模板。结构字段（source_quote/threshold_table/labels/priority/…）全程冻结。

默认 stub（不富化、零 LLM）；仅 route=openai_compatible 才真调（复用 review_pipeline.yaml 的
model_routes.openai_compatible + M2 的 llm_client）。内容指纹缓存，重跑命中零花费。

用法：python -m spec_enrich --out <atomizer 输出目录> [--route openai_compatible]
TODO: 缓存/并发/快速失败/熔断的批处理逻辑与 llm_pipeline 重复，将来可抽 llm_batch 共用。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

from cosem_behavior_spec import extract_codes, extract_ints
from llm_client import LLMClientConfig, LLMConnectionError, LLMError, chat_json
from llm_pipeline import (
    DEFAULT_PIPELINE_PATH,
    FAST_FAIL_SAMPLE_SIZE,
    PROGRESS_INTERVAL,
    llm_config_from_route,
    load_review_pipeline,
    resolve_route_name,
)

LOGGER = logging.getLogger("requirement_atomizer")
ENRICH_PROMPT_VERSION = "enrich-v1"
ENRICH_CACHE = "spec_enrich_cache.jsonl"
# 推理模型（如 GLM-5.2）会把 max_tokens 大量花在 reasoning_content 上，content 可能空；
# 富化给足下限，避免正文被推理预算挤空导致整批降级。
ENRICH_MIN_MAX_TOKENS = 2048

SYSTEM_PROMPT = (
    "你是 DLMS/COSEM 需求文档编辑。把给定需求的描述改写为更清晰、信息更丰富的中文叙述，"
    "面向研发团队、可据此实现计量软件。严禁新增或改动任何 OBIS 码、类 ID(CL)、访问权限位"
    "(RC/PC/SC/LC、R-/RW 等)、数字、十六进制、事件号——这些只能原样保留或不出现。"
    "不要编造原文没有的事实。只输出 JSON：{\"description\": \"…\"}"
)


def table_text(req: dict[str, Any]) -> str:
    tt = req.get("threshold_table")
    if not isinstance(tt, dict):
        return ""
    parts = [str(tt.get("description") or ""), " ".join(str(c) for c in tt.get("columns") or [])]
    for row in tt.get("rows") or []:
        parts.append(" ".join(str(c) for c in row))
    return " ".join(parts)


def frozen_text(req: dict[str, Any]) -> str:
    """漂移 baseline 与指纹的冻结输入：模板描述 + 原文 + 标题 + 表格。"""
    return " ".join([
        str(req.get("description") or ""),
        str(req.get("source_quote") or ""),
        str(req.get("title") or ""),
        table_text(req),
        " ".join(str(x) for x in req.get("labels") or []),
    ])


def fingerprint(req: dict[str, Any], model: str) -> str:
    digest = hashlib.sha256(f"{frozen_text(req)}\n{model}\n{ENRICH_PROMPT_VERSION}".encode("utf-8")).hexdigest()
    return digest[:24]


def build_user_prompt(req: dict[str, Any]) -> str:
    payload = {
        "title": req.get("title"),
        "current_description": req.get("description"),
        "source_quote": req.get("source_quote"),
        "labels": req.get("labels"),
        "threshold_table_summary": table_text(req)[:1200],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def check_drift(req: dict[str, Any], new_description: str) -> list[str]:
    """返回漂移项（编码 + 数字）；空 = 通过。baseline = 冻结输入里出现过的码/数。"""
    base = frozen_text(req)
    base_codes, base_ints = extract_codes(base), extract_ints(base)
    drift = sorted((extract_codes(new_description) - base_codes) | (extract_ints(new_description) - base_ints))
    return drift


def append_note(req: dict[str, Any], note: str) -> None:
    existing = str(req.get("notes") or "")
    req["notes"] = f"{existing}；{note}" if existing else note


def apply_result(req: dict[str, Any], description: str, *, enriched: bool, note: str) -> None:
    if enriched:
        req["description"] = description
    append_note(req, note)


def enrich_one(req: dict[str, Any], config: LLMClientConfig) -> tuple[str, str]:
    """调 LLM 改写并过漂移护栏。返回 (description, note)。可能抛 LLMError（由批处理捕获降级）。"""
    payload = chat_json(config, SYSTEM_PROMPT, build_user_prompt(req))
    new_desc = str(payload.get("description") or "").strip()
    if not new_desc:
        return req.get("description") or "", "描述富化跳过：模型返回空"
    drift = check_drift(req, new_desc)
    if drift:
        return req.get("description") or "", f"描述富化被拒：编码/数字漂移 {', '.join(drift[:8])}"
    return new_desc, "描述经 LLM 富化（结构字段未变）"


# --- 批处理（镜像 llm_pipeline 的缓存/并发/快速失败/熔断/降级）------------------

def read_cache(path: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return cache
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            key = str(row.get("fingerprint") or "")
            if key:
                cache[key] = row
    return cache


def append_cache(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def enrich_descriptions(
    requirements: list[dict[str, Any]],
    *,
    config: LLMClientConfig,
    cache_path: Path,
    concurrency: int = 1,
    connection_failure_abort: int = 10,
) -> tuple[int, int, int]:
    """原地富化 description；返回 (enriched, rejected, failed)。最佳努力：服务不可达不抛出、保留模板。"""
    cache = read_cache(cache_path)
    enriched = rejected = failed = 0
    new_rows: list[dict[str, Any]] = []
    pending: list[tuple[dict[str, Any], str]] = []  # (req, 指纹)——指纹基于模板，在改写前算定

    # 1) 缓存命中直接应用
    for req in requirements:
        fp = fingerprint(req, config.model)
        hit = cache.get(fp)
        if hit is not None:
            apply_result(req, hit["description"], enriched=bool(hit.get("enriched")), note=str(hit.get("note") or ""))
            enriched += 1 if hit.get("enriched") else 0
            rejected += 0 if hit.get("enriched") else 1
        else:
            pending.append((req, fp))

    if not pending:
        return enriched, rejected, failed

    def apply_and_record(req: dict[str, Any], fp: str, desc: str, note: str) -> None:
        nonlocal enriched, rejected
        is_enriched = "富化（结构字段未变）" in note
        apply_result(req, desc, enriched=is_enriched, note=note)
        if is_enriched:
            enriched += 1
        else:
            rejected += 1
        new_rows.append({"fingerprint": fp, "model": config.model,
                         "prompt_version": ENRICH_PROMPT_VERSION, "description": desc,
                         "enriched": is_enriched, "note": note})

    total = len(pending)
    done = 0

    # 2) 快速失败探测：前 N 条串行，全连不上即判定服务不可达、整体降级（不抛出 assemble）
    sample = pending[:FAST_FAIL_SAMPLE_SIZE]
    sample_conn_fail = 0
    for req, fp in sample:
        try:
            desc, note = enrich_one(req, config)
        except LLMConnectionError as exc:
            sample_conn_fail += 1
            failed += 1
            append_note(req, f"描述富化失败（服务不可达）：{exc}")
        except LLMError as exc:
            failed += 1
            append_note(req, f"描述富化失败：{exc}")
        else:
            apply_and_record(req, fp, desc, note)
            done += 1
            if done % PROGRESS_INTERVAL == 0:
                LOGGER.info("spec enrich %s/%s", done, total)
    if sample and sample_conn_fail == len(sample):
        LOGGER.warning("描述富化：前 %s 条均连接失败，判定服务不可达，其余保留模板", len(sample))
        append_cache(cache_path, new_rows)
        return enriched, rejected, failed + (total - len(sample))

    # 3) 其余并发 + 熔断
    remaining = pending[FAST_FAIL_SAMPLE_SIZE:]
    if remaining:
        consecutive_conn_fail = 0
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            futures = {executor.submit(enrich_one, req, config): (req, fp) for req, fp in remaining}
            for future in as_completed(futures):
                req, fp = futures[future]
                try:
                    desc, note = future.result()
                except LLMConnectionError as exc:
                    failed += 1
                    consecutive_conn_fail += 1
                    append_note(req, f"描述富化失败（服务不可达）：{exc}")
                    if consecutive_conn_fail >= connection_failure_abort:
                        LOGGER.warning("描述富化：连续 %s 次连接失败，熔断", consecutive_conn_fail)
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    continue
                except LLMError as exc:
                    failed += 1
                    consecutive_conn_fail = 0
                    append_note(req, f"描述富化失败：{exc}")
                    continue
                consecutive_conn_fail = 0
                apply_and_record(req, fp, desc, note)
                done += 1
                if done % PROGRESS_INTERVAL == 0:
                    LOGGER.info("spec enrich %s/%s", done, total)

    append_cache(cache_path, new_rows)
    return enriched, rejected, failed


def config_for_route(route: str | None, pipeline_path: Path = DEFAULT_PIPELINE_PATH) -> tuple[LLMClientConfig | None, int, int]:
    """解析 route → (config, concurrency, connection_failure_abort)；stub/未配返回 (None, …)。"""
    pipeline = load_review_pipeline(pipeline_path)
    route_name = resolve_route_name(pipeline, route)
    if route_name != "openai_compatible":
        return None, 1, 10
    payload = dict(pipeline.model_routes.get("openai_compatible") or {})
    config = llm_config_from_route(payload)
    if config.max_tokens < ENRICH_MIN_MAX_TOKENS:  # 给推理模型留出正文预算
        config = replace(config, max_tokens=ENRICH_MIN_MAX_TOKENS)
    return config, int(payload.get("concurrency", 1) or 1), int(payload.get("connection_failure_abort", 10) or 10)


def enrich_requirement_lists(
    requirement_lists: list[list[dict[str, Any]]],
    *,
    out_dir: Path,
    route: str | None,
    pipeline_path: Path = DEFAULT_PIPELINE_PATH,
) -> dict[str, int]:
    config, concurrency, abort = config_for_route(route, pipeline_path)
    if config is None:
        return {"enriched": 0, "rejected": 0, "failed": 0, "route": "stub"}
    cache_path = out_dir.expanduser().resolve() / ENRICH_CACHE
    flat = [req for lst in requirement_lists for req in lst]
    LOGGER.info("描述富化：%s 条候选（模型 %s）", len(flat), config.model)
    enriched, rejected, failed = enrich_descriptions(
        flat, config=config, cache_path=cache_path, concurrency=concurrency, connection_failure_abort=abort)
    return {"enriched": enriched, "rejected": rejected, "failed": failed, "route": "openai_compatible"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM-enrich requirement descriptions (structured fields frozen).")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory")
    parser.add_argument("--route", default=None, help="stub | openai_compatible")
    parser.add_argument("--reviews", type=Path, default=None, help="Behaviour LLM reviews jsonl (for fresh assemble)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out.expanduser().resolve()
    from assemble_spec import assemble
    doc, breakdown = assemble(out_dir, args.reviews, source=out_dir.name,
                              extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
                              enrich_route=args.route)
    target = out_dir / "dlms_cosem_spec_requirements.json"
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_dir), "written": [target.name], "breakdown": breakdown},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
