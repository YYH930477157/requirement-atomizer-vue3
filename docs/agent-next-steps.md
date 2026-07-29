# Agent 化待办方案（2026-07-28 快照）

当前进度：Phase 0 ✅ → Phase 1 ✅（v2 修复）→ Phase 1.5 ✅（裁定：规则保持默认）→
Phase 2 ✅（工具化审查 + WP2 待澄清/兜底渲染）→ 专家审核十项修复 ✅（main `e32770a`）
→ 专家审核第二轮十三项修复 ✅（main `e3ad2a7`，1627 tests / golden 6/6）
→ **Claim Conservation Ledger Phase 0A/0B ✅（main `a08a60a`，shadow 双写不切生产门控；
总纲 `docs/agent-claim-ledger-spec.md` v2.4）**
→ **Claim Ledger Phase 1 ✅（已合 main `617e1ce`，生产双写不切门控；主检出全量 2106
tests OK、golden 6/6 退出门通过；总纲 v2.4 + Phase 1 规格 v1.4）**。
下一步主线：Claim Ledger **Phase 1.5**（闭环故障恢复验证 + A/B 写入口 review-revision CAS +
启用 claim mutation，唯一通道 targeted_reextract；规格未冻结，等用户指示开工）。
Phase 3（Orchestrator）**搁置**（2026-07-23 用户裁定：编排层增量价值待 Phase 2 真实
项目验证后再议）。

## 待办清单（按优先级）

### 1. 轮换 deepseek API key（用户本人，5 分钟，最优先）

- 原因：key 曾于 2026-07-22 明文出现在 AI 会话记录中，应按泄露处理。
- 动作：deepseek 控制台吊销 `sk-87ca...c1ae`，签发新 key；本机以
  `RATOMIZER_LLM_API_KEY` 环境变量配置，不落任何文件/仓库。
- 验收：新 key 跑一次 `python llm_pipeline.py --out <副本> --llm-route
  openai_compatible --llm-review-limit 1` 成功即可。

### 2. Claim Ledger Phase 1.5 规格冻结（半天讨论 + 半天成文，Phase 1.5 前置）

- Phase 1 已合 main `617e1ce`（golden 6/6、全量 2106 OK），生产门控未切换。
- Phase 1.5 范围（总纲 v2.4 §9）：闭环故障恢复验证（真实 `os._exit` 崩溃矩阵扩展到
  effective WAL、锁序反序注入、interrupted fold 的 health 登记）、A/B 写入口
  `expected_target_fingerprint`/`expected_target_review_revision` CAS、启用 claim 级专家
  写入与定点补抽 mutation（唯一通道 `targeted_reextract`）、mutation 失败补偿与并发冲突、
  ledger-only cache rebuild、downstream incomplete_inputs 贯通。
- Phase 1 审查延后项一并纳入：publish 后双重 fold 去重、hook 门控加轨道校验、
  acceptance/review_packet 换显式三层 API、`decide_trace.jsonl` 入零-mutation 守卫监视、
  clarification entries TIER 前后对比断言、启动 fold 的 fresh 短路。
- 规格必须先冻结经确认再动工（总纲硬性前置）。

### 3. 评测集 20 条扩充案例人工核对（用户/领域专家，约 1–2 小时）

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

### 4. WP2 的 test3 真实复验（Phase 2 规格 §8.5 遗留，约半天）

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

### 5. ~~grouping 基线 0.5 改进（确定性聚类规则）~~ **已完成（2026-07-23，main `67216b5`）**
- 三规则落地：周期档位分家（审核人裁定）、对象词组合并（误拆修复）、变体护栏
  （编号/制式不同不并）；agent_eval grouping **4/8 → 8/8**，生产影响实测为零
  （test2/test3 新旧逐组一致）；`FUNCTIONAL_SYNTHESIS_VERSION` 升 v7。

### 6. worktree 清理（10 分钟）——✅ 已完成（2026-07-25，Kimi Work 执行）

- 执行时文档所列 7 个 worktree/分支已被此前清理删除；实际剩余为
  `requirement-atomizer-vue3-remediation` worktree + 10 个 `codex/*` 分支。
- 核实全部 10 个分支均已合并进 main、remediation worktree 工作区干净且
  落后 main 38 个提交后：移除该 worktree、`git worktree prune`、
  `git branch -d` 删除全部 10 个分支。
- 终态：单一 worktree（main `97c3ce7`），本地仅剩 main 分支。

### 7. ~~重新打包桌面应用~~ **已完成（2026-07-23）**
- 新包 `ui/dist/标准需求抽取与审查平台 0.1.0.exe`（192MB，与旧包同量级），含全部
  修复：专家审核两轮、锚点一致化（guards-v11/review-tools-v3）、WP2 v3、
  grouping v7；包内代码版本已抽查核实。旧包备份在 `ui/.pkg-backup/`。
- **打包教训（留痕）**：electron-builder `files` 含 `dist/**/*`，构建前必须清
  `dist/`——否则历史 win-unpacked/旧 exe 被递归打进新包（本次先产出 581MB 废包，
  清 dist 后回 192MB）。

### 8. must_ask 语义档自动判定评估（不急，Phase 2 稳定后）

- 背景：must_ask 类 10 条中 6 条语义型陷阱标记 `judge_note: "manual"`，
  不计自动通过率分母——信息充分性判断当前只能靠人。
- 方向：Phase 2 tool-loop 在真实项目稳定后，评估用带工具的 LLM 判定这 6 条
  （判定过程也必须过幻觉护栏，判定器本身先拿 4 条已稳定案例校准）。
- 不做：在 LLM 判定没校准前，不得把 manual 档计入自动基线。

### 9. 默认方案显式标注政策（审核人 2026-07-23 裁定，待立项）

- 背景：人工核对 must-ask-002/003/004 与 hallucination-001 时审核人裁定——原文
  确实未提及的参数**可以按默认方案做，但必须显式标注"这是默认方案，不是客户
  需求"**；与既有 `developer_guidance`"公司通用做法："标注通道同向。
- 口径：**参数类**（响应时间/费率数/阈值/周期等）允许默认方案 + 标注；
  **编码/文号类**（OBIS、标准号、事件码）永远不允许默认——错一位即严重，
  无依据只能"待澄清"。
- 评测语义不变：must_ask/forbidden 判的是"无标注地把缺省值当需求写死"，
  四条相关案例保持原判（ask/reject）。
- 待立项：默认方案的标注格式与承载通道（developer_guidance"公司通用做法："是否
  承载）、与"待澄清"占位的边界、进哪一阶段规格。

## 观察项（不占专门时间）

- **瞬时测试 error**：Windows 文件占用类抖动留痕过一次（2026-07-22 主检出），
  复跑均绿；再出现必须抓到具体测试名再处理。
- **test3 目录 agent 产物**：`decide_trace.jsonl`（25 行 v1/v2 混合轨迹）、
  `agent_loop_summary.json`、`omission_states.jsonl`（36 行）按用户裁定**保留**
  作缺陷修复证据。
- **锚点一致化已修（main `24a7b21`，guards-v11）**：批注蓝区=原句跨越块集、
  section_fallback 按小节收窄；**test5 需用新 key 重跑抽取**才能吃到收窄
  （可与待办 4 的 WP2 复验合并成一次重跑）；块内相邻句仍可能进框（块粒度），
  句级裁剪留作后续立项。
- **审查缓存 v4→v5 一次性失效**：第二轮修复升 `llm-review-cache-v5`（schema 修复
  续接 transcript 行为变化）后旧缓存全 miss（安全方向），首次全量审查会慢一轮，
  属预期；llm-review 阶段指纹结构变化同样令旧阶段产物自然失效一次。

## 参考文档

- 总纲：`docs/agent-rollout-plan.md`（路线/铁律/阶段前置/搁置记录）
- 规格：`docs/agent-phase0-spec.md`、`agent-phase1-spec.md`、
  `agent-phase1.5-spec.md`、`agent-phase2-spec.md`、`agent-eval-v2-spec.md`
- CLI：`docs/cli-contract.md`（agent_eval / agent_loop / agent_compare /
  review tool-loop 用法）
- 决策日志：`CLAUDE.md`（各里程碑与实证数据）
