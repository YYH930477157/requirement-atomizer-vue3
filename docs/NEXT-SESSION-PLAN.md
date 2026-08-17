# 新会话继续方案（2026-08-17 交接，基于已合入 main 的 81f51f9）

> 本文件是唯一需要带进新会话的入口。所有细节文档都已合并到 main 并推送。

## 一、当前状态（已验证的事实，不要重新推导）

- **仓库**：main = `81f51f9`（已 push）。全量测试 **3953 项 OK**（1 项机器本地样本跳过）；golden 三种子 KB 再生成后 **6/6 绿**；前端 npm test 277 + build 绿。
- **方案十六项**：15 项已落地合并；**第 15 项（默认翻转）未执行**——WS0 真值门禁 FAIL（exit 2），按 §31 红线 `RATOMIZER_EXECUTION_POLICY` 默认保持 `legacy_combined`。
- **门禁 FAIL 两条根因**：① B 轨（直抽）守恒失败——flash 文档级大包的 duplicates（已证 clause_family 可修）+ 表格内容混入 B 轨（正确修法是 unit 级路由，未接线）；② A 轨（原子化）链路本身跑通（343 节→996 原子→1847 行成文），门禁读取器缺口已由 phase2 独立会话修好（`ab-runner-report/v3`，模板校准+列契约）。
- **花费**：key 余额已耗尽过一次（HTTP 402 后恢复），门禁 A 轨 343 节是最大成本项（~4.5M tokens）。低成本工具 `--warm-a-cache` 已就绪：下次门禁 A 轨零付费，只付 B 轨（~236k tokens ≈ 2 元）。

## 二、新会话工作项（按优先级排序）

### 1. B 轨守恒修复：unit 级路由接线（主任务，0 元开发 + ~2 元验证）

**这是翻转默认前的最后一座山。** 三个根因两个已修、一个定位：

| 根因 | 状态 |
|---|---|
| duplicates（文档级大包） | ✅ `strategy="clause_family"` 已实证修复（probe2，56 节子集 PASS） |
| 表格标记伪影（引文/数字假失败） | ✅ guards-v6 已合并（`_strip_table_markers`，5 测试） |
| 表格内容混入 B 轨 | ⏳ **本项**：section 级路由已被证伪（`2 20 Control of` 等 section_path 截断撞名，50+ 节共享 id），正确粒度是 M1 的 block/unit 级 |

**做法**：
- `functional_extract.run_functional_extract` 消费 `extraction_units.load_extraction_units` + `unit_router` 决策：表格单元（a_track/context）出 B 轨输入与守恒基线；
- 跳过清单写进产物 meta（`table_dominated_routed_out` 之类），绝不静默；
- 仅在 clause_family 策略下启用（legacy 零变化）；护栏版本按需 bump；
- **零成本验证**：probe3 产物已存 `out/probe3-items.json`（131 条），守恒是确定性检查——改完路由逻辑后对它重算即可判断，不用花一分钱；
- 通过后一次全量 B（~236k tokens ≈ 2 元）确认文档级守恒。

### 2. 门禁重跑 + 翻转评估（~2 元）

B 轨修好后（真值/阈值已在仓库：`golden_sets/ws0_human_v1/`）：

```bash
PYTHONPATH=. RATOMIZER_LLM_API_KEY=<key> python tools/ab_runner.py \
  --parsed-dir out/abnt_nbr_16968 --template "C:/Users/YYHwudi/Desktop/Canna-29/电表软件标准化需求列表-V2.3.12 - 2026-4-14..xlsx" \
  --route openai_compatible --keep-dirs --warm-a-cache <上次A_atoms目录> \
  --truth golden_sets/ws0_human_v1/truth.jsonl \
  --thresholds golden_sets/ws0_human_v1/thresholds.json --out out/ab-gate-report.json
```

- 首次需全量 A（记得 `--keep-dirs` 留缓存给下次暖启动）；此后每次 ~2 元。
- **exit 0 → 独立提交翻转 `RATOMIZER_EXECUTION_POLICY` 默认值**（config + `tests/test_pipeline_plan.py` 默认断言 + AGENTS/CLAUDE + golden 再生成流程）；exit 1/2 → 如实不翻。

### 3. M9 第 3-5 刀（0 元，每刀独立提交）

全量 patch 目标清单已落盘 `out/m9-patch-targets.json`（api_server 20 / desktop_tasks 32 / ai_extract 25 / claim_review_actions 7）。**剩余大符号全部有模块内依赖**——依赖簇级搬运，每刀必须：AST 定位 → 逐字搬运 → 原名重导出 → 全量测试。蓝图：`docs/m9-split-plan-2026-08-17.md`（含别名 patch 盲区教训）。已完成样例：第 1 刀 `annotation_translations.py`、第 2 刀 `desktop_task_args.py`。

### 4. 可选：parse 侧复查 section_path 截断撞名（0 元）

`2 20 Control of` 这类标题截断使 50+ 小节共享 id——影响 duplicates 分组与路由键。在 `extract_units`/`atomize` 的 heading 检测处查（M0/probe 日志有实例）。

## 三、关键文件索引（全在 main）

| 主题 | 文件 |
|---|---|
| 原方案（16 项拆分） | `docs/quality-first-unit-routing-complete-plan-2026-08-16.md` |
| 架构决策（八项） | `docs/adr/2026-08-17-quality-first-unit-routing.md` |
| 门禁运行手册（含成本/判定） | `docs/ws0-truth-flip-runbook-2026-08-17.md` |
| 门禁 FAIL 详情 | `docs/ws0-gate-result-2026-08-17.md` |
| M0 成本基线 | `docs/m0-baseline-abnt-summary-2026-08-17.md` |
| ABNT 路由统计（4285 单元） | `docs/unit-routing-shadow-abnt-2026-08-17.md` |
| M9 蓝图 + patch 目标 | `docs/m9-split-plan-2026-08-17.md` + `out/m9-patch-targets.json` |
| phase2 进展（含探针实证） | `docs/phase2-handoff-2026-08-17.md` + `docs/phase2-item2-gate-xlsx-reader-fix-2026-08-17.md` |
| 探针产物（零成本验证素材） | `out/probe3-items.json`、`out/clause-family-probe*.log` |

## 四、新会话开场白（复制即用）

> 仓库 main=81f51f9。按 docs/NEXT-SESSION-PLAN.md 继续：先做第 1 项（B 轨 unit 级路由接线，
> 用 out/probe3-items.json 零成本验证），通过后花 ~2 元跑门禁（--warm-a-cache），
> exit 0 才翻默认。M9 第 3-5 刀每刀独立提交。预算控制在 10 元内。

## 五、硬红线（不要因任何理由绕过）

1. 门禁 exit 0 才翻默认（§31）；合成夹具/代定阈值不可伪造门禁通过。
2. 每次行为版本 bump 后：全量测试 + golden 三种子 KB 再生成流程。
3. M9 每刀独立提交可回滚；patch 保真（别名导入是扫描盲区）。
4. 付费调用前确认 key 余额；大额（>5 元）先告知。
