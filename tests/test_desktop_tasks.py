from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from unittest.mock import ANY, patch

import desktop_tasks

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


class RunLoggingTests(unittest.TestCase):
    """GUI 路径日志：run.log 跟着输出目录走；任务结束关句柄（不锁目录）；幂等不重复挂 handler。"""

    def tearDown(self) -> None:
        import desktop_tasks
        desktop_tasks.teardown_run_logging()

    def test_setup_writes_run_log_and_is_idempotent(self) -> None:
        import logging
        from desktop_tasks import setup_run_logging, teardown_run_logging

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            setup_run_logging(out)
            setup_run_logging(out)   # 幂等：不重复挂 handler
            logger = logging.getLogger("requirement_atomizer")
            tags = [getattr(h, "_ratomizer_tag", None) for h in logger.handlers]
            self.assertEqual(tags.count("runlog"), 1)
            logger.info("marker-line-123")
            teardown_run_logging()   # 关句柄，tmp 目录才能删（Windows）
            content = (out / "run.log").read_text(encoding="utf-8")
        self.assertIn("marker-line-123", content)

    def test_main_produces_run_log_for_summary_command(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o"
            out.mkdir()
            write_jsonl(out / "atomic_requirements.jsonl", [])
            with redirect_stdout(io.StringIO()):
                exit_code = desktop_tasks.main(["summary", "--out", str(out)])
            self.assertEqual(exit_code, 0)
            log_text = (out / "run.log").read_text(encoding="utf-8")
        self.assertIn("desktop task 开始：summary", log_text)


class DesktopTaskEncodingTests(unittest.TestCase):
    def test_main_writes_json_payload_on_gbk_stdout(self) -> None:
        """Packaged Windows stdout may be GBK; non-GBK payload chars must not crash."""
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o"
            out.mkdir()
            write_jsonl(out / "atomic_requirements.jsonl", [])
            raw = io.BytesIO()
            gbk_stdout = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
            with (
                mock.patch("sys.stdout", gbk_stdout),
                mock.patch("desktop_tasks.build_output_summary", return_value={"text": "A\u0300"}),
            ):
                exit_code = desktop_tasks.main(["summary", "--out", str(out)])
            gbk_stdout.flush()

        self.assertEqual(exit_code, 0)
        payload = json.loads(raw.getvalue().decode("gbk"))
        self.assertEqual(payload["kind"], "summary")

    def test_emit_progress_writes_json_on_gbk_stdout(self) -> None:
        import desktop_tasks

        raw = io.BytesIO()
        gbk_stdout = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
        with mock.patch("sys.stdout", gbk_stdout):
            desktop_tasks.emit_progress({"stage": "probe", "text": "A\u0300"})
        gbk_stdout.flush()

        text = raw.getvalue().decode("gbk")
        self.assertIn(desktop_tasks.PROGRESS_PREFIX, text)
        self.assertEqual(json.loads(text.split(desktop_tasks.PROGRESS_PREFIX, 1)[1])["text"], "A\u0300")


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

    def test_assemble_task_passes_blue_book_index_to_assemble(self) -> None:
        from desktop_tasks import assemble_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            index_path = out_dir / "blue_book_index.json"
            index_path.write_text("{}", encoding="utf-8")
            with patch("desktop_tasks.assemble") as assemble:
                assemble.return_value = ({"requirements": [], "analysis": {}}, {"total": 0})

                assemble_task(out_dir, formats=[], enrich_route="openai_compatible", blue_book_index_path=index_path)

        assemble.assert_called_once()
        self.assertEqual(assemble.call_args.kwargs["blue_book_index_path"], index_path)

    def test_assemble_task_autodetects_index_in_out_dir(self) -> None:
        """桌面「运行」链没有索引输入口——out_dir 下有编译好的索引就自动带上（零配置）。"""
        from desktop_tasks import assemble_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            index_path = out_dir / "blue_book_index.json"
            index_path.write_text("{}", encoding="utf-8")
            with patch("desktop_tasks.assemble") as assemble:
                assemble.return_value = ({"requirements": [], "analysis": {}}, {"total": 0})

                payload = assemble_task(out_dir, formats=[], enrich_route="openai_compatible")

        self.assertEqual(assemble.call_args.kwargs["blue_book_index_path"], index_path)
        self.assertEqual(payload["blue_book_index"], str(index_path))   # 载荷追溯用了哪个索引

    def test_assemble_task_autodetect_falls_back_to_package_root(self) -> None:
        """dev 仓库编译位置 out/bluebook/ 作最后候选（打包后 resources/ 无 out/，自然探测不到）。"""
        from desktop_tasks import assemble_task

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            out_dir = Path(tmp) / "out"
            out_dir.mkdir()
            index_path = root / "out" / "bluebook" / "blue_book_index.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text("{}", encoding="utf-8")
            with (
                patch("desktop_tasks.assemble") as assemble,
                patch("desktop_tasks.package_root", return_value=root),
            ):
                assemble.return_value = ({"requirements": [], "analysis": {}}, {"total": 0})

                assemble_task(out_dir, formats=[], enrich_route="openai_compatible")

        self.assertEqual(assemble.call_args.kwargs["blue_book_index_path"], index_path)

    def test_assemble_task_env_var_overrides_autodetect(self) -> None:
        import os
        from desktop_tasks import BLUE_BOOK_INDEX_ENV, assemble_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "blue_book_index.json").write_text("{}", encoding="utf-8")  # 候选存在
            env_path = out_dir / "elsewhere.json"
            prior = os.environ.get(BLUE_BOOK_INDEX_ENV)
            os.environ[BLUE_BOOK_INDEX_ENV] = str(env_path)
            try:
                with patch("desktop_tasks.assemble") as assemble:
                    assemble.return_value = ({"requirements": [], "analysis": {}}, {"total": 0})
                    assemble_task(out_dir, formats=[], enrich_route="openai_compatible")
            finally:
                if prior is None:
                    os.environ.pop(BLUE_BOOK_INDEX_ENV, None)
                else:
                    os.environ[BLUE_BOOK_INDEX_ENV] = prior

        self.assertEqual(assemble.call_args.kwargs["blue_book_index_path"], env_path)   # env 优先于探测

    def test_assemble_task_no_index_anywhere_passes_none(self) -> None:
        """哪都没有索引 → None，行为与 P2 之前完全一致（默认零变化）。"""
        from desktop_tasks import assemble_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            out_dir.mkdir()
            with (
                patch("desktop_tasks.assemble") as assemble,
                patch("desktop_tasks.package_root", return_value=Path(tmp) / "repo"),
            ):
                assemble.return_value = ({"requirements": [], "analysis": {}}, {"total": 0})

                payload = assemble_task(out_dir, formats=[], enrich_route="openai_compatible")

        self.assertIsNone(assemble.call_args.kwargs["blue_book_index_path"])
        self.assertIsNone(payload["blue_book_index"])

    def test_main_assemble_accepts_blue_book_index_argument(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            index_path = Path(tmp) / "blue_book_index.json"
            index_path.write_text("{}", encoding="utf-8")
            with patch("desktop_tasks.assemble_task") as assemble:
                assemble.return_value = {"kind": "assemble", "out_dir": str(out_dir), "written": []}
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main([
                        "assemble",
                        "--out",
                        str(out_dir),
                        "--formats",
                        "",
                        "--enrich-route",
                        "openai_compatible",
                        "--blue-book-index",
                        str(index_path),
                    ])

        self.assertEqual(exit_code, 0)
        assemble.assert_called_once_with(
            out_dir,
            formats=[],
            enrich_route="openai_compatible",
            blue_book_index_path=index_path,
        )

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

    def test_requirements_analysis_task_wraps_run_requirements_analysis(self) -> None:
        from desktop_tasks import requirements_analysis_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            template = Path(tmp) / "template.xlsx"
            out_dir.mkdir()
            template.write_bytes(b"placeholder")
            # written 只报真实存在的产物：只落盘其中 2 个，xlsx/co_design 缺席
            (out_dir / "engineering_analysis.json").write_text("{}", encoding="utf-8")
            (out_dir / "hardware_items.md").write_text("# Hardware Items\n", encoding="utf-8")
            with patch("desktop_tasks.run_requirements_analysis") as run_analysis:
                run_analysis.return_value = {"kind": "requirements_analysis", "analysis_count": 1, "issues": 0}

                payload = requirements_analysis_task(out_dir, route="stub", template_path=template)

        from desktop_tasks import emit_progress
        run_analysis.assert_called_once_with(out_dir.resolve(), route="stub", template_path=template,
                                             progress_callback=emit_progress)
        self.assertEqual(payload["kind"], "requirements_analysis")
        self.assertEqual(payload["analysis"]["analysis_count"], 1)
        self.assertEqual(
            sorted(payload["written"]),
            sorted([
                str(out_dir.resolve() / "engineering_analysis.json"),
                str(out_dir.resolve() / "hardware_items.md"),
            ]),
        )
        self.assertEqual(payload["summary"]["counts"]["requirements"], 0)

    def test_requirements_analysis_task_rejects_missing_explicit_template(self) -> None:
        from desktop_tasks import requirements_analysis_task

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            out_dir.mkdir()
            missing_template = Path(tmp) / "missing-template.xlsx"

            with self.assertRaises(FileNotFoundError) as ctx:
                requirements_analysis_task(out_dir, route="stub", template_path=missing_template)

        self.assertIn("Template file does not exist", str(ctx.exception))

    def test_main_requirements_analysis_command_dispatches(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            template = Path(tmp) / "template.xlsx"
            with patch("desktop_tasks.requirements_analysis_task") as task:
                task.return_value = {
                    "kind": "requirements_analysis",
                    "out_dir": str(out_dir),
                    "analysis": {"analysis_count": 1},
                    "written": [],
                    "summary": {},
                }
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main([
                        "requirements-analysis",
                        "--out",
                        str(out_dir),
                        "--llm-route",
                        "stub",
                        "--template",
                        str(template),
                    ])

        self.assertEqual(exit_code, 0)
        task.assert_called_once_with(out_dir, route="stub", template_path=template)
        self.assertEqual(json.loads(stdout.getvalue())["kind"], "requirements_analysis")

    def test_functional_synthesis_cli_records_actual_degraded_route(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "ai_requirements.jsonl").write_text(
                json.dumps({"ai_req_id": "AI-1", "title": "事件管理", "module": "事件"}) + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout), mock.patch.dict("os.environ", {"RATOMIZER_LLM_API_KEY": ""}):
                rc = desktop_tasks.main([
                    "functional-synthesis", "--out", str(out),
                    "--llm-route", "openai_compatible",
                ])
            payload = json.loads(stdout.getvalue())
            manifest = json.loads((out / desktop_tasks.RUN_MANIFEST).read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload["route"], "stub")
        self.assertEqual(payload["route_requested"], "openai_compatible")
        self.assertEqual(manifest["stages"]["functional-synthesis"]["route"], "stub")

    def test_functional_synthesis_task_forwards_route(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with mock.patch.object(
                desktop_tasks, "run_functional_synthesis",
                return_value={"kind": "functional_synthesis", "written": ["functional_requirements.json"]},
            ) as run:
                payload = desktop_tasks.functional_synthesis_task(out, route="openai_compatible")

        run.assert_called_once_with(out.resolve(), route="openai_compatible")
        self.assertEqual(payload["kind"], "functional_synthesis")

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
                                       progress_callback=desktop_tasks.emit_progress,
                                       limit_sections=None, sample_ratio=None)
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
        task.assert_called_once_with(out_dir, route="stub", limit_sections=None, sample_ratio=None)
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

    def test_export_annotation_html_cli_forwards_layout_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch("desktop_tasks.export_annotation_html_task") as task:
                task.return_value = {
                    "kind": "annotation_html",
                    "out_dir": str(out),
                    "path": str(out / "document_annotation.html"),
                    "written": [],
                }
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main([
                        "export-annotation-html",
                        "--out",
                        str(out),
                        "--layout-mode",
                        "pdf_original",
                    ])

        self.assertEqual(exit_code, 0)
        task.assert_called_once_with(out, route=None, layout_mode="pdf_original")

    def test_import_ai_decisions_preserves_ownership_override(self) -> None:
        import desktop_tasks
        import ai_review_actions

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            decisions_file = out / "decisions.json"
            decisions_file.write_text(json.dumps({
                "decisions": [{
                    "ai_req_id": "AI-1",
                    "status": "accepted",
                    "module_override": "时钟需求",
                    "ownership_override": "co_design",
                    "reason": "硬件 RTC 依赖",
                }]
            }, ensure_ascii=False), encoding="utf-8")

            result = desktop_tasks.import_ai_decisions_task(out, decisions_file)
            states = ai_review_actions.read_ai_review_states(out)

        self.assertEqual(result["applied"], 1)
        self.assertEqual(states["AI-1"]["ownership_override"], "co_design")

    def test_import_decisions_rebuilds_merged_spec(self) -> None:
        """P0 裁决回流：导入裁决后交付物自动重建，rejected 不再出现在 merged_spec。"""
        import desktop_tasks
        import ai_review_actions

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            req = {"title": "体积计量", "description": "应计量体积", "type": "functional",
                   "priority": "P1", "module": "计量", "labels": ["计量"],
                   "source_section": "4", "source_quote": "The meter shall measure volume.",
                   "source_block_ids": ["B2"], "acceptance_criteria": [], "notes": "",
                   "status": "draft", "dependencies": [], "parent": None, "children": []}
            (out / "ai_requirements.jsonl").write_text(
                json.dumps(req, ensure_ascii=False) + "\n", encoding="utf-8")
            (out / "dlms_cosem_spec_requirements.json").write_text('{"requirements": []}', encoding="utf-8")
            rid = ai_review_actions.ai_req_id(req)
            (out / "dec.json").write_text(
                json.dumps({"decisions": [{"ai_req_id": rid, "status": "rejected"}]}), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = desktop_tasks.main(["import-ai-decisions", "--out", str(out), "--file", str(out / "dec.json")])
            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["applied"], 1)
            self.assertIn("rebuilt", payload)                          # 交付物已重建
            merged = json.loads((out / "merged_spec_requirements.json").read_text(encoding="utf-8"))
            self.assertEqual(merged["requirements"], [])               # rejected 已从交付物剔除



class ChainAndManifestTests(unittest.TestCase):
    """F1+F7：后端链编排 + run_manifest 显式状态账本。"""

    def test_affected_stage_producers_include_implementation_revision(self) -> None:
        expected = {
            "atomize": "atomize+impl-v4",
            "ai-extract": "ai-extract-v15+impl-v3",
            "assemble": "assemble_spec/v1+impl-v2",
            "functional-synthesis": "functional-synthesis-v5+impl-v2",
            "requirements-analysis": "analyze-llm-v5+impl-v2",
            "template-write": "template_writer/v1+impl-v2",
            "clarification-report": "clarification/v2-tiered+impl-v3",
            "export-annotation-html": "doc_annotation_export/v5",
        }
        self.assertEqual(
            {stage: desktop_tasks.stage_producer(stage) for stage in expected},
            expected,
        )

    def test_requirements_analysis_fingerprint_tracks_term_map(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            for name in desktop_tasks.STAGE_INPUTS["requirements-analysis"]:
                (out / name).write_text("{}\n", encoding="utf-8")
            term_map = out / "term_map.json"
            term_map.write_text(
                json.dumps({"terms": [{"source": "meter", "target": "电表"}]}),
                encoding="utf-8",
            )
            first = desktop_tasks.stage_input_fingerprint(out, "requirements-analysis")
            term_map.write_text(
                json.dumps({"terms": [{"source": "meter", "target": "表计"}]}),
                encoding="utf-8",
            )
            second = desktop_tasks.stage_input_fingerprint(out, "requirements-analysis")

        self.assertNotEqual(first, second)

    def test_annotation_fingerprint_tracks_layout_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            optimized = desktop_tasks.stage_input_fingerprint(
                out, "export-annotation-html", config={"layout_mode": "optimized"})
            original = desktop_tasks.stage_input_fingerprint(
                out, "export-annotation-html", config={"layout_mode": "pdf_original"})

        self.assertNotEqual(optimized, original)

    def test_manifest_with_old_producer_is_not_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "engineering_analysis.json").write_text("{}", encoding="utf-8")
            for name in desktop_tasks.STAGE_REQUIRED_OUTPUTS["template-write"]:
                (out / name).write_bytes(b"old-output")
            old_producer = "template_writer/v1"
            with mock.patch.object(desktop_tasks, "stage_producer", return_value=old_producer):
                fingerprint = desktop_tasks.stage_input_fingerprint(out, "template-write")
                desktop_tasks.update_run_manifest(
                    out, "template-write", "ok",
                    outputs=desktop_tasks.STAGE_REQUIRED_OUTPUTS["template-write"],
                    input_fingerprint=fingerprint,
                )

            self.assertFalse(desktop_tasks.stage_is_reusable(out, "template-write"))

    def test_clarification_fingerprint_tracks_functional_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            for name in ("ai_requirements.jsonl", "engineering_analysis.json",
                         "consistency_report.json", "blocks.jsonl"):
                (out / name).write_text("{}\n", encoding="utf-8")
            synthesis = out / desktop_tasks.FUNCTIONAL_REQUIREMENTS
            synthesis.write_text(
                json.dumps({"items": [{"conflict_flags": ["30 min"]}]}), encoding="utf-8")
            first = desktop_tasks.stage_input_fingerprint(out, "clarification-report")
            synthesis.write_text(
                json.dumps({"items": [{"conflict_flags": ["60 min"]}]}), encoding="utf-8")
            second = desktop_tasks.stage_input_fingerprint(out, "clarification-report")

        self.assertNotEqual(first, second)

    def test_chain_manifest_records_actual_functional_synthesis_route(self) -> None:
        import desktop_tasks

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "ai_requirements.jsonl").write_text(
                json.dumps({"ai_req_id": "AI-1", "title": "事件管理", "module": "事件"}) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                desktop_tasks, "functional_synthesis_task",
                return_value={
                    "kind": "functional_synthesis", "route_requested": "openai_compatible",
                    "route": "stub", "written": ["functional_requirements.json"],
                },
            ):
                (out / "functional_requirements.json").write_text("{}", encoding="utf-8")
                desktop_tasks.chain_task(
                    out, stages=["functional-synthesis"], route="openai_compatible")

            manifest = json.loads((out / desktop_tasks.RUN_MANIFEST).read_text(encoding="utf-8"))

        self.assertEqual(manifest["stages"]["functional-synthesis"]["route"], "stub")

    def test_chain_orders_dedupes_and_aggregates(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with (mock.patch.object(desktop_tasks, "clarification_report_task",
                                    side_effect=lambda o: (calls.append("clarification-report") or
                                                           {"kind": "clarification_report", "questions": 7,
                                                            "readiness": {"verdict": "READY", "reasons": []},
                                                            "summary": {"big": 1}})),
                  mock.patch.object(desktop_tasks, "ai_extract_task",
                                    side_effect=lambda o, **kw: (calls.append("ai-extract") or
                                                                 {"kind": "ai_extract", "count": 3,
                                                                  "consistency": {"duplicate_groups": 1},
                                                                  "summary": {"big": 1}}))):
                payload = desktop_tasks.chain_task(
                    out, stages=["clarification-report", "ai-extract", "ai-extract"],
                    route="openai_compatible")

            self.assertEqual(calls, ["ai-extract", "clarification-report"])   # 依赖序 + 去重
            self.assertEqual(payload["stages"], ["ai-extract", "clarification-report"])
            self.assertEqual(payload["questions"], 7)                          # 顶层聚合
            self.assertEqual(payload["consistency"], {"duplicate_groups": 1})
            self.assertNotIn("summary", payload["results"]["ai-extract"])      # 阶段 summary 被剥离
            manifest = json.loads((out / desktop_tasks.RUN_MANIFEST).read_text(encoding="utf-8"))
            self.assertEqual(manifest["stages"]["ai-extract"]["status"], "ok")
            self.assertEqual(manifest["stages"]["ai-extract"]["producer"],
                             desktop_tasks.stage_producer("ai-extract"))

    def test_chain_forwards_annotation_layout_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(
                desktop_tasks,
                "export_annotation_html_task",
                return_value={
                    "kind": "annotation_html",
                    "path": str(out / "document_annotation.html"),
                    "written": [],
                },
            ) as export_task:
                desktop_tasks.chain_task(
                    out,
                    stages=["export-annotation-html"],
                    route="stub",
                    annotation_layout_mode="pdf_original",
                )

        export_task.assert_called_once_with(
            out.resolve(), route="stub", layout_mode="pdf_original")

    def test_chain_unknown_stage_and_missing_template_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with self.assertRaises(ValueError):
                desktop_tasks.chain_task(out, stages=["nope"], route="stub")
            with self.assertRaises(ValueError):
                desktop_tasks.chain_task(out, stages=["template-write"], route="stub")

    def test_chain_stage_failure_recorded_and_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            with mock.patch.object(desktop_tasks, "ai_extract_task",
                                   side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    desktop_tasks.chain_task(out, stages=["ai-extract"], route="stub")
            manifest = json.loads((out / desktop_tasks.RUN_MANIFEST).read_text(encoding="utf-8"))
            entry = manifest["stages"]["ai-extract"]
            self.assertEqual(entry["status"], "failed")
            self.assertIn("boom", entry["error"])

    def test_update_run_manifest_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            desktop_tasks.update_run_manifest(out, "assemble", "running")
            desktop_tasks.update_run_manifest(out, "assemble", "ok")
            data = json.loads((out / desktop_tasks.RUN_MANIFEST).read_text(encoding="utf-8"))
            entry = data["stages"]["assemble"]
            self.assertEqual(entry["status"], "ok")
            self.assertIn("started", entry)
            self.assertIn("finished", entry)
            self.assertEqual(data["manifest_version"], 2)

    def test_run_pipeline_task_reuses_completed_atomize_and_review_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_path = root / "input.docx"
            input_path.write_text("doc", encoding="utf-8")
            out = root / "out"
            out.mkdir()
            (out / "manifest.json").write_text(json.dumps({
                "input": str(input_path.resolve()),
                "counts": {"atomic_requirements": 1},
            }), encoding="utf-8")
            for name in [
                "blocks.jsonl",
                "chunks.jsonl",
                "table_items.jsonl",
                "atomic_requirements.jsonl",
                "llm_tasks.jsonl",
                "quality_report.json",
                "summary.md",
                "llm_review_results.jsonl",
                "review_states.jsonl",
            ]:
                (out / name).write_text("{}\n", encoding="utf-8")
            atomize_config = {
                "chunk_chars": 3500,
                "kb_paths": [str(path) for path in desktop_tasks.resolve_kb_paths(None)],
                "domain_pack_dir": "",
            }
            desktop_tasks.update_run_manifest(
                out, "atomize", "ok", input_path=input_path, config=atomize_config)
            desktop_tasks.update_run_manifest(out, "llm-review", "ok", route="stub")

            with (mock.patch("desktop_tasks.run_atomizer_pipeline") as atomize,
                  mock.patch("desktop_tasks.run_review_pipeline") as review):
                payload = desktop_tasks.run_pipeline_task(input_path, out, llm_route="stub")

            atomize.assert_not_called()
            review.assert_not_called()
            self.assertEqual(payload["manifest"]["resume_action"], "skipped")
            self.assertEqual(payload["review"]["resume_action"], "skipped")
            self.assertEqual(payload["summary"]["run_manifest"]["stages"]["atomize"]["status"], "ok")

    def test_chain_skips_completed_stage_with_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "ai_requirements.jsonl").write_text("{}\n", encoding="utf-8")
            (out / "merged_spec_requirements.json").write_text('{"requirements":[]}', encoding="utf-8")
            (out / "merged_spec.xlsx").write_bytes(b"xlsx")
            desktop_tasks.update_run_manifest(
                out,
                "ai-extract",
                "ok",
                route="stub",
                outputs=["ai_requirements.jsonl", "merged_spec_requirements.json", "merged_spec.xlsx"],
                config={"sample_ratio": None, "limit_sections": None},
            )

            with mock.patch.object(desktop_tasks, "ai_extract_task") as task:
                payload = desktop_tasks.chain_task(out, stages=["ai-extract"], route="stub")

            task.assert_not_called()
            self.assertEqual(payload["results"]["ai-extract"]["resume_action"], "skipped")
            self.assertIn("ai-extract", payload["skipped_stages"])

    def test_chain_reruns_legacy_outputs_without_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "ai_requirements.jsonl").write_text("{}\n", encoding="utf-8")
            (out / "merged_spec_requirements.json").write_text('{"requirements":[]}', encoding="utf-8")

            with mock.patch.object(
                desktop_tasks, "ai_extract_task",
                return_value={"written": ["ai_requirements.jsonl", "merged_spec_requirements.json"]},
            ) as task:
                payload = desktop_tasks.chain_task(out, stages=["ai-extract"], route="stub")

            task.assert_called_once()
            self.assertNotIn("ai-extract", payload["skipped_stages"])
            manifest = json.loads((out / desktop_tasks.RUN_MANIFEST).read_text(encoding="utf-8"))
            self.assertEqual(manifest["stages"]["ai-extract"]["last_action"], "ran")


if __name__ == "__main__":
    unittest.main()
