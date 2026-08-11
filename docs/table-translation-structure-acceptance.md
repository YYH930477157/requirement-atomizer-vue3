# 表格呈现与翻译结构化验收

日期：2026-08-11
分支：`codex/table-translation-structure`

## 交付范围

- `full-translation-v2` 将规整表格拆为题注、真实表头行、数据行三级翻译单元，不再把拍平 `block.text` 发送给翻译模型。
- 行文本复用 `ai_extract._row_render_line`，缓存键继续使用现有内容 SHA；相同行只生成一个键，二次运行全部命中时零新增调用。
- `document-translation/v2` 对表格嵌套行三态、来源单元格、物理行号、模型与策略 provenance 做严格 schema 约束。
- 全文双语 HTML 使用真 `table` 呈现原文行和译文行；横向单行合并保留 `colspan`，纵向合并与嵌套表诚实降级。
- fallback 及混合合成表头中的 `column_N` 不进入翻译输入或 HTML。
- `table-structure-v8` 识别连续三列以上 `(a)…(j)` inline/stacked 复合表头，展示列名去除字母前缀，evidence 仍保留识别依据。

## SBD 实证

隔离目录：`out/table-translation-structure-acceptance-20260811/`

- 输入仅取现有 SBD 结果中的 `BLK-000215` 与 `BLK-000221`，未修改正式结果包，未调用付费模型。
- `BLK-000221` 输出为 `record_kind=table`；5A、5B、6A-6D、GRAND TOTAL 均出现在结构表格中，末行横向合并呈现为 `colspan=5`。
- HTML 不含 `column_\d+` 可见文本；221 的题注、表头和数据单元全部为 `translated`，表格行统计为 translated 7 / failed 0 / skipped 0，覆盖率 100%。
- `BLK-000215` 含纵向多层复合合并，输出为 `record_kind=complex_table` 并明确显示“复杂表按原文展示”。
- 两条 `document_translations.jsonl` 记录均通过 `document-translation/v2` Draft 2020-12 schema。

## 回归覆盖

- 真表格 `figure/thead/tbody` 与中英行对照。
- 表格物理行号和 `_row_render_line` 逐字一致。
- fallback/混合合成表头隔离。
- 重复数据行内容哈希去重与二次运行零调用。
- 单行失败向表块汇总为 `table_rows_failed:N`，失败行译文保持空串。
- 横向合并结构化与纵向合并降级。
- inline/stacked 字母复合表头正例，以及短序列/规范性句负例。

## 最终验证

- `python -m unittest tests.test_full_translation`：12/12 通过。
- `python run_smoke.py`：90 modules / 1,649 tests，全部通过，111.982 秒。
- 设置 `RATOMIZER_HISTORICAL_SAMPLE=C:/Users/YYHwudi/Desktop/Canna-29/eval_assets/test18_functional_synthesis_sample.json` 后运行最终版后端全量：3,446 tests，全部通过，236.738 秒。
- `ui/` 下 `npm test`：12 files / 264 tests，全部通过。
- `ui/` 下 `npm run build`：`vue-tsc --noEmit` 与 Vite production build 通过；仅保留既有 chunk size warning。
- 修改 Python 文件 `py_compile`、三个 JSON schema 解析、仓库密钥全文扫描与 `git diff --check` 通过。
