"""WS0 真值集英文重建（2026-09-08，P1 语言断层修复的配套工具）。

从 Canna29 条目化 xlsx 的 **English Translation 列**（分析师人工提供的英文）重建
ab_runner 真值——不是机器翻译，人工真值权威保留。与 v1（Chinese Analysis 列，
golden_sets/ws0_human_v1）逐行对齐：同选行（有中文分析的行）、同顺序、同 truth_id。

新增确定性 ``domain`` 标记（进 notes 留证据）：
- ``b_track``：expected_text 与「路由保留基线（前置章节剔除后）」内容重叠 ≥ 阈值
  （默认 0.4，``--domain-threshold`` 可调）——scoped recall 的分母；
- ``out_of_scope``：前置/定义/域外行（结构性 FN，如实报告、不进 scoped 分母）。

数值/单位/编码从英文文本按 ``truth_from_review._truth_row`` 同一正则权威重提。
输出逐行过 ``schemas/functional_truth.schema.json``（v2 起含可选 domain 字段）。

用法::

    PYTHONPATH=. python tools/truth_rebuild_en.py \\
        --input "C:/.../Canna29 需求条目化 ....xlsx" \\
        --document-id abnt_nbr_16968 --corpus out/abnt_nbr_16968 \\
        --output golden_sets/ws0_human_v2_en/truth.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for entry in (str(REPO_ROOT), str(REPO_ROOT / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import ab_runner as ab  # noqa: E402
from truth_from_review import SCHEMA_PATH, _cell_text, _truth_row  # noqa: E402

# 条目化 xlsx 的固定列名（表头文字识别，不依赖列位）
_COL_TITLE = "Título Principal"
_COL_SUB1 = "Subtítulo Nível 1"
_COL_EN = "English Translation"
COL_CN = "Chinese Analysis"


def _read_rows(path: Path) -> list[dict]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise SystemExit("输入表为空")
    header = [_cell_text(c) for c in rows[0]]
    try:
        idx_en = header.index(_COL_EN)
        idx_cn = header.index(COL_CN)
    except ValueError as exc:
        raise SystemExit(f"输入表缺必需列（{_COL_EN}/{COL_CN}）：{exc}") from exc
    idx_sub1 = header.index(_COL_SUB1) if _COL_SUB1 in header else None
    skipped_mislabeled = 0
    out = []
    for row in rows[1:]:
        english = _cell_text(row[idx_en]) if idx_en < len(row) else ""
        chinese = _cell_text(row[idx_cn]) if idx_cn < len(row) else ""
        if not chinese:
            continue  # v1 对齐口径：无中文分析的行不进真值
        if not english:
            continue  # v2 口径：重建锚定人工英文列，缺英文的行跳过（计数上报）
        cjk = sum(1 for ch in english if "\u4e00" <= ch <= "\u9fff")
        if cjk and cjk / max(1, len(english)) > 0.3:
            # 源表个别行的 English 列实为中文（列内容错标）——视同缺英文跳过并计数
            skipped_mislabeled += 1
            continue
        section = ""
        if idx_sub1 is not None and idx_sub1 < len(row):
            section = _cell_text(row[idx_sub1])
        out.append({"expected_text": english, "section_id": section or "*",
                    "condition_text": "", "_chinese": chinese})
    if skipped_mislabeled:
        print(json.dumps({"warn": "english-column-mislabeled-rows-skipped",
                          "count": skipped_mislabeled}, ensure_ascii=False))
    return out


def _baseline_clauses(corpus: Path) -> list[dict]:
    """B 轨抽取域：全量条款 → 剔前置章节 → 路由保留（与抽取管线的域定义同源）。"""
    import functional_extract as fe

    sections, _audit = fe.load_clauses_detailed(corpus)
    kept = []
    for section in sections:
        path = section.get("section_path") or []
        top = fe._front_matter_top_key(str(path[0]) if path else "")
        if top in fe._FRONT_MATTER_TOP_LEVEL:
            continue
        kept.append(section)
    from io_utils import read_jsonl

    blocks = read_jsonl(corpus / "blocks.jsonl")
    kept, _meta = fe.apply_unit_routing(kept, blocks=blocks, out_dir=corpus)
    return list(kept)


def main(argv: list[str | None] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WS0 真值集英文重建（English Translation 列）")
    parser.add_argument("--input", type=Path, required=True, help="Canna29 条目化 xlsx")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--corpus", type=Path, required=True,
                        help="解析目录（域判定：路由保留基线）")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain-threshold", type=float, default=0.4,
                        help="b_track 域判定的窗口联合覆盖率阈值（默认 0.4）")
    parser.add_argument("--domain-window", type=int, default=15,
                        help="域判定滑动窗口条款数（默认 15——对冲切分病理的碎片化）")
    args = parser.parse_args(argv)

    rows = _read_rows(args.input)
    if not rows:
        raise SystemExit("重建结果为 0 行——拒绝写盘（检查输入列）")

    import functional_extract as fe

    clauses = _baseline_clauses(args.corpus)
    # 语料因切分病理碎成大量条款片（337 片「2 20 Control of」）——真值行内容常跨
    # 多个连续片段，单条款覆盖被稀释。域判定用**滑动窗口联合覆盖**：连续
    # ``window`` 个条款的 token 并集（文档序），窗口预计算一次、逐行取最大。
    window = max(1, args.domain_window)
    clause_tokens = [
        fe._content_tokens(str(clause.get("text") or "")) for clause in clauses
    ]
    windows: list[set[str]] = []
    for start in range(0, len(clause_tokens)):
        union: set[str] = set()
        for tokens in clause_tokens[start:start + window]:
            union |= tokens
        windows.append(union)
        if not union:
            break  # 尾部全空——无需继续

    truth = []
    domains = {"b_track": 0, "out_of_scope": 0}
    for seq, row in enumerate(rows, start=1):
        entry = _truth_row(args.document_id, seq, row, extract=True)
        truth_tokens = fe._content_tokens(row["expected_text"])
        best_cov, best_at = 0.0, 0
        if truth_tokens:
            for index, union in enumerate(windows):
                if not union:
                    continue
                cov = len(truth_tokens & union) / len(truth_tokens)
                if cov > best_cov:
                    best_cov, best_at = cov, index
        best_sid = (str(clauses[best_at].get("section_id") or "")
                    if best_at < len(clauses) else "")
        domain = "b_track" if best_cov >= args.domain_threshold else "out_of_scope"
        domains[domain] += 1
        entry["domain"] = domain
        entry["notes"] = (
            "rebuilt-2026-09-08 from xlsx 'English Translation' column (analyst-provided "
            f"English; v1 Chinese truth id-aligned); domain={domain} via max window-union "
            f"coverage {best_cov:.2f} @ clause#{best_at} section {best_sid or 'n/a'} "
            f"(window={window})"
        )
        truth.append(entry)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        from jsonschema import Draft202012Validator

        validator = Draft202012Validator(schema)
        for row in truth:
            for error in validator.iter_errors(row):
                raise SystemExit(f"真值行校验失败 {row['truth_id']}: {error.message}")
    except ImportError:  # pragma: no cover
        for row in truth:
            for key in ab.TRUTH_REQUIRED_KEYS:
                if key not in row:
                    raise SystemExit(f"真值行缺必需键 {key}: {row['truth_id']}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in truth) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "rows": len(truth),
        "domains": domains,
        "domain_threshold": args.domain_threshold,
        "baseline_clauses": len(clauses),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
