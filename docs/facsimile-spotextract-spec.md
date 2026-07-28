# Word/Excel 影印支路 + 点解析 实施规格（冻结）

日期：2026-07-28
状态：已冻结，实施中
前置：PDF 影印链路（`doc_annotation_export.py` document_pages + geometry + Vue 页图视图）、
`omission_actions.targeted_reextract`、参数表行展开（guards-v16）

## 0. 定位

两个工作包，共享"行级定位"基础，一起实施：

- **WP-A 影印支路**：docx/xlsx 审查界面获得与 PDF 一致的原文版式影印视图
  （页图 + 页码 + 分页标记 + 引句页定位）；
- **WP-B 点解析**：批注视图任意行/块可单独触发定向解析，结果进澄清待确认。

铁律不变：结构化字段确定性裁决；确定性行为/产物变更 bump 对应版本并进 chain 戳；
影印缺失如实降级（不得用文本视图冒充影印）；点解析结果如实标 `spot_extract` 来源。

## 1. WP-A：影印支路

### 1.1 转换层（新模块 `doc_facsimile.py`，注册 py-modules）

- `convert_to_pdf(input_path, work_dir) -> Path | None`：
  1. **首选 Word/Excel COM**（Windows Office；`win32com.client`，Word `SaveAs2(FileFormat=17)` /
     Excel 同理 `ExportAsFixedFormat`）——Office 自家排版引擎，保真最高；
  2. **LibreOffice `soffice --headless --convert-to pdf --outdir`** 兜底；
  3. 两者均不可用 → 返回 None，调用方如实走现有文本批注视图（日志记录降级原因）。
- COM 调用全程单线程、带超时与进程清理（Office 进程不得残留）；`pywin32` 进
  requirements.txt/pyproject（Windows 条件依赖 `pywin32; sys_platform=="win32"`）。
- **懒转换**：不在 atomize 主管线跑；在 `export-annotation-html` 阶段按需触发。
  产物 `out/document_facsimile.pdf`（保留供重渲染），以输入文件内容指纹 +
  `DOC_FACSIMILE_VERSION` 做缓存，指纹不变不重转。

### 1.2 影印渲染接入（`doc_annotation_export.py`）

- 现有 `_resolve_pdf_geometry` 目前只认原生 PDF 输入；扩展为：docx/xlsx 输入时若
  `document_facsimile.pdf` 存在（或现场转换成功），按其走现有页图渲染 + 几何 +
  锚定路径——**渲染代码零分叉**，只是 PDF 来源不同。
- 引句锚定仍在 blocks；页映射用转换后 PDF 的几何（Office 转换文本层质量高，
  与原生 PDF 锚定路径一致）。转换失败/无转换器：维持现状文本批注，报告
  `facsimile: "unavailable:<reason>"`，不伪造页图。
- 版本：`DOC_FACSIMILE_VERSION = "doc-facsimile-v1"`；annotation 导出相关版本戳
  （`export-annotation-html` 的 chain 戳组成）纳入它；impl 戳按既有惯例随行。
- Vue 侧零改动目标（已有"有页图就显示"逻辑）；API（api_server）页图路由对
  docx/xlsx 输出目录同等开放。

## 2. WP-B：点解析（spot extract）

### 2.1 后端（api_server 新端点 + 核心逻辑）

- `POST /api/spot-extract`：`{out_dir, block_id, row_index?}`（row_index 仅表格块）。
- 核心 `spot_extract(out_dir, block_id, row_index=None) -> dict`（放
  `omission_actions` 相邻的新模块 `spot_extract.py`，注册 py-modules）：
  - 表格块 + row_index：该行是需求型参数表行 → 复用 guards-v16 确定性行展开逻辑
    生成一条 draft 需求；否则把该行文本单独送 LLM 抽取（复用 targeted_reextract
    的 LLM 调用与护栏，范围限定该行文本）；
  - 段落块：整块文本送 LLM 单段抽取（同上护栏）；
  - 产出追加进 `ai_requirements.jsonl`（共享文件锁纪律）：`status: draft`、
    `source_mapping: "spot_extract"`、`suspicion_reasons: ["用户定点解析"]`
    （澄清策略新增映射：CAT_AMBIGUOUS/内部核对/IMPORTANT/HARD）、
    `source_block_ids` 如实、`ai_req_id: "SPOT-<block_id>[-R<row>]"` 冲突时加序号；
  - LLM 不可用：响亮报错（envelope ok:false），不伪造 stub 抽取结果；
  - **结果只进 draft + 澄清待确认**（冻结口径：先人工确认再转正，不直接转正）。
- LLM 调用走现有 `ai_extract.config_for_route("openai_compatible")` 与 key 检查。

### 2.2 UI（`ui/src/DocumentReview.vue` 或批注组件）

- 批注视图行/块悬停出现"解析此段"按钮（表格行与段落块都有）；
- 点击调端点，成功 toast 提示"已生成 N 条 draft 需求，进澄清待确认"并刷新；
- 失败如实 toast 错误原因；按钮在无 LLM 配置时不隐藏但点击返回真实错误
  （不假装可用）。

## 3. 测试要求（unittest.TestCase）

- 转换层：COM/soffice/双缺三路径（全部 mock，COM 调用断言参数与清理）；
  缓存指纹命中不重转；版本未 bump 时契约测试失败。
- 影印接入：有 facsimile PDF 时几何/页图产出与原生 PDF 同构；无转换器时
  如实降级字段。
- 点解析：参数表行确定性产出；非参数行 LLM 路径（mock chat）；draft/suspicion/
  provenance 字段；id 冲突序号化；LLM 缺失响亮报错；澄清报告出现「用户定点解析」条目。
- 全部 mock LLM；全量 discover 绿；评测基线不降。

## 4. 验收清单

1. 全量测试绿（新增 ≥15）；
2. 本机真实转换（Word COM 可用）：STO docx 出页图，批注界面 docx 显示影印页；
3. 点解析端到端：真实 out/ 上对术语表行点解析，draft 行进澄清、provenance 正确；
4. 版本：DOC_FACSIMILE_VERSION、guards 不受影响（本批不动抽取行为）、annotation
   戳、impl 戳随行；
5. 无转换器环境如实降级，无伪造页图。

## 5. 明确不做

- 不打 LibreOffice 进安装包（运行时探测）；
- 不动 PDF 原生影印路径；
- 点解析不支持跨行/跨块多选（单行/单块粒度）；
- 不做影印页上的框选解析（行/块粒度足够，框选是另一件事）。
