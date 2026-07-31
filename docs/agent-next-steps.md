# Agent 化待办方案（2026-07-30 下班快照）

当前进度：表格行级化 Phase 1+2 ✅、影印支路+行热区+行区切片 ✅、专家审核十项修复 ✅、
claim-ledger（远端）Phase 0A/0B→1→1.5 ✅（shadow 观察期，未切门控）、
影印页图并发加载 ✅。main 与 origin 同步（`c46877a`）。

## 待办清单（按优先级）

### 1. 轮换 deepseek API key（用户本人，5 分钟，最优先）
- key 曾明文出现在 AI 会话记录中，按泄露处理：控制台吊销 `sk-87ca...c1ae` 重发；
- 本机以 `RATOMIZER_LLM_API_KEY` 环境变量配置，不落文件/仓库。

### 2. ~~评测集 20 条扩充案例人工核对~~（✅ 已完成，本条为旧快照留痕）
- 已于 **2026-07-23 由审核人本人逐条核对并登记**：manifest `human_review_status: reviewed`、
  `unreviewed_count=0`（29 条维持原判、3 条改判、1 条授权补判、4 条默认方案标注政策，
  详见 manifest curation statement）。2026-07-30 快照误沿用旧状态。
- 2026-07-30 复验：`agent_eval` 跑通 unreviewed=0，`tests.test_agent_eval` 5/5 绿。
- 遗留观察（非本待办）：classification 基线 0.6667（classify-003/004/006/010 期望
  hardware 但无确定性关键词命中被默认 software）——规则层已知缺口，可归入待办 4 同类
  规则改进另行评估。

### 3. STO atomize 性能优化（新浮出，1–2 天）
- 卡死修复后 203s 仍偏慢（claim catalog 对 ~391 表格行的处理是热点方向）；
- 动作：cProfile 定位（faulthandler 已备好用法），目标 ≤60s；
- 注意：`source_spans` 行级 diff 已在（`cac9273`），勿重复修。

### 4. grouping 基线 0.5 改进（确定性聚类，1–2 天）
- `functional_catalog.build_function_catalog` 零 LLM 聚类在 8 个评测案例对上 4 错；
- 先看 `agent_eval` 的 grouping_details 失败模式（误并 vs 误拆），改规则层，不引入 LLM；
- 动它必须 bump `FUNCTIONAL_SYNTHESIS_VERSION` 并更新 chain 戳测试；不许改案例刷分
  （案例修改走待办 2 的人工核对通道）。

### 5. WP2 的 test3 真实复验（规格 §8.5 遗留，半天）
- 用有效 LLM key 在 test3 副本上重跑 analyze（--llm-route openai_compatible）：
  拒/无据字段全部"待澄清"+`clarify_fallback` 底稿、open_questions 进澄清报告、
  xlsx 显示"待澄清+标注原始候选"、有据字段逐字节不变；
- 结果记入 `CLAUDE.md` WP2 条目。

### 6. claim-ledger 规格文档回写（远端团队，半天）
- Phase 1 规格写"零 mutation、无 POST"，代码已有裁决写入（Phase 1.5 的
  `apply_claim_adjudication`/POST 接口/queue v2/CAS）；事件 schema 已 v2（规格写 v1）；
- 按代码实况回写 `docs/agent-claim-ledger-phase1-spec.md`，避免后来人误读。

### 7. claim-ledger Phase 2 切生产门控（决策点，不是纯工程）
- 前置全部未满足：成本门（唯一真实演练调用增量 100% > 25% 上限）+ golden held-out
  人工裁决未完成；
- 切门意味着"有 open claim 就不 READY"——这是改变 READY 门语义的决策，需用户+
  专家明确批准，不能顺手做。

### 8. 打包版本号（工程卫生，30 分钟）
- 所有 exe 同名 `标准需求抽取与审查平台 0.1.0.exe`，手上多个包分不清；
- 建议 electron-builder 产物名带日期+关键版本戳（如 `平台-2026-07-30-guards-v17.exe`），
  或至少 `package.json` version 递增并反映到产物名。

## 观察项（不占专门时间）

- **影印加载**：已改 6 路并发（04:40 的包）；若仍慢，下一档是视口优先懒加载。
- **claim 面板 "unknown"**：是"影子验证未授权预算"的诚实默认值，非 bug；
  如要 UI 改人话（"未判定（影子验证未授权）"），一行改动，需要就说。
- **瞬时测试抖动**：Windows 文件占用类，三次留痕；再出现抓具体测试名。
- **test3 目录 agent 实验产物**：按用户裁定保留。
- **STO 几何解析 71.5s**：有缓存只疼第一次，可做增量/异步（不急）。

## 参考文档

- 总纲：`docs/agent-rollout-plan.md`
- 表格行级化：`docs/table-granularity-plan.md`（最终方案）+
  `docs/param-row-extract-phase2-spec.md`（Phase 2 冻结规格）
- 规格：`docs/agent-phase*-spec.md`、`docs/agent-eval-v2-spec.md`
- CLI：`docs/cli-contract.md`；决策日志：`CLAUDE.md`
