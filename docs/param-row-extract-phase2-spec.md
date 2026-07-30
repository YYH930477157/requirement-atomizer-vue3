# 主抽取轨行级化（Phase 2）可执行规格：三条实证阻塞的封堵设计

状态：已冻结，待实施（实施者：同事；审核人：本方案作者）
日期：2026-07-29
前置：同事方案 `joyful-waddling-manatee.md`（方向/红线/阶段划分全部沿用）；
guards-v16 参数表行展开、v12/v13 行级影印热区已合 main

## 0. 定位

同事方案的 Phase 1 可直接做（实证：STO 四表扩展前后命中一致、零误伤）。
Phase 2（主抽取轨行级化）经实证尖刺确认存在**三条硬阻塞**，本规格是其
封堵设计——实施范围只含 Phase 2，且必须按第 1–3 节的冻结口径执行，
否则不接受交付。

实证依据（STO 真实数据，2026-07-29）：

- 143 行参数表按 ~5k 字符切分为 3 chunk，**第 2、3 chunk 完全无表头**（LLM 将看到
  104 行无列名上下文的内容）；
- 单文档行级 source_block 从 ~3 表块 → **337 个行级入口**，现有 68 条需求已带
  130 条 suspicion，READY 门（`READY_MAX_QUESTIONS=30`）必被打爆；
- 行级 LLM 抽取（叙述体）与确定性行展开（逐字 PROW-DET）同行双份无去重规则。

## 1. 封堵一：chunk 表头重复（冻结口径）

行级展开进入 `assemble_sections` 时，**表头行是表级元数据，不是第 0 数据行**：

- 行展开产物 = `table_header_line`（表头渲染行 + 表标题/所属节路径前缀）+
  N 个数据行条目；
- 切分 chunk 时，**每个**包含某表数据行的 chunk，其首行**必须**是该表的
  `table_header_line`（重复注入），后跟本 chunk 的数据行；
- `table_header_line` 不计入数据行计数、不产生 source_block、不参与需求锚定
  （它只是上下文）；引句匹配跳过它（防止表头行被当成某行的引句）；
- 单测钉死：143 行表切 3 chunk，三个 chunk 的首行都是表头行；
  且表头行不出现在任何 `source_blocks` 里。

## 2. 封堵二：参数表需求形态与去重（冻结口径）

参数表的需求形态**一律为确定性逐字行**（guards-v16 既有路径），LLM 不产
参数表行需求——结构化字段确定性裁决的铁律在此的具体化：

- 行级 `section.text` 仍送 LLM（保持叙述性段落与跨行关系的抽取完整性）；
- 后处理去重：LLM 需求若其最长实质单元格（沿用 guards-v16 的 key_cell 口径）
  命中某确定性展开行（PROW-DET 或将来由本阶段产生的确定性行）的渲染行文本 →
  该 LLM 需求**不独立成行**，其叙述内容并入对应确定性行的
  `llm_narrative` 可选字段（无则丢弃），并在 `merge_trace` 记一行审计
  （`llm_merged_into: <PROW-DET-id>`）；未命中任何确定性行的 LLM 需求正常成行；
- 确定性行覆盖判定失败时宁补勿漏（沿用现有 suspicion 进澄清）；
- schema：新增可选字段 `llm_narrative`（str）、`merge_trace`（list[dict]），
  向后兼容，block 级消费者零感知；
- 单测钉死：同行 LLM 需求不并列出现，叙述并入确定性行，审计行可追溯。

## 3. 封堵三：澄清放大治理（冻结口径）

护栏逐行触发（语义正确，不改），**呈现与门控按表块聚合**：

- `clarification_report.collect_questions` 对同表块、同类型的行级 suspicion
  聚合为**一条**汇总条目：`表格 <table_id>（<title>）：<reason> N 行待核`
  （明细挂 `row_details` 数组，行号+引句摘要，审核界面可展开）；
- 聚合条目在 READY 门计数中按 1 计；`row_details` 不改变 blocker_level/tier
  （取组内最高级别）；
- 聚合只适用于 `source_mapping: deterministic_fallback` 的行级条目
  （PROW-DET 系）；LLM 需求的 suspicion 维持逐条（它们是个体语义）；
- 验收硬口径：STO 全量重跑后，澄清必答条目总数增幅 ≤ 2x（基线 = 当前
  result4 的必答数），且每张参数表最多一条行级汇总条目。

## 4. 实施内容（在同事方案 Phase 2 基础上的修订清单）

1. `extract_units.assemble_sections`：按同事方案行级展开 + 本规格第 1 节
   表头重复；
2. `ai_extract._map_requirement_source`：`source_row_index`/`source_item_id`
   可选字段（同事方案原样）；
3. `ai_extract` 后处理：第 2 节去重与 `llm_narrative`/`merge_trace`；
4. `clarification_report`：第 3 节行级聚合（`row_details` 进
   clarification_questions 的展开视图，xlsx/md 渲染列同步）；
5. 版本纪律：`EXTRACT_GUARDS_VERSION` → guards-v17（新护栏面，进
   `section_fingerprint`）；ai-extract impl → v5（section.text 结构变）；
   `PARAM_ROW_EXPANSION_VERSION` 保持 v2；澄清报告有结构变化则
   `clarification` 戳随行；全部进 chain 戳测试；
6. golden：合并后主检出用三 seed KB + domain-pack 重生成，漂移逐项说明。

## 5. 验收清单（审核人逐项核对）

1. 全量测试绿（新增 ≥15 个 unittest.TestCase，覆盖第 1–3 节每个冻结点）；
2. STO 全量重跑实测：
   - 三 chunk 首行均为表头行（打印验证）；
   - 同行无 LLM/确定性双份，`merge_trace` 审计行数与并合数一致；
   - 必答条目增幅 ≤ 2x，每参数表 ≤1 条行级汇总条目；
   - 参数表逐行需求引句逐字率 100%；
3. `blocks.jsonl` block_id 序列与改动前逐字一致（红线）；
4. 版本戳全部随行且 chain 戳测试通过；golden 6/6（或逐项漂移说明）；
5. diff 范围：`extract_units.py`、`ai_extract.py`、`clarification_report.py`、
   schema（如需）、tests、文档。其余打回。

## 6. 明确不做

- 不改 `blocks.jsonl` 结构、不造顶层行 block（同事方案红线）；
- 不动确定性行展开（guards-v16）的生成逻辑，只加去重后处理；
- 不动 READY 门阈值（30/60%）本身——放大治理靠聚合不靠放水；
- Phase 3（mapping/cell）维持后置，不在本阶段范围内。
