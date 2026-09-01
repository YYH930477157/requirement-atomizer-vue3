# 待核成文 v3 Implementation Plan

> **给 GLM / 实施代理：** 本文是唯一施工说明书。基线是 **已推送的 `origin/main` @ `193efc8`**（待核成文 v2），不是本机旧方案里的 `94c6100`。
> 按任务顺序做，**先写失败测试再改代码**。测试必须是 `unittest.TestCase`（仓库未装 pytest；模块级 `def test_*` 会被静默跳过）。
> PowerShell 5.1 无 `&&`，用 `;` 串联。
> 实施在隔离 worktree，分支 **`codex/partial-export-hotfix`**（已从 `193efc8` 建好：`.worktrees/codex-partial-export-hotfix`）。不要在 `main` 上改。不要 push。不要 commit，除非用户本会话明确要求。

**Goal:** 桌面 `package_v1` 上待核标记真正落进成文；`draft`+未闭合不能靠旁路出表；失败行标红，并增加「守恒待核」清单 sheet。验收闸（claim / closure / ab_runner / 结果包 completed）一字不放宽。

**Architecture:** 不重做 v2 闸。`allow_unclosed` / `RATOMIZER_PARTIAL_EXPORT` / `{fre_id: [classes]}` 标记权威全部保留。本片只修寻址与 draft 旁路，并在 **已挂标记的行** 上加红字 + 工作簿内清单。标记算法身份升 `conservation-partial-export-v3`，迫使已跑过的未标记 analysis / template-write 代失效重跑（零 LLM）。

**Tech Stack:** 现有 Python 管线 + Vue `App.vue` / `PartialExport.spec.ts`。零新依赖。openpyxl 已在用。

---

## 0. 背景：为什么不能按 08-31 / 09-01 旧方案从零施工

两份旧方案都过时了：

| 文档 | 假设基线 | 现状 |
|---|---|---|
| `docs/pending-export-plan-2026-08-31.md` | 从无旁路写起 | **已在 `193efc8` 落地**（`allow_unclosed`、行级 `⚠待核`、默认开、extract_degraded） |
| `docs/pending-export-plan-2026-09-01.md` | 本机 `94c6100`，API 叫 `provisional=` | 不要再引入第二套参数名；不要改写 `conservation_pending_marks` 的返回形状 |

2026-09-01 审查（对照 `origin/main`）结论：

1. **Critical：** 分析能读到 governed 产物（`_read_functional_requirements_payload`），但 `unclosed_basis` 与两处 attach 裸读根目录 `functional_requirements.json`。桌面新跑是 `package_v1`（文件在 `.ratomizer/pipeline/`）。结果：成文照出、行不标、UI 当干净表。既有链测试全用无 marker 的 `TemporaryDirectory`，测不出来。
2. **Important：** 方案 / `ENV_REGISTRY` 写明 `draft:true` 仍拦。`functional_direct_basis` 只拦 `failed`。关 LLM 的显式 stub + 守恒未闭合会进成文。
3. **呈现债（用户本轮拍板）：** 红字 + 「守恒待核」sheet。这是 CLAUDE.md 2026-08-31「带标记的部分成文」原意；v2 只做了说明列前缀。

---

## 1. 硬约束（违反即返工）

1. **不放宽守恒。** `conservation_report` / `FUNCTIONAL_CONSERVATION_MODEL_VERSION` 不 bump。binding / preservation / obligation 判定一字不动。
2. **不改抽取。** prompt / routing / outline flag / `RATOMIZER_EXECUTION_POLICY` / `RATOMIZER_FUNCTIONAL_EXTRACT` 默认值不动。`extraction_fingerprint` 不进 `CONSERVATION_PARTIAL_EXPORT_VERSION`。
3. **不改闸参数名。** 保持 `allow_unclosed=`。禁止再加 `provisional=`。
4. **不改标记权威形状。** `conservation_pending_marks` 仍返回 `{fre_id: [classes]}`。uncovered / preservation **继续连带**声明在该条款块上的 FRE（v2 grok 审核第 1 条，已落地）。禁止退回「缺口不挂 FRE」。
5. **零 FRE 仍不造需求行。** 条款覆盖缺口 / 无人认领的义务缺口只进「守恒待核」sheet，不往需求 sheet 追加占位行。
6. **failed 一律拦。** `execution_status=failed` 无论开关都 raise `FunctionalExtractionIncompleteError`。
7. **draft + 未闭合一律拦。** `payload.get("draft")` 且 conservation `ok is False` 时，即使 `allow_unclosed=True` 也 raise Incomplete。`draft` + 守恒闭合（显式 stub opt-in / 烟测）保持现状，不扩大拦。
8. **验收闸禁止传 `allow_unclosed=True`，禁止改判定：**
   - `raise_if_unconserved` 默认
   - `functional_direct_basis` 默认
   - `desktop_tasks._publish_functional_claim_shadow` 的 `conservation.ok` 前置（约 477 行）
   - `evaluate_full_closure` 的 `conservation_open`
   - `tools/ab_runner.py` B 腿 `conservation_ok is False → FAIL`（约 1117 行）
   - 结果包 `_completion_evidence` / quality_gates：`needs_work` 仍拒绝 `completed`
9. **文件名仍是 `软件需求列表-成文.xlsx`。** 不另起 `-待核`。
10. **禁止顺手做：** 任务 D、conservation v8、大纲 flag、`DOCUMENT_OUTLINE_VERSION` 进指纹、列契约合一、routing v9、翻 EXECUTION_POLICY、默认开分析富化。

---

## 2. 文件地图

| 文件 | 本片职责 |
|---|---|
| `functional_extract.py` | draft+未闭合拦截；`extract_degraded` 比对 coerce 后形状；版本 v2→v3；新增 `conservation_pending_gaps`（只供清单 sheet） |
| `requirements_analysis.py` | attach / `unclosed_basis` 改走 `_read_functional_requirements_payload` |
| `template_writer.py` | 待核行标红；写「守恒待核」sheet；FR 走 governed 读；report 增 sheet 审计 |
| `desktop_tasks.py` | producer 钉串随 v3；`STAGE_IMPLEMENTATION_REVISIONS["template-write"]` `v5`→`v6` |
| `prompt_registry.py` | `conservation-partial-export` 版本改 v3 |
| `tests/test_partial_export_marks.py` | coerce 形状钉；draft 钉 |
| `tests/test_partial_export_chain.py` | **package_v1 主钉** + 链载荷 |
| `tests/test_template_writer.py` | 红字 / 清单 sheet / 守恒 ok 零漂移 |
| `tests/test_desktop_tasks.py` | producer 期望串改 v3 / impl-v6 |
| `tests/test_functional_conservation_v2.py` | 默认 basis 零漂移；draft+未闭合+allow_unclosed 新钉 |
| `ui/src/App.vue` | 交付物 hint 提「含守恒待核清单」；旧三形态文案保留 |
| `ui/src/__tests__/PartialExport.spec.ts` | hint 文案 |
| `CLAUDE.md` / `TODO.md` | 决策记录；验收闸未放宽 |

不改：`tools/ab_runner.py` 判定、`claim_ledger.py`、抽取 prompt、守恒检查本体、`raise_if_unconserved` 默认语义。

---

## 3. 锁定的设计（相对 v2 的增量）

### 3.1 读路径单源

所有「为了待核而读 `functional_requirements.json`」的站点必须走：

```python
from requirements_analysis_rules import _read_functional_requirements_payload
payload = _read_functional_requirements_payload(Path(out_dir))
```

已走这条路、不要改的：`functional_direct_basis`（约 3148 行）。

必须改掉裸 `out_dir / "functional_requirements.json"` 的：

- `requirements_analysis._attach_conservation_pending_marks`（约 267–271 行）
- `requirements_analysis._attach_extract_degraded_marks`（约 303–307 行）
- `run_requirements_analysis` 无原子分支里 `synthesized_path.read_text()` 算 `unclosed_basis`（约 356–362 行）
- `template_writer.run_writer` 若为本片去读 FR（写清单 sheet）——**新建读点也必须走同一函数**

空 payload / 坏 JSON：attach 返回 `{}`，`unclosed_basis=False`（与今天「读不到」同形，但 package_v1 不再读不到）。

有原子的 else 分支（约 370–397 行）若根目录没有 FR、pipeline 里有：今天会退回逐原子输入。那是 B 轨桌面主路径用不到的预存缺口，**本片不修**（爆炸半径大，且默认链无 `ai_requirements.jsonl`）。

`engineering_analysis.json` 现写根目录（`requirements_analysis.py:592`），`run_writer` 继续读根目录。不要改分析落点。

### 3.2 draft 旁路

在 `functional_direct_basis`，`raise_if_unconserved(...)` 与 `execution_status` 检查之后、返回 items 之前：

```python
conservation_closed = (
    not isinstance(conservation, dict) or bool(conservation.get("ok", True))
)
if payload.get("draft") and not conservation_closed:
    raise FunctionalExtractionIncompleteError(
        "功能直抽产物带 stub 草稿水印且守恒未闭合（draft=true），"
        "阻塞需求分析/澄清/成文下游；partial export 旁路不放行 draft"
    )
```

| 产物 | `allow_unclosed=False` | `allow_unclosed=True` |
|---|---|---|
| 未闭合 + `ok` 执行 | raise Conservation | 放行 + 标记 |
| mixed / `partial` + 未闭合 | raise Incomplete | 放行 + 标记 |
| `failed` | raise Incomplete | raise Incomplete |
| `draft` + 未闭合 | raise Conservation（先撞守恒闸）或 Incomplete | **raise Incomplete（本片）** |
| `draft` + 守恒闭合（显式 stub） | 放行（现状） | 放行（现状，不扩大） |
| mixed 不是 draft | 见上 | 见上 |

不要检查「任意 draft 都拦」——那会打断既有 stub 烟测 / 守恒闭合的 opt-in。

### 3.3 extract_degraded 比对 coerce 后形状

`extract_degraded_marks`（约 2013 行）今天比对 `_stub_shape`（coerce 前）。改为比对该条款 `_stub_item(section, 1)` 的 `objective` / `behaviors`（与落盘条目同一清洗链）。

`_source_text` 已含 heading，多数标题编码不会被洗掉；本改是防漂移，不是新启发式。`test_stub_shape_matches_stub_item` 改为断言与 `_stub_item` 字段相等（或留旧钉再加一条带标准号标题的 coerce 钉）。

### 3.4 红字 + 「守恒待核」sheet

说明列前缀 **保持 v2**：`⚠待核（{pending_class_label(classes)}）`。不要改成「⚠ 守恒待核：」，以免既有链测试字面漂。

在 `append_analysis_to_template` 写入循环里，对 `conservation_pending.classes` 非空的**本趟追加行**：

- 给「序号 / 需求 / 说明」三格（`seq` / `answer` / `notes` 解析列，缺则回退 `_COL_SEQ` / `_COL_ANSWER` / `_COL_NOTES`）设 `Font(color="FFFF0000")`。
- **禁止**改模板自带样例行颜色。
- 正文仍走 refinement → requirement → objective 兜底。待核行禁止空正文。

工作簿内新建 sheet **`守恒待核`**（已存在则清空后重写，避免续跑叠行）：

1. A1 总述（可合并 A1:F1）：`本工作簿为待核导出。不得作为已验收交付。`
2. 表头：`类别 | 原因 | 功能需求ID | 章节 | token | 说明`
3. 行来源：
   - 每个已挂 `conservation_pending.classes` 的分析条目：每个 class 一行（类别=人读标签，功能需求ID=FRE，章节=`source_section`，说明=说明列前缀所用同一 `pending_class_label`）。
   - **外加** `conservation_pending_gaps(report)` 的缺口行（无 FRE id）：
     - `checks.obligation_coverage.uncovered_obligations` 里，按现有 `_clause_block_candidates` 还原块集后，**没有任何 item 的 `source_block_ids` 相交**的那些义务（已连带过的不要重复一行「义务未覆盖」——需求 sheet 已经标了；gap 只补「零 FRE 可挂」的）。
     - `checks.clause_coverage.uncovered_sections` 全部进 gap（v2 标记函数本来就不收这一类）。

守恒 `ok=true` 且没有任何 pending class、没有任何 gap：**不建该 sheet**，report 无新键或 `pending_sheet_rows=0`。用回归钉锁死与 v2 同形（无新 sheet、无前缀、无红字）。

仅 `extract_degraded`（守恒闭合）：**要建 sheet**（清单必须看见降级行），总述仍用上面那句。

`run_writer` 读 FR 只为算 gaps（条目上的 class 已由分析挂好）。FR 缺席：只根据分析条目写 sheet；没有条目标记则不建 sheet。

report `conservation_pending_export` 在现有 `{marked_rows, classes}` 上增加：

```python
{
    "marked_rows": pending_rows,          # 需求 sheet 被标的行数（含红字）
    "classes": {...},                     # 原样
    "pending_sheet_rows": N,              # 守恒待核 sheet 数据行（不含总述/表头）
    "gap_rows": G,                        # 其中无 FRE 的缺口行
}
```

`template_write_task` 对 `unclosed_basis` 的判定（约 877–880 行，`classes` 是 `{失败类: 行数}`）**不要改**。

### 3.5 链 / UI

链编排 **保持 v2**：`allow_unclosed` 由 `RATOMIZER_PARTIAL_EXPORT` 注入；成功旁路置 `conservation_blocked` + `partial_export`；`unclosed_basis` → 阶段 `partial`。不要按 09-01 旧方案改回「分析阶段记 ok」。

UI 三形态保留（`App.vue` 约 2281–2295 行）。增量：

- `pendingExportNote` 在「成文已出」两支都追加 `；工作簿含「守恒待核」清单`。
- 仅 `conservation_blocked` 且无 `partial_export`（旧包 / `=0`）仍「成文已阻断」。

### 3.6 版本 / 指纹

| 常量 | 新值 | 为什么 |
|---|---|---|
| `CONSERVATION_PARTIAL_EXPORT_VERSION` | `conservation-partial-export-v3` | 寻址修复后，package_v1 上 v2 分析代是「ok + 零标记」，不 bump 会永久复用假干净分析 |
| `prompt_registry` 同 id | v3 | 与常量同步 |
| `STAGE_IMPLEMENTATION_REVISIONS["template-write"]` | `v5` → **`v6`** | 红字 + 清单 sheet，旧 xlsx 必须重写（零 LLM） |
| `_STAGE_BASE_PRODUCERS["template-write"]` | 保持 `template_writer/v1` | 报告 provenance 已是 v3；基戳历史债本片不顺手对齐（避免无关 pin 大面积改） |
| 分析 impl | **不 bump** | 内容变化已由 partial-export-v3 进 producer |
| 守恒 / extract prompt / routing | **不 bump** | |

`tests/test_desktop_tasks.py` 约 1218–1219 行钉串随改：

```
...+conservation-partial-export-v3+partial-export-True+impl-v6
template-write: ...+conservation-partial-export-v3+partial-export-True+impl-v6
```

（分析行 impl 仍是 v6，只换 partial-export 版本。）

### 3.7 成本

本片零付费。寻址 / draft / 红字 / sheet 全是确定性。禁止打真实 LLM。既有 v2 旁路已经会跑分析；本片不扩大付费面。

---

## 4. 开工前

```powershell
cd D:\Codex\requirement-atomizer-vue3\.worktrees\codex-partial-export-hotfix
git status
git log -1 --oneline
```

期望：`codex/partial-export-hotfix` @ `193efc8`，工作区干净。若分支不在，从已 pull 的 main 重建：

```powershell
cd D:\Codex\requirement-atomizer-vue3
git worktree add .worktrees/codex-partial-export-hotfix -b codex/partial-export-hotfix main
```

---

## Task 1: package_v1 寻址（Critical）

**Files:**
- Modify: `requirements_analysis.py`（三处裸读）
- Test: `tests/test_partial_export_chain.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_partial_export_chain.py` 增加 helper 与用例。复用文件里已有的 `_seed_fr` / `_make_template` / `_run`。**不要**把 FR 写在根目录。

```python
def _init_package(root: Path) -> Path:
    from result_package import initialize_result_package, governed_artifact_path
    src = root / "standard.docx"
    src.write_bytes(b"docx-fixture")
    initialize_result_package(
        root, input_path=src,
        requested_stages=["requirements-analysis", "template-write"],
    )
    return root


def _seed_fr_governed(root: Path, **kwargs) -> None:
    from result_package import governed_artifact_path
    _seed_fr(root, **kwargs)  # 先写根目录
    pipeline = governed_artifact_path(
        root, "functional_requirements.json",
        category="pipeline", for_write=True)
    pipeline.parent.mkdir(parents=True, exist_ok=True)
    pipeline.write_text(
        (root / "functional_requirements.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    (root / "functional_requirements.json").unlink()  # 逼出裸读漏洞


class PartialExportPackageV1Tests(unittest.TestCase):
    def test_package_v1_unclosed_marks_rows_and_sets_partial_export(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_package(root)
            tpl = root / "tpl.xlsx"
            _make_template(tpl)
            _seed_fr_governed(root, execution_status="ok", conservation_ok=False)
            # 无原子：根目录也不得有 ai_requirements.jsonl
            self.assertFalse((root / "functional_requirements.json").exists())
            payload = PartialExportChainTests()._run(root, tpl)
            self.assertTrue(payload.get("partial_export"))
            self.assertGreater(int(payload.get("pending_marked_rows") or 0), 0)
            xlsx = root / "软件需求列表-成文.xlsx"
            self.assertTrue(xlsx.is_file())
            wb = load_workbook(xlsx)
            notes = []
            for ws in wb.worksheets:
                if ws.title == "守恒待核":
                    continue
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if row and any(c not in (None, "") for c in row):
                        notes.append(" ".join(str(c or "") for c in row))
            self.assertTrue(
                any("⚠待核" in text for text in notes),
                "package_v1 成文必须带待核前缀，不能是干净表",
            )
```

`initialize_result_package` 的精确关键字以 `tests/test_result_package.py` 的 `_initialize` 为准（约 47–52 行）；缺的参数按那个夹具抄，不要发明新契约。

- [ ] **Step 2: 跑红**

```powershell
python -m unittest tests.test_partial_export_chain.PartialExportPackageV1Tests -v
```

期望：`partial_export` 为假，或 `pending_marked_rows==0`，或说明列无 `⚠待核`。

- [ ] **Step 3: 最小实现**

抽一个模块内 helper（放 `requirements_analysis.py`，不要新文件）：

```python
def _functional_payload(out_dir: Path) -> dict[str, Any]:
    from requirements_analysis_rules import _read_functional_requirements_payload
    payload = _read_functional_requirements_payload(Path(out_dir))
    return payload if isinstance(payload, dict) else {}
```

两处 attach 开头改：

```python
payload = _functional_payload(out_dir)
if not payload:
    return {}
```

无原子分支：

```python
if allow_unclosed:
    fr_payload = _functional_payload(out_dir)
    conservation = fr_payload.get("conservation") if fr_payload else None
    unclosed_basis = bool(
        isinstance(conservation, dict) and not conservation.get("ok", True))
    if unclosed_basis:
        pending_marks = _attach_conservation_pending_marks(out_dir, requirements)
    pending_marks.update(_attach_extract_degraded_marks(out_dir, requirements))
```

删掉这段的 `synthesized_path.read_text()` try/except。

- [ ] **Step 4: 聚焦绿**

```powershell
python -m unittest tests.test_partial_export_chain tests.test_partial_export_marks -v
```

既有扁平目录用例必须仍绿（governed 读会回退根目录）。

---

## Task 2: draft + 未闭合仍拦（Important）

**Files:**
- Modify: `functional_extract.py` `functional_direct_basis`
- Test: `tests/test_functional_conservation_v2.py`（与既有 basis 钉同文件）

- [ ] **Step 1: 写失败测试**

```python
def test_direct_basis_blocks_draft_when_unconserved_even_if_allow_unclosed(self) -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "functional_requirements.json").write_text(json.dumps({
            "producer": "functional-extract-v1",
            "route_requested": "stub",
            "route": "stub",
            "execution_status": "ok",
            "draft": True,
            "items": [{"functional_requirement_id": "F1"}],
            "conservation": {"ok": False},
        }, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(fe.FunctionalExtractionIncompleteError):
            fe.functional_direct_basis(out, allow_unclosed=True)

def test_direct_basis_allows_explicit_stub_when_conserved(self) -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "functional_requirements.json").write_text(json.dumps({
            "producer": "functional-extract-v1",
            "route_requested": "stub",
            "route": "stub",
            "execution_status": "ok",
            "draft": True,
            "items": [{"functional_requirement_id": "F1"}],
            "conservation": {"ok": True},
        }, ensure_ascii=False), encoding="utf-8")
        items = fe.functional_direct_basis(out, allow_unclosed=True)
        self.assertEqual(items[0]["functional_requirement_id"], "F1")
```

- [ ] **Step 2: 跑红**

```powershell
python -m unittest tests.test_functional_conservation_v2.DirectBasisTests -v
```

类名以文件里实际为准；没有独立类就把两条加进现有 basis 测试类。期望：第一条 **通过**（现状放行）——也就是测试失败（`assertRaises` 没撞到）。

- [ ] **Step 3: 按 §3.2 加上 draft 判断**。更新 `functional_direct_basis` docstring：写明 draft+未闭合无论开关都拦。

- [ ] **Step 4:**

```powershell
python -m unittest tests.test_functional_conservation_v2 tests.test_partial_export_chain -v
```

`test_partial_export_chain` 里 `_seed_fr(..., route="stub")` 默认 **没有** `draft:true`。不要给扁平未闭合 stub 夹具加 draft，否则链旁路测试会被本片误伤。若某条链测试开始 raise，是夹具不诚实，给那份 payload 去掉 draft 或改 `conservation_ok=True`，不要放宽闸。

---

## Task 3: extract_degraded 对 coerce 后形状

**Files:**
- Modify: `functional_extract.py` `extract_degraded_marks`
- Test: `tests/test_partial_export_marks.py`

- [ ] **Step 1: 写失败测试**

```python
def test_mixed_marks_coerced_stub_item_not_pre_shape(self) -> None:
    section = _section("IEC 62056-21", "The meter shall log events.", ["B1"])
    item = fe._stub_item(section, 1)
    payload = {"route": "mixed", "items": [item]}
    marks = fe.extract_degraded_marks(payload, [section])
    self.assertEqual(marks, {item["functional_requirement_id"]: ["extract_degraded"]})
```

若当前 `_stub_shape` 与 `_stub_item` 字段已相等，这条会 **立刻绿**——那它锁不住 bug。再加一条显式：标记函数必须对 `_stub_item` 字段相等、对仅 `_stub_shape` 相等但 coerce 后不同的条目也要能标。实现上直接比 `_stub_item` 即可，测试只钉「落盘 stub 条目能标上」。

把 `test_stub_shape_matches_stub_item` 改名为或补一条 `test_degraded_compare_uses_stub_item_fields`。

- [ ] **Step 2–4:** 红（或钉落盘条目）→ 比对改为：

```python
stub = _stub_item(section, 1)
if (
    str(item.get("objective") or "") == str(stub.get("objective") or "")
    and [str(b) for b in (item.get("behaviors") or [])]
    == [str(b) for b in (stub.get("behaviors") or [])]
):
    ...
```

`_stub_item` 会重算 id，只借用字段，不要用它的 id 去对 payload。

---

## Task 4: 红字 + 「守恒待核」sheet

**Files:**
- Modify: `template_writer.py`
- Modify: `functional_extract.py`（新增 `conservation_pending_gaps`）
- Test: `tests/test_template_writer.py` + `tests/test_partial_export_marks.py`

- [ ] **Step 1: gaps 失败测试**（`tests/test_partial_export_marks.py`）

```python
def test_gaps_include_clause_coverage_not_fabricated_fre(self) -> None:
    report = _report()
    report["checks"]["clause_coverage"] = {
        "ok": False,
        "uncovered_sections": [{"section_id": "4.9", "heading": "Spare"}],
    }
    gaps = fe.conservation_pending_gaps(
        report, [_item("F1", ["B1"])],
        [_section("4.1", "The meter shall log events.", ["B1"]),
         _section("4.9", "Spare parts list.", ["B9"])],
    )
    self.assertTrue(gaps)
    self.assertTrue(all(not g.get("functional_requirement_id") for g in gaps))
    self.assertEqual(gaps[0]["category"], "clause_gap")

def test_gaps_omit_uncovered_already_connected_to_declared_fre(self) -> None:
    report = _report(uncovered=[{"section_id": "4.2", "sentence": "shall archive logs"}])
    sections = [_section("4.2", "The logger shall archive logs.", ["B2"])]
    items = [_item("F2", ["B2"])]
    # 连带已挂 F2，gap 不得再为同一义务造无 id 行
    gaps = fe.conservation_pending_gaps(report, items, sections)
    self.assertEqual(gaps, [])
```

`conservation_pending_gaps` 返回：

```python
{"category": "clause_gap"|"uncovered", "reason": str, "section_id": str,
 "functional_requirement_id": "", "token": "", "detail": str}
```

- [ ] **Step 2: 成文呈现失败测试**（`tests/test_template_writer.py`）

```python
class PendingPresentationTests(unittest.TestCase):
    def test_pending_row_is_red_and_sheet_lists_fre(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tpl = root / "tpl.xlsx"
            make_template(tpl)
            row = item("事件记录", "记录事件", text="电表应记录事件", seq_hint=1)
            row["functional_requirement_id"] = "F1"
            row["conservation_pending"] = {"classes": ["binding"]}
            out = root / "软件需求列表-成文.xlsx"
            report = tw.append_analysis_to_template(tpl, [row], out)
            wb = load_workbook(out)
            self.assertIn("守恒待核", wb.sheetnames)
            ws = wb["事件需求"]
            # 追加行 = 模板表头后第一条新数据（事件需求夹具无样例数据行）
            notes_cell = ws.cell(row=2, column=7)
            self.assertIn("⚠待核", str(notes_cell.value or ""))
            self.assertEqual(str(notes_cell.font.color.rgb), "FFFF0000")
            body_cell = ws.cell(row=2, column=6)
            self.assertTrue(str(body_cell.value or "").strip())
            self.assertEqual(str(body_cell.font.color.rgb), "FFFF0000")
            pending = wb["守恒待核"]
            blob = " ".join(
                str(c or "") for r in pending.iter_rows(values_only=True) for c in r)
            self.assertIn("F1", blob)
            self.assertIn("不得作为已验收交付", blob)
            self.assertGreater(int((report.get("conservation_pending_export") or {}).get("pending_sheet_rows") or 0), 0)

    def test_clean_workbook_has_no_pending_sheet_or_red_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tpl = root / "tpl.xlsx"
            make_template(tpl)
            out = root / "out.xlsx"
            tw.append_analysis_to_template(tpl, [item("时钟", "历法", text="公历", seq_hint=1)], out)
            wb = load_workbook(out)
            self.assertNotIn("守恒待核", wb.sheetnames)
            clock = wb["时钟需求"]
            # 模板样例行（row 2）不得被涂红
            sample = clock.cell(row=2, column=6)
            color = sample.font.color
            rgb = getattr(color, "rgb", None) if color is not None else None
            self.assertNotEqual(str(rgb or ""), "FFFF0000")
```

openpyxl 无色时 `font.color` 可能是 `None` 或 theme。干净行断言「不是 FFFF0000」即可，不要断言必须是黑。

- [ ] **Step 3: 实现**

`conservation_pending_gaps`：只读 report，复用 `_clause_block_candidates`。不要 bump 守恒模型。

`append_analysis_to_template`：写入后对 pending 行设红字；收集 `(fre_id, classes, section)`；函数末尾、`safe_save` 前调 `_write_pending_sheet(wb, item_rows, gap_rows)`。

`run_writer`：

```python
from requirements_analysis_rules import _read_functional_requirements_payload
from functional_extract import conservation_pending_gaps, load_conservation_baseline
fr = _read_functional_requirements_payload(out_dir)
gaps = []
if isinstance(fr, dict) and isinstance(fr.get("conservation"), dict):
    sections = load_conservation_baseline(out_dir)
    gaps = conservation_pending_gaps(
        fr["conservation"],
        fr.get("items") if isinstance(fr.get("items"), list) else [],
        sections,
    )
report = append_analysis_to_template(..., gap_rows=gaps)
```

给 `append_analysis_to_template` 加可选 `gap_rows: list | None = None`，默认 `None`=不追加缺口（单元测试只测条目标记时仍能建 sheet）。

- [ ] **Step 4:**

```powershell
python -m unittest tests.test_template_writer tests.test_partial_export_marks tests.test_partial_export_chain -v
```

Task 1 的 package_v1 钉扫说明列时已跳过「守恒待核」sheet，无需改断言。可再断言该 sheet 存在。

---

## Task 5: 版本戳 + UI

**Files:**
- Modify: `functional_extract.py` 常量；`prompt_registry.py`；`desktop_tasks.py` `STAGE_IMPLEMENTATION_REVISIONS["template-write"]`
- Modify: `tests/test_desktop_tasks.py` 钉串
- Modify: `ui/src/App.vue`；`ui/src/__tests__/PartialExport.spec.ts`

- [ ] **Step 1:** 先改测试钉串期望为 v3 / template-write `impl-v6`，跑红。

```powershell
python -m unittest tests.test_desktop_tasks.ProducerStampTests -v
```

类名以文件里实际 `assertEqual(stage_producer...)` 那条为准。

- [ ] **Step 2:** 改常量与 impl。注释写明：v3 = package_v1 寻址 + draft 未闭合拦截 + 红字/清单；不进 extract 指纹。

- [ ] **Step 3:** UI：两处 `pendingExportNote` 赋值末尾加 `；工作簿含「守恒待核」清单`。vitest 钉 `statDeliverables` 存在成文时 hint 含该短语（`PartialExport.spec.ts` 已有 deliverable 形状）。

```powershell
cmd /c "cd ui && npm test -- PartialExport.spec.ts"
```

---

## Task 6: 回归与文档

- [ ] **聚焦**

```powershell
python -m unittest tests.test_partial_export_chain tests.test_partial_export_marks tests.test_template_writer tests.test_functional_conservation_v2 tests.test_desktop_tasks tests.test_claim_functional_store tests.test_ab_runner -v
```

`test_ab_runner` 必须仍：`conservation_ok is False → FAIL`。不要改 `tools/ab_runner.py` 去让它绿。

- [ ] **全量（worktree）**

```powershell
python tools/run_tests_parallel.py
```

worktree 无 `out/`：golden 环境性 skip。本片不触 atomize，主检出 golden 预期零漂移。

- [ ] **`py_compile` + `git diff --check`**

```powershell
python -m py_compile functional_extract.py requirements_analysis.py template_writer.py desktop_tasks.py prompt_registry.py
git diff --check
```

- [ ] **`CLAUDE.md` 顶部加 2026-09-01c 条目**：v3 = 寻址修复 + draft 未闭合仍拦 + 红字/守恒待核 sheet；默认开关不变；验收闸未放宽；缓存影响 = analysis / template-write 因 v3 戳失效重跑（零 LLM）。

- [ ] **`TODO.md`**：勾「带标记的部分成文」；写明验收闸未放宽、门禁仍挂起。

---

## 5. 验收清单（给审核方）

1. 扁平目录既有 `test_partial_export_chain` / marks 全绿（根目录 FR 仍可读）。
2. `package_v1`：根目录无 `functional_requirements.json`，pipeline 里有未闭合产物 → 成文有 `⚠待核`、链 `partial_export=true`、`pending_marked_rows>0`。
3. `functional_direct_basis(allow_unclosed=True)`：`draft`+未闭合 raise Incomplete；`draft`+闭合放行；`failed` 仍 raise；默认参数未闭合仍 raise Conservation。
4. 待核行：说明前缀仍是 `⚠待核（…）`；序号/需求/说明为红；正文非空。
5. 存在 sheet `守恒待核`，含 FRE id 与「不得作为已验收交付」；clause_gap 只在该 sheet、不增加 `appended_total`。
6. 守恒 ok 且无降级：无该 sheet、无前缀、模板样例行不红。
7. claim publish / full closure / ab_runner 仍因守恒失败而不 PASS。
8. producer 含 `conservation-partial-export-v3`；extract 指纹不含该版本。
9. UI 待核 hint 含「守恒待核」。
10. 无 prompt / 守恒模型 / routing / EXECUTION_POLICY 改动。

---

## 6. 明确不要做

- 不要引入 `provisional=`，不要重写 `conservation_pending_marks` 为 list[dict]。
- 不要为了门禁绿去改 `ab_runner`。
- 不要 bump 守恒模型 / 抽取 prompt。
- 不要把结果包标 `completed`。
- 不要打真实 LLM。
- 不要在 `main` 上改，不要 push。
- 不要实施任务 D / 大纲 flag / routing v9。

---

## 7. 做完之后怎么交

1. worktree 聚焦 + 并行全量的摘要（命令、OK 数、skip 数）。
2. `git diff --stat` 相对 `193efc8`。
3. 四句话：寻址怎么修的、draft 怎么拦的、xlsx 多了什么、哪几道闸没动。
4. 停下来等用户审查 / 合并。
