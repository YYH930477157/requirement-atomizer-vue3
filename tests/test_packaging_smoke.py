"""安装后冒烟测试（审计 P1）：wheel 构建 → 内容检查 → 隔离安装 → 真实导入。

此前验收只在仓库根跑测试，py-modules 漏注册 functional_catalog、顶层 schemas/ 未打包
都因此漏网——安装后 import agent_eval 报 ModuleNotFoundError、
decide_trace.load_decide_trace_schema() 报文件不存在。本测试把"安装后能用"钉成回归。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _build_wheel(target: Path) -> Path:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--no-input", "-w", str(target), str(ROOT)],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise unittest.SkipTest(f"wheel build unavailable in this environment: {result.stderr[-500:]}")
    wheels = sorted(target.glob("*.whl"))
    if not wheels:
        raise unittest.SkipTest("wheel build produced no artifact")
    return wheels[-1]


class WheelPackagingSmokeTests(unittest.TestCase):
    def test_electron_backend_build_requires_office_com_runtime(self) -> None:
        script = (ROOT / "packaging" / "build-electron-backend.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("import pythoncom, win32com.client", script)
        self.assertIn("Office COM packaging dependencies are missing", script)
        self.assertIn("Resolve-Path -LiteralPath $Python", script)

    def test_wheel_contents_and_installed_imports(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dist = Path(td) / "dist"
            dist.mkdir()
            wheel = _build_wheel(dist)

            names = set(zipfile.ZipFile(wheel).namelist())
            for required in (
                "agent_eval.py", "agent_loop.py", "agent_state.py", "agent_tools.py",
                "agent_compare.py", "agent_decider.py", "decide_trace.py",
                "functional_catalog.py", "functional_synthesis.py", "review_tools.py",
                "desktop_tasks.py", "result_package.py", "semantic_quality.py",
                "claim_artifacts.py", "claim_acceptance.py", "claim_catalog.py", "claim_focus.py",
                "claim_queue_execution.py",
                "claim_held_out.py", "claim_ledger.py", "claim_reextract_attempts.py",
                "claim_structural_confirmation.py", "claim_structural_operations.py",
                "claim_structural_overrides.py", "table_claim_authority.py",
                "claim_review_packet.py", "input_completeness.py",
                "claim_review_import.py", "claim_review_actions.py", "claim_views.py",
                "process_file_lock.py",
                "normative_framing.py", "source_spans.py",
                "schemas/decide_trace.schema.json", "schemas/agent_eval_case.schema.json",
                "schemas/claim_verifier_attempt.schema.json",
                "schemas/claim_shadow_acceptance_report.schema.json",
                "schemas/claim_shadow_review_decisions.schema.json",
                "schemas/claim_effective_health.schema.json",
                "schemas/claim_effective_ledger.schema.json",
                "schemas/claim_effective_meta.schema.json",
                "schemas/claim_effective_meta_seed.schema.json",
                "schemas/claim_effective_publication_journal.schema.json",
                "schemas/claim_queue_proposal.schema.json",
                "schemas/claim_queue_proposal_v2.schema.json",
                "schemas/claim_queue_proposal_v3.schema.json",
                "schemas/claim_review_event.schema.json",
                "schemas/claim_review_event_v2.schema.json",
                "schemas/claim_reextract_attempt.schema.json",
                "schemas/claim_structural_operation.schema.json",
                "schemas/claim_structural_override.schema.json",
                "schemas/claim_structural_candidate_decision.schema.json",
                "schemas/claim_structural_candidate_decision_v2.schema.json",
                "schemas/claim_structural_candidate_decision_v3.schema.json",
                "schemas/table_cell_dispositions_v2.schema.json",
                "schemas/table_cell_item.schema.json",
                "schemas/result_package.schema.json",
                "golden_sets/claim_ledger_v1/manifest.json",
                "golden_sets/claim_ledger_v1/history/programmable-equivalent-001-v2-rejection.json",
                "llm_agents/review_pipeline.yaml", "domain_packs/dlms_cosem/pack.yaml",
            ):
                self.assertIn(required, names, f"wheel missing {required}")

            site = Path(td) / "site"
            install = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-deps", "--no-input",
                 "--target", str(site), str(wheel)],
                capture_output=True, text=True, timeout=600,
            )
            self.assertEqual(install.returncode, 0, install.stderr[-500:])

            probe = (
                "import agent_eval, decide_trace;"
                "decide_trace.load_decide_trace_schema();"
                "agent_eval.load_case_schema();"
                "import functional_catalog, functional_synthesis, semantic_quality, review_tools;"
                "import agent_state, agent_loop, agent_compare, llm_pipeline;"
                "import claim_artifacts, claim_acceptance, claim_catalog, claim_focus, claim_held_out;"
                "import claim_queue_execution;"
                "import claim_ledger, claim_reextract_attempts, claim_structural_confirmation, claim_structural_operations, claim_structural_overrides, claim_review_packet, normative_framing, source_spans;"
                "import claim_review_import, claim_review_actions, claim_views, process_file_lock, result_package, table_claim_authority;"
                "import json;from pathlib import Path;from jsonschema import Draft202012Validator;"
                "schema_root=Path(claim_artifacts.__file__).parent/'schemas';"
                "phase1_schemas=['claim_effective_health.schema.json',"
                "'claim_effective_ledger.schema.json','claim_effective_meta.schema.json',"
                "'claim_effective_meta_seed.schema.json',"
                "'claim_effective_publication_journal.schema.json',"
                "'claim_queue_proposal.schema.json','claim_queue_proposal_v2.schema.json',"
                "'claim_queue_proposal_v3.schema.json',"
                "'claim_review_event.schema.json',"
                "'claim_review_event_v2.schema.json','claim_reextract_attempt.schema.json',"
                "'claim_structural_operation.schema.json',"
                "'claim_structural_override.schema.json',"
                "'claim_structural_candidate_decision.schema.json',"
                "'claim_structural_candidate_decision_v2.schema.json',"
                "'claim_structural_candidate_decision_v3.schema.json',"
                "'table_cell_dispositions_v2.schema.json',"
                "'table_cell_item.schema.json',"
                "'result_package.schema.json'];"
                "[Draft202012Validator.check_schema(json.loads((schema_root/name).read_text(encoding='utf-8')))"
                " for name in phase1_schemas];"
                "claim_held_out.load_golden_held_out();"
                "assert llm_pipeline.DEFAULT_PIPELINE_PATH.exists();"
                "assert llm_pipeline.DEFAULT_DOMAIN_PACK_PATH.exists();"
                "print('SMOKE OK')"
            )
            # cwd 必须是与源码无关的空目录：python -c 的 sys.path[0]=''（即 cwd）优先于
            # PYTHONPATH，从仓根跑测试时不隔离 cwd 会命中源码树而非隔离安装（假绿）。
            empty_cwd = Path(td) / "cwd"
            empty_cwd.mkdir()
            run = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True, text=True, timeout=120,
                cwd=empty_cwd,
                env={"PYTHONPATH": str(site), "PATH": ""},
            )
            self.assertEqual(run.returncode, 0, f"{run.stdout[-300:]} {run.stderr[-500:]}")
            self.assertIn("SMOKE OK", run.stdout)


if __name__ == "__main__":
    unittest.main()
