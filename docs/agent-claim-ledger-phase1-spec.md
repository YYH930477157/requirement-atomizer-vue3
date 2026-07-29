# Claim Conservation Ledger — Phase 1 实施规格（生产双写，不切门控）v1.4

状态：**v1.4 worktree 实现与代码/真实复演/规模/分发门已通过；仅待用户决定合并及 main checkout golden 6/6。该门通过前不标记 Phase 1 完成**。本稿是
`docs/agent-claim-ledger-spec.md`（v2.4，实施契约澄清）§9 Phase 1 的
施工规格；总纲与本稿冲突时以总纲为准。总纲 §14 冻结项 10 规定的顺序
（Phase 0A/0B → Phase 1 只读投影闭环 → Phase 1.5 mutation/CAS → Phase 2 切门控）不可跳过。

- 实施分支：`codex/claim-ledger-phase1`（独立 worktree，用户决定合并）。
- 实施纪律：后端测试一律 `unittest.TestCase`；提交前全量 unittest + golden 6/6 绿；
  版本常量按 §7 表 bump；未要求不 commit、不 push。

---

## 1. 定位与范围

Phase 0A/0B 已把 catalog / coverage groups / base+effective ledger / 双 meta / verifier attempt
链以 **shadow** 形态写入每次 ai-extract 的产物目录（默认常开，stub 路由也写），并已进入
`desktop_tasks.STAGE_REQUIRED_OUTPUTS["ai-extract"]`。Phase 1 把这些产物从"影子"转为
**生产双写**：旧覆盖报表与 readiness 原样保留（兼容字段），新账本并排展示、可被 API/UI/导出
消费，但**任何现有门控（readiness、stage 复用、golden、chain）都不依赖 ledger 结论**。

总纲 §9 Phase 1 原文边界（逐字引用，不可扩大）：

> - 正式写 catalog、base/effective ledger、generation/effective meta；
> - 接入 claim 级只读 API/UI/导出、effective reducer 和 review-state bridge；
> - claim queue 与定点补抽在本阶段只生成 shadow/dry-run proposal，不修改 requirements 或
>   claim 终态；旧覆盖报表继续作为兼容字段；
> - 新旧 coverage 并列展示，生产 readiness 暂不依赖 ledger。

**Phase 1 一句话**：账本开始"正式说话"，但还"说了不算"；唯一会动的机制是
**review/target authority 驱动的 effective fold + 审计事件投影**——专家拒绝/恢复一个 AI 需求后，
关联 claim 在不重跑抽取的前提下于 effective ledger 中重开/恢复。

## 2. v1.4 实施状态基线（2026-07-28 最终 worktree 证据）

本节只报告当前 `codex/claim-ledger-phase1` worktree 的事实，不替代 §10/§11 的退出门。worktree 可执行的
代码、真实数据、规模、HTTP、前端与 wheel 门已经连续复验；main checkout golden 仍必须在用户批准合并后执行。

**已实现并通过最终验证：**

- immutable base 与 mutable effective loader 分层；effective ledger/queue/meta 三文件 WAL、唯一提交点、
  torn-tail/quarantine、health 与 freshness；effective-only 路径为 deterministic、零 LLM/verifier；
- `claim_review_events.jsonl` 的 seq/hash chain/幂等投影，B 轨 authority 全历史 reconcile，target
  `missing → restored → missing` 的 ABA 防护，group 失效与同一验证事实的显式复用；
- 六个只读 view、API 路由、固定排序/分页/revision pin，以及 Vue3 Claim Ledger 页面；
- ai-extract、B 轨专家裁决、服务启动 maintenance、CLI/desktop `claim-ledger-fold` 的 fold 触发；
- informational `clarification_report.claim_ledger`、chain 的 fresh/open 摘要、run manifest
  `claim_components`、整块 covered/excluded/uncertain 批注角标；新模块已登记进 wheel 配置。
- A 轨已与 B 轨共用 target authority、全 history、reconcile/event/fold/freshness 契约；无 committed
  generation 才 honest no-op。A/B 完整坏行均产生 live audit gap，GET 零写入；target parse/hash 使用同一
  bytes snapshot，只读前后复验及 fold CAS 阻断 ABA。
- 六端点真实 HTTP 200/503、pending journal/recovery、generation/claim-hash 事件过滤、分页和 GET 物理零写入
  均有回归；`claim_components`、clarification 与批注角标有端到端断言。
- 合并前专家门 B1-B6 已闭合：旧质量口径读取真实生产文件，异常边界只吸收声明的 artifact 错误，
  v1→v2 migration 进入 health，脏 legacy validation fingerprint 跳过复用；A/B hook 故障、effective-only
  版本 bump、两 claim revision 隔离、document revision 五要素、migration-required HTTP、producer 分层与
  `claim_shadow_metrics.json` 字节不变均有机制级断言。
- 真实 B 轨 878-claim 副本完成 reject/reactivate：verifier attempt/call/token 增量 0，attempt 日志 SHA-256
  不变；恢复复用 1 个 validated group。客户文本、ID 与本机路径不进仓。
- 500-block 基线：catalog p50/p95 0.0227s/0.0232s，base 2.76 MiB；500 links + 2000 history/events 的
  reconcile+fold p50/p95 3.603s/3.699s，candidate checks=2000，证明无笛卡尔扫描。
- 最终后端 2104 tests OK（7 个环境 skip），前端 145 tests、typecheck/build、wheel/schema 隔离安装 smoke、
  `git diff --check` 与独立最终审查均通过。

**尚待唯一退出门**：用户决定合并后，在拥有冻结 `out/` 的 main checkout 按三 seed KB + domain-pack 口径
跑 golden 6/6。worktree 的环境 skip 不计通过，未执行前不宣称 Phase 1 完成。

## 3. Phase 1 设计公理

在总纲 §1 公理之上，Phase 1 追加七条，违反任何一条即返工：

1. **零 mutation**：Phase 1 代码不得写 `requirements*.jsonl`（除既有抽取路径自身）、
   `review_states.jsonl`、`ai_review_states.jsonl`、`omission_states.jsonl`、
   `decide_trace.jsonl`。claim queue 只产出 dry-run proposal 文件。测试必须断言这一点
   （见 §10 测试 9）。
2. **事件只有投影**：`claim_review_events.jsonl` 在 Phase 1 只承载 bridge 对 review authority 与
   target-set authority 变化的审计投影
   （`target_invalidated` / `target_reactivated`），actor 恒为
   `system:claim-review-bridge`；没有任何专家写入口、没有 API POST。
3. **正确性不依赖投影成功**：effective fold 每次都必须直接重读当前 target set 与权威
   review state（总纲 §2.5）；投影事件是审计便利，丢失/滞后只影响审计完整性，不影响
   fold 结论。
4. **三层读取**：不可变 base generation、已提交 effective snapshot、live target/review authority
   分层校验。API/UI/导出只读取前两层并单独计算 freshness；撕裂/损坏读 → 503 retryable，
   内部一致但 authority 落后的 effective → 返回已提交快照并标记 stale，不在请求路径里 fold。
5. **门控绝缘**：readiness_verdict、stage 复用、golden、chain 跳过逻辑、merged_consistency
   输出结构、clarification TIER 判定，Phase 1 一律不改语义。账本结论以 informational
   字段并列出现。
6. **base 不可变**：review authority、bridge/effective reducer/queue/event schema 的变化不得令
   base generation 失效；base currency 只由 catalog、coverage/negative 验证及其生成时血缘决定。
7. **effective-only 零 LLM**：authority 变化、旧 effective 迁移及 queue 重建只允许 deterministic
   fold；不得调用 `refresh_claim_shadow`、coverage/negative verifier 或任一 chat 入口。

## 4. 数据契约（新增）

### 4.0 规范化序列化、hash 与 ID

Phase 1 新增产物只允许一套规范化规则；禁止各模块分别使用“带换行 JSON / 不带换行 JSON”、裸 hex
和 `sha256:` 前缀等不同口径：

- `canonical_json_bytes(value)` = UTF-8 编码的 JSON，`ensure_ascii=false`、对象键按 Unicode
  code point 升序、分隔符固定为 `(',', ':')`、禁止 NaN/Infinity，**无 BOM、无尾随换行**；字符串
  内容不另做 Unicode 归一化。JSONL 物理行固定为 `canonical_json_bytes(row) + b'\n'`。
- `sha256_bytes(payload)` = 原始 bytes 的 SHA-256，wire value 同样为小写 `sha256:<64 hex>`；
  `sha256(empty_bytes)` 是它在空 bytes 上的固定值。
- `hash_json(domain, payload)` = `sha256(canonical_json_bytes({"domain": domain,
  "payload": payload}))`，wire value 一律为小写 `sha256:<64 hex>`。所有下述“hash”公式都按此
  domain-separated 形式实现，不再用歧义的字符串 `a | b | c` 拼接。
- 既有 B 轨 `review_subject_fingerprint` / coverage edge 允许历史裸 `<64 hex>`，但进入 Phase 1
  event、effective meta/facts、API envelope 前必须经
  `canonical_target_fingerprint(value)` 规范为 `sha256:<64 hex>`；比较前两侧都先规范化。base group
  冻结，不就地改写历史裸值。非法或大小写不规范的输入不是“不同 fingerprint”，而是 artifact error。
- `digest_hex(value)` 只接受规范化 `sha256:` 值并去掉前缀。任何 ID 中的摘要片段均从
  `digest_hex(...)` 截取，不能从包含 `sha256:` 的 wire string 直接切片。

`base_generation_id` 固定为：

```
hash_json("claim-base-generation/v1", {
  document_generation_id,
  catalog_generation_id,
  catalog_sha256,
  coverage_groups_sha256,
  base_ledger_sha256
})
```

它标识 immutable base facts，不等同于 extraction `run_id`，也不等同于只标识源文的
`document_generation_id`。effective meta 与所有 API envelope 都携带该值。

### 4.1 `claim_review_events.jsonl`（新文件，append-only）

schema：`schemas/claim_review_event.schema.json`，`schema: "claim-review-event/v1"`。
字段（总纲 §2.5 的 Phase 1 投影子集）：

- 链与身份：`event_seq`（publication 锁内单调分配）、`event_id`
  （`CRE-<十进制 event_seq>-<digest_hex(idempotency_key) 前12>`，避免 event_id/event_hash 循环定义）、
  `prev_event_hash`、`event_hash`
  （见本节下方公式）、`schema`；
- 归属：`claim_id`、`claim_hash`、`document_generation_id`、`catalog_generation_id`、
  `event_kind`（`target_invalidated|target_reactivated`）、`eligibility_before`、
  `eligibility_after`（`active|rejected|unknown`）；
- 证据：`actor`（恒 `system:claim-review-bridge`）、`recorded_at`（带时区 ISO）、
  `reason`（非空受控原因）、`trigger_kind`（`review_authority|target_set`）、
  `source_store`（review 触发为 `ai_review_states.jsonl|review_states.jsonl`，target-set 触发为
  `ai_requirements.jsonl|atomic_requirements.jsonl`）、
  `source_event_revision`、`target_review_revision`、`target_kind`、`target_requirement_id`、
  `target_fingerprint`（关联 base edge 的期望 fingerprint，按 §4.0 规范化）、
  `observed_target_fingerprint`（当前 target 缺失时为 `null`，否则按 §4.0 规范化）、
  `linked_claim_ids`（同一 target 影响的全部 claim）、`idempotency_key`；
- CAS 与代际：`projection_mode`（`cas_effective|bootstrap_base`）、
  `expected_base_claim_row_hash`、`expected_claim_effective_revision`、`bridge_version`
  （= `CLAIM_REVIEW_BRIDGE_VERSION`）、`route: "deterministic"`（投影零 LLM）。

revision 口径固定为：

- B 轨 `source_event_revision = hash_json("claim-source-event-revision/v1",
  {source_store, append_ordinal, source_row})`；`append_ordinal` 是 torn-tail 恢复后从 1 开始的**有效
  物理记录序号**，空行不计数，完整坏行不得被静默跳过后继续编号；
  adapter 必须在 authority 锁内返回全部有效行、每行有效序号及最终 snapshot，不能只返回去元数据后的
  最后一行 dict。**当前 claim generation 发布之前已经存在的 B 轨 review rows 也在扫描范围内**：reconcile
  以当前 generation 的 target identity/fingerprint 建立初始 `active` 时间线，再按物理序回放所有能唯一关联
  该 identity 的 row，只为 eligibility 实际 transition 生成绑定当前 document/catalog generation 的投影；
  同状态重复 row、无法唯一关联的旧 fingerprint 或当前 base 未引用的 target 不生成事件。该投影保留原
  `source_event_revision`，但不伪造“claim 在 generation 之前已存在”；最终 fold 仍以 live authority 为准；
- A 轨 `source_event_revision = hash_json("claim-source-event-revision/v1",
  {source_store, requirement_id, history_index, history_event})`；A 轨同样扫描当前 committed generation 所
  引用 target 的**全部**内嵌 history，按 `history_index` 回放 transition；同状态无新 history event 时不产生
  投影，不能只把当前 A 轨 state 包装成一条合成历史；
- target-set 触发 `source_event_revision = hash_json("claim-target-source-event-revision/v2",
  {source_store, target_publication_revision, target_set_hash, target_kind, target_requirement_id,
  target_fingerprint, observed_target_fingerprint, previous_transition_event_hash})`；
  `target_publication_revision = hash_json("claim-target-publication-revision/v1",
  {source_store, source_present, source_file_sha256})`，把事件绑定到实际 target 文件发布事实；target 缺失时
  observed 为 `null`，没有前序 transition 时 `previous_transition_event_hash=sha256(empty_bytes)`。
  `previous_transition_event_hash` 是必要的 ABA 防护：在 `missing -> restored -> missing` 中，即使第二次 missing
  的 target-set 与 observed fingerprint 再次等于第一次，也必须形成不同的 source revision，不能被幂等键
  吞掉。该三事件序列已有回归测试锁定。不得借用最后一条 review row 冒充 target 变化来源；
- `target_review_revision` 继续表示 adapter 对当前权威语义状态的可复算 hash。它参与 freshness/effective
  revision，但不能替代逐次 source event identity。公式固定为
  `hash_json("claim-target-review-revision/v1", {source_store, target_kind,
  target_requirement_id, target_fingerprint, effective_state: {status, eligibility, reason,
  source_fingerprint, review_subject_fingerprint, needs_reconfirmation}, adapter_version})`；
  `recorded_at`、备注及 source row ordinal 不进入该语义 revision，同状态重复记录不会制造语义漂移。

幂等键：`hash_json("claim-review-event-idempotency/v1", {document_generation_id,
catalog_generation_id, claim_hash, source_store, source_event_revision, target_kind,
target_requirement_id, target_fingerprint, observed_target_fingerprint, claim_id, event_kind,
bridge_version})`。
**重复投影同键必须被现有有效前缀吸收**（追加前在锁内检查同键事件已存在则跳过），
重启/重跑/补投影均不产生重复行。

事件 envelope 固定为**每个受影响 claim 一行**：`claim_id` 是该行唯一归约归属，`linked_claim_ids`
只是按 `claim_id` 排序的完整 fan-out 审计信息。某 claim 的 `ordered_relevant_event_hashes` 只收
`event.claim_id == claim_id` 且 document/catalog generation、claim hash 均匹配的事件；不得因
`linked_claim_ids` 包含该 claim 而把其他 fan-out 行重复计入。`/claim-review-events?claim_id=` 同口径过滤。

第一条事件的 `prev_event_hash = sha256(empty_bytes)`；其余必须等于上一有效物理行的 `event_hash`。
`event_hash = hash_json("claim-review-event/v1", event 中除 event_hash 外的完整对象)`。
`event_prefix_sha256` 是从文件第 0 字节起，到 `last_event_seq` 对应规范 JSONL 行的换行符为止的**原始
字节 SHA-256**；它不是末事件 hash。无事件时 `last_event_seq=0` 且 prefix 为
`sha256(empty_bytes)`。event writer 必须拒绝非规范物理行，因此重放、API 与 fold 得到同一 prefix。

正常已有 v2 effective 行时，`projection_mode=cas_effective` 且
`expected_claim_effective_revision` 必须等于锁内已提交行；旧 v1 / 首次物化没有 v2 revision 时，允许
`projection_mode=bootstrap_base`、`expected_claim_effective_revision=null`，但
`expected_base_claim_row_hash` 必须匹配锁内 base。bootstrap 只适用于 system bridge 审计投影，不是
Phase 1.5 claim mutation 的 CAS 逃生口；后者始终要求非空 effective revision。

文件纪律沿用 `review_state.py` 既有模式：跨进程锁（复用 `claim_artifacts.lock` 同一把
publication 锁，见 §5.3 锁序）+ append + flush + fsync + torn-tail 恢复（读到坏尾即截断至
最后完整行并记 `torn_tail_recovered` 指标）。hash 链校验失败时必须先把坏后缀原字节写入带
sha256 的 quarantine 文件并 fsync，再把主事件流截断到最后有效字节；禁止在坏后缀之后继续追加。
投影事件只记录 authority 变化；`reused_validation` 属于 fold 结果，记录在 effective facts，绝不回写事件。

### 4.2 effective ledger v2

新增 `schemas/claim_effective_ledger.schema.json`，`schema: "claim-effective-ledger/v1"`。
effective 行复制 base 行的业务字段，但不冒充 `claim-ledger/v3`，并增加：
`base_ledger_schema`、`base_claim_row_hash`、`claim_effective_revision`、`effective_facts`、
`last_relevant_event_seq`。该行序号只表示该 claim 最后一条相关事件；meta 的 `last_event_seq` 才是全局
已提交前缀序号。`effective_facts` 至少包含 `valid_group_ids`、按 group 给出的
`invalid_group_reasons`、`validated_negative_id`、`invalidated_targets`（target kind/ID、base 期望与当前
observed fingerprint、reason/review revision；fingerprint 按 §4.0 规范化）
及 `reused_validation_group_ids`，供 API/UI 如实展示当前有效性。
`validated_negative_id` 在 base `semantic_negative.status == "validated"` 时固定为
`hash_json("claim-semantic-negative/v1", semantic_negative)`，否则为 `null`；它不是模型提供的 ID。

`claim_effective.meta.json` 使用 `schemas/claim_effective_meta.schema.json`，并升
`CLAIM_EFFECTIVE_SNAPSHOT_VERSION = claim-effective-snapshot-v2`：
- `claim_events_enabled: true`；
- `base_generation_id`（按 §4.0）、`generation_meta_sha256`、`base_ledger_sha256`；
- `event_prefix_sha256`、`last_event_seq`、`document_effective_revision`；
- `target_set_hash`、`requirement_review_state_hash`（fold 时实读计算）；
- `reducer_version`（= 新 `CLAIM_EFFECTIVE_REDUCER_VERSION`）、`bridge_version`；
- `queue_sha256`、`queue_count`、`queue_version`；
- 沿用：base/effective 文件 sha256、generation 绑定，并写当前 effective 状态计数与四项 ratio。

无事件时 `last_event_seq=0`，`event_prefix_sha256=sha256(empty_bytes)`。
`base_claim_row_hash = hash_json("claim-base-row/v1", base row)`，不得直接复用 base 行中历史命名的
`claim_effective_revision`。

revision 公式（总纲 §5.1，逐字实现，不得简化）：

```
document_effective_revision = hash_json("claim-document-effective-revision/v1", {
  base_generation_id, last_event_seq, event_prefix_sha256,
  target_set_hash, requirement_review_state_hash,
  effective_ledger_schema, effective_snapshot_version, effective_artifact_version,
  reducer_version, bridge_version, queue_version
})
claim_effective_revision    = hash_json("claim-effective-revision/v1", {
  base_claim_row_hash, ordered_relevant_event_hashes,
  linked_targets: [{target_kind, target_requirement_id,
                    target_fingerprint, target_review_revision}],
  effective_ledger_schema, reducer_version, bridge_version,
  review_adapter_versions
})
```

`linked_targets` 按 `(target_kind, target_requirement_id, target_fingerprint)` 排序并统一 target hash
前缀；target 缺失时保留 base edge 的 identity，并令 `target_review_revision =
hash_json("claim-target-review-missing/v1", {target_kind, target_requirement_id,
target_fingerprint})`。adapter 单点导出下列两个 projection；fold 与 API 只能调用该导出，不能复制公式：

```
target_set_hash = hash_json("claim-target-set/v1", sorted([
  {target_kind, target_requirement_id, canonical target_fingerprint}
]))
requirement_review_state_hash = hash_json("claim-review-authority/v1", sorted([
  {target_kind, target_requirement_id, canonical target fingerprint,
   eligibility, target_review_revision}
]))
```

两数组按 `(target_kind, target_requirement_id, target_fingerprint)` 排序，重复 identity 不去重，使歧义可被
复算。无关 requirement/claim 的事件**不得**改变某 claim 的
`claim_effective_revision`（测试断言），但会按设计改变 document revision。

target-set generation 采用**逐 target 内容寻址复用**：全局 `target_set_hash` 变化必然改变 document
revision，但对某 claim 而言，只要其全部 target ID/fingerprint、produced-evidence locator/field hash 与
validator/runtime version 均未变化，允许跨 target-set generation 复用既有验证；全局 generation 变化本身
不使无关 claim 重开。edge 中旧 `target_generation_id` 继续作为生成时 provenance，不作为 Phase 1
effective closure 的单独否决条件。

旧 semantic coverage 的复用使用独立、可复算但不必持久化到 group schema 的
`semantic_validation_fingerprint = hash_json("claim-semantic-validation/v1", {
claim_hash, source_evidence: {text_hash, claim_start, claim_end, match_method},
edges: sorted([{target_kind, target_requirement_id, target_fingerprint, relation,
produced_evidence: sorted([{field, item_index, start, end, position_basis, field_value_hash}])}]),
prefilter: {version, status, missing_protected_facts}, validation_method, validator_version,
verifier_runtime_fingerprint, reuse_version})`。所有数组使用上述字段组成的元组排序，禁止加入自然语言
说明或未声明字段。该指纹明确排除 review
status/revision；review eligibility 只决定一个
既有验证事实当前是否生效。reactivation 本身不制造 coverage，只有该指纹及 locator/version 全部未变的
旧 `validated` group 才进入 `reused_validation_group_ids`。
`reuse_version` 固定取 `CLAIM_VALIDATION_REUSE_VERSION`；Phase 1 首个发布值直接为
`claim-validation-reuse-v2`，用于绑定规范化 target fingerprint 与完整 semantic validation fingerprint，
避免脏 legacy 指纹被错误复用。`claim-validation-reuse-v1` 仅是设计阶段占位，未发布过生产 snapshot，
因此这里不是从已发布 v1 迁移，也不得为追求编号连续而改回 v1。

### 4.3 `claim_queue_proposals.jsonl`（新文件，派生快照）

schema：`schemas/claim_queue_proposal.schema.json`，`schema: "claim-queue-proposal/v1"`。
**派生物，非权威**：每次 effective materialization 后在同一锁内整文件原子重写（tmp+fsync+
`PermissionError` retry），不做 append、不做事件。

每行：`proposal_id`（`CQP-<digest_hex(claim_hash)前8>-<digest_hex(proposal_hash)前8>`，其中
`proposal_hash = hash_json("claim-queue-proposal-id/v1", {claim_id, claim_effective_revision,
action, queue_version})`）、`claim_id`、`parent_block_id`、
`locator`（catalog 原样精确 locator）、`claim_source_fingerprint`、
`document_generation_id`、`catalog_generation_id`、`claim_effective_revision`、
`action: "needs_extraction"`（Phase 1 唯一动作）、`dry_run: true`、
`queue_version`（= 新 `CLAIM_QUEUE_VERSION`）、`expected_ledger_state: "uncertain"`、
`created_from_event_seq`。`claim_source_fingerprint` 固定等于 catalog 的规范化 `claim_hash`；
`created_from_event_seq` 固定等于该 effective 行的 `last_relevant_event_seq`，不使用全局 document seq。

候选来源：当前 effective ledger 中 `resolution == "uncertain"` 的 claims（其中包括
`classification_status == "invalid"`），不经过 `requirement_like` 复核。covered/excluded 永不出现。
初代无事件物化时 `created_from_event_seq=0`。

兼容展示不写入 claim proposal 文件：`/claim-queue` 另行在 omission authority 锁下实时读取
`omission_states.jsonl`，映射到独立 `compat_omissions` schema，并标记 `compat_whole_block: true`；
它不携带伪造 claim ID，也不冒充块内全部子 claim。

### 4.4 operational health（新文件）

`claim_effective_health.json` 只记录 `bridge_fold_lag`、`torn_tail_recovered`、事件 quarantine、
`effective_snapshot_migrations`、最近成功/失败 maintenance 时间及 `authority_cas_gap`。
`effective_snapshot_migrations` 逐 base generation 留存 source/target snapshot 版本、实际提交的
effective run/time 与 `actor_trigger`；相同 base generation 的 v1→v2 迁移只能记录一次，普通 v2
refold 不得伪造迁移。health 在 publication 锁内原子替换，但不进入
immutable generation hash；不得修改 `claim_shadow_metrics.json` 来记录运行期 bridge 状态。

## 5. 机制设计

### 5.1 模块归属

新模块 `claim_review_actions.py`（总纲 §12 已为其留位），唯一拥有：事件追加与 hash 链、
bridge 投影与幂等、reconcile、effective fold 与 materialization。`claim_ledger.py` 抽出 base/effective
共用的纯优先表原语，但 base reducer/version 保持冻结；`claim_artifacts.py` 新增
`load_committed_claim_base`、`load_committed_effective_snapshot`、`assess_effective_freshness` 及
effective-only WAL，继续复用同一 publication 锁与原子写工具，不另造锁体系。

### 5.2 fold 流程（authority-driven effective reducer）

`fold_effective_ledger(out_dir, *, actor_trigger) -> dict`（authority-driven，不以 event 作为当前事实来源）：

1. **加载 base**：只校验 generation-time catalog/groups/base ledger、其文件 hash、验证 runtime 与
   base versions；不得要求 live review authority 等于 generation-time authority，也不得用 live review
   重放 base group。
2. **reconcile**：按物理顺序读取 B 轨全部有效 review rows、A 轨全部 history events，以及当前 target
   set 变化事实；不得只读取每个 target 的最终 snapshot。与有效事件前缀已投影的
   `(source_store, source_event_revision, target_fingerprint, claim_id, event_kind)` 集合比对，逐 source
   transition 补投影（§4.1 幂等键吸收重复）。完整坏行之后的 authority rows 不得静默续编：adapter
   返回 `audit_gaps`，fold 仍以当前可验证 authority 计算正确结论，但 health 标记
   `authority_audit_gap`，Phase 2 READY 不得忽略该缺口。
3. **实读快照**：重新读 target set 与权威（fold 专用一致快照），计算
   `target_set_hash` / `requirement_review_state_hash`。
4. **逐 claim 归约**：base 行 + 该 claim 有效事件前缀 + 当前事实（group 有效性、target
   rejected/missing/fingerprint 不符）走 `reduce_claim` 同一优先表；target 已 rejected、
   缺失或 fingerprint 不符时，**即使事件追加失败也立即使相关 group 失效并重开 claim**
   （总纲 §2.5 硬要求）；target 恢复且 claim/target fingerprint、evidence locator、
   validator/runtime versions 全未变时，按 §4.2 指纹显式复用旧验证，并把结论写入 effective facts。
5. **前后复验**：提交前重读 target 文件 hash、`target_set_hash` 与 authority hash；任一变化即放弃
   当前候选并重试，不能提交跨 target/review 代际结果。
6. **物化**：走 §5.3 effective WAL，依次原子替换 effective ledger、queue、effective meta，
   重读并校验全部 hash/schema/count；最后删除 journal 才完成提交。

### 5.3 锁序与并发（总纲 §2.5 "固定锁顺序或前后复验"）

固定锁序：**先取 `claim_artifacts.lock`（publication 锁），锁内只读所声明轨道的 review authority
文件**（B 轨 `read_ai_review_states`、A 轨 review-state snapshot 均沿用各自 authority lock；持
publication 锁期间短暂嵌套获取是允许的唯一方向）；**绝不在持有 review 锁时反取 publication 锁**。
fold 完成后释放。

若在 fold 期间 target 或 authority 被并发写入：物化前在 publication 锁内**同时复验**
target 文件 hash、`target_set_hash`、`requirement_review_state_hash`，与步骤 3 不一致则放弃本次
物化并重试（上限 3 次，
仍失败则记 `bridge_fold_lag` 指标并保留旧 effective——**绝不提交混合两个 review 代际的
READY**）。

新增 `.claim_effective_publication.journal.json`（schema：
`schemas/claim_effective_publication_journal.schema.json`），只服务
`transaction_kind=effective_fold`，共同保护 effective ledger、queue、effective meta。独立事务协议固定为：

1. publication 锁内先恢复 generation journal，再恢复遗留 effective journal；
2. 将三个旧文件（含“不存在”状态）写入同 transaction ID 的 backup 目录，逐文件 flush+fsync；
3. 原子写入并 fsync `state=prepared` 的 effective journal。journal 同时钉住 base generation/meta hash、
   三个旧快照及三个候选快照的 hash/count、candidate document revision；**journal 成功落盘前不得 replace
   任一生产文件**；
4. 按 effective ledger → queue → effective meta 的顺序原子替换，每次保留 Windows
   `PermissionError` retry；随后从生产路径重读，严格校验 schema/hash/count/base binding；
5. 校验成功后删除 journal；**journal 不存在是唯一提交点**。meta 替换完成、甚至三文件全部替换完成但
   journal 仍存在，都仍是未提交事务；
6. 提交后的 backup 清理是 best-effort。无 journal 的孤儿 backup 只能按受控 transaction ID/文件白名单
   清理，不参与回滚。

`snapshot_files` 必须按文件名排序且恰好各含 effective ledger、queue、effective meta 一项，不能重复；
schema 的三项长度约束不能替代该跨项校验。`journal_sha256 =
hash_json("claim-effective-publication-journal/v1", journal 中除 journal_sha256 外的完整对象)`。

恢复时只要 journal 存在，无论三个生产文件走到哪一步，都必须把**三个文件一起**恢复为 journal 记录的
旧快照（旧状态为 absent 则删除），重读验证后再删 journal；不得“补完”候选事务。事件流已经 fsync 的
前缀不回滚，下次 fold 会纳入它。现有 `.claim_publication.journal.json` v1 与 verifier attempt recovery
保持 generation 专用，fold 崩溃不得写 verifier failure/checkpoint。两个 journal 禁止互相复用 schema、
backup 目录或提交点。

锁序固定为 extraction operation lock → publication lock → authority lock。fold 不获取 extraction lock，
只用 target 前后复验避开并发；绝不在持有 authority lock 时反取 publication lock。review hook 必须先
保存权威写入结果、完全退出 authority lock，再调用 fold。

事件 CAS：已有 v2 时按 §4.1 校验 `expected_claim_effective_revision`；bootstrap 按 base row hash。
普通 CAS 不匹配时应放弃本次候选、释放当前 fold 调用栈，再从 reconcile 顶层重试（上限 3 次），禁止在
持 publication 锁的 fold 内递归调用 fold。Phase 1 只有系统 actor，冲突只来自并发 generation/fold。

### 5.4 触发点

| 触发 | 位置 | 说明 |
| --- | --- | --- |
| ai-extract 收尾 publish 后 | `ai_extract.run_ai_extract` claim 段尾 | 初代 effective 物化；失败仅 warning |
| ledger-only refresh | `ai_extract.refresh_claim_shadow` 尾 | 同上 |
| B 轨专家动作提交后 | `ai_review_actions.apply_ai_review_action` 尾部 hook | 先完成自身 fsync 再调 `fold_effective_ledger`；**hook 异常必须吞掉只记 warning + `bridge_fold_lag`**，绝不让审查动作失败 |
| A 轨专家动作提交后 | `review_state.apply_expert_decision` 尾部 hook | 先提交 `review_states.jsonl` 并释放 authority lock；若已有声明 A 轨的 committed claim generation，则执行同一 fold；无 generation 时 honest no-op，不创建 claim artifacts（见 §8） |
| API/桌面服务启动后 | 请求监听前的 maintenance hook | 请求路径之外执行一次 recover + reconcile + fold；失败记录 lag，但不伪装 fresh |
| CLI | `cli.py` 新增 `claim-ledger-fold --out-dir <dir>` | 人工/调试入口；走统一 JSON envelope，退出码 0/2/3/4 口径同既有子命令 |

**API 请求路径不 fold**（公理 4）。`/claim-metrics` 等读端点实时重算
`target_set_hash` / `requirement_review_state_hash` / 事件前缀并与 effective meta 比对，
返回 `effective_fresh: bool`；stale 时照常返回已提交快照并如实标记（UI 展示"账本待刷新"，
不主动触发写）。

### 5.5 review/target authority bridge 语义（A/B 同等 fold）

- 权威语义逐字执行总纲 §2.5：B 轨以 `ai_review_states.jsonl` 中每个 `ai_req_id` 最后一条
  有效且与当前 target ID/fingerprint 匹配的记录为权威；A 轨以 `review_states.jsonl` 当前 state 及其
  内嵌 history 为权威。无 row ≠ rejected；无 fingerprint、匹配歧义或 `needs_reconfirmation` 的旧 row
  → eligibility `unknown`，不得用于关闭 claim。
- 投影映射：rejected / 内容变化 / target 替换 → `target_invalidated`；恢复为非 rejected →
  `target_reactivated`；`accepted`、`expert_pending` 等非 rejected 状态只表示没有 rejection
  阻断，**不创建 edge、不验证 coverage、不引入"必须先 accepted"的新门**。
- adapter 必须由声明的 `target_kind` 选择，禁止按 `AIR-` 等 ID 外形猜轨道。
- generation 声明 `delivery_track=A,target_kind=atomic_requirement` 时，target set 必须读取
  `atomic_requirements.jsonl`，authority/history 必须读取 `review_states.jsonl`；声明 B 时仍读取
  `ai_requirements.jsonl` / `ai_review_states.jsonl`。两种 adapter 导出相同的 target set、review revision、
  source-history 和 audit-gap 结构，并进入同一 reconcile/fold/freshness/CAS 路径；禁止 A 轨固定 no-op。
- target 缺失、fingerprint 变化或恢复若没有对应 review row，必须按 §4.1 的 `target_set` trigger
  投影；不得伪造 review source revision。
- Phase 1 **不实现** claim → requirement 方向的反向桥（那是 Phase 1.5 mutation）。
- 现有 A/B 写入入口尚无完整 review-revision CAS：本阶段如实记录为已知缺口
  （metrics `authority_cas_gap: true` + CLAUDE.md 留痕），总纲已定其为 Phase 1.5 必改项，
  Phase 1 不用 claim event CAS 冒充它。

## 6. 接入面设计

### 6.1 只读 API（`api_server.py`，全部 GET，token 校验同既有）

在 `do_GET` 既有模式上追加（读 committed base/effective 快照 + 独立 freshness）。artifact/锁错误
`(ClaimArtifactError, TimeoutError, OSError, JSONDecodeError, UnicodeDecodeError)` → 503
`{"error": "...", "retryable": true}`；查询参数错误单独返回 400，禁止用宽泛 `ValueError` 把客户端
错误伪装成 503。分页 `?limit=&offset=` 固定默认 `limit=100, offset=0`，`limit` 范围 1..500，
`offset >= 0`：

| 端点 | 内容 | schema 自封 |
| --- | --- | --- |
| `/claim-catalog` | `rows`：catalog 行 join 当前 effective（resolution/classification/exclusion_kind/claim_effective_revision），支持 `?resolution=&owner_unit_id=` | `claim-catalog-view/v1` |
| `/claim-ledger` | `rows`：当前 effective ledger 行，支持 `?resolution=covered\|excluded\|uncertain` | `claim-ledger-view/v1` |
| `/claim-coverage-groups` | `groups`：generation groups + effective status/reason/reused overlay，支持 `?claim_id=` | `claim-coverage-group-view/v1` |
| `/claim-metrics` | `generation_metrics` / `effective_metrics` + informational `document_ready` / `health` | `claim-metrics-view/v1` |
| `/claim-review-events` | `events`：effective meta 已提交、且与当前 document/catalog generation 匹配的事件前缀；不暴露未 fold 新尾或旧代事件，支持 `?claim_id=` | `claim-review-event-view/v1` |
| `/claim-queue` | `proposals` + 独立 `compat_omissions`；两者全部 `dry_run: true` | `claim-queue-view/v1` |

六个成功响应统一使用下列 envelope；集合键固定为 `rows|groups|events|proposals`，queue 另带
`compat_omissions`，不能返回裸数组或通用 `items`：

```json
{
  "schema": "claim-*-view/v1",
  "available": true,
  "phase": "production-dual-write-v1",
  "base_generation_id": "sha256:...",
  "document_generation_id": "sha256:...",
  "catalog_generation_id": "sha256:...",
  "document_effective_revision": "sha256:...",
  "event_prefix_sha256": "sha256:...",
  "last_event_seq": 12,
  "effective_fresh": true,
  "freshness_reasons": [],
  "limit": 100,
  "offset": 0,
  "total": 123,
  "rows": []
}
```

`limit/offset/total` 只在 `rows|groups|events|proposals` 主集合存在；metrics 不带分页字段，queue
的分页只作用于 `proposals`，`compat_omissions` 另带
`compat_omission_revision` 与 `compat_omission_total`。所有 response-level hash 都按 §4.0 规范化。
`freshness_reasons` 是排序去重的受控值数组，初版只允许 `event_prefix_advanced`、
`target_set_changed`、`review_authority_changed`、`effective_version_stale`、
`claim_generation_unavailable`；`effective_recovery_pending` 是下述 503 error code，不进入成功响应的
freshness reasons。`effective_fresh=false` 时不得返回
`document_ready=true`。

通用约束：仅在 `claim_generation.meta.json` 确实不存在、且没有任一 claim generation 文件的老 out 目录
返回 200 + `available:false` + 对应空集合；envelope 的 generation/revision/hash 字段为 `null`、
`last_event_seq=0`、`effective_fresh=false`、`freshness_reasons=["claim_generation_unavailable"]`。
只缺部分 generation 文件不是老目录，必须 503。文件存在但 hash/schema/WAL 损坏必须 503，不能伪装
unavailable。payload 统一携带
`phase: "production-dual-write-v1"`、`document_effective_revision`、base generation ID、
event prefix hash 与 `effective_fresh`。内部一致但 authority 落后的快照仍返回 200+stale；不加任何 POST。
`document_ready` 严格按总纲 §4.1 计算，但只作 ledger 观察指标，不参与生产 readiness。

旧 effective v1 只能由启动 maintenance/CLI 做 deterministic 迁移。迁移失败或尚未完成时，六个端点统一
返回 503 `{"error":"effective_migration_required","retryable":true}`；不得把缺少 v2 revision/facts/queue
的 v1 包装成 `200 + stale`。只有 schema/hash/WAL 内部一致的 v2 快照允许 `200 + effective_fresh:false`。

**GET 路径必须物理只读**：六个 endpoint 只能调用 read-only base/effective loader。发现
`.claim_effective_publication.journal.json` 时统一返回 503
`{"error":"effective_recovery_pending","retryable":true}`；handler 不得调用 recovery/fold、不得删除或
改写 journal、backup、effective 三文件、event/health，也不得以“补完事务”换取 200。回滚旧三文件只允许
服务启动 maintenance、显式 CLI/desktop maintenance 或下一次受锁写侧 fold 执行。测试必须通过真实
`ThreadingHTTPServer`（或项目实际 server factory）发请求，并在请求前后比较目录级文件 hash/mtime/存在性，
不能只直接调用 `build_claim_view` 来证明该契约。

### 6.2 Vue3 UI（`ui/src/`）

- `phaseNavItems` 新增 `"claim"`（账本）页，挂载方式同 DocumentReview；新组件
  `ui/src/ClaimLedger.vue`。
- 页面构成（全部只读，顶部固定徽标"**双写观察期 · 不影响 READY 判定**"）：
  1. 指标卡：四比率按总纲 §10 口径同时显示 numerator/denominator，分母 0 → `null` 展示
     为 "—"；`document_ready`（informational）与 `effective_fresh` 状态灯；
  2. **新旧并列卡**：旧 `coverage_pct / core_coverage_pct`（`ai_extract_quality.json` 经
     既有 `/ai-extraction-status` 口径）vs 新 `verified_coverage_ratio /
     eligible_resolution_ratio`，并排、等宽、各自标注来源版本；
  3. claim 表格：resolution 过滤（covered/excluded/uncertain）、owner unit 过滤、分页；
     行点击开详情抽屉（claim 文本、精确 locator、`/claim-coverage-groups?claim_id=` 的
     target edge 与验证方法、`/claim-review-events?claim_id=` 事件时间线）；
  4. 队列页签：`/claim-queue` 提案列表 + `compat_omissions` 分区，每行 "dry-run" 徽标，
     **无任何执行按钮**。
- `api-client.ts` 按既有 `request<T>` 模式加 6 个方法与 payload 类型。
- 页面主列表响应确定 revision pin；详情 group/event 请求若 pin 不同，丢弃响应并统一刷新，禁止把两个
  effective revision 拼成一个画面。
- 测试：vitest 组件测试（mock client）+ api-client 测试；零 LLM。

### 6.3 导出与兼容字段

- `clarification_report.py`：`clarification_report.json` 新增 `claim_ledger` 键
  （informational）：metrics 摘要（四比率含分子分母）、`document_ready`、
  `effective_fresh`、uncertain claims 前 50 条（claim_id + 精确 locator + claim 文本截
  120 字符）。**readiness_verdict 逻辑、TIER 判定、coverage_basis 一字不动**。
  `STAGE_IMPLEMENTATION_REVISIONS["clarification-report"]` v5→v6（加性 informational
  字段，只失效本阶段重渲染）；其 `STAGE_INPUTS` 增加 effective ledger/meta、queue 与 health，
  authority fold 后只重渲染 clarification，不重跑抽取。
- `desktop_tasks.py`：chain payload 的 `claim_shadow` 摘要扩 `document_ready` /
  `effective_fresh` / `open_claim_count`（informational，skipped payload 同步）；
  `run_manifest` 的 ai-extract 阶段条目新增 `claim_components` 子块
  （catalog/coverage/effective/bridge/reducer/queue 各自版本与 revision，
  informational；`manifest_version` 保持 2，加性）。
- 批注导出（`doc_annotation_export.py`）：Phase 1 仅在块徽标配色区增加"块内 claim
  分布"角标（covered/excluded/uncertain 计数，整块级，数据来自
  `/claim-catalog` 同源快照）。**span/row 级 claim 批注定位不在本阶段**（见 §12 冻结项
  第 4 条，需审核人明示确认）。

### 6.4 claim queue 与 agent

- 提案由 fold 派生（§4.3），`/claim-queue` 与 UI 只读消费；动作契约字段与总纲 §6.2 对齐，
  `CLAIM_QUEUE_VERSION` = `claim-queue-shadow-v1`。
- `decide_trace.jsonl` 只记 agent 对提案的摘要，不承载逐 claim 事实（总纲 §6.5），
  本阶段 `agent_state.py` / `agent_tools.py` 零改动；agent 只读视图明确延后到 agent 线接入，不能把
  “已生成 proposal 文件”表述为“agent 已消费”。

## 7. 版本与缓存纪律

| 常量 | 现值 | Phase 1 | 理由 |
| --- | --- | --- | --- |
| `CLAIM_LEDGER_SCHEMA_VERSION` | claim-ledger-v3 | **不动** | base 行结构不变 |
| `CLAIM_EFFECTIVE_SNAPSHOT_VERSION` | v1 | **v2** | events enabled + 新键 |
| `CLAIM_REDUCER_VERSION` | claim-reducer-v2 | **不动** | 冻结 generation-time base reducer |
| 新 `CLAIM_EFFECTIVE_LEDGER_SCHEMA` | — | `claim-effective-ledger/v1` | effective 行独立 schema |
| 新 `CLAIM_EFFECTIVE_REDUCER_VERSION` | — | `claim-effective-reducer-v1` | authority overlay + revision 公式 |
| 新 `CLAIM_EFFECTIVE_ARTIFACT_PROTOCOL_VERSION` | — | `claim-effective-artifacts-v1` | effective WAL/loader 协议 |
| `CLAIM_REVIEW_BRIDGE_VERSION` | shadow-v1 | **claim-review-bridge-v2** | 生产投影 + 幂等键 + reconcile |
| 新 `CLAIM_VALIDATION_REUSE_VERSION` | 设计占位 v1（未发布） | `claim-validation-reuse-v2` | 规范化 target fingerprint + 完整 semantic validation fingerprint；阻断脏 legacy 复用 |
| `CLAIM_QUEUE_VERSION` | disabled-v1 | **claim-queue-shadow-v1** | dry-run 提案 |
| `CLAIM_AUDIT_POLICY_VERSION` | shadow-v4 | **不动** | 抽样审计策略未变 |
| 新 `CLAIM_REVIEW_EVENT_SCHEMA` | — | `claim-review-event/v1` | §4.1 |
| 新 `CLAIM_QUEUE_PROPOSAL_SCHEMA` | — | `claim-queue-proposal/v1` | §4.3 |
| `STAGE_IMPLEMENTATION_REVISIONS["clarification-report"]` | v5 | **v6** | informational 字段 |

**硬纪律（总纲 §7）**：以上 effective/bridge/queue CLAIM_* bump 一律不得进入
`stage_producer("ai-extract")` 与初抽 section cache key；它们只触发 ledger-only
refold，**不得触发 base ledger rebuild，新增初抽或 verifier LLM 调用必须为 0**。实现后用测试断言：同输入下
Phase 1 版本 bump 前后 `stage_producer("ai-extract")` 串不变（除 clarification-report
自身 impl 戳）。新增 `committed_base_versions_are_current` 只比较 generation-time 版本；
`effective_versions_are_current` 单独比较新常量。旧 effective v1 只触发纯 fold 迁移；测试必须 patch
`refresh_claim_shadow`、chat 和三类 verifier 为失败哨兵并证明均未调用。

stage reuse 真值表固定如下；实现必须把 generation-time base outputs 与 runtime effective sidecars 分开，
后者不得作为 `ai-extract` 复用的必需文件：

| base generation | effective | ai-extract 复用 | 处置 |
| --- | --- | --- | --- |
| current | current v2 | 是 | 直接读取 |
| current | stale v2 | 是 | 后台 deterministic fold；期间 API 200+stale |
| current | missing/corrupt/v1 | 是 | recovery/migration fold；不可用期间 API 503 |
| current | fold 失败 | 是 | 保留内部一致旧 v2并记 lag；绝不调用 verifier |
| missing/corrupt/stale generation-time facts | 任意 | 否（仅 ledger generation 层） | requirements cache 命中时只重建 base；不得重跑初抽 |

generation meta 的 `requirements_sha256`、`target_generation_id` 是生成时 provenance；base loader 不与 live
target/review 文件比较。live target/review 只进入 freshness 与 effective fold。

成本：Phase 1 **零新增 LLM 调用路径**（投影/fold/提案全确定性）。验收时必须实测：
同一份已抽取 out 目录执行 fold，verifier 调用/token 增量 = 0。

## 8. A 轨边界

- Phase 1 对**已经存在且明确声明** `delivery_track=A,target_kind=atomic_requirement` 的 committed
  catalog/base generation，交付与 B 轨同等的 authority adapter、全部 history reconcile、event projection、
  effective fold、freshness 与 effective revision；读取
  `atomic_requirements.jsonl` + `review_states.jsonl`，不得按 target ID 外形猜轨。
- `review_state.apply_expert_decision` 在权威状态原子提交且释放 review lock 后触发 fold。若当前 out 目录
  没有 claim generation，hook honest no-op，专家裁决照常成功且**不得现场创建或猜造 A 轨 claim
  artifacts**；若存在 B 轨 generation，则仍严格按 generation 声明使用 B adapter。
- 本阶段不把 assemble 接线为 A 轨 catalog 生产器，也不因此声称 A 轨生产双写已覆盖所有运行；A 轨 fold
  的冻结回归使用显式 A 轨 committed fixture。Phase 2 前仍须以 A 轨独立数据通过同一质量门，B 轨通过不能
  替 A 轨背书。

## 9. 工作包分解（按依赖序）

- **WP0 分层持久化**：base/effective loader、版本域、effective WAL 与旧 v1 snapshot 纯 fold 迁移；
  测试先证明 authority 漂移不使 base/stage 失效且零 verifier。
- **WP1 事件链**：`schemas/claim_review_event.schema.json` + `claim_review_actions.py`
  事件追加/hash 链/torn-tail/锁内 seq；测试先行。
- **WP2 bridge 投影**：B 轨投影 + 幂等键 + 全物理历史 reconcile；`ai_review_actions` hook。
- **WP3 effective reducer**：独立 effective schema + fold + 双 revision 公式 + 物化 + stale 判定；
  `claim-effective-snapshot-v2`；`ai_extract` 两处触发接线；CLI `claim-ledger-fold`。
- **WP4 只读 API**：6 端点 + freshness 计算 + 503/available:false 模式。
- **WP5 兼容字段**：clarification `claim_ledger` 键（impl v6）、desktop payload 与
  run_manifest `claim_components`。
- **WP6 UI**：`ClaimLedger.vue` + api-client + vitest。
- **WP7 queue 提案**：`claim_queue_proposals.jsonl` 派生 + omission 整块兼容映射 +
  `/claim-queue` + UI 页签。
- **WP8 A 轨 parity**：对已有 A 轨 committed generation 实现 authority/history adapter、reconcile、
  event projection、fold/freshness + `review_state` hook；无 generation honest no-op；单测与 B 轨同门。
- **WP9 规模与分发**：500-block/history 复杂度基准、真实 HTTP 200/503、wheel/schema 隔离安装 smoke。
- **WP10 文档**：CLAUDE.md 里程碑、`docs/agent-next-steps.md` 进度行、本规格升"已冻结"
  并记录实施偏差。

WP0→1→2→3 是主干，WP4/5 可并行，WP6/7 依赖 WP4，WP8 复用 WP1→3，WP9 在实现收口后执行。

## 10. 测试矩阵（全部 unittest.TestCase；UI 用 vitest）

1. **事件链**：seq 单调、hash 链可重放、torn-tail 截断恢复、坏后缀 quarantine+截断后可继续追加、
   幂等键吸收同代重复投影但不吸收跨 catalog generation 事件。
2. **reducer 优先表**：复用总纲 §2.4 表全行；正/负同时有效 → uncertain+conflict；
   前置失效 → uncertain+invalid；`classification` 与 `resolution` 不一致记 invalid。
3. **revision/schema 公式**：base/effective 两份 schema 各自严格通过；无关 claim 的事件不改变
   `claim_effective_revision`；authority 变化只改受影响 claim；document revision 五要素任一变化即变。
   effective row 还须通过业务交叉校验：covered 至少一个 valid group；semantic excluded 必须有 validated
   negative；structural excluded 必须可回指 base proof-safe exclusion；effective 业务字段必须与 base row
   一一绑定，不能只靠 JSON Schema 判断闭合。
4. **fold 并发**：fold 中 target 或 authority 被写 → 前后 hash 复验失败重试，不提交跨代际 READY；
   publication 锁与 review 锁方向不颠倒（构造反序注入断言无死锁/无反序）。
5. **bridge 语义与历史**：A/B 两轨 reject → 关联 claim 重开（uncertain）且不触发初抽（mock LLM
   计数=0）；restore 本身不关闭 claim，只有 semantic validation fingerprint/locator/versions 全同
   才显式复用旧验证；review revision 改变不破坏该语义验证指纹；
   无 fingerprint/歧义/needs_reconfirmation → unknown 不关闭；非 rejected 状态不
   创建 edge。B 轨须覆盖 generation 发布前已存在的多行历史、同状态重复行和 generation 后新增行；A 轨
   须覆盖全部内嵌 history，证明两轨均投影实际 transition、最终 fold 服从 live authority 且不伪造旧 claim。
6. **hook 绝缘**：两个 authority lock 释放后才调用 fold；fold 抛异常时 review action 仍成功返回，
   独立 health 中 `bridge_fold_lag` 计数 +1。
7. **真实 HTTP API**：启动实际 HTTP handler，对六个 GET **逐端点**断言 committed snapshot → 200；
   incomplete/corrupt/migration-required/recovery-pending 中适用的错误 → 503 retryable。老 out 目录
   → `available:false` 200；分页/过滤正确；payload 携带 phase 与 revision 钉。effective journal 存在时，
   六个 GET 全部返回 `effective_recovery_pending`，请求前后 journal/backup/effective/event/health 的
   hash、mtime 与存在性完全不变；直接测 view builder 不能替代本项。
8. **兼容字段/导出集成**：用真实 committed fixture 生成 clarification_report.json，断言
   `claim_ledger` 的 available/fresh/open/ratio/uncertain locator 来自同一 revision，且 readiness/TIER 块与
   基线逐字节一致；ai-extract `run_manifest` 的 `claim_components` 含 catalog/coverage/effective/bridge/
   reducer/queue 版本和 revision；批注 HTML 对同一块完整渲染 covered/excluded/uncertain 三计数角标，
   缺失 ledger 时诚实降级且不改变旧批注意义。
9. **零 mutation 守卫**：在 fold/投影/queue/API 全路径 patch
   `review_state.apply_expert_decision`、`ai_review_actions.apply_ai_review_action`
   及 requirements 原子写函数，断言 Phase 1 代码路径对其调用次数为 0。
10. **queue**：只允许 `resolution=uncertain` claim 入提案；compat omission 使用独立 schema 且不
    关闭子 claim；初代 event seq=0；fold 后提案与 effective/meta hash/count 一致。
11. **版本纪律**：effective CLAIM_* bump 后 `stage_producer("ai-extract")` 串和 base currency 不变；
    旧 effective v1 纯 refold 成功，`refresh_claim_shadow` 与所有 LLM/verifier 哨兵调用数为 0。
12. **回归**：全量 unittest、golden 6/6、前端 vitest + `vue-tsc`。
13. **崩溃恢复**：effective 三文件每个 replace 前后及 meta 写完/journal 未删处强杀，重启恢复完整
    旧代且不登记 verifier failure；遗留 generation journal v1 仍可恢复。
14. **启动补偿**：离线改 authority 后重启服务，监听请求前 maintenance reconcile+fold；失败时旧快照
    仍可读但 stale，health 如实记录 lag。
15. **500-block 与复杂度门**：固定 500-block/至少 500 eligible claims、500 linked targets、2000 条
    review history rows 的合成夹具，预热一次后运行 5 次；catalog p50 ≤1.0 秒、catalog+base ≤10 MiB，
    reconcile+fold 的 p50/p95 必须连同 Python/OS/CPU 留痕，首个验收值冻结为后续 baseline。实现必须按
    `(target_kind,target_requirement_id)` 预索引 links；测试 instrumentation 固定
    `link_index_inserts == linked_target_count`，且 `history_candidate_checks` 等于每条历史记录同 ID link
    fan-out 数之和；增加 500 个无关 links 不得改变后者。该可复算线性工作量
    是本阶段硬门；禁止保留 `rows × all_links` 循环后仅靠当前机器“跑得快”过门。后续时延超出冻结
    baseline 必须显式更新性能 baseline/version 并经审核，不能静默放宽。
16. **wheel/schema packaging smoke**：构建 wheel，在 checkout 之外的新临时 venv 中 `pip install --no-deps`
    后导入 `claim_review_actions`/`claim_views`，并能定位、读取且用 Draft 2020-12 校验所有新增 schema
    （effective ledger/meta/health/publication journal、review event、queue proposal）；不得因当前工作目录
    或 `PYTHONPATH` 泄漏而假绿。
17. **真实零 verifier**：对已完成抽取的 B 轨副本记录 verifier attempt/call/token 基线，依次 reject、fold、
    reactivate、fold 后增量均为 0；mock 哨兵测试不能替代该本地实测。

## 11. 验收与退出条件（全部满足才可合并 main）

1. **全量回归**：worktree 最终代码上 `python -m unittest discover -s tests` 全绿；前端最终代码上
   `npm test` 与 `npm run build` 全绿；在具备冻结 `out/` 和正确三 seed KB + domain-pack 的主 checkout
   跑 golden 6/6。worktree 因 git-ignored `out/` 产生的 skip 不能记作 golden 通过，禁止修改 golden baseline。
2. **真实 B 轨复演**（机器本地，真实 LLM 路由，用新副本目录不动既有 test 目录）：
   a. 跑通 ai-extract，确认初代 effective v2 物化、`claim_events_enabled: true`；
   b. 通过 UI/API 拒绝一条有 coverage 的 AI 需求 → **不重跑抽取**（run_manifest 无
      ai-extract 重跑记录、verifier 调用增量 0），fold 后相关 claim 变 uncertain，
      `/claim-review-events` 出现 `target_invalidated`，UI 账本页可见；
   c. 恢复该需求 → `target_reactivated`；事件本身不关闭 claim，语义验证指纹未变的既有 validated
      group 显式恢复生效后才回 covered；
   d. 杀掉服务进程，改 `ai_review_states.jsonl` 后重启 → reconcile 补投影 + fold，
      结论与在线路径一致；
   e. 在 claim generation 之前预置 accepted/rejected/restore 多行 review history，再生成并 fold；事件只投影
      实际 transition、绑定当前 generation，最终 effective 与 live authority 一致；
   f. clarification_report.json 新旧并列块齐全且 readiness 与基线一致。
3. **A 轨 parity**：对已提交且声明 A/atomic 的合成 fixture，重放 `review_states.jsonl` 全 history，完成
   reject/reactivate、target missing/restored、event/freshness/effective fold，并证明 verifier 增量为 0；无
   claim generation 的 A 轨 review hook 是零写入 no-op。该门不要求本阶段把 assemble 接成 catalog 生产器。
4. **读侧与消费面**：§10.7 的六端点真实 HTTP 200/503 + journal 零写入全部通过；§10.8 的
   `claim_components`、clarification committed 摘要与整块三状态角标集成测试通过。
5. **成本与规模**：真实 B 轨 reject/reactivate 的 verifier 调用/token 增量 = 0；§10.15 的 500-block、
   文件大小、fold 时延与非 `rows × all_links` 复杂度门通过，原始测量值留痕。
6. **可分发性**：§10.16 wheel/schema 隔离安装 smoke 通过，wheel 中新增模块与六份 schema 均可用。
7. **文档证据**：CLAUDE.md 记录实现里程碑、实际命令/计数/性能值、真实复演与任何批准偏差；待办文档
   同步。API key、客户 wording、机器本地文档与复演副本均不进仓。

**当前状态（2026-07-28）**：§11.2–§11.7 及 §11.1 的 worktree 后端/前端部分均已有连续可复核证据；
最终独立审查无 gating finding。§11.1 的 main checkout golden 6/6 必须等待用户批准合并后执行，因此当前是
“worktree 可合并候选”，仍不是“Phase 1 已完成”。

## 12. 明确不做（Phase 1）

1. 不切换 readiness / 自检早停 / TIER_GAP / `is_coverage_candidate` 到账本口径
   （Phase 2）；merged_consistency 输出结构不改。
2. 不启用任何 claim/requirement mutation：无专家 claim 裁决 UI/API、无
   targeted_reextract 执行、queue 提案无执行入口（Phase 1.5）。
3. 不实现 claim → requirement 反向桥；不补 A/B 写入入口的 review-revision CAS
   （如实记录缺口，Phase 1.5 必改）。
4. **DOCX/PDF 批注导出的 span/row 级 claim 定位延至 Phase 1.5**（与 mutation 闭环
   同期做，避免双写期按旧状态返工）；Phase 1 只做整块级分布角标。⚠️ 此条相对总纲
   §6.4 终态描述是范围裁剪，需审核人明示确认。
5. 不把 assemble 接成 A 轨 catalog 生产器；但已有 A 轨 committed generation 的 authority/history
   reconcile 与 fold 属于 Phase 1 必交范围，不能以本条固定 no-op。
6. 不动 `gui/`（PySide6 冻结）、不动 golden 基线、不动 decide_trace 封闭 schema。

## 13. 审核冻结项

审核人确认本稿时同时确认：

1. Phase 1 唯一机制增量 = authority-driven effective fold + 审计事件投影 + 只读消费面；
   mutation 全禁（§3 公理 1/2、§12.2）。
2. `claim_review_events.jsonl` 只承载 bridge 投影，hash 链 + 幂等键 + torn-tail 恢复，
   publication 锁与 review 锁序固定（§5.3）。
3. fold 每次实读 target set 与权威；投影丢失只影响审计不影响结论（§3 公理 3、§5.2）。
4. 批注导出 span/row 级定位延至 Phase 1.5（§12.4）——**用户已在此前修订中确认，v1.4 延续**。
5. clarification/readiness/merged_consistency 语义零改动，新信息全部走加性
   informational 字段（§3 公理 5、§6.3）。
6. 版本纪律：CLAIM_* bump 不进初抽 cache key，新增初抽 LLM 调用为 0（§7）。
7. A/B 对已有 committed generation 使用同等 authority/history adapter 与 fold；A 轨无 generation 时才
   honest no-op，本阶段不新增 assemble catalog 生产接线（§8）。
8. 验收以 §11 的 B 轨真实复演、A 轨 parity、真实 HTTP、规模、wheel 与全量/golden 证据为准，
   记录留痕 CLAUDE.md。

用户批准此前修订方向后动工；v1.4 依据实现审查补齐 A 轨、读侧、规模与分发门。
完成 §11 验收并记录实施偏差后再标记冻结完成。
