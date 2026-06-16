from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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

    def test_stub_route_no_network_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            req = obj_req()
            template = req["description"]
            summary = spec_enrich.enrich_requirement_lists([[req]], out_dir=Path(tmp), route=None)
            self.assertEqual(summary["route"], "stub")
            self.assertEqual(req["description"], template)              # 默认 stub 不动


if __name__ == "__main__":
    unittest.main()
