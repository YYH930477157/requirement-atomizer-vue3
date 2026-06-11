from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


BlockType = Literal["heading", "paragraph", "table", "figure", "list", "equation", "footnote"]
SUPPORTED_BLOCK_TYPES = {"heading", "paragraph", "table", "figure", "list", "equation", "footnote"}


@dataclass
class Provenance:
    source_format: str
    source_path: str = ""
    block_id: str = ""
    table_id: str = ""
    row_id: str = ""
    page_ref: str = ""
    locator: str = ""


@dataclass
class TableIR:
    table_id: str
    title: str
    headers: list[str]
    rows: list[dict[str, Any]]
    header_rows: list[list[str]] = field(default_factory=list)
    table_type: str = "unknown"


@dataclass
class BlockIR:
    block_id: str
    block_type: BlockType
    order: int
    text_original: str
    text_normalized: str
    section_path: list[str]
    provenance: Provenance
    lang: str = "und"
    metadata: dict[str, Any] = field(default_factory=dict)
    table: TableIR | None = None


@dataclass
class DocumentIR:
    doc_id: str
    title: str
    source_format: str
    source_path: str
    blocks: list[BlockIR]
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "0.1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def blocks_to_doc_ir(
    *,
    blocks: list[dict[str, Any]],
    table_items: list[dict[str, Any]],
    source_path: Path,
    doc_id: str | None = None,
) -> DocumentIR:
    table_items_by_block: dict[str, list[dict[str, Any]]] = {}
    for item in table_items:
        table_items_by_block.setdefault(str(item.get("table_block_id", "")), []).append(item)

    ir_blocks: list[BlockIR] = []
    for block in blocks:
        block_id = str(block.get("block_id", ""))
        block_type = str(block.get("type", "paragraph"))
        metadata = {key: value for key, value in block.items() if key not in {"block_id", "type", "order", "text", "section_path"}}
        table_ir = None
        if block_type == "table":
            rows = table_items_by_block.get(block_id, [])
            table_ir = TableIR(
                table_id=str(block.get("table_id", "")),
                title=str(block.get("table_title", "")),
                headers=list(block.get("headers", [])),
                header_rows=list(block.get("header_rows", [])),
                rows=rows,
                table_type=infer_table_type(block, rows),
            )
        ir_blocks.append(
            BlockIR(
                block_id=block_id,
                block_type=block_type if block_type in SUPPORTED_BLOCK_TYPES else "paragraph",
                order=int(block.get("order", 0)),
                text_original=str(block.get("text", "")),
                # TODO: real normalization pending; keep original text until a stable policy exists.
                text_normalized=str(block.get("text", "")),
                section_path=list(block.get("section_path", [])),
                provenance=Provenance(
                    source_format=source_path.suffix.lower().lstrip(".") or "unknown",
                    source_path=str(source_path),
                    block_id=block_id,
                    table_id=str(block.get("table_id", "")),
                ),
                metadata=metadata,
                table=table_ir,
            )
        )
    return DocumentIR(
        doc_id=doc_id or source_path.stem,
        title=source_path.stem,
        source_format=source_path.suffix.lower().lstrip(".") or "unknown",
        source_path=str(source_path),
        blocks=ir_blocks,
        metadata={"block_count": len(ir_blocks)},
    )


def infer_table_type(block: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    if any(row.get("matrix_facts") for row in rows):
        return "marker_matrix"
    headers = {header.lower() for header in block.get("headers", [])}
    if {"object/attribute name", "cl", "value"}.issubset(headers):
        return "inherited_context_table"
    if "event number" in headers or "number of event" in headers:
        return "enumeration_with_code"
    return "row_table"
