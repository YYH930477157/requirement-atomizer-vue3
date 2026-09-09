# TODO — 待办与路线（2026-09-09 更新）

> 来源：架构评审（2026-07-06）+ 组件增强评审 + 项目战略评审 + 架构收敛计划
> （`docs/architecture-convergence-plan-2026-08-27.md`）。完成一项划一项；
> 重启任何「有据缓建」项前先重跑探针。日常状态速查：输出目录 `run_manifest.json`。

## 当前待办（2026-09-01 更新，全量交接见 `docs/handoff-2026-08-31.md`）

- [x] **减法：GUI 去掉软件需求分析**（2026-09-01e，分支 `codex/drop-requirements-analysis`）：
  日常 B 轨表面改回功能需求 + 澄清；`requirements-analysis` 不进默认链。分析模块 /
  CLI / `ab_runner` 保留给门禁。下一步不是补分析质量。
- [x] **减法：GUI 去掉公司模板成文**（2026-09-01d，分支 `codex/drop-template-write`）：
  成文写入器/CLI/`ab_runner` 保留，不进默认链。09-01e 起分析也不再是日常产品。

- [x] **门禁 B 轨剩余质量项归因**（2026-08-31 完成，含 E:\Codex 实测补位：
  `docs/binding-attribution-2026-08-31.md` §7）：v7/v8 实测绑定 25→**2**（引句
  逐字锚豁免 24）；剩余 2+3 中 **4 条同源于 Security 条款 Table 3 列序打乱拼接**
  （输入侧病理，任务 D 领域，非 LLM 借位/丢数字）、1 条 b 类重复文本语义
  （须审核方裁定）。
- [x] **任务 D 第一刀：表格 preservation 归类与设计裁决**（2026-09-06）：只读归类工具
  与附录已落盘；重复 section_id/缺少物理块身份的项目保留 `manual_review`，不把旧包
  当作当前门禁 PASS。设计结论优先走提示强化 + 专家定点闭环，不重启原子化粒度。
- [x] **E1/E2 血统与模板列契约收敛**（2026-09-06）：大纲版本进入 functional
  extract 路由指纹；`template_columns.py` 统一写入器与 A/B 门禁的列别名、固定列位和
  归一化逻辑，保留原有兼容导出。
- [x] **WS0 门禁/ABNT 轨道：关账——因目的消失而关闭**（2026-09-09 用户裁定
  「为什么还在纠结 ABNT？」→ 复盘确认）。三个事实：①门禁的本来目的
  （`RATOMIZER_EXECUTION_POLICY` 翻转放行）已被产品演进绕过——功能直抽自
  09-07 起就是生产默认（CLI 默认功能轨、GUI 日常链即它），09-06 边际重估也判
  翻转价值收窄；②门禁自 2026-08-31 起本就处于用户裁定的挂起态；③真值工件
  （Canna29 条目化表）是阅读笔记式注释（定义/转述/段落级），与行级需求清单
  形态根本错配——语言层已修（`ws0_human_v2_en`），粒度/形态层不值得再投。
  **A/B/C 匹配层裁定撤销（不需要裁）**。资产留档备用：v2 英文真值 + 重建工具、
  注入评估方法（`out/inject/`，零付费可复跑）、归因工具链、守恒 v8/v9 与
  preservation 闭环接线（这些本身是产品资产）。若未来真需要 P/R 指标，前置是
  重建真值方法论（分析师侧），不是匹配器调参。
- [ ] **新收尾主线（2026-09-09 起）——以真实工作文档为验收场**：
  ① **进行中**：最新版 ZETDC 真实文档已完成第一轮解析复查；编号义务句、冒号
  引导清单、列表后正文、罗马编号小节和噪声隔离已加规则与回归钉，仍需人工复核
  语义质量；跨页表格续文已按“相邻页、同节、同列数、上一页末条款号、下一页
  小写续文且无条款号”登记为 5 个 `manual_review_or_llm_context` 候选，保留物理
  表边界，不自动拼接；`paragraph_review.html` 已同时展示语义单元与候选提示；②
  **已完成本机无付费链路检查**：功能需求直抽
  240 条、原文块全覆盖，stub 结果如实标 `evidence_presence` 待核并生成
  `document_annotation.html`；真实 LLM 运行仍需用户配置模型与密钥；③ **待 Windows
  主机完成分发验证**：Mac 已完成前端测试/构建，`desktop:pack` 在 macOS 因
  PowerShell 不存在无法执行，Windows 端需跑完整 Electron/PyInstaller 链。
- [ ] **大纲权威 flag 翻转评估重启（可选）**：v1 验证已判 **No-Go**。重启前置
  里 heading-only 退化 objective **已修**（routing v8）；仍缺短条款抽取覆盖
  强化、可选 ¥7 对照腿；须在 routing v8 / conservation v7 基线上重新测量。
- [ ] **队列收敛收尾：旧文件兼容期观察与裁撤评估**：四主体已全部入链
  （omission / clarification_internal / atom_expert / ai_review，第 3 步
  `441fde8`）。旧 JSONL 保持逐字节投影 ≥ 两个桌面发布周期后，评估读者迁移
  与旧文件裁撤（设计 §6 兼容承诺）。
- [ ] **技术表格保留率课题（中期）**：SBD section 6 参数表数字的 preservation
  blocking（~50）是既有质量课题（2026-08-26/27 两轮路由收敛后如实转移归因至
  该表）——方向：表格单元级守恒委托已铺路（WS-A），剩余在真实 b_track 义务表
  上，需按行/格粒度抽取或专家定点闭环。
- [ ] **测试套件有据瘦身（可选，低优先）**：全量已并行化至 ~5 分钟
  （`160b2df`；2026-08-29 合并后 4199 例 311.6s），跑速痛点已解。如仍要瘦身：
  逐文件审计「可删/该留/可合并」清单（目标有据收敛至 3000-3500，禁止按数量
  指标批量删钉子）。
- [ ] **架构收敛 Phase 3**：SQLite 状态存储 + 内容寻址 DAG 指纹（计划文档
  §Phase 3；在队列收敛与大纲接线完成后启动）。

### 已完成（2026-09-01）

- [x] **减法：GUI 去掉软件需求分析**（分支 `codex/drop-requirements-analysis`，
  基线 `2e92140`）：默认链不再跑 `requirements-analysis`；日常产品是功能需求 +
  澄清。分析/成文 CLI 与门禁保留。
- [x] **减法：GUI 去掉公司模板成文**（分支 `codex/drop-template-write`，基线
  `9f40a78`）：`_notes_text` 单源待核前缀；成文 CLI/门禁保留。09-01e 起分析
  也不再是日常产品。
- [x] **待核成文 v3 hotfix（分支 codex/partial-export-hotfix，基线 193efc8）**：
  package_v1 寻址修复（governed 单源——桌面跑不再出零标记假干净表）+ draft+未
  闭合一律拦 + 待核行红字 + 「守恒待核」清单 sheet（零 FRE 缺口只进清单不造
  需求行）。`conservation-partial-export-v3` + template-write impl-v6（旧分析/
  成文代失效重跑，零 LLM）。**验收闸零放宽**：claim shadow / full closure /
  ab_runner / 结果包 completed 判定全部未动；门禁仍挂起（2026-08-31 裁定维持）。
  方案 `docs/pending-export-v3-plan-2026-09-01.md`，聚焦 289 绿 + worktree 全量
  4292/0 失败 + UI 289/289。
- [x] **待核成文 partial export（政策反转，用户拍板）**：守恒未闭合/直抽 partial
  时分析·成文·澄清照跑并如实标 partial，失败面行级「⚠待核（失败类）」进 xlsx；
  首代发布走 record_analysis_partial（marker=incomplete）；failed/draft 仍拦；
  READY/Claim/WS0 门禁语义零改动；`RATOMIZER_PARTIAL_EXPORT=0` 回滚。方案
  `docs/pending-export-plan-2026-08-31.md`（grok 审核三条落实），15 新测试，
  全量 4274 + UI 286 绿，门禁 B 腿真实数据终验 43 行待核。

### 已完成（2026-08-31）

- [x] **heading-only 条款出抽取池**（routing v8，`2a10f28`）：TGS 裸标题不再进
  抽取池；result3 回放 34 条路由出，技术章零误伤。
- [x] **绑定检查 reason 1 引句本地锚**（conservation v7，`6d8db13`）：清单/表格
  行诚实抽取不再误判占位声明；检查 2 不动；reason 2 不再被短路。

### 已完成（2026-08-30/31）

- [x] **大纲 flag 真实语料验证（付费 ¥7.30）**：No-Go 建议（义务覆盖卡线），
  报告与归因底账落盘；计划书「207→239」勘误为 339。
- [x] **WS0 门禁重跑 ×2**（¥36.43 + ¥17.80）：A 轨首次完整通过（template_writer
  v2 修复 60 空正文行）；B 轨失败面收敛至 25 绑定 + 3 preservation（真实质量项）。
- [x] **三修复 + floor**：路由连坐窄门修（routing v7）/ 义务碎片过滤
  （conservation v6）/ 写入器列位（v2）/ extract floor 24576 + B 轨接线——
  均合 main 并 push。
- [x] **任务 C：队列投影只读审计工具**（12 测试，exit 0/2/3 契约）。

### 已完成（2026-08-29）

- [x] **队列收敛第 3 步：A/B 专家裁决双写切换**（`b52d8f1`，合并 `441fde8`）：
  `atom_expert`/`ai_review` 两 subject_kind 入统一事件链，CAS/fold/读者零变化，
  新增 test_review_queue_step3（20 例）。
- [x] **大纲接线 Phase 2b 第一片**（`bef6a86`，合并 `6fe5250`）：条款装配层按
  大纲报告重切边界，flag 门控默认关零漂移，新增 test_outline_authority_wiring
  （25 例）+ 回归组合 flag-on 3 钉。

## 架构债（评审编号 F1-F8；F1+F7 已完成 2026-07-06）

- [x] **F2|数据契约 + 版本戳校验**（2026-07-06 done：requirement_record.py 契约+血统戳+消费端校验）（1 天）
  - `requirement_record.py`：ai_requirements 行的字段契约（7 个消费者现全靠防御式 `.get()`；
    映射器 ai_req_id 缺失 bug 即此类），写入端校验。
  - 产物 JSON 头部盖 `producer_version` + 时间戳；消费端不匹配警告（"拿 v9 旧数据当新结果看"
    的另一半保险——manifest 已记账，产物本体也要可自证）。
- [x] **F8|xlsx 写入重试**（2026-07-06 done：xlsx_io.safe_save_workbook，4 写手接入，实际路径如实上报）（1 小时）：用户开着 Excel → 整链写崩（2026-07-05 实况）。统一
    "重试一次 → 加时间戳后缀另存 + 消息提示"。
- [x] **F4|LLM 调用收口**（2026-07-06 done：PURPOSE_MIN_TOKENS + apply_min_tokens，3 处收口）（半天）：max_tokens 下限已在 3 个模块各写一遍（6144/8192/16384）、
    trace 每个驱动手工接线。`llm_client.llm_call(purpose, ...)` 把 floors/trace/429/JSON 修复
    按用途焊死，新 LLM 环节自动继承纪律。
- [x] **F5|配置注册表**（2026-07-06 done：config.ENV_REGISTRY + 全仓扫描强制核对测试）（半天）：17 个 `RATOMIZER_*` env 散在各模块无文档。`config.py` 集中
    声明（名称/默认/说明/GUI 是否暴露）。
- [x] **F3|拆 ai_extract**（2026-07-06 done：extract_units + extract_guards，1319→1105 行，门面保旧名；自检环耦合深暂留主模块）（2 天，回归语料护航下做）：1319 行 8 种职责 →
    extract_units / extract_guards / extract_selfcheck / 主编排。维护性债非正确性债，不急。
- [x] **F6|双渲染器契约测试**（2026-07-06 done：共享夹具 annotation_contract.json，Python 锁 HTML/vitest 锁 Vue）（半天）：DocumentReview.vue 与 doc_annotation_export.py 同一
    语义两处实现（高亮 bug 修过两遍）。同一种子数据断言两边标记结构等价（jsdom 已在链里）。

## 组件增强（2026-07-06 评审，按落地价值排序）

- [x] **裁决样本库**（2026-07-06 done：adjudication_bank.py，env RATOMIZER_ADJUDICATION_BANK 指路，chain 尾自动收割，富化注入；待真实裁决积累生效）：专家 accepted/rejected 裁决 → 黄金 few-shot / 负例，按模块
    +词面检索注入抽取与富化 prompt（机制同模板知识注入）。跨项目积累，越用越准。
    依赖真实使用积攒裁决——越早上线越早开始攒。
- [x] **澄清答复回灌**（2026-07-06 done：必答 sheet 答复列 → 导入（CLI/GUI）→ 富化注入+有据基线扩展 → 报告消解）：clarification_questions.xlsx 评审会答复回来后无回灌
    入口。答复登记 → 按需求 id 回链 → 裁决/覆盖生效 → 免 LLM 重建交付物。
- [x] **Annex 引用解析**（2026-07-06 done：Annex A / A.1.4.6 形引用解析注入，prompt v11）：跨引用解析器只认数字条款号，不认 "Annex A"/"A.1.4.6"
    ——EN 16314 测试程序全在附录，这些引用现在是瞎的。正则扩展 + 测试。
- [x] **JSON schema 模式**（2026-07-06 done：探针证实 mimo 双模型支持 json_object；RATOMIZER_LLM_JSON_SCHEMA=1 启用，失败自动降级；默认关以兼容其它端点）：mimo 若支持 response_format=json_schema，每轮
    1-2 个 JSON 解析失败单元直接归零。
- [x] **术语定向注入**（2026-07-06 done：按单元检出已定义术语注入定义，漂移基线+指纹折入）：术语表现注入头 1800 字（后面截断）。改为按单元检出所用术语、只注入
    其定义。
- [x] **中英术语对照表**（2026-07-06 done：每文档一次 LLM 生成，哈希缓存 term_map.json，注入 doc_context）：每文档一次 LLM 生成术语译法对照（缓存），注入所有调用——交付物
    中文术语一致性（pressure absorption 等不再多种译法）。
- [x] **few-shot 换真样本**（2026-07-06 机制 done：样本库范例按模块+词面注入富化 prompt；范例质量随真实裁决积累提升）

## 战略项（顺序即建议执行序）

- [ ] **真实试点**：一名工程师 × 一份真实客户文档 × 端到端计时，对比纯人工基线 + 数返工量。
    验证的是商业假设（专家愿意裁决而非重写），优先级高于一切新功能。
- [ ] **金标召回率**：专家标注一份真实标准的全量需求（~50-100 条），每版本算真实查全/查准。
    "不漏、不编"从感觉变数字。回归语料（corpus_eval）已就位，缺金标。
- [ ] **数据治理裁定（一次会议）**：①llm_trace.jsonl 含客户文档全文，输出目录外发前须删；
    ②云端点（小米 MiMo）= 客户标准全文发第三方，公司保密政策是否允许需明文裁定
    （本地 Ollama 路径是现成降级方案）。
- [x] **交付物收敛（文档层）**（2026-07-06：ARCHITECTURE.md 明确成文.xlsx=B 轨主交付物 + 系统地图；UI 呈现精简留后续）：B 轨明确「软件需求列表-成文.xlsx」为唯一主交付物，其余降为中间产物，
    UI 相应呈现；给新人的 ARCHITECTURE.md。
- [ ] **Green Book 引入**（A 轨行为层第二本书）：散文语料无 class_id 键，需与蓝皮书不同的
    检索策略（术语倒排 or 受约束语义），先小样探针再立项。
- [ ] **CLI 契约补链**（2026-07-08 审计 4-A）：docs/cli-contract.md 承诺 `analyze` 但契约内
    无命令产其必需输入（ai_requirements.jsonl 需 ai-extract/chain，均不在 ratomizer CLI）；
    `assemble`（A 轨主交付物）也不在契约。补 `ratomizer chain` 进契约 or 明确 B 轨走
    desktop_tasks——需要产品拍板对接方案后再动契约文本。
- [ ] **词典重分词**（机翻 PDF 残留碎词的下一刀，2026-07-07 OCR 对比裁定的替代路线）：
    确定性词频/SymSpell 重分词 pass，只在去碎门控开启的文档上跑，数字/编码/单位豁免。
    目标：残留小写碎词（UNI 实测 72 处）与词间缺空格（"ofbytes"/"i sencoded"）修掉大半。
    **裁定背景**：OCR 重排被否——文字层字符 100% 准 vs OCR 引入 0/O、1/l 混淆
    （OBIS 错一位即严重缺陷），拿可修的排版问题换不可修的字符问题，方向反了；
    视觉模型只在将来表格结构不够用时按"视觉出结构、字符取文字层"评估。
- [ ] **M4c 扫描件 OCR**：等英文扫描件语料攒够（5-10 份）再立项。选型已定：Tesseract eng +
    框线 CV 切格；VLM 仅辅助且数字双引擎一致。
- [x] **模型 A/B**（2026-07-06 done，**裁决：pro 保持默认**——EN 16314 全量双跑：mimo-v2.5 覆盖率 69% 略高，但漏值 29 vs 18、重复对 8 vs 3、验收空话 6 vs 3，且并发限流下墙钟无优势（716s vs 741s，调用数反翻倍 460 vs 220）。"快 9 倍"仅单调用成立，吞吐被 429 锁死。数据：ab_arch/deep_test_result.json）

## 有据缓建（探针零收益，勿投机重启；重启前先在新语料重跑探针）

- 整章阅读架构（A/B 已裁决 2026-07-05：覆盖率 -6pt、参数表腰斩——lost in the middle；
  代码保留 `RATOMIZER_AI_UNIT_MODE=chapter` 实验开关，换更强模型一键重测）
- analyze 接蓝皮书（B 轨需求无接口类名，0/288）
- OBIS→class 连接提升蓝皮书覆盖（ABNT 行为正文 0 个 OBIS 形码）
- 类名归一化/别名（ABNT 未命中全是噪声或 Green Book 域引用，救回 0 条）
- Blue Book Part1 OBIS 节消费者（70 节已摄入，暂无消费方）
