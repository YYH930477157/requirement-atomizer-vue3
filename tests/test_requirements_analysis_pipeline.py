import json
from pathlib import Path

from requirements_analysis import run_requirements_analysis


def write_jsonl(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_run_requirements_analysis_writes_json_and_reports(tmp_path: Path):
    write_jsonl(tmp_path / "ai_requirements.jsonl", [
        {
            "ai_req_id": "AI-1",
            "title": "Clock",
            "description": "The meter shall support Clock object daylight saving time.",
            "source_quote": "support Clock object daylight saving time",
            "source_block_ids": ["B-1"],
            "module": "时钟需求",
        },
        {
            "ai_req_id": "AI-2",
            "description": "计量芯片型号为 Att7022e。",
            "source_quote": "计量芯片型号为 Att7022e",
            "source_block_ids": ["B-2"],
            "module": "计量需求",
        },
    ])
    write_jsonl(tmp_path / "ai_review_states.jsonl", [
        {"ai_req_id": "AI-2", "ownership_override": "co_design", "reason": "软件需适配驱动"}
    ])

    result = run_requirements_analysis(tmp_path, route="stub", template_path=None)

    assert result["analysis_count"] == 2
    assert (tmp_path / "engineering_analysis.json").exists()
    assert (tmp_path / "hardware_items.md").exists()
    payload = json.loads((tmp_path / "engineering_analysis.json").read_text(encoding="utf-8"))
    by_id = {row["source_requirement_ids"][0]: row for row in payload["items"]}
    assert by_id["AI-2"]["ownership"] == "co_design"
    assert by_id["AI-2"]["ownership_source"] == "reviewer_override"


def test_run_requirements_analysis_fills_base_item_contract(tmp_path: Path):
    write_jsonl(tmp_path / "ai_requirements.jsonl", [
        {
            "stable_req_id": "STABLE-1",
            "description": "The meter shall support this feature.",
            "source_block_ids": [101],
        }
    ])

    run_requirements_analysis(tmp_path, route="stub", template_path=None)

    payload = json.loads((tmp_path / "engineering_analysis.json").read_text(encoding="utf-8"))
    item = payload["items"][0]
    assert item["source_kind"] == "ai_requirement"
    assert item["source_requirement_ids"] == ["STABLE-1"]
    assert item["source_block_ids"] == ["101"]
    assert item["software_requirement_text"] == ""


def test_parse_args_rejects_unknown_route():
    from requirements_analysis import parse_args

    try:
        parse_args(["--out", ".", "--route", "bad"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit")
