# Unit Router Shadow 真实语料统计（M2 完成条件）

**日期：** 2026-08-17
**语料：** Appendix 9-ABNT NBR 16968-2022 EN.docx（默认 KB 解析，M0 基线同源 parse）
**产物：** `out/m0-abnt-2026-08-16/parse/unit_routing_decisions.jsonl`（`unit-router-v1`，零 LLM）

## 路由分布（4285 单元）

| 路由 | 数量 | 占比 | 主要构成 |
|---|---:|---:|---|
| a_track | 2292 | 53.5% | table_row 1711 / table_cell 580 / clause_segment 1 |
| b_track | 88 | 2.1% | clause_segment 52 / table_cell 30 / table_row 6 |
| mixed | 26 | 0.6% | table_row 26 |
| context | 1377 | 32.1% | narrative 539 / table_cell 671 / table_row 157 / heading 10 |
| review | 502 | 11.7% | table_cell 485 / clause_segment 17 |

规则分布：hard_a_only 2292、context_by_disposition 828、context_by_kind 549、
hard_b_only 88、hard_ab_mixed 26、review_disposition 477、review_weak_signal 14、
review_no_signal 11。

## 证据质量抽查

a_track 的证据主力是 **cosem_context（2284）**——本语料含真正的 COSEM 对象表
（TBL-000031 等：OBIS `0-0:41.0.0.255`（SAP Assignment，class 17）、
`0-0:40.0.0.255`（Association LN，class 15）），行带 `cosem_object_context`。
OBIS 406 / class_id 450 佐证。即：**误判抽查未见假阳性主驱动**；a_track 大占比
是"混合文档含 DLMS 对象附件"的真实结构。

## 与方案论断的对照

- 当前默认管线对该文档做**文档级 2 次调用 / 115,851 tokens** 的整文档直抽
  （M0 实测），且守恒失败（duplicates=6）。
- 单元路由视角：53.5% 是确定性 A 型（COSEM join，零 LLM 可得），仅 2.1% B 型 +
  0.6% Mixed 真正需要 B 轨付费提取，11.7% review 物化待专家。
- 这直接支持 §27.3 指标："Context 单元 provider calls = 0" 与
  "B 单元触发无消费者 A review = 0" 在 unit 路由下的可达性。

## 未完成（如实）

- truth-set 对照（§17.5：legacy 整文档 vs unit 路由的 P/R/F1 对比）需要
  WS0 人工真值集；未建前不做默认翻转（§31 红线）。
- review 502 中 477 来自 table_dispositions 的既有 review 候选（cell closure
  语义），与路由无关——路由只是如实物化。
