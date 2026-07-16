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

    def test_echo_block_gets_tag_not_duplicate_chip(self) -> None:
        """回声段契约(0716 用户裁定:批注不过度显示):同文重复段只给轻量"重复·见"
        角标指向汇总条目,不重复挂完整批注 chip;卡片文案两渲染器同源。
        HTML 侧 echo 由 build_ai_requirements 现算——夹具 E1/E2 是真实回声对,
        计算结果必须与夹具声明的 echo_block_ids 一致(两侧数据同源的锁)。"""
        html = self._render()
        expect = self.fixture["expect"]
        # parent_numbers 已锁 chip 总数(回声若挂 chip 会多出重复编号)
        self.assertIn(f'data-echo-req="{expect["echo_req"]}"', html)
        self.assertIn("重复·见03", html)
        self.assertIn(expect["echo_reason"], html)
        # 回声段不显示"未覆盖"(已被条目覆盖)
        e2_seg = html[html.find('data-block-id="E2"'):][:800]
        self.assertNotIn("omission-tag", e2_seg)

    def test_table_block_renders_real_table(self) -> None:
        """表格块按契约渲染真 <table>：题注/表头/数据格/无画线重建徽章（2026-07-07）。"""
        html = self._render()
        expect = self.fixture["expect"]
        self.assertIn('<figure class="doc-table">', html)
        self.assertIn(expect["table_caption"], html)
        self.assertIn(expect["table_badge"], html)
        for cell in expect["table_header_cells"]:
            self.assertIn(f"<th>{cell}</th>", html)
        for cell in expect["table_first_row"]:
            self.assertIn(f"<td>{cell}</td>", html)
        # 表格块不得再输出扁平 text 段落
        self.assertNotIn("Symbol | Type | bytes", html)

    def test_signal_fields_and_templates_present(self) -> None:
        """0714 批次一（E1c 双渲染器信号补齐）：合并徽章/一致性标记/合成冲突三信号——
        数据必须嵌入 REQS、渲染模板必须在位（选中时 JS 动态渲染,Vue 侧由
        AnnotationContract.spec 锁实际渲染文案与夹具 expect 同源）。"""
        html = self._render()
        expect = self.fixture["expect"]
        # 数据面：三信号字段随 REQS 嵌入静态页
        self.assertIn('"functional_merge_confidence": 0.75', html)
        self.assertIn('"functional_source_count": 2', html)
        self.assertIn(expect["consistency_flag_text"], html)
        self.assertIn(expect["conflict_flag_text"], html)
        # 模板面：徽章构造函数与两条渲染分支在位（与 Vue 同语义的文案骨架）
        self.assertIn("functionalMergeBadge", html)
        self.assertIn("跨章合并 ", html)
        self.assertIn("建议核对合并是否恰当", html)
        self.assertIn("全文档一致性", html)
        self.assertIn("待澄清冲突", html)
        self.assertIn(".dd-consistency", html)   # 新样式类必须有 CSS 定义

    def test_select_behavior_matches_contract_via_jsdom_markers(self) -> None:
        """静态可断言的部分：markSpan 的选择器素材必须在（span 的 doc-block[data-block-id]
        与 sub chip 的 data-req）——运行时行为由既有 jsdom 冒烟覆盖。"""
        html = self._render()
        for bid in ("B1", "B2", "B3"):
            self.assertIn(f'data-block-id="{bid}"', html)
        self.assertGreaterEqual(html.count('data-req="AIR-1"'), 3)   # 主 chip + 两个子项 chip
