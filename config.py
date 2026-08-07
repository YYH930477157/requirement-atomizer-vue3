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
    # --- WS2 粒度重构（功能需求直抽 + claim 账本抽检 + 原子级下钻）---
    # 全部默认关闭/采样：直抽是旁路新入口（默认关=旧原子化路径），claim 账本 sampling 为默认档。
    # WS0 功能需求级真值集尚是 pending-human，本切片只交付工程机制（默认关闭、旧路径始终合法）。
    EnvVar("RATOMIZER_FUNCTIONAL_EXTRACT", "0", "功能需求直抽入口开关（=1 启用 functional_extract 单次 LLM 直出功能需求级条目并写 functional_requirements.json；默认 0=旧 extract_units→atomize→functional_synthesis 原子化路径，行为面与缓存指纹不动）", False),
    EnvVar("RATOMIZER_CLAIM_LEDGER_MODE", "sampling", "claim 账本闭合模式（配置解析层默认 sampling；B 轨发布路径 env 未设时仍走 full=生产行为不变，显式设置才 opt-in 生效）。full=全量 verifier 闭合 / sampling=分层抽样 10%+全部高风险 claim，未抽中 claim 延迟到发布门禁并在 claim_sampling_summary.json 留痕 / baseline_gate=发布门禁全量闭合+重型机制联动（用户显式开启时触发全量闭合）。build_shadow_ledger 自身默认 full（直接调用者/既有测试不受影响）；把 sampling 翻转为生产默认属语义变更，留待 S2", False),
    EnvVar("RATOMIZER_CLAIM_LEDGER_SAMPLING_RATE", "0.1", "sampling 模式分层抽样率（0..1，默认 0.1；抽检闭合率低于阈值时自动扩大，判定依据留账本）", False),
    EnvVar("RATOMIZER_CLAIM_LEDGER_SAMPLING_FLOOR_RATE", "0.3", "sampling 模式抽检闭合率下限（低于此值自动扩大抽样或建议转全量，0..1，默认 0.3）", False),
    EnvVar("RATOMIZER_FUNCTIONAL_DRILLDOWN_MULTI_BEHAVIOR", "2", "原子级下钻「多行为」信号阈值：同一主语下义务性模态动词支配不同动作数 ≥N 触发下钻（默认 2）", False),
    EnvVar("RATOMIZER_FUNCTIONAL_DRILLDOWN_MULTI_CONDITION", "1", "原子级下钻「多条件」信号阈值：条件从句/互斥分支数 ≥N 触发下钻（默认 1，与 semantic_quality 互斥限定词判据同源）", False),
    EnvVar("RATOMIZER_FUNCTIONAL_DRILLDOWN_MATRIX_ROWS", "2", "原子级下钻「参数矩阵」信号阈值：条款引用多行参数组合表行数 ≥N 触发下钻（默认 2）", False),
    # --- WS3 成本治理（统一预算单 + 三级模型路由 + 成本看板 + 增量重跑）---
    # 全部默认关闭/非侵入：预算单关闭时 llm_client 文档预算钩子不激活（零行为改变）；
    # 增量重跑默认关，stage_is_reusable 的 bool 契约不变。新机制只交付工程正确性，不切默认行为。
    EnvVar("RATOMIZER_LLM_BUDGET", "0", "文档级统一预算单开关（=1 启用 llm_budget.LLMBudgetLedger：每份文档一份预算单，总调用数/token 上限+各环节子预算+累计消耗，全部 LLM 调用从同一份扣减，耗尽即降级 stub 且 provenance 如实、功能直抽产出强制文档级 NEEDS WORK；默认 0=关闭，llm_client 钩子不激活，既有行为逐字节不变）", False),
    EnvVar("RATOMIZER_INCREMENTAL_RERUN", "0", "章节级增量重跑开关（=1 启用条款候选哈希比对：重解析后逐候选比内容哈希，仅变化候选及其映射功能需求进重跑队列，与全量重跑共用同一 hash_json 幂等键空间；默认 0=全量重跑，desktop_tasks.stage_is_reusable 行为不变）", False),
    # --- WS4 能力补齐（verification 六列状态 + 四态状态机 + 弱词扫描 + 手工入口 + 需求库 + 依赖推荐）---
    # 全部默认非侵入：弱词词典缺省走内置词表；需求库/弱词 YAML 路径未配置时不激活对应加载。
    EnvVar("RATOMIZER_WEAK_WORDS_PATH", "", "弱词词典 YAML 路径（覆盖内置词表；未配置=用内置 适当/尽快/灵活/等 词表，与 domain_packs 词表惯例一致）", False),
    EnvVar("RATOMIZER_REQUIREMENT_LIBRARY", "", "需求库 JSONL 路径（各项目功能需求汇总检索库；API 词面检索缺省读此；未配置=API 检索返回空）", False),
    EnvVar("RATOMIZER_BASE_LIBRARY", "", "基本需求库 JSONL 路径（历史 xlsx 经 A6 管道聚合、专家确认后入库）", False),
    EnvVar("RATOMIZER_SOLUTION_LIBRARY", "", "方案库 JSONL 路径（历史项目 design_options 沉淀、专家确认后入库）", False),
    EnvVar("RATOMIZER_REQUIREMENT_RETRIEVER", "literal", "需求检索器类型（T3-4 插件点：literal=词面 Jaccard 默认 / vector=预留可关开关，当前无向量依赖、选 vector 如实回退词面，产出仍过确定性校验）", False),
    # --- T2 编排环（agent_loop 升格：缺口驱动的再规划，裁决仍在专家面板）---
    # 默认非侵入：allow_llm 关闭时编排环只读缺口并把 extract 缺口转人工，不发起任何 LLM 补抽。
    EnvVar("RATOMIZER_ORCHESTRATION_MAX_ROUNDS", "8", "编排环每文档最大轮次上限（1..50，默认 8；达上限未收敛→文档 NEEDS WORK 交人）", False),
    EnvVar("RATOMIZER_ORCHESTRATION_ALLOW_LLM", "0", "编排环经 openai_compatible 路由自动发起 spot_extract/targeted_reextract 的授权开关（=1 启用；默认 0=只读缺口，extract 缺口转人工）", False),
    # --- WS-A 防漏网 / 内容模型分流（默认关或纯增量登记）---
    EnvVar("RATOMIZER_ENABLE_HTML_PARSER", "0", "HTML 输入解析器开关（=1 启用 parsers/html_parser.py；默认 0，不改变既有 docx/xlsx/pdf 主路径）", False),
    EnvVar("RATOMIZER_PDF_RESEG", "0", "PDF 词典重分词器开关（=1 启用 parsers/pdf_resegment.py 作为碎词修复补充；默认 0）", False),
    EnvVar("RATOMIZER_PDF_RESEG_WORDLIST", "", "PDF 重分词器词表路径（YAML/TXT；未配置使用内置默认词表）", False),
    EnvVar("RATOMIZER_UNEXTRACTED_REGISTRY", "1", "未抽取内容登记册开关（=0 关闭 unextracted_registry.json；默认 1 纯登记不改行为）", False),
    EnvVar("RATOMIZER_DOCX_EXTRA_CHANNELS", "0", "DOCX 文本框/页眉页脚额外通道收容开关（=1 启用 parsers/docx_extra_channels.py；默认 0=正文块与 golden 基线逐字节一致）", False),
    EnvVar("RATOMIZER_XLSX_REQUIREMENT_LIST", "0", "Excel 需求清单型分流开关（=1 对 xlsx 行映射抽取并产出 base_library_candidates.jsonl；默认 0=维持 table 路径）", False),
    EnvVar("RATOMIZER_CLAIM_RESCAN", "0", "claim 账本四视角确定性复扫开关（=1 将归属/数值/约束/覆盖问题汇入 quality_report；默认 0）", False),
    # --- V3 WS-A 三遍法核心（A1 整篇地图 / A2 上下文包 / A3 整篇对账）---
    # 全部默认关闭/legacy：新路径 opt-in，默认行为面与缓存指纹逐字节不变。
    EnvVar("RATOMIZER_DOC_MAP", "0", "A1 整篇地图开关（=1 启用 doc_map.LLM 单遍文档地图并写 doc_map.json；预算走文档预算单 structure_hypothesis 子预算，耗尽/stub 如实 unavailable；默认 0=不生成，调用方走无地图路径）", False),
    EnvVar("RATOMIZER_CONTEXT_PACK_STRATEGY", "legacy", "A2 功能直抽上下文包策略（legacy=遗留 4000 字符切片默认不变 / clause_family=按条款自然边界组装：目标条款整文不截断+同族相邻条款+doc_map 热区摘要）", False),
    EnvVar("RATOMIZER_CONTEXT_PACK_MAX_CHARS", "24000", "A2 上下文包大小上限字符数（只约束拼包：装不下的邻居整条舍弃；目标条款自身超限仍整文进包，宁超勿截）", False),
    EnvVar("RATOMIZER_RECONCILE", "0", "A3 整篇对账开关（=1 时 chain 链尾自动跑 reconcile：规则筛疑+LLM 裁定两段，硬依据一票否决，LLM 不可用如实 rules_only；默认 0=不跑，亦可用 desktop reconcile 子命令显式执行）", False),
    # --- WS-H 知识沉淀闭环（默认关；成文导出后自动 harvest） ---
    EnvVar("RATOMIZER_HARVEST", "0", "成文导出后自动执行 harvest 知识沉淀闭环（=1 启用）", False),
    EnvVar("RATOMIZER_HARVEST_PROJECT_TAG", "", "harvest 项目标签（如 africa-prepaid），用于待审定方案/知识候选分类", False),
    EnvVar("RATOMIZER_AUTO_ADJUDICATE_APPROVE", "0", "功能需求级自动通过开关（=1 启用；默认 0=全部走人工 review）", False),
    EnvVar("RATOMIZER_AUTO_ADJUDICATE_REJECT", "0", "功能需求级自动拒绝开关（=1 启用；硬依据红灯时自动 reject，否则 review）", False),
    EnvVar("RATOMIZER_AUTO_ADJUDICATE_REVIEW_RATE", "0.0", "自动 accept 后按概率强制降级为 review 的比例（能力边界抽样，0..1）", False),
    EnvVar("RATOMIZER_AUTO_ADJUDICATE_SAMPLE_RATE", "0.1", "自动 accept 结果进抽审队列的比例（高风险编码条目必抽，0..1）", False),
    EnvVar("RATOMIZER_AUTO_ADJUDICATE_FAR_THRESHOLD", "0.02", "允许自动通过的误受率上限（默认 2%，需真值集校准）", False),
    EnvVar("RATOMIZER_AUTO_ADJUDICATE_TRUTH_SET", "", "功能需求级真值集路径（缺省用 golden_sets/gold_functional_v1/truth.jsonl）", False),
    EnvVar("RATOMIZER_AUTO_ADJUDICATE_LLM_ROUTE", "", "AI 裁决语义投票 LLM 路由（缺省复用 RATOMIZER_LLM_MODEL）", False),
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
