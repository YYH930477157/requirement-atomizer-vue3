# Requirement Atomizer 仓库结构与 Token 成本综合分析报告（终版）

**报告日期：** 2026-08-16
**审查对象：** `requirement-atomizer-vue3` 当前工作树（分支 `codex/table-translation-structure`，含 `functional_extract.py` / `prompt_registry.py` 未提交改动）
**报告性质：** 静态代码审查 + 运行产物审计；未修改任何业务代码

**报告定位：** 本报告是终版综合报告，输入为三份前序分析：

- `docs/code-structure-token-analysis-2026-08-16.md`（结构深度版）
- `docs/repository-architecture-token-audit-2026-08-16.md`（架构审计版）
- `docs/code-structure-token-analysis-combined-2026-08-16.md`（综合校正版）

前序报告中的全部载荷性论断已在本轮**对照当前工作树代码逐条独立复核**，证据以 `文件:行号` 标注；其中 3 处口径修正见 §13。本报告可独立阅读，无需回翻前序报告。

---

## 1. 执行摘要

两项核心判断均成立，且可精确归因：

> **结构不简洁的本质**：不是功能冗余（多数模块确有独立职责），而是横切基础设施（原子写、指纹、评审状态机、重抽队列、LLM 批处理/缓存）被 5–22 个文件各自重复实现，聚类已自然形成却未成为包边界，控制面集中在前后端各一个"上帝文件"中。

> **Token 异常高的本质**：不是单次调用浪费，而是系统性乘法效应——
> **默认同时运行 5 条付费链路 × 每条链路自带 2–6 倍放大器（多轮重发/工具环累积）× 缓存键捆绑高频 bump 的行为版本（一失效即整文档重付）× 文档级总预算默认关闭（无封顶）**

最严重的四个问题：

1. **P0** 开启 LLM 后，UI 默认同时执行 A 轨逐需求审查 + A 轨富化 + B 轨功能直抽 + B 轨需求分析 + 全文翻译，五条付费链路互不共享模型判断。
2. **P0** 全文翻译没有 UI 开关，只要 `useLlm=true` 即隐式入链；实测单阶段消耗 345 calls / 1,048,945 tokens。
3. **P0** 文档级总预算框架完整存在（分环节子预算、预警、降级语义）但默认关闭，运行时无任何全文档 token 封顶。
4. **P1** 阶段编排存在 4 份真相、付费缓存存在 8 个互不相通的域、缓存指纹混入无关配置，导致重复判断、行为漂移和无谓重跑。

---

## 2. 目录结构与代码组织

### 2.1 布局总览

```text
requirement-atomizer-vue3/
├── *.py                # 129 个顶层模块，约 95,900 行；pyproject py-modules 手工登记 130 条
│   ├── claim_*（19）    # B轨需求账本全生命周期：候选→发布→fold→队列→评审→验收（最庞大聚类）
│   ├── functional_*（5）# WS2 条款直抽/合成/重抽/下钻（当前默认生产主路径）
│   ├── table_*（8）     # 表格物理还原→结构角色→处置→评审→局部重算
│   ├── requirements_analysis*（6）+ ai_extract + spec_enrich   # B轨 LLM 抽取与富化
│   ├── atomize + llm_pipeline + assemble_spec + cosem_*（4）  # A轨：原子化+评审+装配
│   ├── agent_*（7）     # 有界决策环与评测，刻意独立于 CHAIN_ORDER
│   └── 评审/重抽/基础设施系（review_state、omission_actions、llm_client/budget、config…）
├── parsers/            # DOCX/XLSX/PDF/HTML → DocumentIR（生产主路径未真正消费该抽象）
├── requirement_kb/     # 知识库加载/检索/匹配
├── llm_agents/         # review_pipeline.yaml（LLM 管线声明式配置）
├── gui/                # PySide6 旧 GUI（已冻结，只读兼容）
├── ui/                 # Vue3 + Electron 现役前端（14 个源文件，15,772 行）
├── schemas/            # 44 个 JSON Schema
├── tools/              # ab_runner.py（翻转门 A/B）、shadow_run.py 等离线评测
├── tests/              # ~204 个 unittest 文件（不是 pytest）
├── golden_sets/        # 冻结回归基线
└── out/                # 本机运行结果（含 llm_budget.json 实测证据）
```

### 2.2 复杂度中心（实测行数）

| 文件 | 行数 | 承担职责 |
|---|---:|---|
| `claim_artifacts.py` | 6,209 | claim 发布、验证、投影、产物生成 |
| `ui/src/App.vue` | 6,210 | UI、运行配置、链路规划、进度、评审交互 |
| `ai_extract.py` | 4,827 | prompt、调用、自检、复核、缓存、并发 |
| `claim_ledger.py` | 4,566 | 多类账本与闭环规则 |
| `desktop_tasks.py` | 3,920 | Electron 桥 + 37 个子命令 + CHAIN_ORDER + 版本戳注册 |
| `api_server.py` | 3,425 | 47 条手写 if/return 路由（标准库 http.server，无框架） |
| `doc_annotation_export.py` | 5,370 行级（291KB） | 批注导出 + 翻译 |
| `functional_extract.py` | 2,050 行级（102KB） | WS2 直抽 + 守恒 guard + 缓存 |

前端镜像问题：`DocumentReview.vue` 2,846 行、`FunctionalReview.vue` 2,013 行、`api-client.ts` 1,917 行。前后端都是"单文件承载整个控制面"。

### 2.3 结构漂移

1. `parsers/base.py` 定义了 `DocumentParser → DocumentIR` 抽象，但生产 `atomize` 主路径仍按扩展名直调 `extract_docx/xlsx/pdf`。
2. `pyproject.toml` py-modules 手工清单 130 条中 `doc_map`（78/86 行）、`reconcile`（79/87 行）、`adjudicate`（88/145 行）各重复登记两次。
3. `ARCHITECTURE.md:39` 仍声明 functional extract 默认关闭，实际 `config.py:75` 已默认开启。
4. 根目录存在 278KB 误产物文件 `!`（unittest 输出重定向）。

---

## 3. 核心组件

### 3.1 入口点

| 入口 | 角色 |
|---|---|
| `cli.py` | 机器面 CLI（exit 0/2/3/4，stdout = UTF-8 JSON 信封） |
| `atomize.py` | A 轨原子化核心（3,019 行，深耦合 `table_structure` 约 20 个符号） |
| `desktop_tasks.py` | Electron 任务桥 + 单命令编排；`CHAIN_ORDER` 唯一定义处（`desktop_tasks.py:1201-1202`）+ stage producer 版本戳注册（1378 行起） |
| `api_server.py` | 本地评审 HTTP API：`RequirementAPIHandler`（184 行），GET 28 条（`do_GET`:210 起）+ POST 19 条（`do_POST`:570 起）顺序 if/return 分发 |
| `llm_pipeline.py` | LLM 评审管线（`llm_agents/review_pipeline.yaml` 驱动 + 有界工具环） |

Electron 前端 → `desktop_backend.py` → `desktop_tasks.py`（链编排）+ `api_server.py`（评审 API）。

### 3.2 子系统聚类

```text
parsing        DOCX/XLSX/PDF/表格物理结构/facsimile
A-track        atomize → llm-review → assemble(+spec_enrich) → COSEM/DLMS 规格（cosem_* 零 LLM）
B-track        functional-extract → requirements-analysis → template-write → clarification-report
review/claims  review actions → claim_catalog → claim_ledger → claim_queue_execution
               → verifier(WAL) → table_claim_authority → 批注投影
delivery       full-translation → compose → annotation HTML/PDF/XLSX
platform       cli / desktop_tasks / api_server / Vue3+Electron
```

---

## 4. 技术栈

| 层 | 技术 |
|---|---|
| Python 后端 | ≥3.11（本机 3.14）；运行时依赖仅 6 项：python-docx / PyYAML / openpyxl / pdfplumber / jsonschema / pywin32；HTTP 用标准库（无框架、无数据库） |
| LLM | urllib 自实现 OpenAI-compatible client（无官方 SDK、无第三方 agent runtime）；YAML + 环境变量共同配置路由 |
| 持久化 | append-only JSONL、快照 JSON、WAL、锁文件、原子替换（无 DB） |
| 前端 | Vue 3.5 + TypeScript 5.7 + Vite 6 + Electron 33 + naive-ui；pdfjs-dist / docx-preview / xlsx |
| 测试 | 后端 `python -m unittest discover -s tests`（**不是 pytest**）；前端 vitest + vue-tsc |
| 打包 | 后端 PyInstaller → exe；前端 electron-builder portable |

---

## 5. 运行流程

### 5.1 三条抽取链并存

| 链路 | 路径 | 地位 |
|---|---|---|
| A 轨 | `atomize → llm-review → assemble(+spec_enrich) → cosem_*` | DLMS profile / 结构化标准主链 |
| B 轨 WS2 直抽 | `functional-extract → requirements-analysis → template/clarification` | **当前默认**（`RATOMIZER_FUNCTIONAL_EXTRACT=1`） |
| 旧 B 轨 | `ai-extract → functional-synthesis` | 默认被替换；显式回退/单阶段路径仍在 |

`CHAIN_ORDER`（`desktop_tasks.py:1201-1202`）十阶段：`ai-extract → functional-extract → functional-synthesis → assemble → requirements-analysis → template-write → clarification-report → full-translation → compose → export-annotation-html`。注意 **`llm-review` 不在 CHAIN_ORDER 内**，由 `run_pipeline_task`（`desktop_tasks.py:303-332`）单独执行。

### 5.2 LLM 模式下的默认链真相（已逐行复核）

```text
DOCX/XLSX/PDF
  → atomize（解析，零 LLM）
  → A轨 llm-review（逐需求 tool-loop，20,000 token/需求）     ← 付费
  → B轨 functional-extract（替换 ai-extract+functional-synthesis，
      desktop_tasks.py:2676-2686；但不取消已执行的 llm-review）  ← 付费
  → A轨 assemble + spec_enrich（desktop_tasks.py:2718 传真实 route）← 付费
  → B轨 requirements-analysis                                  ← 付费
  → full-translation（useLlm=true 即无条件入链）               ← 付费
  → compose / export-annotation-html
```

关键代码事实：

1. `ui/src/App.vue:927-933`：`llmReview / aiExtract / assemble / analyze / compose / annotationHtml` 六项默认**全部 true**（类型定义 915-922 行）。
2. `ui/src/App.vue:1963` 与 `:2096`：两处均为 `if (useLlm) stages.push("full-translation")`，**无任何 RunStages 门控**（对比：analyze 在 1958-1962 行有 `runStages.value.analyze &&` 门控）。`RunStages` 类型没有 `fullTranslation` 字段——用户无法用与其他阶段一致的方式关闭全文翻译；唯一门控是后端环境变量 `RATOMIZER_FULL_TRANSLATION`（`config.py:43`，默认 1）。
3. `desktop_tasks.py:2676-2686`：`functional_extract_enabled()` 时把 `ai-extract + functional-synthesis` 替换为 `functional-extract`；替换只重排 chain 阶段清单（相关落账 2732-2736），**不触碰 llm-review 的产物与记账**——A 轨审查费用照付，且 `functional-extract` 的输入（`blocks.jsonl / chunks.jsonl / doc_map.json`，1230 行）不消费 `llm_review_results.jsonl`。
4. `desktop_tasks.py:2718`：chain 中 assemble 仍传入真实 LLM route（`route if route != "stub" else None`），assemble 在 `llm_stages` 集合内（2741-2742），内部经 `assemble_spec.py:259,272-276` 调 `spec_enrich`。

**结论：默认行为不是 A/B 二选一，而是 A 轨审查 + A 轨富化 + B 轨直抽 + B 轨分析 + 全文翻译五条付费链叠加。它们共享解析产物，但不共享最昂贵的模型判断。**

### 5.3 claim ledger 流程（B 轨闭环）

`claim_catalog` 候选 → 专家 promote/exclude 决策（决策文件 v3，冻结 v1/v2 重放）→ `claim_ledger` 影子覆盖账本 → `claim_artifacts` 发布/哈希绑定 → burst-coalesced fold → `claim_queue_execution` 执行（预算 checkpoint 经 outbox 扇出到 attempt log + verifier WAL）→ `table_claim_authority` 终态权威 → 批注投影。

---

## 6. AI 实现方式

### 6.1 LLM 客户端基础设施（`llm_client.py`，1,227 行）

统一出口 `_post_json`：`max_retries=3`；**429 独立重试预算** `rate_limit_budget = max(8, max_attempts*2)`（≥8 次，`llm_client.py:39,1066`），退避 2/4/8/16/32s（`_retry_delay`:1209-1217），Retry-After 优先且封顶 60s；**AIMD 自适应限流闸门**（`_AdaptiveRateGate`:63-158：429 → 在飞砍半 + 全局冷却；连续 8 次成功 +1；按 base_url 跨线程共享；默认开）。

三个**全额重发放大器**（均已逐行验证）：

1. **截断升级**：`finish_reason=length` 或空响应时 `max_tokens` 倍升重发（6144→12288→24576→32768，封顶 `MAX_TOKENS_ESCALATION_CAP=32768`，`:58-61,1017-1043`）；每次升级用**同一个未变的 messages** 重建 payload 全额重发（`:965-993`）。起点 ≥4096 时最多 3 次升级；extract 场景下限被 `PURPOSE_MIN_TOKENS` 抬到 6144（`:22-36`）。
2. **JSON 修复**：解析失败后把「原 messages + 完整错误回复 + 修复指令」整体重发一次（`chat_json_messages`:637-665）；二次失败才抛 `LLMResponseError`；升级计数跨首发/修复共享。
3. **tool-loop 累积 transcript**：`chat_with_tools` 每轮把 assistant tool_calls（`:781`）与 tool 结果（`:813-817`）追加进 history，下轮经 `_chat_tools_once(config, history)`（`:734`）**完整重发全量 transcript**——prompt token 随轮次近似平方增长；库级默认 `max_rounds=8`（`:675`），schema 修复在 history 上续接并占一轮（`:761-772`），管线侧续调沿用 `meta["history"]` 与剩余轮数（`llm_pipeline.py:1037-1052`）。

token 计量只信 provider usage，缺失计 0 并标 `usage_complete=False`；`llm_trace.jsonl` 消息级追踪默认开。

### 6.2 A 轨评审（`llm_pipeline.py` + `review_pipeline.yaml`）

- `classify_risk` / `correct_errors` 均为 `executor: "tool_loop"`（yaml:38,43），`tool_loop_max_rounds: 5`（yaml:20）。
- 每需求 token 预算默认 20,000（`TOOL_LOOP_DEFAULT_TOKEN_BUDGET`，`llm_pipeline.py:75`）；5 个只读取证工具（kb_search / kb_get / blue_book_class / source_read / coverage_check）。
- **tool-loop 恒不批处理**（`batch_review_enabled`:129-138 明令注释）：`RATOMIZER_REVIEW_BATCH` 只对旧 single-shot 生效。实测 16 条合批仅 2 calls / 7,883 tokens，但该路径默认关闭。
- 理论封顶：`原子需求数 × 20,000` token，预算表给 llm_review 的子预算上限即 900 万 token。

### 6.3 B 轨直抽（`functional_extract.py`，当前默认主路径）

- `clause_family` 策略按目标条款逐包调用并附带邻近条款与 doc map 摘要；结果执行确定性 guard、守恒检查（M1 局部绑定）与来源验证。
- **付费缓存是文档级**（本轮已确认当前工作树，未提交改动只动了 prompt 版本与文案，缓存结构未变）：
  - `extraction_fingerprint`（180-213 行）：`"clauses": [clause_fingerprint(s) for s in sections]`（207 行）——**全部条款都进指纹**；
  - `_write_cache_entry`（1634-1672 行）：`entry = {"fingerprint", "payload"}`，payload 含整批 items（1954 行）；
  - `run_functional_extract`（1900-1960 行）：任一条款变化 → 整批 miss → 全部 sections 重跑。
- 对照：`ai_extract` 是章节级缓存（`section_fingerprint`:1652，逐章节追加 3842 行）——直抽反而比旧路径粗。

### 6.4 旧 B 轨（`ai_extract.py`，条件性放大器）

每章节付费结构（`extract_section`:3630-3696）：初抽 1 次（3659）+ 自检最多 3 轮（默认开，`RATOMIZER_AI_SELFCHECK_ROUNDS=3`，每轮 `critique_section` **重发整章原文**，2894 行）+ 复核 2 轮（默认开，`DEFAULT_VERIFY_ROUNDS=2`，每轮重发整章原文 + 全部已抽需求，3559-3571 行）= **每章节最多 6 次全额上下文调用**（盲查模式 4 次）。默认链中已被 functional-extract 整体替换；显式 `RATOMIZER_FUNCTIONAL_EXTRACT=0` 或单阶段调用时仍触发。

### 6.5 全文翻译（`full_translation.py` + 批注翻译）

多级恢复：贪心装包 → 批次 JSON 非法递归拆半（最多两轮）→ 缺条单条重试 → 单条失败切句段逐个调用；sidecar journal 持久化。适合最终交付质量，**不适合作为每次普通运行的默认阶段**。

### 6.6 LLM 调用方矩阵（26 个模块，12 条链路，8 个互不相通的缓存域）

| 链路 | 模块 | 默认链 | 调用粒度 | 缓存 |
|---|---|---:|---|---|
| A轨评审 | `llm_pipeline` + `review_tools` | 是 | 每需求 tool-loop | `llm-review-cache-v7`（单条失效） |
| A轨富化 | `spec_enrich` | 是 | batch + 缺槽单发 | `spec_enrich_cache.jsonl`（**裸 append**） |
| B轨直抽 | `functional_extract` | 是 | 文档级或条款族多包 | 整文档 payload（**文档级粒度**） |
| B轨分析 | `requirements_analysis` | 是 | batch 4 | `analyze-enrich-cache-v3`（meta 不匹配整份弃用） |
| 全文翻译 | `full_translation` | 是 | batch 10 + 三级恢复 | 内容哈希 sidecar（guards 零调用迁移） |
| 旧 B轨 | `ai_extract` | 被替换 | 每章节 ×最多6遍 | 章节缓存（**裸 append**，键拼 4 版本） |
| 定点抽取 | `spot_extract` | 用户触发 | 单 block/row | **无缓存，重复点击必调** |
| 条款族重抽 | `functional_reextract` + claim 队列 | 队列派发 | 条款族 | 同指纹缓存行刷新 |
| sidecar | `doc_map` / `reconcile` / `adjudicate` | 默认关 | — | doc_map 有内容指纹缓存 |
| agent 决策 | `agent_decider`（llm 模式 opt-in） | 否 | 决策 only | 无 |
| 预留 | `llm_table_understanding` | 未接线 | — | — |

### 6.7 预算控制面（`llm_budget.py`）

框架完整：分环节子预算（`DEFAULT_SUB_BUDGETS`:85-98）——structure_hypothesis 24/36万、functional_extract 36/72万（按条款数线性放大）、drilldown_adjudication 600/**900万**、clarification 60/60万、llm_review 600/**900万**、analyze_enrich 360/360万、spec_enrich 360/360万、full_translation 360/200万（旧 120-call 上限被 SBD 899 blocks 打爆后上调）、default 兜底 120/120万；80% 预警、耗尽降级、usage 完整性记录。

**但入口 `RATOMIZER_LLM_BUDGET` 默认 0（`config.py:86`）**：钩子不挂载（`llm_client.py:240,1074-1075`；`desktop_tasks.py:126-137`），默认运行时**不存在任何文档级 calls/token 封顶**——一个阶段超支不会阻止后续阶段继续付费。

---

## 7. 重复工作精确清单（"不简洁"的量化归因，全部实测）

| # | 横切关注点 | 重复规模 | 证据 |
|---|---|---|---|
| 1 | **原子写模式** | `os.replace` 52 处/31 文件；**13 个文件各自定义同名私有 `_replace_with_retry`**（adjudicate:880、ai_extract:222、artifact_store:73、clarification_check_states:259、desktop_tasks:1877、claim_artifacts:519、functional_extract:1674、orchestration_loop:676、llm_budget:716、result_package:340、review_state:906、reconcile:367、doc_map:416）+ ~9 处内联循环，共 **22 个文件**重复实现 | 仓库明明有 `process_file_lock.py` / `io_utils.py` 底座；仅 `functional_reextract:519` 跨模块复用私有函数 |
| 2 | **评审状态存储** | **5 套**各自实现状态机+锁+冲突异常+指纹+原子写：`review_state`（ReviewAuthorityConflict:52、VerificationStateConflict:957）、`ai_review_actions`（AIReviewAuthorityConflict:40）、`claim_review_actions`（ClaimReviewActionError:85、ClaimProjectionCasMismatch:89、ClaimAdjudicationCasMismatch:93）、`table_review_state`（TableReviewConflict:57-63）、`clarification_check_states`（无专属 Conflict 类，裸 ValueError） | 锁就有 3 种风格：process_file_lock、claim_publication_lock、`os.open(O_CREAT\|O_EXCL)` 锁文件 |
| 3 | **自定义 fingerprint 函数** | ~48 个 / 19 文件 | 如 `ai_review_actions._fingerprint_payload`:89 vs `table_review_state._fingerprint`:65 vs `omission_actions._canonical_hash`:58 |
| 4 | **定向重做路径** | 5 条各自实现 CAS/预算/失败语义：`spot_extract`（无任何机制）、`omission_actions`（CAS+预算+自建 kernel32 PID 存活锁:113-238）、`functional_reextract`（产物 sha256 CAS:363-372 + 四回调 WAL）、`claim_reextract_attempts`（预算 checkpoint+WAL）、`reconcile`（预算语义+自建重试） | `claim_queue_execution` 已把预算 checkpoint 与 attempt WAL 部分共享化（imports:13-52），证明收敛方向可行 |
| 5 | **LLM batch/修复/缓存逻辑** | ≥5 套镜像实现：`llm_pipeline` / `ai_extract` / `spec_enrich` / `requirements_analysis` / `doc_annotation_export`，并发、缺槽重试、JSON 修复、指纹、降级策略各不相同 | `spec_enrich.py:11` 注释自述"批处理逻辑与 llm_pipeline 重复，将来可抽 llm_batch 共用" |
| 6 | **行为版本常量** | **165 个 `*_VERSION` / 79 文件**，靠人肉纪律 bump 并手工钉进缓存指纹 | `claim_ledger.py` 单文件 21 个；`EXTRACT_GUARDS_VERSION` 拆分后仍留在 `ai_extract.py` 而非 `extract_guards.py` |
| 7 | **阶段编排真相** | 4 份：Vue `plannedAutomaticStages`、Vue 实际提交 stages、Python `CHAIN_ORDER`+替换规则、`ratomizer run` CLI 固定语义 | UI 计划、result package 声明、实际运行、CLI 之间可漂移 |
| 8 | **sha256 调用** | 657 处 / 81 文件 | claim_artifacts 单文件 215 处 |
| 9 | 杂项 | py-modules 3 处重复登记；根目录 278KB `!` 文件；`ARCHITECTURE.md` 默认值描述过时 | — |

**与 token 的关联**：#1/#2/#3/#4 不直接产生 provider token，但造成缓存策略不一致、版本失效范围扩大、同一文本跨链路重复调用；#5/#6/#7 直接导致重复付费与行为漂移。

---

## 8. Token 消耗根因（分级，全部经当前代码验证）

### P0 —— 默认链结构性重复付费

| # | 根因 | 证据 |
|---|---|---|
| P0-1 | A/B 双轨主要付费阶段默认同时执行（五链叠加） | §5.2；替换不取消 llm-review |
| P0-2 | 全文翻译隐式开启、无 UI 开关 | `App.vue:1963,2096`；`config.py:43` |
| P0-3 | 文档级总预算默认关闭，无封顶 | `config.py:86`；§6.7 |

### P1 —— 付费放大与缓存失效

| # | 根因 | 证据 |
|---|---|---|
| P1-1 | **缓存键捆绑高频 bump 的行为版本**：ai_extract 章节缓存键拼 prompt/guards/compliance/table-structure 四版本；`TABLE_STRUCTURE_VERSION` 两周 v6→v10 连 bump 5 次。**活例：当前工作树未提交改动把 `FUNCTIONAL_EXTRACT_PROMPT_VERSION` v2→v3（仅改两段 system prompt 文案），下次运行整个文档级直抽缓存全部作废、全额重付** | §6.3；git diff |
| P1-2 | functional-extract 缓存为文档级粒度，单条款变化 → 全文档重跑 | §6.3 |
| P1-3 | 阶段指纹混入无关配置：`desktop_tasks.py:1773-1788` 把翻译 batch、自检轮次等 15 个环境变量无差别放进**所有阶段**指纹（其他字段块均按阶段过滤，唯独 `llm` 块全阶段共享）——调 `RATOMIZER_TRANSLATE_BATCH` 会令 atomize 缓存失效 | §5.2；复核确认 |
| P1-4 | tool-loop transcript 累积重发（近似平方增长）+ schema 修复续接整份 transcript | §6.1-3 |
| P1-5 | 失败恢复整段重发：截断升级最多 3 次全额重发、JSON 修复一次全额重发；失败边缘章节实际付费 2–4 倍 | §6.1-1/2 |
| P1-6 | 付费缓存裸 append：`spec_enrich.append_cache`（332-337）与 `ai_extract.append_cache`（3710-3715）无锁无原子写——Windows 下尾部撕裂即 miss 即重付（仓库硬约束明令禁止此模式） | §6.6 |
| P1-7 | spot_extract 完全无缓存，重复点击同一 block 每次真调 LLM | `spot_extract.py:165-218` |
| P1-8 | 多套 LLM runner + 4 份编排真相 → 同类错误在不同阶段产生不同调用倍增行为 | §7-5/7 |

### P2 —— 条件性 / 长期结构风险

| # | 根因 | 说明 |
|---|---|---|
| P2-1 | 旧 ai-extract 每章节最多 6 次全额调用 | 默认链已替换；回退/显式路径仍触发（§6.4） |
| P2-2 | analyze enrich 缓存 meta 不匹配整份弃用 | `requirements_analysis.py:591-634` |
| P2-3 | 165 版本常量 + stage producer 人工同步 | §7-6 |
| P2-4 | 每调用固定开销大：~2 千字 system 指令 + doc_context（术语表 ≤1800 字）注入每一遍调用；analyze 轨已验证的前缀缓存友好排序/紧凑 JSON（省 15–25%）未复制到抽取轨 | — |
| P2-5 | **开发时上下文成本**：`CLAUDE.md` 已 224KB，`AGENTS.md` 要求非平凡任务先读——每个开发 agent 每次任务先烧一遍巨量上下文 token，且混有已被覆盖的历史结论 | "token 消耗异常高"同时包含运行时与开发时两个来源 |
| P2-6 | 平铺 129 模块 + 上帝文件 + 5 套评审存储 + 22 处原子写重复 | §2、§7 |

---

## 9. 实测数据与解读

`out/` 下仅有的 3 份 `llm_budget.json`（均为单阶段运行）：

| 运行目录 | full_translation calls | tokens | 说明 |
|---|---:|---:|---|
| `sbd-full-translation-v5-acceptance-360-20260811` | 345 | 1,048,945 | 未耗尽（上限 360/200万），needs_work=False |
| `sbd-full-translation-v5-acceptance-20260811` | 120 | 447,434 | 旧 120-call 上限被击穿（failed=1，exhausted，needs_work=True）——子预算上调的直接原因 |
| `sbd-full-translation-v5-acceptance-prompt-v5-20260811` | 40 | 204,133 | 缓存稳定后的增量轮 |

三组数据的正确解读：

1. 全文翻译本身可达**百万 token 级**；
2. 缓存稳定时增量重跑确实便宜（40 vs 498 calls 的量级差）；
3. **开发期版本变化和失败修复会反复触发大规模付费**（SBD 翻译从干净 v4 到 prompt/guards 返工三轮研发累计 498 calls / 1,583,211 tokens）——因此必须同时治理"默认是否执行"与"版本变化时是否必须重新调用模型"。

其他历史实测：抽取轨 781 次调用中 164 次 429（高并发与 provider 限流真实冲突；AIMD 闸门与 429 独立预算是此后加的缓解）。

---

## 10. 治理方案（分阶段，按收益/风险比排序）

### 阶段 0：建立真实成本基线（先于一切语义改动）

选三类代表文档（prose/tender、DLMS profile、表格密集型），分别按 A / B / Hybrid 运行，开启预算单（初始阈值宽松，先求可见性），记录每阶段 calls、prompt/completion tokens、cache hit/miss、retry 分类、429 次数、tool-loop 平均轮次、wall time、precision/recall/F1。

### 阶段 1：默认链立即止血（1–3 天，零语义风险）

1. 增加 `b_track` / `a_track` / `hybrid_audit` 三个 Profile；普通模式 A/B 互斥，Hybrid 显式选择。
2. `RunStages` 增加独立 `fullTranslation` 开关，默认关闭，仅最终交付时开启。
3. `RATOMIZER_LLM_BUDGET` 产品默认切开启。
4. 运行前展示预计阶段、calls、tokens 与最大重试放大系数。
5. B 轨运行不调度无消费者的 A 轨付费任务；A 轨运行不调度 B 轨直抽/分析。

预期收益：仅消除默认全文翻译一项，现有样本上即可避免约 105 万 token/文档。

### 阶段 2：缓存与成本控制面（1–2 周）

1. 阶段指纹改为按阶段声明 `config_dependencies`（修 `desktop_tasks.py:1773-1788` 的全阶段共享 `llm` 块）。
2. functional-extract 改**条款级模型响应缓存 + 文档级确定性合并**。
3. 付费缓存拆两层：`ModelResponseCache`（key = model + prompt 版本 + 输入哈希，value = 原始响应）+ `DerivedResultCache`（key = 原始响应哈希 + guard/compliance 版本）——guard-only bump 零调用本地重放，不再重新付费。需双写 + 回放验证上线。
4. 统一 `PaidCacheStore`，先消灭 `spec_enrich` / `ai_extract` 两处裸 append。
5. spot_extract 增加 block 文本哈希级缓存。
6. 重试路径记录 `retry_reason` 与额外 token，形成放大系数看板。
7. 保留翻译 guards 零调用重验迁移并补回归测试。

### 阶段 3：统一执行层（2–4 周）

`LLMJobRunner` 统一：route/model 解析、文档与阶段预算、并发与 AIMD、JSON/schema 修复、retry 分类与上限、usage/provenance、cache 读写、progress、ok/partial/failed 状态。业务阶段只提供输入单元、prompt operation、schema、deterministic guard、合并函数。tool-loop 优先裁剪工具回灌而非关工具（保留证据可追溯）。

### 阶段 4：编排统一与结构收敛（渐进，里程碑分离）

1. 后端生成唯一 `PipelinePlan`（profile + stages + paid 标记 + 预算），UI/CLI/bridge/manifest/result package 全部消费同一份。
2. 拆 `desktop_tasks.py`（CLI 定义/编排/manifest/fingerprint）与 `App.vue`（运行配置/任务状态/评审页面）。
3. 5 套评审存储归一；22 处原子写归一；重抽队列以 `claim_queue_execution` 的 CAS/WAL/预算机械为底座收敛。
4. 按聚类落包（claim/tables/functional/review/delivery/platform/compatibility），`packages.find` 替代手工 py-modules。
5. 版本常量收敛单一注册表；`CLAUDE.md` 压缩为现状摘要 + 按月 ADR。
6. 生产解析主路径真正消费 `parsers/` 的 DocumentIR 抽象。

**包重构与模型行为变更不得放同一里程碑；任何行为版本 bump 需走 golden `out/` 再生成 + drift 归零工作流。**

---

## 11. 不建议直接实施的优化（需 truth-set Go/No-Go）

1. verify 2→1 轮、self-check 3→2 轮——直接降召回语义（代码注释自述 verify 两轮召回约 55%、三轮约 70%）。
2. 在当前 tool-loop YAML 下强制开 single-shot review batch——绕过逐需求工具取证。
3. 删除工具 transcript 历史证据而不保留可审计摘要。
4. 只缓存模型原始响应而删除 guard 后产物缓存（两层并存才是目标）。
5. 为减少缓存失效而不 bump 确实影响行为的版本（违反仓库硬约束）。

---

## 12. 验收指标

| 指标 | 目标 |
|---|---:|
| B Profile 触发 A 轨 review/enrich 调用 | 0 |
| A Profile 触发 B 轨直抽/分析调用 | 0 |
| 非最终交付运行触发全文翻译 | 0 |
| 真实 LLM 调用纳入文档预算 | 100% |
| 相同输入、相同版本二次运行 provider calls | 0 |
| guard-only bump 在已有原始响应时 provider calls | 0 |
| 单条款变化后 functional-extract 重跑范围 | 变化条款及必要邻居 |
| 无关配置变化导致的阶段 cache miss | 0 |
| 付费缓存裸 append | 0 处 |
| Pipeline stage 计划来源 | 1 个 |
| usage/provenance 可追踪率 | 100% |
| A/B truth-set mandatory thresholds | 不低于当前基线 |

红线不降：anti-hallucination（宁漏勿错）、stub 不伪装 LLM 产物、provenance 不因缓存合并失真。

---

## 13. 对前序报告的 3 处口径修正

1. **"functional-extract 替换会取消已执行的 llm-review"——不成立。** 复核确认替换只重排 chain 阶段清单（`desktop_tasks.py:2676-2686`），`llm-review` 不在 CHAIN_ORDER 内、由 `run_pipeline_task` 单独执行，产物与 manifest 记账原样保留。**这反而坐实了双轨重复付费：A 轨 review 全额照付且结果无人消费。**
2. **"翻译 guards bump 必然全文重译"——过时。** `doc_annotation_export.py:3009-3033` 已实现零调用重验迁移：旧成功译文经当前确定性 drift guard 重验，通过者仅更新 `guards_version` 不调 LLM；只有渲染读取路径 fail-closed 需先经维护/生成路径迁移。
3. **"ai-extract 3–6 倍放大是当前默认链第一根因"——需限定。** 默认 `RATOMIZER_FUNCTIONAL_EXTRACT=1` 下 `ai-extract` 已被整体替换；6 倍放大属显式回退（`=0`）、单阶段调用与历史重跑路径的条件性风险。**当前默认链的第一根因是五条付费阶段叠加（P0-1）。**

---

## 14. 最终结论

> **Token 的最大即时浪费来自默认运行了不必要的完整阶段；最大迭代浪费来自缓存键与确定性后处理版本耦合；最大长期风险来自横切基础设施和编排逻辑没有单一归属。**

正确治理顺序：

```text
先消除默认重复链路（Profile 互斥 + 翻译 opt-in + 预算默认开）
  → 再修缓存粒度与指纹依赖（条款级缓存 + 两层付费缓存 + config_dependencies）
  → 再统一 LLM runner 与付费缓存（LLMJobRunner + PaidCacheStore）
  → 最后推进 package 级结构拆分与编排单一真相源（PipelinePlan）
```

若只继续压缩单个 prompt，而不动默认双轨、隐式全文翻译和缓存失效机制，token 成本只会有局部改善，无法消除异常波动。

---

### 附：本轮复核方法说明

- 三份前序报告的全部载荷性论断（UI 默认值、隐式翻译入链、CHAIN_ORDER 与替换逻辑、阶段指纹污染、llm_client 三类重发、tool-loop 不批处理、预算默认值、ai_extract 六遍结构、五套评审存储、22 处原子写、165 版本常量、文档级直抽缓存、裸 append、pyproject 重复登记、spot_extract 无缓存、enrich 缓存整份弃用、out/ 实测数字）均由独立并行复核确认，证据已内嵌正文。
- `functional_extract.py` 未提交改动经 git diff 核对：仅 prompt 版本 v2→v3 与两段 system prompt 文案，缓存结构未变。
- 本报告未修改任何业务代码，未执行回归测试。
