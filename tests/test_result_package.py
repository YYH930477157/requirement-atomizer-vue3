from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
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


if __name__ == "__main__":
    unittest.main()
