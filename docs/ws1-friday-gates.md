# WS1 周五门禁检查单（第 1-8 周）

> 实施方案 v1.1 §3.2 排期表把 WS1 的准出门禁拆成周级检查项，每周五在最新代码上完整执行并留档。
> 本文件把第 1-8 周全部周五门禁命令汇成**可逐条执行的检查单**：每条给出命令、预期产出与红灯处置。
> 任一门禁红灯 = 按 §1.2.1 纪律**停线回退**到上一合法运行态（旧路径始终是合法运行态），不带病推进。
>
> 统一测试入口：`python -m unittest discover -s tests`（**不是 pytest**；pytest 未装，模块级 `def test_*` 会被静默跳过）。
> 退出码对齐 `docs/cli-contract.md`：0 成功 / 2 输入或门禁不达标 / 3 校验错误 / 4 环境错误。
> 金标 A/B 实跑依赖机器本地语料资产与冻结 `out/` 基线（见 `AGENTS.md` 的机器本地路径说明）；隔离 worktree 无这些资产时，golden 五项与机器资产相关项会如实 skip，不伪造。

---

## 前置：每个周五先跑这一条（全量回归底座）

| # | 命令 | 预期产出 | 红灯处置 |
|---|---|---|---|
| G0 | `python -m unittest discover -s tests` | 全绿，末行 `OK (skipped=N)`。隔离 worktree 中 N≈26（5 golden + PySide6 GUI + 历史样本 env 三类环境性 skip，与 `AGENTS.md` 口径一致）。主检出设 `RATOMIZER_HISTORICAL_SAMPLE` 后 skip 收窄。 | 任一 `FAIL`/`ERROR`：定位到失败用例，先判定是代码回归还是环境抖动；代码回归即停线回退到本周改动前的提交，红灯项重做。 |

---

## 第 1-2 周：schema 定稿 + 几何校验器先行（TDD）

交付物：`schemas/table_structure_hypothesis.schema.json`、`table_geometry_validator.py` 及单测。

| # | 命令 | 预期产出 | 红灯处置 |
|---|---|---|---|
| W1-2.a | `python -m unittest tests.test_table_geometry_validator` | 校验器单测全绿（三类规则：坐标一致性、合并锚点守恒、受保护编码零漂移；三态 issued/partial_conflict/invalidated）。 | 校验器是双轨制安全底座——单测红即停线，红-绿循环未收敛前不进入第 3 周。 |
| W1-2.b | `python -m unittest discover -s tests` | 全绿（含校验器单测）。 | 见 G0。 |
| W1-2.c | `git diff --name-only -- table_structure.py parsers/ atomize.py` | **空**——解析主线零改动（WS0/WS1 并行不冲突的机器可核查形式）。 | 若有改动：本周触碰了不该碰的解析主线，回退该改动。 |

---

## 第 3-5 周：结构理解器 + 表格族模板库 + 双轨入口 + 面板降级出口

交付物：`llm_table_understanding.py`、`table_family_templates.py` + `domain_packs/dlms_cosem/table_family_templates.yaml`、`table_structure.analyze_table_dual_track` 入口、`table_review_state` 几何冲突通道。

| # | 命令 | 预期产出 | 红灯处置 |
|---|---|---|---|
| W3-5.a | `python -m unittest tests.test_table_family_templates tests.test_table_structure_dual_track tests.test_table_review_state` | 模板库载入/匹配、双轨入口（开关默认关→旧路径字节不变；开关开+签发→假设派生结构；开关开+校验失败→确定性兜底+冲突集）、面板冲突注册往返全绿。 | 双轨入口任何一支路失败：确认 `RATOMIZER_TABLE_DUAL_TRACK` 默认仍是关；签发/兜底/冲突三支路各有独立探针。 |
| W3-5.b | `python -c "import os; os.environ.pop('RATOMIZER_TABLE_DUAL_TRACK',None); import table_structure; print(table_structure.dual_track_enabled())"` | `False`（开关默认关，atomize 缓存指纹与 golden 基线不动）。 | 若为 True：默认被翻转，回退——默认关是"改造期任何时刻流水线都是合法运行态"的前提。 |
| W3-5.c | `python -m unittest discover -s tests` | 全绿，且既有 4.1 万行测试资产零回归。 | 见 G0。 |

---

## 第 6-7 周：PDF 现代解析器主路径 + Excel 语义区域检测

交付物：PDF 现代解析器适配层 + `pdf_parser` 降级开关（provenance 标注解析器来源）、`xlsx_parser` 语义区域检测。

| # | 命令 | 预期产出 | 红灯处置 |
|---|---|---|---|
| W6-7.a | `python -m unittest tests.test_pdf_modern_adapter tests.test_xlsx_region_detect` | PDF 适配层与降级开关、xlsx 区域检测（区域不重叠、合并锚点守恒、失败按行区间降级）全绿。 | 适配层选型第一标准是"输出结构能否对齐双轨制输入契约"，量化以金标门禁为准——单测红即停线。 |
| W6-7.b | `RATOMIZER_TABLE_DUAL_TRACK=0 python tools/parse_ab_gate.py --corpus <fixtures> --report out/ws1/ab_wk67.json`（无真实语料时用夹具） | 决策 `pass`；`corpus_eval.status=pending`（真实语料待金标）；`protected_encoding_drift_total=0`；每文档新旧路径结构增量可读。 | `protected_encoding_drift_total>0`：受保护编码漂移，硬拦——回退降级开关切回手写解析路径。 |
| W6-7.c | 降级开关演练：`RATOMIZER_PDF_MODERN_PARSER=1` 跑一次后切回 `=0` | 切回后 provenance 字段（`parser_provenance`）齐备、产物与旧手写 pdfplumber 路径一致。 | 切不回或 provenance 缺失：回退开关实现，主路径暂缓切换。 |
| W6-7.d | `python -m unittest discover -s tests` | 全绿。 | 见 G0。 |

> 注：PDF 现代解析器开关为 `RATOMIZER_PDF_MODERN_PARSER`（`config.py` ENV_REGISTRY，默认 0=旧手写路径）；适配层 unavailable 时诚实回退手写 pdfplumber 路径并在产出标 `parser_provenance`，缓存指纹与 golden 基线字节不变。

> 注：PDF 降级开关的实际环境变量名以 `config.py` 的 `ENV_REGISTRY` 为准（"code wins"）；本检查单给的是契约形态。

---

## 第 8 周：A/B 门禁裁决 + 角色语义抽审 + 一键回退演练

交付物：`tools/parse_ab_gate.py`（新旧路径 A/B 门禁）、`tools/table_role_audit.py`（角色语义抽审）、A/B 裁决记录存档、切换配置、回退演练记录。

### 8.1 corpus_eval 三指标逐文档不劣化

| # | 命令 | 预期产出 | 红灯处置 |
|---|---|---|---|
| W8.1.a | `python -m corpus_eval --out <OLD_OUT> --out <NEW_OUT> --label old --label new` | 三指标（碎片率=`self_check_ratio`、漏值=`values_left_behind`、覆盖率=`coverage_pct`）并排表。 | —— |
| W8.1.b | `python tools/parse_ab_gate.py --corpus <corpus> --corpus-eval-roots <OLD_OUT> <NEW_OUT> --report out/ws1/ab_wk8.json` | 决策 `pass`（exit 0）：`corpus_eval.degraded_metrics=[]`；`protected_encoding_drift_total=0`；逐文档对比报告生成。 | exit 2：某指标劣化或受保护编码漂移——**该文档类型不切换主路径**，回到对应表格族模板与校验参数调试。 |

### 8.2 受保护编码零漂移（HARD，独立于三指标）

| # | 命令 | 预期产出 | 红灯处置 |
|---|---|---|---|
| W8.2.a | 见 W8.1.b 报告 `red_lights.protected_encoding_drift` | `false`，`drift_tables=[]`。 | `true`：OBIS/事件号/hex 任一漂移即阻断切换（"错一位是严重缺陷"），硬拦停线。 |

### 8.3 角色语义抽审 ≥95%（按表格族，禁止跨族平均）

```powershell
# 1) 抽样：仅签发成功的假设，按 文档×表格族 分层
python tools/table_role_audit.py sample `
  --corpus golden_sets/<corpus_id> `
  --per-family 10 --min-cells 300 --seed <日期种子> `
  --worksheet out/role_audit/week-8.jsonl

# 2) 专家对照批注 HTML 逐格裁定（不裁定几何）后录入
python tools/table_role_audit.py record `
  --worksheet out/role_audit/week-8.jsonl `
  --expert-input out/role_audit/week-8.expert.jsonl `
  --verdicts out/role_audit/week-8.verdicts.jsonl

# 3) 裁决：任一族 < 阈值 → exit 2
python tools/table_role_audit.py evaluate `
  --worksheet out/role_audit/week-8.jsonl `
  --verdicts out/role_audit/week-8.verdicts.jsonl `
  --threshold 0.95 --report out/role_audit/week-8.report.json
```

| # | 预期产出 | 红灯处置 |
|---|---|---|
| W8.3.a | `evaluate` exit 0：每族 `cell_accuracy ≥ 0.95` 且 `meets_threshold=true`；`failing_families=[]`。报告按族分别列准确率（无跨族合并平均）。 | exit 2：某族准确率 < 阈值——**该族切换阻断**，回模板库/校验参数调试；不准用他族高准确率掩盖。exit 3：裁定未填/role 枚举非法——补裁定。 |
| W8.3.b | 工作单/裁定/报告三件存档（`week-8.jsonl` / `.verdicts.jsonl` / `.report.json` + `.meta.json`），作为"质量闸门在抽审与 A/B 指标、不在校验器"的可核查证据。 | 三件不全：门禁未结清。 |

### 8.4 一键回退演练（小时级配置动作）

| # | 命令 | 预期产出 | 红灯处置 |
|---|---|---|---|
| W8.4.a | 切旧：`RATOMIZER_TABLE_DUAL_TRACK=0`（默认）→ 跑 `python -m unittest discover -s tests` | 全绿；解析主线与 4.1 万行测试资产全量在位。 | 切不回：开关实现有误，停线。 |
| W8.4.b | 切回：`RATOMIZER_TABLE_DUAL_TRACK=1` → 跑全量回归 → 切回 0 | 切旧→回归→切回全程通过，证明回退是配置动作而非代码恢复。 | 回退演练未通过：该文档类型保持旧路径不切换。 |

---

## WS1 准出门禁汇总（四条可核查验收，方案 §3.3.1）

1. **复杂表格人工指派率下降**：复核面板从"全部表格逐格指派"收窄为"仅处理校验失败的少数表格"（面板入件量前后对比为证；裁定回填格式与自动签发同构、下游无感知）。
2. **解析指标不劣化**：W8.1 + W8.2 通过（corpus_eval 三指标逐项不低于旧路径 + 受保护编码零漂移）；任一劣化的文档类型保持旧路径。
3. **角色语义抽审达标**：W8.3 通过（按表格族抽样准确率 ≥95%，记录随验收档案留存）。
4. **可一键回退旧路径**：W8.4 通过（配置开关切回经演练验证，成本为小时级）。

四条全绿 = WS1 准出；任一红灯即停线回退，日历 6-8 周的区间正是为这些红灯预留的缓冲。

---

## 实跑 pending 的前置条件（金标 A/B 需要的资产）

本检查单中 **W6-7.b / W8.1 / W8.3 的实跑**（真实金标语料上的 corpus_eval 三指标对比与角色语义抽审）依赖以下资产，缺一不可；隔离 worktree 无这些资产时，相关命令用夹具自证工具链就绪，**实跑裁决标记 pending-human**：

- **金标语料**：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.docx`（ABNT profile，A 轨）+ 第二份散文类标准（B 轨）+ held-out 文档（机器相关路径，换机器需调整）。
- **冻结 `out/` 基线**：主检出的 `out/abnt_nbr_16968_atomizer_v5/`（按**三个种子 `--kb` + domain-pack** 生成，不是单编译库）。
- **签发成功的假设产物**：双轨制结构理解器（`llm_table_understanding.py`）在金标语料上跑出的 `table_structure_hypotheses.jsonl`（`validator_status=="issued"`）。本切片交付时提议轨尚未在金标上实跑，故角色抽审的真实抽样框也 pending。
- **专家档期**：角色语义抽审的逐格裁定（W8.3.b）与 WS0 真值集标注一致，需专家对照批注 HTML 完成。
