# 需求分析剩余欠缺修改方案（2026-07-20）

> 来源：对 test2 运行结果（Slovak 电表招标 PDF，机器翻译版文本层）的实证分析。
> 证据目录：`C:\Users\YYHwudi\Downloads\test2\test2`（blocks.jsonl / consistency_report.json /
> clarification_report.json / document_pages/page-0002.png）。
> 每项均含验收标准；行为面变更的版本 bump 与 golden 纪律见文末「全局纪律」。

## 背景数据（本次 run 实测）

- 46 章、127 条 AI 需求；覆盖率 45.6%（169 requirement_like 块 / 77 覆盖 / 92 未覆盖）
- **176 个 requirement_like 块中 99 个（56%）含断词**（`i sobliged` / `i nsuch` / `a nd` / `beable`）
- 80/127 需求（63%）背「引用非逐字」嫌疑；35 条数字漂移；内部核对 158 条无法消解
- 页图证据（page-0002.png）：印刷文本完全正常 → 断词是 pdfplumber 文本层提取伪影
- 漏抽的实质内容：DLMS/COSEM over IP 双向通信（§2）、STN EN 62053-22 / TSK 型式证书 /
  decree no. 161/2019 / 初始检定周期 / EU 符合性声明（§2.1）

---

## 项 1：断词归一化（解析层，最高优先级）

### 根因

机器翻译版 PDF 的字体字距编码异常，pdfplumber 默认 `x_tolerance` 把字内间隙误判为空格
（`i sobliged` = "is obliged" 错位）、或词间间隙漏判（`beable` = "be able" 粘连）。
伪影沿「块文本 → 抽取引用 → 逐字校验 → 锚点质量门」逐级放大：
模型引用对不上原文 → 63% 需求背嫌疑、真 must 句过不了锚点门被静默丢弃。

### 方案（两层，确定性，先修源头再修残留）

**L1 解析源头（parsers/pdf_parser.py）——x_tolerance 自适应**

1. 页级试提取：对每页用候选 `x_tolerance` 序列（如 1.5 / 3 / 5 / 8）各提取一次。
2. 用确定性「断词密度」度量选最优值：
   `密度 = 命中 (\b[a-z]{1,2} [a-z]{2,}) 且首片段非英文常见词的块数 / 总文本块数`
   （常见词表复用 L2 的 wordlist；首片段为单词的不计，如 "I am"）。
3. 选密度最低且不比默认值差的 tolerance；决策与前后密度写入 `quality_report.json`
   （新字段 `text_hygiene: {x_tolerance, broken_ratio_before, broken_ratio_after}`），可审计。

**L2 归一化兜底（text_normalize.py）——wordlist 引导的残损修复**

对 L1 后仍命中的可疑点做保守修复，规则（全部确定性）：

- 合词：仅当两个片段按所有可能切分点重组后，能切出**全部落在 wordlist** 的形式才修
  （`i sobliged` → 切分点尝试 → "is"+"obliged" 均在表 → 接受；"a nd" → "and" 在表 → 接受）；
  无法全落在表的一律不动（宁漏勿错）。
- 分词：粘连串仅当存在唯一切分使全部片段在表（`beable` → "be able"）才修。
- wordlist：内置常用英文词表（约 5k 词，仓库自带不引第三方依赖）+ 域词表
  （requirement_kb 术语 + MODULE_VOCAB 英文别名）。
- 修复计数写 blocks 元数据（`text_repaired: true`），不伪装原文——导出层照旧展示修复后文本，
  批注「原文引用」注明已经断词修复。

### 验收标准

1. test2 全量重跑：requirement_like 块断词密度 56% → **<5%**（L1 为主，L2 兜底，指标进质量报告）。
2. 引用非逐字嫌疑 80 → **<20**；覆盖率 45.6% 显著提升（目标 >60%，与项 3 口径解耦后看 core）。
3. 单元测试（unittest.TestCase）：正例 `i sobliged→is obliged` / `a nd→and` / `beable→be able` /
   `i nthe→in the`；负例 `I am` / `a nice day` / `in such a way` 必须**零改动**。
4. ABNT golden 基线重生成 + 逐项漂移说明（见全局纪律），DOCX 路径行为不变（断词修复只作用于 PDF 解析产物）。

### 不做

- 不引 wordninja/symspell 等第三方库；不用 LLM 修文本（违反确定性纪律）。

---

## 项 2：合规/证书类需求的类型名分

### 根因

招标文档的 §2.1 混合三类内容：硬技术需求、可核查合规交付项（证书/法令/检定周期）、
伞条款。现有类型体系只有 functional 等，没有「合规交付项」，模型无类可归 → 成批丢弃，
连 DLMS/COSEM 双向通信这种硬需求也连带漏抽。

### 方案

1. **新类型 `compliance`**（合规交付项），与 functional 正交；module 仍走受控词表。
2. **确定性识别**（不靠 LLM 自觉）：后处理层按模式定型——句含
   `(certificate|decree|regulation|legislation|Act\s+\d|Coll\.|STN\s+EN|ISO|IEC|declaration of conformity)`
   + 情态词 → `type=compliance`，并抽结构化字段：
   `instrument`（引用文书原文，如 "Decree no. 161/2019 Coll."）、`deliverable`
   （certificate / declaration / verification_period / legislation_compliance）。
3. **伞条款名分**：仅含 "meet the conditions set forth in the standards … listed in this document"
   型无具体文书引用的，标 `compliance.umbrella=true`（低特异性），保留进清单但不进覆盖率
   core 分母（见项 3）。
4. **prompt 增补**：抽取 prompt 明确「合规/证书/检定条款必须抽取为 compliance，不得跳过」；
   防编造护栏不变——instrument 字段必须是原文子串。
5. 澄清联动：compliance 条目不默认进澄清；仅当 instrument 无法逐字锚定时进「内部核对」。

### 验收标准

1. test2 重跑：§2.1 出现 ≥5 条 compliance 条目（62053-22 证书、TSK/decree 161/2019、
   初始检定周期、EU 符合性声明、Slovak 计量立法），instrument 字段逐字可锚。
2. **回归探针（必须命中）**：存在锚定 `communicate bidirectionally … DLMS/COSEM standards based on IP`
   的需求（项 1 修复后该句应恢复可抽；若仍缺失，说明漏抽另有原因，需回报而不是放行）。
3. 伞条款带 `umbrella` 标记且不进 core 分母。
4. 类型贯穿全链：ai_requirements → functional_requirements → engineering_analysis →
   merged_spec 均保留 type 与 instrument 字段；schema 校验器同步（atomic_requirement_schema /
   requirement_record 行契约）。

---

## 项 3：覆盖率分母分层 + 就绪门按 core 判定

### 根因

coverage 分母把伞条款、合规交付项、（修复前的）断词碎块全算进 requirement_like，
tender 类文档结构性偏低 → READY 永远不可达，NEEDS WORK 成为常量而非信号。
附带既有中危：`clarification_report.py` 的 `effective_uncovered` 用全局已关闭块数做减法，
且 `handle_omission_action` 不校验目标块是否在候选集——计数可被粉饰（漏报方向）。

### 方案

1. `merged_consistency.coverage_denominator_blocks` 分层输出：
   - **core**：规范性措辞且非 umbrella、非已确认 non_requirement；
   - **compliance**：项 2 的合规交付项块（单独报覆盖率）；
   - **excluded**：已确认非需求（omission_actions triage）+ umbrella 标记块。
   排除必须依据确定性规则或专家 triage 记录，不允许 LLM 判定。
2. `consistency_report.json` 输出 `coverage: {core: {...}, compliance: {...}, excluded_count}`，
   保留旧字段兼容（`coverage_ratio` = core 口径，改名注释说明）。
3. 就绪门：`readiness_verdict` 的覆盖率条件改用 **core 覆盖率**；阻塞/普通/内部核对口径不变。
4. 修粉饰通道：`effective_uncovered` 只减「仍在本轮候选集内」的已关闭块；
   `handle_omission_action` 校验目标 block 当前确属候选（来源指纹匹配），否则 409。
5. 版本：consistency/报告口径变更 bump 对应 producer 版本（run_manifest 失效纪律）。

### 验收标准

1. test2 重跑：报告出现 core/compliance/excluded 三口径；verdict 按 core 判定。
2. 单测：构造已关闭块不属于候选集的场景，`effective_uncovered` 不少报；
   对非候选块 POST omission-action 返回 409。
3. 旧 out 目录（无分层字段）读取不崩、回退旧口径并注明 legacy。

---

## 项 4：次要项打包（独立小改动，可并行）

### 4a 模块「其它」13% 与跨文档沉淀

- 现象：test2 有 17/127 落入「其它」，多为法律/交付/质保条款；MODULE_VOCAB 无对应域。
- 方案：(i) review_insights 的 module_override 统计扩展为跨 out_dir 累积
  （用户级目录，如 `~/.ratomizer/insights/`，沿用锁+原子写纪律）；
  (ii) 模块下拉允许「新模块…」自由文本（前端校验非空 ≤20 字，作为 override 落审计，
  不进受控词表——词表变更仍走 review_insights 提示由人决定）。
- 验收：跨两个 out_dir 的 override 计数合并；自由文本模块落 ai_review_states 且
  requirements_analysis 按 override 生效；测试锁定。

### 4b failed_sections 可见性

- 现象：test2 有 1 章抽取失败，verdict 已计入但 UI 看不出是哪章。
- 方案：`ai_extract_quality.json` 已有 failed 计数处补 `failed_section_ids`；
  运行页与文档批注页对失败章节显示标记（不重跑可定位）。
- 验收：失败章节 id 出现在质量报告与 UI 提示；单测锁定。

### 4c 内部核对批量 acknowledge

- 现象：158 条内部核对逐条点不现实（断词修复后会自然消解大半，但存量目录需要）。
- 方案：内部核对 sheet 增加「全部确认无误」批量动作——要求逐条证据指纹仍匹配才落
  `verified_ok`（指纹失效的条目跳过并报告），actor+时间戳进审计；UI 一次操作，
  结果分类汇报（已确认 N / 指纹失效 M / 跳过 K）。
- 验收：批量操作只消解指纹匹配项；审计行完整；并发与锁纪律同单条路径；测试锁定。

---

## 实施顺序与规模

| 序 | 项 | 规模 | 说明 |
|---|---|---|---|
| 1 | 项 1 断词归一化 | M | 收益最大；改块文本→缓存/基线连锁（见下） |
| 2 | 项 3 分母分层+粉饰通道 | M | 与项 1 同批重跑验证 |
| 3 | 项 2 合规类型 | M-L | 依赖项 1 的文本质量（探针验收） |
| 4 | 项 4a/4b/4c | S | 独立，可并行 |

## 全局纪律（实现方必读）

1. **golden 基线**：项 1 改变 blocks 文本 → atomize 产物必漂移。合并后按 CLAUDE.md 流程：
   三个种子 `--kb` + domain-pack 重生成 `out/abnt_nbr_16968_atomizer_v5/`，逐项写明漂移理由。
2. **版本 bump**：文本归一化（解析行为）、覆盖率口径（consistency）、类型 schema、
   翻译/抽取缓存指纹任一变更，同步 bump 对应 `*_VERSION` 并在 commit message 声明
   （见 CLAUDE.md「提交信息准则」三段式：原因/现象/解决方法）。
3. **缓存**：块文本变化自动失效 section 指纹缓存（设计如此）；无需手动清，但
   ai_requirements.meta/partial 代际会重绑定，属预期。
4. **测试纪律**：unittest.TestCase（禁模块级 def test_*）；两个套件全绿才可推送：
   `python -m unittest discover -s tests`、`cd ui && npm test`。
5. **宁漏勿错**：所有文本修复/排除/类型判定要么确定性可复核，要么留人工 triage 痕迹；
   任何「看起来像」的自动判定都不允许静默生效。
