from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_op(x: int, y: int, text: str, *, size: int = 10) -> str:
    return f"BT /F1 {size} Tf {x} {y} Td ({pdf_escape(text)}) Tj ET\n"


def line_op(x1: int, y1: int, x2: int, y2: int) -> str:
    return f"{x1} {y1} m {x2} {y2} l S\n"


def rect_op(x: int, y: int, width: int, height: int) -> str:
    return f"{x} {y} {width} {height} re S\n"


def table_ops(x: int, top: int, columns: list[int], row_height: int, rows: list[list[str]]) -> str:
    width = sum(columns)
    height = row_height * len(rows)
    bottom = top - height
    ops = ["0.8 w\n", rect_op(x, bottom, width, height)]
    current_x = x
    for col_width in columns[:-1]:
        current_x += col_width
        ops.append(line_op(current_x, bottom, current_x, top))
    for row_index in range(1, len(rows)):
        y = top - row_index * row_height
        ops.append(line_op(x, y, x + width, y))
    for row_index, row in enumerate(rows):
        baseline = top - (row_index + 1) * row_height + 7
        current_x = x + 4
        for col_index, value in enumerate(row):
            ops.append(text_op(current_x, baseline, value, size=9))
            current_x += columns[col_index]
    return "".join(ops)


def make_text_fixture() -> list[str]:
    header = "DLMS COSEM PDF SAMPLE"
    footer1 = "Copyright Sample Standard"
    footer2 = "Copyright Sample Standard"
    page1 = [
        text_op(54, 760, header, size=9),
        text_op(500, 744, "Page 1", size=9),
        text_op(54, 720, "1 Scope", size=14),
        text_op(54, 694, "The meter shall support xDLMS GET service.", size=11),
        text_op(54, 668, "5.1 Security requirements", size=13),
        text_op(54, 642, "The profile shall define supported customer application processes.", size=11),
        text_op(54, 610, "Table 1 - Services xDLMS", size=10),
        table_ops(
            54,
            590,
            [160, 110, 110],
            24,
            [
                ["Customer application process", "xDLMS Service", "xDLMS Service"],
                ["Customer application process", "GET", "ACTION"],
                ["Public customer", "X", ""],
                ["Management client", "", "X"],
            ],
        ),
        text_op(54, 40, footer1, size=9),
    ]
    page2 = [
        text_op(54, 760, header, size=9),
        text_op(500, 744, "Page 2", size=9),
        text_op(54, 720, "6 Events", size=14),
        text_op(54, 694, "The event log shall record power down events.", size=11),
        text_op(54, 40, footer2, size=9),
    ]
    return ["".join(page1), "".join(page2)]


def make_no_text_fixture() -> list[str]:
    page = [
        "1.2 w\n",
        rect_op(100, 500, 240, 120),
        line_op(100, 500, 340, 620),
        line_op(100, 620, 340, 500),
    ]
    return ["".join(page)]


def write_pdf(path: Path, page_streams: list[str]) -> None:
    objects: list[bytes] = []

    def add_object(payload: str | bytes) -> int:
        if isinstance(payload, str):
            payload = payload.encode("latin-1")
        objects.append(payload)
        return len(objects)

    page_object_ids: list[int] = []
    content_ids: list[int] = []
    for stream in page_streams:
        data = stream.encode("latin-1")
        content_ids.append(add_object(b"<< /Length " + str(len(data)).encode("ascii") + b" >>\nstream\n" + data + b"endstream"))
        page_object_ids.append(0)

    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id_placeholder = len(objects) + len(page_streams) + 1
    for index, content_id in enumerate(content_ids):
        page_object_ids[index] = add_object(
            f"<< /Type /Page /Parent {pages_id_placeholder} 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
    pages_id = add_object(
        f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_object_ids)}] /Count {len(page_object_ids)} >>"
    )
    assert pages_id == pages_id_placeholder
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(bytes(output))


def main() -> None:
    write_pdf(ROOT / "sample_text_tables.pdf", make_text_fixture())
    write_pdf(ROOT / "sample_no_text_layer.pdf", make_no_text_fixture())


if __name__ == "__main__":
    main()
