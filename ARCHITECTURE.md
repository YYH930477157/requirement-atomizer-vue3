# ARCHITECTURE — Requirement Atomizer

> 给新工程师的系统地图（2026-07-06）。协作纪律与历史见 `CLAUDE.md`，待办见 `TODO.md`。

## 一句话

把客户技术标准（DOCX/XLSX/PDF）转成研发可落地的需求交付物：**确定性骨架 + 护栏化 LLM**——
数字/编码/结构永远走确定性通道，LLM 只做判断与叙述，且每步可溯源、可回归。

## 主流程与兼容流程

| | 默认功能需求流程 | Legacy A 兼容流程 |
|---|---|---|
| 适用 | 所有需要转成研发需求的技术文档 | 历史 DLMS profile 结果或专项诊断 |
| 链条 | `parse → functional-extract → requirements-analysis → clarification/export` | `atomize → llm-review → assemble/compose` |
| 主交付物 | `functional_requirements.json`、澄清清单和需求导出 | `atomic_requirements.jsonl`、实现规格等历史产物 |
| 知识注入 | 条款上下文、领域知识、澄清答复 | 蓝皮书和旧 A 轨规则 |

## 默认功能需求数据流

```
parse(parsers/) → blocks.jsonl / chunks.jsonl / doc_map.json
  → functional-extract（按自然条款保留完整上下文，直接生成完整功能需求）
      → functional_requirements.json（行为、约束、例外和来源证据）
  → 功能需求评审（FunctionalReview.vue / API）
      → requirements-analysis（规则归属、可选 LLM 富化和澄清答复注入）
      → engineering_analysis.json / clarification_questions.xlsx / 需求导出
      ↺ 评审会答复 → import-clarification-answers → 下轮 analyze 作权威输入
```

编排：`desktop_tasks chain --out DIR --stages ...`（单命令全链，GUI 只发命令渲染进度）。
状态：每个输出目录 `run_manifest.json`（manifest v2：阶段状态、producer 版本、route、配置与上游文件 SHA-256 输入指纹）。缺少账本或任一输入指纹变化时不得复用；stub 请求可以保留已验证的 OpenAI 产物，但不能在新目录伪装完成 AI 抽取。

`functional-extract` 直接按自然条款生成完整功能需求；同一条款中的多个动作进入 `behaviors`、约束或例外字段，不通过“拆散再拼回”形成需求。`requirements-analysis` 优先消费 `functional_requirements.json`；仅在读取历史结果时兼容旧的逐原子输入。

**条款直抽主流程（WS2，默认开启）**：chain 内
`ai-extract`+`functional-synthesis` 两阶段被整体替换为 `functional-extract`——条款单元
单次 LLM 直出功能需求级条目写同名 `functional_requirements.json`，不产原子、不再重并
（无"拆散再拼回"的粒度拉锯）。守恒核对按条款块（exactly-once），未闭合即阻塞成文导出；
无原子链形态下 `requirements-analysis`/`clarification-report` 以直抽产物为唯一依据
（资格判定单源 `functional_extract.functional_direct_basis`）。批注/裁决等逐原子面在
此形态下为空，锚点迁移属后续步骤。

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
- 默认功能需求：`functional_extract` `requirements_analysis*` `template_writer` `clarification_report`
- Legacy A 兼容：`atomize` `llm_pipeline` `assemble_spec` `cosem_*` `spec_export/excel/enrich`
  `blue_book_ingest/lookup` `engineering_composer`
  `requirements_analysis*` `template_writer` `clarification_report` `adjudication_bank`
  `merged_consistency` `review_insights` `doc_annotation_export`
- 基建：`llm_client`（重试/429 预算/trace/JSON 模式/用途 floors）`config` `requirement_record`
  `xlsx_io` `corpus_eval` `desktop_tasks`（chain/manifest）`api_server`
- 桌面：`ui/`（Vue3+Electron）

## 测试

`python -m unittest discover -s tests`（约 750，全部 unittest.TestCase——**pytest 未装**）；
`cd ui && npx vitest run && npx vue-tsc --noEmit`。golden 六项只在 main 的 out/ 基线存在时跑。
真实语料回归：`python -m corpus_eval --out <旧> --label A --out <新> --label B`。
