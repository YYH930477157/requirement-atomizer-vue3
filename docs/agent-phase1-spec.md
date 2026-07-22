# Agent 化 Phase 1 实施规格：有边界的决策循环（agentic triage）

状态：待实施（实施者另指派；审核人：本方案作者）
日期：2026-07-22
前置：`docs/agent-phase0-spec.md`（已完成，main `4161f18`）；本规格冻结的接口以该交付为准

## 0. 本阶段的定位

Phase 0 冻结了评测集、决策轨迹格式和版本锚点。Phase 1 在此之上实现**最小可用的
决策循环**：给定一次已跑完的抽取结果（`out/<run>/`），agent 在硬预算内自主执行
"补抽 → 复核 → 提问 → 停止"四类动作，直到 READY 门通过或预算耗尽。

铁律不变（违反即打回）：

- 结构化字段（OBIS、文号、分类、引句）确定性裁决——agent 只能提议，确定性层裁决，
  分歧进澄清清单；
- 决策行为任何变更 bump `AGENT_POLICY_VERSION`，且该版本必须进入受影响产物的缓存
  指纹（chain 版本戳已预留 `agent-*` 后缀机制，`desktop_tasks.stage_producer()`）；
- 每次决策按 `schemas/decide_trace.schema.json` 追加 `decide_trace.jsonl`，
  `decider` 如实区分 `rule`/`llm`；
- 测试必须 `unittest.TestCase`，根目录 `python -m unittest discover -s tests` 全绿。

## 1. 架构与模块边界

新增三个顶层模块（注册进 `pyproject.toml` py-modules），**不改**现有模块的对外行为：

```
agent_state.py     # AnalysisState：现有产物的只读聚合视图
agent_loop.py      # 决策循环 + 规则决策器 v1 + CLI 入口
agent_tools.py     # 四类动作对现有模块的薄包装
```

### 1.1 AnalysisState（`agent_state.py`）

只读聚合，**不重构**底层存储。从 `out/<run>/` 装载：

- `run_manifest.json`：阶段完成状态、失败单元数；
- `clarification_report.readiness_verdict(...)`：READY 门判定与阻塞原因（接口已存在，
  `clarification_report.py:559`）；
- `clarification_report.collect_questions(out_dir)`：未解决澄清计数（区分必答/参考 tier）；
- `merged_consistency.coverage_gaps(...)`：未覆盖 block 清单（接口已存在，
  `merged_consistency.py:308`）；
- 质量报告中的 `coverage_pct` / `core_coverage_pct` / `failed_sections`。

输出一个 dataclass，字段恰好填满 `decide_trace.schema.json` 的 `state_digest`
（`requirements` / `coverage_gaps` / `open_questions` / `ready_gate` /
`blocked_reasons`）+ 决策所需的候选动作输入。**视图不落盘**，每次迭代现算。

### 1.2 四类动作（`agent_tools.py`）

每个动作是带输入 schema 的薄包装，全部复用现有实现：

| 动作 | 包装对象 | 说明 |
|---|---|---|
| `resample_section:<block_id>` | `omission_actions` 的定点补抽路径 | 对 coverage_gaps 报告的未覆盖块定点补抽；遵守 `extraction_operation_lock` |
| `recheck:<req_id>` | 现有复核/自检路径（低置信或带 suspicion 条目） | 不新写复核逻辑，触发既有管线 |
| `ask_clarification` | `clarification_report` | 把当前必答清单落成澄清问题（信息不足时优先于任何猜补） |
| `stop` | — | 终止循环，输出终态摘要 |

动作执行失败的处置：记 `result.status=error` 进轨迹，该动作从后续候选中剔除
（同一动作不允许连续失败重试超过 1 次）。

### 1.3 决策循环（`agent_loop.py`）

```
state = load_state(out_dir)
for iteration in 1..=budget.iterations_max:
    candidates = build_candidates(state)     # 确定性生成候选集
    if not candidates: break                 # 无事可做 → 停止
    action = rule_decider_v1(state, candidates)
    if action == "stop": break
    result = run_tool(action)
    append_decide_trace(out_dir, trace(...))  # 每次迭代必落轨迹
    state = load_state(out_dir)               # 视图现算
write_final_summary(out_dir)
```

**规则决策器 v1（本阶段唯一决策器，不接 LLM）**，优先级从高到低：

1. READY 门 `verdict == "READY"` → `stop`；
2. 存在 `failed_sections` 或未覆盖块 → `resample_section`（按 block_id 排序取第一个，
   确定性）；
3. 必答（TIER_HARD）澄清项 > 0 且无法自动处理 → `ask_clarification`；
4. 其余情况 → `stop`（宁可早停，不做无依据动作）。

**硬预算**：`iterations_max` 默认 10，CLI 可调上限 50；`tokens_max` Phase 1 恒为 0
（不调 LLM），字段照填。预算耗尽以 `result.status=skipped` + 摘要落最后一条轨迹。

CLI：`python agent_loop.py --out-dir DIR [--max-iterations N]`，stdout JSON envelope，
遵守 `docs/cli-contract.md` 退出码（0/2/3，同步更新该文档）。

## 2. 与缓存/指纹的衔接

- `agent_loop` 不产生新的缓存产物：补抽走 `omission_actions` 既有缓存与锁；
- chain 版本戳：若 `desktop_tasks` 未来把 agent triage 纳入 CHAIN_ORDER，使用
  已预留的 `agent-*` + `AGENT_POLICY_VERSION` 机制；**本阶段不动 CHAIN_ORDER**；
- 规则决策器 v1 的任何行为变更（候选生成、优先级、停止条件）= bump
  `AGENT_POLICY_VERSION` 到 `agent-policy-v1`（当前 v0，本阶段首次启用决策即升 v1）。

## 3. 测试要求

新增 `tests/test_agent_state.py`、`tests/test_agent_tools.py`、`tests/test_agent_loop.py`：

- 构造夹具 `out/` 目录（复用现有测试的 fixture 模式），验证 AnalysisState 各字段
  与 `readiness_verdict`/`coverage_gaps` 输出一致；
- 决策器优先级四条规则各至少一个用例，含"READY 即停"、"无事可做即停"；
- 每次迭代轨迹可通过 `decide_trace.validate_decide_trace` 校验；
- 预算耗尽路径：断言迭代数 == 上限且最后轨迹为 skipped；
- 动作失败剔除：mock 补抽抛错，断言后续候选不再含该动作；
- 全程不调 LLM：测试中禁止任何网络访问（现有 MockOpenAIService 模式不需要）。

## 4. 验收清单（审核人逐项核对）

1. 全量测试绿（新增 ≥12 个用例）；golden 6 项在主检出实跑通过；
2. 对一份真实 `out/` 运行 `agent_loop.py`，轨迹行数 == 迭代数，每行过 schema 校验，
   `decider` 全为 `rule`；
3. 终态摘要如实报告 READY/NEEDS WORK 与剩余阻塞；不伪造"已就绪"；
4. `AGENT_POLICY_VERSION` 升至 `agent-policy-v1`，`schemas/decide_trace.schema.json`
   的 `policy_version` const 同步（**允许且仅限这一次**改 const）；
5. diff 无范围外改动：不改 CHAIN_ORDER、不改 READY 门阈值、不改现有模块对外行为、
   不动 UI/`gui/`；
6. `docs/cli-contract.md`、`AGENTS.md` 同步；
7. 用 Phase 0 评测集跑 `agent_eval.py`，分类基线不得下降（当前 0.625）。

## 5. 明确不做

- 不接 LLM 决策（`decider: "llm"` 留到 Phase 1.5 对比实验，见总纲）；
- 不做 grouping / must_ask / hallucination 的自动判定；
- 不改补抽/复核的内部实现，只做编排；
- 不引入多 agent。
