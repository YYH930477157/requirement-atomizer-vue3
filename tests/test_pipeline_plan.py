from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from config import ENV_REGISTRY
from pipeline_contracts import LOGICAL_STAGE_CONTRACTS, contract_for, stage_inputs_for
from pipeline_plan import (
    BUDGET_MODE_ENV,
    EXECUTION_POLICY_ENV,
    PIPELINE_PLAN_FILENAME,
    PIPELINE_PLAN_SCHEMA,
    TRANSLATION_MODE_ENV,
    build_pipeline_plan,
    load_pipeline_plan,
    resolve_budget_mode,
    resolve_execution_policy,
    resolve_translation_mode,
    routing_summary_for_plan,
    validate_pipeline_plan,
    write_pipeline_plan,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = Draft202012Validator(json.loads(
    (REPO_ROOT / "schemas" / "pipeline_plan.schema.json").read_text(encoding="utf-8")))


class PipelineContractTests(unittest.TestCase):
    def test_every_logical_stage_has_contract(self) -> None:
        for stage in ("atomize", "plan-extraction-units", "route-units",
                      "execute-routed-units", "merge-routed-results", "quality-gates",
                      "targeted-escalation", "translation", "publish-deliverables"):
            contract = contract_for(stage)
            self.assertIn("inputs", contract)
            self.assertIn("versions", contract)
            self.assertIn("config", contract)
        with self.assertRaises(ValueError):
            contract_for("nonexistent-stage")

    def test_stage_inputs_listed(self) -> None:
        self.assertIn("extraction_units.jsonl", stage_inputs_for("route-units"))


class PipelinePlanTests(unittest.TestCase):
    def test_quality_first_plan_shape_and_schema(self) -> None:
        plan = build_pipeline_plan(execution_policy="quality_first",
                                   translation_mode="off")
        self.assertEqual(plan["schema"], PIPELINE_PLAN_SCHEMA)
        self.assertEqual(plan["execution_policy"], "quality_first")
        self.assertEqual(plan["delivery"]["translation_mode"], "off")
        self.assertIn("plan-extraction-units", plan["stages"])
        self.assertIn("route-units", plan["stages"])
        self.assertNotIn("translation", plan["stages"])  # off → 无翻译阶段
        errors = list(VALIDATOR.iter_errors(plan))
        self.assertEqual(errors, [])
        validate_pipeline_plan(plan)

    def test_translation_mode_adds_translation_stage(self) -> None:
        plan = build_pipeline_plan(execution_policy="quality_first",
                                   translation_mode="markers")
        self.assertIn("translation", plan["stages"])

    def test_default_policy_is_legacy_combined_not_flipped(self) -> None:
        # §31：Router 未过真实语料门禁前默认不翻 quality_first
        plan = build_pipeline_plan()
        self.assertEqual(plan["execution_policy"], "legacy_combined")
        self.assertIn("ai-extract", plan["stages"])

    def test_legacy_translation_off_drops_full_translation_stage(self) -> None:
        plan = build_pipeline_plan(execution_policy="legacy_combined",
                                   translation_mode="off")
        self.assertNotIn("full-translation", plan["stages"])

    def test_fingerprint_stable_and_tamper_evident(self) -> None:
        first = build_pipeline_plan(execution_policy="quality_first")
        second = build_pipeline_plan(execution_policy="quality_first")
        self.assertEqual(first["plan_fingerprint"], second["plan_fingerprint"])
        tampered = dict(first)
        tampered["execution_policy"] = "force_a"
        with self.assertRaises(ValueError):
            validate_pipeline_plan(tampered)

    def test_delivery_toggles_change_fingerprint(self) -> None:
        base = build_pipeline_plan(execution_policy="quality_first")
        tuned = build_pipeline_plan(execution_policy="quality_first",
                                    delivery={"cosem_spec": False})
        self.assertNotEqual(base["plan_fingerprint"], tuned["plan_fingerprint"])
        self.assertFalse(tuned["delivery"]["cosem_spec"])

    def test_unknown_policy_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_pipeline_plan(execution_policy="yolo")

    def test_env_overrides_resolve(self) -> None:
        import os

        saved = {name: os.environ.get(name) for name in
                 (EXECUTION_POLICY_ENV, TRANSLATION_MODE_ENV, BUDGET_MODE_ENV)}
        try:
            os.environ[EXECUTION_POLICY_ENV] = "full_dual_audit"
            os.environ[TRANSLATION_MODE_ENV] = "markers"
            os.environ[BUDGET_MODE_ENV] = "observe"
            self.assertEqual(resolve_execution_policy(), "full_dual_audit")
            self.assertEqual(resolve_translation_mode(), "markers")
            self.assertEqual(resolve_budget_mode(), "observe")
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_env_vars_registered(self) -> None:
        names = {entry.name for entry in ENV_REGISTRY}
        for name in (EXECUTION_POLICY_ENV, TRANSLATION_MODE_ENV, BUDGET_MODE_ENV):
            self.assertIn(name, names)

    def test_write_load_roundtrip_governed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            plan = build_pipeline_plan(execution_policy="quality_first",
                                       budget_mode="observe")
            write_pipeline_plan(out_dir, plan)
            self.assertTrue((out_dir / PIPELINE_PLAN_FILENAME).is_file())
            loaded = load_pipeline_plan(out_dir)
            self.assertEqual(loaded, plan)
            self.assertIsNone(routing_summary_for_plan(out_dir))  # 无路由产物不伪造


class PipelinePlanCLITests(unittest.TestCase):
    def test_cli_plan_command_writes_envelope(self) -> None:
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "cli.py"), "plan",
                 "--out", str(out_dir),
                 "--execution-policy", "quality_first",
                 "--translation", "off",
                 "--delivery", "cosem_spec=0"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT))
            self.assertEqual(result.returncode, 0, result.stderr[-800:])
            envelope = json.loads(result.stdout)
            self.assertTrue(envelope["ok"])
            self.assertEqual(envelope["plan"]["execution_policy"], "quality_first")
            self.assertFalse(envelope["plan"]["delivery"]["cosem_spec"])
            self.assertTrue((out_dir / PIPELINE_PLAN_FILENAME).is_file())


if __name__ == "__main__":
    unittest.main()
