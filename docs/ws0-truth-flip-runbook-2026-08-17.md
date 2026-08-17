# WS0 真值门禁与 quality_first 默认翻转运行手册

**日期：** 2026-08-17
**目的：** 把「提供人工真值集 → 跑 ab_runner 门禁 → 评估默认翻转」变成到手即跑的
单命令流程（方案 §31 红线：真值门禁通过前不翻 `RATOMIZER_EXECUTION_POLICY`）。

## 现状（2026-08-17 实查）

- `golden_sets/gold_functional_v1/truth.jsonl`：**空**（0 行）。
- `golden_sets/ab_truth_m3_v1/functional_truth.jsonl`：6 行，自我声明
  `SYNTHETIC FIXTURE ... self-proof entry`、document_id=SYN-DLMS-AB-1——是
  ab_runner 自证夹具，**不能充当翻转证据**（对 ABNT 选行数 = 0，已实测）。
- 结论：默认翻转仍被真实人工真值阻塞。

## 第 1 步：提供真值集（唯一需要你做的事）

文件：`golden_sets/ws0_human_v1/truth.jsonl`（新建目录即可），JSONL 每行：

```json
{
  "truth_id": "T-001",
  "document_id": "abnt_nbr_16968",
  "section_id": "4.2",
  "expected_text": "电表应支持四象限有功电能记录。",
  "conditions": [], "exceptions": [], "negations": [],
  "numbers": ["-25", "+70"], "units": ["°C"], "codes": []
}
```

- `document_id` 必须能对上被评文档：**parsed 目录名**、或
  `sha256:<blocks.jsonl 的 sha256>`、或 `*`（通配）。建议把解析目录命名为
  `abnt_nbr_16968` 并用同名 document_id。
- `expected_text` 是该条款应当被抽出的软件需求文本（人工判定"必须抽出什么"）；
  numbers/units/codes 列出该条必须保真的数值/单位/编码。
- 条数建议 ≥ 30 条/文档（覆盖 prose shall 条款与参数表行；越多门禁越可信）。

## 第 1.5 步（已有核对结果时的捷径）：一键转换

不想手写真值？把任一人工核对结果交给转换器（`tools/truth_from_review.py`）：

```bash
python tools/truth_from_review.py   --input "C:/.../人工核对需求表.xlsx" --document-id abnt_nbr_16968   --output golden_sets/ws0_human_v1/truth.jsonl
```

- XLSX：中英文模板列名自动识别（ab_runner 同一别名权威）；任意语言表头用
  `--body-col/--section-col/--condition-col` 显式指定（实测：Canna-29 葡语表头
  `--body-col Conteúdo` 转出 192 行）；
- JSON：`--json-text-key/--json-section-key` 显式指定键名；
- 数值/单位/编码（含 OBIS 连字格式）确定性抽取，`--no-extract` 可关；
- 逐行过 `schemas/functional_truth.schema.json` 校验，任何一行不合法整体拒绝写盘。
- 注意：转换器只做格式转换——**该文件是否够格充当 WS0 真值由你拍板**（内容质量、
  覆盖面、是否经人工核验），拍板后一条命令落到 golden_sets 即可。

## 第 2 步（可选但推荐）：阈值文件

`golden_sets/ws0_human_v1/thresholds.json`——14 项全必需，缺任一 → NO_GATE：

```json
{
  "min_truth_precision": 0.85, "min_truth_recall": 0.85, "min_truth_f1": 0.85,
  "min_condition_preservation": 0.9, "min_exception_preservation": 0.9,
  "min_negation_preservation": 0.95, "min_number_preservation": 0.98,
  "min_unit_preservation": 0.98, "min_code_preservation": 1.0,
  "max_duplicate_rate": 0.05, "max_oversplit_rate": 0.1,
  "max_undersplit_rate": 0.1, "max_manual_action_estimate": 0.2,
  "max_final_row_growth_ratio": 1.5
}
```

（以上数值是示例起点；由你按验收口径定稿。）

## 第 3 步：跑门禁（一条命令）

```bash
RATOMIZER_LLM_API_KEY=<key> python tools/ab_runner.py \
  --parsed-dir out/abnt_gate_abnt_nbr_16968 \
  --template "C:/Users/YYHwudi/Desktop/Canna-29/电表软件标准化需求列表-V2.3.12 - 2026-4-14..xlsx" \
  --route openai_compatible \
  --truth golden_sets/ws0_human_v1/truth.jsonl \
  --thresholds golden_sets/ws0_human_v1/thresholds.json \
  --out out/ab-gate-report.json
```

其中 `out/abnt_gate_abnt_nbr_16968` 是解析产物目录（目录名 = document_id）；
可用 M0 的解析产物复制改名（解析确定性零 LLM，重跑亦可）。

**成本提示（诚实）**：门禁冷跑 A（原子化）+ B（直抽）两整条轨——M0 实测 B 轨
直抽 ≈ 2 调用/23.6 万 tokens；A 轨按章节调用，预计整门禁 0.5–1.5M tokens
（deepseek-v4-flash 计费）。**无匹配真值也会先跑完两轨才给 NO_GATE**——请先
放好真值再跑，避免白付。

## 第 4 步：判定与后续

| 退出码 | 判定 | 动作 |
|---|---|---|
| 0 | PASS（全阈值达标） | 执行默认翻转（见下） |
| 1 | NO_GATE（缺真值/阈值） | 补齐后重跑；不翻默认 |
| 2 | FAIL（链失败/守恒未闭合/stub/阈值未达） | 修复后重跑；不翻默认 |

**PASS 后的默认翻转（独立提交，回滚 = 还原一个 env 默认值）：**
`config.ENV_REGISTRY` 中 `RATOMIZER_EXECUTION_POLICY` 默认
`legacy_combined → quality_first`（同步描述文案）+ `tests/test_pipeline_plan.py`
的默认断言更新 + AGENTS/CLAUDE 条目 + 按仓库流程执行 golden `out/` 再生成
（多个行为版本已 bump；见 AGENTS「Workflow conventions」）。
翻开后 legacy 路径仍完整保留（`--execution-policy legacy_combined` /
env 显式设置即可回滚）。

## 翻转之后的剩余收敛项（与门禁解耦，可先行）

- LLMJobRunner 存量消费者迁移（逐个：spot_extract 单段路径的 chat 闭包被
  critique_section 多轮驱动，迁移需连同自检循环一起设计，不可硬套单发机械）；
- M9 大文件拆分收敛（App.vue 6210 行 / api_server / claim_review_actions 等）。
