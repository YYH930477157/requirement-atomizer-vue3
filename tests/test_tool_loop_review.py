"""Agent Phase 2 WP1-C：operations executor 处置 + tool-loop 融合审查的端到端契约。

冻结点：tool_loop 只改变产出审查字段的过程，字段语义/确定性政策层/下游契约
（decision 枚举、状态机映射、缓存指纹纪律、stub 逐字不动）完全不变。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from llm_pipeline import (
    PROMPT_VERSION,
    REVIEW_TOOLS_VERSION,
    llm_cache_key,
    load_review_pipeline,
    operation_executor_map,
    read_jsonl,
    run_review_pipeline,
    tool_loop_enabled,
)
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))  # 同上：直跑兼容

from test_llm_pipeline_routes import (
    ScriptedOpenAIService,
    openai_review,
    requirement,
    write_jsonl,
    write_pipeline_config,
)
from test_chat_with_tools import final_json_response, tool_call_response


ROOT = Path(__file__).resolve().parents[1]


def write_tool_loop_pipeline_config(path: Path, base_url: str) -> None:
    """带 operations executor 声明的审查 yaml（classify_risk/correct_errors=tool_loop）。"""
    write_pipeline_config(path, base_url)
    text = path.read_text(encoding="utf-8")
    operations = """
operations:
  - operation_id: "classify_risk"
    executor: "tool_loop"
  - operation_id: "correct_errors"
    executor: "tool_loop"
  - operation_id: "merge_duplicates"
    executor: "deterministic"
  - operation_id: "gap_find"
    executor: "deterministic"
  - operation_id: "test_point_generate"
    executor: "deferred"
"""
    path.write_text(text + operations, encoding="utf-8")


def write_budget_tool_loop_pipeline_config(path: Path, base_url: str, budget: int) -> None:
    """带每需求 tokens 上限（route.tool_loop_token_budget）的 tool-loop 审查 yaml。"""
    write_tool_loop_pipeline_config(path, base_url)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "    concurrency: 2",
        f"    concurrency: 2\n    tool_loop_token_budget: {budget}",
    )
    path.write_text(text, encoding="utf-8")


def seed_out(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "atomic_requirements.jsonl", rows)
    write_jsonl(out_dir / "blocks.jsonl", [
        {"block_id": "B1", "order": 1, "type": "paragraph", "noise": False,
         "text": "The meter shall be reviewed.", "section_path": ["1"]},
    ])


class OperationExecutorMapTests(unittest.TestCase):
    def test_default_yaml_executors_match_frozen_disposition(self) -> None:
        """仓库 yaml 的 executor 处置 = 冻结表（tool_loop×2/deterministic×2/deferred×1）。"""
        pipeline = load_review_pipeline(ROOT / "llm_agents" / "review_pipeline.yaml")
        self.assertEqual(
            operation_executor_map(pipeline),
            {
                "classify_risk": "tool_loop",
                "correct_errors": "tool_loop",
                "merge_duplicates": "deterministic",
                "gap_find": "deterministic",
                "test_point_generate": "deferred",
            },
        )
        self.assertTrue(tool_loop_enabled(pipeline))

    def test_legacy_yaml_without_executor_stays_single_shot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pipeline_path = Path(tmp) / "review_pipeline.yaml"
            write_pipeline_config(pipeline_path, "http://127.0.0.1:9/v1")
            pipeline = load_review_pipeline(pipeline_path)
        self.assertEqual(operation_executor_map(pipeline), {})
        self.assertFalse(tool_loop_enabled(pipeline))


class ToolLoopReviewEndToEndTests(unittest.TestCase):
    def test_user_prompt_injects_only_top_three_trimmed_kb_definitions(self) -> None:
        from llm_pipeline import build_user_prompt

        row = {
            "stable_req_id": "SREQ-KB",
            "requirement": "Review KB evidence.",
            "kb_matches": [
                {"name": f"entry-{index}", "definition": str(index) * 500}
                for index in range(5)
            ],
        }

        payload = json.loads(build_user_prompt(row))

        self.assertEqual(len(payload["kb_matches"]), 3)
        self.assertEqual([item["name"] for item in payload["kb_matches"]], ["entry-0", "entry-1", "entry-2"])
        self.assertTrue(all(len(item["definition"]) <= 300 for item in payload["kb_matches"]))

    def test_kb_search_executes_at_most_once_per_requirement(self) -> None:
        from llm_pipeline import build_openai_review_tool_loop
        from test_chat_with_tools import config_for

        pipeline = load_review_pipeline(ROOT / "llm_agents" / "review_pipeline.yaml")
        calls: list[tuple[str, dict]] = []

        def executor(name: str, arguments: dict) -> dict:
            calls.append((name, arguments))
            return {"results": []}

        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"query": "Register"})])},
            {"body": tool_call_response([("c2", "kb_search", {"query": "Tariff"})])},
            {"body": final_json_response({
                "decision": "accept", "risk": "low_risk", "confidence": 0.9,
                "revised_requirement": "The meter shall store data.",
                "review_notes": [], "expert_questions": [],
            })},
        ]
        from test_llm_client import MockOpenAIService
        with MockOpenAIService(responses) as service:
            build_openai_review_tool_loop(
                {"stable_req_id": "SREQ-1", "req_id": "AREQ-1", "requirement": "The meter shall store data.",
                 "requirement_type": "data_definition", "confidence": 0.9},
                pipeline,
                config_for(service),
                tool_executor=executor,
            )

        self.assertEqual([name for name, _args in calls], ["kb_search"])

    def test_default_review_tool_loop_is_capped_at_five_rounds(self) -> None:
        from llm_pipeline import REVIEW_TOOL_LOOP_MAX_ROUNDS

        pipeline = load_review_pipeline(ROOT / "llm_agents" / "review_pipeline.yaml")
        route = pipeline.model_routes["openai_compatible"]
        self.assertEqual(REVIEW_TOOL_LOOP_MAX_ROUNDS, 5)
        self.assertEqual(route["tool_loop_max_rounds"], 5)

    def test_tool_loop_review_passes_schema_and_keeps_contract(self) -> None:
        """工具化融合审查：模型取证后裁决——输出契约/decision/状态机映射不变，
        结果行附 tool_calls 摘要（审计可解释性锚）。"""
        responses = [
            {"body": tool_call_response([("c1", "source_read", {"block_id": "B1"})],
                                        usage={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6})},
            {"body": final_json_response(
                {"decision": "accept", "risk": "low_risk", "confidence": 0.9,
                 "review_notes": ["evidence checked"], "expert_questions": []},
                usage={"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11})},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000T1", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses.pop(0)) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")

            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")
            states = read_jsonl(out_dir / "review_states.jsonl")

        self.assertEqual(summary["llm_reviewed"], 1)
        self.assertEqual(summary["llm_failed"], 0)
        review = reviews[0]
        self.assertEqual(review["decision"], "accept")
        self.assertEqual(review["generated_by"], "llm:mock-review-model")
        self.assertEqual(review["tool_calls"], [{"round": 1, "name": "source_read"}])
        # 下游契约锁：任务/身份/引文字段语义不变
        self.assertEqual(review["task_id"], "REVIEW-SREQ-00000000000000T1")
        self.assertEqual(review["source_refs"], ["SRC-00T1"])
        self.assertEqual(states[0]["status"], "accepted")
        # 第二轮请求携带 role=tool 的工具结果（证据回灌真实发生）
        self.assertEqual(len(service.requests), 2)
        tool_msgs = [m for m in service.requests[1]["messages"] if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_call_id"], "c1")

    def test_deterministic_policy_layer_still_applies_after_tool_loop(self) -> None:
        """确定性政策层照旧：mandatory_review 类型即使模型 accept 也强制 needs_expert。"""
        responses = [
            {"body": final_json_response(
                {"decision": "accept", "risk": "low_risk", "confidence": 0.95,
                 "review_notes": [], "expert_questions": []})},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            row = requirement("SREQ-00000000000000T2", confidence=0.70,
                              requirement_type="security_policy_bit")  # yaml high_risk_types
            seed_out(out_dir, [row])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses.pop(0)) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path,
                    domain_pack_path=ROOT / "domain_packs" / "dlms_cosem" / "pack.yaml",
                    route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(reviews[0]["risk"], "high_risk")
        self.assertEqual(reviews[0]["decision"], "accept")   # high_risk 不强制（只 mandatory 强制）

    def test_round_cap_exhaustion_falls_to_stub_honestly(self) -> None:
        """轮顶耗尽 → 该需求进 stub 并记数；stub 绝不冒充 tool-using 审查（provenance）。"""
        responses = [
            {"body": tool_call_response([("c1", "source_read", {"block_id": "B1"})])},
        ] * 5   # 模型 5 轮都只要工具（审查轮顶 5）
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000T3", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses[count - 1]) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_failed"], 1)
        self.assertEqual(summary["rule_stub"], 1)
        self.assertEqual(summary["llm_reviewed"], 0)
        review = reviews[0]
        self.assertEqual(review["generated_by"], "rule_stub")
        self.assertNotIn("tool_calls", review)   # stub 行无 tool-loop 痕迹（不冒充）
        self.assertTrue(any("llm_unavailable" in note for note in review["review_notes"]))
        self.assertEqual(len(service.requests), 5)   # 恰打满审查轮顶

    def test_token_budget_exceeded_falls_to_stub(self) -> None:
        """每需求 tokens 上限（默认 20000）：超限进 stub 并记数。"""
        responses = [
            {"body": tool_call_response([("c1", "source_read", {"block_id": "B1"})],
                                        usage={"prompt_tokens": 20001, "completion_tokens": 1,
                                               "total_tokens": 20002})},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000T4", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses[0]) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_failed"], 1)
        self.assertEqual(reviews[0]["generated_by"], "rule_stub")
        self.assertTrue(any("token budget" in note for note in reviews[0]["review_notes"]))

    def test_tools_unsupported_4xx_falls_to_stub_with_loud_note(self) -> None:
        """端点不支持 tools（4xx）→ 响亮报错进 stub（notes 点名 tool-calling），不静默无工具降级。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000T5", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(
                    lambda body, count: {"status": 400, "body": {"error": "tools unsupported"}}) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_failed"], 1)
        self.assertEqual(reviews[0]["generated_by"], "rule_stub")
        self.assertTrue(any("tool-calling request" in note for note in reviews[0]["review_notes"]))

    def test_tool_loop_cache_hit_skips_second_run(self) -> None:
        """审查缓存按输入指纹命中（含 REVIEW_TOOLS_VERSION/执行器模式）：二跑零请求。"""
        responses = [
            {"body": final_json_response(
                {"decision": "accept", "risk": "low_risk", "confidence": 0.9,
                 "review_notes": [], "expert_questions": []})},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000T6", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses.pop(0)) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                first = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")
                second = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(first["llm_reviewed"], 1)
        self.assertEqual(second["llm_reviewed"], 1)
        self.assertEqual(len(service.requests), 1)   # 二跑全缓存命中
        self.assertIn("tool_calls", reviews[0])      # 缓存行保留 tool_calls 摘要（可解释性）

    def test_legacy_yaml_keeps_single_shot_without_tools_payload(self) -> None:
        """旧 yaml（无 executor 声明）→ 单发融合审查：请求不带 tools，行为与 Phase 2 前一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000T7", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: {"body": openai_review()}) as service:
                write_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_reviewed"], 1)
        self.assertNotIn("tools", service.requests[0])
        self.assertNotIn("tool_calls", reviews[0])


class CacheFingerprintTests(unittest.TestCase):
    def test_cache_key_covers_tools_version_and_executor_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            legacy_path = tmp_path / "legacy.yaml"
            write_pipeline_config(legacy_path, "http://127.0.0.1:9/v1")
            tool_path = tmp_path / "tool.yaml"
            write_tool_loop_pipeline_config(tool_path, "http://127.0.0.1:9/v1")
            legacy = load_review_pipeline(legacy_path)
            tool_loop = load_review_pipeline(tool_path)
            row = requirement("SREQ-00000000000000T8", confidence=0.70)
            from llm_pipeline import effective_review_scope
            legacy_scope = effective_review_scope(legacy, "targeted")
            tool_scope = effective_review_scope(tool_loop, "targeted")

            legacy_key = llm_cache_key(row, "mock-review-model", legacy, legacy_scope)
            tool_key = llm_cache_key(row, "mock-review-model", tool_loop, tool_scope)

        self.assertNotEqual(legacy_key, tool_key)   # 执行器模式进指纹（single_shot vs tool_loop）
        self.assertEqual(legacy_key[2], PROMPT_VERSION)
        self.assertEqual(tool_key[2], PROMPT_VERSION)

    def test_review_tools_version_change_invalidates_fingerprint(self) -> None:
        """REVIEW_TOOLS_VERSION 在指纹载荷中——工具定义变更（bump 后）旧缓存必然失效。"""
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            pipeline_path = Path(tmp) / "tool.yaml"
            write_tool_loop_pipeline_config(pipeline_path, "http://127.0.0.1:9/v1")
            pipeline = load_review_pipeline(pipeline_path)
            row = requirement("SREQ-00000000000000T9", confidence=0.70)
            from llm_pipeline import effective_review_scope
            scope = effective_review_scope(pipeline, "targeted")
            key = llm_cache_key(row, "mock-review-model", pipeline, scope)

        self.assertTrue(all(key))
        # 指纹对 REVIEW_TOOLS_VERSION 敏感：替换版本常量重算必不同
        import llm_pipeline
        original = llm_pipeline.REVIEW_TOOLS_VERSION
        try:
            llm_pipeline.REVIEW_TOOLS_VERSION = "review-tools-v0-hypothetical"
            changed = llm_cache_key(row, "mock-review-model", pipeline, scope)
        finally:
            llm_pipeline.REVIEW_TOOLS_VERSION = original
        self.assertNotEqual(key, changed)
        self.assertEqual(original, REVIEW_TOOLS_VERSION)
        self.assertIsInstance(hashlib.sha256(key[3].encode()).hexdigest(), str)   # key 可用


class SchemaRepairBudgetTests(unittest.TestCase):
    """审计 P1-c：schema 修复调用与 tool-loop 首轮共享 usage/预算——修复不再免费放行。"""

    def test_schema_repair_over_budget_falls_to_stub(self) -> None:
        """首轮恰好花满预算 + 修复调用超 1 token → 抛错进 stub 记数（修复真实发出且被计量）。"""
        responses = [
            {"body": final_json_response(
                {"decision": "bogus-decision", "risk": "low_risk", "confidence": 0.9,
                 "review_notes": [], "expert_questions": []},
                usage={"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100})},
            {"body": final_json_response(
                {"decision": "accept", "risk": "low_risk", "confidence": 0.9,
                 "review_notes": [], "expert_questions": []},
                usage={"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1})},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000R1", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses.pop(0)) as service:
                write_budget_tool_loop_pipeline_config(pipeline_path, service.base_url, 100)
                summary = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_failed"], 1)
        self.assertEqual(summary["llm_reviewed"], 0)
        self.assertEqual(reviews[0]["generated_by"], "rule_stub")
        notes = " ".join(reviews[0]["review_notes"])
        self.assertIn("token budget", notes)
        self.assertIn("101 > 100", notes)   # 修复调用的 1 token 已计入聚合
        self.assertEqual(len(service.requests), 2)   # 恰花满仍放行修复，但超支即抛

    def test_schema_repair_within_budget_converges_and_is_counted(self) -> None:
        """修复后仍不超预算 → 正常收敛；usage 日志聚合含修复调用（99+1=100）。"""
        responses = [
            {"body": final_json_response(
                {"decision": "bogus-decision", "risk": "low_risk", "confidence": 0.9,
                 "review_notes": [], "expert_questions": []},
                usage={"prompt_tokens": 90, "completion_tokens": 9, "total_tokens": 99})},
            {"body": final_json_response(
                {"decision": "accept", "risk": "low_risk", "confidence": 0.9,
                 "review_notes": [], "expert_questions": []},
                usage={"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1})},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000R2", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses.pop(0)) as service:
                write_budget_tool_loop_pipeline_config(pipeline_path, service.base_url, 100)
                with self.assertLogs("requirement_atomizer", level="INFO") as logs:
                    summary = run_review_pipeline(
                        out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                        route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_reviewed"], 1)
        self.assertEqual(summary["llm_failed"], 0)
        self.assertEqual(reviews[0]["decision"], "accept")
        self.assertEqual(reviews[0]["generated_by"], "llm:mock-review-model")
        self.assertEqual(len(service.requests), 2)
        self.assertTrue(any("tokens=100" in message for message in logs.output))


class SchemaRepairTranscriptTests(unittest.TestCase):
    """审计 H5：schema 修复续接原 transcript（含 role=tool 取证回灌），不再另起四消息列表。"""

    def test_schema_repair_continues_transcript_with_tool_context(self) -> None:
        """取证轮后 schema 校验失败 → 修复请求携带完整 transcript（assistant tool_calls
        与 role=tool 结果俱在）且仍带 tools；修复轮轮次预算为首轮剩余。"""
        responses = [
            {"body": tool_call_response([("c1", "source_read", {"block_id": "B1"})],
                                        usage={"prompt_tokens": 5, "completion_tokens": 1,
                                               "total_tokens": 6})},
            {"body": final_json_response(
                {"decision": "bogus-decision", "risk": "low_risk", "confidence": 0.9,
                 "review_notes": [], "expert_questions": []},
                usage={"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11})},
            {"body": final_json_response(
                {"decision": "accept", "risk": "low_risk", "confidence": 0.9,
                 "review_notes": [], "expert_questions": []},
                usage={"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4})},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            seed_out(out_dir, [requirement("SREQ-00000000000000R3", confidence=0.70)])
            pipeline_path = tmp_path / "review_pipeline.yaml"
            with ScriptedOpenAIService(lambda body, count: responses.pop(0)) as service:
                write_tool_loop_pipeline_config(pipeline_path, service.base_url)
                summary = run_review_pipeline(
                    out_dir, pipeline_path=pipeline_path, domain_pack_path=None,
                    route="openai_compatible")
            reviews = read_jsonl(out_dir / "llm_review_results.jsonl")

        self.assertEqual(summary["llm_reviewed"], 1)
        self.assertEqual(summary["llm_failed"], 0)
        self.assertEqual(reviews[0]["decision"], "accept")
        self.assertEqual(reviews[0]["generated_by"], "llm:mock-review-model")
        self.assertEqual(len(service.requests), 3)   # 取证轮 + 产出轮 + 续接修复轮
        repair_request = service.requests[2]
        # 修复请求 = 原 transcript 续接：role=tool 的取证结果回灌仍在（修复前不丢上下文）
        tool_msgs = [m for m in repair_request["messages"] if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_call_id"], "c1")
        self.assertIn("tools", repair_request)   # 修复轮仍带 tools，模型可继续取证
        # 尾部 = 首轮产出的 assistant JSON + 修复指令（与环内 JSON 修复同型）
        self.assertEqual(repair_request["messages"][-2]["role"], "assistant")
        self.assertIn("bogus-decision", repair_request["messages"][-2]["content"])
        self.assertIn("schema validation failed", repair_request["messages"][-1]["content"])
        # 首轮取证仍如实进 tool_calls 审计摘要
        self.assertEqual(reviews[0]["tool_calls"], [{"round": 1, "name": "source_read"}])


if __name__ == "__main__":
    unittest.main()
