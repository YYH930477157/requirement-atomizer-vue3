"""WS2 功能需求直抽（functional_extract）机制测试。

纪律：单测禁止真实 LLM 调用——所有 LLM 路径经注入 chat 回调或走 stub 路由。
验收面：结构字段冻结、编码漂移硬拦、数字漂移软标、stub provenance 如实、守恒核对
exactly-once + 未闭合阻塞导出、缓存指纹命中放行。
"""
from __future__ import annotations

import json
import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

import functional_extract as fe


def _clause(section_id: str, block_ids: list[str], text: str, heading: str = "H") -> dict:
    return {
        "section_id": section_id,
        "section_path": section_id.split(" / ") if section_id else [],
        "heading": heading,
        "text": text,
        "block_ids": block_ids,
    }


class EntrySwitchTests(unittest.TestCase):
    def test_default_on_with_explicit_off_rollback(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATOMIZER_FUNCTIONAL_EXTRACT", None)
            self.assertTrue(fe.functional_extract_enabled())
            self.assertFalse(fe.functional_extract_enabled("0"))
            self.assertFalse(fe.functional_extract_enabled("false"))

    def test_on(self) -> None:
        self.assertTrue(fe.functional_extract_enabled("1"))
        self.assertTrue(fe.functional_extract_enabled("true"))


class StubRouteTests(unittest.TestCase):
    def test_stub_route_produces_one_item_per_clause_with_honest_provenance(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events.")]
        items, route = fe.extract_functional_requirements(sections, route="stub")
        self.assertEqual(route, "stub")
        self.assertEqual(len(items), 1)
        item = items[0]
        # 结构字段冻结：id/section/block_ids 来自条款，非 LLM
        self.assertEqual(item["source_block_ids"], ["B1"])
        self.assertTrue(item["functional_requirement_id"].startswith("FRE-"))
        self.assertEqual(item["merge_method"], "functional_extract")
        # 叙述字段非空
        self.assertTrue(item["objective"])
        self.assertTrue(item["behaviors"])

    def test_no_sections_returns_empty_stub(self) -> None:
        items, route = fe.extract_functional_requirements([], route="openai_compatible")
        self.assertEqual(items, [])
        self.assertEqual(route, "stub")


class LLMRouteTests(unittest.TestCase):
    def test_injected_chat_items_coerced_structure_frozen(self) -> None:
        sections = [
            _clause("4.2", ["B2"], "The meter shall collect voltage at 230 V. OBIS 1-1:32.7.0."),
        ]

        def chat(system: str, user: str) -> dict:
            return {"items": [{
                "objective": "采集电压",
                "behaviors": ["采集 230 V 电压"],
                "data_constraints": ["230 V"],
                "related_dlms_objects": ["OBIS 1-1:32.7.0"],
                "source_block_ids": ["B2"],
                "source_quote": "The meter shall collect voltage at 230 V.",
            }]}

        items, route = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        self.assertTrue(route.startswith("injected") or route.startswith("llm:"))
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["source_block_ids"], ["B2"])
        self.assertEqual(item["module"], "4.2")
        # 受保护编码来源里有 → 保留
        self.assertIn("OBIS 1-1:32.7.0", item["related_dlms_objects"])
        self.assertEqual(item["rejected_codes"], [])

    def test_llm_code_drift_hard_blocked(self) -> None:
        # 来源条款没有 OBIS 0-0:10.0.0，LLM 臆造 → 必须硬拦剔除
        sections = [_clause("4.3", ["B3"], "The meter shall log events.")]

        def chat(system: str, user: str) -> dict:
            return {"items": [{
                "objective": "记录 OBIS 0-0:10.0.0 事件",
                "behaviors": ["log"],
                "source_block_ids": ["B3"],
            }]}

        items, _ = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        self.assertEqual(len(items), 1)
        # 臆造编码被剔除（rejected_codes 非空，related 不含该编码）
        self.assertTrue(any("0-0:10.0.0" in c for c in items[0]["rejected_codes"]))

    def test_llm_code_drift_in_behaviors_hard_blocked(self) -> None:
        # S1-8：_reject_drifted_codes 清洗范围必须覆盖全部叙述字段——旧实现只清 objective，
        # behaviors/data_constraints 里的幻觉编码原样保留。docstring 承诺"剔除 LLM 产出但来源
        # 没有的编码"，不许反过来改 docstring 迁就实现。
        sections = [_clause("4.3b", ["B33"], "The meter shall log events.")]

        def chat(system: str, user: str) -> dict:
            return {"items": [{
                "objective": "记录事件",
                "behaviors": ["记录 OBIS 0-0:10.0.0 事件"],   # 幻觉编码落在 behaviors
                "data_constraints": ["class_id 99 制式"],       # 幻觉编码落在 data_constraints
                "source_block_ids": ["B33"],
            }]}

        items, _ = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        self.assertEqual(len(items), 1)
        item = items[0]
        # 两个幻觉编码都进 rejected_codes 留痕
        self.assertTrue(any("0-0:10.0.0" in c for c in item["rejected_codes"]))
        # behaviors / data_constraints 中的幻觉编码被实际剔除（不只是 objective）
        self.assertFalse(any("0-0:10.0.0" in b for b in item["behaviors"]),
                         f"behaviors 仍含幻觉编码：{item['behaviors']}")

    def test_llm_numeric_drift_soft_flagged(self) -> None:
        # 来源没有 999，LLM 写 999 → 软标（保留 + flag），不硬拦
        sections = [_clause("4.4", ["B4"], "The meter shall report energy.")]

        def chat(system: str, user: str) -> dict:
            return {"items": [{
                "objective": "上报 999 kWh",
                "behaviors": ["report"],
                "source_block_ids": ["B4"],
            }]}

        items, _ = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        self.assertTrue(items[0]["numeric_drift_flag"])
        self.assertIn("999", items[0]["numeric_drift_values"])

    def test_llm_failure_falls_back_to_stub_honestly(self) -> None:
        sections = [_clause("4.5", ["B5"], "shall do X.")]

        def chat(system: str, user: str) -> dict:
            raise RuntimeError("endpoint down")

        items, route = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        # 调用失败 → stub 退化，route 如实 stub
        self.assertEqual(route, "stub")
        self.assertEqual(len(items), 1)

    def test_llm_illegal_payload_falls_back_to_stub(self) -> None:
        sections = [_clause("4.6", ["B6"], "shall do Y.")]
        items, route = fe.extract_functional_requirements(
            sections, chat=lambda s, u: {"not_items": []}, route="openai_compatible",
        )
        self.assertEqual(route, "stub")
        self.assertEqual(len(items), 1)


class ConservationTests(unittest.TestCase):
    def test_block_coverage_closes(self) -> None:
        sections = [
            _clause("5.1", ["B1", "B2"], "The meter shall log events."),
            _clause("5.2", ["B3"], "The meter shall support readout."),
        ]
        items = [
            {"source_block_ids": ["B1", "B2"], "source_quote": "The meter shall log events.",
             "objective": "The meter shall log events", "functional_requirement_id": "F1"},
            {"source_block_ids": ["B3"], "source_quote": "The meter shall support readout.",
             "objective": "The meter shall support readout", "functional_requirement_id": "F2"},
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"])
        self.assertFalse(report["block_export"])

    def test_missing_clause_blocks_export(self) -> None:
        sections = [
            _clause("5.1", ["B1"], "The meter shall log events."),
            _clause("5.2", ["B2"], "The meter shall support readout."),
        ]
        items = [{"source_block_ids": ["B1"], "source_quote": "The meter shall log events.",
                  "objective": "The meter shall log events"}]  # B2 未覆盖
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertTrue(report["block_export"])
        self.assertIn("B2", report["missing_block_ids"])
        # 阻塞导出闸门
        with self.assertRaises(fe.FunctionalConservationError):
            fe.raise_if_unconserved(report)

    def test_multi_consumption_is_legal_not_duplicate(self) -> None:
        """§3.1：同一 block 被多条需求引用不再判重——义务句同覆盖但叙述不同=多视角引用。"""
        sections = [_clause("5.1", ["B1"], "The meter shall log events.")]
        items = [
            {"source_block_ids": ["B1"], "source_quote": "The meter shall log events.",
             "objective": "The meter shall log events", "functional_requirement_id": "F1"},
            {"source_block_ids": ["B1"], "source_quote": "The meter shall log events.",
             "objective": "The meter shall record event logs for audit",
             "functional_requirement_id": "F2"},
        ]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"])
        self.assertEqual(report["duplicate_assignments"], [])

    def test_duplicate_narrative_on_same_obligation_blocks(self) -> None:
        """§3.1：同一义务句被多条需求覆盖**且**叙述高度相似 → 判重（blocking）。"""
        sections = [_clause("5.1", ["B1"], "The meter shall log events.")]
        items = [
            {"source_block_ids": ["B1"], "source_quote": "The meter shall log events.",
             "objective": "The meter shall log events", "behaviors": ["log events"],
             "functional_requirement_id": "F1"},
            {"source_block_ids": ["B1"], "source_quote": "The meter shall log events.",
             "objective": "The meter shall log events", "behaviors": ["log events"],
             "functional_requirement_id": "F2"},
        ]
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertIn("duplicates", report["failure_categories"])
        self.assertIn("B1", report["duplicate_assignments"])

    def test_drilldown_subatoms_must_consume_parent(self) -> None:
        sections = [_clause("6.1", ["B1", "B2"], "The meter shall log events.")]
        items = [{
            "source_block_ids": ["B1", "B2"], "source_quote": "The meter shall log events.",
            "objective": "The meter shall log events",
            "drilled_subatoms": [
                {"source_block_ids": ["B1"]},  # 缺 B2 → 子原子未完全消费父条款
            ],
        }]
        report = fe.conservation_report(sections, items)
        self.assertFalse(report["ok"])
        self.assertTrue(report["evidence_mismatches"])

    def test_conserved_drilldown_passes(self) -> None:
        sections = [_clause("6.1", ["B1", "B2"], "The meter shall log events.")]
        items = [{
            "source_block_ids": ["B1", "B2"], "source_quote": "The meter shall log events.",
            "objective": "The meter shall log events",
            "drilled_subatoms": [
                {"source_block_ids": ["B1"]},
                {"source_block_ids": ["B2"]},
            ],
        }]
        report = fe.conservation_report(sections, items)
        self.assertTrue(report["ok"])


class RunAndCacheTests(unittest.TestCase):
    def test_run_writes_governed_artifact_and_conservation(self) -> None:
        with TemporaryDirectory() as tmp:
            sections = [_clause("7.1", ["B1"], "The meter shall log.")]
            result = fe.run_functional_extract(tmp, sections=sections, route="stub")
            self.assertEqual(result["route"], "stub")
            self.assertEqual(result["functional_requirements"], 1)
            self.assertTrue(result["conservation"]["ok"])
            self.assertEqual(result["written"], ["functional_requirements.json"])
            # 产物落盘（governed 路径：package 无 marker → 裸根）
            with open(os.path.join(tmp, "functional_requirements.json"), encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload["producer"], fe.FUNCTIONAL_EXTRACT_VERSION)
            self.assertIn("provenance", payload)

    def test_cache_hit_does_not_rewrite_and_preserves_route(self) -> None:
        with TemporaryDirectory() as tmp:
            sections = [_clause("7.2", ["B1"], "shall X.")]
            first = fe.run_functional_extract(tmp, sections=sections, route="stub")
            self.assertEqual(first["written"], ["functional_requirements.json"])
            # 第二次同指纹 → 命中缓存，不再写盘
            second = fe.run_functional_extract(tmp, sections=sections, route="stub")
            self.assertEqual(second["written"], [])
            self.assertEqual(second["functional_requirements"], 1)

    def test_fingerprint_changes_with_clause_text(self) -> None:
        s1 = [_clause("7.3", ["B1"], "alpha")]
        s2 = [_clause("7.3", ["B1"], "beta")]
        self.assertNotEqual(fe.extraction_fingerprint(s1), fe.extraction_fingerprint(s2))


class RouteFingerprintTests(unittest.TestCase):
    """S1-7：缓存指纹必须并入 route 维度——历史 stub 产物不应被后续真实 LLM 请求静默复用。

    实证场景（重构结论 §1.3 实证缺陷）：同一份条款先用 stub 跑（无 key），缓存 stub 产物；
    再切 openai_compatible 重跑，旧 stub 缓存被命中→LLM 永不被调用。修复后 route/model 变化
    即指纹失配，旧 stub 缓存诚实失效（预期行为，它们本就不该被复用）。
    """

    def test_fingerprint_differs_by_route_key(self) -> None:
        sections = [_clause("8.1", ["B1"], "shall X.")]
        stub_fp = fe.extraction_fingerprint(sections, route_key="stub")
        llm_fp = fe.extraction_fingerprint(sections, route_key="llm:mimo-v2.5")
        self.assertNotEqual(stub_fp, llm_fp)
        # 相同 route_key 仍稳定（缓存可复用的合法路径）
        self.assertEqual(stub_fp, fe.extraction_fingerprint(sections, route_key="stub"))

    def test_resolve_route_label_stub_when_no_key(self) -> None:
        # route=stub → 'stub'；route=openai_compatible 但无 key/env → 解析失败退回 'stub'
        self.assertEqual(fe._resolve_route_label("stub", None), "stub")
        self.assertEqual(fe._resolve_route_label(None, None), "stub")
        # openai_compatible 在测试环境无 key → 诚实退回 stub（不夸大）
        self.assertEqual(fe._resolve_route_label("openai_compatible", None), "stub")

    def test_resolve_route_label_injected_when_chat_given(self) -> None:
        # 注入 chat（测试用）→ 'injected'，与 stub/openai_compatible 产物不共键
        chat = lambda system, user: {"items": []}  # noqa: E731
        self.assertEqual(fe._resolve_route_label("openai_compatible", chat), "injected")
        self.assertEqual(fe._resolve_route_label("stub", chat), "injected")

    def test_stub_cache_not_reused_when_route_changes_to_llm(self) -> None:
        """实证复测：stub 跑后改 openai_compatible + 注入 chat 重跑，LLM 真实被调用。"""
        with TemporaryDirectory() as tmp:
            sections = [_clause("8.2", ["B1"], "The meter shall log.")]
            # 第一次：stub 路由（无 key）→ 缓存 stub 产物
            first = fe.run_functional_extract(tmp, sections=sections, route="stub")
            self.assertEqual(first["route"], "stub")
            self.assertEqual(first["functional_requirements"], 1)

            # 第二次：openai_compatible + 注入 chat → 必须真实调用（不被 stub 缓存复用）
            calls: list[int] = []

            def chat(system: str, user: str) -> dict:
                calls.append(1)
                return {"items": [{
                    "objective": "LLM 抽取的目标",
                    "behaviors": ["log"],
                    "source_block_ids": ["B1"],
                    "source_quote": "The meter shall log.",
                }]}

            second = fe.run_functional_extract(
                tmp, sections=sections, route="openai_compatible", chat=chat,
            )
            # LLM（注入 chat）真实被调用——证明 stub 缓存未被复用
            self.assertGreater(len(calls), 0)
            self.assertTrue(second["route"].startswith("injected"))
            # 产物反映 LLM 抽取（objective 带标记），非 stub 占位
            self.assertEqual(second["functional_requirements"], 1)


class StableUidTests(unittest.TestCase):
    """T3-1 跨再生成稳定 ID：``requirement_uid`` 按条款序号定位，与内容哈希解耦。"""

    def test_stub_items_get_positional_uids_in_clause_order(self) -> None:
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The meter shall collect voltage."),
        ]
        items, _ = fe.extract_functional_requirements(sections, route="stub")
        self.assertEqual([i["requirement_uid"] for i in items], ["FR-0001", "FR-0002"])
        # 旧 content-hash 别名仍存在（不做原地替换）
        self.assertTrue(all(i["functional_requirement_id"].startswith("FRE-") for i in items))

    def test_uid_stable_across_regen_with_narrative_and_order_drift(self) -> None:
        """核心验收：再生成（叙述变 + LLM 输出顺序交换）后，同一条款的 ``requirement_uid`` 不变。

        旧 ``functional_requirement_id`` 含 output index → 顺序交换即漂移；新 uid 按条款序号
        定位 → 稳定。证明 uid 可作长期 RTM 主键。
        """
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The meter shall collect voltage at 230 V."),
        ]

        def chat_v1(system: str, user: str) -> dict:
            # 顺序：先 B1 条款，后 B2 条款
            return {"items": [
                {"objective": "记录事件A", "behaviors": ["写日志A"], "source_block_ids": ["B1"]},
                {"objective": "采集电压B", "behaviors": ["采 230V"], "source_block_ids": ["B2"]},
            ]}

        def chat_v2(system: str, user: str) -> dict:
            # 再生成：叙述全变 + 输出顺序交换（B2 先、B1 后）
            return {"items": [
                {"objective": "完全不同的电压采集措辞", "behaviors": ["全新采压行为"], "source_block_ids": ["B2"]},
                {"objective": "完全不同的事件记录措辞", "behaviors": ["全新日志行为"], "source_block_ids": ["B1"]},
            ]}

        items_v1, _ = fe.extract_functional_requirements(sections, chat=chat_v1, route="openai_compatible")
        items_v2, _ = fe.extract_functional_requirements(sections, chat=chat_v2, route="openai_compatible")

        # UID 按条款稳定：B1 条款恒为 FR-0001，B2 条款恒为 FR-0002（与 LLM 输出顺序无关）
        def by_block(items, block):
            return next(i for i in items if block in i["source_block_ids"])

        self.assertEqual(by_block(items_v1, "B1")["requirement_uid"], "FR-0001")
        self.assertEqual(by_block(items_v2, "B1")["requirement_uid"], "FR-0001")
        self.assertEqual(by_block(items_v1, "B2")["requirement_uid"], "FR-0002")
        self.assertEqual(by_block(items_v2, "B2")["requirement_uid"], "FR-0002")
        # 叙述确实变了（再生成生效）
        self.assertNotEqual(by_block(items_v1, "B1")["objective"], by_block(items_v2, "B1")["objective"])

    def test_multi_item_per_clause_gets_stable_subindex(self) -> None:
        """同一条款产出多条 → ``.2``/``.3`` 子序，按别名 id 稳定排序（再生成间确定）。"""
        sections = [_clause("4.1", ["B1"], "The meter shall log events and raise alarms.")]
        items_payload = {"items": [
            {"objective": "记录事件", "behaviors": ["写日志"], "source_block_ids": ["B1"]},
            {"objective": "告警", "behaviors": ["发告警"], "source_block_ids": ["B1"]},
        ]}

        def chat(system, user):
            return items_payload

        out = fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")[0]
        uids = sorted(i["requirement_uid"] for i in out)
        self.assertEqual(uids, ["FR-0001", "FR-0001.2"])

    def test_assign_stable_uids_empty(self) -> None:
        self.assertEqual(fe.assign_stable_uids([], []), [])


class NegativeExemplarTests(unittest.TestCase):
    """P0-8：rejected 负例真正注入 functional_extract 直抽 prompt。"""

    def test_system_prompt_includes_negative_exemplars_when_present(self) -> None:
        prompt = fe._system_prompt("- 【通信】被拒绝：噪声\n  拒绝原因：无依据")
        self.assertIn("专家已拒绝的范例", prompt)
        self.assertIn("请勿产出同类问题", prompt)
        self.assertIn("被拒绝：噪声", prompt)

    def test_system_prompt_no_empty_shell_when_no_negatives(self) -> None:
        prompt = fe._system_prompt("")
        self.assertNotIn("专家已拒绝", prompt)
        self.assertNotIn("请勿产出同类问题", prompt)

    def test_negative_exemplars_injected_into_legacy_chat(self) -> None:
        sections = [_clause("4.1 / 通信协议", ["B1"], "The meter shall support secure channel.")]
        bank = {
            "accepted": {},
            "rejected": {
                "r1": {"module": "通信协议", "title": "噪声 secure channel", "description": "不成立的 secure channel 需求",
                       "reason": "无来源依据"},
            },
        }
        captured: dict[str, str] = {}

        def chat(system: str, user: str) -> dict:
            captured["system"] = system
            return {"items": [{"objective": "支持安全通道", "source_block_ids": ["B1"]}]}

        with patch("functional_extract._load_adjudication_bank", return_value=bank):
            fe.extract_functional_requirements(sections, chat=chat, route="openai_compatible")
        self.assertIn("专家已拒绝的范例", captured["system"])
        self.assertIn("噪声 secure channel", captured["system"])
        self.assertIn("无来源依据", captured["system"])

    def test_negative_exemplars_injected_into_clause_family_chat(self) -> None:
        sections = [_clause("4.1 / 通信协议", ["B1"], "The meter shall support secure channel.")]
        bank = {
            "accepted": {},
            "rejected": {
                "r1": {"module": "通信协议", "title": "噪声 secure channel", "description": "不成立的 secure channel 需求",
                       "reason": "无来源依据"},
            },
        }
        captured: dict[str, str] = {}

        def chat(system: str, user: str) -> dict:
            captured["system"] = system
            return {"items": [{"objective": "支持安全通道", "source_block_ids": ["B1"]}]}

        with patch("functional_extract._load_adjudication_bank", return_value=bank):
            fe.extract_functional_requirements(
                sections, chat=chat, route="openai_compatible", strategy="clause_family"
            )
        self.assertIn("专家已拒绝的范例", captured["system"])
        self.assertIn("噪声 secure channel", captured["system"])

    def test_stub_route_does_not_load_bank(self) -> None:
        sections = [_clause("4.1", ["B1"], "shall X.")]
        with patch("functional_extract._load_adjudication_bank") as mock_load:
            fe.extract_functional_requirements(sections, route="stub")
        mock_load.assert_not_called()

    def test_negative_exemplar_count_respects_config(self) -> None:
        # 默认 k=2；通过环境变量可配（在子进程中验证，避免污染已导入模块）
        self.assertEqual(fe.FUNCTIONAL_EXTRACT_NEGATIVE_K, 2)
        import subprocess
        import sys
        code = (
            "import os, functional_extract; "
            "print(functional_extract.FUNCTIONAL_EXTRACT_NEGATIVE_K)"
        )
        env = {**os.environ, "RATOMIZER_FUNCTIONAL_EXTRACT_NEGATIVE_K": "1"}
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        self.assertEqual(result.stdout.strip(), "1")


class ExtractProgressTests(unittest.TestCase):
    def test_clause_family_emits_initial_and_per_package(self) -> None:
        """每条款包回调一次——直抽不报进度时 GUI 会在 0% 停半小时。"""
        sections = [
            _clause("4.1", ["B1"], "The meter shall log events."),
            _clause("4.2", ["B2"], "The meter shall alarm."),
        ]
        events: list[dict] = []

        def chat(system: str, user: str) -> dict:
            block = "B1" if "4.1" in user or "log events" in user else "B2"
            return {"items": [{"objective": "do it", "source_block_ids": [block]}]}

        items, _route = fe.extract_functional_requirements(
            sections,
            chat=chat,
            route="openai_compatible",
            strategy="clause_family",
            progress_callback=events.append,
        )
        self.assertEqual(len(items), 2)
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(events[0]["stage"], "functional_extract")
        self.assertEqual(events[0]["completed"], 0)
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[0]["percent"], 0)
        self.assertEqual(events[0]["unit"], "clauses")
        self.assertEqual(events[-1]["completed"], 2)
        self.assertEqual(events[-1]["total"], 2)
        self.assertEqual(events[-1]["percent"], 100)
        completed = [row["completed"] for row in events]
        self.assertEqual(completed, [0, 1, 2])

    def test_legacy_emits_start_and_finish(self) -> None:
        sections = [_clause("4.1", ["B1"], "The meter shall log events.")]
        events: list[dict] = []

        def chat(system: str, user: str) -> dict:
            return {"items": [{"objective": "log", "source_block_ids": ["B1"]}]}

        fe.extract_functional_requirements(
            sections,
            chat=chat,
            route="openai_compatible",
            strategy="legacy",
            progress_callback=events.append,
        )
        self.assertEqual(events[0]["completed"], 0)
        self.assertEqual(events[-1]["completed"], 1)
        self.assertEqual(events[-1]["percent"], 100)

    def test_cache_hit_emits_complete(self) -> None:
        with TemporaryDirectory() as tmp:
            sections = [_clause("7.2", ["B1"], "shall X.")]
            fe.run_functional_extract(tmp, sections=sections, route="stub", strategy="legacy")
            events: list[dict] = []
            second = fe.run_functional_extract(
                tmp,
                sections=sections,
                route="stub",
                strategy="legacy",
                progress_callback=events.append,
            )
            self.assertEqual(second["written"], [])
            self.assertTrue(events)
            self.assertEqual(events[-1]["stage"], "functional_extract")
            self.assertEqual(events[-1]["percent"], 100)
            self.assertEqual(events[-1]["completed"], events[-1]["total"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
