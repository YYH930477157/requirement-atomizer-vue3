"""Claim 账本三层防漏网（A4）。

- 消费粒度抬升：sampling 模式下 eligible 集合来源从原子级扩展到功能需求级条目。
- 四视角确定性复扫（归属/数值/约束/覆盖）汇入 quality_report。
- sampling deferred 清单沿用既有通道。

全部默认关闭。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CLAIM_RESCAN_SWITCH = "RATOMIZER_CLAIM_RESCAN"
CLAIM_RESCAN_VERSION = "claim-rescan-v1"


def _load_json(out_dir: Path, filename: str) -> dict[str, Any] | None:
    path = Path(out_dir).expanduser().resolve() / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl(out_dir: Path, filename: str) -> list[dict[str, Any]]:
    path = Path(out_dir).expanduser().resolve() / filename
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _ownership_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """归属视角：未归属/模块冲突。"""
    issues: list[dict[str, Any]] = []
    for item in items:
        module = str(item.get("module") or "").strip()
        if not module or module == "未归属":
            issues.append({
                "type": "ownership_unassigned",
                "functional_requirement_id": item.get("functional_requirement_id") or item.get("functional_key"),
                "title": str(item.get("title") or item.get("functional_key") or "")[:80],
            })
    return issues


def _numeric_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """数值视角：标题/描述含数字但 threshold_table 为空或缺失。"""
    import re
    issues: list[dict[str, Any]] = []
    for item in items:
        surface = " ".join(str(item.get(field) or "") for field in ("title", "description", "objective"))
        has_number = bool(re.search(r"\b\d+(?:\.\d+)?\b", surface))
        thresholds = item.get("threshold_table") or {}
        if has_number and not thresholds:
            issues.append({
                "type": "numeric_missing_threshold",
                "functional_requirement_id": item.get("functional_requirement_id") or item.get("functional_key"),
                "title": str(item.get("title") or item.get("functional_key") or "")[:80],
            })
    return issues


def _constraint_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """约束视角：含情态词但缺少 acceptance criteria。"""
    import re
    issues: list[dict[str, Any]] = []
    modal_re = re.compile(r"\b(shall|must|should|required)\b", re.IGNORECASE)
    for item in items:
        surface = " ".join(str(item.get(field) or "") for field in ("title", "description", "objective"))
        if modal_re.search(surface):
            acceptance = item.get("acceptance_criteria") or []
            if not acceptance:
                issues.append({
                    "type": "constraint_missing_acceptance",
                    "functional_requirement_id": item.get("functional_requirement_id") or item.get("functional_key"),
                    "title": str(item.get("title") or item.get("functional_key") or "")[:80],
                })
    return issues


def _coverage_issues(items: list[dict[str, Any]], atomic_count: int) -> list[dict[str, Any]]:
    """覆盖视角：功能需求无 source_ai_requirement_ids。"""
    issues: list[dict[str, Any]] = []
    for item in items:
        source_ids = item.get("source_ai_requirement_ids") or []
        if not source_ids:
            issues.append({
                "type": "coverage_missing_source",
                "functional_requirement_id": item.get("functional_requirement_id") or item.get("functional_key"),
                "title": str(item.get("title") or item.get("functional_key") or "")[:80],
            })
    if not items and atomic_count > 0:
        issues.append({
            "type": "coverage_no_functional_items",
            "message": "存在原子需求但无功能需求合成条目",
        })
    return issues


def run_claim_rescan(out_dir: Path) -> dict[str, Any] | None:
    """执行四视角复扫，返回可汇入 quality_report 的结构。默认关。"""
    if os.environ.get(CLAIM_RESCAN_SWITCH, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    functional = _load_json(out_dir, "functional_requirements.json")
    items = (functional or {}).get("items") or [] if isinstance(functional, dict) else []
    atomic = _load_jsonl(out_dir, "atomic_requirements.jsonl")
    ownership = _ownership_issues(items)
    numeric = _numeric_issues(items)
    constraint = _constraint_issues(items)
    coverage = _coverage_issues(items, len(atomic))
    total = len(ownership) + len(numeric) + len(constraint) + len(coverage)
    return {
        "version": CLAIM_RESCAN_VERSION,
        "enabled": True,
        "total_issues": total,
        "perspectives": {
            "ownership": {"count": len(ownership), "issues": ownership[:50]},
            "numeric": {"count": len(numeric), "issues": numeric[:50]},
            "constraint": {"count": len(constraint), "issues": constraint[:50]},
            "coverage": {"count": len(coverage), "issues": coverage[:50]},
        },
    }
