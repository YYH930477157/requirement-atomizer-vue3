"""审计 P1-d：审查 KB 透传 + 工具证据内容指纹进缓存。

缺陷两条：① desktop run 把 --kb 传给 atomize 却不传给 review——工具执行器落回默认 KB，
"需求按客户 KB 匹配、审查拿默认 KB 复核"；② 审查缓存指纹与阶段指纹都不含工具实际
读取的证据内容（KB/blocks.jsonl/atomic_requirements.jsonl/蓝皮书索引）——改证据后
旧审查被静默复用。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 允许 tests.test_* 直跑时解析同级测试模块

import review_tools
from llm_pipeline import effective_review_scope, llm_cache_key, load_review_pipeline, run_review_pipeline
from review_tools import _evidence_payload, evidence_fingerprint

from test_chat_with_tools import final_json_response, tool_call_response
from test_llm_pipeline_routes import ScriptedOpenAIService, requirement
from test_tool_loop_review import seed_out, write_tool_loop_pipeline_config


def _kb_file(root: Path, *, entry_id: str = "custom_entry", name: str = "Zqxwcustomterm") -> Path:
    kb = root / "kb.json"
    kb.write_text(json.dumps({
        "kb_id": "test_kb",
        "entries": [
            {"id": entry_id, "name": name, "type": "term", "layer": "term",
             "definition": f"definition of {name}", "keywords": [name.lower()]},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return kb


def _final_accept() -> dict:
    return {"body": final_json_response(
        {"decision": "accept", "risk": "low_risk", "confidence": 0.9,
         "review_notes": [], "expert_questions": []})}


class EvidenceFingerprintTests(unittest.TestCase):
    def test_kb_content_change_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            seed_out(out, [requirement("SREQ-00000000000000E1", confidence=0.70)])
            kb = _kb_file(root)

            first = evidence_fingerprint(out, [kb])
            again = evidence_fingerprint(out, [kb])
            kb.write_text(kb.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            changed = evidence_fingerprint(out, [kb])

        self.assertEqual(first, again)          # 确定性聚合
        self.assertNotEqual(first, changed)     # 改 KB 内容 → 指纹变

    def test_blocks_and_requirements_change_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            seed_out(out, [requirement("SREQ-00000000000000E2", confidence=0.70)])
            kb = _kb_file(root)

            first = evidence_fingerprint(out, [kb])
            with (out / "blocks.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"block_id": "B9", "text": "extra"}) + "\n")
            blocks_changed = evidence_fingerprint(out, [kb])
            with (out / "atomic_requirements.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"stable_req_id": "SREQ-X"}) + "\n")
            requirements_changed = evidence_fingerprint(out, [kb])

        self.assertNotEqual(first, blocks_changed)
        self.assertNotEqual(blocks_changed, requirements_changed)

    def test_missing_blue_book_index_is_recorded_as_none(self) -> None:
        """缺蓝皮书索引时指纹如实含 none（不猜、不跳过该维度）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            seed_out(out, [requirement("SREQ-00000000000000E3", confidence=0.70)])
            fake_pkg = root / "pkg"
            fake_pkg.mkdir()   # 隔离仓库 out/bluebook 的自动探测
            env = dict(os.environ)
            env.pop(review_tools.BLUE_BOOK_INDEX_ENV, None)
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("resources.package_root", return_value=fake_pkg):
                    payload = _evidence_payload(out, [])

        self.assertEqual(payload["blue_book_index"], {"path": None, "sha256": None})

    def test_blue_book_index_content_joins_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            seed_out(out, [requirement("SREQ-00000000000000E4", confidence=0.70)])
            kb = _kb_file(root)
            fake_pkg = root / "pkg"
            fake_pkg.mkdir()
            env = dict(os.environ)
            env.pop(review_tools.BLUE_BOOK_INDEX_ENV, None)
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("resources.package_root", return_value=fake_pkg):
                    before = evidence_fingerprint(out, [kb])
                    (out / "blue_book_index.json").write_text(
                        '{"interface_classes": {}}', encoding="utf-8")
                    after = evidence_fingerprint(out, [kb])
                    payload = _evidence_payload(out, [kb])

        self.assertNotEqual(before, after)
        self.assertTrue(payload["blue_book_index"]["sha256"])

    def test_llm_cache_key_carries_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pipeline_path = Path(td) / "tool.yaml"
            write_tool_loop_pipeline_config(pipeline_path, "http://127.0.0.1:9/v1")
            pipeline = load_review_pipeline(pipeline_path)
            row = requirement("SREQ-00000000000000E5", confidence=0.70)
            scope = effective_review_scope(pipeline, "targeted")

            base = llm_cache_key(row, "mock-review-model", pipeline, scope, evidence="fp-a")
            changed = llm_cache_key(row, "mock-review-model", pipeline, scope, evidence="fp-b")

        self.assertNotEqual(base, changed)
        self.assertEqual(base[:3], changed[:3])   # 只有 input_fingerprint 维度变


class KbPassThroughTests(unittest.TestCase):
    def test_explicit_kb_paths_reach_tool_executor(self) -> None:
        """审查工具按显式 kb_paths 取证——模型 kb_search 命中的是传入 KB 而非默认 KB。"""
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"query": "Zqxwcustomterm"})])},
            _final_accept(),
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            seed_out(out, [requirement("SREQ-00000000000000E6", confidence=0.70)])
            kb = _kb_file(root)
            pipeline_path = root / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses.pop(0)) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible", kb_paths=[kb])

        self.assertEqual(summary["llm_reviewed"], 1)
        tool_msgs = [m for m in service.requests[1]["messages"] if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        content = json.loads(tool_msgs[0]["content"])
        self.assertEqual(content["results"][0]["entry_id"], "custom_entry")
        # 汇总如实记录本次实际使用的 KB（审计 P1-d③）
        self.assertEqual(summary["kb_paths"], [str(kb)])

    def test_default_kb_paths_resolve_to_actual_defaults(self) -> None:
        """kb_paths=None 时按工具执行器同一回退解析默认 KB——汇总记录的是真实路径而非 None。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            seed_out(out, [requirement("SREQ-00000000000000E7", confidence=0.70)])
            kb = _kb_file(root)
            pipeline_path = root / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: _final_accept()) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                with mock.patch(
                    "requirement_kb.cli.default_kb_paths", return_value=[kb]
                ) as default_kb_paths:
                    summary = run_review_pipeline(
                        out, pipeline_path=pipeline_path, domain_pack_path=None,
                        route="openai_compatible", kb_paths=None)

        self.assertEqual(summary["llm_reviewed"], 1)
        default_kb_paths.assert_called()
        self.assertEqual(summary["kb_paths"], [str(kb)])

    def test_kb_content_change_invalidates_review_cache(self) -> None:
        """改 KB 文件内容 → 缓存 key 变 → 重新调用（改证据后旧审查不得静默复用）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            seed_out(out, [requirement("SREQ-00000000000000E8", confidence=0.70)])
            kb = _kb_file(root)
            pipeline_path = root / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: _final_accept()) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                first = run_review_pipeline(
                    out, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible", kb_paths=[kb])
                second = run_review_pipeline(
                    out, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible", kb_paths=[kb])
                requests_after_warm_cache = len(service.requests)
                kb.write_text(kb.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                third = run_review_pipeline(
                    out, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible", kb_paths=[kb])

        self.assertEqual(first["llm_reviewed"], 1)
        self.assertEqual(second["llm_reviewed"], 1)
        self.assertEqual(requests_after_warm_cache, 1)   # 证据未变：二跑全缓存命中
        self.assertEqual(third["llm_reviewed"], 1)
        self.assertEqual(len(service.requests), 2)       # KB 内容变：缓存失效重审


if __name__ == "__main__":
    unittest.main()
