# 01 项目概述

## 这是什么

Requirement Atomizer 是一条 Python 流水线，把技术标准文档（DOCX/XLSX/PDF）原子化为
可评审的原子需求，最终落成 DLMS/COSEM 实现规格与公司格式的软件需求列表。

一句话概括：**确定性骨架 + 护栏化 LLM** —— 数字、编码、结构永远走确定性通道；
LLM 只做判断与叙述，且每步可溯源、可回归。

## 能力边界

- 支持输入：`.docx`、`.xlsx`、带文本层的 `.pdf`
- 不支持：扫描件 PDF（无文本层）。请先转存 `.docx` 或单独做 OCR
- 产出：结构化块、表格行、原子需求候选、LLM 审查结果、评审状态、
  Markdown/CSV 导出、装配后的实现规格、工程需求汇总

## 双轨流水线

系统按文档形态走两条主链：

| | A 轨（DLMS profile 类文档） | B 轨（散文类标准） |
|---|---|---|
| 适用 | 对象表密集（如 ABNT NBR 16968） | 行为散文（如 EN 16314 / 招标文档） |
| 链条 | atomize 规则候选 → LLM 审查 → assemble 规格 | ai_extract → 专家批注裁决 → analyze → 成文 |
| 主交付物 | `dlms_cosem_spec.*`（实现规格） | `软件需求列表-成文.xlsx`（公司 V2.3.x 格式） |
| 知识注入 | 蓝皮书 RAG（接口类条款） | 模板知识 + 裁决样本库 + 澄清答复 |

### B 轨数据流（当前主链路）

```text
parse(parsers/) → blocks.jsonl
  → ai_extract（切分/引用/术语 + LLM + 质量护栏 + 自检环）
      → ai_requirements.jsonl + ai_extract_quality.json
  → 专家批注裁决（DocumentReview / doc_annotation_export）
      → ai_review_states.jsonl → adjudication_bank（few-shot 资产）
  → requirements_analysis（规则归属 + LLM 富化）
      → engineering_analysis.json / software_requirements.xlsx
  → template_writer（确定性成文进公司模板）
      → 软件需求列表-成文.xlsx
  → clarification_report（必答/参考分级 + 就绪判定）
      → clarification_questions.xlsx
      ↺ 评审会答复 → import-clarification-answers → 下轮 analyze 作权威输入
```

全链编排由 `desktop_tasks chain --out DIR --stages ...` 单命令驱动，GUI 只负责发命令与渲染进度。

### 功能直抽（默认路径）

自 main 当前版本起，`RATOMIZER_FUNCTIONAL_EXTRACT` 默认为 `1`：chain 内的
`ai-extract` + `functional-synthesis` 两阶段被整体替换为 `functional-extract` ——
条款单元单次 LLM 直出功能需求级条目写 `functional_requirements.json`，
不产原子、不再重并。显式设置 `RATOMIZER_FUNCTIONAL_EXTRACT=0` 可回滚旧原子化路径。

## 防幻觉与可溯源原则

- **宁漏勿错**：结构化字段（OBIS、class_id、access）只走确定性关联；LLM 富化只填叙述字段，编造的编码/数字会被拒绝
- **出处永不伪造**：路由降级必须如实记录 `route_requested`；stub 输出绝不标注为 LLM 产物；缓存/合并结果保留真实来源
- **缓存指纹**：章节文本 + prompt 版本 + 模型 + 上下文 → 任何输入变化自动失效
- **产物血统**：JSON 产物带 `provenance`（producer/version/generated_at），消费端校验告警

## 主要目录

```text
atomize.py                  # 抽取流水线
cli.py                      # 稳定的机器可读 CLI（ratomizer）
desktop_tasks.py            # Electron 任务桥 / chain 编排
api_server.py               # 本地评审 API
ui/                         # Vue3 + Electron 桌面 UI（现役）
gui/                        # PySide6 旧界面（已冻结，不再扩展）
requirement_kb/             # 可复用知识库包
knowledge_bases/            # 运行时 JSON 知识库
obsidian-vault/             # 可编辑 KB 源（Obsidian）
domain_packs/dlms_cosem/    # DLMS/COSEM 模式与策略
llm_agents/                 # 评审流水线配置
parsers/                    # DOCX/XLSX/PDF 解析桥
schemas/                    # JSON Schema 数据契约
tests/                      # 后端测试（unittest）
docs/                       # 设计笔记与详细契约
```
