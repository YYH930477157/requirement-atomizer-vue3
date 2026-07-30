# Claim Conservation Ledger — Phase 1.5 实施规格（闭环验证与启用 mutation）v1.0

状态：**待审核冻结**。本稿是 `docs/agent-claim-ledger-spec.md`（**v2.4，已冻结**）§9
Phase 1.5 的施工规格；总纲与本稿冲突时以总纲为准。Phase 1 已合 main（`74c5690`，生产
双写不切门控），本稿引用其实际落成物（模块/版本/行号均按 main 现状）。

- 实施分支：`codex/claim-ledger-phase1.5`（独立 worktree，用户决定合并）。
- 实施纪律：后端测试一律 `unittest.TestCase`；提交前全量 unittest + golden 6/6 绿；
  版本常量按 §7 表 bump；未要求不 commit、不 push。

---

## 1. 定位与范围

总纲 v2.4 §9 Phase 1.5 原文边界（逐字引用，不可扩大）：

> - 在 Phase 1 的只读投影、event hash、bridge 补偿、authoritative-state fold 与崩溃恢复
>   已经验证通过后，补齐 A/B requirement authority 写入口的 `expected_target_fingerprint` /
>   `expected_target_review_revision` CAS，才启用 claim 级专家写入、claim queue 与定点补抽
>   对生产 requirements 的 mutation——**mutation 唯一通道为现有 `targeted_reextract`**
>   （前置条件指纹 + 补丁形态），不得长出第二条改写 requirements 的路径；
> - ledger-only cache rebuild；
> - mutation 失败补偿、并发裁决冲突与 downstream generation 刷新全部验证；
> - downstream incomplete_inputs 贯通。

Phase 1.5 一句话：**账本从"只说不算"变成"算了要负责"**——专家可以裁决 claim、可以从
uncertain 队列发起定点补抽，但每一次写都有前置条件、可重放审计和失败补偿；readiness
门控**仍不切换**（那是 Phase 2）。

本阶段四件事（顺序即依赖序）：

1. **闭环验证**：把 Phase 1 已建成机制的故障语义验证补齐（真实强杀矩阵、锁序注入、
   interrupted fold 留痕）；
2. **authority CAS**：所有改变 target 有效性的写入口补齐 revision CAS（总纲 §2.5 硬要求）；
3. **启用两类 mutation**：claim 级专家裁决（只写事件，终态仍由 reducer 派生）与
   claim queue 定点补抽（唯一通道 `targeted_reextract`）；
4. **贯通**：downstream `incomplete_inputs`、批注导出 span/row 级 claim 定位（Phase 1
   经批准延后的项）、Phase 1 审查延后项。

## 2. 现状基线（main `74c5690` 实测事实）

### 2.1 可复用资产

- **mutation 通道** `omission_actions.targeted_reextract`（:644-866）：跨进程租约锁
  （`extraction_operation_lock`，冲突抛 `OmissionConflictError`）；前置条件
  `expected_source_fingerprint`（不符 409 语义）；补丁形态 = append-only
  `ai_supplements.jsonl` + `apply_supplement_patches` 重放（`_patch_is_current` 三重指纹
  才重放）+ `atomic_write_jsonl` 整体重写 + 全量 upsert 生效校验（未生效抛冲突）；
  失败路径诚实（LLM 异常上抛、零产出 `OmissionNoResultError`）；产出后刷新
  compliance/quality/metadata/partial/merged_spec。`POST /omission-reextract` 契约完备
  （409/422/400/502/503）。
- **fold/事件/WAL**（Phase 1）：`claim_review_actions.fold_effective_ledger`、
  `claim_review_events.jsonl`（schema v1，event_kind 仅
  `target_invalidated|target_reactivated`）、独立 effective WAL、`claim_effective_health.json`、
  三层 loader、`reduce_claim` 优先表。
- **review 写入口指纹现状**：B 轨 `POST /ai-review-actions` 已有 source/review_subject
  双指纹 CAS（api_server.py:436-456）；clarification batch 有 evidence_fingerprint CAS；
  omission-actions 有 expected_source_fingerprint CAS。
- **UI**：`ClaimLedger.vue` 队列页签（零按钮）、详情抽屉；api-client 六个只读方法。
- **annotation**：`claim_distribution` 块级三态角标（optimized 布局，:1207-1227 内联计算，
  数据源 effective snapshot）；v12 行级热区挂点（`_pdf_block_zones` :2066-2081、
  `_pdf_context_records` :2161-2174）。

### 2.2 已核实的缺口（Phase 1.5 必须修，附行号）

- **G1 A 轨专家裁决零 CAS**：`POST /review-actions` → `apply_review_action`
  （review_actions.py:13-21）→ `apply_expert_decision`（review_state.py:73-152）
  无任何 fingerprint/revision 入参，唯一硬约束是 frozen 不可改出。
- **G2 HTML 导入零 CAS**：`desktop_tasks.import-ai-decisions`（:1471-1519）不传任何
  fingerprint；总纲 §2.5：旧格式 HTML 裁决缺 token 只能导入为
  `needs_reconfirmation/proposal`，不能成为 ledger authority。
- **G3 无 revision 概念**：所有写入口的 CAS 都是指纹制；没有任何端点/UI 字段携带
  `expected_target_review_revision`（总纲：source/subject fingerprint 只证明内容代际，
  不能替代 prior-review CAS）。UI api-client 同样无 revision 字段。
- **G4 `incomplete_inputs` 全仓零命中**：下游产物（functional_synthesis、
  requirements_analysis、template_writer、assemble_spec、engineering_composer）对
  extraction partial 无感知字段；现行只有 manifest stage `"partial"`、clarification
  readiness 阻断、块级 `extraction_failed`。
- **G5 claim locator 无 row 级消费**：catalog 表格行 claim 的 locator 有行精度，但
  queue 提案 `parent_block_id` 仅块级，annotation 角标仅块级；span/row 级定位未做
  （Phase 1 经批准延后至本阶段）。
- **G6 agent 未接 claim 提案**：agent_state 只读 omission/质量，不读 `/claim-queue` 同源
  提案；`allow_llm=False` 纪律在 agent_tools.py:32/:208 与 test_agent_tools.py:91。
- **G7 targeted_reextract 候选门**：`block_id in current_omission_candidate_ids`
  （omission_actions.py:381-407）——uncertain claim 的块可能已被其他需求"覆盖"而不在
  候选集，直接复用会被候选门拒绝（"第一段有疑问、第五段有答案"型漏项正是此形态）。
- **Phase 1 审查延后项**（已记入待办，本阶段一并收口）：publish 后双重 fold 去重、
  hook 门控加轨道校验、acceptance/review_packet 换显式三层 API、`decide_trace.jsonl`
  入零-mutation 守卫监视、clarification entries TIER 前后对比断言、启动 fold 的
  fresh 短路、effective WAL 真实 `os._exit` 矩阵、锁序反序注入、interrupted fold
  的 health 登记。

## 3. Phase 1.5 设计公理

总纲 §1 与 Phase 1 公理之上追加六条，违反任何一条即返工：

1. **mutation 唯一通道**：对 `ai_requirements.jsonl` 的一切写只能经由
   `targeted_reextract`（含本稿 §5.4 的 claim 模式扩展）的锁、前置条件、补丁与原子性；
   任何新代码路径不得就地改写 requirements。`atomic_requirements.jsonl`（A 轨）本阶段
   仍无任何 mutation 入口。
2. **终态只能派生**：claim 的 `covered|excluded|uncertain` 永远由 reducer 从当前事实
   派生；专家裁决、补抽执行只产生**事实与事件**，任何 API/UI/导入路径不得直接写
   `resolution`（总纲 §6.2"resolved 不允许外部直接写入"）。
3. **写必有 CAS**：凡改变 target 有效性或 claim 状态的写入，必须携带对应
   fingerprint + revision 前置条件并在同一把锁内比对；陈旧写 → 409 + 当前 revision，
   绝不 last-write-wins。缺 token 的遗留通道只能降级为 `needs_reconfirmation/proposal`。
4. **失败要诚实可补偿**：mutation 任一步失败 → requirements 状态不变（补丁原子性）或
   已登记的状态明确标注；补偿路径（重开、重试、重放）必须可重放审计，绝不把失败
   伪装成完成（含"排队说成已抽取"）。
5. **门控绝缘（延续 Phase 1）**：readiness_verdict、TIER、merged_consistency 结构、
   golden、chain 复用语义不改；新信息仍走 informational 字段。
6. **成本可见**：定点补抽是用户显式触发的 LLM 调用——每次执行记录真实 route/模型/
   token/补丁血缘进事件；不得批量隐式触发（agent 不得自动执行，§12）。

## 4. 数据契约（变更与新增）

### 4.1 `claim_review_events.jsonl` 升 schema v2（`claim-review-event/v2`）

新增 event_kind（v1 两种保留不变）：

| event_kind | actor | 语义 |
| --- | --- | --- |
| `expert_adjudication` | `expert:<actor>` | 专家裁决单条 claim：`adjudication ∈ covered \| excluded_non_normative \| reopen`，必填 `reason`、`evidence_refs`（covered 须引 coverage group 或 target+逐字引句；excluded 须受控原因；reopen 可为空列表）、`supersedes_conflict: bool` |
| `audit_conflict` | `expert:<actor>` 或 `system:claim-audit` | 审计分歧登记：绑定被争议 fact 的 hash 与双方证据；reducer 按冲突处理 |
| `reextract_executed` | `system:claim-queue-executor` | 定点补抽审计：`supplement_id`、focus locator、`route/model/tokens`、`result_requirement_ids`、失败时 `error` 与零产出如实记录 |
| `structural_falsification` | `expert:<actor>` | 结构性排除证伪：绑定 claim、原 exclusion 证据、`falsification_reason`、`override_id`（§5.3） |

共同约束：事件仍 append-only + hash 链；新增种类的事件必须携带
`expected_claim_effective_revision`（锁内 CAS，陈旧拒绝）；`actor` 枚举放开但
projection 仍恒 `system:claim-review-bridge`。schema v2 对 v1 行向后兼容（旧行可重放）。

### 4.2 authority revision 与 CAS 协议（新常量）

- 每个 authority adapter 导出**可复算的 per-target `target_review_revision`**：
  B 轨 = `sha256("claim-target-review/v1" | ai_req_id | 最新有效行 canonical | 无row时 sha256(empty))`；
  A 轨 = `sha256("claim-target-review/v1" | requirement_id | status | history长度 | 末条history hash)`。
  公式进 `claim_ledger`（两 adapter 共用，版本钉
  `CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION = "claim-authority-write-v1"`，
  记入 generation/effective meta 与 health）。
- 写入口新增入参：`expected_target_fingerprint` + `expected_target_review_revision`，
  锁内比对，陈旧 → **409 + 当前 revision**（响应携带现值供调用方重试）。
- GET 面透出 revision：`/ai-requirements` 行、`/requirements` 行（经 enrich）各加
  `target_review_revision` 只读字段，供 UI 回显携带。

### 4.3 `claim_queue_proposals.jsonl` 升 v2（`claim-queue-proposal/v2`）

- 提案生命周期：`state ∈ open | executing | executed`（fold 重建时按当前事实重算，
  executed 仅凭 `reextract_executed` 事件成立；**resolved 不是提案状态**——提案消失
  只因 claim 被 reducer 关闭）。
- 新增执行前置字段：`execution_preconditions{claim_id, claim_source_fingerprint,
  claim_effective_revision, parent_block_id, block_source_fingerprint, focus_lines[]}`
  （focus_lines 由 claim locator 派生、必须是所属章节原文子串，沿用
  `_validated_focus_lines` 语义）。
- `dry_run` 字段保留但可执行提案为 `dry_run: false`（Phase 1 的全部为 true，兼容读）。

### 4.4 结构性排除 override 注册表（新文件 `claim_structural_overrides.jsonl`）

append-only、hash 链（沿用事件文件纪律）：`override_id`、`claim_id`、`claim_hash`、
`catalog_generation_id`（证伪时所在代）、原 exclusion 证据、`falsification_reason`、
`actor`、`recorded_at`、`override_version`。catalog 重建时作为**确定性输入**消费
（§5.3），写入 catalog meta 的 override 清单与 hash。

### 4.5 downstream `incomplete_inputs`

下游产物 JSON 各加顶层 `incomplete_inputs: bool`（默认 false；当 ai-extract
`extraction_status=partial` 或 `failed_sections>0` 时置 true）：functional_synthesis 输出、
`engineering_requirements.json`、`template_writer_report.json`、`clarification_report.json`
（其 readiness 已阻断，此处补字段）、merged_spec 报告。数据源 =
`ai_requirements.meta.json` 既有字段，只读不重算。

## 5. 机制设计

### 5.1 authority 写入口 CAS（G1/G2/G3）

- **B 轨 `POST /ai-review-actions`**：在既有双指纹之上**强制新增**
  `expected_target_review_revision`（§4.2 公式，锁内比对）；旧调用方不带 → 400
  `missing_revision`（不留兼容后门，UI 同步改）。指纹继续校验内容代际，revision 校验
  prior-review 状态——两者语义不同，缺一不可（总纲 §2.5）。
- **A 轨 `POST /review-actions` / `apply_expert_decision`**：补
  `expected_target_fingerprint` + `expected_target_review_revision` 入参（当前为零 CAS，
  G1）；链路 `apply_review_action` 透传；UI `applyReviewAction` 先经 `/requirements`
  行携带的 revision 回显。
- **HTML 导入 `import-ai-decisions`**（G2）：无 token 的 HTML 裁决一律导入为
  `needs_reconfirmation=True` 的 proposal 行（保留原状态文本作展示），**不成为 ledger
  authority**（claim 侧 eligibility=unknown，不用于关闭 claim）；导入报告如实统计
  降级条数。若 HTML 模板未来携带 token（导出侧加 data 属性），可按 §4.2 正常 CAS 导入——
  本阶段只预留解析，不实现导出侧改造。
- **自动迁移/生成式合并**（`llm_pipeline.merge_review_states`）：非专家写，现状不动，
  在 health `authority_cas_gap` 的清除条件中显式豁免并留痕。
- `authority_cas_gap`：B/A 两端点 + HTML 降级全部落地后，health 中该 flag 置 false
  并记录 `cas_protocol_version`；`import-clarification-answers` 的静默丢弃改为响亮
  冲突列表（响应逐条列 stale，仍不阻断合法行）。

### 5.2 claim 级专家裁决（reducer 专家层）

- API：`POST /claim-adjudications`（`claim-adjudication/v1`）——body：`claim_id`、
  `adjudication`、`reason`、`evidence_refs[]`、`supersedes_conflict`、
  `expected_claim_effective_revision`（CAS，409+当前值）、`actor`。校验：当前
  generation + claim_hash 匹配；证据规则按 §4.1 表。
- fold 归约（`CLAIM_EFFECTIVE_REDUCER_VERSION` 升 v2，base reducer 不动）在总纲 §2.4
  优先表之上加**专家层**，优先级自上而下：
  1. 当前 `structural_falsification` → 按 §5.3 走重建（不在 fold 内关闭）；
  2. 当前 `expert_adjudication(covered|excluded_non_normative)`：与同代冲突事实
     （相反方向的 verifier-validated fact）并存时——`supersedes_conflict=true` 且有
     reason → 按裁决派生；否则 → `uncertain + conflict`（总纲"并发冲突不闭合"）；
  3. 当前 `audit_conflict` → `uncertain + conflict`；
  4. 总纲 §2.4 原表。
- 专家事实的失效规则与 verifier 事实相同：claim_hash、target fingerprint、evidence
  locator、reducer/adapter 版本任一变化即失效（事件仍在，仅供审计）；绝不跨
  generation 静默复用。
- `expert_adjudication(reopen)` 使对应 covered/excluded 失效回 uncertain；被重开的
  claim 重新进入 queue 提案派生。
- UI：详情抽屉加三个裁决按钮（确认覆盖/确认非需求/推翻闭合）+ reason 输入 +
  冲突时的 supersedes 勾选项（默认不勾）；409 → 整页重取后提示重试。

### 5.3 结构性排除证伪与重建（总纲 §2.5 硬要求）

- 证伪入口：`POST /claim-adjudications` 的 `adjudication="structural_falsification"`
  变体（或独立 `kind` 字段），写 `claim_structural_overrides.jsonl`（§4.4），
  **不在 fold 内改 claim 状态**。
- 重建路径：override 变化使 catalog generation 失效 → 走既有 ledger-only 重建
  （`refresh_claim_shadow` 扩展 overrides 输入参数），catalog 以 overrides 为确定性
  输入重生成（被证伪的排除不再应用，相关行成为 eligible claim；catalog meta 记录
  override 清单 hash 与 `override_version`）——"只追加 ledger event 让错误 catalog 行
  留在文档分区"被显式禁止。
- **两级证伪区分**：per-claim 证伪（override 注册表，运行时可达）与 rule 证伪
  （排除规则本身错误 → 代码修复 + `CLAIM_CATALOG_VERSION` bump，不在运行时通道内，
  本阶段不实现）。
- 成本诚实：重建后新 eligible claim 走正常 verbatim/prefilter/verifier 流程，verifier
  调用受既有预算门约束；UI 在证伪确认对话框中明示"将重建账本并可能消耗 verifier
  预算"，需用户显式确认。`CLAIM_CATALOG_VERSION` 不变（override 是输入不是行为）。

### 5.4 claim queue 定点补抽执行（G7 + 唯一通道）

- **`targeted_reextract` 扩展 claim 模式**（仍是唯一通道，契约 v2）：
  新增可选入参 `claim_id` + `expected_claim_effective_revision`；claim 模式下——
  候选门由"块 ∈ omission 候选集"**替换为**"claim 存在、当前 resolution=uncertain、
  locator 可映射所属章节"（G7：块被其他需求覆盖但 claim 未覆盖正是主目标场景）；
  `focus_lines` 强制取 claim locator 派生行（仍是章节原文子串）；其余锁、前置指纹
  （块级 `expected_source_fingerprint` 照旧校验）、补丁形态、原子重写、
  compliance/quality/meta/partial/merged_spec 刷新**一字不改**。
  `AI_SUPPLEMENT_VERSION` bump（新策略指纹，旧补丁重放规则不受影响）。
- API：`POST /claim-queue/execute`（`claim-queue-execute/v1`）——body：`proposal_id`、
  `expected_claim_effective_revision`、`expected_ledger_state:"uncertain"`、`actor`、
  `allow_llm: true`（**缺省 false 且缺省拒绝**）；错误口径沿用
  `/omission-reextract`（409 stale / 422 零产出 / 502 LLM / 503）。
- 执行后闭环：补丁重放成功 → 目标集合变化 → 同请求内触发一次 fold（沿用触发点
  纪律），reducer 用新需求重新验证关联 claim——**只有重新验证成 covered/excluded
  才关闭**；仍 uncertain 则提案回到 open。执行事件（§4.1）记录全部血缘与 token。
- 失败补偿：LLM 异常/零产出 → requirements 零变化（补丁原子性保证），事件如实记
  `error`，提案保持 open；冲突（CAS/CAS-equivalent 失败）→ 409，不写任何状态。
- agent 纪律延续：agent 只读提案、只排队 `needs_extraction`；`allow_llm=True` 的
  显式外部调用才可执行（既有 agent_tools.py:32/:208 断言保持）；agent_state 增加
  读 `/claim-queue` 同源提案文件作候选来源（G6，只读接线）。

### 5.5 mutation 失败补偿与并发语义（验证主题，非新机制）

- 裁决/执行并发：同一 claim 的并发写 → CAS 拒绝后者（409）；并发裁决冲突（两人
  相反裁决）→ reducer `uncertain + conflict`，等待再次裁决。
- supplement replay 后自动重开（总纲 Phase 1.5 首条）：补丁因指纹失效不再重放 →
  关联 claim 在下一次 fold 自动重开（target 失效语义已覆盖，测试补钉）。
- downstream generation 刷新：补抽改变 requirements → target_set_hash 变化 →
  document_effective_revision 前进 → 下游 informational 字段（clarification 的
  claim_ledger 块、run_manifest claim_components）自然反映新代。

### 5.6 downstream `incomplete_inputs` 贯通（G4）

- 各下游阶段在产物 JSON 顶层加 `incomplete_inputs`（§4.5 口径）；
  `STAGE_IMPLEMENTATION_REVISIONS` 对应阶段 bump（functional-synthesis、
  requirements-analysis、template-write、compose、clarification-report）。
- readiness 语义不变（已由 failed_sections 阻断）；该字段仅供 API/UI/导出如实展示
  "输入不完整"。UI 运行页与账本页读取展示，不加新门。

### 5.7 闭环崩溃/并发验证计划（Phase 1 延后项转正）

- **真实 `os._exit` 矩阵扩展到 effective WAL**：备份后/WAL durable 后/逐文件 replace
  中途/journal 删除前四类强杀点（沿用 Phase 0 generation 矩阵的进程级 harness），
  断言恢复上一代完整 trio、无 verifier failure 登记、interrupted fold 已留痕。
- **interrupted fold 的 health 登记**（Phase 1 放弃项，本阶段实现）：
  `claim_effective_health.json` 增 `interrupted_folds[]`（时间、恢复自哪个 journal
  hash、恢复动作），schema 同步。
- **锁序反序注入**：测试替身强制先取 review 锁再请求 publication 锁，断言被显式
  拒绝/超时而非死锁。
- **publish 后双重 fold 去重**：`publish_b_track_shadow` 内部 fold 结果复用给
  ai-extract 层（同代幂等短路），断言同代第二次 fold 零 WAL 写入。
- **启动 fold fresh 短路**：`assess_effective_freshness` fresh 时启动 maintenance
  跳过物化（保留 journal 恢复职责）；stale 才全量 fold。
- **hook 门控加轨道校验**：A 轨裁决遇 B 轨 generation 直接 no-op（读 generation
  meta 声明的 track，不空跑 fold）。
- **acceptance/review_packet 换显式三层 API**（去兼容别名）；
  **`decide_trace.jsonl` 入零-mutation 守卫监视清单**；**clarification entries
  TIER 前后对比断言**（补进既有 informational 测试）。

### 5.8 批注导出 span/row 级 claim 定位（G5，Phase 1 批准延后项）

- **文本块**：复用 v11/v12 全局匹配机制（精确→包含→边际模糊，宁缺不猜）按 claim
  文本在影印/原生 PDF 上定位 claim 级热区，kind = covered/excluded/uncertain 三色；
  块级角标保留为汇总。
- **表格块**：catalog 行级 locator 对齐 v12 行级热区（row zone 上叠 claim 状态点），
  行卡片追加该行 claim 列表（id + resolution + 详情锚）。
- **两个布局**（optimized + pdf_original）一致覆盖（现状角标只有 optimized）。
- 版本：`doc_annotation_export` 基戳 v12-claim-distribution → **v13**（缓存失效）；
  契约快照测试同步。

## 6. 接入面设计

### 6.1 API 汇总

新增 POST（全部 token 校验、统一错误口径、全部带 CAS）：

| 端点 | schema | 语义 |
| --- | --- | --- |
| `POST /claim-adjudications` | `claim-adjudication/v1` | 专家裁决/证伪（§5.2/§5.3）；200/400/409/503 |
| `POST /claim-queue/execute` | `claim-queue-execute/v1` | 定点补抽执行（§5.4）；200/400/409/422/502/503 |

变更：`/ai-review-actions`、`/review-actions` 强制 revision 入参（§5.1）；
`/ai-requirements`、`/requirements` 行加 `target_review_revision`；
`/claim-queue` 提案带 v2 生命周期与执行前置字段；六个只读端点 view 版本按需 v2。

### 6.2 UI（`ui/src/ClaimLedger.vue` 为主）

- 详情抽屉：裁决按钮组 + reason/evidence 表单 + supersedes 勾选（§5.2）；409 → 重取提示。
- 队列页签：open 提案加「定点补抽」按钮（确认对话框显示 claim 原文、locator、
  "将调用 LLM 并消耗 token"明示 + allow_llm 勾选）；executing 态进度、executed 态
  结果链接（跳转需求列表对应行）；失败如实 toast（不重试伪装）。
- 账本页与运行页：`incomplete_inputs` 横幅（§5.6）。
- 批注导出为静态产物，不含交互（§5.8）。

### 6.3 desktop 与 agent

- desktop：run_manifest ai-extract 条目的 `claim_components` 加
  `cas_protocol_version`、`queue_version`（informational）；`claim-ledger-fold` 子命令不变。
- agent：`agent_state` 增读提案文件为候选来源（G6 只读）；`agent_tools` 纪律断言
  保持；`decide_trace.jsonl` 只记摘要。

## 7. 版本与缓存纪律

| 常量 | 现值 | Phase 1.5 | 域 |
| --- | --- | --- | --- |
| `CLAIM_REVIEW_EVENT_SCHEMA` | claim-review-event/v1 | **v2**（新 event kinds + actor 放开） | effective |
| `CLAIM_EFFECTIVE_REDUCER_VERSION` | claim-effective-reducer-v1 | **v2**（专家层） | effective |
| `CLAIM_QUEUE_VERSION` | claim-queue-shadow-v1 | **claim-queue-v2**（可执行生命周期） | effective |
| `CLAIM_QUEUE_PROPOSAL_SCHEMA` | claim-queue-proposal/v1 | **v2** | effective |
| 新 `CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION` | — | `claim-authority-write-v1` | effective（钉 meta/health） |
| 新 `CLAIM_STRUCTURAL_OVERRIDE_VERSION` | — | `claim-structural-override-v1` | base（override 输入消费于重建） |
| `AI_SUPPLEMENT_VERSION` | ai-supplement-v3-identity-preconditions | **bump**（claim 模式策略指纹） | 既有补丁域 |
| 批注基戳 | v12-claim-distribution | **v13** | 既有导出域 |
| `STAGE_IMPLEMENTATION_REVISIONS`（§5.6 各阶段） | 现值 | 各 +1 | 既有阶段域 |
| API view | v1 系列 | 按需 v2 + 新端点 v1 | — |
| `CLAIM_CATALOG_VERSION` | claim-catalog-v4 | **不动** | base |
| `CLAIM_REDUCER_VERSION`（base） | claim-reducer-v2 | **不动** | base |
| `stage_producer("ai-extract")` | — | **任何 CLAIM_* 不得进入**（延续断言） | — |

缓存语义：effective 域 bump（event schema/reducer/queue/CAS 协议）只触发纯 fold；
override 注册表变化触发 ledger-only 重建（零初抽 LLM）；`AI_SUPPLEMENT_VERSION` bump
不影响旧补丁重放；批注 v13 只失效导出缓存。

## 8. 工作包分解（按依赖序）

- **WP1 闭环验证 harness**：真实 `os._exit` effective WAL 矩阵 + interrupted fold
  health 登记 + 锁序注入 + 双重 fold 去重 + 启动 fresh 短路 + hook 轨道校验（§5.7）。
- **WP2 authority CAS**：§4.2 revision 公式 + B/A 端点强制 + HTML 降级 +
  GET revision 透出 + health `authority_cas_gap` 收口（§5.1）。
- **WP3 事件 schema v2 + 专家层 reducer**：§4.1/§5.2（含冲突/supersedes/失效规则）。
- **WP4 专家裁决 API/UI**：`POST /claim-adjudications` + 抽屉按钮组。
- **WP5 queue v2 + claim 模式补抽**：§4.3/§5.4（targeted_reextract 扩展 +
  `/claim-queue/execute` + 执行事件 + UI 按钮）。
- **WP6 结构性证伪**：§4.4/§5.3（override 注册表 + ledger-only 重建 + UI 确认流）。
- **WP7 incomplete_inputs 贯通**：§4.5/§5.6 + UI 横幅。
- **WP8 批注 span/row**：§5.8。
- **WP9 杂项收口**：acceptance/review_packet 显式三层 API、decide_trace 守卫、
  TIER 对比断言、agent 只读接线。
- **WP10 文档**：CLAUDE.md 里程碑、待办进度、本稿升冻结 + 偏差记录。

WP1 先行（验证基础设施），WP2 是 mutation 的前置门（总纲顺序），WP3→4→5→6 主线，
WP7/8/9 可并行。

## 9. 测试矩阵（全部 unittest.TestCase；UI 用 vitest）

1. **CAS**：B/A 端点缺 revision → 400；陈旧 revision → 409 + 当前值；正确值 → 成功且
   fold 触发；revision 公式双轨可复算；HTML 导入全部降级 `needs_reconfirmation` 且
   不关闭任何 claim。
2. **专家裁决**：covered/excluded/reopen 全生命周期；证据规则缺失 → 400；
   verifier 反向事实 + 未勾 supersedes → uncertain+conflict；勾 supersedes + reason →
   按裁决派生；专家事实跨 generation/指纹变化即失效；reopen 后提案重现。
3. **事件链 v2**：v1 旧行可重放；新 kind 的 hash 链/幂等/CAS（陈旧
   expected_claim_effective_revision 拒绝）。
4. **queue 执行**：端到端（mock LLM 的 targeted_reextract claim 模式）——uncertain →
   执行 → 补丁重放 → fold → covered；块非 omission 候选但 claim uncertain（G7 形态）
   可执行；LLM 异常 → requirements 零变化 + 事件记 error + 提案保持 open；
   `allow_llm` 缺省拒绝。
5. **结构性证伪**：override 写入 → catalog 重建为 eligible → 正常验证流；override
   清单进 catalog meta；fold 内不直接改状态。
6. **崩溃矩阵**：§5.7 真实强杀四类点恢复完整 trio；interrupted fold 留痕；
   无 verifier failure 误登记。
7. **并发**：同 claim 并发裁决 CAS 拒绝后者；并发相反裁决 → conflict；
   supplement 指纹失效 → replay 后 claim 自动重开。
8. **incomplete_inputs**：partial 时各产物置 true；readiness 不变；完整时为 false。
9. **mutation 纪律守卫**：全代码路径 patch requirements 写函数，断言仅
   `targeted_reextract`（含 claim 模式）调用；`decide_trace.jsonl` 在监视清单。
10. **批注**：文本块 claim 热区三态、表格行 claim 状态点、两布局一致、宁缺不猜
    （无匹配不落区）、缓存 v13 失效。
11. **Phase 1 回归**：六端点只读契约、零 LLM 哨兵（fold 路径）、版本纪律
    （CLAIM_* 不进 extraction producer）继续绿。
12. **回归**：全量 unittest、golden 6/6、前端 vitest + vue-tsc。

## 10. 验收与退出条件（全部满足才可合并 main）

1. 全量 unittest 绿、golden 6/6、前端 vitest + vue-tsc 绿。
2. **真实 B 轨复演**（机器本地、真实 LLM 路由、新副本目录）：
   a. 对一条 covered claim 执行 reopen → uncertain 且提案重现；
   b. 从队列发起定点补抽（真实 LLM）→ claim 经 reducer 关闭，事件血缘与 token
      完整；记录成本；
   c. 携带陈旧 revision 调 `/ai-review-actions` → 409 + 当前 revision；
   d. HTML 导入旧裁决 → 全部 `needs_reconfirmation`，相关 claim 不被关闭；
   e. 补抽执行中途强杀 → requirements 补丁原子性成立（无半截需求），fold 恢复；
   f. 证伪一条结构性排除 → 重建后该 claim eligible 且走完验证流；
   g. partial 文档各下游产物 `incomplete_inputs=true`，UI 横幅可见。
3. 成本留痕：b 步骤真实 token 写入 CLAUDE.md 里程碑。
4. 文档同提交。

## 11. 明确不做（Phase 1.5）

1. 不切换 readiness / TIER_GAP / `is_coverage_candidate` / 自检早停到账本口径
   （Phase 2）；`requirement_like` 不退役。
2. A 轨不建生产 catalog；`atomic_requirements.jsonl` 无 mutation 入口。
3. claim 裁决不做批量/HTML 导入（仅单条 API/UI；导出侧 token 预留不实现）。
4. agent 不自动执行补抽（只读提案 + 排队；执行仅限人/API 显式 `allow_llm`）。
5. rule 级结构性排除证伪（代码+版本通道）不在运行时实现。
6. 不动 `gui/`、不动 golden 基线、不改 decide_trace 封闭 schema、不实现第二条
   requirements 写路径。

## 12. 审核冻结项

审核人确认本稿时同时确认：

1. 顺序：WP1 闭环验证与 WP2 authority CAS 是 mutation 的前置门，不得跳序（总纲 §9）。
2. mutation 唯一通道：`targeted_reextract`（含 §5.4 claim 模式扩展——候选门替换为
   claim 前置校验），无第二条 requirements 写路径。
3. 终态只能由 reducer 派生；专家裁决只写事件；`supersedes_conflict` 未勾时冲突
   一律 uncertain（不给人机对判留捷径）。
4. HTML 导入降级 `needs_reconfirmation` 是有意的行为收紧，旧导入结果不再能关闭
   claim——**明示确认/否决**。
5. 结构性证伪走 catalog 重建（override 注册表为确定性输入），不追加 ledger event
   糊弄；per-claim 与 rule 级证伪分层。
6. 补抽执行必须显式 `allow_llm: true`，成本逐次记录；agent 不自动执行。
7. `incomplete_inputs` 仅 informational，readiness 语义不变。
8. 批注 span/row 定位沿用宁缺不猜（边际匹配，无匹配不落区）。
9. Phase 1 延后项（§5.7 九项）全部转正为本阶段强制项。
10. 验收以 §10 真实 B 轨复演为准，复演记录与成本留痕 CLAUDE.md。

冻结后动工；实施偏差逐项回本稿修订并重新确认。
