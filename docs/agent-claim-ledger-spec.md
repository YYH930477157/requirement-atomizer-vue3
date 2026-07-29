# 原文命题保全账本（Claim Conservation Ledger）实施规格 v2.2

状态：**已冻结（v2.2；冻结历史见文末修订记录）**  
日期：2026-07-26（v2.2 修订 2026-07-28）  
前置：Phase 0/1/1.5/2 及专家审核两轮修复（main `b8f8e34`）；
`docs/agent-rollout-plan.md` 铁律全部适用

**v2.2 修订记录（2026-07-28，Phase 1 详稿专家审查后修订，逐条留痕）**：

1. **状态转正**：v2.1 已经用户复核并据以完成 Phase 0A/0B（main `a08a60a` 及后续整合
   `5827482`），本条仅补记"已冻结"，无语义改动。
2. **Phase 1 / Phase 1.5 边界澄清**（审查 P0-1）：§9 两分节原文存在张力——Phase 1 列有
   "effective reducer 和 review-state bridge"，Phase 1.5 又把"自动重开、event hash/CAS、
   bridge 补偿、实时 fold"并列。澄清为：**Phase 1 建成机制本体**（只读投影、effective fold、
   必要的 WAL/崩溃恢复），全部只读、零 mutation；**Phase 1.5 验证闭环**（target invalidation、
   专家拒绝、supplement replay 后自动重开的端到端故障恢复，event hash/CAS、bridge 补偿、
   authoritative-state 实时 fold 的验证）通过后，才启用任何 claim/requirements mutation 与
   authority CAS。阶段顺序不变（§14 第 10 条）。
3. v2.2 不改变 Phase 0A/0B 已完成产物的任何口径与验收结论。

## 0. 定位、保证边界与目标

本规格解决的不是某组英文动词漏识别，而是一个更基础的问题：
**每段进入系统的原文是否被保全、是否有明确处置、处置是否有可复核证据。**

test5/test11 的差异已证明，`requirement_like` 只是启发式优先级信号，不能承担完整性分母、
自检早停条件和遗漏告警三种职责。同一提示、同一模型、同一原文仍可能因模型方差产生不同
抽取结果；只扩充 `assigned/configured/programmed` 等词表会不断追着措辞打补丁。

本规格提供两层保证：

1. **确定性保全保证**：解析产物中的每个源文叶子单元，要么成为 claim，要么带受控原因
   显式排除；每个 claim 恰好归属一个抽取单元，并恰好有一条当前账本记录。
2. **证据化处置保证**：每个 claim 最终只能成为“已验证覆盖”“已验证排除”或“未解决”；
   模型单方面判断、块级来源匹配和预算耗尽都不能把 claim 关闭。

保证边界从 `blocks.jsonl` / `table_items.jsonl` 这一代解析产物开始。扫描图像未 OCR、解析器
未提取出的文字仍由现有 parse audit/OCR 就绪门负责；本账本不得把“解析器没有看见”伪装成
“原文已经处置”。

## 1. 不可违反的设计公理

1. **先枚举、后抽取**：claim catalog 必须在任何 LLM 抽取之前确定。
2. **叶子唯一**：容器块与其清单行/表格行不得同时作为可关闭 claim；分母只包含叶子。
3. **恰好一次归属**：每个 claim 必须有且只有一个 `owner_unit_id`；零归属或多归属均为硬失败。
4. **出处不等于覆盖**：`block_id`、`anchor_block_id`、`source_block_ids`、
   `quote_block_ids`、`section_fallback` 只能帮助定位，不能证明语义已覆盖。
5. **负向结论举证**：模型提出 `non_normative` 不是终态；必须有原因专属的确定性证据、
   独立语义复核或专家裁决。
6. **状态正交**：源文是否入账、语义是否解决、抽取是否成功、为何停止必须分字段表达，
   不得再压成一个 `closed` 布尔值。
7. **同代提交**：catalog、requirements、ledger 必须绑定同一 generation；任一文件缺失、陈旧或
   哈希不符时，消费者不得把组合产物视为成功。
8. **旧信号降级**：`requirement_like` 只用于预算排序、A 轨候选和可观测性，永远不再决定
   claim 是否存在、是否入队或是否早停。

## 2. 核心数据契约

### 2.1 Claim Catalog：全量源文坐标与保全清单

新增 `claim_catalog.jsonl`，由确定性模块在抽取单元打包前生成。catalog 同时覆盖
`blocks.jsonl` 与 `table_items.jsonl`，不依赖 LLM。

每行至少包含：

```json
{
  "schema": "claim-catalog/v1",
  "catalog_version": "claim-catalog-v1",
  "document_generation_id": "sha256:...",
  "catalog_generation_id": "sha256:...",
  "claim_id": "CLM-...",
  "claim_hash": "sha256:...",
  "source_kind": "paragraph_sentence|list_item|table_row|table_fallback|heading|caption|noise|other",
  "locator": {
    "block_id": "BLK-000094",
    "line": null,
    "start": 0,
    "end": 40,
    "position_basis": "repaired_text",
    "table_item_id": null,
    "row_index": null
  },
  "text": "Auxiliary outputs are user-programmable.",
  "raw_text": "Auxiliary o utputs are user-programmable.",
  "text_repair_version": "pdf-text-repair-vN",
  "normalized_text_hash": "sha256:...",
  "owner_unit_id": "UNIT-...",
  "eligibility": "claim|excluded",
  "exclusion": null
}
```

`eligibility=excluded` 的记录不进入 LLM 单元，`owner_unit_id=null`；它仍必须有 claim ID、
locator、排除证据和 ledger row，以证明不是在 catalog 之前被静默丢弃。

#### 2.1.1 叶子切分规则

- 普通段落按确定性句界切成可审计 span；句界规则、缩写白名单、分号/冒号处理均归
  `CLAIM_CATALOG_VERSION` 管理。复合句未进一步拆开时，整个 span 必须被完整覆盖，不能只覆盖
  其中一个子句后关闭。
- 清单并块只把“引导句”和每个非空清单行作为叶子；原并块容器只通过 catalog meta 的
  conservation mapping 留痕，不生成重叠的 catalog row。没有可分离引导句时，第一个非空清单行
  直接作为第一个叶子，不得为了凑“引导句”而吞掉或复制首行。
- 表格以 `table_items.jsonl` 的完整行作为叶子，保留 canonical cells、`item_id`、`row_index` 和
  表头上下文；对应 table block 只进入 conservation mapping。若解析器未生成 table item，则
  不得把整个 table block 作为一个 `table_fallback` claim：必须先按保留表头上下文的行组切分，
  每组最多 20 个非空行或 2000 个字符；单行仍超限时先按 cell/句界切分，最终才使用不重叠的固定
  2000 字符窗。每个 fallback 叶子保留 `fallback_group_id`、行范围和精确 locator。若底层 table block
  已被 5000 字符截断、缺少完整原始表格文本或 parser 明示不完整，记录 `parse_incomplete` 并阻断
  Phase 0A/READY，不能拿截断文本冒充完整 catalog。
- heading、caption、TOC、`reference_stub` 和普通 noise 标签本身都不足以证明非规范性，默认仍为
  eligible claim。只有空内容、精确父容器重复，以及由稳定位置/重复次数等确定性证据证明的页眉页脚、
  水印等 page furniture，才可直接标记 `eligibility=excluded`；均须记录
  `reason/rule_id/rule_version/evidence`。其余疑似结构噪声进入负向 proposal，不得在 catalog 前丢弃。
- 同一字符 span 只能属于一个叶子；父容器不得与叶子重复计数。
- paragraph/list locator 的 offset 一律以修复后 `text` 为基准，并保存 raw text、repair version 和
  PDF/DOCX region 存证；禁止混用 raw/repaired offset。

#### 2.1.2 身份与代际

- `document_generation_id = sha256(blocks.jsonl bytes | table_items.jsonl bytes | parser/text-repair
  provenance)`，表示源文解析代际。
- `catalog_generation_id = sha256(document_generation_id | CLAIM_CATALOG_VERSION |
  CLAIM_UNIT_PACKING_VERSION | unit packing config)`，表示 claim 切分和 owner 归属代际。
- `claim_id = sha256(document_generation_id | CLAIM_CATALOG_VERSION | source_kind | canonical locator |
  normalized text)` 的可读截断；完整 `claim_hash` 必须同时保存并做碰撞检查。
- claim 身份只承诺在相同解析代际和相同切分版本内稳定。源文件或解析代际变化后，旧专家事件
  不得自动冒充当前裁决；迁移必须是显式、有审计记录的独立动作。

#### 2.1.3 恰好一次归属

抽取单元由 claim 打包，而不是先切裸文本、再把整章全部 `block_ids` 复制给每个 chunk。
catalog 发布前必须校验：

- 每个 `eligibility=claim` 的记录恰有一个 `owner_unit_id`；
- 每个 owner unit 的 prompt 确实包含该 claim 的完整 text；
- claim 集合无重复 locator、无重复完整 hash、无跨 unit 重复所有权；
- sample 模式只生成 `scope=sample` 的账本，绝不能宣称文档级闭合。

#### 2.1.4 Source universe 与 conservation 方程

Phase 0A 冻结的分母不是含糊的“原文字符”，而是当前 parser generation 的 canonical source universe：

- 普通 block 使用完整 `repaired_text`；table 使用 `table_items` 的 canonical cells；已有权威子项的
  list/table 父容器只保留 container mapping，不再进入字符分母；
- parser/text repair 必须提供 raw-to-repaired span map。每个 raw 非布局字符要么映射到 canonical span，
  要么进入带原因的 repair deletion；每个 repair insertion 也单列来源。repair 层无法解释的增删直接
  形成 `unmapped_raw_span`，不得由 catalog 排除掩盖；
- **声明式豁免**：repair 的拼接/拆分使个别字符无法一一对应时（机翻词内空格修复高发），允许登记
  `repair_declared_unmappable`——必须带规则 ID、可复算证据（raw 片段+修复后片段+所用规则）、
  并计入指标；其字符占比超过 2% 才令 accounting incomplete，未超按 declared 处理。
  硬门 `unmapped_raw_span=0` 只对**无声明**的无法映射生效——防止为凑零而编造 span map。
  （2026-07-26 实施裁定：**Phase 0 选严不启用该豁免**——当前实现一律不可映射即 incomplete，
  真实文档遇未注册变换时经 parser 版本升级重建；豁免通道留作 Phase 1 复盘项，届时以真实
  unmapped 数据决定是否启用。）
- canonical span 内的分隔符和空白按固定规则归给相邻叶子或显式 separator exclusion，不允许在句界
  自由丢弃；table cell、行和表头上下文通过 ID mapping 计数，不把重复展示文本再计一遍。

对每个 document generation 必须满足：

`canonical_source_spans = disjoint(eligible_leaf_spans) ∪ disjoint(excluded_leaf_spans)`，且两集合交集为空；
同时 `raw_non_layout_spans = repaired_mapped_raw_spans ∪ repair_deletions`。任一 unmapped、overlap、截断
或无法复算的 repair mapping 都令 accounting incomplete。

### 2.2 Coverage Edge：claim 到最终需求的证据关系

`requirement` 与 `covered_by` 不再作为互斥 disposition。它们是 claim 到 requirement 的关系类型。
一个 claim 可由一个或多个最终 requirements 联合覆盖，因此闭合对象是 `coverage_group`；group 内每条
edge 仍只指向一个稳定 target。单 target 场景也必须生成只含一条 edge 的 group：

```json
{
  "schema": "claim-coverage-group/v1",
  "document_generation_id": "sha256:...",
  "catalog_generation_id": "sha256:...",
  "claim_id": "CLM-...",
  "claim_hash": "sha256:...",
  "coverage_group_id": "CGR-...",
  "source_evidence": {
    "text": "Auxiliary outputs are user-programmable.",
    "claim_start": 0,
    "claim_end": 40,
    "match_method": "verbatim_span"
  },
  "edges": [{
    "edge_id": "CED-...",
    "target_kind": "ai_requirement|atomic_requirement",
    "target_generation_id": "sha256:...",
    "target_requirement_id": "AIR-...",
    "target_fingerprint": "sha256:...",
    "relation": "generated_from|merged_into",
    "produced_evidence": [{
      "field": "description|sub_items|acceptance_criteria|title",
      "item_index": null,
      "start": 0,
      "end": 16,
      "position_basis": "target_field_unicode_codepoints",
      "field_value_hash": "sha256:...",
      "text": "电表输出端口可通过用户程序分配。"
    }]
  }],
  "prefilter": {
    "version": "claim-edge-prefilter-v1",
    "status": "pass|reject|not_applicable",
    "missing_protected_facts": []
  },
  "validation_method": "deterministic_verbatim|independent_semantic|expert",
  "validator_version": "claim-coverage-validator-v1",
  "validator_request_id": "...",
  "status": "proposed|validated|invalid"
}
```

coverage group 只有满足以下全部条件才能成为 `validated`；任一 edge 不能单独关闭 claim：

1. target requirement 已经过现有归一化、漂移护栏、折叠/合并并取得稳定 ID；
2. `source_evidence` 的归一化 span 必须覆盖 claim 的完整规范性内容；仅引用 claim 内的一部分
   不足以关闭 claim，复合句的全部约束必须被覆盖；
3. **verbatim-span 边**：claim 文本必须逐字出现在 target 正式产出字段中；`source_evidence` 与每个
   `produced_evidence` 都保存原文、字段路径及 start/end，只有完整 span 原样保留才可走
   `deterministic_verbatim`；
4. **semantic 边**：`source_evidence` 仍须完整覆盖 claim；每个 `produced_evidence.text` 只要求逐字
   落在当前 target 的正式字段内，并以 `field/item_index/start/end` 精确定位，**不要求它与英文 claim
   逐字相等**。跨语言、改写或多 target 合并的证据并集必须由独立 coverage verifier 判断是否完整蕴含
   claim，并记录 `validation_method=independent_semantic`、validator/version/request ID；
4a. **produced_evidence 定位规则**：`produced_evidence.text` 由提案方给出；`start/end/field_value_hash`
   一律由确定性 locator 在 target 正式字段内归一化定位计算——**禁止模型自报偏移**；定位失败即
   invalid，不得进入 verifier；
5. 进入 semantic verifier 前必须经过 §2.2.1 的 reject-only 确定性预筛；预筛通过只表示“允许复核”，
   不能直接验证 coverage；
6. group 中所有 `target_fingerprint`、target generation 和 requirement review state 必须仍是当前有效值。

独立 verifier 必须是与 proposal/初抽分离的请求，`validator_request_id` 不得等于 proposer request ID，
且输入不携带 proposer 的正负结论或解释。它必须对 target evidence 并集逐项检查主体、情态强度、极性、
数量/单位、条件、例外和适用范围；证据不完整、超时、解析失败、模型分歧或无法判断一律保持
`proposed/invalid + uncertain`，不得降级成已覆盖。

#### 2.2.1 Reject-only 确定性预筛

`CLAIM_EDGE_PREFILTER_VERSION` 管理一个零 LLM、只拒绝不验证的候选门。它复用现有
`extract_codes`、`source_int_baseline`、`produced_ints` 等漂移护栏的 token 提取与规范化规则，但检查
方向相反：现有 drift 防止“产出新增无据事实”，本预筛防止“原 claim 的受保护事实在 target evidence
中丢失”。

- 从完整 claim 提取受保护编码、标准号、数值、单位和受控术语；数值与单位按 canonical pair 比较，
  术语仅使用版本化 alias 映射，不临时猜译。**alias 第一来源必须是当前文档的 per-doc glossary**
  （doc_context/annotation_translations 一类按文档生成的英中映射，版本化并进入预筛指纹），
  全局 KB 只作补充——全局别名覆盖不足导致的 false-reject 计入 `prefilter_reject_rate` 并受 §9
  Phase 0B 评审约束；
- 对 coverage group 的全部 `produced_evidence` 并集做包含检查。任一受保护事实缺失即
  `prefilter.status=reject`，group 标 `invalid`，claim 保持 open，且该 group 不进入 LLM verifier；
- 无受保护事实时标 `not_applicable` 并照常进入 semantic verifier；全部保全时标 `pass`，也仍须完成
  独立语义复核；
- 预筛不得检查或证明完整语义蕴含，不得因 protected facts 全部出现就关闭 claim，也不得用模糊向量
  相似度补救缺失事实；
- 预筛输入只允许当前正式 target 字段内已定位的 `produced_evidence`，不能读取 title/notes 等未申报
  上下文替候选补证。

以下信号永远不足以关闭 claim：共享 `block_id`、`quote_block_ids` 成员关系、anchor 回退、
`section_fallback`、模糊来源块命中、相同章节标题。

初抽调用可以返回按临时 slot 的 coverage proposal 以节省 token，但 proposal 不是终态；稳定 ID
生成后必须重绑并经过上述验证。target 被护栏删除、合并、专家拒绝、补丁替换或内容改变时，所有
旧边立即失效，claim 自动回到 open，直到重新绑定或专家裁决。

### 2.3 Claim Adjudication：负向裁决与未解决状态

每个 claim 的语义分类独立表示：

- `normative`：需求、约束、能力、条件、验收、交付义务；
- `non_normative`：非需求；
- `unknown`：当前无法可靠分类。

分类状态独立表示：`proposed | validated | needs_review | invalid`。

`non_normative` 的受控原因分两组：

1. **结构性原因**：只允许 `empty / separator_only / repeated_page_furniture`，并必须附
   可复算的确定性 `rule_id/version/evidence`。（2026-07-26 与实现对齐：`separator_only`
   依 §2.1.4 的显式分隔符排除纳入；`exact_container_duplicate` 未实现、移出枚举。）
   heading、caption、TOC、普通 noise 和
   `reference_stub` 只是候选标签，不属于 proof-safe 终态。
2. **语义性原因**：`scope_statement / definition / informative / example /
   instrument_only`。初抽模型只能提出 proposal；必须由独立语义复核或专家裁决确认。

模型仅返回一个合法 reason 字符串不构成验证。任何缺证、冲突或验证失败的负向 proposal 均转为
`unknown + needs_review`。默认 10% 抽样审计只用于监测已验证裁决的误判率，不能替代逐 claim 的
终态验证，也不能参与关闭条件。

语义性负向验证按 `CLAIM_NEGATIVE_POLICY_VERSION` 执行原因专属准入：verifier 必须同时给出完整
source locator、该原因成立的证据、未发现规范性义务的检查结果和上下文依赖。**上下文集合规范化**
（同一判据可复算）：同一 `owner_unit_id` 内的全部兄弟 claim 及其父容器映射，写入
`CLAIM_NEGATIVE_POLICY_VERSION`——不定上下文范围的验证视为证据不完整。definition、scope 或
instrument-only 文本一旦约束实现范围、取值、接口、验收或其他 requirement 的解释，就不得作为
non-normative 关闭，而应生成 coverage/context dependency 或保持 uncertain。出现规范性反信号、混合
规范/说明内容、证据不完整或前后文依赖未读取时一律不得验证负向；混合 span 能确定性切分则产生新
catalog generation，不能安全切分则整体保持 eligible/open。负向 verifier 与 proposal 同样必须是分离、
proposal-blind 的请求；独立模型重复原标签不算证据。

### 2.4 Unit Ledger：派生结果，不混合工作流维度

新增 `claim_ledger.jsonl`，每个 catalog 记录恰有一行。终态 resolution 只有：

- `covered`：至少一个当前有效、完整验证的 coverage group；
- `excluded`：validated `non_normative` 或 proof-safe 的 validated 结构性排除，并另记
  `exclusion_kind=semantic|structural`；
- `uncertain`：其余所有情况，包括 proposal、证据失效、冲突和预算耗尽。

reducer 使用以下互斥优先表，不能用“任一终态存在即关闭”的短路实现：

| 当前有效事实 | 派生 resolution |
| --- | --- |
| proof-safe catalog exclusion，且规则版本/证据仍有效 | `excluded(structural)` |
| validated coverage group，且无当前 validated negative | `covered` |
| validated semantic negative，且无当前 validated coverage group | `excluded(semantic)` |
| positive 与 negative 同时有效、并发裁决冲突或任一前置条件失效 | `uncertain` + conflict/invalid reason |
| 只有 proposal、invalid/stale edge、超时或无事实 | `uncertain` |

positive 事实派生 `classification=normative + validated`；validated semantic/structural exclusion 派生
`classification=non_normative + validated`，不能反过来用一个分类字符串制造 closure。同一 base revision
上的并发负向裁决必须经 CAS 拒绝或显式形成 conflict；历史旧边和旧裁决只供审计，不参与当前归约。
分类与 resolution 不一致时记录为 invalid，不得按任一侧单独关闭。

`uncertain` 是显式 open 状态，不是“合法闭合 disposition”。账本“已入账”只说明记录齐全；
只有 `covered|excluded` 才说明语义已解决。

### 2.5 Claim Review Event：专家和自动动作历史

专家改判、定点补抽、target 重绑、审计冲突进入独立 append-only
`claim_review_events.jsonl`。每个事件至少包含：

- `event_seq / event_id / prev_event_hash / event_hash / claim_id / claim_hash /
  document_generation_id / catalog_generation_id / prior_state / next_state`；
- actor、时间、reason、两侧证据、关联 requirement ID/fingerprint；
- route requested/used、模型、prompt/validator version、request ID；
- source generation、expected claim fingerprint 和 `expected_claim_effective_revision` CAS 前置条件。

事件应用必须校验当前 generation、claim fingerprint 与 claim effective revision；不匹配时拒绝并要求刷新。
`event_seq` 在跨进程锁内单调分配，事件 hash 链保证有效前缀可复算，不能仅靠文件 mtime 判断新旧。现有
`decide_trace.jsonl` 只记录 agent 对账本采取的动作摘要，不承载逐 claim 事实，避免破坏其封闭 schema。

requirement 级专家裁决仍是 target 有效性的权威来源：A 轨读取 `review_states.jsonl`，B 轨读取
`ai_review_states.jsonl`。具体语义固定为：A 轨以 `review_states.jsonl` 当前 state 及内嵌 history 为权威，
`review_state_events.jsonl` 只是投影；B 轨以 `ai_review_states.jsonl` 中每个 `ai_req_id` 的最后一条有效
且与当前 target ID/fingerprint 匹配的记录为权威。完全没有 review row 不等于 rejected；但存在无
fingerprint、匹配歧义或 `needs_reconfirmation` 的旧 row 时，target review eligibility 为 unknown，不能用
它关闭 claim。adapter 必须由声明的 `target_kind` 选择，禁止根据 `AIR-` 等 ID 外形猜轨道。
`CLAIM_REVIEW_BRIDGE_VERSION` 将 requirement 的 reject、内容变化和 target
替换幂等投影为 `target_invalidated`，并把后续恢复为非 rejected 状态投影为 `target_reactivated`；幂等键
至少包含 source store、源 review revision、target fingerprint、edge/claim ID 和 bridge version。reducer
只接受 source revision 仍等于当前 authority 的投影，旧 revision 的 invalidation/reactivation 永远只供审计。
投影是审计便利，不是正确性单点：effective reducer 每次 fold 都
必须直接重读当前 requirement set 及其权威 review state；target 已 rejected、缺失或 fingerprint 不符时，
即使 claim event 追加失败也立即使相关 group 失效并重开 claim，后台 reconciliation 再补投影事件。
target 恢复后必须重新 reconcile；只有 claim/target fingerprint、evidence locator 和 validator versions
全部未变时才可显式复用旧验证。`accepted`、`expert_pending` 等非 rejected 状态只表示没有 rejection
阻断，不会创建 edge、验证 coverage，也不引入“所有 requirement 必须先经专家 accepted”的新门。

两种 authority adapter 都必须导出可复算的 `target_review_revision`。所有可能改变 target 有效性的专家
写入（含 Vue API、批量/HTML import 和自动迁移）必须携带 `expected_target_fingerprint` 与
`expected_target_review_revision` 并在同一锁内 CAS；source/subject fingerprint 只能证明内容代际，不能
替代 prior-review CAS。陈旧写返回 409 及当前 revision，不得 last-write-wins。旧格式 HTML 裁决缺少上述
token 时只能导入为 `needs_reconfirmation/proposal`，不能成为 ledger authority。现有 A/B 写入入口尚无
完整 review-revision CAS，这属于 Phase 1.5 启用 claim mutation 前的必改项，不能用 claim event CAS
代替 requirement authority 自身的并发保护。fold 必须按固定锁顺序取得一致快照，或在前后复验 authority
revision 并于变化时重试；混合两个 review 代际的结果不得产生 READY。

proof-safe 结构排除若被专家或审计证伪，必须使对应 rule/catalog generation 失效并重建为 eligible claim；
不能只追加一个 ledger event，让错误 catalog 行继续留在文档分区里。

## 3. 抽取与账本数据流

catalog 是跨轨源文账本；coverage target 通过显式 adapter 区分：

- B 轨 `target_kind=ai_requirement`：目标来自 `ai_requirements.jsonl`，权威专家状态来自
  `ai_review_states.jsonl`；
- A 轨 `target_kind=atomic_requirement`：目标来自 `atomic_requirements.jsonl`，权威专家状态来自
  `review_states.jsonl`。

run 必须声明 `delivery_track`，target ID/fingerprint/review adapter 必须进入 generation meta。Phase 0B
先验证本问题所在的 B 轨；在 A 轨 adapter 完成同等冻结回归前，不得把 B 轨 Phase 2 通过解释为 A 轨
也已切换。每个 B 轨单元按以下顺序处理：

1. 解析后、LLM 前生成 catalog，校验叶子保全与唯一 owner；
2. 初抽 requirements；
3. 执行现有 normalize、来源护栏、漂移护栏、fold/merge，并分配稳定 requirement ID；
4. 对当前 claim 与最终 requirements 批量生成 coverage group，先执行 reject-only 预筛，再由独立
   verifier 验证剩余 semantic groups 和负向 proposal；
5. 所有 `uncertain` claim 进入定向自检；焦点由 claim text/locator 提供，不再经过
   `requirement_like` 候选过滤；
6. 自检新增/并入内容再次经过同一套护栏、ID 和 coverage 校验；
7. 循环直到 resolution 全部解决、无新增，或预算/轮数耗尽；
8. 应用当前 supplements、合规补充和专家有效状态后，做一次 target referential reconciliation；
9. 写 generation 文件并最后提交 generation meta。

同调用扩展字段只是成本优化，不是正确性边界。账本必须针对**护栏后的最终有效需求集合**验证，
不能把 raw LLM slot 当成最终 requirement identity。

## 4. 状态机与成功语义

### 4.1 四个正交维度

单元与文档均分别记录：

- `extraction_status = success | partial | failed`；
- `accounting_status = complete | incomplete`；
- `resolution_status = resolved | open`；
- `termination_reason = converged | budget_exhausted | round_cap | llm_error |
  validation_error | stalled_open | cancelled`。

`route_mode=llm|stub` 和 `scope=full|sample` 是独立 provenance，不塞进 extraction outcome。

定义：

- `accounting_status=complete`：catalog conservation 通过，且每个 catalog row 都有唯一 ledger row；
- `resolution_status=resolved`：所有 eligible claim 为 `covered|excluded`，不存在 uncertain、失效 target
  或待审 proposal；
- `unit_ledger_ready=true`：该单元 `extraction_status=success`、accounting complete、resolution resolved，
  且 effective revision 与当前 target/review state 一致；`partial` 永远不满足；
- `document_ready=true`：`scope=full`、所有应处理单元均 unit_ledger_ready、文档级 accounting 覆盖包括
  `owner_unit_id=null` 的结构性排除行、当前 effective ledger 已提交、parse audit 通过、无
  `parse_incomplete` 且无阻塞澄清项。sample、partial、stub 路由均不得 READY。

预算耗尽、轮数触顶和“零新增但仍有 uncertain”只能得到
`accounting_status=complete + resolution_status=open`；最后一种显式记录
`termination_reason=stalled_open`，不得标成功闭合。

### 4.2 失败与部分产物

- requirements 抽取成功但 ledger 调用失败时，保留并独立缓存已有 requirements；不得把它们清空，
  也不得把 ledger 错误塞进现有 `failed_sections`。
- `failed_sections` 只表示需求抽取本身失败；新增
  `open_ledger_units / uncertain_claims / invalid_coverage_edges / ledger_failed_calls`。
- requirements cache 命中而 ledger 缺失/过期时，执行 ledger-only rebuild，不重发初抽。
- partial requirements 可以供人工查看，但所有下游产物必须携带 `incomplete_inputs=true`；
  readiness 不得为 READY。
- `route_mode=stub` 可以生成 catalog，但不得制造模型 proposal 或把空需求标成已验证；其 eligible
  claims 保持 uncertain，`extraction_status` 记录实际 stub 产物结果，route provenance 如实记录。

## 5. 持久化与同代提交

### 5.1 文件职责

- `claim_catalog.jsonl`：当前 generation 的不可变 catalog 原子快照；
- `claim_ledger.jsonl`：当前 generation 的不可变基础 ledger 原子快照；
- `claim_ledger.partial.json`：运行中进度、attempt、open claims；不是权威终态；
- `claim_review_events.jsonl`：append-only 专家/自动裁决事件；
- `claim_generation.meta.json`：权威提交指针，记录 run ID、document/catalog generation ID、
  声明轨道的 target requirements、requirements meta、catalog、base ledger 的 SHA-256，以及
  schema/producer versions 和状态计数；
- `claim_effective_ledger.jsonl` / `claim_effective.meta.json`：可重建的当前归约快照及其提交指针。
  文档级 revision 定义为
  `sha256(base_generation_id | event_seq | event_prefix_hash | target_set_hash |
  requirement_review_state_hash | reducer_version)`；每行另有
  `claim_effective_revision = sha256(base_claim_row_hash | ordered_relevant_event_hashes |
  linked_target_fingerprints | linked_target_review_revisions | reducer_version)`。claim 写入只 CAS 后者，
  无关 requirement/claim 的事件不得使该 claim 的 revision 改变。

### 5.2 提交协议

1. 在 extraction operation lock 内写各 `.tmp` 文件并 fsync；
2. 对每个快照执行带 `PermissionError` 重试的原子替换；
3. 重新读取并计算最终文件 hash；
4. 最后原子替换 `claim_generation.meta.json`；
5. 读侧只接受 meta 指向且 hash 全部匹配的一代；meta 缺失或 hash 不符即视为 incomplete/stale。

初代 base 提交成功后，以及每次有效 claim/review revision 变化后，在 ledger materialization lock 内用同样
的 tmp+fsync+`PermissionError` retry 协议重建 `claim_effective_ledger.jsonl`，重新读取 hash，最后原子替换
`claim_effective.meta.json`。读侧还须重算其 event prefix、target set 和 review-state revisions；任一已前进
即把 materialization 视为 stale 并重试，不能返回刚写完但已落后一代的 READY。

`claim_ledger.jsonl` 不是 append log。“增量落盘”只发生在 partial 文件；专家历史只进入 event log。
event log 沿用跨进程锁、append+flush+fsync、torn-tail 恢复，并通过 generation/fingerprint 前置条件
规避陈旧裁决。

读侧先验证 committed base ledger，再读取完整有效事件前缀、当前 target set 和两套 requirement review
authority，按序归并得到 `effective ledger`；每次 fold 都重验 target existence/fingerprint/review status。
materialized effective snapshot 只是带 revision 的缓存：revision 不等于当前输入时必须重建，不能继续
用于 readiness。报表、队列、readiness 和导出只消费当前 effective ledger。事件不得直接改写 base
snapshot，也不得越过 generation/fingerprint/CAS 前置条件。

## 6. 现有通道的系统性改造

### 6.1 ai_extract / extract_units

- ai-extract 输入增加 `table_items.jsonl`；抽取单元由 claim spans 组装并携带精确 claim IDs；
- 超长章节拆分不得复制整章 claim 所有权；
- 自检输入改为 ledger open claims，早停改为 resolution resolved；
- `_prepare_requirement_rows` 分配稳定 ID 后再生成/验证 coverage group；
- supplements、合规补充、fold、专家拒绝后必须重做 target reconciliation。

### 6.2 omission 与 agent loop

新增 claim 级动作契约，至少包含：

`claim_id / parent_block_id / locator / claim_source_fingerprint /
document_generation_id / catalog_generation_id / expected_ledger_state`。

- 候选直接来自 ledger 的 uncertain/invalid，不再调用 requirement_like coverage denominator 复核；
- `block_id` 只用于找到上下文和展示；list/table claim 必须按精确 locator 聚焦；
- `resolved` 不允许外部直接写入，只有 exact claim 重新验证成 covered/excluded 后由 reducer 派生；
- Phase 1 零 LLM agent 只能排队 `needs_extraction`，不得把排队描述成已抽取；
- 旧 `omission_states.jsonl` 可映射到 whole-block claim 作兼容展示，但不能冒充块内全部子 claim。

### 6.3 coverage / clarification / readiness

- `merged_consistency` 分开报告 inventory accounted、verified covered、verified excluded、open、failed；
- clarification 的 TIER_GAP 输入改为 uncertain claims，并保留 exact claim locator；
- `non_normative` 只有 validated 后才从 unresolved 清单消解；
- requirement target 被拒绝或 fingerprint 漂移时，关联 claim 自动重新出现；
- `is_coverage_candidate` 不再使用“是否有任意 disposition”，而由 catalog eligibility 与 ledger
  resolution 决定。

### 6.4 API、导出与 Vue3 UI

- API 下发 claim locator、resolution、validation method、target ID/fingerprint 和 review events；
- `quote_block_ids` 继续服务蓝色证据区展示，但不得作为后端 closure 依据；
- Vue3 批注视图展示“已验证覆盖 / 已验证排除 / 待处理 / 失效证据”，支持 claim 级裁决；
- DOCX/PDF 批注导出按 claim span/row 定位；不能只给整块标签；
- `gui/` PySide6 保持冻结。

### 6.5 provenance

- claim 事实与裁决写入新 ledger/event schema；
- `decide_trace.jsonl` 仅记录 agent iteration 对 claim queue 的输入摘要、动作和结果；
- 所有 LLM proposal/validator 记录真实 route、模型、request ID 和版本；stub 永不标 LLM。

## 7. 缓存、run manifest 与血缘

独立版本常量至少包括：

- `CLAIM_CATALOG_VERSION`：切分、locator、catalog schema；
- `CLAIM_UNIT_PACKING_VERSION`：claim 到唯一 owner unit 的分配与打包；
- `CLAIM_LEDGER_SCHEMA_VERSION`：base/effective ledger 与 event schema；
- `CLAIM_LEDGER_PROMPT_VERSION`：coverage/negative proposal prompt；
- `CLAIM_EDGE_PREFILTER_VERSION`：受保护事实抽取、canonicalization、术语 alias 与 reject-only 规则；
- `CLAIM_COVERAGE_VALIDATOR_VERSION`：正向边验证；
- `CLAIM_NEGATIVE_POLICY_VERSION`：负向原因准入、反信号和 context dependency 规则；
- `CLAIM_NEGATIVE_VALIDATOR_VERSION`：负向原因验证；
- `CLAIM_REVIEW_BRIDGE_VERSION`：requirement review state 到 claim invalidation 的幂等投影；
- `CLAIM_REDUCER_VERSION`：effective revision、冲突优先表和 readiness 派生；
- `CLAIM_QUEUE_VERSION`：claim 级补抽动作契约；
- `CLAIM_AUDIT_POLICY_VERSION`：抽样审计策略。

版本必须进入其实际影响层级，不能把所有 ledger 版本粗暴塞进 section extraction fingerprint：

| 缓存/产物层 | 必须包含的主要依赖 | 不应连带失效 |
| --- | --- | --- |
| catalog | document generation、text repair、实际 segmentation/locator 行为版本 | parser 原始产物 |
| initial requirements extraction | canonical unit prompt hash、packing、现有 extraction prompt/guards/model config | prefilter/validator/reducer/bridge/audit 变化 |
| coverage validation | catalog generation、claim hash、target ID/content fingerprint、produced-evidence locator、prefilter/prompt/validator/model versions | requirements extraction cache |
| effective ledger | base ledger hash、该 claim 的有效 event hashes、linked target review revisions、schema/bridge/reducer | requirements 与 coverage proposal cache |
| claim queue | claim effective revision、`CLAIM_QUEUE_VERSION` | catalog/requirements/base ledger |
| audit | document effective revision、`CLAIM_AUDIT_POLICY_VERSION` | extraction 与 validated group 本身 |

`stage_producer("ai-extract")` 只表示 requirements extraction producer；catalog、coverage validation 和
effective reducer 使用独立 component producer/revision，并写入 generation/effective meta。各层版本进入
对应的 `STAGE_IMPLEMENTATION_REVISIONS` 和 downstream fingerprint，但只失效受影响层。
`CLAIM_LEDGER_SCHEMA_VERSION`、prefilter、正负 validator/policy、bridge、reducer、queue、audit 的升级均
不得进入 initial extraction cache key；它们最多触发 ledger-only rebuild/revalidation，新增初抽 LLM 调用
必须为 0。

`desktop_tasks.STAGE_INPUTS["ai-extract"]` 增加 `table_items.jsonl`；
`STAGE_REQUIRED_OUTPUTS["ai-extract"]` 增加 catalog、base/effective ledger 及两份 meta。functional
synthesis 与 requirements analysis 继续由 target requirements/generation 驱动，纯 ledger event/schema
变化不得令其重跑；claim queue、clarification、readiness、API 和 annotation export 等账本消费者增加
effective meta/review events。补抽若实际改变 requirements，其 target hash 按现有依赖自然使语义下游失效。
影响处置的环境变量（含 audit ratio、ledger verifier 开关/轮数）进入对应 ledger/audit fingerprint，而
不是无差别污染 requirements section cache。

cache hit 同时校验 requirement cache 与 ledger generation。只有 requirements 命中时允许 ledger-only
重建；只有 ledger 命中但 target requirements fingerprint 不一致时，ledger 必须失效。

run manifest 的阶段执行状态与 ledger readiness 分开记录：

- generation 文件成功提交只表示本次阶段执行有可审计产物，不自动表示 `document_ready`；
- `extraction_status=partial|failed` 时整阶段不可复用，但已成功单元继续走 section cache，只重跑失败单元；
- `extraction_status=success + accounting_status=complete + resolution_status=open` 时可复用
  requirements cache，但 skipped payload、API 和所有下游必须继续暴露 open 状态，并通过 claim queue
  或 ledger-only retry 处理，绝不能因 stage 被跳过而显示 READY；
- `stage_is_reusable` 必须额外验证 generation meta 及其文件哈希，不能只检查文件存在。

## 8. 成本纪律

- deterministic verbatim group 和 proof-safe 结构性排除走零 LLM；跨语言/改写 coverage group 先过
  reject-only 预筛，只有 `pass|not_applicable` 才进入 semantic verifier。预筛拒绝的 group 直接 invalid/open，
  不消耗 verifier token。
- coverage verifier 按单元批量处理预筛后候选，并尽量复用现有独立 verify 的请求批次；不得逐 claim
  各发一次请求。请求融合不能破坏 proposer/validator 分离，也不能把未复核 claim 顺带标 validated。
- 只重验 open、target/evidence/review revision 变化，或 prefilter/policy/validator/reducer version 变化的
  claims；已验证且全部前置条件未变的 group 才可复用。
- Phase 0 的成本线为**用户已批准（2026-07-26）：LLM 调用增量 ≤ 25%、token 增量 ≤ 65%**
  （`claim-cost-policy-v3-user-approved`；用户原话："多一点，但是效果好，我也接受的"）。
  统计以相同文档、route、模型和 extraction 配置的无账本基线为分母。超线时优先合批、
  ledger-only cache 和增量重验；不得通过放宽负向验证或恢复块级覆盖来满足成本线。
- 成本仍超线时保持 shadow 模式，不切换生产完整性门控。

## 9. 分阶段落地

### Phase 0A：Claim Catalog 保全探针

旁路生成 catalog，不调用 LLM、不改变生产输出。至少覆盖：

- test5/test10/test11 已知遗漏的机器本地对账样本；
- 多句同块、清单并块、短清单行；
- 大表格与超过 5000 字符的 table block；
- 章节超长拆分、sample 模式；
- heading/noise/TOC 误分类复核样本。

硬门：unmapped source/raw span=0、overlapping leaf span=0、orphan claim=0、multi-owner claim=0、
父子重复=0、`parse_incomplete=0`。source conservation 严格按 §2.1.4 的两个集合方程计算。

### Phase 0B：Shadow Ledger 探针

对当前最终 requirements 旁路生成 coverage groups、负向裁决和 ledger，不影响自检或 readiness。
Phase 0B 同时负责建立 `golden_sets/claim_ledger_v1/` 冻结回归集，至少包含 manifest、匿名/合成输入、
claim 级期望 catalog/eligibility/resolution 和人工裁决依据。仓内样本覆盖可编程能力等价句、同块部分覆盖、
水印/页码、无引导句清单、正常表格与 table fallback；机器本地 test5/test10/test11 仅作验收，客户 wording
不进仓。
manifest 还须冻结一个不参与 prompt/阈值调优的 human-adjudicated held-out partition。baseline 变更必须逐项
说明并记录到 `CLAUDE.md`，不得用刷新期望值掩盖漂移。

输出：

- accounted / covered / excluded / uncertain / invalid edge 分布；
- semantic negative 独立复核通过率与审计分歧率；
- target 失效重开数量；
- `deterministic_verbatim_ratio / prefilter_reject_rate / semantic_verifier_candidate_ratio`；
- `avg_verifier_calls_per_unit / verifier_tokens_per_claim` 及相对无账本基线的调用/token 增量；
- `multi_claim_quote_count / sibling_claim_open_rate`，以及引句合并型需求的 resolution path 分布
  （独立 `merged_into` group、补抽后覆盖、专家裁决、仍 open）；同一 requirement 可分别覆盖多个兄弟
  claims，但每个 sibling 的 group 必须独立验证，不能共享一次 closure；
- test5/test10/test11 对账：已知遗漏 claim 必须为 covered 或 uncertain，绝不能靠同块其他需求、anchor
  fallback 或未验证 informative 关闭。

### Phase 1：生产双写，不切门控

**机制本体在本阶段建成，全部只读、零 mutation**（v2.2 澄清）：

- 正式写 catalog、base/effective ledger、generation/effective meta；
- 接入 claim 级只读 API/UI/导出、effective reducer 和 review-state bridge——含只读投影
  （requirement review authority → claim review event）、事件驱动 effective fold，以及支撑
  fold 所必需的 WAL/崩溃恢复机制本体；
- claim queue 与定点补抽在本阶段只生成 shadow/dry-run proposal，不修改 requirements 或 claim 终态；
  旧覆盖报表继续作为兼容字段；
- 新旧 coverage 并列展示，生产 readiness 暂不依赖 ledger。

### Phase 1.5：闭环验证与启用 mutation

**Phase 1 建成的机制在本阶段完成闭环验证，验证通过前仍不启用任何 mutation**（v2.2 澄清）：

- 端到端验证 target invalidation、专家拒绝、supplement replay 后的自动重开；
- event hash/CAS、requirement-review bridge 补偿和 authoritative-state 实时 fold 验证通过后，才启用
  claim 级专家写入、claim queue 与定点补抽对生产 requirements 的 mutation——**mutation 唯一通道为
  现有 `targeted_reextract`**（前置条件指纹 + 补丁形态），不得长出第二条改写 requirements 的路径；
- A/B 两轨 requirement 写入口补齐 review-revision CAS（总纲 §2.5 已定其为启用 claim mutation 前的
  必改项）；
- ledger-only cache rebuild；
- 崩溃、并发、torn partial、Windows replace retry 全部验证；
- downstream incomplete_inputs 贯通。

### Phase 2：切换完整性门控

只有以下条件同时成立才切换：

1. 相同 catalog/prefilter/validator/reducer 版本在至少 3 次连续完整 shadow run 中通过；合并样本不少于
   10 份代表性文档和 500 个 eligible claims，catalog conservation 硬门始终为零错误；
2. 冻结回归集中的已知遗漏召回 100%；
3. held-out partition 至少分别含 150 个 semantic positive、150 个 semantic-negative candidate 和
   150 个 structural-exclusion candidate；positive 中至少 75 个为跨语言/改写。三类 terminal false
   closure 均为 0，且各自双侧 95% Wilson 上界不超过 2.5%；
4. human adjudication 的总 verifier/audit disagreement 点估计不超过 5%，95% Wilson 上界不超过 8%；
   所有 semantic negative 终态均有独立复核或专家证据；
5. stale/rejected target、missing ledger、旧 effective revision、hash mismatch、partial/sample/stub、
   budget exhaustion 和 stalled_open 均无法得到 READY；
6. 三次 shadow run 均满足 §8 成本线，或经用户基于 §9 实测指标明确批准新成本线；
7. 声明的 `delivery_track` adapter 已通过同一套门；B 轨通过不得替 A 轨背书；
8. 全量 unittest、golden 6/6、Vue tests/build 通过。

切换后：`requirement_like` 只保留排序/预算和未切换轨道的兼容用途；已切换 `delivery_track` 的
coverage、self-check、遗漏告警和 readiness 全部以当前 effective revision 的 ledger 为准。

## 10. 指标口径

禁止再用一个“命题级覆盖率”混合不同事实。必须分别报告：

- `catalog_total_count = structural_excluded_count + eligible_claim_count`；
- `eligible_claim_count = covered_count + semantic_excluded_count + uncertain_count`；
- `inventory_accounted_ratio`：有 ledger row 的 catalog 数 / catalog 总数；
- `verified_coverage_ratio`：covered / eligible claims；
- `verified_semantic_exclusion_ratio`：semantic excluded / eligible claims；
- `eligible_resolution_ratio`：`(covered + semantic excluded) / eligible claims`，与 §2.4 的 effective
  resolution 派生使用同一分区；
- `structural_exclusion_ratio`：proof-safe structural excluded / catalog 总数；
- `verified_exclusion_ratio`：`(structural excluded + semantic excluded) / catalog 总数`；
- `uncertain_count`：所有 open claims；
- `invalid_group_count / invalid_edge_count`：target、证据或 group 验证失效；
- `failed_extraction_units` 与 `open_ledger_units`；
- `negative_validation_disagreement_rate`；
- `audit_disagreement_rate`；
- `catalog_orphan_count / multi_owner_count / duplicate_leaf_count`；
- `unmapped_source_span_count / unmapped_raw_span_count / overlapping_leaf_span_count`；
- §9 的 verbatim/prefilter/semantic-candidate/call/token 和 sibling-claim 指标。

`non_normative` 不计入 verified coverage；它单列为 verified exclusion。uncertain 率不是越低越好，
不得用“uncertain <= 5%”作为质量门，因为模型可通过滥判 non_normative 人为压低它。
所有 ratio 必须同时输出 numerator/denominator；分母为 0 时 ratio 输出 `null` 而不是 0 或 100%。全结构性
排除文档可在其他 READY 条件满足时 resolved，但其 eligible coverage/resolution ratios 均为 `null`。

## 11. 必须覆盖的测试矩阵

后端测试必须是 `unittest.TestCase`，不得写模块级 pytest 风格函数。

1. **Catalog conservation**：同代同 ID、跨代 claim ref 不混用、raw-to-repaired 方程、list 首行退化、
   父容器不重复、排除项 proof-safe、claim 恰好一个 owner。
2. **Table fallback**：无 table item 时按行组/字符窗生成多个 claim；5000 字符截断或 parser incomplete
   必须阻断，不允许整块单 claim 闭合。
3. **同块与多 target 覆盖**：句 B 被引用时句 A 仍 open；共享 block/quote/anchor 不关闭兄弟 claim；
   compound claim 只有在 coverage group 的 target evidence 并集完整验证后才 covered。
4. **跨语言证据契约**：semantic edge 的 source span 覆盖完整 claim，target-side text/field/index/offset
   可复算；不要求中英文逐字相等；verbatim edge 必须真的逐字命中。
5. **Reject-only 预筛**：编码、标准号、数值+单位、受控术语任一丢失时零 LLM reject；pass 和
   not_applicable 均不能直接 validated；验证提取方向与现有 drift guard 相反。
6. **独立验证**：proposer/validator request 分离且 proposal-blind；主体、情态、极性、数量、条件、例外、
   范围任一缺失、timeout 或 disagreement 均保持 uncertain。
7. **负向逃生**：真实需求被提议为 informative/definition/heading 时保持 uncertain；混合 span 不得整体
   排除；只有原因专属证据或专家裁决可关闭。
8. **状态机**：partial、sample、stub、budget exhausted、round cap、ledger LLM error、stalled_open、
   ownerless catalog 未入账均非 READY。
9. **部分产物**：ledger-only 失败保留有效 requirements，且不计入 `failed_sections`。
10. **claim queue**：`requirement_like=False` 的已知可编程输出 claim 可入队；table/list claim 按 locator
    补抽；无 exact claim 后置验证不得 resolved；Phase 1 dry-run 不修改生产 target。
11. **review bridge/target 失效**：A/B 权威 review store 的拒绝、merge、supplement、fingerprint 改变均
    自动重开；投影 event 追加失败仍重开；reject 改回非 rejected 触发 reactivation/reconcile，但不自动
    covered；陈旧 API/HTML CAS 写入被拒绝，旧 HTML 只能 needs_reconfirmation；无关 requirement 裁决不
    改变该 claim 的 effective revision。
12. **代际/effective 提交**：missing ledger、旧 meta/event prefix/review hash、hash mismatch、崩溃中断、
    torn partial、并发写均被拒绝复用。
13. **缓存**：catalog/packing/extraction/validation/reducer/queue/audit 版本只失效正确层；ledger schema、
    prefilter、validator、bridge、reducer 或 audit bump 可 ledger-only rebuild/revalidation，初抽 LLM 调用为 0。
14. **路由与轨道**：stub 不伪造 reviewed；sample 只报告 sample scope；route provenance 保真；A/B target
    adapter 不按 ID 形状猜测，B 轨通过不令 A 轨 READY。
15. **规模**：固定 500-block 合成夹具预热后运行 5 次，catalog 生成 p50 不超过 1.0 秒，catalog+base
    ledger snapshot 总大小不超过 10 MiB；超线必须显式更新性能 baseline/version，不能静默放宽。
16. **端到端**：test5/test10/test11 的同源复跑不论初抽方差，已知遗漏 claim 最终只能 covered 或显式 uncertain，
    不得静默消失；冻结集覆盖 siblings、水印/页码、list/table 和 protected-fact 丢失。

真实客户 wording 只用于机器本地验收，不进仓。仓内回归使用合成等价句和结构夹具。

## 12. 代码范围与所有权边界

Phase 0/1 的实施计划可涉及：

- 新模块：`claim_catalog.py`、`claim_ledger.py`、`claim_review_actions.py` 及 schema；
- 抽取：`ai_extract.py`、`extract_units.py`、`merged_consistency.py`；
- 状态与 agent：`omission_actions.py` 兼容适配、`agent_state.py`、`agent_tools.py`、
  `clarification_report.py`；
- 血缘：`desktop_tasks.py`、必要的 API artifact freshness/memo 逻辑；
- 消费端：`api_server.py`、`doc_annotation_export.py`、`ui/` Vue3 类型/视图/测试；
- 对应 `tests/`、文档和 `CLAUDE.md` 里程碑记录。

不得扩展 `gui/` PySide6，不改 structured fields 的确定性 join 纪律，不改 golden 基线，不提交客户文档、
Blue Book PDF、公司模板或 API key。每个 Phase 在独立 `codex/*` worktree 实施，用户决定是否合并；
未经要求不 commit、不 push。

## 13. 明确不做

- 不用情态词/动词词表作为完整性分母；
- 不用向量相似度、共享块或 section fallback 自动关闭 claim；
- 不让初抽模型单方面写 terminal non_normative；
- 不把 10% 抽样审计冒充逐项验证；
- 不自动迁移不同 document generation 的专家裁决；
- 不因 ledger 失败删除已经通过护栏的 requirements；
- 不在 Phase 0/1 双写验证完成前切换生产 readiness。

## 14. 审核冻结项

审核人确认本稿时同时确认：

1. 坐标采用 versioned leaf claim catalog，父容器不进分母；
2. `requirement/covered_by` 改为 coverage group 内的 target edge，不再与 uncertain/non_requirement 混为
   单枚举，任一 edge 不能独自关闭 compound claim；
3. 块级字段只定位，不作 closure 证据；
4. 语义性负向结论逐项独立复核或专家裁决，10% 审计只做监测；
5. accounting、resolution、extraction、termination 四维状态分开；
6. claim queue 替代“omission 状态机原样复用”；
7. reject-only protected-fact prefilter 只拦截候选，跨语言 semantic group 仍须独立验证；
8. requirement review authority 与 claim event 投影分离，reject/reactivate、CAS 和 effective revision
   规则不可省略；
9. catalog/requirements/base ledger 通过 generation meta 同代提交，effective ledger 绑定事件与 review
   revision；
10. Phase 0A/0B -> Phase 1 只读双写 -> Phase 1.5 闭环/启用 mutation -> Phase 2 切门控的顺序不可跳过。

本规格复核通过后，下一步只编写 Phase 0A/0B 的详细 TDD 实施计划；不直接一次性铺开 Phase 1/2。
