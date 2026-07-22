# CLAUDE.md — Requirement Atomizer 项目上下文

> 本文件供 Claude Code 在任何机器上自动加载。包含协作工作流、当前状态与关键决策。
> 状态快照截至 2026-07-22，里程碑推进后请同步更新本文件。

## 项目是什么

把技术标准文档（DOCX/XLSX/PDF）原子化为可审查的需求条目，**终点是装配成给研发团队的 DLMS/COSEM 实现规格**：
确定性解析 → 规则候选 → LLM 审查（OpenAI 兼容，本地/云端可切换）→ 专家工作台（**Vue3+Electron 桌面应用 + 本地 API**）→ 导出 / 装配实现规格（`assemble`/`compose`）。
CLI 契约见 `docs/cli-contract.md`（对接公司任务管理系统的接口承诺，exit 0/2/3/4，stdout 为 UTF-8 JSON 信封）。

## 协作工作流（重要）

1. **Claude 写修改方案**（带验收标准）→ 用户转交 ChatGPT/Codex 实现
2. **实现必须在隔离 git worktree**（分支 `codex/*`），审查通过前不合 main、不推送
3. **Claude 复查**：实测优先——mock HTTP 服务打故障场景、真实文档逐字节等价对比、打包产物在仓库外验证、GUI offscreen 截图
4. 用户决定合并；合并后在 main 跑全量测试（golden 六项只在 main 的 out/ 基线存在时执行）

> 2026-06-14 起「需求文档生成」轨道由 Claude 直接实现并自查（仍在 `codex/*` 分支、实测优先、用户决定合并、push 需用户同意）；解析等既有轨道沿用上面的 Codex 转交流程。
> 2026-06-27：**GUI 正式以 Vue3+Electron（`ui/`）为准，PySide6（`gui/`）冻结**；终点交付物（`assemble`/`compose` 实现规格）数据完整性修复由 Claude 直接实现并自查（同上轨道纪律）。
> 换机继续：项目上下文靠本文件 + `~/.claude/.../memory/` 自动加载；完整聊天 transcript 在 HOME `~/.claude/projects/<proj>/`，**不进代码仓**（含客户文档/业务细节，公开仓会泄密），如需带走走私有同步。

## 提交信息准则（每次推送必守）

每条 commit message 必须说清三件事，修复类提交按发现逐条列出"三段式"：

1. **原因**：为什么改——缺陷根因或需求来源（引用审查发现/问题单/真实案例）
2. **现象**：用户可观察到的症状——什么丢了、什么崩了、什么误导了，附 `file:line`
3. **解决方法**：修复机制（不是动作清单）——改了什么不变量、为什么这样修是对的

配套规则：

- 行为面变更（`EXTRACT_GUARDS_VERSION` / `*_PROMPT_VERSION` / `ENRICH_GUARDS_VERSION` / `LLM_REVIEW_CACHE_VERSION` / 策略指纹）必须在 message 中显式声明，并注明对缓存与 golden 基线的影响
- 推送前全量测试必须绿（`python -m unittest discover -s tests` + `cd ui && npm test`），message 不写未经测试验证的声明
- 已推送的历史不改写；信息写错了用新提交修正，不 amend/force-push

## 回归纪律

- `golden_sets/abnt_nbr_16968_v5/golden_summary.json` 是冻结基线；动它必须逐项写明原因
- 真实测试文档：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.docx`（机器相关路径，换机器需调整）
- 真实测试 PDF：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.pdf`（同目录文字层 PDF；旧 `D:\Codex\abnt_converted.pdf` 已失效）
- **Blue Book Ed.16 两 PDF**（P2 行为 RAG 语料，版权文件不进仓）：同目录 `Blue-Book-Ed-16-part-{1,2}-V1.0.pdf`；索引编译 `python -m blue_book_ingest --pdf <p1> --pdf <p2> --out out/bluebook`（约 2 分钟，产物 gitignored）
- 测试命令：`python -m unittest discover -s tests`（2026-07-19：**1344 tests** + ui `vitest 120` + vue-tsc；Python 3.14 / python-docx 1.2.0 / pdfplumber / openpyxl 已装；PySide6 未装时 GUI 测试 skip）。0 skip 需设 env `RATOMIZER_HISTORICAL_SAMPLE="C:/Users/YYHwudi/Desktop/Canna-29/eval_assets/test18_functional_synthesis_sample.json"`（历史守恒样本含客户词面已外置,不进仓;不设则 1 skip 如实降级）
- golden 基线输出 `out/abnt_nbr_16968_atomizer_v5/` 已于 2026-07-04 重新生成（真实 ABNT docx + **三个 --kb + domain-pack**，缺 KB 会假漂移）；测试用例只做 unittest.TestCase（**pytest 未装**，模块级 `def test_*` 会被静默跳过）
- **Node 24 环境坑（2026-07-17 实证）**：`extract-zip`/yauzl 在 Node v24 上**静默空转**（报成功不写文件），electron 的 install.js 因此 exit 0 但 `dist/` 只留 1 个文件——`npm run desktop:dev` 或直跑 electron 报 "Electron failed to install correctly"，且 `npm install` 重装无效（同一破损路径）。修法：PowerShell `Expand-Archive` 把 `%LOCALAPPDATA%\electron\Cache\<hash>\electron-v*-win32-x64.zip` 解进 `ui/node_modules/electron/dist`，再写 `ui/node_modules/electron/path.txt`（内容仅 `electron.exe`）；此后 install.js 幂等跳过，electron 升版本需重做一次。**打包不受影响**（electron-builder 自带 7zip 解压）。根治 = Node 降回 LTS 22 或等 extract-zip 修 Node 24 兼容。
- **KB 双轨口径（2026-07-07 实证裁定，勿混淆）**：**运行时**（CLI 默认 + GUI 预设）已收敛为单编译库 `compiled_from_obsidian.json`（三个种子库的富化超集：86 条目 id 100% 继承、6 条真实探针零丢失、四库并载会重复命中）；**golden 基线**仍按"三个种子 --kb + domain-pack"冻结生成**不动**——重生成时若改单编译库会假漂移。两者用途不同，并存是刻意的。种子 JSON 保留作轻量演示/定向调试。

## 重大更新（2026-07-22）——Agent 化 Phase 0 骨架（分支待复核）

- **范围边界**：本阶段不实现决策循环、不接 LLM 决策、不改 UI/既有状态账本；只冻结评测集、决策轨迹格式和策略版本锚点，Phase 1 未开始。
- **评测基线**：新增 `golden_sets/agent_eval_v1/` 共 20 条（分类 8、分组 4、必问 4、幻觉 4）。客户场景仅保留脱敏改写并登记仓库内证据来源；后三类 Phase 0 仅校验 schema/计数。现有确定性分类实测 `5/8=62.5%`，如实保留英文 battery、IP enclosure、仅文号审批三处错分。项目审核人已于 2026-07-22 逐条核对 `classify-001/003/005/006` 与 `must-ask-001`，manifest 仅登记这 5 条，runner 回归锁定不得改写人工审核字段。
- **冻结契约**：`agent_eval.py` 使用 JSON Schema 校验并输出 CLI JSON envelope；`schemas/decide_trace.schema.json` 冻结 `decide-trace-v1` 必填字段，`decide_trace.py` 按 `review_state.py` 同型跨进程锁在锁内 fsync 追加单行，并重试 Windows `PermissionError`。新增运行依赖 `jsonschema>=4.23.0`。
- **版本纪律**：`agent_policy.AGENT_POLICY_VERSION=agent-policy-v0`；`desktop_tasks.stage_producer()` 只为未来 `agent-*` 阶段预留该后缀，现有阶段 producer 字符串逐项不变，因此不触发已有缓存或 ABNT golden 失效。
- **验证**：Phase 0 聚焦 12 tests、全量后端 **1438 tests（26 skip）**、前端 **130 tests**、`vue-tsc` 与 Vite 临时目录构建、Python compileall 均通过；评测 CLI 输出 20 条计数及 62.5% 基线。

## 重大更新（2026-07-20）——test2 招标 PDF 解析、合规分流与审计闭环（分支待复核）

- **根因与边界**：test2 是 Google 机翻 PDF，词内空格是内容流里的真实空格字形，调 `x_tolerance` 无效；旧 `defragment_text` 又会把 `i s obliged`/`b e able` 链式误并为 `i sobliged`/`beable`，继而使来源引用锚定失败、真实需求被漏掉。修复坚持确定性和“宁漏勿猜”：结构编码仍只允许原文逐字锚定，无法唯一判断的残留只显示为审计信号，不自动改字。
- **PDF 文本修复 v2**：内置 `parsers/data/english_words_top50000.txt.gz` + 电表域词，按词频与唯一切分修复单字母碎片、粘连词、全大写缩写、拆分数字和假粗体；每块保留 `raw_text`、修复前后、规则与坐标，词表/算法 hash 纳入解析缓存和 PyInstaller 资源。质量报告区分“实际修复事件”与“保守疑似碎片”，避免把“修复器已无把握”误报为“文本已无缺陷”。行为版本 `PDF_TEXT_REPAIR_VERSION=pdf-text-repair-v2`，抽取 prompt/护栏升级为 `ai-extract-v21` / `guards-v9`。
- **来源与覆盖口径**：引用匹配改为空白不敏感、标点/数字/编码严格保留，支持 12 个相邻块及多摘录；`section_fallback` 不再虚标整章覆盖。覆盖拆成 `core` / `compliance` / `excluded` 三层；当前指纹仍匹配的专家 `non_requirement` triage 从 core/compliance 分母移出并在 excluded 留审计原因。fuzzy 映射和未验证 echo 不计覆盖，echo 使用与批注视图同源的确定性重复门；旧顶层字段继续代表 core，就绪门读取实时 core 覆盖率。
- **compliance 独立流转**：证书、法令、初始检定、符合性声明等不再挤入软件/硬件研发需求；输出 `compliance_requirements.json`、`compliance_items.json/md`，功能合成（`functional-synthesis-v6`）、软件分析和模板成文均防御性排除。结构分流只读原文证据，生成的 type/title/description 不能改覆盖分母；“技术义务 + 末尾证书/法令引用”的混合块保留在 core。umbrella 只由原文多个合规义务确定，instrument 错配不再静默替换且保留审计说明；合规义务也经过编码/数字/标准号漂移护栏。未处置合规漏项作为 blocking 内部核对项保留，不靠改分母掩盖。
- **审计与操作性**：质量报告记录失败章节及具体块，Vue/静态 HTML/PDF 热区均提供轻量“原文修复”“抽取失败”标记，点击可查修复前后与事件明细。内部核对新增按 signal/module 批量确认，整批在单锁内原子写入，每条必须匹配当前 `evidence_fingerprint`；stale/missing/ineligible/duplicate 分类汇报，409 会刷新证据并要求重新确认。模块自由文本前后端均限制为非空、最多 20 字；旧目录覆盖率明确标记 `legacy`。澄清报告版本为 `clarification/v6-coverage-basis`，一致性报告版本为 `merged-consistency/v2-triage-strict-evidence`。
- **跨文档模块沉淀**：模块控件支持自由文本 + 建议列表；后端 `/document` 返回 bank 词表且 Vue datalist 实际消费；已接受的 `module_override` 在裁决/API 导入后立即收割到 `RATOMIZER_ADJUDICATION_BANK`。样本库使用跨进程锁、Windows `PermissionError` 重试和原子替换，并记录模块使用计数；旧 bank 的 accepted 范例也可直接形成模块词表。
- **test2 确定性实测**：569 块中 408 块发生修复，共 4723 个修复事件；同一保守探针的疑似断词率 `24.91% -> 1.93%`（4333 -> 246），重复运行的块正文、原文和修复事件逐块一致。复用旧 127 条真实 AI 需求映射到新块做离线链路核验：core `119/162=73.46%`、compliance `6/6=100%`、excluded 7；独立合规条目 3（其中一个 umbrella 含 5 项义务），DLMS/COSEM over IP 双向通信探针命中。按当前确定性功能合成后有 121 条研发分析项且无 compliance 混入。就绪门仍为 `NEEDS WORK`：158 条内部核对尚未处置，其中 48 条 blocking，且普通待澄清量超阈值；core 覆盖率已通过 60% 门槛。
- **诚实限制与合并纪律**：本轮无可用 LLM/API Key，未执行 `ai-extract-v21` 的 test2 在线全量复抽；上述需求侧指标是旧真实抽取结果的离线重锚定，只验证确定性后处理与分流，不宣称验证新 prompt 召回。隔离 worktree 全量为 **1415 unittest（26 skip）+ 130 vitest + vue-tsc/Vite build**；`git diff --check` 与 Python compileall 通过。golden 文件未修改；合入 main 后必须按三个种子 KB + domain-pack 重生成 main 的 ABNT 输出并完成 golden 零漂移或逐项说明，才算最终合并完成。

## 重大更新（2026-07-19）——审查并行化与遗漏闭环（已合并 main `26a72f7`）

- **运行中增量审查**：AI 抽取逐终态章节发布 `ai_requirements.partial.json`，前端按章节进度节流刷新需求与 PDF 标记，复用已加载页图；早期裁决绑定需求 id + 来源/审查内容指纹，内容变化后保留历史但强制复核。final 新增 `ai_requirements.meta.json` 绑定 `blocks.jsonl` 代际，stale partial/final 不得跨文档回退。
- **澄清闭环**：必答拆为问客户/内部核对，内部核对用 `verified_ok / issue_confirmed / deferred` 审计状态；只有证据指纹仍匹配的 `verified_ok` 和客户答复可消解就绪门/进入分析权威输入。就绪门分开统计阻塞项、普通问题、内部核对、覆盖率与失败章节；旧工作簿在写入前校验新版列。
- **遗漏可行动**：`omission_states.jsonl` 记录非需求/确认遗漏/已补抽；定点补抽只跑目标章节并走原抽取护栏，补丁以策略、原需求、全部来源块和前置条件指纹约束，版本为 `ai-supplement-v3-identity-preconditions`。补抽会刷新 AI final 代际、质量覆盖率、merged spec 与下游输入指纹；full/targeted/下游消费共享跨进程 lease。
- **翻译降级与缓存纪律**：批量失败后按单条、再按句段重试，每级过同一数字/编码护栏；旧 accepted 译文先以当前 guards 零调用复验，迁移前不展示。存在 unresolved/failed call 时 `export-annotation-html` manifest 记 `partial`，下次 chain 必须重跑；producer 动态纳入翻译策略与 guards 版本。
- **专家操作效率**：文档审查支持 `j/k` 顺序导航与 `a/r/d` 裁决，输入框/IME/重复键防误触；同输出目录 API 重连保留选中项和按 requirement/block id 暂存的评论、模块、归属、遗漏备注，异步响应均有 client/generation 护栏，结构化 409 会刷新当前证据。
- **验证**：历史样本启用的后端 `1341 tests`（0 skip）、前端 `vitest 120`、`vue-tsc + vite build`、Python/Node 语法检查与 `git diff --check` 全部通过；golden 文件未修改。

## 重大更新（2026-06-27）

- **GUI 决策（已拍板，勿重新讨论）**：仓库里 PySide6（`gui/`）与 Vue3+Electron（`ui/`）两套 GUI 并存，**正式产品以 Vue3+Electron 为准**，PySide6（`gui/`）**冻结、不再投入**。GUI 改动只动 `ui/`，不碰 `gui/`。下文历史段里凡写「专家工作台(PySide6)」均指已冻结的旧壳。
- **平台架构演进（以 `README.md` 为最新）**：核心 Python（`atomize`/`cli`/`assemble_spec`/`engineering_composer`）+ **本地 API `api_server.py`**（只读 + 审查写入端点，origin allowlist + 可选 token）+ **Electron 任务桥 `desktop_tasks.py`** + **Vue3+Electron UI `ui/`**；知识库迁为 **`requirement_kb/` 包**（Obsidian vault → 编译 JSON）；解析器在 **`parsers/`**（docx/xlsx/pdf）。
- **终点交付物数据完整性修复（Phase 1+2，分支 `codex/spec-data-integrity`）**：一轮严格 code review 发现并修复 5 项直接污染研发实现规格的缺陷——
  - **H1 OBIS 静默拆码**：`cosem_object_model._normalize_single_obis_value` 移除无证据的「2 位值组拆单数字」（会把 `0-0:96.1.0` 静默腐蚀成 `0-0:9.6.1.0`，违反"OBIS 错一位即严重"）；缺分隔点的修复改走空格还原路径（仅在有空格证据时）。
  - **H4 访问权限错列**：`parse_access` 切不出 4 段时不再把整串塞 RC 列；新增统一 `access_cells()` 渲染（cosem MD/CSV + `assemble_spec` 门限表共用），四列留空 + 新增 `access_raw` 列追溯 + MD 未解析附录。真实 ABNT 1425 行 **0 错列**（`Association LN.add_user -/-/-A--` 入待审附录）。
  - **公式注入**：新增 `text_normalize.formula_safe()`，中和 Excel/CSV 里 `= + - @` 开头单元格（豁免纯数字与 DLMS 访问码），应用于 `spec_excel` 与 cosem CSV 导出。
  - **H2 审查校验绕过**：`llm_review_schema` 把必填字段 `None` 视为缺失，恢复 schema 修复回路（此前 `decision=None`/`confidence=None` 静默过校验）。
  - **H3 KB id 遮蔽**：`requirement_kb.repository.get()` 改首个/权威优先 + 新增 `id_collisions()` 暴露冲突（默认 4 库 86 处），不再随加载顺序静默遮蔽权威条目。
  - 验收：**全量 416 tests 全绿**（含各项新增回归），atomize golden 未动，真实 ABNT 端到端 `assemble` 注入样本 0 活公式。
- **Phase 3 端到端硬化与 gui 冻结（分支 `codex/phase3-golden-and-freeze`）**：
  - **P3-A 终点交付物 golden 回归**（`tests/test_spec_deliverable_regression.py`）：合成 fixture（含 H1/H4/注入触发场景）端到端跑 `assemble`→Excel，锁定 OBIS 稳定 / access 零泄漏 + `unresolved_access` 计数 / Excel 零活公式 / 计数。fresh-clone 可跑——把 Phase 1+2 修复变成永久回归（此前终点交付物零回归保护）。
  - **P3-B 解耦 `review_actions`**：从 `gui/` 提升到顶层 `review_actions.py`，`api_server` 改 import，`gui/` 成无人依赖的纯 PySide6 叶子；`ui/package.json` 打包配置同步移除 `../gui` 拷贝（后端依赖已被顶层 `*.py` 覆盖）。
  - **P3-C Vue3 前端 5 项 UX 修**：API 错误体透出后端原因（不再只显示状态码）、`originalText` 回退 `source_context.paragraph_text`、`confidenceFilter` 默认「全部」、审查按钮 `isSubmitting` 防抖、审查意见 textarea 接 `v-model` 并作为 `reason` 提交。`vitest 39 + vue-tsc` 全绿。
  - **P3-D gui 冻结**：README 标注 `gui/` 冻结。**保留代码/入口/测试**（冻结≠删除；`test_platform_scaffold` 契约化了 `ratomizer-gui` 入口，且不删能跑的东西）。
  - 验收：**Python 420 tests + ui vitest 39 + vue-tsc** 全绿。
- **测试规模**：196 → **420 tests**（`python -m unittest discover -s tests`）+ ui `vitest 39`。

## 重大更新（2026-07-04）——AI 抽取轨 + agent 化四方向全部落地

- **AI 主抽双引擎轨（`ai_extract.py`，2026-07 上旬）**：LLM 逐章节抽行为需求 + 确定性结构需求合并 → `ai_requirements.jsonl` / `merged_spec_requirements.json` / `merged_spec.xlsx`。上下文工程（`build_doc_context`：表计画像+术语表+大纲注入每章，折进缓存指纹）；**自检收敛循环**（定向模式 loop-until-dry，默认 3 轮硬顶 6，env `RATOMIZER_AI_SELFCHECK_ROUNDS`；盲查单趟防过度生成）；防幻觉分级护栏（code_drift 严拦 / int_drift 软标，基线=章节原文）；prompt v6（dev_guidance 研发指引）。
- **文档批注闭环**：批注视图（Vue `DocumentReview` + 可分享自包含 HTML）——段落级锚点、归属/模块下拉、suspicion 徽章；裁决写 `ai_review_states.jsonl`（内容稳定 AIR-sha1 id）→ `rebuild_merged_spec` 免 LLM 重建交付物（rejected 剔除、override 生效）。
- **软件需求分析轨（`requirements_analysis.py`，GLM 实现 + 多轮复查修复）**：软/硬/协同归属分类（规则初判+专家改判）→ `software_requirements.xlsx`（公司模板版式）+ hardware/co_design 清单；**LLM 富化层**（openai_compatible）推导可研发正文——结构/归属/id 冻结、编码硬拒/整数软标、无 key 如实降级 stub、内容指纹缓存、**并发+增量落盘+逐条进度**（288 条真实规模跑挂的教训：串行数小时+零落盘）。
- **全局一致性 critic（`merged_consistency.py`，确定性零 LLM）**：合并后产 `consistency_report.json`（跨章重复/OBIS 共引数值待核/覆盖缺口）；**已闭环**——摘要进跑完消息、批注视图行带 `consistency_flags` 标记。
- **裁决学习回路（`review_insights.py`，确定性零 LLM）**：从 module/ownership override 模式提炼规则改进建议（≥3 次成建议，人审采纳），裁决回流自动刷新 `review_insights.json/md`。
- **P2 行为层 RAG（Blue Book，GLM 实现 + 验收修复）**：`blue_book_ingest`（两 PDF 确定性编译 98 接口类+70 OBIS 节，逐字节可复现）→ `blue_book_lookup`（class_id/类名**精确**查找，不猜）→ `spec_enrich` P3 富化注入条款（出处程序校验+补写、drift 基线扩至条款、指纹折条款 hash）。桌面**自动探测**（`resolve_blue_book_index`：显式>env `RATOMIZER_BLUE_BOOK_INDEX`>out_dir>仓库 out/bluebook）。真实验收：ABNT 端到端注入出处逐条核对全过。**检索是确定性查找而非向量语义（刻意）**：宁漏勿错；语义回退留作将来升级路径。
- **GUI「运行」= 可配置整链**：4 个交付物按钮合并——设置面板「运行阶段」勾选（AI抽取/装配/分析/组装，localStorage 持久化），点「运行」按依赖顺序跑完；顶栏「LLM」勾选统一控 openai_compatible 路由；逐阶段进度（analyze 富化 n/total）。
- **LLM 端点（本机）**：小米 MiMo `https://token-plan-cn.xiaomimimo.com/v1`（`mimo-v2.5`/`mimo-v2.5-pro`，推理模型）；**该端点只认 `x-api-key` 头**——`llm_client` 已双头同发兼容。密钥经 GUI 设置面板 safeStorage 加密存、内存解密注入 env，绝不落盘。
- **双轨行为需求分工（建议已记录，终局待用户拍板）**：`assemble`（A 轨：atoms+llm_review，P1-P5）= **DLMS profile 类文档**的结构规格主交付物（蓝皮书行为富化挂此轨）；`merged_spec`+`analyze`（B 轨：AI 抽取+批注裁决）= **非 DLMS 剖面类文档**（散文型标准，无 COSEM 对象表，如 AFD/SM-CG 附加功能标准）的行为/软件需求主交付物。两轨并存各司其职，交付时按文档类型选主件。
- **有据缓建（实测量化为零收益，勿投机重启）**：① analyze 接蓝皮书——B 轨需求无接口类名可匹配（test5 多词类名 0/288）；② OBIS→class 连接提升蓝皮书覆盖——ABNT 行为 atom 正文 0 个 OBIS 形码（码全在表格→P1）；③ 类名归一化/别名——ABNT 未命中全是抽取噪声或 Green Book 领域引用，归一化救回 0 条；④ Part1 OBIS 节（70 节已摄入）——留给将来 OBIS 语义富化，暂无消费者。重启任一项前先在新语料上重跑探针。

## 重大更新（2026-07-15）——抽取质量重构七刀（已合 main）

- **背景与纪律**：用户裁定双线对比全遍历验收（工具 ≥ Claude 自身解析基线,整文档不抽样）+ 通用规则不打单文档补丁（fixtures 合成中性化,禁止测试文件作弊）。评测资产在 scratchpad `dual_track_eval/`（含客户内容**不进仓**）:units.jsonl 冻结坐标系 110 单元、reference_*.jsonl 参考基线 121 条、compare.py 对齐、4-agent 全遍历内容审计（A误读/B不自包含/C遗漏/D空话验收/E指引空转/F语言/G引用失真,好/中/差）。
- **七刀内容（15 commits）**：①目录子树打包 `pack_by_outline`（条款族=一条需求;test 标题绑前兄弟;三明治吸收水印夹层;ABNT 结构门 blocks=1362/items=2036 逐字节）②忠实性护栏族 `extract_guards`（情态升格/外标准号/定义桩/漏值窗口归一/数词与千分位基线）③自检并入契约（supplements 目标匹配+越界丢弃+锚定复核;未匹配转独立通道防漏抽）④数值配对+表文单元格一致性（表通道可靠文通道抄错:Type1 1 l/h→正文 5 l/h 实证）⑤**资料性附录跨单元状态机**（informative 区段条目降 P2+硬标——Annex B 对照表升格 9 条差评的最大病灶）⑥溯源节号原文回填（锚点必须自证质量:带点条款号/字母条款/Annex 行,裸整数图注不作证据——六刀自伤七刀修复的教训）⑦元话语句级剥除+去重加固（标点底座 J≥0.5+数字多重集守卫,校准实测恰好保住 1型/2型 异档判据）+情态确定性软化（should 引句的"必须"→"宜"）+RS232/EN 号整移豁免。prompt v18（免责从句保向/Q max 下标/单位词不猜译/步骤号配对复核）。
- **缓存指纹产品缺陷修复**：缓存存终处理结果而指纹只含 prompt 版本→护栏升级被旧缓存整体绕过（实测 wall=0s 零生效,GUI 用户升级即中招）。已修:`EXTRACT_GUARDS_VERSION` 折入 `section_fingerprint`,护栏行为变更必须 bump（现 guards-v4）。
- **三轮真实全量验证（EN 16314,mimo-v2.5-pro,每版 4-agent 整文遍历审计）**：条目 186(v1)→160、差评 17→12、A 误读 34→23、多抽 47→33、漏抽 14→13、拆碎 30→25;定义条目/自检碎片/同标签重复/标准号误归属假阳全部归零;资料性升格 9→0。**残余差评已收敛到 LLM 语义理解层**（免责从句反转/范围方向反转/one-or-more→全部/受试主体错置——prompt v18 针对性写入仍复发,mimo-v2.5-pro 能力边界）,用户已拍板走"第二遍 LLM 复核"（见下条,已合入）。
- **专家审核修复+回声锚点（2026-07-16 合入）**：①阶段续跑指纹缺口——verify 开关/轮数进 env 清单,producer 折入 guards+verify 版本（EXTRACT_GUARDS_VERSION 三次升级从未失效过阶段指纹,与缓存指纹同族的洞一并堵死,现 `ai-extract-v18+guards-v4+ai-verify-v1+impl-v3`）;②自检并入路径复用交付字段整移护栏（无据数字不再能经并入直进验收）;③**重复文本回声锚点**（电表招标实证:同段两处出现第二处无标注被误判"没解析出"）——`echo_block_ids` 视图层字段 api_server 单点计算双渲染器同源,匹配判据真实探针校准（全剥空白互含+原文近重复 J≥0.8+数字守卫）;用户裁定轻量显示:重复段只给"重复·见NN"角标+重复段卡片,不重复挂 chip,汇总层归并,parent_numbers 契约锁防倒退。**招标类文档教训**:名词短语式规格无情态动词,规则层 requirement_like/A 轨对其全盲,coverage_candidate 安全网同样失明——招标文档必须走 B 轨(AI 抽取)作主件;范围声明剔除正则只认 "this standard" 词面对 "this technical specification" 失配（侥幸留活,判据缺口已记录待跨文档探针）。测试 1198 unittest + 79 vitest。专家审核悬项:二遍复核自动改写、同名需求 by_title 对齐(碰撞挂错),等最小复现结论后修。
- **二遍语义复核轨（同日合入,用户拍板）**：每章节抽取+自检+折叠后 **N 轮复核投票**（默认 2 轮,`RATOMIZER_AI_VERIFY`/`RATOMIZER_AI_VERIFY_ROUNDS`,开关+版本+轮数折入缓存指纹）,只查七类误读受控清单（免责从句/方向/数量词/主体/数值配对/步骤号/归属）;发现须**双侧逐字锚定**才采纳为软标+证据留痕,自动改写仅当精确子串+过漂移守卫,绝不新增条目。实测:单轮对细微语义错误命中率仅 1/3（模型判断随机性,定点探针实证）;2 轮后三大慢性错类全部落网（温度方向/免责从句/one-or-more）,17 标记精度 ~60-73%（误报均软标）,10 改写零事实损伤,成本 +4min/链。轮数=召回/成本旋钮。
- **教训入库（testing-blind-spots）**：缓存类系统的确定性后处理版本必须进缓存键;护栏的覆盖动作必须要求锚点自证质量（六刀溯源校正把正确 D.3.3 改错）;suspicion 自标与真实缺陷相关性弱（真差评零自标,自标反是误杀）,软标分布不可当质量指标。
- 测试规模 **1174 unittest**;新增回归集中在 `tests/test_faithfulness_guards.py`（926 行）与 `tests/test_outline_packing.py`。

## 重大更新（2026-07-14）——整体 review 三批次：速度与效果 25 笔（已合 main）

- **量化依据（EN 16314 全量真实 trace）**：一轮 ~1030 次 LLM 调用累计 5.5h 模型时间;审查 371 次/147min 最大单项;抽取轨 164/781 次 429 限流(有效并发 3.2/4);富化两轨 66+34.5min 逐条调用。
- **速度**：审查并发接通 GUI 设置+全局默认 4→8;**富化合批**(软需同模块 `RATOMIZER_ANALYZE_BATCH`=4、硬件×2、装配无蓝皮书条目 `RATOMIZER_ENRICH_BATCH`=6;enrich_slot 槽位映射宁缺勿错、失败回退单条;缓存 key 逐条与批组成无关;护栏逐条不放宽——真 mimo 验收零串条);**429 自适应闸门**(`RATOMIZER_LLM_ADAPTIVE`,按端点全局冷却+在飞上限 AIMD);JSON 模式默认开(端点不支持 4xx 一次记住降级);分析 prompt 按稳定性降序重排吃 KV 前缀缓存;**缓存 key 收窄**(软背景 doc_context/siblings/exemplars 进 prompt 不进 key——背景漂移不再整库报废);裁决重建防抖(`RATOMIZER_REBUILD_DEBOUNCE_S`=1.5s);api_server 装配路径按源文件签名 memo(deepcopy 防串改);链内 8 阶段 summary 白算跳过。
- **效果**：冻结归属注入富化 prompt(analyze-llm-v6,模型只写不判);富化部分降级上屏(note+样本消息);**遗漏候选进澄清清单**(uncovered_samples 带 block_id 溯源,TIER_GAP 独立档不进就绪门,clarification/v3-gap-tier);**双渲染器信号补齐**(应用内补「所属研发功能」整块+跨章合并置信徽章≥2源/<0.9 警示;静态 HTML 补 consistency_flags;契约夹具锁三信号);**覆盖/遗漏统一口径** `merged_consistency.is_coverage_candidate`(剔除标题/引用书目/非正文假阳性;requirement_like 候选生成宽口径不动);**PDF 水印串确定性清除**(三清洗点;ABNT A/B 逐字节零变化、EN16314 61→0);guidance 模板编码软标 template-sourced(无声放行契约作废);review_insights 接通消费端(GET /review-insights+工作台「裁决复盘建议」卡);**裁决样本回灌抽取**(accepted→「模块+标题」few-shot,软背景不进指纹);functional_key 构造规则+priority 判级基准(ai-extract-v16,真实小样 P0/P1/P2 分级生效)。
- **数据否决记入有据缓建（勿投机重启,重启前重跑探针）**：⑤ 零 requirement_like 章节跳 LLM——省 35% 抽取调用但真实 158 条需求有 16 条(10%)完全来自这些单元(定义类条款规则认不出);⑥ assemble 内同文件读 2-4 遍去重——动 5 个 golden 邻接模块换每链 1-2s。
- 测试规模 **1082 unittest + 77 vitest**;新增回归集中在 `tests/test_batch{1,2,3}_0714.py`。

## 重大更新（2026-07-06）——TODO 全量清扫（架构债+组件增强）与深测裁决

- **架构债 F1-F8 全清**：chain 单命令编排+run_manifest（F1/F7，前日）；requirement_record 行契约+provenance 血统戳（F2）；xlsx 安全保存（F8）；llm_client 用途 floors 收口（F4）；config.ENV_REGISTRY 配置单源+强制核对测试（F5）；ai_extract 拆分 extract_units/extract_guards 门面保旧名（F3）；双渲染器共享契约夹具测试（F6）。系统地图见 `ARCHITECTURE.md`，待办勾选状态见 `TODO.md`。
- **组件增强落地**：裁决样本库 `adjudication_bank.py`（env RATOMIZER_ADJUDICATION_BANK，accepted→few-shot 注入富化，chain 尾自动收割）；**澄清答复回灌闭环**（必答 sheet 答复列→导入（GUI「导入澄清答复」）→富化注入+有据基线扩展→报告消解；真实往返验证：2 答复 46s 重跑仅重富化关联条）；Annex 引用解析 + 术语定向注入（prompt v11）；中英术语对照（每文档一次缓存）；JSON 模式开关（mimo 双模型探针支持 json_object）。
- **模型 A/B 裁决（勿重启）**：mimo-v2.5 vs pro 全量双跑——fast 覆盖率略高但漏值/重复/空话验收全劣，且并发限流下墙钟无优势（716s vs 741s，调用反翻倍）。**pro 保持默认**；数据 ab_arch/deep_test_result.json。
- v11 回归零倒退（覆盖率 65.8、失败 0、自检占比 14.1%）；测试规模 **744 unittest + 55 vitest**。

## 重大更新（2026-07-05）——B 轨终局架构：理解→分析→按公司模板成文

- **架构三轮裁定（用户）**：公司《电表软件标准化需求列表》V2.3.x 是**交付格式与知识源，不是问题库**——否决"问题库检索作答"（带着答案找问题）；终局链条：**理解**（AI 抽取按文档逻辑，地区无关）→ **分析**（analyze 轨：软/硬/协同+可研发正文）→ **成文**（`template_writer.py` 确定性零 LLM：分析结果按模板格式追加进对应模块 sheet，模板行原样保留、硬件跳过、无对应 sheet 落「其他需求(新增)」页）。桌面端设置面板可选模板路径（localStorage），运行链/测试运行自动接成文，产 `软件需求列表-成文.xlsx`。
- **模板知识注入（analyze-llm-v2）**：模板 19 sheet ~1160 行（描述/需求模版/**说明示例**——选项枚举/条件做法/固件宏名）运行时现读为公司知识（不进仓不落索引），富化 prompt 按模块+词面相关注入 top-8（`extract_template_knowledge`/`select_template_references`）；防搬运：需求正文数值只准客户有据（漂移基线故意不放宽），公司做法进 developer_guidance 带「公司通用做法：」标注。真实验收：注入路由 14/14 精确、30 条公司做法落指引、漂移拒绝 0。
- **抽取质量修复束（2026-07-04/05）**：跨章节引用解析（"given in 7.13.4.5.1"→被引条款注入+漂移有据）；数值落地（prompt v8 强规则+漏值检测 suspicion）；条款族切分（4.6.1 要求+4.6.2 测试同单元，prompt v9：条款族=一条需求+sub_items 二级+Test→验收）；批注三级标记（黄=引用依据/蓝=证据段/细条=分析上下文）+分层编号（01/01.a）+全局消息条。真实 ABNT 全量：覆盖率 81.2%、108 章仅 1 失败。
- 模板文件是公司资产：**绝不进仓**（与蓝皮书 PDF 同纪律），机器相关路径 `C:\Users\YYHwudi\Desktop\Canna-29\电表软件标准化需求列表-V2.3.12 - 2026-4-14..xlsx`。

## 历史状态（2026-06-16，已被上文覆盖）

- **已合入 main**：M1a CLI 契约、M1b GUI 审查工作台、M2 LLM 审查路由、M3 document_profile + PyInstaller 双 exe、M4a Excel 接入、M4b PDF 文字层、A1-PDF-1（`first_field_value` 去空格 fallback + `pdf_parser` 段落切分透传 document_profile，0.7.1）、GUI Phase 1 仪表盘重构 + 复查修订（`5f9e059`）
- **需求文档生成轨道 P1-P5 全部落地（2026-06-15）**：P1 数据字典 `cosem_object_model.py`、P2 访问/安全矩阵 `cosem_access_security.py`、P3 功能/行为派生 `cosem_behavior_spec.py`（已对齐公司格式 + 13 质量规则）、**P4 外部规范交叉引用索引 `cosem_external_refs.py`（`9f4e3be`，确定性零 LLM）**、P5 装配 `assemble_spec.py` + **人读导出 `spec_export.py`**（JSON 喂公司工具链 + Word/MD 人读规格：按功能域分组、带溯源、外部规范附录）；均有单测
- **生成器接入 GUI + 标签精化（2026-06-16，`e5815d1`，已推 origin）**：① 专家工作台应用栏「装配实现规格」按钮（`gui/pipeline_worker.AssembleSpecWorker` 复用后台线程）→ 结果对话框；② 左栏「实现规格」整段需求视图（`gui/spec_view.py`，按 21 领域分段、复用 `spec_export.group_by_domain`，与导出同分组）；③ **Excel 导出 `spec_excel.py`**（版式移植公司 requirement-analyst 技能的 `generate_excel`，逐 sheet 一致；装配默认产 JSON+xlsx+docx+md）；④ **标签精化**：`requirement_schema.map_labels` 按对象名分类、特定域优先于「通信协议」（事件记录/状态字排在计量前处理 current=当前 假朋友）+ `assemble_spec` P1 用对象名分类——**通信协议 388→77**，计量/事件记录/安全/门限范围/需量各就各位
- **剩余**：① P1-P5 + requirement_schema/text_normalize/spec_export/spec_excel 未注册进 pyproject `py-modules`（独立小清理；打包靠 ratomizer.spec 的 hiddenimports 兜住）；②（可选）**描述 LLM 富化**——Excel/规格版式已对齐 skill，但 `description` 仍是确定性模板，不如 skill 的 LLM 叙述丰富；富化时须保留 OBIS/CL/访问位等结构字段确定性不变（防幻觉）
- **本机环境（E:\Codex\requirement-atomizer-github，Python 3.14 + PySide6 6.11 / pdfplumber / openpyxl / pyinstaller 全装）**：196 tests 全绿；真实 docx/PDF 在 `C:\Users\YYHwudi\Desktop\Canna-29\`、golden 基线输出在 `out/abnt_nbr_16968_atomizer_v5/`（带三个 `--kb` 生成）
- **暂缓**：M4c 扫描件 OCR（等英文扫描件语料攒够再立项）

> A1-PDF-1 验收实测（2026-06-13，真实 ABNT 文档）：DOCX golden 六项全绿（DOCX-safe，fallback 仅精确匹配失败时触发）；PDF 候选 326→1991（达 DOCX 基线 2337 的 85%），`cosem_object_instance`=363 与 DOCX 精确相等；全量 128 tests 全绿。注意 golden 必须带三个 `--kb` 生成，否则 llm_tasks / 类型分布 / domain_table_candidate_ratio 会假漂移。

## 需求文档生成轨道（研发实现规格）—— 2026-06-14 立项

> 用户已确认：原子化只是中间产物，终点是把 atom 装配成给**研发团队**的可落地实现规格（据此实现 DLMS/COSEM 计量软件）。此轨道由 Claude 直接掌控实现。

- **目标分两层**：
  - 数据/配置层（对象模型、OBIS、class_id、访问矩阵 RC/PC/SC/LC、单位、事件枚举）——已在结构化字段，**装配优先**、可逐字段验证，是 DLMS 实现规格主体。
  - 行为/协议层（GET/SET/ACTION 语义、关联建立/HLS 握手状态机、加密策略、错误/access-result 码）——ABNT profile 多为交叉引用 DLMS Green/Blue Book，atom 里没有，需 LLM 派生 + 引进核心文档当 KB，**高幻觉风险**。
- **关键技术事实**：cosem atom 由 `table_item` 生成；结构化字段（OBIS、CL=class_id、属性、访问权限、单位）经 `source_refs → source_index → table_item.fields` 可确定性取回（GUI 详情面板已这么 join）；`verification_method` 已 denormalize 到每个 atom（验收/验证方法的种子）。**数据字典 = 确定性 join，不用重抽。**
- **范围真相**：单凭一份 ABNT profile 文档 → 极好的数据字典 + 访问矩阵，但行为/协议单薄；完整实现规格迟早要把 DLMS Green/Blue Book 作为额外输入/KB。
- **阶段（状态截至 2026-06-15，P1-P5 全完成）**：P1 数据字典 ✅ / P2 访问安全矩阵 ✅ / P3 功能行为派生 ✅（已对齐公司格式 + 13 质量规则）/ **P4 协议交叉引用 ✅**（C 折中：确定性引用索引，零 LLM；按 manifest 源文件名排除文档自身号；Green/Blue Book 俗称仅附 5-3/6-1/6-2 并标公开常识）/ **P5 装配 + 人读导出 ✅**（JSON + Word/MD/**Excel**，按功能域分组、带溯源、外部规范附录）。**已接入 GUI（2026-06-16，`e5815d1`）**：装配按钮 + 整段需求视图 + Excel 导出（对齐公司 skill `generate_excel` 版式）；标签精化使分段准确（通信协议 388→77）。
- **策略已定：装配优先**（契合"OBIS 码错一位是严重缺陷 / 数字双引擎"防幻觉纪律）。与 M4c OCR 正交。

## 下一步行动（2026-07-04 更新）

1. **专家实战反馈迭代**——用户/团队用新 exe 跑真实文档，review_insights 的建议累积后回改 map_labels/classify_ownership 规则；批注视图一致性标记的实用性验证。
2. **Green Book 引入**（行为/协议层第二本书）——散文语料无 class_id 键，需与蓝皮书不同的检索策略（术语倒排 or 受约束语义），先做小样探针再立项。
3. **GUI 富化结果展示**（可选）——analyze 的 software_requirement_text / 研发指引目前只在导出 xlsx，可加应用内视图。
4. **M4c 扫描件 OCR**——等英文扫描件语料攒够再立项（选型见下「关键产品决策」）。

## 关键产品决策（已拍板，勿重新讨论）

- 输入格式：Word(.docx)/Excel(.xlsx)/PDF；扫描件 PDF 占比大，OCR（M4c）必做
- 语言：**90% 英文，只做英文**；小语种全部挂起（将来倾向"先翻译后处理+原文对照"）
- LLM：统一 OpenAI 兼容客户端（`llm_client.py`），本地 Ollama / 云端 GLM 经 `llm_agents/review_pipeline.yaml` 切换；密钥只走环境变量；审查范围默认 targeted
- M4c OCR 选型方向：Tesseract（仅 eng 包）+ 框线表格 CV 切格逐格 OCR；ML 表格模型仅兜底；VLM 只做辅助纠错且数字/编码需双引擎一致（防幻觉，OBIS 码错一位是严重缺陷）；OCR 置信度直通 confidence/ambiguity → targeted 审查 → 专家队列
- 专家评审语义：`apply_expert_decision` 是裁决覆盖（除 frozen 外任意状态可改），自动管线走严格状态机

## 用户待办

- 攒英文扫描件 PDF 测试语料（5-10 份，不同扫描质量/表格密度/脏样本），M4c 立项用
- 第一份真实客户 Excel 到手后走 A1 差距报告流程（GPT 出报告 → Claude 技术筛查 → 用户拍板 → 再修）
