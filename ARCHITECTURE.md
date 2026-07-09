# ARCHITECTURE — Requirement Atomizer

> 给新工程师的系统地图（2026-07-06）。协作纪律与历史见 `CLAUDE.md`，待办见 `TODO.md`。

## 一句话

把客户技术标准（DOCX/XLSX/PDF）转成研发可落地的需求交付物：**确定性骨架 + 护栏化 LLM**——
数字/编码/结构永远走确定性通道，LLM 只做判断与叙述，且每步可溯源、可回归。

## 双轨

| | A 轨（DLMS profile 类文档） | B 轨（散文类标准） |
|---|---|---|
| 适用 | 对象表密集（如 ABNT NBR 16968） | 行为散文（如 EN 16314 / AFD） |
| 链条 | atomize 规则候选 → LLM 审查 → assemble P1-P5 | ai_extract → 批注裁决 → analyze → 成文 |
| 主交付物 | `dlms_cosem_spec.*`（实现规格） | **`软件需求列表-成文.xlsx`**（公司 V2.3.x 格式） |
| 知识注入 | 蓝皮书 RAG（接口类条款） | 模板知识 + 裁决样本库 + 澄清答复 |

## B 轨数据流（当前主战场）

```
parse(parsers/) → blocks.jsonl
  → ai_extract（extract_units 切分/引用/术语 + LLM + extract_guards 质量信号 + 自检环）
      → ai_requirements.jsonl（行契约：requirement_record）+ ai_extract_quality.json
  → 批注（DocumentReview.vue / doc_annotation_export.py，契约测试锁两侧等价）
      → ai_review_states.jsonl（专家裁决）→ adjudication_bank（few-shot 资产，env 指路）
  → requirements_analysis（规则归属 + LLM 富化：模板知识/范例/澄清答复注入，assumptions 契约）
      → engineering_analysis.json / software_requirements.xlsx
  → template_writer（确定性成文进公司模板）→ 软件需求列表-成文.xlsx
  → clarification_report（必答/参考分级 + 就绪判定）→ clarification_questions.xlsx
      ↺ 评审会答复 → import-clarification-answers → 下轮 analyze 作权威输入
```

编排：`desktop_tasks chain --out DIR --stages ...`（单命令全链，GUI 只发命令渲染进度）。
状态：每个输出目录 `run_manifest.json`（阶段/状态/producer 版本戳）。

## 关键机制（动之前先读）

- **防幻觉分级**：受保护编码（OBIS/hex/事件号）漂移=硬拦；普通整数=软标。基线可被
  跨条款引用/术语定义/澄清答复**有据扩展**，绝不被模板默认值/范例扩展（防搬运）。
- **缓存指纹**：章节文本+prompt 版本+模型+doc_context+注入内容（refs/terms）→ 任何输入变化
  自动失效。改 prompt 必须 bump `AI_EXTRACT_PROMPT_VERSION`/`ANALYZE_PROMPT_VERSION`。
- **产物血统**：JSON 产物带 `provenance`（producer/version/generated_at），消费端校验告警。
- **确定性检索哲学**：宁漏勿错（模板知识/蓝皮书/样本库全是词面匹配，零向量语义）。
- **回归裁判**：`corpus_eval`（碎片率/重复对/噪声/漏值/验收可测性/覆盖率）——动抽取必跑对比。
- **配置单源**：`config.ENV_REGISTRY`（测试强制核对全仓 RATOMIZER_* 变量）。

### 新增 LLM 输出通路检查单（同一病灶两天两现：2026-07-08 审计 B2 → 2026-07-09 硬件翻译）

任何让 LLM 输出进入交付物/评审面（xlsx、md、批注 HTML、few-shot 教材）的新通路，合并前逐条过：

1. **漂移基线**：写清"有据"的定义——源文哪些字段 ∪ 哪些授权注入（模板/答复/蓝皮书条款）；
   基线永不含范例与模板默认值（防搬运）。
2. **双向校验**：编码（extract_codes）硬拦——拒绝或移除，绝不只标记；数字（extract_ints）
   按字段性质定级——研发直接执行的字段（验收/指引/参数表/翻译）硬处理，叙述字段软标。
3. **标记随行**：软标必须钉在条目上（如 `enrichment_warnings`）并被所有渲染器（xlsx/成文/
   批注视图）呈现——只进 run 级 issues = 交付物零标记（B1 病灶）。
4. **出处落账**：route/model 进产物 provenance 与 run_manifest（stub 降级≠真 LLM 必须可区分；
   复用/续跑判定依赖它——见 `stage_is_reusable` 的方向性守卫）。
5. **两向回归**：漏（源文内容丢失）与编（无据内容出现）各至少一条测试；测试放
   `tests/test_audit_fixes.py` 同风格（名字带病灶编号可倒查）。

## 模块索引（顶层 *.py）

- 解析：`parsers/`（docx/xlsx/pdf → blocks/table_items）
- A 轨：`atomize` `llm_pipeline` `assemble_spec` `cosem_*` `spec_export/excel/enrich`
  `blue_book_ingest/lookup` `engineering_composer`
- B 轨：`ai_extract`（编排）+ `extract_units`（切分/引用/术语）+ `extract_guards`（质量信号）
  `requirements_analysis*` `template_writer` `clarification_report` `adjudication_bank`
  `merged_consistency` `review_insights` `doc_annotation_export`
- 基建：`llm_client`（重试/429 预算/trace/JSON 模式/用途 floors）`config` `requirement_record`
  `xlsx_io` `corpus_eval` `desktop_tasks`（chain/manifest）`api_server`
- 桌面：`ui/`（Vue3+Electron；`gui/` PySide6 已冻结勿动）

## 测试

`python -m unittest discover -s tests`（约 750，全部 unittest.TestCase——**pytest 未装**）；
`cd ui && npx vitest run && npx vue-tsc --noEmit`。golden 六项只在 main 的 out/ 基线存在时跑。
真实语料回归：`python -m corpus_eval --out <旧> --label A --out <新> --label B`。
