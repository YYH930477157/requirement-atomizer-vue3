"""T3-3 存储抽象收口：``ArtifactStore`` 门面行为 + 裸拼 lint 契约测试。

覆盖三块：
1. 门面行为：governed 寻址 / JSONL 读（tolerant+严格）/ 原子写 / append / JSON 读写 / 跨进程锁
   ——产物落 ``.ratomizer/<category>/``（package_v1），与既有 governed 路径一致。
2. lint 抓手：``scan_bare_artifact_joins`` 对一段故意裸拼的源码必须命中。
3. 基线冻结：仓库现存 governed 裸拼的 (file, filename) 多集 == 冻结白名单；基线之外的新裸拼
   即失败（把「寻址靠纪律」升级为「寻址靠门禁」）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import artifact_store
from artifact_store import ArtifactStore, scan_bare_artifact_joins, scan_repo_bare_joins


class ArtifactStoreFacadeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_path_resolves_governed_category(self) -> None:
        from result_package import governed_artifact_path

        store = ArtifactStore(self.root, category="state")
        # 委托 governed_artifact_path：同一 (root, filename, category) 解析一致
        self.assertEqual(
            store.path("foo.jsonl", for_write=True),
            governed_artifact_path(self.root, "foo.jsonl", category="state", for_write=True),
        )

    def test_read_jsonl_missing_returns_empty(self) -> None:
        store = ArtifactStore(self.root, category="state")
        self.assertEqual(store.read_jsonl("absent.jsonl"), [])
        self.assertEqual(store.read_jsonl("absent.jsonl", tolerant=True), [])

    def test_write_then_read_jsonl_roundtrip(self) -> None:
        store = ArtifactStore(self.root, category="cache")
        rows = [{"a": 1}, {"b": "x"}]
        store.write_jsonl("things.jsonl", rows)
        self.assertEqual(store.read_jsonl("things.jsonl"), rows)

    def test_append_jsonl_is_append_only(self) -> None:
        store = ArtifactStore(self.root, category="state")
        store.append_jsonl("events.jsonl", {"i": 1})
        store.append_jsonl("events.jsonl", {"i": 2})
        self.assertEqual(store.read_jsonl("events.jsonl"), [{"i": 1}, {"i": 2}])

    def test_read_jsonl_tolerant_skips_bad_lines(self) -> None:
        store = ArtifactStore(self.root, category="state")
        path = store.path("messy.jsonl", for_write=True)
        path.write_text(
            json.dumps({"ok": True}) + "\n{NOT JSON}\n" + json.dumps({"ok": 2}) + "\n",
            encoding="utf-8",
        )
        # tolerant 跳过坏行；严格模式抛错
        self.assertEqual(store.read_jsonl("messy.jsonl", tolerant=True), [{"ok": True}, {"ok": 2}])
        with self.assertRaises(json.JSONDecodeError):
            store.read_jsonl("messy.jsonl")

    def test_write_json_atomic_roundtrip(self) -> None:
        store = ArtifactStore(self.root, category="pipeline")
        store.write_json("summary.json", {"k": [1, 2, 3]})
        self.assertEqual(store.read_json("summary.json"), {"k": [1, 2, 3]})
        self.assertIsNone(store.read_json("absent.json"))

    def test_locked_serializes_read_modify_write(self) -> None:
        # locked() 给 read-modify-write 一个跨进程临界区（OS 锁非可重入，与
        # review_state_lock 同型——不要嵌套；同进程多线程经 RLock 串行）
        store = ArtifactStore(self.root, category="state")
        with store.locked():
            existing = store.read_jsonl("ev.jsonl", tolerant=True)
            store.write_jsonl("ev.jsonl", existing + [{"x": 1}])
        self.assertEqual(store.read_jsonl("ev.jsonl"), [{"x": 1}])

    def test_sequential_locked_blocks_are_independent(self) -> None:
        store = ArtifactStore(self.root, category="state")
        with store.locked():
            store.append_jsonl("ev.jsonl", {"i": 1})
        with store.locked():
            store.append_jsonl("ev.jsonl", {"i": 2})
        self.assertEqual(store.read_jsonl("ev.jsonl"), [{"i": 1}, {"i": 2}])

    def test_write_overwrites_atomically(self) -> None:
        store = ArtifactStore(self.root, category="state")
        store.write_jsonl("a.jsonl", [{"v": 1}])
        store.write_jsonl("a.jsonl", [{"v": 2}, {"v": 3}])
        self.assertEqual(store.read_jsonl("a.jsonl"), [{"v": 2}, {"v": 3}])


class BareJoinScannerTests(unittest.TestCase):
    def test_scanner_flags_deliberate_bare_join(self) -> None:
        """lint 抓手：一段故意 ``root / "new_shared.jsonl"`` 裸拼必须被命中。"""
        src = (
            "def f(root):\n"
            "    return root / \"new_shared.jsonl\"\n"
        )
        hits = scan_bare_artifact_joins(src, file="evil.py")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].filename, "new_shared.jsonl")
        self.assertEqual(hits[0].file, "evil.py")
        self.assertEqual(hits[0].line, 2)

    def test_scanner_flags_lock_join_and_various_lefts(self) -> None:
        """左操作数形态不限（root / out_dir / self.dir），.lock 同样命中。"""
        src = (
            "def g(out_dir, self):\n"
            "    a = out_dir / \"run.lock\"\n"
            "    b = self.dir / \"table_cell_items.jsonl\"\n"
            "    return a, b\n"
        )
        names = sorted(h.filename for h in scan_bare_artifact_joins(src, file="x.py"))
        self.assertEqual(names, ["run.lock", "table_cell_items.jsonl"])

    def test_scanner_ignores_non_governed_and_string_division(self) -> None:
        """非 governed 后缀（.txt/.json/.md）与字符串里的 '/' 不命中。"""
        src = (
            "def h(root):\n"
            "    p = root / \"config.txt\"\n"
            "    q = root / \"summary.json\"\n"
            "    s = \"a/b.jsonl\"  # 字符串字面量，不是 BinOp 除法\n"
            "    return p, q, s\n"
        )
        self.assertEqual(scan_bare_artifact_joins(src, file="ok.py"), [])

    def test_scanner_handles_syntax_error(self) -> None:
        self.assertEqual(scan_bare_artifact_joins("def (", file="bad.py"), [])


# 现存 governed 裸拼的 (file, filename) 多集白名单——T3-3 把「寻址靠纪律」升级为「寻址靠门禁」。
# 新代码出现基线之外的裸拼即失败：改走 ArtifactStore 或 governed_artifact_path。修改既有裸拼
# 数量时同步更新本表（删/迁移合法，新增必须走接口层）。
BASELINE_BARE_JOINS: dict[str, dict[str, int]] = {
    "adjudication_bank.py": {"ai_requirements.jsonl": 1},
    "agent_state.py": {"ai_requirements.jsonl": 1, "blocks.jsonl": 1},
    "agent_tools.py": {"ai_requirements.jsonl": 1, "blocks.jsonl": 1},
    "ai_extract.py": {"blocks.jsonl": 2, "llm_review_results.jsonl": 1},
    "api_server.py": {
        "ai_requirements.jsonl": 4, "atomic_requirements.jsonl": 3, "blocks.jsonl": 3,
        "llm_review_results.jsonl": 3,
    },
    "atomize.py": {
        "atomic_requirements.jsonl": 1, "blocks.jsonl": 1, "chunks.jsonl": 1,
        "llm_tasks.jsonl": 1, "table_cell_items.jsonl": 1, "table_items.jsonl": 1,
    },
    "claim_artifacts.py": {
        "ai_requirements.jsonl": 5, "blocks.jsonl": 2, "table_cell_items.jsonl": 4,
        "table_items.jsonl": 2,
    },
    "claim_catalog.py": {"blocks.jsonl": 1, "table_cell_items.jsonl": 1, "table_items.jsonl": 1},
    "claim_ledger.py": {"ai_requirements.jsonl": 2},
    "claim_queue_execution.py": {
        "blocks.jsonl": 2, "table_cell_items.jsonl": 2, "table_items.jsonl": 2,
    },
    "claim_reextract_attempts.py": {"ai_requirements.jsonl": 1},
    "claim_review_actions.py": {"blocks.jsonl": 1, "table_cell_items.jsonl": 1, "table_items.jsonl": 1},
    "clarification_report.py": {"ai_requirements.jsonl": 3, "blocks.jsonl": 3},
    "corpus_eval.py": {"ai_requirements.jsonl": 1},
    "cosem_access_security.py": {"atomic_requirements.jsonl": 1, "table_items.jsonl": 1},
    "cosem_behavior_spec.py": {"atomic_requirements.jsonl": 1, "llm_review_results.jsonl": 1},
    "cosem_external_refs.py": {"atomic_requirements.jsonl": 1, "blocks.jsonl": 1, "table_items.jsonl": 1},
    "cosem_object_model.py": {"atomic_requirements.jsonl": 1, "table_items.jsonl": 1},
    "decide_trace.py": {"decide_trace.lock": 1},
    "desktop_tasks.py": {
        "ai_requirements.jsonl": 2, "atomic_requirements.jsonl": 1, "llm_review_results.jsonl": 2,
        "llm_trace.jsonl": 1, "run_manifest.lock": 1,
    },
    "doc_annotation_export.py": {
        "blocks.jsonl": 2, "table_items.jsonl": 1,
    },
    "engineering_composer.py": {"atomic_requirements.jsonl": 1, "table_items.jsonl": 1},
    "export_requirements.py": {"atomic_requirements.jsonl": 1},
    "extract_cosem_instances.py": {"table_items.jsonl": 1},
    "extract_terms.py": {"blocks.jsonl": 1, "table_items.jsonl": 1},
    "functional_synthesis.py": {"ai_requirements.jsonl": 1},
    "llm_pipeline.py": {
        "atomic_requirements.jsonl": 3, "llm_review_results.jsonl": 1,
        "review_state_events.jsonl": 1,
    },
    "meter_profile.py": {"blocks.jsonl": 2},
    "omission_actions.py": {"ai_requirements.jsonl": 1, "blocks.jsonl": 6},
    "orchestration_gaps.py": {"ai_requirements.jsonl": 1, "blocks.jsonl": 1, "claim_catalog.jsonl": 1},
    "orchestration_loop.py": {"blocks.jsonl": 1},
    "requirements_analysis.py": {"ai_requirements.jsonl": 1, "blocks.jsonl": 1},
    "review_insights.py": {"ai_requirements.jsonl": 1},
    "review_state.py": {"atomic_requirements.jsonl": 1},
    "review_tools.py": {"atomic_requirements.jsonl": 2, "blocks.jsonl": 2},
    "spot_extract.py": {"blocks.jsonl": 2, "table_cell_items.jsonl": 1},
}


class RepoBareJoinBaselineTests(unittest.TestCase):
    def test_no_new_bare_artifact_joins(self) -> None:
        """仓库现存 governed 裸拼多集 == BASELINE_BARE_JOINS。

        新增基线之外的 ``root / "*.jsonl|.lock"`` 裸拼即失败——改走 ``ArtifactStore``
        （新代码）或 ``governed_artifact_path``。合法删除/迁移既有裸拼时同步缩表。
        """
        repo = Path(__file__).resolve().parent.parent
        hits = scan_repo_bare_joins(repo)
        actual: dict[str, dict[str, int]] = {}
        for hit in hits:
            file = Path(hit.file).name
            bucket = actual.setdefault(file, {})
            bucket[hit.filename] = bucket.get(hit.filename, 0) + 1
        # 只比较非门面文件（artifact_store.py 自身的锁/tmp 用 with_name，不应出现裸拼；
        # 若将来出现也应在白名单里显式登记）
        self.assertEqual(
            actual, BASELINE_BARE_JOINS,
            "governed 裸拼集合变化：新增裸拼必须走 ArtifactStore/governed_artifact_path；"
            "若属合法迁移/删除，同步更新 BASELINE_BARE_JOINS。实际=%r" % actual,
        )


if __name__ == "__main__":
    unittest.main()
