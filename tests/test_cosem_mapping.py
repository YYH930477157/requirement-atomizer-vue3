import unittest

from cosem_mapping import (
    COSEM_MAPPING_SCHEMA,
    COSEM_MAPPING_VERSION,
    attach_functional_mappings,
    map_functional_requirement,
)


class CosemMappingTests(unittest.TestCase):
    def test_resolves_obis_and_whitelisted_class_without_llm(self) -> None:
        item = {
            "objective": "Expose Register value through OBIS 1-0:1.8.0.255",
            "description": "interface class 3, read only",
        }
        mapping = map_functional_requirement(item)
        self.assertEqual(mapping["schema"], COSEM_MAPPING_SCHEMA)
        self.assertEqual(mapping["version"], COSEM_MAPPING_VERSION)
        self.assertEqual(mapping["status"], "mapped")
        self.assertEqual(mapping["obis"], ["1-0:1.8.0.255"])
        self.assertEqual(mapping["class_names"], ["Register"])
        self.assertEqual(mapping["unresolved_class_ids"], [])

    def test_unknown_class_stays_candidate_and_is_not_invented(self) -> None:
        mapping = map_functional_requirement({"objective": "DLMS interface class 99"})
        self.assertEqual(mapping["status"], "candidate")
        self.assertEqual(mapping["class_ids"], ["99"])
        self.assertEqual(mapping["class_names"], [])
        self.assertEqual(mapping["unresolved_class_ids"], ["99"])

    def test_attach_adds_non_blocking_aggregate_and_preserves_items(self) -> None:
        payload = {"items": [{"objective": "The meter shall log events."}]}
        result = attach_functional_mappings(payload)
        self.assertIs(result, payload)
        self.assertEqual(result["domain_mapping"]["counts"]["unmapped"], 1)
        self.assertFalse(result["domain_mapping"]["blocking"])
        self.assertEqual(result["items"][0]["domain_mapping"]["status"], "unmapped")


if __name__ == "__main__":
    unittest.main()
