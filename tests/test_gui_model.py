from __future__ import annotations

import csv
import getpass
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pyside6 = importlib.util.find_spec("PySide6")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@unittest.skipIf(pyside6 is None, "PySide6 not installed")
class GuiModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_requirements_model_loads_rows_and_proxy_filters(self) -> None:
        from gui.requirements_model import RequirementsFilterProxyModel, RequirementsTableModel, load_output_bundle

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir)

            bundle = load_output_bundle(out_dir)
            model = RequirementsTableModel()
            model.set_bundle(bundle)
            proxy = RequirementsFilterProxyModel()
            proxy.setSourceModel(model)

            self.assertEqual(model.rowCount(), 2)
            self.assertEqual(model.data(model.index(0, 0)), "AREQ-1")
            proxy.set_type_filter("security")
            self.assertEqual(proxy.rowCount(), 1)
            proxy.set_status_filter("accepted")
            self.assertEqual(proxy.rowCount(), 1)
            proxy.set_min_confidence(0.95)
            self.assertEqual(proxy.rowCount(), 0)
            proxy.set_min_confidence(0.0)
            proxy.set_text_filter("HLS")
            self.assertEqual(proxy.rowCount(), 1)
            proxy.set_ambiguous_only(True)
            self.assertEqual(proxy.rowCount(), 0)

    def test_main_window_loads_output_dir_and_status_counts(self) -> None:
        from PySide6.QtWidgets import QHeaderView

        from gui.main_window import MainWindow
        from gui.requirements_model import HEADERS

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir)

            window = MainWindow()
            window.load_output_dir(out_dir)

            self.assertEqual(window.model.rowCount(), 2)
            self.assertEqual(window.model.data(window.model.index(0, 0)), "AREQ-1")
            self.assertEqual(window.total_card.value_label.text(), "2")
            self.assertEqual(window.accepted_card.value_label.text(), "1")
            self.assertIsNone(window.pinned_source_row)
            self.assertTrue(window.table.currentIndex().isValid())
            self.assertEqual(window.table.horizontalHeader().sectionResizeMode(HEADERS.index("requirement")), QHeaderView.Stretch)
            self.assertGreaterEqual(window.detail_panel.metadata_widget.minimumHeight(), 170)

    def test_count_label_uses_visible_and_total_rows(self) -> None:
        from gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir)
            window = MainWindow()
            window.load_output_dir(out_dir)

            self.assertEqual(window.table_count_label.text(), f"显示 {window.proxy.rowCount()} / 2")
            window.set_combo_to_data(window.status_filter, "accepted")

            self.assertEqual(window.table_count_label.text(), "显示 1 / 2")

    def test_status_card_resets_filters_once_and_counts_match_visible_rows(self) -> None:
        from gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir)
            window = MainWindow()
            window.load_output_dir(out_dir)
            window.confidence_filter.setValue(0.95)
            calls = 0
            original_refresh = window.proxy.refresh_filter

            def counted_refresh() -> None:
                nonlocal calls
                calls += 1
                original_refresh()

            window.proxy.refresh_filter = counted_refresh

            window.apply_status_card_filter("accepted")

            self.assertEqual(calls, 1)
            self.assertEqual(window.confidence_filter.value(), 0.0)
            self.assertEqual(window.proxy.rowCount(), 1)
            self.assertEqual(window.table_count_label.text(), "显示 1 / 2")

    def test_decision_failure_is_visible(self) -> None:
        from gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir)
            window = MainWindow()
            window.load_output_dir(out_dir)

            with patch("gui.main_window.apply_review_action", side_effect=ValueError("frozen row")), patch(
                "gui.main_window.QMessageBox.warning"
            ) as warning:
                window.apply_decision("accepted")

        warning.assert_called_once()

    def test_next_row_under_filter_does_not_skip_rows(self) -> None:
        from gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir, candidate_count=5)
            window = MainWindow()
            window.load_output_dir(out_dir)
            window.set_combo_to_data(window.status_filter, "candidate")
            self.assertEqual(window.proxy.rowCount(), 5)

            visited: list[str] = []
            for _ in range(5):
                current = window.table.currentIndex()
                row = window.model.row_at(window.proxy.mapToSource(current).row())
                visited.append(str(row["stable_req_id"]))
                window.apply_decision("accepted")

        self.assertEqual(visited, [f"SREQ-C{i}" for i in range(5)])

    def test_gui_app_smoke_constructs_window_without_event_loop(self) -> None:
        from gui.app import main

        self.assertEqual(main(["ratomizer-gui", "--smoke"]), 0)

    def test_open_output_uses_async_loader(self) -> None:
        from gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir)
            window = MainWindow()
            calls: list[Path] = []
            window.load_output_dir_async = calls.append

            window.open_output_dir(out_dir)

        self.assertEqual(calls, [out_dir])

    def test_review_action_updates_state_and_cli_export_uses_same_status(self) -> None:
        from export_requirements import export_requirements
        from review_actions import apply_review_action

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir)

            apply_review_action(out_dir, "SREQ-1", "accepted", actor="gui-test", reason="accepted in GUI")
            export_requirements(out_dir, formats=["csv"], status="accepted")

            with (out_dir / "requirements_export.csv").open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual([row["req_id"] for row in rows], ["AREQ-1", "AREQ-2"])

    def test_review_action_defaults_actor_to_current_user(self) -> None:
        from review_actions import apply_review_action

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            self.write_output_fixture(out_dir)

            apply_review_action(out_dir, "SREQ-1", "accepted")

            events = read_jsonl(out_dir / "review_state_events.jsonl")

        self.assertEqual(events[-1]["actor"], getpass.getuser())

    def write_output_fixture(self, out_dir: Path, *, candidate_count: int = 0) -> None:
        extra_candidates = [
            {
                "req_id": f"AREQ-C{i}",
                "stable_req_id": f"SREQ-C{i}",
                "requirement_type": "communication",
                "domain": "communication",
                "object": f"Candidate {i}",
                "requirement": f"The meter shall support candidate behavior {i}.",
                "confidence": 0.9,
                "ambiguity": False,
                "source_refs": ["BLK-1"],
                "kb_matches": [],
            }
            for i in range(candidate_count)
        ]
        write_jsonl(
            out_dir / "atomic_requirements.jsonl",
            extra_candidates
            or [
                {
                    "req_id": "AREQ-1",
                    "stable_req_id": "SREQ-1",
                    "requirement_type": "communication",
                    "domain": "communication",
                    "object": "Meter",
                    "requirement": "The meter shall support xDLMS GET service.",
                    "confidence": 0.68,
                    "ambiguity": True,
                    "source_refs": ["BLK-1"],
                    "kb_matches": [{"name": "xDLMS", "definition": "Protocol service"}],
                },
                {
                    "req_id": "AREQ-2",
                    "stable_req_id": "SREQ-2",
                    "requirement_type": "security",
                    "domain": "security",
                    "object": "Association",
                    "requirement": "Associations shall use HLS.",
                    "confidence": 0.9,
                    "ambiguity": False,
                    "source_refs": ["TBL-1-R1"],
                    "kb_matches": [],
                },
            ],
        )
        write_jsonl(
            out_dir / "review_states.jsonl",
            []
            if extra_candidates
            else [
                    {"requirement_id": "SREQ-1", "status": "expert_pending", "metadata": {"req_id": "AREQ-1"}},
                    {"requirement_id": "SREQ-2", "status": "accepted", "metadata": {"req_id": "AREQ-2"}},
                ],
        )
        write_jsonl(
            out_dir / "llm_review_results.jsonl",
            []
            if extra_candidates
            else [{"requirement_id": "SREQ-1", "decision": "needs_expert", "risk": "high_risk"}],
        )
        write_jsonl(out_dir / "blocks.jsonl", [{"block_id": "BLK-1", "text": "The meter shall support xDLMS GET service."}])
        write_jsonl(out_dir / "table_items.jsonl", [{"item_id": "TBL-1-R1", "fields": {"Requirement": "Associations shall use HLS."}}])


if __name__ == "__main__":
    unittest.main()
