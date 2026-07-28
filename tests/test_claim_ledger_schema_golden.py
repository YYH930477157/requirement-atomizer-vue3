from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

import claim_catalog
import claim_held_out
import claim_ledger
from source_spans import source_alignment_fields


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
GOLDEN_DIR = ROOT / "golden_sets" / "claim_ledger_v1"

SCHEMA_PATHS = {
    "catalog": SCHEMA_DIR / "claim_catalog.schema.json",
    "catalog_meta": SCHEMA_DIR / "claim_catalog_meta.schema.json",
    "coverage_group": SCHEMA_DIR / "claim_coverage_group.schema.json",
    "ledger": SCHEMA_DIR / "claim_ledger.schema.json",
    "shadow_meta": SCHEMA_DIR / "claim_shadow_meta.schema.json",
    "golden_manifest": SCHEMA_DIR / "claim_ledger_golden_manifest.schema.json",
    "review_decisions": SCHEMA_DIR / "claim_shadow_review_decisions.schema.json",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _claim_matches(claim: dict[str, Any], selector: dict[str, Any]) -> bool:
    locator = claim.get("locator") or {}
    for key, expected in selector.items():
        actual = locator.get(key) if key in {
            "block_id", "table_item_id", "row_index", "row_start", "row_end",
            "fallback_group_id", "start", "end",
        } else claim.get(key)
        if actual != expected:
            return False
    return True


class ClaimLedgerSchemaGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = {name: _read_json(path) for name, path in SCHEMA_PATHS.items()}
        cls.validators = {
            name: Draft202012Validator(schema) for name, schema in cls.schemas.items()
        }
        cls.manifest = _read_json(GOLDEN_DIR / "manifest.json")
        cls.inputs = _read_json(GOLDEN_DIR / "inputs.json")
        cls.expected = _read_json(GOLDEN_DIR / "expected.json")

    def test_schemas_are_valid_draft_2020_12_and_reject_incomplete_rows(self) -> None:
        for schema in self.schemas.values():
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            Draft202012Validator.check_schema(schema)

        incomplete = {
            "schema": "claim-catalog/v1",
            "catalog_version": "claim-catalog-v4",
        }
        with self.assertRaises(ValidationError):
            self.validators["catalog"].validate(incomplete)

        raw = "The  meter shall record data.\n"
        repaired = "The meter shall record data."
        block = {
            "block_id": "B-RULE",
            "order": 1,
            "type": "paragraph",
            "text": repaired,
            "raw_text": raw,
            **source_alignment_fields(raw, repaired),
            "section_path": ["Synthetic"],
            "noise": False,
        }
        claim = claim_catalog.build_claim_catalog([block], [])["catalog"][0]
        self.validators["catalog"].validate(claim)
        separator_claim = claim_catalog.build_claim_catalog(
            [{
                **block,
                "block_id": "B-SEPARATOR",
                "text": "...",
                "raw_text": "...",
                **source_alignment_fields("...", "..."),
            }],
            [],
        )["catalog"][0]
        self.validators["catalog"].validate(separator_claim)
        broken = copy.deepcopy(claim)
        changed = next(
            opcode for opcode in broken["source_alignment"]["opcodes"]
            if opcode["tag"] != "equal"
        )
        changed.pop("transformation")
        with self.assertRaises(ValidationError):
            self.validators["catalog"].validate(broken)

        contradictions = []
        mapped_without_locator = copy.deepcopy(claim)
        mapped_without_locator["raw_locator"] = None
        contradictions.append(mapped_without_locator)
        mapped_without_alignment = copy.deepcopy(claim)
        mapped_without_alignment["source_alignment"] = None
        contradictions.append(mapped_without_alignment)
        unavailable_with_mapping = copy.deepcopy(claim)
        unavailable_with_mapping["raw_mapping_status"] = "unavailable"
        contradictions.append(unavailable_with_mapping)
        unknown_rule = copy.deepcopy(claim)
        changed = next(
            opcode for opcode in unknown_rule["source_alignment"]["opcodes"]
            if opcode["tag"] != "equal"
        )
        changed["transformation"]["rule_id"] = "evil.rule"
        contradictions.append(unknown_rule)
        for contradiction in contradictions:
            with self.assertRaises(ValidationError):
                self.validators["catalog"].validate(contradiction)

    def test_schemas_reject_invalid_terminal_and_readiness_combinations(self) -> None:
        case = self.inputs["cases"][0]
        catalog_build = claim_catalog.build_claim_catalog(
            copy.deepcopy(case["blocks"]), copy.deepcopy(case["table_items"])
        )
        ledger_build = claim_ledger.build_shadow_ledger(
            catalog_build, copy.deepcopy(case["requirements"])
        )

        semantic_without_request = copy.deepcopy(ledger_build["groups"][0])
        semantic_without_request["status"] = "validated"
        semantic_without_request["validator_request_id"] = ""
        with self.assertRaises(ValidationError):
            self.validators["coverage_group"].validate(semantic_without_request)

        rejected_but_proposed = copy.deepcopy(ledger_build["groups"][0])
        rejected_but_proposed["prefilter"]["status"] = "reject"
        rejected_but_proposed["status"] = "proposed"
        with self.assertRaises(ValidationError):
            self.validators["coverage_group"].validate(rejected_but_proposed)

        covered_without_group = copy.deepcopy(ledger_build["ledger"][0])
        covered_without_group.update({
            "resolution": "covered",
            "classification": "normative",
            "classification_status": "validated",
            "coverage_group_ids": [],
        })
        with self.assertRaises(ValidationError):
            self.validators["ledger"].validate(covered_without_group)

        false_ready = copy.deepcopy(ledger_build["meta"])
        false_ready["document_ready"] = True
        with self.assertRaises(ValidationError):
            self.validators["shadow_meta"].validate(false_ready)

    def test_schema_rejects_forged_registered_transformation_metadata(self) -> None:
        raw = "The  meter records data."
        repaired = "The meter records data."
        block = {
            "block_id": "B-FORGED-RULE",
            "order": 1,
            "type": "paragraph",
            "text": repaired,
            "raw_text": raw,
            **source_alignment_fields(raw, repaired),
            "section_path": ["Synthetic"],
            "noise": False,
        }
        claim = claim_catalog.build_claim_catalog([block], [])["catalog"][0]

        for field, forged in (
            ("rule_version", "source-whitespace-forged-v1"),
            ("reason", "normalization.forged"),
        ):
            with self.subTest(field=field):
                forged_claim = copy.deepcopy(claim)
                forged_opcode = next(
                    opcode for opcode in forged_claim["source_alignment"]["opcodes"]
                    if opcode["tag"] != "equal"
                )
                forged_opcode["transformation"][field] = forged
                with self.assertRaises(ValidationError):
                    self.validators["catalog"].validate(forged_claim)

    def test_catalog_meta_schema_rejects_pattern_valid_stale_ruleset(self) -> None:
        build = claim_catalog.build_claim_catalog(
            [{
                "block_id": "B-STALE-RULESET",
                "order": 1,
                "type": "paragraph",
                "text": "The meter records data.",
                "raw_text": "The meter records data.",
                "section_path": ["Synthetic"],
                "noise": False,
            }],
            [],
        )
        stale = copy.deepcopy(build["meta"])
        stale["parser_provenance"]["source_transformation_ruleset_version"] = (
            "source-transform-rules-v3-deadbeef0000"
        )

        with self.assertRaises(ValidationError):
            self.validators["catalog_meta"].validate(stale)

    def test_incomplete_negative_proposal_is_schema_valid_but_cannot_close(self) -> None:
        block = {
            "block_id": "NEG-INCOMPLETE",
            "order": 1,
            "type": "paragraph",
            "text": "A generic note.",
            "section_path": ["Synthetic"],
            "noise": False,
        }
        catalog_build = claim_catalog.build_claim_catalog([block], [])

        def proposer(_unit_id: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "request_id": "bad-negative-proposal",
                "usage_complete": True,
                "decisions": {claims[0]["claim_id"]: {
                    "non_normative": True,
                    "reason": "",
                    "evidence": [],
                }},
            }

        result = claim_ledger.build_shadow_ledger(
            catalog_build,
            [],
            semantic_negative_proposer=proposer,
        )

        row = result["ledger"][0]
        self.validators["ledger"].validate(row)
        self.assertEqual(row["resolution"], "uncertain")
        self.assertEqual(row["semantic_negative"]["status"], "invalid")

    def test_manifest_is_anonymous_complete_and_has_a_frozen_held_out_partition(self) -> None:
        case_ids = [case["case_id"] for case in self.inputs["cases"]]
        expected_ids = [case["case_id"] for case in self.expected["cases"]]
        declared_ids = [case["case_id"] for case in self.manifest["cases"]]
        self.assertEqual(case_ids, expected_ids)
        self.assertEqual(case_ids, declared_ids)
        self.assertEqual(self.manifest["case_count"], len(case_ids))
        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertEqual(self.manifest["schema"], "claim-ledger-golden-manifest/v3")
        self.assertEqual(self.manifest["version"], "claim-ledger-golden-v4")
        self.assertEqual(
            self.manifest["curation"]["review_contract_version"],
            "claim-golden-heldout-review-v2",
        )

        held_out = [case for case in self.manifest["cases"] if case["partition"] == "held_out"]
        self.assertGreaterEqual(len(held_out), 1)
        self.assertTrue(all(case["tuning_eligible"] is False for case in held_out))
        self.assertEqual(
            self.manifest["partition_counts"]["held_out"],
            len(held_out),
        )
        self.validators["golden_manifest"].validate(self.manifest)
        held_out_summary = claim_held_out.summarize_held_out_review(
            claim_held_out.load_golden_held_out(GOLDEN_DIR)
        )
        if self.manifest["curation"]["human_review_status"] == "pending":
            self.assertEqual(held_out_summary["evidence_status"], "pending")
        else:
            self.assertEqual(
                self.manifest["curation"]["human_review_status"],
                "reviewed",
            )
            self.assertIn(
                held_out_summary["evidence_status"],
                {"complete", "not_approved"},
            )

        serialized = json.dumps(
            {"manifest": self.manifest, "inputs": self.inputs, "expected": self.expected},
            ensure_ascii=False,
        ).casefold()
        self.assertNotRegex(serialized, r"[a-z]:[\\/]")
        self.assertNotIn(r"\\users\\", serialized)
        self.assertNotIn("/users/", serialized)
        self.assertNotRegex(serialized, r"\btest\d+\b")
        for case in self.inputs["cases"]:
            self.assertEqual(case["source"]["origin"], "synthetic")
            self.assertFalse(case["source"]["contains_customer_wording"])

        prior = next(
            case for case in self.manifest["cases"]
            if case["case_id"] == "programmable-equivalent-001"
        )
        self.assertEqual(prior["partition"], "development")
        self.assertTrue(prior["tuning_eligible"])
        self.assertEqual(
            [case["case_id"] for case in held_out],
            ["configurable-interface-capability-001"],
        )
        self.assertEqual(len(self.manifest["baseline_revisions"]), 2)

    def test_manifest_v3_requires_exact_dimension_verdicts(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["curation"].update({
            "human_review_status": "reviewed",
            "reviewed_by": "independent-reviewer",
            "reviewed_at": "2026-07-27T16:00:00Z",
        })
        item = claim_held_out.load_golden_held_out(GOLDEN_DIR)["review_items"][0]
        manifest["curation"]["held_out_adjudications"] = [{
            "case_id": item["case_id"],
            "claim_id": item["claim_id"],
            "claim_hash": item["claim_hash"],
            "fixture_hash": item["fixture_hash"],
            "dimension_verdicts": {
                dimension: "agree"
                for dimension in claim_held_out.HELD_OUT_REVIEW_DIMENSIONS
            },
            "rationale": "All seven dimensions agree with the replacement fixture.",
        }]
        self.validators["golden_manifest"].validate(manifest)

        for mutation in ("missing", "extra", "legacy"):
            with self.subTest(mutation=mutation):
                broken = copy.deepcopy(manifest)
                adjudication = broken["curation"]["held_out_adjudications"][0]
                if mutation == "missing":
                    adjudication["dimension_verdicts"].pop("target_modality")
                elif mutation == "extra":
                    adjudication["dimension_verdicts"]["other"] = "agree"
                else:
                    adjudication["verdict"] = "agree"
                with self.assertRaises(ValidationError):
                    self.validators["golden_manifest"].validate(broken)

    def test_every_golden_case_rebuilds_to_schema_valid_claim_level_expectations(self) -> None:
        expected_by_id = {case["case_id"]: case for case in self.expected["cases"]}
        for case in self.inputs["cases"]:
            with self.subTest(case_id=case["case_id"]):
                catalog_build = claim_catalog.build_claim_catalog(
                    copy.deepcopy(case["blocks"]),
                    copy.deepcopy(case["table_items"]),
                    scope=case.get("scope", "full"),
                )
                negative_fixture = copy.deepcopy(case.get("semantic_negative_fixture"))
                negative_proposer = None
                negative_verifier = None
                if isinstance(negative_fixture, dict):
                    def negative_proposer(
                        _unit_id: str,
                        claims: list[dict[str, Any]],
                    ) -> dict[str, Any]:
                        claim = claims[0]
                        text = str(claim["source_evidence"]["text"])
                        return {
                            "request_id": "golden-negative-proposal",
                            "usage_complete": True,
                            "decisions": {claim["claim_id"]: {
                                "non_normative": True,
                                "reason": negative_fixture["proposal_reason"],
                                "evidence": [{"start": 0, "end": len(text), "text": text}],
                            }},
                        }

                    def negative_verifier(
                        _unit_id: str,
                        claims: list[dict[str, Any]],
                    ) -> dict[str, Any]:
                        claim = claims[0]
                        text = str(claim["source_evidence"]["text"])
                        return {
                            "request_id": "golden-negative-verifier",
                            "usage_complete": True,
                            "decisions": {claim["claim_id"]: {
                                "non_normative": True,
                                "reason": negative_fixture["validator_reason"],
                                "checks": {
                                    name: negative_fixture.get("all_checks") is True
                                    for name in claim_ledger.SEMANTIC_NEGATIVE_CHECKS
                                },
                                "evidence": [{"start": 0, "end": len(text), "text": text}],
                            }},
                        }
                ledger_build = claim_ledger.build_shadow_ledger(
                    catalog_build,
                    copy.deepcopy(case["requirements"]),
                    review_states=copy.deepcopy(case.get("review_states") or {}),
                    controlled_term_aliases=copy.deepcopy(
                        case.get("controlled_term_aliases") or {}
                    ),
                    semantic_negative_proposer=negative_proposer,
                    semantic_negative_verifier=negative_verifier,
                )
                expected = expected_by_id[case["case_id"]]

                self.validators["catalog_meta"].validate(catalog_build["meta"])
                self.validators["shadow_meta"].validate(ledger_build["meta"])
                for row in catalog_build["catalog"]:
                    self.validators["catalog"].validate(row)
                for group in ledger_build["groups"]:
                    self.validators["coverage_group"].validate(group)
                    target_by_id = {
                        str(requirement["ai_req_id"]): requirement
                        for requirement in case["requirements"]
                    }
                    for edge in group["edges"]:
                        target = target_by_id[edge["target_requirement_id"]]
                        for evidence in edge["produced_evidence"]:
                            self.assertTrue(claim_ledger.evidence_is_current(evidence, target))
                for row in ledger_build["ledger"]:
                    self.validators["ledger"].validate(row)

                self.assertEqual(len(catalog_build["catalog"]), expected["catalog_count"])
                self.assertEqual(len(ledger_build["groups"]), expected["group_count"])
                self.assertEqual(len(ledger_build["ledger"]), expected["catalog_count"])
                self.assertEqual(
                    len(catalog_build["meta"]["container_mappings"]),
                    expected["container_mapping_count"],
                )
                self.assertEqual(
                    catalog_build["meta"]["accounting_status"],
                    expected["accounting_status"],
                )
                self.assertEqual(
                    ledger_build["meta"]["resolution_status"],
                    expected["resolution_status"],
                )

                matched_claim_ids: set[str] = set()
                ledger_by_claim = {row["claim_id"]: row for row in ledger_build["ledger"]}
                groups_by_claim: dict[str, list[dict[str, Any]]] = {}
                for group in ledger_build["groups"]:
                    groups_by_claim.setdefault(group["claim_id"], []).append(group)

                for claim_expected in expected["claims"]:
                    matches = [
                        row for row in catalog_build["catalog"]
                        if _claim_matches(row, claim_expected["selector"])
                    ]
                    self.assertEqual(len(matches), 1, claim_expected["selector"])
                    claim = matches[0]
                    self.assertNotIn(claim["claim_id"], matched_claim_ids)
                    matched_claim_ids.add(claim["claim_id"])

                    for key, value in claim_expected["catalog"].items():
                        self.assertEqual(claim.get(key), value, key)
                    ledger_row = ledger_by_claim[claim["claim_id"]]
                    for key, value in claim_expected["ledger"].items():
                        self.assertEqual(ledger_row.get(key), value, key)

                    groups = groups_by_claim.get(claim["claim_id"], [])
                    coverage_expected = claim_expected.get("coverage")
                    if coverage_expected is None:
                        self.assertEqual(groups, [])
                    else:
                        self.assertEqual(len(groups), 1)
                        group = groups[0]
                        self.assertEqual(
                            {
                                "validation_method": group["validation_method"],
                                "status": group["status"],
                                "prefilter_status": group["prefilter"]["status"],
                                "edge_count": len(group["edges"]),
                            },
                            coverage_expected,
                        )

                self.assertEqual(len(matched_claim_ids), len(catalog_build["catalog"]))


if __name__ == "__main__":
    unittest.main()
