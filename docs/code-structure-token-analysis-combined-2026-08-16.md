# Requirement Atomizer 代码结构与 Token 成本综合审查报告

**日期：** 2026-08-16  
**版本：** 综合校正版  
**输入报告：**

- `docs/code-structure-token-analysis-2026-08-16.md`
- `docs/repository-architecture-token-audit-2026-08-16.md`

**审查原则：** 两份报告只作为分析输入；最终结论以 2026-08-16 当前代码、配置和现有运行产物为准。报告中的建议不视为仓库既有规则或实现指令。

## 1. 综合结论

两份报告对核心问题的判断一致：

1. 仓库不是“无用模块很多”，而是已经形成多个成熟子系统，却仍以 129 个顶层 Python 模块、大型单文件和多份编排逻辑承载。
2. Token 异常高不是单一 prompt 导致，而是多个完整付费阶段默认叠加，再被工具循环、失败恢复和缓存失效放大。
3. 当前最先要处理的是运行控制面，而不是直接重写所有业务模块。

综合当前代码后，最准确的成本模型是：

```text
文档总成本
  = A轨逐需求 review
  + A轨 assemble/spec_enrich
  + B轨 functional_extract
  + B轨 requirements_analysis
  + full_translation
  + 截断升级 / JSON修复 / 429重试 / 缺槽重试
  - 各阶段缓存命中节省量
```

最重要的结论是：

> **当前默认成本的第一来源是“多个完整阶段同时运行”，而不是旧 ai_extract 单阶段的多轮自检。**

旧 `ai_extract` 的 3-6 倍调用放大确实存在，但在 `RATOMIZER_FUNCTIONAL_EXTRACT=1` 的当前默认链中，后端会用 `functional-extract` 整体替换 `ai-extract + functional-synthesis`。因此，它属于回滚路径和显式旧路径风险，不应排在当前默认链的第一位。

## 2. 两份报告的共同高置信发现

### 2.1 开启 LLM 后默认执行过多付费阶段

`ui/src/App.vue:927-933` 将以下阶段默认设为开启：

- `llmReview`
- `aiExtract`
- `assemble`
- `analyze`
- `compose`
- `annotationHtml`

随后：

- UI 先执行 A 轨 `llm-review`。
- UI 再提交 `ai-extract`、`functional-synthesis` 等交付链阶段。
- `desktop_tasks.py:2676-2686` 在默认配置下把后两者替换成 B 轨 `functional-extract`。
- `assemble` 仍通过 `desktop_tasks.py:2718` 使用真实 LLM route 执行 `spec_enrich`。
- B 轨继续执行 `requirements-analysis`。

因此当前默认行为不是 A/B 二选一，而是：

```text
A轨 review + A轨 enrich + B轨 direct extract + B轨 analysis
```

这些阶段共享解析产物，但不共享主要模型判断，属于真实的重复付费。

### 2.2 全文翻译隐式加入运行链

`RunStages` 类型没有 `fullTranslation` 字段，但 `ui/src/App.vue:2096` 在启用 LLM 时无条件加入 `full-translation`；`config.py:43` 又将 `RATOMIZER_FULL_TRANSLATION` 默认设为 `1`。

这意味着用户可以关闭其他显式阶段，却没有同等粒度的 UI 控制来关闭全文翻译。

### 2.3 文档总预算存在但默认关闭

`config.py:86` 将 `RATOMIZER_LLM_BUDGET` 默认设为 `0`。

当前代码已经具备：

- 文档总 calls/token 限额
- 阶段子预算
- 80% 预警
- 预算耗尽后的降级和 NEEDS WORK 语义
- usage 完整性记录

但默认运行不启用该控制面。各阶段虽然有局部 batch、轮次或 token 上限，整个文档仍没有统一封顶。

### 2.4 LLM tool-loop 会累积重发历史

`llm_client.chat_with_tools` 默认最多 8 轮；A 轨 review YAML 将实际最大轮次设为 5。

代码在每一轮把 assistant tool call 和 tool result 追加到 `history`，下一轮再次发送完整 history。总 prompt token 因此随轮次呈超线性增长；当每轮工具结果规模接近时，累计成本可近似按轮次数平方增长。

Schema repair 也会续接已有 transcript，而不是从一个最小修复上下文重新开始。

### 2.5 失败恢复会整段重发

`llm_client.py` 当前包含以下恢复机制：

- 输出截断或空响应时，`max_tokens` 最多按 6144 -> 12288 -> 24576 -> 32768 升级。
- JSON 解析失败时，附带原 messages 和错误回复再调用一次修复。
- 429 使用独立重试预算，至少允许 8 次限流尝试。
- 普通 5xx 等错误使用 `max_retries + 1` 次尝试。

这些机制提高成功率并减少整章丢失，但成本特征是“同一输入再次完整发送”。在模型处于截断、限流或格式不稳定边缘时，单单元调用成本可能放大 2-4 倍。

### 2.6 横切基础设施重复实现

两份报告共同识别出以下重复：

- 多套 review state/store、冲突异常、fingerprint 和锁
- 多条 spot/reextract/rescan/recompute/reconcile 路径
- 多份 LLM batch、JSON 修复、fast-fail 和缓存逻辑
- 数十处 `os.replace`、锁和 Windows retry 实现
- 大量分散的 `*_VERSION` 常量和 stage producer 拼接逻辑
- UI、CLI、Electron bridge 和后端 chain 各自推导阶段

这些重复不一定立即产生 provider token，但会造成缓存策略不一致、版本失效范围扩大和相同文本跨链路重复调用。

## 3. 需要校正的结论

### 3.1 旧 ai_extract 的 3-6 倍调用不是当前默认最大来源

同事报告指出旧 B 轨每章节可能执行：

```text
初次抽取 1 次 + self-check 最多 3 次 + verify 2 次
```

代码证据成立：

- `RATOMIZER_AI_SELFCHECK=1`
- `RATOMIZER_AI_SELFCHECK_ROUNDS=3`
- `RATOMIZER_AI_VERIFY=1`
- `RATOMIZER_AI_VERIFY_ROUNDS=2`

但在当前默认 `RATOMIZER_FUNCTIONAL_EXTRACT=1` 下，chain 会替换掉 `ai-extract + functional-synthesis`。因此应这样分级：

| 场景 | 是否存在 3-6 倍旧抽取放大 |
|---|---|
| 当前默认 GUI 全链 | 否，ai-extract 被 functional-extract 替换 |
| 显式 `RATOMIZER_FUNCTIONAL_EXTRACT=0` | 是 |
| 单独调用 `ai-extract` | 是 |
| 历史结果重跑或 rollback drill | 可能是 |

结论：它是重要的条件性成本风险，但不是当前默认链的 P0 第一根因。

### 3.2 当前 tool-loop review 不能直接通过开关启用批处理

`config.py:39` 和 `llm_pipeline.py:129-137` 明确规定：

- `RATOMIZER_REVIEW_BATCH` 只对旧 single-shot review 生效。
- 当前 YAML 的 `classify_risk` 和 `correct_errors` 使用 `executor=tool_loop`。
- tool-loop 路径恒不批处理，以避免绕过逐需求工具取证、KB 查询上限和 token 预算。

因此“直接默认开启 review batch”并非无语义改动的现成优化。要降低当前 review 成本，优先方向应是：

1. A/B Profile 避免不必要地启动 review。
2. 缩减工具返回体和重复 transcript。
3. 对可确定的 operation 继续下沉 deterministic executor。
4. 另行设计保留逐条证据隔离的批量裁决机制，并通过 golden/eval 验证。

### 3.3 翻译 guards bump 已有零调用重验迁移

同事报告认为 guards 版本变化会让旧翻译缓存整体丢弃并全文重译。当前代码只部分符合该描述：

- `api_server.load_annotation_translations` 和渲染读取路径确实 fail-closed，只接受当前 guards version。
- 但 `doc_annotation_export.py:3009-3033` 的翻译生成路径会对旧成功译文重新运行当前确定性 drift guard。
- 通过新 guard 的旧译文只更新 `guards_version`，不调用 LLM。
- 只有新 guard 判定不安全的译文才会失效并进入重译。

因此，“guards bump 必然全文重译”是过时或不完整的判断。当前更准确的问题是：

- 直接渲染旧 sidecar 时会先 fail-closed；
- 必须经过维护/生成路径才能完成零调用迁移；
- 应增加测试保证版本升级始终优先重验迁移，而不是退化成全量重译。

### 3.4 Functional Extract 当前仍是文档级缓存

同事报告部分位置将它称为“条款指纹缓存”。当前实现中：

- fingerprint 的 `clauses` 字段包含全部条款 fingerprint；
- cache entry 保存整个 functional extract payload；
- `clause_family` 只改变调用拆包方式，没有改变外围缓存粒度。

因此一个条款变化仍可能导致整文档所有条款包重新调用。条款级缓存是建议目标，不是当前事实。

### 3.5 “缓存模型原始响应”是正确方向，但不是低风险开关

当前付费缓存通常保存 guard 后结果，因此 guard、compliance 或 table structure 版本 bump 会使缓存失效并重新调用模型。

将缓存拆为两层具有明显收益：

```text
ModelResponseCache
  key = model + prompt版本 + 输入文本/上下文哈希
  value = 原始模型响应 + usage + provenance

DerivedResultCache
  key = 原始响应哈希 + parser/guard/compliance/table版本
  value = 当前确定性后处理结果
```

这样 guard-only bump 可以只重放本地处理，不重新付费。

但迁移必须处理：

- 原始响应 schema 与 parser 版本
- 旧响应是否保留完整字段
- 失败响应和部分响应能否复用
- prompt 与 guard 边界是否真的确定
- anti-hallucination 和 provenance 是否仍可审计

因此它应进入中期高收益改造，并通过双写和回放验证上线，不能归类为“立即启用且不改变行为”。

### 3.6 减少 self-check/verify 轮次会改变召回语义

将 verify 2 -> 1、self-check 3 -> 2 很可能直接降低召回率。仓库当前已经提供 `tools/ab_runner.py` 和 mandatory thresholds，这类改变应通过真实 truth set 做 Go/No-Go，而不是仅按 token 收益上线。

## 4. 当前代码结构综合画像

### 4.1 规模

- 顶层 Python 模块：129 个
- 测试 Python 文件：204 个
- `CLAUDE.md`：224,718 bytes，约 1,021 行
- 顶层和 package 中存在约 160+ 个行为/缓存版本常量；不同统计口径会略有变化
- LLM 直接和间接调用分散在十余个生产模块
- 原子替换、fingerprint、锁和缓存辅助函数分布在数十个文件

### 4.2 最大复杂度中心

| 模块 | 规模 | 问题 |
|---|---:|---|
| `claim_artifacts.py` | 约 6,209 行 | 发布、验证、投影和产物职责集中 |
| `ui/src/App.vue` | 约 6,210 行 | UI、运行计划、进度和交互集中 |
| `ai_extract.py` | 约 4,827 行 | prompt、抽取、自检、复核、缓存、并发集中 |
| `claim_ledger.py` | 约 4,566 行 | 多类账本和闭环规则集中 |
| `desktop_tasks.py` | 约 3,701 行 | bridge、CLI、chain、manifest、fingerprint 集中 |
| `api_server.py` | 约 3,425 行 | 标准库 HTTP 路由和业务处理集中 |

### 4.3 主要子系统

```text
parsing
  DOCX / XLSX / PDF / table physical structure / facsimile

A-track
  atomize -> llm-review -> assemble -> COSEM specs

B-track
  functional-extract -> requirements-analysis -> template/clarification

review and claims
  review actions -> catalog -> ledger -> queue -> verifier -> annotation

delivery
  full translation -> compose -> annotation HTML/PDF/XLSX

platform
  cli.py / desktop_tasks.py / api_server.py / Vue3 + Electron
```

### 4.4 当前结构问题的本质

问题不在于每个模块都没有价值，而在于：

1. 领域聚类已经自然形成，但没有成为 package 边界。
2. 横切基础设施由业务模块各自复制。
3. stage contract、缓存依赖和版本血缘依靠人工同步。
4. 兼容路径、实验路径和生产路径混在相同编排文件中。
5. 前端与后端都存在“单文件承载整个控制面”的镜像问题。

## 5. 当前真实 AI 调用矩阵

| 阶段 | 当前默认链 | 调用粒度 | 主要放大因素 | 缓存现状 |
|---|---:|---|---|---|
| A轨 `llm-review` | 是 | 每需求一次 tool-loop | 5轮、20k/需求、history累积、schema repair | 单需求证据作用域缓存 |
| A轨 `spec_enrich` | 是 | batch，部分条目单发 | 缺槽回退、Blue Book 条目约束 | 独立 JSONL 缓存 |
| B轨 `functional-extract` | 是 | legacy 文档调用或 clause-family 多包 | 文档级 cache miss 导致全包重跑 | 整文档 payload 缓存 |
| B轨 `requirements-analysis` | 是 | 默认 batch 4 | 缺槽重试、上下文富化 | 独立 enrich cache |
| `full-translation` | 是 | 默认 batch 10 | 拆半、单条、句段三级恢复 | 内容哈希 sidecar，可迁移 guards |
| 旧 `ai-extract` | 默认被替换 | 每章节 | 抽取+self-check+verify 最多 3-6倍 | 章节缓存，版本耦合较多 |
| `spot_extract` | 用户触发 | 单 block/row | 重复点击无缓存 | 无付费结果缓存 |
| claim verifier | 有授权才运行 | claim/requirement | 多轮验证 | 预算和 WAL 约束 |

## 6. Token 实测应如何解释

仓库中存在三组常被引用的数据，它们代表不同口径：

| 数据 | 含义 |
|---|---|
| 345 calls / 1,048,945 tokens | 某次 `full_translation` 预算账本中的单阶段实际消耗 |
| 498 calls / 1,583,211 tokens | SBD 翻译从干净 v4 到 prompt/guards 返修的三轮研发累计消耗 |
| 40 calls / 204,133 tokens | 同一 SBD 在已有缓存基础上的最终增量验收轮 |

这三组数据共同说明：

1. 全文翻译本身可以达到百万 token 级。
2. 缓存稳定时增量重跑确实显著便宜。
3. 开发期间的版本变化和失败修复会反复触发大规模付费。
4. 因此应同时治理“默认是否执行”与“版本变化时是否必须重新调用模型”。

另一个历史实测为：抽取轨 781 次调用中出现 164 次 429。它说明当前高并发和 provider 限流之间存在真实冲突；代码已增加共享 AIMD 闸门和 429 独立重试，但限流期间仍会增加延迟和 provider attempts。

## 7. 综合风险排序

### P0：立即影响默认成本

1. **普通运行同时执行 A 轨和 B 轨主要付费阶段。**
2. **全文翻译在 LLM 模式下隐式开启。**
3. **文档级总预算默认关闭。**

### P1：导致付费放大或重复重跑

4. **阶段 fingerprint 混入无关配置，造成跨阶段缓存失效。**
5. **functional-extract 外围缓存为整文档粒度。**
6. **tool-loop transcript 累积、截断升级和 JSON repair 完整重发。**
7. **LLM runner、付费缓存、review store 和重做队列未统一。**
8. **部分付费缓存仍使用裸 append，缓存损坏后可能重新付费。**
9. **UI、CLI、bridge、backend 各自维护阶段计划。**

### P2：条件性或长期结构风险

10. **旧 ai-extract 在显式回滚路径中仍有 3-6 倍调用放大。**
11. **spot extract 重复调用无缓存。**
12. **版本常量和 stage producer 依赖人工同步。**
13. **大型 flat layout、上帝文件和多套状态机提高修改成本。**
14. **`CLAUDE.md` 作为强制前置上下文过大，增加 agent token 成本。**

### P3：工程卫生

- 根目录存在约 278KB 的 `!` 文件。
- `pyproject.toml` 中 `doc_map`、`reconcile`、`adjudicate` 重复登记。
- `ARCHITECTURE.md` 对 functional extract 默认值的描述已经过时。
- archive/cache 等目录需要按仓库策略整理。

这些问题应清理，但不应挤占 P0/P1 的 token 治理资源。

## 8. 建议的治理方案

### 阶段 0：建立真实成本基线

在改变模型语义前，选择三类代表文档：

1. prose/tender 文档
2. DLMS profile 文档
3. 表格密集 DOCX/XLSX/PDF 文档

分别运行 A、B、Hybrid Profile，记录：

- 每阶段 calls
- prompt/completion/total tokens
- cache hit/miss
- retry 分类
- 429 次数
- tool-loop 平均轮次
- 每阶段 wall time
- 最终 precision/recall/F1 和 mandatory thresholds

预算单应从第一轮基线开始启用，但初始阈值可以保持宽松，先用于可见性和防止失控。

### 阶段 1：默认链立即止血

1. 增加 `b_track`、`a_track`、`hybrid_audit` 三个文档 Profile。
2. 普通 Profile 中 A/B 互斥；Hybrid 必须显式选择。
3. 增加独立 `fullTranslation` 开关，默认关闭，只在最终交付时开启。
4. 产品默认启用文档预算，并在运行前展示预计 calls/tokens。
5. B 轨运行不生成或不调度无消费者的 A 轨付费任务。
6. A 轨运行不调度 B 轨 functional extract/analysis，除非 Hybrid 明确要求。

这一阶段不调整 self-check、verify、工具权限或 anti-hallucination 规则，风险最低、收益最大。

### 阶段 2：缓存与成本控制面

1. 每阶段声明独立 `input_files`、`config_dependencies` 和 `producer_versions`。
2. 将 functional extract 改为条款级模型响应缓存、文档级确定性合并。
3. 建立 `ModelResponseCache + DerivedResultCache` 两层缓存。
4. 抽取统一 `PaidCacheStore`，先迁移 `spec_enrich` 和 `ai_extract` 的裸 append。
5. 对 spot extract 增加 block/row 文本哈希级重复请求缓存或复用提示。
6. 给重试路径记录 `retry_reason`、原始调用和额外 token，形成放大系数看板。
7. 保留翻译旧缓存的零调用 guard 重验迁移，并增加回归测试。

### 阶段 3：统一 LLM 执行层

建立 `LLMJobRunner`，统一负责：

- route/model 解析
- 文档和阶段预算
- 并发与 AIMD 限流
- JSON/schema 修复
- retry 分类和上限
- usage/provenance
- cache lookup/write
- progress event
- ok/partial/failed 状态

业务阶段只负责：

- 定义输入单元
- 构建 operation/prompt
- 定义 schema
- 执行 deterministic guard
- 合并结果

对于 tool-loop，应优先限制工具输出大小和重复回灌，而不是简单切换到无工具 batch。任何 transcript 裁剪都必须保证证据可追溯和工具结论不失真。

### 阶段 4：统一 PipelinePlan

由 Python 后端生成唯一计划：

```json
{
  "profile": "b_track",
  "stages": [
    {"name": "atomize", "paid": false},
    {"name": "functional-extract", "paid": true},
    {"name": "requirements-analysis", "paid": true},
    {"name": "template-write", "paid": false}
  ],
  "estimated_calls": 42,
  "estimated_tokens": 380000,
  "budget": {"max_calls": 60, "max_tokens": 500000}
}
```

UI、CLI、Electron bridge、manifest、result package 和进度状态全部消费该计划，不再自行推导 stages。

### 阶段 5：结构收敛

建议逐步形成以下 package：

```text
ratomizer/
├── core/                   # ID、hash、schema、artifact store
├── parsing/                # DOCX/XLSX/PDF -> 统一 IR
├── pipelines/
│   ├── a_track/
│   └── b_track/
├── llm/                    # client、runner、budget、cache、tools
├── review/                 # stores、actions、projections
├── claims/                 # catalog、ledger、queue、verifier
├── delivery/               # translation、compose、annotation
├── platform/               # api、desktop、cli
└── compatibility/          # legacy schema/output/PySide6
```

优先拆分顺序：

1. `desktop_tasks.py` 的 chain、manifest、fingerprint、CLI 定义
2. `App.vue` 的运行配置、任务状态、评审页面
3. review stores 和冲突处理
4. paid cache 和原子写底座
5. claim 发布、ledger、queue、projection

不要一次性移动全部模块，也不要把 package 重构与模型行为变化放在同一个 milestone。

## 9. 不建议直接实施的优化

以下建议需要先经过真实语料验证：

1. 直接把 ai-extract verify 从 2 轮降为 1 轮。
2. 直接把 self-check 从 3 轮降为 2 轮。
3. 在当前 tool-loop YAML 下强制开启 single-shot review batch。
4. 删除工具 transcript 中的历史证据而不保留可审计摘要。
5. 只缓存模型原始响应而删除 guard 后产物缓存。
6. 为减少缓存失效而不 bump 确实影响行为的版本。

这些措施可能降低 token，但也可能降低召回、绕过工具取证或让旧缓存静默绕过新 guard。

## 10. 验收指标

| 指标 | 目标 |
|---|---:|
| B Profile 触发 A 轨 review/enrich 调用 | 0 |
| A Profile 触发 B 轨 direct extract/analysis 调用 | 0 |
| 非最终交付运行触发全文翻译 | 0 |
| 真实 LLM 调用纳入文档预算 | 100% |
| 相同输入、相同版本二次运行 provider calls | 0 |
| guard-only bump 在已有原始响应时 provider calls | 0 |
| 单条款变化后的 functional extract 重跑范围 | 变化条款及必要邻居 |
| 无关配置变化造成的 stage cache miss | 0 |
| 付费缓存裸 append | 0 处 |
| Pipeline stage 计划来源 | 1 个 |
| usage/provenance 可追踪率 | 100% |
| A/B truth-set mandatory thresholds | 不低于当前基线 |

## 11. 建议实施顺序

综合收益、风险和依赖关系，建议按以下顺序推进：

```text
1. 开启成本观测与文档预算
2. 引入 A/B/Hybrid Profile
3. 全文翻译改为显式 opt-in
4. 修正阶段级 config dependencies
5. Functional Extract 条款级缓存
6. 两层付费缓存 + PaidCacheStore
7. LLMJobRunner
8. PipelinePlan 单一真相源
9. review/claim/redo 基础设施收敛
10. package 化和大型文件拆分
```

前三项用于立即停止无意成本；第 4-7 项减少版本迭代和失败恢复造成的重复付费；第 8-10 项解决长期结构复杂度。

## 12. 最终判断

两份报告并不矛盾，它们分别强调了不同层面：

- 第一份更深入地识别了 retry、tool transcript、review stores、版本常量和原子写等横切重复。
- 第二份更准确地还原了当前默认 GUI 链、A/B 双轨叠加、全文翻译隐式开启、整文档 functional cache 和编排多份真相。

综合后，当前最可信的判断是：

> **Token 的最大即时浪费来自默认运行了不必要的完整阶段；最大迭代浪费来自缓存键与确定性后处理版本耦合；最大长期风险来自横切基础设施和编排逻辑没有单一归属。**

因此，先优化运行产品形态和成本控制面，再优化单阶段 prompt 与轮次，最后做大规模 package 重构，是风险最低且收益最高的路线。

