from __future__ import annotations

import unittest

import compliance


class ComplianceClassificationTests(unittest.TestCase):
    def test_approved_according_to_named_standard_is_compliance(self) -> None:
        source = "The meter shall be approved according to STN EN 62053-22 before delivery."

        self.assertTrue(compliance.looks_like_compliance(source))

    def test_approval_without_a_numbered_standard_is_not_compliance(self) -> None:
        samples = [
            "The design shall be approved according to internal review procedure.",
            "The meter shall be approved according to IEC.",
            "The design needs approval according to ISO guidelines.",
            "The meter shall be approved according to EN procedure.",
        ]

        for source in samples:
            with self.subTest(source=source):
                self.assertFalse(compliance.contains_compliance_signal(source))
                self.assertFalse(compliance.looks_like_compliance(source))

    def test_technical_action_is_not_reclassified_by_approval_signal(self) -> None:
        source = (
            "The meter shall measure and record energy; "
            "it is approved according to IEC 62053."
        )

        self.assertTrue(compliance.contains_compliance_signal(source))
        self.assertFalse(compliance.looks_like_compliance(source))

    def test_certificate_and_legislation_obligations_are_compliance(self) -> None:
        samples = [
            "Valid Certificate according to the standard STN EN 62053-22.",
            "The meter must comply with national metrological legislation.",
            "EU declaration of conformity or Declaration of Conformity.",
            "The initial verification period must comply with Decree no. 161/2019 Coll.",
        ]
        for sample in samples:
            self.assertTrue(compliance.looks_like_compliance(sample), sample)

    def test_behavior_and_accuracy_references_are_not_retyped_as_compliance(self) -> None:
        samples = [
            "Communication must use DLMS/COSEM standards based on IP.",
            "Accuracy class 0.2 S for active energy according to STN EN 62053-22.",
            (
                "The meter must meet mechanical environmental class M1 in accordance with "
                "Regulation of the Government No. 145/2016."
            ),
        ]
        for sample in samples:
            self.assertFalse(compliance.looks_like_compliance(sample), sample)

    def test_generated_fields_cannot_create_compliance_without_source_evidence(self) -> None:
        requirement = {
            "type": "compliance",
            "title": "Legal certificate",
            "description": "A declaration of conformity shall be supplied.",
            "source_quote": "The meter shall communicate bidirectionally over DLMS/COSEM.",
        }

        self.assertFalse(compliance.is_compliance_requirement(requirement))

    def test_mixed_technical_requirement_is_not_wholly_routed_to_compliance(self) -> None:
        source = (
            "Electricity meters must show resistance to electrostatic discharges according to "
            "STN EN 61000-4-2. We require a certificate of conformity to be supplied."
        )

        self.assertTrue(compliance.contains_compliance_signal(source))
        self.assertFalse(compliance.looks_like_compliance(source))
        self.assertFalse(compliance.is_compliance_requirement({
            "type": "constraint",
            "module": "环境可靠性",
            "source_quote": source,
        }))

    def test_decree_reference_does_not_remove_nameplate_requirements_from_core(self) -> None:
        source = (
            "It must be made in accordance with decree no. 161/2019 Coll. "
            "The type plate must be located on the front side of the electricity meter and "
            "must be resistant to UV radiation throughout the life of the meter."
        )

        self.assertTrue(compliance.contains_compliance_signal(source))
        self.assertFalse(compliance.looks_like_compliance(source))

    def test_declaration_content_sentence_remains_pure_compliance(self) -> None:
        self.assertTrue(compliance.looks_like_compliance(
            "The declaration of conformity shall contain the applicable legal references."
        ))

    def test_pure_compliance_source_is_classified_regardless_of_model_type(self) -> None:
        requirement = {
            "type": "constraint",
            "source_quote": "Valid Certificate according to the standard STN EN 62053-22.",
        }

        self.assertTrue(compliance.is_compliance_requirement(requirement))

    def test_instrument_must_be_literal_source_evidence(self) -> None:
        source = "Valid Certificate according to the standard STN EN 62053-22."

        self.assertEqual(
            compliance.source_backed_instrument("STN EN 62053-22", source),
            "STN EN 62053-22",
        )
        self.assertEqual(
            compliance.source_backed_instrument("IEC 99999", source),
            "",
        )

    def test_ambiguous_source_instruments_are_not_guessed(self) -> None:
        source = "Certificates according to IEC 62053-22 and IEC 62053-23 shall be supplied."

        self.assertEqual(compliance.source_backed_instrument("", source), "")

    def test_instrument_requires_an_actual_identifier(self) -> None:
        source = "The enclosure shall comply with the Regulation of the Slovak Republic."

        self.assertEqual(compliance.source_backed_instrument("Regulation of", source), "")

    def test_payload_keeps_one_umbrella_item_with_multiple_obligations(self) -> None:
        payload = compliance.build_compliance_payload([{
            "ai_req_id": "AIR-1",
            "title": "Legal deliverables",
            "type": "compliance",
            "compliance_umbrella": True,
            "compliance_instrument": "Decree no. 161/2019 Coll.",
            "compliance_obligations": [
                {"label": "a", "text": "Provide the type certificate."},
                {"label": "b", "text": "Provide the declaration of conformity."},
            ],
            "source_quote": (
                "A type certificate and declaration of conformity shall be supplied under "
                "Decree no. 161/2019 Coll."
            ),
        }])

        self.assertEqual(payload["count"], 1)
        self.assertTrue(payload["items"][0]["umbrella"])
        self.assertEqual(len(payload["items"][0]["obligations"]), 2)

    def test_multiple_source_subitems_are_deterministically_marked_as_umbrella(self) -> None:
        payload = compliance.build_compliance_payload([{
            "ai_req_id": "AIR-2",
            "title": "Certificates and declarations",
            "type": "compliance",
            "sub_items": [
                {"label": "a", "text": "Provide the type certificate."},
                {"label": "b", "text": "Provide the declaration of conformity."},
            ],
            "source_quote": "Provide the type certificate and declaration of conformity.",
        }])

        self.assertTrue(payload["items"][0]["umbrella"])

    def test_model_umbrella_flag_cannot_override_single_obligation(self) -> None:
        item = compliance.compliance_item({
            "ai_req_id": "AIR-3",
            "compliance_umbrella": True,
            "compliance_obligations": [{"text": "Provide the declaration of conformity."}],
            "source_quote": "The declaration of conformity shall be supplied.",
        })

        self.assertFalse(item["umbrella"])

    def test_multiple_model_obligations_cannot_create_an_umbrella_without_source_structure(self) -> None:
        item = compliance.compliance_item({
            "ai_req_id": "AIR-4",
            "compliance_obligations": [
                {"text": "Provide one certificate."},
                {"text": "Provide another certificate."},
            ],
            "source_quote": "A valid type certificate shall be supplied.",
        })

        self.assertFalse(item["umbrella"])


if __name__ == "__main__":
    unittest.main()
