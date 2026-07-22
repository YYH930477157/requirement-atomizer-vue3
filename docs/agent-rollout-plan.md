# Agent 化总纲：路线、边界与各阶段验收口径

日期：2026-07-22
状态：Phase 0 已完成（main `4161f18`）；Phase 1 已完成（main `baba522`）；Phase 1.5 未开始

## 定位

把本仓库从"LLM 增强的确定性管道"演进为**有边界的单 Agent + 现有确定性工具**。
不做多 agent；agent 管理编排与决策，证据层（结构化字段、引句、文号、缓存指纹）
永远确定性。

## 三条铁律（所有阶段适用，违反即打回）

1. **结构化字段确定性裁决**——agent 只能提议，确定性层裁决，分歧进澄清清单；
2. **缓存指纹覆盖决策行为**——决策/prompt 变更 bump `AGENT_POLICY_VERSION`，
   受影响产物的指纹必须包含它；
3. **决策轨迹全量落盘、可重放**——`decide_trace.jsonl` 按冻结 schema 追加，
   `decider` 如实区分 rule/llm，循环有硬预算。

## 阶段路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | 评测集骨架（20 条，分类基线 0.625）、`decide-trace-v1` 契约、`agent-policy-v0` 锚点 | ✅ 已完成 |
| Phase 1 | 规则决策器 v1 的决策循环：补抽/复核/提问/停止四类动作，硬预算，全程不调 LLM | ✅ 已完成（main `baba522`） |
| Phase 1.5 | LLM 决策器对比实验：同一批真实 `out/`，rule vs llm 决策器并行跑，用 Phase 0 评测集 + 轨迹回放对比决策质量与成本；只有 llm 显著优于 rule 才允许成为默认 | 未开始 |
| Phase 2 | Tool-using reviewer：`llm_agents/review_pipeline.yaml` 的 operations 改 function calling，模型审查中自主调 KB/覆盖校验；软件需求按内部模板输出，无依据字段强制"待澄清" | 未开始 |
| Phase 3 | Orchestrator：自然语言任务 → 规划 `cli.py` 子命令序列。前两步见效后评估是否需要 | 未开始 |

## 各阶段推进的硬性前置

- 任何阶段开工前，其规格文档（仿 Phase 0/1 格式）必须先冻结并经审核人确认；
- 任何阶段合入 main 前：主检出全量测试绿 + golden 6/6 + 评测集基线不下降；
- 评测集随阶段扩充：Phase 1.5 前 grouping/must_ask/hallucination 三类要有自动
  判定逻辑并脱离 schema-only 状态，案例数从 20 扩到 ≥40；
- 每阶段合入后在 `CLAUDE.md` 记里程碑（三段式 commit）。

### Phase 1 审核遗留（Phase 1.5 开工前处理）

1. **澄清口径收敛**：`agent_state._unresolved_hard_questions` 与 `clarification_report`
   的已解决判定是两份实现，存在 READY 门口径分裂风险；抽成单一函数两边共调。
2. ~~补测试钉死"已排队不算新缺口"语义~~ **已完成（`agent-policy-v2`）**：test3 实测
   证实这不只是测试缺失而是行为缺陷（跨运行重复登记同一批 block）。修复：状态层新增
   `pending_extraction_block_ids`（needs_extraction/issue_confirmed），候选只含未排队
   缺口；新增批量动作 `queue_all_gaps`（test3 实测逐块登记 26 缺口耗尽 10 轮预算）；
   `resample_section` 幂等。复跑幂等已被测试钉死。
3. **零 LLM 循环的真实效用实测**：v2 修复后形态为"一轮批量登记 → 澄清 → 停止"，
   仍需在 test2/test3 类真实产物上复测一次端到端效用，作为 Phase 1.5 rule 基线。
4. **tokens 计量口径先入规格**：Phase 1.5 规格须先定义 `tokens_used` 口径
   （仅决策调用 vs 含决策触发的补抽调用），否则成本对比指标无效。

## 不做的事（长期有效）

- 不多 agent；硬件侧维持轻处理，不开放"设计建议"；
- 不让模型直接改结构化字段、版本指纹、缓存失效逻辑；
- 不重构现有状态存储与 UI——审查界面与 HITL 闭环照常是最终裁决者。
