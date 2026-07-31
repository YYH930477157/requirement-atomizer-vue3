from __future__ import annotations

import json
import logging
import os
import threading
import time
import http.client
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("requirement_atomizer")

# 429 限流的独立重试预算下限（与普通 max_retries 解耦）：退避 2,4,8,16,32,32… 秒，
# 8 次 ≈ 两分钟耐心——限流风暴通常几十秒内过去，比丢整章便宜得多
# 按用途的 max_tokens 下限（F4 收口：此前散在 3 个模块各写一遍，第 4 个环节必再忘一次）。
# 推理模型思维链会挤占输出预算，低于下限 → JSON 截断 → 整环节失败。
PURPOSE_MIN_TOKENS = {
    "extract": 6144,          # 逐条款抽取
    "extract-chapter": 16384,  # 整章模式（实验）：几十条需求的输出
    "analyze": 8192,          # 软件需求富化（v5 连贯多段正文+更长注入上下文,6144 实测偏紧）
    "enrich": 6144,           # 装配描述富化（蓝皮书）
}


def apply_min_tokens(config, purpose: str):
    """按用途抬高 config.max_tokens 到下限（不降低用户显式设置的更高值）。"""
    from dataclasses import replace
    floor = PURPOSE_MIN_TOKENS.get(purpose, 0)
    if floor and config.max_tokens < floor:
        return replace(config, max_tokens=floor)
    return config


RATE_LIMIT_MIN_ATTEMPTS = 8
LLM_ATTEMPT_POLICY_VERSION = "llm-attempt-policy-v1"

# 截断自动升级上限（test3 实证：3.22 章推理模型 reasoning 吃光 6144 预算 → 空响应 →
# JSON 修复调用同样被截 → 整章稳定失败）。finish_reason=length 或空 content 时 max_tokens
# 倍升重试,封顶 32768（6144→12288→24576→32768 最多 3 次升级）——比丢整章便宜得多。
MAX_TOKENS_ESCALATION_CAP = 32768

# --- 429 自适应闸门（0714 批次一 S2）--------------------------------------------
# 真实数据（EN 16314 全量跑）：并发 4 时抽取轨 781 次调用有 164 次 429——各线程各自
# 退避重试、其余线程照常轰端点，有效并发只剩 3.2；并发调 8 只会加剧限流。闸门跨线程
# 共享（按 base_url 一门）：任一线程命中 429 → ①全局冷却（其它线程的**新**请求等冷却期
# 过后再发,不是各睡各的）②在飞上限砍半（AIMD：连续成功缓慢 +1 恢复,封顶 32）。
# 默认开；RATOMIZER_LLM_ADAPTIVE=0 关闭（行为回到各线程独立退避）。
ADAPTIVE_ENV = "RATOMIZER_LLM_ADAPTIVE"
GATE_CEILING = 32
GATE_RECOVERY_SUCCESSES = 8   # 连续成功 N 次,在飞上限 +1


class _AdaptiveRateGate:
    def __init__(self, ceiling: int = GATE_CEILING, now_fn=time.monotonic):
        self._cv = threading.Condition()
        self._now = now_fn
        self._ceiling = ceiling
        self._limit: int | None = None   # None=尚未限流,不设上限（由各阶段线程池自然限定）
        self._active = 0
        self._successes = 0
        self._pause_until = 0.0

    def acquire(self) -> None:
        with self._cv:
            while True:
                wait = self._pause_until - self._now()
                if wait > 0:
                    self._cv.wait(min(wait, 1.0))
                    continue
                if self._limit is None or self._active < self._limit:
                    self._active += 1
                    return
                self._cv.wait(1.0)

    def release(self) -> None:
        with self._cv:
            self._active = max(0, self._active - 1)
            self._cv.notify_all()

    def on_rate_limited(self, delay: float) -> None:
        with self._cv:
            base = self._active if self._limit is None else self._limit
            self._limit = max(1, min(base, self._ceiling) // 2)
            self._successes = 0
            self._pause_until = max(self._pause_until, self._now() + max(0.0, delay))
            self._cv.notify_all()

    def on_success(self) -> None:
        with self._cv:
            if self._limit is None:
                return
            self._successes += 1
            if self._successes >= GATE_RECOVERY_SUCCESSES:
                self._successes = 0
                if self._limit < self._ceiling:
                    self._limit += 1
                    self._cv.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._cv:
            return {"limit": self._limit, "active": self._active, "pause_until": self._pause_until}


_GATES: dict[str, _AdaptiveRateGate] = {}
_GATES_LOCK = threading.Lock()


def _adaptive_enabled() -> bool:
    return os.environ.get(ADAPTIVE_ENV, "").strip().lower() not in ("0", "false", "no", "off")


def llm_attempt_policy() -> dict[str, Any]:
    """Return the key-free effective policy that can change provider attempts."""
    return {
        "version": LLM_ATTEMPT_POLICY_VERSION,
        "adaptive_enabled": _adaptive_enabled(),
        "rate_limit_min_attempts": RATE_LIMIT_MIN_ATTEMPTS,
        "gate_ceiling": GATE_CEILING,
        "gate_recovery_successes": GATE_RECOVERY_SUCCESSES,
        "max_tokens_escalation_cap": MAX_TOKENS_ESCALATION_CAP,
    }


def _gate_for(base_url: str) -> _AdaptiveRateGate:
    key = str(base_url or "").rstrip("/")
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = _AdaptiveRateGate()
            _GATES[key] = gate
        return gate


def _reset_rate_gates() -> None:
    """仅测试用：清空按端点的闸门单例。"""
    with _GATES_LOCK:
        _GATES.clear()

# LLM 消息级追踪：set_trace_path() 启用后，每次 HTTP 调用（含 JSON 修复回路）在
# llm_trace.jsonl 追加一行完整收发——messages 原文 + 响应全文（含 usage token 用量、
# 推理模型的 reasoning_content）。排查"为什么被拒/为什么 0 条/为什么慢"看这里。
# 写入线程安全（并发富化/抽取共用），失败绝不影响调用本身。
_TRACE_PATH: Path | None = None
_TRACE_LOCK = threading.Lock()


def set_trace_path(path: Path | None) -> None:
    global _TRACE_PATH
    _TRACE_PATH = Path(path) if path is not None else None


def _write_trace(record: dict[str, Any]) -> None:
    if _TRACE_PATH is None:
        return
    try:
        line = json.dumps(record, ensure_ascii=False)
        with _TRACE_LOCK:
            with _TRACE_PATH.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
    except Exception:  # pragma: no cover - 追踪写失败不影响任务
        pass


# llm_trace.jsonl 默认开启、写入客户文档全文（排查必需），但大段专有标准正文落盘是数据外发面。
# 截断长文本字段：messages[].content / response.choices[].message.content 各保留上限字符，
# usage / model / 错误码等结构化字段不动（排查"0 条/慢/被拒"看这些就够）。可通过
# RATOMIZER_LLM_TRACE_FULL=1 关闭截断（完整落盘，仅离线调试用）。
_TRACE_TEXT_CAP = 2000


def _truncate_for_trace(value: Any) -> Any:
    if os.environ.get("RATOMIZER_LLM_TRACE_FULL"):
        return value
    if isinstance(value, str):
        return value if len(value) <= _TRACE_TEXT_CAP else value[:_TRACE_TEXT_CAP] + f"…<truncated {len(value) - _TRACE_TEXT_CAP} chars>"
    if isinstance(value, list):
        return [_truncate_for_trace(v) for v in value]
    if isinstance(value, dict):
        return {key: _truncate_for_trace(item) for key, item in value.items()}
    return value


class LLMError(Exception):
    """Base exception for OpenAI-compatible LLM calls."""


class LLMConnectionError(LLMError):
    """Raised when the LLM service cannot be reached or stays unavailable."""


class LLMResponseError(LLMError):
    """Raised when the LLM response cannot be used as a review payload."""


class LLMResponseFormatUnsupported(LLMResponseError):
    """Raised only when an endpoint explicitly rejects response_format=json_object."""


class LLMBudgetExceeded(LLMError):
    """Raised before an HTTP request that would exceed a shared hard budget."""


def _normalized_usage(usage: object) -> dict[str, int] | None:
    """Return trustworthy token counts for one successful provider response."""
    if not isinstance(usage, dict):
        return None

    def count(name: str) -> int | None:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    total = count("total_tokens")
    prompt = count("prompt_tokens")
    completion = count("completion_tokens")
    if "total_tokens" in usage:
        if total is None or total <= 0:
            return None
        if "prompt_tokens" in usage and prompt is None:
            return None
        if "completion_tokens" in usage and completion is None:
            return None
        if prompt is not None and prompt > total:
            return None
        if completion is not None and completion > total:
            return None
        if prompt is not None and completion is not None and prompt + completion != total:
            return None
        return {
            "prompt_tokens": prompt or 0,
            "completion_tokens": completion or 0,
            "total_tokens": total,
        }
    if prompt is None or completion is None or prompt + completion <= 0:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


class LLMRequestBudget:
    """Thread-safe hard budget covering every underlying HTTP attempt."""

    VERSION = "llm-request-budget-v1"

    def __init__(self, *, max_calls: int, max_tokens: int) -> None:
        if isinstance(max_calls, bool) or int(max_calls) <= 0:
            raise ValueError("max_calls must be a positive integer")
        if isinstance(max_tokens, bool) or int(max_tokens) <= 0:
            raise ValueError("max_tokens must be a positive integer")
        self.max_calls = int(max_calls)
        self.max_tokens = int(max_tokens)
        self._lock = threading.RLock()
        self._checkpoint_lock = threading.RLock()
        self._next_id = 0
        self._reservations: dict[int, int] = {}
        self._attempted_calls = 0
        self._failed_calls = 0
        self._tokens = 0
        self._usage_complete = True
        self._denied = False
        self._termination_reason = ""
        self._checkpoint: Callable[[dict[str, Any]], None] | None = None

    @classmethod
    def from_settled_snapshot(
        cls,
        snapshot: dict[str, Any],
    ) -> "LLMRequestBudget":
        """Restore cumulative accounting after a durable settled checkpoint.

        A reservation means the provider outcome may be unknown. Such a state
        must be reconciled or explicitly reconfirmed by the caller; silently
        turning it into a new request would make the hard budget restart.
        """
        if not isinstance(snapshot, dict) or snapshot.get("version") != cls.VERSION:
            raise ValueError("invalid LLM request budget checkpoint")

        def count(name: str, *, positive: bool = False) -> int:
            value = snapshot.get(name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"invalid LLM request budget {name}")
            if value < (1 if positive else 0):
                raise ValueError(f"invalid LLM request budget {name}")
            return value

        max_calls = count("max_calls", positive=True)
        max_tokens = count("max_tokens", positive=True)
        attempted_calls = count("attempted_calls")
        failed_calls = count("failed_calls")
        tokens = count("tokens")
        reserved_tokens = count("reserved_tokens")
        if reserved_tokens:
            raise ValueError("cannot restore an unsettled LLM budget reservation")
        if attempted_calls > max_calls or failed_calls > attempted_calls:
            raise ValueError("invalid cumulative LLM request budget checkpoint")
        if not isinstance(snapshot.get("usage_complete"), bool):
            raise ValueError("invalid LLM request budget usage completeness")
        if not isinstance(snapshot.get("denied"), bool):
            raise ValueError("invalid LLM request budget denied state")
        termination_reason = snapshot.get("termination_reason")
        if not isinstance(termination_reason, str):
            raise ValueError("invalid LLM request budget termination reason")

        budget = cls(max_calls=max_calls, max_tokens=max_tokens)
        with budget._lock:
            budget._next_id = attempted_calls
            budget._attempted_calls = attempted_calls
            budget._failed_calls = failed_calls
            budget._tokens = tokens
            budget._usage_complete = bool(snapshot["usage_complete"])
            budget._denied = bool(snapshot["denied"])
            budget._termination_reason = termination_reason
        return budget

    def _snapshot_unlocked(self) -> dict[str, Any]:
        reserved = sum(self._reservations.values())
        return {
            "version": self.VERSION,
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "attempted_calls": self._attempted_calls,
            "failed_calls": self._failed_calls,
            "tokens": self._tokens,
            "reserved_tokens": reserved,
            "remaining_calls": max(0, self.max_calls - self._attempted_calls),
            "remaining_tokens": max(0, self.max_tokens - self._tokens - reserved),
            "usage_complete": self._usage_complete,
            "denied": self._denied,
            "termination_reason": self._termination_reason,
        }

    def set_checkpoint(
        self,
        checkpoint: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        """Synchronously persist budget mutations before an HTTP attempt proceeds."""
        with self._checkpoint_lock:
            with self._lock:
                if checkpoint is not None and self._checkpoint is not None:
                    raise RuntimeError("LLM request budget already has a checkpoint")
                previous = self._checkpoint
                self._checkpoint = checkpoint
                snapshot = self._snapshot_unlocked()
            try:
                if checkpoint is not None:
                    checkpoint(snapshot)
            except BaseException:
                with self._lock:
                    self._checkpoint = previous
                raise

    @staticmethod
    def _token_ceiling(payload: dict[str, Any]) -> int:
        # UTF-8 bytes are a conservative upper bound for input tokens.  Add the
        # provider's maximum completion allowance and a small envelope margin.
        # Keep serialization identical to _post_json; escaped CJK and default
        # separators are larger than the compact ensure_ascii=False form.
        body_bytes = len(serialize_json_request_body(payload))
        return body_bytes + max(0, int(payload.get("max_tokens") or 0)) + 256

    def reserve(self, payload: dict[str, Any]) -> int:
        ceiling = self._token_ceiling(payload)
        with self._checkpoint_lock:
            with self._lock:
                reserved = sum(self._reservations.values())
                if self._attempted_calls >= self.max_calls:
                    self._denied = True
                    self._termination_reason = "call_budget_exhausted"
                    raise LLMBudgetExceeded("LLM request call budget exhausted")
                if self._tokens + reserved + ceiling > self.max_tokens:
                    self._denied = True
                    self._termination_reason = "token_budget_exhausted"
                    raise LLMBudgetExceeded("LLM request token budget exhausted")
                self._next_id += 1
                reservation_id = self._next_id
                self._reservations[reservation_id] = ceiling
                self._attempted_calls += 1
                checkpoint = self._checkpoint
                snapshot = self._snapshot_unlocked()
            try:
                if checkpoint is not None:
                    checkpoint(snapshot)
            except BaseException:
                # Persistence failed before the caller could issue the HTTP request.
                with self._lock:
                    if self._reservations.pop(reservation_id, None) is not None:
                        self._attempted_calls -= 1
                raise
        return reservation_id

    @staticmethod
    def _usage_total(usage: object) -> int | None:
        normalized = _normalized_usage(usage)
        return normalized["total_tokens"] if normalized is not None else None

    def commit(self, reservation_id: int, usage: object) -> None:
        with self._checkpoint_lock:
            with self._lock:
                ceiling = self._reservations.pop(reservation_id)
                total = self._usage_total(usage)
                if total is None:
                    self._tokens += ceiling
                    self._usage_complete = False
                else:
                    self._tokens += total
                if self._tokens > self.max_tokens:
                    self._denied = True
                    self._termination_reason = "reported_token_budget_exceeded"
                checkpoint = self._checkpoint
                snapshot = self._snapshot_unlocked()
            if checkpoint is not None:
                checkpoint(snapshot)

    def fail(self, reservation_id: int) -> None:
        with self._checkpoint_lock:
            with self._lock:
                ceiling = self._reservations.pop(reservation_id, None)
                if ceiling is None:
                    return
                # Failed responses do not carry trustworthy usage.  Charge the
                # reservation so the hard financial ceiling remains conservative.
                self._tokens += ceiling
                self._failed_calls += 1
                self._usage_complete = False
                checkpoint = self._checkpoint
                snapshot = self._snapshot_unlocked()
            if checkpoint is not None:
                checkpoint(snapshot)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()


@dataclass(frozen=True)
class LLMClientConfig:
    base_url: str
    model: str
    api_key_env: str = "RATOMIZER_LLM_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_s: float = 60.0
    max_retries: int = 3


def build_chat_json_request_payload(
    config: LLMClientConfig,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int | None = None,
    json_mode: bool,
) -> dict[str, Any]:
    """Build the exact payload shape sent by the JSON chat path."""
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": int(config.max_tokens if max_tokens is None else max_tokens),
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def serialize_json_request_body(payload: dict[str, Any]) -> bytes:
    """Serialize exactly as the HTTP transport and request budget do."""
    return json.dumps(payload).encode("utf-8")


def chat_json(
    config: LLMClientConfig,
    system_prompt: str,
    user_prompt: str,
    _usage_sink: list[dict[str, Any]] | None = None,
    _request_budget: LLMRequestBudget | None = None,
    _request_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return chat_json_messages(
        config,
        messages,
        _usage_sink=_usage_sink,
        _request_budget=_request_budget,
        _request_stats=_request_stats,
    )


def chat_json_with_meta(
    config: LLMClientConfig,
    system_prompt: str,
    user_prompt: str,
    *,
    request_budget: LLMRequestBudget | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """chat_json + 全底层调用（首发/修复/截断升级重发）聚合的 token 用量。

    返回 (data, meta)。meta = {"usage": {prompt_tokens, completion_tokens, total_tokens},
    "usage_complete": bool}——端点未返回 usage 的调用计 0 且 usage_complete=False
    （不得估算冒充精确值,见 Phase 1.5 tokens 口径）。"""
    usage_sink: list[dict[str, Any]] = []
    request_stats = {"call_count": 0, "failed_call_count": 0}
    data = chat_json(
        config,
        system_prompt,
        user_prompt,
        _usage_sink=usage_sink,
        _request_budget=request_budget,
        _request_stats=request_stats,
    )
    aggregate = _aggregate_usage(usage_sink)
    if request_stats["failed_call_count"]:
        aggregate["usage_complete"] = False
    return data, {**aggregate, **request_stats}


def chat_json_messages(
    config: LLMClientConfig,
    messages: list[dict[str, str]],
    _usage_sink: list[dict[str, Any]] | None = None,
    _request_budget: LLMRequestBudget | None = None,
    _request_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    content = _chat_content(
        config,
        messages,
        _usage_sink=_usage_sink,
        _request_budget=_request_budget,
        _request_stats=_request_stats,
    )
    try:
        return _loads_json_content(content)
    except (json.JSONDecodeError, LLMResponseError) as first_error:
        repair_messages = [
            *messages,
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "Only output valid JSON. Do not include Markdown fences, prose, or comments. "
                    f"Repair the previous response. JSON parser error: {first_error}"
                ),
            },
        ]
        repaired_content = _chat_content(
            config,
            repair_messages,
            _usage_sink=_usage_sink,
            _request_budget=_request_budget,
            _request_stats=_request_stats,
        )
        try:
            return _loads_json_content(repaired_content)
        except json.JSONDecodeError as second_error:
            raise LLMResponseError(f"LLM response is not valid JSON after repair: {second_error}") from second_error
        except LLMResponseError as second_error:
            raise LLMResponseError(f"LLM response is not a JSON object after repair: {second_error}") from second_error


# --- Agent Phase 2 WP1-A：OpenAI 兼容 tools 调用与有界 tool-loop -----------------------
# 审查器从"单次 prompt"升级为有边界的工具调用：模型在审查单条需求时可请求确定性只读
# 工具（review_tools.py），工具结果以 role=tool 消息回灌，模型再续审。证据仍由确定性
# 层供给——本函数只搬运消息，绝不替模型/工具生成任何内容。

# tool-loop 默认轮顶（含首轮；模型连续请求工具则每轮 +1）。超过轮顶抛 LLMResponseError，
# 调用方按现有失败路径处理（该需求进 stub 审查并记数，不得伪造模型已审）。
TOOL_LOOP_DEFAULT_MAX_ROUNDS = 8


def chat_with_tools(
    config: LLMClientConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    max_rounds: int = TOOL_LOOP_DEFAULT_MAX_ROUNDS,
    on_tool_call: Callable[[str, dict[str, Any]], dict[str, Any]],
    token_budget: int | None = None,
    _usage_sink: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """OpenAI 兼容 tools 有界 tool-loop：返回 (final_dict, meta)。

    循环：发请求 → 响应含 tool_calls 则逐个经 on_tool_call(tool_name, arguments) 执行、
    结果以 role=tool 回灌 → 下一轮；无 tool_calls 则按 chat_json 同口径解析最终 JSON
    （解析失败修复重发一次，占一轮）。硬顶 max_rounds（默认 8，含首轮）；轮顶耗尽抛
    LLMResponseError。非法 tool_call（结构畸形/未知工具/参数非法/执行异常）以
    {"error": ...} 回灌一次让其纠正；同一工具同一轮连续错 2 次视为轮顶耗尽同等处理。
    端点不支持 tools（4xx）响亮报错，不静默降级为无工具审查。token_budget（tokens 上限）
    按全部轮次 usage 累计，超限即抛 LLMResponseError；usage 缺失计 0（无法计量即无法
    超限），meta.usage_complete 标 partial。

    meta = {"usage": {...}, "usage_complete": bool, "tool_calls": [{"round","name"}...],
    "rounds": n, "history": [...]}——tool_calls 摘要是审查结果行的审计锚（产出过程
    可解释性）；history 为收敛时的完整 transcript（含 assistant tool_calls 与 role=tool
    回灌，不含最终 assistant JSON 消息），供调用方续接（如 schema 修复轮）。"""
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")
    usage_sink = _usage_sink if _usage_sink is not None else []
    history = [dict(message) for message in messages]
    tool_call_summary: list[dict[str, Any]] = []
    round_no = 0
    while True:
        round_no += 1
        if round_no > max_rounds:
            raise LLMResponseError(
                f"tool loop did not converge within max_rounds={max_rounds} "
                f"(model kept requesting tools or never returned final JSON)")
        response = _chat_tools_once(config, history, tools, usage_sink)
        if token_budget is not None:
            spent = _aggregate_usage(usage_sink)["usage"]["total_tokens"]
            if spent > token_budget:
                raise LLMResponseError(
                    f"tool loop token budget exceeded: {spent} > {token_budget} tokens "
                    f"(round {round_no})")
        try:
            choice = response["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM response missing choices[0].message") from exc
        if not isinstance(message, dict):
            raise LLMResponseError("LLM response message must be an object")
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            content = message.get("content")
            if not isinstance(content, str):
                raise LLMResponseError("LLM response content must be a string")
            try:
                final = _loads_json_content(content)
            except (json.JSONDecodeError, LLMResponseError) as first_error:
                if round_no >= max_rounds:
                    raise LLMResponseError(
                        f"tool loop final response is not valid JSON and max_rounds={max_rounds} "
                        f"is exhausted: {first_error}") from first_error
                # 与 chat_json 同口径：修复重发一次（占一轮）；模型修复轮改调工具也自然成环
                history = [
                    *history,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "Only output valid JSON. Do not include Markdown fences, prose, or comments. "
                            f"Repair the previous response. JSON parser error: {first_error}"
                        ),
                    },
                ]
                continue
            return final, {
                **_aggregate_usage(usage_sink),
                "tool_calls": tool_call_summary,
                "rounds": round_no,
                "history": list(history),
            }
        # 工具轮：assistant 消息原样回灌（含 tool_calls，tool_call_id 需逐字对应）
        history.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
        error_streak: dict[str, int] = {}
        for call in tool_calls:
            name, arguments, parse_error = _parse_tool_call(call)
            if parse_error is not None:
                result = {"error": parse_error}
            else:
                try:
                    result = on_tool_call(name, arguments)
                except Exception as exc:  # 工具执行异常 → error 回灌一次（provenance 如实）
                    result = {"error": f"tool {name} raised: {exc}"}
                if not isinstance(result, dict):
                    result = {"error": f"tool {name} returned a non-object result"}
            tool_call_summary.append({"round": round_no, "name": name or "<malformed>"})
            if "error" in result:
                error_streak[name] = error_streak.get(name, 0) + 1
                if error_streak[name] >= 2:
                    raise LLMResponseError(
                        f"tool {name} failed twice in a row within round {round_no} "
                        f"(invalid tool_call correction exhausted): {result['error']}")
            else:
                error_streak[name] = 0
            history.append({
                "role": "tool",
                "tool_call_id": str(call.get("id") or "") if isinstance(call, dict) else "",
                "content": json.dumps(result, ensure_ascii=False),
            })


def _parse_tool_call(call: Any) -> tuple[str, dict[str, Any], str | None]:
    """解析 OpenAI tool_call 结构 → (name, arguments, error)；error 非空则前两者无效。"""
    if not isinstance(call, dict):
        return "<malformed>", {}, "malformed tool_call: not an object"
    function = call.get("function")
    if not isinstance(function, dict):
        return "<malformed>", {}, "malformed tool_call: missing function object"
    name = str(function.get("name") or "").strip()
    if not name:
        return "<malformed>", {}, "malformed tool_call: empty function name"
    raw_arguments = function.get("arguments", "")
    if isinstance(raw_arguments, dict):
        return name, raw_arguments, None
    try:
        arguments = json.loads(str(raw_arguments or "{}"))
    except json.JSONDecodeError as exc:
        return name, {}, f"invalid tool arguments JSON for {name}: {exc}"
    if not isinstance(arguments, dict):
        return name, {}, f"tool arguments for {name} must be a JSON object"
    return name, arguments, None


def _chat_tools_once(
    config: LLMClientConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    _usage_sink: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """一轮 tools 请求（含截断/空响应的 max_tokens 升级重试，口径同 _chat_content）。

    不带 response_format——json_object 模式与 tool_calls 在多数端点互斥。空 content +
    无 tool_calls 才视为空响应（模型调工具时 content 常为 null，那是正常工具轮）。"""
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "tools": tools,
    }
    max_tokens = int(config.max_tokens)
    while True:
        payload["max_tokens"] = max_tokens
        try:
            response = _post_json(config, payload)
        except LLMResponseError as exc:
            # 端点 4xx（tools 不支持）响亮报错并点名 tools 语境——绝不静默降级为无工具重发
            # （provenance：无工具审查不得冒充 tool-using 审查）。其余响应错误原样抛出。
            if str(exc).startswith("LLM service returned HTTP 4"):
                raise LLMResponseError(
                    f"LLM endpoint rejected the tool-calling request "
                    f"(endpoint does not support tools?): {exc}") from exc
            raise
        if _usage_sink is not None:
            usage = response.get("usage")
            _usage_sink.append(usage if isinstance(usage, dict) else {})
        try:
            choice = response["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM response missing choices[0].message") from exc
        if not isinstance(message, dict):
            raise LLMResponseError("LLM response message must be an object")
        content = message.get("content")
        has_tool_calls = bool(message.get("tool_calls"))
        finish_reason = str(choice.get("finish_reason") or "")
        empty_content = content is None or (isinstance(content, str) and not content.strip())
        truncated = finish_reason == "length" or (empty_content and not has_tool_calls)
        if not truncated:
            return response
        if max_tokens >= MAX_TOKENS_ESCALATION_CAP:
            LOGGER.warning("tool 轮输出截断/空响应且 max_tokens 已到升级上限 %d（finish=%s）,按原样返回",
                           MAX_TOKENS_ESCALATION_CAP, finish_reason)
            return response
        escalated = min(max_tokens * 2, MAX_TOKENS_ESCALATION_CAP)
        LOGGER.warning("tool 轮输出截断/空响应（finish=%s）——max_tokens %d→%d 自动升级重试 model=%s",
                       finish_reason, max_tokens, escalated, config.model)
        max_tokens = escalated


def _aggregate_usage(usage_sink: list[dict[str, Any]]) -> dict[str, Any]:
    """汇聚全部底层调用（首发/工具轮/修复/截断升级）的 usage——同 chat_json_with_meta 口径：
    逐轮归一再求和（每轮 total_i = total_tokens；缺 total 且 prompt+completion 双明细
    俱在则取二者之和）——混合序列不得被"全或无"兜底低计（如一轮报 total、一轮只报
    明细时，旧兜底会丢弃明细轮）。usage 缺失计 0 且 usage_complete=False
    （不得估算冒充精确值,见 Phase 1.5 tokens 口径）。"""
    normalized = [_normalized_usage(usage) for usage in usage_sink]
    valid = [usage for usage in normalized if usage is not None]
    prompt = sum(usage["prompt_tokens"] for usage in valid)
    completion = sum(usage["completion_tokens"] for usage in valid)
    total = sum(usage["total_tokens"] for usage in valid)
    complete = bool(usage_sink) and len(valid) == len(usage_sink)
    return {
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total},
        "usage_complete": complete,
    }


JSON_MODE_ENV = "RATOMIZER_LLM_JSON_SCHEMA"   # 默认开;=0 关闭（0714 批次二 S6）

# 端点不支持 response_format 的记忆（按 base_url|model）：此前每次调用都探测,
# 不支持的端点每次白发一遍 4xx（调用翻倍）。命中一次 4xx 即记住,本进程后续直发无 JSON 模式。
_JSON_MODE_UNSUPPORTED: set[str] = set()
_JSON_MODE_LOCK = threading.Lock()


def _json_mode_enabled() -> bool:
    raw = os.environ.get(JSON_MODE_ENV)
    if raw is None or not raw.strip():
        # 默认开（0714 批次二 S6）：mimo 双模型探针已验证 json_object;开着能基本消灭
        # "解析失败→修复重发"的调用翻倍。不支持的端点 4xx 一次后被记住并降级。
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _reset_json_mode_memory() -> None:
    """仅测试用。"""
    with _JSON_MODE_LOCK:
        _JSON_MODE_UNSUPPORTED.clear()


def _chat_content(
    config: LLMClientConfig,
    messages: list[dict[str, str]],
    _usage_sink: list[dict[str, Any]] | None = None,
    _request_budget: LLMRequestBudget | None = None,
    _request_stats: dict[str, int] | None = None,
) -> str:
    endpoint_key = f"{config.base_url}|{config.model}"
    with _JSON_MODE_LOCK:
        endpoint_supported = endpoint_key not in _JSON_MODE_UNSUPPORTED
    max_tokens = int(config.max_tokens)
    while True:
        json_mode = _json_mode_enabled() and endpoint_supported
        payload = build_chat_json_request_payload(
            config,
            messages,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        if json_mode:
            try:
                response = _post_json(
                    config,
                    payload,
                    _request_budget=_request_budget,
                    _request_stats=_request_stats,
                )
            except LLMResponseFormatUnsupported:
                # 只有端点明确指出 response_format/json_object 不受支持才记忆并降级。
                # 其它 4xx、畸形 200 和响应结构错误原样抛出,避免掩盖真实故障并重复调用。
                with _JSON_MODE_LOCK:
                    _JSON_MODE_UNSUPPORTED.add(endpoint_key)
                endpoint_supported = False
                LOGGER.warning("端点疑似不支持 response_format=json_object,已记住并降级重发: %s", endpoint_key)
                payload = build_chat_json_request_payload(
                    config,
                    messages,
                    max_tokens=max_tokens,
                    json_mode=False,
                )
                response = _post_json(
                    config,
                    payload,
                    _request_budget=_request_budget,
                    _request_stats=_request_stats,
                )
        else:
            response = _post_json(
                config,
                payload,
                _request_budget=_request_budget,
                _request_stats=_request_stats,
            )
        if _usage_sink is not None:
            usage = response.get("usage")
            _usage_sink.append(usage if isinstance(usage, dict) else {})
        try:
            choice = response["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM response missing choices[0].message.content") from exc
        if not isinstance(content, str):
            raise LLMResponseError("LLM response content must be a string")
        finish_reason = str(choice.get("finish_reason") or "")
        # 截断检测：finish_reason=length（输出被 max_tokens 切断）或空 content（推理模型
        # reasoning 吃光预算、可见输出为零）。两者都注定 JSON 解析失败——立即升级重试,
        # 不走"截断 JSON → 修复重发"的弯路（修复调用用同一 max_tokens,同样被截）。
        truncated = finish_reason == "length" or not content.strip()
        if not truncated:
            return content
        if max_tokens >= MAX_TOKENS_ESCALATION_CAP:
            LOGGER.warning("LLM 输出截断/空响应且 max_tokens 已到升级上限 %d（finish=%s）,按原样返回交下游修复",
                           MAX_TOKENS_ESCALATION_CAP, finish_reason)
            return content
        escalated = min(max_tokens * 2, MAX_TOKENS_ESCALATION_CAP)
        LOGGER.warning("LLM 输出截断/空响应（finish=%s bytes=%d）——max_tokens %d→%d 自动升级重试 model=%s",
                       finish_reason, len(content), max_tokens, escalated, config.model)
        max_tokens = escalated


def _post_json(
    config: LLMClientConfig,
    payload: dict[str, Any],
    *,
    _request_budget: LLMRequestBudget | None = None,
    _request_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    body = serialize_json_request_body(payload)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = os.environ.get(config.api_key_env, "") if config.api_key_env else ""
    if api_key:
        # 同时发标准 Bearer 与 x-api-key：多数 OpenAI 兼容端点认前者、部分代理（如小米 MiMo
        # token-plan）只认后者；同发对标准端点无害（未知头被忽略），扩大端点兼容面。
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key

    max_attempts = max(0, int(config.max_retries)) + 1
    # 429 限流单独预算：并发跑时限流是常态（test7 实测 140 次 429、3 次重试打光 → 10 个
    # 章节整体失败=文档 17% 内容丢失）。限流≠服务坏了，值得更耐心：独立预算 + 更长退避。
    rate_limit_budget = max(RATE_LIMIT_MIN_ATTEMPTS, max_attempts * 2)
    gate = _gate_for(config.base_url) if _adaptive_enabled() else None
    attempt = 0
    rate_hits = 0
    while attempt < max_attempts:
        reservation_id = (
            _request_budget.reserve(payload) if _request_budget is not None else None
        )
        budget_settled = False
        request_succeeded = False
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        if gate is not None:
            gate.acquire()   # 冷却期内阻塞新请求;在飞数受 AIMD 上限约束
        started = time.monotonic()
        try:
            if _request_stats is not None:
                _request_stats["call_count"] = int(
                    _request_stats.get("call_count") or 0
                ) + 1
            with urllib.request.urlopen(request, timeout=config.timeout_s) as response:
                raw = response.read().decode("utf-8")
                duration = time.monotonic() - started
                # 每次 LLM 调用记时长（慢的可见性：推理模型单次可达 50-130s，没有这行
                # 用户只能感觉"卡"）。所有 LLM 环节（抽取/审查/富化/分析/翻译）共此一处。
                LOGGER.info("LLM 调用 model=%s dur=%.1fs attempt=%d bytes=%d",
                            config.model, duration, attempt + 1, len(raw))
                parsed = _loads_response_json(raw)
                request_succeeded = True
                if _request_budget is not None and reservation_id is not None:
                    _request_budget.commit(reservation_id, parsed.get("usage"))
                    budget_settled = True
                _write_trace({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "model": config.model,
                              "dur_s": round(duration, 1), "attempt": attempt + 1,
                              "messages": _truncate_for_trace(payload.get("messages")),
                              "response": _truncate_for_trace(parsed)})
                if gate is not None:
                    gate.on_success()
                return parsed
        except urllib.error.HTTPError as exc:
            raw = _read_error_body(exc)
            LOGGER.warning("LLM 调用失败 model=%s dur=%.1fs attempt=%d http=%s",
                           config.model, time.monotonic() - started, attempt + 1, exc.code)
            _write_trace({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "model": config.model,
                          "dur_s": round(time.monotonic() - started, 1), "attempt": attempt + 1,
                          "messages": _truncate_for_trace(payload.get("messages")),
                          "error": {"http": exc.code, "body": raw[:2000]}})
            if exc.code in {401, 403}:
                raise LLMConnectionError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
            if exc.code == 429:
                rate_hits += 1
                if rate_hits < rate_limit_budget:
                    # 尊重 Retry-After；没有就按限流命中次数指数退避（封顶 30s）——不占普通重试预算
                    delay = _retry_delay(min(rate_hits, 5), exc.headers.get("Retry-After"))
                    if gate is not None:
                        gate.on_rate_limited(delay)   # 全局冷却+在飞上限砍半,其它线程一起收敛
                    time.sleep(delay)
                    continue
                raise LLMConnectionError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
            if _is_retryable_status(exc.code):
                attempt += 1
                if attempt < max_attempts:
                    time.sleep(_retry_delay(attempt - 1, exc.headers.get("Retry-After")))
                    continue
                raise LLMConnectionError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
            body_low = raw.casefold()
            if ("response_format" in payload
                    and exc.code in {400, 404, 415, 422}
                    and ("response_format" in body_low or "json_object" in body_low)):
                raise LLMResponseFormatUnsupported(
                    f"LLM endpoint does not support response_format=json_object: HTTP {exc.code}: {raw}"
                ) from exc
            raise LLMResponseError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            # http.client.HTTPException（IncompleteRead/RemoteDisconnected/BadStatusLine）不是
            # URLError 子类——漏捕时一次传输抖动直接中止整轮抽取（test3 实测三连崩）。
            LOGGER.warning("LLM 连接异常 model=%s dur=%.1fs attempt=%d err=%s",
                           config.model, time.monotonic() - started, attempt + 1,
                           str(exc)[:120])
            attempt += 1
            if attempt < max_attempts:
                time.sleep(_retry_delay(attempt - 1, None))
                continue
            raise LLMConnectionError(f"LLM service is unavailable: {exc}") from exc
        finally:
            if _request_stats is not None and not request_succeeded:
                _request_stats["failed_call_count"] = int(
                    _request_stats.get("failed_call_count") or 0
                ) + 1
            if (_request_budget is not None and reservation_id is not None
                    and not budget_settled):
                _request_budget.fail(reservation_id)
            if gate is not None:
                gate.release()
    raise LLMConnectionError("LLM service is unavailable")


def _loads_response_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(f"LLM HTTP response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LLMResponseError("LLM HTTP response must be a JSON object")
    return payload


def _loads_json_content(content: str) -> dict[str, Any]:
    payload = json.loads(_strip_markdown_fence(content))
    if not isinstance(payload, dict):
        raise LLMResponseError("LLM content JSON must be an object")
    return payload


def _strip_markdown_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after is not None:
        try:
            # 封顶 60s：服务端可能返回超大 Retry-After（如 3600），指数分支已有 2**attempt 上限，
            # 服务端值分支同样必须有界，否则恶意/误配网关会让单次重试睡掉整轮运行。
            return min(max(0.0, float(retry_after)), 60.0)
        except ValueError:
            pass
    return float(2**attempt)


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    finally:
        exc.close()
