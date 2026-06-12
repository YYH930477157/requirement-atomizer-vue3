from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


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
    max_tokens: int = 1024
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
    except json.JSONDecodeError as first_error:
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


def _chat_content(config: LLMClientConfig, messages: list[dict[str, str]]) -> str:
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
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
        headers["Authorization"] = f"Bearer {api_key}"

    max_attempts = max(0, int(config.max_retries)) + 1
    for attempt in range(max_attempts):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_s) as response:
                raw = response.read().decode("utf-8")
                return _loads_response_json(raw)
        except urllib.error.HTTPError as exc:
            raw = _read_error_body(exc)
            if exc.code in {401, 403}:
                raise LLMConnectionError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
            if _is_retryable_status(exc.code):
                if attempt + 1 < max_attempts:
                    time.sleep(_retry_delay(attempt, exc.headers.get("Retry-After")))
                    continue
                raise LLMConnectionError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
            raise LLMResponseError(f"LLM service returned HTTP {exc.code}: {raw}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt + 1 < max_attempts:
                time.sleep(_retry_delay(attempt, None))
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
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return float(2**attempt)


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
