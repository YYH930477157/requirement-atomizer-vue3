# 新会话继续方案（2026-08-17e 交接，基于 codex/table-translation-structure @ 0144773）

> 本文件是唯一需要带进新会话的入口。上一轮完成了第 1 项（B 轨 unit 级路由接线，
> 零成本验证 PASS）与第 3 项（M9 第 3-5 刀）；**付费步骤因 API key 未设置未执行**。

## 一、当前状态（已验证的事实，不要重新推导）

- **分支**：`codex/table-translation-structure`，HEAD `6794da3`（路由接线 + M9③-⑥ + **路由 v3 收口**：unit-router-v3/
  planner-v3/prompt-v4/front-matter——10% 诊断四轮实证，表格类守恒失败全部消除，
  剩余为 flash 模型质量残差）。全量测试
  **3972 项 OK**（1 机器本地跳过；golden 无漂移）。未推送、未合 main。
- **第 1 项（B 轨守恒修复）代码已落地**：
  - `functional_extract.apply_unit_routing`（`functional-unit-routing-v1`，仅
    clause_family）：纯表格条款出 B 轨输入与守恒基线，`unit_routing` 审计块进产物；
  - `unit_router` v2：COSEM 结构表带义务模态改判 a_track（`cosem_table_a_priority`）；
  - `extraction_units` planner v2：COSEM 表级语境下沉到行/格单元 `cosem_structured`；
  - `functional_reextract` 同口径过滤 + 审计块刷新。
- **零成本验证 PASS**（`PYTHONPATH=. python out/tools/replay_probe3_conservation.py`）：
  probe3 的 131 条真实 flash 输出重放，50/50 失败簇条款全部路由出；ABNT 全量
  358 节 → 186 提取 / 172 路由出 / 3 张非 COSEM 表保留（含真实 b_track 单元）。
- **10% 诊断已完成四轮**（2026-08-18，实付 ~¥4.7）：路由 v3 收口后 B 轨范围
  358→177 节，表格类守恒失败全部消失；**剩余失败 = flash 模型质量残差**（意译丢
  表号/引文改写/空响应，非确定性 ~2/33 节）。全量门禁 A 轨冷跑实测 ¥8.07/70 节
  （外推 ¥45+，缓存已保留在 %TEMP%/ab-runner.uqw4d3je 可暖启）。
- **待用户决策**（见 CLAUDE.md 2026-08-18 残差定性）：a) 换更强模型再 probe
  （~¥1.5/轮）；b) 接受残差走 M5 升级/专家审（门禁会 FAIL，不翻默认）；
  c) 先修 parse（garbled PDF 丢号根因）。

## 二、新会话工作项（按优先级排序）

### 1. key 就位后：全量 B 确认 + 门禁重跑（~2-4 元，一条龙）

```bash
# ② 门禁重跑（runbook 命令已补策略 env 与暖启动参数；①全量 B 确认可先单独跑直抽链）
PYTHONPATH=. RATOMIZER_CONTEXT_PACK_STRATEGY=clause_family RATOMIZER_LLM_API_KEY=<key> \
  python tools/ab_runner.py \
  --parsed-dir out/abnt_nbr_16968 --template "C:/Users/YYHwudi/Desktop/Canna-29/电表软件标准化需求列表-V2.3.12 - 2026-4-14..xlsx" \
  --route openai_compatible --keep-dirs --warm-a-cache <上次A_atoms目录> \
  --truth golden_sets/ws0_human_v1/truth.jsonl \
  --thresholds golden_sets/ws0_human_v1/thresholds.json --out out/ab-gate-report.json
```

- **策略 env 必须显式带**（§17 路由只在 clause_family 下启用；不设则 B 走 legacy
  文档级大包，守恒预期仍 FAIL）。gate_verify 实证上次门禁 B 腿即 clause_family 运行。
- B 轨剩余风险（零成本验证覆盖不到的）：prose 条款的义务覆盖（Foreword 样板文等），
  以及 3 张保留非 COSEM 表（Table 1/4/21）——全量 B 一跑便知。
- **exit 0 → 独立提交翻转 `RATOMIZER_EXECUTION_POLICY` 默认值**（config +
  `tests/test_pipeline_plan.py` 默认断言 + AGENTS/CLAUDE + golden 再生成流程）；
  exit 1/2 → 如实不翻，按报告归因。
- 门禁通过合 main 前：行为版本已 bump（planner v2/router v2/接线 v1）→ golden
  三种子 KB 再生成流程必须执行。

### 2. M9 第 6+ 刀（可选，0 元）

第 3-6 刀已完成（api_server_support / ai_extract_verify / claim_events_journal /
desktop_imports，蓝图 `docs/m9-split-plan-2026-08-17.md`）。剩余：ai_extract 函数族
（120 函数交织，最难）与 claim_review_actions 主体（effective ledger 权威）；
每刀纪律：AST 依赖闭包审计（不搬 patch 目标、不反向依赖原模块）→ 逐字搬运 →
原名重导出 → py-modules 登记 → BASELINE_BARE_JOINS 同步 → 全量测试 → 独立提交。

### 3. parse 侧 section_path 修复（已诊断，未修）

ABNT PDF：`2.20 Control of disconnection` 行断裂成 heading「2 20 Control of」+
段落「disconnection」（点号丢失）；50 个 heading 中 48 个是目录条目（带页码）。
337/358 chunk 共享同一 section_id。当前路由按 block_id 判定不受影响；修复需重解析
+ 指纹连锁 + golden 再生成，建议门禁通过后独立处理（影响：duplicates 分组、
clause_family 邻居、批注视图章节归属）。

## 三、关键文件索引

| 主题 | 文件 |
|---|---|
| 本轮完整记录 | `CLAUDE.md` 2026-08-17e 条目 |
| 零成本重放脚本（机器本地） | `out/tools/replay_probe3_conservation.py` |
| 门禁运行手册（命令已补全） | `docs/ws0-truth-flip-runbook-2026-08-17.md` |
| 探针产物 | `out/probe3-items.json`、`out/clause-family-probe*.log` |
| M9 蓝图 + patch 目标 | `docs/m9-split-plan-2026-08-17.md` + `out/m9-patch-targets.json` |
| 路由测试 | `tests/test_functional_unit_routing.py`（15）+ `tests/test_unit_router.py` v2 节 |

## 四、新会话开场白（复制即用）

> 仓库 codex/table-translation-structure @ 0144773。按 docs/NEXT-SESSION-PLAN.md 继续：
> key 就位后先跑全量 B 确认（clause_family + 路由接线已落地、零成本重放已 PASS），
> 然后 --warm-a-cache 跑门禁，exit 0 才翻默认并走 golden 再生成。预算控制在 10 元内。

## 五、硬红线（不要因任何理由绕过）

1. 门禁 exit 0 才翻默认（§31）；合成夹具/代定阈值不可伪造门禁通过。
2. 每次行为版本 bump 后：全量测试 + golden 三种子 KB 再生成流程（合 main 前）。
3. M9 每刀独立提交可回滚；patch 保真（别名导入是扫描盲区）。
4. 付费调用前确认 key 余额；大额（>5 元）先告知。
