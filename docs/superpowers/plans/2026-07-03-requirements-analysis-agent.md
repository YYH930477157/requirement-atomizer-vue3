# Requirements Analysis Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立的需求分析 Agent，把现有 AI/原子需求结果分类为 `software`、`hardware`、`co_design`，并生成面向软件工程师的软件需求 Excel 与全量 JSON 分析结果。

**Architecture:** 保留 `atomize` 和 `ai_extract` 的职责不变，新增 `requirements_analysis` 后处理阶段。该阶段先应用人工 HTML 裁决，再用规则做高置信度归属分类，必要时调用 LLM 生成软件侧详细说明，最后导出 JSON、Markdown 和软件需求 Excel。

**Tech Stack:** Python 3.11、pytest、openpyxl、现有 `llm_client.py` / `llm_pipeline.py` OpenAI-compatible 配置、Electron standalone HTML 批注导出。

---

## 文件结构

- Create: `requirements_analysis_schema.py`
  - 定义 ownership 常量、分析项结构归一化、人工 override 应用、基础校验。
- Create: `requirements_analysis_rules.py`
  - 实现确定性软硬件归属分类规则。
- Create: `requirements_analysis_template.py`
  - 从内部软件模板 workbook 抽取模块/子模块词表，提供 fallback 词表。
- Create: `requirements_analysis_agent.py`
  - 构造 LLM prompt、解析 LLM 响应、做漂移和 schema 校验。
- Create: `requirements_analysis.py`
  - 编排读取输入、应用人工裁决、规则分类、可选 LLM 深化、写出 JSON/Markdown/Excel。
- Create: `requirements_analysis_excel.py`
  - 导出 `software_requirements.xlsx`，只包含 `software` 和 `co_design` 软件侧。
- Create: `tests/test_requirements_analysis_schema.py`
- Create: `tests/test_requirements_analysis_rules.py`
- Create: `tests/test_requirements_analysis_template.py`
- Create: `tests/test_requirements_analysis_agent.py`
- Create: `tests/test_requirements_analysis_pipeline.py`
- Modify: `ai_review_actions.py`
  - 保存 `ownership_override`。
- Modify: `doc_annotation_export.py`
  - HTML 批注详情增加 ownership 下拉框，导出裁决时带回 `ownership_override`。
- Modify: `api_server.py`
  - `build_ai_requirements()` 把人工 ownership override 带给 HTML/Vue 消费。
- Modify: `desktop_tasks.py`
  - 增加 `requirements-analysis` 桌面任务。
- Modify: `cli.py`
  - 增加 `ratomizer analyze` 命令。
- Modify: `pyproject.toml`
  - 注册新 root 模块。
- Modify: `packaging/desktop_backend.spec`
  - 加入新模块 hiddenimports。
- Modify: `README.md`
  - 增加需求分析 Agent 使用说明。

---

### Task 1: 归属 Schema 与人工 Override

**Files:**
- Create: `requirements_analysis_schema.py`
- Test: `tests/test_requirements_analysis_schema.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_requirements_analysis_schema.py
from requirements_analysis_schema import (
    apply_ownership_override,
    build_analysis_id,
    normalize_ownership,
    validate_analysis_item,
)


def test_normalize_ownership_accepts_supported_values():
    assert normalize_ownership("software") == "software"
    assert normalize_ownership("hardware") == "hardware"
    assert normalize_ownership("co_design") == "co_design"


def test_normalize_ownership_rejects_unknown_value():
    try:
        normalize_ownership("firmware")
    except ValueError as exc:
        assert "unknown ownership" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_apply_ownership_override_wins_over_existing_decision():
    item = {
        "ai_req_id": "AI-1",
        "ownership": "hardware",
        "ownership_source": "rule",
        "notes": [],
    }
    state = {"ownership_override": "software", "reason": "软件需要实现协议处理"}

    updated = apply_ownership_override(item, state)

    assert updated["ownership"] == "software"
    assert updated["ownership_source"] == "reviewer_override"
    assert "规则或 LLM 判断被人工归属覆盖" in updated["notes"][0]


def test_build_analysis_id_is_stable_and_prefixed():
    assert build_analysis_id(1) == "ANREQ-000001"
    assert build_analysis_id(42) == "ANREQ-000042"


def test_validate_analysis_item_requires_source_ids():
    item = {
        "analysis_id": "ANREQ-000001",
        "ownership": "software",
        "source_requirement_ids": [],
        "source_block_ids": ["B-1"],
    }

    issues = validate_analysis_item(item)

    assert issues == ["source_requirement_ids is required"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_requirements_analysis_schema.py -q`

Expected: FAIL，提示 `ModuleNotFoundError: No module named 'requirements_analysis_schema'`。

- [ ] **Step 3: 实现 schema 模块**

```python
# requirements_analysis_schema.py
from __future__ import annotations

from copy import deepcopy
from typing import Any


OWNERSHIP_SOFTWARE = "software"
OWNERSHIP_HARDWARE = "hardware"
OWNERSHIP_CO_DESIGN = "co_design"
VALID_OWNERSHIPS = {OWNERSHIP_SOFTWARE, OWNERSHIP_HARDWARE, OWNERSHIP_CO_DESIGN}


def normalize_ownership(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "软件": OWNERSHIP_SOFTWARE,
        "硬件": OWNERSHIP_HARDWARE,
        "软硬件协同": OWNERSHIP_CO_DESIGN,
        "software": OWNERSHIP_SOFTWARE,
        "hardware": OWNERSHIP_HARDWARE,
        "co_design": OWNERSHIP_CO_DESIGN,
        "codesign": OWNERSHIP_CO_DESIGN,
    }
    normalized = aliases.get(text)
    if normalized in VALID_OWNERSHIPS:
        return normalized
    raise ValueError(f"unknown ownership: {value}")


def build_analysis_id(index: int) -> str:
    return f"ANREQ-{index:06d}"


def apply_ownership_override(item: dict[str, Any], state: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(item)
    if not state or not state.get("ownership_override"):
        return result
    override = normalize_ownership(state["ownership_override"])
    previous = result.get("ownership")
    result["ownership"] = override
    result["ownership_source"] = "reviewer_override"
    result["ownership_confidence"] = 1.0
    notes = list(result.get("notes") or [])
    if previous and previous != override:
        reason = str(state.get("reason") or "").strip()
        suffix = f"：{reason}" if reason else ""
        notes.append(f"规则或 LLM 判断被人工归属覆盖（{previous} -> {override}）{suffix}")
    result["notes"] = notes
    return result


def validate_analysis_item(item: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not str(item.get("analysis_id") or "").startswith("ANREQ-"):
        issues.append("analysis_id must start with ANREQ-")
    try:
        normalize_ownership(item.get("ownership"))
    except ValueError as exc:
        issues.append(str(exc))
    if not item.get("source_requirement_ids"):
        issues.append("source_requirement_ids is required")
    if not item.get("source_block_ids"):
        issues.append("source_block_ids is required")
    return issues
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_requirements_analysis_schema.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add requirements_analysis_schema.py tests/test_requirements_analysis_schema.py
git commit -m "feat: add requirements analysis schema"
```

---

### Task 2: 确定性 Ownership 分类规则

**Files:**
- Create: `requirements_analysis_rules.py`
- Test: `tests/test_requirements_analysis_rules.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_requirements_analysis_rules.py
from requirements_analysis_rules import classify_ownership


def test_classifies_protocol_behavior_as_software():
    req = {
        "title": "GET service",
        "description": "The meter shall support xDLMS GET service for Clock object.",
        "module": "通信协议",
        "source_quote": "support xDLMS GET service",
    }

    decision = classify_ownership(req)

    assert decision["ownership"] == "software"
    assert decision["ownership_source"] == "rule"
    assert decision["ownership_confidence"] >= 0.75


def test_classifies_metering_chip_as_hardware():
    req = {
        "description": "计量芯片型号为 Att7022e，火线采样类型为 CT。",
        "module": "计量",
    }

    decision = classify_ownership(req)

    assert decision["ownership"] == "hardware"
    assert "计量芯片" in decision["ownership_reason"]


def test_classifies_baudrate_hardware_limit_as_co_design():
    req = {
        "description": "波特率最大值与硬件相关，需要驱动适配。",
        "module": "协议栈",
    }

    decision = classify_ownership(req)

    assert decision["ownership"] == "co_design"
    assert decision["ownership_confidence"] >= 0.7


def test_low_signal_defaults_to_software_with_low_confidence():
    req = {"description": "The meter shall support this feature."}

    decision = classify_ownership(req)

    assert decision["ownership"] == "software"
    assert decision["ownership_confidence"] < 0.7
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_requirements_analysis_rules.py -q`

Expected: FAIL，提示缺少 `requirements_analysis_rules`。

- [ ] **Step 3: 实现规则分类**

```python
# requirements_analysis_rules.py
from __future__ import annotations

from typing import Any

from requirements_analysis_schema import OWNERSHIP_CO_DESIGN, OWNERSHIP_HARDWARE, OWNERSHIP_SOFTWARE


SOFTWARE_TERMS = (
    "dlms", "cosem", "obis", "xdmls", "xdlms", "get service", "set service", "action",
    "event", "事件", "profile", "曲线", "tariff", "费率", "billing", "结算",
    "prepaid", "预付费", "push", "p1", "display", "显示", "status word", "状态字",
    "upgrade", "升级", "clock", "时钟", "access right", "访问权限",
)

HARDWARE_TERMS = (
    "计量芯片", "芯片型号", "ct采样", "ct 采样", "锰铜", "shunt", "relay physical",
    "继电器物理", "电源", "电池", "frequency band", "频段", "mechanical", "结构尺寸",
    "寿命", "器件", "硬件更换",
)

CO_DESIGN_TERMS = (
    "驱动", "hardware related", "硬件相关", "波特率", "baud", "dataflash", "存储容量",
    "flash", "mbus", "m-bus", "wmbus", "w-mbus", "模块适配", "硬件接口",
    "采样影响", "继电器状态",
)


def classify_ownership(requirement: dict[str, Any]) -> dict[str, Any]:
    haystack = _requirement_text(requirement)
    matched_co = _matched_terms(haystack, CO_DESIGN_TERMS)
    matched_hw = _matched_terms(haystack, HARDWARE_TERMS)
    matched_sw = _matched_terms(haystack, SOFTWARE_TERMS)

    if matched_co:
        return _decision(OWNERSHIP_CO_DESIGN, 0.78, f"命中协同关键词：{', '.join(matched_co[:3])}")
    if matched_hw and not matched_sw:
        return _decision(OWNERSHIP_HARDWARE, 0.82, f"命中硬件关键词：{', '.join(matched_hw[:3])}")
    if matched_sw:
        return _decision(OWNERSHIP_SOFTWARE, 0.80, f"命中软件关键词：{', '.join(matched_sw[:3])}")
    return _decision(OWNERSHIP_SOFTWARE, 0.55, "未命中明确硬件或协同信号，按软件候选低置信度保留")


def _decision(ownership: str, confidence: float, reason: str) -> dict[str, Any]:
    return {
        "ownership": ownership,
        "ownership_confidence": confidence,
        "ownership_reason": reason,
        "ownership_source": "rule",
    }


def _requirement_text(requirement: dict[str, Any]) -> str:
    parts = [
        requirement.get("title"),
        requirement.get("description"),
        requirement.get("requirement"),
        requirement.get("module"),
        requirement.get("source_quote"),
        " ".join(str(x) for x in requirement.get("labels") or []),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term.lower() in text]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_requirements_analysis_rules.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add requirements_analysis_rules.py tests/test_requirements_analysis_rules.py
git commit -m "feat: classify requirement ownership with rules"
```

---

### Task 3: 软件模板词表抽取

**Files:**
- Create: `requirements_analysis_template.py`
- Test: `tests/test_requirements_analysis_template.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_requirements_analysis_template.py
from pathlib import Path

from openpyxl import Workbook

from requirements_analysis_template import extract_template_vocabulary, fallback_template_vocabulary


def test_extracts_sheet_modules_and_submodules(tmp_path: Path):
    path = tmp_path / "template.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "时钟需求"
    ws.append(["关闭", "序号", "子模块", "描述", "需求"])
    ws.append(["", 1, "时钟", "夏令时：", "支持"])
    ws.append(["", 2, "时钟同步", "时区：", "东八区"])
    ws2 = wb.create_sheet("协议栈需求")
    ws2.append(["关闭", "序号", "子模块", "描述", "需求"])
    ws2.append(["", 1, "通信口1", "通信方式：", "Optical"])
    wb.save(path)

    vocab = extract_template_vocabulary(path)

    assert "时钟需求" in vocab["modules"]
    assert vocab["submodules_by_module"]["时钟需求"] == ["时钟", "时钟同步"]
    assert vocab["submodules_by_module"]["协议栈需求"] == ["通信口1"]


def test_fallback_vocabulary_contains_core_modules():
    vocab = fallback_template_vocabulary()

    assert "系统需求" in vocab["modules"]
    assert "协议栈需求" in vocab["modules"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_requirements_analysis_template.py -q`

Expected: FAIL，提示缺少 `requirements_analysis_template`。

- [ ] **Step 3: 实现模板词表**

```python
# requirements_analysis_template.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook


DEFAULT_MODULES = [
    "系统需求", "计量需求", "时钟需求", "费率需求", "显示需求", "需量需求",
    "结算需求", "负荷曲线", "报警窃电需求", "电网质量需求", "升级需求",
    "负控需求", "状态字需求", "事件需求", "协议栈需求", "push需求",
    "P1需求", "MBUS需求", "预付费需求",
]


def fallback_template_vocabulary() -> dict[str, Any]:
    return {"modules": list(DEFAULT_MODULES), "submodules_by_module": {module: [] for module in DEFAULT_MODULES}}


def extract_template_vocabulary(path: Path | None) -> dict[str, Any]:
    if path is None or not Path(path).exists():
        return fallback_template_vocabulary()
    wb = load_workbook(path, data_only=True, read_only=True)
    modules: list[str] = []
    submodules_by_module: dict[str, list[str]] = {}
    for ws in wb.worksheets:
        title = str(ws.title).strip()
        if not title or title.endswith("列表") or title in {"需求模版Release notes", "原始需求对应表", "需求变更管理"}:
            continue
        modules.append(title)
        submodules_by_module[title] = _extract_submodules(ws)
    return {"modules": modules, "submodules_by_module": submodules_by_module}


def _extract_submodules(ws: Any) -> list[str]:
    header_row = next(ws.iter_rows(min_row=1, max_row=5, values_only=True), ())
    submodule_col = None
    for index, value in enumerate(header_row):
        if str(value or "").strip() == "子模块":
            submodule_col = index
            break
    if submodule_col is None:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        value = str(row[submodule_col] or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_requirements_analysis_template.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add requirements_analysis_template.py tests/test_requirements_analysis_template.py
git commit -m "feat: extract software template vocabulary"
```

---

### Task 4: LLM Prompt 与响应校验

**Files:**
- Create: `requirements_analysis_agent.py`
- Test: `tests/test_requirements_analysis_agent.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_requirements_analysis_agent.py
from requirements_analysis_agent import build_analysis_prompt, validate_llm_item


def test_prompt_mentions_template_and_no_translation_only_rule():
    req = {"ai_req_id": "AI-1", "description": "支持夏令时", "source_quote": "shall support daylight saving"}
    vocab = {"modules": ["时钟需求"], "submodules_by_module": {"时钟需求": ["时钟"]}}

    prompt = build_analysis_prompt([req], vocab)

    assert "电表软件需求分析工程师" in prompt["system"]
    assert "不能只翻译" in prompt["user"]
    assert "时钟需求" in prompt["user"]


def test_validate_llm_item_rejects_number_drift():
    source = {"source_quote": "capture period shall be 900 seconds"}
    item = {
        "ownership": "software",
        "software_requirement_text": "系统应支持 600 seconds 捕获周期。",
        "source_requirement_ids": ["AI-1"],
    }

    issues = validate_llm_item(item, source)

    assert "source number 900 missing from analysis text" in issues
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_requirements_analysis_agent.py -q`

Expected: FAIL，提示缺少 `requirements_analysis_agent`。

- [ ] **Step 3: 实现 prompt 与基础漂移校验**

```python
# requirements_analysis_agent.py
from __future__ import annotations

import json
import re
from typing import Any


def build_analysis_prompt(requirements: list[dict[str, Any]], vocabulary: dict[str, Any]) -> dict[str, str]:
    system = (
        "你是电表软件需求分析工程师。你的任务不是翻译原文，"
        "而是基于可追溯的抽取结果推导软件研发需求。"
    )
    user = "\n".join([
        "请分析以下需求，输出 JSON 数组。",
        "ownership 只能是 software、hardware、co_design。",
        "hardware 只做简要处理，不生成软件模板需求。",
        "software 要给出输入/触发、处理逻辑、输出/状态变化、验收建议。",
        "co_design 要详细写软件侧，简要写硬件依赖。",
        "不能只翻译原文。不能修改数字、OBIS、DLMS class ID、阈值、时间、访问权限。",
        f"模板词表：{json.dumps(vocabulary, ensure_ascii=False)}",
        f"需求：{json.dumps(requirements, ensure_ascii=False)}",
    ])
    return {"system": system, "user": user}


def validate_llm_item(item: dict[str, Any], source: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    source_text = str(source.get("source_quote") or source.get("description") or source.get("requirement") or "")
    analysis_text = " ".join(
        str(item.get(key) or "")
        for key in ("requirement", "software_requirement_text", "hardware_dependency", "ownership_reason")
    )
    for number in _numbers(source_text):
        if number not in analysis_text:
            issues.append(f"source number {number} missing from analysis text")
    return issues


def _numbers(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\b\d+(?:\.\d+)?\b", text)))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_requirements_analysis_agent.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add requirements_analysis_agent.py tests/test_requirements_analysis_agent.py
git commit -m "feat: add requirements analysis prompt"
```

---

### Task 5: 分析编排与 JSON/Markdown 输出

**Files:**
- Create: `requirements_analysis.py`
- Test: `tests/test_requirements_analysis_pipeline.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_requirements_analysis_pipeline.py
import json
from pathlib import Path

from requirements_analysis import run_requirements_analysis


def write_jsonl(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_run_requirements_analysis_writes_json_and_reports(tmp_path: Path):
    write_jsonl(tmp_path / "ai_requirements.jsonl", [
        {
            "ai_req_id": "AI-1",
            "title": "Clock",
            "description": "The meter shall support Clock object daylight saving time.",
            "source_quote": "support Clock object daylight saving time",
            "source_block_ids": ["B-1"],
            "module": "时钟需求",
        },
        {
            "ai_req_id": "AI-2",
            "description": "计量芯片型号为 Att7022e。",
            "source_quote": "计量芯片型号为 Att7022e",
            "source_block_ids": ["B-2"],
            "module": "计量需求",
        },
    ])
    write_jsonl(tmp_path / "ai_review_states.jsonl", [
        {"ai_req_id": "AI-2", "ownership_override": "co_design", "reason": "软件需适配驱动"}
    ])

    result = run_requirements_analysis(tmp_path, route="stub", template_path=None)

    assert result["analysis_count"] == 2
    assert (tmp_path / "engineering_analysis.json").exists()
    assert (tmp_path / "hardware_items.md").exists()
    payload = json.loads((tmp_path / "engineering_analysis.json").read_text(encoding="utf-8"))
    by_id = {row["source_requirement_ids"][0]: row for row in payload["items"]}
    assert by_id["AI-2"]["ownership"] == "co_design"
    assert by_id["AI-2"]["ownership_source"] == "reviewer_override"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_requirements_analysis_pipeline.py -q`

Expected: FAIL，提示缺少 `requirements_analysis`。

- [ ] **Step 3: 实现编排函数**

```python
# requirements_analysis.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from io_utils import read_jsonl
from requirements_analysis_rules import classify_ownership
from requirements_analysis_schema import apply_ownership_override, build_analysis_id, validate_analysis_item
from requirements_analysis_template import extract_template_vocabulary


def run_requirements_analysis(out_dir: Path, *, route: str = "stub", template_path: Path | None = None) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "ai_requirements.jsonl")
    states = _states_by_ai_req_id(read_jsonl(out_dir / "ai_review_states.jsonl"))
    vocabulary = extract_template_vocabulary(template_path)
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for index, req in enumerate(requirements, start=1):
        item = _base_item(index, req, vocabulary)
        item.update(classify_ownership(req))
        item = apply_ownership_override(item, states.get(str(req.get("ai_req_id") or "")))
        item_issues = validate_analysis_item(item)
        if item_issues:
            issues.append({"analysis_id": item["analysis_id"], "issues": item_issues})
        items.append(item)

    payload = {"schema_version": "0.1", "route": route, "items": items, "issues": issues}
    (out_dir / "engineering_analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(out_dir / "hardware_items.md", [row for row in items if row["ownership"] == "hardware"], "硬件需求简报")
    _write_report(out_dir / "co_design_items.md", [row for row in items if row["ownership"] == "co_design"], "软硬件协同需求")
    return {"kind": "requirements_analysis", "analysis_count": len(items), "issues": len(issues)}


def _base_item(index: int, req: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    source_id = str(req.get("ai_req_id") or req.get("stable_req_id") or req.get("req_id") or f"REQ-{index}")
    module = _module_or_unmapped(req, vocabulary)
    return {
        "analysis_id": build_analysis_id(index),
        "source_kind": "ai_requirement",
        "source_requirement_ids": [source_id],
        "source_block_ids": [str(x) for x in req.get("source_block_ids") or []],
        "source_section": str(req.get("source_section") or ""),
        "source_quote": str(req.get("source_quote") or ""),
        "module": module,
        "submodule": str(req.get("module") or module),
        "template_match": "matched" if module in vocabulary.get("modules", []) else "unmapped",
        "description": str(req.get("title") or req.get("description") or ""),
        "requirement": str(req.get("description") or req.get("requirement") or ""),
        "software_requirement_text": "",
        "developer_guidance": [],
        "hardware_dependency": "",
        "acceptance_criteria": [],
        "open_questions": [],
        "notes": [],
    }


def _module_or_unmapped(req: dict[str, Any], vocabulary: dict[str, Any]) -> str:
    module = str(req.get("module") or "").strip()
    return module if module in vocabulary.get("modules", []) else (module or "unmapped")


def _states_by_ai_req_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("ai_req_id") or "")
        if key:
            result[key] = row
    return result


def _write_report(path: Path, rows: list[dict[str, Any]], title: str) -> None:
    lines = [f"# {title}", ""]
    for row in rows:
        lines.extend([
            f"## {row['analysis_id']} {row.get('description') or ''}",
            f"- 归属原因：{row.get('ownership_reason') or ''}",
            f"- 来源：{', '.join(row.get('source_requirement_ids') or [])}",
            f"- 原文：{row.get('source_quote') or ''}",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run requirements analysis agent.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--route", default="stub", choices=["stub", "openai_compatible"])
    parser.add_argument("--template", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_requirements_analysis(args.out, route=args.route, template_path=args.template)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_requirements_analysis_pipeline.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add requirements_analysis.py tests/test_requirements_analysis_pipeline.py
git commit -m "feat: orchestrate requirements analysis"
```

---

### Task 6: 软件需求 Excel 导出

**Files:**
- Create: `requirements_analysis_excel.py`
- Modify: `requirements_analysis.py`
- Test: `tests/test_requirements_analysis_pipeline.py`

- [ ] **Step 1: 给 Excel 导出补失败测试**

Append to `tests/test_requirements_analysis_pipeline.py`:

```python
from openpyxl import load_workbook


def test_software_workbook_excludes_hardware_and_includes_codesign(tmp_path: Path):
    write_jsonl(tmp_path / "ai_requirements.jsonl", [
        {
            "ai_req_id": "AI-1",
            "description": "The meter shall support push notification.",
            "source_quote": "support push notification",
            "source_block_ids": ["B-1"],
            "module": "push需求",
        },
        {
            "ai_req_id": "AI-2",
            "description": "计量芯片型号为 Att7022e。",
            "source_quote": "计量芯片型号为 Att7022e",
            "source_block_ids": ["B-2"],
            "module": "计量需求",
        },
        {
            "ai_req_id": "AI-3",
            "description": "波特率最大值与硬件相关，需要驱动适配。",
            "source_quote": "波特率最大值与硬件相关",
            "source_block_ids": ["B-3"],
            "module": "协议栈需求",
        },
    ])

    run_requirements_analysis(tmp_path, route="stub", template_path=None)

    wb = load_workbook(tmp_path / "software_requirements.xlsx", data_only=True)
    values = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=2, values_only=True):
            if any(row):
                values.append(row)

    descriptions = [str(row[3] or "") for row in values]
    hardware_flags = [str(row[9] or "") for row in values]
    assert any("push" in value.lower() for value in descriptions)
    assert not any("计量芯片" in value for value in descriptions)
    assert "是" in hardware_flags
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_requirements_analysis_pipeline.py::test_software_workbook_excludes_hardware_and_includes_codesign -q`

Expected: FAIL，提示 `software_requirements.xlsx` 不存在。

- [ ] **Step 3: 实现 Excel 导出**

```python
# requirements_analysis_excel.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


HEADERS = [
    "关闭", "序号", "子模块", "描述", "需求模版", "需求", "说明、示例、注意事项",
    "是否客户需求", "客户需求章节", "驱动/硬件相关", "项目负责人确认", "测试负责人确认",
    "研发测试确认", "功能是否实现", "测试用例号", "测试是否完成",
]


def write_software_requirements_xlsx(items: list[dict[str, Any]], output_path: Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item.get("ownership") not in {"software", "co_design"}:
            continue
        grouped.setdefault(str(item.get("module") or "unmapped"), []).append(item)
    if not grouped:
        grouped["软件需求"] = []
    for module, rows in grouped.items():
        ws = wb.create_sheet(_safe_sheet_title(module))
        ws.append(HEADERS)
        _style_header(ws)
        for index, item in enumerate(rows, start=1):
            ws.append(_excel_row(index, item))
        ws.freeze_panes = "A2"
    wb.save(output_path)
    return output_path


def _excel_row(index: int, item: dict[str, Any]) -> list[Any]:
    notes = []
    notes.extend(str(x) for x in item.get("developer_guidance") or [])
    if item.get("source_quote"):
        notes.append(f"原文：{item['source_quote']}")
    notes.extend(f"待确认：{x}" for x in item.get("open_questions") or [])
    return [
        "", index, item.get("submodule") or "", item.get("description") or "",
        "" if item.get("template_match") == "unmapped" else item.get("description") or "",
        item.get("software_requirement_text") or item.get("requirement") or "",
        "\n".join(notes), "是", item.get("source_section") or ",".join(item.get("source_requirement_ids") or []),
        "是" if item.get("ownership") == "co_design" else "",
        "", "", "", "", "", "",
    ]


def _style_header(ws: Any) -> None:
    fill = PatternFill(fill_type="solid", fgColor="D9EAF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill


def _safe_sheet_title(value: str) -> str:
    title = "".join(ch for ch in value if ch not in r'[]:*?/\\')[:31].strip()
    return title or "软件需求"
```

Modify `requirements_analysis.py`:

```python
from requirements_analysis_excel import write_software_requirements_xlsx
```

Inside `run_requirements_analysis()` before return:

```python
    write_software_requirements_xlsx(items, out_dir / "software_requirements.xlsx")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_requirements_analysis_pipeline.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add requirements_analysis_excel.py requirements_analysis.py tests/test_requirements_analysis_pipeline.py
git commit -m "feat: export software requirements workbook"
```

---

### Task 7: HTML 批注 Ownership 回流

**Files:**
- Modify: `ai_review_actions.py`
- Modify: `doc_annotation_export.py`
- Modify: `api_server.py`
- Test: `tests/test_ai_extract.py` or new `tests/test_ai_review_actions.py`
- Test: `tests/test_doc_annotation_export.py`

- [ ] **Step 1: 写裁决存储失败测试**

Create `tests/test_ai_review_actions.py`:

```python
from ai_review_actions import apply_ai_review_action, read_ai_review_states


def test_ai_review_action_persists_ownership_override(tmp_path):
    state = apply_ai_review_action(
        tmp_path,
        "AI-1",
        "accepted",
        module_override="时钟需求",
        ownership_override="co_design",
        reason="硬件 RTC 依赖需要确认",
        actor="tester",
    )

    assert state["ownership_override"] == "co_design"
    states = read_ai_review_states(tmp_path)
    assert states["AI-1"]["ownership_override"] == "co_design"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_ai_review_actions.py -q`

Expected: FAIL，提示 `apply_ai_review_action()` 不接受 `ownership_override`。

- [ ] **Step 3: 修改 `ai_review_actions.py`**

Update function signature:

```python
def apply_ai_review_action(
    out_dir: Path,
    req_id: str,
    status: str,
    *,
    module_override: str | None = None,
    ownership_override: str | None = None,
    reason: str = "",
    actor: str | None = None,
) -> dict[str, Any]:
```

Before writing `row`, normalize ownership:

```python
    ownership = str(ownership_override or "").strip() or None
```

Add to row:

```python
        "ownership_override": ownership,
```

- [ ] **Step 4: 更新 API 接收字段**

Modify `api_server.py` in `handle_ai_review_action()`:

```python
        ownership_override = str(payload.get("ownership_override") or "").strip() or None
```

Pass to `apply_ai_review_action()`:

```python
            state = apply_ai_review_action(
                self.output_dir,
                req_id,
                status,
                module_override=module_override,
                ownership_override=ownership_override,
                reason=reason,
                actor=actor,
            )
```

In `build_ai_requirements()`, when `state` exists:

```python
        if state and state.get("ownership_override"):
            row["ownership_effective"] = state["ownership_override"]
```

- [ ] **Step 5: 修改 HTML 导出**

In `doc_annotation_export.py`, add ownership display helper in JS template:

```javascript
function ownershipOf(r) {
  const d = decisionOf(r.ai_req_id);
  return (d && d.ownership_override) || r.ownership_effective || r.ownership || "software";
}
```

In detail card HTML, add select:

```javascript
const ownershipOptions = [
  ["software", "软件"],
  ["hardware", "硬件"],
  ["co_design", "软硬件协同"],
].map(([value, label]) => '<option value="'+value+'"'+(value===ownershipOf(r)?' selected':'')+'>'+label+'</option>').join("");
```

Add field markup near module select:

```javascript
'<div class="dd-section"><div class="dd-label">归属（可改）</div><select id="own-sel" class="dd-select">'+ownershipOptions+'</select></div>'+
```

When building exported decision:

```javascript
ownership_override: document.getElementById("own-sel").value,
```

- [ ] **Step 6: 运行相关测试**

Run:

```powershell
python -m pytest tests/test_ai_review_actions.py tests/test_api_server.py -q
python -m pytest tests/test_doc_annotation_export.py -q
```

Expected: PASS. If `tests/test_doc_annotation_export.py` does not exist, create a focused test that calls `export_annotation_html()` on a minimal out_dir and asserts the output contains `own-sel` and `ownership_override`.

- [ ] **Step 7: 提交**

```powershell
git add ai_review_actions.py api_server.py doc_annotation_export.py tests/test_ai_review_actions.py tests/test_doc_annotation_export.py
git commit -m "feat: support ownership review overrides"
```

---

### Task 8: CLI、桌面任务、打包注册

**Files:**
- Modify: `cli.py`
- Modify: `desktop_tasks.py`
- Modify: `pyproject.toml`
- Modify: `packaging/desktop_backend.spec`
- Test: `tests/test_cli_contract.py`
- Test: `tests/test_desktop_tasks.py`
- Test: `tests/test_platform_scaffold.py`

- [ ] **Step 1: 给 CLI 增加失败测试**

Append to `tests/test_cli_contract.py`:

```python
def test_analyze_command_emits_success_envelope(tmp_path):
    import json
    from cli import main

    (tmp_path / "ai_requirements.jsonl").write_text(
        json.dumps({
            "ai_req_id": "AI-1",
            "description": "The meter shall support push notification.",
            "source_quote": "support push notification",
            "source_block_ids": ["B-1"],
            "module": "push需求",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert main(["analyze", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "engineering_analysis.json").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cli_contract.py::test_analyze_command_emits_success_envelope -q`

Expected: FAIL，提示 CLI 不认识 `analyze`。

- [ ] **Step 3: 修改 `cli.py`**

In imports:

```python
from requirements_analysis import run_requirements_analysis
```

In `parse_args()`:

```python
    analyze = subparsers.add_parser("analyze", help="Run requirements analysis agent.")
    analyze.add_argument("--out", type=Path, required=True)
    analyze.add_argument("--template", type=Path, default=None)
    analyze.add_argument("--llm-route", choices=["stub", "openai_compatible"], default="stub")
    add_verbosity_arguments(analyze)
```

In `main()` dispatch:

```python
        elif args.command == "analyze":
            envelope = command_analyze(args, started, timing_ms)
```

Add function:

```python
def command_analyze(args: argparse.Namespace, started: float, timing_ms: dict[str, int]) -> dict[str, Any]:
    analysis = run_requirements_analysis(args.out, route=args.llm_route, template_path=args.template)
    timing_ms["analyze"] = elapsed_ms(started)
    timing_ms["total"] = timing_ms["analyze"]
    return success_envelope("analyze", args.out, analysis=analysis, timing_ms=timing_ms)
```

- [ ] **Step 4: 修改 `desktop_tasks.py`**

Add task function:

```python
def requirements_analysis_task(out_dir: Path, *, route: str = "stub", template_path: Path | None = None) -> dict[str, Any]:
    from requirements_analysis import run_requirements_analysis
    out_dir = out_dir.expanduser().resolve()
    result = run_requirements_analysis(out_dir, route=route, template_path=template_path)
    return {
        "kind": "requirements_analysis",
        "out_dir": str(out_dir),
        **result,
        "summary": build_output_summary(out_dir),
    }
```

Add parser:

```python
    analyze_parser = subparsers.add_parser("requirements-analysis")
    analyze_parser.add_argument("--out", type=Path, required=True)
    analyze_parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default="stub")
    analyze_parser.add_argument("--template", type=Path, default=None)
```

Add dispatch:

```python
        elif args.command == "requirements-analysis":
            payload = requirements_analysis_task(args.out, route=args.llm_route, template_path=args.template)
```

- [ ] **Step 5: 注册打包模块**

Modify `pyproject.toml` `[tool.setuptools].py-modules`:

```toml
  "requirements_analysis",
  "requirements_analysis_agent",
  "requirements_analysis_excel",
  "requirements_analysis_rules",
  "requirements_analysis_schema",
  "requirements_analysis_template",
```

Modify `packaging/desktop_backend.spec` `spec_generator_modules`:

```python
    "requirements_analysis",
    "requirements_analysis_agent",
    "requirements_analysis_excel",
    "requirements_analysis_rules",
    "requirements_analysis_schema",
    "requirements_analysis_template",
```

- [ ] **Step 6: 运行测试**

Run:

```powershell
python -m pytest tests/test_cli_contract.py tests/test_desktop_tasks.py tests/test_platform_scaffold.py -q
```

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add cli.py desktop_tasks.py pyproject.toml packaging/desktop_backend.spec tests/test_cli_contract.py tests/test_desktop_tasks.py tests/test_platform_scaffold.py
git commit -m "feat: expose requirements analysis command"
```

---

### Task 9: 文档、端到端验证、质量检查

**Files:**
- Modify: `README.md`
- Test: full relevant suite

- [ ] **Step 1: 更新 README**

Add after the AI Review or Desktop App section:

```markdown
## Requirements Analysis Agent

Run the analysis agent after `atomize` and optional `ai-extract`:

```powershell
ratomizer analyze --out ".\out\run-001" --llm-route stub
```

The analysis stage reads `ai_requirements.jsonl`, applies imported HTML review decisions, classifies each item as `software`, `hardware`, or `co_design`, and writes:

- `engineering_analysis.json`
- `software_requirements.xlsx`
- `hardware_items.md`
- `co_design_items.md`

Hardware-only items are summarized but excluded from `software_requirements.xlsx`. Co-design items appear in the software workbook with `驱动/硬件相关 = 是`.
```

- [ ] **Step 2: 跑新增测试**

Run:

```powershell
python -m pytest `
  tests/test_requirements_analysis_schema.py `
  tests/test_requirements_analysis_rules.py `
  tests/test_requirements_analysis_template.py `
  tests/test_requirements_analysis_agent.py `
  tests/test_requirements_analysis_pipeline.py `
  tests/test_ai_review_actions.py `
  -q
```

Expected: PASS。

- [ ] **Step 3: 跑现有关键回归**

Run:

```powershell
python -m pytest tests/test_cli_contract.py tests/test_desktop_tasks.py tests/test_api_server.py tests/test_doc_annotation_export.py -q
```

Expected: PASS。

- [ ] **Step 4: 跑前端/Electron 测试**

Run:

```powershell
cd .\ui
npm test
npm run build
```

Expected: both PASS。

- [ ] **Step 5: 跑全量后端测试**

Run:

```powershell
python -m pytest -q
```

Expected: PASS。

- [ ] **Step 6: 提交文档和最终验证修订**

```powershell
git add README.md
git commit -m "docs: document requirements analysis agent"
```

---

## 自审清单

- Spec 覆盖：
  - 三分类：Task 1、Task 2、Task 5。
  - 规则 + LLM 策略：Task 2、Task 4、Task 5。
  - 软件模板词表：Task 3。
  - 软件 Excel：Task 6。
  - HTML ownership 可改：Task 7。
  - CLI/桌面入口：Task 8。
  - 测试和文档：Task 9。
- 占位符扫描：计划中没有未决占位字段；每个任务有具体文件、测试、实现方向、命令和提交点。
- 类型一致性：
  - 归属字段统一为 `ownership`。
  - 人工覆盖字段统一为 `ownership_override`。
  - 输出 ID 统一为 `ANREQ-000001` 格式。
  - 软件 Excel 输出文件统一为 `software_requirements.xlsx`。
