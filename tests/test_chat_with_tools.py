"""Agent Phase 2 WP1-A：chat_with_tools 有界 tool-loop 的契约测试。

Mock 沿用 tests/test_llm_client.py 的 MockOpenAIService（按序弹出响应体），此处仅补
tool_calls 响应构造助手——mock 本体零改动（它本就透传任意 body）。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 允许 tests.test_* 直跑时解析同级测试模块

from llm_client import LLMClientConfig, LLMResponseError, chat_with_tools
from test_llm_client import MockOpenAIService


def final_json_response(payload: dict[str, Any], usage: dict[str, int] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "choices": [{
            "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
            "finish_reason": "stop",
        }]
    }
    if usage:
        body["usage"] = usage
    return body


def tool_call_response(
    calls: list[tuple[str, str, dict[str, Any]]],
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """构造一轮 tool_calls 响应：calls = [(tool_call_id, name, arguments_dict), ...]。"""
    body: dict[str, Any] = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                    }
                    for call_id, name, arguments in calls
                ],
            },
            "finish_reason": "tool_calls",
        }]
    }
    if usage:
        body["usage"] = usage
    return body


def config_for(service: MockOpenAIService, **overrides: Any) -> LLMClientConfig:
    values: dict[str, Any] = dict(
        base_url=service.base_url, model="mock-model", api_key_env="", timeout_s=2, max_retries=0)
    values.update(overrides)
    return LLMClientConfig(**values)


MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
FAKE_TOOLS = [{
    "type": "function",
    "function": {
        "name": "kb_search",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
}]


class RecordingExecutor:
    """on_tool_call 测试替身：记录调用并按需返回结果/异常。"""

    def __init__(self, results: dict[str, Any] | None = None, fail_with: Exception | None = None):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = results or {}
        self.fail_with = fail_with

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        if self.fail_with is not None:
            raise self.fail_with
        result = self.results.get(tool_name, {"ok": True, "tool": tool_name})
        return result


class ChatWithToolsTests(unittest.TestCase):
    def test_direct_json_answer_single_round(self) -> None:
        """无 tool_calls 的首轮直接按 chat_json 同口径解析最终 JSON。"""
        executor = RecordingExecutor()
        with MockOpenAIService([{"body": final_json_response({"decision": "accept", "confidence": 0.9})}]) as service:
            final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(final["decision"], "accept")
        self.assertEqual(meta["rounds"], 1)
        self.assertEqual(meta["tool_calls"], [])
        self.assertEqual(executor.calls, [])
        self.assertEqual(service.requests[0]["tools"], FAKE_TOOLS)   # tools schema 透传
        self.assertNotIn("response_format", service.requests[0])     # 工具轮不强制 json_object

    def test_multi_round_tool_loop_feeds_results_back(self) -> None:
        """工具轮：逐个回调、结果以 role=tool 回灌（tool_call_id 逐字对应）、下轮收敛。"""
        executor = RecordingExecutor({"kb_search": {"results": [{"entry_id": "e1"}]}})
        responses = [
            {"body": tool_call_response([("call_1", "kb_search", {"query": "Register"})])},
            {"body": final_json_response({"decision": "revise", "confidence": 0.7})},
        ]
        with MockOpenAIService(responses) as service:
            final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(final["decision"], "revise")
        self.assertEqual(executor.calls, [("kb_search", {"query": "Register"})])
        self.assertEqual(meta["tool_calls"], [{"round": 1, "name": "kb_search"}])
        self.assertEqual(meta["rounds"], 2)
        second_messages = service.requests[1]["messages"]
        # assistant 工具轮原样回灌 + role=tool 结果消息
        assistant_tool_msg = second_messages[-2]
        self.assertEqual(assistant_tool_msg["role"], "assistant")
        self.assertEqual(assistant_tool_msg["tool_calls"][0]["id"], "call_1")
        tool_msg = second_messages[-1]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertEqual(tool_msg["tool_call_id"], "call_1")
        self.assertEqual(json.loads(tool_msg["content"]), {"results": [{"entry_id": "e1"}]})

    def test_round_cap_exhaustion_raises(self) -> None:
        """模型连续请求工具超过轮顶 → LLMResponseError（调用方进 stub,不伪造已审）。"""
        executor = RecordingExecutor()
        responses = [{"body": tool_call_response([(f"c{i}", "kb_search", {"query": "x"})])} for i in range(3)]
        with MockOpenAIService(responses) as service:
            with self.assertRaisesRegex(LLMResponseError, "max_rounds"):
                chat_with_tools(
                    config_for(service), MESSAGES, FAKE_TOOLS, max_rounds=3, on_tool_call=executor)

        self.assertEqual(len(service.requests), 3)   # 恰打满轮顶,不多发

    def test_unknown_tool_error_fed_back_once_then_converge(self) -> None:
        """未知工具名 → {"error": ...} 回灌一次让模型纠正；下轮给最终 JSON 即收敛。"""
        executor = RecordingExecutor()   # 回调自身不判未知——由调用方（review_tools）返回 error
        responses = [
            {"body": tool_call_response([("c1", "kb_delete", {"query": "x"})])},
            {"body": final_json_response({"ok": True})},
        ]

        def strict_executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            if name != "kb_search":
                return {"error": f"unknown tool: {name}"}
            return {"ok": True}

        with MockOpenAIService(responses) as service:
            final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=strict_executor)

        self.assertEqual(final, {"ok": True})
        tool_msg = service.requests[1]["messages"][-1]
        self.assertEqual(tool_msg["role"], "tool")
        self.assertIn("unknown tool", json.loads(tool_msg["content"])["error"])
        self.assertEqual(meta["tool_calls"], [{"round": 1, "name": "kb_delete"}])

    def test_same_tool_failing_twice_bans_tool_instead_of_aborting(self) -> None:
        """同一工具连续错 2 次 → 不再中止整条 tool-loop（旧路径把已付费轮次整体丢弃）：
        该工具从后续请求的 tools 面移除、该次调用回灌最终错误消息指示直接产出最终 JSON；
        模型下轮收敛则完整保留此前取证上下文。"""
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"query": "x"}),
                                         ("c2", "kb_search", {"query": "y"})])},
            {"body": final_json_response({"ok": True})},
        ]
        fail_count = {"n": 0}

        def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            fail_count["n"] += 1
            return {"error": f"unknown block_id: {args}"}

        with MockOpenAIService(responses) as service:
            final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(final, {"ok": True})               # 收敛：付费轮次未丢弃
        self.assertEqual(fail_count["n"], 2)                # 恰执行两次（第二次后禁用）
        self.assertEqual(len(service.requests), 2)
        # 禁用后 tools 面为空 → 请求不再携带 tools 键（端点不会再看到已禁用工具）
        self.assertNotIn("tools", service.requests[1])
        # 首次错误回灌仍是原始错误（provenance 如实）；第二次是最终处置消息
        first_tool_msg = service.requests[1]["messages"][3]
        self.assertIn("unknown block_id", json.loads(first_tool_msg["content"])["error"])
        second_tool_msg = service.requests[1]["messages"][4]
        error_text = json.loads(second_tool_msg["content"])["error"]
        self.assertIn("unavailable", error_text)
        self.assertIn("final JSON", error_text)
        # 审计摘要如实记录两次调用
        self.assertEqual(meta["tool_calls"], [{"round": 1, "name": "kb_search"}] * 2)

    def test_banned_tool_keeps_remaining_tools_and_is_not_executed_again(self) -> None:
        """多工具面下禁用只移除肇事工具；此后模型再点名它 → 不执行,直接回灌不可用消息。"""
        two_tools = [FAKE_TOOLS[0], {
            "type": "function",
            "function": {
                "name": "source_read",
                "parameters": {"type": "object", "properties": {"block_id": {"type": "string"}}},
            },
        }]
        responses = [
            # 第 1 轮：source_read 连续两次 error → 禁用；kb_search 成功不受影响
            {"body": tool_call_response([("c1", "source_read", {"block_id": "BAD"}),
                                         ("c2", "source_read", {"block_id": "WORSE"}),
                                         ("c3", "kb_search", {"query": "Register"})])},
            # 第 2 轮：模型仍点名已禁用的 source_read → 不执行；最终收敛
            {"body": tool_call_response([("c4", "source_read", {"block_id": "BAD"})])},
            {"body": final_json_response({"ok": True})},
        ]
        calls: list[tuple[str, dict[str, Any]]] = []

        def executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            calls.append((name, arguments))
            if name == "source_read":
                return {"error": f"unknown block_id: {arguments.get('block_id')}"}
            return {"results": []}

        with MockOpenAIService(responses) as service:
            final, _meta = chat_with_tools(
                config_for(service), MESSAGES, two_tools, on_tool_call=executor)

        self.assertEqual(final, {"ok": True})
        self.assertEqual([name for name, _ in calls], ["source_read", "source_read", "kb_search"])
        # 禁用后第 2 轮请求的 tools 面只剩 kb_search
        self.assertEqual(
            [tool["function"]["name"] for tool in service.requests[1]["tools"]], ["kb_search"])
        # 已禁用工具的再次点名：不执行,回灌不可用消息
        banned_msg = service.requests[2]["messages"][-1]
        self.assertIn("unavailable", json.loads(banned_msg["content"])["error"])

    def test_meta_exposes_final_banned_tools_for_carry(self) -> None:
        """meta.banned_tools 外传终态禁用集——续接轮（schema 修复）据此携带主环禁用状态。"""
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"query": "x"}),
                                         ("c2", "kb_search", {"query": "y"})])},
            {"body": final_json_response({"ok": True})},
        ]

        def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"error": "boom"}

        with MockOpenAIService(responses) as service:
            _final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(meta["banned_tools"], ["kb_search"])

    def test_initial_banned_tools_seed_carried_from_outer_loop(self) -> None:
        """initial_banned_tools 预置禁用集（外环续接）：首轮请求 tools 面即不含该工具；
        模型再点名不执行,直接回灌不可用处置消息——不浪费付费轮重新试错。"""
        two_tools = [FAKE_TOOLS[0], {
            "type": "function",
            "function": {
                "name": "source_read",
                "parameters": {"type": "object", "properties": {"block_id": {"type": "string"}}},
            },
        }]
        responses = [
            {"body": tool_call_response([("c1", "source_read", {"block_id": "BAD"})])},
            {"body": final_json_response({"ok": True})},
        ]
        calls: list[str] = []

        def executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            calls.append(name)
            return {"results": []}

        with MockOpenAIService(responses) as service:
            final, meta = chat_with_tools(
                config_for(service), MESSAGES, two_tools,
                on_tool_call=executor, initial_banned_tools={"source_read"})

        self.assertEqual(final, {"ok": True})
        self.assertEqual(calls, [])   # 续接禁用：再点名也不执行
        # 首轮请求 tools 面已不含续接禁用的工具（端点从第一轮就看不到它）
        self.assertEqual(
            [tool["function"]["name"] for tool in service.requests[0]["tools"]], ["kb_search"])
        banned_msg = service.requests[1]["messages"][-1]
        self.assertEqual(banned_msg["role"], "tool")
        error_text = json.loads(banned_msg["content"])["error"]
        self.assertIn("unavailable", error_text)
        self.assertIn("final JSON", error_text)
        # 终态禁用集仍随 meta 外传（供后续续接轮继续携带）
        self.assertEqual(meta["banned_tools"], ["source_read"])

    def test_consecutive_errors_across_rounds_also_ban(self) -> None:
        """跨轮连续同工具错误同样禁用（第 1 轮错、第 2 轮再错 → 禁用并继续）。"""
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"query": "x"})])},
            {"body": tool_call_response([("c2", "kb_search", {"query": "y"})])},
            {"body": final_json_response({"ok": True})},
        ]

        def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"error": "boom"}

        with MockOpenAIService(responses) as service:
            final, _meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(final, {"ok": True})
        self.assertNotIn("tools", service.requests[2])   # 第 3 轮请求已无 tools 面

    def test_error_then_success_resets_streak(self) -> None:
        """错→成→错 不构成连续两次：不禁用,循环照常收敛。"""
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"query": "x"})])},
            {"body": tool_call_response([("c2", "kb_search", {"query": "y"})])},
            {"body": tool_call_response([("c3", "kb_search", {"query": "z"})])},
            {"body": final_json_response({"ok": True})},
        ]
        outcomes = ["error", "ok", "error"]
        calls = {"n": 0}

        def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            outcome = outcomes[calls["n"]]
            calls["n"] += 1
            return {"error": "transient"} if outcome == "error" else {"results": []}

        with MockOpenAIService(responses) as service:
            final, _meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(final, {"ok": True})
        self.assertEqual(calls["n"], 3)
        self.assertEqual(service.requests[3]["tools"], FAKE_TOOLS)   # 未禁用

    def test_never_converging_after_ban_still_raises_at_round_cap(self) -> None:
        """禁用后模型仍不产出最终 JSON → 轮顶耗尽照旧抛 LLMResponseError
        （调用方进 stub 记数,绝不把失败伪装成已审）。"""
        responses = [{"body": tool_call_response([(f"c{i}", "kb_search", {"query": "x"})])}
                     for i in range(3)]
        with MockOpenAIService(responses) as service:
            with self.assertRaisesRegex(LLMResponseError, "max_rounds"):
                chat_with_tools(
                    config_for(service), MESSAGES, FAKE_TOOLS, max_rounds=3,
                    on_tool_call=RecordingExecutor(fail_with=RuntimeError("down")))
        self.assertEqual(len(service.requests), 3)

    def test_hard_provider_error_mid_loop_still_raises_loudly(self) -> None:
        """传输/服务层硬错误（连接失败）不做工具禁用兜底——原样上抛（provenance 红线：
        失败不得被吞成"模型已收敛"）。"""
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"query": "x"})])},
            {"status": 500, "body": {"error": "provider down"}},
        ]
        from llm_client import LLMConnectionError
        with MockOpenAIService(responses) as service:
            with self.assertRaises(LLMConnectionError):
                chat_with_tools(
                    config_for(service), MESSAGES, FAKE_TOOLS,
                    on_tool_call=RecordingExecutor())

    def test_tool_execution_exception_becomes_error_result(self) -> None:
        """工具执行异常 → {"error": ...} 回灌（不炸穿循环）；下轮模型收敛。"""
        executor = RecordingExecutor(fail_with=RuntimeError("kb file missing"))
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"query": "x"})])},
            {"body": final_json_response({"ok": True})},
        ]
        with MockOpenAIService(responses) as service:
            final, _meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(final, {"ok": True})
        tool_msg = service.requests[1]["messages"][-1]
        self.assertIn("kb file missing", json.loads(tool_msg["content"])["error"])

    def test_malformed_tool_call_structure_fed_back_as_error(self) -> None:
        """tool_call 结构畸形（缺 function）→ 不调回调,直接 error 回灌。"""
        executor = RecordingExecutor()
        malformed = {"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function"}],   # 缺 function 对象
        }, "finish_reason": "tool_calls"}]}
        with MockOpenAIService([{"body": malformed}, {"body": final_json_response({"ok": 1})}]) as service:
            final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(final, {"ok": 1})
        self.assertEqual(executor.calls, [])   # 畸形调用不触达回调
        tool_msg = service.requests[1]["messages"][-1]
        self.assertIn("malformed tool_call", json.loads(tool_msg["content"])["error"])
        self.assertEqual(meta["tool_calls"][0]["name"], "<malformed>")

    def test_bad_arguments_json_fed_back_as_error(self) -> None:
        """arguments 不是合法 JSON → error 回灌；模型下轮修好参数收敛。"""
        executor = RecordingExecutor()
        bad_args = {"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "kb_search", "arguments": "{not json"}}],
        }, "finish_reason": "tool_calls"}]}
        with MockOpenAIService([{"body": bad_args}, {"body": final_json_response({"ok": 2})}]) as service:
            final, _meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(final, {"ok": 2})
        self.assertEqual(executor.calls, [])
        tool_msg = service.requests[1]["messages"][-1]
        self.assertIn("invalid tool arguments JSON", json.loads(tool_msg["content"])["error"])

    def test_4xx_tools_unsupported_is_loud_error(self) -> None:
        """端点不支持 tools（4xx）→ 响亮报错点名 tools 语境,不静默降级为无工具重发。"""
        responses = [{"status": 400, "body": {"error": {"message": "tools is not supported"}}}]
        with MockOpenAIService(responses) as service:
            with self.assertRaisesRegex(LLMResponseError, "tool-calling request"):
                chat_with_tools(
                    config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=RecordingExecutor())

        self.assertEqual(len(service.requests), 1)   # 不重试、不降级重发

    def test_usage_aggregated_across_tool_and_final_rounds(self) -> None:
        """usage 汇聚全部轮次（首发+工具轮+最终轮）——同 chat_json_with_meta 口径。"""
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"q": "x"})],
                                        usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})},
            {"body": final_json_response({"ok": True},
                                         usage={"prompt_tokens": 14, "completion_tokens": 3, "total_tokens": 17})},
        ]
        with MockOpenAIService(responses) as service:
            _final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=RecordingExecutor())

        self.assertEqual(meta["usage"], {"prompt_tokens": 24, "completion_tokens": 5, "total_tokens": 29})
        self.assertTrue(meta["usage_complete"])

    def test_missing_usage_counts_zero_and_marks_partial(self) -> None:
        """端点不返回 usage → 计 0 且 usage_complete=False（不得估算冒充精确值）。"""
        with MockOpenAIService([{"body": final_json_response({"ok": True})}]) as service:
            _final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=RecordingExecutor())

        self.assertEqual(meta["usage"]["total_tokens"], 0)
        self.assertFalse(meta["usage_complete"])

    def test_token_budget_exceeded_raises(self) -> None:
        """每需求 tokens 上限：累计 usage 超预算即抛（该需求进 stub 记数）。"""
        responses = [
            {"body": tool_call_response([("c1", "kb_search", {"q": "x"})],
                                        usage={"prompt_tokens": 90, "completion_tokens": 20, "total_tokens": 110})},
        ]
        with MockOpenAIService(responses) as service:
            with self.assertRaisesRegex(LLMResponseError, "token budget exceeded"):
                chat_with_tools(
                    config_for(service), MESSAGES, FAKE_TOOLS,
                    on_tool_call=RecordingExecutor(), token_budget=100)

        self.assertEqual(len(service.requests), 1)   # 超限即中止,不再发下一轮

    def test_final_json_repair_round_converges(self) -> None:
        """最终轮非法 JSON → 修复重发一次（占一轮）,与 chat_json 同口径。"""
        responses = [
            {"body": {"choices": [{"message": {"role": "assistant", "content": "not json"},
                                   "finish_reason": "stop"}]}},
            {"body": final_json_response({"decision": "accept"})},
        ]
        with MockOpenAIService(responses) as service:
            final, meta = chat_with_tools(
                config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=RecordingExecutor())

        self.assertEqual(final["decision"], "accept")
        self.assertEqual(len(service.requests), 2)
        self.assertIn("Only output valid JSON", service.requests[1]["messages"][-1]["content"])
        self.assertEqual(meta["rounds"], 2)

    def test_final_json_invalid_at_round_cap_raises(self) -> None:
        """最后一轮仍非法 JSON 且轮顶已尽 → LLMResponseError。"""
        responses = [
            {"body": {"choices": [{"message": {"role": "assistant", "content": "not json"},
                                   "finish_reason": "stop"}]}},
        ]
        with MockOpenAIService(responses) as service:
            with self.assertRaisesRegex(LLMResponseError, "not valid JSON"):
                chat_with_tools(
                    config_for(service), MESSAGES, FAKE_TOOLS, max_rounds=1,
                    on_tool_call=RecordingExecutor())

    def test_tool_round_truncation_escalates_max_tokens(self) -> None:
        """工具轮 finish_reason=length → max_tokens 倍升重试（同单发截断升级策略）。"""
        truncated = {"choices": [{"message": {"role": "assistant", "content": '{"partial}'},
                                  "finish_reason": "length"}]}
        responses = [{"body": truncated}, {"body": final_json_response({"ok": True})}]
        with MockOpenAIService(responses) as service:
            final, _meta = chat_with_tools(
                config_for(service, max_tokens=100), MESSAGES, FAKE_TOOLS,
                on_tool_call=RecordingExecutor())

        self.assertEqual(final, {"ok": True})
        self.assertEqual(service.requests[0]["max_tokens"], 100)
        self.assertEqual(service.requests[1]["max_tokens"], 200)


if __name__ == "__main__":
    unittest.main()
