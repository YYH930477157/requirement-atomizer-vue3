# 修复任务清单（2026-08-04，实机实测发现）

> 来源：2026-08-03/04 对 `e2524c8`（result package + review-2026-08-03 修复合并后）的实机使用验证。
> 全部问题均有实测证据（真实 SBD PDF 文档 899 块/126 节/546 atom，deepseek-v4-flash）。
> 验证环境：Windows 10、Python 3.14、Vue3+Electron 打包版（`ui/dist/标准需求抽取与审查平台 0.1.0.exe`）。
> 基线：后端全量 2570 tests OK（0 skip）、前端 vitest 199/199。
> 优先级：**B1 必须最先修**（每个首次运行用户必踩），B2 用户已拍板方向，P3/P4 为成本与体验优化。

---

## B1（阻断）首次运行后批注/需求视图全部空数据——API 路径锁存 + Electron 会话复用

### 现象

新建空目录首次运行分析，完成后「文档批注」「审查工作台」全部无数据，无报错提示。

### 实测证据

- 运行中的 API 服务（PID 6968，启动于运行**前** 22:53:58）自报 `analysis_root: C:\...\result`（应为 `C:\...\result\.ratomizer\pipeline`）；`GET /requirements` 返回 `[]`；`GET /document/pdf` 返回 `available:false, "非 PDF 输入或缺少源文档"`。
- 同一目录用正确 analysis_root 本地重放 `build_pdf_annotation_payload()`：99 页 / 444 需求标记 / 634 块热区 / 2301 claim 记录——数据完好。

### 根因（两层缺陷叠加）

1. **后端一次性锁存**：`api_server.py:2305-2306` 启动时 `output_dir = resolve_analysis_root(package_root)` 只解析一次。API 服务先于管线启动时（`.ratomizer/pipeline` 尚不存在），解析退回包根并**终身锁存**，布局出现后不重解析。
2. **Electron 复用过期会话**：`ui/electron/main.helpers.cjs:232` `shouldReuseApiSession` 只比对 `session.outputDir === outputDir` + 进程存活；`main.cjs:341-346` `startApiServerExclusive` 命中复用即直接返回。管线完成后的重连（`main.cjs:233`、`App.vue refreshAfterDesktopTask:2112`）与「打开已有结果」（`main.cjs:152`）全部走同一复用路径——**用户连「重新打开目录」都修不好**，只能换目录或杀进程。

### 修法（两层都修）

1. **后端（治本）**：analysis root 改为按请求惰性解析（`resolve_analysis_root` 只是 `.ratomizer/pipeline` 存在性检查，开销可忽略），或至少在解析结果与当前布局不一致时重解析。消除整族「启动时快照过期」问题（与已修的 B1 claim 闸同族）。
2. **Electron（治标/双保险）**：管线运行完成、写命令完成后的重连**强制重启 API 服务**（候选进程模式已有，跳过 `shouldReuseApiSession` 即可）；或复用前经 `/result-package` 校验服务端 `analysis_root` 与预期一致，不一致则重启。

### 验收标准

- 端到端复现脚本/测试：新空目录 → 启动 API 服务 → 跑管线（可 stub）→ 完成后 `GET /requirements` 非空、`GET /document/pdf` `available` 如实——修复前必现空，修复后有数据。
- 「打开已有结果」重新选择同一目录后视图有数据（当前复用路径下修复前也必现空）。
- 既有 `tests.test_api_server` / electron helpers 测试全绿；前端 vitest 全绿。

---

## B2（重要，用户已拍板）partial 运行根目录零交付物

### 现象

ai-extract 部分章节失败（本例 deepseek 端点超时/503，3/126 节）→ `commit_analysis_completion` 按设计拒绝 → **根目录一个结果文件都没有**。交付物实际全部在 `.ratomizer/pipeline/`，但用户视角是"跑了一个半小时啥也没产出"。

### 背景

PR1/I3 修复将发布推迟到完成提交（防"失败运行的产物冒充成果"），但首次运行 + partial 的组合下根目录恒空。fail-closed 方向正确，**但把"部分成功"与"什么都没有"混为一谈**。

### 用户拍板（2026-08-04）

**partial 也发布交付物，marker 如实标 `incomplete`/`partial` 状态**——交付物可见可用，状态不造假。当日已用公开 API 手动验证该形态可行：`record_analysis_failure`（关闭 attempt、原因入档）+ `publish_registered_deliverables` → 根目录 7 个交付物、marker `analysis_status=incomplete`、`load_result_package(verify=True)` 通过。

### 修法

1. `desktop_tasks`/结果包提交路径：requested stages 存在 partial（非 failed）时，不再整体拒绝发布——发布已产出交付物，`analysis_status="incomplete"`（或新增 `"partial"` 枚举，schema 同步），`last_attempt` 如实记 partial 原因。
2. UI 状态芯片/最近会话分类已具备「分析未完成」展示，接线即可。
3. 真正 failed（非 partial）的阶段维持现状不发布。

### 验收标准

- partial 运行（构造 1 节抽取失败的夹具）后：根目录交付物存在且与 pipeline 逐字节一致、marker `analysis_status=incomplete`、`verify=True` 通过、`/result-package` 与最近会话显示「分析未完成」而非「运行失败/已完成」。
- 全部 ok 的运行仍走 `completed` 原路径，行为不变（既有测试全绿）。

---

## P3（成本+体验）功能重组截断重试旋涡

### 现象

功能重组阶段对「未分类」模块（86 条 PROW-DET 参数表行，标题如 "6D"）调 LLM 分组，推理模型 reasoning 吃光输出预算：`8000→16000→32000` 三次升级全部 `finish=length`，每次 ~90-100s 付费调用，结局必然失败回退确定性分组。该阶段全程 28 分钟（25 个模块），其中约 6 分钟是纯浪费。

### 根因

1. `functional_catalog.py:609-655` `_llm_groups` **整模块一次调用**，大模块 + cryptic 表行是推理模型的硬输入；
2. `llm_client.py:926-941` 截断升级策略假设"预算配小了"，对**输入驱动**的截断（reasoning 耗尽）无效，升级 3 次全被思维链吃掉。

### 修法（按杠杆排序，可全做）

1. **分组批大小上限**：>30 条的模块先按 `functional_key` 确定性预切再分批送 LLM，单次输出有界，旋涡结构性消除。
2. **PROW-DET/参数表行确定性分组**：参数表行展开条目本身是确定性产物，按来源表块分组即可，不进 LLM（本例直接省掉 86 条的整个旋涡）。
3. **截断旋涡闸**：同一输入升级后仍截断（尤其空 content 的 reasoning 耗尽形态）→ 不再升级，直接回退，省 2-3 次注定失败的调用。

### 验收标准

- 合成 ≥80 条 cryptic 表行模块：分组 LLM 调用 ≤⌈N/30⌉ 次、零截断升级重试、PROW-DET 行零 LLM 调用。
- 既有 functional-synthesis 测试与 agent_eval grouping 基线（8/8）不回归；版本面（`FUNCTIONAL_SYNTHESIS_VERSION` 等）按纪律 bump。

---

## P4（成本优化，可选）llm-review token 占总量 65%

### 实测账（SBD 单次全链）

1834 次 LLM 调用、prompt ~594 万字符（≈250-280 万 tokens）：

- **llm-review 1134 次 / 389 万字符（65%）**：546 条需求平均每条 2.08 次调用（工具循环）；**审查 prompt 的 49% 是工具结果**（191 万字符）；`kb_search` 平均每条需求 2.1 次（有冗余，首轮 prompt 已带预匹配 KB 但只有 ~86 字符太弱）。
- ai-extract 252 次 + ai-verify 253 次（29%）。
- 功能重组 29 次（<1%）。

### 修法选项（按杠杆排序）

1. **批量审查**：一次调用审 N 条（analyze 富化合批 `RATOMIZER_ANALYZE_BATCH=4` 先例）。×4 合批约省总量一半。难点：与工具循环冲突、逐条护栏不能放宽（enrich_slot 宁缺勿错先例）。
2. **工具循环瘦身**：首轮 prompt 预注入 KB top-3 连定义（各 ≤300 字符）+ 每条需求 `kb_search` 限 1 次；`source_read` 上限 2000→800；`max_rounds` 8→5。
3. **确定性表结构 atom 免审**（产品决策，需用户拍板）：OBIS/访问矩阵等表来源 atom 已被确定性护栏验证，`table_row` 移出 `always_review_source_types`。
4. **立即可用不改代码**：`RATOMIZER_AI_VERIFY_ROUNDS=1`；`review_scope.confidence_below` 0.75→0.5。

### 验收标准

- 同一真实文档重跑：总 token 降幅达标（目标 ≥40%），审查覆盖率/裁决一致性回归通过（golden 6/6、agent_eval 四类基线不变）。
- 行为面版本（`REVIEW_TOOLS_VERSION`/`PROMPT_VERSION`/cache 版本）按纪律 bump 并显式声明缓存影响。

---

## 次要项（顺手修，不单独立项）

1. **孤儿 API 进程**：实测 3 个 STO 旧会话 API 进程残留监听（`stopApiServer` 在应用退出/多实例场景未回收）。建议应用退出时统一 kill 已 spawn 的 API 子进程。
2. **S4 嵌套校验不齐**：`result_package.py:_validate_package` 只校验顶层，`last_attempt` 内容、`tool`/deliverable 的 `additionalProperties:false`、evidence `minItems:1` 未镜像 schema——外来 marker 可"过代码不过 schema"。补齐或将注释降级为"顶层对齐"。
3. **休眠 split-brain**：`omission_actions.py:656` `extraction_in_progress` 裸读 `root/"run_manifest.json"`（package_v1 下永读不到），当前无生产调用方——接线前先修或删除。
4. **错误面缺口**：`/result-package` 之外的 GET（如 `/review-states`）未包 `ResultPackageError`，marker 损坏时裸异常掐连接而非结构化 503。

## 修复纪律提醒（仓库红线）

- 实现必须在隔离 git worktree（`codex/*` 分支），审查通过前不合 main。
- 行为面变更（版本常量/策略指纹）必须 bump 并在 commit message 显式声明缓存/golden 影响。
- commit message 三段式：原因 / 现象（附 file:line）/ 修复机制。
- 推送前全量绿：`python -m unittest discover -s tests` + `cd ui && npm test`。
- 不改 `golden_sets/`、冻结 `out/` 基线、LLM prompt（prompt 变更需单独声明）。
