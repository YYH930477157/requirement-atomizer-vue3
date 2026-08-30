# WS0 真值门禁重跑 v2 结果——FAIL（B 轨 partial，失败面缩至 25 绑定 + 3 preservation；A 轨首次完整通过）

**日期：** 2026-08-30（用户预算 ≤¥20）
**命令：** 同 `docs/ws0-gate-result-2026-08-30.md`，差异：`--warm-a-cache %TEMP%\ab-runner.hywzdhbl\A_atoms`（A 轨 343 节抽取缓存复用）+ 当前 main（`e1c1fee`：路由 v7 / conservation v6 / template_writer v2 / extract floor 24576）
**退出码：2（FAIL）**；报告 `out/ab-gate-report-rerun2-2026-08-30.json`；工作目录 `%TEMP%\ab-runner.9gqsr665`（--keep-dirs，含**完整 343 节 A 抽取缓存**，供后续更暖重跑）

## 成本账（≤¥20 达标）

- **总花费 ¥17.80**（余额 49.29→31.49）：A 轨 ¥14.18（warm cache 命中省 ≈¥27——首次启动误传文件路径在付费前 fail-loud，零损失重启）+ B 轨 ¥3.62
- B 轨单条款 ¥0.026（上次 SBD 口径 ¥0.041）——extract floor 24576 消灭截断重试浪费的直接证据
- 无 402、无 stub 降级

## 判定明细

| 腿 | 结果 | 数据 |
|---|---|---|
| **A_atoms** | **ok=True（首次完整通过）** | 902 FRE / 894 成文行 / 无错误——template_writer v2 空正文行修复实证生效（上次 60 条空行 FAIL） |
| **B_direct** | FAIL（exec=partial） | 抽取完整 176/176 条款、225 FRE；守恒闸拦下 analysis/成文 |

## B 轨失败面（本轮核心增量信息——小而真实）

| 守恒项 | 结果 | 明细 |
|---|---|---|
| clause_coverage | ✓ | 0 未覆盖 |
| **obligation_coverage** | **✓（0 未覆盖）** | 路由 v7 + 碎片过滤 v6 在 ABNT 实证生效（剔 5 碎片）；上次"守恒闭合"是在 402 stub 截短产物上的假象 |
| duplicates | ✓ | 0 组 |
| **evidence_presence** | ✗ | **binding_mismatches=25**：`narrative_covers_other_clauses_not_declared`（跨条款借位叙述）+ `declared_section_has_no_local_obligation_coverage` |
| **preservation** | ✗ | **blocking=3**（Security 节：否定词 no + 数字 5/64）——对比 SBD 的 50 |

失败面从上次的"基础设施截胡"（402/stub/读取器）收敛为 **28 条可逐条核查的真实质量项**——门禁开始做它该做的事。阈值门未评估（failures 短路优先）。

## 下一步（若再战）

1. 28 条逐条归因（25 绑定：LLM 借位叙述 vs 无义务条款上的 FRE；3 preservation：Security 数值/否定）——修 prompt 或绑定校验的语义缺口；
2. 重跑成本进一步下降：本轮 A 轨缓存已**全量 343 节**（上轮仅 ~236），再跑 A 抽取仍零付费，B 轨 ¥3.6 级——**重跑全门禁 ≈¥5-8**；
3. B 轨过了守恒闸后，truth 阈值门（14 键）才会第一次真正评估。
