from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from parsers.docx_parser import DocxParser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a source document into Requirement Atomizer Document IR.")
    parser.add_argument("input", type=Path, help="Input .docx file")
    parser.add_argument("--out", type=Path, required=True, help="Output DocumentIR JSON path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    out_path = args.out.expanduser().resolve()
    if input_path.suffix.lower() != ".docx":
        print("Only .docx input is supported by the current parser.", file=sys.stderr)
        return 2
    doc_ir = DocxParser().parse(input_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc_ir.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "doc_id": doc_ir.doc_id,
                "source_format": doc_ir.source_format,
                "blocks": len(doc_ir.blocks),
                "out": str(out_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
