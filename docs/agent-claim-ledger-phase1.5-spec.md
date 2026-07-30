# Claim 守恒账本 Phase 1.5 实施规格（v1.1）

状态：**合并前修复与复核基线**。本文是
`docs/agent-claim-ledger-spec.md` v2.4 的 Phase 1.5 实施规格；如本文与账本总纲冲突，
以总纲为准。Phase 1 已合并于 `74c5690`，本阶段仅在
`codex/claim-ledger-phase1.5` 分支实施。

本修订替代 v1.0，并追认设计复核及合并前专家复核的裁决：需求发生变更后不得暗示已经
重新验证；语义 revision 不得复用为写 token；任何付费操作都必须留下可恢复的审计记录；
verifier 正负事实冲突不得由一条未明确 supersede 冲突事实的专家裁决直接闭合。

## 1. 范围与非目标

Phase 1.5 按依赖顺序启用四类受控能力：

1. 完成 Phase 1 的崩溃恢复、锁顺序和 fold 验证。
2. 为 A/B 两轨的需求权威写路径增加 compare-and-swap（CAS）保护。
3. 增加 claim 级专家事实、结构性排除证伪，以及必须由用户显式授权的定向补抽队列。
4. 传播 `incomplete_inputs`，并增加 claim 级批注定位。

readiness 裁决、TIER 逻辑、`is_coverage_candidate`、early-stop 行为、golden 基线、
`gui/` 和已冻结的 `decide_trace` schema 均保持不变。B 轨仍只有一条需求变更路径：
`omission_actions.targeted_reextract`。A 轨没有需求变更入口。Agent 可以读取或排队 proposal，
但不得执行 proposal。

## 2. 不可变术语

### 2.1 语义 revision 与写 revision

`target_review_revision` 是 Phase 1 的**语义 revision**。它表示当前权威语义审核状态，
参与 freshness/effective fold，并刻意排除时间戳、评论、append ordinal 等仅属于物理历史的
字段。其既有公式和消费者保持不变。

Phase 1.5 新增独立的 `target_authority_write_revision`，由 umbrella 常量
`CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION = "claim-authority-write-v1"` 固定。该 revision
仅用于权威写入，并且必须检测 ABA：

- B 轨：对 target id、当前 canonical row hash、source-event revision、有效 append ordinal
  和完整权威历史 prefix hash 求哈希。
- A 轨：对 target id、当前 state-row hash 和完整 review history prefix hash 求哈希。

因此，即使 `missing -> restored -> missing` 后当前状态表面相同，或者连续写入语义等价的
状态行，write revision 也必须不同。GET `/ai-requirements` 和 GET `/requirements` 同时暴露
两种 revision。既有 ledger base/effective row 继续使用原来的 `target_review_revision`
语义，不得用新的 write revision 替换。

允许 A 轨、B 轨和自动 merge 保留各自的 per-track 协议常量，但它们必须共同归入上述
umbrella 版本。umbrella 常量必须进入公共常量层和 health，不得只存在于文字规格中。

### 2.2 锁与稳定快照

所有 writer 使用以下全局锁顺序：

```text
B 轨变更：extraction-operation lock -> B target-publication lock -> review authority lock
A 轨审核：A target-publication lock -> review authority lock
ledger fold：target-publication snapshot -> review authority snapshot -> effective publication lock
```

持有后序锁时不得再获取前序锁。target publication lock 将 requirements 文件、metadata 和
publication revision 保护为同一个快照。对于无法持有该锁的 legacy 位置，writer 必须执行
bytes/hash CAS：先读取 target publication revision 与 fingerprint，获取 authority lock，
再读取并比较两者，任何变化都必须拒绝。

`expected_target_fingerprint`、`expected_target_publication_revision` 和
`expected_target_authority_write_revision` 必须来自同一受保护快照，并在变更前立即比较。
陈旧请求返回 409 及全部当前值。第 6 章定义的 LLM 前检查和 publication 前检查缺一不可。

`llm_pipeline.merge_review_states` 不享受豁免：每次自动 authority merge 都必须获取同一组锁，
并从受保护的输入快照提供或派生当前 write token。任何过渡期兼容路径如果无法提供 token，
只能跳过权威写入并留下显式 gap 记录，不得静默写入。缺 token 的 legacy 导入同样不得生成
权威事实。

### 2.3 resolution 事实与 operation 事实

只有 resolution 事实参与 `reduce_claim`：

- bridge 事实：`target_invalidated`、`target_reactivated`；
- `expert_adjudication`、`audit_conflict`；
- 结构有效的 catalog/base 事实。

operation 事实包括 `reextract_started`、budget checkpoint、publication checkpoint、成功、
失败、中断和重试。它们不进入 resolution reducer，也不改变
`claim_effective_revision`，只用于派生队列 lifecycle 和恢复被中断的付费操作。

## 3. 事件与文件契约

### 3.1 `claim_review_events.jsonl`：v1/v2 混合 append-only 链

`CLAIM_REVIEW_EVENT_SCHEMA` 升为 `claim-review-event/v2`。该文件是混合版本的
append-only 日志，不得整体重写为 v2：

- 每个已存储 row 保留自己的 `schema` 值；
- loader 按 row 分派到 v1 或 v2 validator；
- 在做 normalization/defaulting 之前，必须依据原始存储 row 及其声明的 hash domain 验证哈希；
- v2 appender 接受合法的 v1 prefix，并继续同一条物理 hash chain；
- torn-tail recovery 和 quarantine 保持相同的逐 row 行为。

v2 JSON schema 必须是严格的、按 `event_kind` 判别的 union（`oneOf`）。bridge 字段不得变成
其他 event kind 的可选字段。v1 bridge event 继续保留其 v1 必填字段和原有含义。

v2 resolution event：

| event kind | 必填事实 | reducer 含义 |
| --- | --- | --- |
| `expert_adjudication` | claim id/hash、adjudication、reason、结构化 evidence、expected effective revision、被 supersede 的 fact hash | 候选专家事实 |
| `audit_conflict` | claim id/hash、冲突 fact hash、evidence、reason | `uncertain + conflict` |
| `structural_falsification` | claim id/hash、允许证伪的原结构原因、override id/hash | 请求 catalog 重建，不直接改变 resolution |

`expert_adjudication` 的值只能是 `covered`、`excluded_non_normative` 或 `reopen`。
evidence 必须结构化，不得是自由文本数组：

- `coverage_group`：group id 和当前 group hash；
- `target_evidence`：target id/fingerprint、produced-evidence locator/hash，以及 source claim
  locator/hash；
- `source_exclusion`：当前 source verbatim locator/hash 和允许的排除原因。

reducer 每次 fold 都重新验证全部 locator、hash、target active 状态及关联 coverage group。
`covered` 必须具有当前 validated group 或 target evidence；`excluded_non_normative` 必须具有
当前 source exclusion span。只有 reason 的裸裁决永远不能闭合 claim。

`reopen` 的 `supersedes_fact_hashes` 在 schema 中必须设置 `minItems: 1`。实现采用
`supersedes_fact_hashes[]` 而不是布尔 `supersedes_conflict`，以便明确指出被替代的具体事实。

### 3.2 补抽 attempt 日志

新增 `claim_reextract_attempts.jsonl`，schema 为 `claim-reextract-attempt/v1`。该文件在
extraction operation lock 下 append-only 且 hash chained，具有独立的 sequence 和
idempotency namespace，不属于 `claim_review_events.jsonl`。

每个 attempt 包含 `attempt_id`、`proposal_id`、`claim_id`、request idempotency key、actor、
请求的 route/model、显式 budget、preflight fingerprint/revision、focus adapter 结果和时间戳。
合法 transition event 为：

```text
reextract_started
budget_checkpoint
supplement_persisted
requirements_published
base_rebuild_published
effective_folded
reextract_succeeded | reextract_failed | reextract_interrupted | reextract_aborted_stale
```

每个 attempt 最多有一个 terminal event。远程调用前，以及获得响应或错误后，都必须持久化
budget checkpoint，并记录实际已知 usage。必须使用 `chat_json_with_meta` 或等价的
usage-bearing API；普通 `chat_json` 不满足要求。进程在计费后、结果落盘前死亡时，必须恢复为
带已收费或 usage unknown 的 `interrupted` attempt，不能伪造成零成本失败。

启动或读取队列时，recovery 从 attempt log、supplement 和 requirements publication 事实派生
状态，绝不盲目重试。已持久化 supplement 或 requirements publication 但缺少下一 checkpoint
时，应补投影相应 checkpoint；状态有歧义时标记 `interrupted`，并要求用新的 attempt id
显式重试。

### 3.3 队列 proposal

`claim_queue_proposals.jsonl` 升为 `claim-queue-proposal/v2`。proposal 是当前 claim 与
attempt 的确定性投影：

- `open`：eligible `uncertain` claim，且无 live attempt；
- `executing`：存在持久化的非终态 attempt；
- `executed`：最新 terminal attempt 为 `reextract_succeeded`，且 base rebuild 与
  effective fold checkpoint 均成功；
- `rebuild_pending`：requirements 已发布，但 base rebuild/fold 尚未成功发布；不得显示为已闭合；
- failed、interrupted 或 stale-aborted attempt 使仍 eligible 的 claim 回到 `open`，并暴露
  最新 attempt outcome。

`execution_preconditions` 包括 claim id/hash/source fingerprint、
`expected_claim_effective_revision`、parent block fingerprint、target publication revision、
适用时的 semantic/authority-write revision，以及按 source kind 区分的 focus object。
不存在通用的 `focus_lines` 断言。

focus adapter 必须确定且有版本：

- `text_span`/list item：经过验证的 source text line 和 offset；
- `table_item`：table id、row index、field key/value identity；
- `table_data_rows`：稳定 row window 和 canonical cell hash；
- `table_fallback`：确定性 row-window identity，禁止把整个大表 block 作为单个 claim。

无法派生合法 adapter 时，在任何 LLM 调用之前以 422 拒绝 proposal execution。table row
不要求是 section prose 的逐字子串；这是按数据类型处理的既定设计，不得退回通用字符串断言。

### 3.4 结构 override registry

`claim_structural_overrides.jsonl` 是 append-only、hash chained 的唯一权威来源，记录已接受的
per-claim 结构 override。review event 日志中的 `structural_falsification` 只是引用该 registry
的审计投影，不是第二个权威源。

首版仅允许证伪 `repeated_page_furniture`。`empty` 和 `separator_only` 不可在 runtime
override。每条 override 记录当前 claim id/hash、catalog generation、original proof、允许的
reason、actor 和 registry prefix hash。registry prefix hash 与 override version 必须进入
catalog-generation identity，而不能只作为 metadata。

写入 override 后，旧 effective snapshot 立即 stale。重建失败时必须保持
`stale/rebuild_pending`，不得继续把旧 structural exclusion 表示为 fresh。确认 API 必须携带
显式 `allow_llm`、route 和 verifier budget，因为新 eligible claim 的 ledger-only refresh
可能需要经过授权的 semantic verifier。默认结构 override 路径为确定性 `0 LLM`；只有用户
明确授权时才允许 verifier 调用。

### 3.5 Legacy supplement

既有 supplement 必须继续可 replay。`AI_SUPPLEMENT_VERSION` 不得被全局当作单一 equality
gate；loader 按 `strategy_version` 分派，并保留
`ai-supplement-v3-identity-preconditions` compatibility handler。claim-mode supplement 使用
新的 mode-specific strategy version，并携带
`origin={kind:"claim_queue", claim_id, proposal_id, attempt_id}`。未知或不支持的版本必须带
显式 replay diagnostic 诚实跳过，不得静默应用。

## 4. Authority CAS 写路径

所有 B 轨 `/ai-review-actions` 和 A 轨 `/review-actions` 写入都要求：

```text
expected_target_fingerprint
expected_target_publication_revision
expected_target_authority_write_revision
```

缺字段返回 400；任一不匹配返回 409，并返回全部当前值。UI 必须在提交前读取 fresh 值，
并在 409 后重新拉取 authoritative row，同时保留用户尚未提交成功的草稿。旧的语义
`target_review_revision` 继续展示，但不能充当 write CAS。

无当前 token 的 HTML decision import 采用更严格的降级策略：跳过权威写入并计数，不生成
`needs_reconfirmation` proposal。`import-clarification-answers` 必须逐 record 报告 conflict，
不得静默丢弃 stale record。该 skip+count 口径比 v1.0 的 proposal 方案更保守，现正式追认。

health 中既有 `authority_cas_gap` 仅表示 fold/runtime 观察；写协议 rollout 使用独立字段：

```text
authority_write_protocol_version
legacy_authority_write_gap_count
```

`authority_write_protocol_version` 必须等于 umbrella
`CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION`。任何 legacy、自动 merge 或暂时兼容路径只要未执行
完整 CAS，就必须增加 `legacy_authority_write_gap_count` 并留下 route/reason 留痕；不得以
per-track 常量替代 umbrella health 契约，也不得存在无 CAS 且无留痕的豁免。

## 5. Claim 裁决与并发

`POST /claim-adjudications` 要求当前 catalog generation、claim id/hash、adjudication、reason、
typed evidence、actor 和 `expected_claim_effective_revision`。它在 claim-event lock 下精确
append 一条 v2 resolution event，并在释放 authority lock 后调度或执行确定性 fold。

并发有三种刻意区分的语义：

1. 两个请求基于同一 effective revision 竞争：第一个提交，第二个返回 409，不创建
   conflict fact。
2. 后续请求读取新 revision 后刻意推翻先前裁决：必须使用 `reopen`，或携带 reason 并在
   `supersedes_fact_hashes[]` 中显式替代具体先前事实。
3. 独立存在的当前冲突事实，包括 imported/audited facts，由 `audit_conflict` 表示，并归约为
   `uncertain + conflict`，直到后续事实显式 supersede 或 reopen。

当 base 已包含 `positive_negative_conflict` 时，`covered`、
`excluded_non_normative` 和 `reopen` 都必须在 `supersedes_fact_hashes[]` 中包含**全部当前
正向 base fact hash 与全部当前负向 base fact hash**。不传、只传一侧或漏掉任一当前冲突
事实时，写入阶段返回 400，且不 append event；历史日志中不满足该条件的事件在 replay 时
必须判为非 current，claim 保持 `uncertain`。只有显式 supersede 冲突两侧全部事实、且 typed
evidence 仍 current 时，专家裁决才可闭合。

对于已处于普通 `covered` 或 `excluded` 终态的 base，未显式 supersede 当前相反终态事实的
反向裁决同样在写入阶段返回 400，不得先写入再由 fold 制造 conflict。携带正确具体 fact hash
的显式推翻仍按本章第 2 类并发语义处理。

不存在布尔 `supersedes_conflict`，因为它不能标识被替代的事实。专家事实会在 claim hash、
evidence locator/hash、target activity/fingerprint、adapter version、reducer version 或
catalog generation 变化后过期，但仍作为审计历史可读。

## 6. 队列执行与真实闭合路径

`POST /claim-queue/execute` 要求 proposal id、expected claim effective revision、expected
ledger state `uncertain`、actor、`allow_llm: true`、route、maximum calls、total token budget
以及 client idempotency key。默认拒绝执行。endpoint 在 LLM 工作前返回 400/409/422，远程
失败返回 502，artifact 不可用或 recovery pending 返回 503。

UI 点击执行时不得由 api-client 硬编码 `allow_llm: true`。必须先显示确认对话框，明确展示
claim、route/model、maximum calls 和 total token budget，并提供默认未勾选的
`allow_llm` checkbox。只有用户主动勾选并确认后才发送 `allow_llm: true`；取消、未勾选、
关闭对话框或切换 claim 均不得发起执行请求。409 后重取最新状态并保留可复用的表单输入，
但必须重新取得本次付费授权。Vitest 必须覆盖未授权零请求、授权 payload、取消和 409 路径。

claim mode 只在需求变更和既有 extraction-operation lease 范围内扩展
`targeted_reextract`。它**不得调用 `apply_omission_action`**，不得修改
`omission_states.jsonl`，也不得写 block 级 `issue_confirmed` 或 `resolved`。测试必须断言
claim-mode 执行前后该文件逐字节相同。

必须遵循以下持久化顺序：

1. 按第 2.2 节顺序获取锁，验证全部 queue、claim、authority、source、target-publication
   和 budget precondition。
2. append `reextract_started`；持久化调用前 budget checkpoint。
3. 通过 usage-bearing API 调用 LLM；持久化调用后 usage 或 error。
4. 重新获取并验证全部 mutation-sensitive precondition。不匹配时写入
   `reextract_aborted_stale` 和真实 usage，返回 409，不发布需求变更。
5. 持久化 supplement，并原子发布 requirements；记录两类 checkpoint 和产生的 target
   publication revision。
6. 释放 extraction/authority lock。以 **ledger-only base rebuild** 调用
   `refresh_claim_shadow`；只有实际需要且用户已经显式授权时，才转发 `allow_llm`、route 和
   verifier budget。该步骤构建新的 coverage group，并可运行已授权 verifier；单独调用
   `fold_effective_ledger` 不能完成此工作。
7. 发布新 base generation，再执行 fold；记录 base 与 effective generation/revision
   checkpoint。仅在此后写入 `reextract_succeeded`。

如果 requirements 发布后 refresh/fold 失败，attempt 按可恢复性进入 `rebuild_pending` 或
`reextract_failed`，claim 保持未闭合。recovery 只恢复确定性的 pending publication 工作，
不得自动发起 LLM，也不得因为 supplement 存在就声称 `covered`。只有新 base 已构建后，
fold 才是零 LLM 操作。

## 7. 下游与批注契约

使用一个确定性 helper 读取并校验 source `ai_requirements.meta.json` lineage 和当前
requirements publication。当 `failed_sections`、`failed_section_ids` 或
`failed_section_block_ids` 非空，或者所选 snapshot 为 partial 时，设置
`incomplete_inputs=true`。不得虚构 `extraction_status` 字段。该字段传播到：

- functional synthesis output；
- `engineering_requirements.json`、`engineering_analysis.json` 和
  `compliance_items.json`；
- template writer report、merged-spec report、clarification report 和 engineering
  composer output。

每个 consumer 在传播该标志前，都必须校验 input fingerprint/producer lineage。该标志只作
信息提示，不改变 readiness 行为。

`template-write` 和 `compose` 的 `STAGE_INPUTS` 必须显式包含
`ai_requirements.meta.json`；对应 `STAGE_IMPLEMENTATION_REVISIONS` 必须 bump，使缺少
`incomplete_inputs` 的旧缓存失效。仅修改 helper 而不 bump stage revision 不满足本规格。
测试必须证明 metadata 变化会使这两个 stage 的旧缓存失效，并在新产物中传播该字段。

annotation export 通过第 3.3 节的 focus adapter 映射每个 claim。text/list claim 仅在
确定性 source 精确匹配时生成 span zone；table claim 使用 row geometry 和 row card；匹配
失败时不生成 zone。不得使用宽松或推测定位作为 fallback。optimized 与 original-PDF layout
必须包含相同的 claim status 集合。`doc_annotation_export` 从
`v12-claim-distribution` bump 到 v13。该“只用精确档”的实现比早期规格更严格，现正式追认。

## 8. 版本与缓存纪律

| 常量/artifact | Phase 1.5 值 | 域 |
| --- | --- | --- |
| `CLAIM_REVIEW_EVENT_SCHEMA` | `claim-review-event/v2` | effective/audit |
| `CLAIM_EFFECTIVE_REDUCER_VERSION` | `claim-effective-reducer-v2` | effective |
| `CLAIM_QUEUE_VERSION` | `claim-queue-v2` | effective |
| `CLAIM_QUEUE_PROPOSAL_SCHEMA` | `claim-queue-proposal/v2` | effective |
| `CLAIM_AUTHORITY_WRITE_PROTOCOL_VERSION` | `claim-authority-write-v1` | write protocol/health |
| `CLAIM_REEXTRACT_ATTEMPT_SCHEMA` | `claim-reextract-attempt/v1` | operation audit |
| `CLAIM_STRUCTURAL_OVERRIDE_VERSION` | `claim-structural-override-v1` | catalog generation |
| `AI_SUPPLEMENT_VERSION` | 保留 v3 loader；新增 claim-mode strategy version | supplement replay |
| annotation export | v13 | annotation cache |

override registry prefix hash 必须进入 `catalog_generation_id`、base metadata 和 freshness
检查。effective-only 版本变化不得进入 `stage_producer("ai-extract")` 或 extraction cache key，
也不得触发 initial extraction。需求变更是例外：requirements 发布后必须有意调用
`refresh_claim_shadow`，因为 base coverage graph 已改变；这不是 effective-only refold。

所有新增的 `CLAIM_*` effective 常量都必须有 stage-producer 不变性断言。第 7 章要求的
`template-write`/`compose` stage revision bump 属于下游缓存修复，不得误接入 extraction
producer fingerprint。

## 9. 工作包

1. WP1：effective WAL 崩溃、锁顺序、双 fold 去重与 fresh 启动短路 harness。
2. WP2：target publication lock、semantic/write revision 拆分、A/B/automatic merge CAS、
   GET 暴露，以及 umbrella health rollout 字段。
3. WP3：混合 v1/v2 event chain、严格 schema、typed expert evidence、reducer
   conflict/supersession 规则，以及 expert API。
4. WP4：attempt log/WAL、queue lifecycle 投影、budget accounting 和 recovery。该工作包通过前
   不得提供 UI 执行控制。
5. WP5：claim-mode targeted extraction、两次 CAS 检查、supplement compatibility、
   refresh-base-then-fold 闭合路径，以及带显式付费确认的 queue UI。
6. WP6：structural override registry、catalog identity/freshness、rebuild 路径，以及确认时的
   budget contract。
7. WP7：incomplete inputs 和 annotation adapter。
8. WP8：文档、metrics 和 `CLAUDE.md` 里程碑记录。

WP1 和 WP2 是强制 gate。WP3 和 WP4 必须先于任何 mutation endpoint。WP5 依赖 WP2-WP4。
WP6 可在 WP2 后执行，但必须使用相同的 base publication/freshness 协议。WP7 在 adapter
contract 固定后可独立执行。

WP1 的“完成”必须包含以下四项机制级验证，不得以普通异常 mock 或相邻单测替代：

1. 真 `os._exit` effective WAL 矩阵：覆盖 journal durable 前后、每个固定文件 replace、
   effective meta/commit point 前后；恢复结果只能是完整旧代或完整新代，不能混代。
2. 双 fold 去重：对同一 base、authority 和 event prefix 连续 fold，不重复 append bridge
   event、不重复 queue operation、不改变无关 claim revision，第二次结果与第一次语义等价。
3. 启动 fresh 短路：current effective snapshot 在启动时不重建、不改写文件字节、不增加
   health/fold 计数，也不调用 refresh/chat/verifier。
4. 锁顺序注入：在 A 写、B 写、automatic merge、fold 和 recovery 入口注入锁探针，证明无
   逆序获取、无 TOCTOU 接受，并能在受控并发下结束而非死锁。

另外必须恢复 v1.0 已提出但 v1.1 曾遗漏的治理验证：authority 已提交但 fold 被中断时，health
如实增加 `bridge_fold_lag` 并在后续恢复清零；A/B hook 必须各自验证所声明的轨道和 producer，
不得串轨；Phase 1.5 行为不得改变冻结的 `decide_trace` schema/内容；TIER 与 readiness 仍按
既有口径，并有显式断言。上述删除项此前没有批准理由，本版不再将其静默视为取消。

### 9.1 延后项：acceptance/review-packet 显式 API

Phase 1.5 不新增 acceptance 和 review packet 的显式 HTTP API，继续使用现有 CLI 与机器本地
artifact 流程。延后理由是：两者是离线验收/人工审核载体，可能包含敏感 source/target wording；
在 mutation 安全门修复期间仓促扩大 HTTP surface，会引入额外的权限、脱敏和 freshness 契约，
且不阻塞本阶段的权威写安全。

该延后存在明确风险：桌面端暂时无法通过统一 API 获取 freshness-bound acceptance 状态和
review packet identity，调用方仍需协调文件路径与 CLI schema，可能产生展示漂移。缓解措施是
Phase 1.5 不让这些离线文件参与 mutation 授权，且 readiness 切换仍以既有 acceptance gate
为准。

后续工作固定在 **Phase 2 readiness 切换前**：设计 local-only、read-only 的显式 endpoint，
绑定 artifact schema、generation/freshness 和敏感字段最小化策略；补 200/409/503、stale
identity、脱敏和不写盘测试。该项只能按独立规格启用，不得在没有安全契约时临时暴露文件。

## 10. 必需测试

所有后端测试必须使用 `unittest.TestCase`；UI 测试使用 Vitest。

1. comment/timestamp-only authority 变化不改变 semantic revision，但 history/ABA 变化必须
   改变 authority write revision。
2. A/B/manual/automatic 写入拒绝缺失或 stale 的 publication/write token；锁顺序注入证明
   无逆序获取和 TOCTOU 接受。`llm_pipeline.merge_review_states` 必须包含同等 CAS 断言。
3. v1 prefix 加 v2 row 可以 replay 并验证 hash，且不先 normalization；拒绝 malformed v2
   discriminated variant；torn-tail recovery 正常工作。
4. 同一 base 上的竞争裁决得到一次 commit 加一次 409，而不是 conflict。后续显式推翻和独立
   记录的 conflict 分别遵循第 5 章语义。
5. conflict base 的无 supersede、单侧 supersede 和漏事实裁决均不能闭合；显式 supersede
   全部正负事实后才可闭合。普通终态的无 supersede 反向裁决在写入时返回 400。
6. evidence contract 拒绝 bare reason、stale locator、stale coverage group、inactive target
   和非法 exclusion reason；`reopen.supersedes_fact_hashes` 为空时 schema 拒绝。
7. attempt crash matrix 覆盖每个 checkpoint、billed-before-result recovery、idempotent retry、
   第二次 CAS stale，以及 requirements publication 缺对应 attempt checkpoint；实际已知成本
   永不丢失。
8. claim-mode re-extraction 前后 `omission_states.jsonl` 逐字节相同；LLM failure/zero output
   保持 requirements 不变、proposal open。
9. 端到端变更证明 `requirements_published -> refresh_claim_shadow -> new base generation ->
   fold`；只 mock fold 不能闭合 claim。重建失败返回 `rebuild_pending`/stale，不得 covered。
10. 允许的 structural override 改变 catalog generation/freshness；重建失败不能把旧排除显示为
    fresh；禁止的 reason 返回 400。
11. legacy v3 supplement 可以 replay，claim-mode supplement 按 strategy version 和 origin
    replay，不支持的版本产生诚实 diagnostic。
12. partial 与 lineage-mismatched input 将 `incomplete_inputs` 传播到所有已列 artifact，且不
    改变 readiness；`template-write`/`compose` 的 metadata input 与 stage revision 可使旧缓存
    失效。
13. text/list/table/table-fallback adapter 及两种 PDF layout 定位正确；无法精确匹配时不生成
    zone。
14. Phase 1 回归：effective-only version bump 不调用 refresh/chat/verifier；无关 claim event
    不改变 claim revision；既有六个 read API 契约不变；所有新增 effective `CLAIM_*` 常量不
    改变 extraction producer。
15. WP1 四项 mandatory harness 全部通过：真 `os._exit` WAL 矩阵、双 fold 去重、启动 fresh
    短路、锁序注入。
16. authority-write umbrella 常量和两个 health rollout 字段有 schema/读写测试；legacy gap 与
    automatic merge 的无 token 路径必须有计数和留痕。
17. authority commit 后 hook/fold 故障产生 `bridge_fold_lag`，A/B hook 各自归属正确；恢复后
    health 收敛。
18. `decide_trace` 文件/schema 不变，TIER/readiness 口径不变，并断言
    `claim_shadow_metrics.json` 在 effective-only 操作中逐字节不变。
19. queue UI：默认未授权时零请求；勾选后 payload 才含 `allow_llm: true` 和用户看到的
    route/budget；取消、切换 claim 和 409 重取路径保持成本授权诚实。

## 11. 验收门

合并前必须通过完整 `python -m unittest discover -s tests`、前端 `npm test`、
`npm run build`，以及在 main checkout 中使用文档规定的三个 seed KB/domain pack 完成
golden 6/6。不得修改 golden baseline。

WP1 四项 mandatory harness、B3 冲突 supersession、B5 umbrella health、B6 stage cache
失效和 B7 UI 成本确认均是 gating；缺任一机制级断言时不得以“其他全量测试通过”替代。

在新的本地副本中进行一次真实 B 轨演练，并记录：

1. expert reopen 和 stale-CAS rejection；
2. 一次由用户显式授权的 targeted extraction，包含真实 route/model/token checkpoint、
   refresh-base-then-fold 证据和诚实终态；
3. 一次 interrupted paid attempt，以及无重复 publication 的 recovery；
4. 一次带 base generation/freshness 变化的 structural override；
5. partial-input propagation 和 annotation row/span output。

`CLAUDE.md` 必须记录命令、测试数量、真实演练成本、性能测量和批准的偏差。API key、客户文档、
客户措辞和本地 replay 副本永不提交。

acceptance/review-packet 显式 API 是第 9.1 节唯一获批准的延后项；其延后不豁免现有 CLI/artifact
acceptance gate，也不得被解释为允许 mutation 绕过审核。

## 12. 批准清单

批准表示接受以下不变量：

1. fold 永不创建 coverage edge；需求变更必须先重建 base，之后才能 fold 或声称闭合。
2. semantic review revision 与 physical authority-write revision 相互独立，ABA 必须可检测。
3. 每次 authority write 都使用稳定 cross-store snapshot 和 CAS；automatic merge 无豁免。
4. umbrella write-protocol version 和 legacy gap 必须进入 health，不能只保留 per-track 常量。
5. 付费 queue execution 具有持久 attempt/budget 历史并可恢复；UI 授权默认关闭且逐次显式。
6. claim-mode execution 不得改变 block-level omission authority。
7. event v1/v2 共存时保留 raw-row hash-chain validation。
8. base verifier 正负冲突只有在全部两侧事实被显式 supersede 后才可由专家闭合。
9. structural override 是 catalog-generation/freshness 输入，不是装饰性 metadata。
10. `incomplete_inputs` 和 locator 行为必须显式、按 source kind 区分、仅作信息提示；下游缓存
    必须绑定 metadata producer lineage。
11. `decide_trace`、TIER、readiness、golden 和 Phase 1 read API 契约保持不变。
12. acceptance/review-packet 显式 API 仅按第 9.1 节延后，并须在 Phase 2 readiness 切换前完成
    独立安全规格和实现。
