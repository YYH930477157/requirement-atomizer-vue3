# Agent 化 Phase 2 实施规格：Tool-using Reviewer + 软件需求无依据字段强制"待澄清"

状态：**已完成**（2026-07-23 合入 main `9d548a9`。验收：tools 探针通过（deepseek-v4-flash
支持 function calling）；真实 test3 tool-loop 审查 10/10（首轮 8/10 暴露蓝皮书索引
崩溃，修复 review-tools-v2 后 llm_failed 归零）；主检出全量 1571 tests OK、
golden 6/6 零漂移、评测四类基线 0.6667/0.5/1.0/1.0 不变）
日期：2026-07-22
前置：Phase 0（`4161f18`）、Phase 1（`baba522` + v2 `1d3b61c`）、Phase 1.5（`5cd03be`，
对比裁定"规则保持默认"）、评测扩充（`11af616`，agent-eval-v2 基线 0.6667/0.5/1.0/1.0）；
总纲 `docs/agent-rollout-plan.md` Phase 2 行

## 0. 定位

Phase 2 把审查从"单次 prompt"升级为**有边界的工具调用审查**：模型在审查单条需求
过程中可自主调用**确定性只读工具**（KB 查询、蓝皮书查询、原文块读取、覆盖校验），
证据仍由确定性层供给，结构化字段仍由确定性层裁决。两个工作包：

- **WP1（主）**：llm_client 增加 OpenAI 兼容 tools 调用与有界 tool-loop；
  `llm_agents/review_pipeline.yaml` 的 operations 落到执行器；
- **WP2（小，独立）**：软件需求模板输出（`requirements_analysis` →
  `template_writer`）中无依据的富化字段强制写"待澄清"，不再静默放行。

**关键现状（2026-07-22 核实，规格据此立项）**：

1. yaml 的五个 operations（classify_risk/correct_errors/merge_duplicates/gap_find/
   test_point_generate）**当前是声明性死代码**——`run_review_pipeline`
   （`llm_pipeline.py:737`）从不迭代它们，实际审查是每条需求一次融合 prompt
   （`SYSTEM_PROMPT`，`llm_pipeline.py:36`）。本阶段是**首次实现执行器**，不是改写。
2. `llm_client.py` 只有单发 JSON 模式（`llm_client.py:298-310`），无 tools 参数、
   无 tool_calls 解析、无 tool-loop——需新建，口径见第 1 节。
3. `merge_duplicates` 与 `gap_find` 已有**确定性等价物**
   （`merged_consistency.find_cross_section_duplicates` / `find_obis_coreference` /
   `coverage_gaps`）；按铁律"结构化裁决确定性优先"，这两个 operation 不做 LLM 版，
   见第 3 节处置表。
4. `schemas/test_point.schema.json` 存在但**零生产者、零消费者**——
   test_point_generate 缓建（有据缓建纪律：无消费者不立项）。

## 1. WP1-A：llm_client 工具调用基础（新建）

- 新 API：`chat_with_tools(config, messages, tools, *, max_rounds, on_tool_call) ->
  (final_dict, meta)`。tools 为 OpenAI 兼容 tools schema（function 定义）；
  meta 汇聚全部轮次 usage（同 `chat_json_with_meta` 口径，usage 缺失计 0 标 partial）。
- **有界循环硬顶**：`max_rounds` 默认 **8**（含首轮；模型连续请求工具则每轮 +1）；
  轮顶或模型给出无 tool_calls 的最终 JSON 即返回。超过轮顶 → 抛
  `LLMResponseError`，调用方按现有失败路径处理（该需求进 stub 审查并在汇总记数，
  **不得伪造模型已审**）。
- 非法 tool_call（未知工具名/参数 schema 不符/工具执行异常）→ 工具结果以
  `{"error": ...}` 回灌模型一次让其纠正；同轮再犯 → 视为轮顶耗尽同等处理。
- 端点不支持 tools（4xx）→ 响亮报错，不静默降级为无工具审查（provenance：
  stub 不得冒充 tool-using 审查）。
- 复用现有：JSON 模式、429 自适应闸门、截断升级、双头发送、llm_trace 全量落盘。
- 新常量 `REVIEW_TOOLS_VERSION = "review-tools-v1"`：工具定义（名称/参数/返回
  裁剪）任何变更必须 bump，并进入审查缓存指纹（同 `EXTRACT_GUARDS_VERSION` 纪律）。

## 2. WP1-B：工具面（冻结契约，全部确定性只读）

工具实现为 `review_tools.py`（新顶层模块，注册 py-modules），只做现有确定性函数的
薄封装与返回裁剪；**不写、不猜、不联网**：

| 工具名 | 封装 | 返回（裁剪后） |
|---|---|---|
| `kb_search(query, limit?)` | `KnowledgeRepository.search`（默认 KB 集） | top≤5：entry_id/name/definition≤300 字/score |
| `kb_get(entry_id)` | `KnowledgeRepository.get` | 单条 compact_metadata 白名单字段 |
| `blue_book_class(class_id?, name?)` | `blue_book_lookup.lookup_class(_by_name)` + `condensed_text` | section/name/condensed≤1500 字；未命中如实 null |
| `source_read(block_id)` | `blocks.jsonl` 查块 | block 原文≤2000 字 + section 路径；未知 id 如实 error |
| `coverage_check(requirement_id)` | `merged_consistency.match_source_quote_blocks` + `find_obis_coreference` / `find_cross_section_duplicates` 按该需求过滤 | 引句命中块、共引 OBIS 清单、跨章重复候选 |

- 工具输出全部确定性可复现（同输入同输出）；工具调用本身零 token。
- 模型只能经工具读证据；结构化字段（OBIS/文号/访问）仍由确定性层裁决——模型
  输出与工具证据冲突时按现有护栏处理（`apply_deterministic_review_policy`、
  `llm_review_schema` 校验、code-drift 强制 needs_expert 均不动）。

## 3. WP1-C：operations 处置（冻结项）

| operation | 处置 | 说明 |
|---|---|---|
| classify_risk | **工具化融合审查**（与 correct_errors 合并为每条需求一次 tool-loop 调用） | 输出契约不变：decision/risk/confidence/revised_requirement/review_notes/expert_questions；`llm_review_schema` 与确定性政策层照旧 |
| correct_errors | 同上（融合） | 修正文本须与工具证据一致，否则按现有 drift 护栏处置 |
| merge_duplicates | **确定性承担，不做 LLM 版** | `find_cross_section_duplicates`/`find_obis_coreference` 已在 consistency_report；yaml 中该 operation 标 `"executor": "deterministic"` |
| gap_find | **确定性承担，不做 LLM 版** | `coverage_gaps` + 澄清遗漏档已在；语义漏抽发现归既有 ai-extract 自检轨，不进本阶段 |
| test_point_generate | **缓建** | schema 有、零消费者；有据缓建，消费者出现再立项 |

- yaml 结构调整最小化：operations 增 `executor: "tool_loop" | "deterministic" | "deferred"` 字段；`load_review_pipeline` 透传。
- **缓存与版本**：tool-loop 审查为新的 prompt 路径——`PROMPT_VERSION` 升
  `m2-review-v2`，`LLM_REVIEW_CACHE_VERSION` 升 `llm-review-cache-v3`，缓存 key 增
  `REVIEW_TOOLS_VERSION`；stub 审查路径（`build_stub_review`）逐字不动。
- **缓存语义与不可复现性**：Phase 1.5 实测托管端点同输入输出不可复现。审查缓存
  按输入指纹命中即可，**不要求模型输出可复现**；但每条审查结果的产出过程必须可
  由 `llm_trace.jsonl` + `tool_calls` 摘要完整解释（审计纪律落在轨迹可解释性上，
  不落在输出逐字一致上）。
- **下游零冲击**（契约锁）：decision 枚举、risk 值域、task_id/身份字段、
  source_refs、`review_states.jsonl` 状态机映射、api_server `/reviews`、
  cosem_behavior_spec.reviews_by_id、Vue 字段全部不变——tool-loop 只改变
  产出这些字段的过程，不改变字段语义。
- golden：基线输出由 stub 路径生成，stub 不动 → 预期零漂移；合入后主检出
  golden 6/6 复验坐实。

## 4. WP2：无依据字段强制"待澄清"

- 适用范围：`requirements_analysis` 的富化叙述字段（`software_requirement_text`、
  `hardware_dependency`、`developer_guidance`、`design_options`、
  `acceptance_criteria`）。确定性 join 字段（id/归属/引句/模块）**永不**标待澄清。
- 规则（确定性，挂 `_apply_llm_item`（`requirements_analysis.py:558`）现有
  `validate_llm_item` 之后）：
  1. 富化被护栏整体拒绝（现有行为：回退 base 值）→ 该字段写 **"待澄清"**，
     不再静默以 base 文本充当软件需求正文；
  2. 富化被接受但某字段证据校验降级（现有 soft-flag 升级为拒的同一判据）→
     该字段写"待澄清"；
  3. 每个"待澄清"同步生成一条 `open_questions` 条目（内部核对受众），
     进既有澄清闭环（`clarification_report` 读 `engineering_analysis.json`
     的通道已存在）；
  4. 渲染：`software_requirements.xlsx` 说明列与 `template_writer` 成文列
     原样透出"待澄清"字样（现有"待确认：…"渲染通道复用）。
- **版本**：`ANALYZE_PROMPT_VERSION` 升 `analyze-llm-v7` 并使
  analyze_enrich_cache key 纳入本规则版本（确定性后处理变更必须进指纹，
  AGENTS.md 硬约束）。
- 明确界限：本规则只对"无依据"下手；有依据但写得差的文本不动（质量问题归
  专家审查，不归确定性层）。

## 5. tokens 与轨迹口径（沿用 Phase 1.5 口径扩展）

- 计数：tool-loop 审查的**全部 chat 调用**（首发 + 工具轮 + JSON 修复/截断升级）
  的 usage 之和；usage 缺失计 0 标 partial，不估算。工具执行零 token。
- 预算：每需求 tool-loop tokens 上限默认 20000（可调）；全跑不设总顶（审查本质
  是批处理，超预算的需求进 stub 并记数）。
- 轨迹：`llm_trace.jsonl` 照旧全量；审查结果行附加 `tool_calls` 摘要（工具名 +
  轮次，schema additionalProperties 允许），不另建轨迹文件。

## 6. 测试要求（`unittest.TestCase`，根目录 discover）

- `chat_with_tools`：MockOpenAIService 扩 tool_calls 响应——正常多轮收敛、
  轮顶耗尽、非法工具回灌纠正、4xx 不支持响亮报错、usage 汇聚与 partial 标注；
- `review_tools`：五工具各正/反例（含未命中如实 null/error、裁剪长度、确定性
  复现）；工具定义变更 → REVIEW_TOOLS_VERSION 未 bump 则契约测试失败；
- operations 执行器：融合审查输出过 `llm_review_schema`、确定性政策层照旧、
  下游契约字段锁（decision 枚举/状态机映射/api 字段）；
- WP2：拒绝→待澄清、接受但无据→待澄清、有据→原文保留、open_questions 同步、
  渲染透出；缓存指纹含新规则版本；
- 全量绿；评测基线（agent-eval-v2）不下降；主检出 golden 6/6。

## 7. 明确不做（范围护栏）

- 不做 merge_duplicates/gap_find 的 LLM 版（确定性优先）；test_point_generate 缓建；
- 不写工具（全部只读）、不做向量/语义 KB 检索（精确查找纪律）、不多 agent；
- 不动 agent_loop/agent_decider（Phase 1/1.5 决策循环与本阶段审查器是两条线）；
- 不动 UI/`gui/`；不动 decide_trace schema；`AGENT_POLICY_VERSION` 不动
  （本阶段不改变 agent 决策行为）。

## 8. 验收清单（审核人逐项核对）

1. `python -m unittest discover -s tests` 全绿（新增 ≥20 用例）；
2. 真实 test3 产物在有 key 环境跑 tool-loop 审查 ≥10 条：逐条核 tool_calls 摘要
   与最终 decision/revised 文本，无凭空证据；
3. 缓存三版本（PROMPT_VERSION/LLM_REVIEW_CACHE_VERSION/REVIEW_TOOLS_VERSION）
   与 ANALYZE_PROMPT_VERSION 已升且指纹覆盖；
4. stub 路径逐字不变，golden 6/6 零漂移（主检出实跑）；
5. WP2 在 test3 工程分析产物上复跑：拒/无据字段全部"待澄清"且 open_questions
   同步进澄清报告，有据字段逐字节不变；
6. diff 范围：`llm_client.py`、新增 `review_tools.py`、`llm_pipeline.py`、
   `requirements_analysis*.py`、`template_writer.py`、`llm_agents/review_pipeline.yaml`、
   `schemas/`（如需）、tests、文档。其余打回。

## 9. 冻结点（审核人确认项）

1. operations 处置表（merge_duplicates/gap_find 确定性承担、test_point_generate
   缓建）；
2. 工具面 5 件套与只读纪律（`kb_search/kb_get/blue_book_class/source_read/
   coverage_check`）；
3. 预算口径：max_rounds=8、每需求 tokens 上限 20000、超限进 stub 记数；
4. WP2 触发面：仅富化叙述字段，确定性 join 字段永不标待澄清；
5. 开工第一任务：有 key 环境对 deepseek-v4-flash 做 tools 支持探针（不支持则
  WP1 暂停换端点，不得伪造）。

## 10. 审核方式

实施者交付 diff + 本清单自检结果；审核人跑第 1 条命令、抽核第 2 条、逐条核对
3–6。任何一条不过即整体打回，不部分接收。
