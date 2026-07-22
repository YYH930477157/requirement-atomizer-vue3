# Agent 化待办方案（2026-07-22 下班快照；2026-07-22 晚更新：#1 已裁定）

当前进度：Phase 0 ✅ → Phase 1 ✅（含 v2 修复）→ Phase 1.5 功能 ✅（main `467ad49`）
→ **真实对比实验 ✅ 已裁定：规则保持默认**（n=4，详见 CLAUDE.md 里程碑）。
下一步主线：**评测集扩充（#2）→ Phase 2 规格冻结（#3）**。

## 待办清单（按优先级）

### 1. ~~真实 rule vs llm 对比实验~~ **已完成（2026-07-22）**
- 结果：序列完全一致率 0/4、失败回退 0%、tokens 870–1358/run、readiness 4/4 相同；
  终态产物仅 1/4 追平 rule（2/4 丢 26 行缺口登记、1/4 提前 stop）。
- 裁定：**规则保持默认**（llm 最好情况=追平 rule；temperature 0.0 下同输入三序列，
  不可复现本身是否决项）。llm 决策 revisit 留 Phase 2。
- 证据（机器本地）：`test3-agent-compare-clean-20260722/agent_compare_result.json`、
  `test3-agent-compare-llm-reruns-20260722/run{1,2,3}/`。

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
