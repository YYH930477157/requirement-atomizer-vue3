"""WS3 统一预算单（文档级 LLM 成本封顶），默认关闭 / 非侵入。

预算单是 WS3 唯一新增数据结构：每份文档进入流水线即生成一份，携带总调用数 / 总
token 上限、各环节子预算（``stage → {max_calls, max_tokens}``）与累计消耗。全部 LLM
调用从同一份预算单扣减，耗尽即停。

**扣减通道（不侵入任何调用点）**：``llm_client._post_json`` 是所有 OpenAI 兼容 HTTP
调用的唯一出口。``llm_client`` 暴露一个**模块级文档预算钩子挂载点**
（``set_document_budget_hook`` / ``clear_document_budget_hook``），默认 ``None`` = 零行为
改变（硬边界：默认不启用不改变行为）。本模块的 ``LLMBudgetLedger`` 实现该钩子接口
（``intercept`` / ``settle`` / ``charge_failed``），开启后：

* ``intercept(payload)`` 在 HTTP **发出前**按 token ceiling 估算余量，超额即抛
  ``llm_client.LLMBudgetExceeded``——调用方既有的 ``except Exception → stub`` 降级路径
  自然接管（``functional_extract`` / ``llm_table_understanding`` / ``review_tools`` 等均
  已有此 catch），无需修改这些模块。
* ``settle(usage)`` / ``charge_failed()`` 在收到响应后按真实 / 保守 token 结算。

**复用既有机制（不复制实现）**：

* token ceiling 估算：``llm_client.LLMRequestBudget._token_ceiling`` 同算法。
* usage 归一：``llm_client._normalized_usage``。
* 幂等键：``claim_artifacts.hash_json``——与 ``claim_queue_execution`` 的 budget
  checkpoint event 幂等键同源，落盘 snapshot 带防重放指纹，进程重启后 ``load`` 续算，
  已 checkpoint 的累计消耗不重置、不二次累加。
* checkpoint 落盘续算：跨进程锁（``process_file_lock``）+ 命名临时文件 + ``os.replace``
  重试，纪律与 ``functional_extract._write_cache_entry`` /
  ``review_state`` / ``ai_review_actions`` 一致。

**耗尽语义**（与仓库"宁漏勿错、provenance 不造假"纪律一致）：降级 stub 且 provenance
如实标注；功能需求直抽产出（核心交付物）因预算耗尽降级时，``document_needs_work``
强制为 ``True``——文档级 NEEDS WORK 标记写在预算单上，不允许仅 provenance 标注静默通过。

**成本看板数据源**：``snapshot()`` 暴露分环节累计调用数 / token 占比、缓存命中率
（缓存命中记为 ``T=0`` 零成本条目而非跳过记账）、路由分布——全部来自预算单记账流水，
无新增埋点。80% 黄色预警、100% 耗尽降级在 checkpoint 落盘时点计算。

封顶初值按方案 §5.1 口径估算（条款候选数 × 各环节单次均值 + 上浮 20%），可经环境变量
逐项覆盖；第 18 周实测回填收紧。入口开关 ``RATOMIZER_LLM_BUDGET``（默认 ``0``=关闭）。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

LOGGER = logging.getLogger("requirement_atomizer")

LLM_BUDGET_VERSION = "llm-budget-v1"
LLM_BUDGET_SCHEMA = "llm-budget/v1"
LLM_BUDGET_FILENAME = "llm_budget.json"
LLM_BUDGET_LOCK = "llm_budget.lock"

# 入口开关（config.ENV_REGISTRY 登记）：默认 0=关闭，llm_client 挂载点不激活。
ENTRY_SWITCH_ENV = "RATOMIZER_LLM_BUDGET"

# 80% 黄色预警、100% 耗尽降级（方案 §5.1 第 16 周）。
WARN_THRESHOLD = 0.8
EXHAUSTED_THRESHOLD = 1.0

# ---------------------------------------------------------------------------
# 环节（stage）枚举——与方案 §5.1 第 15 周三级路由对照表对齐。
# stub 永远优先（零调用）；小模型承担结构假设 / 功能需求初稿 / 澄清草稿；大模型只留给
# 原子级下钻七维裁定 / 发布门禁双模型制衡 / 叙述字段富化。
# ---------------------------------------------------------------------------

STAGE_STRUCTURE_HYPOTHESIS = "structure_hypothesis"   # 结构假设（小模型，全文档 ≤20 次）
STAGE_FUNCTIONAL_EXTRACT = "functional_extract"       # 功能需求初稿（小模型，估算 10–30 次）
STAGE_DRILLDOWN = "drilldown_adjudication"            # 原子级下钻七维裁定（大模型，300–500 次）
STAGE_CLARIFICATION = "clarification"                 # 澄清草稿（小模型）
STAGE_REVIEW = "llm_review"                           # 发布门禁双模型制衡（大模型）
STAGE_ANALYZE_ENRICH = "analyze_enrich"               # 叙述字段富化（大模型）
STAGE_SPEC_ENRICH = "spec_enrich"                     # 装配描述富化（大模型）
STAGE_FULL_TRANSLATION = "full_translation"           # 全文翻译（独立子预算）
STAGE_DEFAULT = "default"                             # 兜底（未显式 enter_stage 的调用）

# 各环节默认子预算封顶（calls / total_tokens）。第 18 周金标实测回填收紧；以下为方案
# §5.1 估算口径（上浮 20% 后的保守值），可经环境变量逐项覆盖（见 _default_sub_budgets）。
DEFAULT_SUB_BUDGETS: dict[str, dict[str, int]] = {
    STAGE_STRUCTURE_HYPOTHESIS: {"max_calls": 24, "max_tokens": 360_000},
    STAGE_FUNCTIONAL_EXTRACT: {"max_calls": 36, "max_tokens": 720_000},
    STAGE_DRILLDOWN: {"max_calls": 600, "max_tokens": 9_000_000},
    STAGE_CLARIFICATION: {"max_calls": 60, "max_tokens": 600_000},
    STAGE_REVIEW: {"max_calls": 600, "max_tokens": 9_000_000},
    STAGE_ANALYZE_ENRICH: {"max_calls": 360, "max_tokens": 3_600_000},
    STAGE_SPEC_ENRICH: {"max_calls": 360, "max_tokens": 3_600_000},
    # Base batches are only part of the cost: strict token guards may retry a
    # rejected item once and then fall back to sentence segments.  SBD's 899
    # blocks exhausted the old 120-call cap with most of the token budget left.
    STAGE_FULL_TRANSLATION: {"max_calls": 360, "max_tokens": 2_000_000},
    STAGE_DEFAULT: {"max_calls": 120, "max_tokens": 1_200_000},
}

# 三级模型路由默认（环节 → 模型档位）。配置项可逐项覆盖；"结构假设环节不出现大模型调用"
# 是可执行门禁（see _route_for_stage + tests）。
ROUTE_STUB = "stub"
ROUTE_SMALL = "small"
ROUTE_LARGE = "large"
DEFAULT_STAGE_ROUTES: dict[str, str] = {
    STAGE_STRUCTURE_HYPOTHESIS: ROUTE_SMALL,
    STAGE_FUNCTIONAL_EXTRACT: ROUTE_SMALL,
    STAGE_CLARIFICATION: ROUTE_SMALL,
    STAGE_DRILLDOWN: ROUTE_LARGE,
    STAGE_REVIEW: ROUTE_LARGE,
    STAGE_ANALYZE_ENRICH: ROUTE_LARGE,
    STAGE_SPEC_ENRICH: ROUTE_LARGE,
    STAGE_FULL_TRANSLATION: ROUTE_SMALL,
    STAGE_DEFAULT: ROUTE_SMALL,
}

# 单次调用 token 均值估算（用于按条款候选数推封顶初值，方案 §5.1 第 13 周）。
_AVG_TOKENS_PER_CALL: dict[str, int] = {
    STAGE_STRUCTURE_HYPOTHESIS: 12_000,
    STAGE_FUNCTIONAL_EXTRACT: 18_000,
    STAGE_DRILLDOWN: 14_000,
    STAGE_CLARIFICATION: 8_000,
    STAGE_REVIEW: 14_000,
    STAGE_ANALYZE_ENRICH: 9_000,
    STAGE_SPEC_ENRICH: 9_000,
    STAGE_FULL_TRANSLATION: 16_000,
    STAGE_DEFAULT: 10_000,
}
_CEILING_UPSCALE = 1.2  # 上浮 20%（方案口径）

# 当前 stage 上下文（同 claim_artifacts._VERIFIER_ATTEMPT_CONTEXT 的 ContextVar 模式）。
# owner（pipeline / 测试）经 ``ledger.enter_stage(stage)`` 显式设置；functional_extract 等
# 被调用模块不改，其内部 llm_client 调用自动落到当前 stage 子预算。
_ACTIVE_STAGE: ContextVar[str] = ContextVar("ratomizer_llm_budget_stage", default=STAGE_DEFAULT)
# 当前线程待结算的预留（intercept 设、settle/charge_failed 清；线程隔离防并发串账）。
_PENDING_RESERVATION: ContextVar[tuple[str, int] | None] = ContextVar(
    "ratomizer_llm_budget_pending", default=None
)


def budget_mode() -> str:
    """预算模式（方案 §14，第 9 项）：off | observe | enforce。

    - off（默认）：行为面零变化——账本开关仍由 ``RATOMIZER_LLM_BUDGET`` 决定
      （开启即沿既有 enforce 语义）；
    - observe：账本开启、逐调用记账 + 超限预警日志，**不阻断**（耗尽不抛
      LLMBudgetExceeded、不降级 stub）；
    - enforce：账本开启 + 既有事前拦截语义。
    """
    from config import get_env

    mode = str(get_env("RATOMIZER_BUDGET_MODE") or "off").strip().lower()
    if mode not in ("off", "observe", "enforce"):
        raise ValueError(
            f"未知预算模式: {mode}（可用: off | observe | enforce）")
    return mode


def budget_enabled(value: str | None = None) -> bool:
    """预算账本是否开启：mode observe/enforce 强制开；off 时由 legacy 开关决定。"""
    if budget_mode() in ("observe", "enforce"):
        return True
    raw = os.environ.get(ENTRY_SWITCH_ENV) if value is None else value
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _route_for_stage(stage: str, overrides: dict[str, str] | None) -> str:
    route = (overrides or {}).get(stage) or DEFAULT_STAGE_ROUTES.get(stage) or ROUTE_SMALL
    return route


# 轻量环节（小模型承担）：结构假设 / 功能需求初稿 / 澄清草稿。方案 §5.1 第 15 周三级路由
# 明令这些环节不出现大模型调用——本集合是可执行门禁 ``validate_stage_routes`` 的依据。
LIGHT_STAGES: frozenset[str] = frozenset({
    STAGE_STRUCTURE_HYPOTHESIS, STAGE_FUNCTIONAL_EXTRACT, STAGE_CLARIFICATION,
    STAGE_FULL_TRANSLATION,
})


class StageRouteViolation(ValueError):
    """三级模型路由门禁违例（如轻量环节被配置为大模型）。"""


def validate_stage_routes(routes: dict[str, str] | None = None) -> None:
    """可执行门禁：结构假设 / 功能需求初稿 / 澄清草稿环节不得出现大模型调用。

    方案 §5.1 第 15 周：stub 永远优先（零调用）；小模型承担结构假设 / 功能需求初稿 /
    澄清草稿；大模型只留给原子级下钻七维裁定 / 发布门禁双模型制衡 / 叙述字段富化。
    违例抛 ``StageRouteViolation``——在 ``for_document`` 构造时调用，配置错误 fail-closed。
    """
    table = dict(DEFAULT_STAGE_ROUTES)
    if routes:
        table.update(routes)
    for stage in LIGHT_STAGES:
        if table.get(stage) == ROUTE_LARGE:
            raise StageRouteViolation(
                f"stage {stage!r} must not use the large model route "
                f"(three-tier routing gate, WS3 §15w): got {ROUTE_LARGE!r}"
            )


def _default_sub_budgets(
    clause_count: int | None,
    overrides: dict[str, dict[str, int]] | None,
) -> dict[str, dict[str, int]]:
    """按方案 §5.1 口径估算封顶初值：条款候选数 × 单次均值 × 1.2（上浮 20%）。

    ``clause_count`` 缺省时回退保守固定值（``DEFAULT_SUB_BUDGETS``）。环境变量 / 显式
    overrides 逐项覆盖。
    """
    base: dict[str, dict[str, int]] = {}
    for stage, fixed in DEFAULT_SUB_BUDGETS.items():
        if clause_count and clause_count > 0:
            avg_tokens = _AVG_TOKENS_PER_CALL.get(stage, 10_000)
            # 估算调用数：抽取类按条款线性、其余取固定上限的较小者（不超估）。
            if stage in (STAGE_FUNCTIONAL_EXTRACT, STAGE_DRILLDOWN):
                est_calls = max(1, int(clause_count * _CEILING_UPSCALE))
            elif stage == STAGE_STRUCTURE_HYPOTHESIS:
                est_calls = fixed["max_calls"]  # 全文档固定上限
            else:
                est_calls = fixed["max_calls"]
            base[stage] = {
                "max_calls": est_calls,
                "max_tokens": int(est_calls * avg_tokens),
            }
        else:
            base[stage] = dict(fixed)
    if overrides:
        for stage, sub in overrides.items():
            if isinstance(sub, dict):
                merged = dict(base.get(stage, {"max_calls": 0, "max_tokens": 0}))
                if isinstance(sub.get("max_calls"), int):
                    merged["max_calls"] = int(sub["max_calls"])
                if isinstance(sub.get("max_tokens"), int):
                    merged["max_tokens"] = int(sub["max_tokens"])
                base[stage] = merged
    return base


def _normalized_total(usage: object) -> int | None:
    """复用 ``llm_client._normalized_usage`` 取可信 total_tokens（None=不可信）。"""
    from llm_client import _normalized_usage

    normalized = _normalized_usage(usage)
    return normalized["total_tokens"] if normalized is not None else None


def _token_ceiling(payload: dict[str, Any]) -> int:
    """复用 ``LLMRequestBudget._token_ceiling`` 的发送前 token 上限估算。"""
    from llm_client import LLMRequestBudget

    return LLMRequestBudget._token_ceiling(payload)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class _Reservation:
    stage: str
    ceiling: int


class LLMBudgetLedger:
    """文档级 LLM 预算单。

    生命周期：``for_document(...)`` 生成 → ``attach()`` 挂到 ``llm_client`` 模块级钩子 →
    各环节经 ``enter_stage(stage)`` 推进 → 调用经钩子扣减 → ``save(out_dir)`` 落盘 →
    重启后 ``load(out_dir)`` 续算。关闭（``detach``）后 ``llm_client`` 回到无预算行为。
    """

    def __init__(
        self,
        document_id: str,
        sub_budgets: dict[str, dict[str, int]],
        *,
        stage_routes: dict[str, str] | None = None,
        warn_threshold: float = WARN_THRESHOLD,
        out_dir: Path | str | None = None,
    ) -> None:
        if not document_id:
            raise ValueError("document_id is required")
        self.document_id = str(document_id)
        self.sub_budgets = {
            str(stage): {
                "max_calls": int(sub["max_calls"]),
                "max_tokens": int(sub["max_tokens"]),
            }
            for stage, sub in sub_budgets.items()
        }
        self.stage_routes = dict(stage_routes or DEFAULT_STAGE_ROUTES)
        self.warn_threshold = float(warn_threshold)
        self.out_dir = Path(out_dir).expanduser().resolve() if out_dir else None

        self._lock = threading.RLock()
        self._consumed: dict[str, dict[str, int | bool]] = {
            stage: {
                "calls": 0,
                "tokens": 0,
                "reserved_tokens": 0,
                "failed_calls": 0,
                "cache_hits": 0,
                "usage_complete": True,
            }
            for stage in self.sub_budgets
        }
        self._route_distribution: dict[str, int] = {}
        self._warnings: list[dict[str, Any]] = []
        self._exhausted: dict[str, str] = {}     # stage → reason
        self._degraded: dict[str, str] = {}      # stage → degradation reason
        self.document_needs_work = False
        self.created_at = _utc_now()
        self.updated_at = self.created_at
        self.last_event_seq = 0

    # ------------------------------------------------------------------
    # 工厂
    # ------------------------------------------------------------------

    @classmethod
    def for_document(
        cls,
        document_id: str,
        *,
        clause_count: int | None = None,
        out_dir: Path | str | None = None,
        sub_budget_overrides: dict[str, dict[str, int]] | None = None,
        stage_route_overrides: dict[str, str] | None = None,
        warn_threshold: float = WARN_THRESHOLD,
    ) -> "LLMBudgetLedger":
        """按方案 §5.1 口径估算封顶初值生成预算单。"""
        sub_budgets = _default_sub_budgets(clause_count, sub_budget_overrides)
        routes = dict(DEFAULT_STAGE_ROUTES)
        if stage_route_overrides:
            routes.update(stage_route_overrides)
        validate_stage_routes(routes)  # 三级路由门禁：轻量环节不得配大模型（fail-closed）
        return cls(
            document_id,
            sub_budgets,
            stage_routes=routes,
            warn_threshold=warn_threshold,
            out_dir=out_dir,
        )

    # ------------------------------------------------------------------
    # stage 上下文
    # ------------------------------------------------------------------

    def enter_stage(self, stage: str) -> "_StageScope":
        """显式推进当前环节（ContextVar；线程隔离）。``with ledger.enter_stage(s): ...``。"""
        return _StageScope(stage)

    def current_stage(self) -> str:
        return _ACTIVE_STAGE.get()

    def _sub(self, stage: str) -> dict[str, int | bool]:
        if stage not in self._consumed:
            # 未登记 stage 回退到 default 子预算记录（仍记账，不丢调用）。
            self._consumed.setdefault(stage, {
                "calls": 0, "tokens": 0, "reserved_tokens": 0,
                "failed_calls": 0, "cache_hits": 0, "usage_complete": True,
            })
            self.sub_budgets.setdefault(stage, dict(self.sub_budgets[STAGE_DEFAULT]))
        return self._consumed[stage]

    # ------------------------------------------------------------------
    # 钩子接口（挂 llm_client.set_document_budget_hook）
    # ------------------------------------------------------------------

    def intercept(self, payload: dict[str, Any]) -> None:
        """HTTP 发出**前**的余量拦截：超额抛 ``LLMBudgetExceeded``（调用方 stub catch 接管）。

        与 ``LLMRequestBudget.reserve`` 同口径：按发送体字节 + max_tokens + 余量估算 token
        ceiling，超出剩余余量即拦截（幂等键只防重复扣费，不防单次大调用击穿余量——本钩子
        补这道事前闸门，方案 §5.1 第 16 周）。
        """
        # 清可能的 pending 残留（同线程串行，无并发）：上游 per-call _request_budget.reserve
        # 抛异常时会跳过 settle/charge_failed，此处复原确保每次 intercept 从干净状态开始。
        _PENDING_RESERVATION.set(None)
        stage = _ACTIVE_STAGE.get()
        ceiling = _token_ceiling(payload)
        with self._lock:
            sub = self._sub(stage)
            budget = self.sub_budgets[stage]
            observe_only = budget_mode() == "observe"
            if int(sub["calls"]) >= int(budget["max_calls"]):
                self._mark_exhausted_unlocked(stage, "call_budget_exhausted")
                if observe_only:
                    # observe（§14）：预警不阻断——记账继续，调用放行
                    LOGGER.warning(
                        "[budget:observe] stage=%s 调用数触顶（%s/%s），放行不阻断",
                        stage, sub["calls"], budget["max_calls"])
                else:
                    raise _budget_exceeded(
                        f"document budget call-exhausted stage={stage}")
            reserved = int(sub["reserved_tokens"])
            if int(sub["tokens"]) + reserved + ceiling > int(budget["max_tokens"]):
                self._mark_exhausted_unlocked(stage, "token_budget_exhausted")
                if observe_only:
                    LOGGER.warning(
                        "[budget:observe] stage=%s token 触顶（tokens=%s reserved=%s "
                        "ceiling=%s max=%s），放行不阻断",
                        stage, sub["tokens"], reserved, ceiling, budget["max_tokens"])
                else:
                    raise _budget_exceeded(
                        f"document budget token-exhausted stage={stage} "
                        f"(tokens={sub['tokens']} reserved={reserved} ceiling={ceiling} "
                        f"max={budget['max_tokens']})"
                    )
            sub["calls"] = int(sub["calls"]) + 1
            sub["reserved_tokens"] = reserved + ceiling
            _PENDING_RESERVATION.set((stage, ceiling))
            self._checkpoint_unlocked(reason="reserve")

    def settle(self, usage: object) -> None:
        """HTTP 成功后按真实 usage 结算（usage 不可信时保守按 ceiling 计，标 usage_complete=False）。"""
        pending = _PENDING_RESERVATION.get()
        if pending is None:
            return
        stage, ceiling = pending
        total = _normalized_total(usage)
        with self._lock:
            sub = self._sub(stage)
            sub["reserved_tokens"] = max(0, int(sub["reserved_tokens"]) - ceiling)
            if total is None:
                sub["tokens"] = int(sub["tokens"]) + ceiling
                sub["usage_complete"] = False
            else:
                sub["tokens"] = int(sub["tokens"]) + int(total)
            _PENDING_RESERVATION.set(None)
            self._checkpoint_unlocked(reason="settle")

    def charge_failed(self) -> None:
        """HTTP 失败后保守按 ceiling 扣费（与 ``LLMRequestBudget.fail`` 同口径）。"""
        pending = _PENDING_RESERVATION.get()
        if pending is None:
            return
        stage, ceiling = pending
        with self._lock:
            sub = self._sub(stage)
            sub["reserved_tokens"] = max(0, int(sub["reserved_tokens"]) - ceiling)
            sub["tokens"] = int(sub["tokens"]) + ceiling
            sub["failed_calls"] = int(sub["failed_calls"]) + 1
            sub["usage_complete"] = False
            _PENDING_RESERVATION.set(None)
            self._checkpoint_unlocked(reason="fail")

    # ------------------------------------------------------------------
    # 记账辅助（缓存命中 / 路由分布）
    # ------------------------------------------------------------------

    def record_cache_hit(self, stage: str | None = None) -> None:
        """缓存命中记为 ``T=0`` 零成本条目（计 cache_hits，不增 calls/tokens）而非跳过记账。

        成本看板的缓存命中率 = cache_hits / (cache_hits + paid_calls)，方案 §5.1 第 16 周。
        """
        target = stage or _ACTIVE_STAGE.get()
        with self._lock:
            self._sub(target)["cache_hits"] = int(self._sub(target)["cache_hits"]) + 1
            self._checkpoint_unlocked(reason="cache_hit")

    def record_route(self, route: str) -> None:
        """记录实际执行路由分布（stub / small / large / injected …），看板第三列。"""
        with self._lock:
            self._route_distribution[str(route)] = int(self._route_distribution.get(str(route), 0)) + 1
            self._checkpoint_unlocked(reason="route")

    def mark_degraded(self, stage: str, reason: str) -> None:
        """环节因预算耗尽降级 stub。

        功能需求直抽（核心交付物）降级时强制 ``document_needs_work=True``——文档级 NEEDS
        WORK 标记，不允许仅 provenance 标注静默通过（方案 §5.1 第 14 周）。
        """
        with self._lock:
            self._degraded[str(stage)] = str(reason)
            if str(stage) == STAGE_FUNCTIONAL_EXTRACT:
                self.document_needs_work = True
            self._checkpoint_unlocked(reason="degraded")

    # ------------------------------------------------------------------
    # 阈值评估（80% 预警 / 100% 耗尽，checkpoint 时点）
    # ------------------------------------------------------------------

    def _mark_exhausted_unlocked(self, stage: str, reason: str) -> None:
        self._exhausted[str(stage)] = str(reason)
        self.document_needs_work = True

    def _evaluate_thresholds_unlocked(self) -> None:
        for stage, sub in self._consumed.items():
            budget = self.sub_budgets.get(stage)
            if not budget:
                continue
            for metric, spent, limit in (
                ("calls", int(sub["calls"]), int(budget["max_calls"])),
                ("tokens", int(sub["tokens"]) + int(sub["reserved_tokens"]), int(budget["max_tokens"])),
            ):
                if limit <= 0:
                    continue
                ratio = spent / limit
                if ratio >= EXHAUSTED_THRESHOLD and stage not in self._exhausted:
                    self._mark_exhausted_unlocked(stage, f"{metric}_budget_exhausted")
                elif ratio >= self.warn_threshold:
                    key = f"{stage}:{metric}:warn"
                    if not any(w.get("key") == key for w in self._warnings):
                        self._warnings.append({
                            "key": key,
                            "stage": stage,
                            "metric": metric,
                            "spent": spent,
                            "limit": limit,
                            "ratio": round(ratio, 4),
                            "level": "warn",
                            "at": _utc_now(),
                        })

    # ------------------------------------------------------------------
    # 落盘续算（跨进程锁 + 原子替换 + 幂等键指纹）
    # ------------------------------------------------------------------

    def _checkpoint_unlocked(self, *, reason: str) -> None:
        self.last_event_seq += 1
        self.updated_at = _utc_now()
        self._evaluate_thresholds_unlocked()
        if self.out_dir is not None:
            self._write_unlocked(reason)

    def snapshot(self) -> dict[str, Any]:
        """完整可序列化状态（成本看板数据源 + 落盘载体）。"""
        with self._lock:
            consumed_view: dict[str, dict[str, Any]] = {}
            for stage, sub in self._consumed.items():
                budget = self.sub_budgets.get(stage, {"max_calls": 0, "max_tokens": 0})
                consumed_view[stage] = {
                    "calls": int(sub["calls"]),
                    "tokens": int(sub["tokens"]),
                    "reserved_tokens": int(sub["reserved_tokens"]),
                    "failed_calls": int(sub["failed_calls"]),
                    "cache_hits": int(sub["cache_hits"]),
                    "usage_complete": bool(sub["usage_complete"]),
                    "max_calls": int(budget["max_calls"]),
                    "max_tokens": int(budget["max_tokens"]),
                }
            payload = {
                "schema": LLM_BUDGET_SCHEMA,
                "version": LLM_BUDGET_VERSION,
                "document_id": self.document_id,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "warn_threshold": self.warn_threshold,
                "stage_routes": dict(self.stage_routes),
                "sub_budgets": {
                    stage: dict(budget) for stage, budget in self.sub_budgets.items()
                },
                "consumed": consumed_view,
                "route_distribution": dict(self._route_distribution),
                "warnings": list(self._warnings),
                "exhausted_stages": dict(self._exhausted),
                "degraded_stages": dict(self._degraded),
                "document_needs_work": bool(self.document_needs_work),
                "last_event_seq": int(self.last_event_seq),
            }
            payload["idempotency_key"] = _snapshot_idempotency_key(payload)
            return payload

    def _write_unlocked(self, reason: str) -> None:
        from result_package import governed_artifact_path

        assert self.out_dir is not None
        target = governed_artifact_path(
            self.out_dir, LLM_BUDGET_FILENAME, category="state", for_write=True
        )
        lock_path = governed_artifact_path(
            self.out_dir, LLM_BUDGET_LOCK, category="state", for_write=True
        )
        payload = self.snapshot()
        tmp: Path | None = None
        try:
            from process_file_lock import process_file_lock

            with process_file_lock(lock_path, timeout_s=10.0, label="llm_budget"):
                with tempfile.NamedTemporaryFile(
                    mode="w", dir=target.parent, prefix=".llm_budget.",
                    suffix=".tmp", delete=False, encoding="utf-8", newline="\n",
                ) as handle:
                    tmp = Path(handle.name)
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                _replace_with_retry(tmp, target)
                tmp = None
        except Exception as exc:  # 预算单落盘失败不阻断主流程，只记日志（同 functional_extract 缓存纪律）
            LOGGER.warning("llm_budget 落盘失败（%s）：%s", reason, exc)
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

    def save(self, out_dir: Path | str | None = None) -> dict[str, Any]:
        """显式落盘并返回 snapshot。"""
        target_dir = Path(out_dir).expanduser().resolve() if out_dir else self.out_dir
        if target_dir is None:
            raise ValueError("out_dir required to save budget ledger")
        with self._lock:
            prev_dir = self.out_dir
            self.out_dir = target_dir
            try:
                self._write_unlocked(reason="save")
            finally:
                # 若调用方临时指定 out_dir，落盘后不改变实例默认目录。
                if out_dir is not None and prev_dir is not None:
                    self.out_dir = prev_dir
            return self.snapshot()

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> "LLMBudgetLedger":
        """从落盘 snapshot 续算（已 checkpoint 的累计消耗原样恢复，不二次累加）。"""
        if not isinstance(data, dict):
            raise ValueError("budget snapshot must be a JSON object")
        if data.get("schema") != LLM_BUDGET_SCHEMA:
            raise ValueError(f"unsupported budget schema: {data.get('schema')!r}")
        if data.get("version") != LLM_BUDGET_VERSION:
            raise ValueError(f"unsupported budget version: {data.get('version')!r}")
        document_id = str(data.get("document_id") or "")
        if not document_id:
            raise ValueError("budget snapshot missing document_id")

        sub_budgets: dict[str, dict[str, int]] = {}
        consumed: dict[str, dict[str, int | bool]] = {}
        raw_consumed = data.get("consumed") or {}
        raw_subs = data.get("sub_budgets") or {}
        stages = list(dict.fromkeys([*raw_consumed.keys(), *raw_subs.keys()]))
        for stage in stages:
            sub_info = raw_consumed.get(stage) or {}
            budget = raw_subs.get(stage) or {}
            sub_budgets[stage] = {
                "max_calls": int(sub_info.get("max_calls") or budget.get("max_calls") or 0),
                "max_tokens": int(sub_info.get("max_tokens") or budget.get("max_tokens") or 0),
            }
            consumed[stage] = {
                "calls": int(sub_info.get("calls") or 0),
                "tokens": int(sub_info.get("tokens") or 0),
                "reserved_tokens": int(sub_info.get("reserved_tokens") or 0),
                "failed_calls": int(sub_info.get("failed_calls") or 0),
                "cache_hits": int(sub_info.get("cache_hits") or 0),
                "usage_complete": bool(sub_info.get("usage_complete", True)),
            }
        if not sub_budgets:
            sub_budgets = _default_sub_budgets(None, None)

        ledger = cls(
            document_id,
            sub_budgets,
            stage_routes=data.get("stage_routes") or dict(DEFAULT_STAGE_ROUTES),
            warn_threshold=float(data.get("warn_threshold") or WARN_THRESHOLD),
        )
        ledger._consumed = consumed
        ledger._route_distribution = dict(data.get("route_distribution") or {})
        ledger._warnings = list(data.get("warnings") or [])
        ledger._exhausted = dict(data.get("exhausted_stages") or {})
        ledger._degraded = dict(data.get("degraded_stages") or {})
        ledger.document_needs_work = bool(data.get("document_needs_work"))
        ledger.created_at = str(data.get("created_at") or ledger.created_at)
        ledger.updated_at = str(data.get("updated_at") or ledger.created_at)
        ledger.last_event_seq = int(data.get("last_event_seq") or 0)
        return ledger

    @classmethod
    def load(cls, out_dir: Path | str) -> "LLMBudgetLedger | None":
        """从 governed state 路径加载预算单（缺失返回 None）。"""
        from result_package import governed_artifact_path

        path = governed_artifact_path(out_dir, LLM_BUDGET_FILENAME, category="state", for_write=False)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"corrupt budget ledger at {path}: {exc}") from exc
        ledger = cls.from_snapshot(data)
        ledger.out_dir = Path(out_dir).expanduser().resolve()
        return ledger

    # ------------------------------------------------------------------
    # 挂载 / 卸载 llm_client 钩子
    # ------------------------------------------------------------------

    def attach(self) -> None:
        """把本预算单挂到 ``llm_client`` 模块级文档预算钩子（此后所有 HTTP 调用扣减）。"""
        import llm_client

        llm_client.set_document_budget_hook(self)

    def detach(self) -> None:
        """卸载钩子（``llm_client`` 回到无预算拦截的旧行为）。"""
        import llm_client

        llm_client.clear_document_budget_hook()


class _StageScope:
    """``with ledger.enter_stage(stage):`` 的 ContextVar 还原 scope。"""

    def __init__(self, stage: str) -> None:
        self._stage = stage
        self._token = None

    def __enter__(self) -> "_StageScope":
        self._token = _ACTIVE_STAGE.set(self._stage)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._token is not None:
            _ACTIVE_STAGE.reset(self._token)


# ---------------------------------------------------------------------------
# 模块级辅助
# ---------------------------------------------------------------------------

def _budget_exceeded(message: str) -> "LLMBudgetExceeded":
    from llm_client import LLMBudgetExceeded

    return LLMBudgetExceeded(message)


def _snapshot_idempotency_key(payload: dict[str, Any]) -> str:
    """落盘 snapshot 的防重放指纹。

    与 ``claim_artifacts.hash_json`` 同算法（``sha256(canonical {domain, payload})``），
    与 ``claim_queue_execution`` 的 budget checkpoint event 幂等键同源——进程重启后 ``load``
    续算时校验：同一 (document_id, consumed 状态, seq) 的 snapshot 指纹不变，已 checkpoint
    的累计消耗不重置、不二次累加（幂等键只防重复扣费 / 防重放，不防单次大调用击穿余量——
    后者由 ``intercept`` 的事前拦截负责）。
    """
    from claim_artifacts import hash_json

    digest_payload = {
        "document_id": payload.get("document_id"),
        "consumed": payload.get("consumed"),
        "route_distribution": payload.get("route_distribution"),
        "last_event_seq": payload.get("last_event_seq"),
    }
    return hash_json("llm-budget-snapshot/v1", digest_payload)


def _replace_with_retry(source: Path, target: Path) -> None:
    """Windows reader 阻塞 ``os.replace`` 的重试（同 functional_extract / review_state 纪律）。"""
    for attempt in range(8):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= 8:
                raise
            import time

            time.sleep(0.02 * (attempt + 1))


# ---------------------------------------------------------------------------
# 成本看板视图（数据全部来自预算单记账流水，无新增埋点）
# ---------------------------------------------------------------------------

def cost_report(ledger: LLMBudgetLedger) -> dict[str, Any]:
    """三列指标：分环节累计调用数 / token 占比、缓存命中率、路由分布（方案 §5.1 第 16 周）。

    数据源全部来自 ``ledger.snapshot()`` 的记账流水——无新增埋点。
    """
    snap = ledger.snapshot()
    stages: list[dict[str, Any]] = []
    total_paid_calls = 0
    total_cache_hits = 0
    for stage, sub in (snap.get("consumed") or {}).items():
        max_calls = int(sub.get("max_calls") or 0)
        max_tokens = int(sub.get("max_tokens") or 0)
        calls = int(sub.get("calls") or 0)
        cache_hits = int(sub.get("cache_hits") or 0)
        tokens = int(sub.get("tokens") or 0)
        total_paid_calls += calls
        total_cache_hits += cache_hits
        stages.append({
            "stage": stage,
            "calls": calls,
            "calls_ratio": round(calls / max_calls, 4) if max_calls else 0.0,
            "tokens": tokens,
            "tokens_ratio": round(tokens / max_tokens, 4) if max_tokens else 0.0,
            "cache_hits": cache_hits,
            "failed_calls": int(sub.get("failed_calls") or 0),
            "usage_complete": bool(sub.get("usage_complete", True)),
            "exhausted": stage in (snap.get("exhausted_stages") or {}),
            "route": (snap.get("stage_routes") or {}).get(stage),
        })
    accounting_total = total_paid_calls + total_cache_hits
    return {
        "schema": "llm-budget-cost-report/v1",
        "document_id": snap.get("document_id"),
        "version": LLM_BUDGET_VERSION,
        "stages": stages,
        "cache_hit_rate": round(total_cache_hits / accounting_total, 4) if accounting_total else 0.0,
        "route_distribution": dict(snap.get("route_distribution") or {}),
        "warnings": list(snap.get("warnings") or []),
        "exhausted_stages": dict(snap.get("exhausted_stages") or {}),
        "degraded_stages": dict(snap.get("degraded_stages") or {}),
        "document_needs_work": bool(snap.get("document_needs_work")),
        "warn_threshold": snap.get("warn_threshold"),
    }
