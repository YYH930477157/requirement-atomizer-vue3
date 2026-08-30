# WS0 真值门禁重跑结果——FAIL（与 08-17 根因构成不同：两旧根因实证已修，新暴露 A 轨空行缺陷 + 余额 402 截胡）

**日期：** 2026-08-30（08-29 深夜启动，`next-steps-plan-2026-08-29.md` 任务 B；按任务 A 的
No-Go 建议以 **flag 关**形态跑）
**命令：** `PYTHONPATH=. RATOMIZER_CONTEXT_PACK_STRATEGY=clause_family RATOMIZER_LLM_API_KEY=<env> python tools/ab_runner.py --parsed-dir out/abnt_nbr_16968 --template "C:\Users\YYHwudi\Desktop\Canna-29\电表软件标准化需求列表-V2.3.12 - 2026-4-14..xlsx" --route openai_compatible --truth golden_sets/ws0_human_v1/truth.jsonl --thresholds golden_sets/ws0_human_v1/thresholds.json --out out/ab-gate-report-rerun-2026-08-29.json --keep-dirs`
**退出语义：** FAIL（报告 `overall_verdict=FAIL`；运行 wrapper 的管道吞了进程退出码，
报告 JSON 为权威——`out/ab-gate-report-rerun-2026-08-29.json`，schema `ab-runner-report/v3`）

## 失败明细（两条，任一即 FAIL）

1. **A_atoms（原子化轨）：最终 XLSX 60 条空正文行**。读取器已能正确定位正文列
   （08-17 的表头别名缺口实证已修——本腿成文 932 行全部可读），但模板追加行中
   60 条只写了序号、正文列全空。抽样证据（`ab-runner.hywzdhbl/A_atoms/软件需求列表-成文.xlsx`）：
   - 状态字需求 sheet r4-r6：仅序号 2/3/4，子模块/描述/需求/说明全空（r9 起的追加行内容完整）；
   - 事件需求 sheet r6-r8：仅序号 4/5/6，其余全空。
   **分诊：写入侧问题**（`template_writer` 序号分配与合成载荷不齐——状态字/事件类
   表格派生需求的行载荷缺失；非读取器列映射问题）。根因定位到 file:line 需开修复
   任务，本报告只钉症状与证据。
2. **B_direct（直抽轨）：execution_status=failed**——**key 余额耗尽（HTTP 402）**，
   functional-extract 在 171/176 条款处余额见底，末段 6+ 条款包退 stub
   （stub 降级如实记 failed，绝不冒充）。**非管线缺陷，是经费截胡**。
   **重要正向事实：B 轨 conservation_ok=True（176 FRE，ABNT 真实语料守恒闭合）**
   ——08-17 根因 #2（duplicates=6 确定性失败）实证已修。

## 与 2026-08-17 FAIL 的根因对照

| 08-17 根因 | 本次状态 |
|---|---|
| ① XLSX 读取器表头别名不命中（A 轨成文不可读） | **已修实证**：932 行全部读出，空正文行是写入侧新问题 |
| ② B 轨守恒失败（duplicates=6，文档级 flash 直抽） | **已修实证**：clause_family 策略下 cons_ok=True |
| ③ guards 表格 marker 假失配 | 无复发（B 轨 evidence 检查未报假失配） |
| （新）A 轨合成/模板写入空正文行 | **新暴露**，待修复任务 |
| （新）402 余额耗尽 | **复发**（08-17 同样末段 402） |

## 成本账（§5.3 纪律：余额是支付权威）

- 门禁总花费 **≈¥36.43**（余额 ¥35.73 → **-¥0.70 透支**，`is_available=false`）；
  A 轨 343 节抽取 1001 原子为主要项，B 轨 176 条款直抽进行到 171/176。
- 两腿工作目录（chain 内嵌运行）未落 llm_trace/run.log，per-leg token 拆分
  不可得——如实记录，余额差为总账权威。
- 工作目录已用 `--keep-dirs` 保留：`%TEMP%\ab-runner.hywzdhbl\`（A/B 两腿完整产物
  + A 腿 `ai_extract_cache.jsonl` 343 节抽取缓存）。

## 结论与下一步

- **三态：FAIL**（真值/阈值齐备非 NO_GATE；失败为上述两条）。
- 重跑前置顺序（缺一重跑必再 FAIL 或浪费钱）：
  1. **先修 A 轨空正文行缺陷**（修复任务：`template_writer` 追加行为什么只有序号
     没有载荷——状态字/事件类需求在合成侧的载荷去哪了）；
  2. **key 充值**（当前透支 -0.70；重跑预算 **≈¥8-12**：A 轨用
     `--warm-a-cache %TEMP%\ab-runner.hywzdhbl\A_atoms\ai_extract_cache.jsonl`
     抽取零付费，B 轨 176 条款重付 ≈¥5-7 + 余量）；
  3. 重跑同命令 + `--warm-a-cache`，报告归档新路径。
- 本次已得的正向证据保留：A 轨全链在 flash 上可出 932 行成文（08-17 即证，本次复核）；
  B 轨守恒在真实语料闭合（新）；阈值门未走到（failures 短路优先）。
