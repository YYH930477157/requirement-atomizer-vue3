"""WS2 条款直抽接入 chain 的编排测试（RATOMIZER_FUNCTIONAL_EXTRACT 入口开关）。

覆盖面：
- 开关开：chain 把 ai-extract+functional-synthesis 整体替换为 functional-extract，
  不跑原子抽取任务，替换动作落账（payload.functional_extract_mode + manifest）；
- 开关关（默认）：chain 行为零变化，旧阶段照跑、无 functional-extract 结果；
- 直抽模式 stub 守卫：AI 依赖阶段无可复用直抽产物时响亮失败；
- 无原子链形态：requirements-analysis / clarification-report 以直抽产物为唯一依据
  （守恒未闭合响亮失败、产物缺失维持原 FileNotFoundError 纪律）；
- 缓存纪律：producer 戳绑定 functional_extract 三版本；开关进阶段指纹（切换必失效）。

纪律：单测禁止真实 LLM 调用——全部走 stub 路由或 mock。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import desktop_tasks
import functional_extract as fe
import requirements_analysis


def _write_min_corpus(out: Path) -> None:
    """单条款语料：blocks.jsonl + chunks.jsonl（parse 阶段产物形态）。"""
    (out / "blocks.jsonl").write_text(
        '{"block_id":"B1","section_path":["4.1"],"text":"The meter shall log events."}\n',
        encoding="utf-8",
    )
    (out / "chunks.jsonl").write_text(
        '{"section_path":["4.1"],"heading":"4.1",'
        '"text":"The meter shall log events.","block_ids":["B1"]}\n',
        encoding="utf-8",
    )


def _direct_payload(items: list[dict], *, conservation_ok: bool = True) -> dict:
    return {
        "schema_version": 1,
        "producer": "functional-extract-v1",
        "route": "stub",
        "items": items,
        "conservation": {"ok": conservation_ok, "missing_block_ids": [] if conservation_ok else ["B1"]},
    }


def _direct_item() -> dict:
    return {
        "functional_requirement_id": "FRE-TEST1",
        "objective": "记录事件",
        "behaviors": ["The meter shall log events."],
        "source_quote": "The meter shall log events.",
        "source_section": "4.1",
        "source_block_ids": ["B1"],
        "merge_method": "functional_extract",
    }


class ChainSubstitutionTests(unittest.TestCase):
    def test_switch_on_replaces_atom_stages_with_functional_extract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            with mock.patch.dict(os.environ, {"RATOMIZER_FUNCTIONAL_EXTRACT": "1"}):
                with mock.patch.object(desktop_tasks, "ai_extract_task") as atom_task:
                    # 第一步只跑抽取阶段（替换后 = functional-extract，stub 合法 opt-in）
                    first = desktop_tasks.chain_task(out, stages=["ai-extract"], route="stub")
                    # 第二步带 AI 依赖阶段：直抽产物已可复用 → 放行并跑分析
                    payload = desktop_tasks.chain_task(
                        out,
                        stages=["ai-extract", "functional-synthesis", "requirements-analysis"],
                        route="stub",
                    )
            atom_task.assert_not_called()
            self.assertIn("functional-extract", first["results"])
            self.assertIn("functional-extract", payload["results"])
            self.assertNotIn("ai-extract", payload["results"])
            self.assertNotIn("functional-synthesis", payload["results"])
            self.assertEqual(
                payload["functional_extract_mode"]["replaced_stages"],
                ["ai-extract", "functional-synthesis"],
            )
            # 第二轮直抽可复用 → 记 skipped 不重跑
            self.assertIn("functional-extract", payload["skipped_stages"])
            # 直抽产物真实落盘，stub 路由如实标注
            product = json.loads(
                (out / "functional_requirements.json").read_text(encoding="utf-8"))
            self.assertEqual(product["route"], "stub")
            self.assertEqual(product["producer"], fe.FUNCTIONAL_EXTRACT_VERSION)
            manifest = json.loads(
                (out / desktop_tasks.RUN_MANIFEST).read_text(encoding="utf-8"))
            self.assertEqual(manifest["stages"]["functional-extract"]["status"], "ok")
            # 无原子链形态：分析阶段以直抽产物为依据跑通
            self.assertIn("requirements-analysis", payload["results"])
            self.assertGreaterEqual(
                payload["results"]["requirements-analysis"]["analysis"]["analysis_count"], 1)
            self.assertTrue((out / "engineering_analysis.json").exists())

    def test_switch_off_keeps_legacy_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            env = {k: v for k, v in os.environ.items() if k != "RATOMIZER_FUNCTIONAL_EXTRACT"}
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(
                    desktop_tasks,
                    "ai_extract_task",
                    return_value={"written": ["ai_requirements.jsonl"], "route": "stub",
                                  "failed_sections": 0},
                ) as atom_task:
                    payload = desktop_tasks.chain_task(out, stages=["ai-extract"], route="stub")
            atom_task.assert_called_once()
            self.assertIn("ai-extract", payload["results"])
            self.assertNotIn("functional-extract", payload["results"])
            self.assertNotIn("functional_extract_mode", payload)

    def test_switch_on_stub_guard_requires_reusable_extract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)   # 空目录：无可复用直抽产物
            with mock.patch.dict(os.environ, {"RATOMIZER_FUNCTIONAL_EXTRACT": "1"}):
                with self.assertRaises(ValueError) as ctx:
                    desktop_tasks.chain_task(
                        out, stages=["ai-extract", "requirements-analysis"], route="stub")
            self.assertIn("功能直抽", str(ctx.exception))


class FunctionalExtractTaskTests(unittest.TestCase):
    def test_missing_key_fails_loudly_for_non_stub_route(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            with mock.patch.object(fe, "_route_config", return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    desktop_tasks.functional_extract_task(out, route="openai_compatible")
            self.assertIn("拒绝静默 stub", str(ctx.exception))

    def test_explicit_stub_route_runs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            result = desktop_tasks.functional_extract_task(out, route="stub")
            self.assertEqual(result["kind"], "functional_extract")
            self.assertTrue(Path(result["written"][0]).is_file())


class NoAtomDownstreamGateTests(unittest.TestCase):
    def test_analysis_accepts_conserved_direct_basis_without_atoms(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "functional_requirements.json").write_text(
                json.dumps(_direct_payload([_direct_item()]), ensure_ascii=False),
                encoding="utf-8")
            result = requirements_analysis.run_requirements_analysis(out, route="stub")
            self.assertEqual(result["analysis_count"], 1)

    def test_analysis_raises_on_unconserved_direct_basis(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "functional_requirements.json").write_text(
                json.dumps(_direct_payload([_direct_item()], conservation_ok=False),
                           ensure_ascii=False),
                encoding="utf-8")
            with self.assertRaises(fe.FunctionalConservationError):
                requirements_analysis.run_requirements_analysis(out, route="stub")

    def test_analysis_raises_without_atoms_or_direct_basis(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                requirements_analysis.run_requirements_analysis(Path(td), route="stub")

    def test_clarification_accepts_direct_basis_without_atoms(self) -> None:
        from clarification_report import run_report

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "blocks.jsonl").write_text(
                '{"block_id":"B1","section_path":["4.1"],"text":"The meter shall log events."}\n',
                encoding="utf-8")
            (out / "functional_requirements.json").write_text(
                json.dumps(_direct_payload([_direct_item()]), ensure_ascii=False),
                encoding="utf-8")
            payload = run_report(out)
            self.assertTrue((out / "clarification_report.json").exists())
            self.assertIn("readiness", payload)

    def test_clarification_raises_without_any_basis(self) -> None:
        from clarification_report import run_report

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                run_report(Path(td))


class CacheArtifactRecoveryTests(unittest.TestCase):
    def test_cache_hit_restores_missing_artifact(self) -> None:
        """缓存命中但产物文件被清理 → 从缓存负载补写,不陷"成功但无产物"。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            first = fe.run_functional_extract(out, sections=None, route="stub")
            self.assertEqual(first["written"], ["functional_requirements.json"])
            (out / "functional_requirements.json").unlink()
            second = fe.run_functional_extract(out, sections=None, route="stub")
            self.assertTrue((out / "functional_requirements.json").is_file())
            self.assertEqual(
                second["functional_requirements"], first["functional_requirements"])


class FingerprintDisciplineTests(unittest.TestCase):
    def test_producer_binds_functional_extract_versions(self) -> None:
        producer = desktop_tasks.stage_producer("functional-extract")
        self.assertIn(fe.FUNCTIONAL_EXTRACT_VERSION, producer)
        self.assertIn(fe.FUNCTIONAL_EXTRACT_PROMPT_VERSION, producer)
        self.assertIn(fe.FUNCTIONAL_EXTRACT_GUARDS_VERSION, producer)

    def test_entry_switch_env_changes_stage_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            _write_min_corpus(out)
            base_env = {k: v for k, v in os.environ.items()
                        if k != "RATOMIZER_FUNCTIONAL_EXTRACT"}
            with mock.patch.dict(os.environ, base_env, clear=True):
                off = desktop_tasks.stage_input_fingerprint(out, "requirements-analysis")
            with mock.patch.dict(os.environ, {**base_env, "RATOMIZER_FUNCTIONAL_EXTRACT": "1"},
                                 clear=True):
                on = desktop_tasks.stage_input_fingerprint(out, "requirements-analysis")
            self.assertNotEqual(off, on)


if __name__ == "__main__":
    unittest.main()
