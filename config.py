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
    EnvVar("RATOMIZER_LLM_SESSION_API_KEY", "", "Electron 子进程专用临时密钥变量（主进程注入，不持久化）", False),
    EnvVar("RATOMIZER_LLM_TEMPERATURE", "0", "采样温度（可复现默认 0）", True),
    EnvVar("RATOMIZER_LLM_MAX_TOKENS", "", "输出上限（各环节另有用途下限，见 llm_client.PURPOSE_MIN_TOKENS）", True),
    EnvVar("RATOMIZER_LLM_TIMEOUT_S", "", "单次调用超时秒", True),
    EnvVar("RATOMIZER_LLM_MAX_RETRIES", "", "非 429 错误重试次数（429 另有独立预算）", True),
    EnvVar("RATOMIZER_LLM_CONCURRENCY", "8", "抽取/富化并发度（1..16；2026-07-14 默认 4→8）", True),
    EnvVar("RATOMIZER_LLM_ADAPTIVE", "1", "429 自适应闸门（跨线程全局冷却+在飞上限 AIMD；=0 关闭回到各线程独立退避）", False),
    EnvVar("RATOMIZER_REQUIREMENTS_ANALYSIS_ENRICH", "0", "需求分析 LLM 富化开关（默认关闭；方案库成熟后设为 1 启用）", False),
    EnvVar("RATOMIZER_ANALYZE_BATCH", "4", "软需富化合批条数（1..8；1=逐条；硬件翻译批量 ×2 封顶 8）", False),
    EnvVar("RATOMIZER_ENRICH_BATCH", "6", "装配描述富化合批条数（1..10；1=逐条；带蓝皮书条款的条目恒单发）", False),
    EnvVar("RATOMIZER_REBUILD_DEBOUNCE_S", "1.5", "裁决后交付物重建防抖秒数（连续裁决合并为一次重建；0=同步重建）", False),
    EnvVar("RATOMIZER_LLM_JSON_SCHEMA", "1", "response_format=json_object（默认开；仅端点明确报不支持时记住并降级；=0 关闭）", False),
    EnvVar("RATOMIZER_LLM_TRACE", "1", "=0/false 关闭 llm_trace.jsonl 消息级追踪（含客户文档全文，外发目录前注意）", False),
    EnvVar("RATOMIZER_LLM_TRACE_FULL", "", "=1 关闭 trace 文本截断、完整落盘 messages/response（仅离线调试，默认截断长文本减数据外发面）", False),
    # --- AI 抽取 ---
    EnvVar("RATOMIZER_AI_SELFCHECK", "1", "完整性自检开关（=0/false 关）", True),
    EnvVar("RATOMIZER_AI_SELFCHECK_ROUNDS", "3", "自检收敛轮数上限（1..6）", False),
    EnvVar("RATOMIZER_AI_VERIFY", "1", "抽取二遍语义复核开关（七类误读清单,=0/false 关）", False),
    EnvVar("RATOMIZER_AI_VERIFY_ROUNDS", "2", "复核投票轮数（1..4;单轮细微语义错误命中率 ~1/3,并集提召回）", False),
    EnvVar("RATOMIZER_CLAIM_SHADOW_VERIFY", "1", "Phase 0B 独立 coverage verifier 开关（仅真实 LLM 路由）", False),
    EnvVar("RATOMIZER_CLAIM_SHADOW_VERIFY_ROUNDS", "1", "Phase 0B coverage verifier 独立复核轮数（1..3；分歧保持 uncertain）", False),
    EnvVar("RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_CALLS", "0", "Phase 0B verifier 真实 HTTP attempt 硬上限（0=未授权）", False),
    EnvVar("RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_TOTAL_TOKENS", "0", "Phase 0B verifier 总 token 硬上限（0=未授权）", False),
    EnvVar("RATOMIZER_ATTEMPT_LOG_TORN_RETRIES", "3", "verifier attempt log torn-tail 重试窗口长度（0=立即判永久损坏；锁内 read 路径）", False),
    EnvVar("RATOMIZER_ATTEMPT_LOG_TORN_DELAY", "0.005", "verifier attempt log torn-tail 重试间隔秒", False),
    EnvVar("RATOMIZER_AI_UNIT_MODE", "clause", "抽取单元模式：clause（条款族，默认）/ chapter（整章，实验，A/B 已裁决劣于 clause）", False),
    # --- 表格双轨制（WS1）---
    EnvVar("RATOMIZER_TABLE_DUAL_TRACK", "0", "表格结构双轨入口开关（=1 启用「LLM 提议→几何校验签发」；默认 0=旧确定性几何单轨，签名失败/无预算/无假设时一律退回单轨）", False),
    EnvVar("RATOMIZER_PDF_MODERN_PARSER", "0", "PDF 现代解析器适配层开关（=1 优先走 pdf_modern_adapter；适配层 unavailable 时诚实回退手写 pdfplumber 路径并在产出标 parser_provenance；默认 0=旧手写路径，缓存指纹与 golden 基线字节不变）", False),
    # --- 知识/资产路径 ---
    EnvVar("RATOMIZER_BLUE_BOOK_INDEX", "", "蓝皮书索引 blue_book_index.json 路径（缺省自动探测 out_dir/仓库 out/bluebook）", False),
    EnvVar("RATOMIZER_ADJUDICATION_BANK", "", "裁决样本库 JSON 路径（专家 accepted 需求作 few-shot 注入富化；缺省不注入）", False),
    EnvVar("RATOMIZER_HISTORICAL_SAMPLE", "", "真实历史抽取样本路径（合并决策回归门；客户数据不进仓,未设置则该门跳过）", False),
    # --- 桌面/运维 ---
    EnvVar("RATOMIZER_PYTHON", "", "Electron dev 模式指定后端 Python 解释器路径", False),
)

ENV_NAMES = frozenset(v.name for v in ENV_REGISTRY)


def describe() -> str:
    lines = ["| 环境变量 | 默认 | GUI | 说明 |", "|---|---|---|---|"]
    for v in ENV_REGISTRY:
        lines.append(f"| {v.name} | {v.default or '-'} | {'✓' if v.gui_exposed else ''} | {v.description} |")
    return "\n".join(lines)
