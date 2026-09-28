# 审核报告：文档预处理与分段准确性（2026-09-27）

## 1. 审核范围与方法

- **范围**：功能需求轨在 LLM 抽取之前的全部环节，即解析、标题识别、段落分段、语义分段、候选筛选和条款装载；同时核对 `docs/architecture.md` 是否与代码一致。
- **方法**：先阅读代码，再用真实产物逐项验证。样本为本机最近一次全量运行：
  `out/ts-novy-nepriamy-elektromer-mimo-v2.6-flash-full-20260926-rerun-v12/`
  （Slovak TS 间接电表技术规范，机翻 PDF，MIMO v2.6 Flash，`semantic_mode=llm`）。
- **未做（原审核时）**：原审核没有修改代码，也没有调用付费模型。第 4 节 F4 的 LLM 错误具体原因尚未从 `llm_trace` 展开核实；后续修复阶段同样没有调用付费模型。

## 2. 结论摘要

预处理和分段不准确，是四个可以复现的缺陷叠加的结果，并非单纯由模型质量引起：

| 编号 | 缺陷 | 严重度 | 直接后果（v12 实测） |
|---|---|---|---|
| F1 | `doc_region` 在候选分类之后才写入，body 保护分支在生产中从未生效 | 高 | 分类只能依赖关键词正则 |
| F2 | 候选分类用 `contents` 等词匹配正文，且 `informational` 状态会一直延续 | **严重** | 3.12 数据接口一节 10 条 must 需求未进入抽取 |
| F3 | PDF 启发式标题识别过宽，`section_path` 被污染 | **严重** | 120 个标题中约 50 个是误识别，3.9～3.29 全部挂在伪章节 `3 decimal places` 下 |
| F4 | LLM 语义分段大面积回退 | 中 | 16 个节出错，424 个单元中 142 个是回退产生的 |
| F5 | text_fallback 重解析后没有重算候选分类 | 中（潜在） | 候选会指向旧的分段；v12 未触发 |
| D1 | 架构图与实际链路不一致 | 文档 | 分段和筛选层缺失，路由层的位置画错 |

其中 F1 和 F2 叠加起来，会**静默丢失需求**：覆盖审计能标出可疑项，但不会阻断流程。F3 是分段边界错乱的主要源头，也会放大 F4 的失败率。

## 3. 实际链路（与架构图对照）

```
parse 阶段（atomize.run_atomizer_pipeline）
  parsers/*  → blocks（PDF：detect_heading + _refine_pdf_heading + SectionState → section_path）
  → paragraph_segmentation.build_segmentation_report
  → semantic_pre_review（仅在 semantic_mode=llm 或显式开关时运行）
  → semantic_segmentation.build_semantic_report（按 section_path 的连续段分组）
  → requirement_candidates.classify_semantic_units          ← atomize.py:2969
  → mark_doc_regions（body / front_matter / …）              ← atomize.py:3002（晚于上一步）
  → build_chunks → chunks.jsonl
functional-extract 阶段
  load_clauses_detailed：语义单元 > chunks.jsonl > 现场聚合 blocks
  → 候选筛选：只保留 requirement/table/needs_review（functional_extract.py:3862）
  → doc_map → apply_unit_routing（extraction_units + unit_router）
  → 条款族 LLM 抽取 → 守恒
```

架构图的问题（D1）：
- 缺少 `semantic_segmentation`、`requirement_candidates` 和候选筛选。这几个环节决定哪些内容会被送去抽取。
- 图上的 `extraction_units → unit_router` 画成了抽取的上游。实际上它们在 functional-extract 内部，只负责把以表格为主的条款、只有标题的条款、前置样板等从 B 轨路由出去。
- `doc_map` 在抽取阶段运行，不属于解析上下文层。

## 4. 缺陷详情

### F1 `doc_region` 写入顺序错误（高）

- **位置**：`atomize.py:2969`（分类）早于 `atomize.py:3002`（`mark_doc_regions`）；PDF 解析器和 `extract_docx` 都不设 `doc_region`。
- **机制**：`requirement_candidates._region_role` 在 `doc_region == "body"` 时直接判为 `normative_body`（`requirement_candidates.py:21`）。分类时 blocks 上还没有这个字段，所以 `explicit_doc_region` 恒为空，该分支永远走不到。代码注释说"传入原始 blocks 以保留显式 doc_region"，但这一意图没有实现。
- **证据**：v12 最终写出的 `blocks.jsonl` 里 496 个块全部是 `doc_region=body`，而 `requirement_candidates.json` 中仍有 24 个单元被判为 `informational`。
- **修复方向**：把 `mark_doc_regions`（以及 tender 区域标注）移到候选分类之前；如果有测试夹具依赖旧顺序，需要同步更新。

### F2 正文关键词误触发 `informational`，且状态延续（严重）

- **位置**：`requirement_candidates.py:10` 的 `NON_REQUIREMENT_REGION`（其中含 `contents`、`references?`、`definitions?`、`introduction` 等），在 `:24` 处拿去匹配 `路径 + 标题 + 正文前 120 字符`；`:65-66` 把结果写入 `current_role`，并延续到后续单元。
- **机制**：退出 `informational` 的条件只有两种：文本开头是 `N scope|requirements|functional`，或者是 `N.N` 开头的正文。F3 让大量伪章节插在中间，真正的 `N.N` 标题又常常被判为 `context`，由 `section_heading` 分支处理，不参与恢复判断，所以状态可能一路延续到节末。
- **证据（v12）**：
  - 3.8 节正文 "…possible to display the **contents**…"（BLK-000148）触发了 `informational`；
  - 3.12 节正文 "The **contents** of register C.1.0…" 触发后，整个数据接口小节都变成 `informational/context`；
  - 在功能需求产物中，有 10 个带 must 的非噪声块没有被任何条目引用：BLK-000148、258、261、262、264、266、267、268、276、278（RS485、DLMS/HDLC、接口独立、P1/RJ12 PUSH、Ethernet/光口、4G+Ethernet 等）；
  - `requirement_coverage_audit.json`：排除 248 个、可疑 31 个，`status=needs_review`。但 `functional_extract.py:3862` 的筛选不读取审计结果，也就不会阻断。
- **附带问题**：`functional_extract.py:3851-3870` 的筛选失败时被 `except Exception: pass` 静默吞掉。另外，只要有任意一个候选命中，就会整体替换条款池，没有记录任何审计信息。
- **修复方向**：
  1. 非需求区域只能由**标题或路径**触发，不能由正文触发；`contents` 只在目录类标题上生效。
  2. 含义务词（must/shall/required）的单元不得判为 `context`。按"宁漏勿错"的原则，至少应降级为 `needs_review`，让它进入抽取池。
  3. 对 `current_role` 的延续加上边界：遇到任何编号标题都要重新判定。
  4. 覆盖审计的可疑项应回流候选池，或在就绪门中显式阻塞；筛选失败时要记录审计信息，不能静默。

### F3 PDF 标题误识别污染 `section_path`（严重）

- **位置**：`atomize.detect_heading`（`atomize.py:452` 附近，规则为 `^\d+(\.\d+)*\s+.{3,}$`，且单段编号 ≤40）；`parsers/pdf_parser._refine_pdf_heading`（`:2508`）；`atomize.SectionState.update`（`:361`，同长度编号会覆盖同级章节）。
- **证据（v12，120 个标题中约 50 个是误识别）**：

| 类型 | 例子 | 数量 | 后果 |
|---|---|---|---|
| 数值加单位的续行 | `3 VAr`、`3 decimal places`、`1.0 m m2 to 2.5 m m2`、`29 characters.` | 4 | 替换了真实章节；3.9～3.29 共 21 个小节的路径变成 `3 decimal places / …` |
| `N.` 编号清单 | `1. Indication of the flow…`～`7. The dial…`、`1. Administrator - address 1…`～`4. Counter…` | 11 | 成了顶级章节，把 3.8.1、4.3 拆碎 |
| OBIS/寄存器表行 | `1.5 P+ active power`、`32.23 At L 1…`、`148.5 Flicker…`、`1.5.0 (W) 1.8.0 (Wh)` | 约 33 | 成了 3.21 下面的伪子章节 |
| 时间戳格式码 | `0.9.1 - Zs7 (yhhmmss)`、`0.9.2 - Ds7` | 2 | 伪子章节 |
| 标题与正文粘连 | `5.3.2 Protection against ingress… A modem with an` | 1 | 标题里混入了正文 |

- **影响**：`semantic_segmentation` 以 `section_path` 的连续段作为分组边界（`semantic_segmentation.py:370-398`），路径一乱，段边界就跟着乱。伪章节还会传到 `chunks.jsonl`、条款 `section_id`、批注的章节显示和成文的章节列。
- **修复方向**（只作用于 PDF 启发式路径，DOCX 的 Heading 样式仍然优先）：
  - 编号必须与已建立的大纲连续（例如当前在 3.8.x，出现 `3 …` 或 `32.23 …` 应当拒绝）；
  - `N.`（带点加空格）形式的清单项不算标题；
  - 标题文本以单位、量词或数值为主时（`VAr`、`decimal places`、`mm2`、`characters`）不算标题；
  - 同一页连续出现大量同形编号行时，判为表格或列表。
  - 这些改动会影响 atomize 的实现版本和解析缓存指纹，需要升级版本。

### F4 LLM 语义分段大面积回退（中）

- **证据（v12 `semantic_segmentation.json`）**：配置为 `mode=llm`，实际为 `effective_mode=deterministic_fallback`；16 个节出错（12 个 `LLMResponseError`，4 个 `ValueError`）；424 个单元中 `boundary_basis` 为 llm 的 282 个、fallback 的 142 个；370 个是单块单元。
- **关联**：4 个 `ValueError` 全部发生在 F3 造成的伪章节上（`2 Communication indication…`、`4 Units of measurement…`、`3 Modem technician…`、`5.3.2 …A modem with an`）。
- **待核**：12 个 `LLMResponseError` 的具体原因（截断、非法 JSON 还是超时）需要从 `llm_trace.jsonl` 确认。另外，窗口上限 `SEMANTIC_WINDOW_MAX_BLOCKS=18` 和 `SEMANTIC_MAX_CALLS=8` 是否让长节超出调用预算，也需要核实。
- **修复方向**：先修 F3，再看剩余的失败率；然后按 trace 的结果决定是调整窗口或预算，还是修改响应契约。

### F5 text_fallback 重解析后候选没有重算（中，潜在）

- **位置**：`atomize.py:2978-2996`。视觉辅助失败且配置为 `fallback=text_fallback` 时，会重新解析 PDF 并重建 `semantic_report`，但 `requirement_candidates` 和 `requirement_coverage_audit` 仍使用旧分段计算的结果。
- **影响**：候选与语义单元之间的 `semantic_unit_id`/`source_block_ids` 对不上，筛选结果不可信。
- **修复方向**：把分类和审计挪到分段的最终结果确定之后统一计算（也就与 F1 的调整顺序合并处理）。

## 5. 建议修复顺序

1. **F1 + F2 + F5**：调整顺序并修改候选分类规则。改动小，收益最大。验收方法是用 v12 产物零付费重放，确认上述 10 个 must 块回到候选池，同时 `informational` 只出现在真正的前言、定义、参考文献区域。
2. **F3**：收紧 PDF 标题识别。升级 atomize 版本；在 v12 原文 PDF 上零付费重新解析，验收标准是伪标题清零，3.9～3.29 回到 `3 Technical specifications` 下，DOCX 的 golden 无漂移。
3. **F4**：在 F3 修复后重跑语义分段（需要付费，先小范围试），再按 trace 结论处理剩余的失败。
4. **D1**：按第 3 节更新 `docs/architecture.md` 并重新生成 SVG。

每一步都需要补充对应的回归测试，使用合成的中性夹具，不引入客户原文。

## 6. 附：本次核对使用的产物

- `.ratomizer/pipeline/blocks.jsonl`（496 块：paragraph 375 / heading 120 / table 1，noise 70）
- `.ratomizer/pipeline/semantic_segmentation.json`、`semantic_pre_review.json`
- `.ratomizer/pipeline/requirement_candidates.json`（context 248 / requirement 141 / needs_review 34 / table 1）
- `.ratomizer/pipeline/requirement_coverage_audit.json`
- `.ratomizer/pipeline/functional_requirements.json`（146 条，`execution_status=partial`，路由：条款 152 → 抽取 146）

## 7. 修复后复核（2026-09-27）

本报告提出的主要问题已经按“最终分区先确定、候选可审计、保守回流”的原则修复：

- F1/F5：`atomize` 现在在视觉/文本回退完成后才执行 `mark_doc_regions`、语义预审、语义分段、候选分类和覆盖审计；候选 ID 与最终 `blocks` 同源。`atomize` producer 已升至 `v15`。
- F2：正文中的 `contents` 等普通词不再触发信息区；信息区义务句进入 `needs_review`；覆盖审计中的强约束信号会在 `functional-extract` 中回流到抽取范围，并写出 `candidate_filter.audit_promoted_block_count`。筛选异常/空命中不再静默吞掉，结果标记为兼容回退。
- F3：PDF 启发式标题加入单位、代码、数值、句末标点、长句清单和高编号护栏；显式 Heading 样式不受影响。对原 TS PDF 的零付费解析核对中，报告列举的 `VAr`、`decimal places`、寄存器/OBIS、时间戳和清单样本均不再被识别为标题。
- F4：语义分段 LLM 现在使用用途级 token 下限、一次截断修复，并将调用预算由 8 窗口提高到 32；语义预审对长文档按完整 block 窗口化，不截断、不丢块，跨窗边界显式保守切开。该项减少结构性回退，但仍需实际模型重跑后以 trace 评估剩余失败率。
- D1：`docs/architecture.md` 与 `docs/architecture.svg` 已按实际链路补齐 Regions、Semantic、Candidates 和抽取内部路由位置。

验证：预处理/候选/语义相关定向测试 73 项通过；另增加候选状态延续、覆盖审计回流和文本回退重建回归。完整测试套件最近一次基线运行的剩余失败包含历史提示词登记/测试基线漂移及平台/前端偶发项，不能归因于本次修复；这些登记项已在本次修复中同步，之后的关键定向测试均已通过。
