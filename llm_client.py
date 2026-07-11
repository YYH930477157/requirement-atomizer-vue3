from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("requirement_atomizer")

# 429 限流的独立重试预算下限（与普通 max_retries 解耦）：退避 2,4,8,16,32,32… 秒，
# 8 次 ≈ 两分钟耐心——限流风暴通常几十秒内过去，比丢整章便宜得多
# 按用途的 max_tokens 下限（F4 收口：此前散在 3 个模块各写一遍，第 4 个环节必再忘一次）。
# 推理模型思维链会挤占输出预算，低于下限 → JSON 截断 → 整环节失败。
PURPOSE_MIN_TOKENS = {
    "extract": 6144,          # 逐条款抽取
    "extract-chapter": 16384,  # 整章模式（实验）：几十条需求的输出
    "analyze": 6144,          # 软件需求富化
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
        out = {}
        for k, v in value.items():
            if k in ("content", "reasoning_content") and isinstance(v, str):
                out[k] = _truncate_for_trace(v)
            else:
                out[k] = v  # role/name/usage/finish_reason/model 等结构字段原样
        return out
    return value


class LLMError(Exception):
    """Base exception for OpenAI-compatible LLM calls."""


class LLMConnectionError(LLMError):
    """Raised when the LLM service cannot be reached or stays unavailable."""


class LLMResponseError(LLMError):
    """Raised when the LLM response cannot be used as a review payload."""


@dataclass(frozen=True)
class LLMClientConfig:
    base_url: str
    model: str
    api_key_env: str = "RATOMIZER_LLM_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout_s: float = 60.0
    max_retries: int = 3


def chat_json(config: LLMClientConfig, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return chat_json_messages(config, messages)


def chat_json_messages(config: LLMClientConfig, messages: list[dict[str, str]]) -> dict[str, Any]:
    content = _chat_content(config, messages)
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
        repaired_content = _chat_content(config, repair_messages)
        try:
            return _loads_json_content(repaired_content)
        except json.JSONDecodeError as second_error:
            raise LLMResponseError(f"LLM response is not valid JSON after repair: {second_error}") from second_error
        except LLMResponseError as second_error:
            raise LLMResponseError(f"LLM response is not a JSON object after repair: {second_error}") from second_error


JSON_MODE_ENV = "RATOMIZER_LLM_JSON_SCHEMA"   # =1 请求 response_format=json_object（端点须支持）


def _json_mode_enabled() -> bool:
    return os.environ.get(JSON_MODE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _chat_content(config: LLMClientConfig, messages: list[dict[str, str]]) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    if _json_mode_enabled():
        # JSON 强制模式：端点支持时基本消灭"解析失败重修"（每轮 1-2 个失败单元的来源）。
        # 端点不支持会 4xx——失败一次即去掉该字段重发（探针式降级，不影响本次调用结果）。
        payload["response_format"] = {"type": "json_object"}
        try:
            response = _post_json(config, payload)
        except LLMError:
            payload.pop("response_format", None)
            response = _post_json(config, payload)
    else:
        response = _post_json(config, payload)
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMResponseError("LLM response missing choices[0].message.content") from exc
    if not isinstance(content, str):
        raise LLMResponseError("LLM response content must be a string")
    return content


def _post_json(config: LLMClientConfig, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(payload).encode("utf-8")
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
    attempt = 0
    rate_hits = 0
    while attempt < max_attempts:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_s) as response:
                raw = response.read().decode("utf-8")
                duration = time.monotonic() - started
                # 每次 LLM 调用记时长（慢的可见性：推理模型单次可达 50-130s，没有这行
                # 用户只能感觉"卡"）。所有 LLM 环节（抽取/审查/富化/分析/翻译）共此一处。
                LOGGER.info("LLM 调用 model=%s dur=%.1fs attempt=%d bytes=%d",
                            config.model, duration, attempt + 1, len(raw))
                parsed = _loads_response_json(raw)
                _write_trace({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "model": config.model,
                              "dur_s": round(duration, 1), "attempt": attempt + 1,
                              "messages": _truncate_for_trace(payload.get("messages")),
                              "response": _truncate_for_trace(parsed)})
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
                    time.sleep(_retry_delay(min(rate_hits, 5), exc.headers.get("Retry-After")))
                    continue
                raise LLMConnectionError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
            if _is_retryable_status(exc.code):
                attempt += 1
                if attempt < max_attempts:
                    time.sleep(_retry_delay(attempt - 1, exc.headers.get("Retry-After")))
                    continue
                raise LLMConnectionError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
            raise LLMResponseError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            LOGGER.warning("LLM 连接异常 model=%s dur=%.1fs attempt=%d err=%s",
                           config.model, time.monotonic() - started, attempt + 1,
                           str(exc)[:120])
            attempt += 1
            if attempt < max_attempts:
                time.sleep(_retry_delay(attempt - 1, None))
                continue
            raise LLMConnectionError(f"LLM service is unavailable: {exc}") from exc
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
