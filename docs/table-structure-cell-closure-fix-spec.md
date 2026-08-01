# 表格结构与单元格级需求闭环 —— 复审修复规格（当前 table-structure-v6）

> 状态：冻结前草案 v1（2026-07-31，Claude 核实后产出，转 Codex 实现）
> 对象分支：`codex/table-structure-cell-closure`（在工作树未提交修改之上继续）
> 验收纪律：实测优先；行为面版本变更必须在 commit message 显式声明；合并后 main 重生成 golden 并逐项说明漂移。

> 实现状态（2026-08-01）：下文 F1-F10 保留为历史复审依据；当前 writer 已推进到 `table-structure-v6` / `claim-catalog-v10`。在原规格之上，所有保守降级 cell 均进入可审核候选，专家可选择提升为 claim 或确认排除；确认写入 append-only `claim_structural_candidate_decisions.jsonl`（v2 writer、v1 历史回放），结构待审数非零时阻断 Ledger Ready。付费 queue/verifier 预算通过持久 outbox 双投影，进程在任一 sink 前后退出均不重复网络调用或丢失累计成本；attempt JSONL 在操作锁内以完整 canonical prefix 原子替换，provider 已返回 2xx 后的本地 checkpoint 失败不得重进 transport retry，queue/verifier checkpoint owner 以 CAS 原子交棒。F10 已覆盖真实 docx `catalog -> publish -> fold -> queue -> execute -> annotation`，默认排除候选单独投影且不进入付费队列。

## 〇、基线核实（2026-07-31，逐条实证）

工作树未提交修改**已经修复**（勿重做、勿回退）：

| 发现 | 状态 | 证据 |
| --- | --- | --- |
| P0#1 队列 schema 拒 table_cell | ✅ 已修（双侧） | `schemas/claim_queue_proposal_v2.schema.json` 已含 `table_cell_text`/`table_cell_focus`；`claim_focus.py` v2 适配器已产出全部必填字段；`_build_queue`（claim_review_actions.py:2507）已传 `table_cell_items` 且有 unavailable 兜底 |
| P0#3 xlsx ListObject 表外守恒 | ✅ 已修 | `parsers/xlsx_parser.py:137-155` 表外非空连通区域成表；`headerRowCount=0` 三态保留；`claim_catalog.py` 新增 `orphan_table_cell_count`/`duplicate_table_cell_id_count` 且进 hard-fail |
| P0#4 PDF 几何伪造合并格 | ⚠️ 大部分已修，**留一处红灯** | 边界聚类/维度匹配/覆盖守恒已落实（`parsers/pdf_parser.py:1655-1742`）；但重叠守卫有洞，见 F1 |
| P0#6 cell claim 语义上下文 | ✅ 已修 | `claim_catalog.py:1409` leaf 带 `semantic_context`；`claim_ledger.py:977-985` `_claim_content` 对 table_cell 用 semantic_context 作 coverage evidence 文本 |
| P0#2 具名探针 | ⚠️ 部分修复 | "Outputs can be assigned…" 现产 1 claim、"Battery service life: 15 years" 现产 1 claim（实测）；但资格耦合与歧义路径仍有内容丢失/畸形，见 F2 |
| P0#5 矩阵伪句式 | ❌ 未修 | 实测：`[["Item","Status","Required"],["Voltage","X","X"],["Current","X",""]]` 仍产 `Voltage shall support Status.` / `Item shall support Required.`（后者**从表头格合成**），且表头格 "Required" 自身成裸词 claim |
| P1#7 cell 产物哈希绑定 | ❌ 未修 | `claim_artifacts.py:3027-3034` generation_meta 只绑 blocks/table_items；`:4277-4283` 加载检查同样漏 table_cell_items.jsonl |
| P1#8 迁移门不收口 | ❌ 未修 | `committed_base_versions_are_current`（claim_artifacts.py:4705-4713）不查 `table_structure_version`/`table_structure_status` |
| P1#9 合并证据 | ❌ 未修（xlsx 部分已修） | 实测：`docx_table_grid_evidence` 对二维 gridSpan+vMerge 产 `[(1,1,1,2),(1,1,2,2)]` 重叠 merge；rowspan 后续行 `row_header_context=[]`（对象值丢失） |
| P1#10 测试空断言 | ❌ 未修 | `tests/test_table_structure_cells.py:247` `if block2["table_kind"] == "prose_grid":` 条件包裹关键断言；实测该 fixture 分类**不是** prose_grid（中位长 31 ≤ 40 且规范性列只有 1 列），断言体是死代码 |
| P1#11 UI cell claim 可达性 | ❌ 未修 | `ui/src/DocumentReview.vue:607-614` `cellContextIndex` 只索引 `data_row_index != null` 的数据格；标题/表头行（`DocumentReview.vue:1558-1560` thead）无任何 cell 入口；合并跨度未渲染 |

**当前工作树测试基线**：`tests.test_table_structure_cells` 23 例中 **1 红**（`test_pdfplumber_cell_evidence_overlap_is_honest_none`）——Codex 本轮修复必须先灭此灯。

---

## F1（P0#4 收尾）：PDF 几何重叠守卫有洞 —— 先灭红灯

- **原因**：`parsers/pdf_parser.py` occupancy 写入循环只拒绝 `occupancy.get((row, column)) == "anchor"`（anchor 撞 anchor）。
- **现象**：矩形 A 的 covered 区域被矩形 B 的 anchor 覆盖时静默放行——错位矩形仍被解释成跨列 merge。实证：`(0,0,100,20)` 与 `(50,0,150,20)` 输入返回非 None，与测试期望矛盾（当前红灯）。
- **机制**：①先对完全相同的 bbox 去重（pdfplumber 偶发重复输出是合法情形）；②此后占用表写入时**任何**已占用坐标（anchor 或 covered，不论来源）一律整体返回 `(None, None)`——几何矛盾即放弃精确几何，保留文本。宁缺不猜口径不变。
- **验收**：`test_pdfplumber_cell_evidence_overlap_is_honest_none` 转绿；新增 anchor-on-covered 专项探针（B 的 anchor 落在 A 的 covered 格）；既有 honest-none 三例与维度匹配例保持绿。

## F2（P0#2 收尾）：结构角色与内容资格彻底解耦

- **原因**：`table_structure.py` 的标题/表头推断仍直接决定内容资格；`is_normative_text` 的保守子集漏掉的规范性内容被路由成纯 context（静默），ambiguous 路径还把未确证的"表头行"拿去渲染数据行列名。
- **现象（全部实测）**：
  1. `Insulation class: II`（冒号规格、无阿拉伯数字）单格行 → context，0 claim，`accounting_status=complete`；
  2. 歧义表 `[["The meter shall log all events.","X"],["Voltage","230 V"]]` → 首行被判表头，数据行用首行句子当列名渲染出畸形 claim 文本 `The meter shall log all events.=Voltage | X=230 V`；
  3. `_COLON_SPEC_RE` 只认 `:\s+\S*\d`，罗马数字/枚举值规格漏判。
- **机制**：
  1. `_COLON_SPEC_RE` 扩展接受罗马数字与全大写枚举值（如 `:\s+(?:[IVX]{1,6}|[A-Z]{2,}|\S*\d)`），仍要求字母标签无数字——只扩值域，不放宽标签侧；
  2. **ambiguous 表头不得参与 headers 渲染**：`detect_header_rows` 返回 `status == "ambiguous"` 时，`build_table_artifacts` 计算 `headers` 必须回退 `unique_headers([], width)`（`column_N`），且该行回到数据区按普通规则出 leaf——任何 claim 文本不得以另一行的规范性句子充当列名；结构状态仍 `needs_review` 进审核（结构状态与内容守恒分离的既定口径不动）；
  3. 单列"标签: 值"连排表（≥2 行、每行恰好一个非空格、均匹配冒号规格）判 headerless 参数表：0 表头行、逐行 row leaf——不再依赖逐格 normative 命中。
- **验收**（全部硬断言，不得条件包裹）：
  - `Insulation class: II` 双行表 → 2 claim，`accounting_status=complete`；
  - 歧义表 → 首行规范性内容有 claim，且全部 claim 文本中不出现以另一行句子为列名的 `=`
    渲染（断言无 `shall log all events.=` 子串），`table_structure_status=needs_review`；
  - 既有 "Outputs…"/"Battery…" 两探针保持各 ≥1 claim。

## F3（P0#5）：矩阵事实合成门禁 —— 消灭确定性幻觉

- **原因**：`is_mapping_matrix`（table_structure.py:416-434）仅凭 marker 占比 ≥0.30 分类；A 轨合成（atomize.py:1440-1470 与 1361-1388）对事实列 marker 格无条件造 `"{subject} shall support {predicate}."`，且**不检查来源格的结构角色**——表头格的 marker 词（"Required" 命中 `_POSITIVE_MARKERS`）也参与合成。
- **现象（实测）**：检查清单表误判 mapping_matrix；产 `Voltage shall support Status.`、`Voltage shall support Required.`、`Item shall support Required.`（来自表头格）；表头格 "Required" 自身成为文本为 "Required" 的裸词 claim。
- **机制**（合成句式必须同时过四道闸，任一不过 → 保留原始 cell claim（B 轨带 semantic_context 闭环），A 轨句式不产）：
  1. **marker 词文本永不单独成 claim**：`plan_table_leaves`/`structural_row` 中 `is_positive_marker(text)` 的格一律 context（表头 "Required" 不再产裸词 claim）；
  2. **结构角色闸**：只有 `structural_role == "data"` 的 marker 格参与合成——表头/标题/分组标题格永不合成（堵 `Item shall support Required.`）；
  3. **维度证据闸**：`matrix_fact_columns` 增补——事实列表头不得是 marker 词、不得是处置词（新确定性停用表：`status|result|required|check|checked|ok|remarks|备注|状态|结果|检查`，与 Note 列口径并列）；首列（subject 维度）值不得全为纯数字/日期；
  4. **subject/predicate 真实性闸**：subject 取数据行首列非空、非 marker、非纯数字文本；predicate 取该列真实表头；subject 或 predicate 为空/被判 marker → 该格放弃合成。
  不满足门禁的表降级按 `other`/cell 保留原文——**内容零丢失，只是不造句**。
- **验收**：
  - 检查清单探针：0 条 `shall support` 伪句式、0 裸词 claim，marker 格仍以 table_cell claim（带 semantic_context）闭环，`accounting_status=complete`；
  - 真实 DLMS 属性×服务矩阵（ABNT 语料）既有合法事实不丢：main 基线重生成时 `capability_matrix`/`table_value_matrix` 计数变化必须逐项说明（允许减少，但每减少一项须能指认是伪句式）；
  - 新增维度闸专项：处置词列表头、marker 词列表头、纯数字首列三例均不合成。

## F4（P0#6 核实性收口）：coverage evidence 上下文断言

- **现状**：已修（semantic_context 进 `_claim_content` → `source_evidence.text`；`_render_unit_prompt` 的 SEMANTIC CONTEXT 头）。本条是把该行为钉成永久回归。
- **机制**：新增端到端断言——mapping_matrix 裸 `X` cell claim 的 coverage group `source_evidence.text` 必须同时包含表标题、行头（首列值）、列头与该 `X`；`cell_start/end` 落在上下文文本内的 claim 正文区间。verifier 请求构造路径不得回退裸格文本。
- **验收**：新专项测试 1 例；既有 claim_ledger 套件零回归。

## F5（P1#7）：table_cell_items.jsonl 哈希绑定（fail-closed）

- **原因**：`claim_artifacts.py:3027-3034` generation_meta 只记 `blocks_file_sha256`/`table_items_file_sha256`；`:4277-4283` 加载检查同漏。发布后替换/删除 cell 产物，旧账本照常加载。
- **机制**：
  1. generation_meta 增加 `table_cell_items_file_sha256`（文件存在时记真实哈希；`table_structure_version ≥ table-structure-v2` 的 base 该字段**必填**——v2 起 cell 产物是权威输入）；
  2. `_load_committed_claim_base_unlocked` 的校验循环加入 `("table_cell_items.jsonl", "table_cell_items_file_sha256")`：hash 非空而文件缺失/不符 → `ClaimArtifactError`；base 声称为 v2+ 而字段缺失 → 同错（不得静默跳过）；
  3. 只读快照缓存（`claim_views._context`）无需改——失效键已含 generation meta 哈希，字段入 meta 后自动覆盖。
- **验收**：发布后篡改 1 字节 / 删除文件 / 换入旧代文件三探针均 fail-closed；合法重载不受影响；旧代（无 cell 产物）base 由 F6 版本门统一拦截、不在这条路径上报双重错误。

## F6（P1#8）：结构迁移状态进入版本门

- **原因**：`claim_catalog.py:1679-1680` 已写 `table_structure_status`/`table_structure_version`，但 `committed_base_versions_are_current`（claim_artifacts.py:4705-4713）不检查——旧产物并未真正"大声失败"。
- **机制**：返回条件追加——`catalog_meta.get("table_structure_version") == TABLE_STRUCTURE_VERSION`（当前常量）且 `catalog_meta.get("table_structure_status") != "base_migration_required"`。`needs_review` 不阻断（结构歧义是审核信号，不是迁移缺口）；版本不一致或显式迁移标记 → 全部既有调用点（API startup、POST `/claim-maintenance`、desktop、ai-extract 前置）如实 `base_migration_required`。
- **验收**：构造 v1/缺字段/base_migration_required 三种旧 base，逐调用点断言 503/`base_migration_required`；v2+`needs_review` base 正常加载。

## F7（P1#9）：合并证据可靠性（DOCX 二维 merge + rowspan 上下文 + 重叠降级）

- **原因**：
  1. `atomize.py:332-379` `docx_table_grid_evidence` 对 gridSpan=2 的 vMerge restart 在**每个列游标**各存一条链（anchor_col/col_span 相同），continue 只推进 `column_cursor` 一条链——关闭时同一逻辑 merge 拆成 `(1,1,1,2)` 与 `(1,1,2,2)` 两份**重叠** range（实测复现）；
  2. `table_structure.normalize_merge_ranges` 不校验重叠，`covered_coordinates`/`merge_anchor_for` 拿重叠证据照常产出；
  3. `_row_header_context` 直读 `matrix[row][0]`——rowspan 覆盖行的首列是空串，对象值降级丢失（实测 R3 的 X 格 `row_header_context=[]`）；纵向合并还使 `is_mapping_matrix` 的 first_col 证据缩水（覆盖行首列为空），可能连带误降级表型。
- **机制**：
  1. **vMerge 链按 anchor 归组**：restart 只登记一个 anchor（key=(row,col)，记 col_span 与其全部游标）；continue 推进该格 gridSpan 覆盖的**所有**游标所属 anchor 的 last_row；关闭时每个 anchor 恰好产一个 range（last_row 取该 anchor 全游标最大值）。continue 格 gridSpan 与 anchor col_span 不一致 = 结构矛盾 → 该表合并证据整体降级为 None（保留文本，放弃精确合并，结构状态 needs_review），绝不伪造；
  2. **`normalize_merge_ranges` 重叠校验**：去重后任两 range 面积相交（含包含关系）→ 视为矛盾证据，调用方按"merge_ranges=None + needs_review"降级（文本守恒，不产精确 span）；单元格 1×1 range 过滤不变；
  3. **rowspan 上下文继承**：`_row_header_context` 与 `plan_table_leaves`/`is_mapping_matrix` 读取 (row, col) 文本时，covered 坐标回溯其 merge anchor 的文本（继承不复制——cell 仍只存 anchor，继承只用于上下文与判定）；R3 的 X 格 `row_header_context` 必须含 anchor 对象名。
- **验收**：
  - 二维 merge docx 探针：`merges == [(1,1,2,2)]`，无重叠；
  - rowspan 探针：`[["Service","GET","SET"],["Object A","X","X"],["","X",""]]` + merge (2,1,3,1) → R3C2 的 `row_header_context == ["Object A"]`，表型不因首列覆盖误降级；
  - 人为重叠 merge 输入 → 降级 None + `needs_review` + 文本零丢失（claim 仍在）；
  - xlsx `headerRowCount=0` 既有修复保持绿。

## F8（P1#10）：原子化测试空断言 + 同格双义务归属

- **原因**：`tests/test_table_structure_cells.py:247` 用 `if block2["table_kind"] == "prose_grid":` 包裹关键断言；该 fixture 实测不是 prose_grid（中位长 31 ≤ 40、规范性列仅 1 列），断言体是死代码。同格双句在行模式表（parameter/other）里仍并成一个 row claim——两个独立义务只有一个 owner。
- **机制**：
  1. **多义务格归属规则**（table_structure，确定性）：任一数据格经 `_sentence_spans` 切出 ≥2 个规范性句 → 该格按句出 cell leaf（owner=cell），同行其余格仍归 row leaf（mixed）——单义务参数行不受影响，双义务格不再骑墙；
  2. 测试去条件化：fixture 先硬断言分类前提（`assertEqual(block2["table_kind"], "prose_grid")`），再断言同格双句两 claim；分类判不出时测试必须变红而非跳过；
  3. 新增短句用例： `[["Topic","Details"],["General","It shall log. It must alarm."]]` → 恰好 2 个 claim、文本分别为两句、focus 指纹互相独立。
- **验收**：三例全绿；故意改坏分类时代码评审可复现变红（非空转）；既有参数表行级归属用例零回归。

## F9（P1#11）：审核界面 cell claim 全部可达

- **原因**：`DocumentReview.vue:607-614` `cellContextIndex` 丢弃 `data_row_index == null` 的条目（标题/表头格）；模板 thead（`:1558-1560`）只渲染文本不挂 cell 入口；`doc_annotation_export.py:2929-2945` 的 cell_context 未下发 `row_span`/`column_span`/`covered_coordinates`，DOM 无法渲染合并跨度。
- **机制**：
  1. 后端 cell_context 条目增补 `row_span`/`column_span`/`covered_coordinates`（来自 canonical cell，不伪造）；annotation 版本戳 v14 → v15（契约快照同步）；
  2. 前端索引改为全量 cell，键用物理 `R×C`（`block_id:R<row>C<col>`）；标题行与 thead 行渲染同样走 cell 查询、挂 cell 按钮与 claim 角标（与数据格同一 `selectCellCard` 通路）；
  3. 合并格按 `row_span`/`column_span` 渲染 DOM `colspan`/`rowspan`，covered 坐标渲染为被占格（不挂按钮、不可点），与 canonical anchor 口径一致。
- **验收**（vitest）：标题 cell claim 可点选并出 cell 卡；表头 cell claim 同；合并格 DOM span 正确且 covered 坐标无按钮；既有 138+ 例零回归。

## F10（系统性回归）：端到端闭环与守恒矩阵

按审核系统性方案落实**真实**端到端回归（非 mock 拼接）：

1. **catalog → queue → publish → reload → execute**：含 mapping_matrix 的合成 docx 全链——`build_claim_catalog` → `_build_queue`（table_cell proposal 过 v2 schema 校验）→ 发布 → 重载 → focus 适配重建 → 执行前置校验通过；
2. **守恒矩阵**（每条一个用例）：ListObject 表外内容成表出 claim；headerless 首行进数据区；错位 PDF `(None,None)` 降级且文本零丢失；二维/纵向 merge；cell artifact 篡改 fail-closed（F5 三探针）；标题/表头规范性内容出 claim 且 UI 可审（F9）；
3. **xlsx sheet 级第一段守恒计数器**：sheet 非空物理格 = Σ regions 非空格（ListObject 覆盖 + leftover 连通区域），不等即 hard-fail 计数器入账——补齐"source region → canonical cell → claim/context"三段守恒的第一段独立计数；
4. 全量 `python -m unittest discover -s tests` + `cd ui && npm test` + `vue-tsc` 绿；`git diff --check` 通过。

## 版本面（必须在 commit message 逐项声明）

| 项 | 变更 | 原因 |
| --- | --- | --- |
| `TABLE_STRUCTURE_VERSION` | v2 → v3 | F2/F3/F7/F8 结构判定与归属规则变化 |
| `CLAIM_CATALOG_VERSION` | v6 → v7 | leaf plan/claim 归属语义变化（catalog generation id 随内容自动失效） |
| `STAGE_IMPLEMENTATION_REVISIONS` atomize | impl-v8 → v9 | 合并证据、合成门禁、leaf plan 影响 blocks/items → 旧解析产物自然失效 |
| annotation 版本戳 | v14 → v15 | cell_context 载荷新增 span 字段（F9） |
| `CLAIM_ARTIFACT_PROTOCOL_VERSION` | 实现时评估并声明理由 | F5 为 generation_meta 增字段：新读旧由 F6 门拦截、旧读新忽略增字段——倾向不动，但必须在 message 写明裁定 |
| ai-extract/extract_units 相关版本 | 实现时评估 | 若单元文本或 prompt 输入因子变化则同步 bump 并声明 |
| golden 基线 | 合并后 main 按「三 seed KB + domain-pack」重生成 | A 轨候选集变化（伪句式出清、多义务格拆分）；counts/requirement_type/source_type 分布漂移必须逐项说明 |

## 提交信息三段式要点（实现时按此组织）

- **原因**：2026-07-31 复审发现——cell 闭环存在 schema/守恒/几何/幻觉/绑定/门禁/UI 十一项缺口（本规格 F1-F9）。
- **现象**：逐条引用本规格 〇 表与 F 项实测探针输出（畸形行文本、伪句式、红灯测试、重叠 merge、rowspan 上下文丢失等）。
- **解决方法**：三段守恒各自 fail-closed；结构角色与内容资格解耦；矩阵合成四道闸；合并证据矛盾即降级保留文本；cell 产物哈希绑定与迁移门收口；UI 全量 cell 可达。

## 明确不做

- 不改 `golden_sets/` 冻结文件、不动 LLM prompt、不引入 LLM 判定（全部保持确定性）；
- 不放宽 `is_normative_text` 之外的任何既有判定口径来"凑绿"；判不出走 `needs_review` + 保留内容；
- 旧 `gui/`（PySide6）不动；客户语料/本机路径不进仓。
