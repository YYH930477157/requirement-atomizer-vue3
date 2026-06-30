from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import ANY, patch

from llm_pipeline import write_jsonl


class ResolveKbPathsTests(unittest.TestCase):
    """锁定 desktop_tasks.resolve_kb_paths：前端预设送相对 --kb 路径，打包后端 cwd=resources/backend
    命中不到时必须按 package_root() 解析（否则报 'No such file: …/backend/knowledge_bases/…json'）。"""

    def test_none_uses_default_kb_paths(self) -> None:
        from desktop_tasks import resolve_kb_paths

        sentinel = [Path("X") / "default.json"]
        with patch("desktop_tasks.default_kb_paths", return_value=sentinel) as default_kb_paths:
            self.assertEqual(resolve_kb_paths(None), sentinel)
            default_kb_paths.assert_called_once()

    def test_absolute_paths_pass_through(self) -> None:
        from desktop_tasks import resolve_kb_paths

        absolute = (Path(tempfile.gettempdir()).resolve() / "abs_kb.json")
        self.assertEqual(resolve_kb_paths([absolute]), [absolute])

    def test_relative_missing_in_cwd_resolves_against_package_root(self) -> None:
        from desktop_tasks import resolve_kb_paths

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 唯一名，保证不在测试 cwd 命中 -> 走 package_root 兜底
            rel = Path("knowledge_bases") / "__resolve_kb_probe__.json"
            with patch("desktop_tasks.package_root", return_value=root):
                self.assertEqual(resolve_kb_paths([rel]), [root / rel])

    def test_resolve_bundled_path_none_returns_none(self) -> None:
        from desktop_tasks import resolve_bundled_path

        self.assertIsNone(resolve_bundled_path(None))

    def test_resolve_bundled_path_relative_domain_pack_uses_package_root(self) -> None:
        from desktop_tasks import resolve_bundled_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # domain pack 预设相对路径（cwd 命中不到）-> package_root 兜底（打包后即 resources/）
            rel = Path("domain_packs") / "__resolve_pack_probe__"
            with patch("desktop_tasks.package_root", return_value=root):
                self.assertEqual(resolve_bundled_path(rel), root / rel)


class DesktopTaskTests(unittest.TestCase):
    def test_run_pipeline_task_uses_default_kbs_when_not_supplied(self) -> None:
        from desktop_tasks import run_pipeline_task

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.docx"
            out_dir = root / "out"
            input_path.write_text("placeholder", encoding="utf-8")
            out_dir.mkdir()

            with (
                patch("desktop_tasks.default_kb_paths") as default_kb_paths,
                patch("desktop_tasks.run_atomizer_pipeline") as atomize,
            ):
                default_kb_paths.return_value = [root / "default-a.json", root / "default-b.json"]
                atomize.return_value = {"counts": {"atomic_requirements": 0}}
                write_jsonl(out_dir / "atomic_requirements.jsonl", [])

                run_pipeline_task(input_path, out_dir, skip_review=True)

        atomize.assert_called_once()
        self.assertEqual(atomize.call_args.kwargs["kb_paths"], [root / "default-a.json", root / "default-b.json"])

    def test_run_pipeline_task_writes_outputs_and_review_summary(self) -> None:
        from desktop_tasks import run_pipeline_task

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.docx"
            out_dir = root / "out"
            input_path.write_text("placeholder", encoding="utf-8")
            out_dir.mkdir()

            with patch("desktop_tasks.run_atomizer_pipeline") as atomize, patch("desktop_tasks.run_review_pipeline") as review:
                atomize.return_value = {
                    "input": str(input_path),
                    "output_dir": str(out_dir),
                    "counts": {"atomic_requirements": 2},
                }
                review.return_value = {"reviews": 2, "accepted": 1, "expert_pending": 1}
                write_jsonl(
                    out_dir / "atomic_requirements.jsonl",
                    [
                        {"stable_req_id": "SREQ-1", "requirement_type": "functional", "confidence": 0.9},
                        {"stable_req_id": "SREQ-2", "requirement_type": "security", "confidence": 0.7},
                    ],
                )
                write_jsonl(
                    out_dir / "review_states.jsonl",
                    [
                        {"requirement_id": "SREQ-1", "status": "accepted"},
                        {"requirement_id": "SREQ-2", "status": "expert_pending"},
                    ],
                )

                payload = run_pipeline_task(input_path, out_dir, skip_review=False)

        self.assertEqual(payload["kind"], "pipeline")
        self.assertEqual(payload["manifest"]["counts"]["atomic_requirements"], 2)
        self.assertEqual(payload["review"]["reviews"], 2)
        self.assertEqual(payload["summary"]["counts"]["requirements"], 2)
        self.assertEqual(payload["summary"]["status_counts"]["accepted"], 1)
        atomize.assert_called_once()
        review.assert_called_once_with(out_dir.resolve(), route=None, scope=None, llm_review_limit=0, progress_callback=ANY)

    def test_main_run_command_passes_kb_and_domain_pack_to_pipeline(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.docx"
            out_dir = root / "out"
            kb_path = root / "kb.json"
            domain_pack = root / "domain_packs" / "dlms_cosem"
            input_path.write_text("placeholder", encoding="utf-8")
            kb_path.write_text("{}", encoding="utf-8")
            domain_pack.mkdir(parents=True)

            with patch("desktop_tasks.run_pipeline_task") as run_pipeline:
                run_pipeline.return_value = {"kind": "pipeline", "out_dir": str(out_dir), "summary": {}}

                with redirect_stdout(io.StringIO()):
                    exit_code = desktop_tasks.main([
                        "run",
                        "--input",
                        str(input_path),
                        "--out",
                        str(out_dir),
                        "--chunk-chars",
                        "1200",
                        "--kb",
                        str(kb_path),
                        "--domain-pack",
                        str(domain_pack),
                    ])

        self.assertEqual(exit_code, 0)
        run_pipeline.assert_called_once_with(
            input_path,
            out_dir,
            skip_review=False,
            llm_route=None,
            review_scope=None,
            llm_review_limit=0,
            chunk_chars=1200,
            kb_paths=[kb_path],
            domain_pack_dir=domain_pack,
        )

    def test_export_task_returns_written_files(self) -> None:
        from desktop_tasks import export_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("desktop_tasks.export_requirements") as export_requirements:
                export_requirements.return_value = ["requirements_export.csv", "requirements_export.md"]

                payload = export_task(out_dir, ["csv", "md"])

        self.assertEqual(payload["kind"], "export")
        self.assertEqual(payload["written"], ["requirements_export.csv", "requirements_export.md"])
        export_requirements.assert_called_once_with(out_dir.resolve(), formats=["csv", "md"])

    def test_assemble_task_writes_json_and_exports_formats(self) -> None:
        from desktop_tasks import ASSEMBLED_JSON, assemble_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("desktop_tasks.assemble") as assemble, patch("desktop_tasks.export_spec") as export_spec:
                assemble.return_value = ({"requirements": [{"id": "REQ-1"}], "analysis": {"total_count": 1}}, {"安全": 1})
                export_spec.return_value = ["dlms_cosem_spec_requirements.md"]

                payload = assemble_task(out_dir, formats=["md"])

            assembled = json.loads((out_dir / ASSEMBLED_JSON).read_text(encoding="utf-8"))

        self.assertEqual(payload["kind"], "assemble")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(assembled["requirements"][0]["id"], "REQ-1")
        self.assertIn(str(out_dir / ASSEMBLED_JSON), payload["written"])
        self.assertIn(str(out_dir / "dlms_cosem_spec_requirements.md"), payload["written"])
        export_spec.assert_called_once()

    def test_compose_task_writes_engineering_requirement_outputs(self) -> None:
        from desktop_tasks import compose_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with (
                patch("desktop_tasks.compose_engineering_requirements") as compose,
                patch("desktop_tasks.write_engineering_requirements") as write_outputs,
            ):
                compose.return_value = {
                    "analysis": {"requirement_functions": 2, "dlms_objects": 3},
                    "requirement_functions": [{}, {}],
                    "dlms_objects": [{}, {}, {}],
                }
                write_outputs.return_value = [
                    "engineering_requirements/engineering_requirements.json",
                    "engineering_requirements/requirement_functions.md",
                    "engineering_requirements/dlms_objects.md",
                ]

                payload = compose_task(out_dir)

        self.assertEqual(payload["kind"], "compose")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["analysis"]["dlms_objects"], 3)
        self.assertIn("engineering_requirements/requirement_functions.md", payload["written"])
        compose.assert_called_once_with(out_dir.resolve())
        write_outputs.assert_called_once_with(out_dir.resolve(), compose.return_value)

    def test_main_compose_command_runs_engineering_composer(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("desktop_tasks.compose_task") as compose:
                compose.return_value = {"kind": "compose", "out_dir": str(out_dir), "count": 1, "written": []}

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main(["compose", "--out", str(out_dir)])

        self.assertEqual(exit_code, 0)
        compose.assert_called_once_with(out_dir)
        self.assertEqual(json.loads(stdout.getvalue())["kind"], "compose")

    def test_ai_extract_task_wraps_run_ai_extract(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("ai_extract.run_ai_extract") as run_ai:
                run_ai.return_value = {
                    "route": "openai_compatible", "requirements": 3,
                    "merged": {"total": 10, "ai_behavioral": 3, "deterministic_structural": 7},
                    "code_drift_flagged": 0, "int_drift_flagged": 1,
                    "written": ["merged_spec.xlsx", "merged_spec_requirements.json"],
                }
                payload = desktop_tasks.ai_extract_task(out_dir, route="openai_compatible")

        run_ai.assert_called_once_with(out_dir.resolve(), route="openai_compatible",
                                       merge_deterministic=True,
                                       progress_callback=desktop_tasks.emit_progress)
        self.assertEqual(payload["kind"], "ai_extract")
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["merged"]["total"], 10)
        self.assertIn(str(out_dir.resolve() / "merged_spec.xlsx"), payload["written"])

    def test_main_ai_extract_command_dispatches(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch("desktop_tasks.ai_extract_task") as task:
                task.return_value = {"kind": "ai_extract", "out_dir": str(out_dir), "count": 0}
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main(["ai-extract", "--out", str(out_dir), "--llm-route", "stub"])

        self.assertEqual(exit_code, 0)
        task.assert_called_once_with(out_dir, route="stub")
        self.assertEqual(json.loads(stdout.getvalue())["kind"], "ai_extract")

    def test_export_annotation_html_and_import_round_trip(self) -> None:
        import desktop_tasks
        import ai_review_actions
        from doc_annotation_export import build_ai_requirements

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "blocks.jsonl").write_text(
                json.dumps({"block_id": "B2", "order": 2, "text": "The meter shall measure volume.",
                            "section_path": ["4"], "requirement_like": True, "noise": False,
                            "type": "paragraph"}) + "\n", encoding="utf-8")
            doc = {"requirements": [{"id": "REQ-001", "title": "体积计量", "description": "应计量体积",
                    "module": "计量", "source_section": "4", "source_quote": "The meter shall measure volume.",
                    "source_block_ids": ["B2"], "acceptance_criteria": ["按 4.2 测试"], "labels": ["计量"]}]}
            (out / "merged_spec_requirements.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

            # 导出 HTML
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = desktop_tasks.main(["export-annotation-html", "--out", str(out)])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(stdout.getvalue())["kind"], "annotation_html")
            self.assertTrue((out / "document_annotation.html").exists())

            # 导入裁决回灌
            rid = build_ai_requirements(out)[0]["ai_req_id"]
            (out / "dec.json").write_text(json.dumps(
                {"decisions": [{"ai_req_id": rid, "status": "accepted", "module_override": "计量精度"}]}),
                encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = desktop_tasks.main(["import-ai-decisions", "--out", str(out), "--file", str(out / "dec.json")])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(stdout.getvalue())["applied"], 1)
            states = ai_review_actions.read_ai_review_states(out)
            self.assertEqual(states[rid]["status"], "accepted")
            self.assertEqual(states[rid]["module_override"], "计量精度")


if __name__ == "__main__":
    unittest.main()
