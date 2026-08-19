# M0 冻结基线报告——ABNT NBR 16968 Appendix 9（默认链，DeepSeek）

**日期：** 2026-08-17（runner `tools/m0_baseline.py`，两轮冷/热，第二轮带 llm_trace）
**语料：** `Appendix 9-ABNT NBR 16968-2022 EN.docx`；默认 KB；route `openai_compatible`
（base_url `https://api.deepseek.com`，model `deepseek-v4-flash`，温度 0）
**原始数据：** `docs/m0-baseline-abnt-2026-08-16.json`（第一轮，无 trace）、
`docs/m0-baseline-abnt2-2026-08-16.json`（第二轮，trace 口径，**以下数字以第二轮为准**）
**运行目录：** `out/m0-abnt-2026-08-16/`、`out/m0-abnt2-2026-08-16/`

## 冷跑成本（缓存全空，逐阶段 trace 计量）

| 阶段 | 调用数 | tokens | 时长 | 说明 |
|---|---:|---:|---:|---|
| functional-extract（ai-extract 槽，文档级 prompt） | 2 | 235,798 | 109.7s | legacy 文档级大包：全文档≈2 个巨型请求 |
| assemble / spec_enrich | 0 | 0 | 2.6s | B 模式无原子可富化 |
| requirements-analysis | — | — | 0.1s | **守恒未闭合阻塞**（duplicates=6；evidence_presence=0） |
| template-write / clarification-report | — | — | 0s | 连带阻塞（如实失败） |
| full-translation | **344** | **1,175,500** | 1,226.0s | **冷跑成本大头（82.6% tokens）** |
| export-annotation-html（marker 补翻） | 4 | 10,948 | 94.9s | 批处理后仅 4 次 |
| **合计** | **350** | **1,422,246** | ~24min | |

## 热跑（同目录复跑）

| 阶段 | 调用数 | tokens | 说明 |
|---|---:|---:|---|
| functional-extract | **2** | **235,798** | **重付**：冷跑 execution_status=failed → 失败结果不缓存（既有正确语义），每次复跑重付直抽 |
| full-translation | **0** | 0 | sidecar 全量复用（冷 1,226s → 0.4s）✓ |
| export-annotation-html | 0 | 0 | marker 缓存复用 ✓ |

## 效果（冷/热同）

- functional 产品：358 items，execution_status=**failed**，conservation_ok=**False**
  （guards `functional-extract-guards-v5` / prompt `functional-extract-prompt-v3`）
- 守恒失败 → 成文模板/澄清报告被 blocking gate 如实阻塞；**无 软件需求列表-成文.xlsx**。
- 两轮冷跑失败形态一致（duplicates=6）→ deepseek-v4-flash + 文档级 118k-token 巨型
  prompt 的确定性失败模式，不是偶发。

## 结论（供方案决策）

1. **翻译是冷成本大头**（82.6% tokens）——方案 §12/§13 翻译交付模式（off/markers）
   是最大的单点成本杠杆；M6 已交付 off=零调用强制。
2. **文档级直抽在 flash 模型上守恒失败**——方案 §17（clause_family/unit 级上下文
   增量化）既是成本路径也是**效果修复路径**；在此之前该文档无法过守恒门。
3. **失败运行没有热复用**——守恒失败的直抽每次复跑重付 235,798 tokens；修好效果
   （ok 才缓存）本身就是成本优化。
4. **计量口径：llm_trace 是成本权威**——预算账本（RATOMIZER_LLM_BUDGET=1）在逐阶段
   调用下会重建账页（跨阶段 delta 为负），且 export/default 段归属不完整；
   trace 逐行含 usage，两口径冷跑合计可互证（functional_extract 段一致）。
5. 对照 M2 shadow 路由（`docs/unit-routing-shadow-abnt-2026-08-17.md`）：该文档
   53.5% 单元是确定性 A 型（COSEM 对象表），2.1% 真正需要 B 轨付费——单元路由
   消除的是"无消费者付费工作"，与 §27.3 指标一致。

## 未覆盖（如实）

- llm-review（A 轨 tool-loop review）不在 CHAIN_ORDER 默认链，本基线未计（口径决定）。
- 燃气表 PDF / Blue Book 两类文档未跑（第一轮已证明 runner 可复用；补跑是机械工作）。
- truth-set P/R/F1：无 WS0 人工真值集，NO_GATE（与 ab_runner 语义一致）。
