"""API server 安全回归。

锁定 token 校验用常量时间比较（防时序侧信道），并保留：无配置 token 时放行、
token 不匹配时拒绝。可独立运行，无网络/LLM 依赖。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import api_server
import ai_review_actions


class TokenIsValidTests(unittest.TestCase):
    def test_no_expected_token_allows_through(self) -> None:
        # 未配置 token（本地无鉴权场景）→ 任意请求放行
        self.assertTrue(api_server.token_is_valid("", {api_server.TOKEN_HEADER: "x"}, {}))
        self.assertTrue(api_server.token_is_valid("", {}, {}))

    def test_matching_header_token_accepted(self) -> None:
        token = "s3cret-token-abc"
        headers = {api_server.TOKEN_HEADER: token}
        self.assertTrue(api_server.token_is_valid(token, headers, {}))

    def test_mismatching_header_token_rejected(self) -> None:
        token = "s3cret-token-abc"
        headers = {api_server.TOKEN_HEADER: "wrong"}
        self.assertFalse(api_server.token_is_valid(token, headers, {}))

    def test_missing_header_token_rejected(self) -> None:
        token = "s3cret-token-abc"
        self.assertFalse(api_server.token_is_valid(token, {}, {}))

    def test_comparison_uses_constant_time_function(self) -> None:
        """S1 回归：token 须走 hmac.compare_digest，而非字符串 == 短路。

        解析源码确认比较路径常量时间：compare_digest 的核心约束是『两串等长才比较内容、
        否则恒为 False 但耗时与内容无关』；等长内容相同须接受、不同须拒绝。
        """
        import inspect
        src = inspect.getsource(api_server.token_is_valid)
        self.assertIn("compare_digest", src)  # 实现里含常量时间比较
        self.assertNotIn("== expected_token", src)  # 不再裸用 == 比较整串

    def test_equal_length_but_different_token_rejected(self) -> None:
        # compare_digest 对等长但内容不同的串恒 False（也是 == 短路会误判的场景）
        token = "aaaaaaaaaaaaaaaa"
        headers = {api_server.TOKEN_HEADER: "aaaaaaaaaaaaaaab"}  # 同长度末字节不同
        self.assertFalse(api_server.token_is_valid(token, headers, {}))


class AiReviewActionsTests(unittest.TestCase):
    def _req(self) -> dict:
        return {"source_section": "3.1.7", "source_quote": "meter shall measure",
                "title": "计量器具定义", "module": "计量"}

    def test_ai_req_id_stable_and_content_based(self) -> None:
        a = ai_review_actions.ai_req_id(self._req())
        b = ai_review_actions.ai_req_id(dict(self._req()))  # 同内容 → 同 ID
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("AIR-"))
        other = ai_review_actions.ai_req_id({**self._req(), "source_quote": "different"})
        self.assertNotEqual(a, other)  # 内容变 → ID 变

    def test_apply_and_read_latest_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rid = ai_review_actions.ai_req_id(self._req())
            ai_review_actions.apply_ai_review_action(out, rid, "needs_discussion", reason="待议")
            ai_review_actions.apply_ai_review_action(out, rid, "accepted",
                                                     module_override="计量精度", reason="改归精度")
            states = ai_review_actions.read_ai_review_states(out)
            self.assertEqual(states[rid]["status"], "accepted")            # 最近覆盖
            self.assertEqual(states[rid]["module_override"], "计量精度")

    def test_invalid_status_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ai_review_actions.apply_ai_review_action(Path(tmp), "AIR-x", "bogus")

    def test_endpoint_rejects_ambiguous_empty_module_override(self) -> None:
        handler = object.__new__(api_server.RequirementAPIHandler)
        handler.read_json_body = lambda: {
            "ai_req_id": "AIR-1", "status": "accepted", "module_override": "",
        }
        responses: list[tuple[int, dict]] = []
        handler.send_json = lambda body, status=200: responses.append((status, body))

        handler.handle_ai_review_action()

        self.assertEqual(responses[0][0], 400)
        self.assertIn("must not be empty", responses[0][1]["error"])

    def test_endpoint_uses_explicit_clear_module_override_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handler = object.__new__(api_server.RequirementAPIHandler)
            handler.output_dir = Path(tmp)
            handler.read_json_body = lambda: {
                "ai_req_id": "AIR-1", "status": "accepted",
                "source_fingerprint": "source-current",
                "review_subject_fingerprint": "subject-current",
                "clear_module_override": True,
            }
            responses: list[tuple[int, dict]] = []
            handler.send_json = lambda body, status=200: responses.append((status, body))
            current = {
                "ai_req_id": "AIR-1", "source_fingerprint": "source-current",
                "review_subject_fingerprint": "subject-current",
                "review_state": {"module_override": "计量精度"},
            }
            state = {"ai_req_id": "AIR-1", "status": "accepted", "module_override": None}
            with patch("api_server.find_current_ai_requirement", return_value=current), patch(
                "api_server.apply_ai_review_action", return_value=state,
            ) as apply:
                handler.handle_ai_review_action()

        self.assertEqual(responses, [(200, state)])
        self.assertIsNone(apply.call_args.kwargs["module_override"])


class AiRequirementsEndpointTests(unittest.TestCase):
    def _seed(self, out: Path) -> None:
        (out / "blocks.jsonl").write_text(
            json.dumps({"block_id": "BLK-2", "order": 2, "text": "B", "section_path": ["4"],
                        "page_number": 1, "type": "paragraph", "kb_matches": [1, 2, 3]}) + "\n" +
            json.dumps({"block_id": "BLK-1", "order": 1, "text": "A", "section_path": ["3"],
                        "page_number": 1, "type": "heading", "kb_matches": []}) + "\n",
            encoding="utf-8")
        doc = {"requirements": [
            {"id": "REQ-001", "title": "T1", "description": "d1", "module": "计量",
             "source_section": "4", "source_quote": "q1", "source_block_ids": ["BLK-2"],
             "acceptance_criteria": ["c1"], "labels": ["计量"]},
        ]}
        (out / "merged_spec_requirements.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_document_blocks_sorted_and_trimmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            result = api_server.build_document_blocks(out)
            self.assertEqual(result["count"], 2)
            self.assertEqual([b["block_id"] for b in result["blocks"]], ["BLK-1", "BLK-2"])  # 按 order
            self.assertNotIn("kb_matches", result["blocks"][0])  # 重负载字段被裁掉

    def test_document_blocks_normalize_embedded_pdf_bullet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            blocks_path = out / "blocks.jsonl"
            rows = [json.loads(line) for line in blocks_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["text"] = "\uf8e7 closed locations"
            blocks_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            result = api_server.build_document_blocks(out)

            by_id = {block["block_id"]: block for block in result["blocks"]}
            self.assertEqual(by_id["BLK-2"]["text"], "- closed locations")

    def test_document_blocks_mark_failed_extraction_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            (out / "ai_extract_quality.json").write_text(json.dumps({
                "failed_sections": 1,
                "failed_section_ids": ["4"],
                "failed_section_block_ids": ["BLK-2"],
            }), encoding="utf-8")

            result = api_server.build_document_blocks(out)

            by_id = {block["block_id"]: block for block in result["blocks"]}
            self.assertFalse(by_id["BLK-1"]["extraction_failed"])
            self.assertTrue(by_id["BLK-2"]["extraction_failed"])
            self.assertEqual(result["failed_section_ids"], ["4"])

    def test_document_blocks_reject_structurally_invalid_quality_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            (out / "ai_extract_quality.json").write_text("[]", encoding="utf-8")

            with self.assertRaises(ValueError):
                api_server.build_document_blocks(out)

    def test_document_endpoint_wraps_structural_json_error_as_retryable_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            (out / "ai_extract_quality.json").write_text("[]", encoding="utf-8")
            handler = object.__new__(api_server.RequirementAPIHandler)
            handler.path = "/document"
            handler.headers = {}
            handler.allowed_origins = set()
            handler.local_token = ""
            handler.output_dir = out
            responses: list[tuple[int, dict]] = []
            handler.send_json = lambda body, status=200: responses.append((status, body))

            handler.do_GET()

        self.assertEqual(responses[0][0], 503)
        self.assertTrue(responses[0][1]["retryable"])

    def test_document_payload_includes_cross_document_custom_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            bank_path = out / "bank.json"
            bank_path.write_text(json.dumps({
                "version": 1,
                "accepted": {},
                "rejected": {},
                "modules": {"通信安全": {"count": 2, "requirement_ids": ["A", "B"]}},
            }, ensure_ascii=False), encoding="utf-8")
            with patch.dict("os.environ", {"RATOMIZER_ADJUDICATION_BANK": str(bank_path)}):
                result = api_server.build_document_blocks(out)

        self.assertIn("通信安全", result["module_vocabulary"])

    def test_anchor_block_id_precise_to_quote_paragraph(self) -> None:
        text_by_block = {
            "BLK-1": "Some intro paragraph without the requirement.",
            "BLK-2": "The meter shall measure volume accurately.",
            "BLK-3": "Other unrelated text.",
        }
        # 精确落到引用句所在的那一小段
        req = {"source_quote": "the meter shall measure volume",
               "source_block_ids": ["BLK-1", "BLK-2", "BLK-3"]}
        self.assertEqual(api_server.anchor_block_id(req, text_by_block), "BLK-2")
        # 引用跨到下一块（尾部超出本段）→ 前缀兜底仍落本段
        req2 = {"source_quote": "The meter shall measure volume accurately and store 12 months",
                "source_block_ids": ["BLK-1", "BLK-2"]}
        self.assertEqual(api_server.anchor_block_id(req2, text_by_block), "BLK-2")
        # 无匹配 → 回退 source_block_ids 首块
        req3 = {"source_quote": "totally nonexistent", "source_block_ids": ["BLK-3", "BLK-1"]}
        self.assertEqual(api_server.anchor_block_id(req3, text_by_block), "BLK-3")
        # 无 quote/无 span → 空
        self.assertEqual(api_server.anchor_block_id({}, text_by_block), "")

    def test_quote_matched_block_ids_returns_full_quote_span(self) -> None:
        """证据区应覆盖原句实际跨越的全部块——多段引句只亮首块会丢后半段（test5 实证）。"""
        text_by_block = {
            "BLK-1": "The terminal box must be supplied with crosshead screws.",
            "BLK-2": "Condition upon delivery - screws must be firmly tightened.",
            "BLK-3": "Unrelated packaging text.",
        }
        req = {
            "source_quote": (
                "The terminal box must be supplied with crosshead screws.\n"
                "Condition upon delivery - screws must be firmly tightened."
            ),
            "source_block_ids": ["BLK-1", "BLK-2", "BLK-3"],
        }
        self.assertEqual(
            api_server.quote_matched_block_ids(req, text_by_block), ["BLK-1", "BLK-2"]
        )
        # 无匹配 → 空（调用方如实回退锚点单块）
        req_none = {"source_quote": "totally nonexistent", "source_block_ids": ["BLK-3"]}
        self.assertEqual(api_server.quote_matched_block_ids(req_none, text_by_block), [])

    def test_anchor_block_id_ignores_pdf_word_internal_spaces(self) -> None:
        text_by_block = {
            "BLK-1": "Unrelated introductory paragraph.",
            "BLK-2": (
                "Electricity meters must beable to communicate bidirectionally "
                "with the data a nd communication center."
            ),
        }
        req = {
            "source_quote": (
                "Electricity meters must be able to communicate bidirectionally "
                "with the data and communication center."
            ),
            "source_block_ids": ["BLK-1", "BLK-2"],
        }

        self.assertEqual(api_server.anchor_block_id(req, text_by_block), "BLK-2")

    def test_echo_block_ids_for_duplicated_text(self) -> None:
        """回声锚点(0715 电表招标实证):同一段产品描述在 Scope 与 3.1 各出现一次,
        条目锚在首次出现,第二次出现在批注视图显示"未覆盖"——用户误判整段没解析出。
        碎词拆点不同("G SM" vs "GSM"),匹配必须用全剥空白底座。"""
        long_desc = ("Static three-phase alternating current meter with GSM modem 4G/LTE "
                     "for indirect measurement of active and reactive consumption")
        blocks = [
            {"block_id": "BLK-1", "text": "1 Scope of validity"},
            {"block_id": "BLK-2",
             "text": "Static three-phase alternating current meter with G SM modem 4G/LTE "
                     "for i ndirect measurement of active a nd reactive consumption"},
            {"block_id": "BLK-3", "text": "3.1 Electrical requirements"},
            {"block_id": "BLK-4",   # 第二次出现:碎词拆点不同
             "text": "Static three-phase a lternating current meter with GSM modem 4G/LTE "
                     "for indirect measurement of a ctive and reactive consumption"},
            {"block_id": "BLK-5", "text": "Voltage 110000/100 V", "noise": False},
            {"block_id": "BLK-6", "text": long_desc, "noise": True},   # 噪声块不回声
        ]
        req = {"source_quote": long_desc,
               "source_block_ids": ["BLK-2"], "anchor_block_id": "BLK-2"}
        echoes = api_server.compute_echo_block_ids(req, blocks)
        self.assertEqual(echoes, ["BLK-4"])   # 命中重复段;跳过锚点自身/噪声块/无关块

    def test_echo_near_duplicate_with_wording_drift(self) -> None:
        """真实形态(0715 电表招标):原文两次出现本身有措辞微差("measurement of"↔
        "measuring"),LLM 引句尾部又意译——引句互含路失效,靠锚点原文近重复路
        (J≥0.8+数字守卫)兜住。"""
        occ1 = ("Static three-phase alternating current meter with GSM modem 4G/LTE for "
                "indirect measurement of load profiles Q1, Q2, Q3, Q4, S and measurement "
                "of quality profiles.")
        occ2 = ("Static three-phase a lternating current meter with GSM modem 4G/LTE for "
                "i ndirect measurement of load profiles Q1, Q2, Q3, Q4, S a nd measuring "
                "quality profiles")
        blocks = [{"block_id": "BLK-1", "text": occ1},
                  {"block_id": "BLK-2", "text": occ2},
                  {"block_id": "BLK-3", "text": "Voltage transfer 110000/100 V and current 100/1 A."}]
        req = {"source_quote": occ1.replace("measurement of quality", "measurement of the quality"),
               "source_block_ids": ["BLK-1"], "anchor_block_id": "BLK-1"}   # 引句非逐字
        self.assertEqual(api_server.compute_echo_block_ids(req, blocks), ["BLK-2"])

    def test_echo_number_guard_blocks_template_rows(self) -> None:
        # 同版式不同数值的模板句:数字多重集守卫拦截(不回声)
        a = "The register shall record values every 15 minutes with a capacity of 60 days."
        b = "The register shall record values every 30 minutes with a capacity of 90 days."
        blocks = [{"block_id": "BLK-1", "text": a}, {"block_id": "BLK-2", "text": b}]
        req = {"source_quote": a, "source_block_ids": ["BLK-1"], "anchor_block_id": "BLK-1"}
        self.assertEqual(api_server.compute_echo_block_ids(req, blocks), [])

    def test_echo_short_quote_never_matches(self) -> None:
        blocks = [{"block_id": "BLK-1", "text": "The meter shall work."},
                  {"block_id": "BLK-2", "text": "The meter shall work."}]
        req = {"source_quote": "The meter shall work.",   # 剥空白后 <30 字
               "source_block_ids": ["BLK-1"], "anchor_block_id": "BLK-1"}
        self.assertEqual(api_server.compute_echo_block_ids(req, blocks), [])

    def test_build_ai_requirements_carries_echo_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)
            self.assertIn("echo_block_ids", rows[0])      # 字段恒在(空列表也在,契约稳定)

    def test_view_prefers_raw_ai_requirements_over_merged(self) -> None:
        """merged 会剔除 rejected（裁决回流交付物），批注视图须读原始文件——被拒条目仍可见、可反悔。"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)  # merged 里 1 条
            raw = [
                {"title": "T1", "description": "d1", "module": "计量", "source_section": "4",
                 "source_quote": "q1", "source_block_ids": ["BLK-2"], "labels": ["计量"]},
                {"title": "T2", "description": "d2", "module": "显示", "source_section": "5",
                 "source_quote": "q2", "source_block_ids": ["BLK-1"], "labels": ["显示"]},
            ]
            with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
                for r in raw:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            rows = api_server.build_ai_requirements(out)
            self.assertEqual(len(rows), 2)  # 读 raw（2 条），而非 merged（1 条）

    def test_ai_requirements_carry_id_anchor_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)
            self.assertEqual(len(rows), 1)
            rid = rows[0]["ai_req_id"]
            self.assertTrue(rid.startswith("AIR-"))
            self.assertEqual(rows[0]["source_block_ids"], ["BLK-2"])      # 锚点保留
            self.assertEqual(rows[0]["module_effective"], "计量")
            self.assertEqual(rows[0]["status"], "draft")                  # 未裁决
            # 裁决（改模块）后再读，module_effective 走 override
            ai_review_actions.apply_ai_review_action(out, rid, "accepted", module_override="计量精度")
            rows2 = api_server.build_ai_requirements(out)
            self.assertEqual(rows2[0]["status"], "accepted")
            self.assertEqual(rows2[0]["module_effective"], "计量精度")

    def test_ai_requirements_use_ownership_override_as_effective_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)
            rid = rows[0]["ai_req_id"]
            with (out / "ai_review_states.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ai_req_id": rid,
                    "status": "accepted",
                    "module_override": None,
                    "ownership_override": "hardware",
                    "reason": "",
                    "actor": "tester",
                }, ensure_ascii=False) + "\n")

            rows2 = api_server.build_ai_requirements(out)

            self.assertEqual(rows2[0]["ownership_effective"], "hardware")

    def test_raw_ai_requirements_preserve_explicit_ai_req_id_for_review_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ai_req_id": "AI-1",
                    "title": "Clock",
                    "description": "The meter shall support Clock object daylight saving time.",
                    "source_section": "4",
                    "source_quote": "support Clock object daylight saving time",
                    "source_block_ids": ["BLK-2"],
                }, ensure_ascii=False) + "\n")
            with (out / "ai_review_states.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ai_req_id": "AI-1",
                    "status": "accepted",
                    "ownership_override": "hardware",
                }, ensure_ascii=False) + "\n")

            rows = api_server.build_ai_requirements(out)

            self.assertEqual(rows[0]["ai_req_id"], "AI-1")
            self.assertEqual(rows[0]["status"], "accepted")
            self.assertEqual(rows[0]["ownership_effective"], "hardware")


class ClarificationBatchEndpointTests(unittest.TestCase):
    def test_internal_checks_endpoint_wraps_structural_json_error_as_retryable_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "consistency_report.json").write_text("[]", encoding="utf-8")
            handler = object.__new__(api_server.RequirementAPIHandler)
            handler.path = "/clarification-internal-checks"
            handler.headers = {}
            handler.allowed_origins = set()
            handler.local_token = ""
            handler.output_dir = out
            responses: list[tuple[int, dict]] = []
            handler.send_json = lambda body, status=200: responses.append((status, body))

            handler.do_GET()

        self.assertEqual(responses[0][0], 503)
        self.assertTrue(responses[0][1]["retryable"])

    def test_batch_endpoint_returns_fingerprint_validation_summary(self) -> None:
        handler = object.__new__(api_server.RequirementAPIHandler)
        handler.output_dir = Path(".")
        handler.read_json_body = lambda: {
            "checks": [{"clarification_id": "CLR-1", "evidence_fingerprint": "FP-1"}],
            "action": "verified_ok",
            "actor": "reviewer",
        }
        responses: list[tuple[int, dict]] = []
        handler.send_json = lambda body, status=200: responses.append((status, body))
        expected = {
            "requested": 1, "applied": 1, "stale": [], "missing": [],
            "ineligible": [], "duplicates": [], "by_signal": {"suspicion:引用": 1},
            "by_module": {"计量": 1}, "readiness": None, "written": [],
        }
        with patch("clarification_report.batch_apply_internal_checks", return_value=expected) as apply:
            handler.handle_clarification_check_batch()

        self.assertEqual(responses, [(200, expected)])
        apply.assert_called_once()

    def test_batch_endpoint_reports_extraction_conflict_as_retryable_409(self) -> None:
        from omission_actions import OmissionConflictError

        handler = object.__new__(api_server.RequirementAPIHandler)
        handler.output_dir = Path(".")
        handler.read_json_body = lambda: {
            "checks": [{"clarification_id": "CLR-1", "evidence_fingerprint": "FP-1"}],
        }
        responses: list[tuple[int, dict]] = []
        handler.send_json = lambda body, status=200: responses.append((status, body))

        with patch(
            "clarification_report.batch_apply_internal_checks",
            side_effect=OmissionConflictError("extraction is running"),
        ):
            handler.handle_clarification_check_batch()

        self.assertEqual(responses[0][0], 409)
        self.assertTrue(responses[0][1]["retryable"])
        self.assertTrue(responses[0][1]["needs_reconfirmation"])


class ConsistencyFlagsTests(unittest.TestCase):
    """一致性闭环：P1b critic 的报表标记挂到批注视图行上（此前只写不读）。"""

    def _seed(self, out: Path) -> None:
        (out / "blocks.jsonl").write_text("", encoding="utf-8")
        rows = [
            {"ai_req_id": "AI-1", "title": "能量寄存器", "description": "记录 1-0:1.8.0.255",
             "source_quote": "total active energy import shall be recorded", "module": "计量",
             "source_section": "4", "source_block_ids": ["B1"], "labels": ["计量"]},
            {"ai_req_id": "AI-2", "title": "重复章", "description": "restated elsewhere",
             "source_quote": "total active energy import shall be recorded", "module": "计量",
             "source_section": "7", "source_block_ids": ["B2"], "labels": ["计量"]},
            {"ai_req_id": "AI-3", "title": "无关", "description": "unrelated",
             "source_quote": "something completely different here", "module": "显示",
             "source_section": "5", "source_block_ids": ["B3"], "labels": ["显示"]},
        ]
        with (out / "ai_requirements.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_rows_carry_duplicate_and_obis_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            report = {
                "summary": {},
                "duplicate_groups": [{"source_quote": "total active energy import shall be recorded",
                                       "members": ["REQ-001", "REQ-050"], "count": 2}],
                "obis_coreference": [{"obis": "1-0:1.8.0.255", "values_differ": True, "count": 2},
                                      {"obis": "0-0:96.1.0.255", "values_differ": False, "count": 3}],
            }
            (out / "consistency_report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            rows = {r["ai_req_id"]: r for r in api_server.build_ai_requirements(out)}

        self.assertIn("跨章重复×2", rows["AI-1"].get("consistency_flags", []))
        self.assertIn("跨章重复×2", rows["AI-2"].get("consistency_flags", []))
        # AI-1 描述里含数值待核的 OBIS → 也带 OBIS 标记；values_differ=False 的码不标
        self.assertTrue(any("1-0:1.8.0.255" in f for f in rows["AI-1"]["consistency_flags"]))
        self.assertFalse(any("96.1.0" in f for f in rows["AI-1"]["consistency_flags"]))
        self.assertNotIn("consistency_flags", rows["AI-3"])   # 无关行零标记

    def test_missing_or_broken_report_yields_no_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._seed(out)
            rows = api_server.build_ai_requirements(out)          # 无报表
            self.assertTrue(all("consistency_flags" not in r for r in rows))

            (out / "consistency_report.json").write_text("{broken", encoding="utf-8")
            rows = api_server.build_ai_requirements(out)          # 损坏报表 → 不抛、零标记
            self.assertTrue(all("consistency_flags" not in r for r in rows))

            (out / "consistency_report.json").write_text("[]", encoding="utf-8")
            rows = api_server.build_ai_requirements(out)          # 结构错误同样不可裸崩
            self.assertTrue(all("consistency_flags" not in r for r in rows))


class FunctionalMembershipProjectionTests(unittest.TestCase):
    def test_ai_requirements_include_synthesized_function_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "ai_requirements.jsonl").write_text(json.dumps({
                "ai_req_id": "AI-1", "title": "采集事件", "description": "采集重要事件。",
                "source_quote": "Collect significant events.", "source_block_ids": ["B-1"], "module": "事件",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            (out / "blocks.jsonl").write_text(json.dumps({
                "block_id": "B-1", "order": 1, "text": "Collect significant events."
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            (out / "functional_requirements.json").write_text(json.dumps({"items": [{
                "functional_requirement_id": "FREQ-1", "title": "重要事件管理",
                "objective": "实现重要事件管理。", "behaviors": ["采集重要事件。"],
                "source_ai_requirement_ids": ["AI-1"], "merge_method": "event_subject",
                "merge_confidence": 0.9, "conflict_flags": [],
            }]}, ensure_ascii=False), encoding="utf-8")

            row = api_server.build_ai_requirements(out)[0]

        self.assertEqual(row["functional_requirement_id"], "FREQ-1")
        self.assertEqual(row["functional_title"], "重要事件管理")
        self.assertEqual(row["functional_objective"], "实现重要事件管理。")
        self.assertEqual(row["functional_behaviors"], ["采集重要事件。"])

if __name__ == "__main__":
    unittest.main()

