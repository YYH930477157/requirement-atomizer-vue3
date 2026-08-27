# Phase 2 评审队列收敛 + atoms 退出交付物——盘点与统一设计

> 日期：2026-08-27  
> 分支：`codex/review-queue-design`（基线 `24132f1`）  
> 范围：只设计、不改生产代码/测试。  
> 依据：`docs/architecture-convergence-plan-2026-08-27.md` 诊断④「评审/状态权威碎裂」与第二节终态「单一账本 + 单一评审队列」；第三节绞杀式纪律。  
> 纪律：全部论断带 `file:line` 证据；宁漏勿错；血统如实；失败不冒充成功。

---

## 0. 问题陈述与目标

Phase 1 已把路由/守恒分轨收进单一内容模型与单一路由器。Phase 2 的产品侧缺口是：**专家裁决散落在至少六套（实际更多）状态文件**，各自带独立 writer、CAS 口径、锁、生命周期。界面上 2026-08-19 已把碎原子降出日常正门，但存储层与 API 仍把多套队列当并列权威。

目标形态（对照收敛计划第二节）：

- 一个带类型主体的评审队列账本：`subject_kind ∈ {atom, functional, table_cell, claim, omission, clarification_internal, clarification_customer, …}`。
- 统一 CAS / 幂等 / 事件链；旧文件有明确归宿（迁移 / 投影保留 / 冻结只读）。
- 每步写明「退役了什么」。
- `atomic_requirements.jsonl` 退出**人读交付物**地位，但 A 轨 DLMS 装配与部分内部中间路径必须保留。

本文**不**启动 SQLite / DAG 指纹（Phase 3）。

---

## 1. 评审/状态权威逐套盘点

寻址总纪律：状态文件必须走 `result_package.governed_artifact_path(..., category="state")`。`result_package.py` 把 `review_states` / `ai_review_states` 登记为内部 state，不进根交付物白名单（`result_package.py:184-186`）。legacy 哨兵清单另含 table/omission/claim/clarification 一族（`result_package.py:275-287`）。

### 1.1 `review_states.jsonl` —— A 轨原子需求评审

| 项 | 证据 |
| --- | --- |
| 存储 | `review_states.jsonl` + 投影 `review_state_events.jsonl`（`review_state.py:153-154`） |
| Schema/版本 | 无独立 JSON Schema。行契约 = `RequirementReviewState.to_dict`（`requirement_id/status/history/metadata/level`，`review_state.py:121-128`）。level：`REVIEW_LEVELS = ("functional","atomic")`，缺省 `atomic`（`review_state.py:46-49`）。CAS 协议常量：`claim-authority-write-v1`、`atomic-target-authority-write-revision-v1`、`target-publication-revision-v1`（`review_state.py:43-45`） |
| Writer | `apply_expert_decision`（`review_state.py:131`）；自动化路径 `RequirementReviewState.transition`（`review_state.py:113-119`），由 `llm_pipeline` 消费 |
| Reader | `read_review_authority_snapshot` / `_readonly`（`review_state.py:497-520`）；`api_server` `/review-actions` 与 `/requirements` 富集；`desktop_tasks.build_output_summary`（`desktop_tasks.py:2826-2828`）；claim 桥 `source_store=review_states.jsonl`（`schemas/claim_review_event_v2.schema.json:71-72`）；冻结 `gui/requirements_model.py` |
| CAS | 锁内比对 `expected_target_authority_write_revision`（物理写修订，含 history 前缀，防 ABA）（`review_state.py:158-170`）+ 可选 `expected_target_fingerprint` = 当前原子行 `review_subject_fingerprint`（`review_state.py:171-182`）。产物绑定 `target_publication_revision`（`review_state.py:78-92`） |
| 生命周期 | 自动化：`VALID_TRANSITIONS`（`candidate → llm_reviewed/rejected → expert_pending/accepted/flagged/… → frozen`，`review_state.py:22-32`）。专家覆盖：`EXPERT_DECISION_STATUSES` 可互改，**唯一禁止 frozen 改出**（`review_state.py:142-145,197-198`） |
| 锁/原子写 | `review_state_lock` + `process_file_lock`；`os.replace` 8 次线性退避（`review_state.py:38-42,906-915`）。状态整文件原子替换；事件 JSONL 尽力追加，失败不回滚状态（`review_state.py:219-236`） |
| 重叠 | 写后 `cover_effective_fold_after_decision` 折进 claim effective（`review_state.py:238` 起）。`level` 字段允许 functional，但功能级权威已明确落在 `ai_review_states`（见 1.2）——两套都能写 `level=functional`，这是碎裂点 |

### 1.2 `ai_review_states.jsonl` —— B 轨 AI / 功能需求评审

| 项 | 证据 |
| --- | --- |
| 存储 | `ai_review_states.jsonl`（`ai_review_actions.py:29`） |
| Schema/版本 | 无独立 schema。追加行 last-wins（`ai_review_actions.py:7-8`）。写修订 `ai-target-authority-write-revision-v1`（`ai_review_actions.py:30`） |
| Writer | `apply_ai_review_action`（`ai_review_actions.py:475`）。API：`POST /ai-review-actions` 与 `POST /functional-review-actions`（后者强制 `level="functional"`，`api_server.py:1669,1792-1805`） |
| Reader | `read_ai_review_states` / `read_ai_review_authority_snapshot`（`ai_review_actions.py:215-267`）；`_project_functional_review_view`（`api_server.py:2461-2504`）；`requirements_analysis` reject/override 投影；`review_insights.build_insights`（`review_insights.py:31-35`）；`claim_ledger.publish_b_track_shadow` 读 B 轨裁决（`claim_ledger.py:4658`）；`adjudication_bank` |
| CAS | 三层指纹：`source_fingerprint` / `review_anchor_fingerprint` / `review_subject_fingerprint`（`ai_review_actions.py:99-127`）。功能叙述字段并入 subject 指纹（`ai_review_actions.py:67-75,123-126`）。写修订按 append_ordinal + source_event_revision，**故意不同于** claim 语义 `target_review_revision`（`ai_review_actions.py:292-303`）。功能入口额外比对产物 `fingerprint`（`api_server.py:1760-1781`） |
| 生命周期 | `VALID_AI_STATUS = {accepted, rejected, needs_discussion, expert_pending, draft}`（`ai_review_actions.py:31`）。**无状态机约束**（覆盖式，`ai_review_actions.py:8`） |
| 锁/原子写 | `_ai_review_state_lock` + `ai_review_states.lock` + `process_file_lock`（`ai_review_actions.py:450-467`）。**追加 + fsync**，非整文件替换（`ai_review_actions.py:546-551`）。撕裂尾扫描恢复 |
| 重叠 | 与 1.1 并列：A 轨原子走 `review_states`，B 轨 AI/FRE 走本文件。§3.3 裁定「不新增状态文件、功能级仍写这里」（`api_server.py:2466-2467`）。写后同样 fold claim effective（`ai_review_actions.py:562-574`）。`source_ai_requirement_id` 主键域已打通 AIR/FRE（`ai_review_actions.py:196-212`） |

### 1.3 `table_review_states.jsonl` + `table_review_events.jsonl` —— 表格复核（已是 claim 投影 + 仍双写）

| 项 | 证据 |
| --- | --- |
| 存储 | `table_review_states.jsonl` / `table_review_events.jsonl`；另有几何冲突侧车 `table_geometry_conflicts.jsonl`（`table_review_state.py:27-40`） |
| Schema/版本 | `table-review-view/v1`、`table-review-state/v1`、`table-review-event/v1`、`table-review-decision-v1`（`table_review_state.py:27-30`）；权威投影 `table-claim-authority-v1`（`table_claim_authority.py:9`） |
| Writer | `apply_table_review_decision`（`table_review_state.py:685`）：**先委托 claim**（`_delegate_claim_cell_decision`，`table_review_state.py:800-807`），再原子写 dispositions（`table_review_state.py:853-856`），**仍把整表状态写回** `table_review_states` / 追加 events（`table_review_state.py:911-957`） |
| Reader | `GET /table-reviews`、`POST /table-review-actions`（`api_server.py:383,633`）；Vue `App.vue` 复核带；视图读 claim 投影 `load_table_claim_authority_projection`（`table_review_state.py:123-128,20-23`） |
| CAS | `table_evidence_fingerprint`（格文本/角色/处置/版本，`table_review_state.py:75-103`）。失配抛 `TableReviewConflict`（`table_review_state.py:57-62,733-738`）。单格幂等键绑定 decision 版本 + table/cell + fingerprint + promote/exclude（`table_review_state.py:760-771`） |
| 生命周期 | 表级 `pending` / `ready`（`table_review_state.py:830-834`）。格级权威状态来自 claim：`pending_review` / `promotion_pending` / `promoted` / `confirmed_excluded`（`table_claim_authority.py:87-118`） |
| 锁/原子写 | `_table_review_lock` + `table_review_states.lock`；`os.replace` 8×（`table_review_state.py:51-52`） |
| 重叠 | **终态权威已是 claim**（`table_review_state.py:694` docstring「Delegate … to Claim Ledger」）。本文件是审计/部分失败（`completed_cell_ids`/`remaining_cell_ids`/`recompute_error`）的第二真相源。这是「投影模式已落地、双写未退役」的活标本 |

### 1.4 `claim_structural_candidate_decisions.jsonl` —— 结构候选裁决

| 项 | 证据 |
| --- | --- |
| 存储 | `claim_structural_candidate_decisions.jsonl`（`claim_structural_overrides.py:33`）+ 并行 `claim_structural_overrides.jsonl`（提升）（`claim_structural_overrides.py:28`） |
| Schema/版本 | writer `claim-structural-candidate-decision/v3`，冻结回放 v1/v2（`claim_structural_overrides.py:34-45`）；schema 三份 `schemas/claim_structural_candidate_decision*.schema.json` |
| Writer | `claim_structural_overrides` 候选决策 writer（锁 `_CANDIDATE_DECISION_LOCK_NAME`，`claim_structural_overrides.py:94`） |
| Reader | `table_claim_authority.build_table_claim_authority_projection` 按 `(claim_id, claim_hash)` + generation 绑定读决策（`table_claim_authority.py:51-56,100-108`）；catalog 待审候选非零阻断 Ledger Ready（历史纪律，见 CLAUDE.md） |
| CAS | generation 四元组 `(document_generation_id, catalog_generation_id, claim_id, claim_hash)`；跨代不得阻塞新代确认 |
| 生命周期 | 确认排除（decision）vs 提升（override）vs pending operation（`table_claim_authority.py:87-115`） |
| 锁/原子写 | 独立 `claim_structural_candidate_decisions.lock`（`claim_structural_overrides.py:94`）；claim publication 锁族 |
| 重叠 | 表格 UI「提升/排除」即写这里，再投影回 table review。与 `claim_review_events` 的 `structural_falsification` 事件种类相邻但不合一 |

### 1.5 `claim_review_events.jsonl` + effective ledger —— Claim 评审事件链（最接近「统一队列内核」）

| 项 | 证据 |
| --- | --- |
| 存储 | `claim_review_events.jsonl`、`claim_effective_ledger.jsonl`、`claim_effective.meta.json`、`claim_queue_proposals.jsonl`、journal `.claim_effective_publication.journal.json`（`claim_artifacts.py:31-42`） |
| Schema/版本 | 事件 `claim-review-event/v2`（legacy v1）（`claim_ledger.py:65-66`）；effective `claim-effective-ledger/v2` / snapshot `claim-effective-snapshot-v3`（`claim_ledger.py:64`；`claim_artifacts.py:58`）；桥 `claim-review-bridge-v2`；队列 `claim-queue-v4` / proposal `claim-queue-proposal/v3`（`claim_ledger.py:61,68-69`） |
| Writer | `append_claim_review_events`（`claim_review_actions.py:236`）；`fold_effective_ledger`（`claim_review_actions.py:2780`）；队列执行、结构操作、A/B 裁决后的 bridge |
| Reader | `GET /claim-catalog|ledger|coverage-groups|metrics|review-events|queue`（`api_server.py:486-491`）；`POST /claim-adjudications` `/claim-queue/execute` `/claim-structural-overrides` `/claim-maintenance`（`api_server.py:642-651`） |
| CAS | 事件草稿禁带链字段；`idempotency_key` 必填，重复吞并（`claim_review_actions.py:265-274`）；可选 projection CAS 要求 base+effective 映射（`claim_review_actions.py:247-258`）；generation 绑定 `document_generation_id`/`catalog_generation_id`（schema `claim_review_event_v2.schema.json:18-21`）；`expected_base_claim_row_hash` + `expected_claim_effective_revision`（同 schema:46-49） |
| 生命周期 | 事件 kind：`target_invalidated` / `target_reactivated` / `expert_adjudication` / `audit_conflict` / `structural_falsification`（schema:33-36）。effective 行经 reducer 归约；queue proposal 独立 lifecycle |
| 锁/原子写 | `claim_publication_lock`；事件 **append binary + 重试**（`claim_review_actions.py:249,294-299`）；effective 走 journal + 固定名 replace |
| 重叠 | **已经桥接** `source_store ∈ {ai_review_states.jsonl, review_states.jsonl, ai_requirements.jsonl, atomic_requirements.jsonl}`（schema:69-73）。这是统一队列最强的现成内核——但只覆盖「claim 投影」，不覆盖 omission/clarification/table 审计双写 |

### 1.6 `omission_states.jsonl` —— 遗漏处置

| 项 | 证据 |
| --- | --- |
| 存储 | `omission_states.jsonl` + 补丁 `ai_supplements.jsonl`（`omission_actions.py:25-27`） |
| Schema/版本 | 无独立 schema。补丁版本 `ai-supplement-v3-identity-preconditions` / claim 焦 `v5-claim-focus-only`（`omission_actions.py:27-28`） |
| Writer | `apply_omission_action`（`omission_actions.py:466`）；agent `queue_all_gaps` / `resample_section` 登记 `needs_extraction` |
| Reader | `GET/POST /omission-actions`、`POST /omission-reextract`（`api_server.py:454,636-639`）；`agent_state.pending_extraction_block_ids` |
| CAS | `omission_source_fingerprint(block_id, text)` + `OMI-` 身份（`omission_actions.py:65-71,486-492`）。`expected_source_fingerprint` 失配 → `OmissionConflictError` |
| 生命周期 | `{non_requirement, needs_extraction, issue_confirmed, resolved}`（`omission_actions.py:29-34`） |
| 锁/原子写 | 自研 `O_EXCL` sidecar `omission_states.lock`（**不是** `process_file_lock`）（`omission_actions.py:203-234`）；追加 fsync。抽取另有 `ai_extraction_operation.lock`（`omission_actions.py:237-274`） |
| 重叠 | 与澄清 `TIER_GAP`「遗漏候选」同源信号、不同权威（`clarification_report.py:61-64`）。与 claim queue `needs_extraction` proposal 可对同一 block 各记一笔。`issue_confirmed` 字符串与内部核对同名、语义不同 |

### 1.7 澄清 / 内部核对（两套文件）

**内部核对状态机**

| 项 | 证据 |
| --- | --- |
| 存储 | `clarification_check_states.jsonl`（`clarification_check_states.py:22`） |
| Schema/版本 | 无独立 schema。动作枚举 `verified_ok / issue_confirmed / deferred`（`clarification_check_states.py:24`） |
| Writer | `apply_clarification_check_action` / `_batch`（`clarification_check_states.py:56-117`）；xlsx 导入 `import_internal_checks`（`clarification_report.py:1327-1336`）；`POST /clarification-internal-checks`、`POST /clarification-check-actions/batch`（`api_server.py:478,659`） |
| Reader | `read_clarification_check_states` last-wins（`clarification_check_states.py:46-53`）；`clarification_report` 就绪门：仅匹配 `evidence_fingerprint` 的 `verified_ok` 消解 blocking（`clarification_report.py` 消费；P1-2 跨语种确认绑定源哈希） |
| CAS | 写时**不比对**旧修订；读侧用 `evidence_fingerprint` 失效旧确认。指纹变 → 新 clarification_id/证据，旧 `verified_ok` 不沿用 |
| 生命周期 | `action` = 命令名，`state` = 有效快照（同值）（`clarification_check_states.py:147-151`） |
| 锁/原子写 | 自研 `O_EXCL` `clarification_check_states.lock`（`clarification_check_states.py:164-184`）；整历史原子替换，20× 退避（`clarification_check_states.py:30-31`） |

**客户答复**

| 项 | 证据 |
| --- | --- |
| 存储 | `clarification_answers.jsonl`（`clarification_report.py:40-41`） |
| Writer | 导入/回灌 `desktop_imports`；分析阶段当有据基线（`requirements_analysis.py:404`） |
| CAS | `(source_id, question)` 合并键（`clarification_report.py:1320-1322`） |
| 重叠 | 与内部核对分受众（`AUDIENCE_CUSTOMER` vs `AUDIENCE_INTERNAL`，`clarification_report.py:67-68`）。不是同一状态机 |

### 1.8 盘点时多出来的并列权威（必须纳入设计，否则「合并六套」会漏）

| 文件 | 模块 | 一句话 |
| --- | --- | --- |
| `claim_queue_proposals.jsonl` | `claim_artifacts.py:36`；`CLAIM_QUEUE_VERSION=claim-queue-v4` | 付费/定向补抽队列，与评审事件链同 publication 锁，但是**工作单**不是专家覆盖裁决 |
| `verification_states.jsonl` | `review_state.py:950-951,957-963` | 验证回写 CAS（`VerificationStateConflict`） |
| `manual_requirements.jsonl` | `review_state.py:953,1054-1066`；`GET` `api_server.py:1815-1825` | 手工建需求 append-only |
| `requirement_lifecycle_events.jsonl` | `review_state.py:952`；`GET` `api_server.py:1827-1837` | 生命周期事件流 |
| `dependency_decisions.jsonl` | `review_state.py:954,1069-1096` | 依赖边接受才落库 |
| `table_geometry_conflicts.jsonl` | `table_review_state.py:39-40` | WS1 几何冲突 overlay，裁决后清除 |

这四套 WS4 文件与 `review_states` **共用 verification 锁族、不共用 review 锁**（`review_state.py:967-975`），又是一层碎裂。

---

## 2. 交叉关系图（现状）

```
blocks / table_cell_items / dispositions
        │
        ▼
 claim_catalog (分母；不读 atomic_requirements)     atomize → atomic_requirements.jsonl
        │                                              │
        ▼                                              ▼
 candidate_decisions / structural_overrides      llm_pipeline → review_states.jsonl
        │                                              │
        ▼                                              ▼
 table_claim_authority 投影 ──GET /table-reviews    claim_review_events (bridge)
        ▲                                              │
        │                                              ▼
 apply_table_review_decision ──仍双写── table_review_states
                                                   fold → claim_effective_ledger

ai_requirements.jsonl  ──► ai_review_states.jsonl ──► 同上 bridge/fold
functional_requirements.json ──► 同一 ai_review_states (level=functional)

omission_states ──► /omission-*          （不进 claim 事件链）
clarification_check_states ──► 就绪门     （不进 claim 事件链）
clarification_answers ──► analyze 有据基线
```

关键不变量（现状已成立、收敛不得破坏）：

1. Claim catalog 从 **blocks / table_items / table_cell_items** 建，不从 atoms（`claim_catalog.py:1-5,1977-1992`）。
2. B 轨 claim target store 是 **`ai_requirements.jsonl` 优先，否则守恒闭合的 `functional_requirements.json`**（`claim_ledger.py:4607-4628`）——不是 `atomic_requirements.jsonl`。
3. 表格格终态以 claim 结构裁决为准（`table_claim_authority.py`）。
4. 功能级专家裁决唯一存储是 `ai_review_states.jsonl`（`api_server.py:2466`）。

---

## 3. atoms 退出交付物分析

### 3.1 2026-08-19 已降级的产品面（不做重复辩论）

- 碎原子不是分析师面对的需求产品；`RATOMIZER_FUNCTIONAL_EXTRACT` 默认 1。
- GUI 日常正门 = 功能需求；「原子诊断」默认关（`ratomizer.showAtomDiagnostics.v1`，`ui/src/App.vue:606-607,815-816`）。
- 打开已有结果落到功能评审。
- **未做**：删除 `atomic_requirements.jsonl`、翻 `EXECUTION_POLICY`、合并四份评审队列。

### 3.2 结果包登记：已经不是根交付物

`atomic_requirements` 登记为 **pipeline 内部产物**，无 `deliverable_path`（`result_package.py:171`）。人读发布物是 summary / 批注 HTML / 成文 xlsx / 澄清 xlsx 等（`result_package.py:188-248`）。

「退出交付物」**不是**「从磁盘删除」，而是：

- 不再作为打开结果、运行总览、导出按钮、模板成文的主指标；
- 不再出现在「最新交付物」面板；
- 打包 exe / CLI 不把缺 atoms 当整链失败（直抽模式本就可能无 atoms）。

### 3.3 生产消费者分类（测试夹具除外）

**A. 必须保留：A 轨 DLMS 装配中间产物**

| 消费者 | 角色 | 证据 |
| --- | --- | --- |
| `atomize.py` | 生产者 | `atomize.py:2920` |
| `cosem_object_model.build_object_model` | P1 数据字典 | `cosem_object_model.py:223` |
| `assemble_spec` | 经 `build_object_model` 间接消费 | `assemble_spec.py:24`；阶段输入 `pipeline_contracts.py:84` |
| `engineering_composer` | compose 溯源 | `engineering_composer.py:73` |
| `desktop_tasks` assemble/compose/llm-review 输入清单 | 阶段门 | `desktop_tasks.py:934,939,957` |
| `llm_pipeline` | A 轨 LLM 审查读写 | `llm_pipeline.py:656,678` |
| `review_tools.evidence_fingerprint` / `coverage_check` | 审查工具分母 | `review_tools.py:187,292-329` |
| `export_requirements` | 原子导出通道 | `export_requirements.py:34` |
| golden `test_golden_regression` | A 轨冻结基线 | 计数钉 `atomic_requirements` |

**B. 必须保留：claim / 审查桥的身份枚举（不是 catalog 分母）**

- claim 事件 `source_store` / `target_kind` 含 `atomic_requirements.jsonl` / `atomic_requirement`（`claim_review_event_v2.schema.json:71-77`）。
- A 轨 `review_states` 绑定的是原子行指纹（`review_state.py:171-182`）。
- **Claim 覆盖分母是 catalog 叶子，不是 atoms**（`claim_catalog.py:1-5`）。「退出交付物」不得误伤 catalog。

**C. 已是内部、可从「产品主指标」摘除**

| 消费者 | 现状 | 退出动作 |
| --- | --- | --- |
| `desktop_tasks.build_output_summary` | 先读 atoms 做类型/置信计数（`desktop_tasks.py:2822-2838`） | 改读 FRE / 分析行；atoms 计数降为诊断字段 |
| `output_writer` summary.md | 「先 Review atomic_requirements.jsonl」（`output_writer.py:207`） | 改成文/功能条指引 |
| `api_server` `GET /requirements` 默认读 atoms（`api_server.py:348,728,2212`） | 原子诊断页仍依赖 | 保留端点，默认 UI 不再进；功能页走 `/functional-requirements` |
| `ui/src/App.vue:1354` 空态文案仍提 atoms | 文案债 | 改功能产物 |
| 冻结 `gui/` | 只认扁平 atoms | **不扩展**；旧结果只读兼容 |

**D. B 轨产品路径（本来就不该以 atoms 为交付物）**

- 直抽：`functional_requirements.json`（`result_package.py:174-177`）。
- 旧 AI 抽：`ai_requirements.jsonl` → analyze → `软件需求列表-成文.xlsx`。
- `resolve_b_track_target_store` 明确原子 AI 产物优先于 FRE（`claim_ledger.py:4617-4625`）——这里的「原子」是 **ai_requirements 行**，不是 `atomic_requirements.jsonl`。

### 3.4 「退出交付物」边界（冻结）

**可以摘除 / 降级**

- 结果包根发布、交付物面板、运行总览主 KPI、默认导航落地。
- 新用户文档/wiki 把 atoms 写成「需求列表」。
- 非 DLMS 文档链上「缺 atoms ⇒ 失败」的误导（直抽模式）。

**必须保留**

- atomize 继续写 `atomic_requirements.jsonl`（A 轨装配输入；golden）。
- `assemble` / `compose` / COSEM P1–P5。
- A 轨 `llm-review` 与 `review_states`。
- claim catalog（blocks/cells）与 B 轨 target（ai_requirements / FRE）。
- `review_tools` 在 A 轨审查开启时对 atoms 的只读依赖。

**禁止借「退出」做的事**

- 不删文件、不改 golden 摘要、不翻 `EXECUTION_POLICY`、不把 catalog 改绑 FRE、不放宽守恒。

---

## 4. 统一队列设计（绞杀式）

### 4.1 目标形态

新增**一条**事件链账本（建议文件名，实施时再钉 schema）：

- `review_queue_events.jsonl`（append-only，hash chain，幂等键）
- `review_queue_effective.jsonl` + meta（由事件归约的当前队列；可先复用 `fold_effective_ledger` 机械）

**不要**第一天新建第六套「统一文件」却让六套旧 writer 继续各自为政。内核**复用 claim 事件协议**（已有 generation、idempotency、projection CAS、publication lock），按 `subject_kind` 扩枚举，而不是从 `review_states` 的整文件替换模型长出来。

每条事件最低字段：

```
schema                  review-queue-event/v1
subject_kind            atom | functional | table_cell | claim | omission
                        | clarification_internal | clarification_customer
                        | verification | dependency | manual   （后三个 Phase 2.1 可延后）
subject_id              稳定主键（SREQ- / AIR- / FRE- / OMI- / CLR- / CLM- / cell_id）
subject_fingerprint     该 kind 的既有指纹公式（禁止另起一套「统一哈希」冒充旧 CAS）
authority_write_revision  该 kind 的既有写修订公式
document_generation_id / catalog_generation_id   仅 claim/table_cell 必填
idempotency_key
event_kind              decided | invalidated | restored | deferred | queued
actor / recorded_at / reason
legacy_source_store     过渡期指向旧文件名
```

有效行 `review_queue_effective`：每个 `(subject_kind, subject_id)` 一条，字段投影自对应旧权威（status、overrides、needs_reconfirmation）。

**统一的是机械，不是语义。** `verified_ok` 不得与 `accepted` 混成一个枚举；`omission.issue_confirmed` 不得与 clarif `issue_confirmed` 同槽。

### 4.2 旧文件归宿

| 旧权威 | 归宿 | 退役声明 |
| --- | --- | --- |
| `claim_review_events` + effective | **内核留下**，升格为 review-queue 的 claim/table_cell 分区 | 退役「claim 事件不能表示非 claim 主体」的范围限制（扩 schema，不另起链） |
| `claim_structural_candidate_decisions` + overrides | **投影保留**：继续当 catalog 代际终态；队列只记 `subject_kind=table_cell` 的专家动作摘要 | 退役「table UI 与 candidate 文件各写各的终态」——终态只在 candidate/override |
| `table_review_states` + `table_review_events` | **冻结只读 → 停止双写** | 退役 table 文件作为**权威**；保留历史行只读。GET `/table-reviews` 只吃 claim 投影 + geometry overlay |
| `review_states.jsonl` | **先双写进队列，再切只读投影** | 退役独立 CAS 入口：`apply_expert_decision` 改为队列 append + 投影回旧文件（兼容期） |
| `review_state_events.jsonl` | 冻结投影 | 退役「状态 history 之外再追加一份可能失败的事件」（`review_state.py:228-236` 已知缺口） |
| `ai_review_states.jsonl` | 同上（functional + AI 原子行） | 退役「功能/AI 两入口两套指纹比对散落在 api_server」——比对进单一 apply |
| `omission_states.jsonl` | 迁入 `subject_kind=omission` | 退役 O_EXCL 自制锁（改 `process_file_lock` 同族） |
| `clarification_check_states.jsonl` | 迁入 `subject_kind=clarification_internal` | 退役「写时无修订、只靠读侧指纹失效」——补 `expected_evidence_fingerprint` CAS |
| `clarification_answers.jsonl` | 迁入 `subject_kind=clarification_customer` 或保持导入投影 | 客户答复是内容输入，不是覆盖裁决；可投影、不强制进同一状态机 |
| `claim_queue_proposals` | **保留为执行工作单**，不并进专家队列 | 退役「把付费 proposal 当成评审状态」的混淆 |
| WS4 verification/manual/lifecycle/dependency | Phase 2.1 再收 | 本期只登记，不迁 |

### 4.3 迁移顺序（先合并哪两套、为什么）

**第 0 步（零行为，只文档/测试钉）**  
冻结上表归宿与「统一机械 ≠ 统一枚举」。不 bump 行为版本。

**第 1 步（风险最低）：停写 table 权威双写**

- 为什么最低：`apply_table_review_decision` **已经**把终态委托给 claim（`table_review_state.py:694,800`），`table_review_states` 是事后审计快照（`:911-948`）。停写不改变专家可见终态，只去掉第二真相源。
- 退役：`table_review_states.jsonl` / `table_review_events.jsonl` 作为 writable authority；`GET /table-reviews` 不再以该文件 status 覆盖 claim 投影。
- 保留：`table_geometry_conflicts` overlay（尚无 claim 主体）。
- 验收：既有 table-review 测试改为断言「写 candidate/override + 投影」；旧文件存在则忽略。

**第 2 步：omission ∪ clarification_internal 进入同一事件链（非 claim 主体第一对）**

- 为什么次低：两者都是 append last-wins、指纹 CAS、**不参与** claim generation / fold（当前无 bridge）。爆炸半径小于 A/B review。
- 不要先合并 `review_states`×`ai_review_states`：二者已钩 `cover_effective_fold_after_decision`，错一次会污染 claim effective / Ledger Ready。
- 退役：`omission_states.lock` / `clarification_check_states.lock` 两套 O_EXCL 协议；两套独立 JSONL writer。
- 兼容：读路径继续从旧文件回放，直到队列前缀哈希证明包含全部历史。

**第 3 步：A/B 专家裁决双写 → 队列为写权威**

- `apply_expert_decision` / `apply_ai_review_action` 改为：锁内 append 队列事件 → 投影回旧 JSONL（字节级 last-wins 兼容）→ 既有 fold 钩子只认队列 revision。
- 退役：两套独立 `*AuthorityConflict` 类型对外暴露（对内仍计算各自指纹公式）；UI 仍打旧端点。
- 版本：新增 `REVIEW_QUEUE_VERSION` 进 stage/env 指纹的**状态层**（不进抽取缓存，避免无谓重付）。

**第 4 步：摘除投影回写（绞杀完成条件）**

- 条件：主检出全量绿；SBD/result3 类结果包只读打开后功能裁决/表格/澄清门与旧文件逐字段一致；打包 exe 一发布周期。
- 退役：旧文件 writer；旧文件改为只读适配器（缺队列则回放旧文件）。

**第 5 步（并行、可独立立项）：atoms 退出交付物**

- UI/summary/交付物面板；不碰 atomize/assemble/golden。
- 退役：运行总览「原子需求」主指标；空态文案；wiki 把 atoms 当需求产品的表述。

### 4.4 版本与兼容

| 层 | 策略 |
| --- | --- |
| 旧 JSONL | **至少两个桌面发布周期**只读兼容；`load_*` 双路径：队列优先，缺席回放旧文件 |
| Schema | 新 `review-queue-event/v1`；claim 事件 v2 **继续有效**（claim 分区可先别名写入旧链，避免双链） |
| API | 过渡期保留 `/review-actions` `/ai-review-actions` `/functional-review-actions` `/table-review-actions` `/omission-actions` `/clarification-*`。新增只读 `GET /review-queue?subject_kind=`。禁止第一天砍旧路径 |
| UI | `api-client.ts` 旧方法签名不变；内部可改打统一 GET。`data-testid` 保留 |
| 打包 exe | 旧 exe 只写旧文件 → 新代码必须回放。新 exe 写队列+投影，旧 exe 再打开同一目录不得丢裁决（投影回旧文件就是为它） |
| 指纹 | **禁止**发明第三套 subject hash。队列字段原样存放 `review_subject_fingerprint` / `omission_source_fingerprint` / `table_evidence_fingerprint` / `evidence_fingerprint` |

### 4.5 每步「退役了什么」（汇总）

1. 退役 table 状态文件的权威地位（保留历史只读）。  
2. 退役 omission/clarification 自制锁与无修订写入。  
3. 退役 A/B 两套独立 writer 作为写权威（旧文件变投影）。  
4. 退役 `review_state_events` 尽力追加的第二审计（并入链上事件，失败即响亮）。  
5. 退役 atoms 作为人读交付物/主 KPI（保留 A 轨中间产物）。  
6. **不退役**：claim catalog 分母、claim queue proposal 执行机械、守恒门、functional extract。

---

## 5. 风险清单

### 5.1 并发写与锁族不一致

今日至少四类锁协议并存：

- `process_file_lock`：`review_states` / `ai_review_states` / table / claim publication / WS4 verification（`review_state.py:946-947`；`ai_review_actions.py:462-466`）。
- 自制 `O_EXCL` + PID 偷锁：omission、clarification_check（`omission_actions.py:79-108,211-225`；`clarification_check_states.py:164-184`）。
- claim journal + 固定名 replace（断电语义与「追加 fsync」不同）。
- `extraction_operation_lock` 与 table recompute 嵌套（`table_review_state.py:887-888`）。

统一队列若只换文件名、不收锁族，Windows 上会出现「队列锁 + 旧投影锁」顺序反转。fold 已有跨轨饥饿与 30s 超时先例，再加一层更容易 503。

### 5.2 Windows `PermissionError` / 读者挡 `os.replace`

各模块退避次数不一致：review/table/claim 8×（`review_state.py:41`），clarification 20×（`clarification_check_states.py:30`）。合并后必须单源退避，否则「偶发 503」会被当成 CAS 失败诱导重试——`review_state` 已记载事件追加失败时重试不会产生新 transition（`review_state.py:230-232`）。

### 5.3 CAS 口径不可互替（最大语义风险）

| 权威 | 乐观并发代币 |
| --- | --- |
| A 轨 review | 物理 write revision（行+history）+ 可选 subject 指纹 |
| B 轨 AI/FRE | append_ordinal 写修订 + source/subject 指纹 +（功能）产物 fingerprint |
| table | 整表 evidence fingerprint |
| claim 事件 | generation + base row hash + effective revision + idempotency |
| omission | block 文本指纹 + OMI- id |
| 内部核对 | 写路径无修订；读路径 evidence_fingerprint |

把六套压进「一个 expected_revision 字段」会静默接受过期裁决或误 409。设计要求：**字段分列，kind 分派比对函数**。

### 5.4 Electron UI 与端点面

现网端点（`api_server.py` + `ui/src/api-client.ts`）：

- `/review-actions`、`/ai-review-actions`、`/functional-review-actions`
- `/table-reviews`、`/table-review-actions`
- `/omission-actions`、`/omission-reextract`
- `/clarification-internal-checks`、`/clarification-check-actions/batch`
- `/claim-*` 六只读 + adjudications/queue/overrides/maintenance

前端 409 已按 `needs_reconfirmation` / `effective_recovery_pending` 自动维护。统一队列的错误码必须**别名旧码**，否则工作台会停在黄条或死循环 POST `/claim-maintenance`。

### 5.5 打包 exe 兼容

旧 onefile 只认识旧路径。package_v1 下裸 `root / "review_states.jsonl"` 会错址（B1 教训）。新队列必须走 `governed_artifact_path`；旧 exe 写入的 legacy 根文件仍要被新读路径找到（`legacy_path` 已登记）。

### 5.6 fold / Ledger Ready 误伤

A/B 裁决已触发 effective fold。队列若重复 fold 或漏 fold，会出现 `bridge_fold_lag` 或假 READY。第 3 步必须单点 fold（已有 burst coalesce）。

### 5.7 atoms 退出误伤 A 轨

`pipeline_contracts` assemble 仍声明输入 atoms（`pipeline_contracts.py:84`）。若有人把「退出交付物」做成「atomize 可选且 assemble 跳过」，DLMS 规格链静默空转。退出范围卡死在 §3.4。

---

## 6. 核心决策清单（实施对照）

1. **内核 = 扩展 claim 事件机械，不新发明第三套账本协议。**  
2. **统一机械，不统一状态枚举。** kind 分派 CAS 与生命周期。  
3. **先停 table 双写，再收 omission+内部核对，最后收 A/B 专家裁决。**  
4. **claim_queue_proposals 仍是执行工作单，不并进专家队列。**  
5. **旧 JSONL 只读兼容 ≥ 两个桌面发布周期；旧 API 路径不砍。**  
6. **atoms 退出的是人读交付物/主 KPI，不是 A 轨中间产物，也不是 claim 分母。**  
7. **本期不迁 WS4 verification/manual/dependency；只登记。**  
8. **本期不 SQLite。**  
9. **每步必须写退役声明 + 回放旧结果包只读一致。**

---

## 7. 风险最大的三点（给审核方）

1. **CAS 口径错并**（§5.3）：一次「统一 revision」就会让过期功能裁决沿用或把 table 整表指纹拿去比 FRE 行。这是正确性红线，不是重构风格问题。  
2. **锁序 + Windows replace + fold**（§5.1/5.2/5.6）：统一队列写路径若再嵌套 claim publication 锁与 extraction 锁，打包机上的 PermissionError 会变成「裁决已点、effective 未折、重试无 transition」的用户可见分裂。  
3. **旧 exe / 旧端点 / 自动 `/claim-maintenance`**（§5.4/5.5）：只改存储不别名错误码，Vue 会把队列 409 当成 claim 恢复；只写新文件不投影回旧 JSONL，用户用旧包打开新结果等于丢评审。

---

## 8. 非目标

- 不改 functional-extract prompt、守恒阈值、`EXECUTION_POLICY`。  
- 不重建 ABNT golden、不删 `atomic_requirements.jsonl`。  
- 不实施本文件（本分支只提交设计）。  
- 不把 Phase 3 SQLite 预埋进本期 API。

---

## 9. 建议的下一步（实施时另立 worktree）

1. 第 0 步：把 §4.2 表钉成 `tests/test_review_queue_contract.py` 的「文件归宿」只读断言（仍不改 writer）。  
2. 第 1 步：table 停双写（独立 PR，可回放真实 table-review 结果包）。  
3. atoms 文案/总览与第 1 步并行（UI-only，零状态迁移）。
