# 第二阶段交接单（quality-first 路由，2026-08-17 会话收尾）

**背景速览**：方案（`docs/quality-first-unit-routing-complete-plan-2026-08-16.md`）十六项中
15 项已落地并验证（本会话）；WS0 真值门禁已按用户授权执行，**FAIL（exit 2）→
`RATOMIZER_EXECUTION_POLICY` 默认保持 `legacy_combined` 不翻转**（详见
`docs/ws0-gate-result-2026-08-17.md`）。后端全量 3938 项测试仅余 4 项既有 golden
漂移（stash 双向验证与本工作无关）；前端 npm test 277 + build 绿。

## 第二阶段工作项（按建议顺序）

### 1. B 轨守恒修复：functional-extract 接 unit 级上下文（方案 §17）

**2026-08-17c 探针实证更新**（定点探针 3 次，实付约 3–5 元；产物 `out/probe3-items.json`、日志 `out/clause-family-probe*.log`）：
- ✅ **clause_family 修复 duplicates**（主根因之一）：56 节定点子集纯 LLM 路由零截断，duplicates PASS（legacy 文档级为 10+ 条重复组）。
- ✅ **guards-v6 已修表格标记伪影**（本轮落盘 + 5 测试绿）：引句剥离 `[TBL-NNNNNN]` 前缀后匹配；保真基线剔除表格 ID 数字（"000008" 假 blocking 消除）。
- ⚠️ **剩余失败全部落在表格块**（COSEM object_list 属性表、事件目录表）——按方案应路由 A 轨/上下文，但 **section 级路由不可行**：实查发现 `2 20 Control of` 等截断 section_path 撞名（50+ 不同小节共享同一 id），家族级表格占比判定会把 prose 混路由（一次空洞验证后已撤销该代码）。
- **修正后的正确粒度 = M1 的 block/unit 级路由**（extraction_units 本就是为此设计）：functional-extract 消费 unit_routing_decisions，表格单元出 B 轨输入与守恒基线，跳过清单进产物 meta。这是 M4/M5 执行接线的核心，工作量一个专注会话。
- 顺带发现：截断 section_path 撞名本身值得在 parse 侧复查（heading 截断使 duplicates 分组与路由键失真）。
- 现象（两次独立证实：M0 + 门禁）：deepseek-v4-flash 文档级大包直抽守恒确定性
  失败（duplicates=6，~236k tokens/轮的 2 个巨型请求）。
- 已就绪机械：`extraction_units.py`（单元模型）、`unit_router.py`（路由）、
  `routed_execution.py`、`routing_escalation.py`、`pipeline_contracts.py`、
  `pipeline_plan.py`（默认未翻）、`llm_job_runner.py`（含 attempt 账本）。
- 任务：把 B/Mixed 单元（或 clause_family）作为 functional-extract 的上下文输入，
  文档级结果由 unit 快照确定性重建；守恒仍在文档级；先 opt-in
  （`RATOMIZER_CONTEXT_PACK_STRATEGY=clause_family` 路径），truth 对比后再翻执行策略。
- 红线：truth-set 门禁通过前不翻默认（§31）。

### 2. 门禁 XLSX 读取器别名补齐（零付费，小改动）
- 现象：A 轨全链跑通（343 节 → 996 原子 → 1847 行成文），但
  `ab_runner._read_final_xlsx_rows` 在 V2.3.12 模板 sheet（计量需求/事件列表/
  费率列表/显示列表/曲线列表/Dataflash…）上正文列表头别名不命中 → fail-closed FAIL。
- 任务：拿到 A 轨成文 XLSX（重跑带 `--keep-dirs`，或先在本地对模板各 sheet 表头
  采样）后，把这些表头加入 `XLSX_COLUMN_ALIASES["body"]`；补单测。
- **状态（2026-08-17b）：已完成**——本地模板采样后定性为结构性缺口而非纯别名缺口：
  计量需求 sheet 的「需求」列被电表类型列拆分；9 个列表/meta sheet 根本不是需求
  sheet（无正文列头可加）；模板自带留空样例行（纯加别名会接着栽在空正文 FAIL）。
  修法 = 模板校准（`_load_template_extents` 行界剥离 annex/样例行，produced = 追加行）
  + 写入器列契约兜底（`template_writer.WRITER_COLUMN_CONTRACT`，读的正是写入器写的
  列位）；报告 schema v3；tests/test_ab_runner.py +8 测试；真实 V2.3.12 模板 E2E
  验证通过（missing_body 清零、section 正确读回、2046 行模板内容剥离）。详见
  CLAUDE.md 2026-08-17b 条目。重跑门禁前注意：第 1 项（B 轨守恒）仍未修，B 轨
  预期仍 FAIL。

### 2b.（已完成 2026-08-17c）A 轨缓存暖启动工具

`ab_runner --warm-a-cache <dir>`（0 元开发，tests 60/60 绿）：把上次 `--keep-dirs`
保留的 A_atoms 里的 `ai_extract_cache.jsonl` 复制进新 A 工作目录再跑——**整链仍真实
执行**（synthesis/analysis/template 全跑、成文 XLSX 端到端再生），仅抽取命中缓存零
付费；指纹含 route/model，不匹配自然全 miss（不自欺）。来源路径 + sha256 记入报告
`a_warm_cache`；目录缺缓存文件响亮 FileNotFoundError。

### 3. key 充值后重跑门禁（一条命令）
```
PYTHONPATH=. RATOMIZER_LLM_API_KEY=<key> python tools/ab_runner.py \
  --parsed-dir out/abnt_nbr_16968 --template "…V2.3.12….xlsx" \
  --route openai_compatible --keep-dirs --warm-a-cache <上次A_atoms目录> \
  --truth golden_sets/ws0_human_v1/truth.jsonl \
  --thresholds golden_sets/ws0_human_v1/thresholds.json --out out/ab-gate-report.json
```
- 真值/阈值已就位（用户已授权的 190 行 + 示例阈值）；成本大头 = A 轨 343 节抽取。
- 本会话末段 key 已 HTTP 402（额度耗尽）。

### 4. M9 大文件拆分（蓝图：docs/m9-split-plan-2026-08-17.md）

**2026-08-17d 进展**：第 2 刀已执行——`desktop_task_args.py`（parse_args 252 行 +
build_requirement_library_task 76 行，逐字搬运 + 重导出，py-modules 已登记）；
全量 patch 目标清单落盘 `out/m9-patch-targets.json`（api_server 20 / desktop_tasks
32 / ai_extract 25 / claim_review_actions 7）。**剩余大符号全部有模块内依赖**——后续
每一刀都是依赖簇级搬运（蓝图第 2-5 刀），必须独立会话 + 每刀独立提交。
- 顺序：api_server（20 patch 目标）→ desktop_tasks（32）→ ai_extract（25）→
  claim_review_actions（7，语义最重）。每刀独立提交 + 全量验证。
- 第 1 刀样板的教训：别名导入的 patch 目标是扫描盲区
  （`patch.object(dae, "…")`）；共享可变态与入口留原模块。

### 5. 可选：quality_first 主执行接线（M4/M5 之后）
- 依赖 1 的效果验证 + 3 的门禁 PASS；翻默认是独立提交（config 默认值 +
  `tests/test_pipeline_plan.py` 默认断言 + 文档 + golden 再生成流程）。

## 交接清单（本会话产物索引）

- 方案与决策：`docs/adr/2026-08-17-quality-first-unit-routing.md`
- M0 基线：`docs/m0-baseline-abnt-summary-2026-08-17.md`；shadow 统计：
  `docs/unit-routing-shadow-abnt-2026-08-17.md`
- 门禁：运行手册 `docs/ws0-truth-flip-runbook-2026-08-17.md`；结果
  `docs/ws0-gate-result-2026-08-17.md`；报告 `out/ab-gate-report.json`
- 拆分蓝图：`docs/m9-split-plan-2026-08-17.md`
- 真值/阈值：`golden_sets/ws0_human_v1/{truth.jsonl,thresholds.json}`
- 新模块：extraction_units / unit_router / routing_gaps / quality_gates /
  routed_execution / pipeline_contracts / pipeline_plan / routing_escalation /
  paid_cache_store / llm_job_runner / annotation_translations +
  tools/{m0_baseline,truth_from_review}
- 工作树未提交（遵守 AGENTS：未被要求不 commit）；分支 codex/table-translation-structure
