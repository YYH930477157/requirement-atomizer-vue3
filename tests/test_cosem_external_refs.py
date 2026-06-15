from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cosem_external_refs as cer


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def write_fixture(out_dir: Path) -> None:
    write_jsonl(out_dir / "blocks.jsonl", [
        # 正文引用 5-3（normative）
        {"block_id": "BLK-1", "type": "paragraph", "section_path": ["Architecture"],
         "text": "The application layer shall follow IEC 62056-5-3 for GET/SET services."},
        # Normative References 节：给出 5-3 与 6-1 的权威标题
        {"block_id": "BLK-2", "type": "heading", "section_path": ["Normative references"],
         "text": "IEC 62056-5-3, Electricity metering - Data exchange - Part 5-3: COSEM application layer"},
        {"block_id": "BLK-3", "type": "heading", "section_path": ["Normative references"],
         "text": "IEC 62056-6-1, Electricity metering - Data exchange - Part 6-1: OBIS object identification system"},
        # 噪声行：不含标准编号，不应误报
        {"block_id": "BLK-4", "type": "paragraph", "section_path": ["Introduction"],
         "text": "Numbers in brackets refer to the Bibliography."},
    ])
    write_jsonl(out_dir / "atomic_requirements.jsonl", [
        {"stable_req_id": "SREQ-1", "requirement_type": "communication", "section_path": ["Architecture"],
         "requirement": "The meter shall implement HDLC according to ISO/IEC 13239."},
    ])
    write_jsonl(out_dir / "table_items.jsonl", [
        {"item_id": "TBL-1-R1", "section_path": ["Architecture"],
         "fields": {"Note": "Transport per IEC 62056-4-7."}},
    ])


class CosemExternalRefsTests(unittest.TestCase):
    def test_finds_specs_and_classifies_materiality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = cer.build_external_refs(out)

        by_id = {e["spec_id"]: e for e in model["references"]}
        # 5 个不同的编号：62056-5-3 / 62056-6-1 / 13239 / 62056-4-7
        self.assertIn("IEC 62056-5-3", by_id)
        self.assertIn("ISO/IEC 13239", by_id)
        self.assertIn("IEC 62056-4-7", by_id)

        # 5-3 正文引用 → normative；标题取自 Normative References 节原文
        s53 = by_id["IEC 62056-5-3"]
        self.assertEqual(s53["materiality"], "normative")
        self.assertIn("COSEM application layer", s53["title"])
        self.assertEqual(s53["cited_by_requirements"], 0)
        self.assertEqual(s53["body_citations"], 1)

        # 13239 被真·需求引用 → cited_by_requirements 计数
        s13239 = by_id["ISO/IEC 13239"]
        self.assertEqual(s13239["materiality"], "normative")
        self.assertEqual(s13239["cited_by_requirements"], 1)

        # 4-7 仅在表格引用 → normative（正文引用）
        self.assertEqual(by_id["IEC 62056-4-7"]["materiality"], "normative")

        # 6-1 只在 Normative References 目录里出现 → listed_only
        s61 = by_id["IEC 62056-6-1"]
        self.assertEqual(s61["materiality"], "listed_only")
        self.assertTrue(s61["listed_in_references"])

    def test_dlms_ua_alias_only_for_canonical_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = cer.build_external_refs(out)
        by_id = {e["spec_id"]: e for e in model["references"]}
        self.assertIn("Green Book", by_id["IEC 62056-5-3"]["dlms_ua_note"])
        self.assertNotIn("dlms_ua_note", by_id["IEC 62056-4-7"])  # 非教科书级映射不附注

    def test_no_false_positive_on_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_jsonl(out / "blocks.jsonl", [
                {"block_id": "BLK-1", "type": "paragraph", "section_path": ["Scope"],
                 "text": "The meter shall store at least 90 days of load profile data."},
            ])
            write_jsonl(out / "atomic_requirements.jsonl", [])
            write_jsonl(out / "table_items.jsonl", [])
            model = cer.build_external_refs(out)
        self.assertEqual(model["counts"]["specs"], 0)

    def test_document_self_reference_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            # 文档自身号在正文反复出现，但应被排除（按基础号匹配：文件名 -2022 ↔ 正文 :2022）
            (out / "blocks.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
                {"block_id": "BLK-1", "type": "paragraph", "section_path": ["Scope"],
                 "text": "This Standard ABNT NBR 16968:2022 applies. See IEC 62056-5-3."},
                {"block_id": "BLK-2", "type": "paragraph", "section_path": ["Architecture"],
                 "text": "Per ABNT NBR 16968:2022 the meter shall expose objects."},
            ]) + "\n", encoding="utf-8")
            (out / "manifest.json").write_text(
                json.dumps({"input": r"C:\docs\Appendix 9-ABNT NBR 16968-2022 EN.docx"}, ensure_ascii=False),
                encoding="utf-8")
            model = cer.build_external_refs(out)

        ids = {e["spec_id"] for e in model["references"]}
        self.assertNotIn("ABNT NBR 16968", ids)               # 自引用已排除
        self.assertIn("ABNT NBR 16968", model["excluded_self_references"])
        self.assertIn("IEC 62056-5-3", ids)                   # 真外部规范保留
        self.assertGreaterEqual(model["counts"]["excluded_self_references"], 1)

    def test_render_markdown_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_fixture(out)
            model = cer.build_external_refs(out)
            written = cer.write_external_refs(out, model)
        self.assertIn("cosem_external_refs.json", written)
        self.assertIn("cosem_external_refs.md", written)


if __name__ == "__main__":
    unittest.main()
