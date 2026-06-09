from __future__ import annotations

from pathlib import Path

from atomize import extract_docx, mark_doc_regions
from doc_ir import DocumentIR, blocks_to_doc_ir
from parsers.base import DocumentParser


class DocxParser(DocumentParser):
    source_format = "docx"

    def parse(self, path: Path) -> DocumentIR:
        input_path = path.expanduser().resolve()
        blocks, table_items = extract_docx(input_path, knowledge_bases=[])
        mark_doc_regions(blocks, table_items)
        return blocks_to_doc_ir(blocks=blocks, table_items=table_items, source_path=input_path)
