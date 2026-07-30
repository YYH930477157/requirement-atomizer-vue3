# Agent 化评测集扩充实施规格：≥40 案例 + 三类自动判定（agent-eval-v2）

状态：**已冻结**（2026-07-22 审核人确认四个冻结点 + 2.2 全文缺席原则；冻结时两处
实施前修正：①must_ask 第二档的 detector 派发需要显式字段，case schema 新增**可选**
字段 `expected.detector`（按类别收窄枚举，向后兼容，README 规则 4 声明范围内）；
②"已核对基线"口径细化为：基线字段覆盖全部自动判定案例，逐案标注
reviewed/unreviewed，人工登记 curation 后自然全 reviewed，runner 永不自称核对状态。
实施中第三处修正：hallucination 判定按生产护栏族派发（漂移 ∪ 外标准号 ∪ 对立限定词），
因 v1 案例横跨三族——见 1.3；配套 `foreign_standard_refs`/`opposed_qualifiers` 一并
提公开，`clarification_report` 新增公开访问器 `suspicion_policy`）
日期：2026-07-22
前置：Phase 0（main `4161f18`，`docs/agent-phase0-spec.md`）；总纲 `docs/agent-rollout-plan.md`
"评测集随阶段扩充"条；待办 `docs/agent-next-steps.md` #2（Phase 2 前置）

## 0. 定位

Phase 0 交付的评测集 20 条中 grouping / must_ask / hallucination 三类只做 schema
校验与计数（`agent_eval.py` 明列 `schema_only_categories`）。本规格把这三类升级为
**确定性自动判定（零 LLM）**，并把案例从 20 扩到 ≥40，来源为 test2/test3 真实
suspicion 记录（脱敏改写）。

本规格不改任何生产行为：只给评测运行器接**现有确定性层**作为被测系统（SUT），
并扩充案例。判定口径即下文第 1 节，是本规格的核心冻结项。

## 1. 判定逻辑口径（冻结项）

三类各自的被测系统（SUT）与 pass 谓词。所有 SUT 均为现有公开/半公开确定性函数，
可在孤立短文本上运行，不依赖管线产物目录。

### 1.1 grouping（软件研发功能分组）

- SUT：`functional_catalog.build_function_catalog(rows, chat=None)` 的零 LLM 聚类路径
  （`_catalog_groups` / `_legacy_family`）。
- pass 谓词：
  - 正对：共享 `expected.group_key` 的案例对喂入后**合并为一组**
    （同一 functional group，`merge_method != "singleton"`）；
  - 负对：数据集中所有**跨 group_key** 的案例对自动两两生成，**不得合并**。
    负对无需新案例字段，由运行器从数据集派生。
- 案例格式沿用 `group_key`（schema 不变）；判定"同组/不同组"，不判分组命名。

### 1.2 must_ask（缺失参数必须提问）

语义上的"信息是否充分"无法零 LLM 全量判定（这正是 Phase 2 LLM 判定的领地）。
本规格把自动判定对象冻结为**确定性护栏/策略层**，分三档：

1. **forbidden 缺省值拦截**：案例 `expected.forbidden`（模型易脑补的缺省值，如
   "15-minute interval"）不得出现在该案例输入经零 LLM 派生链产出的任何字段
   （分类、护栏、功能合成标题/描述等确定性输出）。出现即 fail——这是"不得推断"
   的确定性可判部分。
2. **detector 覆盖族**：案例在 `expected.detector` 显式声明陷阱族
   （`vague_acceptance` → `extract_guards.vague_acceptance`；
   `values_left_behind` → `extract_guards.values_left_behind`），对应 detector
   必须触发，且其 suspicion 经 `clarification_report._SUSPICION_POLICIES` 映射为
   问客户或 blocking。声明了而未触发即 fail（防止"该响没响"被静默归入第三档）。
   输入适配：`vague_acceptance` 以 `input.text` 为验收文本；
   `values_left_behind` 以 `input.text` 为交付文本、`input.context` 为原文基线。
3. **语义型陷阱**：未声明 `expected.detector` 的案例（如纯语义缺参），如实标记
   `judge_note: "manual"`，**不计入自动通过率分母**——不伪造自动化覆盖。
   （第一档 forbidden 拦截对全部 must_ask 案例仍强制执行。）

配套改动：`_vague_acceptance` / `_values_left_behind` 两个下划线私有函数提为
公开 API（纯改名 + 调用点跟随，零行为变化，靠现有测试锁死）；eval 运行器不得
依赖私有名。

### 1.3 hallucination（已知幻觉/漂移的反面案例）

- SUT：按 `expected.detector` 声明的**生产护栏族**判定（v1 既有案例即横跨三族，
  把案例改窄去迁就单一漂移护栏会削弱数据集，故按族派发）：
  - 默认（无 detector 或 `code_drift`/`int_drift`）：`ai_extract.code_drift`（硬）∪
    `ai_extract.int_drift`（软），baseline = `input.text`，candidate = `input.context`
    中 "Rejected candidate:"/"Rejected merge:" 前缀后的被拒候选；
  - `foreign_standard_refs`：`extract_guards.foreign_standard_refs`（标准号张冠李戴，
    按号根比对）；
  - `opposed_qualifiers`：`functional_catalog.opposed_qualifiers`（对立限定词合并拦截，
    适配器：原文行 vs 合并候选行）。
- pass 谓词：`expected.forbidden` 的**每个** token 必须被对应护栏捕获。漂移族的
  token 匹配按**原子口径**（token 提取 编码 ∪ 整数，与漂移输出同口径——"1 l/h"
  匹配漂移原子 "1"）；外标准号族按字符串互含；对立限定词族以护栏返回 True（反对
  合并）为捕获。全部捕获 = pass；任一漏网 = fail（护栏盲区，如实记为改进靶子）。

## 2. 案例扩充（20 → ≥40）

### 2.1 数量目标

| 类别 | 现状 | 目标 | 增量来源 |
|---|---|---|---|
| classify | 8 | ≥12 | test2/test3 真实行的软/硬/合规/非需求归属样例 |
| grouping | 4 | ≥8 | test2/test3 `functional_requirements.json` 真实功能簇 |
| must_ask | 4 | ≥10 | 原文数值未带全（test2 4 / test3 12）、验收不可测（5/4）、语义缺参陷阱 |
| hallucination | 4 | ≥10 | 数字漂移（34/8）、数值配对待核（4/8）、二遍复核翻车族（归属/方向/主体/数量词，test2 6 / test3 7） |

合计 ≥40。test2/test3 suspicion 实测分布（2026-07-22 统计）：test2 共 127 行、
109 行带 suspicion；test3 共 110 行、73 行带 suspicion，各族数量如上表括号，
挖掘余量充足。

### 2.2 纪律（沿用 Phase 0，违反即打回）

- 客户词面不进仓：新案例一律 `origin: "anonymized_rewrite"`，数值/文号可保留作
  证据但措辞脱敏改写；
- 标准答案人工书写，模型生成答案未经人工核对不得入库；
- 数值、标准号、forbidden token 一律精确匹配；
- **must_ask 专项准入（全文缺席原则）**：金标准"信息不足"必须对**整份文档**成立——
  挖掘时对参数名/数值做全文检索，答案在文档任何位置（含跨章节引用可注入的条款）
  已有的案例不得入 must_ask（可改判 grouping 或引用类）；`input.context` 必须记录
  全文缺席声明（v1 "adjacent blocks" 局部口径对新案例不再够用），人工核对时复核
  该声明属实；
- `source.doc_ref` 沿用 manifest `source_registry` 已有代号体系，新代号须同步登记
  registry（指向仓库内证据，不指向客户文件）。

## 3. 人工核对与 manifest 登记

- runner 永不改写 `curation`（现有回归测试已锁，沿用）；
- 新案例逐条经审核人核对 `expected` 与脱敏输入一致后，由**人工**把 case_id 追加进
  `curation.reviewed_case_ids` 并更新 `reviewed_at`/`statement`——登记是人工动作；
- 未核对案例可先入目录参与自动判定；基线字段覆盖全部自动判定案例，报告逐案标注
  reviewed/unreviewed 并单列 unreviewed 计数——人工登记 curation 后全部转为
  reviewed，基线自然收敛，runner 永不自称核对状态。

## 4. 版本与基线口径

- `EVAL_RUNNER_VERSION`：`agent-eval-v1` → **`agent-eval-v2`**（判定逻辑变更）；
- `AGENT_POLICY_VERSION` **不动**（评测判定不影响管线决策与任何缓存指纹，
  铁律 2 不触发）；`EXTRACT_GUARDS_VERSION` 等护栏版本不动（只调用，不改行为）；
- manifest 基线字段：`classification_baseline` / `grouping_baseline` /
  `must_ask_baseline` / `hallucination_baseline` 是仓库冻结比较值。2026-07-30
  修订：runner 默认只读，实时结果允许优于冻结基线而不改写 golden；仅维护者显式传入
  `--update-baseline` 时原子刷新四个字段，且不得改写 `curation`。字段结构为
  evaluated/passed/failed/pass_rate/failed_case_ids；must_ask 分母只含自动判定案例，
  manual 案例单列计数；
- 历史基线 0.625（v1，20 条）在合并里程碑中留痕后由新基线接替；合并门
  "评测基线不下降"自本规格合入起对照**新基线**解释。

## 5. 明确不做（范围护栏）

- 不接 LLM 判定、不改任何生产模块行为（护栏/分组/澄清/分类规则均只调用不修改；
  唯一例外是四个私有护栏函数提公开——`vague_acceptance`、`values_left_behind`、
  `foreign_standard_refs`、`opposed_qualifiers`，纯改名——及 `clarification_report`
  新增只读公开访问器 `suspicion_policy`）；
- case schema 除新增可选字段 `expected.detector` 外不动（向后兼容，README 规则 4
  已声明）；不新建第二套评测目录；
- 不动 UI、不动 `gui/`（冻结）；不动 golden 基线与 `out/` 产物。

## 6. 测试要求（`unittest.TestCase`，根目录 discover）

- 三个判定器各自的合成正/反例单测（含 grouping 负对自动派生、must_ask 三档分流、
  hallucination forbidden 部分漏网）；
- 私有 detector 提公开：改名零行为锁测试（现有护栏测试零改动通过）；
- 案例门槛测试更新为 ≥40 及新的各类下限；全部案例过 schema；
- runner 默认运行后 manifest 字节不变；显式 `--update-baseline` 仍不得改
  `curation`；`unreviewed` 标注不进已核对基线；
- 全量 `python -m unittest discover -s tests` 绿；行为面零变更，golden 6/6 不应
  漂移（在主检出验收）。

## 7. 验收清单（审核人逐项核对）

1. `python -m unittest discover -s tests` 全绿（含新增判定器测试）；
2. `python agent_eval.py --eval-dir golden_sets/agent_eval_v1` 输出四类的
   evaluated/passed/pass_rate 与 failed_case_ids，且 manifest 逐字节不变；需要维护
   新基线时只在可写副本上显式传 `--update-baseline`，刷新后四个基线字段与实测一致，
   `curation` 逐字节不变；
3. 案例 ≥40 且各类达 2.1 下限；抽 ≥5 条新案例人工核对 `expected` 与来源证据；
4. 报告中 must_ask 的 manual 档案例如实标出、不进自动分母；
5. diff 范围：`agent_eval.py`、`extract_guards.py`（仅提公开）、
   `functional_catalog.py`（仅提公开）、`clarification_report.py`（仅新增
   `suspicion_policy` 公开访问器）、`schemas/agent_eval_case.schema.json`
   （仅 `expected.detector` 可选字段）、`tests/test_agent_eval*.py`（可新增文件）、
   `golden_sets/agent_eval_v1/`（cases + README + manifest 基线字段）、本规格文档。
   其余一律打回。

## 8. 审核方式

实施者交付 diff + 本清单自检结果；审核人跑第 1、2 条命令复核，抽查第 3 条，
逐条核对 4–5。任何一条不过即整体打回，不部分接收。
