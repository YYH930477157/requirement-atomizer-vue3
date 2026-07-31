from __future__ import annotations

from typing import Any, Iterable

from claim_artifacts import hash_json


CLAIM_FOCUS_ADAPTER_VERSION = "claim-focus-adapter-v2"


class ClaimFocusError(ValueError):
    pass


def _rows_by_id(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {
        str(row.get(key) or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get(key) or "")
    }


def _block_fingerprint(block: dict[str, Any]) -> str:
    return hash_json(
        "claim-focus-parent-block/v1",
        {
            "block_id": str(block.get("block_id") or ""),
            "type": str(block.get("type") or ""),
            "text": str(block.get("text") or ""),
            "headers": list(block.get("headers") or []),
            "data_rows": list(block.get("data_rows") or []),
        },
    )


def _canonical_cells(row: Any) -> list[str]:
    if isinstance(row, dict):
        return [f"{key}={row[key]}" for key in sorted(row)]
    if isinstance(row, (list, tuple)):
        return [str(value or "") for value in row]
    return [str(row or "")]


def build_claim_focus_adapter(
    claim: dict[str, Any],
    blocks: Iterable[dict[str, Any]],
    table_items: Iterable[dict[str, Any]],
    table_cell_items: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    locator = dict(claim.get("locator") or {})
    block_id = str(locator.get("block_id") or "")
    block = _rows_by_id(blocks, "block_id").get(block_id)
    if block is None:
        raise ClaimFocusError(f"claim parent block is unavailable: {block_id}")
    source_kind = str(claim.get("source_kind") or "")
    text = str(claim.get("text") or "")
    common = {
        "adapter_version": CLAIM_FOCUS_ADAPTER_VERSION,
        "claim_id": str(claim.get("claim_id") or ""),
        "claim_hash": str(claim.get("claim_hash") or ""),
        "block_id": block_id,
        "parent_block_fingerprint": _block_fingerprint(block),
    }

    if source_kind in {"paragraph_sentence", "list_item", "heading", "caption", "other", "noise"}:
        if locator.get("position_basis") != "repaired_text":
            raise ClaimFocusError("text claim does not use repaired_text positions")
        block_text = str(block.get("text") or "")
        start = locator.get("start")
        end = locator.get("end")
        if not isinstance(start, int) or isinstance(start, bool):
            raise ClaimFocusError("text claim start is invalid")
        if not isinstance(end, int) or isinstance(end, bool) or end <= start:
            raise ClaimFocusError("text claim end is invalid")
        if start < 0 or end > len(block_text) or block_text[start:end] != text:
            raise ClaimFocusError("text claim locator no longer matches its source")
        return {
            **common,
            "kind": "text_span" if source_kind != "list_item" else "list_item",
            "start": start,
            "end": end,
            "text_hash": hash_json("claim-focus-text/v1", text),
            "text": text,
        }

    if source_kind == "table_row":
        if locator.get("position_basis") != "table_item_fields":
            raise ClaimFocusError("table row does not use table_item_fields")
        item_id = str(locator.get("table_item_id") or "")
        item = _rows_by_id(table_items, "item_id").get(item_id)
        item_block_id = str(
            (item or {}).get("table_block_id") or (item or {}).get("block_id") or ""
        )
        if item is None or item_block_id != block_id:
            raise ClaimFocusError("table item is unavailable or belongs to another block")
        row_index = locator.get("row_index")
        if not isinstance(row_index, int) or isinstance(row_index, bool):
            raise ClaimFocusError("table row index is invalid")
        if int(item.get("row_index") or 0) != row_index:
            raise ClaimFocusError("table row index changed")
        fields = list(dict(claim.get("table_context") or {}).get("fields") or [])
        if not fields:
            raise ClaimFocusError("table row has no field identity")
        field_identity = [
            {"name": str(field.get("name") or ""), "value": str(field.get("value") or "")}
            for field in fields
        ]
        current_fields = dict(item.get("fields") or {})
        if any(
            str(current_fields.get(field["name"], "")) != field["value"]
            for field in field_identity
        ):
            raise ClaimFocusError("table item field identity changed")
        return {
            **common,
            "kind": "table_item",
            "table_item_id": item_id,
            "row_index": row_index,
            "field_identity": field_identity,
            "field_identity_hash": hash_json("claim-focus-table-item/v1", field_identity),
        }

    if source_kind == "table_fallback":
        if locator.get("position_basis") != "table_data_rows":
            raise ClaimFocusError("table fallback does not use table_data_rows")
        row_start = locator.get("row_start")
        row_end = locator.get("row_end")
        rows = list(block.get("data_rows") or [])
        header_rows = int(block.get("header_row_count") or 0)
        if (
            not isinstance(row_start, int)
            or isinstance(row_start, bool)
            or not isinstance(row_end, int)
            or isinstance(row_end, bool)
            or row_start < header_rows
            or row_end <= row_start
            or row_end - header_rows > len(rows)
        ):
            raise ClaimFocusError("table fallback has no current deterministic row window")
        # Catalog fallback locators use a half-open absolute table-row window.
        # data_rows excludes the header rows, so translate the locator before
        # hashing the current source window.
        data_start = row_start - header_rows
        data_end = row_end - header_rows
        window = [_canonical_cells(row) for row in rows[data_start:data_end]]
        if not window:
            raise ClaimFocusError("table fallback row window is empty")
        from claim_catalog import _group_fallback_fragments

        current_group = next(
            (
                group
                for group in _group_fallback_fragments(block)
                if int(group["row_start"]) == row_start
                and int(group["row_end"]) == row_end
            ),
            None,
        )
        if current_group is None or str(current_group.get("text") or "") != text:
            raise ClaimFocusError("table fallback locator no longer matches its source")
        return {
            **common,
            "kind": "table_data_rows",
            "row_start": row_start,
            "row_end": row_end,
            "fallback_group_id": str(locator.get("fallback_group_id") or ""),
            "row_hashes": [
                hash_json("claim-focus-table-row/v1", row) for row in window
            ],
        }

    if source_kind == "table_cell":
        if locator.get("position_basis") != "table_cell_text":
            raise ClaimFocusError("table cell claim does not use table_cell_text positions")
        cell_id = str(locator.get("table_cell_id") or "")
        cell = _rows_by_id(table_cell_items or [], "cell_id").get(cell_id)
        cell_block_id = str((cell or {}).get("table_block_id") or "")
        if cell is None or cell_block_id != block_id:
            raise ClaimFocusError("table cell is unavailable or belongs to another block")
        row_index = locator.get("row_index")
        column_index = locator.get("column_index")
        if not isinstance(row_index, int) or isinstance(row_index, bool):
            raise ClaimFocusError("table cell row index is invalid")
        if not isinstance(column_index, int) or isinstance(column_index, bool):
            raise ClaimFocusError("table cell column index is invalid")
        if int(cell.get("row_index") or 0) != row_index:
            raise ClaimFocusError("table cell row index changed")
        if int(cell.get("column_index") or 0) != column_index:
            raise ClaimFocusError("table cell column index changed")
        cell_start = locator.get("cell_start")
        cell_end = locator.get("cell_end")
        cell_text = str(cell.get("text") or "")
        if (
            not isinstance(cell_start, int)
            or isinstance(cell_start, bool)
            or not isinstance(cell_end, int)
            or isinstance(cell_end, bool)
            or cell_start < 0
            or cell_end <= cell_start
            or cell_end > len(cell_text)
            or cell_text[cell_start:cell_end] != text
        ):
            raise ClaimFocusError("table cell locator no longer matches its source")
        # 行头/列头/merge anchor 是 cell 身份的一部分：漂移即指纹失效
        header_path = [str(value) for value in (cell.get("header_path") or [])]
        row_header_context = [str(value) for value in (cell.get("row_header_context") or [])]
        claim_context = dict(claim.get("table_context") or {})
        if "header_path" in claim_context and [
            str(value) for value in (claim_context.get("header_path") or [])
        ] != header_path:
            raise ClaimFocusError("table cell header path changed")
        if "row_header_context" in claim_context and [
            str(value) for value in (claim_context.get("row_header_context") or [])
        ] != row_header_context:
            raise ClaimFocusError("table cell row header context changed")
        merge_identity = {
            "row_span": int(cell.get("row_span") or 1),
            "column_span": int(cell.get("column_span") or 1),
            "covered_coordinates": [
                [int(pair[0]), int(pair[1])]
                for pair in (cell.get("covered_coordinates") or [])
            ],
        }
        context_identity = {
            "header_path": header_path,
            "row_header_context": row_header_context,
            "merge_anchor": merge_identity,
            "structural_role": str(cell.get("structural_role") or ""),
        }
        return {
            **common,
            "kind": "table_cell",
            "table_cell_id": cell_id,
            "row_index": row_index,
            "column_index": column_index,
            "data_row_index": cell.get("data_row_index"),
            "cell_start": cell_start,
            "cell_end": cell_end,
            "header_path": header_path,
            "row_header_context": row_header_context,
            "merge_anchor": merge_identity,
            "context_identity_hash": hash_json("claim-focus-table-cell/v1", context_identity),
            "text_hash": hash_json("claim-focus-text/v1", text),
            "text": text,
        }

    raise ClaimFocusError(f"unsupported claim source kind: {source_kind or '<missing>'}")
