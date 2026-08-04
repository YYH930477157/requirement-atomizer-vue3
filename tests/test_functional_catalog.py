from __future__ import annotations

import unittest


class FunctionalCatalogClusteringTests(unittest.TestCase):
    def test_llm_catalog_batches_non_parameter_rows_at_thirty_in_stable_order(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {
                "ai_req_id": f"AI-{index:03d}",
                "title": f"Independent function {index}",
                "description": f"The system shall provide independent function {index}.",
                "module": "general",
            }
            for index in range(35)
        ]
        calls: list[list[str]] = []

        def chat(_system: str, user: str) -> dict:
            import json

            atom_ids = [atom["atom_id"] for atom in json.loads(user)["atoms"]]
            calls.append(atom_ids)
            return {
                "catalog": [
                    {
                        "catalog_key": atom_id,
                        "title": atom_id,
                        "atom_ids": [atom_id],
                        "reason": "single",
                        "confidence": 1.0,
                    }
                    for atom_id in atom_ids
                ]
            }

        catalog = build_function_catalog(rows, chat=chat)

        self.assertEqual([len(call) for call in calls], [30, 5])
        self.assertEqual([atom_id for call in calls for atom_id in call], [row["ai_req_id"] for row in rows])
        self.assertEqual(len(catalog), 35)

    def test_parameter_rows_bypass_llm_and_never_merge_across_source_blocks(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {
                "ai_req_id": "PROW-DET-BLK-1-R0001",
                "functional_key": "voltage-setting",
                "title": "Voltage setting",
                "description": "Voltage setting is required.",
                "module": "configuration",
                "source_block_ids": ["BLK-1"],
            },
            {
                "ai_req_id": "PROW-DET-BLK-2-R0001",
                "functional_key": "voltage-setting",
                "title": "Voltage setting",
                "description": "Voltage setting is required.",
                "module": "configuration",
                "source_block_ids": ["BLK-2"],
            },
            {
                "ai_req_id": "AI-OTHER",
                "title": "Remote configuration",
                "description": "The system shall support remote configuration.",
                "module": "configuration",
            },
        ]
        calls: list[list[str]] = []

        def chat(_system: str, user: str) -> dict:
            import json

            atom_ids = [atom["atom_id"] for atom in json.loads(user)["atoms"]]
            calls.append(atom_ids)
            return {"catalog": [{
                "catalog_key": "remote-configuration",
                "title": "Remote configuration",
                "atom_ids": atom_ids,
                "reason": "single",
                "confidence": 1.0,
            }]}

        catalog = build_function_catalog(rows, chat=chat)

        self.assertEqual(calls, [["AI-OTHER"]])
        self.assertEqual(
            sorted(item["source_ai_requirement_ids"] for item in catalog),
            [["AI-OTHER"], ["PROW-DET-BLK-1-R0001"], ["PROW-DET-BLK-2-R0001"]],
        )
    def test_cross_section_significant_event_actions_merge(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-C", "title": "采集重要事件", "description": "设备必须采集重要事件。",
             "module": "事件记录", "source_section": "5", "source_quote": "The device shall collect significant events."},
            {"ai_req_id": "AI-T", "title": "远程传输重要事件", "description": "设备必须将重要事件远程传输到中心。",
             "module": "事件记录", "source_section": "8", "source_quote": "The device shall remotely transmit significant events."},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["source_ai_requirement_ids"], ["AI-C", "AI-T"])
        self.assertGreaterEqual(catalog[0]["merge_confidence"], 0.8)
        self.assertIn("跨章节", catalog[0]["synthesis_reason"])

    def test_protocol_profiles_merge_as_named_variants(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-PM1", "title": "PM1点对多点协议配置文件要求",
             "description": "设备应支持 PM1 点对多点协议配置。", "module": "通信协议",
             "source_section": "4.5.1 PM1 Point-Multipoint Profile", "source_quote": "PM1 shall be supported."},
            {"ai_req_id": "AI-PM2", "title": "PM2点对多点协议配置文件要求",
             "description": "设备应支持 PM2 点对多点协议配置。", "module": "通信协议",
             "source_section": "4.5.2 PM2 Point-Multipoint Profile", "source_quote": "PM2 shall be supported."},
        ]

        item = build_function_catalog(rows)[0]

        self.assertEqual(len(item["variants"]), 2)
        self.assertEqual({v["name"] for v in item["variants"]}, {"PM1", "PM2"})
        self.assertEqual(item["conflict_flags"], [])

    def test_distinct_event_subjects_do_not_merge(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-BAT", "title": "低电量事件检测与报告", "description": "检测并报告低电量事件。",
             "module": "事件记录", "source_quote": "Detect and report a low battery event."},
            {"ai_req_id": "AI-FLOW", "title": "异常流量事件检测与报告", "description": "检测并报告异常流量事件。",
             "module": "事件记录", "source_quote": "Detect and report an abnormal flow event."},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 2)
        self.assertEqual([{*x["source_ai_requirement_ids"]} for x in catalog], [{"AI-BAT"}, {"AI-FLOW"}])

    def test_opposite_replaceability_qualifiers_do_not_fuzzy_merge(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-NR", "title": "不可更换电池MGW的电池寿命要求",
             "description": "不可更换电池的设备应满足规定寿命。", "module": "环境可靠性"},
            {"ai_req_id": "AI-R", "title": "可更换电池MGW的电池寿命要求",
             "description": "可更换电池的设备应满足规定寿命。", "module": "环境可靠性"},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 2)

    def test_explicit_functional_keys_normalize_punctuation(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-1", "functional_key": "重要事件：采集与远传", "title": "采集事件", "module": "事件"},
            {"ai_req_id": "AI-2", "functional_key": "重要事件-采集与远传", "title": "远传事件", "module": "事件"},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["merge_method"], "explicit_key")

    def test_semantically_equivalent_explicit_event_keys_merge(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {
                "ai_req_id": "AI-D",
                "functional_key": "重要事件检测与记录",
                "title": "检测重要事件",
                "description": "系统应检测并记录重要事件。",
                "module": "事件",
            },
            {
                "ai_req_id": "AI-T",
                "functional_key": "重要事件记录和远传",
                "title": "远传重要事件",
                "description": "系统应将重要事件远程传输。",
                "module": "通信",
            },
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["source_ai_requirement_ids"], ["AI-D", "AI-T"])
        self.assertEqual(catalog[0]["merge_method"], "explicit_semantic")

class FunctionalSynthesisIdentityTests(unittest.TestCase):
    def test_catalog_route_caps_truncation_escalation_at_one(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch
        from functional_synthesis import _resolve_catalog_chat

        config = SimpleNamespace(
            base_url="http://127.0.0.1:1234/v1",
            model="catalog-model",
            api_key_env="",
        )
        with patch("ai_extract.config_for_route", return_value=config), patch(
            "llm_client.chat_json", return_value={"catalog": []}
        ) as chat_json:
            chat, route = _resolve_catalog_chat("openai_compatible", None)
            self.assertIsNotNone(chat)
            result = chat("system", "user")

        self.assertEqual(route, "llm:catalog-model")
        self.assertEqual(result, {"catalog": []})
        chat_json.assert_called_once_with(
            config,
            "system",
            "user",
            max_truncation_escalations=1,
        )

    def test_legacy_rows_receive_stable_source_ids_before_cataloging(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from functional_synthesis import run_functional_synthesis

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rows = [
                {"title": "采集重要事件", "source_section": "5",
                 "source_quote": "The device shall collect significant events.", "module": "事件"},
                {"title": "远程传输重要事件", "source_section": "8",
                 "source_quote": "The device shall transmit significant events.", "module": "事件"},
            ]
            (out / "ai_requirements.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

            run_functional_synthesis(out)
            payload = json.loads((out / "functional_requirements.json").read_text(encoding="utf-8"))
            assigned = [rid for item in payload["items"] for rid in item["source_ai_requirement_ids"]]

        self.assertEqual(len(assigned), 2)
        self.assertEqual(len(set(assigned)), 2)
        self.assertTrue(all(rid.startswith("AIR-") for rid in assigned))
        self.assertEqual(payload["catalog_producer"], "functional-catalog-v2")

    def test_compliance_requirements_do_not_enter_function_catalog(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from functional_synthesis import run_functional_synthesis

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rows = [
                {
                    "ai_req_id": "AI-CORE",
                    "type": "behavior",
                    "title": "双向通信",
                    "description": "The meter shall communicate bidirectionally over DLMS/COSEM.",
                    "source_quote": "The meter shall communicate bidirectionally over DLMS/COSEM.",
                    "module": "通信协议",
                },
                {
                    "ai_req_id": "AI-COMP",
                    "type": "compliance",
                    "title": "型式证书",
                    "description": "A valid type certificate according to IEC 62053-22 shall be supplied.",
                    "source_quote": "A valid type certificate according to IEC 62053-22 shall be supplied.",
                    "module": "测试合规",
                },
            ]
            (out / "ai_requirements.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = run_functional_synthesis(out, route="stub")
            payload = json.loads((out / "functional_requirements.json").read_text(encoding="utf-8"))

        self.assertEqual(result["compliance_requirements"], 1)
        self.assertEqual(payload["compliance_requirements"], 1)
        assigned = {
            source_id
            for item in payload["items"]
            for source_id in item.get("source_ai_requirement_ids") or []
        }
        self.assertEqual(assigned, {"AI-CORE"})


class StructuredFunctionalRequirementTests(unittest.TestCase):
    def test_different_period_variants_split_per_reviewer_ruling(self) -> None:
        """周期档位分家（审核人 2026-07-23 裁定，取代旧"周期变体合并为 variants"行为）：
        15 min × 1 h 是两条独立曲线/对象，拆成两个功能项、各自保留约束与溯源。"""
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-15", "title": "15分钟用量归档", "description": "设备应每15分钟归档一次用量。",
             "module": "曲线", "source_section": "5.3", "source_quote": "Archive consumption every 15 minutes.",
             "source_block_ids": ["B15"], "acceptance_criteria": ["验证15分钟记录存在"]},
            {"ai_req_id": "AI-60", "title": "1小时用量归档", "description": "设备应每1小时归档一次用量。",
             "module": "曲线", "source_section": "5.3", "source_quote": "Archive consumption every 1 hour.",
             "source_block_ids": ["B60"], "design_options": ["可使用统一调度器"]},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 2)
        by_id = {item["source_ai_requirement_ids"][0]: item for item in catalog}
        self.assertEqual(by_id["AI-15"]["source_block_ids"], ["B15"])
        self.assertEqual(by_id["AI-60"]["source_block_ids"], ["B60"])
        self.assertTrue(any("15" in value for value in by_id["AI-15"]["data_constraints"]))
        self.assertTrue(any("1" in value for value in by_id["AI-60"]["data_constraints"]))

    def test_same_unqualified_parameter_with_conflicting_values_is_flagged(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-A", "functional_key": "事件保留", "title": "事件保留时长",
             "description": "事件应保留30天。", "module": "事件", "source_quote": "Events shall be retained for 30 days."},
            {"ai_req_id": "AI-B", "functional_key": "事件保留", "title": "事件保留时长",
             "description": "事件应保留60天。", "module": "事件", "source_quote": "Events shall be retained for 60 days."},
        ]

        item = build_function_catalog(rows)[0]

        self.assertTrue(item["conflict_flags"])
        self.assertTrue(any("30" in flag and "60" in flag for flag in item["conflict_flags"]))

    def test_explicit_key_does_not_override_opposed_qualifiers(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-NR", "functional_key": "电池寿命", "title": "不可更换电池寿命", "module": "电源"},
            {"ai_req_id": "AI-R", "functional_key": "电池寿命", "title": "可更换电池寿命", "module": "电源"},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 2)
        self.assertTrue(all(len(item["source_ai_requirement_ids"]) == 1 for item in catalog))
    def test_explicit_function_key_merges_across_modules_and_preserves_modules(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-C", "functional_key": "事件日志管理", "title": "配置事件日志", "module": "参数配置"},
            {"ai_req_id": "AI-R", "functional_key": "事件日志管理", "title": "读取事件日志", "module": "事件记录"},
        ]

        item = build_function_catalog(rows)[0]

        self.assertEqual(item["source_ai_requirement_ids"], ["AI-C", "AI-R"])
        self.assertEqual(item["source_modules"], ["参数配置", "事件记录"])
        self.assertEqual(item["module"], "参数配置")

    def test_same_event_subject_merges_across_modules(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-D", "title": "检测计量事件", "description": "检测计量事件。", "module": "计量"},
            {"ai_req_id": "AI-T", "title": "上报计量事件", "description": "上报计量事件。", "module": "远程通信"},
        ]

        item = build_function_catalog(rows)[0]

        self.assertEqual(item["source_ai_requirement_ids"], ["AI-D", "AI-T"])
        self.assertEqual(item["source_modules"], ["计量", "远程通信"])
        self.assertEqual(item["merge_method"], "event_subject")

    def test_lifecycle_behaviors_are_classified_without_merging_different_subjects(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-C", "functional_key": "时钟管理", "title": "配置时钟参数", "description": "配置时钟参数。", "module": "时钟"},
            {"ai_req_id": "AI-Q", "functional_key": "时钟管理", "title": "查询时钟状态", "description": "查询时钟状态。", "module": "通信"},
            {"ai_req_id": "AI-T", "functional_key": "时钟管理", "title": "上报时钟状态", "description": "上报时钟状态。", "module": "通信"},
            {"ai_req_id": "AI-E", "title": "上报阀门状态", "description": "上报阀门状态。", "module": "通信"},
        ]

        catalog = build_function_catalog(rows)
        clock = next(item for item in catalog if "AI-C" in item["source_ai_requirement_ids"])
        valve = next(item for item in catalog if "AI-E" in item["source_ai_requirement_ids"])

        self.assertEqual([entry["role"] for entry in clock["lifecycle_behaviors"]], ["configure", "query", "report"])
        self.assertEqual(clock["source_ai_requirement_ids"], ["AI-C", "AI-Q", "AI-T"])
        self.assertEqual(valve["source_ai_requirement_ids"], ["AI-E"])
    def test_generic_requirement_cannot_bridge_opposed_qualifiers(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-NR", "title": "本地上报计量事件", "module": "事件"},
            {"ai_req_id": "AI-G", "title": "上报计量事件", "module": "事件"},
            {"ai_req_id": "AI-R", "title": "远程上报计量事件", "module": "事件"},
        ]

        catalog = build_function_catalog(rows)
        group_by_id = {
            source_id: set(item["source_ai_requirement_ids"])
            for item in catalog for source_id in item["source_ai_requirement_ids"]
        }

        self.assertNotIn("AI-R", group_by_id["AI-NR"])
        self.assertNotIn("AI-NR", group_by_id["AI-R"])
    def test_inferred_event_group_with_conflicting_periods_stays_split(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-A", "title": "阀门非重复性事件检测", "description": "2分钟内检测事件。", "module": "机械"},
            {"ai_req_id": "AI-B", "title": "阀门非重复性事件测试", "description": "10分钟后执行测试。", "module": "测试"},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 2)
        self.assertTrue(all(len(item["source_ai_requirement_ids"]) == 1 for item in catalog))

    def test_lifecycle_role_prefers_primary_action_over_later_configuration_text(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [{
            "ai_req_id": "AI-S", "title": "记录计量事件日志",
            "description": "设备应记录计量事件。日志容量阈值可配置。", "module": "事件",
        }]

        item = build_function_catalog(rows)[0]

        self.assertEqual(item["lifecycle_behaviors"][0]["role"], "store")
    def test_every_atom_assigned_exactly_once(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": f"AI-{index}", "title": title, "module": module}
            for index, (title, module) in enumerate([
                ("采集重要事件", "事件"), ("远程传输重要事件", "事件"),
                ("低电量事件检测", "事件"), ("时钟同步", "时钟"),
            ], start=1)
        ]

        catalog = build_function_catalog(rows)
        assigned = [rid for item in catalog for rid in item["source_ai_requirement_ids"]]

        self.assertCountEqual(assigned, [row["ai_req_id"] for row in rows])
        self.assertEqual(len(assigned), len(set(assigned)))


if __name__ == "__main__":
    unittest.main()


class OptionalLlmCatalogTests(unittest.TestCase):
    def test_valid_llm_catalog_mapping_controls_grouping(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-C", "title": "采集时钟状态", "module": "时钟"},
            {"ai_req_id": "AI-T", "title": "上报时钟状态", "module": "时钟"},
        ]

        def chat(_system: str, _user: str) -> dict:
            return {"catalog": [{
                "catalog_key": "时钟状态管理", "title": "时钟状态管理",
                "atom_ids": ["AI-C", "AI-T"],
                "reason": "同一状态的采集与上报", "confidence": 0.94,
            }]}

        item = build_function_catalog(rows, chat=chat)[0]

        self.assertEqual(item["source_ai_requirement_ids"], ["AI-C", "AI-T"])
        self.assertEqual(item["merge_method"], "llm_catalog")
        self.assertEqual(item["merge_confidence"], 0.94)
        self.assertEqual(item["synthesis_reason"], "同一状态的采集与上报")

    def test_llm_mapping_cannot_merge_opposed_qualifiers(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-NR", "title": "不可更换电池寿命要求", "module": "电源"},
            {"ai_req_id": "AI-R", "title": "可更换电池寿命要求", "module": "电源"},
        ]

        def chat(_system: str, _user: str) -> dict:
            return {"catalog": [{
                "catalog_key": "电池寿命", "title": "电池寿命",
                "atom_ids": ["AI-NR", "AI-R"], "reason": "同类功能", "confidence": 0.95,
            }]}

        catalog = build_function_catalog(rows, chat=chat)

        self.assertEqual(len(catalog), 2)
        self.assertTrue(all(item["merge_method"] != "llm_catalog" for item in catalog))

    def test_llm_mapping_cannot_merge_different_event_subjects(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-L", "title": "低电量事件检测", "module": "事件"},
            {"ai_req_id": "AI-F", "title": "异常流量事件检测", "module": "事件"},
        ]

        def chat(_system: str, _user: str) -> dict:
            return {"catalog": [{
                "catalog_key": "事件检测", "title": "事件检测",
                "atom_ids": ["AI-L", "AI-F"], "reason": "都是事件", "confidence": 0.9,
            }]}

        catalog = build_function_catalog(rows, chat=chat)

        self.assertEqual(len(catalog), 2)
        self.assertTrue(all(item["merge_method"] != "llm_catalog" for item in catalog))

    def test_llm_profile_group_preserves_named_variants(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-PM1", "title": "PM1协议配置", "description": "支持PM1通信。", "module": "通信"},
            {"ai_req_id": "AI-PM2", "title": "PM2协议配置", "description": "支持PM2通信。", "module": "通信"},
        ]

        def chat(_system: str, _user: str) -> dict:
            return {"catalog": [{
                "catalog_key": "PM协议配置", "title": "PM协议配置",
                "atom_ids": ["AI-PM1", "AI-PM2"], "reason": "同一协议家族", "confidence": 0.96,
            }]}

        item = build_function_catalog(rows, chat=chat)[0]

        self.assertEqual(item["merge_method"], "llm_catalog")
        self.assertEqual([variant["name"] for variant in item["variants"]], ["PM1", "PM2"])
    def test_llm_mapping_cannot_hide_conflicting_event_periods_as_variants(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-A", "title": "阀门非重复性事件检测", "description": "2分钟内检测事件。", "module": "事件"},
            {"ai_req_id": "AI-B", "title": "阀门非重复性事件测试", "description": "10分钟后执行测试。", "module": "事件"},
        ]

        def chat(_system: str, _user: str) -> dict:
            return {"catalog": [{
                "catalog_key": "阀门非重复性事件", "title": "阀门非重复性事件",
                "atom_ids": ["AI-A", "AI-B"], "reason": "同一事件", "confidence": 0.95,
            }]}

        catalog = build_function_catalog(rows, chat=chat)

        self.assertEqual(len(catalog), 2)
        self.assertTrue(all(item["merge_method"] != "llm_catalog" for item in catalog))
    def test_llm_route_still_consolidates_safe_cross_module_event_family(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-D", "title": "检测计量事件", "description": "检测计量事件。", "module": "计量"},
            {"ai_req_id": "AI-T", "title": "上报计量事件", "description": "上报计量事件。", "module": "通信"},
        ]

        def chat(_system: str, user: str) -> dict:
            atoms = json.loads(user)["atoms"]
            return {"catalog": [{
                "catalog_key": atom["atom_id"], "title": atom["title"],
                "atom_ids": [atom["atom_id"]], "reason": "单条保留", "confidence": 1.0,
            } for atom in atoms]}

        item = build_function_catalog(rows, chat=chat)[0]

        self.assertEqual(item["source_ai_requirement_ids"], ["AI-D", "AI-T"])
        self.assertEqual(item["merge_method"], "event_subject")
        self.assertEqual(item["source_modules"], ["计量", "通信"])

    def test_collection_has_its_own_lifecycle_role(self) -> None:
        from functional_catalog import build_function_catalog

        item = build_function_catalog([{
            "ai_req_id": "AI-C", "title": "采集计量数据", "description": "采集计量数据并准备后续处理。", "module": "计量",
        }])[0]

        self.assertEqual(item["lifecycle_behaviors"][0]["role"], "collect")

    def test_explicit_key_cannot_merge_different_event_subjects(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-L", "functional_key": "事件管理", "title": "低电量事件检测", "module": "事件"},
            {"ai_req_id": "AI-F", "functional_key": "事件管理", "title": "异常流量事件检测", "module": "事件"},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 2)
    def test_llm_multi_atom_event_group_can_join_safe_cross_module_event_atom(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-D", "title": "检测计量事件", "description": "检测计量事件。", "module": "事件"},
            {"ai_req_id": "AI-S", "title": "存储计量事件", "description": "存储计量事件。", "module": "事件"},
            {"ai_req_id": "AI-T", "title": "上报计量事件", "description": "上报计量事件。", "module": "通信"},
        ]

        def chat(_system: str, user: str) -> dict:
            atoms = json.loads(user)["atoms"]
            if len(atoms) == 2:
                return {"catalog": [{
                    "catalog_key": "计量事件管理", "title": "计量事件管理",
                    "atom_ids": [atom["atom_id"] for atom in atoms],
                    "reason": "同一事件的检测与存储", "confidence": 0.95,
                }]}
            atom = atoms[0]
            return {"catalog": [{
                "catalog_key": atom["atom_id"], "title": atom["title"],
                "atom_ids": [atom["atom_id"]], "reason": "单条", "confidence": 1.0,
            }]}

        item = build_function_catalog(rows, chat=chat)[0]

        self.assertEqual(item["source_ai_requirement_ids"], ["AI-D", "AI-S", "AI-T"])
        self.assertEqual(item["merge_method"], "event_subject")

    def test_inferred_event_group_with_conflicting_flow_thresholds_stays_split(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-5", "title": "异常流量事件检测", "description": "流量超过5 L/h时触发事件。", "module": "事件"},
            {"ai_req_id": "AI-10", "title": "异常流量事件上报", "description": "流量超过10 L/h时上报事件。", "module": "通信"},
        ]

        catalog = build_function_catalog(rows)

        self.assertEqual(len(catalog), 2)

    def test_explicit_group_reports_conflicting_flow_thresholds(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-5", "functional_key": "异常流量事件", "title": "异常流量事件检测", "description": "流量超过5 L/h时触发事件。", "module": "事件"},
            {"ai_req_id": "AI-10", "functional_key": "异常流量事件", "title": "异常流量事件上报", "description": "流量超过10 L/h时上报事件。", "module": "通信"},
        ]

        item = build_function_catalog(rows)[0]

        self.assertTrue(any("5 L/h" in flag and "10 L/h" in flag for flag in item["conflict_flags"]))
    def test_low_confidence_llm_mapping_falls_back(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-C", "title": "采集时钟状态", "module": "时钟"},
            {"ai_req_id": "AI-T", "title": "上报时钟状态", "module": "时钟"},
        ]

        def chat(_system: str, _user: str) -> dict:
            return {"catalog": [{
                "catalog_key": "时钟状态管理", "title": "时钟状态管理",
                "atom_ids": ["AI-C", "AI-T"], "reason": "不确定", "confidence": 0.4,
            }]}

        catalog = build_function_catalog(rows, chat=chat)

        self.assertTrue(all(item["merge_method"] != "llm_catalog" for item in catalog))
    def test_invalid_llm_mapping_falls_back_without_losing_atoms(self) -> None:
        from functional_catalog import build_function_catalog

        rows = [
            {"ai_req_id": "AI-1", "title": "低电量事件检测", "module": "事件"},
            {"ai_req_id": "AI-2", "title": "异常流量事件检测", "module": "事件"},
        ]

        def chat(_system: str, _user: str) -> dict:
            return {"catalog": [{
                "catalog_key": "事件检测", "title": "事件检测",
                "atom_ids": ["AI-1", "AI-1", "UNKNOWN"],
            }]}

        catalog = build_function_catalog(rows, chat=chat)
        assigned = [rid for item in catalog for rid in item["source_ai_requirement_ids"]]

        self.assertEqual(len(catalog), 2)
        self.assertCountEqual(assigned, ["AI-1", "AI-2"])
        self.assertTrue(all(item["merge_method"] != "llm_catalog" for item in catalog))


class PeriodSplitAndObjectMergeRuleTests(unittest.TestCase):
    """聚类两规则（审核人 2026-07-23 裁定 + agent-eval-v2 靶点）：
    period_variant 周期档位不同分家；legacy_concept 标题共享对象词组合并。"""

    @staticmethod
    def _row(rid: str, title: str, text: str = "", module: str = "曲线") -> dict:
        return {"ai_req_id": rid, "title": title,
                "description": text or title, "source_quote": text or title,
                "module": module}

    def test_different_period_values_do_not_merge(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("A", "Load profile recording", "The meter shall record the load profile in 15-minute intervals.")
        b = self._row("B", "Load profile recording", "The meter shall record the load profile in 24-hour intervals.")
        self.assertFalse(_similar_legacy(a, b))

    def test_same_period_values_merge(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("A", "Voltage and current average profile",
                      "The meter shall record average effective voltage and current in 10-minute intervals on each phase.")
        b = self._row("B", "Voltage and current average profile",
                      "The meter shall record average voltage and current values in a 10-minute profile.")
        self.assertTrue(_similar_legacy(a, b))

    def test_unspecified_period_does_not_conflict(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("A", "Load profile recording", "The meter shall record the load profile in 15-minute intervals.")
        b = self._row("B", "Load profile recording", "The meter shall record the load profile.")
        self.assertTrue(_similar_legacy(a, b))

    def test_shared_title_object_phrase_merges_under_merge_pair(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("A", "Load profile behavior",
                      "The meter shall capture load-profile values at the configured integration period.")
        b = self._row("B", "Load profile storage",
                      "The meter shall store each load-profile entry with its timestamp and status.")
        self.assertTrue(_similar_legacy(a, b))

    def test_single_shared_word_does_not_merge(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("A", "Tamper detection", "The device shall detect removal of the terminal cover.",
                      module="机械结构")
        b = self._row("B", "Tamper event retention",
                      "The terminal-cover event shall be stored in the event log.",
                      module="机械结构")
        self.assertFalse(_similar_legacy(a, b))

    def test_cjk_shared_object_substring_merges(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("A", "事件记录与报警功能", module="事件记录")
        b = self._row("B", "事件记录最低存储数量", module="事件记录")
        self.assertTrue(_similar_legacy(a, b))

    def test_opposed_qualifiers_still_veto_object_phrase_merge(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("A", "Battery replacement", "The battery is replaceable.", module="机械结构")
        b = self._row("B", "Battery sealing", "The backup battery is non-replaceable.", module="机械结构")
        self.assertFalse(_similar_legacy(a, b))


class VariantGuardTests(unittest.TestCase):
    """变体护栏：同名但编号/制式不同的对象不因共享对象词组被误并
    （安全套件0×1、NB-IoT×LoRa——语义基线 semantic_v1 实证）。"""

    @staticmethod
    def _row(rid: str, title: str, module: str = "安全") -> dict:
        return {"ai_req_id": rid, "title": title, "description": title, "module": module}

    def test_numbered_variants_do_not_merge(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("AI-S0", "安全套件0支持")
        b = self._row("AI-S1", "安全套件1支持")
        self.assertFalse(_similar_legacy(a, b))

    def test_different_radio_technologies_do_not_merge(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("AI-NB", "NB-IoT远程通信要求", module="通信协议")
        b = self._row("AI-LORA", "LoRa远程通信要求", module="通信协议")
        self.assertFalse(_similar_legacy(a, b))

    def test_same_numbered_variant_still_merges_by_identity(self) -> None:
        from functional_catalog import _similar_legacy
        a = self._row("AI-S0", "安全套件0支持")
        b = self._row("AI-S0B", "安全套件0支持")
        self.assertTrue(_similar_legacy(a, b))
