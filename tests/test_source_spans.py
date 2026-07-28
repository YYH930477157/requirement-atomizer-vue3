from __future__ import annotations

import unittest

from source_spans import (
    SOURCE_TRANSFORMATION_POLICY_VERSION,
    build_source_alignment,
    pdf_text_repair_provenance,
    source_alignment_is_approved,
    source_alignment_fields,
    validate_source_alignment,
)


class SourceAlignmentTests(unittest.TestCase):
    def test_opcode_map_deterministically_covers_raw_and_repaired_text(self) -> None:
        raw = "Auxiliary  outputs are user programmable.\n"
        repaired = "Auxiliary outputs are user programmable."

        first = build_source_alignment(raw, repaired)
        second = build_source_alignment(raw, repaired)

        self.assertEqual(first, second)
        validate_source_alignment(raw, repaired, first)
        self.assertEqual(first["raw_length"], len(raw))
        self.assertEqual(first["repaired_length"], len(repaired))
        self.assertEqual(first["opcodes"][0]["raw_start"], 0)
        self.assertEqual(first["opcodes"][0]["repaired_start"], 0)
        self.assertEqual(first["opcodes"][-1]["raw_end"], len(raw))
        self.assertEqual(first["opcodes"][-1]["repaired_end"], len(repaired))
        self.assertTrue(any(opcode["tag"] != "equal" for opcode in first["opcodes"]))
        for opcode in first["opcodes"]:
            if opcode["tag"] == "equal":
                continue
            transformation = opcode["transformation"]
            self.assertEqual(
                transformation["policy_version"], SOURCE_TRANSFORMATION_POLICY_VERSION)
            self.assertTrue(transformation["rule_id"])
            self.assertTrue(transformation["rule_version"])
            self.assertTrue(transformation["reason"])
            self.assertTrue(transformation["allowed"])
        self.assertTrue(source_alignment_is_approved(raw, repaired, first))

    def test_identity_alignment_uses_one_equal_opcode(self) -> None:
        alignment = build_source_alignment("same text", "same text")

        self.assertEqual(alignment["opcodes"], [{
            "tag": "equal",
            "raw_start": 0,
            "raw_end": 9,
            "repaired_start": 0,
            "repaired_end": 9,
        }])
        validate_source_alignment("same text", "same text", alignment)

    def test_persisted_fields_include_flat_raw_to_repaired_spans(self) -> None:
        fields = source_alignment_fields("me ter", "meter")

        validate_source_alignment("me ter", "meter", fields["source_alignment"])
        self.assertEqual(
            fields["raw_to_repaired_spans"],
            [
                {
                    "operation": opcode["tag"],
                    "raw_start": opcode["raw_start"],
                    "raw_end": opcode["raw_end"],
                    "repaired_start": opcode["repaired_start"],
                    "repaired_end": opcode["repaired_end"],
                }
                for opcode in fields["source_alignment"]["opcodes"]
            ],
        )

    def test_validator_rejects_a_gap_in_either_coordinate_space(self) -> None:
        raw = "broken source"
        repaired = "fixed source"
        alignment = build_source_alignment(raw, repaired)
        alignment["opcodes"][0]["raw_start"] = 1

        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_source_alignment(raw, repaired, alignment)

    def test_validator_rejects_unexplained_change(self) -> None:
        alignment = build_source_alignment("me ter", "meter")
        changed = next(opcode for opcode in alignment["opcodes"] if opcode["tag"] != "equal")
        changed.pop("transformation", None)
        with self.assertRaisesRegex(ValueError, "transformation"):
            validate_source_alignment("me ter", "meter", alignment)

    def test_semantic_replacement_is_audited_but_not_approved(self) -> None:
        raw = "The meter shall expose the output."
        repaired = "The meter may expose the output."

        alignment = build_source_alignment(raw, repaired)

        validate_source_alignment(raw, repaired, alignment)
        transformations = [
            opcode["transformation"]
            for opcode in alignment["opcodes"]
            if opcode["tag"] != "equal"
        ]
        self.assertTrue(transformations)
        self.assertTrue(all(item["allowed"] is False for item in transformations))
        self.assertTrue(all(item["reason"] == "unapproved.non_layout_character_change"
                            for item in transformations))
        self.assertFalse(source_alignment_is_approved(raw, repaired, alignment))

    def test_registered_character_rule_is_replayable(self) -> None:
        raw = "The meter shall use \u201cGET\u201d."
        repaired = 'The meter shall use "GET".'
        alignment = build_source_alignment(raw, repaired)
        validate_source_alignment(raw, repaired, alignment)
        transformations = {
            opcode["transformation"]["rule_id"]
            for opcode in alignment["opcodes"] if opcode["tag"] != "equal"
        }
        self.assertEqual(transformations, {"source.character_replacement"})
        self.assertTrue(source_alignment_is_approved(raw, repaired, alignment))

    def test_pdf_word_repair_requires_current_replay_provenance(self) -> None:
        from parsers.pdf_parser import (
            PDF_TEXT_REPAIR_VERSION,
            text_repair_vocabulary_fingerprint,
        )

        raw = "The m eter shall record data."
        repaired = "The meter shall record data."
        without_proof = build_source_alignment(raw, repaired)
        proof = pdf_text_repair_provenance(
            PDF_TEXT_REPAIR_VERSION,
            text_repair_vocabulary_fingerprint(),
        )
        with_proof = build_source_alignment(
            raw,
            repaired,
            repair_provenance=proof,
        )

        self.assertFalse(source_alignment_is_approved(raw, repaired, without_proof))
        self.assertTrue(source_alignment_is_approved(raw, repaired, with_proof))
        rules = {
            opcode["transformation"]["rule_id"]
            for opcode in with_proof["opcodes"] if opcode["tag"] != "equal"
        }
        self.assertEqual(rules, {"source.pdf_text_repair_replay"})

        stale = dict(with_proof)
        stale["repair_provenance"] = dict(with_proof["repair_provenance"])
        stale["repair_provenance"]["producer_version"] = "pdf-text-repair-vNEXT"
        with self.assertRaisesRegex(ValueError, "stale source repair provenance"):
            validate_source_alignment(raw, repaired, stale)

    def test_pdf_repair_replay_does_not_cross_list_line_boundaries(self) -> None:
        from parsers.pdf_parser import (
            PDF_TEXT_REPAIR_VERSION,
            text_repair_vocabulary_fingerprint,
        )

        raw = "m eter\ni sobliged"
        repaired = "meter\nis obliged"
        proof = pdf_text_repair_provenance(
            PDF_TEXT_REPAIR_VERSION,
            text_repair_vocabulary_fingerprint(),
        )

        alignment = build_source_alignment(
            raw,
            repaired,
            repair_provenance=proof,
        )

        validate_source_alignment(raw, repaired, alignment)
        self.assertTrue(source_alignment_is_approved(raw, repaired, alignment))

    def test_stale_pdf_provenance_is_rejected_even_when_text_is_identity(self) -> None:
        from parsers.pdf_parser import (
            PDF_TEXT_REPAIR_VERSION,
            text_repair_vocabulary_fingerprint,
        )

        proof = pdf_text_repair_provenance(
            PDF_TEXT_REPAIR_VERSION,
            text_repair_vocabulary_fingerprint(),
        )
        alignment = build_source_alignment(
            "The meter records data.",
            "The meter records data.",
            repair_provenance=proof,
        )
        alignment["repair_provenance"] = dict(proof)
        alignment["repair_provenance"]["vocabulary_fingerprint"] = "sha256:stale"

        with self.assertRaisesRegex(ValueError, "stale source repair provenance"):
            validate_source_alignment(
                "The meter records data.",
                "The meter records data.",
                alignment,
            )

    def test_valid_pdf_provenance_does_not_authorize_unreplayed_change(self) -> None:
        from parsers.pdf_parser import (
            PDF_TEXT_REPAIR_VERSION,
            text_repair_vocabulary_fingerprint,
        )

        proof = pdf_text_repair_provenance(
            PDF_TEXT_REPAIR_VERSION,
            text_repair_vocabulary_fingerprint(),
        )
        alignment = build_source_alignment(
            "cannot",
            "can not",
            repair_provenance=proof,
        )

        self.assertFalse(source_alignment_is_approved("cannot", "can not", alignment))

    def test_whitespace_rule_rejects_token_boundary_changes(self) -> None:
        cases = [
            ("10 V", "1 0 V"),
            ("cannot", "can not"),
            ("ab cd", "a bcd"),
            ("Aux iliary", "Auxiliary"),
        ]
        for raw, repaired in cases:
            with self.subTest(raw=raw, repaired=repaired):
                alignment = build_source_alignment(raw, repaired)
                self.assertFalse(source_alignment_is_approved(raw, repaired, alignment))

    def test_mixed_registered_changes_use_an_explicit_composite_rule(self) -> None:
        raw = "The meter  shall use \u201cGET\u201d."
        repaired = 'The meter shall use "GET".'

        alignment = build_source_alignment(raw, repaired)

        validate_source_alignment(raw, repaired, alignment)
        transformations = {
            opcode["transformation"]["rule_id"]
            for opcode in alignment["opcodes"] if opcode["tag"] != "equal"
        }
        self.assertEqual(
            transformations,
            {"source.composite_character_whitespace"},
        )
        self.assertTrue(source_alignment_is_approved(raw, repaired, alignment))

    def test_validator_rejects_forged_rule_metadata(self) -> None:
        raw = "The meter shall expose the output."
        repaired = "The meter may expose the output."
        alignment = build_source_alignment(raw, repaired)
        changed = next(opcode for opcode in alignment["opcodes"] if opcode["tag"] != "equal")
        changed["transformation"] = {
            "policy_version": SOURCE_TRANSFORMATION_POLICY_VERSION,
            "rule_id": "source.whitespace_normalization",
            "rule_version": "source-whitespace-v2",
            "reason": "normalization.whitespace",
            "allowed": True,
        }

        with self.assertRaisesRegex(ValueError, "transformation metadata mismatch"):
            validate_source_alignment(raw, repaired, alignment)

    def test_validator_rejects_resegmented_opcodes_with_valid_rule_metadata(self) -> None:
        raw = "me ter"
        repaired = "meter"
        alignment = build_source_alignment(raw, repaired)
        transformation = next(
            opcode["transformation"]
            for opcode in alignment["opcodes"]
            if opcode["tag"] != "equal"
        )
        alignment["opcodes"] = [{
            "tag": "replace",
            "raw_start": 0,
            "raw_end": len(raw),
            "repaired_start": 0,
            "repaired_end": len(repaired),
            "transformation": transformation,
            "raw_deletion_reason": transformation["reason"],
            "repaired_insertion_source": transformation["reason"],
        }]

        with self.assertRaisesRegex(ValueError, "deterministic opcode sequence"):
            validate_source_alignment(raw, repaired, alignment)


if __name__ == "__main__":
    unittest.main()
