# PDF 现代解析器选型评估（WS1 第 6 周）

> 本文档是 `pdf_modern_adapter.py` 适配层的选型依据。结论供人类决策，**本切片不落任何依赖**。
> 第一标准（实施方案 §3.2.3）：候选解析器的输出结构能否对齐双轨制输入契约（几何矩阵 + 样式证据格式）。量化结论须以金标门禁实测为准，不预设任何工具优势。

## 1. 对齐目标（双轨制输入契约）

适配层归一的目标是 `docx_table_parser.ParsedDocxTable`，即双轨制校验器（`table_geometry_validator`）与提议器（`llm_table_understanding`）共同消费的契约：

| 契约字段 | 用途 | 候选须能提供 |
|---|---|---|
| `matrix: list[list[str]]` | 几何文本矩阵 | 二维文本网格 |
| `cells[(r,c)] → ParsedCell` | 每个规范格（anchor / 独立格） | 逐格坐标 + 文本 |
| `covered_coordinates` | 合并 anchor 的覆盖坐标 | 合并跨度（row_span/col_span 或矩形） |
| `merge_ranges: [(r1,c1,r2,c2)]` | 物理合并矩形 | 合并区域 |
| `style_evidence: {bold/shading/...}` | 角色提示（加粗=表头等） | 逐格样式（可选） |
| `parse_incomplete[_reason]` | 诚实降级 | 解析失败信号 |

**关键不变量**：校验器 rule 2（合并锚点守恒）依赖 `cell.covered_coordinates`。若候选不能提供合并跨度信息（输出已把合并格拍平），rule 2 将无 anchor 可守——这是契约对齐的硬门槛，不是锦上添花。

## 2. 候选矩阵

| 候选 | 契约对齐度 | 合并格物理结构 | 样式证据 | 许可 | 体积 / 依赖 | 备注 |
|---|---|---|---|---|---|---|
| **Docling**（IBM） | **高** | `TableItem.data.grid` + cell 级 `row_span`/`col_span` | 部分（bold/highlight） | MIT | 重（torch/transformers/layouts，模型权重 GB 级，CPU 可跑） | 表格物理还原是其强项；grid + spans 可直接映射 `merge_ranges`/`covered_coordinates` |
| **Marker**（datalab.） | **中** | 输出 GFM pipe table，合并格被拍平/丢失 | 无（纯 markdown） | Marker: 依组件分（surya 等），PDF 主链有商业条款 | 重（surya + torch） | 散文/markdown 强，但表格物理结构弱——合并信息丢失，rule 2 失效 |
| **Camelot** | 中（仅画线表） | 画线表 lattice 精确；无画线表弱 | 无 | GPL（依赖 ghostscript） | 中（ghostscript 系统依赖） | 仅画线表场景强；非画线/扫描件无效 |
| **PaddleOCR PP-Structure** | 中（扫描件） | 表格结构识别模型输出 cell bbox | 弱 | Apache 2.0 | 重（paddlepaddle） | 扫描件 OCR 强；文字层 PDF 过重 |
| **pdfplumber**（现有手写路径） | 基准（手写归一已在用） | 几何聚类推断合并 | 无 | MIT | 轻（已装） | 机翻碎词/词典问题已有 v4 修复层；无 style |

## 3. 归一规约（适配层已实现的映射）

适配层（`pdf_modern_adapter.py`）以"依赖存在则用、不存在则诚实 unavailable"实现，归一规约如下：

- **Docling**：`TableItem` → `data.grid`（矩形化为 `matrix`）；cell 的 `row_span`/`col_span` 重建 `merge_ranges` 与 `covered_coordinates`；`bold`/`highlight` 映射 `style_evidence`。
- **Marker**：markdown → GFM pipe table 解析为 `matrix`；**无合并信息**（`merge_ranges=[]`，每格独立）——rule 2 因此退化为"无 anchor 可守"，仅 rule 1/3 生效。这是 Marker 对齐度被判"中"的根因。
- 任何候选：归一失败 / 空矩阵 → 该表跳过；全部失败 → `status=unavailable`，调用方诚实回退手写 pdfplumber 路径。

> 归一规约基于候选解析器的**公开输出契约**编写，本机无依赖故未实测。Docling cell 级 span 字段名在不同版本有差异，适配层做了多别名防御；真实字段映射须在装依赖后用金标集校准。

## 4. 推荐结论（供人类决策，不落依赖）

1. **首选 Docling 作为现代主路径候选**。理由：唯一同时提供"grid + cell 物理跨度 + 部分样式"的候选，可直接满足双轨制几何矩阵 + 合并锚点守恒契约；MIT 许可无商业壁垒。
2. **不推荐 Marker 作为表格主路径**。其 GFM 输出拍平合并格，使校验器 rule 2（合并锚点守恒）失效——这正是"几何矩阵 + 样式证据"契约要守住的不变量。可作为散文段落抽取的备选评估。
3. **扫描件 OCR（M4c）走 PaddleOCR PP-Structure 单独立项**，与文字层 PDF 主路径解耦（实施方案 §3.2.3 已注明 OCR 支路可顺移）。
4. **切换门槛是"不劣化"，不是"更优"**。任一指标（碎片率 / 漏值 / 覆盖率）在金标语料上劣化即阻断该文档类型切换（实施方案 §3.2.4 第 8 周 A/B 门禁 + 角色语义抽审 ≥95%）。

## 5. 本切片边界与后续

- **本切片交付**：适配层契约 + 归一函数 + `RATOMIZER_PDF_MODERN_PARSER` 降级开关（默认关）。开关开 + 依赖缺位 → 诚实回退手写 pdfplumber 路径并标 `parser_provenance`（可演示）。
- **modern 可用路径当前仅产出表格结构**：散文段落仍是手写路径职责，完整主路径替换由第 8 周 A/B 门禁裁决。这是诚实的渐进式接入，不是隐藏的功能缺口——装依赖后该路径才可达。
- **后续动作（依赖决策落定后）**：① 安装 Docling；② 在金标语料（ABNT/EN16314/SBD/STO）上跑 A/B 三指标；③ 校准 cell span 字段映射；④ 角色语义抽审；⑤ 全指标不劣化才把 PDF 主路径默认切为 modern。
