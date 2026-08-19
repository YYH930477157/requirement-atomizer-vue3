"""RATOMIZER_* 环境变量注册表（架构债 F5：配置面单源）。

17+ 个环境变量此前散在各模块，无文档无清单——换机/交接/排查全靠考古。本表是**唯一权威清单**：
新增环境变量必须先登记（tests/test_config_registry.py 扫描全仓强制核对，漏登记即红）。
各模块可继续持有本地常量，但名称以此处为准。
"""
from __future__ import annotations

import os
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
    EnvVar("RATOMIZER_ANALYZE_NEGATIVE_K", "2", "analyze 富化负例 few-shot 注入数量上限（0=不注入）", False),
    EnvVar("RATOMIZER_ANALYZE_BATCH", "4", "软需富化合批条数（1..8；1=逐条；硬件翻译批量 ×2 封顶 8）", False),
    EnvVar("RATOMIZER_ENRICH_BATCH", "6", "装配描述富化合批条数（1..10；1=逐条；带蓝皮书条款的条目恒单发）", False),
    # --- 复核批处理（默认 OFF=逐条；仅 single-shot 旧路径 opt-in，tool-loop 路径恒不批处理）---
    EnvVar("RATOMIZER_REVIEW_BATCH", "0", "原子复核批处理开关（=0 逐条，默认 m2-review-v3 行为/缓存不动；1 仍逐条；2..20 启用 single-shot 批量复核 m2-review-v4-batch，推荐 15，硬 clamp 20；非整数 fail-safe 关闭。仅当 yaml operations 未声明 executor=tool_loop 时生效——不得绕过工具取证/kb_search 每条上限/token 预算）", False),
    # --- 说明标记翻译优化批处理（默认 10；=0 回退旧 batch=8 简单切片）---
    EnvVar("RATOMIZER_TRANSLATE_BATCH", "10", "说明标记翻译优化批处理开关（默认 10；=0 回退旧 batch=8 简单切片+批次失败直降单条；正整数 N 启用，条数硬 clamp 到 10，且单批输入字符≤RATOMIZER_TRANSLATE_BATCH_MAX_CHARS 的顺序贪心装包，单条超限整条单独发，批次 JSON 非法拆半≤2 轮后逐条；护栏按条照跑零放松）", False),
    EnvVar("RATOMIZER_TRANSLATE_BATCH_MAX_CHARS", "8000", "优化批处理单批输入总字符上限（仅 RATOMIZER_TRANSLATE_BATCH>0 时生效；任一条累加后超出即封包，防 10 条长文译文顶 max_tokens 把 JSON 切半）", False),
    EnvVar("RATOMIZER_FULL_TRANSLATION", "1", "全文翻译正式阶段开关（默认开启；=0 时逐块记 skipped:feature_disabled，不发起翻译调用）", False),
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
    # --- claim 账本追加式压缩阈值（追加 O(1)；超阈值经原子路径重物化，只修复撕裂/非规范行，不丢历史）---
    EnvVar("RATOMIZER_ATTEMPT_LOG_COMPACT_MAX_BYTES", "8388608", "claim_reextract_attempts.jsonl 压缩触发字节数（默认 8 MiB；≤0 回退默认）", False),
    EnvVar("RATOMIZER_ATTEMPT_LOG_COMPACT_MAX_ROWS", "2000", "claim_reextract_attempts.jsonl 压缩触发行数（默认 2000；≤0 回退默认）", False),
    EnvVar("RATOMIZER_VERIFIER_LEDGER_COMPACT_MAX_BYTES", "8388608", "claim_verifier_attempts.jsonl 压缩触发字节数（默认 8 MiB；≤0 回退默认）", False),
    EnvVar("RATOMIZER_VERIFIER_LEDGER_COMPACT_MAX_ROWS", "2000", "claim_verifier_attempts.jsonl 压缩触发行数（默认 2000；≤0 回退默认）", False),
    EnvVar("RATOMIZER_AI_UNIT_MODE", "clause", "抽取单元模式：clause（条款族，默认）/ chapter（整章，实验，A/B 已裁决劣于 clause）", False),
    # --- 表格双轨制（WS1）---
    EnvVar("RATOMIZER_TABLE_DUAL_TRACK", "0", "表格结构双轨入口开关（=1 启用「LLM 提议→几何校验签发」；默认 0=旧确定性几何单轨，签名失败/无预算/无假设时一律退回单轨）", False),
    # --- PDF 版式修复（W8：D1 下标归位 / D2 断行连字符 / D3 两栏定义表；全部 OFF 时解析输出与旧版字节一致）---
    EnvVar("RATOMIZER_PDF_SUBSCRIPT_FIX", "1", "PDF 下标归位开关（D1；=0 关闭 size 证据抽取与下标拼接；默认 1）", False),
    EnvVar("RATOMIZER_PDF_HYPHEN_FIX", "1", "PDF 断行连字符合并开关（D2；=0 回到旧版仅小写续行拼接；默认 1 含 G4 护栏与数字续行）", False),
    EnvVar("RATOMIZER_PDF_TWOCOL_DEF", "0", "PDF 两栏定义表检测开关（D3；=1 启用粗体术语栏+长定义栏结构重建；默认 0 试点）", False),
    EnvVar("RATOMIZER_PDF_MODERN_PARSER", "0", "PDF 现代解析器适配层开关（=1 优先走 pdf_modern_adapter；适配层 unavailable 时诚实回退手写 pdfplumber 路径并在产出标 parser_provenance；默认 0=旧手写路径，缓存指纹与 golden 基线字节不变）", False),
    # --- WS2 粒度重构（功能需求直抽 + claim 账本抽检 + 原子级下钻）---
    # 功能直抽默认开启；旧原子化路径保留为显式 =0 的回滚通道。claim 账本 sampling 为默认档。
    # WS0 功能需求级真值集仍需人工补齐；默认翻转不改变失败必须响亮阻断的门禁语义。
    EnvVar("RATOMIZER_FUNCTIONAL_EXTRACT", "1", "功能需求直抽入口开关（=1 chain 内 ai-extract+functional-synthesis 两阶段整体替换为 functional-extract：条款单元单次 LLM 直出功能需求级条目写 functional_requirements.json，不产原子、不再重并；UI/CLI 仍传旧阶段名，替换由 chain_task 单点完成并落账。默认 1=功能直抽路径；显式 0=回滚旧原子化路径）", False),
    EnvVar("RATOMIZER_FUNCTIONAL_EXTRACT_NEGATIVE_K", "2", "functional_extract 直抽负例 few-shot 注入数量上限（0=不注入）", False),
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
    EnvVar("RATOMIZER_TEXT_MODE", "1", "旧解析文本模式开关（=1 保留 DocumentReview 的「解析文本」模式；=0 隐藏文本模式按钮，删除动作待 G4 平价清单验收后执行）", False),
    # --- WS-A 防漏网 / 内容模型分流（默认关或纯增量登记）---
    EnvVar("RATOMIZER_ENABLE_HTML_PARSER", "0", "HTML 输入解析器开关（=1 启用 parsers/html_parser.py；默认 0，不改变既有 docx/xlsx/pdf 主路径）", False),
    EnvVar("RATOMIZER_PDF_RESEG", "0", "PDF 词典重分词器开关（=1 启用 parsers/pdf_resegment.py 作为碎词修复补充；默认 0）", False),
    EnvVar("RATOMIZER_PDF_RESEG_WORDLIST", "", "PDF 重分词器词表路径（YAML/TXT；未配置使用内置默认词表）", False),
    EnvVar("RATOMIZER_UNEXTRACTED_REGISTRY", "1", "未抽取内容登记册开关（=0 关闭 unextracted_registry.json；默认 1 纯登记不改行为）", False),
    EnvVar("RATOMIZER_DOCX_EXTRA_CHANNELS", "0", "DOCX 文本框/页眉页脚额外通道收容开关（=1 启用 parsers/docx_extra_channels.py；默认 0=正文块与 golden 基线逐字节一致）", False),
    EnvVar("RATOMIZER_XLSX_REQUIREMENT_LIST", "0", "Excel 需求清单型分流开关（=1 对 xlsx 行映射抽取并产出 base_library_candidates.jsonl；默认 0=维持 table 路径）", False),
    EnvVar("RATOMIZER_CLAIM_RESCAN", "0", "claim 账本四视角确定性复扫开关（=1 将归属/数值/约束/覆盖问题汇入 quality_report；默认 0）", False),
    # --- V4 A9 招标文件适配（默认关，OFF 时行为字节不变） ---
    EnvVar("RATOMIZER_TENDER_TABLE_FILTER", "0", "A9-1 商务/表单表识别排除开关（=1 启用 tender_table_filter.py；默认 0=维持既有 table 分类）", False),
    EnvVar("RATOMIZER_TENDER_REGION_FILTER", "0", "A9-2 tender 区域识别开关（=1 启用 tender_regions.py；默认 0=维持既有 doc_region 标记）", False),
    EnvVar("RATOMIZER_TENDER_FIGURE_PAGE_FILTER", "0", "A9-3 疑似流程图页强制高亮开关（=1 在未抽取登记册中单列整页图页；默认 0=维持既有登记行为）", False),
    # --- V3 WS-A 三遍法核心（A1 整篇地图 / A2 上下文包 / A3 整篇对账）---
    # DOC_MAP / RECONCILE 仍默认关。CONTEXT_PACK_STRATEGY 登记默认仍是 legacy（显式回滚
    # 与 get_env 单源字面）；生效策略由 functional_extract.context_pack_strategy() 解析——
    # 直抽开启且环境变量未设时走 clause_family，不在此改登记默认以免与显式 legacy 无法区分。
    EnvVar("RATOMIZER_DOC_MAP", "0", "A1 整篇地图开关（=1 启用 doc_map.LLM 单遍文档地图并写 doc_map.json；预算走文档预算单 structure_hypothesis 子预算，耗尽/stub 如实 unavailable；默认 0=不生成，调用方走无地图路径）", False),
    EnvVar("RATOMIZER_CONTEXT_PACK_STRATEGY", "legacy", "A2 功能直抽上下文包策略（legacy=文档级 4000 字符切片 / clause_family=按条款自然边界组装）。登记默认 legacy 供显式回滚；直抽开启且本变量未设时，context_pack_strategy() 生效 clause_family", False),
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
    # --- quality-first 单元路由（2026-08-17 方案 §11/§14；默认保持既有执行方式） ---
    EnvVar("RATOMIZER_EXECUTION_POLICY", "legacy_combined", "执行策略（quality_first|force_a|force_b|full_dual_audit|legacy_combined；默认 legacy——Router 过真实语料门禁前不翻默认，§31）", False),
    EnvVar("RATOMIZER_TRANSLATION_MODE", "full", "翻译交付模式（off|markers|full；默认 full=既有行为；off/markers 由 M6 接线强制零隐藏调用）", False),
    EnvVar("RATOMIZER_BUDGET_MODE", "off", "预算模式（off|observe|enforce；默认 off=既有行为；observe/enforce 由 M6 接线）", False),
    EnvVar("RATOMIZER_UNIT_ROUTER_RULES", "", "单元路由规则集覆盖（保留给真实语料标定后的阈值集；空=内置规则）", False),
)

ENV_NAMES = frozenset(v.name for v in ENV_REGISTRY)

_REGISTRY_BY_NAME: dict[str, EnvVar] = {v.name: v for v in ENV_REGISTRY}

# 统一布尔真值集合（§3.6 默认值翻转机制的前置：单源默认 + 单一口径）。
# 注意与 text_mode_enabled 的"默认开"极性不同——这里表达"显式开启"。
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def env_default(name: str) -> str:
    """注册表登记的默认值（单源）；未登记的名字直接 KeyError——强制先登记。"""
    try:
        return _REGISTRY_BY_NAME[name].default
    except KeyError:
        raise KeyError(
            f"环境变量 {name} 未在 config.ENV_REGISTRY 登记——先登记再读取"
        ) from None


def get_env(name: str, *, override: str | None = None) -> str:
    """统一环境变量读取（§3.6）：override（测试注入）> os.environ > 注册表默认值。

    默认值只此一份。各模块不得再内联自己的 ``os.environ.get(name, "默认")``——
    翻转默认值时只改注册表 + 本函数族，CLI/Electron 子进程/chain_task/阶段指纹/
    单步命令/测试自动同源。
    """
    if override is not None:
        return str(override)
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return env_default(name)
    return str(raw)


def get_env_bool(name: str, *, override: str | None = None) -> bool:
    """布尔开关读取：真值集合 {1,true,yes,on}，其余（含注册表默认）为关。"""
    return get_env(name, override=override).strip().lower() in _TRUTHY


def get_env_int(name: str, *, override: str | None = None) -> int:
    """整数读取：非法/空值回退注册表默认（fail-safe，与既有 _env_int 口径一致）。"""
    raw = get_env(name, override=override).strip()
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return int(float(env_default(name)))


def get_env_float(name: str, *, override: str | None = None) -> float:
    """浮点读取：非法/空值回退注册表默认。"""
    raw = get_env(name, override=override).strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(env_default(name))


def describe() -> str:
    lines = ["| 环境变量 | 默认 | GUI | 说明 |", "|---|---|---|---|"]
    for v in ENV_REGISTRY:
        lines.append(f"| {v.name} | {v.default or '-'} | {'✓' if v.gui_exposed else ''} | {v.description} |")
    return "\n".join(lines)


def text_mode_enabled(value: str | None = None) -> bool:
    """RATOMIZER_TEXT_MODE 是否保留旧解析文本模式（默认保留）。"""
    raw = os.environ.get("RATOMIZER_TEXT_MODE") if value is None else value
    return str(raw or "").strip().lower() not in {"0", "false", "off", "no"}
