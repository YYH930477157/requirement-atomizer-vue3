"""WS-B 功能需求级 AI 裁决（B1-B4）。

对 ``functional_requirements.json`` 的功能需求级条目做三路裁决：
* ``accept`` — 硬依据全绿 + LLM 语义投票通过 + 阈值校准允许自动通过。
* ``review`` — 进入人工例外队列（硬依据黄灯 / LLM 语义存疑 / 被抽审命中 / 校准未就绪）。
* ``reject`` — 硬依据红灯（编码漂移 / 守恒未闭合 / claim verifier 未闭合）。

核心纪律：
* 硬依据层有一票否决权；LLM 语义层只投"合理性"票，不覆盖硬依据。
* 无 key / stub / LLM 不可用时如实 ``adjudication_unavailable``，全部条目进 review 队列，
  绝不伪造通过。
* 自动通过默认全关（``RATOMIZER_AUTO_ADJUDICATE_APPROVE`` 与 ``RATOMIZER_AUTO_ADJUDICATE_REJECT``
  双开关分离）；自动拒绝可独立开启。
* 真值集 pending 时（``truth.jsonl`` 为空）自动通过硬禁用，但自动拒绝与 review 仍可用。
* 裁决记录 append-only，带硬依据明细、LLM 投票、阈值版本，可追责。
* 误判记录进 ``adjudication_audit.jsonl``；高风险编码条目必抽。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from cosem_behavior_spec import extract_codes
from result_package import governed_artifact_path

ADJUDICATION_VERSION = "adjudication-v2"
ADJUDICATION_SCHEMA = "adjudication-record/v2"
# WS-D D2：语义投票 prompt 的版本戳（prompt_registry 登记锚；prompt 文本变更必须 bump）。
ADJUDICATE_PROMPT_VERSION = "adjudicate-prompt-v1"
AUDIT_SCHEMA = "adjudication-audit/v1"
RESULTS_FILENAME = "adjudication_results.jsonl"
AUDIT_FILENAME = "adjudication_audit.jsonl"

# WS-B V4：忠实性证据门槛（低分二分流用，不用于自动 reject）
FAITHFULNESS_MIN_SOURCE_CHARS = 6
FAITHFULNESS_MIN_BLOCK_IDS = 1

LOGGER = logging.getLogger("requirement_atomizer")

# ---------------------------------------------------------------------------
# 开关（config.ENV_REGISTRY 同步登记）
# ---------------------------------------------------------------------------

ENV_APPROVE = "RATOMIZER_AUTO_ADJUDICATE_APPROVE"
ENV_REJECT = "RATOMIZER_AUTO_ADJUDICATE_REJECT"
ENV_REVIEW_RATE = "RATOMIZER_AUTO_ADJUDICATE_REVIEW_RATE"
ENV_SAMPLE_RATE = "RATOMIZER_AUTO_ADJUDICATE_SAMPLE_RATE"
ENV_FAR_THRESHOLD = "RATOMIZER_AUTO_ADJUDICATE_FAR_THRESHOLD"
ENV_TRUTH_SET = "RATOMIZER_AUTO_ADJUDICATE_TRUTH_SET"
ENV_LLM_ROUTE = "RATOMIZER_AUTO_ADJUDICATE_LLM_ROUTE"

DEFAULT_REVIEW_RATE = 0.0    # 默认不强制 review（除硬依据/抽审外）
DEFAULT_SAMPLE_RATE = 0.1    # 自动 accept 结果中 10% 进抽审
DEFAULT_FAR_THRESHOLD = 0.02  # 误受率 <2% 才允许自动通过


class AdjudicationError(RuntimeError):
    """裁决流程级错误（非单条决策错误）。"""


class AdjudicationUnavailableError(RuntimeError):
    """LLM 语义投票不可用。"""


# ---------------------------------------------------------------------------
# 状态 / 决策枚举
# ---------------------------------------------------------------------------

ADJUDICATION_DECISIONS = ("accept", "review", "reject", "unavailable", "pending_calibration")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float, low: float = 0.0, high: float = 1.0) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def auto_approve_enabled() -> bool:
    """自动通过开关（默认关）。"""
    return _bool_env(ENV_APPROVE, False)


def auto_reject_enabled() -> bool:
    """自动拒绝开关（默认关）。"""
    return _bool_env(ENV_REJECT, False)


def review_rate() -> float:
    """自动裁决为 accept 后按概率强制降级为 review 的比例（可配）。"""
    return _float_env(ENV_REVIEW_RATE, DEFAULT_REVIEW_RATE)


def sample_rate() -> float:
    """自动 accept 结果进抽审队列的比例。"""
    return _float_env(ENV_SAMPLE_RATE, DEFAULT_SAMPLE_RATE)


def far_threshold() -> float:
    """允许自动通过的误受率上限。"""
    return _float_env(ENV_FAR_THRESHOLD, DEFAULT_FAR_THRESHOLD)


def truth_set_path() -> Path | None:
    """真值集路径；未配置时尝试仓内默认 gold_functional_v1/truth.jsonl。"""
    raw = os.environ.get(ENV_TRUTH_SET, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    repo_default = (Path(__file__).resolve().parent / "golden_sets" / "gold_functional_v1").joinpath("truth.jsonl")
    if repo_default.is_file():
        return repo_default
    return None


def llm_route_for_adjudication() -> str | None:
    """语义投票 LLM 路由；未配置时复用当前 RATOMIZER_LLM_MODEL / pipeline yaml 默认路由。"""
    raw = os.environ.get(ENV_LLM_ROUTE, "").strip()
    if raw and raw.lower() != "stub":
        return raw
    return os.environ.get("RATOMIZER_LLM_MODEL", "").strip() or None


# ---------------------------------------------------------------------------
# 硬依据层（确定性，一票否决）
# ---------------------------------------------------------------------------

@dataclass
class HardBasis:
    ok: bool                                  # 是否无否决
    reject_reasons: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _source_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("source_quote", "source_section", "objective", "description"):
        value = item.get(key)
        if value is not None:
            if isinstance(value, list):
                parts.extend(str(v) for v in value if str(v).strip())
            else:
                parts.append(str(value))
    return "\n".join(parts)


def _extract_item_codes(item: dict[str, Any]) -> set[str]:
    """汇总 item 全部叙述字段中的受保护编码。"""
    text = "\n".join(
        str(v) if not isinstance(v, list) else "\n".join(str(x) for x in v)
        for v in item.values()
        if isinstance(v, (str, list))
    )
    return extract_codes(text)


def hard_basis_check(
    item: dict[str, Any],
    *,
    out_dir: Path | None = None,
    conservation: dict[str, Any] | None = None,
) -> HardBasis:
    """对单条功能需求做硬依据检查。

    一票否决项（→ reject）：
    1. 编码零漂移：``rejected_codes`` 非空（functional_extract 已剔除并留痕）。
    2. 受保护编码在 LLM 叙述字段中出现但来源没有（二次保险）。
    3. 守恒门开：conservation.ok == False 且本 item 的 source_block_ids 涉及缺失/重复。
    4. claim verifier 未闭合：claim 账本启用且存在未闭合 claim 关联到本 item 来源块。

    黄灯项（→ review，不否决但需人看）：
    1. numeric_drift_flag 为真（普通数字漂移软标）。
    2. 有 conflict_flags。
    """
    reject_reasons: list[str] = []
    review_reasons: list[str] = []
    evidence: dict[str, Any] = {}

    # 1. 编码零漂移（functional_extract 护栏留痕）
    rejected_codes = item.get("rejected_codes") or []
    if rejected_codes:
        reject_reasons.append(f"受保护编码漂移：{rejected_codes}")
        evidence["rejected_codes"] = list(rejected_codes)

    # 2. 受保护编码在叙述字段中出现但来源没有（二次保险）
    source_text = _source_text(item)
    source_codes = extract_codes(source_text)
    item_codes = _extract_item_codes(item)
    drifted = sorted(item_codes - source_codes)
    if drifted:
        reject_reasons.append(f"受保护编码无来源：{drifted}")
        evidence["unmatched_protected_codes"] = drifted

    # 3. 守恒门
    conservation = conservation or {}
    block_ids = set(str(b) for b in (item.get("source_block_ids") or []) if str(b))
    if not conservation.get("ok", True):
        missing = set(str(b) for b in (conservation.get("missing_block_ids") or []))
        duplicate = set(str(b) for b in (conservation.get("duplicate_assignments") or []))
        extra = set(str(b) for b in (conservation.get("extra_block_ids") or []))
        if block_ids & missing:
            reject_reasons.append("来源块未被功能需求集合覆盖（守恒缺失）")
            evidence["conservation_missing"] = sorted(block_ids & missing)
        if block_ids & duplicate:
            reject_reasons.append("来源块被多条功能需求重复覆盖（守恒重复）")
            evidence["conservation_duplicate"] = sorted(block_ids & duplicate)
        if block_ids & extra:
            reject_reasons.append("来源块不在条款集合中（守恒越界）")
            evidence["conservation_extra"] = sorted(block_ids & extra)
        mismatches = conservation.get("evidence_mismatches") or []
        for mm in mismatches:
            if not isinstance(mm, dict):
                continue
            if str(mm.get("functional_requirement_id") or "") == str(item.get("functional_requirement_id") or ""):
                reject_reasons.append("来源引句与声明块不一致（证据错配）")
                evidence.setdefault("evidence_mismatches", []).append(mm)

    # 4. claim verifier 闭合状态
    if out_dir is not None:
        claim_open = _claim_open_for_blocks(out_dir, block_ids)
        if claim_open:
            reject_reasons.append("关联 claim verifier 未闭合")
            evidence["claim_open_count"] = claim_open

    # 黄灯项
    if item.get("numeric_drift_flag"):
        review_reasons.append("普通数字漂移软标")
        evidence["numeric_drift_values"] = item.get("numeric_drift_values") or []

    conflict_flags = item.get("conflict_flags") or []
    if conflict_flags:
        review_reasons.append(f"冲突标记：{conflict_flags}")
        evidence["conflict_flags"] = list(conflict_flags)

    return HardBasis(
        ok=not reject_reasons,
        reject_reasons=reject_reasons,
        review_reasons=review_reasons,
        evidence=evidence,
    )


def _claim_open_for_blocks(out_dir: Path, block_ids: set[str]) -> int:
    """统计关联到给定 block_ids 的未闭合（uncertain）claim 数量。

    轻量只读：读 ``claim_catalog.jsonl`` 与 ``claim_effective_ledger.jsonl``；
    文件不存在或损坏返回 0（claim 账本未启用时不阻塞）。
    """
    from io_utils import read_jsonl

    root = Path(out_dir).expanduser().resolve()
    try:
        catalog_path = governed_artifact_path(
            root, "claim_catalog.jsonl", category="state", for_write=False
        )
        ledger_path = governed_artifact_path(
            root, "claim_effective_ledger.jsonl", category="state", for_write=False
        )
    except Exception:  # noqa: BLE001
        return 0

    claim_to_block: dict[str, str] = {}
    try:
        for row in read_jsonl(catalog_path):
            if not isinstance(row, dict):
                continue
            claim_id = str(row.get("claim_id") or "").strip()
            if not claim_id:
                continue
            locator = row.get("locator") if isinstance(row.get("locator"), dict) else {}
            block_id = str(
                locator.get("block_id")
                or row.get("block_id")
                or row.get("table_block_id")
                or ""
            ).strip()
            if block_id and block_id in block_ids:
                claim_to_block[claim_id] = block_id
    except Exception:  # noqa: BLE001
        return 0

    open_count = 0
    try:
        for row in read_jsonl(ledger_path):
            if not isinstance(row, dict):
                continue
            claim_id = str(row.get("claim_id") or "").strip()
            if claim_id not in claim_to_block:
                continue
            if str(row.get("resolution") or "").lower() == "uncertain":
                open_count += 1
    except Exception:  # noqa: BLE001
        pass
    return open_count


# ---------------------------------------------------------------------------
# LLM 语义投票层（只投票，不覆盖硬依据）
# ---------------------------------------------------------------------------

SEMANTIC_PROMPT = """你是需求评审助手。仅对下面这一条功能需求的语义合理性投票，
不要检查编码/数字/来源块等技术硬指标（它们由另一套确定性护栏处理）。

投票规则：
- accept：语义自洽、可测试、无歧义、与来源引句一致。
- review：语义含糊、可测性不足、存在潜在歧义、或需要领域专家确认。
- reject：语义明显荒谬、与来源引句矛盾、或不是有效需求。

只返回 JSON：{"vote": "accept|review|reject", "reason": "一句话理由"}。
"""


def _semantic_vote_prompt(item: dict[str, Any]) -> str:
    parts = [
        f"objective: {item.get('objective') or ''}",
    ]
    for key in ("behaviors", "preconditions", "data_constraints", "variants", "exceptions"):
        values = item.get(key)
        if values:
            parts.append(f"{key}: {json.dumps(values, ensure_ascii=False)}")
    parts.append(f"source_quote: {item.get('source_quote') or ''}")
    return "\n".join(parts)


def semantic_vote(
    item: dict[str, Any],
    *,
    route: str | None = None,
    chat: Callable[[str, str], dict[str, Any]] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """对单条功能需求做 LLM 语义投票。

    返回 (vote, usage/audit)。vote 为 None 表示不可用（无 key/stub/调用失败）。
    只投票，不覆盖硬依据；调用方必须单独检查硬依据。
    """
    vote: str | None = None
    usage: dict[str, Any] = {"calls": 0, "tokens": 0, "available": False, "route": route or "stub"}

    if chat is not None:
        try:
            response = chat(SEMANTIC_PROMPT, _semantic_vote_prompt(item))
            usage["calls"] = 1
            usage["available"] = True
            if isinstance(response, dict):
                vote = str(response.get("vote") or "").strip().lower()
                usage["reason"] = str(response.get("reason") or "").strip()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("adjudication 语义投票回调失败：%s", exc)
            usage["error"] = str(exc)
        return vote if vote in {"accept", "review", "reject"} else None, usage

    route = route or llm_route_for_adjudication()
    config = _resolve_route_config(route)
    if config is None:
        usage["error"] = "adjudication_unavailable: no usable LLM route"
        return None, usage

    from llm_client import chat_json

    try:
        response = chat_json(config, SEMANTIC_PROMPT, _semantic_vote_prompt(item), max_truncation_escalations=1)
        usage["calls"] = 1
        usage["available"] = True
        usage["tokens"] = _usage_tokens(response)
        vote = str(response.get("vote") or "").strip().lower() if isinstance(response, dict) else None
        usage["reason"] = str(response.get("reason") or "").strip() if isinstance(response, dict) else ""
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("adjudication 语义投票 LLM 调用失败：%s", exc)
        usage["error"] = f"adjudication_unavailable: {exc}"
    return vote if vote in {"accept", "review", "reject"} else None, usage


def _resolve_route_config(route: str | None):
    """解析 route 到可用 LLM 配置；不可用返回 None（→ unavailable）。"""
    if not route or route.lower() == "stub":
        return None
    try:
        from ai_extract import DEFAULT_PIPELINE_PATH, config_for_route
        config = config_for_route(route, DEFAULT_PIPELINE_PATH)
    except Exception:  # noqa: BLE001
        return None
    if config is None:
        return None
    local_endpoint = any(
        host in config.base_url.casefold() for host in ("127.0.0.1", "localhost", "::1")
    )
    if not local_endpoint and not os.environ.get(config.api_key_env):
        return None
    return config


def _usage_tokens(response: Any) -> int:
    usage = response.get("usage") if isinstance(response, dict) else None
    if isinstance(usage, dict):
        return int(usage.get("total_tokens") or 0)
    return 0


# ---------------------------------------------------------------------------
# 阈值真值校准（B2）
# ---------------------------------------------------------------------------

@dataclass
class CalibrationState:
    """真值校准状态（V4 现状：**单层（single-stratum）**）。

    A-2（2026-08-07）诚实化：校准当前对**整份真值集**计算单一 FAR（= 1 - precision），
    **不**按 KB 命中/未命中分层。V4 设计曾设想"阈值按 KB 命中/未命中分层校准（招标类
    真值文档提供 non-KB 标定样本）"，但该分层依赖真实真值标注（含两个层各自足够样本）
    与 FAR 可达性验证（评审报告 #3：微型真值集上 FAR 系统性偏高、自动通过门当前不可达），
    二者均为纯人工硬阻塞，故分层实现**显式延后**——不在空真值集上构建无法验证的分层机制
    （那只是更精致的空壳）。本 dataclass 因此**不含**任何分层字段（strata / kb_hit_far /
    kb_miss_far 等）；引入分层时必须同步更新此处说明与 ``test_calibration_is_single_stratum``
    特征测试。无论分层与否，真值 pending 时 ``pending_annotation`` 硬禁用自动通过的语义不变。
    """

    status: str  # "pending_annotation" | "calibrated" | "insufficient"
    far: float | None = None           # 误受率（false acceptance rate，单一标量，非分层）
    recall: float | None = None
    precision: float | None = None
    truth_count: int = 0
    threshold_version: str = ADJUDICATION_VERSION
    report_path: Path | None = None
    note: str = ""


def calibration_state(
    out_dir: Path | str,
    *,
    products_path: Path | str | None = None,
) -> CalibrationState:
    """检查真值集状态与误受率（**单层**：整份真值集一个 FAR，不按 KB 命中分层）。

    * 真值集为空 → ``pending_annotation``：自动通过硬禁用。
    * 真值集非空但无法评估 → ``insufficient``。
    * 评估通过且 far < threshold → ``calibrated``。

    A-2：KB 命中/未命中分层校准为**显式延后项**（详见 ``CalibrationState`` 说明与
    ``docs/adjudication-calibration-status.md``）。此处对全部产物计算单一 precision/recall，
    KB 命中只在 ``adjudicate_item`` 的"不熟但忠实"分流里作加分项，不进入校准门槛。
    """
    truth_path = truth_set_path()
    if truth_path is None or not truth_path.is_file() or truth_path.stat().st_size == 0:
        return CalibrationState(
            status="pending_annotation",
            note="真值集尚未标注，自动通过硬禁用",
        )

    products = Path(products_path) if products_path else Path(out_dir).expanduser().resolve()
    try:
        from tools.functional_truth_eval import evaluate_doc, _load_products, _load_truth
        doc_ref, product_items = _load_products(products)
        truth_entries = _load_truth(truth_path)
    except Exception as exc:  # noqa: BLE001
        return CalibrationState(
            status="insufficient",
            note=f"真值评估输入不可用：{exc}",
        )

    if not truth_entries:
        return CalibrationState(
            status="pending_annotation",
            note="真值集文件为空，自动通过硬禁用",
        )

    # 按文档评估；若产物缺少 doc_ref 则退为整体评估
    if doc_ref and doc_ref != "unknown":
        by_doc_truth = {doc_ref: truth_entries}
    else:
        by_doc_truth = {"unknown": truth_entries}

    # 取首文档结果（功能需求级真值集目前为单文档微型集）
    result = evaluate_doc(by_doc_truth["unknown" if "unknown" in by_doc_truth else doc_ref], product_items)
    precision = result.get("precision", 0.0)
    recall = result.get("recall", 0.0)
    # 误受率 ≈ 1 - precision（锚点空悬的产物 ≈ 被自动接受但实际无真值支持）
    far = 1.0 - precision if precision is not None else None
    status = "calibrated" if (far is not None and far < far_threshold()) else "insufficient"
    note = (
        f"truth_count={len(truth_entries)}; recall={recall}; precision={precision}; "
        f"far={far}; threshold={far_threshold()}"
    )
    return CalibrationState(
        status=status,
        far=far,
        recall=recall,
        precision=precision,
        truth_count=len(truth_entries),
        note=note,
    )


# ---------------------------------------------------------------------------
# 单条裁决
# ---------------------------------------------------------------------------

@dataclass
class AdjudicationRecord:
    functional_requirement_id: str
    decision: str
    hard_basis: HardBasis
    semantic_vote: str | None
    semantic_usage: dict[str, Any]
    calibration_status: str
    sample_selected: bool
    actor: str
    reason: str
    timestamp: str
    version: str
    low_score_category: str | None = None
    customer_specific: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ADJUDICATION_SCHEMA,
            "functional_requirement_id": self.functional_requirement_id,
            "decision": self.decision,
            "hard_basis": {
                "ok": self.hard_basis.ok,
                "reject_reasons": self.hard_basis.reject_reasons,
                "review_reasons": self.hard_basis.review_reasons,
                "evidence": self.hard_basis.evidence,
            },
            "semantic_vote": self.semantic_vote,
            "semantic_usage": self.semantic_usage,
            "calibration_status": self.calibration_status,
            "sample_selected": self.sample_selected,
            "low_score_category": self.low_score_category,
            "customer_specific": self.customer_specific,
            "actor": self.actor,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "version": self.version,
        }


def _high_risk_for_sampling(item: dict[str, Any]) -> bool:
    """高风险条目：编码相关字段非空或数字漂移。"""
    if item.get("rejected_codes"):
        return True
    if item.get("numeric_drift_flag"):
        return True
    if item.get("conflict_flags"):
        return True
    return False


def _faithfulness_evidence_ok(item: dict[str, Any]) -> tuple[bool, str]:
    """V4 红线：忠实性证据为骨架——检查来源引句/块 ID/结构字段是否足以对着原文验证。

    返回 (ok, reason)。不满足时 low_score_category = "insufficient_evidence"，进人工队列。
    """
    source_quote = str(item.get("source_quote") or "").strip()
    if len(source_quote) < FAITHFULNESS_MIN_SOURCE_CHARS:
        return False, f"来源引句过短（{len(source_quote)} 字符），无法逐字验证"

    block_ids = [str(b) for b in (item.get("source_block_ids") or []) if str(b)]
    if len(block_ids) < FAITHFULNESS_MIN_BLOCK_IDS:
        return False, "缺少 source_block_ids，来源无法定位"

    objective = str(item.get("objective") or "").strip()
    if not objective:
        return False, "objective 为空，无明确义务主体"

    return True, ""


def _kb_hit_for_item(item: dict[str, Any]) -> bool:
    """KB 命中只作加分项：命中返回 True，未命中/无库返回 False，不扣分。"""
    from adjudication_bank import load_bank, resolve_bank_path, select_exemplars

    bank_path = resolve_bank_path()
    if bank_path is None:
        return False
    bank = load_bank(bank_path)
    module = str(item.get("module") or "")
    query = " ".join([
        str(item.get("objective") or ""),
        " ".join(str(b) for b in (item.get("behaviors") or [])),
        str(item.get("description") or ""),
    ])
    return bool(select_exemplars(bank, module, query))


def _unfamiliar_signal(item: dict[str, Any]) -> bool:
    """内容"不熟"的启发式信号：模块罕见 / 无历史库命中 / 无 few-shot 正例。

    仅用于 unfamiliar_but_faithful 分流，不进入否决逻辑。
    """
    # 若 KB 命中，则不视为不熟
    if _kb_hit_for_item(item):
        return False
    # 需求库命中也视为熟
    library_path_env = os.environ.get("RATOMIZER_REQUIREMENT_LIBRARY", "").strip()
    if library_path_env:
        from requirement_schema import search_requirement_library, tokenize_requirement
        try:
            library: list[dict[str, Any]] = []
            with Path(library_path_env).open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        library.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            query = " ".join([
                str(item.get("objective") or ""),
                " ".join(str(b) for b in (item.get("behaviors") or [])),
            ])
            if search_requirement_library(query, library, limit=1):
                return False
        except Exception:
            pass
    return True


def _build_low_score_reason(
    category: str,
    *,
    faithfulness_reason: str = "",
    approve_ok: bool = False,
    calibration_status: str = "",
    review_reasons: list[str] | None = None,
    semantic_vote_value: str | None = None,
) -> str:
    """为低分二分流生成 reason 文本。"""
    if category == "insufficient_evidence":
        return f"证据不足判不了：{faithfulness_reason}"
    if category == "unfamiliar_but_faithful":
        if approve_ok:
            return "内容不熟但抽取忠实，可放行并标 customer_specific"
        parts: list[str] = ["内容不熟但抽取忠实"]
        if calibration_status != "calibrated":
            parts.append(f"校准未通过：{calibration_status}")
        if review_reasons:
            parts.append(f"硬依据黄灯：{'; '.join(review_reasons)}")
        if semantic_vote_value != "accept":
            parts.append(f"语义投票={semantic_vote_value or 'unavailable'}")
        return "；".join(parts) or "内容不熟但抽取忠实，需专家确认"
    return ""


def adjudicate_item(
    item: dict[str, Any],
    *,
    out_dir: Path | str | None = None,
    conservation: dict[str, Any] | None = None,
    calibration: CalibrationState | None = None,
    route: str | None = None,
    chat: Callable[[str, str], dict[str, Any]] | None = None,
    actor: str = "adjudicator",
) -> AdjudicationRecord:
    """对单条功能需求做三路裁决（V4 分数构成）。

    决策顺序：
    1. 硬依据检查（一票否决）—— auto-reject 仅允许此处触发。
    2. 忠实性证据骨架——证据不足判不了 → ``insufficient_evidence`` → review。
    3. KB 命中只作加分项；不熟但忠实 → ``unfamiliar_but_faithful`` → 可放行但标
       ``customer_specific``。
    4. 真值校准状态（仅影响是否允许自动通过）。
    5. LLM 语义投票。
    6. 综合：accept 需要 approve 开关 + 校准通过 + 硬依据无 review 理由 + 语义 accept；
       reject 只允许硬依据红灯触发；其余进 review。
    """
    rid = str(item.get("functional_requirement_id") or item.get("requirement_uid") or "").strip()
    if not rid:
        raise ValueError("item missing functional_requirement_id / requirement_uid")

    hard = hard_basis_check(item, out_dir=out_dir, conservation=conservation)
    calibration = calibration or calibration_state(out_dir or ".")

    # 1. 硬依据红灯 → reject（只要 reject 开关开）；否则 review。auto-reject 仅此一处。
    if not hard.ok:
        if auto_reject_enabled():
            decision = "reject"
            reason = "; ".join(hard.reject_reasons)
        else:
            decision = "review"
            reason = f"硬依据红灯但自动拒绝未开启：{'; '.join(hard.reject_reasons)}"
        return AdjudicationRecord(
            functional_requirement_id=rid,
            decision=decision,
            hard_basis=hard,
            semantic_vote=None,
            semantic_usage={"calls": 0, "available": False, "route": route or "stub"},
            calibration_status=calibration.status,
            sample_selected=False,
            actor=actor,
            reason=reason,
            timestamp=_now_iso(),
            version=ADJUDICATION_VERSION,
        )

    # 2. 忠实性证据骨架
    faithful_ok, faithfulness_reason = _faithfulness_evidence_ok(item)

    # 3. LLM 语义投票（硬依据无红灯后调用）
    semantic_vote_value, usage = semantic_vote(item, route=route, chat=chat)

    # 4. 加分项：KB 命中 / 不熟信号
    kb_hit = _kb_hit_for_item(item)
    unfamiliar = faithful_ok and _unfamiliar_signal(item)
    customer_specific = False
    low_score_category: str | None = None

    approve_ok = (
        auto_approve_enabled()
        and calibration.status == "calibrated"
        and not hard.review_reasons
        and semantic_vote_value == "accept"
    )

    # 低分二分流
    if not faithful_ok:
        low_score_category = "insufficient_evidence"
        decision = "review"
        reason = _build_low_score_reason(
            low_score_category, faithfulness_reason=faithfulness_reason
        )
        sample_selected = False
    elif unfamiliar:
        low_score_category = "unfamiliar_but_faithful"
        customer_specific = True
        if approve_ok:
            # 客户特殊需求不因不熟悉被自动拒绝：approve_ok 时 accept 但标记
            if random.random() < review_rate():
                decision = "review"
                reason = f"自动 accept 后按 review_rate={review_rate()} 强制降级为 review（客户特定内容能力边界抽样）"
                sample_selected = False
            else:
                high_risk = _high_risk_for_sampling(item)
                sample_selected = high_risk or (random.random() < sample_rate())
                decision = "accept"
                reason = "硬依据全绿 + 语义 accept + 真值校准通过（客户特定内容，抽取忠实）"
                if sample_selected:
                    reason += "（已进抽审队列）"
        else:
            decision = "review"
            reason = _build_low_score_reason(
                low_score_category,
                approve_ok=approve_ok,
                calibration_status=calibration.status,
                review_reasons=hard.review_reasons,
                semantic_vote_value=semantic_vote_value,
            )
            sample_selected = False
    elif approve_ok:
        # review_rate：按概率强制降级为 review（模拟能力边界抽样）
        if random.random() < review_rate():
            decision = "review"
            reason = f"自动 accept 后按 review_rate={review_rate()} 强制降级为 review（能力边界抽样）"
            sample_selected = False
        else:
            # 抽审：高风险编码条目必抽 + 随机比例
            high_risk = _high_risk_for_sampling(item)
            sample_selected = high_risk or (random.random() < sample_rate())
            decision = "accept"
            reason = "硬依据全绿 + 语义 accept + 真值校准通过"
            if sample_selected:
                reason += "（已进抽审队列）"
    elif semantic_vote_value == "reject" and auto_reject_enabled():
        # V4：语义 reject 不再触发 auto-reject（拒绝仅允许硬依据红灯）
        decision = "review"
        reason = "语义投票 reject，但 V4 自动拒绝仅限硬依据红灯，故转人工审"
        sample_selected = False
    else:
        decision = "review"
        parts: list[str] = []
        if not auto_approve_enabled():
            parts.append("自动通过未开启")
        elif calibration.status != "calibrated":
            parts.append(f"校准未通过：{calibration.status}")
        if hard.review_reasons:
            parts.append(f"硬依据黄灯：{'; '.join(hard.review_reasons)}")
        if semantic_vote_value != "accept":
            parts.append(f"语义投票={semantic_vote_value or 'unavailable'}")
        reason = "; ".join(parts) or "未满足自动通过条件"
        sample_selected = False

    return AdjudicationRecord(
        functional_requirement_id=rid,
        decision=decision,
        hard_basis=hard,
        semantic_vote=semantic_vote_value,
        semantic_usage=usage,
        calibration_status=calibration.status,
        sample_selected=sample_selected,
        low_score_category=low_score_category,
        customer_specific=customer_specific,
        actor=actor,
        reason=reason,
        timestamp=_now_iso(),
        version=ADJUDICATION_VERSION,
    )


# ---------------------------------------------------------------------------
# 批量裁决与审计台账（B3）
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    from io_utils import read_jsonl
    return read_jsonl(path)


def _read_adjudication_results(out_dir: Path) -> list[dict[str, Any]]:
    path = governed_artifact_path(out_dir, RESULTS_FILENAME, category="state", for_write=False)
    if not path.is_file():
        return []
    return _read_jsonl(path)


def _write_adjudication_records(
    out_dir: Path,
    records: Sequence[AdjudicationRecord],
    *,
    audit_entries: Sequence[dict[str, Any]],
) -> None:
    """append-only 写 adjudication_results.jsonl 与 adjudication_audit.jsonl。

    使用跨进程锁 + 原子替换，与 review_state / ai_review_actions 同纪律。
    """
    results_path = governed_artifact_path(out_dir, RESULTS_FILENAME, category="state", for_write=True)
    audit_path = governed_artifact_path(out_dir, AUDIT_FILENAME, category="state", for_write=True)
    lock_path = governed_artifact_path(out_dir, "adjudication.lock", category="state", for_write=True)

    from process_file_lock import process_file_lock

    def _append(path: Path, lines: Sequence[str]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        existing: list[str] = []
        if path.is_file():
            existing = [
                line for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            for line in existing:
                handle.write(line + "\n")
            for line in lines:
                handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)

    with process_file_lock(lock_path, timeout_s=30.0, label="adjudication"):
        result_lines = [json.dumps(r.to_dict(), ensure_ascii=False) for r in records]
        _append(results_path, result_lines)
        if audit_entries:
            audit_lines = [json.dumps(a, ensure_ascii=False) for a in audit_entries]
            _append(audit_path, audit_lines)


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


def _build_audit_entries(
    records: Sequence[AdjudicationRecord],
    *,
    run_id: str,
    calibration: CalibrationState,
) -> list[dict[str, Any]]:
    """为自动 accept/reject 结果生成审计条目。

    * accept 结果中 sample_selected=True 的进抽审队列。
    * reject 结果全部进审计（潜在误判）。
    * 统计误判率并给出阈值收紧建议。
    """
    entries: list[dict[str, Any]] = []
    accepted = [r for r in records if r.decision == "accept"]
    rejected = [r for r in records if r.decision == "reject"]
    reviewed = [r for r in records if r.decision == "review"]

    for r in accepted:
        if r.sample_selected:
            entries.append({
                "schema": AUDIT_SCHEMA,
                "run_id": run_id,
                "functional_requirement_id": r.functional_requirement_id,
                "kind": "sample",
                "decision": "accept",
                "reason": r.reason,
                "hard_basis_ok": r.hard_basis.ok,
                "semantic_vote": r.semantic_vote,
                "recorded_at": r.timestamp,
            })

    for r in rejected:
        entries.append({
            "schema": AUDIT_SCHEMA,
            "run_id": run_id,
            "functional_requirement_id": r.functional_requirement_id,
            "kind": "potential_misjudgment",
            "decision": "reject",
            "reason": r.reason,
            "hard_basis": {
                "reject_reasons": r.hard_basis.reject_reasons,
                "review_reasons": r.hard_basis.review_reasons,
            },
            "semantic_vote": r.semantic_vote,
            "recorded_at": r.timestamp,
        })

    # 误判率统计 + 阈值收紧建议
    total_auto = len(accepted) + len(rejected)
    if total_auto > 0:
        # 保守估计：把 review 也视作潜在误受（它们本应被处理但未自动 accept）
        estimated_far = len(reviewed) / len(records) if records else 0.0
        entries.append({
            "schema": AUDIT_SCHEMA,
            "run_id": run_id,
            "kind": "summary",
            "counts": {
                "accept": len(accepted),
                "reject": len(rejected),
                "review": len(reviewed),
                "total": len(records),
            },
            "sampled_count": sum(1 for r in accepted if r.sample_selected),
            "estimated_far": round(estimated_far, 4),
            "far_threshold": far_threshold(),
            "calibration_status": calibration.status,
            "tighten_recommendation": (
                "建议收紧 far_threshold 或扩大抽审比例"
                if estimated_far > far_threshold() else ""
            ),
            "recorded_at": _now_iso(),
        })
    return entries


def adjudicate_all(
    out_dir: Path | str,
    *,
    items: Sequence[dict[str, Any]] | None = None,
    route: str | None = None,
    chat: Callable[[str, str], dict[str, Any]] | None = None,
    actor: str = "adjudicator",
    run_id: str | None = None,
) -> dict[str, Any]:
    """批量裁决功能需求条目，写 adjudication_results.jsonl 与 adjudication_audit.jsonl。

    ``items`` 缺省时从 ``functional_requirements.json`` 读取。
    返回摘要（counts / calibration_status / sampled_count / written）。
    """
    root = Path(out_dir).expanduser().resolve()

    if items is None:
        from requirements_analysis_rules import read_functional_requirements
        items = read_functional_requirements(root)
    items = [item for item in items if isinstance(item, dict)]

    # 读取既有裁决结果，避免重复裁决（幂等：同一 functional_requirement_id 只保留最新）
    existing = {str(r.get("functional_requirement_id") or ""): r for r in _read_adjudication_results(root)}

    conservation: dict[str, Any] = {}
    try:
        from requirements_analysis_rules import _read_functional_requirements_payload
        payload = _read_functional_requirements_payload(root)
        conservation = payload.get("conservation") or {}
    except Exception:  # noqa: BLE001
        pass

    calibration = calibration_state(root)
    run_id = run_id or _now_iso()

    records: list[AdjudicationRecord] = []
    for item in items:
        record = adjudicate_item(
            item,
            out_dir=root,
            conservation=conservation,
            calibration=calibration,
            route=route,
            chat=chat,
            actor=actor,
        )
        records.append(record)
        existing[record.functional_requirement_id] = record.to_dict()

    audit_entries = _build_audit_entries(records, run_id=run_id, calibration=calibration)
    _write_adjudication_records(root, records, audit_entries=audit_entries)

    counts = {"accept": 0, "review": 0, "reject": 0}
    for r in records:
        counts[r.decision] = counts.get(r.decision, 0) + 1

    return {
        "schema": "adjudication-summary/v1",
        "version": ADJUDICATION_VERSION,
        "run_id": run_id,
        "counts": counts,
        "total": len(records),
        "calibration_status": calibration.status,
        "far": calibration.far,
        "sampled_count": sum(1 for r in records if r.sample_selected),
        "written": [RESULTS_FILENAME, AUDIT_FILENAME],
    }


# ---------------------------------------------------------------------------
# 人工推翻（写回裁决流，actor 留痕）
# ---------------------------------------------------------------------------

def overturn_adjudication(
    out_dir: Path | str,
    functional_requirement_id: str,
    *,
    new_decision: str,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """人工推翻自动裁决结果，写回 adjudication_results.jsonl。

    不删除原记录，而是追加一条新记录；按 functional_requirement_id 取最新即当前有效决策。
    actor/reason 必填，可追责。
    """
    if new_decision not in ("accept", "review", "reject"):
        raise ValueError(f"new_decision must be accept|review|reject, got {new_decision}")
    if not actor.strip() or not reason.strip():
        raise ValueError("actor and reason are required for overturn")

    root = Path(out_dir).expanduser().resolve()
    record = AdjudicationRecord(
        functional_requirement_id=functional_requirement_id,
        decision=new_decision,
        hard_basis=HardBasis(ok=True),
        semantic_vote=None,
        semantic_usage={"calls": 0, "available": False, "overturn": True},
        calibration_status="manual_override",
        sample_selected=False,
        actor=actor.strip(),
        reason=f"人工推翻：{reason.strip()}",
        timestamp=_now_iso(),
        version=ADJUDICATION_VERSION,
    )
    _write_adjudication_records(root, [record], audit_entries=[])
    return record.to_dict()


# ---------------------------------------------------------------------------
# 读取接口（供 API / UI）
# ---------------------------------------------------------------------------

def read_adjudication_results(out_dir: Path | str) -> list[dict[str, Any]]:
    """读取当前有效的 adjudication 结果（每个 functional_requirement_id 取最新）。"""
    root = Path(out_dir).expanduser().resolve()
    rows = _read_adjudication_results(root)
    # 按时间戳取最新；时间戳相同时按文件出现顺序取最后一条（覆写语义）
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = str(row.get("functional_requirement_id") or "").strip()
        if not rid:
            continue
        existing = by_id.get(rid)
        if existing is None or str(row.get("timestamp") or "") >= str(existing.get("timestamp") or ""):
            by_id[rid] = row
    return list(by_id.values())


def read_adjudication_audit(out_dir: Path | str) -> list[dict[str, Any]]:
    """读取 adjudication_audit.jsonl（全部审计记录）。"""
    root = Path(out_dir).expanduser().resolve()
    path = governed_artifact_path(root, AUDIT_FILENAME, category="state", for_write=False)
    if not path.is_file():
        return []
    return _read_jsonl(path)


def adjudication_summary(out_dir: Path | str) -> dict[str, Any]:
    """供 API 返回的当前裁决摘要。"""
    root = Path(out_dir).expanduser().resolve()
    results = read_adjudication_results(root)
    counts = {"accept": 0, "review": 0, "reject": 0}
    for r in results:
        d = str(r.get("decision") or "")
        counts[d] = counts.get(d, 0) + 1

    calibration = calibration_state(root)
    audit = read_adjudication_audit(root)
    summaries = [a for a in audit if a.get("kind") == "summary"]
    latest_summary = summaries[-1] if summaries else None

    return {
        "schema": "adjudication-summary/v1",
        "version": ADJUDICATION_VERSION,
        "enabled": {
            "auto_approve": auto_approve_enabled(),
            "auto_reject": auto_reject_enabled(),
        },
        "counts": counts,
        "total": len(results),
        "calibration": {
            "status": calibration.status,
            "far": calibration.far,
            "recall": calibration.recall,
            "precision": calibration.precision,
            "truth_count": calibration.truth_count,
            "note": calibration.note,
        },
        "latest_run": {
            "run_id": latest_summary.get("run_id") if latest_summary else None,
            "recorded_at": latest_summary.get("recorded_at") if latest_summary else None,
            "sampled_count": latest_summary.get("sampled_count") if latest_summary else 0,
            "estimated_far": latest_summary.get("estimated_far") if latest_summary else None,
        },
    }
