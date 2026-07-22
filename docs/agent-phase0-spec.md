# Agent 化 Phase 0 实施规格：评测集骨架 + 决策轨迹格式 + 决策器版本锚点

状态：待实施（实施者另指派；审核人：本方案作者）
日期：2026-07-22
前置阅读：`AGENTS.md`（硬约束全部适用）、`docs/agent-rollout-plan.md`（总方案，如已落盘）

## 0. 本阶段的定位

Phase 0 不写任何 agent 决策逻辑。它只交付三样东西，是 Phase 1（agentic triage）的
前置条件：

1. **评测集骨架**：≥20 条带标准答案的真实案例，让 Phase 1 每次改 prompt/策略有回归依据；
2. **决策轨迹 schema**：`decide_trace.jsonl` 的冻结格式，Phase 1 的决策循环按此落盘；
3. **决策器版本锚点**：`AGENT_POLICY_VERSION` 常量并入缓存指纹体系。

完成判定：本文"验收清单"全部通过，审核人确认。未完成前不得开工 Phase 1。

## 1. 仓库纪律（实施者必读，违反即打回）

- 测试必须是 `unittest.TestCase`（pytest 未安装，模块级 `def test_*` 会被静默跳过）。
  运行方式：仓库根目录 `python -m unittest discover -s tests`。
- 影响缓存产物行为的变更必须 bump 对应版本常量，否则旧缓存静默绕过新行为。
- 结构化字段（OBIS、文号、分类、引句）确定性裁决；评测集的"标准答案"同样
  不得由模型生成后未加人工核对直接入库。
- provenance 不伪造：评测案例必须记录真实来源；脱敏改写过的要标注。
- 不 commit、不 push，由用户决定。

## 2. 交付物一：评测集骨架

### 2.1 位置与布局

```
golden_sets/agent_eval_v1/
├── README.md                  # 数据集说明：来源、脱敏方式、维护规则
├── manifest.json              # 版本、案例计数、生成/核对记录
├── cases/
│   ├── classify/              # 软/硬/合规/非需求 分类题
│   │   ├── case-001.json
│   │   └── ...
│   ├── grouping/              # 软件研发功能分组题
│   ├── must_ask/              # 必须提问、不得推断的案例
│   └── hallucination/         # 已知幻觉/误合并的反面案例
└── schemas -> ../../schemas/agent_eval_case.schema.json   # 引用,不复制
```

### 2.2 案例格式（`schemas/agent_eval_case.schema.json`）

每个案例一个 JSON 文件，字段：

```json
{
  "case_id": "classify-001",
  "category": "classify | grouping | must_ask | hallucination",
  "source": {
    "doc_ref": "内部文档代号(脱敏,如 ABNT-NBR-16968)",
    "block_ids": ["BLK-000017"],
    "origin": "real | anonymized_rewrite",
    "curated_by": "姓名或缩写",
    "curated_at": "2026-07-22"
  },
  "input": {
    "text": "喂给被测逻辑的原文(逐字)",
    "context": "必要的上下文(章节路径/相邻块),无则空串"
  },
  "expected": {
    "verdict": "分类题填 software|hardware|compliance|non_requirement; 其他类别见下",
    "rationale": "为什么这是标准答案(人工书写,一句话)",
    "forbidden": ["不得出现的输出特征,如:虚构文号/无依据行为描述"],
    "must_ask_questions": ["must_ask 类专用:应当提出的澄清问题要点"]
  },
  "notes": "可选:历史上哪个模型/prompt 在此翻车"
}
```

- `grouping` 类：`expected.verdict` 填功能分组标识（同一功能的多个案例共享一个
  `group_key`，另设字段），判定逻辑是"同组/不同组"而非精确命名。
- `hallucination` 类：`expected.verdict` 填 `reject`，`forbidden` 必填。
- 数值/文号类断言一律精确匹配，不允许模糊比较。

### 2.3 数量与构成（最低门槛）

| 类别 | 最少条数 | 来源要求 |
|---|---|---|
| classify | 8 | 至少覆盖 software / hardware / compliance / non_requirement 各 2 |
| grouping | 4 | 来自 ≥2 份不同文档 |
| must_ask | 4 | 必须含"原文信息不足、模型易脑补"的真实陷阱 |
| hallucination | 4 | 取自 test3 等真实翻车记录（如虚构 OBIS、跨块误合并） |

合计 ≥20。来源优先：`out/` 下真实运行的 suspicion 记录、澄清报告历史、
`docs/remediation-plan-2026-07-20.md` 里的 test3 分诊案例。

### 2.4 评测运行器（最小实现）

新增 `agent_eval.py`（顶层模块，注册进 `pyproject.toml` py-modules）：

- 加载 `golden_sets/agent_eval_v1/cases/**/*.json`，用 schema 校验每个案例；
- 对 classify 类调用现有分类逻辑（规则层，不接 LLM），输出 pass/fail 明细；
- must_ask / hallucination / grouping 在 Phase 0 只做 schema 校验与计数上报，
  判定逻辑属 Phase 1+（在 README 里注明，避免实施者过度建设）；
- CLI：`python agent_eval.py --eval-dir golden_sets/agent_eval_v1`，输出 stdout
  JSON envelope（遵守 `docs/cli-contract.md`：退出码 0/2/3/4）。

### 2.5 测试

`tests/test_agent_eval.py`：

- 全部案例过 schema 校验；
- 类别计数满足 2.3 的最低门槛；
- classify 类在当前规则层下的 pass 率被记录进
  `golden_sets/agent_eval_v1/manifest.json`（作为基线，**不强制 100%**——规则层
  已知的错分案例如实记录，这正是后续改进的靶子）；
- 运行器对空目录/畸形案例返回正确退出码。

## 3. 交付物二：决策轨迹 schema

新增 `schemas/decide_trace.schema.json`，Phase 1 的循环每次迭代追加一行到
`out/<run>/decide_trace.jsonl`：

```json
{
  "trace_version": "decide-trace-v1",
  "run_id": "与 run_manifest 一致",
  "iteration": 3,
  "ts": "ISO-8601",
  "policy_version": "见交付物三",
  "state_digest": {
    "counts": {"requirements": 0, "coverage_gaps": 0, "open_questions": 0},
    "ready_gate": "pass|blocked",
    "blocked_reasons": ["..."]
  },
  "candidates": ["resample_section:BLK-1", "ask_clarification", "stop"],
  "action": "resample_section:BLK-1",
  "decider": "rule | llm",
  "reason": "为什么选这个动作(规则命中条件或模型理由摘要)",
  "budget": {"iterations_used": 3, "iterations_max": 10, "tokens_used": 0, "tokens_max": 0},
  "result": {"status": "ok|error|skipped", "summary": "一句话"}
}
```

硬性要求：

- `decider` 如实区分规则决策与模型决策（provenance 纪律，`stub` 不得冒充 `llm`）；
- 文件写入遵守仓库共享状态文件纪律：跨进程锁 + 原子替换 + `PermissionError`
  重试（参照 `review_state.py` 现有模式），但 decide_trace 是 append 语义——
  允许"锁内追加写单行"，不做全文件重写；
- schema 里 `required` 字段一次定死，Phase 1 不得随意加字段（加字段 = bump
  `trace_version`）。

测试：`tests/test_decide_trace.py`——schema 校验、追加写并发（两个 writer 线程
不丢行）、缺必填字段拒收。

## 4. 交付物三：决策器版本锚点

- 在 `agent_eval.py`（或新顶层模块 `agent_policy.py`，若实施者判断需要独立）定义：

```python
# 决策器行为版本——决策逻辑/候选动作集/停止条件任何变更必须 bump。
# 指纹纪律同 EXTRACT_GUARDS_VERSION：缓存产物若受决策影响,指纹必须含此值。
AGENT_POLICY_VERSION = "agent-policy-v0"
```

- v0 只做"锚点存在 + 进指纹"：把 `AGENT_POLICY_VERSION` 拼进
  `desktop_tasks.py` 的 chain 版本戳中 agent 相关段的**预留位置**（当前尚无 agent
  阶段，做法：在版本戳构造函数里加常量引用 + 注释，不改现有戳字符串内容，
  避免无谓缓存失效），并同步更新 `tests/test_desktop_tasks.py` 对应断言的注释。
- `decide_trace.schema.json` 的 `policy_version` 字段引用此常量。

## 5. 明确不做（范围护栏）

- 不写任何决策循环、不接 LLM 决策；
- 不重构 `run_manifest` / `review_states.jsonl` 等现有状态存储；
- 不做 grouping / must_ask / hallucination 的自动判定逻辑（Phase 1+）；
- 不追求 classify 基线 100%——如实记录现状；
- 不动 UI、不动 `gui/`（冻结）。

## 6. 验收清单（审核人逐项核对）

1. `python -m unittest discover -s tests` 全绿（含新增 3 个测试文件）；
2. `python agent_eval.py --eval-dir golden_sets/agent_eval_v1` 输出合规 JSON
   envelope，分类基线 pass 率写入 manifest 且与实测一致；
3. 案例数 ≥20 且各类别满足 2.3 下限；抽 5 条人工核对 `expected` 与原文一致、
   来源可追溯；
4. `schemas/agent_eval_case.schema.json`、`schemas/decide_trace.schema.json`
   存在且被测试真正执行（不是摆设）；
5. decide_trace 追加写并发测试通过，锁模式与 `review_state.py` 一致；
6. `AGENT_POLICY_VERSION` 已定义、被 chain 版本戳构造函数引用、被 trace schema
   引用，且现有版本戳字符串未变（`tests/test_desktop_tasks.py` 原断言不动）；
7. diff 中无范围外改动（状态存储重构、UI、gui/ 一律打回）；
8. `AGENTS.md` 新增一行：agent_eval / decide_trace 的位置与版本常量名。

## 7. 审核方式

实施者交付 diff + 本清单自检结果；审核人跑第 1、2 条命令复核，抽查第 3 条，
逐条核对 4–8。任何一条不过即整体打回，不部分接收。
