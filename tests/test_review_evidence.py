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
from llm_pipeline import (
    LLM_REVIEW_CACHE_VERSION,
    effective_review_scope,
    llm_cache_key,
    llm_cache_row,
    load_review_pipeline,
    run_review_pipeline,
)
from review_tools import _evidence_payload, evidence_fingerprint, evidence_fingerprint_parts

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


class PerRequirementEvidenceScopingTests(unittest.TestCase):
    """FIX 4（2026-08-14）：证据指纹按需求行切分——改一条需求不再全文档失效审查缓存。

    切分：稳定部分（KB/blocks/蓝皮书索引——只在管线轮次间变化,审查编辑期间不动）进
    每条缓存 key；需求自身整行 hash 进 key（覆盖 prompt 未携带的行字段,如
    review_questions）；coverage_check 读取全文档聚合 → 缓存行 evidence_deps 记录写入
    时的 atomic_requirements 整文件 sha256,命中校验失配即失效（宁失效不陈旧）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"
        self.row_a = requirement("SREQ-00000000000000C1", confidence=0.70)
        self.row_b = requirement("SREQ-00000000000000C2", confidence=0.70)
        seed_out(self.out, [self.row_a, self.row_b])
        self.kb = _kb_file(self.root)
        self.pipeline_path = self.root / "review_pipeline.yaml"
        write_tool_loop_pipeline_config(self.pipeline_path, "http://127.0.0.1:9/v1")
        self.pipeline = load_review_pipeline(self.pipeline_path)
        self.scope = effective_review_scope(self.pipeline, "targeted")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_parts_split_stable_vs_requirements(self) -> None:
        first = evidence_fingerprint_parts(self.out, [self.kb])
        whole_before = evidence_fingerprint(self.out, [self.kb])
        # 改 atomic_requirements：稳定部分不动（审查编辑不失效 KB/blocks/蓝皮书指纹）,
        # atomic 整文件 hash 变化
        rows = [self.row_a, {**self.row_b, "requirement": "edited requirement text."}]
        write_jsonl_out(self.out, rows)
        after_edit = evidence_fingerprint_parts(self.out, [self.kb])
        whole_after = evidence_fingerprint(self.out, [self.kb])

        self.assertEqual(first["stable_fingerprint"], after_edit["stable_fingerprint"])
        self.assertNotEqual(first["atomic_requirements_sha256"],
                            after_edit["atomic_requirements_sha256"])
        # 整证据指纹（旧口径,desktop 阶段戳继续使用）保持对 atomic 变化敏感
        self.assertNotEqual(whole_before, whole_after)
        # 稳定成员变化（blocks）→ 稳定指纹变
        with (self.out / "blocks.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"block_id": "B99", "text": "extra"}) + "\n")
        after_blocks = evidence_fingerprint_parts(self.out, [self.kb])
        self.assertNotEqual(after_edit["stable_fingerprint"], after_blocks["stable_fingerprint"])

    def test_llm_cache_key_carries_own_row_hash(self) -> None:
        """行内 prompt 未携带的字段（review_questions）变化 → key 变（旧口径靠全文档
        指纹兜底,新口径必须由自身行 hash 覆盖——不得陈旧）。批路径键同口径。"""
        from llm_pipeline import llm_cache_key_batch

        base = llm_cache_key(self.row_a, "m", self.pipeline, self.scope)
        changed_row = {**self.row_a, "review_questions": ["new question from expert"]}
        # 自身行变化即使 prompt 不含该字段也换 key
        self.assertNotEqual(base, llm_cache_key(changed_row, "m", self.pipeline, self.scope))
        # 他人行变化不换 key（按需求行切分的核心收益）
        other_changed_scope = self.scope
        self.assertEqual(base, llm_cache_key(self.row_a, "m", self.pipeline, other_changed_scope))

        batch_base = llm_cache_key_batch(
            self.row_a, "m", self.pipeline, self.scope,
            batch_member_ids={self.row_a["stable_req_id"], self.row_b["stable_req_id"]},
            batch_config=4, evidence="")
        self.assertNotEqual(batch_base, llm_cache_key_batch(
            changed_row, "m", self.pipeline, self.scope,
            batch_member_ids={self.row_a["stable_req_id"], self.row_b["stable_req_id"]},
            batch_config=4, evidence=""))

    def test_llm_cache_row_records_evidence_deps(self) -> None:
        review_plain = {"decision": "accept", "tool_calls": [{"round": 1, "name": "source_read"}]}
        row = llm_cache_row(self.row_a, "m", self.pipeline, self.scope, review_plain,
                            evidence="fp", atomic_requirements_sha256="sha-1")
        self.assertFalse(row["evidence_deps"]["coverage_check_used"])
        self.assertEqual(row["evidence_deps"]["atomic_requirements_sha256"], "sha-1")

        review_coverage = {"decision": "accept",
                           "tool_calls": [{"round": 1, "name": "coverage_check"}]}
        row = llm_cache_row(self.row_a, "m", self.pipeline, self.scope, review_coverage,
                            evidence="fp", atomic_requirements_sha256="sha-1")
        self.assertTrue(row["evidence_deps"]["coverage_check_used"])

    def test_cache_version_bumped_for_scoping(self) -> None:
        """切分改变 key 构成与行形状——版本必须随行（旧缓存行一次性失效,声明过可接受）。"""
        self.assertEqual(LLM_REVIEW_CACHE_VERSION, "llm-review-cache-v7")


def write_jsonl_out(out_dir: Path, rows: list[dict]) -> None:
    (out_dir / "atomic_requirements.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class ReviewCacheScopingEndToEndTests(unittest.TestCase):
    """端到端：编辑一条需求行,只有该行与 coverage_check 依赖行重审,其余缓存命中。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "out"
        self.row_a = requirement("SREQ-00000000000000D1", confidence=0.70)
        self.row_b = requirement("SREQ-00000000000000D2", confidence=0.70)
        seed_out(self.out, [self.row_a, self.row_b])
        self.kb = _kb_file(self.root)
        self.pipeline_path = self.root / "review_pipeline.yaml"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _scripted_service(self, plans: dict[str, list[dict]]) -> "ScriptedOpenAIService":
        """按请求中的 requirement_id 派发脚本（plans: rid → 该需求每次收到请求时按序
        返回的响应）。计划耗尽时返回最终收敛响应——让请求计数断言（而非连接崩溃）
        暴露"缓存未命中/意外重审"类行为差异。"""
        counts: dict[str, int] = {rid: 0 for rid in plans}

        def handler(body: dict, count: int) -> dict:
            content = str(body["messages"][1]["content"])
            for rid, plan in plans.items():
                if rid in content:
                    n = counts[rid]
                    counts[rid] = n + 1
                    return plan[n] if n < len(plan) else _final_accept()
            raise AssertionError(f"unexpected request: {content[:120]}")

        return ScriptedOpenAIService(handler)

    def _plans_for(self, tool_name: str | None, *, with_arg: dict | None = None,
                   only_for: str | None = None,
                   rounds: dict[str, int] | None = None) -> dict[str, list[dict]]:
        """plans: rid → 响应序列。rounds[rid] 指定该需求预期被完整审查的次数（默认 1）,
        每次审查 = 可选工具轮 + 最终收敛轮;跨 run 的重审按序续排在同一序列里。"""
        rounds = rounds or {}
        plans: dict[str, list[dict]] = {}
        for row in (self.row_a, self.row_b):
            rid = row["stable_req_id"]
            queue: list[dict] = []
            for _ in range(max(1, rounds.get(rid, 1))):
                if tool_name is not None and (only_for is None or only_for == rid):
                    queue.append({"body": tool_call_response(
                        [(f"{rid}-c{len(queue)}", tool_name, with_arg or {"x": 1})])})
                queue.append(_final_accept())
            plans[rid] = queue
        return plans

    def test_editing_other_requirement_keeps_non_coverage_cache(self) -> None:
        # B 预期被完整重审（run1 + run2 各一轮工具轮+收敛轮）;A 仅 run1
        plans = self._plans_for("source_read", with_arg={"block_id": "B1"},
                                rounds={self.row_a["stable_req_id"]: 1,
                                        self.row_b["stable_req_id"]: 2})
        with self._scripted_service(plans) as service:
            write_tool_loop_pipeline_config(self.pipeline_path, service.base_url)
            first = run_review_pipeline(
                self.out, pipeline_path=self.pipeline_path, domain_pack_path=None,
                route="openai_compatible", kb_paths=[self.kb])
            requests_after_first = len(service.requests)
            # 编辑 B 行（A 行逐字节不动）
            write_jsonl_out(self.out, [self.row_a, {**self.row_b, "requirement": "Edited B text."}])
            second = run_review_pipeline(
                self.out, pipeline_path=self.pipeline_path, domain_pack_path=None,
                route="openai_compatible", kb_paths=[self.kb])

        self.assertEqual(first["llm_reviewed"], 2)
        self.assertEqual(requests_after_first, 4)          # A、B 各两轮（工具轮+收敛轮）
        self.assertEqual(second["llm_reviewed"], 2)
        # A 的缓存命中（未重审）：只重付 B 的两轮
        self.assertEqual(len(service.requests), 6)

    def test_coverage_check_cache_invalidated_by_other_requirement_edit(self) -> None:
        """coverage_check 返回全文档聚合 → 任何需求行变化都使其证据陈旧,缓存必须失效。"""
        plans = self._plans_for(
            "coverage_check",
            with_arg={"requirement_id": self.row_a["stable_req_id"]},
            only_for=self.row_a["stable_req_id"],   # B 不调工具（区分两类依赖）
            # A run1 完整审查 + run2 因 B 行编辑而 coverage 证据失配重审;B run1+run2 各一轮
            rounds={self.row_a["stable_req_id"]: 2, self.row_b["stable_req_id"]: 2},
        )
        with self._scripted_service(plans) as service:
            write_tool_loop_pipeline_config(self.pipeline_path, service.base_url)
            first = run_review_pipeline(
                self.out, pipeline_path=self.pipeline_path, domain_pack_path=None,
                route="openai_compatible", kb_paths=[self.kb])
            requests_after_first = len(service.requests)
            write_jsonl_out(self.out, [self.row_a, {**self.row_b, "requirement": "Edited B text."}])
            second = run_review_pipeline(
                self.out, pipeline_path=self.pipeline_path, domain_pack_path=None,
                route="openai_compatible", kb_paths=[self.kb])

        self.assertEqual(first["llm_reviewed"], 2)
        self.assertEqual(requests_after_first, 3)          # A 两轮 + B 一轮
        self.assertEqual(second["llm_reviewed"], 2)
        # B 行变化 → B 重审（1 轮）且 A 的 coverage_check 行失效重审（2 轮）
        self.assertEqual(len(service.requests), 6)

    def test_own_row_edit_invalidates_own_cache_only(self) -> None:
        plans = self._plans_for(None)
        with self._scripted_service(plans) as service:
            write_tool_loop_pipeline_config(self.pipeline_path, service.base_url)
            run_review_pipeline(
                self.out, pipeline_path=self.pipeline_path, domain_pack_path=None,
                route="openai_compatible", kb_paths=[self.kb])
            write_jsonl_out(self.out, [{**self.row_a, "requirement": "Edited A text."}, self.row_b])
            run_review_pipeline(
                self.out, pipeline_path=self.pipeline_path, domain_pack_path=None,
                route="openai_compatible", kb_paths=[self.kb])

        self.assertEqual(len(service.requests), 3)          # A 重审,B 缓存命中


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
