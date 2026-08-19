from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import spec_enrich
from llm_client import LLMClientConfig


class _Handler(BaseHTTPRequestHandler):
    reply_description = "改写后的更丰富的描述。"
    status = 200
    calls = 0

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).calls += 1
        if self.status != 200:
            body = json.dumps({"error": {"message": "boom"}}).encode("utf-8")
            self.send_response(self.status)
        else:
            content = json.dumps({"description": self.reply_description})
            body = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # noqa: D401
        return


def start_server() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def make_config(port: int) -> LLMClientConfig:
    return LLMClientConfig(base_url=f"http://127.0.0.1:{port}/v1", model="mock", api_key_env="", max_retries=0)


def obj_req() -> dict:
    return {
        "id": "REQ-001", "title": "Clock (OBIS 0-0:1.0.0.255 / CL 8)",
        "description": "计量软件 SHALL 实现 COSEM 对象 Clock（OBIS 0-0:1.0.0.255，接口类 8），其属性按属性表实现。",
        "source_quote": "COSEM object Clock / CL 8 / OBIS 0-0:1.0.0.255 shall be defined.",
        "threshold_table": {"description": "Clock 属性访问表", "columns": ["#", "属性", "RC"],
                            "rows": [["1", "time", "R-"]]},
        "labels": ["时钟"], "priority": "P1", "type": "functional", "status": "confirmed",
        "acceptance_criteria": ["读取 logical_name 返回 OBIS 0-0:1.0.0.255"], "notes": "",
    }


class SpecEnrichTests(unittest.TestCase):
    def setUp(self) -> None:
        _Handler.reply_description = "Clock 对象用于管理日期时间，按属性表实现各关联访问权限。"
        _Handler.status = 200
        _Handler.calls = 0

    def test_enriches_and_freezes_structured_fields(self) -> None:
        server, port = start_server()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                req = obj_req()
                before = json.dumps({k: req[k] for k in ("source_quote", "threshold_table", "labels", "priority")},
                                    ensure_ascii=False, sort_keys=True)
                e, r, f = spec_enrich.enrich_descriptions([req], config=make_config(port),
                                                          cache_path=Path(tmp) / "c.jsonl")
                self.assertEqual((e, r, f), (1, 0, 0))
                self.assertIn("管理日期时间", req["description"])      # 已改写
                after = json.dumps({k: req[k] for k in ("source_quote", "threshold_table", "labels", "priority")},
                                   ensure_ascii=False, sort_keys=True)
                self.assertEqual(before, after)                         # 结构字段逐字冻结
                self.assertIn("富化", req["notes"])
        finally:
            server.shutdown()
            server.server_close()

    def test_cache_hit_second_run_zero_calls(self) -> None:
        server, port = start_server()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "c.jsonl"
                spec_enrich.enrich_descriptions([obj_req()], config=make_config(port), cache_path=cache)
                first = _Handler.calls
                spec_enrich.enrich_descriptions([obj_req()], config=make_config(port), cache_path=cache)
                self.assertEqual(_Handler.calls, first)                 # 二跑无新调用
        finally:
            server.shutdown()
            server.server_close()

    def test_cache_reader_repairs_interrupted_final_record(self) -> None:
        valid_row = {"fingerprint": "good", "description": "cached"}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "c.jsonl"
            valid_line = json.dumps(valid_row, ensure_ascii=False) + "\n"
            cache.write_text(valid_line + '{"fingerprint":', encoding="utf-8")

            with self.assertLogs("requirement_atomizer", level="WARNING"):
                rows = spec_enrich.read_cache(cache)

            self.assertEqual(rows, {"good": valid_row})
            self.assertEqual(cache.read_text(encoding="utf-8"), valid_line)

    def test_runner_path_writes_attempt_ledger_and_reraises(self) -> None:
        """M8 迁移：enrich_one 经 LLMJobRunner——账本在案；失败重抛原始异常类型。"""
        from llm_client import LLMError
        from llm_job_runner import LLM_JOB_ATTEMPTS_FILENAME, LLMJobRunner

        server, port = start_server()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                runner = LLMJobRunner(out, route_config=make_config(port))
                desc, note = spec_enrich.enrich_one(obj_req(), make_config(port), None,
                                                 runner=runner)
                self.assertIn("富化", note)
                ledger = out / LLM_JOB_ATTEMPTS_FILENAME
                self.assertTrue(ledger.is_file())
                rows = [json.loads(line) for line in
                        ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertEqual(rows[0]["stage"], "assemble")
                self.assertEqual(rows[0]["processor"], "spec_enrich")
                self.assertEqual(rows[0]["outcome"], "initial")
                self.assertEqual(rows[0]["execution_status"], "ok")
        finally:
            server.shutdown()
            server.server_close()

        # 失败重抛：不可达端点 → 原始 LLMConnectionError（熔断语义依赖的类型）
        from llm_client import LLMConnectionError

        with tempfile.TemporaryDirectory() as tmp:
            runner = LLMJobRunner(Path(tmp),
                                  route_config=LLMClientConfig(
                                      base_url="http://127.0.0.1:9/v1",
                                      model="m", api_key_env="RATOMIZER_TEST_KEY",
                                      timeout_s=1, max_retries=0))
            with self.assertRaises(LLMConnectionError):
                spec_enrich.enrich_one(obj_req(), make_config(1), None, runner=runner)

    def test_guards_version_invalidates_cache_and_is_recorded(self) -> None:
        server, port = start_server()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "c.jsonl"
                spec_enrich.enrich_descriptions([obj_req()], config=make_config(port), cache_path=cache)
                first_calls = _Handler.calls

                # M7 迁移后缓存行是 PaidCacheStore 形态（payload 嵌套）——经
                # read_cache 解包断言语义（guards_version 记录在案且参与指纹）
                first_row = next(iter(spec_enrich.read_cache(cache).values()))
                self.assertEqual(first_row["guards_version"], spec_enrich.ENRICH_GUARDS_VERSION)

                with patch.object(spec_enrich, "ENRICH_GUARDS_VERSION", "enrich-guards-vNEXT"):
                    spec_enrich.enrich_descriptions(
                        [obj_req()], config=make_config(port), cache_path=cache)

                self.assertGreater(_Handler.calls, first_calls)
                rows = spec_enrich.read_cache(cache)
                self.assertGreaterEqual(len(rows), 2)
                last_row = list(rows.values())[-1]
                self.assertEqual(last_row["guards_version"], "enrich-guards-vNEXT")
        finally:
            server.shutdown()
            server.server_close()

    def test_code_drift_rejected(self) -> None:
        _Handler.reply_description = "Clock 对象，参见 OBIS 1-1:99.9.9.255 与第 42 项。"  # 注入新 OBIS + 新数字
        server, port = start_server()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                req = obj_req()
                template = req["description"]
                e, r, f = spec_enrich.enrich_descriptions([req], config=make_config(port),
                                                          cache_path=Path(tmp) / "c.jsonl")
                self.assertEqual((e, r, f), (0, 1, 0))
                self.assertEqual(req["description"], template)          # 回退模板
                self.assertIn("漂移", req["notes"])
        finally:
            server.shutdown()
            server.server_close()

    def test_degradation_on_server_error(self) -> None:
        _Handler.status = 500
        server, port = start_server()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                req = obj_req()
                template = req["description"]
                e, r, f = spec_enrich.enrich_descriptions([req], config=make_config(port),
                                                          cache_path=Path(tmp) / "c.jsonl")
                self.assertEqual((e, r), (0, 0))
                self.assertGreaterEqual(f, 1)
                self.assertEqual(req["description"], template)          # 不崩、保留模板
        finally:
            server.shutdown()
            server.server_close()

    def test_stub_route_no_network_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            req = obj_req()
            template = req["description"]
            summary = spec_enrich.enrich_requirement_lists([[req]], out_dir=Path(tmp), route=None)
            self.assertEqual(summary["route"], "stub")
            self.assertEqual(req["description"], template)              # 默认 stub 不动

    def test_blue_book_hit_injects_clause_and_accepts_matching_citation(self) -> None:
        req = obj_req()
        req["class_id"] = "3"
        index = {
            "interface_classes": {
                "3": {
                    "name": "Register",
                    "section": "4.3.2",
                    "text": "Register value scaler_unit 77 selective access",
                }
            }
        }
        prompts: list[str] = []

        def fake_chat(config, system, user):
            prompts.append(user)
            return {
                "description": (
                    "Register 的 value 与 scaler_unit 行为按条款 77 实现；"
                    "依据 DLMS Blue Book Ed.16 §4.3.2。"
                )
            }

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            index_path = Path(tmp) / "blue_book_index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")

            enriched, rejected, failed = spec_enrich.enrich_descriptions(
                [req],
                config=make_config(1),
                cache_path=Path(tmp) / "c.jsonl",
                blue_book_index_path=index_path,
            )

        self.assertEqual((enriched, rejected, failed), (1, 0, 0))
        self.assertIn("条款 77", req["description"])
        self.assertIn("DLMS Blue Book Ed.16 §4.3.2", req["description"])
        self.assertIn("Register value scaler_unit 77 selective access", prompts[0])
        self.assertIn("§4.3.2", prompts[0])

    def test_blue_book_origin_survives_cache_hit(self) -> None:
        index = {
            "interface_classes": {
                "3": {
                    "name": "Register",
                    "section": "4.3.2",
                    "text": "Register value scaler_unit selective access",
                }
            }
        }
        calls = 0

        def fake_chat(config, system, user):
            nonlocal calls
            calls += 1
            return {"description": "Register 行为说明；依据 DLMS Blue Book Ed.16 §4.3.2。"}

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            root = Path(tmp)
            index_path = root / "blue_book_index.json"
            cache_path = root / "c.jsonl"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            first_req = obj_req()
            first_req["class_id"] = "3"
            second_req = obj_req()
            second_req["class_id"] = "3"

            spec_enrich.enrich_descriptions(
                [first_req], config=make_config(1), cache_path=cache_path,
                blue_book_index_path=index_path)
            first_calls = calls
            spec_enrich.enrich_descriptions(
                [second_req], config=make_config(1), cache_path=cache_path,
                blue_book_index_path=index_path)

        self.assertEqual(calls, first_calls)
        self.assertEqual(first_req.get("blue_book_origin"), "4.3.2")
        self.assertEqual(second_req.get("blue_book_origin"), "4.3.2")

    def test_blue_book_citation_mismatch_rejected_and_template_kept(self) -> None:
        req = obj_req()
        req["class_id"] = "3"
        index = {
            "interface_classes": {
                "3": {"name": "Register", "section": "4.3.2", "text": "Register clause text"}
            }
        }

        def fake_chat(config, system, user):
            return {"description": "引用了错误出处，依据 DLMS Blue Book Ed.16 §4.4.4。"}

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            index_path = Path(tmp) / "blue_book_index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            original = req["description"]

            enriched, rejected, failed = spec_enrich.enrich_descriptions(
                [req],
                config=make_config(1),
                cache_path=Path(tmp) / "c.jsonl",
                blue_book_index_path=index_path,
            )

        self.assertEqual((enriched, rejected, failed), (0, 1, 0))
        self.assertEqual(req["description"], original)
        self.assertIn("出处", req["notes"])

    def test_blue_book_name_fallback_resolves_entry(self) -> None:
        """真实 P3 行为 atom 没有 class_id、只有接口类名（object）——名称回退是真实数据的
        唯一命中路径（验收实测 class_id 0/180、名称 27/180）。大小写不敏感。"""
        req = obj_req()
        req.pop("class_id", None)
        req["interface_class_name"] = "extended REGISTER"   # casefold 匹配
        index = {
            "interface_classes": {
                "4": {"name": "Extended register", "section": "4.3.4",
                       "text": "Extended register value scaler_unit status capture_time"}
            }
        }
        prompts: list[str] = []

        def fake_chat(config, system, user):
            prompts.append(user)
            return {"description": "行为叙述。依据 DLMS Blue Book Ed.16 §4.3.4。"}

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            index_path = Path(tmp) / "blue_book_index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            enriched, rejected, failed = spec_enrich.enrich_descriptions(
                [req], config=make_config(1), cache_path=Path(tmp) / "c.jsonl",
                blue_book_index_path=index_path)

        self.assertEqual((enriched, rejected, failed), (1, 0, 0))
        self.assertIn("Extended register value scaler_unit", prompts[0])   # 条款注入了

    def test_blue_book_missing_citation_auto_appended(self) -> None:
        """出处必带（红线 4）：模型漏写出处时程序化补写正确节号——注入节号我们确知，
        比信任模型可靠。错误节号仍由 citation_mismatch 拒绝。"""
        req = obj_req()
        req["class_id"] = "3"
        index = {
            "interface_classes": {
                "3": {"name": "Register", "section": "4.3.2", "text": "Register clause text"}
            }
        }

        def fake_chat(config, system, user):
            return {"description": "行为叙述但模型忘了写出处。"}

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            index_path = Path(tmp) / "blue_book_index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            enriched, rejected, failed = spec_enrich.enrich_descriptions(
                [req], config=make_config(1), cache_path=Path(tmp) / "c.jsonl",
                blue_book_index_path=index_path)

        self.assertEqual((enriched, rejected, failed), (1, 0, 0))
        self.assertIn("依据 DLMS Blue Book Ed.16 §4.3.2", req["description"])   # 程序化补写

    def test_blue_book_clause_numbers_extend_drift_baseline_but_unrelated_obis_is_rejected(self) -> None:
        req = obj_req()
        req["class_id"] = "3"
        index = {
            "interface_classes": {
                "3": {
                    "name": "Register",
                    "section": "4.3.2",
                    "text": "Register clause permits value 77 and scaler_unit. No OBIS appears here.",
                }
            }
        }

        replies = iter([
            {"description": "Register 行为允许条款中的 77；依据 DLMS Blue Book Ed.16 §4.3.2。"},
            {"description": "Register 行为新增 OBIS 1-1:99.9.9.255；依据 DLMS Blue Book Ed.16 §4.3.2。"},
        ])

        def fake_chat(config, system, user):
            return next(replies)

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            index_path = Path(tmp) / "blue_book_index.json"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            first = dict(req)
            second = dict(req)
            enriched, rejected, failed = spec_enrich.enrich_descriptions(
                [first, second],
                config=make_config(1),
                cache_path=Path(tmp) / "c.jsonl",
                blue_book_index_path=index_path,
            )

        self.assertEqual((enriched, rejected, failed), (1, 1, 0))
        self.assertIn("77", first["description"])
        self.assertEqual(second["description"], req["description"])
        self.assertIn("漂移", second["notes"])

    def test_blue_book_path_absent_does_not_load_or_change_fingerprint(self) -> None:
        req = obj_req()
        req["class_id"] = "3"
        fp_without = spec_enrich.fingerprint(req, "mock")
        fp_missing = spec_enrich.fingerprint(req, "mock", blue_book_entry=None)

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.blue_book_lookup.lookup_class") as lookup:
            server, port = start_server()
            try:
                spec_enrich.enrich_descriptions(
                    [req],
                    config=make_config(port),
                    cache_path=Path(tmp) / "c.jsonl",
                    blue_book_index_path=None,
                )
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(fp_without, fp_missing)
        lookup.assert_not_called()


class BatchSlotRetryTests(unittest.TestCase):
    """FIX 2（2026-08-14）：合批缺槽不再在批任务内串行单条回退——_enrich_batch_unit 把
    缺槽交还编排器,由其以独立单条任务重发到同一线程池（护栏/_finalize_description 不变）。"""

    def _plain_reqs(self, count: int) -> list[dict]:
        return [dict(obj_req(), id=f"REQ-{i}", title=f"条目{i}",
                     description=f"第 {i} 条描述：记录事件并按属性表实现。",
                     source_quote=f"record events {i}") for i in range(count)]

    def test_batch_unit_returns_missing_slots_without_in_task_fallback(self) -> None:
        unit = [(req, f"fp-{i}", None) for i, req in enumerate(self._plain_reqs(3))]
        calls: list[str] = []

        def fake_chat(config, system, user):
            calls.append(system)
            return {"items": [{"enrich_slot": 0, "description": "改写后的第一条描述。"}]}

        with patch("spec_enrich.chat_json", side_effect=fake_chat):
            outcomes, missing = spec_enrich._enrich_batch_unit(unit, make_config(1))

        self.assertEqual(len(calls), 1)                     # 批任务内不再补单条调用
        self.assertEqual(missing, [1, 2])                   # 缺槽交还编排器
        self.assertIsNotNone(outcomes[0])
        self.assertEqual(outcomes[1:], [None, None])        # 占位——等编排器重试回填
        self.assertIn("富化", outcomes[0][1])                # 槽 0 照常过护栏

    def test_missing_slots_retried_as_independent_singles_end_to_end(self) -> None:
        reqs = self._plain_reqs(4)
        batch_calls: list[str] = []
        single_calls: list[str] = []

        def fake_chat(config, system, user):
            if system == spec_enrich.SYSTEM_PROMPT_BATCH:
                batch_calls.append(user)
                return {"items": [{"enrich_slot": 0, "description": "改写后的第一条描述。"}]}
            single_calls.append(user)
            slot_title = json.loads(user)["title"]          # 单条 prompt 是紧凑 payload JSON
            return {"description": f"{slot_title} 的单条补齐描述。"}

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            cache = Path(tmp) / "c.jsonl"
            enriched, rejected, failed = spec_enrich.enrich_descriptions(
                reqs, config=make_config(1), cache_path=cache)
            rows = [json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines()]

        self.assertEqual((enriched, rejected, failed), (4, 0, 0))
        self.assertEqual(len(batch_calls), 1)
        self.assertEqual(len(single_calls), 3)              # 只有缺的 3 条走单条重试
        self.assertIn("单条补齐描述", reqs[3]["description"])
        self.assertEqual(len(rows), 4)                      # 全部成功进缓存


class FastFailProbeTests(unittest.TestCase):
    """FIX 4：快速失败探测从 5 降到 2——全连不上时只烧 2 个样本即整体降级（失败路径不变）。"""

    def test_all_unreachable_aborts_after_two_probes(self) -> None:
        from llm_client import LLMConnectionError
        reqs = [dict(obj_req(), id=f"REQ-{i}") for i in range(6)]
        calls: list[str] = []

        def fake_chat(config, system, user):
            calls.append(user)
            raise LLMConnectionError("connection refused")

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            with self.assertLogs("requirement_atomizer", level="WARNING") as logs:
                enriched, rejected, failed = spec_enrich.enrich_descriptions(
                    reqs, config=make_config(1), cache_path=Path(tmp) / "c.jsonl")

        self.assertEqual((enriched, rejected), (0, 0))
        self.assertEqual(failed, 6)                         # 2 探测失败 + 其余 4 计失败
        self.assertEqual(len(calls), 2)                     # 只烧 2 个样本
        self.assertTrue(any("服务不可达" in line for line in logs.output))

    def test_first_probe_reachable_still_enriches_rest(self) -> None:
        """失败路径不变：探测有任一成功即进入并发阶段,其余条目正常富化。"""
        reqs = [dict(obj_req(), id=f"REQ-{i}") for i in range(4)]

        def fake_chat(config, system, user):
            return {"description": "改写后的描述。"}

        with tempfile.TemporaryDirectory() as tmp, patch("spec_enrich.chat_json", side_effect=fake_chat):
            enriched, rejected, failed = spec_enrich.enrich_descriptions(
                reqs, config=make_config(1), cache_path=Path(tmp) / "c.jsonl")

        self.assertEqual((enriched, rejected, failed), (4, 0, 0))


class BatchPromptCompactTests(unittest.TestCase):
    """FIX 5：合批 user prompt 紧凑 JSON（无缩进换行）——token 成本下降,版本 v4 轮换缓存键。"""

    def test_batch_user_prompt_is_compact(self) -> None:
        prompt = spec_enrich._build_batch_user_prompt([obj_req()])
        self.assertNotIn("\n", prompt)                      # 无排版换行/缩进
        self.assertIn('"enrich_slot":0', prompt)            # 紧凑分隔符（键后无空格）

    def test_enrich_prompt_version_bumped_with_prompt_shape(self) -> None:
        self.assertEqual(spec_enrich.ENRICH_PROMPT_VERSION, "enrich-v4")


if __name__ == "__main__":
    unittest.main()
