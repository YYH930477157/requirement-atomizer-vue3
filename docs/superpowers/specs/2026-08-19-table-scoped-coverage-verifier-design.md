# 表级综合覆盖 Verifier 设计

日期：2026-08-19  
状态：已落地（分支 `codex/table-scoped-coverage-verifier`）  
范围：Claim Ledger 语义覆盖（及同表负向装箱），ledger-only

## 1. 目标

行级 claim 继续登记，B 轨仍按行可见、点行仍能对上。同一张表的待语义覆盖行改为**一次 LLM 调用综合看表、逐行给结论**，不再按行付费。

逐字命中保持免费。`llm_review`、定点补抽、catalog 行资格、`TABLE_STRUCTURE`、A 轨 golden 均不在本设计内。

## 2. 非目标

- 撤销「参数表每行皆需求」或合并/删除行级 claim。
- 用邻行需求或邻行正文闭合本行。
- 整表一条裁决再投影到各行。
- 改 B 轨 `TABLE_LEAF` 组装或 `_supplement_parameter_table_rows`。
- 改 `llm_review` 批处理。
- 伪造覆盖或在超限时静默丢行。

## 3. 数据流

1. Catalog 仍为每个合格 `table_row` 生成一条 claim（`table_context.fields` 不变）。
2. 逐字 `deterministic_verbatim` 照旧免费闭合，不进本请求。
3. 剩余 `independent_semantic` 且 prefilter 通过的组按表归堆。
4. 仅 `source_kind=table_row` 进入 `kind=table` 堆。`table_cell`、散文、清单、heading 走独立批。表键：能取到 `table_id` 则以它为准，否则回退 `locator.block_id`。同一 `block_id` 但不同 `table_id`（嵌套表）不得混装。
5. 同一张表的待验行组成一次覆盖请求（见 §4）。
6. 模型为每个 `group_ref` 返回 `covered` + 七维；账本仍按行写入、按行复用。
7. 负向 proposer/verifier 按同一表键装箱，章节 `unit_context` 只出现一次；负向 prompt 与 schema 不升版。

## 4. 请求形状

新用户请求 schema：`claim-coverage-verifier-request/v3`。

```json
{
  "schema": "claim-coverage-verifier-request/v3",
  "request_id": "CVR-…-R1",
  "batch_request_id": "CVR-…",
  "verification_round": 1,
  "batch_id": "COVERAGE-BATCH-0001",
  "scope": {
    "kind": "table",
    "table_id": "TBL-000215",
    "block_id": "BLK-000215",
    "title": "6.12 Operating conditions",
    "headers": ["clause_index", "Specification", "value_1", "value_2"]
  },
  "target_evidence": [["…"], ["…"]],
  "groups": [
    [0, "clause_index=6.12 | Specification=… | value_1=…", [0, 1]],
    [1, "clause_index=6.13 | Specification=… | value_1=…", [1]]
  ]
}
```

约束：

- `scope.kind` 仅为 `table` 或 `independent`。`independent` 时 `table_id`/`title`/`headers` 必须省略或为空，不得混入另一张表的行。
- `groups[i][1]` 对表行优先用 `table_context.fields` 的 `name=value` 管道串，不重复题注/表头。
- `target_evidence` 仍是本批各行**已提出边**的去重并集，不是整份文档、也不是「该表所有 B 轨需求」的额外池。
- 每一行的 `target_refs` 只指向本行已有候选边。邻行边不得出现在本行 refs 里。
- 返回格式保持 v6 契约：`{"decisions":[[group_ref,covered,[seven_checks]],...]}`。`covered` ∈ `{true,false,null}`，七维全是 boolean，每个 `group_ref` 恰好一条，无 rationale、无额外键。

System prompt 在现有七维顺序上增加表范围句（仅 `kind=table` 时生效）：

- 同批其他行只用于辨认结构（续页无表头、变体列、分组标题）。
- 不得把邻行正文当作本行义务。
- 不得用未列入本行 `target_refs` 的证据闭合本行。
- 不得整表一刀切；证据不够必须 `null`。

`kind=independent` 的 system 语义与当前 v6 逐字等价，仅信封改为 v3。

## 5. 装箱

| 集合 | 条数上限 | 字节上限 |
| --- | --- | --- |
| 同表 `kind=table` 待验组 | 无 24 上限 | 48_000 UTF-8（现 `CLAIM_COVERAGE_BATCH_MAX_UTF8_BYTES`） |
| 散文/清单 `kind=independent` | 24 | 同上 48_000 |
| 负向同表装箱 | 现有 48 | 现有 48_000 |

拆批规则：

- 规划 payload 必须是真实首发 HTTP body（v3 信封 + 现行 system + model/json_mode），与 `claim-verifier-batch-v3-full-http-body` 同口径。
- 单行自身超过 48KB：不发网，该行保持 `uncertain`/`open`，计入 oversized，不得塞进邻行请求。
- 整表超过 48KB：按行顺序切成多个 `kind=table` 子批，每子批仍带同一 `scope`（题注/表头），不得跨表。
- 两张表不得出现在同一请求。
- 预算头寸、轮次、429/JSON 修复/截断升级沿用现账本，不另开窗口。

## 6. 复用与指纹

每组仍有独立 `coverage_group_id` / `validation_input_hash`。表级请求额外绑定：

`table_scope_fingerprint` = sha256({
  `table_id` 或回退 `block_id`,
  `title`,
  `headers`,
  该表 catalog 中全部 `table_row` claim 的 `claim_hash` 排序列表
})

任一行增删改（含字段文本变化导致 hash 变）→ 该表所有 semantic 复用失效，必须按新指纹重验。已逐字闭合的组不重付。

`validation_input_hash` 对表行组必须纳入 `table_scope_fingerprint`、v3 scope、本行 `target_refs` 与 validator/runtime 版本。旧 v6 组不得在新 runtime 下复用。

## 7. 版本与迁移

| 常量 | 新值 |
| --- | --- |
| `CLAIM_COVERAGE_RUNTIME_VERSION` | `claim-coverage-runtime-v12` |
| `CLAIM_COVERAGE_VALIDATOR_VERSION` | `claim-coverage-validator-v7` |
| `CLAIM_VERIFIER_BATCH_POLICY_VERSION` | `claim-verifier-batch-v4-table-scoped` |
| 覆盖请求 schema | `claim-coverage-verifier-request/v3` |

不升：`CLAIM_CATALOG_VERSION`、`CLAIM_CANDIDATE_POLICY_VERSION`、`CLAIM_LEDGER_PROMPT_VERSION`（负向 prompt 未改）、`CLAIM_NEGATIVE_POLICY_VERSION`、`CLAIM_NEGATIVE_VALIDATOR_VERSION`、`TABLE_STRUCTURE_VERSION`、抽取/护栏/翻译 prompt。

`current_base_versions()` 已包含 `coverage_validator` 与 `batch_policy`。升版后旧 snapshot 的 `base_versions_are_current` 为假，读路径 `base_migration_required`。恢复方式：用**现有** `blocks.jsonl` / table artifacts 重建 catalog 与 claim base，再 ledger-only 跑覆盖。不要求重解析文档，不要求重跑 B 轨初抽。不得在 GET 里改版本字段假装 current。

Frozen golden `out/abnt_nbr_16968_atomizer_v5/` 与 `golden_sets/abnt_nbr_16968_v5` 不因本设计改写。Claim held-out / acceptance 若绑定 runtime 或 `current_base_versions`，按现契约诚实失效并在实施计划里列更新步骤，不改写人工裁决。

## 8. 失败语义

- 返回缺决策、重复 `group_ref`、非 `{true,false,null}`、七维缺项/非布尔、含 rationale/额外键：该批计 `verifier_operation_failure_count`，相关行保持 open，不得部分采纳。
- 子批 HTTP 失败：未确认的子批保持 open；已成功落盘的子批不回滚。
- 规划阶段不得把表行误装进 `independent` 批，也不得把两表装进同一 `table` 批——单测钉死，实现里直接分堆，不靠模型自觉。
- 负向仍 proposal-blind；装箱变化不改变五检与 reason 枚举。
- 进程中断、budget outbox、attempt WAL 沿用现协议；本设计不新开双写窗口。

## 9. 验收

全部 `unittest.TestCase`，挂在 `tests/test_claim_ledger.py`（必要时小幅辅助模块）。禁止 pytest 模块级 `def test_*`。

必须有的失败先写再实现：

1. **同表一次调用**：20 行续页条款表（headerless sequential clause）仅 pending semantic → 恰好 1 次覆盖 HTTP；20 条决策，`group_ref` 与 claim 一一对应。
2. **只按 48KB 拆**：构造使 24 行仍小于 48KB → 仍 1 次调用（证明 24 上限已取消）；再构造单行合法、整表超 48KB → 拆成 ≥2 个 `kind=table` 子批，且每子批 `scope.table_id` 相同。
3. **单行超限**：一行自身 >48KB → 0 HTTP，该行 open，其他行仍可发。
4. **邻行不得顶替**：行 A 的 `target_refs` 只有目标 1，行 B 有足以「看起来能盖住 A」的目标 2；请求里 A 的 refs 不含 2；夹具/契约断言 transport 如此。模型即使误判，落盘边仍不得把目标 2 写到 A（边集以请求 refs 为准）。
5. **跨表隔离**：两张表的 pending 行不得出现在同一 HTTP body；`table_cell` 不得进入 `kind=table` 批。
6. **散文仍 24**：无表 claim 仍按 24 组拆，信封 `scope.kind=independent`。
7. **逐字零调用**：仅 verbatim 命中的表行 → 覆盖 HTTP 为 0。
8. **复用失效**：改该表另一行的 `claim_hash` 后，本行旧 validated group 不得复用。
9. **旧 runtime 不复用**：v6/v11 组在 v7/v12 下必须重验。
10. **负向同表**：同一张表的负向候选进同一 proposer 批（不超过现 48/48KB）；不同表不混。
11. **规划字节**：planner 用的 body 与真实 `_post_json` 首发 body 逐字节一致（沿用 v3-full-http-body 钉法）。
12. **版本闸**：升版后旧 `shadow_meta.versions` 不得被当成 current。

回归：现有 coverage 七维、proposal-blind、inactive exact 不屏蔽、budget outbox、oversized 不计入已付成功，全部保持。

前端不改。`npm test` 不作为本设计门，除非误伤类型。

## 10. 实现落点（实施计划再拆）

- `claim_ledger.py`：装箱、v3 payload、prompt、`table_scope_fingerprint`、runtime/validator/batch 常量。
- `claim_artifacts.py`：只消费新 runtime 指纹，不改 publication 锁序。
- 若有 schema 文件登记 verifier request，同步加 v3；无独立 schema 则测试钉字符串即可。
- `prompt_registry`：仅当现有登记含 coverage validator 时同步，不登记则不新造入口。

## 11. 已裁定项

- 范围 = claim/审查付费，不是 B 轨按行抽取。
- 行级 claim 保留；整表一次看、逐行结论。
- 邻行只作结构，不能拿邻行需求闭合本行。
- 同表取消 24 上限；升版允许触发 `base_migration_required`（重建 catalog/base，不重抽）。
