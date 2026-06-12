from __future__ import annotations

import unittest
from pathlib import Path

from atomize import DEFAULT_DOCUMENT_PROFILE, load_document_profile_from_domain_pack
from domain_pack import load_domain_pack


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "domain_packs" / "dlms_cosem" / "pack.yaml"


class DomainPackTests(unittest.TestCase):
    def test_load_dlms_cosem_domain_pack(self) -> None:
        pack = load_domain_pack(PACK)

        self.assertEqual(pack.pack_id, "dlms_cosem")
        self.assertIn("cosem_attribute_access", pack.capability_names("requirement_patterns"))
        self.assertTrue(pack.resolve_file("requirement_patterns").exists())
        self.assertTrue(pack.resolve_file("table_patterns").exists())
        self.assertTrue(pack.resolve_file("kb_sources").exists())
        self.assertTrue(pack.resolve_file("golden_set").exists())

    def test_knowledge_base_paths_exist(self) -> None:
        pack = load_domain_pack(PACK)

        paths = pack.knowledge_base_paths()

        self.assertGreaterEqual(len(paths), 3)
        for path in paths:
            self.assertTrue(path.exists(), path)

    def test_document_profile_matches_default_abnt_profile(self) -> None:
        profile = load_document_profile_from_domain_pack(PACK.parent)

        self.assertEqual(profile, DEFAULT_DOCUMENT_PROFILE)


if __name__ == "__main__":
    unittest.main()
