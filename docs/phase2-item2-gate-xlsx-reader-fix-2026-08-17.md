# Phase2 交接单第 2 项——门禁 XLSX 读取器修复报告（2026-08-17b）

**任务来源**：`docs/phase2-handoff-2026-08-17.md` 第 2 项「门禁 XLSX 读取器别名补齐
（零付费，小改动）」。
**目标**：修好 `tools/ab_runner.py::_read_final_xlsx_rows` 在公司模板 V2.3.12 上的
正文列识别失败，使 WS0 真值门禁可以复评 A 轨（当次门禁 A 轨链路本身跑通：343 节 →
996 原子 → 1847 行成文，仅读取器 fail-closed FAIL）。
**成本**：零付费（纯本地模板采样 + 确定性代码 + 单测，无 LLM 调用）。

---

## 1. 问题定性（本地模板采样证据）

对 `C:/Users/YYHwudi/Desktop/Canna-29/电表软件标准化需求列表-V2.3.12 - 2026-4-14..xlsx`
逐 sheet 采样后，门禁报告的 10 个 `missing_body_sheets` 分为三类，**交接单原设想的
"把表头加进 `XLSX_COLUMN_ALIASES["body"]`"不可行**：

| 类别 | Sheet | 实际形态 | 纯别名方案的后果 |
|---|---|---|---|
| 需求 sheet（拆分列） | 计量需求 | 表头 `关闭/序号/子模块/描述/1P2W_SP/3P4W_DC/3P4W_LVCT/说明…`——「需求」列被电表类型列拆分；`template_writer` 按固定列位 `_COL_ANSWER=6` 写入 | 无表头可加；加类型名当别名会读到错误列 |
| 非需求 sheet（9 个） | 计量列表、费率列表、显示列表、曲线列表、事件列表、需求模版Release notes、原始需求对应表、需求变更管理、Dataflash容量计算 | OBIS 清单/费率结构/事件码表/模板变更记录等，管线**从不写入** | 无正文列头可加；硬加会把清单 √、Release notes 等全部当成需求正文，毁掉 precision |
| 模板自带留空行 | 全部 19+1 个需求 sheet | 大量「需求列留空」样例行（如计量需求"基本电压可配值-V"行，说明列写着"没有需求就不填"） | 别名修完后门禁会接着栽在 `empty_body_rows` FAIL（当次 1185 个空正文行大半是模板内容） |

## 2. 修复设计（两层机制）

读取器使用它本来就拿到手的 `--template` 作为校准权威；表头别名机制保留且优先级不变。

### 2.1 写入器列契约兜底（修计量需求）

- `template_writer.py` 新增公开常量 `REQUIREMENT_SHEET_SIGNATURE = ("序号", "子模块")`
  与 `WRITER_COLUMN_CONTRACT = {module: 3, body: 6, notes: 7, section: 9}`——
  写入与读取共用同一列位权威（V2.3.x 实测 19 个需求 sheet 一致）。
- `ab_runner._writer_contract_columns(header_row)`：表头别名**优先**；仅当签名命中、
  body 别名不命中、且表头列数足够（≥6）时，按契约列位定位。
  **读的正是写入器写的列位**——计量需求 sheet 的正文（col6）与章节（col9）都能读回；
  纯别名方案即使读到 col6 也会丢 col9 的章节（写入器因该 sheet 表头右移，实际把
  section 落在 col9），拉低匹配分。
- 诊断：走契约兜底的 sheet 记入报告 `contract_body_sheets`。

### 2.2 模板校准（修 annex sheet 与样例行）

- `ab_runner._load_template_extents(template_path)`：sheet 名 → 模板内最后一个非空
  行号（与 `template_writer._next_seq` 同一"末个非空行"判定——成文器只在该行之后
  追加）。模板缺席/不可读 → None（退回旧语义；生产路径模板坏时链路本身先失败，
  不会静默放行）。
- `_read_final_xlsx_rows(xlsx_path, template_extents=...)`：行界**之内** = 模板自带
  内容（annex 清单 sheet、需求 sheet 样例行、留空行），剥离进
  `template_rows_skipped` / `template_only_sheets`——不计 produced、不触发缺列/空正文
  FAIL；行界**之后** = 管线产物，空正文/缺列/不可读单元格仍 fail-closed，annex sheet
  出现行界外内容同样判缺列。
- **produced 口径 = 真实追加行**：模块 docstring 里"A/B 必须使用空模板"的警告作废
  （门禁用模板自校准），precision/recall/重复率/拆分率全部只衡量管线产物。
- 报告 schema：`ab-runner-report/v2 → v3`（新增 `contract_body_sheets` /
  `template_only_sheets` / `template_rows_skipped` 诊断键，produced 行口径变更）。

### 2.3 兼容性

- `template_extents` 为 keyword-only 参数，默认 None：不传模板的旧调用
  （`tools/m0_baseline.py`、全部既有测试）保持字节级旧语义。
- `tools/truth_from_review.py` 只消费别名表与正则（未改动的 API），不受影响。
- `template_writer.py` 的 diff 为纯新增常量，对链路行为惰性。

## 3. 变更清单

| 文件 | 变更 |
|---|---|
| `template_writer.py` | +11 行：`REQUIREMENT_SHEET_SIGNATURE` / `WRITER_COLUMN_CONTRACT` 公开常量（纯新增，零行为变化） |
| `tools/ab_runner.py` | 读取器重写（契约兜底 + 模板校准 + 新诊断键）；`_load_template_extents` / `_writer_contract_columns` 新函数；`run_ab_for_document` 三处读取接线；模块与函数 docstring；`REPORT_SCHEMA` v3 |
| `tests/test_ab_runner.py` | +181 行：`METERING_SPLIT_HEADERS` / `V2_REQUIREMENT_HEADERS` / `_v2_template` / `_final_appended` 夹具 + 4 个新测试类 8 个测试 |
| `CLAUDE.md` | 新增「重大更新（2026-08-17b）」条目 |
| `AGENTS.md` | WS0 段落补读取器修复事实（reader follow-up） |
| `docs/phase2-handoff-2026-08-17.md` | 第 2 项标注完成状态与实查定性 |

## 4. 验证结果

| 验证 | 结果 |
|---|---|
| TDD 纪律 | 先写 8 个新测试确认 RED（2 failures + 6 errors，全部因新 API/行为缺失），最小实现后 GREEN |
| `tests.test_ab_runner` | 58/58 通过（50 既有 + 8 新增） |
| `tests.test_template_writer` | 10/10 通过 |
| 全量后端（`python -m unittest discover -s tests`，含历史样本 env） | **3946 项，仅 4 失败** = 交接单已记载的既有 golden 漂移（`test_golden_regression` 四项，stash 双向验证过与近期工作无关；3938 + 8 新增 = 3946，0 新增失败） |
| 真实 V2.3.12 模板 E2E（零付费） | 真实 `append_analysis_to_template` 追加 2 条需求（计量需求=拆分表头 sheet + 时钟需求=普通 sheet）→ 读取器 `ok=true`、`missing_body=[]`（修复前 10 个 sheet 全中）、`row_count=2`（恰好 = 追加行）、计量需求 body/section `6.12` 正确读回、`contract_body_sheets=['计量需求']`、2046 行模板内容剥离、26 个纯模板 sheet 列入 `template_only_sheets`、空正文/不可读单元格 = 0 |

## 5. 对门禁判定的影响与后续

- **A 轨**：读取器缺口消除后，A 轨成文可被正常评估；produced 口径变为真实追加行
  （此前 1847 行含全部模板样例行），precision/recall 与 `max_final_row_growth_ratio`
  首次具备真实区分力。
- **B 轨**：不受影响——当次 FAIL 根因是 deepseek-v4-flash 文档级直抽守恒失败
  （duplicates=6），即交接单第 1 项（functional-extract 接 unit/clause_family 级
  上下文，方案 §17），**未修，重跑预期 B 轨仍 FAIL**。
- **下一步（交接单第 3 项）**：key 充值后一条命令重跑门禁：

```bash
PYTHONPATH=. RATOMIZER_LLM_API_KEY=<key> python tools/ab_runner.py \
  --parsed-dir out/abnt_nbr_16968 --template "…V2.3.12….xlsx" \
  --route openai_compatible --keep-dirs \
  --truth golden_sets/ws0_human_v1/truth.jsonl \
  --thresholds golden_sets/ws0_human_v1/thresholds.json --out out/ab-gate-report.json
```

（建议带 `--keep-dirs` 保留 A/B 工作目录，便于再次人工复核成文 XLSX。）
