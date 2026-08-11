# Agent v5 近期改动验收记录

日期：2026-08-11

## 已完成

- T-1：收紧数字枚举边界，`CLASS 1)` 不再误剥；共用归一化同步修复。SBD 全文验收继续发现目录清洁文本与护栏原文口径不一致，最终护栏升为 `annotation-translation-guards-v5`：校验、缓存复验和失效判定统一使用模型实际可见文本，不放宽数字/编码/单位保护。
- T-2：恢复仓库冒烟层，`run_smoke.py` + `tests/smoke.txt` 固化为 90 模块 / 1,649 个 `unittest`；本机实跑 1,649/1,649，通过耗时 112.029 秒。
- T-3：新增 `context_submit.submit_with_context`，统一 5 个模块、6 个生产线程池 LLM 提交点的 `ContextVar` 传播；AST 门禁禁止回归为裸 `submit`。
- T-4：新增 `full-translation` chain/CLI 阶段，默认由 `RATOMIZER_FULL_TRANSLATION=1` 开启；使用 `annotation_translations.json` 同键缓存，输出 `document_translations.jsonl`、`document_translation.html`、`clarification_questions_bilingual.html`，并把覆盖率、三态计数和调用账目写入 `quality_report.json`。阶段有独立 producer、结果包注册和 `full_translation` 预算段。
- T-6：Vue 工作台加入全文翻译阶段；需求表采用固定行高窗口化；批量接受只处理当前筛选范围内置信度不低于 0.90、低歧义、未终审的需求，并逐条携带 CAS 指纹写入。

## T-5 评估结论

- D3 两栏定义表保持 `RATOMIZER_PDF_TWOCOL_DEF=0`。当前只有 SBD 单文档零误触证据，没有跨文档人工真值集，不满足转正门槛。
- 现代解析器保持 `RATOMIZER_PDF_MODERN_PARSER=0`。本机 2026-08-11 探测结果为 Docling 未安装、Marker 未安装，无法对 SBD p23 等边界页做有效 A/B；手写解析路径暂不退役。

## SBD 全文真实 LLM 验收

- 隔离目录：`out/sbd-full-translation-v5-acceptance-prompt-v5-20260811/`。原始 SBD 结果包未修改，客户文本、缓存、trace 和抽样文件均留在 git-ignored `out/`，不入仓。
- 最终策略：`deepseek-v4-flash` / `translation-prompt-v5-greedy-splithalf-b10-c8000` / `annotation-translation-guards-v5`。`prompt-v5` 把护栏检出的缺失 token 明确反馈为逐个原样保留清单；`guards-v5` 修正目录点引导线/尾页码已在发送前清理、护栏却仍要求保留的假拒绝。
- 完整性：899 个 block 全部有唯一三态记录；translated 891、failed 8、skipped 0，覆盖率 **99.11%**，通过不低于 99% 门禁。失败中 rejected 7、unresolved 1，均保留失败状态，没有以原文或 stub 冒充译文。
- 产物：`document_translations.jsonl` 899/899 行通过 `document-translation/v1` schema；双语全文 HTML 与澄清双语 HTML 均为有效 UTF-8，未发现替换字符。
- 抽评：按 block_id SHA-256 排序，从 40..600 字符的成功块确定性抽取 20 条，逐条检查为 20/20 可接受；样本证据仅存本机 `human_review_sample_20.json`，不提交客户原文。
- 成本：最终修复后的增量验收为 40 calls / 204,133 tokens；从干净 v4 首验到 prompt-v5、guards-v5 两轮返修的研发验收累计为 498 calls / 1,583,211 tokens。预算未耗尽，货币价格未由接口返回，因此不补造金额。
- 全文翻译独立预算默认由 120 calls 调整为 360 calls，token 硬上限仍为 2,000,000；899-block 首验曾在 120 calls 时仅消耗 447,434 tokens，证明旧调用上限漏计严格护栏的单条/句段重试。

## 尚需外部验收

- D3 跨文档误触率与现代解析器 A/B 需要独立标注语料及可用解析器依赖后重跑。

## 最终回归

- 后端：设置历史样本环境后 `python -m unittest discover -s tests`，3,437 tests 全部通过。
- 冒烟：`python run_smoke.py`，90 modules / 1,649 tests，1,649/1,649 通过。
- 前端：Vitest 264/264 通过；`npm run build`（`vue-tsc --noEmit` + Vite）通过。
- 产物/源码：修改 Python 文件 `py_compile` 通过，`git diff --check` 通过；SBD 899 行 schema 校验零错误。
