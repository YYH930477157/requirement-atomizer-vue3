"""双渲染器契约（F6，Python 侧）：自包含 HTML 的批注标记必须符合共享夹具的契约。

同一语义在 DocumentReview.vue 与 doc_annotation_export.py 各实现一遍（高亮 bug 修过两遍）。
契约夹具 tests/fixtures/annotation_contract.json 由两侧共用：本测试锁 HTML 侧静态结构，
vitest AnnotationContract.spec 锁 Vue 侧渲染与选中行为——任一侧漂移即红。
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import doc_annotation_export as dae

FIXTURE = Path(__file__).parent / "fixtures" / "annotation_contract.json"


class HtmlSideContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _render(self) -> str:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with (tmp / "blocks.jsonl").open("w", encoding="utf-8", newline="\n") as f:
                for b in self.fixture["blocks"]:
                    f.write(json.dumps(b, ensure_ascii=False) + "\n")
            with (tmp / "ai_requirements.jsonl").open("w", encoding="utf-8", newline="\n") as f:
                for r in self.fixture["requirements"]:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            return dae.render_annotation_html(tmp)

    def test_parent_numbers_and_sub_chips_match_contract(self) -> None:
        html = self._render()
        expect = self.fixture["expect"]
        parent_numbers = re.findall(
            r'<button class="chip annotation-index" [^>]*>.*?<span class="annotation-number">(\d+)</span>',
            html)
        self.assertEqual(parent_numbers, expect["parent_numbers"])
        sub_labels = re.findall(
            r'<button class="chip annotation-index sub" [^>]*>.*?<span class="annotation-number">([^<]+)</span>',
            html)
        self.assertEqual(sub_labels, expect["sub_chip_labels"])

    def test_select_behavior_matches_contract_via_jsdom_markers(self) -> None:
        """静态可断言的部分：markSpan 的选择器素材必须在（span 的 doc-block[data-block-id]
        与 sub chip 的 data-req）——运行时行为由既有 jsdom 冒烟覆盖。"""
        html = self._render()
        for bid in ("B1", "B2", "B3"):
            self.assertIn(f'data-block-id="{bid}"', html)
        self.assertGreaterEqual(html.count('data-req="AIR-1"'), 3)   # 主 chip + 两个子项 chip
