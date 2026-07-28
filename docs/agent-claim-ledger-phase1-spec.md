# Claim Conservation Ledger — Phase 1 实施规格（生产双写，不切门控）v1.1

状态：**待复审冻结**。v1.1 落实专家审查全部 7 项（6×P0 + 1×P1），相对 v1.0 的改动见 §14。
本稿是 `docs/agent-claim-ledger-spec.md`（**v2.2，已冻结**）§9 Phase 1 的施工规格；
总纲与本稿冲突时以总纲为准。总纲 v2.2 已澄清阶段边界：**Phase 1 建成机制本体（只读投影、
effective fold、必要的 WAL/恢复），零 mutation；Phase 1.5 验证闭环后启用 mutation 与
authority CAS**。

- 实施分支：`codex/claim-ledger-phase1`（独立 worktree，用户决定合并）。
- 实施纪律：后端测试一律 `unittest.TestCase`；提交前全量 unittest + golden 6/6 绿；
  版本常量按 §7 表 bump；未要求不 commit、不 push。

---

## 1. 定位与范围

Phase 0A/0B 已把 catalog / coverage groups / base+effective ledger / 双 meta / verifier
attempt 链以 shadow 形态写入每次 ai-extract 的产物目录。Phase 1 转为**生产双写**：旧覆盖
报表与 readiness 原样保留（兼容字段），账本并排展示、可被 API/UI/导出消费，但**任何现有
门控（readiness、stage 复用、golden、chain）都不依赖 ledger 结论**。

Phase 1 的一句话：账本开始"正式说话"，但还"说了不算"。唯一机制增量 = **只读事件投影 +
事件驱动 effective reducer + 支撑 fold 的 WAL/恢复**——专家拒绝/恢复一个 AI 需求后，关联
claim 在不重跑抽取、**不重跑 verifier** 的前提下于 effective ledger 中重开/恢复。

## 2. 现状基线与已核实的 Phase 0 缺口

### 2.1 可复用资产（实现前必读）

- 写路径：`ai_extract.run_ai_extract` 起手 catalog probe，收尾
  `claim_ledger.publish_b_track_shadow` → `claim_artifacts.publish_shadow_generation`；
  失败仅 warning。`refresh_claim_shadow` 提供 ledger-only 重建。
- 磁盘产物与锁：`claim_artifacts.py` 文件名常量 + `claim_artifacts.lock`（publication 锁）
  + journal/checkpoint 崩溃恢复（协议 v6）。
- build 期 reducer：`claim_ledger.reduce_claim`（`CLAIM_REDUCER_VERSION=claim-reducer-v2`）
  实现总纲 §2.4 互斥优先表，fold 必须复用同一优先级逻辑，不得分叉。
- B 轨权威读取：`read_ai_review_states` + `claim_ledger.b_track_authority_state`
  （`target_generation_id` / `target_review_authority_revision`）。
- effective == base 逐字节复制占位（`claim_events_enabled: False`）。

### 2.2 专家审查核实确认的 Phase 0 缺口（Phase 1 必须修复，附行号）

- **G1 loader 混淆代际**：`claim_artifacts.py` `_load_committed_shadow_unlocked`
  （约 :2966-2975）读取**当前** `ai_review_states.jsonl` 并强制当前 authority revision 等于
  提交时 revision，不等即 raise。专家一改判，整个 committed shadow 加载失败。
- **G2 版本域平铺**：`claim_ledger.current_shadow_versions()`（:3334-3351）把 base 层版本
  与 `reducer`/`review_bridge`/`queue` 平铺在一个 dict，`committed_shadow_versions_are_current`
  用它判全代生死——effective 层 bump 会误杀 base。
- **G3 验证指纹绑错对象**：`claim_ledger.py` 约 :762 的 `validation_input_hash` 在每条 edge
  里绑入 `target_review_revision`；约 :2133 的复用逻辑要求该 hash 相等。reject→restore 后
  revision 已变，旧验证事实无法复用，verifier 被迫全量重验（真实 LLM 花费）。
- **G4 schema 独占**：`schemas/claim_ledger.schema.json:101` 为 `additionalProperties:false`，
  base/effective 共用同一 schema，effective 行无法扩展字段。
- **G5 journal 语义绑死 generation**：现有 WAL 固定保护 8 个 generation 文件，恢复路径会登记
  verifier failure（约 :924）；journal 删除才是全局提交点。零 LLM 的 effective fold 不能复用。
- **G6 权威时间精度**：`ai_review_actions.py:303` `recorded_at` 为秒精度，快速
  reject→restore→reject 可得到相同 revision，事件排序不能依赖它。
- **G7 stage 复用入口过粗**：`desktop_tasks.py` 约 :953 `stage_is_reusable` 对 claim 校验失败
  一律 `except Exception: return False`，无法区分 base 损坏（该重建）与 effective 滞后
  （该 fold）。

## 3. Phase 1 设计公理

总纲 §1 公理之上追加七条，违反任何一条即返工：

1. **零 mutation**：Phase 1 代码不得写 `requirements*.jsonl`（除既有抽取路径自身）、
   `review_states.jsonl`、`ai_review_states.jsonl`、`omission_states.jsonl`、
   `decide_trace.jsonl`。claim queue 只产出 dry-run proposal 文件。测试断言（§10 测试 9）。
2. **事件只有投影**：`claim_review_events.jsonl` 只承载 bridge 投影，actor 恒为
   `system:claim-review-bridge`；无专家写入口、无 API POST。
3. **正确性不依赖投影成功**：fold 每次直接重读当前 target set 与权威 review state；投影
   只供审计，丢失/滞后不影响 fold 结论。
4. **stale ≠ corruption**：base 损坏才重建；effective 滞后只触发纯 fold。authority 或
   effective 层版本变化**永远不得**进入 `refresh_claim_shadow`。
5. **只读消费**：API/UI/导出读账本一律经 committed 快照校验；撕裂读 → 503 retryable；
   stale → 如实标记，请求路径不 fold。
6. **门控绝缘**：readiness_verdict、stage 复用语义、golden、chain 跳过逻辑、
   merged_consistency 输出结构、clarification TIER 判定，一律不改语义。
7. **健康信号与 hash 绑定产物分离**：运行期健康指标（fold lag、torn tail、quarantine）
   只写独立 sidecar，绝不写入 `claim_shadow_metrics.json` 等 hash 绑定文件。

## 4. 数据契约（四份独立 schema + revision 公式，先行冻结）

### 4.1 schema 清单

| 文件 | schema | 说明 |
| --- | --- | --- |
| `schemas/claim_ledger.schema.json` | `claim-ledger/v3`（**不动**） | 仅 base 行 |
| `schemas/claim_effective_ledger.schema.json`（新） | `claim-effective-ledger/v1` | effective 行 |
| `schemas/claim_review_event.schema.json`（新） | `claim-review-event/v1` | 投影事件 |
| `schemas/claim_queue_proposal.schema.json`（新） | `claim-queue-proposal/v1` | dry-run 提案 |
| `schemas/claim_queue_compat.schema.json`（新） | `claim-queue-compat/v1` | omission 整块兼容行（**独立文件/集合**，见 §4.4） |

全部 `additionalProperties: false`；base schema 不背两种行结构。

### 4.2 `claim_effective_ledger.jsonl`（claim-effective-ledger/v1）

行 = base 行（claim-ledger/v3 全字段，逐字）+ 三个追加键：

- `claim_effective_revision`（公式见 §4.5）；
- `effective_facts`：fold 输入事实摘要——`{valid_group_ids, validated_negative_id,
  invalidated_target_ids, reused_validation: bool}`（`reused_validation` 是 fold 结果，
  **只出现在这里，永不写入事件**）；
- `last_event_seq`：fold 时事件流最大已应用 seq。

### 4.3 `claim_review_events.jsonl`（claim-review-event/v1，append-only）

字段（全集冻结，任何增删升 schema 主版本）：

- 链与身份：`schema`、`event_seq`（publication 锁内单调）、`event_id`
  （`CRE-<seq>-<event_hash前12>`）、`prev_event_hash`、`event_hash`
  （`sha256(canonical_json(除 event_hash 外全部字段))`）；
- 事件语义：`event_kind` ∈ `target_invalidated | target_reactivated`（**独立字段**）；
  `eligibility_before` / `eligibility_after` ∈ `active | rejected | unknown`；
- 归属：`claim_id`、`claim_hash`、`document_generation_id`、`catalog_generation_id`、
  `linked_claim_ids`（同 target 影响全部 claim）；
- 证据：`actor`（恒 `system:claim-review-bridge`）、`recorded_at`（带时区 ISO，**仅展示，
  不参与排序/幂等**）、`reason`、`source_store`（`ai_review_states.jsonl` /
  `review_states.jsonl`）、`target_requirement_id`、`target_fingerprint`、
  `target_review_revision`（当前权威语义状态，沿用 `b_track_authority_state` 公式）；
- 排序与幂等：`source_event_revision`（公式见下）、`idempotency_key`；
- CAS 与代际：`expected_claim_effective_revision`、`bridge_version`、
  `route: "deterministic"`（投影零 LLM）。

**`source_event_revision` 公式**（G6 修复，不依赖秒级时间戳）：

- B 轨：`"<append_ordinal>:<canonical_row_sha256前16>"`——`append_ordinal` 为该记录在
  `ai_review_states.jsonl` 中的行序（0 起，锁内确定），hash 为该行 canonical JSON 的
  SHA-256 前 16  hex；
- A 轨：`"<history_index>:<event_hash前16>"`——review_states 内嵌 history 的下标 +
  该 history 条目的 hash。

**幂等键**（在 v1.0 基础上补全代际维度）：

```
idempotency_key = sha256(document_generation_id | catalog_generation_id |
                         claim_id | claim_hash | event_kind |
                         target_fingerprint | source_event_revision | bridge_version)
```

锁内追加前检查有效前缀，同键已存在则跳过；重启/重跑/reconcile 不产生重复行。
**v1.0 的 `prior_state/next_state` 废除**（与 event_kind 混淆），由
`eligibility_before/after` 取代。

文件纪律：publication 锁内 append + flush + fsync；torn-tail 恢复截断至最后完整行；
**hash 链校验失败的后缀必须先隔离**（重命名为
`claim_review_events.quarantine-<yyyymmddThhmmss>.jsonl` 留存审计）再截断，隔离事实记入
`claim_health.json`——绝不静默丢弃，也绝不让新事件接在断链点之后。

### 4.4 `claim_queue_proposals.jsonl` 与 `claim_queue_compat.jsonl`（派生快照）

均为**派生物、非权威**：每次 effective materialization 后在同一锁内整文件原子重写
（tmp+fsync+`PermissionError` retry），不 append、不进事件、**不进 fold WAL 之外的任何
回滚集**（proposals 与 effective trio 同事务，compat 文件同事务一并重写，见 §5.4）。

- 提案行（claim-queue-proposal/v1）：`proposal_id`、`claim_id`、`parent_block_id`、
  `locator`（catalog 精确 locator 原样）、`claim_source_fingerprint`、
  `document_generation_id`、`catalog_generation_id`、`claim_effective_revision`、
  `action: "needs_extraction"`（唯一动作）、`dry_run: true`、`queue_version`、
  `created_from_event_seq`。
- 候选条件精确为：**当前 effective 行 `resolution == "uncertain"`**（resolution 无
  `invalid` 取值；invalid group/edge 经 reducer 表现为 uncertain——总纲 §2.4）。
- 兼容行（claim-queue-compat/v1，`claim_queue_compat.jsonl` 独立文件）：旧
  `omission_states.jsonl` open 项的整块映射，含 `compat_whole_block: true`、原 omission
  字段与 best-effort block 定位；**只作展示，不冒充块内全部子 claim，不参与提案计数**。

### 4.5 revision 公式（总纲 §5.1 逐字实现；`reducer_version` = `CLAIM_EFFECTIVE_REDUCER_VERSION`）

```
document_effective_revision = sha256(base_generation_id | event_seq | event_prefix_hash |
                                     target_set_hash | requirement_review_state_hash |
                                     reducer_version)
claim_effective_revision    = sha256(base_claim_row_hash | ordered_relevant_event_hashes |
                                     linked_target_fingerprints |
                                     linked_target_review_revisions | reducer_version)
```

无关 requirement/claim 的事件不得改变某 claim 的 `claim_effective_revision`（测试断言）。

### 4.6 `claim_effective.meta.json`（`CLAIM_EFFECTIVE_SNAPSHOT_VERSION = claim-effective-snapshot-v2`）

`claim_events_enabled: true`；`event_prefix_sha256`、`last_event_seq`、
`document_effective_revision`、`target_set_hash`、`requirement_review_state_hash`、
`reducer_version`、`bridge_version`、**`queue_sha256` / `queue_count` / `queue_version`（新增，
queue 与 effective 同事务提交）**；沿用 base/effective 文件 sha256、generation 绑定、状态计数。

### 4.7 `claim_health.json`（新文件，**不 hash 绑定、不进任何 generation meta**）

运行期健康 sidecar，publication 锁内原子重写：`last_fold`（status/trigger/finished_at）、
`bridge_fold_lag`（计数+最近原因）、`torn_tail_recovered`（计数+quarantine 文件引用）、
`authority_cas_gap: true`（已知缺口留痕，Phase 1.5 必改）、`protocol_migrations`
（v6→v7 等迁移记录）。读侧对它只做 best-effort 展示，永不据以判 corruption。

## 5. 机制设计

### 5.1 loader 三层拆分（G1 修复，`claim_artifacts.py`）

- `load_committed_claim_base(out_dir)`：验证不可变 base 代——generation meta schema/协议、
  catalog/catalog meta/groups/base ledger/metrics 的 hash 与计数、catalog↔ledger 一一对应、
  blocks/table_items/requirements 绑定、`_validate_shadow_graph`。**绝不读当前
  `ai_review_states.jsonl` 做有效性判断**；meta 中记录的
  `target_generation_id`/`target_review_authority_revision` 仅作 provenance 返回。
- `load_committed_effective_snapshot(out_dir)`：验证 effective 文件族内部一致性——
  effective meta、effective ledger hash、queue hash/count、重算事件有效前缀 hash 与
  `event_prefix_sha256` 比对、逐行 schema 校验。不一致 = 损坏（可经 fold 重建），
  与"滞后"严格区分。
- `assess_effective_freshness(out_dir, snapshot)`：实读当前
  `ai_requirements.jsonl`（文件 sha256）、`target_set_hash`、
  `requirement_review_state_hash`、事件前缀，与 effective meta 比对，返回
  `{fresh: bool, stale_reasons: [...]}`。**stale 不抛异常、不判死**。

`load_committed_shadow` 保留为 legacy 包装（内部改调三层接口），其"当前 authority 必须等于
提交时"的行为**删除**；现存调用点（`desktop_tasks.stage_is_reusable`、acceptance、review
packet）逐一改为显式三层语义（§6.5）。

### 5.2 版本域拆分（G2 修复）

| 域 | 常量 | 变化后的动作 |
| --- | --- | --- |
| base 域 | catalog/packing、alignment 三件套、ledger schema、prompt、candidate_policy、prefilter、coverage_validator、batch_policy、cost_policy、negative_policy、negative_validator、review_adapter、**validation_reuse（新）** | ledger-only 重建（`refresh_claim_shadow`），**不得**新增初抽 LLM 调用；复用走 §5.3 |
| effective 域 | effective snapshot version、effective ledger schema、bridge、**effective_reducer（新）**、queue | **纯 fold**，永远不得进入 `refresh_claim_shadow` |

`current_shadow_versions()` 拆为 `current_base_versions()` 与
`current_effective_versions()`；`committed_shadow_versions_are_current` 对应拆两个判定。
`CLAIM_REDUCER_VERSION`（build 期，= claim-reducer-v2）留在 base 域**不动**；fold 用新常量
`CLAIM_EFFECTIVE_REDUCER_VERSION = claim-effective-reducer-v1`。

### 5.3 `semantic_validation_fingerprint`（G3 修复）

```
semantic_validation_fingerprint(group) = sha256(
  claim_hash | edges[(target_requirement_id, target_fingerprint, relation,
                      produced_evidence)] | prefilter | validation_method |
  verifier_runtime_fingerprint | validator_version)
```

即现行 `validation_input_hash` **剔除 `target_review_revision`**；由 group 行已存字段在
比较时**派生**（group schema 不变、无迁移）。行内缺任一组件 → 该 group 不可复用
（如实重验，不强行闭合）。公式版本钉 `CLAIM_VALIDATION_REUSE_VERSION =
claim-validation-reuse-v1`，记入 shadow/effective meta，归属 base 域。

- **重建复用规则**（替代 :2133 旧逻辑）：前序 group 为终态（`validated` 或
  `invalid:semantic_not_entailed`）且派生指纹相等且 request 血缘完整 → 复用。
- **fold 使用规则**：已验证 group 可用于闭合，当且仅当派生指纹与当前 target 内容匹配、
  target 存在、当前 eligibility ≠ rejected。
- **reactivation 语义**：eligibility 回到 active 且 target_fingerprint 与验证时相同 →
  既有验证事实**重新启用**（`effective_facts.reused_validation: true`），claim 回 covered；
  target 内容在 rejected 期间变化（fingerprint 不同）→ 旧验证不可复用，claim 保持 open。
  **reactivation 本身永不制造新的验证事实**（总纲 §2.5）。

### 5.4 fold 流程与 WAL v2（G5 修复，`claim_review_actions.py` 拥有）

`fold_effective_ledger(out_dir, *, trigger) -> dict`：

1. **reconcile**：实读 target set 与权威，与有效事件前缀已投影集合比对；缺投影（如审查
   动作发生时未触发 fold）先在锁内补投影（§4.3 幂等吸收）。
2. **实读快照**：再读 target set 与权威，计算 `target_set_hash` /
   `requirement_review_state_hash` 及 `ai_requirements.jsonl` 文件 sha256。
3. **逐 claim 归约**：base 行 + 该 claim 有效事件前缀 + 当前事实，走 `reduce_claim` 同一
   优先表；target rejected/缺失/fingerprint 不符时，即使事件追加失败也立即使相关 group
   失效并重开 claim（总纲 §2.5）。
4. **物化（journal v2）**：`CLAIM_ARTIFACT_PROTOCOL_VERSION` 升 v7——journal 增加
   `transaction_kind: generation | effective_fold`（v4/v5/v6 journal 恢复路径保留）。
   effective_fold 事务**共同保护且仅保护**：
   `claim_effective_ledger.jsonl`、`claim_queue_proposals.jsonl`（与
   `claim_queue_compat.jsonl`）、`claim_effective.meta.json`。
   逐文件 hash-bound backup → WAL durable → tmp+fsync+原子替换 → 重读校验 →
   **journal 删除 = 全局提交点**。事件流**不参与** fold 回滚（自带 append/fsync/隔离恢复）。
5. **提交前复验**（P1）：journal 删除前在 publication 锁内复验三项——
   `ai_requirements.jsonl` 文件 sha256、`target_set_hash`、
   `requirement_review_state_hash`，任一与步骤 2 不符则放弃本次物化、恢复备份并重试
   （上限 3 次；仍失败记 `bridge_fold_lag`，保留旧 effective）。**绝不提交混合两个
   review/target 代际的快照**。

崩溃恢复：发现 `transaction_kind=effective_fold` 的未完成 journal → 恢复上一代 effective
trio、在 `claim_health.json` 登记 interrupted fold；**绝不登记 verifier failure**
（那是 generation 路径语义）。

### 5.5 锁序、hook 与触发点（P1）

- 锁序唯一方向：**先取 publication 锁，锁内短暂嵌套读 review authority**；绝不在持有
  review 锁时反取 publication 锁。
- **hook 必须在 review 锁完全释放后执行**（v1.0 的"fsync 后"表述作废）：
  `apply_ai_review_action` / `apply_expert_decision` 在锁释放、动作已成功返回之后调用
  `fold_effective_ledger(trigger="review_action")`；fold 异常吞掉只记
  `bridge_fold_lag`，绝不让审查动作失败。
- 触发点：**ai-extract publish 后**（初代物化）、**refresh_claim_shadow 尾**、
  **review 动作 hook**、**maintenance hook**（请求路径之外的自动 reconcile：
  api_server 启动时与 desktop chain 启动时执行 `fold_if_stale`——先
  `assess_effective_freshness`，stale 才 fold，fresh 零开销跳过）、
  **CLI `claim-ledger-fold --out-dir <dir>`**（统一 JSON envelope，退出码 0/2/3/4 口径同
  既有子命令）。API 请求路径不 fold（公理 5）。

### 5.6 review-state bridge 语义（B 轨生产，A 轨只建 adapter）

- 权威语义逐字执行总纲 §2.5：无 row ≠ rejected；无 fingerprint、匹配歧义或
  `needs_reconfirmation` 的旧 row → eligibility `unknown`，不得用于关闭 claim。
- 投影映射：rejected / 内容变化 / target 替换 → `target_invalidated`；恢复为非 rejected
  → `target_reactivated`；`accepted`、`expert_pending` 等非 rejected 状态不创建 edge、
  不验证 coverage、不引入新门。
- adapter 必须由声明的 `target_kind` 选择，禁止按 ID 外形猜轨道。
- Phase 1 不实现 claim → requirement 反向桥；A/B 写入口的 review-revision CAS 缺口如实
  记入 `claim_health.json`（`authority_cas_gap`），Phase 1.5 必改。

## 6. 接入面设计

### 6.1 只读 API（`api_server.py`，全部 GET，token 校验同既有）

读 committed 快照 + 版本校验；撕裂读 `(TimeoutError, OSError, ValueError)` → 503
`{"error","retryable":true}`；分页 `?limit/&offset=`；无 committed generation → 200 +
`available: false` + 空集合。所有 payload 携带 `phase: "production-dual-write-v1"` 与
`document_effective_revision`（**revision 一致性钉**：UI 发现多个端点 revision 不一致时
必须丢弃并重新获取，不得拼装两个代际的数据）。

| 端点 | 内容 | schema 自封 |
| --- | --- | --- |
| `/claim-catalog` | catalog 行 join 当前 effective（resolution/classification/exclusion_kind/claim_effective_revision），`?resolution=&owner_unit_id=` | `claim-catalog-view/v1` |
| `/claim-ledger` | 当前 effective 行，`?resolution=covered\|excluded\|uncertain` | `claim-ledger-view/v1` |
| `/claim-coverage-groups` | 当前 generation groups + **effective invalidation overlay**（每组 `currently_invalidated: bool` + 失效原因，fold 产物），`?claim_id=` | `claim-coverage-group-view/v1` |
| `/claim-metrics` | **`generation_metrics`（hash 绑定的 claim_shadow_metrics 原样）与 `effective_metrics`（fold 后当前计数/比率 + document_ready informational + effective_fresh + stale_reasons）分键返回** + 新旧并列块 | `claim-metrics-view/v1` |
| `/claim-review-events` | 有效事件前缀（hash 校验后），`?claim_id=` | `claim-review-event-view/v1` |
| `/claim-queue` | `{proposals: [...], compat_omissions: [...]}`（**两个独立集合**，分别来自两个派生文件），全部 `dry_run: true` | `claim-queue-view/v1` |

### 6.2 Vue3 UI（`ui/src/`）

- `phaseNavItems` 新增 `"claim"`（账本）页 + 新组件 `ui/src/ClaimLedger.vue`，挂载同
  DocumentReview；顶部固定徽标"**双写观察期 · 不影响 READY 判定**"。
- 构成（全只读）：① 指标卡（`effective_metrics` 四比率含分子分母，分母 0 → "—"；
  `document_ready` / `effective_fresh` 状态灯，stale 时显示"账本待刷新"不主动触发写）；
  ② 新旧并列卡（旧 coverage_pct/core_coverage_pct vs 新 verified_coverage_ratio /
  eligible_resolution_ratio，并排等宽各标来源版本）；③ claim 表格（resolution/owner unit
  过滤 + 分页；详情抽屉：claim 文本、精确 locator、带 overlay 的 coverage groups、事件
  时间线）；④ 队列页签（proposals 与 compat_omissions 分区展示，"dry-run" 徽标，
  **无执行按钮**）。
- `api-client.ts` 按 `request<T>` 模式加 6 个方法与类型；**revision 一致性**：同一页面
  两次请求 `document_effective_revision` 不一致 → 整页重取。
- vitest 组件/客户端测试，零 LLM。

### 6.3 导出与兼容字段

- `clarification_report.py`：`clarification_report.json` 新增 `claim_ledger` 键
  （informational：`effective_metrics` 摘要、`document_ready`、`effective_fresh`、
  uncertain 前 50 条 claim_id+locator+文本截 120 字符）。readiness_verdict / TIER /
  coverage_basis 一字不动。`STAGE_IMPLEMENTATION_REVISIONS["clarification-report"]`
  v5→v6（加性字段，只失效重渲染）。
- `desktop_tasks.py`：chain payload 的 `claim_shadow` 摘要扩 `document_ready` /
  `effective_fresh` / `open_claim_count`（skipped payload 同步）；run_manifest 的
  ai-extract 条目新增 `claim_components` informational 子块（base/effective 两域版本 +
  各自 revision；`manifest_version` 保持 2，加性）。
- 批注导出：仅增加块内 claim 分布角标（covered/excluded/uncertain 计数，整块级）。
  **span/row 级定位延至 Phase 1.5**（§13 第 4 条）。

### 6.4 claim queue 与 agent

`CLAIM_QUEUE_VERSION = claim-queue-shadow-v1`；agent 侧只读两个派生文件，动作契约对齐
总纲 §6.2；`decide_trace.jsonl` 封闭 schema 不动；agent 代码本阶段零改动。

### 6.5 既有调用点迁移（G7 修复）

- `desktop_tasks.stage_is_reusable`：claim 校验改为 `load_committed_claim_base` +
  base 域版本判定；**删除 `except Exception: return False` 的笼统判死**——base 损坏
  （`ClaimArtifactError`）才 False（随后走既有 `refresh_claim_shadow` ledger-only 重建）；
  effective 滞后/缺失**不影响** stage 复用判定，由 maintenance hook 的 `fold_if_stale`
  补齐（§5.5）。verifier-enabled 与环境一致性检查保留。
- `claim_acceptance` / `claim_review_packet` / `claim_review_import`：改用三层接口，
  acceptance 的 authority 校验改为显式读取 provenance 字段（语义不变，仅换显式 API）。

## 7. 版本与缓存纪律

| 常量 | 现值 | Phase 1 | 域 |
| --- | --- | --- | --- |
| `CLAIM_LEDGER_SCHEMA_VERSION` | claim-ledger-v3 | **不动** | base |
| 新 `CLAIM_EFFECTIVE_LEDGER_SCHEMA` | — | `claim-effective-ledger/v1` | effective |
| `CLAIM_EFFECTIVE_SNAPSHOT_VERSION` | v1 | **v2** | effective |
| `CLAIM_REDUCER_VERSION` | claim-reducer-v2 | **不动（留 base 域）** | base |
| 新 `CLAIM_EFFECTIVE_REDUCER_VERSION` | — | `claim-effective-reducer-v1` | effective |
| 新 `CLAIM_VALIDATION_REUSE_VERSION` | — | `claim-validation-reuse-v1` | base |
| `CLAIM_REVIEW_BRIDGE_VERSION` | shadow-v1 | **claim-review-bridge-v2** | effective |
| `CLAIM_QUEUE_VERSION` | disabled-v1 | **claim-queue-shadow-v1** | effective |
| 新 `CLAIM_REVIEW_EVENT_SCHEMA` | — | `claim-review-event/v1` | effective |
| 新 `CLAIM_QUEUE_PROPOSAL_SCHEMA` / `CLAIM_QUEUE_COMPAT_SCHEMA` | — | `claim-queue-proposal/v1` / `claim-queue-compat/v1` | effective |
| `CLAIM_ARTIFACT_PROTOCOL_VERSION` | v6 | **v7**（journal v2 `transaction_kind` + loader 三层） | base（迁移见下） |
| `CLAIM_AUDIT_POLICY_VERSION` | shadow-v4 | **不动** | — |
| `STAGE_IMPLEMENTATION_REVISIONS["clarification-report"]` | v5 | **v6** | — |

**硬纪律**：以上 CLAIM_* 一律不得进入 `stage_producer("ai-extract")` 与初抽 section
cache key；base 域 bump 只触发 ledger-only 重建，effective 域 bump 只触发纯 fold，
**新增初抽 LLM 调用必须为 0**（§10 测试 11 断言）。

**协议迁移（如实记录）**：loader 判 `artifact_protocol_version != v7` 的存量快照为
legacy——按 v4→v5→v6 既有先例保留 v6 只读加载用于迁移复用；首个 Phase 1 运行执行一次
ledger-only 重建（初抽 LLM = 0；verifier 复用走 §5.3 派生指纹，组件齐全则零重验，
缺失组件的 group 如实重验并受预算约束）。迁移记入 `claim_health.json`。

成本：fold/投影/提案全确定性，**零新增 LLM 调用路径**；验收实测 verifier 增量 = 0（§11.3）。

## 8. A 轨边界

- 交付 `target_kind=atomic_requirement` 只读 adapter（`atomic_requirements.jsonl` +
  `review_states.jsonl` 权威，含 history 内嵌语义与 §4.3 的 A 轨
  `source_event_revision` 公式），单测覆盖；`review_state.apply_expert_decision` 挂
  fold hook（无 catalog 时 no-op）。
- A 轨不生成生产 catalog、不做双写展示，如实不展示；A 轨冻结回归另行冻结，本稿不背书。

## 9. 工作包分解（按专家建议顺序：契约 → loader/版本域/WAL → 机制 → 触发/API → UI）

- **WP1 契约冻结**：四份新 schema（§4.1）+ 双 revision 公式（§4.5）+
  `semantic_validation_fingerprint` 公式（§5.3）+ 事件字段全集（§4.3），含 schema
  golden 测试先行。
- **WP2 loader 与版本域**：三层接口（§5.1）+ 版本域拆分（§5.2）+ G7 调用点迁移（§6.5）。
- **WP3 WAL v2**：journal `transaction_kind`、effective trio 事务、legacy journal 恢复、
  quarantine 语义、`claim_health.json`。
- **WP4 事件链与 fold**：`claim_review_actions.py`——事件追加/hash 链/幂等、reconcile、
  fold、物化、提交前三重复验；reuse 指纹替换 :2133 旧逻辑。
- **WP5 触发与 maintenance hook**：ai-extract/refresh 接线、review 动作 hook（锁释放后）、
  api_server 与 chain 启动 `fold_if_stale`、CLI `claim-ledger-fold`。
- **WP6 只读 API**：6 端点 + overlay + freshness + revision 一致性钉。
- **WP7 兼容字段**：clarification `claim_ledger` 键、desktop payload、run_manifest
  `claim_components`。
- **WP8 UI**：`ClaimLedger.vue` + api-client + vitest。
- **WP9 queue 提案与 compat**：两个派生文件 + `/claim-queue` + UI 页签。
- **WP10 A 轨 adapter**：只读 + hook + 单测。
- **WP11 文档**：CLAUDE.md 里程碑、待办进度、本稿升"已冻结"+ 实施偏差记录。

## 10. 测试矩阵（全部 unittest.TestCase；UI 用 vitest）

1. **schema golden**：四份新 schema 与示例行互验；`additionalProperties:false` 拒绝多字段；
   base 行不被 effective schema 接受、反之亦然。
2. **loader 三层**：base loader 在当前 authority 变化后仍成功（G1 回归）；effective
   snapshot 内部不一致 → 损坏路径；freshness 对 stale 只报告不抛异常。
3. **版本域**：effective 域 bump（bridge/reducer/queue）后 base 判定仍 current、只触发
   fold；base 域 bump 触发 ledger-only 重建且初抽 LLM = 0。
4. **事件链**：seq 单调、hash 链可重放、torn-tail 截断、**坏后缀先隔离再截断**（quarantine
   文件存在且健康 sidecar 有记录）、幂等键吸收重复、`source_event_revision` 在秒级同刻
   reject→restore→reject 下仍保序可分。
5. **reducer 优先表**：总纲 §2.4 全行；正/负同时有效 → uncertain+conflict；前置失效 →
   uncertain+invalid reason；classification/resolution 不一致记 invalid。
6. **revision 公式**：无关 claim 的事件不改 `claim_effective_revision`；authority 变化只改
   受影响 claim；document revision 五要素任一变化即变。
7. **fold 并发与复验**：fold 中 authority 或 `ai_requirements.jsonl` 被写 → 三重复验失败
   重试，不提交跨代际快照；锁序不颠倒（反序注入断言无死锁）；hook 在 review 锁释放后
   执行（以锁状态探针断言）。
8. **bridge 语义**：reject → 关联 claim 重开（uncertain），**verifier 调用 = 0**（mock 计数）；
   restore 且 fingerprint 未变 → `reused_validation: true` 回 covered；restore 但内容已变
   → 保持 open；无 fingerprint/歧义/needs_reconfirmation → unknown 不关闭；非 rejected
   状态不创建 edge。
9. **零 mutation 守卫**：fold/投影/queue/API 全路径 patch requirements/review 写函数，
   断言调用次数为 0。
10. **WAL v2 崩溃矩阵**：effective_fold 在 backup 后/WAL durable 后/替换中途/journal 删除前
    强杀（真实 `os._exit`），重启恢复上一代完整 trio、health 登记 interrupted、
    **无 verifier failure 记录**；v6 legacy journal 恢复不回归。
11. **版本纪律**：CLAIM_* bump 后 `stage_producer("ai-extract")` 串不变；v6 存量快照经
    legacy 路径迁移，ledger-only 重建初抽 LLM = 0。
12. **queue**：仅 `resolution=="uncertain"` 入提案；compat 独立集合、
    `compat_whole_block: true`、不关闭子 claim、不计入提案计数。
13. **API**：老 out 目录 → `available:false` 200；撕裂读 → 503 retryable；分页/过滤；
    metrics 双键分离；groups overlay 与 effective 一致；revision 钉齐全。
14. **健康分离**：fold lag/torn tail/quarantine 只出现在 `claim_health.json`，
    `claim_shadow_metrics.json` 与其 hash 绑定不变。
15. **回归**：全量 unittest、golden 6/6、前端 vitest + vue-tsc。

## 11. 验收与退出条件（全部满足才可合并 main）

1. 全量 unittest 绿、golden 6/6、前端 vitest + vue-tsc 绿。
2. **真实 B 轨复演**（机器本地、真实 LLM 路由、新副本目录）：
   a. ai-extract 跑通，初代 effective v2 物化、`claim_events_enabled: true`；
   b. UI/API 拒绝一条有 coverage 的 AI 需求 → **不重跑抽取、verifier 增量 = 0**，
      fold 后相关 claim 变 uncertain，事件流出现 `target_invalidated`，UI 可见；
   c. 恢复该需求 → `target_reactivated`，`reused_validation: true` 回 covered，
      **verifier 增量仍 = 0**；
   d. fold 中途强杀 → 重启恢复上一代 effective trio，health 如实登记；
   e. 服务停止期间改 `ai_review_states.jsonl` → 重启经 maintenance hook 自动
      reconcile + fold，结论与在线路径一致；
   f. clarification_report.json 新旧并列块齐全且 readiness 与基线逐字节一致。
3. 成本实测：b/c 两步 verifier 调用/token 增量 = 0。
4. CLAUDE.md 里程碑 + 待办文档更新随代码同提交。

## 12. 明确不做（Phase 1）

1. 不切换 readiness / 自检早停 / TIER_GAP / `is_coverage_candidate` 到账本口径；
   merged_consistency 输出结构不改。
2. 不启用任何 claim/requirement mutation：无专家 claim 裁决 UI/API、无
   targeted_reextract 执行、queue 提案无执行入口。
3. 不实现 claim → requirement 反向桥；不补 A/B 写入口 review-revision CAS
   （`authority_cas_gap` 如实留痕，Phase 1.5 必改）。
4. **DOCX/PDF 批注导出 span/row 级 claim 定位延至 Phase 1.5**；Phase 1 只做整块级
   分布角标。⚠️ 相对总纲 §6.4 终态是范围裁剪，需审核人明示确认。
5. A 轨不建生产 catalog、不做双写展示。
6. 不动 `gui/`、不动 golden 基线、不动 decide_trace 封闭 schema。

## 13. 审核冻结项

审核人确认本稿时同时确认：

1. Phase 1 机制增量 = 只读投影 + effective fold + WAL/恢复本体；mutation 全禁
   （§3、§12.2），与总纲 v2.2 边界一致。
2. 四份独立 schema（§4.1）+ revision 公式（§4.5）+ 事件契约（§4.3，含
   `source_event_revision` 与幂等键全集）先行冻结。
3. loader 三层拆分 + 版本域拆分（§5.1/§5.2）：stale ≠ corruption；authority/effective
   层变化只触发纯 fold，永不进 `refresh_claim_shadow`。
4. `semantic_validation_fingerprint` 剔除 review eligibility（§5.3）：reactivation 只
   重新启用既有验证事实，绝不制造新事实；reject→restore 全程 verifier 增量 = 0。
5. effective WAL（journal v2 `transaction_kind`）只保护 effective trio，事件流隔离
   恢复、坏后缀先 quarantine 再截断（§4.3/§5.4）。
6. 健康信号独立 sidecar（§4.7），不进 hash 绑定产物。
7. hook 在 review 锁完全释放后执行；maintenance hook 承担重启 reconcile（§5.5）。
8. 批注导出 span/row 级定位延至 Phase 1.5（§12.4）——**明示确认/否决**。
9. 版本纪律：CLAIM_* bump 不进初抽 cache key，新增初抽 LLM 调用为 0（§7）。
10. 验收以 §11 真实 B 轨复演为准，复演记录留痕 CLAUDE.md。

## 14. v1.0 → v1.1 变更摘要（对应专家审查 7 项）

- P0-1 阶段边界：引用总纲 v2.2 澄清（§1）；hook/reject/restore 验收保留在 Phase 1
  只读语义内（fold 不写 requirements/review 文件）。
- P0-2 loader/版本域：§2.2 G1/G2、§5.1/§5.2、§6.5、§7。
- P0-3 schema 不兼容：§4.1/§4.2（独立 effective schema），版本表更正。
- P0-4 复用指纹：§2.2 G3、§5.3、§10.8、§11.2b/c。
- P0-5 事件契约：§4.3（`event_kind`/`eligibility_*`/`source_event_revision`/幂等键
  补全代际；废 `prior_state/next_state`；`reused_validation` 移入 effective_facts）。
- P0-6 崩溃事务：§4.6/§4.7/§5.4（journal v2、effective trio、queue 同事务、
  quarantine-then-truncate、不登记 verifier failure）。
- P1 触发/并发/口径：§5.4 提交前三重复验、§5.5 hook 锁释放后 + maintenance hook、
  §4.4 queue 条件与 compat 分集合、§4.7 health sidecar、§6.1 metrics 双键 + groups
  overlay + revision 一致性钉、§6.2 UI 重取纪律。
