# CLAUDE.md — Requirement Atomizer 项目上下文

> 本文件供 Claude Code 在任何机器上自动加载。包含协作工作流、当前状态与关键决策。
> 状态快照截至 2026-06-27，里程碑推进后请同步更新本文件。

## 项目是什么

把技术标准文档（DOCX/XLSX/PDF）原子化为可审查的需求条目，**终点是装配成给研发团队的 DLMS/COSEM 实现规格**：
确定性解析 → 规则候选 → LLM 审查（OpenAI 兼容，本地/云端可切换）→ 专家工作台（**Vue3+Electron 桌面应用 + 本地 API**）→ 导出 / 装配实现规格（`assemble`/`compose`）。
CLI 契约见 `docs/cli-contract.md`（对接公司任务管理系统的接口承诺，exit 0/2/3/4，stdout 为 UTF-8 JSON 信封）。

## 协作工作流（重要）

1. **Claude 写修改方案**（带验收标准）→ 用户转交 ChatGPT/Codex 实现
2. **实现必须在隔离 git worktree**（分支 `codex/*`），审查通过前不合 main、不推送
3. **Claude 复查**：实测优先——mock HTTP 服务打故障场景、真实文档逐字节等价对比、打包产物在仓库外验证、GUI offscreen 截图
4. 用户决定合并；合并后在 main 跑全量测试（golden 六项只在 main 的 out/ 基线存在时执行）

> 2026-06-14 起「需求文档生成」轨道由 Claude 直接实现并自查（仍在 `codex/*` 分支、实测优先、用户决定合并、push 需用户同意）；解析等既有轨道沿用上面的 Codex 转交流程。
> 2026-06-27：**GUI 正式以 Vue3+Electron（`ui/`）为准，PySide6（`gui/`）冻结**；终点交付物（`assemble`/`compose` 实现规格）数据完整性修复由 Claude 直接实现并自查（同上轨道纪律）。
> 换机继续：项目上下文靠本文件 + `~/.claude/.../memory/` 自动加载；完整聊天 transcript 在 HOME `~/.claude/projects/<proj>/`，**不进代码仓**（含客户文档/业务细节，公开仓会泄密），如需带走走私有同步。

## 回归纪律

- `golden_sets/abnt_nbr_16968_v5/golden_summary.json` 是冻结基线；动它必须逐项写明原因
- 真实测试文档：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.docx`（机器相关路径，换机器需调整）
- 真实测试 PDF：`C:\Users\YYHwudi\Desktop\Canna-29\Appendix 9-ABNT NBR 16968-2022 EN.pdf`（同目录文字层 PDF；旧 `D:\Codex\abnt_converted.pdf` 已失效）
- 测试命令：`python -m unittest discover -s tests`（venv 在 `.venv/`，Python 3.14 / python-docx 1.2.0 / pdfplumber / openpyxl 已装；PySide6 未装时 GUI 测试 skip）

## 重大更新（2026-06-27）

- **GUI 决策（已拍板，勿重新讨论）**：仓库里 PySide6（`gui/`）与 Vue3+Electron（`ui/`）两套 GUI 并存，**正式产品以 Vue3+Electron 为准**，PySide6（`gui/`）**冻结、不再投入**。GUI 改动只动 `ui/`，不碰 `gui/`。下文历史段里凡写「专家工作台(PySide6)」均指已冻结的旧壳。
- **平台架构演进（以 `README.md` 为最新）**：核心 Python（`atomize`/`cli`/`assemble_spec`/`engineering_composer`）+ **本地 API `api_server.py`**（只读 + 审查写入端点，origin allowlist + 可选 token）+ **Electron 任务桥 `desktop_tasks.py`** + **Vue3+Electron UI `ui/`**；知识库迁为 **`requirement_kb/` 包**（Obsidian vault → 编译 JSON）；解析器在 **`parsers/`**（docx/xlsx/pdf）。
- **终点交付物数据完整性修复（Phase 1+2，分支 `codex/spec-data-integrity`）**：一轮严格 code review 发现并修复 5 项直接污染研发实现规格的缺陷——
  - **H1 OBIS 静默拆码**：`cosem_object_model._normalize_single_obis_value` 移除无证据的「2 位值组拆单数字」（会把 `0-0:96.1.0` 静默腐蚀成 `0-0:9.6.1.0`，违反"OBIS 错一位即严重"）；缺分隔点的修复改走空格还原路径（仅在有空格证据时）。
  - **H4 访问权限错列**：`parse_access` 切不出 4 段时不再把整串塞 RC 列；新增统一 `access_cells()` 渲染（cosem MD/CSV + `assemble_spec` 门限表共用），四列留空 + 新增 `access_raw` 列追溯 + MD 未解析附录。真实 ABNT 1425 行 **0 错列**（`Association LN.add_user -/-/-A--` 入待审附录）。
  - **公式注入**：新增 `text_normalize.formula_safe()`，中和 Excel/CSV 里 `= + - @` 开头单元格（豁免纯数字与 DLMS 访问码），应用于 `spec_excel` 与 cosem CSV 导出。
  - **H2 审查校验绕过**：`llm_review_schema` 把必填字段 `None` 视为缺失，恢复 schema 修复回路（此前 `decision=None`/`confidence=None` 静默过校验）。
  - **H3 KB id 遮蔽**：`requirement_kb.repository.get()` 改首个/权威优先 + 新增 `id_collisions()` 暴露冲突（默认 4 库 86 处），不再随加载顺序静默遮蔽权威条目。
  - 验收：**全量 416 tests 全绿**（含各项新增回归），atomize golden 未动，真实 ABNT 端到端 `assemble` 注入样本 0 活公式。
- **Phase 3 端到端硬化与 gui 冻结（分支 `codex/phase3-golden-and-freeze`）**：
  - **P3-A 终点交付物 golden 回归**（`tests/test_spec_deliverable_regression.py`）：合成 fixture（含 H1/H4/注入触发场景）端到端跑 `assemble`→Excel，锁定 OBIS 稳定 / access 零泄漏 + `unresolved_access` 计数 / Excel 零活公式 / 计数。fresh-clone 可跑——把 Phase 1+2 修复变成永久回归（此前终点交付物零回归保护）。
  - **P3-B 解耦 `review_actions`**：从 `gui/` 提升到顶层 `review_actions.py`，`api_server` 改 import，`gui/` 成无人依赖的纯 PySide6 叶子；`ui/package.json` 打包配置同步移除 `../gui` 拷贝（后端依赖已被顶层 `*.py` 覆盖）。
  - **P3-C Vue3 前端 5 项 UX 修**：API 错误体透出后端原因（不再只显示状态码）、`originalText` 回退 `source_context.paragraph_text`、`confidenceFilter` 默认「全部」、审查按钮 `isSubmitting` 防抖、审查意见 textarea 接 `v-model` 并作为 `reason` 提交。`vitest 39 + vue-tsc` 全绿。
  - **P3-D gui 冻结**：README 标注 `gui/` 冻结。**保留代码/入口/测试**（冻结≠删除；`test_platform_scaffold` 契约化了 `ratomizer-gui` 入口，且不删能跑的东西）。
  - 验收：**Python 420 tests + ui vitest 39 + vue-tsc** 全绿。
- **测试规模**：196 → **420 tests**（`python -m unittest discover -s tests`）+ ui `vitest 39`。

## 当前状态（2026-06-16）

- **已合入 main**：M1a CLI 契约、M1b GUI 审查工作台、M2 LLM 审查路由、M3 document_profile + PyInstaller 双 exe、M4a Excel 接入、M4b PDF 文字层、A1-PDF-1（`first_field_value` 去空格 fallback + `pdf_parser` 段落切分透传 document_profile，0.7.1）、GUI Phase 1 仪表盘重构 + 复查修订（`5f9e059`）
- **需求文档生成轨道 P1-P5 全部落地（2026-06-15）**：P1 数据字典 `cosem_object_model.py`、P2 访问/安全矩阵 `cosem_access_security.py`、P3 功能/行为派生 `cosem_behavior_spec.py`（已对齐公司格式 + 13 质量规则）、**P4 外部规范交叉引用索引 `cosem_external_refs.py`（`9f4e3be`，确定性零 LLM）**、P5 装配 `assemble_spec.py` + **人读导出 `spec_export.py`**（JSON 喂公司工具链 + Word/MD 人读规格：按功能域分组、带溯源、外部规范附录）；均有单测
- **生成器接入 GUI + 标签精化（2026-06-16，`e5815d1`，已推 origin）**：① 专家工作台应用栏「装配实现规格」按钮（`gui/pipeline_worker.AssembleSpecWorker` 复用后台线程）→ 结果对话框；② 左栏「实现规格」整段需求视图（`gui/spec_view.py`，按 21 领域分段、复用 `spec_export.group_by_domain`，与导出同分组）；③ **Excel 导出 `spec_excel.py`**（版式移植公司 requirement-analyst 技能的 `generate_excel`，逐 sheet 一致；装配默认产 JSON+xlsx+docx+md）；④ **标签精化**：`requirement_schema.map_labels` 按对象名分类、特定域优先于「通信协议」（事件记录/状态字排在计量前处理 current=当前 假朋友）+ `assemble_spec` P1 用对象名分类——**通信协议 388→77**，计量/事件记录/安全/门限范围/需量各就各位
- **剩余**：① P1-P5 + requirement_schema/text_normalize/spec_export/spec_excel 未注册进 pyproject `py-modules`（独立小清理；打包靠 ratomizer.spec 的 hiddenimports 兜住）；②（可选）**描述 LLM 富化**——Excel/规格版式已对齐 skill，但 `description` 仍是确定性模板，不如 skill 的 LLM 叙述丰富；富化时须保留 OBIS/CL/访问位等结构字段确定性不变（防幻觉）
- **本机环境（E:\Codex\requirement-atomizer-github，Python 3.14 + PySide6 6.11 / pdfplumber / openpyxl / pyinstaller 全装）**：196 tests 全绿；真实 docx/PDF 在 `C:\Users\YYHwudi\Desktop\Canna-29\`、golden 基线输出在 `out/abnt_nbr_16968_atomizer_v5/`（带三个 `--kb` 生成）
- **暂缓**：M4c 扫描件 OCR（等英文扫描件语料攒够再立项）

> A1-PDF-1 验收实测（2026-06-13，真实 ABNT 文档）：DOCX golden 六项全绿（DOCX-safe，fallback 仅精确匹配失败时触发）；PDF 候选 326→1991（达 DOCX 基线 2337 的 85%），`cosem_object_instance`=363 与 DOCX 精确相等；全量 128 tests 全绿。注意 golden 必须带三个 `--kb` 生成，否则 llm_tasks / 类型分布 / domain_table_candidate_ratio 会假漂移。

## 需求文档生成轨道（研发实现规格）—— 2026-06-14 立项

> 用户已确认：原子化只是中间产物，终点是把 atom 装配成给**研发团队**的可落地实现规格（据此实现 DLMS/COSEM 计量软件）。此轨道由 Claude 直接掌控实现。

- **目标分两层**：
  - 数据/配置层（对象模型、OBIS、class_id、访问矩阵 RC/PC/SC/LC、单位、事件枚举）——已在结构化字段，**装配优先**、可逐字段验证，是 DLMS 实现规格主体。
  - 行为/协议层（GET/SET/ACTION 语义、关联建立/HLS 握手状态机、加密策略、错误/access-result 码）——ABNT profile 多为交叉引用 DLMS Green/Blue Book，atom 里没有，需 LLM 派生 + 引进核心文档当 KB，**高幻觉风险**。
- **关键技术事实**：cosem atom 由 `table_item` 生成；结构化字段（OBIS、CL=class_id、属性、访问权限、单位）经 `source_refs → source_index → table_item.fields` 可确定性取回（GUI 详情面板已这么 join）；`verification_method` 已 denormalize 到每个 atom（验收/验证方法的种子）。**数据字典 = 确定性 join，不用重抽。**
- **范围真相**：单凭一份 ABNT profile 文档 → 极好的数据字典 + 访问矩阵，但行为/协议单薄；完整实现规格迟早要把 DLMS Green/Blue Book 作为额外输入/KB。
- **阶段（状态截至 2026-06-15，P1-P5 全完成）**：P1 数据字典 ✅ / P2 访问安全矩阵 ✅ / P3 功能行为派生 ✅（已对齐公司格式 + 13 质量规则）/ **P4 协议交叉引用 ✅**（C 折中：确定性引用索引，零 LLM；按 manifest 源文件名排除文档自身号；Green/Blue Book 俗称仅附 5-3/6-1/6-2 并标公开常识）/ **P5 装配 + 人读导出 ✅**（JSON + Word/MD/**Excel**，按功能域分组、带溯源、外部规范附录）。**已接入 GUI（2026-06-16，`e5815d1`）**：装配按钮 + 整段需求视图 + Excel 导出（对齐公司 skill `generate_excel` 版式）；标签精化使分段准确（通信协议 388→77）。
- **策略已定：装配优先**（契合"OBIS 码错一位是严重缺陷 / 数字双引擎"防幻觉纪律）。与 M4c OCR 正交。

## 下一步行动（优先级排序，2026-06-16 更新）

> 远程 main = `e5815d1`（已推送，196 tests 全绿）。「生成器接入 GUI」与「标签精化」已完成（本轮 `e5815d1`）；下面是剩余项。

1. ~~生成器接入 GUI~~ ✅ 已完成（装配按钮 + 整段需求视图 + Excel 导出，`e5815d1`）
2. ~~标签精化~~ ✅ 已完成（通信协议 388→77，`map_labels` 按对象名分类、特定域优先）
3. ~~描述 LLM 富化~~ ✅ 已完成（`spec_enrich.py`，**仅 P3 行为**；默认 stub 零 LLM；内容指纹缓存 + 编码/数字漂移护栏；结构字段全程冻结）。真实 GLM-5.2 验证：P3 6/6 富化、0 漂移；P1 对象剔除（护栏挡不住"已有码错位"）；GLM-5.2 是推理模型，`ENRICH_MIN_MAX_TOKENS=2048`。**已接入 GUI**：装配应用栏「LLM 富化描述」勾选框（默认关，与 M2 审查解耦；`AssembleSpecWorker(enrich_route=…)`；结果对话框显示富化/拒绝/失败计数）；端点配置走设置面板
4. ~~打包完整性~~ ✅ 已完成（`8ac4f2b`：spec_enrich 补进 ratomizer.spec、36 个根模块全注册进 pyproject py-modules、build.ps1 加 `--smoke-assemble` 防"生成器未收全即崩"回归）
5. **pyproject py-modules 统一注册** ~~（已并入第 4 项）~~——P1-P5 + requirement_schema / text_normalize / spec_export / spec_excel 都没注册进 `[tool.setuptools] py-modules`（独立小清理，便于 pip 安装；打包已靠 `ratomizer.spec` 的 hiddenimports 兜住）。
5. **M4c 扫描件 OCR**——等英文扫描件语料攒够再立项（选型见下「关键产品决策」）。

## 关键产品决策（已拍板，勿重新讨论）

- 输入格式：Word(.docx)/Excel(.xlsx)/PDF；扫描件 PDF 占比大，OCR（M4c）必做
- 语言：**90% 英文，只做英文**；小语种全部挂起（将来倾向"先翻译后处理+原文对照"）
- LLM：统一 OpenAI 兼容客户端（`llm_client.py`），本地 Ollama / 云端 GLM 经 `llm_agents/review_pipeline.yaml` 切换；密钥只走环境变量；审查范围默认 targeted
- M4c OCR 选型方向：Tesseract（仅 eng 包）+ 框线表格 CV 切格逐格 OCR；ML 表格模型仅兜底；VLM 只做辅助纠错且数字/编码需双引擎一致（防幻觉，OBIS 码错一位是严重缺陷）；OCR 置信度直通 confidence/ambiguity → targeted 审查 → 专家队列
- 专家评审语义：`apply_expert_decision` 是裁决覆盖（除 frozen 外任意状态可改），自动管线走严格状态机

## 用户待办

- 攒英文扫描件 PDF 测试语料（5-10 份，不同扫描质量/表格密度/脏样本），M4c 立项用
- 第一份真实客户 Excel 到手后走 A1 差距报告流程（GPT 出报告 → Claude 技术筛查 → 用户拍板 → 再修）
