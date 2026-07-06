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
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

import blue_book_lookup
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
ENRICH_PROMPT_VERSION = "enrich-v2"
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


def blue_book_entry_hash(entry: dict[str, Any] | None) -> str:
    if not entry:
        return ""
    return hashlib.sha256(str(entry.get("text") or "").encode("utf-8")).hexdigest()[:24]


def fingerprint(req: dict[str, Any], model: str, blue_book_entry: dict[str, Any] | None = None) -> str:
    digest = hashlib.sha256(
        f"{frozen_text(req)}\n{model}\n{ENRICH_PROMPT_VERSION}\n{blue_book_entry_hash(blue_book_entry)}".encode("utf-8")
    ).hexdigest()
    return digest[:24]


def class_id_for_requirement(req: dict[str, Any]) -> str:
    direct = str(req.get("class_id") or req.get("interface_class") or "").strip()
    if direct:
        return direct
    params = req.get("parameters")
    if isinstance(params, dict):
        for key in ("class_id", "CL", "cl"):
            value = str(params.get(key) or "").strip()
            if value:
                return value
    for key in ("title", "description", "source_quote"):
        match = re.search(r"\b(?:CL|class_id|interface class)\s*[:=]?\s*(\d{1,3})\b", str(req.get(key) or ""), re.I)
        if match:
            return match.group(1)
    return ""


def blue_book_entry_for(req: dict[str, Any], index: dict[str, Any] | None) -> dict[str, Any] | None:
    if index is None:
        return None
    class_id = class_id_for_requirement(req)
    if class_id:
        entry = blue_book_lookup.lookup_class(index, class_id)
        if entry:
            return entry
    # 真实 P3 行为 atom 没有 class_id 字段，但有接口类名（object，如 "Extended Register"）——
    # 按名称精确匹配回退（casefold）。真实 ABNT 验收实测：class_id 路径 0/180、名称路径 27/180；
    # 抽取噪声名（"When"/"Any"）匹配不到任何类名 → 正确地不注入。
    name = str(req.get("interface_class_name") or req.get("object") or "").strip()
    if name:
        return blue_book_lookup.lookup_class_by_name(index, name)
    return None


def blue_book_prompt(entry: dict[str, Any] | None) -> str:
    if not entry:
        return ""
    section = str(entry.get("section") or "").strip()
    name = str(entry.get("name") or "").strip()
    return (
        f"【权威参考：DLMS Blue Book Ed.16 §{section}（{name}）】\n"
        f"{blue_book_lookup.condensed_text(entry)}\n"
        "---\n"
        "要求：结合上面条款，把本需求的行为语义写完整（属性含义、GET/SET/ACTION 行为、"
        "数据类型/selective access 若条款有）。末尾附「依据 DLMS Blue Book Ed.16 §"
        f"{section}」。条款没有的内容绝不编造；OBIS/数字只能照抄本需求原文或条款原文。"
    )


def build_user_prompt(req: dict[str, Any], blue_book_entry: dict[str, Any] | None = None) -> str:
    payload = {
        "title": req.get("title"),
        "current_description": req.get("description"),
        "source_quote": req.get("source_quote"),
        "labels": req.get("labels"),
        "threshold_table_summary": table_text(req)[:1200],
    }
    base = json.dumps(payload, ensure_ascii=False, indent=2)
    reference = blue_book_prompt(blue_book_entry)
    return f"{reference}\n\n{base}" if reference else base


def check_drift(req: dict[str, Any], new_description: str, blue_book_entry: dict[str, Any] | None = None) -> list[str]:
    """返回漂移项（编码 + 数字）；空 = 通过。baseline = 冻结输入里出现过的码/数。"""
    base = frozen_text(req)
    if blue_book_entry:
        base += " " + str(blue_book_entry.get("text") or "")
        section = str(blue_book_entry.get("section") or "").strip()
        if section:
            base += f" DLMS Blue Book Ed.16 §{section}"
    base_codes, base_ints = extract_codes(base), extract_ints(base)
    drift = sorted((extract_codes(new_description) - base_codes) | (extract_ints(new_description) - base_ints))
    return drift


def citation_mismatch(new_description: str, blue_book_entry: dict[str, Any] | None) -> str:
    if not blue_book_entry:
        return ""
    section = str(blue_book_entry.get("section") or "").strip()
    if not section:
        return ""
    section_mark = re.escape(chr(0xA7))
    cited = re.findall(
        rf"Blue Book(?:[^{section_mark}]{{0,40}}){section_mark}\s*([0-9]+(?:\.[0-9]+)*)",
        new_description,
        flags=re.I,
    )
    wrong = [item for item in cited if item != section]
    if wrong:
        return ", ".join(wrong)
    if "Blue Book" in new_description and not cited:
        return "missing"
    return ""


def append_note(req: dict[str, Any], note: str) -> None:
    existing = str(req.get("notes") or "")
    req["notes"] = f"{existing}；{note}" if existing else note


def apply_result(req: dict[str, Any], description: str, *, enriched: bool, note: str) -> None:
    if enriched:
        req["description"] = description
    append_note(req, note)


def enrich_one(
    req: dict[str, Any],
    config: LLMClientConfig,
    blue_book_entry: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """调 LLM 改写并过漂移护栏。返回 (description, note)。可能抛 LLMError（由批处理捕获降级）。"""
    payload = chat_json(config, SYSTEM_PROMPT, build_user_prompt(req, blue_book_entry))
    new_desc = str(payload.get("description") or "").strip()
    if not new_desc:
        return req.get("description") or "", "描述富化跳过：模型返回空"
    mismatch = citation_mismatch(new_desc, blue_book_entry)
    if mismatch:
        return req.get("description") or "", f"描述富化被拒：Blue Book 出处节号不一致 {mismatch}"
    drift = check_drift(req, new_desc, blue_book_entry)
    if drift:
        return req.get("description") or "", f"描述富化被拒：编码/数字漂移 {', '.join(drift[:8])}"
    new_desc = _ensure_citation(new_desc, blue_book_entry)
    if blue_book_entry:
        # 注意：批处理按子串「富化（结构字段未变）」判成败计数——附加信息只能放在其后
        section = str(blue_book_entry.get("section") or "").strip()
        return new_desc, f"描述经 LLM 富化（结构字段未变）；参考 Blue Book §{section}"
    return new_desc, "描述经 LLM 富化（结构字段未变）"


def _ensure_citation(new_desc: str, blue_book_entry: dict[str, Any] | None) -> str:
    """出处必带（红线）：注入了条款而模型漏写出处时，程序化补写——我们确知注入的节号，
    比信任模型可靠。错误节号已在 citation_mismatch 拦截，此处只补缺。"""
    if not blue_book_entry:
        return new_desc
    section = str(blue_book_entry.get("section") or "").strip()
    if not section or f"§{section}" in new_desc:
        return new_desc
    return f"{new_desc.rstrip()}（依据 DLMS Blue Book Ed.16 §{section}）"


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
    blue_book_index_path: Path | None = None,
) -> tuple[int, int, int]:
    """原地富化 description；返回 (enriched, rejected, failed)。最佳努力：服务不可达不抛出、保留模板。"""
    cache = read_cache(cache_path)
    blue_book_index = blue_book_lookup.load_index(blue_book_index_path) if blue_book_index_path is not None else None
    enriched = rejected = failed = 0
    new_rows: list[dict[str, Any]] = []
    pending: list[tuple[dict[str, Any], str, dict[str, Any] | None]] = []  # (req, 指纹, Blue Book entry)

    # 1) 缓存命中直接应用
    for req in requirements:
        blue_book_entry = blue_book_entry_for(req, blue_book_index)
        fp = fingerprint(req, config.model, blue_book_entry)
        hit = cache.get(fp)
        if hit is not None:
            apply_result(req, hit["description"], enriched=bool(hit.get("enriched")), note=str(hit.get("note") or ""))
            enriched += 1 if hit.get("enriched") else 0
            rejected += 0 if hit.get("enriched") else 1
        else:
            pending.append((req, fp, blue_book_entry))

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
    for req, fp, blue_book_entry in sample:
        try:
            desc, note = enrich_one(req, config, blue_book_entry)
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
            futures = {executor.submit(enrich_one, req, config, blue_book_entry): (req, fp) for req, fp, blue_book_entry in remaining}
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
    from llm_client import apply_min_tokens
    config = apply_min_tokens(config, "enrich")
    return config, int(payload.get("concurrency", 1) or 1), int(payload.get("connection_failure_abort", 10) or 10)


def enrich_requirement_lists(
    requirement_lists: list[list[dict[str, Any]]],
    *,
    out_dir: Path,
    route: str | None,
    pipeline_path: Path = DEFAULT_PIPELINE_PATH,
    blue_book_index_path: Path | None = None,
) -> dict[str, int]:
    config, concurrency, abort = config_for_route(route, pipeline_path)
    if config is None:
        return {"enriched": 0, "rejected": 0, "failed": 0, "route": "stub"}
    cache_path = out_dir.expanduser().resolve() / ENRICH_CACHE
    flat = [req for lst in requirement_lists for req in lst]
    LOGGER.info("描述富化：%s 条候选（模型 %s）", len(flat), config.model)
    enriched, rejected, failed = enrich_descriptions(
        flat,
        config=config,
        cache_path=cache_path,
        concurrency=concurrency,
        connection_failure_abort=abort,
        blue_book_index_path=blue_book_index_path,
    )
    return {"enriched": enriched, "rejected": rejected, "failed": failed, "route": "openai_compatible"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM-enrich requirement descriptions (structured fields frozen).")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory")
    parser.add_argument("--route", default=None, help="stub | openai_compatible")
    parser.add_argument("--reviews", type=Path, default=None, help="Behaviour LLM reviews jsonl (for fresh assemble)")
    parser.add_argument("--blue-book-index", type=Path, default=None, help="Optional Blue Book index JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out.expanduser().resolve()
    from assemble_spec import assemble
    doc, breakdown = assemble(out_dir, args.reviews, source=out_dir.name,
                              extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
                              enrich_route=args.route,
                              blue_book_index_path=args.blue_book_index)
    target = out_dir / "dlms_cosem_spec_requirements.json"
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_dir), "written": [target.name], "breakdown": breakdown},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
