"""meter_profile 推断回归：表计类型 + 目标标准的确定性推断。

锁定 P1+P3 修复：燃气表不再被写死成 electric / DLMS/COSEM/ABNT。
判据确定性（文件名 > 正文频次 > 兜底 multi），不依赖 LLM。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from meter_profile import infer_meter_profile, infer_meter_type, infer_target_standards


def _write_atomizer_output(out: Path, *, input_name: str, blocks: list[tuple[str, str]] | None = None) -> None:
    """造一份最小 atomizer 输出（manifest + blocks.jsonl）。"""
    (out / "manifest.json").write_text(
        json.dumps({"input": input_name, "counts": {"blocks": len(blocks or [])}}), encoding="utf-8")
    lines = []
    for bid, text in (blocks or []):
        lines.append(json.dumps({"block_id": bid, "text": text}, ensure_ascii=False))
    (out / "blocks.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


class InferMeterTypeTests(unittest.TestCase):
    def test_gas_meter_from_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_atomizer_output(out, input_name="EN 16314 Gas meter-Additional functionalities.pdf")
            self.assertEqual(infer_meter_type(out), "gas")

    def test_water_meter_from_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_atomizer_output(out, input_name="ISO 4064 Water meter specification.docx")
            self.assertEqual(infer_meter_type(out), "water")

    def test_electric_meter_from_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_atomizer_output(out, input_name="ABNT NBR 16968 electricity meter profile.docx")
            self.assertEqual(infer_meter_type(out), "electric")

    def test_falls_back_to_multi_when_no_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_atomizer_output(out, input_name="generic_standard.pdf", blocks=[("B1", "general requirements")])
            self.assertEqual(infer_meter_type(out), "multi")

    def test_infer_from_body_frequency_when_filename_neutral(self) -> None:
        """文件名无表种词时，正文术语频次占优可定（gas meter 出现多次）。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            blocks = [("B" + str(i), "The gas meter shall measure gas volume.") for i in range(5)]
            _write_atomizer_output(out, input_name="standard.pdf", blocks=blocks)
            self.assertEqual(infer_meter_type(out), "gas")


class InferTargetStandardsTests(unittest.TestCase):
    def test_extracts_standard_from_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_atomizer_output(out, input_name="EN 16314：2013 Gas meter.pdf")
            standards = infer_target_standards(out)
            self.assertIn("EN 16314", standards)

    def test_extracts_iec_standard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_atomizer_output(out, input_name="IEC 62056-5-3 application layer.docx")
            standards = infer_target_standards(out)
            self.assertTrue(any("IEC 62056" in s for s in standards))

    def test_empty_when_no_standard_in_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_atomizer_output(out, input_name="internal notes.pdf", blocks=[("B1", "some text")])
            # 文件名无标准号 + 无 normative references 节 → 空（不再写死电表标准）
            self.assertEqual(infer_target_standards(out), [])


class InferMeterProfileTests(unittest.TestCase):
    def test_gas_profile_combined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_atomizer_output(out, input_name="EN 16314 Gas meter.pdf")
            profile = infer_meter_profile(out)
            self.assertEqual(profile["meter_type"], "gas")
            self.assertIn("EN 16314", profile["target_standards"])


if __name__ == "__main__":
    unittest.main()
