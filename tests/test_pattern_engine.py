from __future__ import annotations

import unittest
from pathlib import Path

from pattern_engine import apply_requirement_patterns, load_requirement_patterns, render_template


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = ROOT / "domain_packs" / "dlms_cosem" / "requirement_patterns.yaml"


class PatternEngineTests(unittest.TestCase):
    def test_load_requirement_patterns_from_domain_pack(self) -> None:
        patterns = load_requirement_patterns(PATTERNS)

        self.assertGreaterEqual(len(patterns), 5)
        self.assertIn("cosem_attribute_access", {pattern.pattern_id for pattern in patterns})

    def test_render_template_resolves_dotted_paths(self) -> None:
        source = {
            "fields": {
                "Object/attribute name": "logical_name",
                "Access rights RC/PC/SC/LC": "R-/R-/R-/R-",
            },
            "cosem_object_context": {
                "object_name": "SAP Assignment",
                "class_id": 17,
                "obis": "0-0:41.0.0.255",
            },
        }

        rendered = render_template(
            "{cosem_object_context.object_name}.{fields.Object/attribute name}: {fields.Access rights RC/PC/SC/LC}",
            source,
        )

        self.assertEqual(rendered, "SAP Assignment.logical_name: R-/R-/R-/R-")

    def test_apply_patterns_generates_cosem_attribute_requirement(self) -> None:
        patterns = load_requirement_patterns(PATTERNS)
        source = {
            "source_type": "table_item",
            "fields": {
                "Object/attribute name": "logical_name",
                "Access rights RC/PC/SC/LC": "R-/R-/R-/R-",
            },
            "cosem_object_context": {
                "object_name": "SAP Assignment",
                "class_id": 17,
                "obis": "0-0:41.0.0.255",
            },
        }

        rows = apply_requirement_patterns(source, patterns)
        row = next(row for row in rows if row["pattern_id"] == "cosem_attribute_access")

        self.assertEqual(row["generic_type"], "access_constraint")
        self.assertEqual(row["requirement_type"], "cosem_attribute_access")
        self.assertEqual(row["object"], "SAP Assignment.logical_name")
        self.assertIn("OBIS 0-0:41.0.0.255", row["requirement"])


if __name__ == "__main__":
    unittest.main()
