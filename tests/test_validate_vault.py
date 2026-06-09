from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from validate_vault import Severity, validate_vault


def write_note(
    vault: Path,
    relative_path: str,
    *,
    entry_id: str = "KB-TEST-ONE",
    name: str = "Test Entry",
    layer: str = "term",
    entry_type: str = "term",
    definition: str = "A test entry used by the vault validator.",
    relations: str = "",
    metadata: str = "",
) -> Path:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    relation_block = f"relations:\n{relations}" if relations else "relations: []"
    structured = f"\n## Structured Data\n\n```json metadata\n{metadata}\n```\n" if metadata else ""
    path.write_text(
        f"""---
id: {entry_id}
kb_id: test_kb
type: {entry_type}
layer: {layer}
name: {name}
aliases: []
keywords:
- {name.lower()}
domain_tags:
- test
{relation_block}
---

# {name}

## Definition

{definition}
{structured}
## Notes

""",
        encoding="utf-8",
    )
    return path


class ValidateVaultTests(unittest.TestCase):
    def test_valid_vault_reports_no_issues_and_counts_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            write_note(vault, "01_terms/Test Entry.md")
            (vault / ".obsidian").mkdir()
            (vault / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")
            (vault / "Knowledge Map.canvas").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")

            report = validate_vault(vault)

            self.assertEqual(report.notes, 1)
            self.assertEqual(report.errors, 0)
            self.assertEqual(report.warnings, 0)

    def test_duplicate_ids_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            write_note(vault, "01_terms/One.md", entry_id="KB-DUPLICATE", name="One")
            write_note(vault, "01_terms/Two.md", entry_id="KB-DUPLICATE", name="Two")

            report = validate_vault(vault)

            self.assertEqual(report.errors, 1)
            self.assertIn("duplicate id", report.issues[0].message)

    def test_missing_required_fields_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = vault / "01_terms/Broken.md"
            path.parent.mkdir(parents=True)
            path.write_text(
                """---
id: KB-BROKEN
name: Broken
---

# Broken

## Definition

Missing required frontmatter fields.
""",
                encoding="utf-8",
            )

            report = validate_vault(vault)

            messages = [issue.message for issue in report.issues if issue.severity == Severity.ERROR]
            self.assertIn("missing required field: type", messages)
            self.assertIn("missing required field: layer", messages)
            self.assertIn("missing required field: kb_id", messages)

    def test_invalid_metadata_json_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            write_note(vault, "01_terms/Bad Metadata.md", metadata='{"broken": true,,}')

            report = validate_vault(vault)

            self.assertEqual(report.errors, 1)
            self.assertIn("invalid metadata JSON", report.issues[0].message)

    def test_missing_relation_target_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            write_note(
                vault,
                "02_protocol_layer/Source.md",
                entry_id="KB-SOURCE",
                name="Source",
                layer="object_model",
                entry_type="object",
                relations="  - relation: uses\n    target: KB-MISSING\n",
            )

            report = validate_vault(vault)

            self.assertEqual(report.errors, 0)
            self.assertEqual(report.warnings, 1)
            self.assertIn("relation target not found: KB-MISSING", report.issues[0].message)


if __name__ == "__main__":
    unittest.main()
