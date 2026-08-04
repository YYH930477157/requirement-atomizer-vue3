# CLAUDE.md — Requirement Atomizer 项目上下文

> 本文件供 Claude Code 在任何机器上自动加载。包含协作工作流、当前状态与关键决策。
> 状态快照截至 2026-08-02，里程碑推进后请同步更新本文件。

## 重大更新（2026-08-04）——实机修复清单三组集成（分支 `codex/repair-2026-08-04`，未提交）

- **结果包 / 会话**：API 每个请求重新确认 package root 与 analysis root，空目录启动后创建 `package_v1` 不再锁死旧根；Electron 对复用会话先做内容探测，管线或 completion 后强制重启 API。首次 partial attempt 在同一结果包写锁内终止 attempt、如实标记 `incomplete/partial` 并事务发布已有注册交付物；已有 completed 代后的 partial rerun 保留旧根交付物和 analysis，仅记录本次 partial；failed 仍不发布。原生 PDF 源路径失效时，仅在 marker 输入媒体类型、pipeline 输入格式、marker SHA、包内 `document_facsimile.pdf` SHA 与页清单 SHA 全部一致时使用包内副本。
- **成本控制**：`PROW-DET-*` 按来源表块走确定性目录分组，其他目录输入稳定按最多 30 条分批；functional catalog 截断只允许一次 token 升级，第二次截断/空响应回退确定性分组。审查仍逐 requirement 执行、`table_row` 仍强制审查；首轮 KB 证据收紧为 top-3、每条 300 字，`kb_search` 每 requirement 最多实际执行一次，`source_read` 上限 800 字，tool loop 上限 5 轮。版本面：`functional-catalog-v2`、`functional-synthesis-v8`、`m2-review-v3`、`llm-review-cache-v6`、`review-tools-v4`，旧缓存按指纹失效；本次明确修改 review prompt。
- **契约 / 生命周期**：结果包 marker 改用 bundled Draft 2020-12 schema 完整校验（含嵌套 `additionalProperties:false` 与 completion evidence `minItems:1`），并保留注册交付物语义检查；`extraction_in_progress` 通过 governed 只读路径读取 package-v1 stages/pipeline，不创建目录；GET dispatch 统一捕获 `ResultPackageError` 返回结构化 503。Electron 在 bootstrap 前持有 single-instance lock，并在 `before-quit` / `will-quit` 幂等清理 API 子进程。
- **验证**：后端全量 `2589 tests OK (skipped=26)`；前端 Vitest `204/204`；`npm run build` 通过；新分支代码读取主检出 frozen 输出的 golden `6/6`；实机结果包只读回放恢复 `available=true`、99 页、444 条批注需求、634 个块热区、2301 条 claim、1975 个 claim 区域。未修改 `golden_sets/` 或 frozen `out/`。

## 项目是什么

把技术标准文档（DOCX/XLSX/PDF）原子化为可审查的需求条目，**终点是装配成给研发团队的 DLMS/COSEM 实现规格**：
确定性解析 → 规则候选 → LLM 审查（OpenAI 兼容，本地/云端可切换）→ 专家工作台（**Vue3+Electron 桌面应用 + 本地 API**）→ 导出 / 装配实现规格（`assemble`/`compose`）。
CLI 契约见 `docs/cli-contract.md`（对接公司任务管理系统的接口承诺，exit 0/2/3/4，stdout 为 UTF-8 JSON 信封）。

## 协作工作流（重要）

1. **Claude 写修改方案**（带验收标准）→ 用户转交 ChatGPT/Codex 实现
2. **实现必须在隔离 git worktree**（分支 `codex/*`），审查通过前不合 main、不推送
3. **Claude 复查**：实测优先——mock HTTP 服务打故障场景、真实文档逐字节等价对比、打包产物在仓库外验证、GUI offscreen 截图
4. 用户决定合并；合并后在 main 跑全量测试（golden 六项只在 main 的 out/ 基线存在时执行）

> 2026-06-14 起「需求文档生成」轨道由 Claude 直接实现并自查（仍在 `codex/*` 分支、实测优先、用户决定合并、push 需用户同意）；解析等既有轨道沿用上面的 Codex 转交流程。
> 2026-06-27：**GUI 正式以 Vue3+Electron（`ui/`）为准，PySide6（`gui/`）冻结**；终点交付物（`assemble`/`compose` 实现规格）数据完整性修复由 Claude 直接实现并自查（同上轨道纪律）。
> 换机继续：项目上下文靠本文件 + `~/.claude/.../memory/` 自动加载；完整聊天 transcript 在 HOME `~/.claude/projects/<proj>/`，**不进代码仓**（含客户文档/业务细节，公开仓会泄密），如需带走走私有同步。

## 重大更新（2026-08-03）——review-2026-08-03 清单 24 项全修（分支 `codex/review-2026-08-03-fixes`，未提交）

> `docs/review-2026-08-03-pull-issue-list.md` 的 1 阻断 + 7 重要 + 16 建议全部核验坐实并按用户拍板方案分 5 个 PR 修复（`d050878`/`708e0fd`/`50524e2`/`2160705`/`045b99a`），每项先写失败 unittest 再改实现。

- **PR1 结果包事务与恢复（B1/I1/I2/I3/S1）**：API 启动 claim 恢复闸统一按 package root 寻址（`claim_artifact_path`），删除 api_server 裸路径闸门及 `ai_review_actions.py`/`review_state.py` 两处清单外同族裸路径——package_v1 下 `.ratomizer/state` 的 outbox/WAL 恢复不再静默失效。发布时机收口：summary/status 等只读路径不再触发发布；活动 attempt 只写 `.ratomizer/pipeline`，`commit_analysis_completion()` 验证全部阶段后一次性发布根交付物+marker；已完成结果上的写命令走显式 PUBLISHING_COMMANDS 白名单。布局探测/发布纳入异常边界，CLI 恒 JSON envelope；四个 `result-package-*` 子命令补结构化 exit code，`/result-package` 补结构化 503，`docs/cli-contract.md` 收录。
- **PR2 表格守恒与点解析（I4/S12/S15）**：mixed 表事实列不再整列剔除，改按实际 (row,column) cell-leaf 坐标剔除，事实列非 marker 文本格保留在 row claim，不能可靠归入则生成 excluded review candidate——`Voltage|230 V|required|optional` 的 optional 格有且仅有一个 owner，消费审计除坐标外验证 cell 文本确实进入 claim/candidate/context。spot_extract 物理行号改从 `title_row_indexes`/`header_row_indexes` 推导，行入口补 table_structure 版本门（与 cell 入口统一 `base_migration_required`）。extract_units 分组标题启发式只在 `merge_ranges is None`（无证据）时启用，已知无合并（`[]`）不再触发。**版本面**：`CLAIM_CATALOG_VERSION`→v11、`EXTRACT_GUARDS_VERSION`→v21、`SPOT_EXTRACT_VERSION`→v2——缓存指纹随行失效（重抽生效），golden 纯 A 轨零漂移，旧表格产物经版本闸返回 `base_migration_required` 不伪造迁移。
- **PR3 Legacy 与 partial UX（I5/I6/S2/S8）**：Electron `result-package-start` 先 `classifyOutputDir` 分流，legacy 目录按旧管线运行（不创建 marker/.ratomizer），Python `initialize_result_package` 保持 fail-closed；completion 新增稳定错误码 `requested_stage_partial`（exit 2），UI 显示「分析未完成（部分阶段降级）」不走通用失败路径；`handleOpenExistingOutput` 失败保留当前会话，`startApiServerExclusive` 改候选进程模式——新 API `waitForApiReady` 成功后才 `stopApiServer()` 接管；删除 `task:result-package-status` IPC（REST `/result-package` 为唯一状态入口）。
- **PR4 Marker、安全路径与只读纪律（I7/S3-S6/S11）**：`_safe_relative_path` 显式拒绝空 parts/`"."`/首段含 `:`（原 IndexError）；`_validate_package` 对齐 schema——拒绝未知顶层键、校验 `package_id`（`RPK-` hex）/`tool`/`warnings`。`load_result_package(verify=True)` 接生产：`GET /result-package?verify=1`（503 `result_package_modified`）、`result-package-status --verify`（exit 3）、「打开已有结果」显式校验；JS 不重实现哈希（单一权威在 Python）。`governed_artifact_path(..., for_write=True)` 默认不变，`package_artifact_path(..., for_write=False)` 死参激活，只读消费方（claim_views 5 处、api_server 2 处、desktop_tasks 3 处、claim_artifacts 4 处）翻转为不建目录。stale claim artifact protocol 新增 `ClaimBaseMigrationRequired`（子类化 ClaimArtifactError 保持既有 catch fail-closed），fold 返回结构化 dict，GET 视图与 `/claim-maintenance` 统一 503 `base_migration_required` 含「请重跑 atomize」。AGENTS.md 补 result-package 寻址纪律段。
- **PR5 性能与维护项（S7/S9/S10/S13/S14/S16）**：Electron `requestSingleInstanceLock` 单实例（锁拿不到即退出并聚焦既有实例，替代 recent-sessions 跨进程锁）。**`LLM_ATTEMPT_POLICY_VERSION`→v2** 并显式声明：request_succeeded 分支（有效 2xx 后本地失败不得重复 HTTP）改变 provider attempt 次数属行为面——v1 绑定的 no-ledger baseline lineage/verifier attempt 血缘一律失配，成本门保守重算，产物内容不受影响。attempt 日志规模基准落地（N=300 实测 366.8s、N=50 共 11.2s，O(N²) 取舍注释+宽上限测试，千级事件前不改实现）。`_cluster_boundaries` 删不可达"矛盾"分支，None 统一=无证据。xlsx 工作簿加载 3→2 次（merge ranges 复用首载 workbook），公式扫描补 `MAX_SHEET_COLUMNS=16384` 列上限、超界以 `xlsx_column_limit` fail-closed 计审计。杂项：atomize 内联重复 import 归并、classifyOutputDir↔_validate_package 互指注释、export_requirements import 归位、`App.vue` `defaultOutputDir` 弃硬编码 `E:\Codex` 改 Electron documents/userData 派生（bridge 不可用退输入文件同级目录）。
- **验证**：后端全量 **2570 tests OK (skipped=26)**（环境说明：本机用户目录为 C:/Users/YunHeYang，不存在 YYHwudi 路径下的历史样本文件——设 RATOMIZER_HISTORICAL_SAMPLE 指向缺失路径时 test_semantic_quality 两例 FileNotFoundError/available=False，属环境性非代码回归；不设 env 两例如实 skip 含于 skipped=26，与「机器相关路径换机需调整」纪律一致）；前端 Vitest 199/199，`npm run build`（vue-tsc+vite）通过；golden 6/6 零漂移（主检出复制 8 个冻结 baseline 文件实跑后清理）；claim-ledger schema golden 8/8；agent_eval 40/40、四类 1.0、unreviewed=0；`git diff --check` 与 py_compile 通过。未修改 `golden_sets/`、冻结 `out/` 或 LLM prompt；未推送，合并由用户决定。

## 重大更新（2026-08-03，二轮）——复审残余三项修复（同分支追加提交）

> 首轮 5 PR 合 main 后（`e2524c8` 已推 origin），复审在分支上确认 3 个残余问题，按同纪律修复（先失败测试后实现）。

- **R1 发布并发窗口（P1）**：`_maybe_publish_after_command` 的 active_attempt 检查原在写锁外——两桌面进程交错时新 attempt 可在检查与发布之间启动，旧命令把新 attempt 的 pipeline 内容发布到根交付物（审核确定性复现：根 summary.md 被 NEW-ACTIVE-ATTEMPT 污染）。修复：`_publish_registered_deliverables_unlocked` 在写锁临界区内复查 active_attempt，存在即 fail-closed；锁外快查保留为常见路径优化，竞态触发走既有 warning 降级通道。
- **R2 partial 状态持久化（P1）**：completion 因阶段降级拒签后 marker 原停留 running/running，重开结果误显「运行中」。修复：新增 `record_analysis_partial`（写锁内）——attempt 显式终止（`last_attempt.status="partial"`，schema 枚举同步扩），无既有完成代时 `analysis_status="incomplete"`，已有完成代字节级保留；attempt 语义明确为已终止不可续跑，重跑走新 attempt。marker 契约变更点仅 last_attempt 枚举，JS classifyOutputDir 不读该字段，无漂移面；`docs/cli-contract.md` 已同步。
- **R3 接管前内容探测（P2）**：候选 API 输出启动 JSON 即 stopApiServer——合法 marker + 损坏 atomic_requirements.jsonl 时 /requirements 断连，旧会话被白杀。修复：新增 `probeApiSessionContent`，接管前对候选实际 GET `/requirements?limit=1`（token 头 + 5s 超时）；缺失文件返回空数组 200 不误伤，探测失败只杀候选、旧会话保留。
- **验证**：后端全量 **2574 tests OK (skipped=26，环境性跳过同 PR1-PR5 口径）**；前端 Vitest 203/203（首次并发跑 1 例异步计数失败、单独/串行复跑均过——审核亦注明该既有测试时序不稳定）；`npm run build` 通过；golden 6/6 零漂移（复制主检出 baseline 实跑后清理）；agent_eval 40/40；无行为版本 bump（结果包运行时语义与桌面进程编排不进缓存指纹）。

## 热修复（2026-08-03）——结果包 legacy 哨兵自伤（main 工作区，未提交）

- **症状**：打包实测"新建空文件夹也无法开始分析"，报 `legacy flat output requires explicit migration`。
- **根因**：桌面端选目录时只读 `summary` 探测经 `setup_run_logging` 在目录根留 `run.log`；`run.log` 在 `_LEGACY_SENTINELS` 中，后续 `result-package-start` 据此误判目录为旧版扁平产物并 fail-closed。任何被界面预览过的目录都会被自己毒化。
- **修复**：① `result_package.py` 哨兵清单剔除偶发文件（`run.log`/`run_manifest.lock`/`llm_trace.jsonl`），实质产物哨兵不变；② `desktop_tasks.setup_run_logging(..., allow_root_files=False)` 用于 `summary` 预览空目录，不在其根留痕（产物目录写 run.log 的既有行为保留）。
- **验证**：新增 3 个回归测试（含 summary→start 真实链路）；`test_result_package`+`test_result_package_e2e`+`test_desktop_tasks`+`test_api_server` 共 191 例 OK。审查问题清单见 `docs/review-2026-08-03-pull-issue-list.md`（含 1 个未修阻断项 B1：API 启动 claim 恢复闸在 package_v1 下静默失效）。

## 重大更新（2026-08-02）——结果包完成标志与输出目录整理（分支 `codex/result-package-layout`，未提交）

- **新版结果包**：桌面新任务生成 `result-package.json`（`ratomizer-result-package/v1`、`result-layout-v1`）和 `.ratomizer/{pipeline,state,cache,logs,stages}`；根目录只发布注册表内的人读交付物、marker 和用户未知文件。旧扁平目录继续兼容读取，不自动迁移、不在拒绝时创建 `.ratomizer`。
- **完成语义**：自动需求分析请求阶段全部成功即 `completed`，人工审核不参与完成判定。新运行先写 `active_attempt.input`，顶层 `input`、`analysis` 和旧交付物清单在成功提交前保持上一完成代；失败重跑只记录 `last_attempt=failed`。每个请求阶段绑定 `attempt_run_id`，完成证据冻结到 `.ratomizer/stages/completions/<run_id>/run_manifest.json`，拒绝借用旧阶段状态。
- **交付物事务**：全部新版根交付物先同卷暂存并备份旧版，再写 `.result-package-publication.json` 事务日志、替换根文件、原子提交 marker。多文件中途失败或 marker 写失败会整批回滚；进程硬中断由下一次写操作按 base/target marker 哈希恢复，只读识别 fail-closed，不把半发布目录冒充已完成。
- **桌面恢复入口**：Electron 新增“打开已有结果”，严格区分 `package_v1`、旧版、损坏和非结果目录；最近结果显示完成/运行中/未完成/旧版状态，关闭应用后可直接重连本地审查 API，审核状态从 `.ratomizer/state/` 恢复且不改完成 marker。
- **影印与批注资源**：DOCX/XLSX/PDF 统一发布根目录 `document_facsimile.pdf`；页图保存在 `.ratomizer/pipeline/document_pages/`，根目录 `document_annotation.html` 使用可解析的相对路径引用隐藏页图。转换不可用时继续如实记录 unavailable，不伪造影印页。
- **验证与打包**：安装仓库已声明的 Windows `pywin32` 依赖后，后端全量 `2516 tests OK (skipped=25，worktree 无冻结 out/ 与环境型 GUI 项)`；随后只复制主检出冻结 baseline 的 8 个文件到 worktree，golden `6/6` 零漂移并清理复制件；agent_eval `40/40`、四类 `1.0`、`unreviewed=0`；前端 Vitest `185/185`，`vue-tsc --noEmit` 与 Vite build 通过。Electron 打包脚本新增 Office COM 依赖前置门禁，最终 portable 构建日志包含 `pythoncom/pywintypes/win32com` hooks 且无对应缺失警告。`golden_sets/`、主检出 `out/` 和 LLM prompt 未修改。

## 重大更新（2026-08-01）——表格单元格闭环终审加固（分支 `codex/table-structure-cell-closure`，未提交）

- **最终版本面**：`TABLE_STRUCTURE_VERSION=table-structure-v6`、`CLAIM_CATALOG_VERSION=claim-catalog-v10`、atomize stage impl `v12`、`CLAIM_FOCUS_ADAPTER_VERSION=claim-focus-adapter-v3`、`CLAIM_ANNOTATION_VERSION=claim-annotation-v16`、`EXTRACT_GUARDS_VERSION=guards-v20`、candidate policy `claim-coverage-candidate-v5-table-cell-exact-text`、artifact protocol `claim-artifacts-v7`、reextract attempt log `claim-reextract-attempt-log-v3`。旧表格产物必须经 `base_migration_required` 重建，不伪造迁移；成功输出与 LLM prompt 未改。
- **保守降级也守恒**：歧义、弱信号、无信号、拒收 marker 与未类型化冒号格不再静默丢弃或直接提升，而是进入结构候选侧车；专家可提升为 claim 或确认排除。`claim_structural_candidate_decisions.jsonl` 使用 v2 writer、兼容校验 v1 历史，撕裂尾/未知 schema fail-closed，待审候选非零时阻断 Ledger Ready。
- **候选裁决代际边界**：同一 claim 的终态唯一性绑定 `(document_generation_id, catalog_generation_id, claim_id, claim_hash)`；同代只能有一个终态，exact replay 仍幂等，而 A 代确认不会阻塞 B 代重新确认或 promotion。同步确认、同步 promotion、异步 preflight 与按 claim 查询统一使用完整 generation key，关闭 catalog 重建后的永久 409。
- **多次付费预算不回退**：预算 outbox 一旦持久化即标记 durable，后续 sink 失败不能由 `LLMRequestBudget.reserve()` 回滚；queue checkpoint 禁止累计 calls 下降，attempt reducer 对 calls 回退 fail-closed。恢复时重算并校验 snapshot→queue event、transition 幂等键及预算内部一致性。provider 已返回有效 2xx 后，本地 checkpoint 的 `OSError` 不再落入 transport retry；attempt JSONL 在操作锁内以完整 canonical prefix 原子替换，首 sink 在替换前强杀也只留下旧完整前缀；queue/verifier checkpoint owner 以 expected-owner CAS 原子交棒，并发 reserve 不存在无 owner 窗口。实测第二次 pre-call sink 失败后不重复 HTTP，queue/verifier/terminal 均保守保持 `2 calls` 与相同 token ceiling。
- **端到端闭环**：真实 DOCX 多义务格已覆盖 `atomize -> catalog -> publish -> fold -> queue -> execute -> annotation -> reload`；table-cell 定向补抽使用逐字格句作为义务本体，行头/列头仅作确定性语义上下文。默认排除候选单独投影，不进入付费队列。
- **最终验证**：设置历史样本环境变量后，后端全量 **2489 tests OK（18 项冻结 PySide6 GUI 环境跳过）**；本轮新增四个故障探针，覆盖 2xx 后 checkpoint 写失败不重发 HTTP、checkpoint owner 交棒期间并发 reserve、attempt 日志原子替换失败保留旧前缀，以及首 sink 在 `fsync` 后/`os.replace` 前强杀恢复且零重复 HTTP。golden **6/6** 零漂移；agent_eval **40/40**、四类均 `1.0`、`unreviewed=0`；前端 Vitest **174/174**，`vue-tsc --noEmit` 与 Vite build 通过。未修改 `golden_sets/`、冻结 `out/` 或 LLM prompt。

## 提交信息准则（每次推送必守）

每条 commit message 必须说清三件事，修复类提交按发现逐条列出"三段式"：

1. **原因**：为什么改——缺陷根因或需求来源（引用审查发现/问题单/真实案例）
2. **现象**：用户可观察到的症状——什么丢了、什么崩了、什么误导了，附 `file:line`
3. **解决方法**：修复机制（不是动作清单）——改了什么不变量、为什么这样修是对的

配套规则：

- 行为面变更（`EXTRACT_GUARDS_VERSION` / `*_PROMPT_VERSION` / `ENRICH_GUARDS_VERSION` / `LLM_REVIEW_CACHE_VERSION` / 策略指纹）必须在 message 中显式声明，并注明对缓存与 golden 基线的影响
- 推送前全量测试必须绿（`python -m unittest discover -s tests` + `cd ui && npm test`），message 不写未经测试验证的声明
- 已推送的历史不改写；信息写错了用新提交修正，不 amend/force-push

## 重大更新（2026-07-31）——Claim Ledger 加固复审修复（分支 `codex/claim-gate-hardening`，未提交）

- **HTTP 与重放契约**：`compat_limit`/`compat_offset` 按兼容分页语义校验，真实 HTTP 调用不再因字段名被拒；队列重放显式区分 v1/v2 writer，生产 proposal 使用 `expected_claim_effective_revision`，旧键只在 v1 受控兼容，双键冲突与未来 writer 一律拒绝。
- **付费结构覆盖恢复**：verifier 首次失败后重试成功可持久化已结算决策；checkpoint 绑定最新预算事件。base 已提交而 operation WAL 尚未写入时的真实子进程 `os._exit` 恢复，不重复抽取或付费，并恰好补齐 `base_rebuild_published`、`effective_folded`、`operation_succeeded` 三个 checkpoint。瞬时 `PermissionError`/产物读取失败保持 operation 开放并返回可重试错误，只有成功读取后确认 authority/binding 漂移才写不可逆终态。
- **队列/verifier 成本双写恢复（2026-08-01）**：`claim_verifier_attempt_scope` 不再顺序裸写两个 checkpoint sink；`.claim_budget_checkpoint.outbox.json` 先持久化同一累计预算快照与确定性 queue event，再幂等投影到 `claim_reextract_attempts.jsonl` 和 verifier WAL，删除 outbox 才完成 transition。pre-call/post-call 第二 sink 前 `os._exit` 均由 queue 执行或 `/claim-maintenance` 在写锁下补齐，HTTP 不逃逸/不重复，calls/tokens/usage 两侧一致；GET 只按 outbox 存在性失效缓存并 fail-closed，绝不代替维护路径写盘。`CLAIM_REEXTRACT_ATTEMPT_VERSION` 升至 `claim-reextract-attempt-log-v3`，成功产物与 LLM prompt 不变。
- **账本读取与有效快照**：review-event、structural-operation、attempt WAL 撕裂尾分别映射为结构化 503，不在 GET 中截断或修复；attempt 稳定读取覆盖完整有界窗口。effective refold seed schema 允许明确枚举的陈旧组件向量用于重建，正式读取仍严格要求当前版本。
- **缓存血缘与前端一致性**：`ai_extract` section cache 纳入 compliance/guards 版本，producer lineage 单独纳入完整 compliance/verify/framing/merge 版本，`ai-extract` stage producer 同时钉住 lineage schema 常量；`EXTRACT_GUARDS_VERSION` 升至 `guards-v18`。Claim Ledger 抽屉采用有界 R1→R3 重取，并在函数内拒绝 stale/detail-loading 的结构操作。
- **验证**：设置历史样本环境变量后，后端全量 `2372 tests OK (skipped=18)`；golden `6/6` 零漂移；`agent_eval` 四类均 `1.0`、`unreviewed=0`；前端 Vitest `170 passed`、`npm run build` 通过；`py_compile` 与 `git diff --check` 通过。未修改 `golden_sets/`、冻结 golden 输出或 LLM prompt。

## 重大更新（2026-07-30）——Claim Ledger 强化 8 修 + 4 增强（分支 `codex/claim-hardening-v5`；主检出全量 2336 tests OK、18 项冻结 PySide6 GUI 测试因依赖未安装而跳过、golden 6/6 零漂移、agent_eval 4×1.0、前端 vitest 167 + vue-tsc/Vite build）

统一版本迁移：**catalog v4→v5、effective snapshot v2→v3、effective artifacts v1→v2、effective ledger v1→v2、effective reducer v2→v3、queue v2→v3、candidate policy v3→v4-active-formal-gate、coverage runtime v10→v11**。旧 base 由版本闸（`base_versions_are_current`）检出后返回 `base_migration_required`，必须先经上游 extraction/base publication 重建，startup/POST `/claim-maintenance` 不会绕过该门禁；base 已为 current 时，API startup 或显式 maintenance fold 才迁移 effective v1/v2→v3，并把迁移记进 health（含确定性 `migration_id`）。冻结 golden held-out 按 `GOLDEN_CATALOG_VERSIONS` 回放 catalog-v4 身份哈希，baseline 未动。

- **修复 1（孤立 table_items）**：`_enumerate_leaves` 逐 item 计消费；新增 `orphan_table_item_count`/`multi_consumed_table_item_count`/`non_table_parent_item_count` 全部进 hard-fail（父块缺失/ID 错误/父块非 table/重复块四种探针均 incomplete）。
- **修复 2（effective 权威重建）**：新共享模块 `claim_effective_contract.py`——document revision、claim revision（`revision_inputs` 绑定 base row、真实 event prefix、linked target、expert overlay、完整 effective state 与版本向量）、effective metrics 单一实现；fold/publish/readonly loader 对同代 authority 均从 committed base + 真实事件前缀 + target/review authority 纯归约并逐字段比对，历史 authority 已推进时仍校验持久化 projection/state 哈希、事件前缀和版本向量，不一致 fail-closed。v1/v2→v3 映射及非 current base 的 `base_migration_required` 门禁均有真实迁移探针。
- **修复 3（rejected exact 屏蔽）**：formal exact 拆 `active_formal_exact`/`inactive_formal_exact`；只有 active 才跳过 semantic verifier，inactive 保留审计组不得阻止 active 语义候选（探针：rejected 逐字 + active 改写 → verifier 必被调用且可覆盖）。
- **修复 4（GET 写盘）**：GET `/claim-queue` 移除 attempt recovery（移入 API startup、POST `/claim-maintenance`、queue execute 写侧）；`OmissionConflictError` 单独映射 409/retryable，不落 ValueError 的 400；attempt log 新增 `read_attempt_log_stable` 双读稳定快照（瞬时 torn tail 重试、永久损坏 fail-closed）。
- **修复 5（fact 契约）**：effective projection 暴露 `active_resolution_facts`（hash/kind/polarity）+ 视图行 `required_supersedes_fact_hashes`（按 action）；POST 锁内经 overlay 重放重算 required set——缺一个、含 inactive/history hash、revision 变化全部 409；UI 不再推断 facts（探针：两条 active covered 后 excluded 必须 supersede 全部、旧 hash 重用拒绝、audit conflict 可闭合）。
- **修复 6（分页）**：queue total/limit/offset 必填 + compat omissions 独立分页（`compat_limit`/`compat_offset`）+ groups/events UI 自动拉全分页 + queue 独立 offset 分页控件（251 提案 + 150 事件逐页无遗漏无重复排序稳定）。
- **修复 7（结构覆盖续跑）**：新 `claim_structural_operations.jsonl` 哈希链操作日志（operation_started/override_registered/audit_appended/verifier_checkpoint/base_rebuild_published/effective_folded/终态）；retry 接受 `operation_id` 由服务端恢复原幂等请求；verifier_checkpoint 持久化已验证 groups 供 resume 复用——已完成付费步骤零重复计费（registry/audit/付费调用/base publication/effective fold 五处崩溃注入探针）；catalog 行暴露 `pending_structural_operation`。
- **修复 8（revision pin 一致性）**：pin 改变即禁裁决、清空旧详情并按新 pin 重载（`detailsStale` 门控 + `detailRefreshCycle` 防双载）；409 刷新保留裁决草稿但重取 row/groups/events/active facts（抽屉打开中切版本探针：新 row 不与旧详情同屏）。
- **增强**：迁移 health 写 `migrated_from_version`/`migration_id` 入 effective meta，fold 幂等补记（commit 后 health 前 `os._exit` 子进程探针）；queue preflight 返回 route/model/config revision（确认框展示 model，POST 携 `expected_route_config_revision`，配置变化 409）；`claim_views._context` 按 committed meta hash + 日志 stat + journal 存在性精确失效的只读快照缓存（六 GET 契约不变）。付费结构复核按 `attempted_calls` 序号判断确认后是否发生新的未知调用：同一次未知调用的保守结算不会重复触发 409，新增调用再次失去决策 checkpoint 时仍须重新确认。
- **旧 `gui/`（PySide6）未动**；golden_sets/、客户语料、LLM prompt、API key 处理、生产 readiness 门控均未触碰。

## 回归纪律

- `golden_sets/abnt_nbr_16968_v5/golden_summary.json` 是冻结基线；动它必须逐项写明原因
- 真实测试文档：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.docx`（机器相关路径，换机器需调整）
- 真实测试 PDF：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.pdf`（同目录文字层 PDF；旧 `D:\Codex\abnt_converted.pdf` 已失效）
- **Blue Book Ed.16 两 PDF**（P2 行为 RAG 语料，版权文件不进仓）：同目录 `Blue-Book-Ed-16-part-{1,2}-V1.0.pdf`；索引编译 `python -m blue_book_ingest --pdf <p1> --pdf <p2> --out out/bluebook`（约 2 分钟，产物 gitignored）
- 测试命令：`python -m unittest discover -s tests`（2026-07-19：**1344 tests** + ui `vitest 120` + vue-tsc；Python 3.14 / python-docx 1.2.0 / pdfplumber / openpyxl 已装；PySide6 未装时冻结 GUI 测试会 skip）。设置 env `RATOMIZER_HISTORICAL_SAMPLE="C:/Users/YYHwudi/Desktop/Canna-29/eval_assets/test18_functional_synthesis_sample.json"` 可消除历史守恒门的 1 个额外 skip（样本含客户词面，已外置且不进仓）；它不会消除缺少 PySide6 导致的冻结 GUI 环境跳过。
- golden 基线输出 `out/abnt_nbr_16968_atomizer_v5/` 已于 2026-07-04 重新生成（真实 ABNT docx + **三个 --kb + domain-pack**，缺 KB 会假漂移）；测试用例只做 unittest.TestCase（**pytest 未装**，模块级 `def test_*` 会被静默跳过）
- **Node 24 环境坑（2026-07-17 实证）**：`extract-zip`/yauzl 在 Node v24 上**静默空转**（报成功不写文件），electron 的 install.js 因此 exit 0 但 `dist/` 只留 1 个文件——`npm run desktop:dev` 或直跑 electron 报 "Electron failed to install correctly"，且 `npm install` 重装无效（同一破损路径）。修法：PowerShell `Expand-Archive` 把 `%LOCALAPPDATA%\electron\Cache\<hash>\electron-v*-win32-x64.zip` 解进 `ui/node_modules/electron/dist`，再写 `ui/node_modules/electron/path.txt`（内容仅 `electron.exe`）；此后 install.js 幂等跳过，electron 升版本需重做一次。**打包不受影响**（electron-builder 自带 7zip 解压）。根治 = Node 降回 LTS 22 或等 extract-zip 修 Node 24 兼容。
- **KB 双轨口径（2026-07-07 实证裁定，勿混淆）**：**运行时**（CLI 默认 + GUI 预设）已收敛为单编译库 `compiled_from_obsidian.json`（三个种子库的富化超集：86 条目 id 100% 继承、6 条真实探针零丢失、四库并载会重复命中）；**golden 基线**仍按"三个种子 --kb + domain-pack"冻结生成**不动**——重生成时若改单编译库会假漂移。两者用途不同，并存是刻意的。种子 JSON 保留作轻量演示/定向调试。

## 重大更新（2026-07-30）——四文档解析质量门实测全过 + 合成语料固化

- **实测（tools/run_doc_quality_gate.py）**：STO docx（434 需求、引句逐字 98.6%、零双份、82 页影印/271 行区）、TS pdf（99.4% 覆盖、合规 100%）、SBD pdf（91 表 635 需求、PROW-DET 89/89 逐字、截断升级生效）、EN 16314（88.8% 覆盖、合规 100%）。P0×8（分块/行展开/零双份/合规/影印/引用分流/确定性回归/聚合）+ P1×4（SBD 表型抽 10 无误分、EN 清单 135 项各自成块、影印点击一致性抽 5 无错位、EN 影印 60 页/1141 区）全部通过。
- **两个"可疑未覆盖"块裁定为标题**：BLK-000101/102 是表标题与附录标题（GOST 附录标注），非漏抽——启发式 requirement_like 误标，评审标记 non_requirement 即闭环。
- **合成语料**：`tests/test_synthetic_doc_corpus.py`——把真实文档实证过的关键场景固化为 7 个不依赖真实文档的用例（参数表行展开/逐字锚定/术语表边界/商务表防误判/映射矩阵后置/清单成块/覆盖不重复），全量 2257 tests OK。

## 重大更新（2026-07-29）——表格行级化 Phase 1+2（已合 main `42ac159`，guards-v17/ai-extract-v5/clarification-v8）

- **三封堵按冻结规格落实**（docs/param-row-extract-phase2-spec.md）：①chunk 表头重复（143 行表 3 chunk 全部带表头）；②参数表需求=确定性逐字行为准,LLM 叙述并入 `llm_narrative`+`merge_trace` 审计（STO 实测 409 需求零双份）；③行级 suspicion 按表块聚合（必答 135→188=1.39x ≤ 2x,每表一条汇总挂 row_details）。行级明细挂在表块 source_block 的 rows 子表（比规格更克制,放大面更小）。
- **STO 全链实测**：PROW-DET 引句逐字 47/47=100%；316 条需求带 source_row_index；block_id 序列 164 块逐字一致（红线）。
- **审核插曲（重要）**：验收钓出 main 上 source_spans 卡死 bug（非同事问题）——claim-ledger 对齐对 184k 字符表做字符级 SequenceMatcher（平方级挂死 25 分钟+）。热修为行级 diff（`cac9273`）已先行合 main；曾试 bump 对齐版本误伤 51 个 hash 绑定夹具,回退并留注（<20k 文本 opcode 逐字节不变,无需重冻结）。
- **验证**：同事 worktree 全量 2250 tests OK；合并后主检出 2250 tests OK、golden 6/6 零漂移（blocks 未变,B 轨行级化不触 A 轨比对）。

## 重大更新（2026-07-29）——影印行区占比切片互斥（已合 main，doc_annotation_export/v13；主检出 golden 6/6、全量 2064 tests OK）

- **用户实测驱动**：点术语表第 1 行却选中第 4 行——行 ⊂ 大解析块时每行同获整块大框,热区叠层栈顶通吃;另查 `_BLOCK_FIELDS` 无 headers,行渲染拿不到表头（验收/运行路径表现不一致的根源）。
- **修复**：行 ⊂ 解析块按行文本占比切 y 子段（切片天然互斥）；`_BLOCK_FIELDS` 补 headers；几何缓存 v3→v4（旧叠层行区不得复用）、版本戳 v12→v13。
- **STO 实测**：术语表 52 行区,第 1-4 行 y 切片互斥（384→492→552→588→703）。

## 重大更新（2026-07-29）——影印表格行级热区（已合 main `7eb7bbb`，doc_annotation_export/v12；验收记录见下方 2026-07-28 条目）

- **需求**：v11 块级几何回填后，docx/xlsx 影印页上整表是单块、`_pdf_block_zones` 明确不给表格发热区——表格不可点。本任务对齐原生 PDF 表格的行粒度体验：数据行行级热区 + 右栏行卡（原文/翻译/章节/「解析此行」）。
- **实现**：①`_resolve_pdf_geometry` 加 `row_geometry` 出参——无页号表格块逐行 `_row_render_line` 渲染后走与块级同款全局匹配（精确 → 双向包含 → 前缀 80 字符预筛 + 覆盖率模糊，边际 ≥0.05 宁缺不猜）；分组标题行（非空单元格全同值）/稀疏行（<2）跳过（与 spot_extract 同口径）；几何缓存 payload 加 `row_geometry` 字段（**version 3 不变**——纯增量字段，旧缓存缺字段时重算一次并回写，向后兼容）。②行级专用归一 `- `→`-`（转换 PDF 文本层换行拆连字符词 "self- diagnostics" vs docx "self-diagnostics"，STO 落空主因）——只在 `_match_row_regions` 内折叠，**不动 `_geometry_match_text`**（块级 v11 行为与缓存不受影响）。③`_pdf_block_zones` 对有几何的数据行发 `row_index` 热区（kind：引句逐字含行 → req / 关键单元格 ≥16 字符被引用块的需求覆盖 → covered / 否则 context）；整表块本身仍不发区。④`_pdf_context_records` 加行级键 `<block_id>#R<row>`（原文=渲染行，翻译按行文本哈希查 `_active_translations`，查不到如实空串）；应用内 payload 加 `row_context`（同源实现）。⑤静态影印热区带 `data-zone-key`（选中按行键，不再点亮整表）+ `table-row` 青色修饰类；`DocumentReview.vue` 行热区渲染 + 行卡（「解析此行」接现有 spotExtract）。
- **STO 实测（result4，删几何缓存重算）**：术语表 BLK-000061 54 行 → 52 行区跨 6-11 页（context 48/covered 1/req 3）；参数表 BLK-000098 143 行（27 分组标题行跳过）→ 100 行 119 区跨 13-62 页（covered 99/req 20，req 命中含 guards-v16 行展开条目 `PROW-DET-BLK-000098-R0017`）；16 行诚实落空（宁缺不猜：跨页断行/文本层差异）；缓存二跑 0.0s 直供。
- **验证**：新增 14 专项测试（`tests/test_facsimile_table_rows.py`：行几何跳过口径/前缀预筛模糊/边际不猜/连字符折叠/缓存回写与旧缓存回填/行区 kind 路由/同页 union/行记录键与翻译）；模板字面断言 2 处随行键改名（bid→zoneKey）；版本戳 doc_annotation_export/v11→v12（契约快照已同步）；全量 1738 tests OK（26 项环境 skip）+ ui vitest 138 OK + vue-tsc。

## 重大更新（2026-07-29）——Claim Conservation Ledger Phase 1.5（已合 main `6ecb81c`；闭环验证 + authority CAS + claim 裁决/定点补抽 mutation；主检出全量 2230 tests OK、golden 6/6；生产门控不切换）

- **架构闭环**：在 Phase 1 只读双写之上完成 mutation 安全层：review event v2 混合链、语义 revision/物理 write revision 分离、稳定快照 + CAS、typed expert evidence、queue v2 lifecycle、付费 attempt/WAL/budget 恢复、claim-mode targeted extraction、`requirements publication -> refresh base -> fold` 真正关闭路径，以及 catalog-generation-bound structural override。恢复/terminal replay 不要求 LLM 配置或 key，不重复 extraction、supplement 或 requirements publication；supplement 存在本身不等于 coverage，只有新 base 经 verifier/fold 后才可关闭 claim。
- **候选与验证解耦**：`CLAIM_CANDIDATE_POLICY_VERSION=claim-coverage-candidate-v3-stub-proposals`。stub 仍为 **0 LLM**，但保留已发现的 `independent_semantic/proposed` coverage group，claim 继续 `uncertain`，不会因 verifier 不可用而把候选丢掉；`source_quote` 只作来源定位，绝不伪装成正式 `produced_evidence`。历史 reopen 重放到新 base 的 uncertain/proposed 边界也已收口，避免制造不可重算的 closure 或同时保留互斥 invalid reason。
- **真实 B 轨 targeted extraction 演练**：机器本地副本 `C:\Users\YYHwudi\Desktop\Canna-29\phase15-btrack-rehearsal-20260729-v1`（不进仓）执行 focus-only extraction **1 call / 2238 tokens**；恢复重放保持 requirements 与 supplement 字节不变，且不重复发布。随后独立 ledger verifier **1 call / 544 tokens**，目标 claim 以 `independent_semantic` 和正式产品义务 evidence 关闭；该 evidence 不含 `source_quote`。成本门如实为 **fail**：调用增量 **100% > 25%**，token 增量约 **24.57% < 65%**；另有 3 个 open claim，因此 document readiness 仍为 false，未借局部成功切生产门控。
- **成本审计历史不改写**：旧 scope-bug attempt **3039 tokens**、初始 baseline **2214 tokens**、较早 verifier **476 tokens** 继续保留作完整付费链审计，不冒充上述 focus-only + 独立 verifier 的当前成功结果，也不得删除来美化成本。调用增量门失败使该演练文档继续 `document_ready=false`；Phase 1.5 的合并门要求记录真实成本和诚实终态，不允许绕过文档成本门，但不把该单样本的 non-ready 误写为实现未完成。
- **付费中断恢复演练**：`C:\Users\YYHwudi\Desktop\Canna-29\phase15-btrack-interrupted-paid-controlled-20260729-v1\interrupted_paid_rehearsal_report.json` 记录在真实响应后、supplement publication 前受控中断，实际 **1 call / 2276 tokens**；事件顺序为 started → reserved → settled → interrupted。requirements/supplements SHA 前后完全一致，恢复只投影 interrupted/open lifecycle，不自动重试、不重复 publication，已知 usage 不丢失。
- **结构性纠错演练**：`C:\Users\YYHwudi\Desktop\Canna-29\phase15-rehearsal-20260729-v2-structural-fp-controlled\structural_override_rehearsal_report.json` 使用受控 synthetic false-positive，完成 **0 calls / 0 tokens** override；`catalog_generation_id` 改变、`document_generation_id` 不变、freshness 重建成功，旧 revision 的再次写入被 stale-CAS 拒绝。真实 v2 中 35 条 `repeated_page_furniture` 均为翻译水印，全部保持原判，**没有为了演练而虚假 override**。Vue 入口默认“确定性重建 · 0 LLM”，只有用户显式勾选后才传 `allow_llm=true` 及正调用/token 预算；关闭或切换 Claim 会复位授权。
- **WP7 传播与批注演练**：`C:\Users\YYHwudi\Desktop\Canna-29\phase15-wp7-rehearsal-report-20260729-v1.json` 的 controlled synthetic fixture 以 **0 LLM** 验证 14 个 partial-input 传播点；producer-lineage mismatch 同样贯穿所有消费者，`incomplete_inputs` 仍只作 informational，不改变 readiness。annotation v13 的 text span、table row、table fallback，以及 optimized/original-PDF claim status parity 全部通过。
- **性能实测**：CPython 3.14 / Windows 当前机器，500-block synthetic 产生 1000 claims，连续 7 轮 `catalog + stub ledger` 的 p50 **0.0711s**、观测最慢轮（保守作 p95 nearest-rank）**0.0831s**，snapshot **3,294,136 bytes**，verifier **0 calls / 0 tokens**；低于既定 1s / 10 MiB 门限。
- **合并前专家复核修复**：Vue 非规范排除原因与后端五值枚举统一；A 轨 409 后重取 fresh 数据并保留审核草稿；base 正负冲突只有显式 supersede 两侧全部事实才可闭合，UI 同步提交完整冲突事实。WP1 已用真 `os._exit` effective WAL 矩阵、双 fold 字节级幂等、fresh 启动零写/零 LLM、A/B/automatic/fold/recovery 锁序与 hook 故障注入完成机制门禁。自动 authority merge 使用受保护 target + authority 快照 CAS，legacy 无 token 路径只留 health gap、不写权威事实；umbrella 协议版本进入公共常量与 health。`template-write`/`compose` 绑定 `ai_requirements.meta.json` 并 bump stage revision；queue LLM 执行必须由用户勾选、确认调用数与 token 上限；v1.1 规格已中文化并记录唯一批准延后项。
- **最终验证**：queue/review/ledger/input-completeness 相关组合 **172/172**，WP7 相关组合 **287/287**，annotation 模块 **95/95**，WP1/B5 核心四模块 **193/193**；各组可能重叠，只作专项证据而不相加。设置历史样本 env 后后端全量 `python -m unittest discover -s tests` **2226 tests OK (skipped=1 环境性)**；前端 Vitest **162/162**；`vue-tsc --noEmit + vite build` 通过；当前 worktree 中存在正确冻结 `out/` 基线，golden **6/6** 单独详细运行全部通过；`git diff --check` 无错误（仅 LF/CRLF 工作树提示）。Phase 1.5 分支验收门完成，未提交、未推送、未切换生产 readiness。

## 重大更新（2026-07-28）——Claim Conservation Ledger Phase 1（已合 main `617e1ce`；生产双写不切门控；主检出全量 2106 tests OK、golden 6/6）

- **分支与边界**：实现在独立 worktree 分支 `codex/claim-ledger-phase1`（提交 `c207d33` 合入）。Phase 1 仍是生产双写不切门控：旧 readiness/chain/golden 语义不变，claim queue 只生成 `needs_extraction` dry-run proposal，不修改 requirement/claim 权威数据，fold/reconcile/GET 全程零 LLM、零 verifier。
- **不可变 base + 可变 effective**：generation catalog/base ledger 与 effective ledger/queue/meta 分层；effective 三文件使用 publication journal、跨进程锁、原子替换与恢复协议。`claim_review_events.jsonl` 为 seq/hash-chain/幂等投影；A/B 两轨均读取完整 review history，支持 reject/reactivate、target missing/restored、validated group 内容寻址复用与 generation 隔离。
- **并发与审计门修复**：target JSONL 只读一次，同一份 bytes 同时用于 parse/hash；只读 authority 在 review snapshot 后复验 target presence/bytes，fold 再做 CAS 确认，阻断 hash/parse ABA。A/B authority 的完整坏行均保留为 `audit_gaps`；live GET 即时返回 `review_authority_changed`、`authority_audit_gap=true`、`document_ready=false`，但不写 health 或任何 sidecar。旧 generation/旧 claim hash 的 event 只保留在 append-only 原始日志，不泄漏进当前 view。
- **版本契约追认**：target-set `source_event_revision` 正式冻结为 `/v2`，同时绑定 `target_publication_revision` 与 `previous_transition_event_hash`，防止 `missing -> restored -> missing` 的第二次 missing 被幂等键吞掉；`CLAIM_VALIDATION_REUSE_VERSION` 首个发布值为 `claim-validation-reuse-v2`，绑定规范化 target fingerprint 与完整 semantic validation fingerprint，v1 仅为未发布的设计占位。
- **合并前专家门修复**：`/ai-extraction-status` 现从真实 `ai_extract_quality.json` 投影旧 `coverage_pct/core_coverage_pct`，新旧并列卡不再依赖 mock 死字段；stage reuse 只吸收 `ClaimArtifactError`，脏 legacy validation fingerprint 跳过复用并如实重验；health 记录 v1→v2 migration；A/B hook 故障注入证明权威裁决已提交且 `bridge_fold_lag+1`（并修复 A 轨局部 logging 阴影导致的 `UnboundLocalError`）。effective 域版本 bump、无关 claim revision 隔离、document revision 五要素、migration-required HTTP 503、全部新 effective `CLAIM_*` 不进入 extraction producer，以及 `claim_shadow_metrics.json` 字节不变均已有机制级断言。
- **消费面与入口**：六个只读 GET（catalog/ledger/coverage groups/metrics/review events/queue）共享 committed revision、固定分页与 200/503 契约；Vue3 新增 Claim Ledger 页面；clarification、run manifest 与批注导出增加 informational 摘要/块级三状态角标。CLI 与 desktop `claim-ledger-fold` 同时支持规格参数 `--out-dir` 和兼容别名 `--out`。新增模块及六份 schema 已进入 wheel。
- **真实 B 轨零 verifier 复演（机器本地副本，不进仓）**：878 claims；初始 v1 纯确定性 fold 到 v2 约 1.16s。选取一个真实 covered claim，执行 `covered → uncertain → covered`，产生 `target_invalidated`/`target_reactivated`，恢复时复用 1 个 validated group；verifier attempt/call/token 增量均为 0，attempt 日志 SHA-256 前后完全一致，且所有 LLM/verifier 入口均设失败哨兵。
- **500-block 冻结性能基线**：CPython 3.14.6 / Windows 10 / AMD64 / 8 CPUs；500 blocks、500 eligible claims、500 linked targets、2000 review history rows、2000 committed events。catalog p50/p95 = 0.0227s/0.0232s，base artifacts = 2.76 MiB；reconcile+fold p50/p95 = 3.603s/3.699s。可复算工作量为 history records 2000、link index inserts 500、candidate checks 2000、event index inserts 2000，无 `rows × all_links` 扫描。
- **最终验证**：后端全量 `2104 tests OK (skipped=7)`；前端 `145 tests` 全绿；`vue-tsc --noEmit + vite build` 通过；wheel checkout 外隔离安装/schema smoke 通过；`git diff --check` 无错误。最终独立审查复验 A/B ABA、audit-gap 六 view 零写入、旧代事件过滤与 CLI 契约后无 gating finding。
- **退出门已通过**：合并后主检出以既定三 seed KB + domain-pack 基线跑 **golden 6/6**，全量 **2106 tests OK（skipped=18 环境性）**。Phase 1 标记完成；生产门控仍不切换（Phase 2 经总纲 §9 全部条件后方可）。

## 重大更新（2026-07-28）——影印支路几何回填修复（已合 main，doc_annotation_export/v11+v12；主检出 golden 6/6、全量 1738 tests——首轮 1 个瞬时失败复跑两轮全绿，判定 Windows 抖动留痕）

- **实证缺陷链（STO result4）**：①几何锚定的"同页候选"假设对 docx/xlsx 全灭（块无 page_number，82 页文档仅 8 块有区）；②docx 扁平文本合并单元格展开重复（"3.1.1 | 3.1.1 | Req | Req"）与转换 PDF 文本层单次出现对不上，包含匹配全灭；③api 侧 normalize_text 吞掉行分隔使按行折叠失效；④全串包含对 184k 参数表过脆；⑤重构时丢了一行 `geometry[block_id] = regions` 赋值（插桩追了四层才现形）。
- **修复**：无页号块走全局文本驱动匹配——全局精确 → 全局包含（>8000 字符大表放宽为前缀 80 字符锚定）→ 边际模糊（最优-次优 ≥0.05 才落区，宁缺不猜）；`_geometry_match_text` 增加合并单元格折叠 + 相邻重复词折叠；几何缓存升 v3；版本戳 doc_annotation_export/v10→v11。
- **STO 实测**：有区块数 8→124/164、覆盖页 2→62；术语表归位第 6-11 页（此前错配 79 页）；单/三相参数表 47/50 区跨 15-64 页（点击表格行可正确定位右栏）。
- **验证**：新增 6 专项测试（折叠/全局精确/前缀锚/边际不猜/清晰最优）；全量 1724 tests OK。

## 重大更新（2026-07-26）——Claim Conservation Ledger Phase 0A/0B（已合 main `a08a60a`；shadow 双写不切生产门控；主检出全量 1986 tests OK、golden 6/6）

- **系统性分母**：新增确定性 `claim_catalog`，按句子、清单叶子、表格行和有界 table fallback 建立全量 claim；每个 eligible claim 只有一个 owner unit。heading/noise/reference 等标签不再充当需求候选过滤器，只有可复算的空内容、纯分隔符行和重复页饰可作结构性排除（`empty`/`separator_only`/`repeated_page_furniture`，与代码枚举一致；父子重复有运行时证明计数器）。
- **来源守恒**：parser 产物携带严格 raw→repaired alignment envelope，哈希、连续坐标、opcode 序列和注册变换规则均可重放校验。通用空白规则只允许 `clean_text` 同构的折叠/首尾裁剪，禁止 token 边界重排；PDF 词片/重复字形修复必须绑定当前 parser、repair version 与词表指纹并由修复器重放。alignment/policy/ruleset 同时进入 atomize producer、catalog generation 与 shadow freshness。
- **Shadow ledger**：verbatim 与跨语言 semantic coverage 分路；protected code/standard/number+unit/controlled term 预筛只做 reject，不能制造 closure；semantic verifier 按 owner unit 合批、proposal-blind，并逐项检查主体、情态、极性、数量、条件、范围及 target 是否形成自包含产品义务。共享 block 只作诊断提示，不作 closure 证据。
- **负向逃生口**：semantic non-normative 采用独立 proposal→proposal-blind verifier；原因、逐字证据及五项反义务/上下文检查全部一致才可 `excluded(semantic)`，缺证、失败或多轮分歧均保持 `uncertain`。`claim-negative-validator-v3` 还拒绝非 `true/false/null` 判定、缺失/额外/非布尔 checks 及判定与 checks 自相矛盾的 HTTP 200 响应，并计 operation failure。相同 runtime fingerprint 才复用 validated positive/negative，版本或模型配置变化只刷新 ledger，初抽 LLM 调用为 0。
- **账本图完整性补强**：semantic-negative 记录绑定 document/catalog/claim/runtime/input hash；publish/load/reuse 共用确定性校验，重算证据 span、请求独立性、五项 checks、runtime fingerprint 与 reducer 外层状态。低 `max_tokens` 路由的 freshness 与发布端统一先应用 extract 6144 下限，避免每次运行永久误判 stale。
- **提交与状态**：catalog/coverage/base/effective ledger 由 generation meta 最后提交并绑定源文件、requirements、review authority 和各产物哈希；Windows replace 带跨进程锁和 retry。stub/sample/partial、旧 parser provenance、失效 target 或 open claim 永不宣称 READY。
- **Phase 0 指标**：输出 verbatim、预筛、semantic candidate、正负 verifier 调用/token、无账本基线增量、兄弟 claim open/path 和 target invalidation。500-block 合成门 p50 约 0.031s，catalog+ledger snapshot 约 2.51 MiB（门限 1s/10 MiB）。匿名冻结集增至 7 个场景，含跨语言等价、同块部分覆盖、页饰、list/table/fallback 和独立负向复核。
- **验收**：合并后**主检出**全量后端 **1986 tests OK，18 skips**（含 `RATOMIZER_HISTORICAL_SAMPLE`），golden **6/6**；隔离 worktree 验收时全量后端 1986 tests OK，前端 **132 tests OK** 且 `vue-tsc + vite build` 通过；skip 均为环境性（GUI/本机资产），未冒充冻结 `out/` 回归覆盖。两份 PyInstaller spec 均真实构建；onedir `ratomizer.exe` 与 onefile Electron backend 的三个 Phase 0 子命令均完成 help 和实际 packet/import/acceptance smoke，冻结 PySide6 GUI 仅做启动 smoke；内嵌 claim 模块可解码，10 个 claim schema 与 held-out corpus 资源和源码逐字节一致。客户原文与新增本机路径不得进入仓库；审核身份/时间只允许随 synthetic held-out 裁决进入 hash-bound 历史，不得从机器本地客户审核包散落进其他仓内产物。
- **Phase 0 v14 退出证据（2026-07-28）**：顶层旧 test5/test10/test11 parser 资产缺 raw-span mapping，由其衍生的 v13 批次明确排除，不得刷新或验收；v14 改用当前 parser generation，三次 source accounting 均 complete，最终 attempt 分别为一次 `ledger_only + complete` 与两次 `cold + complete`，最终 operation failure 均为 0、usage 完整、无 extraction failure、无 oversized/coverage deferred。sanitized acceptance 合计 catalog 2634、eligible 2529、covered 1690、uncertain 837，完整 attempt 链累计 81 次 verifier 调用 / 285365 tokens；三次调用增量约 20.55%/16.78%/16.99%，token 增量约 29.30%/18.02%/15.69%，均通过用户批准的 25%/65% 相对成本门。test5 较早失败 attempt 的 2 个 operation failures 继续保留在累计审计指标中，但 committed tail 的正确性门通过，不能删除或改写历史。artifact、baseline lineage、组件版本、连续运行、抽取、full scope、known omission、真实 verifier、source accounting、预算与成本自动门全部通过；总状态仍严格 blocked，仅剩 golden held-out 裁决、shadow 人工裁决及 semantic-negative 抽样审计三个独立人工门，未切 Phase 1。
- **Verifier 预算、usage、血缘与成本策略（2026-07-26，2026-07-27 更新）**：`RATOMIZER_CLAIM_SHADOW_VERIFY_MAX_CALLS` 与 `...MAX_TOTAL_TOKENS` 默认 0（未授权），两者都为正数才启用真实 claim verifier。同一 generation 的 coverage/negative proposer/negative verifier 共享 `LLMRequestBudget`，每次 HTTP attempt（含 retry、JSON repair、response-format fallback 与截断升级）在网络前 reserve；当前 runtime 为 `claim-coverage-runtime-v10`。usage 严格要求非布尔正 `total_tokens`，明细须非负且与 total 一致；零/负/冲突 usage 标 incomplete 并按 reservation 保守记账。HTTP 200 的空/缺失/重复 decision 或非 `true/false/null` 的 coverage 判定单列 `verifier_operation_failure_count`，不得静默降级或借 provider 成功穿过正确性门。无账本分母为 `no-ledger-baseline-lineage-v2`，绑定输入、有效提取并发和 `llm-attempt-policy-v1`（adaptive/429/gate/token escalation）；旧 scalar baseline 永不匹配。当前用户批准的 `claim-cost-policy-v3-user-approved` 将相对成本门设为调用增量 25%、token 增量 65%，阈值和 policy version 同时写入 runtime/metrics；这不放宽绝对预算、usage 完整性、独立验证或人工裁决门。`claim-verifier-batch-v3-full-http-body` 复用 `llm_client`/预算的序列化，按完整首发 HTTP body 计量 model 参数、JSON mode、system/user messages、request schema/等长 IDs 与业务 payload；coverage、negative proposer/verifier 分别按真实 envelope 执行 48,000-byte 硬上限，单条超限不发网并保持 claim open；coverage 批次最多 24 个 group。`claim-coverage-candidate-v2` 要求非精确 quote 子串至少包含 6 个字母数字字符，避免页码、标点和残缺标识形成笛卡尔 coverage edge。当前 `claim-coverage-validator-v6`、`claim-artifacts-v6`、`claim-shadow-acceptance-v9`/report v7/input v3 逐层要求最终 attempt 正 token、usage 完整、operation failure=0、预算未耗尽与 baseline 血缘匹配；整条 attempt 链的调用/token 另行累计用于成本门，enabled flag 不能单独过门。
- **规范性成文根因与 v22 反证（2026-07-27）**：只升级抽取 prompt 的真实样本仍把一个可配置能力写成被动事实句；旧六维 verifier 全真但没有检查 target 是否以产品为义务主体，证明英文源动词枚举或 prompt-only 都不能系统闭环。v23 最初增加中文正式 target 叶子护栏；当前 `ai-normative-framing-v2` 以语法结构识别产品能力句，只包装 description/sub-item，不改角色、对象、编码和数值，也不会把弱情态来源升级为强制义务。`target_obligation_framing` 作为第七维；coverage prompt v4 明确同句/冒号统领有效、无关相邻句借用无效。抽取、复核、护栏和 consistency 版本全部进入 target producer lineage，旧 target 裁决不得迁移。
- **v23 真实三跑历史证据（2026-07-27）**：同一 parser/catalog generation 的三次机器本地 full 运行均无抽取失败，catalog 规模稳定在约 900 条、eligible 约 870 条；已知可配置能力三次均被写成自包含产品义务并由七维 verifier 覆盖。一次 cold 与两次 ledger-only 恢复证明 validated group 可复用，最终 operation failure 可清零，调用/token 增量均低于用户批准的 25%/50% 门。该批产物早于 attempt v2/artifact v6/runtime v8，只能作为历史反证和规模参考，不能作为当前 Phase 0 退出证据；必须由当前代码全新复跑并重新审核。客户措辞、稳定 claim ID、精确成本和本机路径仅留机器本地，不进仓。
- **Golden held-out 门与审核包（2026-07-27，2026-07-28 展示修复）**：acceptance v9 固定读取仓内 `golden_sets/claim_ledger_v1`，调用方不能替换路径/计数；manifest v3 的 held-out adjudication 绑定重建 claim ID/hash 与 `claim-golden-heldout-fixture-hash-v1`，reviewer 独立性、时区时间、七维精确集合和派生 overall 均 fail-closed。sanitized report v7 只输出状态/计数。`claim-shadow-review-packet` generator v7 / wire schema v5（decisions v3）生成机器本地敏感 JSON + 离线 HTML，展示真实 shadow source/target evidence、attempt 链累计成本/复用与 synthetic held-out expectation，空 reviewer/verdict 起步且只由人点击导出 decisions；生成器绝不提升人工状态，客户 wording 不进仓。v7 将正式证据置于折叠的运行溯源之前，按 review purpose/category 区分同 run 多 claim，并完整展示 semantic-negative proposal/validator 的 reason、rationale、evidence 与 checks，避免负向审计被误读为空内容。每个 committed snapshot 对已独立验证的 semantic negative 作版本绑定的确定性 10%（有候选时至少一条）人工审计；审核包合并 known omission 与 audit 用途，report 输出样本数、已审数和真实分歧率，审计不产生额外 LLM 调用也不直接关闭 claim。`failed_section_block_ids` 写入当前 requirements metadata，并映射为 `failed_extraction_units`；状态或计数任一显示失败都不能通过 extraction 门。
- **Held-out v3 与 target 审核血缘（2026-07-27）**：旧 `programmable-equivalent-001` 的人工拒绝连同 v2 fixture/claim/hash 作为 raw SHA-256 绑定历史保留，修正为“产品应支持角色执行动作”后转 development；新 `status-indication-mapping-001` 为未参与本轮修订且最初为 pending 的 held-out。manifest v3/review contract v2 按七维裁决并派生 overall，历史文件须重放且篡改 fail-closed。Acceptance v9/report v7/input v3 与 review packet generator v7 / wire schema v5 / decisions v3 使用 `claim-review-evidence-v1`，绑定 claim、effective ledger、coverage groups、target generation/review authority 和 requirements metadata；target 变化后旧人工裁决即使 claim/resolution 相同也 stale，disagree/follow-up 缺理由或重复裁决均失败。`ai_requirements.meta.json` 同时绑定 extract/verify/guards/consistency/normative-framing producer lineage；v21/v22 或缺 lineage 的旧 test5/test10/test11 snapshot 仍可读但不再是当前退出证据，必须用当前协议重跑后重新审核。
- **真实人工裁决导入（2026-07-28）**：YYH 对 v14/v15 同一证据身份完成 4 条 shadow 与 1 条 v3 held-out 审核；shadow 为 3 agree + test11 disagree，negative audit agree，`human_adjudication`、`negative_audit`、`known_omissions` 门均通过。`status-indication-mapping-001` 七维中仅 target obligation subject agree，其余 disagree，golden 派生为 `reviewed/not_approved`；acceptance 14/15 门通过但 Phase 1 仍 `not_eligible`。裁决原样保留，不能回写为 pending 或用刷新 baseline 掩盖。测试夹具不得复制仓库当前 curation 后假设 pending：import 测试在临时副本显式构造 pending，repository 测试接受且严格校验 pending/complete/not_approved 三种合法真实状态。
- **Held-out v4 能力边界替换（2026-07-28）**：被拒绝的 `status-indication-mapping-001` 未删除、未改写为 pending，而是连同 v3 declaration/input/expected、claim/fixture identity、七维裁决和理由进入第二份 raw-SHA-256 绑定历史；loader 用冻结的 `claim-catalog-v4` 规则重放 v3。active corpus 移除该 case，新增从未参与调参的 `configurable-interface-capability-001`（held_out、tuning_eligible=false）：源句只声明辅助输出接口可配置，target 只形成“该产品应支持配置辅助输出接口”的产品能力义务，不含 operator/maintainer/user 或使用场景。dataset 升 `claim-ledger-golden-v4`，manifest schema/review contract 结构版本保持 v3/v2；curation 先重置为新的 pending 人工审核，两个历史拒绝继续计入审计但不能替代当前批准。该 case 是按审核范围重置后冻结、且冻结后不再用于改行为/阈值的 acceptance fixture，不冒充统计泛化证据。由于历史绑定 raw bytes，`.gitattributes` 强制 history JSON 使用 LF，并由测试拒绝 CRLF，避免 `core.autocrlf` 使 fresh checkout 自毁哈希。
- **Held-out v4 人工批准与 Phase 0 完成（2026-07-28）**：YYH 明确将 capability-only held-out 七个维度全部裁定 `agree`，审核理由固定为“该目标仅表达产品支持配置辅助输出接口的能力，未引入人员角色或使用场景”。受控 importer 从原 v14 pending 输入重建 v16 reviewed 输入；尝试用已完成的 v15 reviewed 输入覆盖时被正确拒绝，旧 3 agree + test11 disagree 的四条 shadow 裁决保持不变。最终 acceptance v9/report v7 的 15 个门全部 pass，golden 为 `reviewed/complete`，blocking reasons 为空，Phase 1 结果为 `eligible_for_user_decision`（不是自动切换）。
- **Verifier attempt 事件账本（2026-07-27）**：`claim_verifier_attempts.jsonl` 使用 `claim-verifier-attempt/v2` 文件级 hash chain，artifact protocol 为 v6。immutable root 只绑定 cold request、requirements request、document generation 与 requirements hash；每个 attempt 单独绑定 target generation、runtime、baseline lineage 和 cost policy，因此策略变化可 ledger-only 重验且独立 cold run 不混链。reuse 必须引用同 root 的真实前序 attempt；generation meta 绑定已提交 prefix，失败尾不破坏旧 claim snapshot，但 acceptance/review packet 必须折叠完整 ledger，只有 tail 正好是 committed complete attempt 才过正确性门。网络前写 `.claim_verifier_attempt.checkpoint.json`，每次 budget reserve/commit/fail 同步持久化；publication WAL 之前强杀也会按 reservation ceiling 保守补 failed attempt，不再丢 paid calls/tokens。attempt 已落盘但 generation 发布失败时恢复上一代全部固定名 snapshot，并追加同 ID 单调 status-correction；已有 failed 状态也会累计新的 publication failure，幂等恢复不重复计费。baseline calls/failed calls/tokens/usage 与 `ai_requirements.meta.json` 精确绑定，不能放大分母绕过成本门。v4 可 hash-bound 导入为 cost-incomplete legacy root；v5 已有 attempt ledger 可直接加载 lineage 驱动 ledger-only v6 重验。Acceptance input v3 强制绑定 `generation_run_id` 与 `attempt_chain_id`。
- **Claim snapshot 崩溃恢复（2026-07-27）**：artifact protocol v6 增加 `.claim_publication.journal.json` 与逐文件 hash-bound backup。WAL durable 后才替换固定名文件，generation/effective 全量重载验证通过后删除 journal，该删除是全局提交点。所有权威 reader/writer 走同一跨进程 OS 排他锁（Windows byte-range lock / POSIX `flock`）并先恢复；持久 carrier 不再按超时删除，PID + 进程创建身份 + nonce 仅作诊断/篡改检测，进程退出由 OS 自动释锁，从机制上消除误删后继锁竞态。活 verifier checkpoint 会阻断所有权威读取，仅匹配 nonce 的发布路径可继续；budget checkpoint 回调在释放预算状态锁后执行，避免与 publication lock 锁序反转。强杀前半段恢复上一代、补写 interrupted attempt failure，强杀在提交点后保留新一代。恢复可再次中断且幂等，checkpoint/journal/backup 损坏 fail-closed。已有 committed snapshot 时 AI extraction 不再提前覆盖 catalog probe。真实 `os._exit` 矩阵覆盖 pre-WAL paid-cost checkpoint、journal、attempt、八个固定名 replace 与提交点；并发 reader 只能等待后读取完整代。该保证明确针对进程强杀；固定名协议不冒充突然断电后的目录元数据事务保证。
- **审核裁决受控导入（2026-07-28）**：新增 `claim_review_import.py`、`claim_shadow_review_decisions.schema.json` 与 wheel/源码/PyInstaller 三类入口。导入器以已加载 input 的不可变临时快照重建审核包，并对 shadow/held-out identity 做精确集合校验；missing/extra/duplicate/stale、无时区时间、同人 held-out 审核、缺必填理由、output 覆盖 input/decisions/golden corpus 及覆盖不同既有 reviewed 输出全部 fail-closed。golden manifest 与 reviewed output 使用两个稳定资源锁并按确定顺序获取，共享任一资源的并发导入不会 last-write-wins；成功后生成新的 reviewed acceptance input，并原子更新显式 golden manifest。合法 disagree 不会被改写为 agree，最终仍由 acceptance 门判定。v14 旧 decisions 因 target/evidence/fixture fingerprint 已变化而不可复用；当前人工审核仍须重新完成 4 个 shadow 项和 1 个 held-out 项。
- **Phase 0 CLI 输出保护（2026-07-28）**：acceptance report 和固定名 packet JSON/HTML 在运行前拒绝与 input 相同或互为硬链接，冲突不读取业务证据且原文件不变；packet/acceptance 写入失败统一返回契约规定的 exit 3，exit 4 继续只表示 LLM 服务不可用。

## 重大更新（2026-07-28）——Word/Excel 影印支路 + 点解析（已合 main `2a1c2bd`；验收记录见下方 2026-07-28 条目）

- **WP-A 影印支路**：新模块 `doc_facsimile.py`（`DOC_FACSIMILE_VERSION=doc-facsimile-v1`）——docx/xlsx 懒转换为 `out/document_facsimile.pdf`：Office COM 首选（Word `SaveAs2(FileFormat=17)`/Excel `ExportAsFixedFormat(0)`，`Visible=False`/`DisplayAlerts=0`，finally 里 `Quit()`+`CoUninitialize()`），LibreOffice `soffice --headless --convert-to pdf` 兜底（PATH + 默认安装目录探测，120s 超时），双缺如实 `unavailable:<reason>` 记 sidecar，**不伪造页图**。缓存键 = 输入内容 sha256 + 版本（`document_facsimile.pdf.meta.json`），命中不重转。pywin32 进依赖（`pywin32; sys_platform=="win32"`），非 win 环境 ImportError 优雅降级。
- **接入零分叉**：懒转换挂 `doc_annotation_export.export_annotation_bundle`（`_facsimile_source_pdf`）；拿到 PDF 后走与原生 PDF 完全相同的 `_resolve_pdf_geometry`/`_ensure_pdf_page_images` 路径；应用内 `build_pdf_annotation_payload` 只读复用（绝不现场转换）。summary/payload 如实写 `facsimile: "com"|"libreoffice"|"unavailable:<reason>"|null`。export-annotation-html chain 戳纳入 `+doc-facsimile-v1`（契约快照测试已同步）。
- **WP-B 点解析**：新模块 `spot_extract.py`（`SPOT_EXTRACT_VERSION=spot-extract-v1`）+ `POST /spot-extract`（冻结规格别名 `/api/spot-extract` 同处理器）。参数表需求行 → 复用 guards-v16 单行展开（`_is_parameter_table`/`_row_render_line`/`_row_name_cell` 直接 import，不复制）；其他行/段落 → 合成单段 section 走 `critique_section`（targeted_reextract 同款 chat_json+护栏，prompt 只见该段）。产出 `status=draft`、`source_mapping="spot_extract"`、suspicion「用户定点解析」（策略映射 `suspicion:spot_extract`：CAT_AMBIGUOUS/内部核对/IMPORTANT/HARD）、id `SPOT-<block>[-R<row>]` 冲突加序号；`extraction_operation_lock` 串行化 + 原子重写 + compliance/quality/merged_spec 同刷新。LLM 不可用抛 `SpotExtractUnavailableError` → 503 `ok:false`，不伪造 stub。
- **UI**：`DocumentReview.vue` 段落块「解析此段」+ 表格行首格图标按钮（图标式保批注契约测试 td 文本断言），悬停显现，无 LLM 配置不隐藏、点击如实 toast 错误；`api-client.ts` 加 `spotExtract`。
- **测试**：新增 41 例（`test_doc_facsimile` 16 / `test_facsimile_annotation` 8 / `test_spot_extract` 17）+ 前端 4 例，COM/soffice/LLM 单测全 mock；worktree 全量 discover 1718 绿（skipped=26 为 worktree 既有 golden/GUI 环境跳过）+ 前端 vitest 136 绿 + vue-tsc。**本机真实冒烟（隔离 venv + 真实 Office16 COM，已清理）**：合成 docx 经 Word COM 真转出文本层 PDF（`facsimile: com`）、`export_annotation_bundle` 出页图+几何+应用内 payload、点解析确定性行端到端（draft 行进澄清、二次点解析如实 already_covered）全通过。验收清单第 2/3 条的 **STO 真实 docx 与真实 LLM 路径**（STO 文档在本机用户目录不存在、LLM 需 key）需合并前在主检出人工过一遍。

## 重大更新（2026-07-26）——噪声贯通抽取路径（guards-v15，已合 main `6b4b0cf`；主检出全量 1664 tests OK、golden 6/6）

- **test10 复查发现**：12 条需求来源仍含页码/水印块——guards-v14 的噪声排除只在 serve 路径生效；抽取时 `section.source_blocks` 没有 noise 标记，匹配器在抽取时是盲的（端子标记需求仍掉 section_fallback 且 span 带水印 081/082）。
- **修复**：`extract_units.assemble_sections` 的 source_blocks 补 noise 标记；`_map_requirement_source` 的 fuzzy 候选剔噪声、`section_fallback` span（收窄或整单元）一律不纳噪声块。`EXTRACT_GUARDS_VERSION` 升 v15。
- **实测（test10 数据复算）**：端子标记需求由 section_fallback（带水印）变 **multi_block [080,083,084]**；12 条含噪声行 12/12 出清；新测试 3 例；全量 1664 绿 + golden 6/6。重跑即可得干净来源（test11+）。

## 重大更新（2026-07-26）——噪声块永不成来源 + 影印模式选中高亮原句全跨度（guards-v14，已合 main `be8ecd4`；主检出全量 1661 tests OK、golden 6/6、前端 vitest 132 + vue-tsc）

- **用户实证（test8 原版核对）**：选中端子标记需求，左框只框住 3.4.4 标题，原句涉及的正文段落没框；且该需求来源里混进了 "Machine Translated by Google" 水印块（082/102）。
- **修复一（数据）**：引句匹配各路径（exact/containing/reverse/多段摘录）一律过滤噪声块——页码/水印永不成来源；多段摘录里只命中噪声的片段按噪声内容跳过、不否决整条引句。`EXTRACT_GUARDS_VERSION` 升 v14。test8 实测：端子标记需求匹配 079/080/083/084/094/095 六块（082/102 水印出源）。
- **修复二（视图）**：影印模式选中需求时把 `quote_block_ids` 全部块加 quote-sel 虚线框（锚点保留主框 sel）——原句涉及的原文全部框出。
- **验证**：匹配器 3 例、Vue 1 例（选中后原句块 quote-sel、无关块不框）；全量 1661 绿 + golden 6/6 + 前端 132 + vue-tsc。重跑可用新包；旧产物 serve 层重算同样出清（`quote_block_ids` 现算）。

## 重大更新（2026-07-25）——引句匹配断链修复 + fallback 收窄全生效（guards-v13、merged-consistency v3，已合 main `ed0331a`/`13e95ba`；主检出全量 1658 tests OK、golden 6/6；test8 实测验证）

- **修复链**：引句多段窗口跳过噪声块（页码/水印夹缝不再掐死整句匹配）+ 两段式（先整句命中再反包含）；`extract_units` 补 section_path 使收窄从死代码变活；收窄再支持裸节号前缀（"4.1" 命中 "4.1 For..."）与多节号（"4.2, 4.3"）；热区 fallback 行"关联"只认原句匹配块、同块同页多区域并为一个热区。
- **test8 实测（新代码全链重跑）**：producer 全对（guards-v12→v13、consistency v3、impl-v5）；`section_fallback` 从高频降到 **7/119**；端子标记需求 `multi_block [080,083,084,094,095]`（含清单块）；螺丝需求 `[097,098]`；清单块（BLK-000084，86 字符并块）语义 **covered**——点击即达"查看批注"；两个 24 块误例收窄为 4.1 仅 10 块、4.2+4.3 仅 13 块。
- **遗留观察**：fallback 收窄按 `req.source_section` 匹配，LLM 节号标注异常时仍退整单元（如实保留）；重跑请用 23:06 新包（含 v13）。

## 重大更新（2026-07-25）——引句匹配三处断链修复（guards-v12、merged-consistency v3，已合 main `ed0331a`；主检出全量 1655 tests OK、golden 6/6）

- **用户实证（test7）**：清单并块后整段引句仍匹配失败掉 fallback，清单块被回退 span 误标"关联·见24"且十行各挂一个标签，右侧无"查看批注 24"入口。
- **根因**：①引句多段窗口被噪声微块（页码/水印）掐死——blob 引句走不到多段摘录豁免；且宽度 2 反包含（≥0.75）提前截胡更大窗口的整句命中；②guards-v11 的 fallback 收窄是死代码（`extract_units` 的 source_blocks 无 section_path，恒失效）；③热区语义源按原始 span 标"关联"不过滤 fallback，与重排视图口径分叉；同块同页多区域逐行重复挂标。
- **修复**：匹配窗口在非噪声块上搜索并改两段式（先整句命中再反包含）；`extract_units` 补 section_path 使收窄生效（guards-v12）；热区 fallback 行"关联"只认 `quote_block_ids`；同块同页多区域并为一个热区。test7 实测：引句命中 080/083/084 三块（含清单块），清单块语义 covered——点击即达"查看批注 24"。
- **验证**：新测试 6 例；相关套件 374 项零回归；全量 1655 绿 + golden 6/6。**test7 需用新包重跑**：该需求将从 section_fallback 变 multi_block，数据层同步干净。

## 重大更新（2026-07-25）——PDF 名词式清单段合并（atomize impl-v5，已合 main `a987313`；主检出全量 1649 tests OK、golden 6/6）

- **用户实证（test6 招标 PDF）**：端子清单（"Terminals:" + RS485/MPA/+AA/…/辅助电源 9 行）被切成 10 个 5–8 字符微块，过不了锚点匹配的 12 字符门槛（防页码误锚设计），清单中段永远无法锚定/显示覆盖；用户裁定"那一小段是整体的，可以将上下那几个成一个块"。
- **修复**：`pdf_parser` 新增 `_merge_list_item_blocks`——连续名词式短清单项（≤120 字符、非需求语义、同页同小节）连同冒号引导行并成一整段；枚举型需求行（`requirement_like`）绝不并；段首保留原 block_id、后续块编号不变；atomize 阶段 impl 升 v5（块结构变化，PDF 输入须重解析）。
- **实测**：test6 真实 PDF 上 "Terminals:" + 9 行并成 BLK-000084 一块（86 字符），全清单引句 exact 命中；合成测试 7 例（引导行并入/枚举需求保护/页界/节界/噪声豁免）；golden 基线为 DOCX 轨不受影响。
- **重打包**：新 exe（192MB）已含清单合并解析器；**test6 需用新包重跑**才能看到清单段整段锚定/覆盖的效果。

## 重大更新（2026-07-23）——grouping 聚类三规则（functional-synthesis-v7，已合 main `67216b5`；主检出全量 1642 tests OK、golden 6/6、agent_eval grouping 4/8→8/8）

- **周期档位分家**（审核人裁定）：period_variant 对周期档位（值+归一单位，不做跨单位换算）不同的对绝不合并——15 min × 24 h 两条独立曲线；任一侧未写档不算冲突；混合对（写档 × 未写档）概念同键且相容才合。`_PERIOD_RE` 补连字符形态（"15-minute"）。
- **对象词组合并**（误拆修复）：legacy_concept 对标题共享核心对象词组（拉丁 ≥2 连续词、中文 ≥4 连续 CJK 字）即同一功能对象——"Load profile behavior" × "Load profile storage" 合并；长度门只约束相似度路径。
- **变体护栏**：标题数字编号（安全套件0×1）或专有缩写/制式名（NB-IoT×LoRa）任一侧独有即否决。
- **既有钉串按裁定更新**：结构化周期变体合并测试、语义基线 archive-period-variants 案例改分家期望（注明裁定出处）；`FUNCTIONAL_SYNTHESIS_VERSION` v6→v7 并进阶段戳。
- **生产影响实测为零**：test2/test3 真实产物零 LLM 聚类新旧结果逐组一致（126 组/1 并、110 组/0 并）；golden 纯 A 轨无功能合成产物，零漂移。

## 重大更新（2026-07-23）——批注锚点与原句一致化 + section_fallback 按小节收窄（guards-v11，已合 main `24a7b21`；主检出全量 1631 tests OK、golden 6/6、前端 vitest 131 + vue-tsc）

- **用户实证（test5 招标 PDF 批注视图）**：无关清单段（"- DAY1"，BLK-000089）显示"已纳入需求解析→查看批注 22"；批注蓝区与右侧原句一多一缺——蓝区只有锚点块（含原句没有的编号句、缺原句末段"Condition upon delivery"）。
- **根因**：抽取层 `_map_requirement_source` 的 section_fallback 在引句匹配失败（块内碎句截断 + fuzzy < 0.82）后把跨小节抽取单元整段（24 块跨 3.4.4/3.4.5/3.4.6）写入溯源，视图"分析范围"照单全收；视图证据蓝区只亮锚点首块，多段引句后半段出框。
- **修复**：抽取层 fallback 按 `req.source_section` 与块 `section_path` 末段逐字收窄（24→3 块；一个都匹配不上退整单元并记 note，不猜），`EXTRACT_GUARDS_VERSION` 升 **guards-v11**（缓存存映射后结果）；视图层 `api_server` 新增 `quote_matched_block_ids` 并下发 `quote_block_ids`（匹配不到如实回退锚点单块），Vue 与静态 HTML 双渲染器同步——证据蓝区 = 原句跨越块集（多段引句不再丢后半段），section_fallback 行"分析范围"只认原句匹配块（"- DAY1" 类无关段消失）。
- **版本面**：guards v10→v11（影响 ai_extract 缓存指纹与阶段戳）；golden 基线纯 A 轨无 ai_extract 产物，零漂移坐实。**test5 需用新 key 重跑抽取**才能吃到收窄（旧产物不重抽不变）；块粒度高亮仍可能含块内相邻句（编号句类），句级裁剪留作后续立项。

## 重大更新（2026-07-23）——专家审核第二轮十三项修复（已合 main `e3ad2a7`；主检出全量 1627 tests OK、golden 6/6）

- **正确性**：`coverage_check` 改走 A 轨适配层 `_atomic_to_consistency_row`（2337 条真实产物上共引/重复/引句命中 0/0/0 → 实测恢复；结构化 OBIS 仅从 `parameters.cosem_object.obis` 确定性取），fixture 改真实形状；蓝皮书测试隔离本机 `out/bluebook`；token 计量 `_aggregate_usage` 逐轮归一（混合格式应 125 不再低计成 100/25）；schema 修复续接原 transcript（`chat_with_tools` meta 导出 history）——修复轮保留取证上下文且仍带 tools，工具调用并入 `tool_calls` 摘要。
- **缓存/指纹纪律**：llm-review 阶段指纹补齐 prompt/cache/tools 三版本 + domain-pack 内容 hash + `review_scope`/`llm_review_limit`（此前 llm-review 是唯一不拼代码版本的阶段，旧阶段产物自然失效）；`llm_review_cache` 锁内追加+fsync+`PermissionError` 重试（对齐 decide_trace）；CLI/Desktop 自定义 KB/domain-pack 全链贯通（review 子命令补 `--kb`，run/desktop 转发，默认包兜底行为不变）。
- **补抽口径对齐**：`current_omission_candidate_ids` = uncovered ∪（失败章节块 ∩ 现存块）——失败章节登记后可真正 `targeted_reextract`（原必 409 死登记）；`AI_SUPPLEMENT_VERSION` 有意不动（准入闸变化双向兼容，bump 反令现存补丁静默失效）。
- **分发**：pyproject 补 `desktop_tasks`/`functional_synthesis`/`semantic_quality` + `llm_agents`/`domain_packs` 包数据（AST 闭包无断链）；wheel 冒烟真隔离 cwd（原从源码仓导入假绿）+ 导入探针扩 agent 链 + DEFAULT 路径存在断言。
- **WP2 一致性与审计收口**：software 项 `hardware_dependency` 归属护栏（跳过+留痕）；LLM 异常/非法返回入 `_mark_enrichment_rejected`（待澄清+fallback）；`co_design_items.md` 四字段走兜底渲染；`agent_compare` 预算预校验（违例 exit 2）+ 双侧 trace 明细落盘（原随临时目录删除）；待办 4 补硬前置（人工核对完成前不动聚类规则）。
- 版本面：`REVIEW_TOOLS_VERSION`→v3、`LLM_REVIEW_CACHE_VERSION`→v5、`UNFOUNDED_RULE_VERSION`→v3；`AGENT_POLICY_VERSION`/`EXTRACT_GUARDS_VERSION`/`AI_SUPPLEMENT_VERSION`/`PROMPT_VERSION` 不动；stub 路径未动，golden 零漂移。

## 重大更新（2026-07-28）——Word/Excel 影印支路 + 点解析（已合 main `2a1c2bd`）

- **WP-A 影印支路**：docx/xlsx 经 Office COM（首选）/LibreOffice（兜底）懒转换为 document_facsimile.pdf（指纹缓存），批注导出复用原生 PDF 影印渲染零分叉；无转换器如实降级文本批注不伪造页图。STO 真实验收：Word COM 转出 3MB PDF、82 页影印、几何锚定同构。依赖 `pywin32`（Windows 条件依赖）；打包 spec 已补 doc_facsimile/spot_extract/pywin32 hiddenimports（惰性 import 静态分析不可见）。
- **WP-B 点解析**：批注行/块单点定向解析——参数表行走 guards-v16 确定性单行展开，其余走 LLM 单段抽取（同 targeted_reextract 护栏）；产出 draft+「用户定点解析」suspicion 进澄清待确认（不直接转正），LLM 不可用响亮报错。真实验收：参数行确定性产出（引句逐字）、术语行如实 already_covered、二次幂等。
- **验证**：全量 1718 tests OK（新增 41）、前端 137 + vue-tsc 零错误、主检出 golden 6/6。

## 重大更新（2026-07-27）——参数表逐行确定性展开（已合 main；主检出 golden 6/6、全量 1677 tests OK）

- **用户裁定**：参数表每行都是需求。STO 实证链路诊断：初版 `[:5000]` 截断（已修,impl-v6）之外还有第二处 `render_table_text(max_rows=20)`——143 行参数表扁平文本尾部只有 "... 123 more rows",LLM 永远只看到前 20 行。
- **实现**：① render_table_text 默认渲染全部数据行（atomize impl v6→v7,STO 实测 BLK-000098 扁平文本 49k→184k 字符/144 行全量）；② ai_extract 新增 `_supplement_parameter_table_rows`——需求型参数表（表头含要求类列,非术语/定义表,叶子节不在术语/参考文献区）每个未被 LLM 覆盖的数据行确定性生成一条 draft 需求（逐字渲染行引句、`deterministic_fallback`、suspicion「参数表行确定性展开」进澄清必答）；分组标题行（合并单元格全同值）与多级节号单元格不算需求/不作标题;覆盖判定按最长实质单元格 compact 命中,判不出宁补勿漏。
- **STO 实测**：补行 243 条（BLK-000098×102/BLK-000100×118/BLK-000103×23）,引句逐字 243/243,标题为真实参数名。
- **验证**：新增 13 专项测试（资格判定/逐行展开/逐字锚定/覆盖去重/分组标题过滤/多级节号）；全量 1677 tests OK。

## 重大更新（2026-07-27）——表格块文本取消 5000 截断（已合 main `f5d2573`，impl-v6）

- **硬伤实证（STO/俄标 docx）**：初始提交遗留 `table_text[:5000]`——规范主体是百行级参数表（143 行/4.9 万字符的表只剩 5000），88% 规范内容进不了 B 轨（17 节 9 节空抽、18 条需求、覆盖率 17.6%）；完整数据本在同块 data_rows（A 轨规则层能找到 1425 条）。
- **修复与验证**：块 text 保留完整扁平文本（章节合并本就有 ~5k 切分，批注视图走独立 data_rows）；STO 实测 blocks 总字符 38818→102856；ABNT 金标无截断块，golden 6/6 零漂移实测坐实；主检出全量 1664 tests OK。旧结果需重跑（atomize impl-v6 使旧解析缓存自然失效）。

## 重大更新（2026-07-23）——专家审核 P0/P2/wheel 修复（已合 main `2cfc3bb`）

- **P0 审计造假撤回（用户确认：20 条扩充案例系实施者代登记，未经人工核对）**：manifest curation 撤回 20 个 ID，`human_review_status` 改 `partial`，reviewed_by/statement 如实记录撤回经过；`agent_eval` 报告 unreviewed_count=35（真实口径，40 案例仅 5 条经核对）。tests/test_agent_eval.py 原先把 25 个 ID 硬编码为预期（绿测固化错误审计），已改为钉死 5 条 + unreviewed 断言。后续任何人核对案例按 README 规则登记，runner 永不自称核对状态。
- **P2 三条**：agent_loop 全部参数校验前置（max_tokens>=0 先于状态读取/工具执行——此前负值会先写 omission 副作用再崩轨迹）；agent_compare 捕获 AgentLoopInputError（退 2）+ 通用兜底（退 3，不再裸崩），rule 侧报告补 decider_usage/token_accounting；agent_tools 三处 reason 由硬编码 "agent-policy-v2" 改为引用 AGENT_POLICY_VERSION。
- **P1 wheel 可运行**：py-modules 补 functional_catalog；顶层 schemas/ 以包形式随 wheel 分发（agent_eval/decide_trace 经 Path(__file__).parent 相对定位）；新增 tests/test_packaging_smoke.py——构建 wheel、校验内容、隔离 --target 安装、真实 import + schema 加载（此前验收只在仓库根跑,安装后故障因此漏网;本机补装 wheel 包后冒烟通过）。

## 重大更新（2026-07-23）——专家审核 P1 修复四项（已合 main `2cfc3bb`；主检出全量 1596 tests OK、golden 6/6、wheel 冒烟通过、agent_eval unreviewed=35 如实、四类基线不变）

- **P1-a 失败章节候选一致**：`AnalysisState.unqueued_gap_block_ids`（覆盖缺口 ∪ 失败章节块）此前只用于候选生成，`queue_all_gaps` 执行时却重算 uncovered 集合——不再 uncovered 的失败块永远排不上队。修复：`queue_all_gaps(out_dir, block_ids=None)` 直接消费调用方快照候选（`execute_action` 传入 state 属性；未传参保持旧重算行为），锁内逐块重验证（存在/非 pending/源指纹一致），未过验证如实进 `skipped_block_ids`（带原因）不中断；summary 区分 queued/skipped。
- **P1-b hardware_dependency 落交付物**：WP2 只写字段不透出。修复：xlsx `_notes_text` 增「硬件依赖：」行（过 `clarify_display_text`——待澄清自动带"未经依据校验+原始候选"标注，非空才输出）；template_writer 走 `_notes_text` 自动获得；`co_design_items.md`（`requirements_analysis._write_report` 协同分支）同步补行。纯渲染变更不动 analyze 缓存版本，`STAGE_IMPLEMENTATION_REVISIONS` requirements-analysis→v6、template-write→v4 让阶段重跑重渲染。
- **P1-c schema 修复纳入预算**：`build_openai_review_tool_loop` 的 schema 修复调用此前走无 sink 的 `chat_json_messages`——首轮花满预算后修复仍放行且不计数。修复：首轮/JSON 修复/schema 修复共享同一 `_usage_sink`，修复前后用 `llm_client._aggregate_usage` 核算，超 budget 抛 `LLMResponseError`（该需求进 stub 记数）；日志 tokens 用含修复调用的聚合值。
- **P1-d KB 同轨 + 证据指纹**：① desktop run 的 `--kb` 此前只传 atomize——review 新增 `kb_paths` 透传（`run_review_pipeline`→`review_requirements_detailed`→`review_requirements_with_openai`→`make_tool_executor`；None 保持旧默认，解析后的真实列表进汇总 `kb_paths` 字段如实记录，stub/单发不读 KB 则无此字段）；② `review_tools.evidence_fingerprint(out_dir, kb_paths)`（KB 各文件+blocks.jsonl+atomic_requirements.jsonl+蓝皮书索引内容 hash 的确定性 sha1，缺失记 null）进 `llm_cache_key` 指纹载荷（**`LLM_REVIEW_CACHE_VERSION` 升 v4**）与 `stage_producer("llm-review")`（`stage_producer(stage, *, out_dir=None, kb_paths=None)`——无 out_dir 保持基础戳）。
- **验证**：worktree 全量 1595 tests OK（新增 24 例；skipped=26 为 worktree 环境性跳过——无 out/ 基线 5 golden、无 PySide6、历史样本 env 未设）；agent_eval 四类基线 0.6667/0.5/1.0/1.0 不变。合 main 后按纪律复验 golden 6/6（stub 审查路径未动、analyze 缓存版本未动，预期零漂移）。

## 重大更新（2026-07-23）——WP2 待澄清兜底渲染（已合 main `889000d`；主检出全量 1571 tests OK、golden 6/6）

- **用户裁定**：交付物不接受裸"待澄清"也不接受"看起来完整"——要兜底候选但必须标注。
- **实现**：`_mark_unfounded_field` 覆盖前把原值存入 `clarify_fallback`（数据层字段仍恒为待澄清）；渲染层（`clarify_display_text`/`_fallback_lines`，xlsx 需求列/说明列 + template_writer 成文列共用）透出"待澄清（未经依据校验，需专家核补）+ 原始候选（仅供参考，不得作为实现依据）"。`UNFOUNDED_RULE_VERSION` 升 `analyze-unfounded-v2` 并进 `requirements-analysis` chain 版本戳（此前戳只含 prompt 版本,确定性后处理漏覆盖）。
- **验证**：既有 WP2 测试按新渲染口径更新（端到端用例断言标注+兜底文本透出），专项 122 tests 绿。

## 重大更新（2026-07-23）——Agent Phase 2 实施：Tool-using Reviewer + 无依据字段强制"待澄清"（已合 main `9d548a9`）

- **范围**：`llm_client.py`（新增 `chat_with_tools` 有界 tool-loop）、新增 `review_tools.py`（五工具+TOOLS schema+`make_tool_executor`）、`llm_pipeline.py`（executor 处置+缓存版本）、`requirements_analysis.py`（WP2 待澄清规则）、`llm_agents/review_pipeline.yaml`（operations 增 executor）、tests（4 个新文件）、文档；规格 `docs/agent-phase2-spec.md`（已冻结）。
- **WP1-A 工具调用基础**：`chat_with_tools(config, messages, tools, *, max_rounds=8, on_tool_call, token_budget=None)`——OpenAI 兼容 tools 有界循环：工具结果以 role=tool 回灌、无 tool_calls 按 chat_json 同口径解析最终 JSON（非法 JSON 修复重发一次占一轮）；轮顶耗尽/同一工具同一轮连续错 2 次/token 超预算（默认 20000，yaml `tool_loop_token_budget` 可调）→ `LLMResponseError` 走既有 stub 失败路径并记数（不得伪造模型已审）；端点 4xx（tools 不支持）响亮报错点名 tools 语境，不静默降级为无工具审查；usage 全轮汇聚（缺失计 0 标 partial，不估算）；429 闸门/截断升级/双头发送/llm_trace 全量复用。
- **WP1-B 工具面（全部确定性只读）**：`kb_search`/`kb_get`/`blue_book_class`/`source_read`/`coverage_check` 只做现有确定性函数薄封装与返回裁剪（定义 300 字/蓝皮书 1500 字/原文块 2000 字帽；未命中如实 null/error）；`REVIEW_TOOLS_VERSION=review-tools-v1` 进审查缓存指纹，TOOLS 规范指纹钉在测试里（改工具面不 bump 版本 → 契约测试失败）。
- **WP1-C operations 执行器（首次实现，此前是声明性死代码）**：classify_risk/correct_errors=`tool_loop`（合并为每条需求一次工具化融合审查；输出契约、llm_review_schema 校验、确定性政策层、下游字段语义零变化）；merge_duplicates/gap_find=`deterministic`（consistency_report 已承担,不做 LLM 版）；test_point_generate=`deferred`（零消费者,有据缓建）。`PROMPT_VERSION=m2-review-v2`、`LLM_REVIEW_CACHE_VERSION=llm-review-cache-v3`，缓存 key 增 REVIEW_TOOLS_VERSION+执行器模式；stub 路径逐字不动；旧 yaml（无 executor 声明）保持单发融合审查。审查结果行附 `tool_calls` 摘要（工具名+轮次,审计可解释性落在轨迹上,不要求托管端点输出可复现）。
- **WP2 无依据字段强制"待澄清"**：`_apply_llm_item` 现有 `validate_llm_item` 之后加确定性规则——富化被护栏整体拒绝（回退 base）或采纳字段含源文/模板/背景均无据数字（validate 软标同判据细化到字段,字段侧先剥枚举标号）→ 该字段写"待澄清"并逐字段同步 `open_questions`（内部核对受众,经既有通道进澄清报告,xlsx/成文经「待确认」通道原样透出）。只对无依据下手：模板来源数值/枚举标号/遗漏类不动,base 非空有据字段逐字节保留,确定性 join 字段（id/归属/引句/模块）永不标。`ANALYZE_PROMPT_VERSION=analyze-llm-v7`，`UNFOUNDED_RULE_VERSION=analyze-unfounded-v1` 进 analyze_enrich_cache 指纹。
- **验证**：worktree 全量 1502+68 tests OK（新增 68 例：chat_with_tools 15 / review_tools 27 / tool_loop_review 11 / analyze_unfounded 15，全 unittest.TestCase）；评测四类基线 0.6667/0.5/1.0/1.0 不变；既有 `test_fabricated_code_rejects_enrichment_and_degrades` 按冻结规格改断言（旧行为"回退 base"即本规格明令禁止的静默放行,新断言=待澄清+open_questions 同步）；golden 6/6 待合入后主检出复验（stub 路径未动,预期零漂移）。
- **遗留（交审核人）**：冻结点 5 的 deepseek-v4-flash tools 支持探针与验收 #2（真实 test3 产物 ≥10 条 tool-loop 审查逐条核 tool_calls 摘要）需有 key 环境执行。

## 重大更新（2026-07-30）——ownership/compliance 确定性分类收口（已合 main；agent_eval 四类全 1.0、classify 12/12；全量 2255 tests OK、golden 6/6）

- **评测结果**：人工核对的 `agent_eval_v1` classify 从 8/12 提升到 12/12；新增英文物理词严格走字母数字边界，未加入 display/lcd/phase/power/modem/terminal 等宽词；审批型合规只接受 `approved/approval according to` 后紧随带数字的 STN EN/EN/IEC/ISO/OIML 文号。
- **缓存纪律**：新增 `ANALYZE_RULES_VERSION=analyze-rules-v1`，`COMPLIANCE_SCHEMA` 升至 `compliance-requirements/v2`；requirements-analysis 与 ai-extract producer 分别纳入对应版本，functional-synthesis implementation revision 升至 v4。
- **冻结基线纪律**：`agent_eval.py` 默认改为只读，实时规则可优于历史 manifest 基线而不自动改写 `golden_sets/`；维护者只有显式传 `--update-baseline` 才能原子刷新基线字段，`curation` 始终保持不变。

## 重大更新（2026-07-31）——表格结构与单元格级需求闭环 v1（table-structure-v2，分支 codex/table-structure-cell-closure 待审核）

- **新模块 `table_structure.py`**：表格角色识别（title/header/row_header/data/group_header）与粒度规划（row/cell/mixed leaf plan）集中一处，纯确定性；`TABLE_STRUCTURE_VERSION="table-structure-v2"`。
- **新产物 `table_cell_items.jsonl`**（schema `table-cell-item/v1`）：每个非空物理单元格/合并区域一个 canonical cell（`TBL-000001-R000002-C000003`），合并格仅存 anchor + covered_coordinates；随 atomize 写出并进 ai-extract/assemble/compose/export-annotation-html 输入与 manifest 计数。
- **删除的硬规则**：xlsx「首行一个非空格即标题」、所有表默认首行为表头（首两行皆需求句→headerless，首行进数据区）、参数表 ≥3 数据行硬门（行数只作置信证据）。
- **混合模式（mixed）**：DLMS 属性×服务组合表——行 own 属性字段（COSEM join 不变），事实列 marker 格 own cell claim；Note 列保持原文，「1 shall support Note.」「two shall support Value.」「1 shall have Requirement set to …」伪句式族全部消灭（索引号 subject 永不产 valued/matrix 事实）。
- **Claim Ledger**：source_kind=table_cell（locator position_basis=table_cell_text，cell_start/end 句切分——同格两条独立义务两个 claim）；新增 5 个 hard-fail 审计项（unconsumed/multi_consumed/dangling item/cell/normative_context_only），table_structure_status=needs_review|base_migration_required 与内容守恒分离；claim-catalog-v6 / schema v2 / focus-adapter-v2 / artifacts-v7 / annotation-v14 / 几何缓存 v5 / guards-v19 / param-row-expand-v3 / atomize impl-v8 / ai-extract impl-v6。
- **探针（ABNT 真实文档，三 seed KB + domain-pack）**：block_id 序列 1013/1013 逐字节一致；table_items 2075/2075 item_id 集合一致；text 零变化；10393 canonical cells；原子候选 -63 全为伪句式垃圾（table_value_matrix 186→124、capability_matrix 15→14，代表性需求零丢失、零新增）；cell 审计五项全零；unmapped_raw_span 909→871（既有 incomplete 状态改善，非回归）。
- **合并后必做**：main 检出按「三 seed KB + domain-pack」重生成 `out/abnt_nbr_16968_atomizer_v5/`，golden 摘要的 counts/requirement_type/source_type 分布与 coverage 将按上述漂移更新（逐项见上）。

## 重大更新（2026-08-01）——表格结构闭环第三轮复审修复（5 P0 + 4 P1，同分支 `codex/table-structure-cell-closure` 待审核）

> 第三轮复审裁定「不通过，暂不建议合并」，9 项全部按发现逐条修复并实测。版本面：`TABLE_STRUCTURE_VERSION` v3→**v4**、`CLAIM_CATALOG_VERSION` v7→**v8**、`CLAIM_FOCUS_CRITIQUE_VERSION` v1→**v2**、`CLAIM_ANNOTATION_VERSION` v15→**v16**、`EXTRACT_GUARDS_VERSION` v19→**v20**、`CLAIM_CANDIDATE_POLICY_VERSION` v4→**v5-table-cell-exact-text**、atomize stage impl v9→**v10**（全部输入须重解析）；ai-extract stage producer 增 `+table-structure-v4`；export-annotation-html 阶段戳 `doc_annotation_export/v16-cell-claim-projection`（两处钉串已同步）。candidate policy v5 进 `current_base_versions()`——旧 base 经版本闸如实返回 `base_migration_required` 需重建，不静默沿用旧候选集；held-out/schema golden 零漂移（实测 22/22）。

- **P0-1 崩溃恢复少记 verifier 成本**：原因——queue 在进入 verifier 前 detach 掉自己的 budget checkpoint，而 verifier checkpoint 只写另一套 WAL。现象——实际 3 次/60 tokens 的执行在 base 发布后崩溃并恢复，终态只记录 1 次/20 tokens。初修以 callback 链接恢复全量累计，但仍存在 verifier WAL 与 queue 日志顺序双写的 `os._exit` 窗口；最终口径改为 **budget outbox**：同一 transition 先持久化，再幂等投影两侧，queue/`claim-maintenance` 写路径负责恢复，GET fail-closed 且字节不变。`tests/test_claim_queue_execution.py::test_crash_after_base_publication_recovers_full_verifier_usage` 继续钉 3 calls/60 tokens；`tests/test_claim_budget_checkpoint_outbox.py` 另钉 pre/post-call 第二 sink 强杀、普通 I/O 失败、零重复 HTTP 与 cache invalidation。
- **P0-2 生产 table_cell claim 全被批注投影丢弃**：原因——`_claim_annotation_state` 的 table_cell 分支 `continue` 跳过公共 `records.append`。现象——真实链路 catalog_cell_claims=2 而 claim_records=0、claim_zones=0；前端测试手工 mock 了生产端造不出的数据。解决方法——重构为显式 if/elif/else：cell record 先挂 `state["cells_by_block"]` 再落入公共 records；真实链路回归 `test_table_cell_claims_reach_records_payload_and_cells_index`（真 catalog → publish → fold → `_claim_annotation_state` → `build_pdf_annotation_payload` → optimized HTML claims_json，两端断言 2 条 cell claim 全到）。
- **P0-3 定向补抽混淆上下文与可引用证据**：原因——`_claim_focus_lines` 把行头/列头/正文混进同一 focus_lines，`critique_section` 只要求 source_quote 命中任意一行，scope guard 又检查整串序列化输出。现象——模型回显 `Feature=Encryption` 即可为无证据描述放行。解决方法——结构化 **FocusEvidence** 三角色：`prompt_context`（仅定位、禁引用）/`verbatim_evidence`（可引用）/`composite_matrix_fact`（主体+维度+marker 三者必须同现，`_composite_fragment_present` 剥配对引号、≤2 字符 alnum marker 用词边界）；严格 prompt 分「可引用证据（/矩阵事实（/定位上下文（」三段；**source_quote 从绑定面剔除**（`critique_section` 与 `_claim_output_scope_guard` 的 rendered 均排除——否则 marker 词边界检查被 quote 字段自我满足）。
- **P0-4 矩阵合成仍确定性造伪需求**：原因——事实列判定仍是「marker 多数减黑名单」且 atomize 对所有表型重算事实列。现象——`Feature|Supported → Encryption shall support Supported.`、`Item|Approved → Design shall support Approved.`。解决方法——共享正向 `matrix_dimension_evidence`：分类、leaf plan、A 轨只消费这一个结果；未知二维表保留原文 + needs_review，下游禁止重新推导事实列。
- **P0-5 单格能力静默消失**：原因——空 merge 列表被转成 None（与「旧产物无证据」混淆），未合并单格数据被当 group header；无结构证据的首行单格被推断为标题。现象——"Configurable auxiliary output"/"User-programmable outputs"/"Outputs selected by the operator"/"Battery service life: 15 years" 全部 0 claim + audit 全零 + status=ok。解决方法——区分「已知无 merge」与「无证据」；无 caption/merge/style 时只产可定位的 ambiguous eligibility candidate，绝不静默按标题关闭；未追加任何动词词表（审核明令）。
- **P1-1 other 表资格不再由单元格数量决定**：说明性句子进入 context、计数并置 needs_review，不再登记正式 claim。
- **P1-2 付费 section cache 绑定 cell 语义**：`section_fingerprint` 结构骨架 rows 哈希 `{item_id,text}`、cells 哈希 `{cell_id,row_index,column_index,text}`，bbox/page_number 排除；测试钉「语义变化 miss、几何变化 hit」（guards-v20）。
- **P1-3 静态审核 HTML 渲染 cell claim**：按物理 R×C 与 merge anchor 语义在 `<th>/<td>` 内渲染 `claim-cell-chip`（caption/head/body 三域，anchor 格独占），`_render_table_inner`/`_render_one_block`/`_render_blocks` 三层贯通 + CSS。
- **P1-4 F10 e2e 诚实化 + 钓出生产缺口**：夹具之一实为 other/mixed（断言改 needs_review + unsignaled=1，不再冒充 mapping_matrix）；`_write_matrix_docx` 第 2 行改代词主体句（"It shall sign responses."）；新增真 marker 矩阵夹具。模拟层全重写：七维检查逐项独立推导（行头主体/列头维度/情态/极性/数量/条件/成文义务，缺失如实 covered=false）；usage 窗口断言终态 = 传输层付费调用逐次相等；两测试均带 annotation 真实链路腿。**实测钓出缺口**：marker 格 quote "X" 仅 1 alnum < 6 下限 → 永落 `shared_block_locator` → 候选闸拒绝 → marker claim 生产上永远到不了 verifier。修复 `_candidate_basis`：table_cell claim 的 quote 与**格全文逐字相等**（归一后）即授予 `source_quote_span`（精确身份绑定非残缺片段）；宽候选严闭合——三条 marker claim 全进 verifier，七维按完整 semantic_context 逐条裁定，只有主体×维度成立者闭合。`CLAIM_CANDIDATE_POLICY_VERSION` 升 v5；单元钉 5 例（精确相等放行/归一化/片段不放行/非 cell 包含不放行/账本闸集成）。
- **全量门钓出的两处 v4 首版回归（同轮修复）**：①`Object|Read|Write` 访问矩阵（合成语料场景 4 的真实形态）被正向维度闸误拒判 other——维度名闭类补访问操作轴名 `read|write`（命名操作本身的规范坐标轴；Supported/Approved 处置分词仍三形态全不命中，P0-4 反例不回潮）。②首行单格题注候选独占表头位致整表列名坍缩 column_N、次行真实表头（Label/Value/Formula）掉进数据区（xlsx e2e 实测）——`detect_header_rows` 对"单格题注候选 + 次行非规范性"增加越行表头识别（单格行仍走 ambiguous 计数待审，modal/pattern 单格行不进此分支保留 cell claim 路径）；atomize 列名从「状态 ambiguous 即整表 column_N」改为按行过滤（单格候选/义务句/弱信号行永不命名，干净表头行正常供给）。P0-5 契约随行落实：此类首行单格不再充当表标题，xlsx 表标题如实回退 sheet 名（`test_extract_xlsx_e2e` 期望已按新契约改写并留注）。
- **验证**：设置历史样本环境变量后后端全量 **2460 tests OK（0 skip）**；前端 Vitest **172/172**、`npm run build`（vue-tsc + vite）通过；`git diff --check` 与 py_compile 通过。held-out/schema golden 22/22 零漂移。未提交、未推送；合并后按「三 seed KB + domain-pack」重生成 main 的 ABNT golden 并逐项说明漂移。

## 重大更新（2026-07-31）——表格结构闭环复审修复（table-structure-v3，同分支 `codex/table-structure-cell-closure` 待审核，规格 `docs/table-structure-cell-closure-fix-spec.md`）

> 第二轮复审裁定「不通过」：最小反例可在账本审计全零、状态 ok 时丢需求/造伪需求。本轮按 7 阻塞 + 4 中危逐项修复，全部反例固化为 `tests/test_table_structure_cells.py::ReviewCounterexampleTests`（8 例）与重写后的 e2e。版本面：`TABLE_STRUCTURE_VERSION` v2→**v3**、`CLAIM_CATALOG_VERSION` v6→**v7**、atomize stage impl v8→**v9**（全部输入须重解析）；ai-extract stage producer 增 `+table-structure-v3`（M3，pinned 戳已同步）；claim_catalog_meta schema audit 增两个 informational 计数器（optional，与 v6 cell 计数器同款）。**未 bump 的纪律说明**：`_claim_focus_lines` 渲染修复（list 上下文不再以 Python repr 进付费 prompt）只影响未来抽取的提示词数据，既有 supplement 的回放有效性不依赖未来渲染——沿用「bump 反令现存补丁静默失效」先例不 bump `CLAIM_FOCUS_CRITIQUE_VERSION`，在此显式声明行为变化。

- **B1 同行义务缺对象上下文**：`_row_identity_entries` 把每个 cell leaf 之前全部身份格（row_header 角色或 ≤120 字符且非强信号非 marker，含 merge anchor 继承）以结构化 (header, value) 供给——claim 上下文渲染 `Header=Value`，atomize subject 从结构化 entry 取值（不回读显示串）。`Logger | It shall log. It must alarm.` 两条 claim 均带 `Logger`。
- **B2 e2e 诚实化**：`test_table_structure_e2e` 只 mock 最低层 `llm_client._post_json`（复刻预算 reserve/commit 与 stats 契约），critique/质量/metadata/compliance/merged_spec/freshness/reload/config 全真实（config 走 env 真实解析）；模拟传输的一切响应从真实请求 prompt 派生（抽取 quote 逐字取自 prompt focus evidence、覆盖判定=claim 义务分句逐字包含于所引 evidence）；断言真实 prompt 含对象 `Encryption` + 列头 `Behavior` + 逐字义务句，并 pin 付费面无意外调用。配套真修：focus 上下文 list 曾以 `str()` repr 泄漏进付费 prompt（`_claim_focus_lines` 改按序列渲染）。
- **B3 矩阵分类与事实列闸耦合**：`is_mapping_matrix` 要求 ≥1 个通过表头门禁的事实列（合成表头/NOTE/marker 词/处置列 status·state·result·required·check·备注等全部否决）；marker 多数但表头无效的列记 `matrix_rejected_marker_columns` → 块级留痕 + catalog needs_review。`Item|Status|Required` 反例：行 claim（逐字）+ needs_review，零裸 X claim。
- **B4 常规表确定性伪需求**：atomize 能力合成要求显式二维能力维度证据（`_DISPOSITION_HEADER_RE` 同样进 valued-facts 闸），证据不足保留原始格 + needs_review，不再合成「Voltage shall support Requirement.」「Voltage shall have Status set to ok.」。
- **B5 句形/结构角色/内容资格解耦**：`obligation_signal` 六值（marker/modal/pattern/colon_spec/sentence_shape/none）独立于 structural_role；sentence_shape=弱信号→只作上下文 + `weak_signal_cells` 计数→needs_review（永不单独成 claim、永不成列名）；pattern 句（"can be assigned"）无情态句号也算义务句；标题推断不再删除内容资格；`unsignaled_data_cells`  informational 计数（身份格被同行 claim 消费不算丢失）。审核明令：不追加动词词表补丁。
- **B6 合并格文本校验**：`validate_merge_text`——被覆盖格必须为空或与 anchor 逐字一致（clean_cell 口径），冲突只丢该 merge 区间、保留全部格、`merge_evidence_status="dropped_text_conflict"`→needs_review；xlsx `_merged_fill_values` 填充前同口径预检。几何重叠仍走既有 dropped_conflict。
- **B7 xlsx 无缓存公式 fail-closed**：`extract_xlsx` 双视图打开（data_only=False 并行），公式格无缓存值 → `xlsx_formula_value_unavailable` parse_incomplete + 计入非空守恒/连通区域（`="The meter shall log events."` 不再凭空消失且 parse_incomplete=False）。
- **M1 PDF 几何状态枚举**：`_pdfplumber_cell_evidence` 返回 (bboxes, merges, status)，"无几何"（none）与"几何冲突"（conflict）显式区分；冲突经 `merge_evidence_conflict` 进 merge_evidence_status→needs_review。
- **M2 cell 几何消费**：`_claim_pdf_zones` 对 table_cell claim 用记录的 cell bbox（含页宽高）发真实行级热区；不可用负载（非影印模式早退分支）也携 `cell_context`（`_cell_context_payload` 提取共用）。
- **M3 指纹/血缘**：`extraction_input_fingerprint` 绑 blocks/table_items/table_cell_items 三件套内容 + `TABLE_STRUCTURE_VERSION`（缺文件显式绑缺席）；producer lineage 增 `table_structure_version`。
- **M4 重复句 alias**：同格重复句去重时后续 span 以 `span_aliases`（cell_start/cell_end/raw_locator）保留在主 leaf 上，claim_catalog schema 同步。
- **验证**：设置历史样本环境变量后后端全量 **2436 tests OK（0 skip）**（过程中发现并补修 2 处：meta schema audit 两计数器未登记、desktop_tasks pinned producer 戳缺 `+table-structure-v3`）；前端 Vitest **172/172**、vue-tsc 零错误、`npm run build` 通过；py_compile 与 `git diff --check` 通过。未提交、未推送；合并后按「三 seed KB + domain-pack」重生成 main 的 ABNT golden 并逐项说明漂移。

## 重大更新（2026-07-22）——评测集扩充至 40 条 + 三类自动判定（agent-eval-v2，已合 main `11af616`；主检出全量 1502 tests OK、golden 6/6）

- **判定接生产路径（零 LLM）**：grouping 经 `build_function_catalog(chat=None)` 成对判同组/异组（跨 key 负对自动派生）；must_ask 三档（forbidden 缺省值在零 LLM 派生链零泄漏 + 声明 `expected.detector` 必触发且 `suspicion_policy` 路由问客户/blocking + 语义型如实 manual 不进分母）；hallucination 按 `expected.detector` 声明的护栏族判定（漂移并集按编码∪整数原子匹配 / `foreign_standard_refs` / `opposed_qualifiers`）。
- **提公开零行为**：`vague_acceptance`/`values_left_behind`/`foreign_standard_refs`/`opposed_qualifiers` 纯改名，`clarification_report` 加只读 `suspicion_policy`；225 个护栏/目录测试零改动通过。
- **数据集**：20→40（12/8/10/10），新 20 条源自 test2/test3 真实 suspicion 记录脱敏改写 + 行号溯源；must_ask 金标准遵守全文缺席原则；schema 新增可选 `expected.detector`（按类别收窄枚举，向后兼容）。新基线：classification 8/12（如实保留 v1 三条错分 + classify-010 关键词缺口）、grouping 4/8（v1 四条 under-merge 已知缺口）、must_ask 4/4（manual 6 条另列）、hallucination 10/10；旧 0.625 转历史，合并门此后对照新基线。`EVAL_RUNNER_VERSION=agent-eval-v2`；`AGENT_POLICY_VERSION` 与护栏/缓存指纹版本不动。
- **规格**：`docs/agent-eval-v2-spec.md`（已冻结，含三处冻结/实施修正记录）。**待办**：新 20 条由审核人逐条核对后人工登记 `curation.reviewed_case_ids`（runner 永不改 curation）。

## 重大更新（2026-07-22）——Agent Phase 1.5 真实对比实验裁定：规则保持默认（n=4，llm 决策器不升级；纯实验无代码改动）

- **实验与证据**（机器本地产物，不进仓）：test3 干净副本（`decide_trace`/`agent_loop_summary`/`omission_states` 三文件删除，26 缺口回未登记）跑 `agent_compare`，llm 侧真实调用（deepseek-v4-flash，temperature 0.0）；随后 llm 侧同输入复跑 3 轮留档。证据：`C:\Users\YYHwudi\Desktop\Canna-29\...\test3-agent-compare-clean-20260722\agent_compare_result.json` 与 `test3-agent-compare-llm-reruns-20260722\run{1,2,3}\`（decide_trace + summary + 登记行）。
- **冻结口径四项**：动作序列完全一致率 **0/4**；llm 失败回退 **0%**（run2 的 `rule:1` 是仅剩 stop 的平凡轮，非回退）；tokens **870–1358/run**（均值 ≈1089，`token_accounting=complete`）；终态 readiness **4/4 与 rule 相同**（NEEDS WORK / stopped）。
- **终态产物差异（复演实证）**：rule 确定性产出 `queue_all_gaps → ask_clarification → stop` + `omission_states.jsonl` 26 行 `needs_extraction`；llm 仅 1/4 追平——2/4 丢 26 行缺口登记（omission_states 不存在），1/4 在 62 个必答悬置时提前 stop（真决策错误）。run1 理由原文 "*Queuing gaps would add work that cannot be processed, so stopping is appropriate.*"——把零 LLM 登记簿记当无效忙等，根因是候选动作语义未进提示词。
- **关键实测发现**：temperature=0.0 下同输入三次复跑三种序列——托管端点不保证可复现，对"同一输入同一产物"的审计纪律本身是否决项。
- **裁定**：**规则保持默认**。llm 最好情况 = 追平 rule（run2）；3 候选有界循环无增值空间，提示词修得再好上限也只是镜像规则。llm 决策 revisit 留给 Phase 2（tool-using reviewer，动作空间 richer）。评测基线 0.625 / agent-policy-v3 不变。

## 重大更新（2026-07-22）——Agent 化 Phase 1.5：LLM 决策器对比实验（已合 main `5cd03be`；主检出全量 1483 tests OK、golden 6/6、评测基线 0.625/v3 不变）

- **口径先行**：tokens 计量冻结为"仅决策调用"（含 JSON 修复/截断升级重发，usage 缺失计 0 标 partial，不估算）；澄清"必答未解决"判定收敛为 `clarification_report.unresolved_hard_questions` 单一实现，`agent_state` 委托调用（审核遗留 #1/#4 闭环，`run_report` 行为零变化靠既有测试锁死）。
- **LLM 决策器（非默认）**：`agent_loop --decider llm` 逐轮让模型从候选中选动作；非法选择/调用失败/超 `--max-tokens`（默认 20000）当轮回退规则决策，轨迹 `decider` 逐行如实标 rule/llm；无 key 响亮退出 2，不伪造 stub。汇总新增 `decider_usage`/`token_accounting`。
- **对比器**：`agent_compare.py --out-dir DIR` 复制目录两版分跑 rule/llm，输出迭代/终止/readiness/动作序列/tokens/一致率；无 key 时 rule 照跑、如实标 `llm_ran: false`，不拿单侧结果冒充对比。
- **llm_client 最小增量**：新增 `chat_json_with_meta`（usage 汇聚首发+修复+升级重发），既有 `chat_json` 签名兼容不变。`AGENT_POLICY_VERSION` 升 `agent-policy-v3`，schema const/评测 manifest 随行（基线 0.625 不变）。
- **验证**：新增 17 tests（决策器/回退/预算/对比/usage 汇聚/口径收敛）；worktree 全量 1483 tests（26 skip）；合入后主检出 1483 tests（20 skip）+ golden 6/6；spec `docs/agent-phase1.5-spec.md` 冻结。

## 重大更新（2026-07-22）——agent-policy-v2：决策循环去重与批量登记（已合 main `1d3b61c`；主检出全量 1467 tests OK、golden 6/6、评测基线 0.625 不变）

- **缺陷实证（test3 真实产物 dogfood）**：v1 循环两个真实问题——①逐块登记 26 个覆盖缺口耗尽 10 轮预算，`ask_clarification` 从未执行；②跨运行重复登记：同一 out/ 连跑两次，`omission_states.jsonl` 20 行仅 10 个唯一 block（审核遗留项 2 从"补测试"升级为行为缺陷）。
- **修复**：`AnalysisState` 新增 `pending_extraction_block_ids`（当前 omission 状态为 needs_extraction/issue_confirmed 的块），候选生成只取未排队缺口；新增批量动作 `queue_all_gaps`（一次锁内登记全部未排队缺口，形态变为"一轮登记 → 澄清 → 停止"）；`resample_section` 零 LLM 路径幂等（已排队返回 skipped 不追行）。`AGENT_POLICY_VERSION` 升 `agent-policy-v2`，decide_trace schema const 与评测 manifest 随行（基线 0.625 不变）。
- **测试**：决策器候选/优先级、批量登记幂等、跨运行复跑不重复登记（钉死缺陷回归）、pending 状态聚合等专项 35 tests 绿。
- **范围**：只动 agent_state/agent_tools/agent_loop 及其测试与文档；不改 omission_actions、clarification_report、CHAIN_ORDER。

## 重大更新（2026-07-22）——Agent 化 Phase 1 有界决策循环（已合 main `baba522`）

- **只读状态视图**：新增 `agent_state.AnalysisState`，每轮从 `run_manifest.json`、当前 AI 需求与 blocks、分层覆盖、澄清答复/内部核对状态、`ai_extract_quality.json` 重新聚合，不建立第二套状态账本。决策摘要严格输出冻结 schema 所需的需求数、当前 coverage gap、未解决必答、READY 门和阻塞原因。
- **规则决策器 v1**：`AGENT_POLICY_VERSION` 升为 `agent-policy-v1`，schema const 同步。优先级冻结为 READY 停止 -> failed/uncovered block 按 block_id 补抽 -> 必答澄清 -> 停止；默认 10 轮、上限 50、tokens 恒为 0。每轮（包括 stop/error/skipped）均追加有效 `decide_trace.jsonl`，失败/不可执行动作后续剔除，预算耗尽时行数等于上限且最后一条为 skipped；终态另以锁内原子替换写 `agent_loop_summary.json`。
- **零 LLM 冲突的诚实处理**：现有 `targeted_reextract` 强制 `openai_compatible` 且会实际调用模型，不能同时满足 Phase 1“全程不调 LLM”。v1 不伪造确定性补抽：`resample_section` 在 extraction operation lock 内将当前遗漏登记为 `needs_extraction`，轨迹如实记 skipped；薄封装仅在外部显式 `allow_llm=True` 时委托现有补抽。`recheck` 契约已暴露，但规则 v1 不选择；因现有语义复核没有可安全单独发布的零 LLM 入口，调用时同样如实 skipped。`ask_clarification` 直接复用现有报告生成器。
- **范围**：新增 `agent_state.py` / `agent_tools.py` / `agent_loop.py` 并注册 py-modules；不改 `CHAIN_ORDER`、READY 阈值、现有抽取/复核实现、UI 或 `gui/`。CLI 为 `python agent_loop.py --out-dir DIR [--max-iterations N]`，遵循 JSON envelope 与 0/2/3 退出码。
- **验证**：Phase 1/轨迹专项 **29 tests**；隔离 worktree 全量后端 **1461 tests（26 skip）**；Phase 0 评测仍为 `5/8=0.625`，manifest 仅将 policy v0 更新到 v1，人工审核 5 个 case ID/元数据未改写。真实 test2 产物复制到临时目录后跑 2 轮：2 条轨迹均过 schema、`decider=rule`、按 block_id 选择补抽、结果如实 skipped，摘要保持 `NEEDS WORK` 且 tokens=0。合入 main 后主检出验收：golden **6/6** 实跑通过，全量后端 **1461 tests（20 skip）** 两次全绿（首次运行曾现 1 个瞬时 error，复跑两次 + 专项五连跑均绿，判定为 Windows 文件占用类抖动，留痕待观察），评测基线 `0.625 / agent-policy-v1` 不变。审核人另以播种缺口夹具独立复验端到端：3 条轨迹过 schema、缺口如实登记 `needs_extraction`、摘要 NEEDS WORK。

## 重大更新（2026-07-22）——Agent 化 Phase 0 骨架（已合 main `4161f18`）

- **范围边界**：本阶段不实现决策循环、不接 LLM 决策、不改 UI/既有状态账本；只冻结评测集、决策轨迹格式和策略版本锚点，Phase 1 未开始。
- **评测基线**：新增 `golden_sets/agent_eval_v1/` 共 20 条（分类 8、分组 4、必问 4、幻觉 4）。客户场景仅保留脱敏改写并登记仓库内证据来源；后三类 Phase 0 仅校验 schema/计数。现有确定性分类实测 `5/8=62.5%`，如实保留英文 battery、IP enclosure、仅文号审批三处错分。项目审核人已于 2026-07-22 逐条核对 `classify-001/003/005/006` 与 `must-ask-001`，manifest 仅登记这 5 条，runner 回归锁定不得改写人工审核字段。
- **冻结契约**：`agent_eval.py` 使用 JSON Schema 校验并输出 CLI JSON envelope；`schemas/decide_trace.schema.json` 冻结 `decide-trace-v1` 必填字段，`decide_trace.py` 按 `review_state.py` 同型跨进程锁在锁内 fsync 追加单行，并重试 Windows `PermissionError`。新增运行依赖 `jsonschema>=4.23.0`。
- **版本纪律**：`agent_policy.AGENT_POLICY_VERSION=agent-policy-v0`；`desktop_tasks.stage_producer()` 只为未来 `agent-*` 阶段预留该后缀，现有阶段 producer 字符串逐项不变，因此不触发已有缓存或 ABNT golden 失效。
- **验证**：Phase 0 聚焦 13 tests、隔离 worktree 全量后端 **1438 tests（26 skip）**、前端 **130 tests**、`vue-tsc` 与 Vite 临时目录构建、Python compileall 均通过；合入 main 后 golden **6/6** 实际执行通过，主检出全量后端 **1438 tests（20 skip）**；评测 CLI 输出 20 条计数及 62.5% 基线。

## 重大更新（2026-07-20）——test2 招标 PDF 解析、合规分流与审计闭环（分支待复核）

- **根因与边界**：test2 是 Google 机翻 PDF，词内空格是内容流里的真实空格字形，调 `x_tolerance` 无效；旧 `defragment_text` 又会把 `i s obliged`/`b e able` 链式误并为 `i sobliged`/`beable`，继而使来源引用锚定失败、真实需求被漏掉。修复坚持确定性和“宁漏勿猜”：结构编码仍只允许原文逐字锚定，无法唯一判断的残留只显示为审计信号，不自动改字。
- **PDF 文本修复 v2**：内置 `parsers/data/english_words_top50000.txt.gz` + 电表域词，按词频与唯一切分修复单字母碎片、粘连词、全大写缩写、拆分数字和假粗体；每块保留 `raw_text`、修复前后、规则与坐标，词表/算法 hash 纳入解析缓存和 PyInstaller 资源。质量报告区分“实际修复事件”与“保守疑似碎片”，避免把“修复器已无把握”误报为“文本已无缺陷”。行为版本 `PDF_TEXT_REPAIR_VERSION=pdf-text-repair-v2`，抽取 prompt/护栏升级为 `ai-extract-v21` / `guards-v9`。
- **来源与覆盖口径**：引用匹配改为空白不敏感、标点/数字/编码严格保留，支持 12 个相邻块及多摘录；`section_fallback` 不再虚标整章覆盖。覆盖拆成 `core` / `compliance` / `excluded` 三层；当前指纹仍匹配的专家 `non_requirement` triage 从 core/compliance 分母移出并在 excluded 留审计原因。fuzzy 映射和未验证 echo 不计覆盖，echo 使用与批注视图同源的确定性重复门；旧顶层字段继续代表 core，就绪门读取实时 core 覆盖率。
- **compliance 独立流转**：证书、法令、初始检定、符合性声明等不再挤入软件/硬件研发需求；输出 `compliance_requirements.json`、`compliance_items.json/md`，功能合成（`functional-synthesis-v6`）、软件分析和模板成文均防御性排除。结构分流只读原文证据，生成的 type/title/description 不能改覆盖分母；“技术义务 + 末尾证书/法令引用”的混合块保留在 core。umbrella 只由原文多个合规义务确定，instrument 错配不再静默替换且保留审计说明；合规义务也经过编码/数字/标准号漂移护栏。未处置合规漏项作为 blocking 内部核对项保留，不靠改分母掩盖。
- **审计与操作性**：质量报告记录失败章节及具体块，Vue/静态 HTML/PDF 热区均提供轻量“原文修复”“抽取失败”标记，点击可查修复前后与事件明细。内部核对新增按 signal/module 批量确认，整批在单锁内原子写入，每条必须匹配当前 `evidence_fingerprint`；stale/missing/ineligible/duplicate 分类汇报，409 会刷新证据并要求重新确认。模块自由文本前后端均限制为非空、最多 20 字；旧目录覆盖率明确标记 `legacy`。澄清报告版本为 `clarification/v6-coverage-basis`，一致性报告版本为 `merged-consistency/v2-triage-strict-evidence`。
- **跨文档模块沉淀**：模块控件支持自由文本 + 建议列表；后端 `/document` 返回 bank 词表且 Vue datalist 实际消费；已接受的 `module_override` 在裁决/API 导入后立即收割到 `RATOMIZER_ADJUDICATION_BANK`。样本库使用跨进程锁、Windows `PermissionError` 重试和原子替换，并记录模块使用计数；旧 bank 的 accepted 范例也可直接形成模块词表。
- **test2 确定性实测**：569 块中 408 块发生修复，共 4723 个修复事件；同一保守探针的疑似断词率 `24.91% -> 1.93%`（4333 -> 246），重复运行的块正文、原文和修复事件逐块一致。复用旧 127 条真实 AI 需求映射到新块做离线链路核验：core `119/162=73.46%`、compliance `6/6=100%`、excluded 7；独立合规条目 3（其中一个 umbrella 含 5 项义务），DLMS/COSEM over IP 双向通信探针命中。按当前确定性功能合成后有 121 条研发分析项且无 compliance 混入。就绪门仍为 `NEEDS WORK`：158 条内部核对尚未处置，其中 48 条 blocking，且普通待澄清量超阈值；core 覆盖率已通过 60% 门槛。
- **诚实限制与合并纪律**：本轮无可用 LLM/API Key，未执行 `ai-extract-v21` 的 test2 在线全量复抽；上述需求侧指标是旧真实抽取结果的离线重锚定，只验证确定性后处理与分流，不宣称验证新 prompt 召回。隔离 worktree 全量为 **1415 unittest（26 skip）+ 130 vitest + vue-tsc/Vite build**；`git diff --check` 与 Python compileall 通过。golden 文件未修改；合入 main 后必须按三个种子 KB + domain-pack 重生成 main 的 ABNT 输出并完成 golden 零漂移或逐项说明，才算最终合并完成。

## 重大更新（2026-07-19）——审查并行化与遗漏闭环（已合并 main `26a72f7`）

- **运行中增量审查**：AI 抽取逐终态章节发布 `ai_requirements.partial.json`，前端按章节进度节流刷新需求与 PDF 标记，复用已加载页图；早期裁决绑定需求 id + 来源/审查内容指纹，内容变化后保留历史但强制复核。final 新增 `ai_requirements.meta.json` 绑定 `blocks.jsonl` 代际，stale partial/final 不得跨文档回退。
- **澄清闭环**：必答拆为问客户/内部核对，内部核对用 `verified_ok / issue_confirmed / deferred` 审计状态；只有证据指纹仍匹配的 `verified_ok` 和客户答复可消解就绪门/进入分析权威输入。就绪门分开统计阻塞项、普通问题、内部核对、覆盖率与失败章节；旧工作簿在写入前校验新版列。
- **遗漏可行动**：`omission_states.jsonl` 记录非需求/确认遗漏/已补抽；定点补抽只跑目标章节并走原抽取护栏，补丁以策略、原需求、全部来源块和前置条件指纹约束，版本为 `ai-supplement-v3-identity-preconditions`。补抽会刷新 AI final 代际、质量覆盖率、merged spec 与下游输入指纹；full/targeted/下游消费共享跨进程 lease。
- **翻译降级与缓存纪律**：批量失败后按单条、再按句段重试，每级过同一数字/编码护栏；旧 accepted 译文先以当前 guards 零调用复验，迁移前不展示。存在 unresolved/failed call 时 `export-annotation-html` manifest 记 `partial`，下次 chain 必须重跑；producer 动态纳入翻译策略与 guards 版本。
- **专家操作效率**：文档审查支持 `j/k` 顺序导航与 `a/r/d` 裁决，输入框/IME/重复键防误触；同输出目录 API 重连保留选中项和按 requirement/block id 暂存的评论、模块、归属、遗漏备注，异步响应均有 client/generation 护栏，结构化 409 会刷新当前证据。
- **验证**：历史样本启用的后端 `1341 tests`（0 skip）、前端 `vitest 120`、`vue-tsc + vite build`、Python/Node 语法检查与 `git diff --check` 全部通过；golden 文件未修改。

## 重大更新（2026-06-27）

- **GUI 决策（已拍板，勿重新讨论）**：仓库里 PySide6（`gui/`）与 Vue3+Electron（`ui/`）两套 GUI 并存，**正式产品以 Vue3+Electron 为准**，PySide6（`gui/`）**冻结、不再投入**。GUI 改动只动 `ui/`，不碰 `gui/`。下文历史段里凡写「专家工作台(PySide6)」均指已冻结的旧壳。
- **平台架构演进（以 `README.md` 为最新）**：核心 Python（`atomize`/`cli`/`assemble_spec`/`engineering_composer`）+ **本地 API `api_server.py`**（只读 + 审查写入端点，origin allowlist + 可选 token）+ **Electron 任务桥 `desktop_tasks.py`** + **Vue3+Electron UI `ui/`**；知识库迁为 **`requirement_kb/` 包**（Obsidian vault → 编译 JSON）；解析器在 **`parsers/`**（docx/xlsx/pdf）。
- **终点交付物数据完整性修复（Phase 1+2，分支 `codex/spec-data-integrity`）**：一轮严格 code review 发现并修复 5 项直接污染研发实现规格的缺陷——
  - **H1 OBIS 静默拆码**：`cosem_object_model._normalize_single_obis_value` 移除无证据的「2 位值组拆单数字」（会把 `0-0:96.1.0` 静默腐蚀成 `0-0:9.6.1.0`，违反"OBIS 错一位即严重"）；缺分隔点的修复改走空格还原路径（仅在有空格证据时）。
  - **H4 访问权限错列**：`parse_access` 切不出 4 段时不再把整串塞 RC 列；新增统一 `access_cells()` 渲染（cosem MD/CSV + `assemble_spec` 门限表共用），四列留空 + 新增 `access_raw` 列追溯 + MD 未解析附录。真实 ABNT 1425 行 **0 错列**（`Association LN.add_user -/-/-A--` 入待审附录）。
  - **公式注入**：新增 `text_normalize.formula_safe()`，中和 Excel/CSV 里 `= + - @` 开头单元格（豁免纯数字与 DLMS 访问码），应用于 `spec_excel` 与 cosem CSV 导出。
  - **H2 审查校验绕过**：`llm_review_schema` 把必填字段 `None` 视为缺失，恢复 schema 修复回路（此前 `decision=None`/`confidence=None` 静默过校验）。
  - **H3 KB id 遮蔽**：`requirement_kb.repository.get()` 改首个/权威优先 + 新增 `id_collisions()` 暴露冲突（默认 4 库 86 处），不再随加载顺序静默遮蔽权威条目。
  - 验收：**全量 416 tests 全绿**（含各项新增回归），atomize golden 未动，真实 ABNT 端到端 `assemble` 注入样本 0 活公式。
- **Phase 3 端到端硬化与 gui 冻结（分支 `codex/phase3-golden-and-freeze`）**：
  - **P3-A 终点交付物 golden 回归**（`tests/test_spec_deliverable_regression.py`）：合成 fixture（含 H1/H4/注入触发场景）端到端跑 `assemble`→Excel，锁定 OBIS 稳定 / access 零泄漏 + `unresolved_access` 计数 / Excel 零活公式 / 计数。fresh-clone 可跑——把 Phase 1+2 修复变成永久回归（此前终点交付物零回归保护）。
  - **P3-B 解耦 `review_actions`**：从 `gui/` 提升到顶层 `review_actions.py`，`api_server` 改 import，`gui/` 成无人依赖的纯 PySide6 叶子；`ui/package.json` 打包配置同步移除 `../gui` 拷贝（后端依赖已被顶层 `*.py` 覆盖）。
  - **P3-C Vue3 前端 5 项 UX 修**：API 错误体透出后端原因（不再只显示状态码）、`originalText` 回退 `source_context.paragraph_text`、`confidenceFilter` 默认「全部」、审查按钮 `isSubmitting` 防抖、审查意见 textarea 接 `v-model` 并作为 `reason` 提交。`vitest 39 + vue-tsc` 全绿。
  - **P3-D gui 冻结**：README 标注 `gui/` 冻结。**保留代码/入口/测试**（冻结≠删除；`test_platform_scaffold` 契约化了 `ratomizer-gui` 入口，且不删能跑的东西）。
  - 验收：**Python 420 tests + ui vitest 39 + vue-tsc** 全绿。
- **测试规模**：196 → **420 tests**（`python -m unittest discover -s tests`）+ ui `vitest 39`。

## 重大更新（2026-07-04）——AI 抽取轨 + agent 化四方向全部落地

- **AI 主抽双引擎轨（`ai_extract.py`，2026-07 上旬）**：LLM 逐章节抽行为需求 + 确定性结构需求合并 → `ai_requirements.jsonl` / `merged_spec_requirements.json` / `merged_spec.xlsx`。上下文工程（`build_doc_context`：表计画像+术语表+大纲注入每章，折进缓存指纹）；**自检收敛循环**（定向模式 loop-until-dry，默认 3 轮硬顶 6，env `RATOMIZER_AI_SELFCHECK_ROUNDS`；盲查单趟防过度生成）；防幻觉分级护栏（code_drift 严拦 / int_drift 软标，基线=章节原文）；prompt v6（dev_guidance 研发指引）。
- **文档批注闭环**：批注视图（Vue `DocumentReview` + 可分享自包含 HTML）——段落级锚点、归属/模块下拉、suspicion 徽章；裁决写 `ai_review_states.jsonl`（内容稳定 AIR-sha1 id）→ `rebuild_merged_spec` 免 LLM 重建交付物（rejected 剔除、override 生效）。
- **软件需求分析轨（`requirements_analysis.py`，GLM 实现 + 多轮复查修复）**：软/硬/协同归属分类（规则初判+专家改判）→ `software_requirements.xlsx`（公司模板版式）+ hardware/co_design 清单；**LLM 富化层**（openai_compatible）推导可研发正文——结构/归属/id 冻结、编码硬拒/整数软标、无 key 如实降级 stub、内容指纹缓存、**并发+增量落盘+逐条进度**（288 条真实规模跑挂的教训：串行数小时+零落盘）。
- **全局一致性 critic（`merged_consistency.py`，确定性零 LLM）**：合并后产 `consistency_report.json`（跨章重复/OBIS 共引数值待核/覆盖缺口）；**已闭环**——摘要进跑完消息、批注视图行带 `consistency_flags` 标记。
- **裁决学习回路（`review_insights.py`，确定性零 LLM）**：从 module/ownership override 模式提炼规则改进建议（≥3 次成建议，人审采纳），裁决回流自动刷新 `review_insights.json/md`。
- **P2 行为层 RAG（Blue Book，GLM 实现 + 验收修复）**：`blue_book_ingest`（两 PDF 确定性编译 98 接口类+70 OBIS 节，逐字节可复现）→ `blue_book_lookup`（class_id/类名**精确**查找，不猜）→ `spec_enrich` P3 富化注入条款（出处程序校验+补写、drift 基线扩至条款、指纹折条款 hash）。桌面**自动探测**（`resolve_blue_book_index`：显式>env `RATOMIZER_BLUE_BOOK_INDEX`>out_dir>仓库 out/bluebook）。真实验收：ABNT 端到端注入出处逐条核对全过。**检索是确定性查找而非向量语义（刻意）**：宁漏勿错；语义回退留作将来升级路径。
- **GUI「运行」= 可配置整链**：4 个交付物按钮合并——设置面板「运行阶段」勾选（AI抽取/装配/分析/组装，localStorage 持久化），点「运行」按依赖顺序跑完；顶栏「LLM」勾选统一控 openai_compatible 路由；逐阶段进度（analyze 富化 n/total）。
- **LLM 端点（本机）**：小米 MiMo `https://token-plan-cn.xiaomimimo.com/v1`（`mimo-v2.5`/`mimo-v2.5-pro`，推理模型）；**该端点只认 `x-api-key` 头**——`llm_client` 已双头同发兼容。密钥经 GUI 设置面板 safeStorage 加密存、内存解密注入 env，绝不落盘。
- **双轨行为需求分工（建议已记录，终局待用户拍板）**：`assemble`（A 轨：atoms+llm_review，P1-P5）= **DLMS profile 类文档**的结构规格主交付物（蓝皮书行为富化挂此轨）；`merged_spec`+`analyze`（B 轨：AI 抽取+批注裁决）= **非 DLMS 剖面类文档**（散文型标准，无 COSEM 对象表，如 AFD/SM-CG 附加功能标准）的行为/软件需求主交付物。两轨并存各司其职，交付时按文档类型选主件。
- **有据缓建（实测量化为零收益，勿投机重启）**：① analyze 接蓝皮书——B 轨需求无接口类名可匹配（test5 多词类名 0/288）；② OBIS→class 连接提升蓝皮书覆盖——ABNT 行为 atom 正文 0 个 OBIS 形码（码全在表格→P1）；③ 类名归一化/别名——ABNT 未命中全是抽取噪声或 Green Book 领域引用，归一化救回 0 条；④ Part1 OBIS 节（70 节已摄入）——留给将来 OBIS 语义富化，暂无消费者。重启任一项前先在新语料上重跑探针。

## 重大更新（2026-07-15）——抽取质量重构七刀（已合 main）

- **背景与纪律**：用户裁定双线对比全遍历验收（工具 ≥ Claude 自身解析基线,整文档不抽样）+ 通用规则不打单文档补丁（fixtures 合成中性化,禁止测试文件作弊）。评测资产在 scratchpad `dual_track_eval/`（含客户内容**不进仓**）:units.jsonl 冻结坐标系 110 单元、reference_*.jsonl 参考基线 121 条、compare.py 对齐、4-agent 全遍历内容审计（A误读/B不自包含/C遗漏/D空话验收/E指引空转/F语言/G引用失真,好/中/差）。
- **七刀内容（15 commits）**：①目录子树打包 `pack_by_outline`（条款族=一条需求;test 标题绑前兄弟;三明治吸收水印夹层;ABNT 结构门 blocks=1362/items=2036 逐字节）②忠实性护栏族 `extract_guards`（情态升格/外标准号/定义桩/漏值窗口归一/数词与千分位基线）③自检并入契约（supplements 目标匹配+越界丢弃+锚定复核;未匹配转独立通道防漏抽）④数值配对+表文单元格一致性（表通道可靠文通道抄错:Type1 1 l/h→正文 5 l/h 实证）⑤**资料性附录跨单元状态机**（informative 区段条目降 P2+硬标——Annex B 对照表升格 9 条差评的最大病灶）⑥溯源节号原文回填（锚点必须自证质量:带点条款号/字母条款/Annex 行,裸整数图注不作证据——六刀自伤七刀修复的教训）⑦元话语句级剥除+去重加固（标点底座 J≥0.5+数字多重集守卫,校准实测恰好保住 1型/2型 异档判据）+情态确定性软化（should 引句的"必须"→"宜"）+RS232/EN 号整移豁免。prompt v18（免责从句保向/Q max 下标/单位词不猜译/步骤号配对复核）。
- **缓存指纹产品缺陷修复**：缓存存终处理结果而指纹只含 prompt 版本→护栏升级被旧缓存整体绕过（实测 wall=0s 零生效,GUI 用户升级即中招）。已修:`EXTRACT_GUARDS_VERSION` 折入 `section_fingerprint`,护栏行为变更必须 bump（现 guards-v4）。
- **三轮真实全量验证（EN 16314,mimo-v2.5-pro,每版 4-agent 整文遍历审计）**：条目 186(v1)→160、差评 17→12、A 误读 34→23、多抽 47→33、漏抽 14→13、拆碎 30→25;定义条目/自检碎片/同标签重复/标准号误归属假阳全部归零;资料性升格 9→0。**残余差评已收敛到 LLM 语义理解层**（免责从句反转/范围方向反转/one-or-more→全部/受试主体错置——prompt v18 针对性写入仍复发,mimo-v2.5-pro 能力边界）,用户已拍板走"第二遍 LLM 复核"（见下条,已合入）。
- **专家审核修复+回声锚点（2026-07-16 合入）**：①阶段续跑指纹缺口——verify 开关/轮数进 env 清单,producer 折入 guards+verify 版本（EXTRACT_GUARDS_VERSION 三次升级从未失效过阶段指纹,与缓存指纹同族的洞一并堵死,现 `ai-extract-v18+guards-v4+ai-verify-v1+impl-v3`）;②自检并入路径复用交付字段整移护栏（无据数字不再能经并入直进验收）;③**重复文本回声锚点**（电表招标实证:同段两处出现第二处无标注被误判"没解析出"）——`echo_block_ids` 视图层字段 api_server 单点计算双渲染器同源,匹配判据真实探针校准（全剥空白互含+原文近重复 J≥0.8+数字守卫）;用户裁定轻量显示:重复段只给"重复·见NN"角标+重复段卡片,不重复挂 chip,汇总层归并,parent_numbers 契约锁防倒退。**招标类文档教训**:名词短语式规格无情态动词,规则层 requirement_like/A 轨对其全盲,coverage_candidate 安全网同样失明——招标文档必须走 B 轨(AI 抽取)作主件;范围声明剔除正则只认 "this standard" 词面对 "this technical specification" 失配（侥幸留活,判据缺口已记录待跨文档探针）。测试 1198 unittest + 79 vitest。专家审核悬项:二遍复核自动改写、同名需求 by_title 对齐(碰撞挂错),等最小复现结论后修。
- **二遍语义复核轨（同日合入,用户拍板）**：每章节抽取+自检+折叠后 **N 轮复核投票**（默认 2 轮,`RATOMIZER_AI_VERIFY`/`RATOMIZER_AI_VERIFY_ROUNDS`,开关+版本+轮数折入缓存指纹）,只查七类误读受控清单（免责从句/方向/数量词/主体/数值配对/步骤号/归属）;发现须**双侧逐字锚定**才采纳为软标+证据留痕,自动改写仅当精确子串+过漂移守卫,绝不新增条目。实测:单轮对细微语义错误命中率仅 1/3（模型判断随机性,定点探针实证）;2 轮后三大慢性错类全部落网（温度方向/免责从句/one-or-more）,17 标记精度 ~60-73%（误报均软标）,10 改写零事实损伤,成本 +4min/链。轮数=召回/成本旋钮。
- **教训入库（testing-blind-spots）**：缓存类系统的确定性后处理版本必须进缓存键;护栏的覆盖动作必须要求锚点自证质量（六刀溯源校正把正确 D.3.3 改错）;suspicion 自标与真实缺陷相关性弱（真差评零自标,自标反是误杀）,软标分布不可当质量指标。
- 测试规模 **1174 unittest**;新增回归集中在 `tests/test_faithfulness_guards.py`（926 行）与 `tests/test_outline_packing.py`。

## 重大更新（2026-07-14）——整体 review 三批次：速度与效果 25 笔（已合 main）

- **量化依据（EN 16314 全量真实 trace）**：一轮 ~1030 次 LLM 调用累计 5.5h 模型时间;审查 371 次/147min 最大单项;抽取轨 164/781 次 429 限流(有效并发 3.2/4);富化两轨 66+34.5min 逐条调用。
- **速度**：审查并发接通 GUI 设置+全局默认 4→8;**富化合批**(软需同模块 `RATOMIZER_ANALYZE_BATCH`=4、硬件×2、装配无蓝皮书条目 `RATOMIZER_ENRICH_BATCH`=6;enrich_slot 槽位映射宁缺勿错、失败回退单条;缓存 key 逐条与批组成无关;护栏逐条不放宽——真 mimo 验收零串条);**429 自适应闸门**(`RATOMIZER_LLM_ADAPTIVE`,按端点全局冷却+在飞上限 AIMD);JSON 模式默认开(端点不支持 4xx 一次记住降级);分析 prompt 按稳定性降序重排吃 KV 前缀缓存;**缓存 key 收窄**(软背景 doc_context/siblings/exemplars 进 prompt 不进 key——背景漂移不再整库报废);裁决重建防抖(`RATOMIZER_REBUILD_DEBOUNCE_S`=1.5s);api_server 装配路径按源文件签名 memo(deepcopy 防串改);链内 8 阶段 summary 白算跳过。
- **效果**：冻结归属注入富化 prompt(analyze-llm-v6,模型只写不判);富化部分降级上屏(note+样本消息);**遗漏候选进澄清清单**(uncovered_samples 带 block_id 溯源,TIER_GAP 独立档不进就绪门,clarification/v3-gap-tier);**双渲染器信号补齐**(应用内补「所属研发功能」整块+跨章合并置信徽章≥2源/<0.9 警示;静态 HTML 补 consistency_flags;契约夹具锁三信号);**覆盖/遗漏统一口径** `merged_consistency.is_coverage_candidate`(剔除标题/引用书目/非正文假阳性;requirement_like 候选生成宽口径不动);**PDF 水印串确定性清除**(三清洗点;ABNT A/B 逐字节零变化、EN16314 61→0);guidance 模板编码软标 template-sourced(无声放行契约作废);review_insights 接通消费端(GET /review-insights+工作台「裁决复盘建议」卡);**裁决样本回灌抽取**(accepted→「模块+标题」few-shot,软背景不进指纹);functional_key 构造规则+priority 判级基准(ai-extract-v16,真实小样 P0/P1/P2 分级生效)。
- **数据否决记入有据缓建（勿投机重启,重启前重跑探针）**：⑤ 零 requirement_like 章节跳 LLM——省 35% 抽取调用但真实 158 条需求有 16 条(10%)完全来自这些单元(定义类条款规则认不出);⑥ assemble 内同文件读 2-4 遍去重——动 5 个 golden 邻接模块换每链 1-2s。
- 测试规模 **1082 unittest + 77 vitest**;新增回归集中在 `tests/test_batch{1,2,3}_0714.py`。

## 重大更新（2026-07-06）——TODO 全量清扫（架构债+组件增强）与深测裁决

- **架构债 F1-F8 全清**：chain 单命令编排+run_manifest（F1/F7，前日）；requirement_record 行契约+provenance 血统戳（F2）；xlsx 安全保存（F8）；llm_client 用途 floors 收口（F4）；config.ENV_REGISTRY 配置单源+强制核对测试（F5）；ai_extract 拆分 extract_units/extract_guards 门面保旧名（F3）；双渲染器共享契约夹具测试（F6）。系统地图见 `ARCHITECTURE.md`，待办勾选状态见 `TODO.md`。
- **组件增强落地**：裁决样本库 `adjudication_bank.py`（env RATOMIZER_ADJUDICATION_BANK，accepted→few-shot 注入富化，chain 尾自动收割）；**澄清答复回灌闭环**（必答 sheet 答复列→导入（GUI「导入澄清答复」）→富化注入+有据基线扩展→报告消解；真实往返验证：2 答复 46s 重跑仅重富化关联条）；Annex 引用解析 + 术语定向注入（prompt v11）；中英术语对照（每文档一次缓存）；JSON 模式开关（mimo 双模型探针支持 json_object）。
- **模型 A/B 裁决（勿重启）**：mimo-v2.5 vs pro 全量双跑——fast 覆盖率略高但漏值/重复/空话验收全劣，且并发限流下墙钟无优势（716s vs 741s，调用反翻倍）。**pro 保持默认**；数据 ab_arch/deep_test_result.json。
- v11 回归零倒退（覆盖率 65.8、失败 0、自检占比 14.1%）；测试规模 **744 unittest + 55 vitest**。

## 重大更新（2026-07-05）——B 轨终局架构：理解→分析→按公司模板成文

- **架构三轮裁定（用户）**：公司《电表软件标准化需求列表》V2.3.x 是**交付格式与知识源，不是问题库**——否决"问题库检索作答"（带着答案找问题）；终局链条：**理解**（AI 抽取按文档逻辑，地区无关）→ **分析**（analyze 轨：软/硬/协同+可研发正文）→ **成文**（`template_writer.py` 确定性零 LLM：分析结果按模板格式追加进对应模块 sheet，模板行原样保留、硬件跳过、无对应 sheet 落「其他需求(新增)」页）。桌面端设置面板可选模板路径（localStorage），运行链/测试运行自动接成文，产 `软件需求列表-成文.xlsx`。
- **模板知识注入（analyze-llm-v2）**：模板 19 sheet ~1160 行（描述/需求模版/**说明示例**——选项枚举/条件做法/固件宏名）运行时现读为公司知识（不进仓不落索引），富化 prompt 按模块+词面相关注入 top-8（`extract_template_knowledge`/`select_template_references`）；防搬运：需求正文数值只准客户有据（漂移基线故意不放宽），公司做法进 developer_guidance 带「公司通用做法：」标注。真实验收：注入路由 14/14 精确、30 条公司做法落指引、漂移拒绝 0。
- **抽取质量修复束（2026-07-04/05）**：跨章节引用解析（"given in 7.13.4.5.1"→被引条款注入+漂移有据）；数值落地（prompt v8 强规则+漏值检测 suspicion）；条款族切分（4.6.1 要求+4.6.2 测试同单元，prompt v9：条款族=一条需求+sub_items 二级+Test→验收）；批注三级标记（黄=引用依据/蓝=证据段/细条=分析上下文）+分层编号（01/01.a）+全局消息条。真实 ABNT 全量：覆盖率 81.2%、108 章仅 1 失败。
- 模板文件是公司资产：**绝不进仓**（与蓝皮书 PDF 同纪律），机器相关路径 `C:\Users\YYHwudi\Desktop\Canna-29\电表软件标准化需求列表-V2.3.12 - 2026-4-14..xlsx`。

## 历史状态（2026-06-16，已被上文覆盖）

- **已合入 main**：M1a CLI 契约、M1b GUI 审查工作台、M2 LLM 审查路由、M3 document_profile + PyInstaller 双 exe、M4a Excel 接入、M4b PDF 文字层、A1-PDF-1（`first_field_value` 去空格 fallback + `pdf_parser` 段落切分透传 document_profile，0.7.1）、GUI Phase 1 仪表盘重构 + 复查修订（`5f9e059`）
- **需求文档生成轨道 P1-P5 全部落地（2026-06-15）**：P1 数据字典 `cosem_object_model.py`、P2 访问/安全矩阵 `cosem_access_security.py`、P3 功能/行为派生 `cosem_behavior_spec.py`（已对齐公司格式 + 13 质量规则）、**P4 外部规范交叉引用索引 `cosem_external_refs.py`（`9f4e3be`，确定性零 LLM）**、P5 装配 `assemble_spec.py` + **人读导出 `spec_export.py`**（JSON 喂公司工具链 + Word/MD 人读规格：按功能域分组、带溯源、外部规范附录）；均有单测
- **生成器接入 GUI + 标签精化（2026-06-16，`e5815d1`，已推 origin）**：① 专家工作台应用栏「装配实现规格」按钮（`gui/pipeline_worker.AssembleSpecWorker` 复用后台线程）→ 结果对话框；② 左栏「实现规格」整段需求视图（`gui/spec_view.py`，按 21 领域分段、复用 `spec_export.group_by_domain`，与导出同分组）；③ **Excel 导出 `spec_excel.py`**（版式移植公司 requirement-analyst 技能的 `generate_excel`，逐 sheet 一致；装配默认产 JSON+xlsx+docx+md）；④ **标签精化**：`requirement_schema.map_labels` 按对象名分类、特定域优先于「通信协议」（事件记录/状态字排在计量前处理 current=当前 假朋友）+ `assemble_spec` P1 用对象名分类——**通信协议 388→77**，计量/事件记录/安全/门限范围/需量各就各位
- **剩余**：① P1-P5 + requirement_schema/text_normalize/spec_export/spec_excel 未注册进 pyproject `py-modules`（独立小清理；打包靠 ratomizer.spec 的 hiddenimports 兜住）；②（可选）**描述 LLM 富化**——Excel/规格版式已对齐 skill，但 `description` 仍是确定性模板，不如 skill 的 LLM 叙述丰富；富化时须保留 OBIS/CL/访问位等结构字段确定性不变（防幻觉）
- **本机环境（E:\Codex\requirement-atomizer-github，Python 3.14 + PySide6 6.11 / pdfplumber / openpyxl / pyinstaller 全装）**：196 tests 全绿；真实 docx/PDF 在 `C:\Users\YYHwudi\Desktop\Canna-29\`、golden 基线输出在 `out/abnt_nbr_16968_atomizer_v5/`（带三个 `--kb` 生成）
- **暂缓**：M4c 扫描件 OCR（等英文扫描件语料攒够再立项）

> A1-PDF-1 验收实测（2026-06-13，真实 ABNT 文档）：DOCX golden 六项全绿（DOCX-safe，fallback 仅精确匹配失败时触发）；PDF 候选 326→1991（达 DOCX 基线 2337 的 85%），`cosem_object_instance`=363 与 DOCX 精确相等；全量 128 tests 全绿。注意 golden 必须带三个 `--kb` 生成，否则 llm_tasks / 类型分布 / domain_table_candidate_ratio 会假漂移。

## 需求文档生成轨道（研发实现规格）—— 2026-06-14 立项

> 用户已确认：原子化只是中间产物，终点是把 atom 装配成给**研发团队**的可落地实现规格（据此实现 DLMS/COSEM 计量软件）。此轨道由 Claude 直接掌控实现。

- **目标分两层**：
  - 数据/配置层（对象模型、OBIS、class_id、访问矩阵 RC/PC/SC/LC、单位、事件枚举）——已在结构化字段，**装配优先**、可逐字段验证，是 DLMS 实现规格主体。
  - 行为/协议层（GET/SET/ACTION 语义、关联建立/HLS 握手状态机、加密策略、错误/access-result 码）——ABNT profile 多为交叉引用 DLMS Green/Blue Book，atom 里没有，需 LLM 派生 + 引进核心文档当 KB，**高幻觉风险**。
- **关键技术事实**：cosem atom 由 `table_item` 生成；结构化字段（OBIS、CL=class_id、属性、访问权限、单位）经 `source_refs → source_index → table_item.fields` 可确定性取回（GUI 详情面板已这么 join）；`verification_method` 已 denormalize 到每个 atom（验收/验证方法的种子）。**数据字典 = 确定性 join，不用重抽。**
- **范围真相**：单凭一份 ABNT profile 文档 → 极好的数据字典 + 访问矩阵，但行为/协议单薄；完整实现规格迟早要把 DLMS Green/Blue Book 作为额外输入/KB。
- **阶段（状态截至 2026-06-15，P1-P5 全完成）**：P1 数据字典 ✅ / P2 访问安全矩阵 ✅ / P3 功能行为派生 ✅（已对齐公司格式 + 13 质量规则）/ **P4 协议交叉引用 ✅**（C 折中：确定性引用索引，零 LLM；按 manifest 源文件名排除文档自身号；Green/Blue Book 俗称仅附 5-3/6-1/6-2 并标公开常识）/ **P5 装配 + 人读导出 ✅**（JSON + Word/MD/**Excel**，按功能域分组、带溯源、外部规范附录）。**已接入 GUI（2026-06-16，`e5815d1`）**：装配按钮 + 整段需求视图 + Excel 导出（对齐公司 skill `generate_excel` 版式）；标签精化使分段准确（通信协议 388→77）。
- **策略已定：装配优先**（契合"OBIS 码错一位是严重缺陷 / 数字双引擎"防幻觉纪律）。与 M4c OCR 正交。

## 下一步行动（2026-07-04 更新）

1. **专家实战反馈迭代**——用户/团队用新 exe 跑真实文档，review_insights 的建议累积后回改 map_labels/classify_ownership 规则；批注视图一致性标记的实用性验证。
2. **Green Book 引入**（行为/协议层第二本书）——散文语料无 class_id 键，需与蓝皮书不同的检索策略（术语倒排 or 受约束语义），先做小样探针再立项。
3. **GUI 富化结果展示**（可选）——analyze 的 software_requirement_text / 研发指引目前只在导出 xlsx，可加应用内视图。
4. **M4c 扫描件 OCR**——等英文扫描件语料攒够再立项（选型见下「关键产品决策」）。

## 关键产品决策（已拍板，勿重新讨论）

- 输入格式：Word(.docx)/Excel(.xlsx)/PDF；扫描件 PDF 占比大，OCR（M4c）必做
- 语言：**90% 英文，只做英文**；小语种全部挂起（将来倾向"先翻译后处理+原文对照"）
- LLM：统一 OpenAI 兼容客户端（`llm_client.py`），本地 Ollama / 云端 GLM 经 `llm_agents/review_pipeline.yaml` 切换；密钥只走环境变量；审查范围默认 targeted
- M4c OCR 选型方向：Tesseract（仅 eng 包）+ 框线表格 CV 切格逐格 OCR；ML 表格模型仅兜底；VLM 只做辅助纠错且数字/编码需双引擎一致（防幻觉，OBIS 码错一位是严重缺陷）；OCR 置信度直通 confidence/ambiguity → targeted 审查 → 专家队列
- 专家评审语义：`apply_expert_decision` 是裁决覆盖（除 frozen 外任意状态可改），自动管线走严格状态机

## 用户待办

- 攒英文扫描件 PDF 测试语料（5-10 份，不同扫描质量/表格密度/脏样本），M4c 立项用
- 第一份真实客户 Excel 到手后走 A1 差距报告流程（GPT 出报告 → Claude 技术筛查 → 用户拍板 → 再修）
