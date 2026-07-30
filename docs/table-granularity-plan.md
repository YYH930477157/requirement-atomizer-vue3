# 表格按表型智能混合分析（最终方案）

> 状态：Phase 2 口径已专家审核冻结（2026-07-29），Phase 1 可直接做、Phase 3 后置。
> 本文件合并自原三阶段总案 + `docs/param-row-extract-phase2-spec.md`（专家审核冻结规格，Phase 2 历史快照）。
> 实施：同事（Codex）在 `codex/*` worktree；审核：方案作者；复查：Claude。

## Context（为什么改）

当前管线把**整张表格压成一个 `type:"table"` block**，整表扁平文本（`atomize.py:936 render_table_text`）经 `extract_units.assemble_sections`（`extract_units.py:44`）拼进 `section.text`，LLM 把整表**当作一个文本 blob** 分析（`ai_extract.py:2784`），需求溯源也只能落到整表 block（`_map_requirement_source:1891`）。用户实证痛点：3×3 这类表"算作一个总的来分析"。

用户已拍板：改成**按表型智能混合**，**覆盖所有表格（docx/xlsx/pdf）**：
- 参数表/规格表（每行=一个对象，列是属性）→ **按行**各自独立分析
- 映射表/对照表/矩阵表（行列各为维度，每格=独立事实）→ **按格**各自独立分析
- 其他表型 → 默认**按行**（最安全，保留行内关联）

## 关键事实（影响方案）

- **行级基础设施约 80% 已就绪**：`table_items` 已每行一个（`item_id={table_id}-R{row}`，`atomize.py:361-424`）；`_row_render_line`（`ai_extract.py:862`）行渲染与块扁平文本逐字一致；`_supplement_parameter_table_rows`（`ai_extract.py:886`）已是"参数表每行一条需求"的确定性兜底；v12 行级影印热区已有（`doc_annotation_export._table_row_geometry:467`）；COSEM 装配已是行级 join（`cosem_object_model.source_fields`，键是 `item_id`）。
- **Claim Conservation Ledger 对表格本就是行级分母**（`claim_catalog.py` 按 `table_item` 建 claim）→ 行/格细化**无需重算 claim 分母**；只有 `merged_consistency` 的 block 级覆盖分母需注意口径。
- **缓存触发点**：`PARAM_ROW_EXPANSION_VERSION` 只是溯源戳、**不进** `section_fingerprint`；真正让抽取缓存失效的是 `EXTRACT_GUARDS_VERSION`（进 `section_fingerprint`，`ai_extract.py:1273`）。`section.text` 变 → 指纹变 → 旧抽取缓存自然失效。
- **整表 blob 的根因只在主抽取轨**（`assemble_sections` 咽喉 + `_map_requirement_source` 溯源）。

## 设计红线（贯穿三阶段）

1. **反幻觉**：按格的 cell 单元**必须带行列上下文**（`{列表头} | {行首标签} = {格值}`），**绝不裸格**——否则数值脱离名称、`≥16 字符 key_cell` 引句匹配（`ai_extract.py:933`）大量失配。
2. **block_id 稳定**：**不**把行/格升格为顶层 block（会推移所有 BLK 号、破坏持久化 `source_block_ids` 与几何缓存签名 `doc_annotation_export.py:303`）。行/格身份用已有 `item_id` / 新 `cell_id`，溯源记"表块 block_id + row_index [+ col_index]"。
3. **版本纪律**：行为变更一律 bump 版本并写进 commit message，声明缓存/golden 影响。

## 共享前置：通用表型分类器 `classify_table_kind`（三阶段共用底座）

在 `ai_extract.py`（约 842 行）新增 `classify_table_kind(block) -> "parameter" | "mapping_matrix" | "other"`，导出供 `extract_units` / `doc_annotation_export` / `assemble_spec` 复用。判据保守（宁漏勿错）：
- **parameter**：扩展后的要求类列正则 + 现有 `_is_parameter_table` 判据。
- **mapping_matrix**：①首列是维度标签（短编码/枚举/状态名）而非属性名；②表头是非属性维度结构且**不含**要求类列（与 parameter 互斥）；③数据格以短事实为主（中位长度 ≤~24 字符）；④≥2 行×2 列；⑤非术语/定义表。
- **other**：默认按行。
- **优先级**：parameter > mapping_matrix（参数表远多于映射表，按行更安全）。旧 `_is_parameter_table` 改为 `classify_table_kind(block)=="parameter"` 的薄包装，保 import 兼容。

---

## Phase 1 — 参数/规格表稳定按行（可直接做，低风险，可独立合并）

**改什么**
1. 扩展 `_PARAM_REQ_CELL_RE`（`ai_extract.py:833`）：补 `value|spec(ification)?|min(imum)?|max(imum)?|limit|rating|nominal|tolerance|range|unit|值|规格|额定|限值|最小|最大|公差|单位|范围`。
2. `_is_parameter_table`（`ai_extract.py:842`）微调放宽，让更多表命中；可加"数值+单位列占比高"的资格判据（只判资格，不参与引句，防数值脱锚）。
3. 落地 `classify_table_kind`（共享前置）。
4. 版本 bump：`PARAM_ROW_EXPANSION_VERSION` v1→v2（溯源）；`EXTRACT_GUARDS_VERSION` guards-v16→v17（classify_table_kind 是新护栏面，进 `section_fingerprint` 显式失效抽取缓存）。

**复用**：`_supplement_parameter_table_rows` / `_row_render_line` / `_row_name_cell` / `_PARAM_ROW_MIN_CELLS` 全部现成（已被 spot_extract、doc_annotation_export import）。

**如实说明**：Phase 1 保证参数/规格表**每行都成一条需求**（LLM 漏的行由 `_supplement_parameter_table_rows` 确定性补成 draft 进澄清）——"表格内容成片丢失"直接消除。**但 LLM 仍把整表当一个 blob 看**（`assemble_sections` 未改）。即 Phase 1 = 行级**覆盖率安全网**；"整表一个分析单元"的根本结构问题由 Phase 2 根治。

**影响面**：`blocks.jsonl` 不变 → 几何缓存签名稳定；`ai_requirements.jsonl` 的 `PROW-DET` 行变多 → **B 轨 golden 漂移**，须按"三 seed KB + domain-pack"重冻结；claim_catalog 不受影响。

**验收测试点**（unittest.TestCase）
- `test_param_req_regex_covers_english_headers`（Value/Spec/Min/Max/Limit/Rating/Nominal/Tolerance/Range/Unit 命中）
- `test_is_parameter_table_accepts_value_spec_headers` / `..._still_rejects_term_table`
- `test_classify_parameter_precedence_over_matrix`
- `test_supplement_covers_newly_qualified_table_rows`（原漏判的 Value 表每行产 PROW-DET draft，引句逐字=渲染行）
- 回归：既有 13 例参数表逐行展开测试零改动通过

---

## Phase 2 — 主抽取轨行级化（专家审核冻结版）

### 2.0 定位与实证依据

经 STO 真实数据尖刺确认存在**三条硬阻塞**，本节是其封堵设计——实施必须按 2.1–2.3 的冻结口径执行，否则不接受交付。实证依据（STO，2026-07-29）：

- 143 行参数表按 ~5k 字符切分为 3 chunk，**第 2、3 chunk 完全无表头**（LLM 将看到 104 行无列名上下文的内容）；
- 单文档行级 source_block 从 ~3 表块 → **337 个行级入口**，现有 68 条需求已带 130 条 suspicion，READY 门（`READY_MAX_QUESTIONS=30`）必被打爆；
- 行级 LLM 抽取（叙述体）与确定性行展开（逐字 PROW-DET）同行双份，无去重规则。

### 2.1 封堵一：chunk 表头重复（冻结口径）

行级展开进 `assemble_sections` 时，**表头行是表级元数据，不是第 0 数据行**：

- 行展开产物 = `table_header_line`（表头渲染行 + 表标题/所属节路径前缀）+ N 个数据行条目；
- 切分 chunk 时，**每个**包含某表数据行的 chunk，其首行**必须**是该表的 `table_header_line`（重复注入），后跟本 chunk 的数据行；
- `table_header_line` 不计入数据行计数、不产生 source_block、不参与需求锚定（它只是上下文）；引句匹配跳过它（防止表头行被当成某行的引句）；
- 单测钉死：143 行表切 3 chunk，三个 chunk 的首行都是表头行；且表头行不出现在任何 `source_blocks` 里。

### 2.2 封堵二：参数表需求形态与去重（冻结口径）

参数表的需求形态**一律为确定性逐字行**（guards-v16 既有路径），LLM 不产参数表行需求——结构化字段确定性裁决的铁律在此的具体化：

- 行级 `section.text` 仍送 LLM（保持叙述性段落与跨行关系的抽取完整性）；
- 后处理去重：LLM 需求若其最长实质单元格（沿用 guards-v16 的 key_cell 口径）命中某确定性展开行（PROW-DET 或将来由本阶段产生的确定性行）的渲染行文本 → 该 LLM 需求**不独立成行**，其叙述内容并入对应确定性行的 `llm_narrative` 可选字段（无则丢弃），并在 `merge_trace` 记一行审计（`llm_merged_into: <PROW-DET-id>`）；未命中任何确定性行的 LLM 需求正常成行；
- 确定性行覆盖判定失败时宁补勿漏（沿用现有 suspicion 进澄清）；
- schema：新增可选字段 `llm_narrative`（str）、`merge_trace`（list[dict]），向后兼容，block 级消费者零感知；
- 单测钉死：同行 LLM 需求不并列出现，叙述并入确定性行，审计行可追溯。

### 2.3 封堵三：澄清放大治理（冻结口径）

护栏逐行触发（语义正确，不改），**呈现与门控按表块聚合**：

- `clarification_report.collect_questions` 对同表块、同类型的行级 suspicion 聚合为**一条**汇总条目：`表格 <table_id>（<title>）：<reason> N 行待核`（明细挂 `row_details` 数组，行号+引句摘要，审核界面可展开）；
- 聚合条目在 READY 门计数中按 1 计；`row_details` 不改变 blocker_level/tier（取组内最高级别）；
- 聚合只适用于 `source_mapping: deterministic_fallback` 的行级条目（PROW-DET 系）；LLM 需求的 suspicion 维持逐条（它们是个体语义）；
- 验收硬口径：STO 全量重跑后，澄清必答条目总数增幅 ≤ 2x（基线 = 当前 result4 的必答数），且每张参数表最多一条行级汇总条目。

### 2.4 实施清单

1. `extract_units.assemble_sections`：按行级展开 + 2.1 表头重复；
2. `ai_extract._map_requirement_source`：`source_row_index`/`source_item_id` 可选字段；
3. `ai_extract` 后处理：2.2 去重与 `llm_narrative`/`merge_trace`；
4. `clarification_report`：2.3 行级聚合（`row_details` 进展开视图，xlsx/md 渲染列同步）；
5. 版本纪律：`EXTRACT_GUARDS_VERSION` → guards-v17（新护栏面，进 `section_fingerprint`）；ai-extract impl → v5（section.text 结构变）；`PARAM_ROW_EXPANSION_VERSION` 保持 v2；澄清报告有结构变化则 `clarification` 戳随行；全部进 chain 戳测试；
6. golden：合并后主检出用三 seed KB + domain-pack 重生成，漂移逐项说明。

### 2.5 验收清单（审核人逐项核对）

1. 全量测试绿（新增 ≥15 个 unittest.TestCase，覆盖 2.1–2.3 每个冻结点）；
2. STO 全量重跑实测：三 chunk 首行均为表头行；同行无 LLM/确定性双份且 `merge_trace` 一致；必答增幅 ≤ 2x、每参数表 ≤1 条行级汇总；参数表逐行需求引句逐字率 100%；
3. `blocks.jsonl` block_id 序列与改动前逐字一致（红线）；
4. 版本戳随行、chain 戳测试通过；golden 6/6（或逐项漂移说明）；
5. diff 范围：`extract_units.py`、`ai_extract.py`、`clarification_report.py`、schema（如需）、tests、文档；其余打回。

### 2.6 明确不做

- 不改 `blocks.jsonl` 结构、不造顶层行 block（红线）；
- 不动确定性行展开（guards-v16）生成逻辑，只加去重后处理；
- 不动 READY 门阈值（30/60%）本身——放大治理靠聚合不靠放水；
- Phase 3（mapping/cell）维持后置。

### 2.7 实施边界补充（复查关注点，**不覆盖**冻结口径）

1. **跨表 chunk**：2.1"每个含某表数据行的 chunk 首行必须是该表 `table_header_line`"——若一个 chunk 字符窗口同时含**两张表**的数据行（`assemble_sections` 按节聚合 + 字符切分，边界处可能碰到），首行注入须按"表切换"处理，不能只注入一张表头。罕见，建议补一例单测。
2. **2.2 key_cell 空值处置**：去重依赖"最长实质单元格 ≥16 字符"命中。**纯短值参数表**（全为不足 16 字符的数值/编码单元格）`key_cell` 为空 → 属"无法判定"而非"未命中"，去重失效仍双份。建议明确 key_cell 空时的回退判等（如整行渲染文本 compact 严格相等，或此类行默认偏好确定性行），以免短值表漏过去重。

---

## Phase 3 — 映射/对照表按格（cell 级，带行列上下文，后置）

**改什么**
1. `classify_table_kind` 的 mapping_matrix 判据落地。
2. 新增 cell 单元生成（`atomize.py:build_table_artifacts` 同区域或新函数，仅对 mapping_matrix 表）：`cell_id="{table_id}-R{row}-C{col}"`；`text="{col_header} | {row_header} = {cell_value}"`（**双表头上下文，绝不裸格**）；空/分组标题格跳过；产 `table_cell_items.jsonl`。
3. 接入抽取：`assemble_sections` 对 mapping_matrix 表按**格**展开（每 cell 一条 source_block，block_id=表块，cell_id 承载格身份）。
4. 溯源：`_map_requirement_source` 命中 cell 级 source_block 时落 `source_block_ids=[表块]` + 新增 `source_cell_id`/`source_row_index`/`source_col_index`。
5. 格级几何：`pdf_parser.extract_pdf`（`parsers/pdf_parser.py:858`）改读 `table.rows`/`table.cells` 取行 bbox + 单元格 bbox，写入 block 的 `cell_geometry`（docx/xlsx 由 row_geometry + 列均分近似派生，如实标注）；`_pdf_block_zones` 对 mapping_matrix 表发 cell 级热区。
6. 版本 bump：若 `cell_geometry` 进 block 字段则 atomize v7→v8；ai-extract impl v5→v6；`EXTRACT_GUARDS_VERSION` v18→v19；**几何缓存 version 4→5**；export-annotation-html 戳随动。

**COSEM 行 join 隔离（天然）**：COSEM join 只读 `table_items.jsonl`（键 `item_id`，行级）。cell 身份 `cell_id` 进独立 `table_cell_items.jsonl`，**不进** `build_source_index`；映射/对照表通常无 OBIS/class_id 属性列，不产 cosem atom → 隔离。本阶段显式**禁止** mapping_matrix 表进 `build_atomic_candidates` 的 cosem 路径，钉死隔离。

**验收测试点**：`test_classify_mapping_matrix` / `test_cell_text_carries_both_headers`（红线：无裸值）/ `test_cell_id_format` / `test_mapping_table_not_in_cosem_index`（隔离钉死）/ `test_pdf_cell_geometry_from_rows_cells`（mock pdfplumber）/ `test_cell_zone_routing`；回归 Phase 1/2 行级行为零变化、golden 6/6。

---

## worktree 策略 / 验证 / 合并纪律

| 阶段 | 主要触面 | 风险 | 收益 | worktree |
|---|---|---|---|---|
| Phase 1 + 共享前置 | `ai_extract.py` | 低 | 高/即时：参数表行级全覆盖 | `codex/param-row-regex`，可独立合 |
| Phase 2 | `extract_units.py`、`ai_extract.py`、`clarification_report.py`、schema | 中：改主抽取行为；需重冻结 golden | 高：根治"整表一个单元"+行级溯源 | `codex/row-level-extract` |
| Phase 3 | `atomize.py`/新模块、`parsers/pdf_parser.py`、`extract_units.py`、`ai_extract.py`、`doc_annotation_export.py` | 中高：新产物+格级几何 | 高：映射/矩阵表逐格 | `codex/cell-level-mapping` |

**关键风险对策**：①裸格幻觉 → cell.text 强制双表头 + 单测钉死；②block_id 漂移 → 不造顶层行/格 block，身份用 item_id/cell_id，`test_block_id_unchanged_*` 钉死；③golden 假漂移 → 每阶段用"三 seed KB + domain-pack"重生成；④几何缓存复用旧区 → Phase 3 改 cell_geometry 须 bump version 4→5；⑤覆盖分母误判 → block 级分母（merged_consistency）口径不变，claim 行级分母早已行级。

**验证（端到端）**：单测全 `unittest.TestCase`（`python -m unittest discover -s tests`）；实测优先——真实 ABNT docx 跑全链逐字节对比 `blocks.jsonl` block_id 序列不变；每阶段合并后 main 用"三 seed KB + domain-pack"重生成 ABNT 输出，golden 6/6；前端批注视图行/格热区与引句对齐（`ui` vitest + vue-tsc）；Phase 3 打包 spec 补 `table_cell_items` hiddenimports/数据文件。

**合并纪律（CLAUDE.md）**：每阶段独立 `codex/*` worktree；实测优先；行为面版本 bump 写进 commit message（三段式：原因/现象/解决方法）并声明缓存与 golden 影响；合并后 main 跑全量 + golden 6/6；已推送历史不改写。
