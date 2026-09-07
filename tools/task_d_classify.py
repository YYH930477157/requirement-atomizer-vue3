"""只读分类功能抽取的 table preservation blocking findings。

这个工具服务于任务 D 的诊断附录，不参与生产守恒判断，也不会重写输入结果包。
它读取结果包中已经记录的 ``conservation.checks.preservation.blocking_losses``，再把
每一项和当前结果包的 blocks/chunks/table_cell_items/functional_requirements 做确定性
关联。分类是修复方向提示：

* ``a_narrative_loss``：条款/表格内容在扁平源文本中，且有 FRE 声明，但叙述未保留 token；
* ``b_missing_functional_requirement``：源条款可定位，但没有任何 FRE 声明；
* ``c_table_or_baseline_input``：token 只在 cell 或已被路由出基线的输入位置可见；
* ``manual_review``：证据不足，保留为人工裁决，绝不把它伪装成 a/b/c。

历史产物可能由旧 conservation model 生成，因此报告同时写入产物模型版本与关联证据，
供人工审查。当前报告（v2）还会回显 preservation finding 携带的
``section_block_ids``/``section_path``，用于同名条款的物理归属核对；旧报告没有这些
字段时仍按保守的内容证据回退。脚本默认为两个本机已有结果包；也可以用
``--dataset NAME=PATH`` 重跑。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import functional_extract as fe  # noqa: E402

SCHEMA = "task-d-preservation-classification/v2"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _token_present(kind: str, token: str, text: str) -> bool:
    """Use the same token families as preservation_findings, without changing them."""
    if not text:
        return False
    if kind == "number":
        return str(token) in {str(v) for v in fe.extract_ints(text)}
    pattern = fe._PRESERVATION_PATTERNS.get(kind)
    if pattern is None:
        return _norm(token) in _norm(text)
    return str(token).casefold() in {m.group(0).casefold() for m in pattern.finditer(text)}


def _section_paths(row: dict[str, Any]) -> list[str]:
    path = row.get("section_path")
    if isinstance(path, list):
        return [str(x) for x in path if str(x).strip()]
    return [str(path)] if str(path or "").strip() else []


def _context(
    section_id: str,
    baseline: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    section_block_ids: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Locate a loss with block identity first, then path fallback for routed-out clauses."""
    sections = [s for s in baseline if str(s.get("section_id") or "") == section_id]
    explicit_blocks = {
        str(block_id) for block_id in (section_block_ids or ()) if str(block_id)
    }
    if explicit_blocks:
        # Current conservation reports include the exact physical jurisdiction.
        # Use it to disambiguate repeated section labels; old reports omit the
        # field and retain the conservative content/path fallback below.
        exact = [
            section for section in sections
            if {
                str(block_id) for block_id in (section.get("block_ids") or [])
                if str(block_id)
            } == explicit_blocks
        ]
        if exact:
            sections = exact
    block_ids: set[str] = {
        str(block_id)
        for section in sections
        for block_id in (section.get("block_ids") or [])
        if str(block_id)
    }
    # Old conservation records only carry section_id. Chunks retain the original
    # section path and block jurisdiction even when the section was routed out.
    path_chunks = [
        c for c in chunks
        if any(_norm(section_id) == _norm(p) for p in _section_paths(c))
    ]
    path_blocks = [b for b in blocks if any(_norm(section_id) == _norm(p) for p in _section_paths(b))]
    # Preserve the baseline's block identity when it exists.  Path blocks are
    # only a fallback for routed-out clauses; adding them to an existing
    # baseline would falsely turn excluded table blocks into ordinary text.
    if not sections:
        for chunk in path_chunks:
            block_ids.update(str(x) for x in (chunk.get("source_block_ids") or []) if str(x))
        for block in path_blocks:
            block_ids.add(str(block.get("block_id") or ""))
    block_ids.discard("")
    # Cells can be physically associated with a routed table block that is absent
    # from the text baseline; section_path is therefore an intentional fallback.
    table_cells = [
        cell for cell in cells
        if str(cell.get("table_block_id") or "") in block_ids
        or any(_norm(section_id) == _norm(p) for p in _section_paths(cell))
    ]
    source_text = "\n".join(str(s.get("text") or "") for s in sections)
    if not source_text:
        source_text = "\n".join(str(b.get("text") or "") for b in path_blocks)
    table_block_ids = sorted({str(cell.get("table_block_id") or "") for cell in table_cells if str(cell.get("table_block_id") or "")})
    return {
        "sections": sections,
        "block_ids": sorted(block_ids),
        "path_chunks": path_chunks,
        "path_blocks": path_blocks,
        "table_cells": table_cells,
        "table_block_ids": table_block_ids,
        "table_blocks_outside_baseline": [x for x in table_block_ids if x not in block_ids],
        "source_text": source_text,
    }


def _declared_items(section_id: str, context: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    block_ids = set(context["block_ids"])
    out: list[dict[str, Any]] = []
    for item in items:
        declared = {str(x) for x in (item.get("source_block_ids") or []) if str(x)}
        source_section = str(item.get("source_section") or "")
        if block_ids.intersection(declared) or _norm(source_section) == _norm(section_id):
            out.append(item)
    return out


def classify_dataset(name: str, root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    product_path = root / "functional_requirements.json"
    if not product_path.is_file():
        raise FileNotFoundError(f"{name}: missing {product_path}")
    product = _read_json(product_path)
    items = product.get("items") if isinstance(product.get("items"), list) else []
    baseline = fe.load_conservation_baseline(root)
    blocks = _read_jsonl(root / "blocks.jsonl")
    chunks = _read_jsonl(root / "chunks.jsonl")
    cells = _read_jsonl(root / "table_cell_items.jsonl")
    checks = product.get("conservation") or {}
    checks = checks.get("checks") if isinstance(checks, dict) else {}
    preservation = checks.get("preservation") if isinstance(checks, dict) else {}
    losses = preservation.get("blocking_losses") if isinstance(preservation, dict) else []
    if not isinstance(losses, list):
        losses = []
    rows: list[dict[str, Any]] = []
    for raw in losses:
        if not isinstance(raw, dict):
            continue
        section_id = str(raw.get("section_id") or "")
        kind = str(raw.get("kind") or "")
        token = str(raw.get("token") or "")
        context = _context(
            section_id, baseline, blocks, chunks, cells,
            section_block_ids=raw.get("section_block_ids"),
        )
        declared = _declared_items(section_id, context, items)
        source_text = context["source_text"]
        cell_text = "\n".join(str(cell.get("text") or "") for cell in context["table_cells"])
        narrative_text = "\n".join(fe.item_narrative(item) for item in declared)
        source_has = _token_present(kind, token, source_text)
        cell_has = _token_present(kind, token, cell_text)
        narrative_has = _token_present(kind, token, narrative_text)
        routed_only = bool(context["path_chunks"] or context["path_blocks"]) and not context["sections"]
        # A routed-out clause has no stable baseline text.  A cell hit is enough
        # to attribute the loss to the input/table side; without it the stored
        # section_id cannot distinguish a missing requirement from a stale
        # baseline, so keep the row for a human rather than guessing.
        if cell_has and (not source_has or routed_only):
            category = "c_table_or_baseline_input"
            rationale = "token_present_in_table_cells_but_not_current_flat_baseline"
        elif routed_only:
            category = "manual_review"
            rationale = "routed_out_clause_has_no_stable_baseline_identity"
        elif len(context["sections"]) > 1:
            category = "manual_review"
            rationale = "duplicate_section_id_prevents_token_to_section_attribution"
        elif declared and source_has and not narrative_has:
            category = "a_narrative_loss"
            rationale = "token_present_in_flat_source_and_declared_fre_but_absent_from_narrative"
        elif not declared:
            category = "b_missing_functional_requirement"
            rationale = "no_functional_requirement_declares_resolved_section_blocks"
        else:
            category = "manual_review"
            rationale = "available_artifacts_do_not_prove_a_b_or_c"
        rows.append({
            "section_id": section_id,
            "section_block_ids": [
                str(block_id) for block_id in (raw.get("section_block_ids") or [])
                if str(block_id)
            ],
            "section_path": _section_paths(raw),
            "kind": kind,
            "token": token,
            "category": category,
            "rationale": rationale,
            "declared_fre_count": len(declared),
            "baseline_section_count": len(context["sections"]),
            "block_ids": context["block_ids"],
            "table_cell_count": len(context["table_cells"]),
            "table_block_ids": context["table_block_ids"],
            "table_blocks_outside_baseline": context["table_blocks_outside_baseline"],
            "source_token_present": source_has,
            "cell_token_present": cell_has,
            "narrative_token_present": narrative_has,
            "routed_only_context": routed_only,
            "sample_fre_ids": [str(i.get("functional_requirement_id") or "") for i in declared[:5]],
        })
    return {
        "name": name,
        "root": str(root),
        "product_model": product.get("conservation_model"),
        "execution_status": product.get("execution_status"),
        "blocking_total": len(rows),
        "categories": dict(Counter(str(row["category"]) for row in rows)),
        "rows": rows,
    }


def _default_datasets() -> list[tuple[str, Path]]:
    values = [("sbd_result3", ROOT / "out" / "attribution-result3")]
    temp = Path(__import__("tempfile").gettempdir()) / "ab-runner.9gqsr665" / "B_direct"
    if (temp / "functional_requirements.json").is_file():
        values.append(("abnt_ws0_b_direct", temp))
    return values


def _parse_dataset(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("--dataset must use NAME=PATH")
    name, path = value.split("=", 1)
    if not name.strip() or not path.strip():
        raise ValueError("--dataset must use NAME=PATH")
    return name.strip(), Path(path.strip())


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 任务 D：表格 preservation blocking 分类（只读诊断）",
        "",
        "> 本文由 `tools/task_d_classify.py` 生成。分类不改变 `functional_extract` 的守恒语义；输入结果包按其已记录的 conservation report 读取。`manual_review` 保留证据不足项。",
        "",
    ]
    total = sum(int(report["blocking_total"]) for report in payload["datasets"])
    lines.insert(3, f"两个语料合计 blocking：**{total}**。")
    lines.insert(
        4,
        "数据限制：仓库内 SBD 结果包记录的是 v3、ABNT 临时 B 结果包记录的是 v6；当前代码已经是 v7。两者不能直接作为当前 v7/v8 门禁 PASS 证据。旧报告还只保存 `section_id`，无法在同名 Security 等条款之间复原唯一条款序号。",
    )
    for report in payload["datasets"]:
        lines += [
            f"## {report['name']}",
            "",
            f"- 结果包：`{report['root']}`",
            f"- conservation model：`{report.get('product_model') or 'unknown'}`；execution_status：`{report.get('execution_status') or 'unknown'}`",
            f"- blocking 总数：**{report['blocking_total']}**；分类：`{report['categories']}`",
            "",
            "| section | physical blocks | kind | token | 类别 | FRE | baseline/cell | 证据 |",
            "|---|---|---|---|---:|---:|---:|---|",
        ]
        for row in report["rows"]:
            outside = len(row.get("table_blocks_outside_baseline") or [])
            evidence = (
                f"source={'Y' if row['source_token_present'] else 'N'}, "
                f"cell={'Y' if row['cell_token_present'] else 'N'}, "
                f"narrative={'Y' if row['narrative_token_present'] else 'N'}, "
                f"table_out={outside}"
            )
            lines.append(
                f"| {row['section_id'][:70]} | `{','.join(row.get('section_block_ids') or row.get('block_ids') or [])}` | "
                f"{row['kind']} | `{row['token']}` | "
                f"{row['category']} | {row['declared_fre_count']} | "
                f"{row['baseline_section_count']}/{row['table_cell_count']} | {evidence} |"
            )
        lines += ["", "分类规则", "", "- `a_narrative_loss`：源扁平文本和已声明 FRE 都存在 token，FRE 叙述缺失。", "- `b_missing_functional_requirement`：可定位源条款，但没有 FRE 声明。", "- `c_table_or_baseline_input`：token 在物理 cell 中可见，却不在当前扁平守恒基线，或条款仅存在于路由外上下文。", "- `manual_review`：证据不够，必须人工裁决。", ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--out", type=Path, help="write JSON/Markdown report prefix (without extension)")
    args = parser.parse_args(argv)
    datasets = [_parse_dataset(x) for x in args.dataset] if args.dataset else _default_datasets()
    reports = [classify_dataset(name, path) for name, path in datasets]
    payload = {"schema": SCHEMA, "datasets": reports}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.out.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
