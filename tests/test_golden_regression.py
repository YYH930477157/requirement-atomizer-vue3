"""最小 docx 全新管线稳定性钉（原 ABNT golden 回归已退役）。

ABNT 基线测试已于 2026-09-09 退役（用户裁定）：ABNT 文档回归"普通需求文件"
定位，不再是金标。决策脉络见 f143734（WS0/ABNT 轨道关账——门禁目的被产品
演进绕过：功能轨已是生产默认，A/B/C 匹配层裁定撤销）。冻结基线文件
golden_sets/abnt_nbr_16968_v5/ 与本机 out/abnt_nbr_16968_atomizer_v5/
按"资产留档"保留，不再进任何门禁；多文档回归主体是
tests/test_regression_portfolio.py（四类文档病理 fixture、12 钉）。

本模块保留 FreshPipelineRegressionTests：不依赖 out/ 基线的最小 docx
全新管线行为钉（块计数/表格/原子候选形状），随仓库随处可跑。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import atomize
from docx import Document
from io_utils import read_jsonl


ROOT = Path(__file__).resolve().parents[1]


class FreshPipelineRegressionTests(unittest.TestCase):
    def test_minimal_docx_pipeline_generates_stable_outputs(self) -> None:
        self.assertTrue(hasattr(atomize, "run_atomizer_pipeline"))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "minimal_standard.docx"
            out_dir = tmp_path / "out"
            self.write_minimal_docx(input_path)

            manifest = atomize.run_atomizer_pipeline(input_path, out_dir, chunk_chars=800)

            atomic = read_jsonl(out_dir / "atomic_requirements.jsonl")
            quality = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["counts"]["blocks"], 4)
        self.assertEqual(manifest["counts"]["table_items"], 1)
        self.assertEqual(manifest["counts"]["atomic_requirements"], 2)
        self.assertEqual(manifest["counts"]["llm_tasks"], 1)
        self.assertEqual(
            [row["requirement_type"] for row in atomic],
            ["communication", "capability_matrix"],
        )
        self.assertEqual(
            [row["requirement"] for row in atomic],
            [
                "The meter shall support xDLMS GET service.",
                "Public customer shall support xDLMS Service: GET.",
            ],
        )
        self.assertEqual(atomic[0]["req_id"], "AREQ-000001")
        self.assertEqual(atomic[1]["req_id"], "AREQ-000002")
        self.assertRegex(atomic[0]["stable_req_id"], r"^SREQ-[0-9A-F]{16}$")
        self.assertRegex(atomic[1]["stable_req_id"], r"^SREQ-[0-9A-F]{16}$")
        self.assertEqual(quality["coverage"]["body_table_candidate_ratio"], 1.0)
        self.assertEqual(quality["coverage"]["domain_table_candidate_ratio"], 0.0)

    def write_minimal_docx(self, path: Path) -> None:
        document = Document()
        document.add_heading("Scope", level=1)
        document.add_paragraph("The meter shall support xDLMS GET service.")
        document.add_paragraph("Table 1 - xDLMS services")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Customer application process"
        table.cell(0, 1).text = "xDLMS Service: GET"
        table.cell(1, 0).text = "Public customer"
        table.cell(1, 1).text = "X"
        document.save(path)


if __name__ == "__main__":
    unittest.main()
