"""Tests for tools/shadow_run.py (T4 / S3 全开关影子运行).

Self-proves the three deliverables:

* **T4-1 工具链** —— live 模式（合成 docx 跑两条路径）产出并排产物，确定性核字节稳定
  （CAS）、受保护编码零漂移、守恒闭合（stub 降级预期），decision=pass / exit 0；
  ``--baseline-roots`` 离线对比既有产物对（不重跑流水线）。
* **T4-2 合成演示** —— 合成 fixture 身份进报告，真实语料 ``real_corpus_pending=True`` 醒目。
* **T4-3 缺陷回归钩子** —— 三道 HARD 门注入失败各回归为测试（protected-encoding 漂移 /
  守恒未闭合 / 确定性核字节漂移），任一即 exit 2 停线；归因分类器逐模板钉死。

合成文档由 ``tests/docx_fixtures.write_synthetic_docx`` 生成（含 OBIS ``0-0:1.0.0.255`` 与
事件码 ``G1-SG10-E1`` 等受保护编码）。真实金标 / 未见过的语料本机没有，跑批 pending-human——
本套件不伪造真实语料对比结论。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_TOOLS = _REPO / "tools"
for _p in (_REPO, _TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import shadow_run as sr  # noqa: E402
from functional_extract import FUNCTIONAL_REQUIREMENTS_FILENAME  # noqa: E402

# 复用 tests 包内的合成 docx 生成器（与 test_extract_docx_e2e 同源 import 风格）。
from tests.docx_fixtures import write_synthetic_docx  # noqa: E402


def _seed_synthetic_docx(tmp: Path) -> Path:
    """生成一份明确的合成 fixture docx（身份 = 脚本生成、非真实语料）。"""
    docx = tmp / "synthetic_shadow_fixture.docx"
    write_synthetic_docx(docx)
    return docx


class _LivePairMixin:
    """共享一次 live 跑（合成 docx → old/new 产物对），各测试从副本注入。"""

    @classmethod
    def _build_live_pair(cls, tmp: Path) -> tuple[Path, Path, dict]:
        docx = _seed_synthetic_docx(tmp)
        old, new, meta = sr.run_live_pair(docx, tmp / "work", llm_route="stub")
        return old, new, meta


class LiveShadowRunTests(unittest.TestCase, _LivePairMixin):
    """T4-1：live 模式自证——两条路径并排产物 + 归因 + HARD 门。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="shadow_live_"))
        self.old, self.new, self.meta = self._build_live_pair(self.tmp)

    def test_deterministic_core_is_byte_stable(self):
        """CAS：开关翻动不污染确定性核——五件核心产物新旧逐字节一致。"""
        comp = sr.compare_outputs(self.old, self.new, run_meta=self.meta)
        self.assertTrue(comp["core_byte_stable"],
                        f"确定性核字节漂移: {comp['differences']}")
        preserved = {d["file"] for d in comp["differences"]
                     if d.get("template") == sr.TPL_EXPECTED_PRESERVED}
        self.assertEqual(preserved, set(sr.DETERMINISTIC_CORE_FILES))

    def test_protected_encoding_zero_drift(self):
        """受保护编码（OBIS / 事件号）在新路径确定性核里零丢失。"""
        comp = sr.compare_outputs(self.old, self.new, run_meta=self.meta)
        pe = comp["protected_encoding"]
        self.assertFalse(pe["drift"], f"编码漂移: lost={pe['codes_lost']}")
        self.assertGreater(pe["old_count"], 0)  # 合成 docx 含 OBIS
        self.assertEqual(pe["old_count"], pe["new_count"])

    def test_direct_extract_sidecar_is_expected_difference(self):
        """直抽开关 ON：functional_requirements.json 在新路径新增 = 预期差异（直抽粒度）。"""
        comp = sr.compare_outputs(self.old, self.new, run_meta=self.meta)
        fr_diffs = [d for d in comp["differences"]
                    if d["file"] == FUNCTIONAL_REQUIREMENTS_FILENAME]
        self.assertTrue(fr_diffs, "直抽产物应作为差异出现")
        d = fr_diffs[0]
        self.assertEqual(d["kind"], "added")
        self.assertEqual(d["attribution"], sr.ATTR_EXPECTED)
        self.assertEqual(d["template"], sr.TPL_DIRECT_EXTRACT)

    def test_stub_conservation_is_expected_degradation_not_hard_fail(self):
        """stub 直抽守恒：HARD 门必须放过——guards-v6 后 stub 产物可合法闭合。

        guards-v6 剥离 [TBL-NNNNNN] 表格标记伪影后，stub 确定性引句/数字基线在含表
        文档上不再被假失败卡死——闭合（functional_conservation_closed）与预期降级
        （functional_conservation_degraded_expected）都是合法 pass，绝不能 HARD 红灯。"""
        gates = sr.hard_gates(self.old, self.new,
                              sr.compare_outputs(self.old, self.new, run_meta=self.meta))
        self.assertEqual(gates["conservation_closed"]["status"], "pass")
        self.assertIn(gates["conservation_closed"]["reason"],
                      ("functional_conservation_degraded_expected",
                       "functional_conservation_closed"))

    def test_decision_pass_and_exit_zero(self):
        """整体裁决 pass，CLI exit 0（HARD 门全绿、无 defect/unexplained）。"""
        rc = sr.main([
            "--input", str(_seed_synthetic_docx(Path(tempfile.mkdtemp()))),
            "--work-dir", str(self.tmp / "work2"),
            "--report", str(self.tmp / "report.json"),
            "--human", str(self.tmp / "report.md"),
        ])
        self.assertEqual(rc, 0)
        report = json.loads((self.tmp / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["decision"], "pass")
        self.assertEqual(report["summary"]["attribution"].get(sr.ATTR_DEFECT, 0), 0)
        self.assertEqual(report["summary"]["attribution"].get(sr.ATTR_UNEXPLAINED, 0), 0)

    def test_fixture_identity_and_real_corpus_pending_marked(self):
        """T4-2：合成 fixture 身份进报告，真实语料 pending=True 醒目标注。"""
        report_path = self.tmp / "rep.json"
        sr.main(["--input", str(_seed_synthetic_docx(Path(tempfile.mkdtemp()))),
                 "--work-dir", str(self.tmp / "work3"),
                 "--report", str(report_path)])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["fixture_identity"]["kind"], "synthetic_fixture")
        self.assertTrue(report["fixture_identity"]["sha256"].startswith("sha256:"))
        self.assertTrue(report["real_corpus_pending"],
                        "合成 fixture 必须如实标 real_corpus_pending=True")


class OfflineBaselineRootsTests(unittest.TestCase, _LivePairMixin):
    """T4-3：``--baseline-roots`` 离线对比模式（不重跑流水线）。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="shadow_offline_"))
        self.old, self.new, self.meta = self._build_live_pair(self.tmp)

    def test_offline_compare_matches_live_decision(self):
        """离线对比既有产物对 = live 决策（pass，同归因分布）。"""
        rc = sr.main(["--baseline-roots", str(self.old), str(self.new),
                      "--report", str(self.tmp / "off.json")])
        self.assertEqual(rc, 0)
        report = json.loads((self.tmp / "off.json").read_text(encoding="utf-8"))
        self.assertEqual(report["mode"], "baseline-roots")
        self.assertEqual(report["summary"]["decision"], "pass")

    def test_offline_real_corpus_flag_is_opt_in(self):
        """--real-corpus 显式声明才把 real_corpus_pending 翻 False（默认 pending=True）。"""
        import io
        import contextlib

        with contextlib.redirect_stdout(io.StringIO()) as buf_default:
            rc_default = sr.main(["--baseline-roots", str(self.old), str(self.new)])
        env_default = json.loads(buf_default.getvalue())
        self.assertTrue(env_default["real_corpus_pending"], "默认必须 pending=True")

        with contextlib.redirect_stdout(io.StringIO()) as buf_real:
            rc_real = sr.main(["--baseline-roots", str(self.old), str(self.new), "--real-corpus"])
        env_real = json.loads(buf_real.getvalue())
        self.assertFalse(env_real["real_corpus_pending"], "--real-corpus 翻 False")
        self.assertEqual(rc_default, 0)
        self.assertEqual(rc_real, 0)

    def test_offline_rejects_missing_root_as_input_error(self):
        """不存在的 baseline root → input_error / exit 2。"""
        rc = sr.main(["--baseline-roots", str(self.tmp / "nope"), str(self.new)])
        self.assertEqual(rc, 2)


class HardGateInjectionTests(unittest.TestCase, _LivePairMixin):
    """T4-3 缺陷回归钩子：三道 HARD 门注入失败各 exit 2 停线。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="shadow_inject_"))
        self.old, self.new, self.meta = self._build_live_pair(self.tmp)

    def test_protected_encoding_drift_stops_line(self):
        """受保护编码漂移：从新路径 atomic_requirements 抹掉仅在它出现的 G1-SG10-E1 → exit 2。"""
        corrupt = self.tmp / "drift_new"
        shutil.copytree(self.new, corrupt)
        ar = corrupt / "atomic_requirements.jsonl"
        ar.write_text(
            ar.read_text(encoding="utf-8").replace("G1-SG10-E1", "EVENT-REMOVED"),
            encoding="utf-8",
        )
        rc = sr.main(["--baseline-roots", str(self.old), str(corrupt),
                      "--report", str(self.tmp / "drift.json")])
        self.assertEqual(rc, 2)
        report = json.loads((self.tmp / "drift.json").read_text(encoding="utf-8"))
        self.assertEqual(report["hard_gates"]["protected_encoding_zero_drift"]["status"], "fail")
        self.assertIn("G1-SG10-E1",
                      report["summary"]["protected_encoding"]["codes_lost"])

    def test_authoritative_conservation_not_closed_stops_line(self):
        """守恒门：权威 route（openai_compatible）产物守恒未闭合 → exit 2。

        stub 产物未闭合是预期降级（见 LiveShadowRunTests）；本测试把同一产物改标权威 route
        再破坏守恒，证明真实 route 产物未闭合确实触发 HARD 红灯（= 直抽上线时的回归门）。
        """
        corrupt = self.tmp / "conservation_new"
        shutil.copytree(self.new, corrupt)
        frp = corrupt / FUNCTIONAL_REQUIREMENTS_FILENAME
        payload = json.loads(frp.read_text(encoding="utf-8"))
        payload["route"] = "openai_compatible"  # 标权威：未闭合不再是预期降级
        cons = payload.setdefault("conservation", {})
        cons["ok"] = False
        cons["missing_block_ids"] = ["BLK-FAKE-MISSING"]
        frp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rc = sr.main(["--baseline-roots", str(self.old), str(corrupt),
                      "--report", str(self.tmp / "cons.json")])
        self.assertEqual(rc, 2)
        report = json.loads((self.tmp / "cons.json").read_text(encoding="utf-8"))
        self.assertEqual(report["hard_gates"]["conservation_closed"]["status"], "fail")
        self.assertEqual(report["hard_gates"]["conservation_closed"]["reason"],
                         "functional_conservation_not_closed")

    def test_deterministic_core_byte_drift_stops_line(self):
        """CAS：确定性核（blocks）在新路径下逐字节漂移 → exit 2。"""
        corrupt = self.tmp / "cas_new"
        shutil.copytree(self.new, corrupt)
        bp = corrupt / "blocks.jsonl"
        bp.write_text(bp.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        rc = sr.main(["--baseline-roots", str(self.old), str(corrupt),
                      "--report", str(self.tmp / "cas.json")])
        self.assertEqual(rc, 2)
        report = json.loads((self.tmp / "cas.json").read_text(encoding="utf-8"))
        self.assertEqual(report["hard_gates"]["deterministic_core_byte_stable"]["status"], "fail")

    def test_core_product_removed_is_defect(self):
        """确定性核产物在新路径消失 = defect（非 unexplained），exit 2。"""
        corrupt = self.tmp / "removed_new"
        shutil.copytree(self.new, corrupt)
        (corrupt / "atomic_requirements.jsonl").unlink()
        rc = sr.main(["--baseline-roots", str(self.old), str(corrupt)])
        self.assertEqual(rc, 2)


class AttributionClassifierTests(unittest.TestCase):
    """T4-1：归因分类器逐模板钉死（added / mutated / removed → template + attribution）。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="shadow_attr_"))
        self.old = self.tmp / "old"; self.old.mkdir()
        self.new = self.tmp / "new"; self.new.mkdir()
        self.meta = {"dual_track_degraded_no_llm": True}

    def _diff(self, filename: str, kind: str) -> dict:
        return next(
            d for d in sr.compare_outputs(self.old, self.new, run_meta=self.meta)["differences"]
            if d["file"] == filename and d["kind"] == kind
        )

    def _write(self, root: Path, filename: str, content: str) -> None:
        (root / filename).write_text(content, encoding="utf-8")

    def test_added_functional_requirements_is_direct_extract(self):
        self._write(self.new, FUNCTIONAL_REQUIREMENTS_FILENAME, '{"items":[]}'),
        d = self._diff(FUNCTIONAL_REQUIREMENTS_FILENAME, "added")
        self.assertEqual(d["template"], sr.TPL_DIRECT_EXTRACT)
        self.assertEqual(d["attribution"], sr.ATTR_EXPECTED)

    def test_added_hypotheses_is_dual_track_header(self):
        self._write(self.new, sr.TABLE_HYPOTHESES_FILE, "")
        d = self._diff(sr.TABLE_HYPOTHESES_FILE, "added")
        self.assertEqual(d["template"], sr.TPL_DUAL_TRACK_HEADER)
        self.assertEqual(d["attribution"], sr.ATTR_EXPECTED)

    def test_added_cost_report_is_budget(self):
        self._write(self.new, sr.COST_REPORT_FILE, "{}")
        d = self._diff(sr.COST_REPORT_FILE, "added")
        self.assertEqual(d["template"], sr.TPL_BUDGET_COST_REPORT)

    def test_added_sampling_summary_is_sampling_verifier(self):
        self._write(self.new, sr.CLAIM_SAMPLING_SUMMARY_FILE, "{}")
        d = self._diff(sr.CLAIM_SAMPLING_SUMMARY_FILE, "added")
        self.assertEqual(d["template"], sr.TPL_SAMPLING_VERIFIER)

    def test_added_unexpected_file_is_unexplained(self):
        self._write(self.new, "mystery_artifact.jsonl", "{}")
        d = self._diff("mystery_artifact.jsonl", "added")
        self.assertEqual(d["attribution"], sr.ATTR_UNEXPLAINED)
        self.assertEqual(d["template"], "")

    def test_removed_core_file_is_defect(self):
        # old 有 atomic_requirements、new 没有 → removed/defect
        self._write(self.old, "atomic_requirements.jsonl", "{}")
        d = self._diff("atomic_requirements.jsonl", "removed")
        self.assertEqual(d["attribution"], sr.ATTR_DEFECT)

    def test_mutated_core_file_is_unexplained(self):
        # 确定性核两路都在但字节不同 → unexplained（开关污染确定性路径）
        self._write(self.old, "blocks.jsonl", "A")
        self._write(self.new, "blocks.jsonl", "B")
        d = self._diff("blocks.jsonl", "mutated")
        self.assertEqual(d["attribution"], sr.ATTR_UNEXPLAINED)

    def test_mutated_manifest_with_same_counts_is_preserved(self):
        """manifest 仅运行身份字段（generated_at/output_dir）不同 → 内容一致 = preserved。"""
        base_counts = '{"counts": {"blocks": 1}, "files": {"blocks": "blocks.jsonl"}}'
        self._write(self.old, "manifest.json",
                    json.dumps({"generated_at": "t1", "output_dir": "/old",
                                "counts": {"blocks": 1}, "files": {"blocks": "blocks.jsonl"}}))
        self._write(self.new, "manifest.json",
                    json.dumps({"generated_at": "t2", "output_dir": "/new",
                                "counts": {"blocks": 1}, "files": {"blocks": "blocks.jsonl"}}))
        comp = sr.compare_outputs(self.old, self.new, run_meta=self.meta)
        manifest_diffs = [d for d in comp["differences"] if d["file"] == "manifest.json"]
        self.assertEqual(manifest_diffs, [], "仅身份字段不同的 manifest 不应计为差异")


class ReportContractTests(unittest.TestCase, _LivePairMixin):
    """报告契约：schema、人读摘要、HARD 门汇总结构。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="shadow_report_"))
        self.old, self.new, self.meta = self._build_live_pair(self.tmp)

    def test_report_schema_and_hard_gate_structure(self):
        comp = sr.compare_outputs(self.old, self.new, run_meta=self.meta)
        gates = sr.hard_gates(self.old, self.new, comp)
        report = sr.build_report(
            comp, gates, old_root=self.old, new_root=self.new,
            run_meta=self.meta, fixture_identity={"kind": "synthetic_fixture"},
            real_corpus_pending=True, mode="live",
        )
        self.assertEqual(report["schema"], sr.SHADOW_REPORT_SCHEMA)
        self.assertEqual(report["tool"], sr.SHADOW_TOOL)
        for gate_name in ("protected_encoding_zero_drift", "conservation_closed",
                          "deterministic_core_byte_stable"):
            self.assertIn(gate_name, report["hard_gates"])
            self.assertIn(report["hard_gates"][gate_name]["status"], ("pass", "fail"))
        self.assertTrue(report["hard_gates"]["all_pass"])

    def test_human_summary_renders_decision_and_fixture(self):
        comp = sr.compare_outputs(self.old, self.new, run_meta=self.meta)
        gates = sr.hard_gates(self.old, self.new, comp)
        report = sr.build_report(
            comp, gates, old_root=self.old, new_root=self.new, run_meta=self.meta,
            fixture_identity={"kind": "synthetic_fixture", "name": "x.docx"},
            real_corpus_pending=True, mode="live",
        )
        text = sr.render_human_summary(report)
        self.assertIn("影子运行报告", text)
        self.assertIn("PASS", text)
        self.assertIn("真实语料 pending: **True**", text)
        self.assertIn("fixture 身份", text)


class InputValidationTests(unittest.TestCase):
    """退出码对齐 cli-contract：0/2/3/4。"""

    def test_missing_input_mode_is_input_error_exit2(self):
        rc = sr.main([])  # argparse mutually exclusive required → SystemExit(2)
        self.assertEqual(rc, 2)

    def test_unsupported_format_is_input_error_exit2(self):
        bad = Path(tempfile.mkdtemp()) / "x.txt"
        bad.write_text("nope", encoding="utf-8")
        rc = sr.main(["--input", str(bad), "--work-dir", str(bad.parent / "w")])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
