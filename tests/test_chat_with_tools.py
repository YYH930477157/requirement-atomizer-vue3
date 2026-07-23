"""Agent Phase 2 WP1-A：chat_with_tools 有界 tool-loop 的契约测试。

Mock 沿用 tests/test_llm_client.py 的 MockOpenAIService（按序弹出响应体），此处仅补
tool_calls 响应构造助手——mock 本体零改动（它本就透传任意 body）。
"""
from __future__ import annotations

import json
import unittest
from typing import Any

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

    def test_same_tool_failing_twice_in_one_round_raises(self) -> None:
        """同一工具同一轮连续错 2 次 → 视为轮顶耗尽同等处理（抛 LLMResponseError）。"""
        responses = [
            {"body": tool_call_response([("c1", "ghost", {}), ("c2", "ghost", {})])},
        ]

        def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"error": f"unknown tool: {name}"}

        with MockOpenAIService(responses) as service:
            with self.assertRaisesRegex(LLMResponseError, "twice in a row"):
                chat_with_tools(
                    config_for(service), MESSAGES, FAKE_TOOLS, on_tool_call=executor)

        self.assertEqual(len(service.requests), 1)   # 立即失败,不再发请求

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
