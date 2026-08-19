# Requirement Atomizer 结构与 Token 成本完整变更方案

**日期：** 2026-08-16  
**适用代码基线：** `codex/table-translation-structure` 当前工作树  
**方案性质：** 实施计划，不包含本轮代码修改  
**目标读者：** 按里程碑实际修改仓库的开发人员

## 1. 目标

本方案解决四类问题：

1. 消除普通运行中 A/B 两条业务轨道和翻译阶段的无意重复付费。
2. 让每一次真实 LLM 调用都可规划、可计量、可封顶、可追踪。
3. 缩小缓存失效范围，避免确定性后处理变化触发无必要的 provider 重调。
4. 收敛编排、付费缓存、LLM 调度和文件写入等横切基础设施。

最终目标不是简单减少调用数，而是在保持以下红线的前提下降本：

- anti-hallucination 规则不放松；
- structured fields 仍只允许确定性 join；
- stub、partial、failed 不伪装成真实 LLM 成功结果；
- provenance、source anchor 和 route_requested 不失真；
- 缓存不得让旧结果绕过新确定性 guard；
- 结果包路径全部经过 `governed_artifact_path` 或 `package_artifact_path`；
- 共享状态继续使用跨进程锁、fsync、原子替换和 Windows retry。

## 2. 非目标

本轮治理不直接做以下修改：

1. 不直接降低 `ai_extract` self-check 或 verify 轮数。
2. 不把当前 tool-loop review 强制改成 single-shot batch。
3. 不一次性迁移全部顶层模块到 package。
4. 不把五套评审 authority 强行合并成同一个状态机。
5. 不更改 golden baseline，除非行为版本变化已获得逐项批准。
6. 不把 `clause_family` 在没有真实 truth-set 结果时直接翻成默认。

## 3. 当前基线事实

### 3.1 当前默认付费路径

在用户启用 LLM、UI 使用现有默认阶段配置、缓存未命中的情况下：

```text
atomize                                                    确定性
  -> A轨 llm-review                                       付费
  -> B轨 functional-extract                               付费
  -> A轨 assemble/spec_enrich                             付费
  -> B轨 requirements-analysis                            默认确定性
  -> full-translation                                     付费
  -> export-annotation-html                               通常复用翻译缓存；
                                                          缓存缺失时可生成批注翻译并付费
```

必须保留两个校正：

- `RATOMIZER_REQUIREMENTS_ANALYSIS_ENRICH=0`，所以 requirements analysis 的 LLM 富化默认关闭；显式开启后才成为付费阶段。
- `RATOMIZER_CONTEXT_PACK_STRATEGY=legacy`，所以 functional extract 默认是文档级 prompt，每条款截取 4,000 字符；`clause_family` 是 opt-in。

### 3.2 翻译控制的隐藏路径

当前不仅 `full-translation` 会调用翻译：

- `full_translation.run_full_translation()` 调用 `generate_annotation_translations()` 翻译全文单元；
- `export_annotation_bundle()` 也会调用 `generate_annotation_translations()`；当 route 为真实 LLM 且 sidecar 缺少 marker 翻译时，它会发起调用。

因此只增加 `fullTranslation=false` 不能保证零翻译调用。必须统一控制全文翻译和批注 marker 翻译。

### 3.3 当前主要缓存问题

- `functional_extract_cache` 外围是整文档 fingerprint 和整文档 payload。
- `stage_input_fingerprint` 的 `llm` 字段对所有阶段注入同一组环境变量。
- `spec_enrich`、`ai_extract` 仍存在裸 append 付费缓存。
- 多数付费缓存保存 guard 后结果，request-affecting 与 postprocess-only 版本没有明确分层。

## 4. 总体实施顺序

严格按以下顺序实施：

```text
M0  成本基线与契约冻结
M1  Pipeline Profile + Translation Mode + Budget Observe
M2  PipelinePlan 单一计划源 + Result Package 接线
M3  阶段级 config dependencies
M4  PaidCacheStore + 两层缓存底座
M5  Functional Extract 包级缓存与增量合并
M6  LLMJobRunner 与统一成本遥测
M7  Review/IO 基础设施收敛
M8  Package 化与大型文件拆分
```

M0-M3 用于立即停止无意成本；M4-M6 减少开发迭代与失败恢复的重复付费；M7-M8 解决长期结构复杂度。

## 5. 目标运行模型

### 5.1 Pipeline Profile

新增枚举：

```text
legacy_combined   当前兼容链，用于旧用户迁移和紧急回滚
a_track           DLMS profile / 结构化标准
b_track           prose / tender / 软件需求成文
hybrid_audit      显式双轨交叉审计
```

第一版不要实现自动静默分类。可以给出推荐 Profile，但真实付费运行前必须有明确的 resolved profile。

Profile 与阶段关系：

| 阶段 | legacy_combined | a_track | b_track | hybrid_audit |
|---|---:|---:|---:|---:|
| atomize | 是 | 是 | 是 | 是 |
| llm-review | 是 | 是 | 否 | 是 |
| functional-extract | 是 | 否 | 是 | 是 |
| assemble/spec_enrich | 是 | 是 | 否 | 是 |
| requirements-analysis | 是 | 否 | 是 | 是 |
| template-write | 配置决定 | 否 | 配置决定 | 配置决定 |
| clarification-report | 是 | 否 | 是 | 是 |
| compose | 是 | 是 | 是 | 是 |
| export-annotation-html | 独立交付开关 | 独立交付开关 | 独立交付开关 | 独立交付开关 |

说明：`requirements-analysis` 阶段可以运行，但只有 enrichment 开关开启时才标为 paid。

### 5.2 Translation Mode

使用三态枚举替代单一 `fullTranslation` 布尔值：

```text
off       不生成任何新翻译；允许确定性读取/迁移已有安全缓存
markers   仅生成批注 marker 翻译
full      运行全文翻译；批注导出只复用全文翻译 sidecar
```

执行契约：

| 模式 | full-translation | export annotation 生成 marker 翻译 |
|---|---:|---:|
| off | 不进入计划 | 否 |
| markers | 不进入计划 | 是 |
| full | 进入计划 | 否，只读缓存和执行确定性迁移 |

`off` 模式下，批注导出不得把真实 route 传给翻译生成器。建议把“旧缓存重验迁移”和“生成新翻译”拆成两个函数，避免用 `route=stub` 间接表达禁止调用。

### 5.3 Budget Mode

新增枚举：

```text
off       不创建预算账本；仅用于兼容和紧急回滚
observe   记录所有真实调用和预警，但不在调用前阻断
enforce   调用前拦截，耗尽后按现有 stub/NEEDS WORK 语义处理
```

向后兼容：

- 新变量：`RATOMIZER_LLM_BUDGET_MODE`。
- 新变量未设置、旧 `RATOMIZER_LLM_BUDGET=1` 时映射为 `enforce`。
- 两者都未设置时，首个兼容版本映射为 `off`；完成 M0 基线后将产品默认改为 `observe`。
- 只有在真实语料确认阈值后，才将新项目默认改为 `enforce`。

不得把“预算默认开启”描述为零行为风险。`enforce` 会改变失败、降级和结果包 readiness。

## 6. PipelinePlan 设计

### 6.1 新文件

新增：

- `pipeline_contracts.py`
- `pipeline_plan.py`
- `schemas/pipeline_plan.schema.json`
- `tests/test_pipeline_plan.py`
- `tests/test_pipeline_contracts.py`

### 6.2 PipelinePlan Schema

建议结构：

```json
{
  "schema": "ratomizer-pipeline-plan/v1",
  "plan_version": "pipeline-plan-v1",
  "profile_requested": "b_track",
  "profile_resolved": "b_track",
  "translation_mode": "off",
  "budget_mode": "observe",
  "analysis_enrichment": false,
  "source": {
    "input_sha256": "...",
    "document_profile": "tender"
  },
  "stages": [
    {
      "name": "atomize",
      "depends_on": [],
      "paid": false,
      "execution": "required",
      "reason": "all profiles require parsing"
    },
    {
      "name": "functional-extract",
      "depends_on": ["atomize"],
      "paid": true,
      "execution": "required",
      "budget_stage": "functional_extract"
    }
  ],
  "estimated_usage": {
    "calls_min": 0,
    "calls_max": 0,
    "tokens_estimate": null,
    "basis": "no historical usage available"
  },
  "plan_fingerprint": "sha256:..."
}
```

### 6.3 StageContract

每个阶段在 `pipeline_contracts.py` 声明：

```python
StageContract(
    name="functional-extract",
    depends_on=("atomize",),
    input_artifacts=("chunks.jsonl", "blocks.jsonl", "doc_map.json"),
    output_artifacts=("functional_requirements.json",),
    paid_when="route_is_real",
    budget_stage="functional_extract",
    config_dependencies=(...),
    producer_resolver=...,
    cache_policy="successful_only",
)
```

`CHAIN_ORDER` 可以继续作为执行顺序兼容常量，但不得再作为计划真相源。计划生成、UI 展示、结果包 requested stages 和实际执行都必须来自 StageContract registry。

### 6.4 计划生成规则

1. 先解析 profile、translation mode、budget mode 和显式交付选项。
2. 根据 Profile 选择业务阶段。
3. 叠加 translation mode 和 annotation deliverable。
4. 自动补齐依赖阶段。
5. 去重并拓扑排序。
6. 根据有效配置计算每阶段 paid 状态。
7. 生成 plan fingerprint。
8. 结果包启动时冻结该计划；运行中不得因环境变量变化静默改变阶段集合。

## 7. 前端与 Electron 变更

### 7.1 UI 文件

主要修改：

- `ui/src/App.vue`
- `ui/src/api-client.ts`
- Electron preload/bridge 类型声明文件
- 对应 Vitest 文件

### 7.2 控件

新增：

- Profile segmented control：A 轨 / B 轨 / 双轨审计
- Translation segmented control：不翻译 / 仅批注 / 全文
- Budget mode：观察 / 强制；`off` 放入高级设置
- Requirements analysis enrichment 独立开关
- 运行前计划预览：阶段、paid 标记、缓存状态、预算上限

不要继续让 UI 自己维护 `plannedAutomaticStages()` 和另一份实际 stages 拼接逻辑。UI 调用后端 `planPipeline`，只展示返回的 plan，并将 plan fingerprint 原样提交给执行入口。

### 7.3 localStorage 迁移

将 `ratomizer.runStages.v2` 升级为新的设置版本，例如：

```text
ratomizer.pipelineSettings.v1
```

迁移规则：

- 已有用户：迁移为 `legacy_combined`，translation mode 根据旧 LLM+阶段状态映射为 `full`，budget mode 保持 `off`，保证第一次升级不偷偷改变交付物。
- 新用户：首次付费运行必须选择 Profile；translation 默认 `off`；budget 默认 `observe`。
- 完成真实 A/B 验收后，才允许把推荐 Profile 预选为 A 或 B，但仍必须在运行前可见。

### 7.4 进度状态

进度卡由 plan stages 动态生成，不再维护固定的 `RUN_STAGE_ORDER` 和多套 disabled/skipped 推导。

`functional-extract` 不再冒充 `ai-extract` 卡片。UI 应直接显示 resolved stage，同时用兼容说明标记旧阶段被替换。

## 8. Backend 编排改造

### 8.1 第一阶段兼容接线

不要立即重写所有 runner。先让 `execute_pipeline_plan()` 调用现有入口：

```text
atomize / llm-review   -> run_pipeline_task 的现有机械
chain stages           -> chain_task 的现有 runner map
```

但 stages 必须来自冻结的 PipelinePlan，`chain_task` 不得再次根据环境变量重写计划。

Functional extract 替换逻辑应从 `chain_task` 移到 plan resolver：

- `legacy_combined` 根据兼容设置解析旧路径或 direct path；
- `a_track` 不包含 B 轨阶段；
- `b_track` 不包含 A 轨 review/assemble；
- `hybrid_audit` 明确同时包含两轨。

### 8.2 API/Bridge

新增或扩展：

```text
plan-pipeline
run-pipeline-plan
```

入参至少包含：

- input/out path
- profile
- translation mode
- budget mode
- enrichment flag
- template/domain pack/KB
- annotation deliverable/layout

执行时校验提交的 plan fingerprint。环境变化导致 fingerprint 不一致时，返回 `plan_stale`，要求重新预览，不得静默执行新计划。

### 8.3 CLI

为 `ratomizer run` 增加：

```text
--profile legacy_combined|a_track|b_track|hybrid_audit
--translation off|markers|full
--budget-mode off|observe|enforce
--analysis-enrichment
--plan-only
```

机器面 stdout 继续保持 JSON envelope；`--plan-only` 不执行 provider 调用，只返回计划和估算。

## 9. Result Package 与 Manifest

### 9.1 结果包

结果包 active attempt 必须记录：

- pipeline plan schema/version
- plan fingerprint
- profile requested/resolved
- translation mode
- budget mode
- requested stages
- paid stages
- source input hash

完成判断只检查 plan 中 requested stages。translation mode 为 `off` 时，缺少全文翻译产物不应阻塞 package complete。

### 9.2 旧结果兼容

- 没有 plan metadata 的旧结果按 `legacy_combined` 解释。
- 只读兼容，不向旧目录伪造 plan 或完成证据。
- 继续遵守 `package_v1` addressing rule。

### 9.3 Manifest

`run_manifest.json` 每阶段增加：

- `plan_fingerprint`
- `profile`
- `paid`
- `budget_stage`
- `cache_status`
- `provider_attempts`
- `retry_tokens`

不得在 manifest 中落 API key、完整 endpoint secret 或未截断客户全文。

## 10. 阶段指纹改造

### 10.1 原则

删除 `stage_input_fingerprint()` 中对所有阶段共享的全局 `llm` 配置块。改为从 StageContract 读取有效配置依赖。

只记录**解析后的有效值**，不要同时记录 raw env 和默认值，除非 raw 值本身改变语义。

### 10.2 建议依赖表

| 阶段 | config dependencies |
|---|---|
| atomize | chunk chars、KB/domain pack 内容、解析器开关、table/parser/text-repair 版本 |
| llm-review | route/provider/model、temperature、max tokens、review YAML、executor、tools/evidence versions、review scope/limit |
| functional-extract | route/provider/model、prompt、guards、conservation、negative_k、context strategy、doc map key |
| assemble | enrich route/model、enrich batch、prompt/guards、Blue Book evidence |
| requirements-analysis | enrichment enabled、route/model（仅开启时）、analyze batch、prompt/unfounded/format versions、template knowledge hash |
| full-translation | translation mode=full、route/model、batch/max chars、prompt/guards/strategy、eligible source hashes |
| export-annotation-html | layout mode、annotation producer、translation mode、sidecar hash；仅 markers 模式绑定翻译 route/model |
| compose | 上游产物 hash、compose producer；不绑定 LLM 环境变量 |

### 10.3 必测隔离矩阵

- 改 `RATOMIZER_TRANSLATE_BATCH`：只失效 full translation 和 markers translation，不失效 atomize/functional extract/assemble。
- 改 `RATOMIZER_AI_SELFCHECK_ROUNDS`：只失效旧 ai-extract 路径。
- 改 `RATOMIZER_ANALYZE_BATCH`：enrichment 关闭时不失效 requirements analysis；开启时只失效 analyze enrich。
- 改 annotation layout：只失效 annotation export。
- 改 profile：改变 plan，不伪装为同一 stage fingerprint。

## 11. Budget Observe 与 Enforce

### 11.1 `llm_budget.py`

扩展 ledger mode：

- `observe`：`settle()`、usage、warnings、cost report 正常；`intercept()` 永不抛预算异常。
- `enforce`：保持当前调用前拦截语义。
- ledger 必须记录 mode，旧 ledger 缺 mode 时按历史 `enforce` 解释，不静默改变。

### 11.2 预算阈值

不要直接把当前宽松默认当作最终阈值。M0 用三类真实文档建立：

- 每阶段 calls/token P50、P90、P95
- 缓存冷启动与热启动
- 重试放大系数
- 不同 Profile 的实际分布

建议 enforce 阈值初始取合格文档 P95 加安全余量，并对文档规模做线性或分段缩放。

### 11.3 预估

估算只能标记为 estimate，不得冒充 provider usage。优先使用：

1. 同文档历史账本；
2. 同阶段、相似单元规模的历史中位数；
3. 无历史时只给 calls 上限和 token 未知。

## 12. PaidCacheStore

### 12.1 新文件

新增：

- `paid_cache_store.py`
- `schemas/paid_cache_entry.schema.json`
- `tests/test_paid_cache_store.py`

### 12.2 存储契约

所有付费缓存必须：

- 经 `governed_artifact_path(..., category="cache")` 定址；
- 跨进程锁；
- flush + fsync；
- 临时文件 + `os.replace`；
- Windows `PermissionError` retry；
- torn-tail recovery；
- successful-only；
- usage/provenance 完整记录；
- 支持 cache hit/miss/invalidated 统计。

第一批迁移：

1. `spec_enrich.append_cache`
2. `ai_extract.append_cache`

迁移期间双读：优先新缓存，未命中再读旧 JSONL；只向新缓存写。旧缓存不重写、不伪造迁移。

### 12.3 数据治理

原始模型响应可能包含客户文档内容：

- 不得进入 Git；
- 结果包外发默认排除原始 response cache；
- 提供删除/压实入口；
- schema 中记录 `contains_source_text`；
- trace 和 cache 使用一致的截断/保留策略；
- endpoint、API key 和认证头不得写入。

## 13. 两层付费缓存

### 13.1 Version 分类

每个版本依赖必须登记为：

```text
request_affecting    改变发送给模型的内容或模型行为，必须重新调用
postprocess_only     只改变本地解析/guard/合并，可重放原始响应
presentation_only    只改变渲染，不影响模型和领域结果
```

只有明确登记为 `postprocess_only` 的变化，才允许达到 guard-only bump 零 provider 调用。

### 13.2 ModelResponseCache key

不能只使用 model + prompt version + input hash。建议 canonical identity 包含：

```text
operation_id
provider_family
normalized_endpoint_identity_hash
model
temperature / seed / response_format / max_tokens
system_prompt_hash
user_prompt_hash
tool_schema_hash
tool_executor_version
evidence_fingerprint
context_strategy
input_unit_identity
request_contract_version
```

Transport-only 参数如普通 retry 次数不进入响应 identity，但进入 attempt provenance。

### 13.3 DerivedResultCache key

```text
raw_response_sha256
parser_version
schema_version
guard_versions
compliance_versions
merge_version
deterministic_config_hash
```

### 13.4 Tool-loop 限制

第一版两层缓存只覆盖 single-shot/batch JSON 调用。tool-loop 继续使用现有 `llm-review-cache`，因为其响应依赖多轮工具结果和 evidence state。

在没有完整 transcript identity、工具结果哈希和 evidence replay 前，不得把 tool-loop 简化成普通 raw response cache。

## 14. Functional Extract 增量缓存

### 14.1 分两步实施

当前默认 `legacy` 是整文档一次调用，无法真正做到条款级 provider 复用。

因此分两步：

**M5-A：** 在 `clause_family` opt-in 路径实现 package 级缓存，不改变默认策略。  
**M5-B：** 使用真实 truth set 对 `legacy` 与 `clause_family` 做 A/B；通过 mandatory thresholds 后再决定是否翻默认。

### 14.2 Package key

至少包含：

- target clause id/text hash
- neighbor clause ids/text hashes
- doc map summary hash
- source block ids/hash
- prompt/request-affecting versions
- model/route identity
- negative exemplar hash
- context strategy/max chars

### 14.3 合并

- 每个 package 只缓存成功原始响应和成功 derived result。
- 文档级 `functional_requirements.json` 始终由当前 package 快照确定性重建。
- 守恒检查仍在文档级执行。
- 任一 package 失败时产物必须为 partial/failed，不得用旧 package 冒充当前成功，除非 source hash 完全一致。
- targeted reextract 只刷新目标 package，并原子重建文档级产物。

### 14.4 翻转门

`clause_family` 成为默认前必须满足：

- A/B runner mandatory thresholds 全通过；
- precision/recall/F1 不低于 legacy 基线；
- source_quote 和 source anchor 红线通过；
- 单条款变化只触发目标及必要邻居 provider 调用；
- 全文冷启动 token 不高于批准阈值；
- 未匹配 truth 不得从分母中消失。

## 15. Translation 改造

### 15.1 拆分维护与生成

将当前 `generate_annotation_translations()` 的两类职责拆开：

```text
maintain_translation_cache()
  旧 guards 重验、迁移、安全失效，永不调用 LLM

generate_marker_translations()
  仅 markers 模式调用

generate_full_translations()
  仅 full 模式调用
```

### 15.2 Export 契约

`export_annotation_bundle()` 增加显式 `translation_mode`：

- `off`：维护缓存 + 渲染，不生成；
- `markers`：维护 + 补齐 marker；
- `full`：维护 + 只读全文 sidecar，不补调。

必须增加 provider call counter 测试，证明 `off` 和 full 已完成后的 export 均为零新增调用。

### 15.3 缓存

保留当前 guards 零调用迁移。策略版本变化时：

- 旧成功译文先走当前 deterministic guard；
- 通过则迁移；
- 不通过才重译；
- 旧拒绝项是否重试由 strategy/request version 决定。

## 16. LLMJobRunner

### 16.1 新文件

- `llm_job_runner.py`
- `llm_job_types.py`
- `tests/test_llm_job_runner.py`

### 16.2 第一版范围

先统一 single-shot 和 batch JSON 环节：

- spec enrich
- requirements analysis enrich
- ai extract 的普通调用机械
- translation batch/single 调用机械

tool-loop 通过 adapter 接入预算和 telemetry，但不立刻重写其对话循环。

### 16.3 Runner 职责

- route/provider/model 解析
- request identity
- budget mode
- PaidCacheStore
- JSON/schema validation
- retry 分类
- usage/provenance
- progress callback
- fast-fail/circuit breaker
- ok/partial/failed

业务模块保留：

- prompt operation
- 输入单元和上下文选择
- deterministic guards
- 领域合并
- 交付物投影

### 16.4 Retry telemetry

每次 provider attempt 记录：

- operation/stage/unit id
- attempt kind：initial/429/5xx/truncation/json_repair/split/single/segment
- prompt/completion/total tokens
- duration
- cached or provider
- parent attempt id

预算看板显示 `base_tokens` 和 `retry_tokens`，不再只显示总数。

## 17. Spot Extract 缓存

不得只按 block 文本哈希自动复用。

建议 identity：

```text
package_id
source_file_sha256
block/row/cell locator
target_text_hash
neighbor_context_hash
user-selected mode/options
prompt/guard/request versions
route/provider/model
```

交互建议：

- 相同 identity 有成功缓存时，UI 显示“已有同输入结果”；
- 用户选择复用或重新分析；
- 不静默吞掉用户明确的重新分析动作；
- failed/partial 不作为成功缓存复用。

## 18. Review Store 与 IO 收敛

### 18.1 不合并领域 authority

保留：

- atomic review authority
- AI/functional review authority
- claim authority
- table review authority
- clarification check authority

统一的是底层机械：

- typed append store
- CAS token/fingerprint codec
- process lock
- atomic replace
- WAL replay
- conflict base class
- projection snapshot helper

### 18.2 新底座

优先扩展现有 `artifact_store.py`、`process_file_lock.py`、`io_utils.py`，避免再创建互相竞争的第四套 IO 基础设施。

迁移顺序：

1. 裸 append 付费缓存
2. 重复 `_replace_with_retry`
3. review snapshots
4. redo/queue 状态

## 19. Package 化

在 M0-M7 完成后再开始：

```text
ratomizer/
├── core/
├── parsing/
├── pipelines/a_track/
├── pipelines/b_track/
├── llm/
├── review/
├── claims/
├── delivery/
├── platform/
└── compatibility/
```

版本常量不要全部搬进一个巨型文件。版本应保留在领域 owner 附近，由 StageContract registry 声明依赖关系。

使用兼容 re-export 逐模块迁移，保持旧 import 和 `py-modules` 入口可用；稳定后再切 `packages.find`。

## 20. 文件级变更清单

| 文件/模块 | 变更 |
|---|---|
| `config.py` | 注册 profile、translation mode、budget mode；保留旧变量兼容解析 |
| `pipeline_contracts.py` | 新增阶段契约与 config dependency registry |
| `pipeline_plan.py` | 新增计划解析、验证、fingerprint、拓扑排序 |
| `desktop_tasks.py` | 计划预览/执行入口；移除 chain 内隐式替换；按 plan 执行 |
| `cli.py` | 增加 profile/translation/budget/plan-only 参数 |
| `result_package.py` | active attempt 绑定 plan；completion 按 requested stages |
| `schemas/result_package.schema.json` | 增加可选 plan metadata，旧包兼容 |
| `schemas/pipeline_plan.schema.json` | 新增计划 schema |
| `llm_budget.py` | off/observe/enforce 模式 |
| `llm_client.py` | attempt telemetry；observe 模式不拦截 |
| `paid_cache_store.py` | 新增统一付费缓存底座 |
| `spec_enrich.py` | 迁移裸 append；接入 runner/cache |
| `ai_extract.py` | 迁移裸 append；保留旧行为版本 |
| `functional_extract.py` | clause-family package cache、确定性重建 |
| `requirements_analysis.py` | paid 状态由 enrichment effective value 决定；接入 runner |
| `doc_annotation_export.py` | 拆维护/marker 生成；显式 translation mode |
| `full_translation.py` | 仅 full 模式生成；export 只读复用 |
| `llm_job_runner.py` | 新增统一 single-shot/batch runner |
| `api_server.py` | plan/status/cost 查询；不得复制计划解析逻辑 |
| `ui/src/App.vue` | Profile/Translation/Budget 控件；删除本地阶段推导 |
| `ui/src/api-client.ts` | plan API 与类型 |
| Electron bridge/types | planPipeline/runPipelinePlan IPC |
| `ARCHITECTURE.md` | 修正默认值与新计划模型 |
| `AGENTS.md` | 里程碑完成后更新当前事实摘要 |
| `CLAUDE.md` | 只追加里程碑结果；同时启动 CURRENT_STATE 拆分计划 |

## 21. 测试方案

### 21.1 Backend 单元测试

新增测试至少覆盖：

```text
test_pipeline_plan_profiles.py
test_pipeline_plan_translation_modes.py
test_pipeline_plan_budget_modes.py
test_stage_config_dependencies.py
test_paid_cache_store.py
test_model_response_cache_identity.py
test_derived_cache_replay.py
test_functional_extract_package_cache.py
test_translation_mode_no_hidden_calls.py
test_result_package_plan_completion.py
test_llm_retry_telemetry.py
```

关键断言：

- B Profile 的 review/spec enrich provider calls 为 0。
- A Profile 的 functional extract provider calls 为 0。
- requirements analysis enrichment 默认关闭时 provider calls 为 0。
- translation mode off 时 full translation 与 annotation export 的翻译 calls 均为 0。
- markers 模式只翻 marker；full 模式 export 不产生新增调用。
- 改翻译 batch 不失效 atomize。
- 相同成功 request identity 二次运行 provider calls 为 0。
- failed/partial 不进入成功缓存。
- guard-only postprocess bump 重放 derived result，不调用 provider。
- request-affecting bump 必须 miss。
- 单条款变化只重跑受影响 package。

### 21.2 Frontend

运行：

```powershell
cd ui
cmd /c "npm test"
cmd /c "npm run build"
```

覆盖：

- localStorage v2 迁移
- Profile 与 Translation Mode 控件
- plan preview 和 stale plan 错误
- 动态 stage progress
- old package 兼容打开
- budget warnings/exhausted 状态

### 21.3 Backend 全量

```powershell
python -m unittest discover -s tests
```

行为版本变化后必须在具备 `out/` golden 的主检出按仓库约束再生成并执行 golden tests。

### 21.4 集成测试

建立 fake provider call recorder：

- 记录 operation、unit、attempt type、tokens；
- 支持模拟 429、5xx、截断、非法 JSON、缺槽；
- 验证预算、cache、retry 和 plan paid 标记一致。

### 21.5 真实语料门禁

三类文档分别跑：

- cold cache
- warm cache
- 单条款变化
- guard-only bump
- prompt bump
- translation off/markers/full

记录 accuracy 与成本，不只记录绿色测试数。

## 22. 验收指标

| 指标 | 目标 |
|---|---:|
| B Profile 的 A轨 review/spec enrich provider calls | 0 |
| A Profile 的 B轨 functional extract provider calls | 0 |
| requirements analysis enrich 关闭时 provider calls | 0 |
| translation off 的全部翻译 provider calls | 0 |
| full translation 完成后的 annotation export 新增翻译 calls | 0 |
| 真实 provider attempts 纳入 usage ledger | 100% |
| 自动、可缓存、上次成功阶段的同 identity 二次 provider calls | 0 |
| postprocess-only bump 且 raw response 兼容时 provider calls | 0 |
| request-affecting bump 的 cache hit | 0 |
| 单条款变化后的 package 重跑范围 | 目标条款及必要邻居 |
| 无关配置变化造成的 cache miss | 0 |
| 付费缓存裸 append | 0 处 |
| Pipeline plan 来源 | 1 个 |
| usage/provenance 可追踪率 | 100% |
| truth-set mandatory thresholds | 不低于批准基线 |

## 23. 分里程碑完成定义

### M0：基线

完成条件：

- 三类文档有 cold/warm 分阶段 usage 报告；
- 当前默认链 provider calls 有自动计数；
- 当前 accuracy/closure/golden 状态冻结；
- 不改变行为版本。

### M1：Profile/Translation/Budget Observe

完成条件：

- UI/CLI 可生成计划；
- translation off 无隐藏调用；
- observe ledger 统计完整但不拦截；
- 旧用户迁移保持 legacy behavior；
- 新用户运行前明确选择 Profile。

回滚：设置 `legacy_combined + full + budget off`。

### M2：PipelinePlan 与结果包

完成条件：

- UI、CLI、bridge、manifest、result package 使用同一 plan fingerprint；
- stale plan fail loudly；
- completion 只按 requested stages；
- 旧包只读兼容。

### M3：Fingerprint 隔离

完成条件：

- config dependency 矩阵测试全过；
- 调翻译配置不影响解析/抽取；
- producer 与 stage contract 依赖一致。

### M4：PaidCacheStore

完成条件：

- spec enrich/ai extract 无裸 append；
- 并发、崩溃、torn-tail、Windows replace 测试通过；
- raw cache 不进入可发布 deliverables。

### M5：Functional 增量

完成条件：

- clause-family package cache E2E；
- 单条款变化局部重跑；
- global conservation 不放松；
- A/B 门禁决定是否翻默认。

### M6：LLMJobRunner

完成条件：

- 至少三个 single-shot/batch 阶段接入；
- retry telemetry 和预算账本一致；
- 原有 schema/guard 结果无漂移。

### M7-M8：结构收敛

完成条件：

- 通用 IO/review primitives 被多领域复用；
- 无跨模块借用私有 `_replace_with_retry`；
- package 迁移保持旧入口兼容；
- 每个里程碑独立通过全量/golden。

## 24. 风险与回滚

| 风险 | 防护 | 回滚 |
|---|---|---|
| Profile 缺少旧交付物 | 计划预览、requested stage version | legacy_combined |
| Budget enforce 误杀大文档 | observe 基线、按规模阈值 | budget observe/off |
| 两层缓存错误复用 | request/postprocess 版本分类、双写回放 | 关闭 raw reuse，保留 derived 旧缓存 |
| clause-family 召回下降 | truth set A/B mandatory gates | context strategy legacy |
| translation off 仍隐藏调用 | provider call counter integration test | translation route 强制 stub |
| plan/UI 漂移 | plan fingerprint/stale error | 后端拒绝执行 |
| raw cache 泄漏客户内容 | governed cache、发布排除、清理入口 | 禁用 raw cache |
| package 重构 import 破坏 | compatibility re-export | 保留顶层模块入口 |

## 25. 建议提交拆分

实施时每个提交只做一个行为面：

```text
1. pipeline contracts/schema（无行为变化）
2. budget observe mode（无拦截）
3. translation mode + hidden-call tests
4. profile plan + UI preview
5. result package plan binding
6. stage config dependency isolation
7. PaidCacheStore + spec_enrich migration
8. ai_extract cache migration
9. functional clause package cache（仍 opt-in）
10. LLMJobRunner first adopters
11. review/IO primitives
12. package migration batches
```

行为版本 bump、golden 再生成和默认值翻转必须单独提交，便于归因和回滚。

## 26. 实施者最终检查清单

- [ ] 当前工作树用户改动已保留并纳入 prompt version lineage
- [ ] M0 成本与 accuracy 基线已保存
- [ ] Profile、Translation、Budget 三个维度互相独立
- [ ] requirements analysis enrichment 的 paid 状态使用有效开关
- [ ] export annotation 不再隐藏生成翻译
- [ ] 所有执行入口消费同一 PipelinePlan
- [ ] 所有 paid calls 有 stage/operation/unit identity
- [ ] 预算 observe 与 enforce 已分离
- [ ] stage config dependencies 已按阶段声明
- [ ] raw response 与 derived result 缓存分层
- [ ] tool-loop 未被错误套用普通 raw cache
- [ ] functional package cache 仍受 truth-set 翻转门控制
- [ ] 共享缓存全部 governed addressing + lock + fsync + atomic replace
- [ ] 旧结果包只读兼容，不伪造迁移
- [ ] backend unittest、frontend test/build、golden 全部执行
- [ ] `ARCHITECTURE.md`、`AGENTS.md`、`CLAUDE.md` 在里程碑后同步

## 27. 最终推荐

实际开始修改时，先完成 M0-M3，不要直接从大型 package 重构或减少 LLM 轮次开始。

第一批最有价值且风险可控的交付应是：

```text
1. 真实成本基线
2. Translation Mode 三态并消除 annotation export 隐藏调用
3. Budget Observe
4. A/B/Hybrid Profile
5. PipelinePlan 单一计划源
6. 阶段 config dependency 隔离
```

完成这六项后，系统已经能够停止无意重复调用、准确解释每一次付费，并为后续缓存和结构重构提供稳定边界。

