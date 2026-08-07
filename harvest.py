"""WS-H：知识沉淀闭环——每份文档分析完成后自动收割可复用资产。

开关：``RATOMIZER_HARVEST``（默认 0；=1 时启用）。

六类资产路由：
1. 裁决样本 → adjudication_bank（复用 adjudication_bank.update_bank）。
2. confirmed 功能需求 → ``pending_requirements.jsonl``（草稿/未确认条目只进待审定区）。
3. 实现方案（design_options / 归属理由 / 验收写法）→ ``pending_solutions.jsonl``，带地域/客户标签。
4. 领域知识（新术语 / 新协议项）→ ``kb_candidates.jsonl`` 零成本收集（只记录候选，不进 vault）。
5. 语言资产（新弱词 / 变体表头）→ ``dictionary_candidates.jsonl``，带版本戳。
6. 校准资产（裁决统计 / 误判记录）→ ``calibration_review_list.jsonl``，人工评审入册。

产物：``harvest_report.json`` 含五指标：
- 本项目入库量（六类资产合计）
- 下项目库命中率（当前库匹配数 / 当前需求数）
- KB 命中数（当前文档命中已编译 KB 的条目数）
- few-shot 引用数（当前 adjudication_bank 被引用的范例数）
- 负例拦截数（当前 adjudication_bank 负例命中数）

设计原则：
- 默认关闭，行为面零变化。
- 只读/只追加写，不修改既有产物。
- 所有写路径走 governed_artifact_path(state)。
- 失败降级：任何收割失败记录到 report 但不阻断主流程。
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from result_package import governed_artifact_path

HARVEST_VERSION = "harvest-v1"
HARVEST_SCHEMA = "harvest-report/v1"
HARVEST_REPORT_FILE = "harvest_report.json"
PENDING_REQUIREMENTS_FILE = "pending_requirements.jsonl"
PENDING_SOLUTIONS_FILE = "pending_solutions.jsonl"
KB_CANDIDATES_FILE = "kb_candidates.jsonl"
DICTIONARY_CANDIDATES_FILE = "dictionary_candidates.jsonl"
CALIBRATION_REVIEW_FILE = "calibration_review_list.jsonl"

LOGGER = logging.getLogger("requirement_atomizer")

ENV_HARVEST = "RATOMIZER_HARVEST"

# 地域/客户标签启发式（从目录名或 env 读取）
ENV_HARVEST_PROJECT_TAG = "RATOMIZER_HARVEST_PROJECT_TAG"
ENV_REQUIREMENT_LIBRARY = "RATOMIZER_REQUIREMENT_LIBRARY"
ENV_BASE_LIBRARY = "RATOMIZER_BASE_LIBRARY"
ENV_SOLUTION_LIBRARY = "RATOMIZER_SOLUTION_LIBRARY"


def harvest_enabled() -> bool:
    """``RATOMIZER_HARVEST`` 是否启用（默认 0=关闭）。"""
    raw = os.environ.get(ENV_HARVEST, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _project_tag(out_dir: Path) -> str:
    """从环境变量或目录名推断项目标签（如 'africa-prepaid'）。"""
    tag = os.environ.get(ENV_HARVEST_PROJECT_TAG, "").strip()
    if tag:
        return tag
    name = Path(out_dir).name.lower()
    # 简单启发式：目录名含常见地域/客户信号
    signals = ["africa", "african", "prepaid", "zetdc", "zimbabwe", "kenya", "nigeria",
               "tanzania", "uganda", "south africa", "sadc", "namibia", "botswana"]
    for signal in signals:
        if signal in name:
            return signal.replace(" ", "-")
    return ""


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """原子替换写 JSONL（读旧内容 + 合并 + 写临时文件 + replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_jsonl(path)
    existing.extend(rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in existing:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _governed_state_path(out_dir: Path, filename: str, for_write: bool = True) -> Path:
    return governed_artifact_path(out_dir, filename, category="state", for_write=for_write)


def _load_functional_requirements(out_dir: Path) -> list[dict[str, Any]]:
    """读 functional_requirements.json（governed 优先，根目录兜底）。"""
    from requirements_analysis_rules import _read_functional_requirements_payload

    payload = _read_functional_requirements_payload(out_dir)
    items = payload.get("items")
    return [item for item in (items or []) if isinstance(item, dict)]


def _load_lifecycle_states(out_dir: Path) -> dict[str, str]:
    """读 verification_states.jsonl，按 requirement_id 取 lifecycle_state。"""
    from review_state import read_verification_states

    return {
        str(rid): str((row or {}).get("lifecycle_state") or "draft")
        for rid, row in read_verification_states(out_dir).items()
    }


def _load_adjudication_results(out_dir: Path) -> dict[str, dict[str, Any]]:
    """读 adjudication_results.jsonl，按 functional_requirement_id 取最新记录。"""
    from adjudicate import read_adjudication_results

    try:
        rows = read_adjudication_results(out_dir)
    except Exception:
        return {}
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = str(row.get("functional_requirement_id") or "").strip()
        if not rid:
            continue
        existing = latest.get(rid)
        if existing is None or str(row.get("timestamp") or "") >= str(existing.get("timestamp") or ""):
            latest[rid] = row
    return latest


def _is_confirmed(lifecycle_state: str) -> bool:
    from requirement_schema import LIFECYCLE_CONFIRMED, lifecycle_rank

    return lifecycle_rank(lifecycle_state or "draft") >= lifecycle_rank(LIFECYCLE_CONFIRMED)


def _extract_domain_terms(item: dict[str, Any]) -> list[str]:
    """从功能需求文本中提取潜在领域知识候选（协议名 / 专有缩写）。"""
    text = " ".join(
        str(item.get(key) or "")
        for key in ("objective", "description", "title", "behaviors", "preconditions",
                    "data_constraints", "source_quote")
    )
    # 协议/技术缩写：STS, PLC, RF, DCU, DLMS, COSEM, NB-IoT, LoRa, GPRS, 4G, LTE-M
    pattern = re.compile(
        r"\b(STS|PLC|RF|DCU|DLMS|COSEM|NB[\s\-]?IoT|LoRa|GPRS|3G|4G|5G|LTE[\s\-]?M?|"
        r"Zigbee|Bluetooth|Mesh|M-Bus|WM-Bus|OFDM|FSK|PSK|HLS|LLS|CSP|AES|RSA|SHA|TLS|"
        r"HTTP|MQTT|CoAP|TCP/IP|IPv6|APN|VPN|PSTN|GSM|UMTS|CDMA)\b",
        re.IGNORECASE,
    )
    terms = sorted({m.group(0).upper().replace(" ", "-") for m in pattern.finditer(text)})
    return terms


def _extract_weak_words(item: dict[str, Any]) -> list[str]:
    """从功能需求文本中提取潜在弱词/模糊词候选。"""
    text = " ".join(
        str(item.get(key) or "")
        for key in ("objective", "description", "title", "behaviors", "preconditions",
                    "data_constraints", "source_quote")
    )
    # 与内置弱词表互补：适度、尽快、灵活、必要时、视情况、合理的、充分的、尽可能
    candidates = ["适当", "尽快", "灵活", "必要时", "视情况", "合理的", "充分的",
                  "尽可能", "大约", "左右", "etc", "等等", "相关", "某些"]
    found = []
    for word in candidates:
        if word in text:
            found.append(word)
    return found


def _library_hit_count(items: list[dict[str, Any]], library_path: Path | None) -> int:
    """统计当前功能需求命中需求库的数量（词面 Jaccard，与既有检索同口径）。"""
    if library_path is None or not library_path.is_file():
        return 0
    try:
        from requirement_schema import search_requirement_library, tokenize_requirement
    except Exception:
        return 0
    try:
        library: list[dict[str, Any]] = []
        with library_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    library.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return 0
    hits = 0
    for item in items:
        query = " ".join([
            str(item.get("objective") or ""),
            " ".join(str(b) for b in (item.get("behaviors") or [])),
        ])
        tokens = tokenize_requirement(query)
        if not tokens:
            continue
        for entry in library:
            entry_tokens = set(entry.get("tokens") or [])
            if not entry_tokens:
                entry_tokens = tokenize_requirement(
                    f"{entry.get('objective')} {' '.join(entry.get('behaviors') or [])}"
                )
            if tokens & entry_tokens:
                hits += 1
                break
    return hits


def _bank_exemplar_counts(out_dir: Path, items: list[dict[str, Any]]) -> dict[str, int]:
    """统计当前 adjudication_bank 对当前功能需求的 few-shot 正例/负例命中数。"""
    from adjudication_bank import load_bank, resolve_bank_path, select_exemplars, select_negative_exemplars

    bank_path = resolve_bank_path()
    if bank_path is None:
        return {"positive": 0, "negative": 0}
    bank = load_bank(bank_path)
    positive = 0
    negative = 0
    for item in items:
        module = str(item.get("module") or "")
        query = " ".join([
            str(item.get("objective") or ""),
            " ".join(str(b) for b in (item.get("behaviors") or [])),
            str(item.get("description") or ""),
        ])
        if select_exemplars(bank, module, query):
            positive += 1
        if select_negative_exemplars(bank, module, query):
            negative += 1
    return {"positive": positive, "negative": negative}


def harvest_assets(out_dir: Path | str, *, actor: str = "harvester") -> dict[str, Any]:
    """对单个项目目录执行知识沉淀闭环，写 harvest_report.json 与五个候选文件。

    返回 harvest_report 字典（含 ``counts`` / ``metrics`` / ``written`` / ``errors``）。
    """
    root = Path(out_dir).expanduser().resolve()
    tag = _project_tag(root)
    errors: list[str] = []

    items = _load_functional_requirements(root)
    lifecycle_by_rid = _load_lifecycle_states(root)
    adjudication_by_rid = _load_adjudication_results(root)

    counts: dict[str, int] = {
        "adjudication_bank": 0,
        "pending_requirements": 0,
        "pending_solutions": 0,
        "kb_candidates": 0,
        "dictionary_candidates": 0,
        "calibration_reviews": 0,
    }

    pending_requirements: list[dict[str, Any]] = []
    pending_solutions: list[dict[str, Any]] = []
    kb_candidates: list[dict[str, Any]] = []
    dictionary_candidates: list[dict[str, Any]] = []
    calibration_reviews: list[dict[str, Any]] = []

    # 2. confirmed 功能需求 / 草稿分路
    for item in items:
        rid = str(item.get("functional_requirement_id") or "").strip()
        lifecycle = lifecycle_by_rid.get(rid, "draft")
        confirmed = _is_confirmed(lifecycle)
        record = {
            "schema": "pending-requirement/v1",
            "harvested_at": _now_iso(),
            "project_tag": tag,
            "functional_requirement_id": rid,
            "objective": str(item.get("objective") or ""),
            "behaviors": [str(b) for b in (item.get("behaviors") or []) if str(b)],
            "module": str(item.get("module") or ""),
            "ownership": str(item.get("ownership") or ""),
            "source_section": str(item.get("source_section") or ""),
            "source_quote": str(item.get("source_quote") or ""),
            "source_block_ids": [str(b) for b in (item.get("source_block_ids") or []) if str(b)],
            "lifecycle_state": lifecycle,
            "confirmed": confirmed,
            "actor": actor,
        }
        pending_requirements.append(record)
        counts["pending_requirements"] += 1

        # 3. 实现方案（design_options / 归属理由 / 验收写法）
        design_options = [str(v).strip() for v in (item.get("design_options") or []) if str(v).strip()]
        ownership_reason = str(item.get("ownership_reason") or "").strip()
        acceptance = [str(v).strip() for v in (item.get("acceptance_criteria") or []) if str(v).strip()]
        if design_options or ownership_reason or acceptance:
            pending_solutions.append({
                "schema": "pending-solution/v1",
                "harvested_at": _now_iso(),
                "project_tag": tag,
                "functional_requirement_id": rid,
                "lifecycle_state": lifecycle,
                "confirmed": confirmed,
                "design_options": design_options,
                "ownership_reason": ownership_reason,
                "acceptance_criteria": acceptance,
                "actor": actor,
            })
            counts["pending_solutions"] += 1

        # 4. 领域知识候选（只收集，不进 vault）
        terms = _extract_domain_terms(item)
        for term in terms:
            kb_candidates.append({
                "schema": "kb-candidate/v1",
                "harvested_at": _now_iso(),
                "project_tag": tag,
                "functional_requirement_id": rid,
                "term": term,
                "context": str(item.get("objective") or "")[:200],
                "actor": actor,
            })
            counts["kb_candidates"] += 1

        # 5. 语言资产候选
        weak_words = _extract_weak_words(item)
        for word in weak_words:
            dictionary_candidates.append({
                "schema": "dictionary-candidate/v1",
                "harvested_at": _now_iso(),
                "project_tag": tag,
                "functional_requirement_id": rid,
                "word": word,
                "category": "weak_word",
                "version": HARVEST_VERSION,
                "actor": actor,
            })
            counts["dictionary_candidates"] += 1

    # 6. 校准资产： adjudication 误判记录（reject / sample / summary）
    from adjudicate import read_adjudication_audit
    try:
        audit_rows = read_adjudication_audit(root)
    except Exception as exc:
        audit_rows = []
        errors.append(f"read_adjudication_audit failed: {exc}")
    for row in audit_rows:
        kind = str(row.get("kind") or "")
        if kind in ("potential_misjudgment", "sample"):
            calibration_reviews.append({
                "schema": "calibration-review/v1",
                "harvested_at": _now_iso(),
                "project_tag": tag,
                "functional_requirement_id": str(row.get("functional_requirement_id") or ""),
                "kind": kind,
                "decision": str(row.get("decision") or ""),
                "reason": str(row.get("reason") or ""),
                "actor": actor,
            })
            counts["calibration_reviews"] += 1

    # 1. 裁决样本 → adjudication_bank（复用既有 update_bank）
    bank_harvest: dict[str, Any] = {}
    try:
        from adjudication_bank import resolve_bank_path, update_bank
        bank_path = resolve_bank_path()
        if bank_path is not None:
            bank_harvest = update_bank(bank_path, root)
            counts["adjudication_bank"] = int(bank_harvest.get("harvested_accepted") or 0)
    except Exception as exc:
        errors.append(f"adjudication_bank harvest failed: {exc}")

    written: list[str] = []
    try:
        _atomic_write_jsonl(_governed_state_path(root, PENDING_REQUIREMENTS_FILE), pending_requirements)
        written.append(PENDING_REQUIREMENTS_FILE)
    except Exception as exc:
        errors.append(f"write {PENDING_REQUIREMENTS_FILE} failed: {exc}")

    if pending_solutions:
        try:
            _atomic_write_jsonl(_governed_state_path(root, PENDING_SOLUTIONS_FILE), pending_solutions)
            written.append(PENDING_SOLUTIONS_FILE)
        except Exception as exc:
            errors.append(f"write {PENDING_SOLUTIONS_FILE} failed: {exc}")

    if kb_candidates:
        try:
            _atomic_write_jsonl(_governed_state_path(root, KB_CANDIDATES_FILE), kb_candidates)
            written.append(KB_CANDIDATES_FILE)
        except Exception as exc:
            errors.append(f"write {KB_CANDIDATES_FILE} failed: {exc}")

    if dictionary_candidates:
        try:
            _atomic_write_jsonl(_governed_state_path(root, DICTIONARY_CANDIDATES_FILE), dictionary_candidates)
            written.append(DICTIONARY_CANDIDATES_FILE)
        except Exception as exc:
            errors.append(f"write {DICTIONARY_CANDIDATES_FILE} failed: {exc}")

    if calibration_reviews:
        try:
            _atomic_write_jsonl(_governed_state_path(root, CALIBRATION_REVIEW_FILE), calibration_reviews)
            written.append(CALIBRATION_REVIEW_FILE)
        except Exception as exc:
            errors.append(f"write {CALIBRATION_REVIEW_FILE} failed: {exc}")

    # 飞轮仪表盘五指标
    library_path_env = os.environ.get(ENV_REQUIREMENT_LIBRARY, "").strip()
    library_path = Path(library_path_env) if library_path_env else None
    library_hits = _library_hit_count(items, library_path)
    exemplar_counts = _bank_exemplar_counts(root, items)

    metrics = {
        "total_ingested": sum(counts.values()),
        "next_project_library_hit_rate": (
            round(library_hits / max(1, len(items)), 4) if items else 0.0
        ),
        "kb_hit_count": library_hits,
        "few_shot_positive_count": exemplar_counts["positive"],
        "negative_intercept_count": exemplar_counts["negative"],
    }

    report = {
        "schema": HARVEST_SCHEMA,
        "version": HARVEST_VERSION,
        "harvested_at": _now_iso(),
        "enabled": True,
        "project_tag": tag,
        "actor": actor,
        "counts": counts,
        "metrics": metrics,
        "total_functional_requirements": len(items),
        "confirmed_count": sum(1 for rid in lifecycle_by_rid if _is_confirmed(lifecycle_by_rid[rid])),
        "adjudication_summary": {
            "accept": sum(1 for r in adjudication_by_rid.values() if str(r.get("decision")) == "accept"),
            "review": sum(1 for r in adjudication_by_rid.values() if str(r.get("decision")) == "review"),
            "reject": sum(1 for r in adjudication_by_rid.values() if str(r.get("decision")) == "reject"),
        },
        "written": written,
        "errors": errors,
    }

    try:
        report_path = _governed_state_path(root, HARVEST_REPORT_FILE)
        _atomic_write_json(report_path, report)
        written.append(HARVEST_REPORT_FILE)
    except Exception as exc:
        errors.append(f"write {HARVEST_REPORT_FILE} failed: {exc}")

    return report


def read_harvest_report(out_dir: Path | str) -> dict[str, Any]:
    """读取 harvest_report.json；不存在或损坏返回空 report。"""
    root = Path(out_dir).expanduser().resolve()
    path = _governed_state_path(root, HARVEST_REPORT_FILE, for_write=False)
    if not path.is_file():
        return {"schema": HARVEST_SCHEMA, "enabled": False, "metrics": {}}
    try:
        return _read_json(path)
    except Exception:
        return {"schema": HARVEST_SCHEMA, "enabled": False, "metrics": {}}


if __name__ == "__main__":
    import argparse
    import logging

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Harvest reusable assets after document analysis.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--actor", default="harvester")
    args = parser.parse_args()
    report = harvest_assets(args.out, actor=args.actor)
    print(json.dumps(report, ensure_ascii=False, indent=2))
