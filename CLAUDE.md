# CLAUDE.md — Requirement Atomizer 项目上下文

> 本文件供 Claude Code 在任何机器上自动加载。包含协作工作流、当前状态与关键决策。
> 状态快照截至 2026-06-12，里程碑推进后请同步更新本文件。

## 项目是什么

把技术标准文档（DOCX/XLSX/PDF）原子化为可审查的需求条目：
确定性解析 → 规则候选 → LLM 审查（OpenAI 兼容，本地/云端可切换）→ 专家工作台（PySide6 GUI）→ 导出。
CLI 契约见 `docs/cli-contract.md`（对接公司任务管理系统的接口承诺，exit 0/2/3/4，stdout 为 UTF-8 JSON 信封）。

## 协作工作流（重要）

1. **Claude 写修改方案**（带验收标准）→ 用户转交 ChatGPT/Codex 实现
2. **实现必须在隔离 git worktree**（分支 `codex/*`），审查通过前不合 main、不推送
3. **Claude 复查**：实测优先——mock HTTP 服务打故障场景、真实文档逐字节等价对比、打包产物在仓库外验证、GUI offscreen 截图
4. 用户决定合并；合并后在 main 跑全量测试（golden 六项只在 main 的 out/ 基线存在时执行）

## 回归纪律

- `golden_sets/abnt_nbr_16968_v5/golden_summary.json` 是冻结基线；动它必须逐项写明原因
- 真实测试文档：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.docx`（机器相关路径，换机器需调整）
- 真实测试 PDF：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.pdf`（同目录文字层 PDF；旧 `D:\Codex\abnt_converted.pdf` 已失效）
- 测试命令：`python -m unittest discover -s tests`（venv 在 `.venv/`，Python 3.14 / python-docx 1.2.0 / pdfplumber / openpyxl 已装；PySide6 未装时 GUI 测试 skip）

## 当前状态（2026-06-13）

- **已合入 main**：M1a CLI 契约、M1b GUI 审查工作台、M2 LLM 审查路由、M3 document_profile + PyInstaller 双 exe、M4a Excel 接入、M4b PDF 文字层、A1-PDF-1（`first_field_value` 去空格 fallback + `pdf_parser` 段落切分透传 document_profile，0.7.1）
- **下一步**：M4c 扫描件 OCR 方案（等英文扫描件语料攒够立项）

> A1-PDF-1 验收实测（2026-06-13，真实 ABNT 文档）：DOCX golden 六项全绿（DOCX-safe，fallback 仅精确匹配失败时触发）；PDF 候选 326→1991（达 DOCX 基线 2337 的 85%），`cosem_object_instance`=363 与 DOCX 精确相等；全量 128 tests 全绿。注意 golden 必须带三个 `--kb` 生成，否则 llm_tasks / 类型分布 / domain_table_candidate_ratio 会假漂移。

## 关键产品决策（已拍板，勿重新讨论）

- 输入格式：Word(.docx)/Excel(.xlsx)/PDF；扫描件 PDF 占比大，OCR（M4c）必做
- 语言：**90% 英文，只做英文**；小语种全部挂起（将来倾向"先翻译后处理+原文对照"）
- LLM：统一 OpenAI 兼容客户端（`llm_client.py`），本地 Ollama / 云端 GLM 经 `llm_agents/review_pipeline.yaml` 切换；密钥只走环境变量；审查范围默认 targeted
- M4c OCR 选型方向：Tesseract（仅 eng 包）+ 框线表格 CV 切格逐格 OCR；ML 表格模型仅兜底；VLM 只做辅助纠错且数字/编码需双引擎一致（防幻觉，OBIS 码错一位是严重缺陷）；OCR 置信度直通 confidence/ambiguity → targeted 审查 → 专家队列
- 专家评审语义：`apply_expert_decision` 是裁决覆盖（除 frozen 外任意状态可改），自动管线走严格状态机

## 用户待办

- 攒英文扫描件 PDF 测试语料（5-10 份，不同扫描质量/表格密度/脏样本），M4c 立项用
- 第一份真实客户 Excel 到手后走 A1 差距报告流程（GPT 出报告 → Claude 技术筛查 → 用户拍板 → 再修）
