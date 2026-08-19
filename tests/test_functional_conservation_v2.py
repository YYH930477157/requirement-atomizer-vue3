"""去原子化方案 §3.1/§3.5/§3.6 的机制测试（2026-08-15）。

§3.1 obligation/evidence 守恒模型：
- 多对多合法——多义务条款出多条不被压、不被阻；跨条款引用不判重；
- 五项检查（条款覆盖/义务覆盖/无证据需求/重复需求/保留完整性）各有正反测试；
- 证据锚确定性派生（现算，不信任产物里的持久化锚）。

§3.5 失败语义：
- execution_status：显式 stub=ok、LLM 尝试全退化=failed、mixed=partial；
- 缓存重放保留失败语义（失败产物不被洗白成成功）；
- 下游 direct basis 对 failed/partial 响亮阻断。

§3.6 单源配置：get_env* 函数族从 ENV_REGISTRY 取默认值。

纪律：单测禁止真实 LLM 调用——chat 回调全部注入。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import functional_extract as fe


def _clause(sid: str, blocks: list[str], text: str) -> dict:
    return {
        "section_id": sid, "section_path": [sid], "heading": sid,
        "text": text, "block_ids": blocks,
    }


def _item(fid: str, blocks: list[str], narrative: str, quote: str = "") -> dict:
    return {
        "functional_requirement_id": fid,
        "source_block_ids": blocks,
        "source_quote": quote or narrative,
        "objective": narrative,
        "behaviors": [],
    }


class MultiObligationAcceptanceTests(unittest.TestCase):
    """§3.1 验收：多义务条款出多条不被压、不被阻（旧 exactly-once 会判 duplicate 阻塞）。"""

    def test_two_obligations_two_items_conserved(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events and shall send alarms.")]
        items = [
            _item("F1", ["B1"], "The meter shall log events"),
            _item("F2", ["B1"], "The meter shall send alarms"),
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["duplicate_assignments"], [])

    def test_single_item_covering_both_obligations_also_conserved(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events and shall send alarms.")]
        items = [_item("F1", ["B1"], "The meter shall log events and shall send alarms")]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"], report)

    def test_dropped_obligation_blocks(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events and shall send alarms.")]
        items = [_item("F1", ["B1"], "The meter shall log events")]  # 漏掉 send alarms
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertIn("obligation_coverage", report["failure_categories"])
        uncovered = report["checks"]["obligation_coverage"]["uncovered_obligations"]
        self.assertEqual(len(uncovered), 1)
        self.assertIn("send alarms", uncovered[0]["sentence"])
        with self.assertRaises(fe.FunctionalConservationError):
            fe.raise_if_unconserved(report)


class CrossClauseReferenceTests(unittest.TestCase):
    """§3.1 验收：跨条款引用合法——多消费不判重，交叉锚计覆盖。"""

    def test_cross_reference_counts_as_coverage_not_duplicate(self) -> None:
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The logger shall archive events as defined in 4.1."),
        ]
        # F2 的叙述同时覆盖 4.2 的义务和 4.1 的义务（跨条款引用）
        items = [
            _item("F1", ["B1"], "The meter shall log events"),
            _item("F2", ["B2"], "The logger shall archive events; the meter shall log events"),
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["duplicate_assignments"], [])

    def test_anchors_require_declaration_no_borrowing(self) -> None:
        """M1：锚只在声明条款上产生——叙述复述未声明条款不再产生跨条款锚。

        F2 要同时锚定 4.1/4.2，必须声明两个来源（B1+B2）；只声明 B2 时，
        即使叙述复述了 4.1 的义务也不得为其产生锚（借位已删除）。
        """
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The logger shall archive events as defined in 4.1."),
        ]
        borrowing = [
            _item("F1", ["B1"], "The meter shall log events"),
            _item("F2", ["B2"], "The logger shall archive events; the meter shall log events"),
        ]
        fe.assign_evidence_anchors(borrowing, sections)
        f2_anchors = borrowing[1]["evidence_anchors"]
        self.assertTrue(f2_anchors)
        self.assertTrue(all(a["section_id"] == "4.2" for a in f2_anchors))
        # 声明双来源 → 两条锚（M1 合法多对多）
        declaring_both = [
            _item("F3", ["B1", "B2"],
                  "The meter shall log events; the logger shall archive events"),
        ]
        fe.assign_evidence_anchors(declaring_both, sections)
        f3_sections = {a["section_id"] for a in declaring_both[0]["evidence_anchors"]}
        self.assertEqual(f3_sections, {"4.1", "4.2"})

    def test_tampered_persisted_anchors_are_recomputed(self) -> None:
        """产物里的持久化锚被篡改不能伪造覆盖——守恒总是现算。"""
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The logger shall archive events."),
        ]
        items = [
            _item("F1", ["B1"], "The meter shall log events"),
            _item("F2", ["B2"], "The logger shall archive events"),
        ]
        # 伪造 F2 覆盖 B1/B2 之外的块——现算逻辑不受影响
        items[1]["evidence_anchors"] = [
            {"block_ids": ["B1", "B2"], "kind": "obligation", "origin": "home"},
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"])


class FiveChecksTests(unittest.TestCase):
    def test_clause_coverage_positive_and_negative(self) -> None:
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The logger shall archive events."),
        ]
        ok_report = fe.conservation_report(sections, [
            _item("F1", ["B1"], "The meter shall log events"),
            _item("F2", ["B2"], "The logger shall archive events"),
        ])
        self.assertTrue(ok_report["ok"])
        bad_report = fe.conservation_report(sections, [
            _item("F1", ["B1"], "The meter shall log events"),
        ])
        self.assertFalse(bad_report["ok"])
        self.assertIn("clause_coverage", bad_report["failure_categories"])
        self.assertIn("B2", bad_report["missing_block_ids"])

    def test_evidence_presence_negative_empty_blocks(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events.")]
        report = fe.conservation_report(sections, [_item("F1", [], "The meter shall log events")])
        self.assertFalse(report["ok"])
        self.assertIn("evidence_presence", report["failure_categories"])
        self.assertEqual(
            report["checks"]["evidence_presence"]["items_without_evidence"][0]["reason"],
            "empty_source_block_ids",
        )

    def test_evidence_presence_negative_quote_mismatch(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events.")]
        blocks = [{"block_id": "B2", "text": "Completely unrelated content here."}]
        item = _item("F1", ["B1"], "The meter shall log events",
                     quote="Completely unrelated content here.")
        report = fe.conservation_report(sections, [item], blocks=blocks)
        self.assertFalse(report["ok"])
        self.assertTrue(report["evidence_mismatches"])

    def test_preservation_number_loss_blocks(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events for 30 days.")]
        report = fe.conservation_report(sections, [_item("F1", ["B1"], "The meter shall log events")])
        self.assertFalse(report["ok"])
        losses = report["checks"]["preservation"]["blocking_losses"]
        self.assertTrue(any(f["kind"] == "number" and f["token"] == "30" for f in losses))

    def test_preservation_negation_loss_blocks(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall not log events remotely.")]
        report = fe.conservation_report(sections, [_item("F1", ["B1"], "The meter shall log events remotely")])
        self.assertFalse(report["ok"])
        losses = report["checks"]["preservation"]["blocking_losses"]
        self.assertTrue(any(f["kind"] == "negation" for f in losses))

    def test_preservation_condition_loss_warns_only(self) -> None:
        sections = [_clause("4.1", ["B1"], "If the tariff changes, the meter shall log events.")]
        report = fe.conservation_report(sections, [_item("F1", ["B1"], "The meter shall log events")])
        # 条件丢失 = warning：ok 不翻 false，但 warning_count 留痕
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["warning_count"], 0)
        warnings = report["checks"]["preservation"]["warning_losses"]
        self.assertTrue(any(f["kind"] == "condition" for f in warnings))

    def test_preservation_unit_loss_blocks(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall withstand 4 kV surge.")]
        report = fe.conservation_report(sections, [_item("F1", ["B1"], "The meter shall withstand surge of 4")])
        losses = report["checks"]["preservation"]["blocking_losses"]
        self.assertTrue(any(f["kind"] == "unit" for f in losses))
        self.assertFalse(report["ok"])

    def test_preservation_kept_when_narrative_carries_all(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall not exceed 4 kV unless isolated.")]
        report = fe.conservation_report(
            sections, [_item("F1", ["B1"], "The meter shall not exceed 4 kV unless isolated")])
        self.assertTrue(report["ok"], report)

    def test_chinese_obligation_and_negation(self) -> None:
        sections = [_clause("4.1", ["B1"], "电表应记录事件，并在断电时不得丢失数据。")]
        # M1：单个义务单元必须由单条 eligible FRE 完整覆盖（any 语义，不再并集借位）
        ok = fe.conservation_report(sections, [
            _item("F1", ["B1"], "电表应记录事件，并在断电时不得丢失数据"),
        ])
        self.assertTrue(ok["ok"], ok)
        # 同一义务单元拆半分摊到两条 FRE —— M1 判为义务丢失（这是"拆散"病灶本身）
        split = fe.conservation_report(sections, [
            _item("F1", ["B1"], "电表应记录事件"), _item("F2", ["B1"], "断电时电表不得丢失数据"),
        ])
        self.assertFalse(split["ok"])
        self.assertIn("obligation_coverage", split["failure_categories"])
        dropped = fe.conservation_report(sections, [_item("F1", ["B1"], "电表应记录事件，断电时允许丢失数据")])
        self.assertFalse(dropped["ok"])


class ExecutionStatusTests(unittest.TestCase):
    """§3.5：执行结果类别的推导与缓存/下游一致性。"""

    def test_explicit_stub_is_ok(self) -> None:
        self.assertEqual(fe.execution_status("stub", "stub", requested_label="stub"), "ok")
        self.assertEqual(fe.execution_status(None, "stub", requested_label="stub"), "ok")

    def test_degraded_llm_is_failed(self) -> None:
        self.assertEqual(
            fe.execution_status("openai_compatible", "stub", requested_label="llm:test-model"),
            "failed")

    def test_injected_chat_degraded_is_failed(self) -> None:
        self.assertEqual(
            fe.execution_status("stub", "stub", requested_label="injected"), "failed")

    def test_mixed_is_partial(self) -> None:
        self.assertEqual(fe.execution_status("openai_compatible", "mixed", requested_label="llm:m"), "partial")

    def test_run_with_failing_chat_persists_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)

            def broken_chat(system: str, user: str) -> dict:
                raise RuntimeError("network down")

            result = fe.run_functional_extract(
                out, sections=[_clause("7.1", ["B1"], "The meter shall log events.")],
                route="openai_compatible", chat=broken_chat,
            )
            self.assertEqual(result["execution_status"], "failed")
            payload = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["execution_status"], "failed")

    def test_failed_run_not_cached_healthy_rerun_reexecutes(self) -> None:
        """§3.5：全失败不落缓存（瞬时故障不该被钉死）；健康重跑真实再执行。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            sections = [_clause("7.2", ["B1"], "The meter shall log events.")]

            def broken_chat(system: str, user: str) -> dict:
                raise RuntimeError("timeout")

            def healthy_chat(system: str, user: str) -> dict:
                return {"items": [{
                    "objective": "The meter shall log events",
                    "behaviors": ["log events"],
                    "source_quote": "The meter shall log events.",
                    "source_block_ids": ["B1"],
                }]}

            first = fe.run_functional_extract(out, sections=sections, chat=broken_chat)
            self.assertEqual(first["execution_status"], "failed")
            cache_rows = [
                json.loads(line)
                for line in (out / "functional_extract_cache.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()
            ] if (out / "functional_extract_cache.jsonl").exists() else []
            self.assertEqual(cache_rows, [])
            second = fe.run_functional_extract(out, sections=sections, chat=healthy_chat)
            self.assertEqual(second["execution_status"], "ok")

    def test_partial_is_cached_and_replay_keeps_partial(self) -> None:
        """§3.5：mixed（有真实内容）照常缓存，重放保留 partial 语义不洗白。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            sections = [
                _clause("7.3", ["B1"], "The meter shall log events."),
                _clause("8.9", ["B2"], "The logger shall archive events."),
            ]

            def flaky_chat(system: str, user: str) -> dict:
                if "8.9" in user:
                    raise RuntimeError("server error")
                return {"items": [{
                    "objective": "The meter shall log events",
                    "behaviors": ["log events"],
                    "source_quote": "The meter shall log events.",
                    "source_block_ids": ["B1"],
                }]}

            def healthy_chat(system: str, user: str) -> dict:
                return {"items": [{
                    "objective": "The meter shall log events",
                    "behaviors": ["log events"],
                    "source_quote": "The meter shall log events.",
                    "source_block_ids": ["B1"],
                }]}

            first = fe.run_functional_extract(
                out, sections=sections, chat=flaky_chat, strategy="clause_family")
            self.assertEqual(first["execution_status"], "partial")
            (out / "functional_requirements.json").unlink()
            second = fe.run_functional_extract(
                out, sections=sections, chat=healthy_chat, strategy="clause_family")
            # 缓存命中（route_key 同为 injected + 同策略同条款）→ 重放仍是 partial
            self.assertEqual(second["execution_status"], "partial")
            self.assertEqual(second["written"], ["functional_requirements.json"])

    def test_mixed_packages_persist_partial(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            sections = [
                _clause("7.3", ["B1"], "The meter shall log events."),
                _clause("8.9", ["B2"], "The logger shall archive events."),
            ]

            def flaky_chat(system: str, user: str) -> dict:
                if "8.9" in user:
                    raise RuntimeError("server error")
                return {"items": [{
                    "objective": "The meter shall log events",
                    "behaviors": ["log events"],
                    "source_quote": "The meter shall log events.",
                    "source_block_ids": ["B1"],
                }]}

            result = fe.run_functional_extract(
                out, sections=sections, chat=flaky_chat, strategy="clause_family")
            self.assertEqual(result["route"], "mixed")
            self.assertEqual(result["execution_status"], "partial")

    def test_direct_basis_blocks_failed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "functional_requirements.json").write_text(json.dumps({
                "producer": "functional-extract-v1",
                "route_requested": "openai_compatible",
                "route": "stub",
                "items": [{"functional_requirement_id": "F1"}],
                "conservation": {"ok": True},
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(fe.FunctionalExtractionIncompleteError):
                fe.functional_direct_basis(out)

    def test_direct_basis_blocks_partial_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "functional_requirements.json").write_text(json.dumps({
                "producer": "functional-extract-v1",
                "route_requested": "openai_compatible",
                "route": "mixed",
                "items": [{"functional_requirement_id": "F1"}],
                "conservation": {"ok": True},
            }, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(fe.FunctionalExtractionIncompleteError):
                fe.functional_direct_basis(out)

    def test_legacy_cache_row_derives_status(self) -> None:
        """无 execution_status 字段的旧缓存行按路由字段推导，不默认成功。"""
        self.assertEqual(fe._payload_execution_status(
            {"route_requested": "openai_compatible", "route": "stub"}), "failed")
        self.assertEqual(fe._payload_execution_status(
            {"route_requested": "stub", "route": "stub"}), "ok")


class ManifestStatusMappingTests(unittest.TestCase):
    """§3.5：manifest 记账与产物同一失败语义。"""

    def test_stage_completion_status_maps_execution_status(self) -> None:
        import desktop_tasks
        self.assertEqual(desktop_tasks._stage_completion_status(
            "functional-extract", {"execution_status": "ok"}), "ok")
        self.assertEqual(desktop_tasks._stage_completion_status(
            "functional-extract", {"execution_status": "partial"}), "partial")
        self.assertEqual(desktop_tasks._stage_completion_status(
            "functional-extract", {"execution_status": "failed"}), "failed")
        self.assertEqual(desktop_tasks._stage_completion_status(
            "functional-extract", {}), "ok")


class ConfigSingleSourceTests(unittest.TestCase):
    """§3.6：统一读取函数从 ENV_REGISTRY 取单源默认值。"""

    def test_get_env_uses_registry_default(self) -> None:
        import config
        env = {k: v for k, v in os.environ.items()
               if k != "RATOMIZER_FUNCTIONAL_EXTRACT"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(config.get_env("RATOMIZER_FUNCTIONAL_EXTRACT"), "1")
            self.assertTrue(config.get_env_bool("RATOMIZER_FUNCTIONAL_EXTRACT"))
            self.assertFalse(config.get_env_bool(
                "RATOMIZER_FUNCTIONAL_EXTRACT", override="0"))
            self.assertTrue(config.get_env_bool(
                "RATOMIZER_FUNCTIONAL_EXTRACT", override="1"))
        with unittest.mock.patch.dict(os.environ, {"RATOMIZER_FUNCTIONAL_EXTRACT": "true"}):
            self.assertTrue(config.get_env_bool("RATOMIZER_FUNCTIONAL_EXTRACT"))
            self.assertTrue(fe.functional_extract_enabled())

    def test_get_env_int_invalid_falls_back_to_default(self) -> None:
        import config
        self.assertEqual(
            config.get_env_int("RATOMIZER_FUNCTIONAL_EXTRACT_NEGATIVE_K", override="abc"), 2)
        self.assertEqual(
            config.get_env_int("RATOMIZER_FUNCTIONAL_EXTRACT_NEGATIVE_K", override="5"), 5)

    def test_unregistered_name_raises(self) -> None:
        import config
        with self.assertRaises(KeyError):
            config.get_env("RATOMIZER_NOT_A_REAL_VAR")

    def test_negative_k_runtime_refresh(self) -> None:
        """§3.6：负例条数运行时求值——进程内改 env 即生效（修掉 import 时常量不刷新）。"""
        with unittest.mock.patch.dict(os.environ, {"RATOMIZER_FUNCTIONAL_EXTRACT_NEGATIVE_K": "7"}):
            self.assertEqual(fe.functional_extract_negative_k(), 7)



class M1LocalBindingTests(unittest.TestCase):
    """M1（§3.5）测试矩阵：局部绑定后的正反用例。"""

    def _sections(self) -> list[dict]:
        return [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The logger shall archive events."),
        ]

    def test_matrix_1_borrowed_narrative_and_placeholder_fail(self) -> None:
        """F1 声明 B1 却复述 B1/B2，F2 占位声明 B2 —— 必须失败。"""
        sections = self._sections()
        items = [
            _item("F1", ["B1"],
                  "The meter shall log events. The logger shall archive events."),
            _item("F2", ["B2"], "实现归档相关功能"),
        ]
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertIn("obligation_coverage", report["failure_categories"])
        # B2 的义务只能由 eligible（声明 B2）的 F2 覆盖——占位叙述不够
        uncovered = report["checks"]["obligation_coverage"]["uncovered_obligations"]
        self.assertTrue(any(u["section_id"] == "4.2" for u in uncovered))

    def test_matrix_3_one_fre_declares_and_covers_both(self) -> None:
        sections = self._sections()
        items = [_item("F1", ["B1", "B2"],
                       "The meter shall log events. The logger shall archive events.")]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"], report)

    def test_matrix_4_two_fres_two_obligations_same_clause(self) -> None:
        sections = [_clause("4.1", ["B1"],
                            "The meter shall log events and shall send alarms.")]
        items = [
            _item("F1", ["B1"], "The meter shall log events"),
            _item("F2", ["B1"], "The meter shall send alarms"),
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"], report)

    def test_matrix_5_multi_fre_same_obligation_not_duplicate(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events.")]
        items = [
            _item("F1", ["B1"], "The meter shall log events"),
            _item("F2", ["B1"], "The meter shall record event logs for audit",
                  quote="The meter shall log events."),
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["duplicate_assignments"], [])

    def test_matrix_6_cross_script_only_covers_declared_section(self) -> None:
        """跨语种 fallback 只能覆盖声明条款——不得借未声明条款的叙述。"""
        sections = self._sections()
        items = [
            # F1 只声明 B1（ZH 叙述，quote=B1 条款原文）——不得顺带覆盖 B2
            _item("F1", ["B1"], "记录事件与归档", quote="The meter shall log events."),
        ]
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        uncovered = report["checks"]["obligation_coverage"]["uncovered_obligations"]
        self.assertTrue(any(u["section_id"] == "4.2" for u in uncovered))
        # 跨语种覆盖成立 + 人工复核留痕
        cross_reviews = report["checks"]["obligation_coverage"]["cross_script_review"]
        self.assertEqual(len(cross_reviews), 1)
        self.assertEqual(cross_reviews[0]["section_id"], "4.1")
        self.assertEqual(cross_reviews[0]["functional_requirement_id"], "F1")
        # 复审 P1-2 二轮：复核记录绑定源义务文本哈希（身份随文本变化）
        self.assertTrue(cross_reviews[0]["source_text_hash"])

    def test_source_quote_edge_is_anchor_not_coverage(self) -> None:
        """source_quote 边只作证据锚——引句回显不能充当义务覆盖。"""
        sections = [_clause("4.1", ["B1"], "The meter shall log events.")]
        items = [{
            "functional_requirement_id": "F1",
            "source_block_ids": ["B1"],
            "source_quote": "The meter shall log events.",
            "objective": "Implement logging functionality",  # 同语种占位叙述
            "behaviors": [],
        }]
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertIn("obligation_coverage", report["failure_categories"])
        # 但锚存在（绑定检查不触发——有 source_quote 边）
        self.assertEqual(report["checks"]["evidence_presence"]["binding_mismatches"], [])

class ReviewHardeningTests(unittest.TestCase):
    """复审 P1（2026-08-15）：错绑与无效证据不得通过守恒门。"""

    def test_swapped_narratives_block(self) -> None:
        """B1/B2 叙述互换（错绑）→ evidence_presence 阻塞。"""
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The logger shall archive events."),
        ]
        items = [
            _item("F1", ["B1"], "The logger shall archive events",
                  quote="The meter shall log events."),
            _item("F2", ["B2"], "The meter shall log events",
                  quote="The logger shall archive events."),
        ]
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertIn("evidence_presence", report["failure_categories"])
        binding = report["checks"]["evidence_presence"]["binding_mismatches"]
        self.assertEqual(len(binding), 2)

    def test_quote_zero_hit_blocks(self) -> None:
        """source_quote 不命中任何 block → 无效证据（旧逻辑零命中放行）。"""
        sections = [_clause("4.1", ["B1"], "The meter shall log events.")]
        blocks = [{"block_id": "B1", "text": "The meter shall log events."}]
        items = [_item("F1", ["B1"], "The meter shall log events",
                       quote="完全无关的引句 whatsoever zzz.")]
        report = fe.conservation_report(sections, items, blocks=blocks)
        self.assertFalse(report["ok"])
        mismatches = report["evidence_mismatches"]
        self.assertEqual(mismatches[0]["reason"], "quote_matches_no_block")

    def test_correct_binding_still_passes(self) -> None:
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The logger shall archive events."),
        ]
        items = [
            _item("F1", ["B1"], "The meter shall log events"),
            _item("F2", ["B2"], "The logger shall archive events"),
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"], report)


if __name__ == "__main__":
    unittest.main()
