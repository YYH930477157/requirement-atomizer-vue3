# 代码审查问题清单（d1fdf1c..3a75d8f）

> **2026-08-03 补充（实测新发现，已修复）**：打包实测发现比 I5 更严重的自伤 bug——桌面端只读 `summary` 探测会在被预览目录的根留下 `run.log`，而 `run.log` 在 `_LEGACY_SENTINELS` 中，导致**任何被界面看过一眼的新目录**都被 `initialize_result_package` 误判为 legacy_flat、永远拒绝开工（后端日志实测复现）。修复（未提交，在工作区）：① `result_package.py` 哨兵清单剔除 `run.log`/`run_manifest.lock`/`llm_trace.jsonl` 偶发文件；② `desktop_tasks.setup_run_logging` 新增 `allow_root_files`，`summary` 预览空目录时不在其根留痕。回归测试：`test_incidental_log_files_do_not_mark_directory_as_legacy`、`test_summary_preview_of_empty_dir_leaves_no_files`、`test_summary_preview_then_result_package_start_succeeds`。I5 的 legacy 目录 UX 硬墙问题仍然存在，未修。

- 审查日期：2026-08-03
- 范围：`git pull` 拉取的 9 个提交（95 文件，+21486/-1680），四条工作流：结果包（result package）、表格结构与单元格闭环（table-structure）、claim-ledger 硬化、UI/desktop 会话重开。
- 验证基线：全量后端 `python -m unittest discover -s tests` **2516 例 OK**（skip=20，为预期的机器本地/golden 跳项）；各焦点测试文件单独复核亦全绿。
- 总体结论：锁 + 原子替换 + PermissionError 重试约定全程遵守；版本 bump 纪律抽查全部到位且均进入缓存指纹；provenance/反幻觉未见违规；schema 变更向后兼容。存在 **1 个阻断项** 必须修复后方可视为完成。

## 阻断

### B1. API 启动的 claim 恢复闸在 package_v1 布局下静默失效

- 位置：`api_server.py:2249`、`api_server.py:2200`（`run_claim_startup_maintenance`）
- 问题：两处都用裸路径 `(output_dir / "claim_generation.meta.json").is_file()` 做闸门。package_v1 布局下 `output_dir` = `.ratomizer/pipeline`，而该文件经 `claim_artifact_path`（`claim_artifacts.py:114` → `governed_artifact_path(..., category="state")`）落在 `.ratomizer/state/`。
- 后果：所有 package_v1 目录的 API 启动维护被静默跳过（返回 `publication_skipped: claim_generation_unavailable`），AGENTS.md 指定的"启动维护恢复 claim 付费工作（outbox/WAL）"职责在"重开已完成结果"这条核心路径上永远不执行；且是静默跳过而非 fail-closed。
- 修法：两处闸门改用 `claim_artifact_path(root, CLAIM_GENERATION_META)` 或 `governed_artifact_path(root, name, category="state")`。

## 重要

### I1. 只读命令触发发布与恢复写

- 位置：`desktop_tasks.py:2096`（main 末尾）
- 问题：`publish_registered_deliverables(package_root)` 对每个成功命令无条件执行，包括只读的 `summary`（Electron `task:summary` → `getOutputSummary`，`App.vue:restoreOutputContext` 每次打开会话都会调）。发布会先做 `_recover_publication_unlocked`（恢复/清理中断事务）、重写 marker、重哈希并复制全部交付物（merged_spec.xlsx 等大文件）。
- 依据：spec `docs/superpowers/specs/2026-08-02-result-package-layout-design.md` §15 明确"GET 和只读打开操作不得恢复或提交未完成写入"。
- 修法：仅对会改变交付物的命令（CHAIN_ORDER + import/fold 类）发布；`summary` 走纯读。

### I2. 发布异常未兜底，成功被掩盖成崩溃

- 位置：`desktop_tasks.py:2096`
- 问题：发布调用在 try/except 之外：锁超时（15s）、磁盘错误、journal 损坏等都以裸 traceback 退出（非 JSON envelope，违反 `docs/cli-contract.md`），而此时 run_manifest 已记 `ok`——用户看到失败但阶段其实成功。spec §11 要求发布失败"在内部日志和标志警告中记录"（marker `warnings[]` 字段存在但全代码无任何写入点）。
- 同类问题：main 前置的 `detect_result_layout(original_out)`（`desktop_tasks.py:1995`）在残留发布 journal 时抛 `ResultPackageCorrupt`，对所有桌面命令直接 traceback；`update_run_manifest` 在 `try` 之外调用 `load_result_package`（`desktop_tasks.py:1244-1254`），marker 损坏时同样裸 traceback 崩溃，戳破"写失败不阻断"契约。
- 修法：发布包 try，失败降级为 payload warning + 日志；前置探测与 lineage 读取同样包一层输出结构化错误。

### I3. 重跑失败不保留已提交交付物，与 spec §8.2 冲突

- 位置：`result_package.py:791-879` + `desktop_tasks.py:2096`
- 问题：设计承诺"新运行失败时保留旧完成结果"。但每个中间阶段命令结束都会发布：根目录交付物物理文件和 marker 的 `deliverables` 清单在 attempt 提交前就被新运行的产物替换；`record_analysis_failure` 不回滚它们。失败后 marker 状态：`analysis`/`input` 描述上一次 committed 运行，`deliverables` 却是失败的新运行的文件，且 `verify=True` 全部通过——漂移静默。`test_failed_rerun_preserves_previous_committed_completion` 只校验 marker 字段、未覆盖交付物，漏掉了这个面。
- 修法（二选一）：发布推迟到 `commit_analysis_completion` 时一次性做；或失败时按 committed 清单快照恢复根交付物（发布事务已有 backup 机制可复用）。

### I4. mixed 表事实列非 marker 格静默掉出 claim 面，守恒审计全绿

- 位置：`claim_catalog.py:965-977`（fact_header_names 整列剔除）+ `table_structure.py:1078-1120`（plan 只把 marker 格提为 cell leaf）
- 问题：mixed 组合表（参数表 + GET/SET 事实列）中，事实列里填 "optional"/"see note" 等非 marker 文本的格：不是 marker → 无 cell claim；不是 review 候选；不在 unsignaled/弱信号任何计数器；消费审计把它算作"行 own"（`claim_catalog.py:1137-1141` 只按坐标记账，不校验文本真的进了行 claim）→ audit 全零、accounting_status=complete。同一物理内容变成零 owner 且账本显示守恒——正是本变更声明要消灭的事故类型。DLMS 属性×服务矩阵里注释格是现实形态（marker_majority 允许至多一半非 marker）。
- 修法：剔除应按实际 cell leaf 坐标逐格进行（与 `multi_duty_fields`/`review_candidate_fields` 的 per-row per-column 口径一致），而非整列剔除；或在 catalog 侧对"事实列非 marker 非空格"补一类 review 候选。

### I5. legacy 目录重跑被硬拒，无回退

- 位置：`ui/src/App.vue:1603-1614`（`startResultPackage`）；`result_package.py:1007-1014`（`initialize_result_package` 硬拒）
- 问题：对旧版非空目录抛 "legacy flat output requires explicit migration"，该异常直接进入外层 catch，整个运行中止。升级前产生的输出目录重跑分析会全部失败。spec §6 写规则 3 与 §14 要求旧目录保持旧版写法继续可用。fail-closed 本身正确（不伪造迁移），但 App.vue 原样透传英文后端错误，UX 是一堵硬墙。
- 修法：捕获该特定错误后按 legacy 模式继续（跳过 package 跟踪），与 `window.ratomizerDesktop.startResultPackage` 不存在时的行为对齐；UI 至少识别该错误并引导"请另选新输出目录"。

### I6. partial 阶段 → 完成拒绝 → UI 报"运行失败"的语义错位

- 位置：`result_package.py:916-922`、`desktop_tasks.py:1298`、`App.vue:1775-1816`
- 问题：后端 fail-closed 是刻意的（`test_partial_requested_stage_cannot_claim_completion`）。但现状链路：ai-extract 部分章节失败（`_stage_completion_status` 记 "partial"，链本身按设计容忍并给出 stage_notes）→ `completeResultPackage` 抛错 → 外层 catch → `failResultPackage` + 界面"运行失败"。此前同样场景显示"运行完成 + 降级提示"。交付物都在、管道按既定容错语义成功，却呈现为整体失败。
- 修法：UI 区分"分析未完成（部分阶段降级）"与真正失败；或产品层面确认 partial 即失败的口径并改 stage_notes 文案。

### I7. AGENTS.md 未同步 result-package 寻址约定（文档/代码脱节）

- 问题：`result_package.py` 的 `governed_artifact_path` 已成为全部状态/缓存文件（59 处调用点）的强制寻址约定：package_v1 输出下 `review_states.jsonl`、`ai_review_states.jsonl`、锁文件、LLM 缓存全部迁到 `.ratomizer/{state,cache,logs,stages}`。但 624ea9d 只改了 CLAUDE.md 和设计文档，AGENTS.md 硬约束一节仍只字未提新布局。
- 后果：后续 agent 按 AGENTS.md 在输出根目录找 `review_states.jsonl` 会错位；新代码若绕开 `governed_artifact_path` 直写根目录会造成 package_v1 下读写 split-brain。另外冻结的 PySide6 `gui/`（`gui/requirements_model.py:27`）仍直读旧路径，打开 package_v1 输出会静默拿到空裁决，同样应记一句。
- 修法：AGENTS.md 增加 result-package 段落，明确"状态/缓存路径一律经 `governed_artifact_path`，禁止硬编码文件名拼路径"；"冻结 GUI 仅兼容 legacy 扁平输出"。

## 建议

### S1. result-package 子命令与 `/result-package` 端点的错误面

- `desktop_tasks.py:1919-1970` 四个新子命令异常即 traceback + exit 1，无 envelope；`docs/cli-contract.md` 未收录这些命令。
- `api_server.py:160-169` 的 `/result-package` 对 `detect_result_layout`/`load_result_package` 无 try/except，marker 损坏或残留 journal 时连接被直接掐断而非结构化 503。

### S2. `getResultPackageStatus` 全链路死代码

- `main.cjs` handler、`preload.cjs`、`env.d.ts` 都暴露了 `task:result-package-status`，但渲染端从未调用（状态芯片由 `applyResultPackageState` 从其他 payload 喂）。要么接线要么删除——白留一条 IPC 暴露面。

### S3. `_safe_relative_path` 两个边角

- 位置：`result_package.py:323-330`
- 值为 `"."` 时 `PurePosixPath(".").parts` 为空，`parts[0]` 抛 `IndexError`（绕过 `ResultPackageCorrupt`）；盘符相对路径 `"C:foo"` 的 `parts[0]` 不以 `":"` 结尾而漏检（后续 `relative_to` 大概率兜住，但这是 spec §7 路径穿越防线的唯一关口）。建议：空 parts 显式拒绝；任何含 `":"` 的首段直接拒绝。

### S4. schema 与加载校验不一致

- 位置：`result_package.py:_validate_package`
- 不校验 `package_id`（存在性/`^RPK-` 模式）、`tool`、`warnings`，也不拒绝未知顶层键；`schemas/result_package.schema.json` 全部 required + `additionalProperties: false`。代码写出的 marker 永远合规，但手工/外来 marker 可通过代码校验却不符合已发布 schema。建议加载侧直接用 Draft202012Validator，或补齐 `_validate_package`。

### S5. `verify=True` 全哈希校验未接入任何生产路径

- spec §9 的"显式完整校验"（重算证据+交付物 SHA，不一致显示"结果文件已被修改"）只在测试里用；`classifyOutputDir` 与 `/result-package` 都只查存在性。属 spec 功能缺口。

### S6. `governed_artifact_path` 在只读路径上建目录

- 位置：`result_package.py:240`
- 无条件 `mkdir(parents=True, exist_ok=True)`，包括 `read_*_snapshot_readonly` 这类自称"无 sidecar 副作用"的读取路径——只读 GET 会在盘上创建 `.ratomizer/<category>` 空目录，与"GET 路径字节不变"的口径小冲突。建议把建目录下沉到写路径。

### S7. `recordRecentSession` 无跨进程锁

- 位置：`ui/electron/main.helpers.cjs:517-538`
- tmp+rename 原子写正确，但应用无 `requestSingleInstanceLock`，双实例并发登记会 last-writer-wins。stakes 低（userData 应用级历史，损坏自愈），可接受；建议加注释说明这是有意取舍，与仓库"共享状态必锁"口径对齐。

### S8. 打开已有结果失败时误杀当前会话

- 位置：`ui/src/App.vue handleOpenExistingOutput` 的 catch 调 `disconnectReviewSession()`
- 用户只是选错目录，主进程里原 API 会话仍在跑，渲染端却主动断开，需手动重连。失败路径不应动现有会话状态。

### S9. `LLM_ATTEMPT_POLICY_VERSION` 未 bump 缺显式声明

- 位置：`llm_client.py:1029`
- 新增 `request_succeeded` 分支（2xx 后本地 checkpoint/trace 失败不再重发 HTTP）——直接改变 provider attempt 次数的策略变化，而 `llm_attempt_policy()` 自述 "policy that can change provider attempts" 且该常量进入 no-ledger baseline lineage。产物内容不受影响，不 bump 可以成立，但仓库先例要求一句显式声明（目前缺失）。

### S10. `claim_reextract_attempts._append_unlocked` 整文件重写的 I/O 放大

- 位置：`claim_reextract_attempts.py:236`
- 每次 budget checkpoint（每次 LLM 调用至少 reserve/settle 两次）都重写整个 attempt 日志，长历史下为 O(n²) 磁盘写入。正确性无虞（锁内+原子替换），大文档多轮补抽时可观察。建议先记录为已知取舍；若成为瓶颈改追加写 + 启动时 compaction。

### S11. v6 已提交 generation 硬失败而非优雅迁移门

- 位置：`claim_artifacts.py:3010/4660`
- `artifact_protocol_version != v7` 直接 `raise ClaimArtifactError("stale claim artifact protocol")`，不走 `base_migration_required` 结构化返回。与 v5→v6 既有模式一致、测试钉住，属有意设计；但错误文案不含迁移指引，用户拿到裸 500 风格错误。建议 API/视图层映射为 `base_migration_required` 语义，或至少在消息中写明"需重跑 atomize"。

### S12. `spot_extract._deterministic_row_requirement` 物理行号公式依赖隐含连续性假设

- 位置：`spot_extract.py:92-100`
- `physical_row = header_row_count + len(title_row_indexes) + row_index` 仅在"标题/表头全部连续置顶"时成立（当前 `analyze_table` 确实保证，非现行 bug）。block 已存 `title_row_indexes`/`header_row_indexes`，可直接推导 data_row_indexes。另外行级 spot 入口对旧产物无 `base_migration_required` 门（cell 入口有），口径不一致。

### S13. `_cluster_boundaries` 死代码 + docstring 与调用方语义矛盾

- 位置：`parsers/pdf_parser.py:1661-1677`
- 链式聚类保证"簇中心过近返回 None"分支不可达；且 docstring 称 None = "证据自相矛盾"，调用方却把 falsy 簇映射为 `"none"`（证据不足，不置 needs_review）。若未来聚类实现变动使该分支可达，矛盾证据会被误标为无证据。建议删除死分支或改返 conflict。

### S14. xlsx 每个文件加载工作簿 3 次

- 位置：`parsers/xlsx_parser.py:31-34`（主视图 + formula 视图）、`:53`（`_merged_ranges_by_sheet` 第三次）
- 大 xlsx 上解析成本 ×3；formula 视图即使无公式也全量加载。建议合并：formula 视图可同时提供 merge ranges，省掉第三次。另 `_formula_cells_without_cached_values`（`:140`）max_row 有 `MAX_SHEET_ROWS` 截断、max_column 无上限，口径不齐。

### S15. `extract_units._is_group_header_evidence` 对 known-none merge 退回同值启发式

- `merge_ranges = normalize_merge_ranges(block.get("merge_ranges") or [])`；`if not merge_ranges: return True` —— `table_structure` 全模块刻意区分 `[]`（已知无合并）与 `None`（无证据），此处 `or []` 把两者坍缩：新 xlsx 无合并表里的同值数据行会被当分组标题从 section rows 剔除，与 leaf plan 口径分叉。内容不丢，故定建议级。修法：判 `block.get("merge_ranges") is None` 才走旧启发式。

### S16. 杂项

- `atomize.py:1871-1876` `extract_valued_matrix_facts` 函数体内联 import，`NOTE_HEADER_RE` 顶部已导入，重复。
- `claim_catalog.py:970-972` mixed 旧块回退现场重推导 fact columns，与 A 轨"旧产物禁止重推导"口径略不一致——属防御性分支，注释应说明为何此处例外。
- `classifyOutputDir`（`main.helpers.cjs:385`）在 JS 侧重新实现 marker 契约校验，与 Python 侧有漂移风险（目前是其子集，建议注释互相指向）。
- `claim_artifacts.py:2944`（`claim_verifier_attempt_scope` 退出兼容路径）：非 `swap_checkpoint` 路径存在测试 double 专用的 ownerless 窗口；`_cleanup_orphan_publication_backups_unlocked` 改 glob state 根后，旧版本遗留在 analysis 根的孤儿 backup 目录不再被清理。洁癖级，留注即可。
- `export_requirements.py:9` 把 `from result_package import ...` 插在 stdlib import 之间，纯风格。
- 既有问题（非本范围引入）：`App.vue:2127` `defaultOutputDir` 硬编码 `E:\Codex\...`，换机即失效，建议尽早参数化。

## 已核验无误的点（摘要）

- **锁与原子写**：`result_package.py` 全部 marker/journal 写经 `_package_write_lock`（`process_file_lock` 跨进程锁）+ 临时文件 fsync + `os.replace` 带 PermissionError ×8 退避重试；发布事务的 base/target marker 双哈希、中断后按 target 幂等收尾、反向回放恢复推演正确。`claim_reextract_attempts` 从裸 append 改为锁内全量原子替换（比旧实现更强）。
- **版本 bump 全套到位**：guards v17→v20、param-row-expand v2→v3、claim-catalog v5→v10、claim-annotation v13→v16（producer stamp `doc_annotation_export/v16-cell-claim-projection` 同步进 desktop chain stamp）、claim-artifacts v6→v7、claim-focus-adapter v1→v3、claim-queue v4/proposal v3、table-structure-v6（进 extraction_input_fingerprint / producer lineage / section cache / 迁移门）、ai-requirements-producer-lineage v3、candidate-decision v2 writer + v1 冻结回放。`DOC_FACSIMILE_VERSION` 未动（正确——facsimile 未改）。
- **schema 向后兼容**：claim-catalog v2 枚举含 v1 行；队列双版本显式 reader 契约（v3→proposal v2、v4→proposal v3）；candidate decision 注册表 v1/v2 双协议 replay。
- **replay/recovery/幂等**：budget outbox 恢复顺序（队列事件 → verifier WAL → unlink）任一断点崩溃后重放幂等；`_terminalize_stale` 统一 stale 终态且与状态机逐条吻合；attempt 日志 torn tail 有界窗口重读、伪造完整行立即拒绝。
- **反幻觉/provenance**：矩阵维度证据单源；A 轨合成四道闸；几何三态 ok/none/conflict 如实区分；无缓存公式 fail-closed；合并异文拒收；focus evidence 三角色分离（prompt_context 不得充当绑定依据）；table_cell claim 的 locator/span/semantic_context 全部确定性拼装。
- **守恒账本**：sheet 级覆盖计数器（dropped/multi-covered → parse_incomplete 硬失败）；cell 守恒审计六类 hard_fail_keys 联动 acceptance 与发布门；候选五类默认排除、可定位、pending 阻断 Ledger Ready。
- **Electron 侧**：recent-sessions 用 tmp+rename 原子写、损坏自愈不阻塞启动；`startApiServer` 串行化消除竞态；`dialog:open-output` 对损坏标志 fail-closed、`containedPackagePath` 拒绝绝对路径与 `..` 穿越；IPC 未开新权限。
- **打包**：`pyproject.toml` py-modules 已注册 `result_package`/`table_structure`；`build-electron-backend.ps1` 新增 pywin32 前置门禁（大声失败而非静默丢 COM 支路）。
- **out_dir 语义**：`desktop_tasks.py:2098` 把 `payload["out_dir"]` 还原为 package root，不会把 `.ratomizer/pipeline` 泄漏给 Electron 最近会话。

## 修复优先级建议

1. **B1**（claim 恢复闸静默失效）——必须最先修。
2. **I1/I2/I3**（发布时机与只读纪律）——一组围绕 `desktop_tasks.py:2096` 的设计偏差，I3 直接违反 spec §8.2，需做出明确决策（改实现或改 spec 并补测试）。
3. **I4**（mixed 表守恒盲区）——本变更声明要消灭的事故类型仍有残留面。
4. **I5/I6**（UX 硬墙与语义错位）——影响升级用户的第一体验。
5. **I7**（AGENTS.md 同步）——一行文档工作，防止后续 agent 踩坑。
