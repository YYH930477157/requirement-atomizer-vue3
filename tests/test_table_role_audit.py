"""Tests for tools/table_role_audit.py (WS1 wk8 角色语义抽审门禁工具).

Exercises the three subcommands in-process (argv lists, no subprocess) against
synthetic corpora built in temp dirs. Covers: sampling frame = only issued
hypotheses; stratified worksheet reuses table_cell_items coordinates + annotation
anchors; record fills verdicts from expert input; evaluate computes per-family
cell accuracy with NO cross-family averaging and returns exit 2 below threshold /
0 above / 3 on validation problems.

Coordinate authority is the real ``table-cell-item/v1`` shape (cell_id + [row,col]),
so an expert can always re-locate a cell in the annotation HTML — the spec §5
"不要新造坐标系" invariant.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_TOOLS = _REPO / "tools"
for _p in (_REPO, _TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import table_role_audit as audit  # noqa: E402
from output_writer import write_jsonl  # noqa: E402

HEADER_ROW = 1


def _cell_item(table_id, block_id, r, c, role, text, header):
    return {
        "schema": "table-cell-item/v1",
        "cell_id": f"{table_id}-R{r:06d}-C{c:06d}",
        "table_id": table_id, "table_block_id": block_id,
        "table_title": "T", "section_path": ["5.2", "Parameters"],
        "row_index": r, "column_index": c,
        "data_row_index": (r - 1) if role == "data" else None,
        "row_span": 1, "column_span": 1, "covered_coordinates": [],
        "structural_role": role, "text": text, "raw_text": text,
        "header_path": [header], "row_header_context": [], "row_header_entries": [],
        "source_format": "docx", "requirement_like": False, "leaf_kind": "cell",
        "table_structure_version": "table-structure-v7",
    }


def _matrix_cells(table_id, block_id, headers, data_rows):
    """Build table_cell_items: one header row + N data rows x len(headers) cols."""
    items = []
    for c, h in enumerate(headers, start=1):
        items.append(_cell_item(table_id, block_id, HEADER_ROW, c, "header", h, h))
    for ri, row in enumerate(data_rows, start=HEADER_ROW + 1):
        for c, val in enumerate(row, start=1):
            items.append(_cell_item(table_id, block_id, ri, c, "data", val, headers[c - 1]))
    return items


def _hypothesis_cells(header_cols, data_rows_count, wrong_rows=()):
    """Per-cell roles. Rows in wrong_rows are deliberately mislabeled as header."""
    cells = [{"coordinate": [HEADER_ROW, c], "role": "header", "confidence": "high"}
             for c in range(1, header_cols + 1)]
    n_rows = data_rows_count
    for ri in range(HEADER_ROW + 1, HEADER_ROW + 1 + n_rows):
        role = "header" if (ri - HEADER_ROW) in wrong_rows else "data"
        for c in range(1, header_cols + 1):
            cells.append({"coordinate": [ri, c], "role": role, "confidence": "high"})
    return cells


def _signed_record(doc, table_id, block_id, family, headers, hyp_cells, *, issued=True):
    return {
        "schema": "signed-table-hypothesis/v1",
        "document_id": doc, "table_id": table_id, "table_block_id": block_id,
        "table_title": "T", "family_id": family, "headers": headers,
        "validator_status": "issued" if issued else "partial_conflict",
        "hypothesis": {
            "schema": "table-structure-hypothesis/v1",
            "header_level_count": 1, "cells": hyp_cells, "semantic_merges": [],
        },
    }


def _read_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


class RoleAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _write_corpus(self, doc, table_id, block_id, family, headers, data_rows,
                      wrong_rows=(), issued=True):
        docdir = self.root / "corpus" / doc
        docdir.mkdir(parents=True, exist_ok=True)
        items = _matrix_cells(table_id, block_id, headers, data_rows)
        write_jsonl(docdir / "table_cell_items.jsonl", items)
        rec = _signed_record(
            doc, table_id, block_id, family, headers,
            _hypothesis_cells(len(headers), len(data_rows), wrong_rows),
            issued=issued,
        )
        write_jsonl(docdir / "table_structure_hypotheses.jsonl", [rec])
        return items

    def test_sample_only_issued_hypotheses_enter_frame_and_anchor_reuses_cell_coords(self):
        items = self._write_corpus(
            "docA", "TBL-000001", "BLK-000003", "parameter_matrix",
            ["Parameter", "Value", "Unit"],
            [("Voltage", "230", "V"), ("Frequency", "50", "Hz")],
            wrong_rows=(1,),  # one wrong data row
        )
        # Add a non-issued record that MUST be excluded from the frame.
        non_issued = self.root / "corpus" / "docA"
        existing = _read_jsonl(non_issued / "table_structure_hypotheses.jsonl")[0]
        write_jsonl(non_issued / "table_structure_hypotheses.jsonl", [
            existing,
            _signed_record("docA", "TBL-000099", "BLK-000099", "parameter_matrix",
                           ["X"], [], issued=False),
        ])
        ws = self.root / "wk.jsonl"
        rc = audit.main([
            "sample", "--corpus", str(self.root / "corpus"),
            "--per-family", "10", "--min-cells", "1", "--seed", "fixed",
            "--worksheet", str(ws),
        ])
        self.assertEqual(rc, 0)
        rows = _read_jsonl(ws)
        self.assertEqual(len(rows), 1)  # only the issued table
        row = rows[0]
        self.assertEqual(row["schema"], "role-audit-worksheet/v1")
        self.assertEqual(row["family_id"], "parameter_matrix")
        # Anchor reuses the cell-items coordinate system (block id + section).
        self.assertEqual(row["annotation_anchor"]["block_id"], "BLK-000003")
        self.assertEqual(row["annotation_anchor"]["section_path"], ["5.2", "Parameters"])
        # Every worksheet cell reuses the canonical cell_id + [row,col].
        seen_ids = {c["cell_id"] for c in row["cells"]}
        self.assertEqual(seen_ids, {it["cell_id"] for it in items})
        for c in row["cells"]:
            self.assertEqual(len(c["coordinate"]), 2)

    def test_record_and_evaluate_below_threshold_exits_2(self):
        # 2 data rows; row index 1 (first data row) mislabeled by hypothesis.
        self._write_corpus(
            "docA", "TBL-000001", "BLK-000003", "parameter_matrix",
            ["Parameter", "Value", "Unit"],
            [("Voltage", "230", "V"), ("Frequency", "50", "Hz")],
            wrong_rows=(1,),
        )
        ws = self.root / "wk.jsonl"
        audit.main(["sample", "--corpus", str(self.root / "corpus"),
                    "--per-family", "10", "--min-cells", "1", "--seed", "x",
                    "--worksheet", str(ws)])
        row = _read_jsonl(ws)[0]
        # Expert ground truth: HEADER_ROW = header, every data row = data.
        expert = self.root / "expert.jsonl"
        expert.write_text("\n".join(json.dumps({
            "cell_id": c["cell_id"],
            "expert_role": "header" if c["coordinate"][0] == HEADER_ROW else "data",
        }) for c in row["cells"]) + "\n", encoding="utf-8")
        verdicts = self.root / "v.jsonl"
        audit.main(["record", "--worksheet", str(ws), "--verdicts", str(verdicts),
                    "--expert-input", str(expert), "--reviewer", "t"])
        report = self.root / "r.json"
        rc = audit.main(["evaluate", "--worksheet", str(ws), "--verdicts", str(verdicts),
                         "--threshold", "0.95", "--report", str(report)])
        self.assertEqual(rc, 2)  # 3 wrong cells (one data row x 3 cols) < 0.95
        rep = json.loads(report.read_text(encoding="utf-8"))
        fam = rep["families"][0]
        self.assertEqual(fam["family_id"], "parameter_matrix")
        self.assertFalse(fam["meets_threshold"])
        self.assertEqual(fam["cells_wrong"], 3)

    def test_evaluate_meets_threshold_exits_0(self):
        # Hypothesis is fully correct (no wrong rows).
        self._write_corpus(
            "docA", "TBL-000001", "BLK-000003", "parameter_matrix",
            ["Parameter", "Value", "Unit"],
            [("Voltage", "230", "V"), ("Frequency", "50", "Hz")],
            wrong_rows=(),
        )
        ws = self.root / "wk.jsonl"
        audit.main(["sample", "--corpus", str(self.root / "corpus"),
                    "--per-family", "10", "--min-cells", "1", "--seed", "x",
                    "--worksheet", str(ws)])
        row = _read_jsonl(ws)[0]
        expert = self.root / "expert.jsonl"
        expert.write_text("\n".join(json.dumps({
            "cell_id": c["cell_id"],
            "expert_role": "header" if c["coordinate"][0] == HEADER_ROW else "data",
        }) for c in row["cells"]) + "\n", encoding="utf-8")
        verdicts = self.root / "v.jsonl"
        audit.main(["record", "--worksheet", str(ws), "--verdicts", str(verdicts),
                    "--expert-input", str(expert)])
        report = self.root / "r.json"
        rc = audit.main(["evaluate", "--worksheet", str(ws), "--verdicts", str(verdicts),
                         "--threshold", "0.95", "--report", str(report)])
        self.assertEqual(rc, 0)
        rep = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(rep["decision"], "pass")
        self.assertTrue(rep["families"][0]["meets_threshold"])

    def test_per_family_no_cross_family_averaging(self):
        # parameter_matrix fully correct, obis_object fully wrong. Report must
        # list BOTH families separately; decision fails because one family < 0.95.
        self._write_corpus(
            "docA", "TBL-A", "BLK-A", "parameter_matrix",
            ["P", "V"], [("a", "1"), ("b", "2")], wrong_rows=(),
        )
        self._write_corpus(
            "docB", "TBL-B", "BLK-B", "obis_object",
            ["OBIS", "Meaning"], [("x", "y"), ("z", "w")], wrong_rows=(1, 2),
        )
        ws = self.root / "wk.jsonl"
        audit.main(["sample", "--corpus", str(self.root / "corpus"),
                    "--per-family", "10", "--min-cells", "1", "--seed", "x",
                    "--worksheet", str(ws)])
        # Expert ground truth per cell.
        truth = []
        for r in _read_jsonl(ws):
            for c in r["cells"]:
                truth.append({"cell_id": c["cell_id"],
                              "expert_role": "header" if c["coordinate"][0] == HEADER_ROW else "data"})
        expert = self.root / "expert.jsonl"
        expert.write_text("\n".join(json.dumps(t) for t in truth) + "\n", encoding="utf-8")
        verdicts = self.root / "v.jsonl"
        audit.main(["record", "--worksheet", str(ws), "--verdicts", str(verdicts),
                    "--expert-input", str(expert)])
        report = self.root / "r.json"
        rc = audit.main(["evaluate", "--worksheet", str(ws), "--verdicts", str(verdicts),
                         "--threshold", "0.95", "--report", str(report)])
        self.assertEqual(rc, 2)
        rep = json.loads(report.read_text(encoding="utf-8"))
        families = {f["family_id"]: f for f in rep["families"]}
        self.assertIn("parameter_matrix", families)
        self.assertIn("obis_object", families)
        self.assertTrue(families["parameter_matrix"]["meets_threshold"])
        self.assertFalse(families["obis_object"]["meets_threshold"])
        # 禁止跨族平均：obis 0% 不能被 parameter 100% 掩盖——both reported separately.
        self.assertEqual(rep["failing_families"], ["obis_object"])

    def test_evaluate_rejects_forged_correct_boolean_exits_2(self):
        """S1-9：evaluate 不得信任 verdicts 里预固化的 ``correct`` 布尔。

        伪造场景：工作单假设角色为 data；verdicts 文件手填 ``expert_role="header"``（与假设
        不符）却把 ``correct: true`` 一起固化。旧实现读 ``cv["correct"]`` 直接采信→伪造通过
        门禁。修复后 evaluate 必须用 verdicts 的 ``expert_role`` 与工作单的
        ``hypothesized_role`` **重算** correct，伪造被拒（exit 2）。
        """
        # 工作单：假设全对（header 行=header，data 行=data）
        self._write_corpus(
            "docA", "TBL-000001", "BLK-000003", "parameter_matrix",
            ["P", "V"], [("a", "1"), ("b", "2")], wrong_rows=(),
        )
        ws = self.root / "wk.jsonl"
        audit.main(["sample", "--corpus", str(self.root / "corpus"),
                    "--per-family", "10", "--min-cells", "1", "--seed", "x",
                    "--worksheet", str(ws)])
        row = _read_jsonl(ws)[0]

        # 伪造 verdicts：data 行的 expert_role 填成 header（错），但 correct 手填 true
        forged_cells = []
        for c in row["cells"]:
            if c["coordinate"][0] == HEADER_ROW:
                forged_cells.append({**c, "expert_role": "header", "correct": True})  # 真 correct
            else:
                forged_cells.append({**c, "expert_role": "header", "correct": True})  # 伪造 correct
        verdicts = self.root / "v.jsonl"
        write_jsonl(verdicts, [{
            "schema": "role-audit-verdict/v1",
            "document_id": row["document_id"],
            "table_id": row["table_id"],
            "family_id": row["family_id"],
            "reviewer": "forger",
            "cell_verdicts": forged_cells,
            "merge_group_verdicts": [],
        }])
        report = self.root / "r.json"
        rc = audit.main(["evaluate", "--worksheet", str(ws), "--verdicts", str(verdicts),
                         "--threshold", "0.95", "--report", str(report)])
        # 重算后 data 行全错（expert_role=header ≠ 假设 data）→ 族准确率 < 阈值 → exit 2
        self.assertEqual(rc, 2)
        rep = json.loads(report.read_text(encoding="utf-8"))
        fam = rep["families"][0]
        self.assertGreater(fam["cells_wrong"], 0)
        self.assertFalse(fam["meets_threshold"])

    def test_evaluate_family_id_taken_from_worksheet_not_verdict(self):
        """S1-9：family_id 以抽样框（工作单）为准，不信 verdicts 自带值。

        伪造场景：工作单族=obis_object（实为失败族），verdicts 自报 family_id=
        parameter_matrix（企图混入通过族平均掩盖）。修复后以工作单族归类，obis_object 仍按
        自身准确率裁决。
        """
        # 工作单：obis_object 全错（wrong_rows 全标 header，实为 data）
        self._write_corpus(
            "docA", "TBL-A", "BLK-A", "obis_object",
            ["OBIS", "Meaning"], [("x", "y"), ("z", "w")], wrong_rows=(1, 2),
        )
        ws = self.root / "wk.jsonl"
        audit.main(["sample", "--corpus", str(self.root / "corpus"),
                    "--per-family", "10", "--min-cells", "1", "--seed", "x",
                    "--worksheet", str(ws)])
        row = _read_jsonl(ws)[0]
        # 专家真值：header 行=header，data 行=data（与假设 header 不符 → 全错）
        cells = []
        for c in row["cells"]:
            expert = "header" if c["coordinate"][0] == HEADER_ROW else "data"
            cells.append({**c, "expert_role": expert, "correct": True})  # correct 也伪造为 true
        verdicts = self.root / "v.jsonl"
        write_jsonl(verdicts, [{
            "schema": "role-audit-verdict/v1",
            "document_id": row["document_id"],
            "table_id": row["table_id"],
            "family_id": "parameter_matrix",  # 自报假族（工作单实为 obis_object）
            "reviewer": "forger",
            "cell_verdicts": cells,
            "merge_group_verdicts": [],
        }])
        report = self.root / "r.json"
        rc = audit.main(["evaluate", "--worksheet", str(ws), "--verdicts", str(verdicts),
                         "--threshold", "0.95", "--report", str(report)])
        self.assertEqual(rc, 2)
        rep = json.loads(report.read_text(encoding="utf-8"))
        families = {f["family_id"] for f in rep["families"]}
        # 以工作单为准：归入 obis_object（而非 verdicts 自报的 parameter_matrix）
        self.assertIn("obis_object", families)
        self.assertNotIn("parameter_matrix", families)

    def test_evaluate_no_judged_cells_exits_3(self):
        self._write_corpus(
            "docA", "TBL-000001", "BLK-000003", "parameter_matrix",
            ["P", "V"], [("a", "1")], wrong_rows=(),
        )
        ws = self.root / "wk.jsonl"
        audit.main(["sample", "--corpus", str(self.root / "corpus"),
                    "--per-family", "10", "--min-cells", "1", "--seed", "x",
                    "--worksheet", str(ws)])
        verdicts = self.root / "v.jsonl"
        # record with NO expert input → all blanks.
        audit.main(["record", "--worksheet", str(ws), "--verdicts", str(verdicts)])
        rc = audit.main(["evaluate", "--worksheet", str(ws), "--verdicts", str(verdicts),
                         "--threshold", "0.95"])
        self.assertEqual(rc, 3)

    def test_seed_reproducibility(self):
        self._write_corpus(
            "docA", "TBL-000001", "BLK-000003", "parameter_matrix",
            ["P", "V", "U"],
            [("a", "1", "x"), ("b", "2", "y"), ("c", "3", "z"), ("d", "4", "w")],
            wrong_rows=(),
        )
        ws1 = self.root / "wk1.jsonl"
        ws2 = self.root / "wk2.jsonl"
        for ws in (ws1, ws2):
            audit.main(["sample", "--corpus", str(self.root / "corpus"),
                        "--per-family", "2", "--min-cells", "1", "--seed", "2026-08-05",
                        "--worksheet", str(ws)])
        self.assertEqual(_read_jsonl(ws1), _read_jsonl(ws2))


if __name__ == "__main__":
    unittest.main()
