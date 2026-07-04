"""Deterministic DLMS Blue Book Ed. 16 PDF ingest.

The generated ``blue_book_index.json`` is a local artifact. It may contain large
copyrighted source excerpts, so it must not be committed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pdfplumber


SCHEMA_VERSION = "blue-book-index/v1"
EDITION = "Ed. 16"
INDEX_FILENAME = "blue_book_index.json"

_CLASS_HEADING_RE = re.compile(
    r"^(?P<section>\d+(?:\.\d+)+)\s+"
    r"(?P<name>.+?)\s*"
    r"\(class_id\s*=\s*(?P<class_id>\d+)\s*,?\s*version\s*=\s*(?P<version>\d+)\s*\)"
    r"(?:\s*\.{3,}\s*\d+)?\s*$",
    re.IGNORECASE,
)
_SECTION_HEADING_RE = re.compile(r"^(?P<section>\d+(?:\.\d+)+)\s+(?P<title>.+)$")
_DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")
_PAGE_FOOTER_RE = re.compile(
    r"^(?:DLMS User Association\s+)?(?:\d+/\d+\s+)?\d{4}-\d{2}-\d{2}\s+DLMS UA\b.*(?:\d+/\d+)?$",
    re.IGNORECASE,
)
_DLMS_DOC_HEADER_RE = re.compile(r"^DLMS UA 1000-\d\b.*\bEd\.?\s*16(?:\s+Part\s+\d+)?$", re.IGNORECASE)
_COPYRIGHT_RE = re.compile(r"^(?:©|\(c\)|Copyright\b).*DLMS User Association", re.IGNORECASE)
_PAGE_PREFIX_RE = re.compile(r"^\d+/\d+\s+")
_PAGE_SUFFIX_RE = re.compile(r"\s+\d+/\d+$")


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class TextSource:
    source_file: str
    pages: list[PageText]


@dataclass(frozen=True)
class _Line:
    page_number: int
    text: str


@dataclass(frozen=True)
class _ClassSection:
    class_id: str
    name: str
    version: int
    section: str
    pages: list[int]
    text: str


def read_pdf_pages(path: Path) -> list[PageText]:
    with pdfplumber.open(path) as pdf:
        return [
            PageText(page_number=index, text=page.extract_text() or "")
            for index, page in enumerate(pdf.pages, start=1)
        ]


def build_index_from_text_sources(sources: Iterable[TextSource]) -> dict[str, Any]:
    source_list = list(sources)
    interface_classes: dict[str, dict[str, Any]] = {}
    obis_sections: list[dict[str, Any]] = []

    for source in source_list:
        part = _source_part(source)
        if part == 2:
            for class_id, entry in _parse_interface_classes(source).items():
                interface_classes[class_id] = entry
        elif part == 1:
            obis_sections.extend(_parse_obis_sections(source))

    interface_classes = dict(sorted(interface_classes.items(), key=lambda item: int(item[0])))
    obis_sections = sorted(obis_sections, key=lambda item: (str(item["section"]), str(item["key"])))
    stats = {"interface_classes": len(interface_classes), "obis_sections": len(obis_sections)}
    return {
        "meta": {
            "edition": EDITION,
            "schema_version": SCHEMA_VERSION,
            "source_files": [Path(source.source_file).name for source in source_list],
            "stats": stats,
        },
        "interface_classes": interface_classes,
        "obis_sections": obis_sections,
    }


def write_index(index: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / INDEX_FILENAME
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ingest(pdf_paths: list[Path], out_dir: Path) -> dict[str, Any]:
    sources = [TextSource(source_file=str(path), pages=read_pdf_pages(path)) for path in pdf_paths]
    index = build_index_from_text_sources(sources)
    output_path = write_index(index, out_dir)
    return {
        "tool": "requirement-atomizer",
        "schema_version": "1.0",
        "command": "blue_book_ingest",
        "ok": True,
        "output_dir": str(out_dir.expanduser().resolve()),
        "index": str(output_path.expanduser().resolve()),
        "stats": index["meta"]["stats"],
    }


def _parse_interface_classes(source: TextSource) -> dict[str, dict[str, Any]]:
    lines = _clean_lines(source.pages)
    sections: list[_ClassSection] = []
    heading_indexes = [(index, match) for index, line in enumerate(lines) if (match := _CLASS_HEADING_RE.match(line.text))]

    for pos, (start, match) in enumerate(heading_indexes):
        heading = lines[start].text
        if _DOT_LEADER_RE.search(heading):
            continue
        end = heading_indexes[pos + 1][0] if pos + 1 < len(heading_indexes) else len(lines)
        section_lines = lines[start:end]
        text = _join_lines(line.text for line in section_lines)
        if len(text) < 40:
            continue
        pages = sorted({line.page_number for line in section_lines})
        sections.append(
            _ClassSection(
                class_id=match.group("class_id"),
                name=_clean_class_name(match.group("name")),
                version=int(match.group("version")),
                section=match.group("section"),
                pages=pages,
                text=text,
            )
        )

    grouped: dict[str, list[_ClassSection]] = {}
    for section in sections:
        grouped.setdefault(section.class_id, []).append(section)

    entries: dict[str, dict[str, Any]] = {}
    for class_id, variants in grouped.items():
        primary = max(variants, key=lambda item: (item.version, len(item.text)))
        ordered = sorted(variants, key=lambda item: (item.version, item.section, item.pages[0] if item.pages else 0))
        combined_text = _merge_variant_text(ordered)
        entries[class_id] = {
            "name": primary.name,
            "version": primary.version,
            "section": primary.section,
            "pages": sorted({page for item in ordered for page in item.pages}),
            "text": combined_text,
            "attributes": _extract_member_lines(combined_text, "attributes"),
            "methods": _extract_member_lines(combined_text, "methods"),
        }
    return entries


def _parse_obis_sections(source: TextSource) -> list[dict[str, Any]]:
    lines = _clean_lines(source.pages)
    heading_indexes = [(index, match) for index, line in enumerate(lines) if (match := _SECTION_HEADING_RE.match(line.text))]
    sections: list[dict[str, Any]] = []
    for pos, (start, match) in enumerate(heading_indexes):
        title = match.group("title").strip()
        if "value group" not in title.casefold():
            continue
        end = heading_indexes[pos + 1][0] if pos + 1 < len(heading_indexes) else len(lines)
        section_lines = lines[start:end]
        text = _join_lines(line.text for line in section_lines)
        if len(text) < 40:
            continue
        sections.append(
            {
                "key": _slugify(title),
                "section": match.group("section"),
                "pages": sorted({line.page_number for line in section_lines}),
                "text": text,
            }
        )
    return sections


def _clean_lines(pages: list[PageText]) -> list[_Line]:
    cleaned: list[_Line] = []
    for page in pages:
        for raw in str(page.text or "").splitlines():
            text = _clean_line(raw)
            if text:
                cleaned.append(_Line(page.page_number, text))
    return cleaned


def _clean_line(raw: str) -> str:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return ""
    if text in {"COSEM Interface Classes", "OBIS CODES", "TECHNICAL REPORT", "DLMS User Association"}:
        return ""
    if _COPYRIGHT_RE.match(text) or _PAGE_FOOTER_RE.match(text) or _DLMS_DOC_HEADER_RE.match(text):
        return ""
    text = _PAGE_PREFIX_RE.sub("", text)
    text = _PAGE_SUFFIX_RE.sub("", text)
    return text.strip()


def _source_part(source: TextSource) -> int | None:
    name = Path(source.source_file).name.casefold()
    if "part-1" in name or "part_1" in name or "part 1" in name or "part1" in name:
        return 1
    if "part-2" in name or "part_2" in name or "part 2" in name or "part2" in name:
        return 2
    sample = "\n".join(page.text for page in source.pages[:5]).casefold()
    if "obis" in sample and "interface classes" not in sample:
        return 1
    if "cosem interface classes" in sample or "class_id" in sample:
        return 2
    return None


def _join_lines(lines: Iterable[str]) -> str:
    text = "\n".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_class_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().rstrip(".")


def _merge_variant_text(variants: list[_ClassSection]) -> str:
    if len(variants) == 1:
        return variants[0].text
    chunks = []
    for variant in variants:
        chunks.append(
            f"[Blue Book section {variant.section}; class_id = {variant.class_id}, "
            f"version = {variant.version}]\n{variant.text}"
        )
    return "\n\n---\n\n".join(chunks)


def _extract_member_lines(text: str, kind: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    members: list[str] = []
    in_block = False
    for line in lines:
        lowered = line.casefold()
        if kind == "attributes" and lowered == "attributes" or kind == "attributes" and lowered.startswith("attributes "):
            in_block = True
            continue
        if (
            kind == "methods"
            and (lowered == "methods" or lowered == "specific methods" or lowered.startswith("specific methods"))
        ):
            in_block = True
            continue
        if in_block and _block_ends(line, kind):
            in_block = False
        if not in_block:
            continue
        member = _parse_member_line(line, kind)
        if member and member not in members:
            members.append(member)
    return members


def _block_ends(line: str, kind: str) -> bool:
    lowered = line.casefold()
    if kind == "attributes" and lowered.startswith("specific methods"):
        return True
    if re.match(r"^\d+(?:\.\d+){2,}\s+", line):
        return True
    return False


def _parse_member_line(line: str, kind: str) -> str | None:
    match = re.match(r"^(?P<index>\d{1,2})\.?\s+(?P<name>[A-Za-z_][A-Za-z0-9_-]*)(?P<sig>\s*\([^)]*\))?", line)
    if not match:
        return None
    name = match.group("name")
    sig = re.sub(r"\s+", "", match.group("sig") or "")
    if kind == "methods" and not sig and name.casefold() in {"m", "o", "x"}:
        return None
    return f"{int(match.group('index'))} {name}{sig}"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.casefold()).strip("-")
    return slug or "section"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile DLMS Blue Book PDFs into a deterministic local JSON index.")
    parser.add_argument("--pdf", type=Path, action="append", required=True, help="Blue Book PDF path; pass once per part")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for blue_book_index.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        envelope = ingest(args.pdf, args.out)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        print(
            json.dumps(
                {
                    "tool": "requirement-atomizer",
                    "schema_version": "1.0",
                    "command": "blue_book_ingest",
                    "ok": False,
                    "error": {"type": "pipeline_error", "message": str(exc)},
                },
                ensure_ascii=False,
            )
        )
        return 3
    print(json.dumps(envelope, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
