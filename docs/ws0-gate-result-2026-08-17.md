# WS0 真值门禁结果——FAIL，默认不翻转

**日期：** 2026-08-17（用户当日在会话中明确授权：真值=Canna29 需求条目化 xlsx 的
Chinese Analysis 列、document_id=abnt_nbr_16968、阈值=运行手册示例值起步）
**命令：** `PYTHONPATH=. RATOMIZER_LLM_API_KEY=<key> python tools/ab_runner.py --parsed-dir out/abnt_nbr_16968 --template "…电表软件标准化需求列表-V2.3.12….xlsx" --route openai_compatible --truth golden_sets/ws0_human_v1/truth.jsonl --thresholds golden_sets/ws0_human_v1/thresholds.json --out out/ab-gate-report.json`
**退出码：2（FAIL）→ 依据承诺与 §31 红线：`RATOMIZER_EXECUTION_POLICY` 默认保持
`legacy_combined`，不翻转。** 报告：`out/ab-gate-report.json`。

## 失败明细（两条，任一即 FAIL）

1. **A_atoms（原子化轨）**：链本身**完整跑通**——343 节抽取、996 原子、最终成文
   **1847 行**；但门禁的最终 XLSX 读取器在本模板（V2.3.12 的 计量需求/事件列表
   等 sheet）上**表头别名不命中**（需求正文列识别失败）→ 按门禁 fail-closed 语义
   判 FAIL（不可验证的交付物=失败）。这是门禁读取器的别名缺口，非管线失败。
2. **B_direct（直抽轨）**：`requirements-analysis` 被守恒门阻断
   （duplicates=6；evidence_presence=0）→ 无成文交付。与 M0 基线相同的
   deepseek-v4-flash 文档级直抽确定性失败（真实质量问题）。

## 过程事实

- 门禁累计两次运行：首跑暴露 `ab_runner.PARSED_ARTIFACTS` 漏复制
  `table_cell_dispositions.jsonl`（A 轨 ai-extract 被迁移门诚实拒绝）——已修复
  （+dispositions，tests/test_ab_runner.py 全绿）后重跑；另需 `PYTHONPATH=.`
  （脚本目录运行时仓库根不在 sys.path）。
- **末段出现 HTTP 402（key 额度耗尽）**：B 轨后期调用失败源于余额；即使无此问题，
  B 的守恒失败在 402 之前已成立，判定不变。
- 真值：190 行（转换自用户指定 xlsx 的 Chinese Analysis 列 + Subtítulo Nível 1
  节号，`tools/truth_from_review.py`，对 `abnt_nbr_16968` 选行 190/190）。

## 结论与下一步

- **quality_first 默认翻转未获门禁通过，不执行**；legacy 路径保留，一切既有能力
  可用。判定依据已落盘，可复查。
- 真实修复路径（按方案）：
  1. B 轨守恒失败 → 方案 §17 的 clause_family/unit 级上下文（M4/M5 机械已就绪，
     接 functional-extract 的 unit 输入后重评）；
  2. 门禁 XLSX 读取器别名 → 补 V2.3.12 模板各 sheet 的正文列表头（读取器修好即可
     复评 A 轨——A 轨本次已证明全链在 flash 上可出 1847 行成文）；
  3. key 额度恢复后可重跑门禁（成本参考：本次 A 轨 343 节抽取为最大项）。
