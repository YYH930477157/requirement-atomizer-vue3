# 需求分析 Agent 设计

日期：2026-07-03
状态：待用户审阅

## 背景

Requirement Atomizer 当前已经可以从标准或客户需求文档中抽取原子需求，并支持 AI 抽取、段落级 HTML 批注审查，以及合并规格导出。这些能力对“来源覆盖率”和“可追溯性”很有价值，但还没有完全匹配新的产品目标：帮助软件工程师把客户/标准需求文档转成可落地的软件研发需求。

当前效果主要有两个问题：

- 没有明确区分 `software`、`hardware`、`co_design` 三类需求。
- 软件类结果经常像原文翻译或摘要，而不是包含行为、输入、输出、约束和验收建议的软件研发需求。

用户提供了一份内部软件标准化需求模板：

`D:/Users/YunHeYang/Desktop/Canna/Canna-29/电表软件标准化需求列表-V2.3.12 - 2026-4-14.xlsx`

这份模板只用于参考软件需求输出格式，不用于定义硬件需求格式。硬件需求第一版只做轻量分析和来源保留。

## 目标

新增一个独立的需求分析 Agent 阶段，消费现有抽取结果，并产出面向研发的需求分析结果：

- 将每条需求分类为 `software`、`hardware` 或 `co_design`。
- 对硬件-only 项做简要处理。
- 对软件项和协同项的软件侧做详细分析。
- 生成贴近内部软件模板的软件需求 Excel。
- 保留结构化 JSON，方便测试、复核和后续迭代。
- 在现有段落级 HTML 批注流程中允许人工修正软硬件归属。

## 非目标

- 不替换 `atomize.py`。
- 不替换 `ai_extract.py`。
- 不把硬件需求强行套入软件需求模板。
- 第一阶段不做软件内部细分类。当前只做 `software`、`hardware`、`co_design` 三分类。
- 不允许 LLM 静默改写标识符、OBIS、DLMS class ID、阈值、时间、访问权限或来源引用。

## 推荐方案

新增一个后处理阶段，暂定名为 `requirements_analysis`。

现有阶段继续保持各自职责：

```text
atomize
  确定性解析、表格抽取、原子需求候选、知识库匹配。

ai_extract
  AI 辅助抽取行为需求，负责原文锚点、上下文工程、缓存和自检。

requirements_analysis
  工程归属分类、软件需求展开、协同项拆分、软件模板导出。
```

这样可以把“抽得全、锚得准”和“分得准、写得像研发需求”分开调试。

## 数据流

```text
输入文档
-> atomize
   -> blocks.jsonl
   -> table_items.jsonl
   -> atomic_requirements.jsonl
-> ai_extract
   -> ai_requirements.jsonl
   -> ai_extract_quality.json
-> document_annotation.html
   人工可修改 status、module、ownership、reason
-> import decisions
   -> ai_review_states.jsonl
-> requirements_analysis
   -> engineering_analysis.json
   -> software_requirements.xlsx
   -> co_design_items.json
   -> co_design_items.md
   -> hardware_items.json
   -> hardware_items.md
```

`requirements_analysis` 必须优先读取人工裁决结果。人工 override 的优先级高于规则和 LLM。

## 归属模型

每个分析项都应带有归属字段：

```json
{
  "ownership": "software | hardware | co_design",
  "ownership_confidence": 0.86,
  "ownership_reason": "Reason based on requirement content and source context",
  "ownership_source": "rule | llm | reviewer_override"
}
```

### Software

软件项需要详细分析。输出应包含软件需求描述、研发实现提示、验收建议、来源追溯和待确认问题。

### Hardware

硬件项只做轻量处理，不导入软件模板。输出应包含硬件关注点、来源依据、判为硬件的原因、可能的软件影响和待确认问题。

### Co-Design

协同项需要同时出现在两个位置：

- 协同清单，包含软件侧责任和硬件侧依赖。
- 软件需求 Excel，因为软件工程师不能漏掉硬件相关的软件工作。

协同项进入软件 Excel 时，`驱动/硬件相关` 列应标记为 `是`。

## 规则 + LLM 策略

第一层用确定性规则判断。LLM 用于低置信度归属判断、软件需求展开、协同项拆分和功能聚合。

### 规则示例

倾向 `software`：

- DLMS/COSEM 协议行为
- COSEM 对象访问与配置
- 事件记录
- 负荷曲线和捕获逻辑
- 费率、结算、预付费逻辑
- Push、P1、显示、状态字、升级逻辑

倾向 `hardware`：

- 计量芯片型号
- CT 或锰铜采样方式
- 继电器物理能力
- 电源或电池约束
- 通信模组频段
- 机械结构
- 物理寿命或器件级耐久要求

倾向 `co_design`：

- 驱动和硬件接口
- 通信口能力和波特率上限
- DataFlash 或存储容量约束
- 影响软件算法的计量采样方案
- M-Bus 或无线模块集成
- 软件行为依赖继电器状态或硬件能力的负控需求

规则层需要输出置信度。低置信度项进入 LLM。

## 提示词工程

新增专门面向需求分析 Agent 的 prompt，不把这部分职责塞进现有 `ai_extract` prompt。

角色定义建议：

> 你是电表软件需求分析工程师。你的任务不是翻译原文，而是基于可追溯的抽取结果推导软件研发需求。

Prompt 必须包含：

- 归属选项：`software`、`hardware`、`co_design`。
- 内部软件模板字段。
- 从模板工作簿抽取的模块和子模块词表。
- 来源需求 ID。
- 来源 block ID 和原文引用。
- 相邻章节上下文。
- 可用的 KB 匹配和结构化 COSEM 元数据。
- 明确的处理深度规则：
  - Hardware：只做简要处理。
  - Software：做详细软件需求分析。
  - Co-design：软件侧详细分析，硬件侧只写依赖和待确认项。

Prompt 必须禁止：

- 编造来源中没有的事实。
- 修改数字、OBIS、DLMS class ID、阈值、日期、持续时间或访问权限。
- 给硬件-only 项生成软件需求。
- 只返回原文翻译。

Prompt 需要要求模型在最终 JSON 前做自检：

- 归属判断是否合理。
- 软件输出是否包含输入或触发、处理行为、输出或状态变化、验收建议。
- 是否保留 source ID 和 source quote。
- 标识符和数字是否未漂移。
- 硬件-only 项是否没有进入软件需求模板。

## 模板词表

内部软件工作簿应作为词表来源：

- sheet 名作为优先模块名。
- 每个 sheet 的 `子模块` 列作为优先子模块名。
- 如果无法匹配，Agent 可以输出 `template_match: "unmapped"`，并提出新的模块或子模块建议。

这样既能复用现有标准模块，又能兼容客户文档中出现的新功能。

## 结构化输出

每条分析项建议使用如下 schema：

```json
{
  "analysis_id": "ANREQ-000001",
  "source_kind": "ai_requirement | atomic_requirement",
  "source_requirement_ids": ["..."],
  "source_block_ids": ["..."],
  "source_section": "...",
  "source_quote": "...",
  "ownership": "software",
  "ownership_confidence": 0.86,
  "ownership_reason": "...",
  "ownership_source": "llm",
  "module": "时钟需求",
  "submodule": "时钟",
  "template_match": "matched",
  "description": "夏令时默认时段",
  "requirement": "软件应支持配置并应用夏令时开始和结束时段。",
  "software_requirement_text": "系统应根据配置的夏令时开始/结束时间更新时钟偏移，并在跨越切换点时保持计量、事件和曲线时间戳一致。",
  "developer_guidance": [
    "读取 Clock 对象相关配置。",
    "校验开始/结束时间格式和边界。",
    "切换时生成可追溯的时间状态变化。"
  ],
  "hardware_dependency": "",
  "acceptance_criteria": [
    "配置有效夏令时时段后，跨越开始时间时系统时间按要求偏移。",
    "跨越结束时间后系统时间恢复，事件和曲线时间戳连续可解释。"
  ],
  "open_questions": [],
  "notes": []
}
```

硬件-only 项可以省略软件专用字段，或置为空，但必须保留归属原因和来源追溯。

## HTML 审查改造

现有 `document_annotation.html` 应为每条 AI 需求增加可编辑归属控件：

```text
归属:
  软件
  硬件
  软硬件协同
```

导出的裁决 JSON 应包含：

```json
{
  "ai_req_id": "...",
  "status": "accepted",
  "module_override": "...",
  "ownership_override": "software",
  "reason": "..."
}
```

导入逻辑应把 `ownership_override` 持久化到 `ai_review_states.jsonl` 或等价的本地裁决文件。`requirements_analysis` 运行时必须先应用这个 override，再运行规则或 LLM。

## 软件 Excel 输出

生成 `software_requirements.xlsx`，只包含 `software` 和 `co_design` 的软件侧条目。

工作簿应尽量贴近内部软件模板，按模块分 sheet，并包含这些列：

```text
关闭
序号
子模块
描述
需求模版
需求
说明、示例、注意事项
是否客户需求
客户需求章节
驱动/硬件相关
项目负责人确认
测试负责人确认
研发测试确认
功能是否实现
测试用例号
测试是否完成
```

字段映射：

```text
子模块 <- submodule
描述 <- description
需求模版 <- matched template hint or empty
需求 <- software_requirement_text
说明、示例、注意事项 <- developer_guidance + source_quote + open_questions
是否客户需求 <- 是
客户需求章节 <- source_section + source_requirement_ids
驱动/硬件相关 <- co_design 为 是，software 为空或 否
```

这个工作簿是软件交付物。硬件-only 项不得进入该 Excel。

## 错误处理

- 如果模板工作簿缺失，回退到内置最小模块词表，并继续写 JSON。
- 如果 LLM 未启用，规则层仍应分类高置信度项，并写出部分分析结果。
- 如果某个 LLM 批次失败，记录可恢复失败项和来源 ID，并继续处理其他项。
- 如果人工 override 与规则或 LLM 分类冲突，使用人工 override，并在 `notes` 中记录冲突。
- 如果条目无法可靠映射到模板模块，标记为 `unmapped`，并在报告中单独列出。

## 测试

需要增加聚焦测试：

- 规则归属分类。
- 人工 ownership override 优先级。
- 从类似模板的 workbook 中抽取模块和子模块词表。
- LLM 响应校验和漂移检查。
- 软件 Excel 排除硬件-only 项。
- 协同项同时出现在软件 Excel 和协同报告。
- JSON 输出保留 source requirement ID 和 source block ID。
- stub route 在无 LLM 时产出确定性的部分结果。

## 成功标准

第一版实现成功的标准：

- 每条 AI 需求都可以携带软硬件归属分类。
- HTML 审查页可以修改归属，并能导入回本地裁决。
- 硬件-only 项被简要总结，但不会进入软件 Excel。
- 软件项和协同项的软件侧能生成有用的软件需求说明，而不是只做翻译。
- 软件 Excel 足够接近内部模板，软件工程师可以审阅模块、子模块、描述、需求、说明、来源和硬件依赖。
- 全部分析结果都能追溯回原始段落和需求 ID。
