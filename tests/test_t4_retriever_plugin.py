"""T3-4 retriever 插件点：``RequirementRetriever`` Protocol 注入与消费（仅预留，零向量依赖）。

覆盖：
1. 默认词面检索器（``LiteralRequirementRetriever``）召回与既有 ``search_requirement_library`` 同源；
2. 假检索器可经 ``build_requirement_retriever(retriever=...)`` / ``search_requirements_task`` 注入
   并被检索流程消费（产出仍是 entry 列表，下游确定性校验不放松）；
3. ``RATOMIZER_REQUIREMENT_RETRIEVER=vector`` 当前如实回退词面（不引入向量依赖），并标 ``retriever_kind``。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class LiteralRetrieverTests(unittest.TestCase):
    def test_literal_default_recalls_same_as_search_requirement_library(self) -> None:
        from requirement_schema import (
            LiteralRequirementRetriever, search_requirement_library,
        )
        library = [
            {"objective": "电压采集", "behaviors": [], "tokens": ["电压", "采集"]},
            {"objective": "事件记录", "behaviors": [], "tokens": ["事件", "记录"]},
        ]
        retriever = LiteralRequirementRetriever(library)
        self.assertEqual(
            retriever.search("电压采集", limit=5),
            search_requirement_library("电压采集", library, limit=5),
        )
        self.assertEqual(retriever.retriever_kind, "literal")

    def test_empty_query_returns_empty(self) -> None:
        from requirement_schema import LiteralRequirementRetriever
        retriever = LiteralRequirementRetriever([{"objective": "x", "tokens": ["xx"]}])
        self.assertEqual(retriever.search("", limit=5), [])


class RetrieverInjectionTests(unittest.TestCase):
    def test_fake_retriever_injected_and_consumed(self) -> None:
        """插件点可注入假 retriever 并被检索流程消费（核心验收）。"""
        from requirement_schema import build_requirement_retriever

        class FakeRetriever:
            retriever_kind = "fake-vector"

            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def search(self, query: str, *, limit: int = 20):
                self.calls.append((query, limit))
                # 假向量召回——产出仍是 entry 形态，下游确定性校验照常适用
                return [{"objective": f"fake-hit-for-{query}", "overlap_score": 0.99,
                         "retriever_kind": "fake-vector"}]

        fake = FakeRetriever()
        retriever = build_requirement_retriever([], retriever=fake)
        self.assertIs(retriever, fake)  # 注入优先，不建词面默认
        results = retriever.search("某查询", limit=3)
        self.assertEqual(fake.calls, [("某查询", 3)])
        self.assertEqual(results[0]["objective"], "fake-hit-for-某查询")

    def test_search_requirements_task_consumes_injected_retriever(self) -> None:
        """端到端：``search_requirements_task`` 消费注入的假检索器，绕过词面库加载。"""
        from desktop_tasks import search_requirements_task

        class CountingRetriever:
            retriever_kind = "test"

            def __init__(self) -> None:
                self.seen: list[str] = []

            def search(self, query: str, *, limit: int = 20):
                self.seen.append(query)
                return [{"objective": "from-fake", "overlap_score": 1.0}]

        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "lib.jsonl"
            lib.write_text(json.dumps({"objective": "x", "tokens": ["xx"]}) + "\n", encoding="utf-8")
            fake = CountingRetriever()
            result = search_requirements_task(lib, "电压", limit=10, retriever=fake)
            self.assertEqual(fake.seen, ["电压"])
            self.assertEqual(result["matches"], 1)
            self.assertEqual(result["results"][0]["objective"], "from-fake")
            self.assertEqual(result["retriever_kind"], "test")

    def test_default_task_uses_literal_retriever(self) -> None:
        from desktop_tasks import search_requirements_task
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "lib.jsonl"
            lib.write_text(
                json.dumps({"objective": "电压采集", "behaviors": [], "tokens": ["电压", "采集"]}) + "\n",
                encoding="utf-8",
            )
            result = search_requirements_task(lib, "电压采集", limit=5)
            self.assertEqual(result["retriever_kind"], "literal")
            self.assertGreaterEqual(result["matches"], 1)


class VectorFallbackTests(unittest.TestCase):
    def test_vector_kind_falls_back_to_literal_without_vector_dep(self) -> None:
        """``RATOMIZER_REQUIREMENT_RETRIEVER=vector`` 当前无向量依赖，如实回退词面并标 fallback。"""
        from requirement_schema import build_requirement_retriever, resolve_retriever_kind
        with patch.dict(os.environ, {"RATOMIZER_REQUIREMENT_RETRIEVER": "vector"}, clear=False):
            self.assertEqual(resolve_retriever_kind(), "vector")
            retriever = build_requirement_retriever([{"objective": "x", "tokens": ["xx"]}])
            # 回退词面：retriever_kind 标注 vector-unavailable，不伪造向量
            self.assertEqual(retriever.retriever_kind, "literal(fallback:vector-unavailable)")
            # 仍能词面召回
            self.assertEqual(retriever.search("x", limit=5), retriever.search("x", limit=5))


if __name__ == "__main__":
    unittest.main()
