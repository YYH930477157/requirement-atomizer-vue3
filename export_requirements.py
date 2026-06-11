from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


CSV_COLUMNS = [
    "req_id",
    "stable_req_id",
    "requirement_type",
    "domain",
    "object",
    "requirement",
    "condition",
    "verification_method",
    "confidence",
    "ambiguity",
    "review_status",
    "source_refs",
    "section_path",
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def export_requirements(out_dir: Path, *, formats: Iterable[str], status: str = "all") -> list[str]:
    out_dir = out_dir.expanduser().resolve()
    requirements = read_jsonl(out_dir / "atomic_requirements.jsonl")
    states_by_id = review_states_by_id(read_jsonl(out_dir / "review_states.jsonl"))
    rows = [format_row(row, states_by_id) for row in requirements]
    if status != "all":
        rows = [row for row in rows if row["review_status"] == status]

    written: list[str] = []
    for item in formats:
        fmt = item.strip().lower()
        if not fmt:
            continue
        if fmt == "csv":
            write_csv(out_dir / "requirements_export.csv", rows)
            written.append("requirements_export.csv")
        elif fmt == "md":
            write_markdown(out_dir / "requirements_export.md", rows)
            written.append("requirements_export.md")
        else:
            raise ValueError(f"unsupported export format: {item}")
    return written


def review_states_by_id(states: list[dict[str, Any]]) -> dict[str, str]:
    by_id: dict[str, str] = {}
    for state in states:
        requirement_id = str(state.get("requirement_id") or "")
        if requirement_id:
            by_id[requirement_id] = str(state.get("status") or "candidate")
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        for key in ("stable_req_id", "req_id"):
            value = str(metadata.get(key) or "")
            if value:
                by_id[value] = str(state.get("status") or "candidate")
    return by_id


def format_row(row: dict[str, Any], states_by_id: dict[str, str]) -> dict[str, Any]:
    stable_req_id = str(row.get("stable_req_id") or "")
    req_id = str(row.get("req_id") or "")
    review_status = states_by_id.get(stable_req_id) or states_by_id.get(req_id) or "candidate"
    return {
        "req_id": req_id,
        "stable_req_id": stable_req_id,
        "requirement_type": row.get("requirement_type", ""),
        "domain": row.get("domain", ""),
        "object": row.get("object", ""),
        "requirement": row.get("requirement", ""),
        "condition": row.get("condition") or "",
        "verification_method": row.get("verification_method", ""),
        "confidence": row.get("confidence", ""),
        "ambiguity": row.get("ambiguity", ""),
        "review_status": review_status,
        "source_refs": join_values(row.get("source_refs", [])),
        "section_path": join_values(row.get("section_path", [])),
    }


def join_values(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("requirement_type") or "unknown")].append(row)

    lines = ["# Requirements Export", ""]
    for requirement_type in sorted(grouped):
        lines.extend([f"## {requirement_type}", ""])
        for row in grouped[requirement_type]:
            source_refs = row.get("source_refs") or ""
            lines.append(
                f"- `{row.get('req_id')}` {row.get('requirement')} "
                f"(confidence: {row.get('confidence')}, status: {row.get('review_status')}, source: {source_refs})"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export atomic requirements to Markdown or CSV.")
    parser.add_argument("--out", type=Path, required=True, help="Atomizer output directory")
    parser.add_argument("--format", choices=["md", "csv"], required=True)
    parser.add_argument("--status", default="all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    written = export_requirements(args.out, formats=[args.format], status=args.status)
    print(json.dumps({"out": str(args.out.expanduser().resolve()), "exports": written}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
