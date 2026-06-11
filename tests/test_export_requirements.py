from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from export_requirements import export_requirements, read_jsonl


class ExportRequirementsTests(unittest.TestCase):
    def test_export_filters_by_review_status_and_joins_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_jsonl(
                out_dir / "atomic_requirements.jsonl",
                [
                    {
                        "req_id": "AREQ-1",
                        "stable_req_id": "SREQ-1",
                        "requirement_type": "communication",
                        "domain": "communication_profile",
                        "object": "Meter",
                        "requirement": "The meter shall support xDLMS GET service.",
                        "condition": None,
                        "verification_method": "test",
                        "confidence": 0.68,
                        "ambiguity": False,
                        "source_refs": ["BLK-1"],
                        "section_path": ["Scope"],
                    },
                    {
                        "req_id": "AREQ-2",
                        "stable_req_id": "SREQ-2",
                        "requirement_type": "security",
                        "domain": "security_policy",
                        "object": "Association",
                        "requirement": "Associations shall use HLS.",
                        "condition": "When remote access is used.",
                        "verification_method": "configuration_check",
                        "confidence": 0.9,
                        "ambiguity": False,
                        "source_refs": ["BLK-2"],
                        "section_path": ["Security"],
                    },
                ],
            )
            write_jsonl(
                out_dir / "review_states.jsonl",
                [
                    {"requirement_id": "SREQ-1", "status": "expert_pending"},
                    {"requirement_id": "SREQ-2", "status": "accepted"},
                ],
            )

            exports = export_requirements(out_dir, formats=["csv", "md"], status="accepted")

            csv_path = out_dir / "requirements_export.csv"
            md_path = out_dir / "requirements_export.md"
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            md_text = md_path.read_text(encoding="utf-8")

        self.assertEqual(exports, ["requirements_export.csv", "requirements_export.md"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["req_id"], "AREQ-2")
        self.assertEqual(rows[0]["review_status"], "accepted")
        self.assertEqual(rows[0]["source_refs"], "BLK-2")
        self.assertIn("## security", md_text)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    unittest.main()
