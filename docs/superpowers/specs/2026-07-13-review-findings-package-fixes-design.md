# 0713 Review Findings and Packaging Fix Design

## Goal

修复 `0e48704..668b372` 审查确认的六项问题，确保旧输出目录能获得新解析行为、数值漂移仍可追踪、硬件卡不展示软件研发指引、翻译拒绝原因首次导出即可见，并重新生成可试用的 Windows portable 程序。

## Scope

1. `atomize` 和 `ai-extract` 的 producer implementation revision 各递增一次，使修复前 manifest 不可复用。
2. `requirements-analysis` 阶段输入指纹加入 `term_map.json`。
3. 相邻需求标题继续进入提示词，但不再进入普通数字豁免基线；只有文档背景数字保留现有软豁免。
4. Vue 应用内硬件需求卡始终隐藏研发指引和验收建议，与自包含 HTML 保持一致。
5. annotation translation 本轮新增翻译或拒绝记录时都重新渲染 HTML。
6. 删除 `text_normalize.py` 文件尾多余空行，使增量通过 `git diff --check`。

## Architecture

修复保持在问题所属模块内，不改变 JSON schema、API 路径或 UI 交互协议。阶段复用仍使用现有 producer 和输入指纹机制；数值护栏仍保留“普通整数软提示、受保护编码硬拒绝”的现有策略，只纠正 siblings 的基线来源；批注两个渲染面共享“硬件只展示翻译/说明”的语义。

## Data Flow

- `pipeline -> stage_is_reusable`: 新 producer 令旧 atomize/ai-extract manifest 失效；`term_map.json` 内容变化会改变 requirements-analysis fingerprint。
- `requirements_analysis -> validate_llm_item`: `doc_context` 可提供普通数字背景豁免，`siblings` 仅影响生成提示，不提供数值依据。
- `generate_annotation_translations -> export_annotation_bundle`: sidecar 出现 translated 或 rejected 新条目时重渲染，首次 HTML 即嵌入译文或拒绝原因。
- `build_ai_requirements -> DocumentReview`: hardware 卡只展示中文翻译/说明和归属原因，不回退抽取轨软件研发/验收列表。

## Error Handling

- LLM 翻译调用失败或漏答仍保持 pending，下次导出重试。
- 被拒翻译继续留 sidecar，不嵌入译文，只嵌入拒绝原因。
- 缺失 `term_map.json` 时指纹记录空输入，不影响旧输出目录运行。
- 不修改或删除主工作区未跟踪的 `硬件` 文件。

## Verification

- 每项修复先增加失败回归，再实施最小修改。
- 运行相关 Python/Vitest 测试、全部 Python 测试、全部前端测试、TypeScript/Vite build。
- 运行 `git diff --check`。
- 执行 `npm run desktop:pack`，检查 portable `.exe` 和内嵌 backend 文件存在且非空。

## Acceptance Criteria

1. 修复前 `atomize+impl-v2`、`ai-extract-v15+impl-v2` manifest 均不可复用。
2. 仅修改 `term_map.json` 会改变 requirements-analysis fingerprint。
3. 当前需求原文无 `60`、仅 sibling 标题有 `60` 时，输出中的 `60` 产生 fabricated-number 软提示。
4. hardware 卡不渲染抽取轨 `dev_guidance` 或 `acceptance_criteria`。
5. 全部翻译被拒时，第一次导出的 HTML 已包含 `data-*-translation-note`。
6. 测试、构建、diff 检查和 portable 打包全部成功。
