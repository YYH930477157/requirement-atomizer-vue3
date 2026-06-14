"""GUI 端 LLM/API 配置读写。

单一事实源是 `llm_agents/review_pipeline.yaml`（管线 DEFAULT_PIPELINE_PATH 同一文件）。
纪律：API 密钥**只走环境变量**——本模块只读写环境变量「名」(`api_key_env`)，
真实密钥从不写盘；用户在 GUI 里设的密钥只进 `os.environ`（本进程/本会话）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from resources import package_root


PIPELINE_PATH = package_root() / "llm_agents" / "review_pipeline.yaml"

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_API_KEY_ENV = "RATOMIZER_LLM_API_KEY"
REVIEW_MODES = ("targeted", "all")


@dataclass
class LlmSettings:
    enabled: bool
    base_url: str
    model: str
    api_key_env: str
    temperature: float
    max_tokens: int
    timeout_s: float
    max_retries: int
    review_mode: str
    confidence_below: float


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_llm_settings(path: Path = PIPELINE_PATH) -> LlmSettings:
    data = _read_yaml(path)
    routes = data.get("model_routes") if isinstance(data.get("model_routes"), dict) else {}
    oc = routes.get("openai_compatible") if isinstance(routes.get("openai_compatible"), dict) else {}
    scope = data.get("review_scope") if isinstance(data.get("review_scope"), dict) else {}
    mode = str(scope.get("mode") or "targeted")
    return LlmSettings(
        enabled=str(routes.get("default") or "stub") == "openai_compatible",
        base_url=str(oc.get("base_url") or DEFAULT_BASE_URL),
        model=str(oc.get("model") or ""),
        api_key_env=str(oc.get("api_key_env") or DEFAULT_API_KEY_ENV),
        temperature=_as_float(oc.get("temperature"), 0.0),
        max_tokens=_as_int(oc.get("max_tokens"), 1024),
        timeout_s=_as_float(oc.get("timeout_s"), 60.0),
        max_retries=_as_int(oc.get("max_retries"), 3),
        review_mode=mode if mode in REVIEW_MODES else "targeted",
        confidence_below=_as_float(scope.get("confidence_below"), 0.75),
    )


def save_llm_settings(settings: LlmSettings, path: Path = PIPELINE_PATH) -> None:
    """写回 yaml，保留其它键。绝不写入 API 密钥本身，只存 api_key_env（变量名）。"""
    data = _read_yaml(path)
    routes = data.setdefault("model_routes", {})
    routes["default"] = "openai_compatible" if settings.enabled else "stub"
    oc = routes.setdefault("openai_compatible", {})
    oc["base_url"] = settings.base_url.strip()
    oc["model"] = settings.model.strip()
    oc["api_key_env"] = settings.api_key_env.strip() or DEFAULT_API_KEY_ENV
    oc["temperature"] = settings.temperature
    oc["max_tokens"] = settings.max_tokens
    oc["timeout_s"] = settings.timeout_s
    oc["max_retries"] = settings.max_retries
    scope = data.setdefault("review_scope", {})
    scope["mode"] = settings.review_mode if settings.review_mode in REVIEW_MODES else "targeted"
    scope["confidence_below"] = settings.confidence_below
    _write_yaml(path, data)


# --- API 密钥：只进环境变量，不落盘 -------------------------------------------------

def api_key_is_set(api_key_env: str) -> bool:
    return bool(os.environ.get(api_key_env or ""))


def masked_api_key(api_key_env: str) -> str:
    value = os.environ.get(api_key_env or "") or ""
    if not value:
        return ""
    if len(value) <= 6:
        return "•" * len(value)
    return f"{value[:3]}…{value[-2:]}"


def set_session_api_key(api_key_env: str, value: str) -> None:
    """把密钥设进本进程环境（本会话生效，重启即失，不写盘）。"""
    name = (api_key_env or DEFAULT_API_KEY_ENV).strip()
    if value:
        os.environ[name] = value


def test_connection(base_url: str, api_key_env: str, *, timeout_s: float = 5.0) -> tuple[bool, str]:
    """对 {base_url}/models 发探测。可达即视为成功；区分鉴权失败与连不上。"""
    url = base_url.rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    key = os.environ.get(api_key_env or "") or ""
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            response.read()
            return True, f"连接成功 (HTTP {getattr(response, 'status', 200)})"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, f"可达但鉴权失败 (HTTP {exc.code})，检查 API Key"
        return True, f"服务可达 (HTTP {exc.code})"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"连接失败：{exc}（检查 Base URL / 服务是否启动）"


def test_chat(base_url: str, model: str, api_key_env: str, *, timeout_s: float = 15.0) -> tuple[bool, str]:
    """真发一次最小 chat 调用，一次性验证 连通 + 鉴权(key) + 模型名 三件事。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0.0,
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = os.environ.get(api_key_env or "") or ""
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        data["choices"][0]["message"]["content"]  # 校验是标准 OpenAI 响应结构
        return True, f"调用成功：连通 + 鉴权 + 模型 '{model}' 均 OK"
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:160]
        except Exception:
            pass
        if exc.code in (401, 403):
            return False, f"鉴权失败 (HTTP {exc.code})：检查环境变量 {api_key_env} 里的 API Key"
        if exc.code in (400, 404):
            return False, f"模型/端点错误 (HTTP {exc.code})：检查模型名 '{model}' 与 Base URL。{body}"
        return False, f"服务返回 HTTP {exc.code}：{body}"
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        return False, f"已连上但响应格式异常（非标准 OpenAI 返回）：{exc}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"连接失败：{exc}（检查 Base URL / 服务是否启动）"


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
