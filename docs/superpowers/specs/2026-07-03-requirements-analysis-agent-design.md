# Requirements Analysis Agent Design

Date: 2026-07-03
Status: Draft for user review

## Background

Requirement Atomizer currently extracts atomic requirements from standards and customer documents, then supports AI extraction, paragraph-level HTML review, and merged specification exports. This is useful for source coverage and traceability, but it does not yet match the target product goal: helping a software engineer turn a requirement document into actionable software requirements.

The current result has two major gaps:

- It does not explicitly separate software, hardware, and software-hardware co-design requirements.
- Software items often read like translated source text instead of software development requirements with behavior, inputs, outputs, constraints, and test guidance.

The user provided an internal software standardized requirements workbook:

`D:/Users/YunHeYang/Desktop/Canna/Canna-29/电表软件标准化需求列表-V2.3.12 - 2026-4-14.xlsx`

This workbook is a reference for software requirement output only. It must not define the hardware output format.

## Goal

Add an independent requirements analysis agent stage that consumes existing extraction outputs and produces engineering-oriented analysis:

- Classify each requirement as `software`, `hardware`, or `co_design`.
- Briefly process hardware-only items.
- Deeply analyze software items and the software side of co-design items.
- Export software requirements in a workbook format aligned with the internal software template.
- Keep a structured JSON output for testing, review, and future iteration.
- Allow human reviewers to correct ownership in the existing paragraph-level HTML review flow.

## Non-Goals

- Do not replace `atomize.py`.
- Do not replace `ai_extract.py`.
- Do not force hardware requirements into the software template.
- Do not build detailed software sub-classification yet. The first phase only classifies ownership into software, hardware, and co-design.
- Do not let LLM output silently change identifiers, OBIS codes, DLMS class IDs, thresholds, times, or source references.

## Recommended Approach

Create a new post-extraction stage, tentatively named `requirements_analysis`.

Existing stages keep their responsibilities:

```text
atomize
  Deterministic parsing, table extraction, atomic candidates, KB matching.

ai_extract
  AI-assisted behavioral requirement extraction with source anchoring, context engineering, cache, and self-check.

requirements_analysis
  Engineering ownership classification, software requirement elaboration, co-design split, and software-template export.
```

This separation keeps extraction coverage and engineering interpretation debuggable independently.

## Data Flow

```text
input document
-> atomize
   -> blocks.jsonl
   -> table_items.jsonl
   -> atomic_requirements.jsonl
-> ai_extract
   -> ai_requirements.jsonl
   -> ai_extract_quality.json
-> document_annotation.html
   reviewer may edit status, module, ownership, and reason
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

The analysis stage should read reviewer decisions first. Human overrides always win over rules and LLM decisions.

## Ownership Model

Every analyzed item receives:

```json
{
  "ownership": "software | hardware | co_design",
  "ownership_confidence": 0.86,
  "ownership_reason": "Reason based on requirement content and source context",
  "ownership_source": "rule | llm | reviewer_override"
}
```

### Software

Software items should be analyzed in detail. Output should include a software requirement statement, developer guidance, acceptance criteria, source traceability, and open questions.

### Hardware

Hardware items should be processed lightly. They should not be exported into the software template. Output should include the hardware concern, source traceability, reason for hardware classification, possible software impact, and open questions.

### Co-Design

Co-design items should appear in both:

- The co-design report, with software-side and hardware-side responsibilities.
- The software workbook, because software engineers must not miss hardware-dependent software work.

For co-design rows in the software workbook, the `驱动/硬件相关` column should be marked as `是`.

## Rule + LLM Strategy

The first pass is deterministic rules. LLM is used for uncertain ownership, software elaboration, co-design splitting, and aggregation.

### Rule Examples

Likely software:

- DLMS/COSEM protocol behavior
- COSEM object access and configuration
- Event recording
- Load profile and capture logic
- Tariff, billing, settlement, prepaid logic
- Push, P1, display, status word, upgrade logic

Likely hardware:

- Metering chip model
- CT or shunt sampling type
- Relay physical capability
- Power supply or battery constraints
- Communication module frequency
- Mechanical structure
- Physical lifetime or component-level endurance

Likely co-design:

- Driver and hardware interface requirements
- Communication port capability and baud-rate limits
- DataFlash or storage capacity constraints
- Metering sampling choices that affect software algorithms
- M-Bus or wireless module integration
- Relay control where software behavior depends on hardware state or capability

Rules should produce a confidence value. Low-confidence items go to LLM.

## Prompt Engineering

Add a dedicated prompt for the requirements analysis agent. Do not overload the existing AI extraction prompt.

The prompt should define the role as:

> You are an electricity meter software requirements analyst. Your job is not to translate the source text. Your job is to derive software engineering requirements from source-backed extracted requirements.

The prompt must include:

- The ownership choices: `software`, `hardware`, `co_design`.
- The internal software template fields.
- The template module and submodule vocabulary extracted from the workbook.
- Source requirement IDs.
- Source block IDs and source quotes.
- Nearby section context.
- KB matches and structured COSEM metadata when available.
- Explicit processing depth rules:
  - Hardware: brief handling only.
  - Software: detailed requirement analysis.
  - Co-design: detailed software side, brief hardware dependency.

The prompt must forbid:

- Inventing source facts.
- Changing numeric values, OBIS codes, DLMS class IDs, thresholds, dates, durations, or access rights.
- Producing software requirements for hardware-only items.
- Returning only a translation of the source text.

The prompt should require a self-check before final JSON:

- Is the ownership plausible?
- Does software output include input or trigger, processing behavior, output or state change, and acceptance guidance?
- Are source IDs and quotes preserved?
- Are identifiers and numbers unchanged?
- Are hardware-only items kept out of the software workbook?

## Template Vocabulary

The internal software workbook should be parsed as a vocabulary source:

- Sheet names become preferred module names.
- Each sheet's `子模块` column becomes preferred submodule names.
- If no good match exists, the agent may output `template_match: "unmapped"` and propose a new module/submodule.

This enables controlled output while still allowing new customer-specific functionality.

## Structured Output

Each analysis item should use a schema shaped like:

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

Hardware-only items may omit software-specific fields or leave them empty, but must preserve ownership reason and source traceability.

## HTML Review Changes

The existing document annotation HTML should add an editable ownership control for each AI requirement:

```text
归属:
  软件
  硬件
  软硬件协同
```

Exported decision JSON should include:

```json
{
  "ai_req_id": "...",
  "status": "accepted",
  "module_override": "...",
  "ownership_override": "software",
  "reason": "..."
}
```

Import logic should persist `ownership_override` in `ai_review_states.jsonl` or an equivalent local decision file. The analysis stage must apply this override before running rules or LLM.

## Software Workbook Output

Generate `software_requirements.xlsx` for software and co-design software-side items only.

The workbook should be close to the internal software template, with module sheets and these columns:

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

Field mapping:

```text
子模块 <- submodule
描述 <- description
需求模版 <- matched template hint or empty
需求 <- software_requirement_text
说明、示例、注意事项 <- developer_guidance + source quote + open questions
是否客户需求 <- 是
客户需求章节 <- source_section + source_requirement_ids
驱动/硬件相关 <- 是 for co_design, empty or 否 for software
```

The workbook is a software deliverable. Hardware-only items must not be included there.

## Error Handling

- If the template workbook is missing, fall back to a built-in minimal module vocabulary and still write JSON.
- If LLM is disabled, rules still classify high-confidence ownership and write partial analysis.
- If LLM fails for a batch, write recoverable failures with source IDs and continue.
- If reviewer overrides conflict with rule or LLM classification, use reviewer override and record the conflict in `notes`.
- If an item cannot be confidently mapped to a module, mark it as `unmapped` and include it in a report section.

## Testing

Add focused tests for:

- Rule-based ownership classification.
- Reviewer ownership override precedence.
- Template vocabulary extraction from workbook-like sheets.
- LLM response validation and drift checks.
- Software workbook excludes hardware-only items.
- Co-design items appear in both software workbook and co-design report.
- JSON output preserves source requirement IDs and source block IDs.
- Stub route produces deterministic partial outputs without LLM.

## Success Criteria

The first implementation is successful when:

- Every AI requirement can carry an ownership classification.
- HTML review allows ownership correction and imports it back.
- Hardware-only items are summarized but excluded from the software workbook.
- Software and co-design software-side items produce useful software requirement text, not just translation.
- The software workbook resembles the internal template enough for a software engineer to review module, submodule, description, requirement, notes, source, and hardware dependency.
- The full result is traceable back to source paragraphs and requirement IDs.
