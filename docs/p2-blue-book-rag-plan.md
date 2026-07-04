# P2 行为层 RAG：Blue Book 摄入 + 确定性检索 + 行为富化（实施方案）

> 写给实现者（GLM/Codex）。分 B1/B2/B3 三期，每期独立分支、独立验收，B1 不过验收不开 B2。
> 最终总验收由 Claude 执行（见文末清单）。工作流沿用仓库纪律：隔离 worktree、`codex/*` 分支、
> 审查通过前不合 main、不推送。

## 0. 背景与目标

ABNT 等 profile 文档 90% 的行为语义是对 DLMS Blue Book 的交叉引用（`cosem_external_refs`
目前只**索引**"引用了哪些外部规范"，从不读其正文）。结果：数据字典极好，但研发真正需要的
**接口类行为**（属性/方法定义、GET/SET/ACTION 语义、数据类型）单薄。

本期把 Blue Book Ed.16 摄入为**确定性可检索索引**，在装配 P3 行为富化时按 class_id 检索对应
条款正文注入 prompt，派生带出处的行为规格。

**素材事实（已实测，pdfplumber 文字层良好）：**

| 文件 | 页数 | 内容 |
|---|---|---|
| `Blue-Book-Ed-16-part-1-V1.0.pdf` | 117 | OBIS 识别系统（value group 语义） |
| `Blue-Book-Ed-16-part-2-V1.0.pdf` | 718 | **COSEM 接口类**（行为语义主体） |

Part 2 全书 `class_id\s*=\s*(\d+)` 锚点 401 处、去重 **102 个 class_id**（含目录页干扰——
摄入器必须区分目录行与正文定义节）。本机 PDF 路径：`C:\Users\YYHwudi\Desktop\Canna-29\`。

## 1. 红线（违反任一条即验收不通过）

1. **版权文件绝不进 git**：两个 PDF 与编译出的索引 JSON（含大段原文）都不进仓库、不进
   fixture。`.gitignore` 加 `blue_book_index.json`。测试 fixture 一律自造迷你文本。
2. **结构字段确定性不变**：OBIS / class_id / 访问位 / 数字仍只来自源文档 `table_items`
   确定性链路。蓝皮书内容只补**行为叙述**，绝不覆盖任何结构字段。
3. **检索是确定性查找，不是语义检索**：class_id / 接口类名 精确匹配，未命中返回 None——
   不猜、不模糊匹配、不引入 embedding/向量库依赖。
4. **出处必带且必须可核**：每条派生行为必须带 `依据 DLMS Blue Book Ed.16 §<节号>`，且该节号
   必须等于**本次注入条款的节号**（防 LLM 编造引用；程序校验，不靠 prompt 约束）。
5. **测试用 unittest.TestCase**：`python -m unittest discover -s tests` 必须能收集到。
   本仓库**没有装 pytest**——模块级 `def test_*` 函数和 `tmp_path` fixture 会被静默跳过、
   零回归保护（前车之鉴：34 条孤儿测试）。用 `tempfile.TemporaryDirectory()`。
6. **默认零行为变化**：不给 `--blue-book-index` 参数（或索引不存在/未命中）时，所有既有
   产物逐字节不变。golden 六项不动。

## 2. 架构（三个新模块 + 一处接入）

```
blue_book_ingest.py   B1 摄入编译（确定性，零 LLM）   PDF ×2 → blue_book_index.json
blue_book_lookup.py   B2 检索 API（确定性）           class_id/类名 → 条款文本+出处
spec_enrich.py        B3 接入（扩展既有富化，复用其路由/缓存/护栏/仅 P3 纪律）
assemble_spec.py      B3 传参（--blue-book-index 可选透传）
```

---

## B1 摄入编译 `blue_book_ingest.py`（确定性，零 LLM）

**分支建议**：`codex/blue-book-ingest`

### 任务

CLI：`python -m blue_book_ingest --pdf <part1> --pdf <part2> --out <dir>`
→ 写 `<dir>/blue_book_index.json`，stdout 一行 JSON 统计信封（对齐 cli-contract 风格）。

索引结构（键全为字符串）：

```json
{
  "meta": {"edition": "Ed. 16", "source_files": ["...pdf", "...pdf"],
            "schema_version": "blue-book-index/v1",
            "stats": {"interface_classes": 0, "obis_sections": 0}},
  "interface_classes": {
    "3": {"name": "Register", "version": 0, "section": "4.3.2",
           "pages": [57, 59], "text": "……该节全文……",
           "attributes": ["1 logical_name", "2 value", "3 scaler_unit"],
           "methods": ["1 reset(data)"]}
  },
  "obis_sections": [
    {"key": "value-group-c-electricity", "section": "6.x", "pages": [30, 34], "text": "……"}
  ]
}
```

### 实现要点

- **Part 2 切分**：按章节标题行切节（形如 `4.3.2 Register (class_id = 3, version = 0)`
  或紧邻正文的 `class_id = N, version = M`——先实测标题行精确形状再定正则）。
  **目录页干扰**：TOC 行有 `....... 页码` 点线特征且无正文跟随——只把"节文本长度 ≥ 300 字"
  的命中当定义节；同一 class_id 命中多节时取文本最长者为主节。
- **同一 class 多 version**：以 version 最高者为主条目，其余版本节文本并入 `text`（标注
  version 分隔）——检索按 class_id，不按 version。
- `attributes` / `methods`：能从节文本里确定性抽出行就抽（形如行首序号 + 名称的属性/方法表
  行），抽不出**保留空数组即可**，`text` 里反正有全文——不要为解析表格过度工程。
- **Part 1 切分**：按章节切 OBIS value group 相关节，进 `obis_sections`（本期只存不用，
  B3 只用 interface_classes；留给后续 OBIS 语义富化）。
- 文本清洗：去页眉页脚（每页重复的 `COSEM Interface Classes` / `DLMS UA 1000-x Ed. 16` 行）、
  合并断行。复用 `text_normalize` 里已有的工具（先看有什么，别重写）。
- **幂等可复现**：同输入两次运行产物逐字节一致（禁 `datetime.now()` 进正文；meta 里如需时间戳
  用 `--ingested-at` 参数传入或省略）。

### B1 验收标准（实现者自测 + Claude 复核）

```powershell
# A. 真实摄入（本机路径）
python -m blue_book_ingest --pdf "C:\Users\YYHwudi\Desktop\Canna-29\Blue-Book-Ed-16-part-1-V1.0.pdf" `
  --pdf "C:\Users\YYHwudi\Desktop\Canna-29\Blue-Book-Ed-16-part-2-V1.0.pdf" --out out\bluebook
```
1. 统计：`interface_classes ≥ 90`（实测锚点去重 102，允许目录/引用噪声损耗）。
2. 常用类 **1, 3, 4, 5, 7, 8, 9, 15, 20, 40, 64, 70** 全部命中，且每个 `text ≥ 500 字`、
   `section` 非空。
3. class 3 (Register) 的 text 里能找到 `value` 与 `scaler_unit` 字样；class 7 (Profile
   generic) 的 text 里能找到 `capture_objects`；class 15 (Association LN) 的 text 里能找到
   `object_list`。（内容真实性抽查）
4. 复现性：连跑两次，`fc`/`diff` 索引文件逐字节一致。
5. unittest：自造 3-4 页迷你文本 fixture（不进真实 PDF），覆盖：标题行切节 / TOC 行被排除 /
   多 version 合并 / 页眉清洗。全量 `python -m unittest discover -s tests` 全绿。
6. `git status`：无 PDF、无真实索引 JSON 进版本库。

---

## B2 检索 API `blue_book_lookup.py`（确定性）

**分支建议**：同分支或 `codex/blue-book-lookup`（B1 验收后再动工）

### 任务

```python
def load_index(path: Path) -> dict | None          # 不存在/损坏 → None（不抛，调用方降级）
def lookup_class(index, class_id: int | str) -> dict | None   # 精确命中或 None
def lookup_class_by_name(index, name: str) -> dict | None     # casefold 精确匹配类名
def condensed_text(entry: dict, max_chars: int = 4000) -> str # 注入 LLM 用的截断
```

- `condensed_text` 截断策略：优先保留节首（类定义与属性/方法表通常在前部），尾部截断加
  `…（节选，完整定义见 Blue Book §X）`。
- 未命中一律 None。**不做**模糊匹配/相似度。

### B2 验收标准

1. unittest：查得 / 查不得（None）/ 索引文件缺失（None 不抛）/ 损坏 JSON（None 不抛）/
   截断保留节首与出处尾注。
2. 全量测试全绿。

---

## B3 行为富化接入（扩展 `spec_enrich.py`，复用其全部既有纪律）

**分支建议**：`codex/blue-book-enrich`（B1+B2 验收后动工）

### 任务

`spec_enrich` 现状：仅富化 P3 行为需求、stub 默认零 LLM、内容指纹缓存
（`spec_enrich_cache.jsonl`）、`check_drift` 编码/数字护栏、`ENRICH_PROMPT_VERSION`。
扩展（全部向后兼容）：

1. `enrich_requirements(...)` 加可选参 `blue_book_index_path: Path | None = None`。
   `assemble_spec.assemble()` 与 CLI `assemble` 子命令加 `--blue-book-index` 透传；
   `desktop_tasks` 的 assemble 子命令同步加参（GUI 面板本期不做，CLI/桌面后端可用即可）。
2. 富化单条 P3 需求时：从需求行取 class_id（P3 行源自 cosem 对象行，`derive_item` 的 row
   里有；若个别行没有 class_id 字段则跳过注入，行为与现在一致）→ `lookup_class` →
   命中则把 `condensed_text(entry)` 注入 user prompt：

   ```
   【权威参考：DLMS Blue Book Ed.16 §{section}（{name}, class_id={cid}）】
   {condensed_text}
   ---
   要求：结合上面条款，把本需求的行为语义写完整（属性含义、GET/SET/ACTION 行为、
   数据类型/selective access 若条款有）；末尾附「依据 DLMS Blue Book Ed.16 §{section}」。
   条款没有的内容绝不编造；OBIS/数字只能照抄本需求原文或条款原文。
   ```

3. **护栏扩展（程序校验，两条都必须实现）**：
   - `check_drift` 基线扩展：编码/数字漂移的"有据"基线 = 原 frozen_text **∪ 注入条款文本**
     （条款里的数字是有据的）。未注入条款时基线与现在完全一致。
   - **出处校验**：产出文本里出现的 `Blue Book …§<节号>` 必须与本次注入的 `section` 一致，
     不一致 → 拒绝该条富化、降级保留原描述、记 note（防编造引用）。
4. **指纹**：注入条款的 sha256 折进 `fingerprint`（条款变/索引变 → 缓存失效重富化；未注入
   时指纹不变——保证默认路径缓存不受影响）。`ENRICH_PROMPT_VERSION` 升版。
5. 未给索引路径 / 索引加载失败 / class 未命中：**与现在的 spec_enrich 行为逐字节一致**。

### B3 验收标准

1. unittest（自造迷你索引 + 注入 fake chat）：
   - 命中 class → prompt 含条款与节号；产出带正确出处 → 接受。
   - 产出写了**不一致的节号** → 拒绝、降级、note 记录。
   - 产出含条款里有而源文没有的数字 → 不再误拒（基线扩展生效）。
   - 产出含条款与源文都没有的 OBIS → 仍严格拒绝。
   - 不给索引路径 → 一次 lookup 都不发生、产物与基线用例逐字节一致。
2. stub 路由零 LLM 调用（与现在一致）。
3. 全量测试全绿；golden 六项不动。

---

## 3. 测试与交付纪律汇总

- 每期一个 `tests/test_blue_book_*.py`，**unittest.TestCase**（理由见红线 5）。
- 新模块注册进 `pyproject.toml [tool.setuptools] py-modules` + 两个 PyInstaller spec
  （`packaging/desktop_backend.spec`、`packaging/ratomizer.spec`）的 hiddenimports——
  惰性 import 不注册会漏打包（前车之鉴）。
- 提交信息写清做了什么、为什么、验收结果；不合 main、不推送。

## 4. Claude 总验收清单（实现者可预跑自查）

1. `python -m unittest discover -s tests` 全绿，新增测试被收集（数量 > 合并前）。
2. 真实摄入统计 ≥90 类 + 常用类内容抽查（B1 验收 2/3 条）+ 两次运行逐字节一致。
3. test5 端到端：`assemble --blue-book-index out\bluebook\blue_book_index.json` →
   P3 行为需求出现带 `依据 DLMS Blue Book Ed.16 §…` 的富化描述；随机抽 10 条核对节号与
   蓝皮书原文一致；导出 xlsx 0 活公式。
4. 不带 `--blue-book-index` 重跑 → 产物与合并前基线一致（默认零变化）。
5. 漂移抽查：派生文本的编码/数字 ⊆ 源文 ∪ 注入条款。
6. `git log --stat` 无 PDF/真实索引进仓；`.gitignore` 已加。
7. golden 六项全绿（main 的 out/ 基线存在时）。
