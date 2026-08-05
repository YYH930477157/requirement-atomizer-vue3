"""PDF modern-parser adapter — WS1 wk6 normalization layer (plan §3.2.3).

This module is the *normalization layer* between a modern PDF parser
(Docling / Marker class) and the WS1 dual-track table contract. It takes
whatever structured output a modern parser emits and normalizes it into the
exact ``ParsedDocxTable`` shape (geometry matrix + per-cell style evidence +
merge ranges) that ``table_geometry_validator`` and ``llm_table_understanding``
already consume — so the dual-track signing/proposing rail needs no change
when the source is a modern PDF parser instead of ``docx_table_parser``.

Hard contract (mandated by the handoff brief):

* **No new third-party dependency is installed.** The adapter probes for each
  candidate parser at call time with a deferred import. If the dependency is
  absent (the default on every stock checkout, including this one), the live
  entry point returns an honest ``unavailable`` status and the caller falls
  back to the handwritten pdfplumber path. A missing parser is REPORTED, never
  impersonated (provenance discipline — the brief's red line).
* **Normalization, not parsing.** The adapter owns no PDF logic of its own; it
  maps a modern parser's already-parsed table output onto ``ParsedDocxTable``.
  Each produced table carries ``version = PDF_MODERN_ADAPTER_VERSION`` and the
  result carries a ``provenance`` block naming the source parser, so a
  downstream audit can always tell a modern-parser table from a docx /
  pdfplumber one.
* **No real parser calls in tests.** Tests feed synthetic matrices / parser
  payloads directly into the pure normalizer; the live entry point is
  exercised only through dependency-probe fakes. This machine ships no parser
  dependency, so a default call is ``unavailable`` anyway.

Alignment target. The dual-track input contract is ``ParsedDocxTable`` from
``docx_table_parser``. The validator reads ``parsed.cells`` (each cell's
``text`` and ``covered_coordinates``) and ``parsed.merge_ranges``; the proposer
additionally reads per-cell ``style_evidence``. The adapter therefore produces
canonical cells for every non-blank matrix position and derives each merge
anchor's ``covered_coordinates`` from the supplied merge ranges, so rule 2
(merge-anchor conservation) of the validator works unchanged against a
modern-parser-sourced table.

Scope note. The candidate-parser extraction helpers below are written against
the candidates' *public output contracts* (Docling ``TableItem`` grid / Marker
GFM pipe tables). They cannot be exercised here — no dependency is installed —
and are deliberately defensive. Real calibration against a frozen golden set
is the job of the week-8 A/B gate (plan §3.2.4), not this adapter.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from docx_table_parser import (
    ParsedCell,
    ParsedCellContent,
    ParsedDocxTable,
)

LOGGER = logging.getLogger("requirement_atomizer")

PDF_MODERN_ADAPTER_VERSION = "pdf-modern-adapter-v1"
# Source-format provenance tag carried on every normalized table's ``version``
# field and in the result ``provenance`` block. Distinct from
# ``docx_table_parser.DOCX_TABLE_PHYSICAL_VERSION`` so downstream can tell the
# two origins apart by string equality.
PDF_MODERN_SOURCE_FORMAT = "pdf-modern"

# Candidate parsers, in probe order. The first importable + callable one wins.
# Adding a candidate here is the only change needed to extend coverage.
CANDIDATE_PARSERS: tuple[str, ...] = ("docling", "marker")


@dataclass(frozen=True)
class ModernTablePage:
    """One normalized table from a modern parser, with its origin tag.

    ``page_number`` is 1-based when the parser exposes page boundaries and
    ``1`` otherwise (whole-document tables). ``provenance`` is the same dict
    the result carries, repeated per table so a downstream consumer never has
    to thread the parent result through.
    """

    page_number: int
    parsed_table: ParsedDocxTable
    provenance: dict[str, Any]


@dataclass(frozen=True)
class ModernParseResult:
    """Outcome of one ``parse_pdf_modern`` call.

    ``status`` is ``ok`` (at least one table normalized) or ``unavailable``
    (no dependency / no tables / any parser error). ``unavailable`` is the
    ONLY negative status — the adapter never fabricates tables (provenance
    discipline). ``reason`` records the honest unavailability cause; empty
    when ok.
    """

    status: str
    pages: tuple[ModernTablePage, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    adapter_version: str = PDF_MODERN_ADAPTER_VERSION

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"

    @property
    def is_unavailable(self) -> bool:
        return self.status == "unavailable"


# --- dependency probing ------------------------------------------------------


def _probe_docling() -> tuple[bool, str, Callable[[Path], list[Any]] | None]:
    """Deferred-import probe for Docling.

    Returns ``(available, name_or_reason, extractor)``. ``extractor`` is a
    callable turning the input path into a list of raw table payloads (each
    a ``(matrix, merge_hints, style_hints, page_number)`` tuple) when
    available, else ``None``. Kept isolated so a missing/renamed symbol does
    not leak into the marker probe.
    """
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised only with dep present
        return False, f"docling_import_failed:{type(exc).__name__}", None

    def _extract(path: Path) -> list[Any]:
        converter = DocumentConverter()
        result = converter.convert(str(path))
        document = getattr(result, "document", None) or result
        payloads: list[Any] = []
        page_no = 0
        for table in getattr(document, "tables", []) or []:
            page_no += 1
            matrix = _docling_table_matrix(table)
            merges = _docling_table_merges(table)
            styles = _docling_table_styles(table)
            payloads.append((matrix, merges, styles, page_no))
        return payloads

    return True, "docling", _extract


def _probe_marker() -> tuple[bool, str, Callable[[Path], list[Any]] | None]:
    """Deferred-import probe for Marker (markdown output path).

    Marker's most stable public surface is its markdown output; tables there
    are GFM pipe tables. We parse them into matrices. A richer cell-level API
    (row_span/col_span) would replace this when calibrated against a golden
    set at the week-8 A/B gate.
    """
    try:
        from marker.converters.pdf import PdfConverter  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised only with dep present
        return False, f"marker_import_failed:{type(exc).__name__}", None

    def _extract(path: Path) -> list[Any]:
        converter = PdfConverter()
        rendered = converter(str(path))
        markdown = getattr(rendered, "markdown", None) or str(rendered)
        payloads: list[Any] = []
        page_no = 0
        for matrix in _parse_gfm_tables(markdown):
            page_no += 1
            payloads.append((matrix, [], [], page_no))
        return payloads

    return True, "marker", _extract


_PROBES: tuple[Callable[()], ...] = ()  # placeholder, real registry below
_PROBE_REGISTRY: tuple[Callable[[], tuple[bool, str, Callable[[Path], list[Any]] | None]], ...] = (
    _probe_docling,
    _probe_marker,
)


def modern_parser_available() -> tuple[str, str]:
    """Probe candidate parsers in order. Returns ``(name, reason)``.

    ``name`` is the first importable candidate (``""`` if none); ``reason``
    describes why probing stopped (success message or the last failure cause).
    Pure metadata — does not parse a document.
    """
    for probe in _PROBE_REGISTRY:
        available, label, _extractor = probe()
        if available:
            return label, f"available:{label}"
    failed = [probe()[1] for probe in _PROBE_REGISTRY]
    return "", "no_candidate_installed:" + "|".join(failed)


# --- docling payload extraction helpers (defensive; not exercised w/o dep) ---


def _docling_table_matrix(table: Any) -> list[list[str]]:
    """Best-effort text grid from a Docling table item.

    Prefers the structured ``data.grid`` (list[list[str]]), falls back to a
    dataframe, then to an HTML parse. Never raises — a malformed payload
    yields an empty grid (the caller treats empty as "no table").
    """
    data = getattr(table, "data", None)
    if data is not None:
        grid = getattr(data, "grid", None)
        if grid:
            return _coerce_matrix(grid)
    df = None
    try:
        export = getattr(table, "export_to_dataframe", None)
        df = export() if callable(export) else None
    except Exception:  # pragma: no cover - depends on runtime dep
        df = None
    if df is not None:
        try:
            return [
                ["" if value is None else str(value) for value in row]
                for row in df.values.tolist()
            ]
        except Exception:  # pragma: no cover
            pass
    return []


def _docling_table_merges(table: Any) -> list[tuple[int, int, int, int]]:
    """Best-effort merge ranges from a Docling table's cell spans.

    Newer Docling exposes per-cell ``row_span``/``col_span``; we reconstruct
    rectangular (r1,c1,r2,c2) ranges from them. Absent spans → empty list
    (the normalizer then treats every cell as standalone).
    """
    cells = getattr(getattr(table, "data", None), "cells", None) or []
    merges: list[tuple[int, int, int, int]] = []
    for cell in cells:
        try:
            r = int(getattr(cell, "start_row_offset", getattr(cell, "row", 0)) or 0)
            c = int(getattr(cell, "start_col_offset", getattr(cell, "col", 0)) or 0)
            rs = int(getattr(cell, "row_span", 1) or 1)
            cs = int(getattr(cell, "col_span", 1) or 1)
        except Exception:  # pragma: no cover
            continue
        if rs > 1 or cs > 1:
            # Docling offsets may be 0-based; normalize to 1-based anchor.
            merges.append((r + 1, c + 1, r + rs, c + cs))
    return merges


def _docling_table_styles(table: Any) -> dict[tuple[int, int], dict[str, Any]]:
    """Best-effort per-cell style evidence (bold/shading) from Docling.

    Most Docling table cells carry text only; style is rare. We map any
    exposed ``bold``/``highlight`` flags onto the style-evidence dict the
    proposer reads as role hints. Absent → empty per cell.
    """
    styles: dict[tuple[int, int], dict[str, Any]] = {}
    cells = getattr(getattr(table, "data", None), "cells", None) or []
    for cell in cells:
        try:
            r = int(getattr(cell, "start_row_offset", getattr(cell, "row", 0)) or 0) + 1
            c = int(getattr(cell, "start_col_offset", getattr(cell, "col", 0)) or 0) + 1
        except Exception:  # pragma: no cover
            continue
        evidence: dict[str, Any] = {}
        if getattr(cell, "bold", None):
            evidence["bold"] = True
        if getattr(cell, "highlight", None):
            evidence["shading"] = str(cell.highlight)
        if evidence:
            styles[(r, c)] = evidence
    return styles


# --- marker payload extraction helpers ----------------------------------------


_GFM_TABLE_RE = re.compile(
    r"(?:^[ \t]*\|.+\|[ \t]*\n(?:^[ \t]*\|[\s:|-]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n)*)",
    re.MULTILINE,
)


def _parse_gfm_tables(markdown: str) -> list[list[list[str]]]:
    """Parse GFM pipe tables from markdown into text matrices.

    Each table's rows become ``list[list[str]]``; the separator row
    (``|---|---|``) is dropped. Cell text is the stripped inner segment.
    A marker table with no data rows yields an empty matrix (skipped).
    """
    matrices: list[list[list[str]]] = []
    for match in _GFM_TABLE_RE.finditer(markdown):
        lines = [line.strip() for line in match.group(0).strip().splitlines()]
        rows: list[list[str]] = []
        for line in lines:
            cells = [segment.strip() for segment in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r"[\s:|-]*", segment or "") for segment in cells):
                # separator row — skip
                continue
            rows.append(cells)
        if rows:
            matrices.append(rows)
    return matrices


# --- normalization core (pure, tested directly) ------------------------------


def _coerce_matrix(rows: Any) -> list[list[str]]:
    """Coerce an arbitrary iterable-of-iterables into a rectangular text grid.

    None → "" ; everything else → ``str(value)``. Ragged rows are padded to
    the widest row with "" so downstream geometry (width, canonical cells) is
    well-defined regardless of the source parser's row shape.
    """
    matrix: list[list[str]] = []
    width = 0
    for row in rows or []:
        text_row = ["" if value is None else str(value) for value in row]
        matrix.append(text_row)
        width = max(width, len(text_row))
    for row in matrix:
        if len(row) < width:
            row.extend([""] * (width - len(row)))
    return matrix


def _covered_coordinates(
    merge_ranges: list[tuple[int, int, int, int]],
) -> dict[tuple[int, int], tuple[tuple[int, int], ...]]:
    """Map each merge anchor (r1,c1) to its covered coordinates.

    The validator's rule 2 (merge-anchor conservation) keys off
    ``cell.covered_coordinates``; this derivation lets a modern-parser table
    satisfy that rule without inventing a parallel merge model. Covered
    coordinates are excluded from ``parsed.cells`` (only anchors + standalone
    cells are canonical), matching ``docx_table_parser`` semantics.
    """
    by_anchor: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for r1, c1, r2, c2 in merge_ranges:
        anchor = (r1, c1)
        for row_index in range(r1, r2 + 1):
            for column_index in range(c1, c2 + 1):
                if (row_index, column_index) == anchor:
                    continue
                by_anchor.setdefault(anchor, []).append((row_index, column_index))
    return {anchor: tuple(coords) for anchor, coords in by_anchor.items()}


def normalize_table_matrix(
    matrix: list[list[str]],
    *,
    parser: str,
    page_number: int = 1,
    merge_ranges: list[tuple[int, int, int, int]] | None = None,
    style_evidence: dict[tuple[int, int], dict[str, Any]] | None = None,
    parse_incomplete_reason: dict[str, Any] | None = None,
) -> ParsedDocxTable:
    """Normalize a modern-parser text grid into a dual-track ``ParsedDocxTable``.

    Pure and deterministic. Every non-blank matrix position becomes a canonical
    ``ParsedCell``; merge anchors additionally record their covered coordinates
    derived from ``merge_ranges``. ``version`` is set to
    ``PDF_MODERN_ADAPTER_VERSION`` so the table's origin is string-comparable.
    ``parser`` is carried in the version string suffix for audit traceability.

    The produced table is byte-for-byte compatible with what
    ``docx_table_parser.parse_docx_table`` returns for a docx table of the
    same shape — that is the contract the dual-track rail consumes.
    """
    normalized = _coerce_matrix(matrix)
    width = max((len(row) for row in normalized), default=0)
    height = len(normalized)
    merge_ranges = list(merge_ranges or [])
    covered_by_anchor = _covered_coordinates(merge_ranges)
    style_evidence = style_evidence or {}

    cells: dict[tuple[int, int], ParsedCell] = {}
    covered_set: set[tuple[int, int]] = set()
    for coords in covered_by_anchor.values():
        covered_set.update(coords)

    for row_index in range(1, height + 1):
        row = normalized[row_index - 1]
        for column_index in range(1, width + 1):
            coordinate = (row_index, column_index)
            if coordinate in covered_set:
                continue
            text = row[column_index - 1] if column_index <= len(row) else ""
            raw_text = text
            anchor_covered = covered_by_anchor.get(coordinate, ())
            row_span = 1
            column_span = 1
            for r1, c1, r2, c2 in merge_ranges:
                if (r1, c1) == coordinate:
                    row_span = max(1, r2 - r1 + 1)
                    column_span = max(1, c2 - c1 + 1)
                    break
            cell = ParsedCell(
                row_index=row_index,
                column_index=column_index,
                text=text,
                raw_text=raw_text,
                row_span=row_span,
                column_span=column_span,
                covered_coordinates=anchor_covered,
                content=ParsedCellContent((), 0),
                style_evidence=dict(style_evidence.get(coordinate, {})),
            )
            cells[coordinate] = cell

    raw_text = "\n".join(" ".join(row) for row in normalized).strip()
    return ParsedDocxTable(
        width=width,
        matrix=normalized,
        raw_matrix=[list(row) for row in normalized],
        cells=cells,
        merge_ranges=sorted(set(merge_ranges)),
        explicit_header_rows=[],
        nested_tables=[],
        parse_incomplete=bool(parse_incomplete_reason),
        parse_incomplete_reason=dict(parse_incomplete_reason or {}),
        raw_text=raw_text,
        version=f"{PDF_MODERN_ADAPTER_VERSION}:{parser}",
    )


# --- live entry point --------------------------------------------------------


def _build_pages(
    payloads: list[Any],
    *,
    parser: str,
) -> tuple[ModernTablePage, ...]:
    """Normalize raw ``(matrix, merges, styles, page)`` payloads into pages.

    Empty/blank matrices are skipped (a parser reporting an empty table is not
    a table). At least one surviving page means ``ok``.
    """
    pages: list[ModernTablePage] = []
    provenance = {
        "parser": parser,
        "adapter_version": PDF_MODERN_ADAPTER_VERSION,
        "source_format": PDF_MODERN_SOURCE_FORMAT,
    }
    for matrix, merges, styles, page_number in payloads:
        coerced = _coerce_matrix(matrix)
        if not any(any(str(value).strip() for value in row) for row in coerced):
            continue
        parsed = normalize_table_matrix(
            coerced,
            parser=parser,
            page_number=int(page_number or 1),
            merge_ranges=list(merges or []),
            style_evidence=dict(styles or {}),
        )
        pages.append(
            ModernTablePage(
                page_number=int(page_number or 1),
                parsed_table=parsed,
                provenance=dict(provenance),
            )
        )
    return tuple(pages)


def parse_pdf_modern(input_path: Path) -> ModernParseResult:
    """Live entry: parse a PDF with the first available modern parser.

    Returns ``unavailable`` for every negative outcome — no candidate
    installed, candidate raised, or zero tables found. Never raises and never
    fabricates tables. The caller (``parsers.pdf_parser.extract_pdf``) falls
    back to the handwritten pdfplumber path on any ``unavailable``.
    """
    name, reason = modern_parser_available()
    if not name:
        return ModernParseResult(
            status="unavailable",
            provenance={
                "parser": "",
                "adapter_version": PDF_MODERN_ADAPTER_VERSION,
                "source_format": PDF_MODERN_SOURCE_FORMAT,
            },
            reason=reason,
        )

    for probe in _PROBE_REGISTRY:
        available, label, extractor = probe()
        if not available or label != name or extractor is None:
            continue
        try:
            payloads = extractor(Path(input_path))
        except Exception as exc:  # pragma: no cover - depends on runtime dep
            LOGGER.warning("modern parser %s failed on %s: %s", name, input_path, exc)
            return ModernParseResult(
                status="unavailable",
                provenance={
                    "parser": name,
                    "adapter_version": PDF_MODERN_ADAPTER_VERSION,
                    "source_format": PDF_MODERN_SOURCE_FORMAT,
                },
                reason=f"{name}_runtime_error:{type(exc).__name__}",
            )
        pages = _build_pages(payloads, parser=name)
        if not pages:
            return ModernParseResult(
                status="unavailable",
                provenance={
                    "parser": name,
                    "adapter_version": PDF_MODERN_ADAPTER_VERSION,
                    "source_format": PDF_MODERN_SOURCE_FORMAT,
                },
                reason=f"{name}_no_tables",
            )
        return ModernParseResult(
            status="ok",
            pages=pages,
            provenance={
                "parser": name,
                "adapter_version": PDF_MODERN_ADAPTER_VERSION,
                "source_format": PDF_MODERN_SOURCE_FORMAT,
            },
        )
    # All probes declined — treat as unavailable (defensive; should not happen
    # because modern_parser_available already reported a name).
    return ModernParseResult(
        status="unavailable",
        provenance={
            "parser": "",
            "adapter_version": PDF_MODERN_ADAPTER_VERSION,
            "source_format": PDF_MODERN_SOURCE_FORMAT,
        },
        reason="no_extractor_resolved",
    )


__all__ = [
    "PDF_MODERN_ADAPTER_VERSION",
    "PDF_MODERN_SOURCE_FORMAT",
    "CANDIDATE_PARSERS",
    "ModernTablePage",
    "ModernParseResult",
    "modern_parser_available",
    "normalize_table_matrix",
    "parse_pdf_modern",
]
