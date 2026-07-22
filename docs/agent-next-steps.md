# Agent 化待办方案（2026-07-22 下班快照）

当前进度：Phase 0 ✅ → Phase 1 ✅（含 v2 修复）→ Phase 1.5 功能 ✅（main `467ad49`）。
下一步主线：**拿到真实对比数据 → 裁定 LLM 决策器去留 → Phase 2**。

## 待办清单（按优先级）

### 1. 真实 rule vs llm 对比实验（阻塞裁定，半天）
- 前置：设好 `RATOMIZER_LLM_API_KEY`。
- 复制 test3 到干净状态：`decide_trace.jsonl`、`agent_loop_summary.json`、
  `omission_states.jsonl` 三个文件删掉（26 个缺口回到未登记）。
- 跑：`python agent_compare.py --out-dir "<干净副本>"`。
- 产出 comparison JSON 交审核人裁定。
- 裁定口径（冻结）：动作序列一致率、llm 侧回退率（`decider_usage`）、
  tokens 成本、终态 readiness 差异。**一致率高且回退率低 → llm 无增量价值，
  规则保持默认**（这是最可能的结论，也是好结论：省钱且可解释）；
  llm 在规则失误场景有实质更优选择 → 才考虑混合模式。

### 2. 评测集扩充到 ≥40（Phase 2 前置，1–2 天）
- grouping / must_ask / hallucination 三类写自动判定逻辑，脱离 schema-only；
- 案例从 20 扩到 ≥40，来源：test2/test3 真实 suspicion 记录；
- 新案例标准答案人工核对后登记 manifest（沿用 Phase 0 流程）。

### 3. Phase 2 规格冻结（半天讨论 + 半天成文）
- 主题：tool-using reviewer——`llm_agents/review_pipeline.yaml` operations 改
  function calling，模型审查中自主调 KB/覆盖校验；
- 软件需求按内部模板输出，无依据字段强制"待澄清"；
- 规格必须先冻结经确认再动工（总纲硬性前置）。

### 4. 观察项（不占专门时间）
- 主检出全量测试曾现 1 个瞬时 error（Windows 文件占用类），复跑两轮 + 专项
  五连跑均绿，已留痕 CLAUDE.md；再出现需追查具体测试名。
- test3 目录里的 agent 产物（25 行混合 v1/v2 轨迹、omission_states 36 行）
  建议保留作缺陷修复证据；待对比实验用干净副本，不动原件。

## 已完成备案（不需要再做）

- v2 修复：跨运行去重 + 批量登记（`1d3b61c`）
- Phase 1.5：LLM 决策器（非默认）、tokens 口径、对比器、澄清口径收敛（`5cd03be`）
- 全部主检出验收：golden 6/6、全量 1483 tests、评测基线 0.625

## 参考文档

- 总纲：`docs/agent-rollout-plan.md`（路线/铁律/阶段前置）
- 规格：`docs/agent-phase0-spec.md`、`agent-phase1-spec.md`、`agent-phase1.5-spec.md`
- CLI：`docs/cli-contract.md`（agent_loop / agent_compare / agent_eval 用法）
