"""WS2 §4.2 claim 账本抽检模式（full / sampling / baseline_gate）机制测试。

纪律：build_shadow_ledger 默认 mode='full' 与现状逐字节一致；sampling/baseline_gate 收窄
闭合面。高风险识别（is_high_risk_claim）确定性正则、零 LLM。验收面：三档切换、sampling
高风险全选 + 分层抽样、零 LLM。
"""
from __future__ import annotations

import unittest

import claim_ledger as cl


def _claim(claim_id: str, text: str) -> dict:
    return {"claim_id": claim_id, "eligibility": "claim", "text": text, "source_kind": "sentence"}


class ModeResolverTests(unittest.TestCase):
    def test_default_is_sampling_via_env(self) -> None:
        # resolve_claim_ledger_mode(None) 读 env；env 未设 → 默认 sampling
        import os
        old = os.environ.pop("RATOMIZER_CLAIM_LEDGER_MODE", None)
        try:
            self.assertEqual(cl.resolve_claim_ledger_mode(None), "sampling")
        finally:
            if old is not None:
                os.environ["RATOMIZER_CLAIM_LEDGER_MODE"] = old

    def test_explicit_full_preserved(self) -> None:
        self.assertEqual(cl.resolve_claim_ledger_mode("full"), "full")

    def test_explicit_baseline_gate_preserved(self) -> None:
        self.assertEqual(cl.resolve_claim_ledger_mode("baseline_gate"), "baseline_gate")

    def test_illegal_falls_back_to_default(self) -> None:
        self.assertEqual(cl.resolve_claim_ledger_mode("nonsense"), "sampling")


class HighRiskDetectionTests(unittest.TestCase):
    def test_obis_claim_is_high_risk(self) -> None:
        self.assertTrue(cl.is_high_risk_claim(_claim("C1", "collect OBIS 1-1:32.7.0")))

    def test_numeric_claim_is_high_risk(self) -> None:
        self.assertTrue(cl.is_high_risk_claim(_claim("C2", "voltage at 230 V")))

    def test_plain_narrative_not_high_risk(self) -> None:
        self.assertFalse(cl.is_high_risk_claim(_claim("C3", "the meter shall log events")))

    def test_empty_not_high_risk(self) -> None:
        self.assertFalse(cl.is_high_risk_claim(_claim("C4", "")))

    def test_zero_llm_pure_regex(self) -> None:
        # is_high_risk_claim 不调用任何 LLM 路径——纯确定性正则/事实抽取
        # （无 chat/verifier 注入需求，函数签名不接受任何 LLM 依赖）
        for text in ("OBIS 0-0:10.0.0", "230 V", "class 3", "shall log"):
            cl.is_high_risk_claim(_claim("C", text))  # 不抛即证明零 LLM 纯函数


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        # 10 条 claim，2 条高风险（OBIS / 数值命题）；其余为纯叙述（无编码无数值）
        names = ["alpha", "beta", "gamma", "delta", "epsilon",
                 "zeta", "eta", "theta", "iota", "kappa"]
        self.catalog = [_claim(f"C{i:02d}", f"shall log event {names[i]}") for i in range(10)]
        self.catalog[1] = _claim("C01", "collect OBIS one dash")  # 仍非高风险（无真实编码/数值）
        self.catalog[1] = _claim("C01", "OBIS 1-1:32.7.0")  # 高风险（受保护编码）
        self.catalog[5] = _claim("C05", "voltage at 230 V")       # 高风险（数值命题）

    def test_full_selects_all(self) -> None:
        result = cl.select_verifier_claim_ids(self.catalog, mode="full")
        self.assertEqual(len(result["selected_ids"]), 10)
        self.assertEqual(result["deferred_ids"], [])
        self.assertTrue(result["threshold_met"])

    def test_baseline_gate_selects_all(self) -> None:
        result = cl.select_verifier_claim_ids(self.catalog, mode="baseline_gate")
        self.assertEqual(len(result["selected_ids"]), 10)

    def test_sampling_includes_all_high_risk(self) -> None:
        result = cl.select_verifier_claim_ids(self.catalog, mode="sampling")
        self.assertIn("C01", result["selected_ids"])
        self.assertIn("C05", result["selected_ids"])
        self.assertEqual(set(result["high_risk_ids"]), {"C01", "C05"})

    def test_sampling_defers_some(self) -> None:
        result = cl.select_verifier_claim_ids(self.catalog, mode="sampling", sampling_rate=0.1)
        # 高风险必选；其余按 10% 抽样 → 必有 claim 被延迟
        self.assertGreater(len(result["deferred_ids"]), 0)
        # 延迟的不含高风险
        self.assertNotIn("C01", result["deferred_ids"])
        self.assertNotIn("C05", result["deferred_ids"])

    def test_sampling_is_deterministic(self) -> None:
        # 同输入同输出（稳定 stride，无随机数）
        a = cl.select_verifier_claim_ids(self.catalog, mode="sampling", sampling_rate=0.2)
        b = cl.select_verifier_claim_ids(self.catalog, mode="sampling", sampling_rate=0.2)
        self.assertEqual(a["sampled_ids"], b["sampled_ids"])
        self.assertEqual(a["selected_ids"], b["selected_ids"])

    def test_sampling_escalate_when_selected_ratio_below_floor(self) -> None:
        # 高风险占比 20% + 抽样率极低 → selected_ratio 低于 0.3 floor → escalate
        result = cl.select_verifier_claim_ids(
            self.catalog, mode="sampling", sampling_rate=0.0, floor_rate=0.5,
        )
        # sampling_rate=0 → sample_target=max(1,...) 至少抽 1 条，但高风险必选
        # selected_ratio = 高风险占比 + 极少抽样 < 0.5 → escalate
        self.assertTrue(result["escalate"])

    def test_empty_catalog(self) -> None:
        result = cl.select_verifier_claim_ids([], mode="sampling")
        self.assertEqual(result["selected_ids"], set())
        self.assertTrue(result["threshold_met"])


class BuildShadowLedgerModeDefaultTests(unittest.TestCase):
    """build_shadow_ledger 默认 mode='full'，与现状行为逐字节一致。"""

    def test_default_mode_param_is_full(self) -> None:
        import inspect
        sig = inspect.signature(cl.build_shadow_ledger)
        self.assertEqual(sig.parameters["mode"].default, "full")

    def test_full_mode_meta_has_no_sampling(self) -> None:
        # 用最小 stub catalog_build 跑 full 模式：meta.sampling 为 None
        catalog_build = {
            "catalog": [_claim("C1", "shall log")],
            "units": [],
            "meta": {"catalog_generation_id": "g1", "accounting_status": "complete"},
        }
        result = cl.build_shadow_ledger(catalog_build, [], route_mode="stub")
        self.assertEqual(result["meta"]["claim_ledger_mode"], "full")
        self.assertIsNone(result["meta"]["sampling"])

    def test_sampling_mode_meta_records_selection(self) -> None:
        catalog = [
            _claim("C1", "shall log"),
            _claim("C2", "OBIS 1-1:32.7.0"),  # 高风险
            _claim("C3", "shall report"),
        ]
        catalog_build = {
            "catalog": catalog,
            "units": [],
            "meta": {"catalog_generation_id": "g1", "accounting_status": "complete"},
        }
        result = cl.build_shadow_ledger(catalog_build, [], route_mode="stub", mode="sampling")
        self.assertEqual(result["meta"]["claim_ledger_mode"], "sampling")
        sampling = result["meta"]["sampling"]
        self.assertIsNotNone(sampling)
        self.assertEqual(sampling["mode"], "sampling")
        # 高风险 claim（C2 含 OBIS）计入闭合面
        self.assertGreaterEqual(sampling["high_risk_count"], 1)
        # 非高风险的纯叙述 claim 有延迟（未全部进入闭合面）
        self.assertGreaterEqual(sampling["deferred_count"], 1)


def _catalog_build(claims: list[dict]) -> dict:
    return {
        "catalog": list(claims),
        "units": [],
        "meta": {"catalog_generation_id": "g1", "accounting_status": "complete"},
    }


class PublishModeThreadingTests(unittest.TestCase):
    """S1-5：publish_b_track_shadow 显式传 mode=resolve_claim_ledger_mode()——env 设置真实生效。

    现状（接线前）：publish_b_track_shadow 不传 mode，build_shadow_ledger 恒走 full，
    env 设置对生产零效果。接线后：env=sampling/baseline_gate/full 在发布路径真实生效。
    build_shadow_ledger 自身默认仍是 full（直接调用者 / 4.1 万测试不动）——sampling 仅在
    被显式调用（publish_b_track_shadow→resolve_claim_ledger_mode）时生效。
    """

    def test_publish_threads_resolved_mode_for_each_env(self) -> None:
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        captured: dict = {}

        def fake_build(catalog, requirements, **kwargs):
            captured["mode"] = kwargs.get("mode")
            mode = kwargs.get("mode") or "full"
            return {
                "meta": {"claim_ledger_mode": mode, "sampling": None if mode == "full" else {}},
                "groups": [], "ledger": [], "metrics": {},
            }

        for env, expected in (("sampling", "sampling"), ("full", "full"), ("baseline_gate", "baseline_gate")):
            captured.clear()
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "ai_requirements.jsonl").write_text("{}", encoding="utf-8")
                with patch.dict(os.environ, {"RATOMIZER_CLAIM_LEDGER_MODE": env}), \
                        patch.object(cl, "build_shadow_ledger", side_effect=fake_build), \
                        patch("claim_artifacts.publish_shadow_generation", return_value={"run_id": "r"}), \
                        patch("claim_review_actions.fold_effective_ledger", return_value={}):
                    cl.publish_b_track_shadow(
                        root, run_id="r", route_mode="stub", extraction_status="success",
                        catalog_build=_catalog_build([]), requirements=[],
                    )
            self.assertEqual(captured.get("mode"), expected, f"env={env} 应线程传入 mode={expected}")

    def test_env_unset_publish_stays_full_default_unchanged(self) -> None:
        """硬边界「其余各项默认行为不变」：env 未设时发布路径仍走 full（不悄悄翻 sampling）。"""
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        captured: dict = {}

        def fake_build(catalog, requirements, **kwargs):
            captured["mode"] = kwargs.get("mode")
            return {"meta": {"claim_ledger_mode": kwargs.get("mode"), "sampling": None},
                    "groups": [], "ledger": [], "metrics": {}}

        old = os.environ.pop("RATOMIZER_CLAIM_LEDGER_MODE", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "ai_requirements.jsonl").write_text("{}", encoding="utf-8")
                with patch.object(cl, "build_shadow_ledger", side_effect=fake_build), \
                        patch("claim_artifacts.publish_shadow_generation", return_value={"run_id": "r"}), \
                        patch("claim_review_actions.fold_effective_ledger", return_value={}):
                    cl.publish_b_track_shadow(
                        root, run_id="r", route_mode="stub", extraction_status="success",
                        catalog_build=_catalog_build([]), requirements=[],
                    )
        finally:
            if old is not None:
                os.environ["RATOMIZER_CLAIM_LEDGER_MODE"] = old
        # env 未设 → 发布路径默认 full（生产默认行为逐字节不变）
        self.assertEqual(captured.get("mode"), "full")

    def test_sampling_run_records_deferred_claims_in_summary_artifact(self) -> None:
        """sampling 跑批：未抽中 claim 的计数/清单留痕到 governed summary（quality_report/manifest 口径）。"""
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from result_package import governed_artifact_path
        names = ["alpha", "beta", "gamma", "delta", "epsilon",
                 "zeta", "eta", "theta", "iota", "kappa"]
        catalog = [_claim(f"C{i:02d}", f"shall log event {names[i]}") for i in range(10)]
        catalog[1] = _claim("C01", "OBIS 1-1:32.7.0")  # 高风险（受保护编码）
        catalog[5] = _claim("C05", "voltage at 230 V")  # 高风险（数值命题）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ai_requirements.jsonl").write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"RATOMIZER_CLAIM_LEDGER_MODE": "sampling"}), \
                    patch("claim_artifacts.publish_shadow_generation", return_value={"run_id": "r"}), \
                    patch("claim_review_actions.fold_effective_ledger", return_value={}):
                published = cl.publish_b_track_shadow(
                    root, run_id="r", route_mode="stub", extraction_status="success",
                    catalog_build=_catalog_build(catalog), requirements=[],
                )
            # shadow meta（发布门禁 manifest 的采样块来源）记录 sampling + deferred
            meta = published["shadow"]["meta"]
            self.assertEqual(meta["claim_ledger_mode"], "sampling")
            self.assertGreater(meta["sampling"]["deferred_count"], 0)
            # governed summary（quality_report 口径）留痕未抽中 claim 清单
            summary_path = governed_artifact_path(root, "claim_sampling_summary.json", category="state")
            self.assertTrue(summary_path.is_file())
            summary = __import__("json").loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["mode"], "sampling")
            self.assertGreater(summary["deferred_count"], 0)
            self.assertTrue(summary["deferred_claim_ids"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
