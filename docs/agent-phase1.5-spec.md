# Agent 化 Phase 1.5 实施规格：LLM 决策器对比实验

状态：**已完成**（2026-07-22 合入 main `5cd03be`；主检出全量 1483 tests OK、golden 6/6、评测基线 0.625 不变）
日期：2026-07-22
前置：Phase 0（`4161f18`）、Phase 1（`baba522`）、agent-policy-v2 修复（`1d3b61c`）；
总纲 `docs/agent-rollout-plan.md`；Phase 1 审核遗留 #1/#4 在本阶段内处理

## 0. 定位

Phase 1 的决策器只有规则（`rule_decider_v2`）。Phase 1.5 引入 **LLM 决策器**，
并让两者在**同一批真实产物**上平行运行，用轨迹对比决策质量与成本。
**LLM 决策器在本阶段不是默认**——只有对比数据显示其显著优于规则版，后续阶段
才允许改默认。

铁律不变：结构化字段确定性裁决；决策行为变更 bump `AGENT_POLICY_VERSION`；
轨迹逐行落盘且 `decider` 如实标注实际做出决策的机制（rule/llm）。

## 1. tokens 计量口径（审核遗留 #4，先行冻结）

- `budget.tokens_used` **只计决策调用**：LLM 决策器为选择动作发起的 chat 调用
  （含其 JSON 修复重发、截断升级重发）的 `usage.prompt_tokens + completion_tokens`
  之和；端点不返回 usage 时，该次调用计 0 并在汇总 `token_accounting` 标
  `"partial"`（不得估算冒充精确值）。
- **不含**工具执行触发的任何 LLM 调用（Phase 1.5 工具层保持零 LLM；未来的
  LLM 补抽若启用，须在各自产物里单独计量，不进 `budget.tokens_used`）。
- `budget.tokens_max` 为决策预算上限，CLI `--max-tokens` 可调，默认 20000；
  决策前检查发现已超限 → 当轮不发起 LLM 调用，规则决策兜底并在 reason 标注。

## 2. 审核遗留 #1：澄清口径收敛

- `clarification_report` 新增公开函数 `unresolved_hard_questions(out_dir)`，
  返回 `(unresolved_entries, counts)`，是"必答未解决"判定的**唯一实现**；
- 判定谓词（客户问题=答复采纳且指纹当前；内部核对=`verified_ok` 且指纹当前）
  抽为小函数，`run_report` 与 `agent_state` 共调；
- `run_report` 对外输出（报告文件、READY 门数值）**行为零变化**——纯抽取重构，
  靠现有测试锁死；
- `agent_state._unresolved_hard_questions` 删除，改为调用公开函数。

## 3. LLM 决策器（`agent_decider.py`，新增顶层模块）

- 输入：`AnalysisState.state_digest()` + 候选动作列表 + 决策规则提示
  （只能从候选中选；无事可做选 stop；信息不足选 ask_clarification；
  禁止编造 block_id/需求 id）；
- 输出 JSON：`{"action": "...", "reason": "..."}`；
- **校验与兜底**：action 不在候选中、JSON 无效、调用异常 → 当轮回退
  `rule_decider_v2`，轨迹 `decider="rule"`，reason 前缀 `llm 决策失败回退：`——
  绝不让 llm 名义落 rule 的决策（provenance 到每一行）；
- LLM 配置复用 `ai_extract.config_for_route("openai_compatible")`；API key 缺失 →
  CLI 响亮报错退出 2，不伪造 stub 决策。

## 4. 循环与 CLI 变更（`agent_loop.py`）

- 新参数：`--decider rule|llm`（默认 rule，行为与 v2 完全一致）、
  `--max-tokens N`（默认 20000）；
- llm 模式每轮：`llm_decide` 成功 → `decider="llm"`；失败/超限 → rule 兜底；
- 汇总新增：`decider_usage: {"rule": n, "llm": m}`、`token_accounting`；
- 规则决策器改名 `rule_decider_v2` 已定；LLM 决策器接入即
  `AGENT_POLICY_VERSION = "agent-policy-v3"`，decide_trace schema const、
  评测 manifest、test_agent_policy 同步。

## 5. 对比器（`agent_compare.py`，新增顶层模块）

CLI：`python agent_compare.py --out-dir DIR [--max-iterations N] [--max-tokens M]`

- 把 `out/` 复制两份到临时目录，分别跑 rule / llm 循环（**不碰原目录**）；
- 输出 JSON envelope：`rule` 与 `llm` 各自的迭代数、termination_reason、终态
  readiness、动作序列、decider_usage、tokens_used，以及 `agreement`
  （动作序列一致率）；
- API key 缺失时：rule 侧照跑，llm 侧标 `"error": "llm_unavailable"`，整体退出码 0
  但 envelope `ok: true` + `llm_ran: false`——对比报告如实标注 LLM 侧未运行，
  禁止用 rule 结果冒充对比结论。

## 6. 测试要求

- LLM 调用全部 mock（沿用 `tests/test_llm_client.py` 的 MockOpenAIService）；
- llm 决策：合法选择、非法 action 回退、异常回退、tokens 累计与超限不调用；
- 循环：`--decider llm` 轨迹 decider 字段逐行如实；混合回退时 rule/llm 计数正确；
- 对比器：mock 下两路各跑、agreement 计算、key 缺失时 `llm_ran: false`；
- 澄清收敛：`agent_state` 开放问题数与 `unresolved_hard_questions` 一致；
  现有澄清测试零改动通过（证明 run_report 行为未变）；
- 全量测试绿；评测基线 0.625 不降。

## 7. 验收清单

1. 全量测试绿（新增 ≥15 用例）；
2. `agent_compare` 在 mock 与真实 test3 产物（有 key 时）各跑一次，输出与轨迹
   互证；
3. 任何 llm 轨迹行 `decider="llm"` 且 action ∈ 当轮 candidates；回退行
   `decider="rule"` 且 reason 有回退标注；
4. `AGENT_POLICY_VERSION=agent-policy-v3`，schema const/评测 manifest/文档同步；
5. READY 门与澄清报告输出与 v2 逐项一致（收敛重构零行为变化）；
6. diff 范围：llm_client（仅新增 with_meta）、clarification_report（纯抽取）、
   agent_state/agent_loop + 新增 agent_decider/agent_compare 及各自测试、文档。
   不动 CHAIN_ORDER、omission_actions、工具层 LLM 策略。

## 8. 明确不做

- 不把 llm 设为默认决策器；
- 不给工具层开放 LLM（补抽/复核仍零 LLM）；
- 不做多轮对话式决策（每轮独立单调用，无决策记忆）；
- 不做成本金额估算（无价格表，只报 tokens）。
