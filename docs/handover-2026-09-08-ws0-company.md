# 交接文档——WS0 门禁收尾三步（2026-09-08，赴公司机执行）

> 承接 `docs/ws0-smoke-100-2026-09-08.md`（100 节限量冒烟，FAIL 但失败面已收窄到
> 单条款族）。本文给出三步的可执行命令、验收标准与机器前置清单。
> **密钥纪律：API key 只走环境变量，绝不写入任何文件/仓库/文档。**

## 0. 当前状态快照（截至 de913a7，均已 push）

- main = `de913a7`；关键提交：`9affa30`（红门修复+任务D闭环+conservation v8 豁免）、
  `e4382bb`（`--limit-sections` 贯通）、`de913a7`（冒烟结果档）。
- 后端全量 **4326/0/0/0**（含 golden）；UI vitest **294/294**；vue-tsc 0 错。
- 冒烟判定：**FAIL，唯一失败 = B_direct execution_status=partial**。
  - A 轨：100 节 → 935 FRE → 成文在场（通过）。
  - B 轨：47 条款真 LLM + **1 条款（「2 20 Control of」BLK-000363）LLM 调用失败退 stub**
    → mixed → fail-closed。
  - B 守恒：binding/duplicates/obligation/evidence **全绿**（v8 豁免未被触发）；
    唯一红类 preservation 2 条否定词（cannot/not @「2 20 Control of」表格碎片块，
    块锚 BLK-000365…、BLK-000410…）。
  - 对照 08-17 全量门禁：duplicates 6→0、binding 全绿、A reader 通过——三大失败面消失。
- 报告：`out/ab-gate-report-v8.json`（本机 out/，git-ignored）；保留工作目录
  `%TEMP%\ab-runner.8k0bn96r\{A_atoms,B_direct}`（--keep-dirs，本机临时目录，重启可能清空）。

## 1. 公司机前置清单（缺一不可）

| 项 | 来源 | 说明 |
|---|---|---|
| 仓库最新 | `git pull` main=de913a7+ | 真值/阈值在 repo：`golden_sets/ws0_human_v1/` |
| 解析语料 | 本机拷贝 `out/abnt_nbr_16968/` 或公司机重 parse | out/ 是 git-ignored；重 parse：`PYTHONPATH=. python -m cli atomize "<ABNT NBR 16968 docx>" --out out/abnt_nbr_16968` |
| 公司模板 xlsx | 本机 `C:\Users\YYHwudi\Desktop\Canna-29\Canna-29\电表软件标准化需求列表-V2.3.12 - 2026-4-14.xlsx` 拷贝 | 路径按公司机实际改 |
| API key | DeepSeek，环境变量 `RATOMIZER_LLM_API_KEY` | 模型 `deepseek-v4-flash`、base `https://api.deepseek.com`；**确认余额**（历史曾 402） |
| Python 环境 | ≥3.11，`pip install -e .` | 测试跑法见 AGENTS.md（unittest，非 pytest） |

必设环境变量（runbook 红线）：`RATOMIZER_CONTEXT_PACK_STRATEGY=clause_family`。

## 2. 三步收尾

### ① 消 mixed（B 轨单条款 stub 回退）

最便宜路径（推荐先做）：**直接重跑限量冒烟**——新工作目录无缓存，47 条款全部重付
（flash 单价下约几十万 token，人民币元级以内）；上次失败是单次 LLM 截断/空响应
（本次 A 轨 29 次截断自动升级重试全部成功），重试大概率过。

```
PYTHONPATH=. RATOMIZER_LLM_API_KEY=<key> RATOMIZER_CONTEXT_PACK_STRATEGY=clause_family ^
  python tools/ab_runner.py --parsed-dir out/abnt_nbr_16968 --template "<V2.3.12.xlsx>" ^
  --route openai_compatible --truth golden_sets/ws0_human_v1/truth.jsonl ^
  --thresholds golden_sets/ws0_human_v1/thresholds.json --limit-sections 100 --keep-dirs ^
  --out out/ab-gate-report-v8.json
```

若「2 20 Control of」**复现**失败（稳定性病理，该条款为巨型表格条款）：走定点重抽——
`functional_reextract.functional_targeted_reextract(out_dir, affected_block_ids=["BLK-000363"],
expected_product_fingerprint=<产物 fingerprint>, route="openai_compatible")`（同条款族重抽、
未受影响 FRE 字节稳定、仅 ok+守恒闭合原子替换）；或归入②任务 D 通道。

**验收**：B 路报告不再出现 `execution_status=partial`。注意：①完成后若 preservation
2 条仍在，B 仍会因守恒未闭合 FAIL——①②是一体两面。

### ② 任务 D：preservation 否定词 2 条闭环

- 事实：blocking losses 为 negation token=cannot/not，都在「2 20 Control of」表格碎片
  （列序打乱拼接病理，`docs/table-preservation-design-2026-09-06.md` 裁决候选 3/4）。
- 已接好的机械（`9affa30`）：preservation blocking loss 带 `section_block_ids` →
  `routing_gaps.gaps_from_functional_product` 分流 `targeted_reextract`（块锚可定位）；
  专家确认后经既有 claim 队列执行（同 clause family、不越界、字节稳定、守恒重过）。
- 期望修复面：v5 提示词已要求参数行字段/值/单位/适用条件进 data_constraints；
  重抽该族时观察否定词是否落叙述（`item_narrative` 覆盖 behaviors/data_constraints）。
- **验收**：B 守恒 preservation.ok=true；「守恒待核」清单不再有该族缺口行。

### ③ 全量 343 节正式门禁（Go/No-Go）

前置：①②收敛（B 轨 ok + 守恒闭合）。命令同上去掉 `--limit-sections 100`（或用仓库根
`ws0-gate-rerun.cmd` 的全量版本，本机未提交、公司机按上文自拼）。

- 退出码：0=PASS / 1=NO_GATE / 2=FAIL；报告 schema `ab-runner-report/v3`。
- PASS 才进入 `RATOMIZER_EXECUTION_POLICY` 翻转讨论——触发条件见
  `docs/execution-policy-margin-2026-09-06.md` 的 4 条（含翻转前后 legacy_combined
  对照轮）。**限量冒烟与单文档 PASS 都不是翻转依据。**
- 失败归因工具：`tools/binding_attribution.py`（b/c 类信号）、
  `tools/task_d_classify.py`（表格病理 a/b/c/manual_review）。

## 3. 红线提醒（AGENTS/CLAUDE 口径）

- 不放宽守恒：v8 逐字重复豁免是用户 2026-09-07 裁定项，语义边界见
  `functional_extract._unit_sentence_duplicated_in_home_clauses` docstring。
- 门禁 fail-closed：mixed/failed 一律 FAIL，不用 partial 产物充数。
- 行为版本改动（提示词/守恒/护栏）必须 bump 对应常量并登记 `prompt_registry`。
- key 只在 env；`ws0-gate-rerun.cmd`（未提交）内也只有 setx 占位、无真实密钥。
