PDF fixtures for M4b text-layer parsing tests.

Files:

- `sample_text_tables.pdf`: two-page text-layer PDF with repeated page header/footer text, numbered headings, shall paragraphs, a captioned table, and ruled table lines.
- `sample_no_text_layer.pdf`: one-page PDF with drawn graphics only and no text objects, used to exercise the scanned/no-text-layer rejection path.

Regenerate them from the repository root with:

```powershell
python .\tests\fixtures\generate_pdf_fixtures.py
```

The generator intentionally uses only the Python standard library and writes a tiny deterministic PDF. It avoids adding a test-only PDF authoring dependency.
