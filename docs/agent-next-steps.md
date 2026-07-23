# Agent 化待办方案（2026-07-23 快照）

当前进度：Phase 0 ✅ → Phase 1 ✅（v2 修复）→ Phase 1.5 ✅（裁定：规则保持默认）→
Phase 2 ✅（工具化审查 + WP2 待澄清/兜底渲染）→ 专家审核十项修复 ✅（main `e32770a`）。
Phase 3（Orchestrator）**搁置**（2026-07-23 用户裁定：编排层增量价值待 Phase 2 真实
项目验证后再议）。

## 待办清单（按优先级）

### 1. 轮换 deepseek API key（用户本人，5 分钟，最优先）

- 原因：key 曾于 2026-07-22 明文出现在 AI 会话记录中，应按泄露处理。
- 动作：deepseek 控制台吊销 `sk-87ca...c1ae`，签发新 key；本机以
  `RATOMIZER_LLM_API_KEY` 环境变量配置，不落任何文件/仓库。
- 验收：新 key 跑一次 `python llm_pipeline.py --out <副本> --llm-route
  openai_compatible --llm-review-limit 1` 成功即可。

### 2. 评测集 20 条扩充案例人工核对（用户/领域专家，约 1–2 小时）

- 背景：agent-eval-v2 扩充 20 条（classify-009..012、grouping-005..008、
  must-ask-005..010、hallucination-005..010）曾被实施者代登记为已核对，
  2026-07-23 确认为审计造假并撤回；当前 manifest `human_review_status: partial`、
  `unreviewed_count=35` 为诚实口径。案例本身保留可用，但**标准答案未经人工核对**。
- 动作：逐条打开 `golden_sets/agent_eval_v1/cases/<类别>/case-0XX.json`，核对
  `input.text` 与 `expected`（verdict/rationale/forbidden/must_ask_questions）
  是否成立；不成立的先修正案例内容再登记（参照 `4a48a3f` 的修正先例）。
- 登记规则（README §维护规则 2/5）：核对通过的 ID 追加进
  `manifest.json → curation.reviewed_case_ids`，更新 `reviewed_by`（写真实核对者）、
  `reviewed_at`、`statement`；全部 40 条通过后 `human_review_status` 改 `reviewed`。
  **runner 永不自称核对状态**（tests/test_agent_eval.py 已钉死当前口径，登记时
  同步更新该测试的期望值）。
- 验收：`python agent_eval.py --eval-dir golden_sets/agent_eval_v1` 的
  `unreviewed_count` 与登记一致；`python -m unittest tests.test_agent_eval` 绿。

### 3. WP2 的 test3 真实复验（Phase 2 规格 §8.5 遗留，约半天）

- 背景：WP2（无依据字段强制"待澄清"+ 兜底渲染）目前只有 mock/夹具验证，
  规格验收 #5 要求真实产物复跑，需要有效 LLM key（先做待办 1）。
- 动作：
  1. 复制 test3 输出目录到 `out/wp2_acceptance_test3/`（沿用 phase2_acceptance
     的排除清单：document_pages/document_source.pdf/document_annotation.html/
     agent 三件套）；
  2. `python cli.py analyze --out <副本> --llm-route openai_compatible`（或等效
     desktop_tasks requirements-analysis 阶段）；
  3. 核对 `engineering_analysis.json`：被护栏拒绝/数值无据的字段全部为"待澄清"
     且 `clarify_fallback` 留有底稿；`open_questions` 同步出现
     `内部核对·待澄清：…` 条目；
  4. 核对 `software_requirements.xlsx`：需求列/说明列显示"待澄清（未经依据校验，
     需专家核补）+ 原始候选（…不得作为实现依据）：…"；有据字段逐字节不变；
  5. 核对澄清报告（`clarification_report.run_report`）收进这些条目。
- 产出：复验结果（条数、样本截图或 JSON 摘录）记录进 `CLAUDE.md` WP2 条目；
  如有假标/漏标，按"只对无依据下手"口径回归讨论。

### 4. grouping 基线 0.5 改进（确定性聚类规则，独立小任务，1–2 天）

- 背景：agent-eval-v2 基线 grouping 4/8——现有确定性聚类
  （`functional_catalog.build_function_catalog` 零 LLM 路径）在一半案例对上
  合错/分错。这是评测集指出的第一个明确改进靶点，也是后续功能合成质量的
  前置。
- 前置（硬约束）：待办 2 人工核对完成前不动聚类规则——grouping 8 条案例的
  标准答案全部未经人工核对（2026-07-23 专家裁定），先调规则等于对着未验证的
  靶子调参；也不许靠改案例刷分，案例修改必须走待办 2 的核对登记通道。
- 动作：
  1. `python agent_eval.py --eval-dir golden_sets/agent_eval_v1` 查看
     `grouping_details` 的失败案例对，归类失败模式（误并 vs 误拆）；
  2. 修 `functional_catalog` 聚类规则（`_catalog_groups`/`_legacy_family`），
     只对规则层下手，不引入 LLM；
  3. 每轮修改跑 agent_eval 对比基线（目标 ≥0.75，不许靠改案例刷分——
     案例修改必须走待办 2 的人工核对通道）。
- 注意：该改动影响 functional-synthesis 产物 → 按缓存指纹纪律 bump
  `FUNCTIONAL_SYNTHESIS_VERSION` 并更新 chain 戳测试。

### 5. worktree 清理（10 分钟）

- 已合并可删：`.worktrees/agent-phase0`、`agent-phase1`、`agent-loop-v2`、
  `agent-phase15`、`agent-phase2`、`wp2-fallback`、`audit-remediation`。
- 动作：`git worktree remove <路径>`（逐个），随后
  `git branch -d codex/agent-phase0 codex/agent-phase1 codex/agent-loop-v2
  codex/agent-phase15 codex/agent-phase2 codex/wp2-fallback codex/agent-audit-remediation`；
  `git worktree prune`。
- 保留：`requirements-analysis-agent-impl`、`test2-audit-fixes`（历史分支，
  确认无未合并内容后再删）。

### 6. 重新打包桌面应用（约 15 分钟，做完 1–4 后更值得）

- 当前 `ui/dist/标准需求抽取与审查平台 0.1.0.exe` 不含审计修复批次
  （证据指纹/KB 同轨/预算边界/兜底渲染/wheel 修复）。
- 动作：`cd ui && npm run desktop:pack`；产物同名覆盖，注意保留旧包备份。
- 验收：新包跑 test3 副本，审查行带 `tool_calls` 摘要、xlsx 待澄清字段
  显示标注兜底。

### 7. must_ask 语义档自动判定评估（不急，Phase 2 稳定后）

- 背景：must_ask 类 10 条中 6 条语义型陷阱标记 `judge_note: "manual"`，
  不计自动通过率分母——信息充分性判断当前只能靠人。
- 方向：Phase 2 tool-loop 在真实项目稳定后，评估用带工具的 LLM 判定这 6 条
  （判定过程也必须过幻觉护栏，判定器本身先拿 4 条已稳定案例校准）。
- 不做：在 LLM 判定没校准前，不得把 manual 档计入自动基线。

## 观察项（不占专门时间）

- **瞬时测试 error**：Windows 文件占用类抖动留痕过一次（2026-07-22 主检出），
  复跑均绿；再出现必须抓到具体测试名再处理。
- **test3 目录 agent 产物**：`decide_trace.jsonl`（25 行 v1/v2 混合轨迹）、
  `agent_loop_summary.json`、`omission_states.jsonl`（36 行）按用户裁定**保留**
  作缺陷修复证据。
- **审查缓存 v4 一次性失效**：P1-d 升 `llm-review-cache-v4` 后旧缓存全 miss
  （安全方向），首次全量审查会慢一轮，属预期。

## 参考文档

- 总纲：`docs/agent-rollout-plan.md`（路线/铁律/阶段前置/搁置记录）
- 规格：`docs/agent-phase0-spec.md`、`agent-phase1-spec.md`、
  `agent-phase1.5-spec.md`、`agent-phase2-spec.md`、`agent-eval-v2-spec.md`
- CLI：`docs/cli-contract.md`（agent_eval / agent_loop / agent_compare /
  review tool-loop 用法）
- 决策日志：`CLAUDE.md`（各里程碑与实证数据）
