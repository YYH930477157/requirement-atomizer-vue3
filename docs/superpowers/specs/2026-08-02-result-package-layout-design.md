# 结果包完成标志与输出目录整理设计

- 日期：2026-08-02
- 状态：设计已由用户确认，等待书面规格复核
- 目标版本：`ratomizer-result-package/v1`

## 1. 背景

当前桌面工具把用户交付物、抽取中间产物、Claim 账本、缓存、日志、锁文件和阶段恢复文件全部写在同一个输出目录根部。真实结果目录可能包含 50 个以上文件，用户难以判断哪些是最终结果，工具也只能通过 `manifest.json`、`blocks.jsonl` 等启发式文件猜测该目录是否已经运行过。

本设计把输出目录定义为一个有明确契约的“结果包”：

1. 根目录只保留用户需要直接查看或交付的文件。
2. 根目录使用 `result-package.json` 明确声明自动需求分析是否已完成。
3. 内部运行文件统一进入 `.ratomizer/`。
4. 人工审核进度独立保存，不影响“自动分析已完成”的状态。
5. 旧版扁平目录继续可读，不自动搬移或伪造新版标志。

## 2. 用户确认的完成口径

“已完成”表示工具的自动需求分析任务已经成功产出，不要求人工审核完成。

这里的“自动需求分析任务”是桌面端一次明确启动的顶层运行计划。该计划必须包含至少一个会生成需求结果的阶段；单独打开目录、执行人工审核、重新导出 HTML、导入裁决或刷新摘要都不构成新的自动需求分析任务。

- 自动需求分析成功：结果包可标记为 `completed`。
- 人工尚未审核：结果包仍然是 `completed`。
- 人工审核进行中：审核进度单独保存，重新打开后继续。
- 自动需求分析失败或中断：不得标记为 `completed`。
- 后续批注、裁决、翻译或重新导出交付物：不得撤销已有的自动分析完成状态。

## 3. 目标与非目标

### 3.1 目标

- 让桌面工具确定性识别新版结果目录及其完成状态。
- 让用户在根目录只看到最终交付物、摘要和完成标志。
- 保证审查会话、Claim 账本、缓存、恢复和续跑能力不丢失。
- 保证旧结果目录仍可打开。
- 保证崩溃、中断或部分发布不会形成虚假的完成标志。
- 为后续“打开已有结果”按钮和最近结果列表提供统一状态来源。

### 3.2 非目标

- 本版本不自动整理或迁移旧结果目录。
- 本版本不删除用户自行放入输出目录的未知文件。
- 本版本不把人工审核完成作为自动分析完成的前置条件。
- 本版本不修改需求分析、Claim 判定或 LLM 语义结果。
- 本版本不修改冻结 golden 的语义基线。

## 4. 术语

- **结果包根目录**：用户在桌面工具中选择的输出目录。
- **最终交付物**：明确登记为可直接查看、分享或交给下游使用的文件。
- **内部产物**：抽取、分析、账本、缓存、日志、锁和恢复所需文件。
- **完成标志**：根目录中的 `result-package.json`。
- **旧版目录**：不存在 `result-package.json`，仍按历史扁平结构保存文件的输出目录。
- **自动分析完成**：本次桌面任务请求的自动分析步骤成功完成并提交完成证据。
- **审核进度**：专家接受、拒绝、待审核、Claim 裁决及批注状态；它不参与自动分析完成判定。

## 5. 目录结构

新版结果目录采用以下结构：

```text
<result-root>/
├─ result-package.json
├─ summary.md
├─ document_annotation.html
├─ document_facsimile.pdf
├─ merged_spec.xlsx
├─ software_requirements.xlsx
├─ 软件需求列表-成文.xlsx
├─ clarification_questions.xlsx
├─ engineering_requirements/
└─ .ratomizer/
   ├─ pipeline/
   ├─ state/
   ├─ cache/
   ├─ logs/
   └─ stages/
```

只有实际生成的最终交付物才出现在根目录，不创建空占位文件。

### 5.1 根目录允许的工具产物

根目录不是按扩展名放行，而是按逻辑产物登记。首版允许：

| 逻辑产物 | 典型路径 | 用途 |
|---|---|---|
| 结果包标志 | `result-package.json` | 完成状态、版本和交付物清单 |
| 人读摘要 | `summary.md` | 本次分析摘要 |
| 批注视图 | `document_annotation.html` | 应用外查看和审查 |
| 影印文档 | `document_facsimile.pdf` | Word/Excel/PDF 统一影印视图；不可用时不伪造 |
| 合并规格 | `merged_spec.xlsx` | 合并后的需求表 |
| 软件需求表 | `software_requirements.xlsx` | 分析轨输出 |
| 公司模板成文 | `软件需求列表-成文.xlsx` | 标准化交付物 |
| 澄清清单 | `clarification_questions.xlsx` | 对外或内部澄清 |
| 研发规格目录 | `engineering_requirements/` | 最终研发规格及其人读文件 |

新的最终交付物必须先在产物注册表中登记，不能仅凭文件扩展名写入根目录。

用户自行放入根目录的未知文件保持原样；工具不得自动移动或删除它们。

### 5.2 内部产物分类

| 目录 | 典型内容 |
|---|---|
| `.ratomizer/pipeline/` | `blocks.jsonl`、`chunks.jsonl`、表格单元格、AI 需求、质量报告、分析 JSON、内部 Markdown、`document_pages/` 批注页图 |
| `.ratomizer/state/` | `review_states`、`ai_review_states`、Claim 账本、队列、裁决事件、结构覆写、检查点及相关锁 |
| `.ratomizer/cache/` | 抽取缓存、审查缓存、规格富化缓存及其他可重建缓存 |
| `.ratomizer/logs/` | `run.log`、LLM trace、诊断日志 |
| `.ratomizer/stages/` | `run_manifest.json`、`_stages/`、部分结果、阶段指纹、恢复台账 |

文件归类必须由统一注册表确定，业务模块不得自行猜测目录。

## 6. 统一产物路径契约

新增结果包模块，集中负责：

- 布局探测：`legacy_flat` 或 `package_v1`。
- 逻辑产物到物理路径的映射。
- 根目录最终交付物发布。
- 完成标志的初始化、提交和校验。
- 旧版根目录读取回退。
- Windows 原子替换和文件锁重试。

建议公开的最小接口：

```python
detect_result_layout(root) -> ResultLayout
initialize_result_package(root, run_context) -> ResultPackage
artifact_path(root, artifact_id, *, for_write=False) -> Path
publish_deliverable(root, artifact_id, source_path) -> PublishedArtifact
commit_analysis_completion(root, completion) -> ResultPackage
record_analysis_failure(root, failure) -> ResultPackage
load_result_package(root, *, verify=False) -> ResultPackage
```

所有受治理的文件使用逻辑 `artifact_id`，而不是在不同模块中重复拼接文件名。

读取规则：

1. 有合法 `result-package.json`：按 `package_v1` 路径读取。
2. 有损坏或不支持版本的 `result-package.json`：大声失败，不降级猜成旧版目录。
3. 没有完成标志：按旧版扁平路径读取。

写入规则：

1. 新桌面任务默认初始化 `package_v1`。
2. 已有新版目录继续按新版路径写入。
3. 已有旧版非空目录保持旧版写法，除非用户以后显式执行迁移。
4. 空目录可由桌面任务初始化为新版结果包。

## 7. `result-package.json` 契约

示例：

```json
{
  "schema": "ratomizer-result-package/v1",
  "layout_version": "result-layout-v1",
  "package_id": "RPK-...",
  "analysis_status": "completed",
  "active_attempt": null,
  "last_attempt": {
    "run_id": "RUN-...",
    "status": "completed",
    "finished_at": "2026-08-02T12:30:00Z"
  },
  "input": {
    "display_name": "standard.docx",
    "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "sha256": "sha256:..."
  },
  "analysis": {
    "run_id": "RUN-...",
    "started_at": "2026-08-02T12:00:00Z",
    "completed_at": "2026-08-02T12:30:00Z",
    "requested_stages": ["atomize", "ai-extract", "requirements-analysis"],
    "completed_stages": ["atomize", "ai-extract", "requirements-analysis"],
    "completion_evidence": [
      {
        "artifact_id": "run_manifest_snapshot",
        "path": ".ratomizer/stages/completions/RUN-.../run_manifest.json",
        "sha256": "sha256:..."
      }
    ]
  },
  "workspace": ".ratomizer",
  "deliverables": [
    {
      "artifact_id": "document_annotation",
      "path": "document_annotation.html",
      "media_type": "text/html",
      "bytes": 7329636,
      "sha256": "sha256:..."
    }
  ],
  "tool": {
    "version": "0.1.0",
    "output_layout_version": "result-layout-v1"
  },
  "warnings": []
}
```

约束：

- 根标志不记录 API key、模型密钥或其他凭据。
- 根标志只记录输入文件显示名称和哈希，不暴露机器绝对路径。
- 所有相对路径必须位于结果包根目录内，禁止 `..` 和路径穿越。
- `deliverables` 只登记已经原子发布成功的文件。
- `analysis_status` 仅表示自动分析状态，不表示人工审核状态。
- `active_attempt` 只描述当前更新尝试；目录已有已提交完成结果时，新尝试不会提前抹掉该结果。
- 新尝试的输入身份写入 `active_attempt.input`；顶层 `input` 始终指向最后一次已提交完成结果，只有新尝试成功提交后才切换。
- 完成证据必须按 `run_id` 冻结到 `.ratomizer/stages/completions/<run_id>/run_manifest.json`，不能引用会被后续运行覆盖的活动 manifest。

## 8. 完成状态机

### 8.1 首次运行

1. 桌面任务在任何分析写入前初始化结果包，状态为 `running`。
2. 内部产物写入 `.ratomizer/`。
3. 最终交付物先完整暂存并备份旧版，随后在发布事务内替换根目录文件。
4. 自动分析任务成功且完成证据可校验后，原子提交 `completed`；marker 提交失败时整批回滚交付物。
5. 捕获到失败或取消时，记录 `incomplete` 和失败摘要。
6. 进程崩溃导致标志停在 `running` 时，下次打开显示“上次运行中断”，不得视为已完成。

### 8.2 已完成目录再次运行

已有完成结果不能因一次失败的更新尝试而被抹掉。

- 标志保留最后一次已提交完成记录。
- 新运行写入 `active_attempt`，但在成功提交前不替换 `analysis` 和已发布交付物清单。
- 新运行成功后替换已提交完成记录。
- 新运行失败时清除活动尝试、保留旧完成结果，并在 `last_attempt` 中记录“最近更新失败”。

### 8.3 审核与导出

- 接受、拒绝、批注、翻译和 Claim 裁决只修改 `.ratomizer/state/`。
- 审核操作不修改 `analysis_status`。
- 重新生成批注 HTML 或其他交付物时，可更新交付物清单与哈希，但不得把 `completed` 改回 `running`。

## 9. 完成证据与完整性

完成标志不能只依赖“某个文件存在”。提交 `completed` 前至少验证：

1. 本次自动分析顶层任务返回成功。
2. 请求执行的自动阶段均有成功终态。
3. `run_manifest` 或等价阶段台账可以解析且与本次 `run_id` 一致。
4. 主需求分析产物存在并通过基本 schema 校验。
5. 已登记交付物已经原子发布完成。

打开目录时提供两级校验：

- 默认快速校验：标志 schema、状态、相对路径和完成证据文件存在。
- 显式完整校验：重新计算完成证据和最终交付物 SHA-256。

哈希不一致时显示“结果文件已被修改”，但不得静默改写或自动恢复。

## 10. 人工审核进度

审核进度继续由权威状态文件派生，不写入根标志，避免每次裁决都重写 `result-package.json`。

新版目录中的权威审核文件存入 `.ratomizer/state/`，包括：

- `review_states` 和 `review_state_events`
- `ai_review_states`
- Claim review events、ledger、queue、attempts
- 结构候选裁决和补抽状态
- 批注、翻译及澄清处置状态

打开完成结果时，UI 分别显示：

- 自动分析：已完成 / 未完成 / 上次中断 / 旧版结果
- 人工审核：已审核数量 / 总数
- 最近审核时间

人工审核未完成不阻止打开、查看或继续裁决。

## 11. 最终交付物发布

最终交付物不由文件扩展名自动识别，而由生产阶段显式登记。

发布流程：

1. 生产阶段先在内部目录生成完整文件。
2. 在 `.ratomizer/stages/result-package-publications/<transaction_id>/` 同卷暂存全部新版交付物，并备份即将替换的旧版根文件。
3. 校验暂存文件可读，计算大小和 SHA-256，并写入 `.result-package-publication.json` 事务日志。
4. 使用 `os.replace` 把暂存文件发布到根目录，按既有 Windows `PermissionError` 重试纪律处理。
5. 最后原子更新 `result-package.json` 的交付物清单和完成记录。
6. marker 提交成功后删除事务日志和备份；若清理被中断，下一次写操作按 target marker 哈希幂等收尾。

若发布失败：

- marker 尚未提交时，按事务日志恢复全部上一版根交付物，不允许留下半新半旧目录。
- 不登记本次交付物。
- 在内部日志和标志警告中记录失败。

## 12. 桌面端识别与交互

“打开已有结果”按钮的目录识别顺序：

1. 合法新版标志且自动分析完成：直接连接审查会话，显示“自动分析已完成”。
2. 合法新版标志但运行中断或未完成：允许打开可用内容，明确显示未完成状态，不冒充完整结果。
3. 无新版标志但命中旧版产物：作为“旧版结果”打开。
4. 存在损坏新版标志：拒绝自动降级，提示标志损坏。
5. 普通空文件夹或无关目录：提示“不是需求分析结果目录”。

最近结果列表增加状态标签：

- `已完成分析`
- `分析未完成`
- `上次运行中断`
- `旧版结果`
- `目录已移动或删除`

## 13. 旧版兼容与迁移

### 13.1 读取兼容

旧版目录继续使用历史根路径读取，API、审查和裁决行为保持不变。

### 13.2 写入兼容

在旧版非空目录上继续审核或生成交付物时，不自动创建虚假的新版完成标志，也不自动移动内部文件。

### 13.3 显式迁移

“整理为新版目录”属于后续独立功能。迁移必须具备：

- 迁移计划和文件清单
- 原目录备份或可逆日志
- 同卷原子提交
- 崩溃恢复
- 迁移完成后的哈希复核

本设计的首版不实现该操作。

## 14. CLI 与冻结回归纪律

为避免一次性打翻机器接口和冻结 golden：

- 桌面新运行首先启用 `package_v1`。
- 直接调用底层函数且未初始化结果包时，继续使用旧版扁平布局。
- CLI 首阶段保留 `legacy_flat` 默认，可显式选择 `package_v1`；完成兼容验证后再单独决定是否调整默认值。
- golden 基线目录不迁移、不重生成、不修改。
- 路径布局变化必须使用独立 `OUTPUT_LAYOUT_VERSION` 和结果包 schema 版本，不借用语义规则版本。

## 15. 并发、锁与崩溃恢复

- `result-package.json` 使用跨进程锁、临时文件和 `os.replace`。
- 多交付物发布使用同一事务日志、同卷暂存和旧版备份；普通异常立即回滚，进程硬中断由下一次写操作在同一锁内恢复。
- Windows 读者阻塞替换时使用既有短重试策略。
- GET 和只读打开操作不得恢复或提交未完成写入。
- 只读识别发现未完成发布事务时必须 fail-closed，不能把部分发布目录显示成正常完成结果。
- 恢复只能由桌面任务、启动维护或显式维护 API 在写锁下执行。
- 审核状态锁移动到 `.ratomizer/state/` 后仍保持原有锁序。
- 完成标志更新必须在最终交付物发布之后，避免标志先于文件出现。

## 16. 测试与验收门禁

### 16.1 确定性单元测试

- 新目录初始化生成 `running` 标志和内部目录。
- 自动分析成功后生成 `completed` 标志。
- 自动分析失败或取消不得生成虚假完成状态。
- 崩溃留下的 `running` 标志被识别为中断。
- 人工裁决不改变自动分析完成状态。
- 重新导出交付物只更新交付物哈希。
- 多交付物发布中途失败、marker 提交失败均恢复旧文件与旧 marker。
- 硬中断留下事务日志时，下一次写操作恢复旧交付物后再开始新尝试。
- 损坏标志 fail-closed，不降级为旧版。
- 路径穿越和绝对路径被拒绝。
- 未登记的工具产物不得写入根目录。
- 用户未知文件不得被移动或删除。

### 16.2 兼容测试

- 旧版目录仍可打开、审核和继续保存进度。
- 新版目录可关闭应用后重新打开并恢复审核进度。
- 最近结果列表正确区分新版、旧版、未完成和缺失目录。
- API 所有受影响端点同时覆盖 legacy 和 package_v1。

### 16.3 端到端测试

真实最小文档执行：

1. 桌面任务启动。
2. 内部产物全部进入 `.ratomizer/`。
3. 根目录只出现登记的最终交付物、摘要和完成标志。
4. 关闭并重新打开桌面应用。
5. 使用“打开已有结果”直接进入审查工作台。
6. 完成一次人工裁决。
7. 再次重启后裁决进度保持。

### 16.4 回归门

- 后端全量 `unittest` 通过。
- 前端 Vitest、`vue-tsc` 和 Vite build 通过。
- agent_eval 四类指标不回退。
- golden 六项零漂移。
- `git diff --check` 通过。

## 17. 分阶段落地

1. **结果包契约层**：新增 schema、布局探测、原子标志和产物注册表。
2. **桌面识别层**：打开已有结果、最近结果和状态展示改用结果包契约。
3. **内部路径层**：按注册表把内部文件迁入 `.ratomizer/`，保持 legacy 回退。
4. **交付物发布层**：根目录最终文件统一走原子发布和哈希登记。
5. **审核恢复层**：验证新版 state 路径、锁序、Claim 账本和恢复机制。
6. **端到端与打包验收**：真实文档、重启恢复、旧目录兼容、portable 包验证。

每一步必须在对应测试门通过后进入下一步，不允许用一次性批量搬移替代路径契约。

## 18. 验收结论

满足以下条件才算完成：

- 新桌面任务成功后根目录存在合法 `result-package.json`。
- 工具能确定性显示“自动分析已完成”。
- 人工未审核不影响完成状态，审核进度可跨重启恢复。
- 根目录不再出现工具生成的账本、缓存、锁、日志和中间 JSONL。
- 所有内部文件均位于 `.ratomizer/` 的受控目录中。
- 旧结果目录仍能正常打开和继续审核。
- 中断、损坏或部分输出不会被误识别为已完成。
