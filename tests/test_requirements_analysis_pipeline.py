import json
from pathlib import Path

from openpyxl import load_workbook

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


def test_run_requirements_analysis_applies_review_state_for_raw_ai_requirement(tmp_path: Path):
    from ai_review_actions import ai_req_id

    req = {
        "description": "The meter shall support Clock object daylight saving time.",
        "source_quote": "support Clock object daylight saving time",
        "source_block_ids": ["B-1"],
        "module": "时钟需求",
    }
    computed_id = ai_req_id(req)
    write_jsonl(tmp_path / "ai_requirements.jsonl", [req])
    write_jsonl(tmp_path / "ai_review_states.jsonl", [
        {"ai_req_id": computed_id, "ownership_override": "co_design", "reason": "人工改为协同"}
    ])

    run_requirements_analysis(tmp_path, route="stub", template_path=None)

    payload = json.loads((tmp_path / "engineering_analysis.json").read_text(encoding="utf-8"))
    item = payload["items"][0]
    assert item["source_requirement_ids"] == [computed_id]
    assert item["ownership"] == "co_design"
    assert item["ownership_source"] == "reviewer_override"


def test_software_workbook_excludes_hardware_and_includes_codesign(tmp_path: Path):
    write_jsonl(tmp_path / "ai_requirements.jsonl", [
        {
            "ai_req_id": "AI-1",
            "description": "The meter shall support push notification.",
            "source_quote": "support push notification",
            "source_block_ids": ["B-1"],
            "module": "push需求",
        },
        {
            "ai_req_id": "AI-2",
            "description": "计量芯片型号为 Att7022e。",
            "source_quote": "计量芯片型号为 Att7022e",
            "source_block_ids": ["B-2"],
            "module": "计量需求",
        },
        {
            "ai_req_id": "AI-3",
            "description": "波特率最大值与硬件相关，需要驱动适配。",
            "source_quote": "波特率最大值与硬件相关",
            "source_block_ids": ["B-3"],
            "module": "协议栈需求",
        },
    ])

    run_requirements_analysis(tmp_path, route="stub", template_path=None)

    wb = load_workbook(tmp_path / "software_requirements.xlsx", data_only=True)
    values = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=2, values_only=True):
            if any(row):
                values.append(row)

    descriptions = [str(row[3] or "") for row in values]
    hardware_flags = [str(row[9] or "") for row in values]
    assert any("push" in value.lower() for value in descriptions)
    assert not any("计量芯片" in value for value in descriptions)
    assert "是" in hardware_flags


def test_parse_args_rejects_unknown_route():
    from requirements_analysis import parse_args

    try:
        parse_args(["--out", ".", "--route", "bad"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit")
