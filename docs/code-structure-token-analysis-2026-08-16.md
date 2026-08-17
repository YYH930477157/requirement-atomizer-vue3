# Requirement Atomizer 代码库结构与 Token 消耗深度分析报告

**调研对象**：`e:\Codex\requirement-atomizer-vue3`
**调研方式**：全仓静态源码分析（未修改任何文件）
**日期**：2026-08-16

---

## 1. 摘要

本报告验证了「仓库结构不简洁、存在大量重复工作、导致 token 消耗异常高」的判断——**两点均成立，且可精确归因**。

- **结构问题**：129 个扁平顶层模块以「每次修复/新特性 = 新增一个模块 + 一套自包含机制」的方式生长，导致评审状态、原子写、指纹计算、重抽队列、缓存失效五类横切关注点被反复实现。
- **Token 问题**：根源不是单次调用浪费，而是四个放大器叠加——**抽取轨多遍全额重发（3–6 倍）**、**缓存键捆绑高频 bump 版本（bump 即全量重付）**、**审查 tool-loop transcript 累积重发（近似平方增长）**、**全局预算开关默认关闭（消耗无封顶）**。

---

## 2. 量化概览

| 维度 | 数据 |
|---|---|
| 根目录扁平 `.py` 模块 | 129 个，约 86,422 行 |
| 顶层 `*_VERSION` 指纹常量 | 160 个，分布在 40+ 文件（`claim_ledger.py` 单文件 21 个） |
| LLM 调用方 | 约 26 个模块，跨 12 条链路、8 个缓存域 |
| 各自定义 `fingerprint` 函数的文件 | 17 个；`sha256` 出现 656 处 / 37 文件 |
| `os.replace` 原子写 | 51 处 / 25 个文件，`PermissionError` 重试在 25+ 文件各写一遍 |
| `desktop_tasks.py` 子命令 | 37 个（191KB）；`api_server.py` 约 47 条 if/elif 路由（3,426 行） |
| 最大后端文件 | `doc_annotation_export.py` 291KB、`claim_artifacts.py` 264KB、`ai_extract.py` 243KB、`claim_ledger.py` 201KB |
| 前端巨型单文件 | `ui/src/App.vue` 195KB、`DocumentReview.vue` 140KB、`FunctionalReview.vue` 98KB（仅 15 个源文件承载全部界面） |
| 规模参照（CLAUDE.md 实测） | 899 blocks 文档全文翻译三轮累计 498 calls / **1,583,211 tokens**；全量审查 781 calls 中 164 次 429 |

---

## 3. 目录结构与模块组织

### 3.1 根目录扁平模块聚类（129 个）

| 聚类 | 数量 | 职责 |
|---|---|---|
| **claim_* 账本系** | 19 | B-track 需求账本全生命周期：候选→发布→fold→队列执行→专家评审→结构决策→验收。仓库最庞大、切分最碎的聚类 |
| **table_* 表格系** | 8 | 表格物理还原→结构角色→处置→评审→局部重算，本可独立成包 |
| **requirements_analysis* 系** | 6 | B-track LLM 富化/防幻觉（`待澄清` 标记），已按后缀拆分但仍平铺 |
| **functional_* 系** | 5 | 条款级功能需求直抽/合成/重抽/下钻（当前生产主路径） |
| **cosem_* 系** | 4 | DLMS/COSEM 规格三层确定性装配（零 LLM） |
| **agent_* 系** | 7 | 有界决策环与评测，刻意独立于主管道 |
| **评审/裁决系** | 7 | 四套评审对象各配一套独立状态存储（详见 §8） |
| **重抽/补扫系** | 7 | 7 条平行的「定向重做」路径（详见 §8） |
| **spec_* / blue_book_* / doc_* / xlsx_* / 评测系 / 三库系 / 编排系 / 基础设施系** | 60+ | 规格富化导出、蓝皮书知识库、文档中间表示与批注导出、XLSX 输入探测、A/B 评测、统一检索、编排环、配置与 IO 底座 |

### 3.2 包结构（仅 4 个真正的包）

| 包 | 职责 |
|---|---|
| `parsers/` | 输入解析（DOCX/XLSX/PDF/HTML → DocumentIR） |
| `requirement_kb/` | 知识库：加载/检索/匹配/Obsidian 转换/蓝皮书报表 |
| `gui/` | **已冻结的 PySide6 GUI**，只读兼容旧输出 |
| `ui/` | 现役 Vue3+Electron 前端 |

另有 `tools/`（离线评测脚本：`ab_runner.py` 58KB、`shadow_run.py` 44KB 等）、`schemas/`（44 个 JSON Schema）、`tests/`（203 个测试文件）。

---

## 4. 核心组件与运行流程

### 4.1 入口点

| 入口 | 角色 |
|---|---|
| `cli.py` | 机器面 CLI（exit 0/2/3/4，stdout = UTF-8 JSON 信封） |
| `atomize.py` | A-track 原子化核心（3,020 行，深度耦合 `table_structure` 约 20 个符号） |
| `desktop_tasks.py` | Electron 任务桥 + 单命令编排，**CHAIN_ORDER 唯一定义处**（第 1201 行）+ stage_producer 版本戳注册（第 1378 行） |
| `api_server.py` | 本地评审 HTTP API（标准库 `http.server`，无框架，约 47 条路由纯 if/elif 分发） |
| `llm_pipeline.py` | LLM 评审管线（`llm_agents/review_pipeline.yaml` 驱动 + 有界工具环） |

Electron 前端 → `desktop_backend.py` → `desktop_tasks.py`（链编排）+ `api_server.py`（评审 API）。

### 4.2 主管道 CHAIN_ORDER 十阶段

`ai-extract` → `functional-extract` → `functional-synthesis` → `assemble` → `requirements-analysis` → `template-write` → `clarification-report` → `full-translation` → `compose` → `export-annotation-html`

### 4.3 三条抽取链路并存

- **B-track**（散文/标书文档主链）：`ai_extract.py`（`guards-v23`）全量抽取 → `requirements_analysis.py` 逐条富化
- **WS2 直抽**（当前默认生产路径，`RATOMIZER_FUNCTIONAL_EXTRACT=1` 时整体替换 ai-extract + functional-synthesis）：`functional_extract.py` 条款族级直抽 → `functional_requirements.json`
- **A-track**（DLMS profile 文档主链）：`atomize.py` 确定性原子化 → `llm_pipeline.py` 评审 → `assemble_spec.py` 装配 P1/P2/P3 三层 → `cosem_*` 出实现规格

### 4.4 缓存/指纹机制

`desktop_tasks.stage_producer()` 为每阶段拼生产者版本戳；各模块行为版本（160 个顶层 `*_VERSION` 常量）钉入缓存指纹。硬约束：改护栏行为必须 bump 版本，否则旧缓存静默绕过新行为——这是正确性设计，但代价是**确定性后处理的任何改动都在重付全部 LLM 成本**。

### 4.5 claim ledger 流程

`claim_catalog` 候选 → 专家 promote/exclude 决策（决策文件 v3 含冻结 v1/v2 重放）→ `claim_ledger.py` 影子覆盖账本 → `claim_artifacts.py` 发布/哈希绑定 → burst-coalesced fold → `claim_queue_execution.py` 执行（预算 checkpoint 经 outbox 扇出到 attempt log + verifier WAL）→ `table_claim_authority.py` 终态权威 → 批注投影。

---

## 5. 技术栈

| 层 | 技术 |
|---|---|
| Python 后端 | ≥3.11（本机 3.14）；运行时依赖仅 6 项：python-docx / PyYAML / openpyxl / pdfplumber / jsonschema / pywin32；HTTP 用标准库（无框架） |
| 测试 | `python -m unittest discover -s tests`（**不是 pytest**）；前端 vitest + vue-tsc |
| 前端 | Vue 3.5 + TypeScript 5.7 + Vite 6 + Electron 33 + naive-ui；文档渲染 pdfjs-dist / docx-preview / xlsx |
| 打包 | 后端 PyInstaller → `ratomizer-desktop.exe`；前端 electron-builder portable（Node 24 破坏 extract-zip 需手工解压 electron） |
| 资产 | 44 个 JSON Schema、`llm_agents/review_pipeline.yaml`、`domain_packs/dlms_cosem/`、`knowledge_bases/`、`obsidian-vault/` |

---

## 6. AI/LLM 实现方式

### 6.1 LLM 基础设施（`llm_client.py`，1,227 行）

- **统一出口** `_post_json`：`max_retries=3`；429 限流独立重试预算至少 8 次（退避 2,4,8…32s）；跨线程自适应限流闸门（AIMD）
- **截断自动升级**：`finish_reason=length` 或空响应时 `max_tokens` 翻倍重发（6144→12288→24576→32768，最多 3 次），**每次升级整条 prompt 全额重发**
- **JSON 修复回路**：解析失败时把「原 messages + assistant 回复 + 修复指令」整体重发一次，又是一次全额调用
- **tool-loop**：`chat_with_tools` 默认 8 轮上限（审查轨实际 5 轮、每需求预算 20,000 token）；**history 累积式回传**——每轮把此前全部 assistant/tool 消息原样重发，prompt token 随轮次近似平方增长
- **token 计量**：只信 provider 返回的 usage，缺失计 0 并标 `usage_complete=False`；`llm_trace.jsonl` 消息级追踪默认开启
- **文档级预算** `llm_budget.py`：分环节子预算（drilldown/review 各 900 万、analyze_enrich 360 万、full_translation 200 万……），但**入口开关 `RATOMIZER_LLM_BUDGET` 默认 `0` = 关闭**

### 6.2 LLM 调用方全景（26 个模块，12 条链路）

| 链路 | 模块 | 触发 | 缓存 |
|---|---|---|---|
| B-track 抽取 | `ai_extract.py`（+自检 critique 最多 3 轮 + 二遍复核默认 2 轮 + 术语表） | `ai-extract` 阶段 | 章节指纹缓存 |
| 功能直抽 | `functional_extract.py`（当前默认主路径） | `functional-extract` 阶段 | 条款指纹缓存 |
| 条款族重抽 | `functional_reextract.py` + `claim_queue_execution.py` | claim 队列派发 | 同指纹缓存行刷新 |
| 定点抽取 | `spot_extract.py` | 用户 UI 定点 | **无缓存，每次必调** |
| 需求富化 | `requirements_analysis.py`（默认关） | `requirements-analysis` 阶段 | `analyze-enrich-cache-v3` |
| 规格富化 | `spec_enrich.py` | assemble 后 | `spec_enrich_cache.jsonl` |
| A-track 评审 | `llm_pipeline.py` + `review_tools.py`（5 个只读工具） | 独立阶段/CLI | `llm-review-cache-v7` |
| 全文翻译 | `full_translation.py`（默认开） | `full-translation` 阶段 | 内容哈希缓存（与批注翻译共享） |
| 批注翻译 | `api_server.py` 翻译端点 + `doc_annotation_export.py` 批量 | 评审/导出按需 | 内容哈希缓存，guards 版本必须匹配 |
| agent 决策 | `agent_decider.py`（llm 模式 opt-in；rule 模式零 LLM） | `agent_loop.py --decider llm` | 无 |
| sidecar | `doc_map.py` / `reconcile.py` / `adjudicate.py`（均默认关） | 环境变量 opt-in | doc_map 有内容指纹缓存 |
| 预留 | `llm_table_understanding.py` | 当前无生产接线 | — |

### 6.3 缓存机制（8 个互不相通的域）

各缓存键均内嵌多个行为版本号——**bump 即整域作废**：

- `ai_extract_cache`：章节指纹 = 章节文本 + model + **ai-extract prompt / guards / compliance_schema / table-structure 四个版本拼接** + 上下文/引用/表骨架哈希
- `functional_extract_cache`：条款指纹 + guards + conservation 版本 + route + negative_k + 上下文策略
- `analyze_enrich_cache`：prompt/unfounded/format 版本 + model + 五段上下文；meta 不匹配整份弃用
- `llm-review-cache-v7`：稳定证据指纹 + REVIEW_TOOLS_VERSION + 需求整行哈希（v7 改进为单条失效）
- 翻译 sidecar：内容哈希，**guards 版本不匹配的条目整体丢弃**
- 另有 spec_enrich / doc_map / critique 缓存

**有效面**：版本不变时重跑是零 LLM 的（实测增量轮 40 calls / 20.4 万 tokens vs 全量 498 calls / 158 万 tokens）。问题集中在版本 bump 触发的整体作废与多轮重复投喂。

---

## 7. Token 消耗异常高的根因（按影响排序）

### 高影响

**R1 — B-track 抽取多遍全额重发（最大单一乘数）**
每章节付费路径 = 抽取 1 次 + 自检最多 3 轮（默认开）+ 二遍复核 2 轮（`DEFAULT_VERIFY_ROUNDS=2`，默认开）= **最多 6 次全额调用**，每轮完整重发整章文本 + 术语表 + 被引条款。代码注释自述 verify 两轮召回约 55%、三轮约 70%——用重复付费换召回，且 verify 无任何提前停机制。**实际付费约为基础抽取的 3–6 倍**。

**R2 — 付费缓存键捆绑高频 bump 的行为版本**
`section_cache_versions()` 把 4 个版本拼进每个章节缓存键；历史记录显示 `TABLE_STRUCTURE_VERSION` 两周 v6→v10 连 bump 5 次、`EXTRACT_GUARDS_VERSION` v18→v23、functional guards/conservation 一周三连 bump。**任一 bump → 全文档所有章节缓存作废、整文档付费重抽**。开发迭代期每次合并后重跑几乎必然全量付费。

**R3 — A-track 逐需求 tool-loop 审查**
每条需求 20,000 token 预算 × 5 轮工具环；transcript 累积式回传使 prompt token 随轮次近似平方增长；schema 修复轮续接整份 transcript。批量复核（`m2-review-v4-batch`）实测 16 条合批仅 2 calls / 7,883 tokens，但**默认关闭**（`RATOMIZER_REVIEW_BATCH` 空）。预算表给 review 的封顶就是 900 万 token——数百条需求单次审查数百万 token。

**R4 — 翻译 guards bump 触发整文档重译**
翻译有内容哈希缓存，但 `load_annotation_translations` 对 guards 版本不匹配的条目**整体丢弃而非逐条重验**（当前已到 `annotation-translation-guards-v5`）。full-translation 默认开、消费全文档所有可翻译 block。实测规模：899 blocks 三轮累计 158 万 tokens。

### 中影响

**R5 — 截断升级/JSON 修复/限流重试的付费放大**：截断升级最多 3 次、每次全额重发且 max_tokens 翻倍；JSON 修复重发一次全额上下文；429 独立重试至少 8 次。失败边缘的章节实际付费 2–4 倍。

**R6 — 平行链路不共享缓存**：同一文本可被 ai_extract、functional_extract、functional_reextract（按「宁多勿漏」整条款族重跑）、spot_extract（完全无缓存）、A-track 评审/富化分别付费，跨链路无复用机制。

**R7 — claim shadow verifier 第二遍全文档 LLM 通道**：开关默认 1 但预算闸默认 0 → 不执行；一旦被授权启用即在抽取成本上再叠一层（verifier 可 3 轮投票）。

### 低-中影响

**R8 — 每调用固定开销大**：约 2 千字 system 指令 + doc_context（术语表 ≤1800 字 + 大纲 60 条）注入每一章节的每一遍调用；analyze 轨已做的前缀缓存友好排序与紧凑 JSON（每调用省 15–25%）尚未复制到抽取轨。

**R9 — 已治理/边界路径**：json_mode 探测已记忆化、合批缺槽回退有界、agent Phase 1 零 LLM、stub/降级不重复付费——这类浪费已被此前修复堵住。

### 关键控制面发现

**`RATOMIZER_LLM_BUDGET` 默认关闭**：`llm_budget.py` 已有完整的分环节子预算、80% 预警/100% 降级语义和成本看板，但默认运行时全管道无任何全局 token 封顶——消耗既不可见也不可控。

---

## 8. 结构性重复工作（「不简洁」的精确归因）

### 8.1 四套评审轨道各自实现「状态机 + 指纹 + 锁」（最重）

`review_state.py`（53KB，atomic 状态机）、`ai_review_actions.py`（覆盖式裁决）、`claim_review_actions.py`（130KB）、`table_review_state.py`（乐观并发写），外加 `clarification_check_states.py` 与 `review_insights.py`。每套各持 jsonl、各定义冲突异常（三种 Conflict 类在 `api_server.py` 分别 import）、各写指纹函数——17 个文件各自定义 `fingerprint` 函数。

### 8.2 七条重抽/重算/复扫路径机制各异

`spot_extract` / `omission_actions.targeted_reextract` / `functional_reextract` / `claim_reextract_attempts` / `claim_quality_rescan` / `table_recompute` / `reconcile`——每条各自实现 CAS 指纹、预算扣减、失败语义。`claim_queue_execution.py` 已把部分 CAS/WAL/预算机械共享化，证明收敛方向可行，但 7 条入口仍未归一。

### 8.3 原子写模式被复制 25+ 次

`os.replace` 51 处 + `PermissionError` 线性重试在 25+ 文件各写一遍；仓库已有 `process_file_lock.py` / `artifact_store.py` / `io_utils.py` 底座但复用率低，甚至出现跨模块借用私有函数（`functional_reextract` 复用 `functional_extract._replace_with_retry`）。

### 8.4 扁平 129 模块 + 手工注册清单已出错

`pyproject.toml` `py-modules` 手工维护约 128 行，已出现 3 处重复注册（`doc_map`、`reconcile`、`adjudicate` 各登记两次）。

### 8.5 版本常量散乱 + 上帝文件 + 前端同构问题

160 个版本常量靠人肉纪律 bump；`EXTRACT_GUARDS_VERSION` 拆分后仍留在 `ai_extract.py` 而非 `extract_guards.py`。`desktop_tasks.py` 一个文件承担任务桥 + 37 子命令 + 编排 + 版本戳注册四种角色。前端 15 个源文件中 `App.vue` 195KB，组件化问题与后端镜像。

### 8.6 杂物

根目录存在名为 `!` 的 278KB 误产物文件（unittest 输出重定向）；`session-archive/`、`.pytest_cache/` 等陈旧痕迹。

---

## 9. 优化建议（按收益排序）

### 第一阶段：Token 降本（不动行为语义，可立即做）

| # | 措施 | 针对根因 | 预期收益 |
|---|---|---|---|
| 1 | **默认启用文档级预算单**（`RATOMIZER_LLM_BUDGET=1`），先让消耗可见、可封顶，按实测回填收紧子预算 | 控制面 | 可控性 |
| 2 | **付费缓存与确定性后处理解耦**：缓存改存模型原始响应，guards/compliance/table-structure 在命中后本地重放；只有 prompt 措辞/输入构造变化才轮换付费键 | R2 | **最大** |
| 3 | **抽取轨减轮**：verify 2→1 轮或抽样复核，且改发条目+必要原文片段；自检上限评估 3→2 | R1 | 高（3–6 倍乘数直接减半以上） |
| 4 | **审查批处理默认开启 + transcript 裁剪**：启用 `RATOMIZER_REVIEW_BATCH`（已有实测数据）；tool-loop 对早期轮次工具回灌做裁剪/摘要 | R3 | 高 |
| 5 | **翻译护栏 bump 时逐条重验**而非整体丢弃：用新护栏对「源文+既有译文」重跑确定性校验，通过则原地升级 | R4 | 高 |
| 6 | **局部化重抽**：spot_extract 增加缓存键（block_id+文本哈希+版本）；条款族重抽按受影响 block 缩小输入 | R6 | 中 |
| 7 | **截断升级加输入侧对策**：升级前先尝试切半章节/压缩输入，而非仅翻倍 max_tokens | R5 | 中 |
| 8 | **复用 analyze 轨已验证的 prompt 优化**（前缀友好排序/紧凑 JSON/doc_context 按章节相关性裁剪）到抽取轨 | R8 | 低-中 |

### 第二阶段：结构收敛（中期重构）

1. **统一 review-store 层**：四套评审状态机收敛为一套，schema 变体区分
2. **归一定向重做队列**：以 `claim_queue_execution.py` 的 CAS/WAL/预算机械为底座收敛 7 条重抽路径——同时消除同一文本多链路重复付费
3. **强制走原子写底座**：消灭 25+ 处重复的 `os.replace` 重试
4. **按聚类落包**：`claim_ledger/`、`tables/`、`functional/`、`review/` 等，用 `packages.find` 替代手工 `py-modules`（顺带修复 3 处重复注册）
5. **集中版本登记表**：160 个版本常量收敛到单一注册表，`stage_producer` 只读登记表
6. **上帝文件拆分**：desktop_tasks 拆 CLI 定义/编排/记账；api_server 引入路由表

### 第三阶段：低成本清理

删除根目录 `!` 文件；`EXTRACT_GUARDS_VERSION` 归位 `extract_guards.py`；blue_book 职责从顶层归位 `requirement_kb/`；清理 archive 目录。

---

## 10. 风险与验证建议

1. **先实测再动手**：以上根因排序基于静态分析。建议落地前开 `llm_trace.jsonl` + 预算单看板，对一份代表性文档做一次分环节消耗实测，验证 R1/R3 的实际占比，并核对本机环境中 `RATOMIZER_AI_SELFCHECK*`、`RATOMIZER_AI_VERIFY*`、`RATOMIZER_REVIEW_BATCH`、`RATOMIZER_LLM_BUDGET` 的实际取值——这些开关直接改变各根因权重。
2. **重构前先冻结版本常量**：任何缓存键或行为版本改动都会再次触发全量重跑，降本改造本身若伴随 bump，会短期推高而非降低 token。
3. **golden 基线是冻结的**：结构性重构需走 `codex/*` worktree + golden `out/` 再生成的既定工作流，merge 前 drift 必须为零或在 CLAUDE.md 逐项说明。
4. **R2 的 bump 频率统计**基于 CLAUDE.md/AGENTS.md 历史条目与当前 registry 版本号，未逐一核对 git 提交时间线。

---

**总评**：核心矛盾不是功能冗余（多数模块确有独立职责），而是**横切基础设施未收敛 + 聚类未成包 + 缓存失效机制与开发迭代速度冲突**。第一阶段的 8 项措施均不动行为语义、风险低，建议从「预算单开启 + 一次实测消耗画像」起步，用真实数据确定后续优先顺序。
