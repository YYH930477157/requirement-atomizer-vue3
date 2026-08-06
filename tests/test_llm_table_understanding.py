"""Tests for llm_table_understanding.py — the WS1 dual-track proposer.

No real LLM calls: routing, prompt assembly, structural validation and degradation
are exercised via a stub config and an injected fake ``chat`` callable. A missing
route / any failure / malformed output must surface as an honest ``unavailable``
result so the caller falls back to the deterministic geometry single-track — the
proposer never fabricates a hypothesis.
"""
from __future__ import annotations

import unittest
from typing import Any

from docx_table_parser import (
    ParsedCell,
    ParsedCellContent,
    ParsedDocxTable,
)
from llm_table_understanding import (
    LLM_TABLE_UNDERSTANDING_PROMPT_VERSION,
    LLM_TABLE_UNDERSTANDING_VERSION,
    PROPOSED,
    UNAVAILABLE,
    TableUnderstandingUnavailable,
    build_proposal_prompt,
    propose_table_structure,
)
from table_geometry_validator import TABLE_STRUCTURE_HYPOTHESIS_VERSION


def _cell(r: int, c: int, text: str, **style: Any) -> ParsedCell:
    return ParsedCell(
        row_index=r,
        column_index=c,
        text=text,
        raw_text=text,
        style_evidence=dict(style),
        content=ParsedCellContent((), 0),
    )


def _parsed() -> ParsedDocxTable:
    cells = {
        (1, 1): _cell(1, 1, "Object/attribute name", bold=True),
        (1, 2): _cell(1, 2, "CL", bold=True),
        (1, 3): _cell(1, 3, "Value", bold=True),
        (2, 1): _cell(2, 1, "Logical Name"),
        (2, 2): _cell(2, 2, "1"),
        (2, 3): _cell(2, 3, "0-0:96.1.0"),
    }
    matrix = [
        ["Object/attribute name", "CL", "Value"],
        ["Logical Name", "1", "0-0:96.1.0"],
    ]
    return ParsedDocxTable(
        width=3,
        matrix=[list(row) for row in matrix],
        raw_matrix=[list(row) for row in matrix],
        cells=cells,
        merge_ranges=[],
        explicit_header_rows=[],
        nested_tables=[],
        parse_incomplete=False,
        parse_incomplete_reason={},
        raw_text="",
    )


def _valid_hypothesis() -> dict[str, Any]:
    return {
        "schema": TABLE_STRUCTURE_HYPOTHESIS_VERSION,
        "table_structure_version": "docx-table-physical-v1",
        "header_level_count": 1,
        "cells": [
            {"coordinate": [1, 1], "role": "header", "confidence": "high"},
            {"coordinate": [1, 2], "role": "header", "confidence": "high"},
            {"coordinate": [1, 3], "role": "header", "confidence": "high"},
            {"coordinate": [2, 1], "role": "data", "confidence": "high"},
            {"coordinate": [2, 2], "role": "data", "confidence": "high"},
            {"coordinate": [2, 3], "role": "data", "confidence": "high"},
        ],
        "semantic_merges": [],
    }


class _StubConfig:
    """A non-None config marker — when a fake chat is injected, config is not used."""


class _FakeChat:
    def __init__(self, payload: Any, *, raises: BaseException | None = None) -> None:
        self._payload = payload
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if self._raises is not None:
            raise self._raises
        return self._payload


class StubRoutingTests(unittest.TestCase):
    def test_no_config_returns_unavailable_stub_route(self) -> None:
        result = propose_table_structure(_parsed(), config=None)
        self.assertEqual(result.status, UNAVAILABLE)
        self.assertIsNone(result.hypothesis)
        self.assertEqual(result.route, "stub")
        self.assertEqual(result.reason, "no_openai_compatible_route")
        self.assertFalse(result.is_proposed)
        self.assertTrue(result.is_unavailable)

    def test_llm_call_exception_is_honest_unavailable(self) -> None:
        chat = _FakeChat(None, raises=RuntimeError("connection refused"))
        result = propose_table_structure(_parsed(), config=_StubConfig(), chat=chat)
        self.assertEqual(result.status, UNAVAILABLE)
        self.assertIsNone(result.hypothesis)
        self.assertEqual(result.route, "openai_compatible")
        self.assertIn("llm_call_failed", result.reason)
        self.assertIn("connection refused", result.reason)

    def test_non_object_response_is_unavailable(self) -> None:
        chat = _FakeChat("not a dict")
        result = propose_table_structure(_parsed(), config=_StubConfig(), chat=chat)
        self.assertEqual(result.status, UNAVAILABLE)
        self.assertEqual(result.reason, "model_returned_non_object")

    def test_proposed_hypothesis_round_trips(self) -> None:
        chat = _FakeChat(_valid_hypothesis())
        result = propose_table_structure(_parsed(), config=_StubConfig(), chat=chat)
        self.assertEqual(result.status, PROPOSED)
        self.assertEqual(result.route, "openai_compatible")
        self.assertEqual(result.reason, "")
        self.assertEqual(result.module_version, LLM_TABLE_UNDERSTANDING_VERSION)
        self.assertEqual(result.prompt_version, LLM_TABLE_UNDERSTANDING_PROMPT_VERSION)
        # The proposer is NOT the signing authority; the hypothesis must still pass the
        # geometry validator downstream. Here we only assert it is well-shaped.
        self.assertEqual(result.hypothesis["schema"], TABLE_STRUCTURE_HYPOTHESIS_VERSION)
        self.assertEqual(len(result.hypothesis["cells"]), 6)


class ShapeValidationTests(unittest.TestCase):
    """Malformed model output must never become a hypothesis (no fabrication)."""

    def _run(self, payload: Any) -> str:
        chat = _FakeChat(payload)
        result = propose_table_structure(_parsed(), config=_StubConfig(), chat=chat)
        self.assertEqual(result.status, UNAVAILABLE, msg=f"payload={payload}")
        return result.reason

    def test_wrong_schema_rejected(self) -> None:
        bad = _valid_hypothesis()
        bad["schema"] = "something-else/v1"
        self.assertTrue(self._run(bad).startswith("shape_invalid:"))

    def test_bad_role_rejected(self) -> None:
        bad = _valid_hypothesis()
        bad["cells"][0]["role"] = "caption"  # not in enum
        self.assertIn("role not in enum", self._run(bad))

    def test_bad_coordinate_rejected(self) -> None:
        bad = _valid_hypothesis()
        bad["cells"][0]["coordinate"] = [0, 1]  # < 1
        self.assertIn("coordinate invalid", self._run(bad))

    def test_extra_top_level_key_rejected(self) -> None:
        bad = _valid_hypothesis()
        bad["narrative_summary"] = "free text must not leak"
        self.assertIn("top-level must have exactly", self._run(bad))

    def test_extra_cell_key_rejected(self) -> None:
        bad = _valid_hypothesis()
        bad["cells"][0]["rationale"] = "free text must not leak"
        self.assertIn("exactly coordinate/role/confidence", self._run(bad))

    def test_bad_confidence_rejected(self) -> None:
        bad = _valid_hypothesis()
        bad["cells"][0]["confidence"] = "very"
        self.assertIn("confidence not in enum", self._run(bad))

    def test_duplicate_coordinate_rejected(self) -> None:
        bad = _valid_hypothesis()
        bad["cells"].append({"coordinate": [1, 1], "role": "data", "confidence": "high"})
        self.assertIn("duplicate cell coordinate", self._run(bad))

    def test_merge_group_too_small_rejected(self) -> None:
        bad = _valid_hypothesis()
        bad["semantic_merges"] = [{"coordinates": [[1, 1]]}]
        self.assertIn(">=2 members", self._run(bad))

    def test_extra_key_stripped_on_success(self) -> None:
        payload = _valid_hypothesis()
        payload["cells"][0]["junk"] = "x"
        chat = _FakeChat(payload)
        result = propose_table_structure(_parsed(), config=_StubConfig(), chat=chat)
        # Extra key on a cell entry is REJECTED (additionalProperties:false), not silently
        # stripped — the format itself must close the hallucination channel.
        self.assertEqual(result.status, UNAVAILABLE)


class PromptAssemblyTests(unittest.TestCase):
    def test_prompt_carries_matrix_coordinates_and_no_free_text_request(self) -> None:
        system, user = build_proposal_prompt(_parsed(), family=None)
        # Coordinates of canonical cells appear in the user payload.
        self.assertIn("[1, 1]", user)
        self.assertIn("[2, 3]", user)
        # The protected OBIS value is carried verbatim for the model to reference.
        self.assertIn("0-0:96.1.0", user)
        # The system prompt enforces the role enum and the no-free-text rule.
        self.assertIn("title", system)
        self.assertIn("header", system)
        self.assertIn("No free-text", system)
        # Version stamps are pinned for cache fingerprinting downstream.
        self.assertIn(LLM_TABLE_UNDERSTANDING_PROMPT_VERSION, user)

    def test_family_context_rendered_as_data_when_matched(self) -> None:
        from table_family_templates import match_table_family

        family = match_table_family(["Object/attribute name", "CL", "Value"])
        self.assertIsNotNone(family)
        self.assertEqual(family.family_id, "obis_object")
        _system, user = build_proposal_prompt(_parsed(), family=family)
        self.assertIn("obis_object", user)
        # Protected-code column kinds appear as structured data, not prompt prose.
        self.assertIn("obis", user)


class FamilyMatchingTests(unittest.TestCase):
    def test_proposer_matches_family_from_header_when_none_given(self) -> None:
        chat = _FakeChat(_valid_hypothesis())
        result = propose_table_structure(_parsed(), config=_StubConfig(), chat=chat)
        self.assertEqual(result.status, PROPOSED)
        # The parsed table's header row matches the OBIS-object family indicators.
        self.assertEqual(result.family_id, "obis_object")

    def test_no_match_yields_empty_family_id(self) -> None:
        cells = {(1, 1): _cell(1, 1, "a"), (1, 2): _cell(1, 2, "b")}
        parsed = ParsedDocxTable(
            width=2,
            matrix=[["a", "b"]],
            raw_matrix=[["a", "b"]],
            cells=cells,
            merge_ranges=[],
            explicit_header_rows=[],
            nested_tables=[],
            parse_incomplete=False,
            parse_incomplete_reason={},
            raw_text="",
        )
        chat = _FakeChat({
            "schema": TABLE_STRUCTURE_HYPOTHESIS_VERSION,
            "table_structure_version": "docx-table-physical-v1",
            "header_level_count": 0,
            "cells": [],
            "semantic_merges": [],
        })
        result = propose_table_structure(parsed, config=_StubConfig(), chat=chat)
        self.assertEqual(result.status, PROPOSED)
        self.assertEqual(result.family_id, "")


class DefaultChatErrorTests(unittest.TestCase):
    def test_default_chat_wraps_llm_error_as_unavailable(self) -> None:
        # When the caller does not inject a chat, the proposer builds one from config
        # via llm_client.chat_json. An LLMError there surfaces as unavailable, never a
        # fabricated hypothesis. We exercise the wrapper directly with a stub config
        # whose chat_json raises an LLMError-shaped exception.
        from llm_table_understanding import _default_chat
        from llm_client import LLMError

        class _Config:
            def __init__(self) -> None:
                self.model = "stub-model"
                self.base_url = "http://stub"
                self.temperature = 0.0
                self.max_tokens = 64
                self.api_key_env = "RATOMIZER_LLM_API_KEY"
                self.timeout_s = 5.0
                self.max_retries = 1

        def _failing_chat_json(config, system, user, **kwargs):  # noqa: ANN001
            raise LLMError("endpoint down")

        import llm_client

        original = llm_client.chat_json
        llm_client.chat_json = _failing_chat_json  # type: ignore[assignment]
        try:
            chat = _default_chat(_Config(), None)
            with self.assertRaises(TableUnderstandingUnavailable):
                chat("sys", "usr")
        finally:
            llm_client.chat_json = original  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
