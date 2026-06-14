# 行为需求派生与审查指南（P3）

> 改编自公司 requirement-analyst-pro 的提取质量规则与领域标签，适配 DLMS/COSEM 协议 profile。
> LLM（或开发期的 Claude）派生行为需求时遵循本指南；`requirement_schema.py` 保证输出字段完备、`cosem_behavior_spec.py` 的护栏保证数字不被 LLM 篡改。

## 一、防幻觉铁律（最高优先级，不可违反）
- **数字 / OBIS / class_id / 访问位 / 事件号 绝不由 LLM 产出或修改**；它们只来自确定性层（P1 数据字典 / P2 访问矩阵 / 源原文）。
- 改写文本里若出现原文没有的编码 → 装配器 `code-drift` 护栏强制 `needs_expert`，打回专家队列。
- 不确定的编码（如疑似抽取噪声）**标记交专家，不自动猜改**（确定性归一化除外，见 `text_normalize.py`）。

## 二、13 条提取质量规则（派生时遵循）
1. **独立性**：每条需求是可单独开发/测试的功能单元。
2. **清晰性**：避免模糊、可多解的描述。
3. **可实施性**：技术上可实现、可衡量。
4. **完整性**：所有需求合起来完全覆盖原文。
5. **风格一致**：参考历史需求点保持粒度与风格。
6. **适当粒度**：不过大（含多功能）不过小（过细）。
7. **避免重复**：不提取重复/高度相似项。
8. **自完备**：脱离其它需求也能独立理解。
9. **顺序/相关动作合并**：「配置 A 后显示 B」这类连贯动作视为单条需求，不拆。
10. **枚举拆分**：「支持 a、b、c」→ 每个枚举项各成一条需求。
11. **可扩展短语处理**：遇「包括但不限于/等/例如」——先拆每个具体项为独立需求；再加**一条抽象总结需求**，该总结**只用上层类别词、绝不引用任何具体项**（例：「系统应按需支持各种结构化数据格式」，不提 CSV/XML/JSON）。
12. **充足上下文**：每条需求自带足够上下文，单看即可理解。
13. **不扩展原文**：除非原文用了可扩展短语，否则不自行扩大范围。

## 三、每条需求必备字段（对齐公司标准格式）
`id` `title`(≤80) `description`(详细自包含) `type`(functional/non_functional/constraint/business_rule) `priority`(P0/P1/P2) `status`(draft/confirmed/conflict/gap) `source_section` **`source_quote`(原文，必填非空)** `threshold_table`(规范表必填，否则 null) `acceptance_criteria[]` `dependencies[]` `parent` `children[]` **`labels[]`(至少一个)** `notes`。

- **description**：不能只写「应支持 XX」，要写清做什么、什么条件、什么范围、涉及参数。
- **source_quote**：保留原文语言（英文就英文），原样引用不可改写。
- **分析输出**（title/description/acceptance/notes）用中文；原文引用保留原语言。

## 四、适配后的领域标签（取自公司 21 域，按协议 profile 取相关子集）
常用：`通信协议` `安全` `事件记录` `Push` `计量` `时钟` `费率` `需量` `状态字` `升级`。
（产品专属域如 窃电/预付费/CIU/节假日/电网质量/环境可靠性 在协议 profile 行为里少见，按需才用，不硬塞。）

## 五、覆盖审查（防遗漏）
对照 `requirement_schema.COVERAGE_CHECKLIST`（适配后的 10 个 DLMS/COSEM 行为域）逐项检查：每个域是否至少有一条需求？缺失 → 记入 `analysis.gaps` + `validation_result.omissions_found`，提示专家核对原文。
