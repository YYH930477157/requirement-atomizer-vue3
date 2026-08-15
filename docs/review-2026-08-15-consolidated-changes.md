# 整体变更审核清单（2026-08-15，供专家审核）

> **范围**：分支 `codex/table-translation-structure` 工作区全部未提交改动 = 三轮工作的总和。
> 第一轮（08-14）：全库代码评审定位的 25+ 项效率/效果问题实施（11 个并行工作流）。
> 第二轮（08-14 晚）：用户审查反馈的 11 项缺陷（6×P1/4×P2/1×P3）核实后修复（7 个并行工作流）。
> 第三轮（08-15）：专家复核反馈（1×P1 红线证伪、6×P2、文档不实与 P3）核实后修复（8 个并行工作流 + 主会话），见文末「第三轮」章节。
> **总量**：71 文件，+10714/−1027 行（35 个测试文件）；另有 8 个未跟踪文件（2 个新测试文件 + 6 个文档）提交时需显式 `git add`。
> **验证**：后端全量 **3679 tests OK（0 失败 0 跳过**，历史样本 env 已设）；冒烟 90 modules / 1766 cases；前端 **Vitest 273/273** + `vue-tsc` + `vite build` 通过。
> 细节级对照（问题→修复→证据）见 `docs/review-2026-08-14-fix-implementation.md`（第一轮一~十节 + 第二轮章节）；本文是跨轮整合的子系统视图。

---

## A. 追加式文件写入（四处 O(N²) → O(1)，加崩溃完整性）

**统一动机**：原来每追加一条记录都全量扫描+整文件重写（claim attempt 日志自带基准：300 事件 366.8s）；且第二轮审查发现新引入的追加日志有两类完整性洞。

| 文件 | 改动点 | 实测 |
|---|---|---|
| `claim_reextract_attempts.py` | 真追加（open("ab")+fsync/事件）+ stat 签名链头备忘（行/幂等键/增量 sha256）+ 压缩重物化；撕裂尾写侧截断治愈，纯 GET 读者保持 fail-closed | 300 事件 366.8s→**0.99s**；1000 次备忘读 0.22s |
| `claim_artifacts.py`（verifier WAL） | 同构：增量链式追加 + `_VerifierLedgerState` 备忘 + 前缀哈希缓存 + 压缩 | 60 次链式发布 2.22s；50 次基座加载 0.36s |
| `requirements_analysis.py`（富化缓存） | 单 JSON 整写 → JSONL 追加（`analyze-enrich-cache-v3`）：**锁内四态代际探测**（缺失→建/匹配→追加/漂移→原子滚动换 meta/**换模型可恢复**/不可读→如实失败）；process_file_lock + 8 次线性 PermissionError 重试；flushed_keys 只记成功落盘（失败本轮重试） | 双线程×15 并发保存单 meta 无交错；换模型二轮零调用 |
| `doc_annotation_export.py`（翻译 sidecar） | 每批读-合-写 → `annotation_translations.journal.jsonl` 追加日志+压缩（主 JSON 格式字节不变，api_server 读取器零改动）；第二轮加固：写入 ensure_ascii（U+2028/29 物理不裸进文件）、锁内追加前截断崩溃残行、读取只按 LF 切分；压实删日志仅在 os.replace 成功后 | 3 批→3 追加+1 压缩；崩溃重放零丢失；U+2028 译文字节等价回放 |
| `ai_extract.py`（partial 快照） | 每节全量重写+全行重跑 framing → 插入时一次性 framing（等价性+不动点测试）+ 节流写（8 次/5s）+ 终态无条件 publish | 10 节 11→3 次快照，终态字节等价 |

**压缩语义（两本 claim 账本）**：永不丢行（attempt 历史是付费重放的幂等基底）；跳过条件="字节已规范即跳过"（第二轮修复：原三合一阈值条件导致超阈值后每次恢复全量重写）；阈值降为上报字段。
**追加重试覆盖（第三轮补齐）**：全部文件变更型 open（追加/截断）均带 8×线性 PermissionError 重试、预算耗尽响亮抛出——claim 两账本的追加与撕裂尾截断、verifier WAL 追加、翻译 journal"截断+追加+fsync"整段、`claim_review_events` 批量句柄打开（第三轮主会话补）。措辞澄清：所谓"O(1) 追加"指**磁盘 I/O O(1)**（每追加含 O(现行数) 的备忘复制/索引重建，绝对开销小——300 事件 0.99s 实测含此成本）。
**审核重点**：① 各追加路径的崩溃窗口（撕裂行是否恒等于"未完成"）；② 代际滚动的并发正确性（双 meta 是否可能出现）；③ 压缩幂等性（规范字节不再重写）。

## B. 缓存身份与完整性（stat 信任分层）

**统一动机**：第一轮把热路径全量哈希换成 stat 签名备忘（性能），第二轮审查证明 stat 可被"原地同尺寸覆盖+恢复 mtime"绕过（Windows ctime=创建时间不随覆盖变），必须分层加固。

| 站点 | 身份方案 | 关闭的攻击面 |
|---|---|---|
| `result_package` marker（小文件） | 缓存键=**内容 SHA-256**（每次读 KB 级字节） | 全部（任何伪造改变摘要→重验 fail-closed）；verify=True 交付物 SHA 复核保持每调用 |
| `desktop_tasks._file_sha256_cached`、`api_server._memoized` | stat 加 `st_dev/st_ino`（原子 os.replace=新文件身份→工具链所有写必失效） | 工具链写路径全部；st_ino=0 的网络/重解析路径退化为旧行为 |
| `claim_artifacts.effective_snapshot_revision_key` | 三层：stat 身份五元组 + **两条哈希链账本尾行链头摘要**（尾部 8KiB）+ 两个提交锚 meta 内容摘要 | 实证：os.replace 复位 mtime 的评审复现→失效；**原地同尺寸尾部编辑仅链头摘要可测出**（身份签名测不出）——每层有独立覆盖面 |
| `llm_pipeline` 审查缓存（证据指纹） | 全局指纹 → 按需求作用域：键=稳定证据（KB/块/蓝皮书）+自身行哈希；**调用过 coverage_check 的行保持全文件哈希校验**（其返回全文档聚合，不作用域化） | 改一条需求不再作废全文档审查缓存；可靠性边界显式（见审核重点） |
| 阶段指纹（desktop_tasks） | 每阶段同批文件 5-6 遍全量 SHA → 单遍 {name:sha} 映射派生全部指纹；producer 只算一次并穿入 manifest | 指纹值字节不变（纯性能）；atomize producer 补钉 `DOCX_TABLE_PHYSICAL_VERSION`+`TABLE_DISPOSITION_RULE_VERSION`（修掉 bump 不失效的静默缓存洞） |

**残留风险（如实声明，各站点已注释）**：恢复 mtime 的**原地中部同尺寸**篡改大文件——stat+链头摘要测不出；防御=缓存未命中路径仍做全量内容校验 + 该写法不在工具链任何路径中。
**审核重点**：① coverage_check 行的全文件校验是否真正覆盖所有全文档聚合依赖（唯一读 atomic_requirements.jsonl 的工具是它——需复核）；② st_ino 在目标部署文件系统的可用性；③ 残留风险声明是否可接受。

## C. LLM 调用层（成本与鲁棒性）

1. **coverage_check 备忘化**（`review_tools.py`，`review-tools-v5`）：块索引/需求索引/一致性索引（共指+重复组）/紧凑块文本每执行器算一次；单调用 3.57ms→**0.052ms（~68x）**；与旧算法参考实现在多样合成语料**字节等价**。
2. **工具循环禁用替代中断**（`llm_client.py`）：同一工具连续两错→剩余轮次禁用+催最终 JSON，已付费轮次不再丢弃；硬性供应商错误（4xx 工具不支持/500/连接）仍大声失败——stub 化红线不变。
3. **prompt 紧凑序列化**（4 处，`ai-extract-v25`/`enrich-v4`/llm 两处入 `llm-review-cache-v7`）：`indent=2`→紧凑分隔符，零措辞变化（往返测试），每次调用省 ~15-25% token。
4. **快速失败探针** 5→2（review 与 spec_enrich 各自常量）；**缺槽回退**从 worker 内串行改为编排器 FIRST_COMPLETED 重提交到同池。
5. **逐字段造码降级**（`analyze-unfounded-v4`）：同一提取器同一基线（整项校验的**划分**而非启发式）——含造码字段排除采纳、干净字段存活；造码不写入任何交付字段（含澄清通道）；无可采纳字段仍整项拒收。红线测试：逐字段注入造码断言零残留。
**审核重点**：① 逐字段划分的基线完备性（analysis 侧 basis=source∪section_context，delivery 侧=source∪template codes——是否存在划分外的注入路径）；② 禁用工具后模型被迫提前输出的质量影响（是否需要在 prompt 中声明）。

## D. 表格翻译与结构（效果主线，`full-translation-v3`/`table-structure-v9`）

1. **纵向合并保结构化**：不再整表降级 complex_table——`_physical_matrix` 从块载荷重建物理网格，单元经 `inherit_merged_text`（只喂纵向 range）渲染；降级只留嵌套表与真冲突几何。SBD 实测 8 张原降级表全部恢复逐行。
2. **HTML 网格（第二轮重写，第三轮精确化）**：**数据/表头源行无 rowspan、无逐格 colspan**——每物理行渲染全列，纵向续行显示继承锚文本（`data-inherited`），横向合并文本在最左格一次+被覆盖格空置标记（`data-merge-covered`）；标题源行与全部译文行是 `colspan=表宽` 的全宽条带（有意布局，非逐格合并）；第三轮补：2D 合并分解为纵向分量，锚行横向跨幅保持空置、续行仅锚列继承（账本/LLM 输入锚文本每行恰一次）。DOM 级不变量测试（无 rowspan、每行 colspan 和=表宽、源/翻译行严格成对同构）。
3. **堆叠标题行**：atomize 写入 `title_rows` 载荷（与索引对齐）端到端打通；账本每行一个 title 单元（零内容损失）；HTML 与 figcaption 相同文本只显示一次、表头前标题进 thead 顶部保文档顺序。
4. **可译性门槛**：空行/纯数字行 `nothing_translatable` 不进 LLM；`_looks_translatable` 规则（第三轮精确化）= **非 CJK 字母≥3 且 ≥CJK 字数**——俄文等字母文字可译（CJK≈0），中文为主仅含缩写的混排文本不进管线（保持旧拉丁版比例语义，仅放开字母文种）；xlsx 全宽合并标题行在 atomize 边界按合并范围折叠为锚格+空覆盖格（第三轮修复 N 重复制进 LLM/账本/HTML 的问题）。
5. **字母复合表头** (a)..(j)→(a)..(z)（两处镜像正则同步，仍须 a 起头）；claim_catalog_meta schema 枚举同步。
6. **性能**：`table_structure` set 提升/几何上下文共享（plan 与 cell_items 一次算清）/增量列集合/锚映射预计算——420×12 合并表 1.3x；`atomize` frozenset 缓存 1.9x；输出与改动前字节一致（钉测基线）。
**审核重点**：① `_physical_matrix` 放置证据校验的保守性（证据不完整回退块列表，是否可能误信）；② 继承锚文本的 data-inherited 渲染在续行重复出现——账本去重键是内容哈希（重复行共享译文），HTML 重复显示是否可接受的产品取舍；③ 横向合并"文本渲染一次+空置标记"相对旧 colspan 视觉变化。

## E. docx 解析与处置（`docx-table-physical-v2`/`table-disposition-rules-v3`）

- **row_width_conflict 拆分**：解析器已确定性调和（width=max(声明,观测)+补齐，内容无损）的冲突降为 `reconciled:true` 审计注记，不再整表 review；调和无损条件**运行时显式验证**（每个观测 cell 列与合并 range 列 ∈[1,width]），未来代码回归自动退回阻断（宁漏勿错入码）；merge_conflict/merge_text_conflict 永不豁免。
- **死代码消除**：`_parse_cell_content` 返回已构建 `paragraph_objects` 穿入 `_cell_style_evidence`，每 cell 双遍 Paragraph 构建删除（输出字节不变）。
**审核重点**：reconciled 判定的无损验证是否覆盖所有几何路径（行窄于声明网格的补齐方向）。

## F. API 服务与热路径

1. `/requirements` 先切页再富化（响应为纯列表契约已核实）；`/ai-extraction-status` 接 `_memoized`（partial 写入即失效，进度仍实时）；`/table-reviews`、`/document/pdf` 走 `load_committed_effective_snapshot_cached`（LRU+single-flight+分层身份键）。
2. **启动顺序**：先绑端口打 readiness，claim 维护+表重算恢复放守护线程（模块级 Event 保证每进程恰好一次）；维护期 GET 照旧 fail-closed 结构化 503——消除 Electron 30s 杀进程三连重做。
3. `/requirements`、`/review-states` 补结构化 503 边界（撕裂尾不再裸断连接）；`_memoized` 拷贝 deepcopy→pickle 往返（实测 4.3ms→1.1ms，deepcopy 兜底不可序列化值）。
4. `_file_sha256` 备忘（doc_annotation_export，含身份五元组）；doc_facsimile 输入哈希一次穿两处；spot_extract 锁内一次读 blocks（新读路径走 `governed_artifact_path`）。
**审核重点**：后台维护线程与首批 GET 的 503 窗口（UI 是否所有视图都优雅处理 `effective_recovery_pending`）；pickle 往返的类型保真（自定义 `__reduce__` 对象）。

## G. 审查状态层（`review_state`/`ai_review_actions`/`omission_actions`）

- os.replace 统一 8 次线性退避（原最热保存路径仅 80ms 窗口，Windows AV 持锁即 503）。
- **fold 猝发合并协调器**：权威写入→注册单调 pass 号→属主同步 fold/等待者 Condition；不变量=返回时必有 ≥注册号的同轨 pass 完成（**读后写可见性不变**，因 claim_views/队列终态投影在决策返回后立即读 committed effective——全异步需读路径配合，留作后续）；K 并发点击 1-2 次 fold；崩溃恢复语义不变。
- 进程锁按 (root, 锁族) 键控（review 快照扫描不再阻塞 verification POST）；manifest/omission 陈旧锁偷取加 PID 活性（活进程只等待到诚实 TimeoutError）；权限修订哈希按快照内容 sha 缓存（8 项 LRU）。
**审核重点**：协调器 covering-pass 不变量的证明链（属主崩溃→等待者接管路径）；排空上限 3/任期的饥饿可能性。

## H. 前端（`ui/src/api-client.ts`）

- claim 恢复类 503 自动 POST `/claim-maintenance` 并重放原 GET 一次；**代际（epoch）屏障**：GET 捕获派发时 epoch，迟到的旧 503 只重放不再触发（慢 GET 场景恰 1 次 POST，变异验证）；并发去重 in-flight promise；POST 永不自动恢复。措辞澄清（专家指正）：GET 实际只会收到 `effective_recovery_pending`（第三轮起 /table-reviews 与 /document/pdf 也返回该机器码）；`claim_artifact_recovery_required` 仅出现在 POST 响应中而 POST 不自愈——前端双码匹配是无害的冗余防御。
**审核重点**：epoch 递增点（POST finally）与 in-flight 清除的时序；维护失败后的退避策略（当前无时间退避，仅代际去重）。

## I. 解析器性能（输出字节等价已证）

- PDF：每页词提取 2→1 遍（检测遍存紧凑 8 槽元组——实测 ~712B/词→~277B/词省 61%——消费点重建）；**400 页上限**超限整体回退逐页提取（两路径输出 JSON 等价+调用计数证明分支真实）；词表指纹 lru_cache。
- xlsx：三遍全表扫描合一 + `_RowColumnIntervals` 区间覆盖计数（5 万行桩区域检测 ~3x；真实工作簿 2.71→2.35s）。
- 等价性证明方法：同进程反向应用改动块重建旧模块，前后输出 SHA-256 相等（2 PDF+3 工作簿含合成桩）。
**审核重点**：8 槽属性集的消费者完备性（doctop/direction/width/height 确认无消费者）；400 页阈值的合理值。

---

## 版本 bump 总表（合并纪律）

| 常量 | 旧→新 | 说明 |
|---|---|---|
| `TABLE_STRUCTURE_VERSION` | v8→v9 | 字母表头 a-z；进 atomize producer、claim_catalog_meta schema |
| `DOCX_TABLE_PHYSICAL_VERSION` | v1→v2 | reconciled 拆分；**本轮起钉入 atomize producer** |
| `TABLE_DISPOSITION_RULE_VERSION` | v2→v3 | 处置变化；同上新钉入 |
| `FULL_TRANSLATION_VERSION`/schema | v2→v3 | 纵向合并结构化+网格重写+标题行+可译性（同一未发布 bump 内含第二轮渲染修复） |
| `AI_EXTRACT_PROMPT_VERSION` | v24→v25 | 紧凑 JSON（prompt_registry 同步） |
| `ENRICH_PROMPT_VERSION` | v3→v4 | 紧凑 JSON |
| `UNFOUNDED_RULE_VERSION` | v3→v4 | 逐字段造码降级 |
| `REVIEW_TOOLS_VERSION` | v4→v5 | 备忘化（注：AGENTS.md 原记 v3 为滞后，代码实为 v4） |
| `LLM_REVIEW_CACHE_VERSION` | v6→v7 | 紧凑 prompt+证据作用域（原记 v6 为当前值） |
| `ENRICH_CACHE_FORMAT_VERSION` | 新增→v3 | JSONL 格式+无碰撞键编码（v2 为本变更集内过渡值） |

不 bump 但格式相关的决策：claim attempt 日志（v3）/翻译 journal（v1）盘上格式逐字节不变（纯写入策略加固）；`ANALYZE_PROMPT_VERSION` 实为 v8 未动。
**合并 main 后必须**：三种子 KB+domain-pack 重生成 `out/abnt_nbr_16968_atomizer_v5/` 并核对 golden 漂移为零或逐项说明——完成前合并不算定案。

## 红线保持矩阵

| 红线 | 保持机制 | 证据 |
|---|---|---|
| 造码零残留（宁漏勿错） | 逐字段划分同提取器同基线；造码不进任何交付字段含澄清通道 | 逐字段注入×双模式断言零残留 |
| 来源不伪造 | 工具循环禁用≠失败伪装；硬错误仍 stub 化大声失败；JSON 侧车 provenance 不变 | llm_client 中途错误仍 raise 测试 |
| 读者 fail-closed | 撕裂尾只在写侧治愈；GET 路径校验失败返回结构化 503 不猜 | 伪造行→`claim_reextract_attempt_recovery_required` |
| 无静默内容损失 | 标题行逐单元进账本；网格重写防御性保留异文被覆盖格；reconciled 运行时验证 | 堆叠标题三单元断言；等价性/不动点测试 |
| 共享文件写纪律 | 全部文件变更型追加/截断路径锁内+PermissionError 8×线性重试+原子替换（代际/压缩/重试第三轮补齐含 claim_review_events） | 双线程并发保存单 meta；全部重试路径红先行（瞬时成功/预算耗尽响亮/文件保持完好） |
| 缓存失效诚实 | 版本 bump 显式；stat 加固残留风险注释；未命中路径全量校验 | 评审两复现场景红转绿 |

## 建议专家重点复核的六个面

1. **证据指纹作用域化**（B/llm-review-cache-v7）：coverage_check 全文件校验的完备性论证——是否还有隐式全文档依赖未被 `evidence_deps` 覆盖。
2. **fold 协调器不变量**（G）：covering-pass 证明、属主崩溃接管、排空上限饥饿。
3. **stat 身份分层**（B）：残留攻击面声明是否可接受；st_ino 在部署 FS 的行为。
4. **HTML 网格重写**（D.2）：data-inherited 重复渲染与 data-merge-covered 空置的产品取舍；DOM 不变量测试的覆盖面（嵌套场景）。
5. **代际滚动**（A 富化缓存）：四态探测在极端交错（两进程同时探测到漂移同时滚动）下的收敛性。
6. **golden 重生成预期**：多个行为版本 bump 后 `out/` 基线将整体漂移——合并时需逐项归因（本变更集有意为之，非意外）。

## 验证矩阵

- 全量后端：3641 tests OK / 0 失败 / 0 跳过（`RATOMIZER_HISTORICAL_SAMPLE` 已设；exit 0）。
- 冒烟：90 modules / 1766 cases（`test_run_smoke` 稳定）。
- 前端：273/273 + vue-tsc + vite build。
- 字节等价证明：解析器（反向补丁同进程对比 SHA-256）、coverage_check 备忘（参考实现对比）、framing 插入时化（等价+不动点）、table_structure 重构（钉测基线）、PDF 备忘/回退（JSON 对比+调用计数）、xlsx 区间覆盖（第三轮起另有种子化随机差分测试固化）。
- TDD 纪律：三轮全部新测试先红后绿；前端代际屏障另做变异验证（还原旧逻辑→测试失败）。
- 已知遗留（非本批范围）：巨型 xlsx 矩阵物化内存 ~20GB；claim 账本单调增长（设计后果，磁盘 I/O O(1)/追加）。

---

# 第三轮：专家复核修复对照（2026-08-15，全部完成）

> 专家审核意见逐条核实（含 PoC）后修复；除标注外全部 TDD 红先行。终验：后端 3679 全绿 0 跳过、冒烟 1766、前端 273/273+构建。

## P1 造码检测对 str 类型列表字段失明 → ✅ R3-1

**核实**：`requirements_analysis_agent.py` 的 `delivery_text` 对 `(item.get(field) or [])` 直接迭代——LLM 对 design_options 返回 str 时迭代出单字符，三种受保护编码全被切碎，`extract_codes` 永不命中；专家 PoC：G-SGX-EY str 形态零 issue 直接收、OBIS str 形态造码经 `clarify_fallback` 透出进澄清通道（红线声明被证伪）。该洞在 HEAD(v3) 同样存在，非本轮回归。
**修复**：`_as_list` 归一进 `delivery_text`（str→单元素列表；tuple→list；None→[]）；字段级重检本已归一，整体检出门控修复后自然激活。两个 PoC 现均硬拦截、降级待澄清、**造码不进整个交付项 JSON（含 clarify_fallback/open_questions）**；str 与 list 路径逐字节平价（平价测试锁定）。
**版本决策**：不 bump `UNFOUNDED_RULE_VERSION`（v4）——富化缓存存**原始** LLM 条目、护栏每次命中重跑，旧缓存 str 载荷被回溯拦截，bump 只会迫使全库重付费换零正确性收益。

## P2 六项 → ✅ 全部修复

1. **fold 跨轨饥饿**（review_state）：饥饿场景红先行复现（4 个 A 轨持续生产者 + B 轨等待者 5s 零进展）→ 槽位释放时**异轨优先让位**（双轨等待严格交替；纯单轨等待保持原猝发合并）+ `cover()` 30s 有界等待，超时抛 `EffectiveFoldCoverTimeout(TimeoutError)`（现有处理器已映射可重试 503，零额外改动）；决策先持久化后 cover 的语义、covering-pass 不变量、崩溃恢复全部保持。
2. **xlsx 合并标题 N 重复制**：atomize 边界新增 `_collapse_merged_title_row`——按归一化合并范围保留锚格文本、清空覆盖格（镜像 docx 物理网格；`validate_merge_text` 已保证覆盖格文本与锚一致，清空零损失）；title_rows 单元与 table_title 相等 → figcaption 去重生效；data_rows/header_rows 不动（xlsx 数据行扁平填充是既有语义）。连带修复 **2D 合并双份锚文本**（P3）：纵向喂入分解为锚列条带，锚行横向跨幅空置，账本/LLM 输入锚文本每行恰一次。
3. **富化缓存收尾 flush**：futures 循环后补一次 flush（空集短路零开销），末批失败由收尾 flush 重试。
4. **翻译 journal 追加重试**：锁内"截断+追加+fsync"整段 8×线性重试、耗尽响亮；截断路径原先静默吞 PermissionError（会在残行上追加=粘行损坏成因）改为抛入重试。
5. **未跟踪测试文件**：`tests/test_analyze_enrich_cache_integrity.py`、`tests/test_analyze_enrich_perf.py` 确认存在——**提交时必须显式 git add**（见文末提交清单）。
6. **构建产物入库风险**：`.gitignore` 新增 `ui/.pkg-backup/`、`ui/dist-open-existing/`、`ui/ui-dev-server.log`、`session-archive/`（`git check-ignore` 验证生效）。

## 文档不实/夸大 → ✅ 已修正（本文件）

- 红线矩阵"全部追加路径重试"声明经第三轮补齐后为真（含 claim_review_events）。
- "源行完全无 rowspan/colspan" → 精确为"数据/表头源行无 rowspan、无逐格 colspan；标题行与译文行为全宽条带"。
- "O(1) 追加" → 明确为磁盘 I/O O(1)，每追加含 O(现行数) 备忘复制（实测含此成本）。
- `_looks_translatable`"与旧口径对齐" → 修复代码本身：恢复比例约束（非 CJK≥3 且 ≥CJK），中文为主含缩写文本不再进 LLM，注释改述真实规则。
- 前端双码说明 → GET 实际只见 `effective_recovery_pending`；双码匹配为无害冗余防御。
- AGENTS.md `analyze-enrich-cache-v2` → v3；"rowspan"措辞 → 无 rowspan。
- **/table-reviews 与 /document/pdf 恢复挂起机器码化**（子代理报告核实为真并修复）：前者加专属 `ClaimEffectiveRecoveryPending` 分支，后者经 `__cause__` 链还原语义——两端现返回前端自动恢复触发键精确对齐的结构化 503。

## P3 七项 → ✅ 全部修复

1. **`_RowColumnIntervals` 退化矩形**：构造器跳过倒置矩形（实证旧代码产出 -1 被守恒门静默放过，现响亮上报 dropped）；**种子化随机差分测试**（40 合成表×含退化形态，与朴素逐格参考逐格断言）固化等价性。
2. **2D 合并双份锚文本**：见 P2.2 连带修复。
3. **`_pid_is_alive`**：模块级缓存 `WinDLL(use_last_error=True)`；判死仅限明确证据（exit code≠STILL_ACTIVE / OpenProcess ERROR_INVALID_PARAMETER），探测异常一律视为活——绝不偷活锁；真实子进程活/死/探测失败三态测试。
4. **schema 修复轮 banned_tools 携带**：`chat_with_tools` 新增 `initial_banned_tools` 种子（首轮 tools 面排除+连击预置+meta 暴露禁用集），修复轮接线——已禁工具不再重执行浪费付费轮（恰 4 次付费请求断言）。
5. **`_file_signature` 身份加固**：claim 两处内部备忘签名升级为 (size, mtime_ns, ctime_ns, st_ino, st_dev)；测试用 `SetFileTime` 恢复创建时间的确定性伪造（实证朴素 os.replace+utime 在 NTFS 上不总能骗过旧三元组）。
6. **备忘淘汰上限**：`_STAGE_INPUT_SHA_CACHE` 256 项 clear-on-overflow（与 `_FILE_SHA256_MEMO` 同款约定）。
7. **/reviews 撕裂尾边界**：补齐兄弟端点同款结构化 503（红先行复现裸断连接）。

## 提交清单（合并时）

- 71 个已跟踪修改文件 + **8 个未跟踪文件必须显式 git add**：`tests/test_analyze_enrich_cache_integrity.py`、`tests/test_analyze_enrich_perf.py`（红线矩阵证据）、`docs/review-2026-08-14-fix-implementation.md`、`docs/review-2026-08-15-consolidated-changes.md`（本文件）及 4 个既有用户文档。
- 版本 bump 与 golden 重生成义务见第八节（第三轮无新增行为版本；`UNFOUNDED_RULE_VERSION` 维持 v4 的论证见上文）。
