"""RATOMIZER_* 环境变量注册表（架构债 F5：配置面单源）。

17+ 个环境变量此前散在各模块，无文档无清单——换机/交接/排查全靠考古。本表是**唯一权威清单**：
新增环境变量必须先登记（tests/test_config_registry.py 扫描全仓强制核对，漏登记即红）。
各模块可继续持有本地常量，但名称以此处为准。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvVar:
    name: str
    default: str
    description: str
    gui_exposed: bool = False   # GUI 设置面板是否有对应入口


ENV_REGISTRY: tuple[EnvVar, ...] = (
    # --- LLM 端点（GUI 设置面板 safeStorage 管理，密钥绝不落盘） ---
    EnvVar("RATOMIZER_LLM_BASE_URL", "", "OpenAI 兼容端点 base URL（覆盖 pipeline yaml）", True),
    EnvVar("RATOMIZER_LLM_MODEL", "", "模型名（覆盖 pipeline yaml）", True),
    EnvVar("RATOMIZER_LLM_API_KEY", "", "API 密钥（只走环境变量；小米 MiMo 端点用 x-api-key 头双发兼容）", True),
    EnvVar("RATOMIZER_LLM_API_KEY_ENV", "", "自定义密钥所在的环境变量名（间接引用）", False),
    EnvVar("RATOMIZER_LLM_TEMPERATURE", "0", "采样温度（可复现默认 0）", True),
    EnvVar("RATOMIZER_LLM_MAX_TOKENS", "", "输出上限（各环节另有用途下限，见 llm_client.PURPOSE_MIN_TOKENS）", True),
    EnvVar("RATOMIZER_LLM_TIMEOUT_S", "", "单次调用超时秒", True),
    EnvVar("RATOMIZER_LLM_MAX_RETRIES", "", "非 429 错误重试次数（429 另有独立预算）", True),
    EnvVar("RATOMIZER_LLM_CONCURRENCY", "4", "抽取/富化并发度（1..16）", True),
    EnvVar("RATOMIZER_LLM_JSON_SCHEMA", "0", "=1 请求 response_format=json_object（端点须支持；不支持自动降级）", False),
    EnvVar("RATOMIZER_LLM_TRACE", "1", "=0/false 关闭 llm_trace.jsonl 消息级追踪（含客户文档全文，外发目录前注意）", False),
    # --- AI 抽取 ---
    EnvVar("RATOMIZER_AI_SELFCHECK", "1", "完整性自检开关（=0/false 关）", True),
    EnvVar("RATOMIZER_AI_SELFCHECK_ROUNDS", "3", "自检收敛轮数上限（1..6）", False),
    EnvVar("RATOMIZER_AI_UNIT_MODE", "clause", "抽取单元模式：clause（条款族，默认）/ chapter（整章，实验，A/B 已裁决劣于 clause）", False),
    # --- 知识/资产路径 ---
    EnvVar("RATOMIZER_BLUE_BOOK_INDEX", "", "蓝皮书索引 blue_book_index.json 路径（缺省自动探测 out_dir/仓库 out/bluebook）", False),
    EnvVar("RATOMIZER_ADJUDICATION_BANK", "", "裁决样本库 JSON 路径（专家 accepted 需求作 few-shot 注入富化；缺省不注入）", False),
    # --- 桌面/运维 ---
    EnvVar("RATOMIZER_PYTHON", "", "Electron dev 模式指定后端 Python 解释器路径", False),
)

ENV_NAMES = frozenset(v.name for v in ENV_REGISTRY)


def describe() -> str:
    lines = ["| 环境变量 | 默认 | GUI | 说明 |", "|---|---|---|---|"]
    for v in ENV_REGISTRY:
        lines.append(f"| {v.name} | {v.default or '-'} | {'✓' if v.gui_exposed else ''} | {v.description} |")
    return "\n".join(lines)
