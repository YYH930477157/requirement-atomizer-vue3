from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


STOPWORDS = {
    "THE",
    "AND",
    "FOR",
    "WITH",
    "THIS",
    "THAT",
    "FROM",
    "TABLE",
    "FIGURE",
    "STANDARD",
    "BRAZILIAN",
    "REQUIREMENTS",
}


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def candidate_terms(text: str) -> Iterable[str]:
    text = text.replace("–", "-").replace("—", "-")

    for match in re.finditer(r"\b(?:IEC|ISO|ABNT|NBR|EN|IEEE)\s*\d{3,6}(?:-\d+)*(?::\d{4})?\b", text, flags=re.I):
        yield normalize(match.group(0))

    for match in re.finditer(r"\b[A-Z][A-Z0-9]{1,}(?:/[A-Z0-9]{2,})+\b", text):
        yield normalize(match.group(0))

    for match in re.finditer(r"\b[A-Z]{2,}(?:-[A-Z0-9]{2,})+\b", text):
        yield normalize(match.group(0))

    for match in re.finditer(r"\b[A-Z]{2,8}\b", text):
        term = normalize(match.group(0))
        if term not in STOPWORDS:
            yield term

    for match in re.finditer(r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,}|of|and|for)){1,5}\b", text):
        term = normalize(match.group(0))
        if len(term) > 5:
            yield term


def normalize(term: str) -> str:
    term = re.sub(r"\s+", " ", term.strip())
    return term


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract candidate domain terms from atomizer outputs.")
    parser.add_argument("input", type=Path, help="blocks.jsonl, chunks.jsonl, table_items.jsonl, or a directory containing them")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path")
    parser.add_argument("--min-count", type=int, default=2, help="Minimum occurrence count")
    parser.add_argument("--limit", type=int, default=300, help="Maximum terms to output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    if input_path.is_dir():
        files = [p for p in [input_path / "blocks.jsonl", input_path / "table_items.jsonl"] if p.exists()]
    else:
        files = [input_path]

    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}

    for file in files:
        for row in iter_jsonl(file):
            parts = [row.get("text", ""), row.get("table_title", "")]
            fields = row.get("fields")
            if isinstance(fields, dict):
                parts.extend(str(v) for v in fields.values())
            text = " ".join(str(part) for part in parts if part)
            for term in candidate_terms(text):
                counts[term] += 1
                examples.setdefault(term, text[:300])

    rows = [
        {"term": term, "count": count, "example": examples.get(term, "")}
        for term, count in counts.most_common(args.limit)
        if count >= args.min_count
    ]

    out_path = args.out.expanduser().resolve() if args.out else input_path / "candidate_terms.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out_path), "terms": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

