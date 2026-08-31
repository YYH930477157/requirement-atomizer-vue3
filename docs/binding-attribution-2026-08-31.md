# 守恒绑定失配（binding_mismatches）归因诊断——SBD result3 语料

日期：2026-08-31 · 分支：`codex/binding-attribution` · 语料：`D:\Users\YunHeYang\Desktop\Canna\Canna-29\17388\result3`（**只读**，293 条 FRE）· 代码：当前 worktree（routing v7 / conservation v6 形态）

## 0. 方法与口径

- 诊断脚本（`out/tools/`，gitignored）把 result3 的 pipeline 产物复制进临时目录后按生产口径重放：`load_clauses` → `apply_unit_routing` → `conservation_report`（守恒永远现算，零 LLM 零付费，result3 零写入）。
- **`conservation_report` 的 binding_mismatches 有 `[:50]` 截断**——本诊断用镜像收集器 `tools/binding_attribution.py::collect_binding_findings`（同一批内部权威函数、同一判定顺序、不截断）取全量，并与 report 输出逐条（fre_id, reason）核对一致（parity 断言在运行器与单测两处钉住）。
- 归因走确定性信号（`build_signals` → `classify_signals`），信号包括：引句（剥表格标记 + `_squashed`）是否逐字落在声明条款基线文本内 / 落在基线内其他条款 / 只落在**被路由出基线**的条款；`source_section` 字段与引句真实落点条款的标签是否对得上；被覆盖条款义务句是否在声明条款文本内重复出现；叙述是否词面覆盖非 home 条款义务单元；stub 字面判定。
- SBD 语料 **section_id 大面积撞名**（同 id 多 chunk），条款身份一律用 `block_ids` 元组（`section_identity_key`），不用字符串 id。

重放规模：207 条款 → 路由后保留 102；binding findings 全量 **58 条**（report 截断口径 50）。reason 分布：`declared_section_has_no_local_obligation_coverage` 57、`narrative_covers_other_clauses_not_declared` 1——**reason 1 命中即 `continue`，同一 FRE 的 reason 2 检测被短路**，所以本语料几乎测不到 reason 2（见 §5 与 WS0 门禁样本的差异声明）。

## 1. 归因分布（58 条）

| 类别 | 数量 | 细分 |
|---|---|---|
| **b) 检查误报疑似**（内容属于声明条款，边建不起来） | **49** | 纯"引句在声明条款内但零边" 27；同上且叙述词面覆盖他款（混杂病灶，见 §3）21；他款义务句在声明条款内逐字重复 1 |
| **c) 条款切分/基线漂移**（FRE 如实继承） | **9** | 引句真实落点条款已被路由出守恒基线，声明块指向邻近条款 9 |
| **a) 叙述真借位**（LLM 输出问题） | **0** | 本语料无确定性信号可证的借位（见 §5 的诚实边界） |
| **d) stub/失败条目** | **0** | 293 条 FRE 无 stub 字面条目 |

## 2. b 类主体（49 条）：引句逐字在声明条款内，三种建边方法全部失败

**这是本语料的最大病灶，且是检查语义缺口而非 FRE 不诚实。** 48/49 的信号形态一致：`quote_in_home=true`（引句剥表格标记后逐字落在声明条款基线文本内）、`home_unit_in_quote=false`（引句里不含任何义务单元句）、叙述也不覆盖本款义务单元。

### 机制（最小复现已固化为 `tests/test_binding_attribution.py::CollectorMirrorTests`）

义务单元由 `_obligation_index` 生成 = **模态动词支配的句段**。清单/表格行/公式类内容没有模态动词，**永远成不了义务单元**。于是当条款内另有任一条模态句（`home_with_units` 非空）时，一条诚实抽取自清单内容的 FRE：

- lexical 边：叙述说的是清单内容，覆盖不了那条不相干的模态句；
- source_quote 边：引句是清单片段，不含任何模态单元句；
- cross_script 边：同语种不适用；

→ 三法全灭 → reason 1（"占位声明"）误伤。最小复现：

> 条款 = `"The meter shall record monthly energy usage totals. Display options:\n- Currency display\n- Tariff index display"`；FRE 引句 = `"- Currency display\n- Tariff index display"`（逐字）、objective 只讲显示选项 → reason 1 触发。

### 代表实例

1. `FRE-4de659ecf6be`（reason 1）——「6 TECHNICAL DATA REQUIREMENTS TABLE」，objective "The meter shall meet Protective class ӀӀ as specified."，引句 `Protective class ӀӀ`（表格行片段，逐字在声明块 BLK-000275）。表格行值无模态动词。
2. `FRE-3e036d5e8ebe`（reason 1）——「8.11.0 TOU and Block Inclining Step Tariffs」，objective "Provide Time-of-Use (TOU) tariff with three TOU rates for energy"，引句 `- Three TOU rates for energy: - Standard - Off-peak - On-peak…`（bullet 清单，逐字在本款）。
3. `FRE-1f6a4628653a`（reason 1）——同款 TOU 时段表（`H o u r D a y o f W e e k…` 字符拆散的表格），引句逐字在本款，无模态单元可锚。

### 修复方案

- **方案一（已落地，conservation v7）**：绑定检查（仅检查 3 的 reason 1）承认「引句逐字锚定声明条款」为本地锚——`quote_sq ⊆ home 基线文本` 时不判"占位声明"。义务覆盖（检查 2）分母与判定完全不动；reason 1 放行后 reason 2（叙述覆盖他款未声明）不再被短路。`FUNCTIONAL_CONSERVATION_MODEL_VERSION` v6→v7。
- **方案二（大动作，不建议本轮做）**：义务单元切分扩展到冒号/模态引导下的清单项（bullet 成单元）——影响检查 2 分母与全部守恒消费者，需独立立项。

## 3. b 类子集（21 条）：叙述同时词面覆盖非 home 条款——混杂病灶，需人工复核

这 21 条除上述形态外，叙述还词面覆盖（token ≥0.6）了至少一个非声明条款的义务单元。**逐条抽查证明该信号不足以证明借位**，实际混有三种情况：

1. **吞并 heading 切分病理（用户人工核查的「张冠李戴」真身）**：`FRE-80cb7a7c336b`（"Detect and prevent unauthorized physical or virtual access…"）与 `FRE-24ae7be2d078`（"Ensure secure and authenticated firmware updates."）——安全用例散文被切分器吞进「8.11.0 TOU and Block Inclining Step Tariffs」条款的块范围（BLK-000490..519），FRE 的引句逐字就在这些块里（`quote_in_home=true`）。**FRE 声明的是文本物理所在的块，如实**；标题张冠李戴是条款切分把 8.12 安全内容吞进 8.11.0 所致 → 本质是 **c 类**（吞并 heading，正是大纲权威 Phase 2b 立项的病灶），确定性信号无法与下述两种分开，故保守留在 b 并单列 detail。
2. **条款间重复文本**：`FRE-33bbbb0119cb`（「7.5 Display」显示清单）——非 home 命中是「1 METER TECHNICAL SPECIFICATION」里的 "shall display Currency which is user configurable"，显示需求在第 1 节与 7.5 重复出现。
3. **短单元弱词面重叠（虚假命中）**：`FRE-800604f3373a`（token 指示）命中 10.2.4 的 "may be manually entered into Meter B."——通用词重叠，非复述。

reason 2 的唯一一条（`FRE-bdccb0567f18`，TOU 支持）判 b：被覆盖条款（8.10 Net Metering）的义务句文本在声明条款（第 1 节）内逐字重复出现——重复文本使"覆盖他款"与"覆盖本款"不可区分。

## 4. c 类（9 条）：引句真实落点条款已离开守恒基线

9 条形态完全一致：引句逐字落在「13 Delivery period is two (2) months or better…」条款（**句子形 heading 的招标病理条款**，已被 tender 路由出守恒基线），而 `source_block_ids` 指向邻近的「18. Type Test Reports…」条款块（BLK-000070..80）；FRE 的 `source_section` 字段**正确**写着 13——即 LLM 标注对了条款，是抽取时的条款边界/块归属与当前切分不一致 + 路由把真实归属条款移出基线的叠加。代表实例：

1. `FRE-3af028bef7f3`——objective "Ensure the delivery period is clearly stated as two (2) months or better…"，引句逐字 = 13 条款正文。
2. `FRE-44ae9ecc540c`——incoterm C.I.P. Harare 声明，同款形态。
3. `FRE-2ab3bcd445ae`——制造商授权书（Tender No. ZETDC/INTER/05/2026），同款形态。

修复方向在 parse/outline/routing（大纲权威接线 + 句子形 heading 处理），不在本任务范围，如实记录。

## 5. a 类为 0 的诚实边界（与 WS0 门禁 25 条的关系）

- 本语料（result3 重放）57/58 是 reason 1，**reason 1 命中即短路 reason 2**——跨条款借位（reason 2）在本语料几乎测不到，不能据此断言"生产上没有借位"。
- WS0 门禁 v2 的 25 条 binding（ABNT 语料，以 `narrative_covers_other_clauses_not_declared` 为主）工作目录在另一台机器（`%TEMP%b-runner.9gqsr665`），本机拿不到，**那 25 条的归因本诊断未覆盖**。归因器已实现并测试了 reason 2 的判定路径（重复文本 → b；否则 → a），门禁工作目录可用时对 `tools/binding_attribution.py` 直接复用即可。
- 用户人工核查的两例「张冠李戴」（DLMS Suite 2 挂 8.11.0、设备安全挂 21.5）经机器信号核实：引句逐字在声明块内、安全散文被吞进 TOU 条款块范围——**是切分病理（c 类），不是 LLM 借位（a 类）**。

## 6. 修了什么 / 没修什么

| 项 | 决定 | 理由 |
|---|---|---|
| 抽取 prompt（`FUNCTIONAL_EXTRACT_PROMPT_VERSION`） | **不改** | 任务约定"(a) 类占主体才修 prompt"；本语料 a=0，机器可证的病灶在检查语义（b）与切分（c），prompt 强化无的放矢且要付费验证 |
| 绑定检查语义 | **方案一已落地（v7）** | reason 1 承认引句逐字锚定为本地锚；检查 2 不动；reason 2 不再被短路 |
| 条款切分/路由（c 类） | **不改** | 修复方向在 parse/outline/routing，另有线程在做大纲权威与路由 |
| 归因工具 `tools/binding_attribution.py` | **新增** | 只读诊断库：不截断镜像收集器 + 确定性信号归因；不触任何守恒语义与生产路径 |
| 测试 `tests/test_binding_attribution.py` | **新增 13 例** | 分类判定 9 例 + stub 判定 2 例 + 合成语料镜像一致性/最小复现 1 例 + 身份键 1 例 |

版本变更：**无**（未动任何行为版本/缓存指纹/prompt registry；新增文件均在生产链路之外）。
