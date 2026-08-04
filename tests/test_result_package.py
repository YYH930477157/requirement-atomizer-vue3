from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import desktop_tasks
import clarification_check_states
import cosem_object_model
from jsonschema import Draft202012Validator
from api_server import (
    ANNOTATION_TRANSLATION_GUARDS_VERSION,
    ANNOTATION_TRANSLATIONS,
    load_annotation_translations,
)

from result_package import (
    RESULT_PACKAGE_FILE,
    RESULT_PACKAGE_SCHEMA,
    ResultPackageCorrupt,
    ResultPackageError,
    commit_analysis_completion,
    detect_result_layout,
    governed_artifact_path,
    initialize_result_package,
    load_result_package,
    package_artifact_path,
    package_root_for_analysis_root,
    record_analysis_failure,
    resolve_analysis_root,
    publish_registered_deliverables,
)
from version import __version__


class ResultPackageTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "standard.docx"
        source.write_bytes(b"docx-fixture")
        return source

    def _initialize(self, root: Path) -> dict:
        return initialize_result_package(
            root,
            input_path=self._source(root),
            requested_stages=["atomize", "requirements-analysis"],
        )

    def _write_completion_evidence(self, root: Path) -> None:
        run_id = load_result_package(root)["active_attempt"]["run_id"]
        path = package_artifact_path(root, "run_manifest", for_write=True)
        path.write_text(
            json.dumps({
                "manifest_version": 2,
                "stages": {
                    "atomize": {"status": "ok", "attempt_run_id": run_id},
                    "requirements-analysis": {
                        "status": "ok", "attempt_run_id": run_id,
                    },
                },
            }),
            encoding="utf-8",
        )

    def test_initialize_empty_directory_creates_running_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)

            self.assertEqual(package["schema"], RESULT_PACKAGE_SCHEMA)
            self.assertEqual(package["tool"]["version"], __version__)
            self.assertEqual(package["analysis_status"], "running")
            self.assertEqual(package["input"]["display_name"], "standard.docx")
            self.assertEqual(package["active_attempt"]["requested_stages"], [
                "atomize", "requirements-analysis",
            ])
            self.assertTrue((root / RESULT_PACKAGE_FILE).is_file())
            for name in ("pipeline", "state", "cache", "logs", "stages"):
                self.assertTrue((root / ".ratomizer" / name).is_dir(), name)

            schema = json.loads(
                (Path(__file__).parents[1] / "schemas" / "result_package.schema.json")
                .read_text(encoding="utf-8")
            )
            Draft202012Validator(schema).validate(package)

    def test_commit_completion_records_evidence_and_deliverable_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            self._write_completion_evidence(root)
            summary = package_artifact_path(root, "summary_md", for_write=True)
            summary.write_text("# Analysis complete\n", encoding="utf-8")

            completed = commit_analysis_completion(
                root,
                run_id=package["active_attempt"]["run_id"],
                completed_stages=["atomize", "requirements-analysis"],
            )

            self.assertEqual(completed["analysis_status"], "completed")
            self.assertIsNone(completed["active_attempt"])
            self.assertEqual(completed["analysis"]["completed_stages"], [
                "atomize", "requirements-analysis",
            ])
            self.assertTrue(completed["analysis"]["completion_evidence"])
            deliverable = next(
                item for item in completed["deliverables"]
                if item["artifact_id"] == "summary_md"
            )
            self.assertEqual(deliverable["path"], "summary.md")
            self.assertRegex(deliverable["sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual((root / "summary.md").read_text(encoding="utf-8"), "# Analysis complete\n")
            self.assertEqual(load_result_package(root, verify=True), completed)

    def test_review_state_changes_do_not_change_analysis_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            self._write_completion_evidence(root)
            completed = commit_analysis_completion(
                root,
                run_id=package["active_attempt"]["run_id"],
                completed_stages=["atomize", "requirements-analysis"],
            )
            before = (root / RESULT_PACKAGE_FILE).read_bytes()

            review_states = package_artifact_path(root, "review_states", for_write=True)
            review_states.write_text('{"requirement_id":"REQ-1","status":"accepted"}\n', encoding="utf-8")

            self.assertEqual((root / RESULT_PACKAGE_FILE).read_bytes(), before)
            self.assertEqual(load_result_package(root)["analysis_status"], "completed")
            self.assertEqual(load_result_package(root)["analysis"]["run_id"], completed["analysis"]["run_id"])

    def test_review_export_updates_hash_without_changing_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            self._write_completion_evidence(root)
            annotation = package_artifact_path(root, "document_annotation", for_write=True)
            annotation.write_text("first", encoding="utf-8")
            completed = commit_analysis_completion(
                root,
                run_id=package["active_attempt"]["run_id"],
                completed_stages=["atomize", "requirements-analysis"],
            )
            first_analysis = completed["analysis"]
            first_hash = next(
                item["sha256"] for item in completed["deliverables"]
                if item["artifact_id"] == "document_annotation"
            )

            annotation.write_text("second", encoding="utf-8")
            publish_registered_deliverables(root)
            updated = load_result_package(root)

            second_hash = next(
                item["sha256"] for item in updated["deliverables"]
                if item["artifact_id"] == "document_annotation"
            )
            self.assertNotEqual(first_hash, second_hash)
            self.assertEqual(updated["analysis_status"], "completed")
            self.assertEqual(updated["analysis"], first_analysis)

    def test_multi_deliverable_publish_failure_restores_previous_files_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            self._write_completion_evidence(root)
            summary = package_artifact_path(root, "summary_md", for_write=True)
            annotation = package_artifact_path(root, "document_annotation", for_write=True)
            summary.write_text("old summary", encoding="utf-8")
            annotation.write_text("old annotation", encoding="utf-8")
            commit_analysis_completion(
                root,
                run_id=package["active_attempt"]["run_id"],
                completed_stages=["atomize", "requirements-analysis"],
            )
            marker_before = (root / RESULT_PACKAGE_FILE).read_bytes()

            summary.write_text("new summary", encoding="utf-8")
            annotation.write_text("new annotation", encoding="utf-8")
            import result_package as result_package_module

            original_install = result_package_module._install_staged_path
            calls = 0

            def fail_second_install(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated second deliverable failure")
                original_install(source, target)

            with patch.object(
                result_package_module,
                "_install_staged_path",
                side_effect=fail_second_install,
            ):
                with self.assertRaisesRegex(OSError, "second deliverable"):
                    publish_registered_deliverables(root)

            self.assertEqual((root / "summary.md").read_text(encoding="utf-8"), "old summary")
            self.assertEqual(
                (root / "document_annotation.html").read_text(encoding="utf-8"),
                "old annotation",
            )
            self.assertEqual((root / RESULT_PACKAGE_FILE).read_bytes(), marker_before)
            load_result_package(root, verify=True)

    def test_marker_commit_failure_restores_previous_deliverables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            self._write_completion_evidence(root)
            summary = package_artifact_path(root, "summary_md", for_write=True)
            summary.write_text("old summary", encoding="utf-8")
            commit_analysis_completion(
                root,
                run_id=package["active_attempt"]["run_id"],
                completed_stages=["atomize", "requirements-analysis"],
            )
            marker_before = (root / RESULT_PACKAGE_FILE).read_bytes()
            summary.write_text("new summary", encoding="utf-8")

            import result_package as result_package_module

            original_write = result_package_module._atomic_write_json

            def fail_marker_write(path: Path, payload: dict) -> None:
                if path.name == RESULT_PACKAGE_FILE:
                    raise OSError("simulated marker commit failure")
                original_write(path, payload)

            with patch.object(
                result_package_module, "_atomic_write_json", side_effect=fail_marker_write
            ):
                with self.assertRaisesRegex(OSError, "marker commit"):
                    publish_registered_deliverables(root)

            self.assertEqual((root / "summary.md").read_text(encoding="utf-8"), "old summary")
            self.assertEqual((root / RESULT_PACKAGE_FILE).read_bytes(), marker_before)
            load_result_package(root, verify=True)

    def test_next_mutation_recovers_hard_interrupted_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            self._write_completion_evidence(root)
            summary = package_artifact_path(root, "summary_md", for_write=True)
            summary.write_text("old summary", encoding="utf-8")
            commit_analysis_completion(
                root,
                run_id=package["active_attempt"]["run_id"],
                completed_stages=["atomize", "requirements-analysis"],
            )

            import result_package as result_package_module

            transaction_id = "a" * 32
            transaction_root = result_package_module._publication_transaction_root(
                root, transaction_id
            )
            backup = transaction_root / "backup" / "summary_md"
            result_package_module._copy_path_snapshot(root / "summary.md", backup)
            base_marker_sha = result_package_module._sha256_file(
                root / RESULT_PACKAGE_FILE
            )
            (root / "summary.md").write_text("partially published", encoding="utf-8")
            result_package_module._atomic_write_json(
                result_package_module._publication_journal_path(root),
                {
                    "schema": "result-package-publication/v1",
                    "transaction_id": transaction_id,
                    "base_marker_sha256": base_marker_sha,
                    "target_marker_sha256": "sha256:" + "f" * 64,
                    "entries": [{
                        "artifact_id": "summary_md",
                        "path": "summary.md",
                        "staged_path": (
                            transaction_root / "new" / "summary_md"
                        ).relative_to(root).as_posix(),
                        "had_target": True,
                        "backup_path": backup.relative_to(root).as_posix(),
                    }],
                },
            )
            replacement = root / "replacement.docx"
            replacement.write_bytes(b"replacement")

            restarted = initialize_result_package(
                root,
                input_path=replacement,
                requested_stages=["requirements-analysis"],
            )

            self.assertEqual((root / "summary.md").read_text(encoding="utf-8"), "old summary")
            self.assertFalse(
                result_package_module._publication_journal_path(root).exists()
            )
            self.assertEqual(restarted["active_attempt"]["input"]["display_name"], "replacement.docx")

    def test_failed_rerun_preserves_previous_committed_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._initialize(root)
            self._write_completion_evidence(root)
            committed = commit_analysis_completion(
                root,
                run_id=first["active_attempt"]["run_id"],
                completed_stages=["atomize", "requirements-analysis"],
            )
            committed_run_id = committed["analysis"]["run_id"]
            committed_input = dict(committed["input"])
            replacement = root / "replacement.docx"
            replacement.write_bytes(b"replacement-docx-fixture")

            rerun = initialize_result_package(
                root,
                input_path=replacement,
                requested_stages=["requirements-analysis"],
            )
            self.assertEqual(rerun["input"], committed_input)
            self.assertEqual(
                rerun["active_attempt"]["input"]["display_name"], "replacement.docx"
            )
            failed = record_analysis_failure(
                root,
                run_id=rerun["active_attempt"]["run_id"],
                error="endpoint unavailable",
            )

            self.assertEqual(failed["analysis_status"], "completed")
            self.assertEqual(failed["analysis"]["run_id"], committed_run_id)
            self.assertEqual(failed["input"], committed_input)
            self.assertIsNone(failed["active_attempt"])
            self.assertEqual(failed["last_attempt"]["status"], "failed")
            self.assertIn("endpoint unavailable", failed["last_attempt"]["error"])
            self.assertEqual(load_result_package(root, verify=True), failed)

    def test_completion_rejects_stage_status_from_another_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            manifest = package_artifact_path(root, "run_manifest", for_write=True)
            manifest.write_text(json.dumps({
                "manifest_version": 2,
                "stages": {
                    "atomize": {"status": "ok", "attempt_run_id": "RUN-old"},
                    "requirements-analysis": {
                        "status": "ok", "attempt_run_id": "RUN-old",
                    },
                },
            }), encoding="utf-8")

            with self.assertRaisesRegex(Exception, "active attempt"):
                commit_analysis_completion(
                    root,
                    run_id=package["active_attempt"]["run_id"],
                    completed_stages=["atomize", "requirements-analysis"],
                )

    def test_rejecting_legacy_initialization_leaves_directory_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "blocks.jsonl"
            legacy.write_text("legacy\n", encoding="utf-8")

            with self.assertRaisesRegex(Exception, "explicit migration"):
                initialize_result_package(
                    root,
                    input_path=self._source(root),
                    requested_stages=["atomize"],
                )

            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy\n")
            self.assertFalse((root / ".ratomizer").exists())

    def test_partial_requested_stage_cannot_claim_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            manifest = package_artifact_path(root, "run_manifest", for_write=True)
            manifest.write_text(json.dumps({
                "manifest_version": 2,
                "stages": {
                    "atomize": {
                        "status": "ok",
                        "attempt_run_id": package["active_attempt"]["run_id"],
                    },
                    "requirements-analysis": {
                        "status": "partial",
                        "attempt_run_id": package["active_attempt"]["run_id"],
                    },
                },
            }), encoding="utf-8")

            with self.assertRaisesRegex(Exception, "requirements-analysis"):
                commit_analysis_completion(
                    root,
                    run_id=package["active_attempt"]["run_id"],
                    completed_stages=["atomize", "requirements-analysis"],
                )

            self.assertEqual(load_result_package(root)["analysis_status"], "running")

    def test_corrupt_marker_fails_closed_instead_of_legacy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RESULT_PACKAGE_FILE).write_text("{broken", encoding="utf-8")
            (root / "blocks.jsonl").write_text("", encoding="utf-8")

            with self.assertRaises(ResultPackageCorrupt):
                detect_result_layout(root)

    def test_legacy_directory_without_marker_remains_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blocks.jsonl").write_text("", encoding="utf-8")

            self.assertEqual(detect_result_layout(root), "legacy_flat")
            self.assertEqual(package_artifact_path(root, "blocks"), root / "blocks.jsonl")

    def test_legacy_manifest_alone_is_not_reclassified_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text("{}", encoding="utf-8")

            self.assertEqual(detect_result_layout(root), "legacy_flat")

    def test_incidental_log_files_do_not_mark_directory_as_legacy(self) -> None:
        # 回归（2026-08-03）：桌面端只读探测曾在被预览目录根留 run.log，
        # 导致新目录被误判 legacy_flat、result-package-start 永远拒绝开工。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run.log").write_text("stale log\n", encoding="utf-8")
            (root / "run_manifest.lock").write_text("", encoding="utf-8")
            (root / "llm_trace.jsonl").write_text("", encoding="utf-8")

            self.assertEqual(detect_result_layout(root), "empty")
            package = self._initialize(root)
            self.assertEqual(package["analysis_status"], "running")

    def test_marker_relative_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            package["deliverables"] = [{
                "artifact_id": "summary_md",
                "path": "../outside.md",
                "media_type": "text/markdown",
                "bytes": 1,
                "sha256": "sha256:" + "0" * 64,
            }]
            (root / RESULT_PACKAGE_FILE).write_text(
                json.dumps(package, ensure_ascii=False), encoding="utf-8",
            )

            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_unknown_user_file_is_never_moved_or_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / "my-notes.txt"
            notes.write_text("keep me", encoding="utf-8")
            package = self._initialize(root)
            self._write_completion_evidence(root)
            package_artifact_path(root, "summary_md", for_write=True).write_text(
                "done", encoding="utf-8",
            )

            commit_analysis_completion(
                root,
                run_id=package["active_attempt"]["run_id"],
                completed_stages=["atomize", "requirements-analysis"],
            )

            self.assertEqual(notes.read_text(encoding="utf-8"), "keep me")

    def test_analysis_root_round_trip_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)

            analysis_root = resolve_analysis_root(root)

            self.assertEqual(analysis_root, root / ".ratomizer" / "pipeline")
            self.assertEqual(package_root_for_analysis_root(analysis_root), root)

    def test_desktop_lifecycle_commands_use_package_root_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "result"
            root.mkdir()
            source = self._source(root)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = desktop_tasks.main([
                    "result-package-start",
                    "--out", str(root),
                    "--input", str(source),
                    "--stages", "atomize,requirements-analysis",
                ])
            self.assertEqual(exit_code, 0)
            started = json.loads(stdout.getvalue())
            self.assertEqual(started["out_dir"], str(root.resolve()))
            self.assertEqual(started["analysis_root"], str(root.resolve() / ".ratomizer" / "pipeline"))
            run_id = started["package"]["active_attempt"]["run_id"]
            self._write_completion_evidence(root)
            package_artifact_path(root, "summary_md", for_write=True).write_text(
                "done", encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = desktop_tasks.main([
                    "result-package-complete",
                    "--out", str(root),
                    "--run-id", run_id,
                    "--completed-stages", "atomize,requirements-analysis",
                ])

            self.assertEqual(exit_code, 0)
            completed = json.loads(stdout.getvalue())
            self.assertEqual(completed["package"]["analysis_status"], "completed")
            self.assertTrue((root / "summary.md").is_file())

    def test_desktop_summary_accepts_package_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)
            analysis_root = resolve_analysis_root(root)
            (analysis_root / "atomic_requirements.jsonl").write_text("", encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = desktop_tasks.main(["summary", "--out", str(root)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["out_dir"], str(root.resolve()))

    def test_governed_state_and_cache_paths_remain_flat_for_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp) / "package"
            package_root.mkdir()
            self._initialize(package_root)

            self.assertEqual(
                governed_artifact_path(
                    package_root, "clarification_answers.lock", category="state"
                ),
                package_root / ".ratomizer" / "state" / "clarification_answers.lock",
            )
            self.assertEqual(
                governed_artifact_path(
                    package_root, ANNOTATION_TRANSLATIONS, category="cache"
                ),
                package_root / ".ratomizer" / "cache" / ANNOTATION_TRANSLATIONS,
            )

            legacy_root = Path(tmp) / "legacy"
            legacy_root.mkdir()
            (legacy_root / "blocks.jsonl").write_text("", encoding="utf-8")
            self.assertEqual(
                governed_artifact_path(
                    legacy_root, "clarification_answers.lock", category="state"
                ),
                legacy_root / "clarification_answers.lock",
            )
            self.assertEqual(
                governed_artifact_path(
                    legacy_root, ANNOTATION_TRANSLATIONS, category="cache"
                ),
                legacy_root / ANNOTATION_TRANSLATIONS,
            )

    def test_clarification_state_is_hidden_and_readable_from_both_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)
            analysis_root = resolve_analysis_root(root)

            clarification_check_states.apply_clarification_check_action(
                analysis_root,
                "CLR-1",
                "verified_ok",
                evidence_fingerprint="evidence-1",
                actor="reviewer",
            )

            state_path = root / ".ratomizer" / "state" / "clarification_check_states.jsonl"
            self.assertTrue(state_path.is_file())
            self.assertFalse((analysis_root / "clarification_check_states.jsonl").exists())
            self.assertEqual(
                clarification_check_states.read_clarification_check_states(root)["CLR-1"]["actor"],
                "reviewer",
            )

    def test_hidden_review_state_feeds_summary_and_cosem_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)
            analysis_root = resolve_analysis_root(root)
            (analysis_root / "atomic_requirements.jsonl").write_text(
                json.dumps({
                    "stable_req_id": "O-CLOCK",
                    "requirement_type": "cosem_object_instance",
                    "object": "Clock",
                    "source_refs": ["TBL-1"],
                }) + "\n",
                encoding="utf-8",
            )
            (analysis_root / "table_items.jsonl").write_text(
                json.dumps({
                    "item_id": "TBL-1",
                    "fields": {
                        "Object/attribute name": "Clock",
                        "CL": "8",
                        "Value": "0-0:1.0.0.255",
                    },
                }) + "\n",
                encoding="utf-8",
            )
            governed_artifact_path(
                analysis_root, "review_states.jsonl", category="state"
            ).write_text(
                json.dumps({"requirement_id": "O-CLOCK", "status": "accepted"}) + "\n",
                encoding="utf-8",
            )

            summary = desktop_tasks.build_output_summary(analysis_root)
            model = cosem_object_model.build_object_model(analysis_root)

            self.assertEqual(summary["status_counts"], {"accepted": 1})
            self.assertEqual(model["objects"][0]["review_status"], "accepted")

    def test_annotation_translation_loader_reads_hidden_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)
            key = "translation-key"
            governed_artifact_path(
                root, ANNOTATION_TRANSLATIONS, category="cache"
            ).write_text(json.dumps({
                "items": {
                    key: {
                        "translation": "中文译文",
                        "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
                    }
                }
            }, ensure_ascii=False), encoding="utf-8")

            translations, notes = load_annotation_translations(root)

            self.assertEqual(translations, {key: "中文译文"})
            self.assertEqual(notes, {})


class ResultPackagePublicationTimingTests(unittest.TestCase):
    """2026-08-03 审查 I1/I2/I3 回归：发布时机、只读纪律与结构化错误面。"""

    def _source(self, root: Path) -> Path:
        source = root / "standard.docx"
        source.write_bytes(b"docx-fixture")
        return source

    def _start(self, root: Path, stages: str = "ai-extract") -> dict:
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = desktop_tasks.main([
                "result-package-start", "--out", str(root),
                "--input", str(self._source(root)), "--stages", stages,
            ])
        self.assertEqual(exit_code, 0)
        return json.loads(stdout.getvalue())["package"]

    def _run_ai_extract_stub(self, root: Path, summary_text: str) -> dict:
        analysis_root = resolve_analysis_root(root)

        def fake_task(out_dir: Path, **kwargs: object) -> dict:
            target = package_artifact_path(root, "summary_md", for_write=True)
            target.write_text(summary_text, encoding="utf-8")
            return {"kind": "ai_extract", "written": [str(target)]}

        stdout = StringIO()
        with (
            patch.object(desktop_tasks, "ai_extract_task", side_effect=fake_task),
            redirect_stdout(stdout),
        ):
            exit_code = desktop_tasks.main(["ai-extract", "--out", str(root)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(analysis_root, root / ".ratomizer" / "pipeline")
        return json.loads(stdout.getvalue())

    def test_summary_on_package_v1_never_publishes(self) -> None:
        # I1：只读 summary 不得触发恢复/发布写（spec §15）。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize_package(root)

            with patch.object(
                desktop_tasks,
                "publish_registered_deliverables",
                side_effect=AssertionError("readonly summary triggered publication"),
            ):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main(["summary", "--out", str(root)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["out_dir"], str(root.resolve()))

    def _initialize_package(self, root: Path) -> dict:
        return initialize_result_package(
            root,
            input_path=self._source(root),
            requested_stages=["ai-extract"],
        )

    def test_active_attempt_stage_command_defers_root_publication(self) -> None:
        # I3：活动 attempt 期间阶段命令只写 .ratomizer/pipeline，根交付物保持上一完成代。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = self._start(root)

            self._run_ai_extract_stub(root, "mid-attempt summary")

            self.assertFalse(
                (root / "summary.md").exists(),
                "mid-attempt publication replaced a root deliverable",
            )
            package = load_result_package(root)
            self.assertEqual(package["deliverables"], [])
            self.assertEqual(package["analysis_status"], "running")

            completed = commit_analysis_completion(
                root,
                run_id=started["active_attempt"]["run_id"],
                completed_stages=["ai-extract"],
            )
            self.assertEqual(
                (root / "summary.md").read_text(encoding="utf-8"),
                "mid-attempt summary",
            )
            self.assertTrue(completed["deliverables"])

    def test_failed_attempt_after_stage_writes_preserves_committed_deliverables(self) -> None:
        # I3 + spec §8.2：失败重跑后旧完成代的根交付物与 marker 清单保持字节一致。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._start(root)
            self._run_ai_extract_stub(root, "committed summary")
            commit_analysis_completion(
                root,
                run_id=first["active_attempt"]["run_id"],
                completed_stages=["ai-extract"],
            )
            committed_root_bytes = (root / "summary.md").read_bytes()
            committed = load_result_package(root)

            rerun = self._start(root)
            self._run_ai_extract_stub(root, "failed rerun summary")
            failed = record_analysis_failure(
                root,
                run_id=rerun["active_attempt"]["run_id"],
                error="endpoint unavailable",
            )

            # 根交付物与 marker 的完成代字段保持上一完成代；只有 last_attempt 记 failed。
            self.assertEqual((root / "summary.md").read_bytes(), committed_root_bytes)
            self.assertEqual(failed["analysis"], committed["analysis"])
            self.assertEqual(failed["input"], committed["input"])
            self.assertEqual(failed["deliverables"], committed["deliverables"])
            self.assertEqual(failed["analysis_status"], "completed")
            self.assertEqual(failed["last_attempt"]["status"], "failed")
            load_result_package(root, verify=True)

    def test_write_command_on_completed_package_publishes(self) -> None:
        # 白名单：已完成结果上的写命令结束后发布（维持既有"重导出即更新根交付物"行为）。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._start(root)
            self._run_ai_extract_stub(root, "committed summary")
            commit_analysis_completion(
                root,
                run_id=first["active_attempt"]["run_id"],
                completed_stages=["ai-extract"],
            )

            def fake_export(out_dir: Path, formats: list[str]) -> dict:
                target = package_artifact_path(root, "summary_md", for_write=True)
                target.write_text("re-exported summary", encoding="utf-8")
                return {"kind": "export", "written": [str(target)]}

            with patch.object(desktop_tasks, "export_task", side_effect=fake_export):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main([
                        "export", "--out", str(root), "--formats", "md",
                    ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                (root / "summary.md").read_text(encoding="utf-8"),
                "re-exported summary",
            )
            load_result_package(root, verify=True)

    def test_publication_failure_degrades_to_warning_not_crash(self) -> None:
        # I2：发布失败（锁超时/磁盘/journal）不得把已成功阶段呈现为崩溃；
        # 降级为 payload warning + marker warnings[]，run_manifest 仍记 ok。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._start(root)
            self._run_ai_extract_stub(root, "committed summary")
            commit_analysis_completion(
                root,
                run_id=first["active_attempt"]["run_id"],
                completed_stages=["ai-extract"],
            )

            def fake_export(out_dir: Path, formats: list[str]) -> dict:
                return {"kind": "export", "written": []}

            with (
                patch.object(desktop_tasks, "export_task", side_effect=fake_export),
                patch.object(
                    desktop_tasks,
                    "publish_registered_deliverables",
                    side_effect=OSError("simulated publication lock timeout"),
                ),
            ):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = desktop_tasks.main([
                        "export", "--out", str(root), "--formats", "md",
                    ])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload.get("warnings"))
            self.assertIn("publication", payload["warnings"][0])
            marker = load_result_package(root)
            self.assertTrue(marker["warnings"])
            self.assertIn("publication", marker["warnings"][-1])

    def test_partial_completion_returns_stable_error_code(self) -> None:
        # I6：请求阶段未全部成功 → exit 2 + envelope error.type=requested_stage_partial
        # （桌面端据此显示"分析未完成（部分阶段降级）"而非"运行失败"）；
        # 语义 fail-closed：不冒充 completed；R2 起 attempt 锁内终止为 partial。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = self._start(root, stages="ai-extract,requirements-analysis")
            self._run_ai_extract_stub(root, "partial summary")

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = desktop_tasks.main([
                    "result-package-complete", "--out", str(root),
                    "--run-id", started["active_attempt"]["run_id"],
                    "--completed-stages", "ai-extract,requirements-analysis",
                ])

            self.assertEqual(exit_code, 2)
            envelope = json.loads(stdout.getvalue())
            self.assertFalse(envelope["ok"])
            self.assertEqual(envelope["error"]["type"], "requested_stage_partial")
            self.assertIn("requirements-analysis", envelope["error"]["message"])
            # stderr 落同一 JSON 行（Electron 非零退出以 stderr 为错误消息）
            self.assertIn("requested_stage_partial", stderr.getvalue())
            # R2：partial 拒绝即锁内持久化终止——不再停留 running/running
            package = load_result_package(root)
            self.assertEqual(package["analysis_status"], "incomplete")
            self.assertIsNone(package["active_attempt"])
            self.assertEqual(package["last_attempt"]["status"], "partial")

    def test_result_package_start_on_legacy_returns_json_envelope(self) -> None:
        # S1/I2：legacy 硬拒走结构化 envelope（exit 2），不再裸 traceback。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "blocks.jsonl").write_text("legacy\n", encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = desktop_tasks.main([
                    "result-package-start", "--out", str(root),
                    "--input", str(self._source(root)), "--stages", "atomize",
                ])

            self.assertEqual(exit_code, 2)
            envelope = json.loads(stdout.getvalue())
            self.assertFalse(envelope["ok"])
            self.assertIn("legacy", envelope["error"]["message"])

    def test_result_package_status_verify_detects_modified_deliverable(self) -> None:
        # S5：桌面桥显式完整校验——篡改交付物后 status --verify 返回
        # result_package_modified（exit 3）；默认不带 --verify 保持纯存在性检查。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = self._start(root)
            self._run_ai_extract_stub(root, "committed summary")
            commit_analysis_completion(
                root,
                run_id=started["active_attempt"]["run_id"],
                completed_stages=["ai-extract"],
            )
            (root / "summary.md").write_text("tampered\n", encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                plain_exit = desktop_tasks.main([
                    "result-package-status", "--out", str(root),
                ])
            self.assertEqual(plain_exit, 0)

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = desktop_tasks.main([
                    "result-package-status", "--out", str(root), "--verify",
                ])

            self.assertEqual(exit_code, 3)
            envelope = json.loads(stdout.getvalue())
            self.assertFalse(envelope["ok"])
            self.assertEqual(envelope["error"]["type"], "result_package_modified")
            self.assertIn("结果文件已被修改", envelope["error"]["message"])

    def test_result_package_status_with_corrupt_marker_returns_exit_3(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / RESULT_PACKAGE_FILE).write_text("{broken", encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = desktop_tasks.main([
                    "result-package-status", "--out", str(root),
                ])

            self.assertEqual(exit_code, 3)
            envelope = json.loads(stdout.getvalue())
            self.assertFalse(envelope["ok"])
            self.assertEqual(envelope["error"]["type"], "result_package_corrupt")

    def test_command_with_interrupted_journal_returns_structured_error(self) -> None:
        # I2：前置布局探测遇残留发布 journal 不得裸 traceback。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize_package(root)
            journal = root / ".ratomizer" / "stages" / ".result-package-publication.json"
            journal.write_text("{}", encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = desktop_tasks.main(["summary", "--out", str(root)])

            self.assertEqual(exit_code, 3)
            envelope = json.loads(stdout.getvalue())
            self.assertFalse(envelope["ok"])
            self.assertEqual(envelope["error"]["type"], "result_package_corrupt")

    def test_update_run_manifest_tolerates_corrupt_marker(self) -> None:
        # I2：marker 损坏时阶段记账退化为警告，不戳破"写失败不阻断"契约。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize_package(root)
            analysis_root = resolve_analysis_root(root)

            with patch.object(
                desktop_tasks,
                "load_result_package",
                side_effect=ResultPackageCorrupt("simulated corrupt marker"),
            ):
                desktop_tasks.update_run_manifest(analysis_root, "ai-extract", "ok")

            manifest = package_artifact_path(root, "run_manifest")
            self.assertTrue(manifest.is_file())


class PublishRaceAndPartialPersistenceTests(unittest.TestCase):
    """2026-08-03 复审残余项回归：R1 发布并发窗口、R2 partial 状态持久化。"""

    def _source(self, root: Path) -> Path:
        source = root / "standard.docx"
        source.write_bytes(b"docx-fixture")
        return source

    def _start(self, root: Path, stages: str = "ai-extract") -> dict:
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = desktop_tasks.main([
                "result-package-start", "--out", str(root),
                "--input", str(self._source(root)), "--stages", stages,
            ])
        self.assertEqual(exit_code, 0)
        return json.loads(stdout.getvalue())["package"]

    def _run_ai_extract_stub(self, root: Path, summary_text: str) -> dict:
        def fake_task(out_dir: Path, **kwargs: object) -> dict:
            target = package_artifact_path(root, "summary_md", for_write=True)
            target.write_text(summary_text, encoding="utf-8")
            return {"kind": "ai_extract", "written": [str(target)]}

        stdout = StringIO()
        with (
            patch.object(desktop_tasks, "ai_extract_task", side_effect=fake_task),
            redirect_stdout(stdout),
        ):
            exit_code = desktop_tasks.main(["ai-extract", "--out", str(root)])
        self.assertEqual(exit_code, 0)
        return json.loads(stdout.getvalue())

    def test_locked_publish_refuses_during_active_attempt(self) -> None:
        # R1：publish_registered_deliverables 必须在写锁临界区内复查
        # active_attempt——锁外检查与锁内发布之间另一进程可启动新 attempt，
        # 此时发布会把新 attempt 的 pipeline 内容复制到根交付物。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._start(root)
            package_artifact_path(root, "summary_md", for_write=True).write_text(
                "NEW-ACTIVE-ATTEMPT", encoding="utf-8",
            )

            with self.assertRaises(ResultPackageError):
                publish_registered_deliverables(root)

            self.assertFalse((root / "summary.md").exists())

    def test_stale_check_snapshot_cannot_publish_new_attempt_pipeline(self) -> None:
        # R1 确定性复现（审核实测：published=True、marker 仍有活动 attempt、
        # 根 summary.md 变成 NEW-ACTIVE-ATTEMPT）：本进程持"无活动 attempt"的
        # 锁外旧快照，另一进程已启动新 attempt——发布必须被拒。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._start(root)
            self._run_ai_extract_stub(root, "committed summary")
            commit_analysis_completion(
                root,
                run_id=first["active_attempt"]["run_id"],
                completed_stages=["ai-extract"],
            )
            committed_root_bytes = (root / "summary.md").read_bytes()
            stale_snapshot = load_result_package(root)

            self._start(root)  # 另一"进程"启动新 attempt
            package_artifact_path(root, "summary_md", for_write=True).write_text(
                "NEW-ACTIVE-ATTEMPT", encoding="utf-8",
            )

            payload: dict = {"kind": "export", "written": []}
            with patch.object(
                desktop_tasks, "load_result_package", return_value=stale_snapshot,
            ):
                published = desktop_tasks._maybe_publish_after_command(
                    "export", root, payload,
                )

            self.assertIsNone(published)
            self.assertEqual((root / "summary.md").read_bytes(), committed_root_bytes)
            self.assertTrue(payload.get("warnings"))
            load_result_package(root, verify=True)

    def test_partial_completion_persists_terminated_partial_attempt(self) -> None:
        # R2（审核实测：完成命令返回 requested_stage_partial 后磁盘 marker 仍是
        # running/running，重开结果再次显示"运行中"）：partial 拒绝即锁内终止
        # attempt 并持久化——重开显示"未完成"；attempt 已终止，重跑走新 attempt。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = self._start(root, stages="ai-extract,requirements-analysis")
            self._run_ai_extract_stub(root, "partial summary")

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = desktop_tasks.main([
                    "result-package-complete", "--out", str(root),
                    "--run-id", started["active_attempt"]["run_id"],
                    "--completed-stages", "ai-extract,requirements-analysis",
                ])

            self.assertEqual(exit_code, 2)
            envelope = json.loads(stdout.getvalue())
            self.assertEqual(envelope["error"]["type"], "requested_stage_partial")
            package = load_result_package(root)
            self.assertEqual(package["analysis_status"], "incomplete")
            self.assertIsNone(package["active_attempt"])
            self.assertEqual(
                package["last_attempt"]["run_id"],
                started["active_attempt"]["run_id"],
            )
            self.assertEqual(package["last_attempt"]["status"], "partial")
            self.assertEqual(
                [item["artifact_id"] for item in package["deliverables"]],
                ["summary_md"],
            )
            self.assertEqual((root / "summary.md").read_text(encoding="utf-8"), "partial summary")
            load_result_package(root, verify=True)
            # 重跑（新 attempt）不受终止影响
            rerun = self._start(root, stages="ai-extract,requirements-analysis")
            self.assertEqual(rerun["analysis_status"], "running")

    def test_partial_completion_preserves_previous_completed_generation(self) -> None:
        # R2：已有完成代时的 partial 重跑只更新 last_attempt——analysis/input/
        # deliverables 与根交付物保持上一完成代字节一致，verify 仍通过。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._start(root)
            self._run_ai_extract_stub(root, "committed summary")
            commit_analysis_completion(
                root,
                run_id=first["active_attempt"]["run_id"],
                completed_stages=["ai-extract"],
            )
            committed_root_bytes = (root / "summary.md").read_bytes()
            committed = load_result_package(root)

            rerun = self._start(root, stages="ai-extract,requirements-analysis")
            self._run_ai_extract_stub(root, "partial rerun summary")
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = desktop_tasks.main([
                    "result-package-complete", "--out", str(root),
                    "--run-id", rerun["active_attempt"]["run_id"],
                    "--completed-stages", "ai-extract,requirements-analysis",
                ])

            self.assertEqual(exit_code, 2)
            package = load_result_package(root)
            self.assertEqual(package["analysis_status"], "completed")
            self.assertEqual(package["analysis"], committed["analysis"])
            self.assertEqual(package["input"], committed["input"])
            self.assertEqual(package["deliverables"], committed["deliverables"])
            self.assertEqual(package["last_attempt"]["status"], "partial")
            self.assertEqual((root / "summary.md").read_bytes(), committed_root_bytes)
            load_result_package(root, verify=True)


class ClaimGenerationGatePackageLayoutTests(unittest.TestCase):
    """B1 回归（2026-08-03）：claim_generation.meta.json 在 package_v1 下落
    .ratomizer/state/，裸路径闸门会把启动维护与裁决后 fold 钩子静默跳过。"""

    def _package_v1_analysis_root(self, root: Path) -> Path:
        source = root / "standard.docx"
        source.write_bytes(b"docx-fixture")
        initialize_result_package(
            root, input_path=source, requested_stages=["atomize"],
        )
        analysis_root = resolve_analysis_root(root)
        governed_artifact_path(
            analysis_root, "claim_generation.meta.json", category="state",
        ).write_text("{}", encoding="utf-8")
        return analysis_root

    def test_expert_decision_fold_hook_fires_for_package_v1(self) -> None:
        import review_state

        with tempfile.TemporaryDirectory() as tmp:
            analysis_root = self._package_v1_analysis_root(Path(tmp))

            with patch(
                "claim_review_actions.fold_effective_ledger"
            ) as fold:
                review_state.apply_expert_decision(
                    analysis_root, "REQ-1", "accepted", actor="tester",
                )

            fold.assert_called_once()

    def test_ai_review_action_fold_hook_fires_for_package_v1(self) -> None:
        import ai_review_actions

        with tempfile.TemporaryDirectory() as tmp:
            analysis_root = self._package_v1_analysis_root(Path(tmp))

            with patch(
                "claim_review_actions.fold_effective_ledger"
            ) as fold:
                ai_review_actions.apply_ai_review_action(
                    analysis_root, "AIR-1", "accepted", actor="tester",
                )

            fold.assert_called_once()

    def test_legacy_layout_fold_hook_still_fires(self) -> None:
        import review_state

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "claim_generation.meta.json").write_text("{}", encoding="utf-8")

            with patch(
                "claim_review_actions.fold_effective_ledger"
            ) as fold:
                review_state.apply_expert_decision(
                    root, "REQ-1", "accepted", actor="tester",
                )

            fold.assert_called_once()


class MarkerContractHardeningTests(unittest.TestCase):
    """PR4（2026-08-03 清单 S3/S4/S6）：路径安全边角、marker 校验与 schema 对齐、
    只读路径不建目录。"""

    def _initialize(self, root: Path) -> dict:
        source = root / "standard.docx"
        source.write_bytes(b"docx-fixture")
        return initialize_result_package(
            root, input_path=source, requested_stages=["atomize"],
        )

    def _rewrite_marker(self, root: Path, mutate) -> None:
        marker_path = root / RESULT_PACKAGE_FILE
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        mutate(marker)
        marker_path.write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    def test_safe_relative_path_rejects_dot_segments(self) -> None:
        # S3：PurePosixPath(".").parts 为空，此前 parts[0] 抛裸 IndexError 绕过
        # ResultPackageCorrupt——路径穿越防线的唯一关口必须 fail-closed 成结构化错误
        import result_package

        for value in (".", "./"):
            with self.assertRaises(ResultPackageCorrupt, msg=value):
                result_package._safe_relative_path(value, label="deliverable path")

    def test_safe_relative_path_rejects_drive_relative_first_segment(self) -> None:
        # S3："C:foo" 是盘符相对路径，首段含 ":" 但不以 ":" 结尾，此前漏检
        import result_package

        for value in ("C:foo", "C:foo/bar"):
            with self.assertRaises(ResultPackageCorrupt, msg=value):
                result_package._safe_relative_path(value, label="deliverable path")

    def test_validate_package_requires_package_id(self) -> None:
        # S4：schemas/result_package.schema.json 要求 package_id 且 ^RPK-[0-9a-f]+
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)

            self._rewrite_marker(root, lambda marker: marker.pop("package_id"))
            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_validate_package_rejects_malformed_package_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)

            self._rewrite_marker(
                root, lambda marker: marker.update(package_id="PKG-123"),
            )
            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_validate_package_requires_tool_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)

            self._rewrite_marker(root, lambda marker: marker.pop("tool"))
            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_validate_package_requires_matching_tool_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)

            self._rewrite_marker(
                root,
                lambda marker: marker["tool"].update(output_layout_version="other-layout"),
            )
            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_validate_package_requires_string_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)

            self._rewrite_marker(
                root, lambda marker: marker.update(warnings=["ok", 1]),
            )
            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_validate_package_rejects_unknown_top_level_keys(self) -> None:
        # S4：schema additionalProperties=false——外来/手工 marker 不得带病通过
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)

            self._rewrite_marker(root, lambda marker: marker.update(surprise={}))
            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_validate_package_rejects_unknown_nested_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)

            self._rewrite_marker(
                root, lambda marker: marker["input"].update(surprise={}),
            )
            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_validate_package_rejects_empty_completion_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = self._initialize(root)
            active = package["active_attempt"]

            def complete_without_evidence(marker: dict) -> None:
                marker["analysis_status"] = "completed"
                marker["active_attempt"] = None
                marker["last_attempt"] = {
                    "run_id": active["run_id"],
                    "status": "completed",
                    "finished_at": active["started_at"],
                }
                marker["analysis"] = {
                    "run_id": active["run_id"],
                    "started_at": active["started_at"],
                    "completed_at": active["started_at"],
                    "requested_stages": ["atomize"],
                    "completed_stages": ["atomize"],
                    "completion_evidence": [],
                }

            self._rewrite_marker(root, complete_without_evidence)
            with self.assertRaises(ResultPackageCorrupt):
                load_result_package(root)

    def test_readonly_governed_path_does_not_create_directories(self) -> None:
        # S6：只读解析不得落盘——for_write=False 纯解析，for_write=True 才建父目录
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)
            shutil.rmtree(root / ".ratomizer" / "state")

            resolved = governed_artifact_path(
                root, "review_states.jsonl", category="state", for_write=False,
            )
            self.assertEqual(
                resolved, (root / ".ratomizer" / "state" / "review_states.jsonl").resolve(),
            )
            self.assertFalse((root / ".ratomizer" / "state").exists())

            governed_artifact_path(root, "review_states.jsonl", category="state")
            self.assertTrue((root / ".ratomizer" / "state").is_dir())

    def test_package_artifact_path_readonly_does_not_create_directories(self) -> None:
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)
            shutil.rmtree(root / ".ratomizer" / "stages")

            resolved = package_artifact_path(root, "run_manifest")
            self.assertFalse((root / ".ratomizer" / "stages").exists())
            self.assertEqual(
                resolved,
                (root / ".ratomizer" / "stages" / "run_manifest.json").resolve(),
            )

            package_artifact_path(root, "run_manifest", for_write=True)
            self.assertTrue((root / ".ratomizer" / "stages").is_dir())

    def test_claim_view_read_does_not_create_internal_directories(self) -> None:
        # S6 消费方回归：claim 只读视图不得自称"无副作用"却在盘上建空目录
        import shutil

        import claim_views

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._initialize(root)
            analysis_root = resolve_analysis_root(root)
            shutil.rmtree(root / ".ratomizer" / "state")

            self.assertTrue(claim_views._has_no_generation(analysis_root))
            self.assertFalse((root / ".ratomizer" / "state").exists())


if __name__ == "__main__":
    unittest.main()
