"""M2 §4.6（去原子化修复方案，2026-08-15）：功能级 Claim 队列离线 E2E。

矩阵（全部离线：chat 注入，禁止真实 LLM）：
① 真实直抽产生 uncertain claim + 队列 proposal；
② 队列对相关 section 重抽并 fold；
③ 未受影响 FRE 指纹/ID 级稳定（不重排、不改写）；
④ 受影响 FRE 被替换；
⑤ claim generation 绑定新 functional product hash；
⑥ coverage edge 携带可复核的 target_source_anchors（块辖域校验 + 加载重放）；
⑦ fold 后 uncertain 归零；
⑧ full closure 自动 ready（队列闭合 claim，无需人工 claim 裁决）；
⑨ CAS 冲突（旧 expected_product_fingerprint）拒绝且产物不动；
⑩ 同 idempotency key 重放不重复执行（chat 不被再次调用）；
⑪ stub/失败 chat 不覆盖健康产物；
⑫ 复审四轮 P1-1：产品替换前持久化 publication_prepared（新旧产品哈希），
替换后、requirements_published 落账前的中断（WAL 异常/进程退出）按哈希路由
确定性恢复——==新哈希补记 published 进 rebuild_pending；==旧哈希按未发布
（interrupted 可重试）；均不等按 CAS 冲突；绝不落 reextract_failed 终态。

fixture 参考 tests/test_claim_functional_store.py（objective 含句号使 coverage
确定性 validated）。B2 初始用弱叙述（token 覆盖守恒、但不逐字包含 claim 文本）
→ 语义候选组 proposed → uncertain；重抽换强叙述 → deterministic verbatim validated。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ai_extract
import claim_queue_execution as execution
import claim_reextract_attempts
import desktop_tasks
import functional_extract as fe
from llm_client import LLMClientConfig

B1_TEXT = "The meter shall log events."
# 产品义务名词须落在 normative_framing 的产品名词表内（controller），否则
# product_obligation_governs_span 不认 deterministic verbatim 闭合。
B2_TEXT = "The controller shall forward alarms to the management platform."
WEAK_B2_OBJECTIVE = "Alarms from the controller shall reach the management platform."


def _sections() -> list[dict]:
    return [
        {
            "section_id": "4.1", "section_path": ["4.1"], "heading": "4.1",
            "text": B1_TEXT, "block_ids": ["B1"],
        },
        {
            "section_id": "4.2", "section_path": ["4.2"], "heading": "4.2",
            "text": B2_TEXT, "block_ids": ["B2"],
        },
    ]


def _write_corpus(out: Path) -> None:
    (out / "blocks.jsonl").write_text(
        '{"block_id":"B1","section_path":["4.1"],"text":"'
        + B1_TEXT.replace('"', '\\"') + '"}\n'
        '{"block_id":"B2","section_path":["4.2"],"text":"'
        + B2_TEXT.replace('"', '\\"') + '"}\n',
        encoding="utf-8",
    )
    (out / "chunks.jsonl").write_text(
        '{"section_path":["4.1"],"heading":"4.1","text":"'
        + B1_TEXT.replace('"', '\\"') + '","block_ids":["B1"]}\n'
        '{"section_path":["4.2"],"heading":"4.2","text":"'
        + B2_TEXT.replace('"', '\\"') + '","block_ids":["B2"]}\n',
        encoding="utf-8",
    )


def _chat_v1(system: str, user: str) -> dict:
    """初始直抽：B1 强叙述（validated）；B2 弱叙述（守恒 ok 但 claim 只到 proposed）。"""
    return {"items": [
        {
            "objective": B1_TEXT,
            "behaviors": ["log events"],
            "source_quote": B1_TEXT,
            "source_block_ids": ["B1"],
        },
        {
            "objective": WEAK_B2_OBJECTIVE,
            "behaviors": ["deliver alarms"],
            "source_quote": B2_TEXT,
            "source_block_ids": ["B2"],
        },
    ]}


def _chat_v2_payload() -> dict:
    return {"items": [{
        "objective": B2_TEXT,
        "behaviors": ["forward alarms"],
        "source_quote": B2_TEXT,
        "source_block_ids": ["B2"],
    }]}


def _seed_direct_mode(root: Path) -> dict:
    """真实直抽（注入 chat）→ claim 发布 → 返回 fold 出的 uncertain proposal。"""
    _write_corpus(root)
    result = fe.run_functional_extract(
        root, sections=_sections(), chat=_chat_v1, route="openai_compatible")
    assert result["execution_status"] == "ok", result
    assert not result["draft"]
    assert result["conservation"].get("ok") is True, result["conservation"]
    desktop_tasks._publish_functional_claim_shadow(root, route="openai_compatible")
    from claim_artifacts import load_committed_effective_snapshot

    snapshot = load_committed_effective_snapshot(root)
    proposals = [dict(row) for row in snapshot.get("queue_proposals") or []]
    assert proposals, "seed must leave an uncertain claim with a queue proposal"
    proposal = proposals[0]
    assert proposal["schema"] == "claim-queue-proposal/v3"
    return proposal


def _config() -> LLMClientConfig:
    return LLMClientConfig(
        base_url="https://example.invalid/v1",
        model="deepseek-chat",
        max_tokens=128,
        max_retries=0,
    )


def _execute(root: Path, proposal: dict, *, chat_with_meta, key: str = "freq-1"):
    config = _config()
    with mock.patch.object(
        ai_extract, "config_for_route", return_value=config,
    ), mock.patch.object(
        execution, "apply_min_tokens", side_effect=lambda value, _purpose: value,
    ):
        route_revision = execution._resolved_route_preflight(
            "openai_compatible", config,
        )[1]["route_config_revision"]
        return execution.execute_claim_queue_proposal(
            root,
            proposal_id=proposal["proposal_id"],
            expected_claim_effective_revision=proposal["claim_effective_revision"],
            expected_ledger_state="uncertain",
            actor="expert:yyh",
            allow_llm=True,
            route="openai_compatible",
            maximum_calls=4,
            total_token_budget=20000,
            request_idempotency_key=key,
            chat_with_meta=chat_with_meta,
            expected_route_config_revision=route_revision,
        )


def _chat_v2_with_meta(calls: list[str] | None = None):
    def chat(_config, system, user, *, request_budget=None):
        if calls is not None:
            calls.append(user)
        return _chat_v2_payload(), {}
    return chat


def _read_product(root: Path) -> dict:
    return json.loads(
        (root / "functional_requirements.json").read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class FunctionalClaimQueueE2ETests(unittest.TestCase):
    def test_queue_reextract_replaces_affected_fre_and_closes_claim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            before_product = _read_product(root)
            before_items = before_product["items"]
            self.assertEqual(len(before_items), 2)
            kept_before = next(
                item for item in before_items
                if "B1" in (item.get("source_block_ids") or []))
            affected_before = next(
                item for item in before_items
                if "B2" in (item.get("source_block_ids") or []))
            self.assertNotEqual(
                affected_before.get("objective"), B2_TEXT)

            calls: list[str] = []
            result = _execute(root, proposal, chat_with_meta=_chat_v2_with_meta(calls))

            # ② 队列执行成功，claim 经新 coverage 组闭合
            self.assertEqual(result["lifecycle"], "executed")
            self.assertEqual(result["resolution"], "covered")
            self.assertTrue(result["mutation"]["conservation_ok"])
            # 重抽只发生在受影响条款族（4.2），未把 4.1 拖进 prompt
            self.assertEqual(len(calls), 1, calls)
            self.assertNotIn(B1_TEXT, calls[0])

            # WAL 事件顺序（与原子路径同族保障）
            rows = claim_reextract_attempts.read_attempt_log(root).rows
            kinds = [row["event_kind"] for row in rows]
            self.assertEqual(kinds[0], "reextract_started")
            for left, right in (
                ("reextract_started", "supplement_persisted"),
                ("supplement_persisted", "requirements_published"),
                ("requirements_published", "base_rebuild_published"),
                ("base_rebuild_published", "effective_folded"),
                ("effective_folded", "reextract_succeeded"),
            ):
                self.assertLess(kinds.index(left), kinds.index(right), kinds)

            after_product = _read_product(root)
            after_items = after_product["items"]
            self.assertEqual(after_product["execution_status"], "ok")
            self.assertTrue(after_product["conservation"].get("ok"))

            # ③ 未受影响 FRE 指纹/ID 级稳定（不重排、不改写）
            kept_after = next(
                item for item in after_items
                if item.get("functional_requirement_id")
                == kept_before.get("functional_requirement_id"))
            self.assertEqual(kept_after, kept_before)
            self.assertEqual(after_items.index(kept_after), 0)

            # ④ 受影响 FRE 被替换：条款序号 UID 稳定（FR-0002），叙述换为强覆盖；
            #    旧 FRE（输出序 hash id）不再在场。
            affected_after = next(
                item for item in after_items
                if item.get("requirement_uid")
                == affected_before.get("requirement_uid"))
            self.assertEqual(affected_after.get("objective"), B2_TEXT)
            self.assertIn(B2_TEXT, str(affected_after.get("description") or ""))
            self.assertNotEqual(
                affected_after.get("functional_requirement_id"),
                affected_before.get("functional_requirement_id"))
            self.assertNotIn(
                affected_before.get("functional_requirement_id"),
                {item.get("functional_requirement_id") for item in after_items})

            # ⑤ generation 绑定新 functional product hash
            from claim_artifacts import file_sha256, load_committed_claim_base

            meta = json.loads(
                (root / "claim_generation.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(
                meta["requirements_store"], "functional_requirements.json")
            self.assertEqual(
                meta["requirements_sha256"],
                file_sha256(root / "functional_requirements.json"))
            base = load_committed_claim_base(root)  # 锚重放校验通过（⑥ 加载侧）
            self.assertEqual(
                base["generation_meta"]["requirements_sha256"],
                meta["requirements_sha256"])

            # ⑥ coverage edge 携带 target_source_anchors，块辖域可复核
            catalog = {
                row["claim_id"]: row for row in _read_jsonl(root / "claim_catalog.jsonl")
            }
            groups = _read_jsonl(root / "claim_coverage_groups.jsonl")
            anchored = 0
            for group in groups:
                claim = catalog[group["claim_id"]]
                locator_block = str(
                    (claim.get("locator") or {}).get("block_id") or "")
                for edge in group.get("edges") or []:
                    anchors = edge.get("target_source_anchors")
                    if anchors is None:
                        continue
                    anchored += 1
                    self.assertTrue(anchors, edge)
                    for anchor in anchors:
                        self.assertIn(
                            "section_id", anchor)
                        self.assertIn("block_ids", anchor)
                        self.assertIn("sentence_index", anchor)
                        self.assertIn("unit_index", anchor)
                        # 锚必须落在该 claim 的 locator 块辖域内（§4.4 校验）
                        self.assertIn(locator_block, anchor["block_ids"])
            self.assertGreaterEqual(anchored, 2, groups)

            # ⑦ fold 后 uncertain 归零
            from claim_artifacts import load_committed_effective_snapshot

            snapshot = load_committed_effective_snapshot(root)
            uncertain = [
                row for row in snapshot.get("effective_ledger") or []
                if row.get("resolution") == "uncertain"
            ]
            self.assertEqual(uncertain, [])
            self.assertEqual(snapshot.get("queue_proposals") or [], [])

    def test_full_closure_ready_after_queue_without_manual_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            result = _execute(root, proposal, chat_with_meta=_chat_v2_with_meta())
            self.assertEqual(result["resolution"], "covered")

            # 专家只需裁决 FRE 条目（分析侧"全部已裁决"门）——claim 已被队列闭合，
            # 无需人工 claim 裁决（对照 DirectModeFullClosureE2ETests 的裁决步骤）。
            from ai_review_actions import (
                apply_ai_review_action,
                review_anchor_fingerprint,
                review_subject_fingerprint,
                source_ai_requirement_id,
                source_fingerprint,
            )

            for item in _read_product(root)["items"]:
                apply_ai_review_action(
                    root, source_ai_requirement_id(item), "accepted",
                    level="functional", actor="expert",
                    source_fingerprint_value=source_fingerprint(item),
                    review_subject_fingerprint_value=review_subject_fingerprint(item),
                    review_anchor_fingerprint_value=review_anchor_fingerprint(item),
                )

            with mock.patch.dict(
                    os.environ, {"RATOMIZER_CLAIM_LEDGER_MODE": "full"}):
                closure = desktop_tasks.evaluate_full_closure(root)
            self.assertTrue(closure["ready"], closure["gaps"])
            self.assertEqual(closure["gaps"], [])

    def test_same_idempotency_key_replay_skips_paid_chat(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            first = _execute(root, proposal, chat_with_meta=_chat_v2_with_meta())
            self.assertEqual(first["lifecycle"], "executed")
            product_after_first = (root / "functional_requirements.json").read_bytes()

            def refusing_chat(*_args, **_kwargs):
                raise AssertionError("idempotent replay must not call the LLM chat")

            second = _execute(
                root, proposal, chat_with_meta=refusing_chat, key="freq-1")
            rows = claim_reextract_attempts.read_attempt_log(root).rows
            product_after_replay = (
                root / "functional_requirements.json").read_bytes()

        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(second["attempt_id"], first["attempt_id"])
        self.assertEqual(second["lifecycle"], "executed")
        self.assertEqual(
            sum(row["event_kind"] == "reextract_started" for row in rows), 1)
        self.assertEqual(
            sum(row["event_kind"] == "reextract_succeeded" for row in rows), 1)
        self.assertEqual(product_after_replay, product_after_first)


class ReextractCacheRefreshTests(unittest.TestCase):
    """复审 P1-1（2026-08-16）+ 二轮残余：缓存刷新必须可证成功，否则失效/响亮失败。"""

    def test_cache_hit_restores_merged_product_not_pre_reextract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            result = _execute(
                root, proposal, chat_with_meta=_chat_v2_with_meta([]))
            self.assertEqual(result["lifecycle"], "executed")
            merged = _read_product(root)
            self.assertIn("reextract", merged)
            merged_b2 = next(
                item for item in merged["items"]
                if item.get("source_block_ids") == ["B2"])
            self.assertEqual(merged_b2["objective"], B2_TEXT)

            # 产物被清理（模拟交付目录瘦身/拷贝丢文件）→ 同指纹普通重跑走缓存
            (root / "functional_requirements.json").unlink()
            restored = fe.run_functional_extract(
                root, sections=_sections(), chat=_chat_v1, route="openai_compatible")
            self.assertEqual(restored["written"], ["functional_requirements.json"])
            replayed = _read_product(root)
            # 缓存恢复的必须是合并产物（定向重抽结果），不是重抽前的 v1 产物
            self.assertIn("reextract", replayed)
            replayed_b2 = next(
                item for item in replayed["items"]
                if item.get("source_block_ids") == ["B2"])
            self.assertEqual(replayed_b2["objective"], B2_TEXT)
            self.assertNotEqual(replayed_b2["objective"], WEAK_B2_OBJECTIVE)

    def test_refresh_failure_falls_back_to_invalidation(self) -> None:
        """复审 P1-1 二轮：刷新写不进去 → 删除该行兜底——普通重跑缓存 miss 走
        全量真实抽取（chat 被再次调用），绝不恢复重抽前产物。"""
        import functional_reextract as fr

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            original_write = fr.fe._write_cache_entry if hasattr(fr, "fe") else None
            import functional_extract as fe_mod

            with mock.patch.object(
                    fe_mod, "_write_cache_entry",
                    side_effect=OSError("cache volume read-only")):
                result = _execute(
                    root, proposal, chat_with_meta=_chat_v2_with_meta([]))
            self.assertEqual(result["lifecycle"], "executed")
            # 兜底失效成功：缓存里没有该指纹的行
            fingerprint = _read_product(root).get("fingerprint")
            self.assertNotIn(fingerprint, fe_mod._read_cache(root))
            # 产物被清理后普通重跑：缓存 miss → 真实再抽取（chat 被调用）
            (root / "functional_requirements.json").unlink()
            rerun_calls: list[str] = []

            def chat_any(system: str, user: str) -> dict:
                rerun_calls.append(user)
                return _chat_v1(system, user)

            fe_mod.run_functional_extract(
                root, sections=_sections(), chat=chat_any, route="openai_compatible")
            self.assertTrue(rerun_calls)  # 没有走缓存恢复
            replayed = _read_product(root)
            self.assertNotIn("reextract", replayed)  # 全量新跑，不再是旧缓存行内容

    def test_refresh_and_invalidate_both_failing_raises_loudly(self) -> None:
        """复审 P1-1 二轮：刷新与失效都失败 → FunctionalReextractCacheRefreshError，
        队列不得记 executed（复现：模拟缓存完全不可用）。"""
        import functional_extract as fe_mod
        import functional_reextract as fr

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            with mock.patch.object(
                    fe_mod, "_write_cache_entry",
                    side_effect=OSError("write failed")),                     mock.patch.object(
                        fr, "_invalidate_cache_entry", return_value=False):
                before = _read_product(root)
                with self.assertRaises(fr.FunctionalReextractCacheRefreshError):
                    fr.functional_targeted_reextract(
                        root,
                        affected_block_ids=["B2"],
                        expected_product_fingerprint=fr.functional_product_fingerprint(root),
                        route="openai_compatible",
                        chat=lambda system, user: _chat_v2_payload(),
                    )
                # 半提交消除：失效失败发生在产品替换之前——产物分毫未动
                self.assertEqual(_read_product(root), before)



class FunctionalReextractGuardTests(unittest.TestCase):
    def test_stale_expected_fingerprint_is_rejected_without_paid_call(self) -> None:
        from functional_reextract import (
            FunctionalReextractConflict,
            functional_product_fingerprint,
            functional_targeted_reextract,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_direct_mode(root)
            before = (root / "functional_requirements.json").read_bytes()

            def refusing_chat(system: str, user: str) -> dict:
                raise AssertionError("CAS conflict must abort before the paid call")

            with self.assertRaises(FunctionalReextractConflict):
                functional_targeted_reextract(
                    root,
                    affected_block_ids=["B2"],
                    expected_product_fingerprint="sha256:" + "0" * 64,
                    route="openai_compatible",
                    chat=refusing_chat,
                )
            self.assertEqual(
                (root / "functional_requirements.json").read_bytes(), before)

    def test_stub_chat_does_not_overwrite_healthy_product(self) -> None:
        from functional_reextract import (
            FunctionalReextractUnhealthy,
            functional_product_fingerprint,
            functional_targeted_reextract,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _seed_direct_mode(root)
            before = (root / "functional_requirements.json").read_bytes()
            fingerprint_before = functional_product_fingerprint(root)

            def stub_chat(system: str, user: str) -> dict:
                return {"items": []}  # 非法负载 → 护栏退化 stub → failed

            with self.assertRaises(FunctionalReextractUnhealthy):
                functional_targeted_reextract(
                    root,
                    affected_block_ids=["B2"],
                    expected_product_fingerprint=fingerprint_before,
                    route="openai_compatible",
                    chat=stub_chat,
                )
            self.assertEqual(
                (root / "functional_requirements.json").read_bytes(), before)

    def test_queue_stub_chat_is_terminal_failure_and_keeps_product(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            before = (root / "functional_requirements.json").read_bytes()

            def stub_chat(_config, system, user, *, request_budget=None):
                return {"items": []}, {}

            with self.assertRaises(execution.ClaimQueueExecutionUnavailable):
                _execute(root, proposal, chat_with_meta=stub_chat, key="stub-1")
            rows = claim_reextract_attempts.read_attempt_log(root).rows

            self.assertEqual(
                (root / "functional_requirements.json").read_bytes(), before)
            self.assertFalse(any(
                row["event_kind"] == "requirements_published" for row in rows))
            terminal = rows[-1]
            self.assertEqual(terminal["event_kind"], "reextract_failed")
            self.assertEqual(
                terminal["outcome"]["code"], "functional_product_unhealthy")


class AnchorTextIdentityTests(unittest.TestCase):
    """复审 P2-1（2026-08-16）：Claim 源锚必须按当前义务重算并核验 source_text_hash。"""

    def test_edge_drops_anchor_with_mismatched_text_hash(self) -> None:
        from claim_ledger import _edge, functional_anchor_obligation_hashes

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_corpus(root)
            hashes = functional_anchor_obligation_hashes(root)
            self.assertIn(("4.1", 0), hashes)
            identity_41 = hashes[("4.1", 0)]
            self.assertEqual(identity_41["sentence_index"], 0)
            target = {
                "target_requirement_id": "FRE-X",
                "target_fingerprint": "fp",
                "review": {
                    "status": "unreviewed", "eligibility": "active",
                    "target_review_revision": "rev",
                    "review_adapter_version": "ai-review-adapter-v1",
                },
                "source_anchors": [
                    {   # 正确哈希
                        "section_id": "4.1", "sentence_index": 0, "unit_index": 0,
                        "block_ids": ["B1"],
                        "source_text_hash": hashes[("4.1", 0)]["source_text_hash"],
                        "match_method": "lexical",
                    },
                    {   # 篡改哈希（自证伪造）
                        "section_id": "4.1", "sentence_index": 0, "unit_index": 0,
                        "block_ids": ["B1"],
                        "source_text_hash": "deadbeef" * 8,
                        "match_method": "lexical",
                    },
                ],
            }
            edge = _edge(
                target, claim_hash="sha256:c", target_generation_id="g",
                produced_evidence=[], relation="generated_from",
                claim_locator_blocks=frozenset({"B1"}),
                obligation_hashes=hashes,
            )
            self.assertEqual(len(edge["target_source_anchors"]), 1)
            self.assertEqual(edge["target_source_anchor_text_mismatch"], 1)
            self.assertNotIn("target_source_anchor_stale", edge)
            # 无索引（legacy）时不核验——两个锚都保留
            edge_legacy = _edge(
                target, claim_hash="sha256:c", target_generation_id="g",
                produced_evidence=[], relation="generated_from",
                claim_locator_blocks=frozenset({"B1"}),
            )
            self.assertEqual(len(edge_legacy["target_source_anchors"]), 2)

    def test_foreign_block_ids_cannot_borrow_across_clauses(self) -> None:
        """四轮复审 P1-2：合法 section/unit/hash + 外条款 block_ids 的伪锚被拒。

        4.1 的合法义务身份配上 B2 的伪造 block、参与 B2 Claim——必须剔除。
        """
        from claim_ledger import _edge, functional_anchor_obligation_hashes

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_corpus(root)
            hashes = functional_anchor_obligation_hashes(root)
            target = {
                "target_requirement_id": "FRE-X",
                "target_fingerprint": "fp",
                "review": {
                    "status": "unreviewed", "eligibility": "active",
                    "target_review_revision": "rev",
                    "review_adapter_version": "ai-review-adapter-v1",
                },
                "source_anchors": [
                    {   # 4.1 合法身份 + B2 伪造块（借位）
                        "section_id": "4.1", "sentence_index": 0, "unit_index": 0,
                        "block_ids": ["B2"],
                        "source_text_hash": hashes[("4.1", 0)]["source_text_hash"],
                        "match_method": "lexical",
                    },
                    {   # 对照组：4.1 合法身份 + 真实块 B1
                        "section_id": "4.1", "sentence_index": 0, "unit_index": 0,
                        "block_ids": ["B1"],
                        "source_text_hash": hashes[("4.1", 0)]["source_text_hash"],
                        "match_method": "lexical",
                    },
                ],
            }
            # B2 claim 的辖域：伪锚因辖域相交曾被保留——现在必须先被块集合同剔除
            edge = _edge(
                target, claim_hash="sha256:c", target_generation_id="g",
                produced_evidence=[], relation="generated_from",
                claim_locator_blocks=frozenset({"B2"}),
                obligation_hashes=hashes,
            )
            self.assertEqual(edge["target_source_anchors"], [])
            self.assertIs(edge["target_source_anchor_stale"], True)
            # 伪锚被块集合同剔除（mismatch=1）；合法锚被 B2 辖域过滤（不计 mismatch）
            self.assertEqual(edge["target_source_anchor_text_mismatch"], 1)

    def test_semantic_validation_rejects_forged_anchor_fields(self) -> None:
        """三轮复审 P2：sentence_index=999 / match_method=forged 的锚不得通过。"""
        from claim_ledger import _edge, functional_anchor_obligation_hashes

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_corpus(root)
            hashes = functional_anchor_obligation_hashes(root)
            target = {
                "target_requirement_id": "FRE-X",
                "target_fingerprint": "fp",
                "review": {
                    "status": "unreviewed", "eligibility": "active",
                    "target_review_revision": "rev",
                    "review_adapter_version": "ai-review-adapter-v1",
                },
                "source_anchors": [
                    {   # 伪句序：unit/hash 正确但 sentence_index=999
                        "section_id": "4.1", "sentence_index": 999, "unit_index": 0,
                        "block_ids": ["B1"],
                        "source_text_hash": hashes[("4.1", 0)]["source_text_hash"],
                        "match_method": "lexical",
                    },
                    {   # 伪造方法名：字段齐全但 match_method=forged
                        "section_id": "4.1", "sentence_index": 0, "unit_index": 0,
                        "block_ids": ["B1"],
                        "source_text_hash": hashes[("4.1", 0)]["source_text_hash"],
                        "match_method": "forged",
                    },
                    {   # 合法锚（对照组）
                        "section_id": "4.1", "sentence_index": 0, "unit_index": 0,
                        "block_ids": ["B1"],
                        "source_text_hash": hashes[("4.1", 0)]["source_text_hash"],
                        "match_method": "lexical",
                    },
                ],
            }
            edge = _edge(
                target, claim_hash="sha256:c", target_generation_id="g",
                produced_evidence=[], relation="generated_from",
                claim_locator_blocks=frozenset({"B1"}),
                obligation_hashes=hashes,
            )
            self.assertEqual(len(edge["target_source_anchors"]), 1)
            self.assertEqual(edge["target_source_anchor_text_mismatch"], 2)
            self.assertNotIn("target_source_anchor_stale", edge)  # 合法锚保住 edge

    def test_republish_after_clause_tamper_marks_group_not_validated(self) -> None:
        """条款义务文本被改动后重发布：旧锚哈希失配 → 组不再 validated（不闭合 claim）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            result = _execute(root, proposal, chat_with_meta=_chat_v2_with_meta([]))
            self.assertEqual(result["lifecycle"], "executed")
            validated_before = [
                g for g in _read_jsonl(root / "claim_coverage_groups.jsonl")
                if g.get("status") == "validated"]
            self.assertTrue(validated_before)

            # 篡改条款文本 → 义务单元哈希全变（锚里的旧哈希全部失配）
            tampered = B1_TEXT.replace("log events", "record events")
            newline = chr(10)
            (root / "chunks.jsonl").write_text(newline.join([
                json.dumps({"section_path": ["4.1"], "heading": "4.1",
                            "text": tampered, "block_ids": ["B1"]},
                           ensure_ascii=False),
                json.dumps({"section_path": ["4.2"], "heading": "4.2",
                            "text": B2_TEXT, "block_ids": ["B2"]},
                           ensure_ascii=False),
            ]) + newline, encoding="utf-8")
            (root / "blocks.jsonl").write_text(newline.join([
                json.dumps({"block_id": "B1", "section_path": ["4.1"],
                            "text": tampered}, ensure_ascii=False),
                json.dumps({"block_id": "B2", "section_path": ["4.2"],
                            "text": B2_TEXT}, ensure_ascii=False),
            ]) + newline, encoding="utf-8")
            from functional_reextract import republish_functional_claim_shadow

            republish_functional_claim_shadow(root, route="openai_compatible")
            groups_after = _read_jsonl(root / "claim_coverage_groups.jsonl")
            # 篡改条款(4.1)的锚哈希全部失配 → 4.1 不得再有 validated 组;
            # 未篡改条款(4.2)的锚仍匹配 → 保持 validated(精细而非一刀切)。
            validated_after = [
                g for g in groups_after if g.get("status") == "validated"]
            self.assertTrue(validated_after)
            for group in validated_after:
                sections = {
                    str(a.get("section_id") or "")
                    for edge in (group.get("edges") or [])
                    for a in (edge.get("target_source_anchors") or [])
                }
                self.assertNotIn("4.1", sections, group)


class SourceAnchorProjectionTests(unittest.TestCase):
    def test_projection_drops_unlocatable_anchor_and_edge_marks_stale(self) -> None:
        import claim_ledger

        requirement = {
            "evidence_anchors": [
                {   # 六字段齐全——进 edge
                    "section_id": "4.2", "block_ids": ["B2"],
                    "sentence_index": 0, "unit_index": 0,
                    "source_text_hash": "a" * 64, "match_method": "lexical",
                    "kind": "obligation", "origin": "home",
                    "quote": "The gateway shall forward alarms.",
                },
                # 复审 P2 二轮：缺 match_method/source_text_hash 的不完整锚
                # （只有 section/block/unit/hash 之类）——六字段合同下剔除
                {"section_id": "9.9", "block_ids": ["B9"], "unit_index": 0,
                 "source_text_hash": "b" * 64},
                {"block_ids": ["B8"]},  # 无 section_id——不可定位，剔除
            ],
        }
        anchors = claim_ledger.functional_source_anchors(requirement)
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["section_id"], "4.2")
        self.assertEqual(anchors[0]["block_ids"], ["B2"])
        # 只投影 §4.4 指定的身份字段（quote/kind/origin 不进 edge）
        self.assertNotIn("quote", anchors[0])
        self.assertNotIn("kind", anchors[0])

        target = {
            "target_requirement_id": "FRE-X",
            "target_fingerprint": "sha256:x",
            "review": {
                "status": "unreviewed",
                "eligibility": "active",
                "target_review_revision": "sha256:r",
                "review_adapter_version": "v",
            },
            "source_anchors": anchors,
        }
        claim = {"claim_hash": "sha256:c", "locator": {"block_id": "B2"}}
        edge = claim_ledger._edge(
            target, claim_hash="sha256:c", target_generation_id="sha256:g",
            produced_evidence=[], relation="generated_from",
            claim_locator_blocks=claim_ledger._claim_locator_blocks(claim),
        )
        self.assertEqual(
            [anchor["block_ids"] for anchor in edge["target_source_anchors"]],
            [["B2"]])
        self.assertNotIn("target_source_anchor_stale", edge)

        foreign_claim = {"claim_hash": "sha256:c", "locator": {"block_id": "B7"}}
        stale_edge = claim_ledger._edge(
            target, claim_hash="sha256:c", target_generation_id="sha256:g",
            produced_evidence=[], relation="generated_from",
            claim_locator_blocks=claim_ledger._claim_locator_blocks(foreign_claim),
        )
        self.assertEqual(stale_edge["target_source_anchors"], [])
        self.assertIs(stale_edge["target_source_anchor_stale"], True)

        # 原子目标（无锚）不加该键——既有行为不变
        atomic_target = {**target, "source_anchors": []}
        atomic_edge = claim_ledger._edge(
            atomic_target, claim_hash="sha256:c", target_generation_id="sha256:g",
            produced_evidence=[], relation="generated_from",
            claim_locator_blocks=frozenset({"B2"}),
        )
        self.assertNotIn("target_source_anchors", atomic_edge)
        self.assertNotIn("target_source_anchor_stale", atomic_edge)


class PreparedPublicationRecoveryTests(unittest.TestCase):
    """复审四轮 P1-1：产品替换后、requirements_published 落账前的中断窗口。

    复现①：on_requirements_published 抛异常（WAL 追加失败）→ 队列不得记
    reextract_failed 终态，按 prepared 哈希路由（产品==新哈希 → 补记 published
    走确定性恢复），同幂等键重放不死锁、不重复付费；
    复现②：产品替换后、WAL 前进程退出（SystemExit 穿透 except Exception）→
    恢复器按哈希比对补记 requirements_published 进 rebuild_pending；产品不变
    （==旧哈希）按未发布处理；哈希均不等按 CAS 冲突。
    """

    def _patch_append(self, *, crash: bool = False, tamper: Path | None = None):
        """让 requirements_published 的 WAL 落账失败。

        ``crash=True`` 用 SystemExit（BaseException，穿透 except Exception——
        等价"进程在替换后、WAL 前退出"）；否则 OSError（普通异常，走队列
        except 路由）。``tamper`` 在失败瞬间改写 functional 产品（制造"当前
        哈希与新旧均不等"的 CAS 冲突窗口）。
        """
        real_append = execution._append_event

        def failing_append(root, event, *, operation_lock_held):
            if event.get("event_kind") != "requirements_published":
                return real_append(root, event, operation_lock_held=operation_lock_held)
            if tamper is not None:
                tamper.write_text("{}\n", encoding="utf-8")
            if crash:
                raise SystemExit("crash between product replace and WAL append")
            raise OSError("attempt WAL volume unavailable")

        return mock.patch.object(execution, "_append_event", side_effect=failing_append)

    def _kinds(self, root: Path) -> list[str]:
        return [
            row["event_kind"]
            for row in claim_reextract_attempts.read_attempt_log(root).rows
        ]

    def test_wal_append_failure_after_replace_routes_to_deterministic_recovery(self) -> None:
        """复现①：WAL 追加异常 → 不落 reextract_failed，重放确定性恢复不死锁。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            old_bytes = (root / "functional_requirements.json").read_bytes()

            calls: list[str] = []
            with self._patch_append(), self.assertRaises(
                execution.ClaimQueueExecutionUnavailable,
            ) as ctx:
                _execute(root, proposal, chat_with_meta=_chat_v2_with_meta(calls), key="wal-1")

            # 路由结果：产品已替换 + prepared 已持久化 → rebuild_pending 可重试，
            # 绝不是 reextract_failed 终态。
            self.assertEqual(ctx.exception.result["lifecycle"], "rebuild_pending")
            self.assertTrue(ctx.exception.result["retryable"])
            kinds = self._kinds(root)
            self.assertIn("publication_prepared", kinds)
            self.assertNotIn("requirements_published", kinds)
            self.assertFalse(
                set(kinds) & {
                    "reextract_failed", "reextract_succeeded",
                    "reextract_interrupted", "reextract_aborted_stale",
                },
                kinds,
            )
            # 产品已被替换（新哈希在场），不得回滚
            self.assertNotEqual(
                (root / "functional_requirements.json").read_bytes(), old_bytes)

            # 同幂等键重放：execute 入口的孤儿恢复按 prepared 哈希补记
            # requirements_published → rebuild_pending → 确定性重建（零付费调用）
            def refusing_chat(*_args, **_kwargs):
                raise AssertionError(
                    "deterministic recovery must not repeat the paid chat")

            second = _execute(root, proposal, chat_with_meta=refusing_chat, key="wal-1")

        self.assertEqual(second["lifecycle"], "executed")
        self.assertEqual(second["resolution"], "covered")
        self.assertEqual(len(calls), 1, "paid chat must have run exactly once")

    def test_wal_append_failure_with_foreign_product_is_cas_conflict(self) -> None:
        """复现①变体：落账失败瞬间产品已他变（哈希均不等）→ 既有 CAS 冲突路径。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            with self._patch_append(
                tamper=root / "functional_requirements.json",
            ), self.assertRaises(execution.ClaimQueueExecutionConflict):
                _execute(root, proposal, chat_with_meta=_chat_v2_with_meta(), key="cas-1")
            rows = claim_reextract_attempts.read_attempt_log(root).rows

        terminal = rows[-1]
        self.assertEqual(terminal["event_kind"], "reextract_aborted_stale")
        self.assertEqual(terminal["outcome"]["code"], "recovery_target_changed")
        self.assertNotIn(
            "requirements_published", [row["event_kind"] for row in rows])

    def test_process_exit_between_replace_and_wal_recovers_publication_fact(self) -> None:
        """复现②主路径：替换后、WAL 前进程退出 → 恢复器补记 published 进
        rebuild_pending（publication 哈希与权威口径一致，可直接过重放护栏）。"""
        from claim_artifacts import file_sha256
        from claim_review_actions import _load_b_track_authority

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            with self._patch_append(crash=True), self.assertRaises(SystemExit):
                _execute(root, proposal, chat_with_meta=_chat_v2_with_meta(), key="crash-1")
            new_bytes = (root / "functional_requirements.json").read_bytes()

            kinds = self._kinds(root)
            self.assertIn("publication_prepared", kinds)
            self.assertNotIn("requirements_published", kinds)
            # SystemExit 穿透 except Exception：没有任何终态
            self.assertFalse(
                set(kinds) & {
                    "reextract_failed", "reextract_succeeded",
                    "reextract_interrupted", "reextract_aborted_stale",
                },
                kinds,
            )

            recovery = claim_reextract_attempts.recover_interrupted_attempts(root)
            self.assertEqual(recovery["recovered"], 1)

            rows = claim_reextract_attempts.read_attempt_log(root).rows
            attempt = claim_reextract_attempts.attempt_id(
                proposal["proposal_id"], "crash-1")
            state = claim_reextract_attempts.derive_attempt_states(rows)[attempt]
            published = [
                row for row in rows if row["event_kind"] == "requirements_published"
            ]
            authority_revision = _load_b_track_authority(root)[
                "target_publication_revision"]
            product_sha = file_sha256(root / "functional_requirements.json")
            # 恢复器只记账，不改产品
            self.assertEqual(
                (root / "functional_requirements.json").read_bytes(), new_bytes)

        self.assertEqual(state["lifecycle"], "rebuild_pending")
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["requirements_sha256"], product_sha)
        # 补记的 publication revision 必须与权威口径一致（重放护栏比对项）
        self.assertEqual(
            published[0]["target_publication_revision"], authority_revision)

    def test_recovery_treats_unchanged_product_as_unpublished(self) -> None:
        """复现②变体：prepared 已落账但产品未替换（当前==旧哈希）→ 未发布，
        interrupted 可重试终态。"""
        real_replace = fe._replace_with_retry

        def crash_replace(source: Path, target: Path):
            if target.name == "functional_requirements.json":
                raise SystemExit("crash between prepared WAL and product replace")
            return real_replace(source, target)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            before = (root / "functional_requirements.json").read_bytes()
            with mock.patch.object(fe, "_replace_with_retry", side_effect=crash_replace), \
                    self.assertRaises(SystemExit):
                _execute(root, proposal, chat_with_meta=_chat_v2_with_meta(), key="pre-1")

            self.assertIn("publication_prepared", self._kinds(root))
            self.assertEqual(
                (root / "functional_requirements.json").read_bytes(), before)

            recovery = claim_reextract_attempts.recover_interrupted_attempts(root)
            rows = claim_reextract_attempts.read_attempt_log(root).rows
            attempt = claim_reextract_attempts.attempt_id(
                proposal["proposal_id"], "pre-1")
            state = claim_reextract_attempts.derive_attempt_states(rows)[attempt]

        self.assertEqual(recovery["interrupted"], 1)
        self.assertEqual(state["lifecycle"], "interrupted")
        self.assertEqual(rows[-1]["event_kind"], "reextract_interrupted")
        self.assertEqual(
            rows[-1]["outcome"]["code"], "process_interrupted_before_publication")

    def test_recovery_routes_unknown_product_hash_to_cas_conflict(self) -> None:
        """复现②变体：prepared 后产品被外部改写（哈希均不等）→ CAS 冲突终态。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            with self._patch_append(crash=True), self.assertRaises(SystemExit):
                _execute(root, proposal, chat_with_meta=_chat_v2_with_meta(), key="far-1")
            # 进程退出后、恢复前：外部把产品改写成未知哈希
            (root / "functional_requirements.json").write_text(
                "{}\n", encoding="utf-8")

            recovery = claim_reextract_attempts.recover_interrupted_attempts(root)
            rows = claim_reextract_attempts.read_attempt_log(root).rows
            attempt = claim_reextract_attempts.attempt_id(
                proposal["proposal_id"], "far-1")
            state = claim_reextract_attempts.derive_attempt_states(rows)[attempt]

        self.assertEqual(recovery["conflicted"], 1)
        self.assertEqual(recovery["recovered"], 0)
        self.assertEqual(state["lifecycle"], "aborted_stale")
        self.assertEqual(rows[-1]["event_kind"], "reextract_aborted_stale")
        self.assertEqual(
            rows[-1]["outcome"]["code"], "recovery_target_changed")

    def test_prepared_event_binds_exact_bytes_and_old_hash(self) -> None:
        """prepared 事件的新哈希 == 替换后产品文件的 sha256（确切字节合同）。"""
        import functional_reextract as fr
        from claim_artifacts import file_sha256

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proposal = _seed_direct_mode(root)
            old_hash = fr.functional_product_fingerprint(root)
            result = _execute(root, proposal, chat_with_meta=_chat_v2_with_meta())
            self.assertEqual(result["lifecycle"], "executed")

            rows = claim_reextract_attempts.read_attempt_log(root).rows
            prepared = [
                row for row in rows if row["event_kind"] == "publication_prepared"
            ]
            published = [
                row for row in rows if row["event_kind"] == "requirements_published"
            ]
            product_sha = file_sha256(root / "functional_requirements.json")

        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["target_store"], "functional_requirements.json")
        self.assertEqual(prepared[0]["previous_requirements_sha256"], old_hash)
        self.assertEqual(prepared[0]["requirements_sha256"], product_sha)
        self.assertEqual(published[0]["requirements_sha256"], product_sha)
        self.assertRegex(prepared[0]["supplement_id"], r"^SUP-[0-9a-f]{12}$")

    def test_history_validation_rejects_published_before_prepared(self) -> None:
        """事件顺序合同：requirements_published 不得先于 publication_prepared。"""
        import claim_reextract_attempts as attempts
        from claim_artifacts import hash_json as _hash_json

        def _hash(value: str) -> str:
            return _hash_json("claim-reextract-attempt-test/v1", value)

        def _common(attempt: str, kind: str, suffix: str) -> dict:
            return {
                "attempt_id": attempt,
                "proposal_id": "CQP-12345678-9abcdef0",
                "claim_id": "CLM-" + "0" * 16,
                "claim_hash": _hash("claim"),
                "event_kind": kind,
                "actor": "expert:yyh",
                "idempotency_key": _hash(suffix),
            }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            attempt = attempts.attempt_id("CQP-12345678-9abcdef0", "request-1")
            started = {
                **_common(attempt, "reextract_started", "started"),
                "request_idempotency_key": "request-1",
                "route": "openai_compatible",
                "model": "deepseek-chat",
                "route_config_revision": _hash("route"),
                "budgets": {
                    "max_calls": 1,
                    "max_total_tokens": 4000,
                    "allow_semantic_verifier": False,
                },
                "preconditions": {"claim_effective_revision": _hash("revision")},
                "focus": {"kind": "text_span", "block_id": "B1", "start": 0, "end": 5},
            }
            attempts.append_attempt_events(root, [started])
            with self.assertRaisesRegex(
                attempts.ClaimReextractAttemptError,
                "follows the requirements publication",
            ):
                attempts.append_attempt_events(root, [
                    {
                        **_common(attempt, "supplement_persisted", "supplement"),
                        "supplement_id": "SUP-" + "0" * 12,
                        "supplement_hash": _hash("supplement"),
                    },
                    {
                        **_common(attempt, "requirements_published", "published"),
                        "requirements_sha256": _hash("new"),
                        "target_publication_revision": _hash("publication"),
                    },
                    {
                        **_common(attempt, "publication_prepared", "prepared"),
                        "target_store": "functional_requirements.json",
                        "requirements_sha256": _hash("new"),
                        "previous_requirements_sha256": _hash("old"),
                    },
                ])


if __name__ == "__main__":
    unittest.main()
