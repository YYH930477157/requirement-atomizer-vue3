# 评审问题修复对照表（2026-08-14，待审核）

> 来源：2026-08-14 全库代码评审（四个并行审查代理 + 人工汇总报告）。
> 实施方式：11 个并行工作流（文件域互不重叠）+ 主会话集成收尾。
> **第二轮**：用户审查反馈的 11 项缺陷（6×P1、4×P2、1×P3）已全部修复，见文末「第二轮：审查反馈修复对照」。
> 状态：全部改动在工作区**未提交**（分支 `codex/table-translation-structure`），等用户审核。
> 最终验证（含两轮）：后端全量 **3641 tests OK（0 失败 0 跳过）**，冒烟 90 modules / **1746 cases**，前端 **Vitest 273/273** + `vue-tsc` + `vite build` 全部通过。
> 总量：64 文件，+7187/−975 行。

## 阅读指引

- 每条问题给出：**评审发现 → 实施的修复 → 证据（测试/实测/文件位置）**。
- 「设计取舍」小节列出实施中的判断点，是需要用户重点过目的部分。
- 「合并义务」列出合入 main 前后必须执行的仓库纪律动作。

---

## 状态总览

| # | 问题（评审编号） | 状态 | 关键证据 |
|---|---|---|---|
| 一.1 | 阶段指纹同批文件哈希 5-6 遍 | ✅ | 哈希计数断言测试（12→预期 1 遍/文件） |
| 一.2 | /table-reviews、/document/pdf 每请求全量重哈希 | ✅ | 快照缓存命中测试（2 次 GET → 1 次盘读） |
| 一.3 | /document/pdf 同一 PDF 每请求哈希 2 次 + docx 源哈希 | ✅ | `_file_sha256` 备忘 + 实测每运行恰 1 次哈希 |
| 一.4 | GET /requirements 先富化全量再切页 | ✅ | enrich 调用计数测试（只富化页内行） |
| 一.5 | /ai-extraction-status 无备忘但被 180ms 轮询 | ✅ | 备忘命中/失效测试 |
| 二.1 | attempt 日志/verifier WAL 追加即全量重写 | ✅ | 300 次事件 366.8s→0.99s（~370x） |
| 二.2 | analyze_enrich_cache 每任务整文件重写 | ✅ | JSONL 追加 + O(1)/任务断言 |
| 二.3 | 翻译 sidecar 每批读-合-写全量 | ✅ | 3 批 → 3 追加 + 1 次压缩；崩溃重放零丢失 |
| 二.4 | extract_all 每节重写快照+全行重跑 framing | ✅ | 10 节 11→3 次快照；终态字节等价测试 |
| 三.1 | prompt JSON indent=2 多付 15-25% token | ✅ | 四处紧凑化 + 版本 bump |
| 三.2 | coverage_check 每次调用重算全文档分析 | ✅ | 3.57ms→0.052ms（~68x），字节等价测试 |
| 三.3 | 证据指纹全有全无，改一行作废全文档审查缓存 | ✅ | 按行作用域化 + 命中/失效 E2E 测试 |
| 三.4 | 同一工具两连错丢弃全部已付费轮次 | ✅ | 禁用降级测试；硬错误仍大声失败 |
| 三.5 | 缺槽回退在 worker 内串行 | ✅ | 编排器重提交（复用 work_single） |
| 四.1 | 任意纵向合并整表降级非结构化 | ✅ | SBD 8 张表恢复逐行 + rowspan（v3） |
| 四.2 | 多标题行只留第一行（内容损失） | ✅ | 逐行单元 + atomize `title_rows` 载荷 E2E |
| 四.3 | 两个版本常量未钉入 atomize producer | ✅ | producer 随常量变化测试 |
| 四.4 | 一个良性 row_width_conflict 整表进人工审查 | ✅ | 已调和降审计注记；真冲突仍阻断 |
| 四.5 | 空行/纯数字行仍成为 LLM 翻译单元 | ✅ | skipped/nothing_translatable 不进 LLM |
| 五.a | 启动维护同步阻塞，Electron 30s 杀进程 3 连重做 | ✅ | readiness 先行 + 恰好一次测试 |
| 五.b | 每次专家点击同步 fold_effective_ledger | ✅ | K 并发点击 → 1-2 次 fold（协调器） |
| 五.c | UI 从不调 /claim-maintenance，恢复类 503 卡死 | ✅ | 自动 POST+重放（7 个 vitest） |
| 五.d | 最热写路径 os.replace 重试仅 80ms 窗口 | ✅ | 三模块统一 8 次线性退避（~0.56s） |
| 五.e | 解析层小项（PDF 双提取/docx 双 Paragraph/set 重建/词表重读） | ✅ | 输出字节等价证明 + 实测提速 |

评审细化发现（超出首版报告、随实施一并修复）的条目见第六节。

---

## 一、热路径重复计算

### 一.1 阶段指纹多遍哈希（desktop_tasks.py）

**发现**：一次阶段求值中 `stage_input_fingerprint`、`_stage_is_reusable`、租约装饰器（前后各一次）、`update_run_manifest` 各自全量 SHA-256 同一批文件（5-6 遍）；`blocks.jsonl` 是 6 个阶段的输入，一次链式运行整个读十几次。

**修复**：`_STAGE_INPUT_SHA_CACHE`（解析路径键 → ((size, mtime_ns), sha256)，RLock 保护）+ `_file_sha256_cached`（stat 快路径、失配全量回退、文件消失逐出）；两个指纹函数共用一次哈希映射；`_stage_is_reusable` 重构为 `_stage_reuse_check` 返回 `(reusable, record_fingerprint)`，producer 只算一次并穿入；跳过路径把已算指纹传给 `update_run_manifest(input_fingerprint=)`（stub-over-openai 分支按记录路由重算保持 manifest 自洽）。

**证据**：`tests/test_desktop_tasks.py::FingerprintReuseAndLockHardeningTests` 11 个测试（TDD 红先行：哈希计数 12≠0/6≠1、producer 计数 2≠1 等先失败后转绿）；指纹值字节不变由既有测试锁定。

### 一.2 /table-reviews、/document/pdf 每请求全量重哈希

**发现**：两 GET 链路经 `table_review_state` → `table_claim_authority` → `claim_artifacts` 无缓存地对全部 claim 工件做完整 SHA-256，且 `table_cell_items`/catalog/`ai_requirements.jsonl` 在**同一次加载里各哈希两遍**。

**修复**：`claim_artifacts.effective_snapshot_revision_key(root)`（25 个输入文件的 stat 签名 + 两个提交锚 meta 的内容摘要 + journal/checkpoint 存在性）+ `load_committed_effective_snapshot_cached`（线程安全、LRU 16、per-root single-flight）；基座加载内目录摘要传递复用（每文件恰哈希一次）。接线点：`claim_views._context`、`table_claim_authority.load_table_claim_authority_projection`、`doc_annotation_export._claim_annotation_state`。

**证据**：连续两次加载返回同一对象、触碰任一输入即失效的测试；基座加载哈希恰一次的计数测试；60 次链式发布 2.22s、50 次 `load_committed_claim_base` 0.36s 实测。

### 一.3 /document/pdf 重复哈希大文件

**发现**：`build_pdf_annotation_payload` 内 `_file_sha256(仿样PDF)` 与 `_resolve_pdf_geometry` 各一次（同一 PDF 每请求 2 遍），`doc_facsimile._cached_facsimile` 再对源 docx/xlsx 全量哈希一次。

**修复**：`doc_annotation_export._FILE_SHA256_MEMO`（(normcase 路径, size, mtime_ns) 键，128 项上限，读后 stat 复核防竞态）；`doc_facsimile.convert_to_pdf` 算一次摘要穿入 `_cached_facsimile` 与 `_write_facsimile_meta`。

**证据**：转换/缓存命中/不可用三条路径每运行恰 1 次哈希的调用计数测试（tests/test_doc_facsimile.py）。

### 一.4 GET /requirements 先富化后切页

**发现**：`enrich_requirements(rows, ...)[:limit]` 对全语料逐行做 CAS/投影（O(rows×states) 哈希 + 跨进程锁）后丢弃。

**修复**：先按类型过滤全量、`rows[:limit]` 切页再富化。响应契约为纯列表（无 total、无 offset 参数，UI 只消费数组），无需重算总数。

**证据**：patched enrich 计数器证明只调页内行数（tests/test_api_server.py::RequirementsEndpointTests）。

### 一.5 /ai-extraction-status 无备忘

**发现**：该端点被 UI 在抽取期间每 180ms 轮询，每次重算 4 文件全量 SHA 指纹 + 全行锚点匹配 + 跨进程锁快照。

**修复**：`build_ai_extraction_status` 包 `_memoized`（与 build_ai_requirements 同机制），备忘源含 partial 文件、指纹 4 输入与富化输入（每次 partial 写入改变 stat 签名 → 进度仍然实时）；构造器异常不缓存。

**证据**：备忘命中/私有拷贝/签名失效/异常不缓存 4 个测试（tests/test_api_server.py::AiExtractionStatusMemoTests）。

---

## 二、O(N²) 追加写模式

### 二.1 claim attempt 日志与 verifier WAL

**发现**：`_append_unlocked` 每事件=全量扫描（逐行 jsonschema+哈希链验证）→ 整文件重写 → 再全量扫描；代码注释自带基准 N=300 时 **366.8s**；一次队列执行追加 7+ 事件。verifier WAL 与 `_attempt_binding`/`_attempt_cost_chain` 同模式。

**修复**：真追加（`open("ab")`+flush+fsync/事件），链头状态按文件 stat 签名备忘（行、幂等键、增量 sha256 哈希器）；每追加只校验本批触及的 attempt 历史（装载时已全量验证）；撕裂尾由写侧恢复（启动维护/队列执行的压缩入口 `compact_attempt_log` / `compact_claim_verifier_attempts`，原子路径重物化）。纯 GET 读路径保持 fail-closed 不变。压缩阈值 env（默认 2000 行/8MiB）已登记 `config.ENV_REGISTRY`。

**证据**：300 次顺序追加 **0.99s**（vs 366.8s）；1000 次备忘读 0.22s；撕裂尾/伪造行/崩溃矩阵测试更新后全绿（tests/test_claim_reextract_attempts.py 等 6 个测试文件，合计约 500 用例）。

**版本**：`CLAIM_REEXTRACT_ATTEMPT_VERSION` 不变（v3）——盘上行格式与读者语义逐字节不变，只改写入 I/O 策略与崩溃恢复。

### 二.2 analyze_enrich_cache 整文件重写

**发现**：`_save_enrich_cache` 在 as_completed 消费者里每完成一个任务就 `json.dumps(整个缓存, indent=2)` 全量重写。

**修复**：改 `analyze_enrich_cache.jsonl`（meta 行 + 每项一行），每完成任务追加一行 fsync；装载读双格式（JSONL 同键后写胜出；撕裂尾修复、中段损坏整弃宁可重富化）；新 `ENRICH_CACHE_FORMAT_VERSION="analyze-enrich-cache-v2"` 进 `_enrich_key`。

**证据**：tests/test_analyze_enrich_perf.py 17 个测试（含 O(1)/任务断言与双格式装载）。

### 二.3 翻译 sidecar 每批读-合-写

**发现**：`_write_translation_sidecar` 每批完成在锁内重读-解析-合并-全量重序列化（indent=2）-fsync-os.replace；并发池完成被锁串行化，累积写成本平方级。

**修复**：新增 `annotation_translations.journal.jsonl`（governed cache 类别）：每完成键一行 fsync（锁内），O(批) 而非 O(全部项)；装载在 JSON 之上重放日志（撕裂行/版本不配行跳过=崩溃恢复；合并序与旧重写一致）。压缩时机：运行结束、日志超 256KiB、无 pending 早退分支。**主 JSON 格式字节不变**（`_TRANSLATION_SIDECAR_VERSION=2` 不变），api_server 现有读取器零改动。

**证据**：端到端冒烟：3 批 → 3 追加 + 恰 1 次原子压缩，日志删除，旧读取器从 JSON 读全 23 条译文；崩溃中断重放零丢失（0 新增 LLM 调用）；tests/test_doc_annotation_export.py +6。

### 二.4 extract_all partial 快照 O(S²)

**发现**：每节完成后 `publish()` 重建可见列表 → 对**所有**已完成行重跑 `enforce_normative_framing` 正则 → 整快照原子序列化+fsync（都在 futures 消费线程里）。

**修复**：framing 改为插入时每节一次（付费缓存仍存未框架行——保持缓存键不含框架的不变量）；快照写节流（8 次完成或 5s + 循环后无条件 publish；complete=True 终态写不变）。

**证据**：插入时框架化 vs 收集后框架化字节等价测试；重跑已框架行是不动点测试；10 节运行快照次数 [0,8,10]（原 11）；tests/test_ai_extract.py +7。

---

## 三、LLM token 成本

### 三.1 prompt JSON 紧凑化

**发现**：`llm_pipeline.build_user_prompt`/`build_batch_review_prompt`、`ai_extract.build_section_prompt`、`spec_enrich._build_batch_user_prompt` 用 `indent=2`，每键值独占一行，约多付 15-25% token（每轮工具循环、每次重试、每个缓存键都在付）。

**修复**：四处改 `separators=(",", ":")`，零措辞/键序变化（往返测试）。版本：`ai-extract-v24→v25`（prompt_registry 同步）、`enrich-v3→v4`、llm 两处入 `llm-review-cache-v7`。

### 三.2 coverage_check 每调用重算全文档

**发现**：每次工具调用对全部需求跑 OBIS 共指、跨节去重、quote-块匹配（全块正则规范化 + O(块×窗口)），`_source_read`/`_find_requirement` O(N) 线性扫——都在 8 路并发审查循环的延迟关键路径上。

**修复**：执行器 state 惰性构建一次：block_id 索引、需求候选索引、`_ConsistencyIndex`（适配行+共指/重复组）、`_BlockQuoteIndex`（有序紧凑规范化语料 + 每引用备忘匹配，复用 `merged_consistency` 的匹配函数原语）。惰性锁升 RLock。

**证据**：备忘执行器 vs 旧算法参考实现在多样合成语料上**字节等价**（含乱序块/重复 id/噪声块/多摘录/结构化 OBIS/短引用/未知 id）；`find_obis_coreference`/`find_cross_section_duplicates` 每执行器恰 1 次的计数测试；300 需求/450 块语料单调用 3.57ms→0.052ms（**~68x**）。`REVIEW_TOOLS_VERSION v4→v5`。

### 三.3 证据指纹全有全无

**发现**：全局 `evidence_fingerprint`（哈希 KB+blocks+atomic_requirements+蓝皮书）进入**每条**需求的缓存键——编辑一条需求作废全文档审查缓存（占 LLM 成本 65% 的阶段）。

**修复**（可靠实现）：键拆为稳定证据部分（KB+blocks+蓝皮书，审查编辑期间不变）+ 自身行 sha256；缓存行持久化 `evidence_deps{coverage_check_used, atomic_requirements_sha256}`——**调用过 coverage_check 的行仍按全文件哈希校验**（其返回全文档聚合，作用域化会供旧结论，可靠性优先）；批键同时补行哈希（顺带关掉 review_questions 陈旧命中洞）。桌面 llm-review 阶段戳仍用全文档指纹（阶段复用语义不变），只有按需求缓存被作用域化。

**证据**：E2E 测试——改 B 行保持 A 行非 coverage 命中；A 的 coverage 行被 B 编辑失效；自身行编辑只失效该行。`LLM_REVIEW_CACHE_VERSION v6→v7`。

### 三.4 工具循环两连错中断

**发现**：同一工具连续两次出错（如 block_id 打错两次）→ `LLMResponseError` → 整条需求变 needs_expert stub，**已付费轮次全部丢弃**。

**修复**：第二次连续同名工具错误时从剩余轮次的 tools 列表移除该工具（拷贝，不污染调用方 TOOLS）并回喂"该工具不可用，请直接产出最终 JSON"；再调用不执行；全部工具被禁后请求省略 tools 键。轮数上限/token 预算不变；不收敛仍走既有 stub 路径；4xx 工具不支持/500/连接错误仍大声失败（来源红线）。

**证据**：轮内禁用/跨轮禁用/禁用后不执行/streak 重置/禁用后轮上限仍 raise/中途供应商错误仍 raise + 管线级 E2E（双错 block_id → 先前轮次保留、审查以 `llm:…` 完成）。

### 三.5 缺槽回退串行

**发现**：批响应缺槽时，每个缺槽项在**同一 worker 任务内**逐条串行单发（timeout 已放大到 60×批），一个降级批串行霸占池线程。

**修复**：`_llm_enrich_batch`/`_llm_enrich_hardware_batch`/`spec_enrich._enrich_batch_unit` 返回缺槽索引，编排器 `wait(FIRST_COMPLETED)` 循环把它们作为独立单发任务重提交到同池（复用既有 `work_single`）；单发失败接入连接失败断路器（优于旧的静默吞掉）。护栏/拒收行为逐条不变。

**证据**：tests/test_analyze_enrich_perf.py、tests/test_spec_enrich.py 新增并发编排测试。

---

## 四、效果：内容损失与过度/不足路径

### 四.1 纵向合并整表降级（最大表最可能翻不出）

**发现**：`_regular_table_plan` 遇任何 `min_row != max_row` 合并或嵌套表就返回 None → 整表拍平文本成单个巨型翻译单元，超 8000 字符批上限"宁超勿截"单独打包，护栏失败再级联逐句重试；逐行双语表格 UI 恰好对最大的表丢失。

**修复**：降级只留给嵌套表与真冲突几何（`merge_ranges_overlap`）。纵向合并走结构化路径：`_physical_matrix` 从块载荷重建物理行网格，数据/表头单元经 `inherit_merged_text` **只喂纵向 range**的有效矩阵渲染（续行携带锚文本；横向合并保持 covered 空、colspan 语义不变）；`_render_source_cells` 泛化 rowspan+colspan（续行省略 covered 格）。放置证据不完整时回退块列表渲染，不伪造。

**证据**：真实 SBD 验收：8 张纵向合并表（原全部 complex_table，如 BLK-000215 16 列×13 行）全部产出结构化逐行单元 + 正确 `rowspan="4"` HTML；既有 colspan 测试字节不变。`FULL_TRANSLATION_VERSION v2→v3`、`document-translation/v3`（schema 同步）。

### 四.2 多标题行只留第一行（已验证内容损失路径）

**发现**：唯一题注单元来自提升后的 `table_title`（= `title_row_indexes[0]`），而 `physical_data_row_indexes` 扣除**全部**标题行——堆叠标题+副标题形态下副标题不进任何单元（账本/HTML/LLM 输入全无）。

**修复**：full_translation 按 `title_row_indexes` 每行发一个 `role:"title"` 单元（`unit_id :title-row:N`，题注单元保留）；**主会话补 atomize 生产端**——`build_table_artifacts` 新写 `title_rows` 载荷（与索引逐行对齐），端到端打通。

**证据**：消费端（合成块）+ 生产端（build_table_artifacts → `_regular_table_plan`）E2E 测试：`title_row_indexes=[1,2]` → `:title`、`:title-row:1`、`:title-row:2` 三单元，副标题文本进账本进 HTML。

### 四.3 版本常量未钉入 atomize producer（静默缓存洞）

**发现**：`DOCX_TABLE_PHYSICAL_VERSION` 与 `TABLE_DISPOSITION_RULE_VERSION` 实质影响 atomize 输出（分别戳进 cells/blocks 与 dispositions 每行），但不在 producer 字符串里——bump 它们修 bug 后旧 manifest 仍匹配、链静默复用过期产物。这正是版本戳机制要防的失效模式。

**修复**：两常量以**符号导入**追加进 `stage_producer("atomize")`（不硬编码字面量，并发 bump 自动跟随）。

**证据**：monkeypatch 常量 → producer 串变化 → 阶段不复用的测试。

### 四.4 一个良性 row_width_conflict 整表进审查

**发现**：解析器已确定性调和宽度冲突（width=max(声明,观测)、矩阵补齐、**内容无损**），但 `parse_incomplete=bool(issues)` 仍让 `_base_disposition` 把全表每个 cell 打成 review——手工 DOCX 常见，审查面按表面积而非真实歧义增长。

**修复**：调和后运行时显式验证无损条件（每个观测 cell 列与每个合并 range 列都在 [1,width] 内）——满足才把 `row_width_conflict` 标 `reconciled: True` 并排除出 blocking_issues；merge_conflict/merge_text_conflict 永不豁免。所有 issue（含 reconciled 标记）保留为审计注记。未来代码回归时该校验自动退回阻断（宁漏勿错入码）。

**证据**：宽度冲突调和 → parse_incomplete False、issue 带 reconciled 标记、无 `parse_incomplete:*` 证据进处置；merge_conflict 表全表 review 漏斗不变。`DOCX_TABLE_PHYSICAL_VERSION v1→v2`、`TABLE_DISPOSITION_RULE_VERSION v2→v3`。

### 四.5 空行/纯数字行进 LLM

**发现**：数据行循环没有表头循环的空行守卫（全空行渲染 `"|  |"` 也发 LLM）；纯数字/标记行耗批槽与缓存项，污染覆盖计数。

**修复**：全空数据行不产单元；`_looks_translatable` 逐单元应用，不过者标 `skipped`/`nothing_translatable`（列在 `feature_disabled` 之后、与 `empty_text` 同构），排除出 `texts`（零 LLM 调用）与 `eligible` 聚合。**主会话补充**：`_looks_translatable` 从"拉丁字母≥3 且 ≥CJK"放宽为"任意非 CJK 字母≥3"（目标语是中文；俄文 STO 等西里尔内容不再整表跳过；纯数字/符号/已是中文仍不进管线）。

**证据**：全空行零单元零调用、纯数字行 nothing_translatable 且不计入 eligible、西里尔断言（Напряжение… True；"1 2 3 | X | 0.5" False；纯中文 False）测试。

---

## 五、交互延迟与健壮性

### 五.a 启动维护同步阻塞

**发现**：`main()` 在创建 HTTP 服务**前**跑完 claim 恢复 + 表重算恢复（含全量哈希扫、可能整账本 fold）；Electron 30s 超时杀进程重试 3 次，慢恢复被三倍放大。

**修复**：先创建/绑定 `ThreadingHTTPServer` 并打印 readiness JSON，维护放守护后台线程；模块级 `Event`+派发锁保证每进程**恰好一次**；任一步异常记日志、进程照常服务；维护期间 GET 照旧 fail-closed（结构化 503）。

**证据**：readiness 先于维护打印、两次 main() 恰一次、维护失败仍 exit 0 三组测试；`_reset_startup_maintenance_for_tests` 供测试复位。

### 五.b 每次点击同步 fold

**发现**：A/B 两轨决策钩子在请求内同步跑 `fold_effective_ledger`（claim_publication_lock + 全量基座加载 + 有效账本/队列重发布），每次点击都卡。

**修复**：`_EffectiveFoldCoordinator` 猝发合并：权威写入（决策先持久化，后注册单调 pass 号）后，本轨决策要么成为 fold 属主（在自己的请求线程同步跑）、要么等 Condition；属主排空同轨窗口内落地的决策（上限 3/任期）后让位。不变量：`cover()` 返回时必有编号 ≥ 注册号的同轨 pass 完成 ⇒ 该次决策必被折算。K 并发点击 → 1-2 次 fold；崩溃恢复语义不变（无请求外延迟，fold 滞后健康度照旧由下次决策/队列执行/启动维护兜底）。

**证据**：covering-pass 序号证明、属主崩溃恢复、6 线程合并 ≤ 上限且 6 行全部持久、既有 5 个 fold 钩子契约测试与读后写可见性测试（5/5 重复）不变。

### 五.c UI 从不触发 claim 恢复

**发现**：遗留 outbox 使 claim GET 全部 503 `effective_recovery_pending`，恢复只在 API 重启或下次队列执行时发生；`ui/src` 零处调用 `/claim-maintenance`——用户视角永久卡死。

**修复**：`ui/src/api-client.ts`——GET 收到可重试结构化错误且 code 为 `effective_recovery_pending`/`claim_artifact_recovery_required` 时，POST `/claim-maintenance` **恰一次**（in-flight promise 并发去重、失败吞掉——重放的 GET 才是权威），随后重放原请求一次；仍失败按原样上浮。POST 永不自动恢复。

**证据**：7 个 vitest（调用序与请求体、嵌套 `{error:{code}}` 信封、并发共享一次 POST、仍失败上浮不二触发、普通可重试/不可重试码不触发、POST 不触发）。

### 五.d os.replace 重试预算不一致

**发现**：最热的 `review_states.jsonl` 保存路径只有 5×0.02s（共 80ms 窗口），而 claim_artifacts/ai_review_actions 是 8 次线性 ≈0.56s——Windows AV/索引器常持锁超 80ms，用户刚点的保存报 PermissionError。

**修复**：`review_state.py` 与 `desktop_tasks.py` 统一 8 次线性退避（0.02×(1..7)），与 claim_artifacts 逐字对齐；不建共享助手（匹配仓库扁平模块风格）。

**证据**：两模块各自的退避预算测试。

### 五.e 解析层小项（输出字节等价已证）

| 项 | 修复 | 证据 |
|---|---|---|
| PDF 每页词提取 2 遍 | 检测遍存词表、主循环 pop 复用（同 subscript/twocol 标志） | EN 16314（60 页）`extract_words` 120→60 次 |
| 词表指纹每调用重读归档 | `@lru_cache(1)`（同 `_repair_word_ranks` 先例） | 值不变 |
| xlsx 全表 3 遍 + 矩形逐格枚举 | 单遍 non_empty 结构复用 + `_RowColumnIntervals` 区间覆盖计数（bisect） | 5 万行 ListObject 桩区域检测 0.28→0.10s（~3x）；真实 ABNT 工作簿 2.71→2.35s |
| doc_facsimile 输入哈希 2 次 | `convert_to_pdf` 算一次穿入两处 | 调用计数测试 |
| spot_extract 读 blocks 2 次 | 锁内一次装载穿入两路径；新读路径走 `governed_artifact_path(for_write=False)` | 既有 19 测试 + 地址纪律测试绿 |
| table_structure set 每元素重建 / `_row_identity_entries` 每 cell 重算 / plan 与 cell_items 几何重复 | 集合提升、`_nearest_group_header_texts`/`_merge_anchor_map` 预计算、`table_geometry_context` 共享（可选参数，向后兼容） | 420×12 合并表 plan+cells 63.4→48.9ms；输出与改动前字节一致（钉测基线） |
| atomize `is_noise`/`detect_heading` 每 call 建 set | `DocumentProfile` 缓存 frozenset（cached_property 不动 frozen 语义） | 400 词表 191→102ms（~1.9x） |

字节等价证明方法：同进程内反向应用改动块重建改动前模块，对 2 个真实 PDF + 3 个工作簿（含 ListObject+合并+残留合成桩）前后输出 SHA-256 相等。

---

## 六、评审细化发现（超出首版报告，随实施一并修复）

这些是实施代理深入代码后确认的相邻问题，均在对应工作流内一并解决：

1. **字母复合表头 (a)..(j) 上限**：`table_structure` 与 `full_translation` 两处镜像正则同步扩到 `(a)..(z)`（仍须 a 起头、连续；b 起头的分表序列按设计不识别）。`TABLE_STRUCTURE_VERSION v8→v9`（claim_catalog_meta schema 枚举同步）。
2. **result-package marker 每请求重验**：`detect_result_layout`/`load_result_package` 经 `_load_marker_contract`（mtime_ns/ctime_ns/size 键）缓存；`verify=True` 的交付物 SHA 复核**不缓存**。
3. **进程内锁按路径键控串行两族锁**：`_PROCESS_LOCKS` 键升 (root, 锁族)，review_states 快照扫描不再阻塞 verification POST。
4. **队列执行临界区重复扫描 attempt 日志**：`_proposal_attempt_state` 快照穿入执行路径、`_durable_usage(rows=)`、`require_published_attempt(rows=)`（重扫路径 patch 成 raise 的防回归测试）。
5. **manifest/omission 陈旧锁按年龄偷取**：加 PID 活性检查（活进程的锁只等待到诚实 TimeoutError，绝不偷）。
6. **`/requirements`、`/review-states` 缺结构化错误边界**：撕裂尾 ValueError 掐连接 → 结构化 503（对齐 /document 兄弟端点）。
7. **`_memoized` 每命中 deepcopy**：实测 pickle 往返 1.1ms vs deepcopy 4.3ms vs json 8.9ms（3000 行载荷）→ pickle + deepcopy 兜底。
8. **富化造码整项拒收丢弃干净字段**：`analyze-unfounded-v4` 逐字段归属——同一提取器同一基线（是整项校验的**划分**而非启发式子串匹配），含造码字段排除采纳、干净字段存活；造码不写入任何交付字段（含澄清通道文本）；无可采纳字段时仍整项拒收如旧。红线测试：向每个可采纳字段逐一注入造码 × {software, co_design}，断言码不残留在任何交付值。
9. **快速失败探针 5 次串行**：review 与 spec_enrich 各自降为 2 样本（可用性检测价值几乎不变，失败路径不变）。
10. **`_software_prompt_parts` 每项重序列化模块词表**：按 (module, template) 备忘（输出字节不变）。
11. **`_unit_disposition` 不校验 guards_version**（顺序依赖隐患）：补上与 `load_annotation_translations` 同款闸门，处置与调用顺序无关。
12. **翻译单元重复哈希/延迟导入/块分支重复处置逻辑**：`_finalize_unit` 一次算键/摘要并复用；`_row_render_line` 提升到模块顶（子进程回归测试证无环）；块分支改调 `_unit_disposition`（语义不可分叉）。
13. **docx 每 cell 双遍 Paragraph 构建（一遍死代码）**：`_parse_cell_content` 返回已构建 `paragraph_objects` 穿入 `_cell_style_evidence`，重建循环删除。
14. **AGENTS.md 版本记载滞后**：实施中发现 `REVIEW_TOOLS_VERSION` 实为 v4、`LLM_REVIEW_CACHE_VERSION` 实为 v6、`ANALYZE_PROMPT_VERSION` 实为 v8（文档写 v3/v6/v7）——按"代码为准"各自从现值 bump 一级。

---

## 七、设计取舍（请重点审核）

1. **fold 未做全异步**：读后写可见性是承重契约（claim_views/队列终态投影/导出门禁在决策返回后立即读 committed effective），而这些读路径不在本次可改文件域内。选择"猝发合并 + 末次同步"：语义与今天完全一致，性能拿到 K→1-2 的合并收益。全异步化需要读路径 flush 配合，留作后续独立工作流。
2. **claim 压缩不丢历史**：attempt 全历史是付费工作重放的幂等基底（attempt_id = hash(proposal_id, idempotency_key)），丢历史会让重放键重新执行付费调用。因此"压缩"只修复撕裂/非规范行 + 阈值触发的原子重写，文件仍单调增长——但追加已是 O(1)，增长不再有平方级代价。
3. **证据作用域化的可靠性边界**：调用过 coverage_check 的缓存行保持全文件校验（该工具返回全文档聚合数）。审查缓存命中率的收益来自未调用 coverage 的行（多数）。若未来要求 coverage 行也按行失效，需要把 coverage_check 改为可声明作用域的输出，属工具契约变更。
4. **`_looks_translatable` 文种放宽**：改为"非 CJK 字母 ≥3"。混排文本以非 CJK 字母计数为准（如中日英混排里拉丁足够多即视为可译）——与旧拉丁版口径对齐，只是放开了字母文种。
5. **`title_rows` 是新的可选块载荷**：其缓存失效搭 v9（结构）/v3（翻译）版本 bump 的车（同一未合并变更集内原子生效）。旧结果包无此载荷时 full_translation 诚实输出空占位标题行，不伪造。
6. **sidecar journal 的可见性窗口**：只读 JSON 的 API 读者最多滞后一个压缩间隔；已完成翻译永不丢失（journal 为准）。api_server 读取器零改动是刻意约束。
7. **撕裂尾只在写侧治愈**：纯 GET 读者保持 fail-closed 原语义（三个旧测试因此改用恢复型入口或注入点重写，行为等价、断言更强）。

---

## 八、版本 bump 与缓存影响（合并纪律清单）

| 常量 | 旧 → 新 | 影响面 |
|---|---|---|
| `TABLE_STRUCTURE_VERSION` | v8 → v9 | atomize producer、claim_catalog_meta schema 枚举、结构依赖缓存 |
| `DOCX_TABLE_PHYSICAL_VERSION` | v1 → v2 | 物理网格戳（cells/blocks/rows） |
| `TABLE_DISPOSITION_RULE_VERSION` | v2 → v3 | table_cell_dispositions 每行 decision_version |
| `FULL_TRANSLATION_VERSION` / schema | v2 → v3 | 翻译计划/HTML、document_translation schema |
| `AI_EXTRACT_PROMPT_VERSION` | v24 → v25 | 付费 section 缓存键、ai-extract producer lineage |
| `ENRICH_PROMPT_VERSION` | v3 → v4 | spec 富化缓存键 |
| `UNFOUNDED_RULE_VERSION` | v3 → v4 | analyze 缓存键 |
| `REVIEW_TOOLS_VERSION` | v4 → v5 | 审查缓存指纹 |
| `LLM_REVIEW_CACHE_VERSION` | v6 → v7 | 审查缓存键（含紧凑 prompt + 作用域化） |
| `ENRICH_CACHE_FORMAT_VERSION` | 新增 v2 | 富化缓存格式（进 `_enrich_key`） |

- `prompt_registry.py` 五处同步（ai-extract/analyze-unfounded/llm-review-cache/review-tools/enrich），lint 测试绿。
- **合并 main 后必须**：用三种子 KB + domain-pack 重生成 `out/abnt_nbr_16968_atomizer_v5/`，跑 golden 六项核对漂移为零或在 CLAUDE.md 逐项说明——**重生成完成前合并不算定案**。
- 各行为版本使既有缓存一次性失效（每文档重跑一次对应阶段），符合纪律且已在提交信息草案中声明。

---

## 九、最终验证记录

- 后端：`RATOMIZER_HISTORICAL_SAMPLE=... python -m unittest discover -s tests` → **Ran 3598 tests, OK**（0 失败、0 跳过，255s；退出码 0）。
- 冒烟清单：90 modules / **1720 cases**（`tests/test_run_smoke.py` 基线 1649→1720 同步）。
- 前端：`cmd /c "npm test"` → **271/271（12 文件）**；`cmd /c "npm run build"` → vue-tsc + vite 构建通过（chunk 体积警告为既有噪音）。
- 集成期发现并修复的 4 个滞后基线：spot_extract 新读路径改 `governed_artifact_path`（地址纪律，AGENTS.md 红线）；4 个压缩阈值 env 登记 `config.ENV_REGISTRY`；`test_reason_with_fabricated_code_rejects_whole_enrichment` 按逐字段新契约改写（保留"造码不残留任何交付字段"红线断言， enriched 0→1 为预期语义变化）；冒烟用例计数基线更新。
- 输出不变性证明：解析器（同进程反向补丁对比，SHA-256 相等）、coverage_check 备忘（参考实现对比字节等价）、framing 插入时化（等价 + 不动点测试）、table_structure 性能重构（钉测基线）。

## 十、已知遗留（不属本次评审范围，已记录）

1. 巨型 xlsx（Canna-29 五万行级）下游矩阵物化内存峰值 ~20GB——`build_table_artifacts` 全量驻留问题，独立立项处理。
2. claim 账本文件单调增长（压缩不丢历史的设计后果；追加 O(1) 后增长代价线性）。
3. golden 漂移在合并重生成前未验证（见第八节合并义务）。

---

# 第二轮：审查反馈修复对照（2026-08-14，11 项全部修复）

> 用户对第一轮实施审查发现的缺陷，逐项核实（含行号与复现确认）后修复。修复分组与文件域：R2-1 requirements_analysis / R2-2 doc_annotation_export / R2-3 stat 三站 / R2-4 full_translation / R2-5 claim 两账本 / R2-6 前端 / R2-7 pdf_parser。
> 纪律：全部 TDD（先红后绿）；修复组 R2-6 另做变异验证（故意还原旧逻辑时新测试失败）。

## P1-1 翻译追加日志会永久丢失已付费译文 → R2-2 ✅

**核实**：读取 `raw.splitlines()` 会按 U+2028/U+2029 拆行；写入 `ensure_ascii=False` 让这些字符裸进文件；追加前不截断崩溃残行，新记录接在残行后双方皆坏；坏行被读取器静默跳过，随后压实可能删除日志。
**修复（三层）**：① 日志行改 `ensure_ascii=True`（机器专用缓存，U+2028/29 物理上无法裸进文件）；② 锁内追加前 `_truncate_torn_journal_tail`（r+b 截断无换行结尾的残行，撕裂行本就不是已完成条目，零损失）；③ 读取改 `split("\n")` 仅按 LF 切分。另核实压实删日志时序本就正确（os.replace 成功后才 unlink）并补回归测试。
**证据**：U+2028+U+2029 译文经日志写→读→重放字节等价；残行后追加两条完好行；遗留裸 U+2028 行按一行解析；replace 失败时日志存活。5 个新测试红转绿，158+46 测试绿。日志行 schema（v1）不变，无需 bump。

## P1-2 多组新缓存用 stat 代替内容身份 → R2-2/3/5 ✅

**核实**：Windows 上原地同尺寸覆盖+恢复 mtime 后 size/mtime/ctime 全不变（ctime=创建时间不随覆盖变）。五个站点全部确认。
**修复（按站点分层）**：
- `result_package` marker（小文件）：缓存键从 stat 三元组改为**内容 SHA-256**——任何伪造都改变摘要触发重验，彻底关闭（评审复现的"无效 marker 被当合法"现在 fail-closed）。verify=True 的交付物 SHA 复核保持每调用执行。
- `desktop_tasks._file_sha256_cached`、`api_server._memoized`：签名加 `st_dev/st_ino`——工具链唯一写路径是原子 os.replace（新文件身份），所有工具链写必失效；st_ino=0 的网络/重解析路径退化为旧行为（不更差）。
- `claim_artifacts.effective_snapshot_revision_key`：stat 加身份五元组 + 两条哈希链账本（ledger/WAL）加**尾行链头摘要**（尾部 8KiB 读取、SHA-256，含撕裂尾）。
**实证**：NTFS 上 os.replace 连创建时间一起变，marker 的复现必须用原地同尺寸写（与评审路径一致）；**原地同尺寸尾部编辑连身份签名都测不出、只有链头摘要能抓到**——分层各有独立价值。ledger 原子替换+恢复 mtime 的评审复现场景现在失效并 fail-closed（`hash mismatch for claim_ledger.jsonl`）。残留（恢复 mtime 的原地中部同尺寸篡改）在各站点如实注释，缓存未命中路径仍做全量内容校验。

## P1-3 富化缓存换模型/prompt 后永不恢复 → R2-1 ✅

**核实**：装载端遇旧 meta 整份弃用（语义正确），保存端只在空文件写 meta——换模型后新记录挂在旧 meta 下，每次装载仍返回空。
**修复**：锁内 `_probe_enrich_cache_generation` 四态探测——缺失→写 meta+行；匹配→追加；漂移（旧 meta/双 meta/形状不可信/中段损坏）→**代际滚动**：tmp+fsync+os.replace 换成新 meta+新行（与装载端弃用语义一致）；不可读（瞬时 OSError）→如实返回失败不动旧文件。
**证据**：换模型端到端——首轮重富化并重写 meta，二轮零调用；v2 过渡文件在 v3 下滚动；prompt 漂移同样恢复。5 个代际测试红转绿。

## P1-4 富化 JSONL 违反共享文件写入约束 → R2-1 ✅

**核实**：裸 `open("a")`，无锁、无原子代际初始化、无 PermissionError 重试。
**修复**：代际初始化、撕裂尾修复（read_jsonl_recover_torn_tail 原子修复，追加永不粘在残行上）、追加、滚动全部进 `process_file_lock`（仓库无 unlink 的 OS 级锁模式，锁文件经 governed_artifact_path）；追加与替换均 8 次线性退避 PermissionError 重试；稳态仍是每 flush 一次锁内 fsync 追加（O(1)/任务不变）。
**证据**：双线程屏障释放 ×15 次锁内保存 → 恰一行 meta 在首行、31 行全部完好、30 键全部可读。

## P1-5 富化缓存键确定性碰撞 → R2-1 ✅

**核实**：五段 `"".join` 无分隔拼接，("ab","c") 与 ("a","bc") 同键（复现 sha1 相同）。
**修复**：五段改规范 JSON 数组（`json.dumps([...], ensure_ascii=True, separators=(",",":"))`）进既有 sha1；`ENRICH_CACHE_FORMAT_VERSION` v2→v3（键方案变化，v2 过渡文件不可被 v3 误读/交叉命中）。
**证据**：template_refs×answers 与 answers×section_context 两组碰撞对键不同；相同输入键稳定；frozen_ownership 仍折入键。5 个编码测试红转绿。

## P1-6 纵向合并表格 HTML 网格错误 → R2-4 ✅

**核实**：rowspan 按物理行数输出，但每源行后插翻译行——rowspan="2" 实际吞掉翻译行的格位，下一物理行又省略被覆盖列 → 列错位；thead/tbody 跨段 rowspan 无效；旧测试只查字符串不验网格。
**修复（仅渲染层，账本/单元不变）**：源行完全取消 rowspan/colspan——每个物理行渲染全列；纵向续行渲染继承锚文本并标 `data-inherited="1"`（文本来自单元有效格/`_vertical_inheritance_map`，绝不虚构）；横向合并文本在最左格渲染一次、被覆盖格空置标 `data-merge-covered="1"`（翻译行是行级条带无法镜像逐格 colspan，取任务书中的内容保真回退）；防御性地保留与锚不同的被覆盖格原文（永不丢内容）。
**证据**：stdlib html.parser 的 DOM 级不变量测试——全文档无 rowspan、每 `<tr>` colspan 和=表宽、源/翻译行严格交替且成对网格一致；纵向续行显示继承锚、横向"Grand Total"恰一次。26 测试绿（修复前 4 失败复现双缺陷）。

## P2-1 堆叠标题重复且顺序颠倒 → R2-4 ✅

**核实**：首个物理标题行被提升为 table_title → figcaption 与 tbody 各渲染一次；thead 恒在 tbody 前，表头前的副标题显示到表头后。
**修复**：与 figcaption 文本相同的标题行只渲染一处（保留 figcaption）；表头物理行之前的标题行渲染为 thead 顶部全宽行（colspan=width，先于列表头——保持文档顺序）；表头之后（含表尾标题）按物理位置渲染进 tbody。账本保留全部标题单元（零内容损失）。
**证据**："Main Title" 恰一次、"Subtitle Line" 恰一次且 DOM 序在表头行之前；表后标题行在 tbody 表头之后。2 个新测试红转绿。

## P2-2 富化缓存写失败后本次运行不重试 → R2-1 ✅

**核实**：`flush_new_cache_rows` 在调用保存**前**更新 flushed_keys；保存吞 OSError。
**修复**：`_save_enrich_cache` 返回 bool（失败仍记警告）；flush 只在成功后把这批键计入 flushed_keys，失败留下轮 flush 重试；PermissionError 在保存的重试预算内先重试再报失败。
**证据**：追加失败→False+文件未动；瞬时 PermissionError 在预算内重试成功；端到端前两次 flush 失败→3 行最终全部持久化。3 个测试红转绿。

## P2-3 attempt-log"压实"超阈值后每次恢复全量重写 → R2-5 ✅

**核实**：跳过条件为"已规范∧行数≤阈值∧字节≤阈值"三合一，压缩不删行 → 超阈值后每次恢复（启动+每次队列执行）都整文件重写，产物字节相同纯浪费；verifier ledger 同构。
**修复**：两本账本跳过条件改为"**字节已规范即跳过**"（重写规范字节恒为 no-op）；阈值降级为纯上报字段（返回值新增 `over_threshold`，无调用方键删除）；撕裂尾在写侧装载时先截断再比较，治愈路径不变；真实漂移（非规范序列化）与 force=True 仍走重写。永不丢行、读者保持 fail-closed。
**证据**：超阈值规范账本 3 次恢复 + 压缩调用 → 原子写入器 0 次触发（计数补丁）；撕裂尾治愈回已提交字节；force 恰一次；非规范漂移仍重写规范化。183 测试绿。

## P2-4 前端 claim-maintenance 并发去重存在时间窗口 → R2-6 ✅

**核实**：维护请求结束即清空 in-flight promise；维护开始前发出、结束后才返回旧 503 的慢 GET 会再次触发维护；180ms 轮询下可能连环执行昂贵恢复。
**修复**：维护代际（epoch）屏障——GET 派发时同步捕获 epoch；返回可恢复 503 时仅当捕获 epoch == 当前 epoch 才触发维护（期间已有人恢复 → 只重放一次不再触发）；epoch 在每个维护 POST 的 finally 恰好 +1（成功/失败皆计，并发共享 in-flight 不多计）。单次重放与"POST 永不自动恢复"规则不变。
**证据**：慢 GET（派发早于维护、503 迟于维护完成）→ 仍恰 1 次维护 POST 且重放成功；恢复完成后的新 503 → 正常触发第二次（恰 2 次）；并发双 503 共享一次 POST（既有测试原样通过）。**变异验证**：把闸门还原为旧行为时新测试失败（2≠1）。前端 273/273 + 构建绿。

## P3 PDF 优化整文档词对象驻留内存 → R2-7 ✅

**核实**：检测遍把所有页的 extract_words() 词字典（11 键/词）全量驻留至主循环消费完。
**修复（两层）**：① 紧凑表示——备忘改 8 槽元组 (text,x0,x1,top,bottom,upright,size,fontname)（消费者逐一追踪确定，doctop/direction/width/height 无人消费），消费点 `_expand_words` 按需重建字典（可选键不凭空造）；② 有界回退——`PDF_PAGE_WORD_MEMO_MAX_PAGES=400`，超页文档整体弃用备忘回退逐页二次提取（页数前置已知）。
**证据**：实测 dict ~712B/词 → 元组 ~277B/词（**省 61%**）；400 页×500 词投影 ~136MiB→~53MiB，超 400 页备忘归零。备忘/回退两路径对同一 PDF 输出 JSON 等价且 `_extract_page_words` 调用数证明分支真实分叉（N vs 2N，非空跑）。162 测试绿。

## 第二轮版本与计数影响

- `ENRICH_CACHE_FORMAT_VERSION`："analyze-enrich-cache-v2" → **v3**（键编码变化；v2 过渡文件按代际滚动弃用）。
- 翻译日志行 schema（v1）、attempt 账本（v3）格式不变——均为字节层加固，无需 bump；`FULL_TRANSLATION_VERSION` 维持本变更集内已升的 v3（渲染契约属同一未发布 bump）。
- 冒烟用例计数基线 1720 → **1746**（两轮新增测试）；`test_run_smoke` 双跑稳定。
- 最终回归：后端全量 **3641 tests OK（0 失败 0 跳过，历史样本 env 已设）**；前端 **273/273** + `vue-tsc` + `vite build` 通过。
