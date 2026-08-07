"""裁决样本库回归：accepted→范例入库、rejected→负例、检索确定性、富化注入。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import adjudication_bank as ab
from llm_pipeline import write_jsonl


def seed_out(tmp: Path) -> None:
    write_jsonl(tmp / "ai_requirements.jsonl", [
        {"title": "时钟精度要求", "description": "时钟精度须优于每天 5 秒",
         "source_quote": "clock accuracy within 5 s per day", "source_block_ids": ["B1"],
         "module": "时钟", "sub_items": [], "acceptance_criteria": ["24h 偏差 ≤5s"]},
        {"title": "垃圾条目", "description": "应拒绝", "source_quote": "noise",
         "source_block_ids": ["B2"], "module": "时钟"},
    ])
    from ai_review_actions import source_ai_requirement_id
    reqs = [json.loads(l) for l in (tmp / "ai_requirements.jsonl").read_text(encoding="utf-8").splitlines()]
    states = [
        {"ai_req_id": source_ai_requirement_id(reqs[0]), "status": "accepted",
         "module_override": "", "reason": ""},
        {"ai_req_id": source_ai_requirement_id(reqs[1]), "status": "rejected",
         "module_override": "", "reason": "抽取噪声"},
    ]
    write_jsonl(tmp / "ai_review_states.jsonl", states)


def seed_transition(tmp: Path, status: str, *, suspicious: bool = False) -> str:
    rid = "AIR-transition"
    requirement = {
        "ai_req_id": rid,
        "title": "Clock accuracy requirement",
        "description": "Clock accuracy shall remain within five seconds per day.",
        "source_quote": "clock accuracy within five seconds per day",
        "source_block_ids": ["B-transition"],
        "module": "clock",
        "suspicion_reasons": ["unverified"] if suspicious else [],
    }
    write_jsonl(tmp / "ai_requirements.jsonl", [requirement])
    write_jsonl(tmp / "ai_review_states.jsonl", [{
        "ai_req_id": rid,
        "status": status,
        "reason": "latest decision",
    }])
    return rid


class BankTests(unittest.TestCase):
    def test_custom_module_vocabulary_accumulates_across_documents_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bank_path = root / "bank.json"
            for index in (1, 2):
                out = root / f"out-{index}"
                out.mkdir()
                write_jsonl(out / "ai_requirements.jsonl", [{
                    "ai_req_id": f"AI-{index}",
                    "title": f"安全通信 {index}",
                    "description": "The meter shall use a secure communication channel.",
                    "source_quote": f"Secure communication channel {index} shall be used.",
                    "source_block_ids": [f"B-{index}"],
                    "module": "通信协议",
                }])
                write_jsonl(out / "ai_review_states.jsonl", [{
                    "ai_req_id": f"AI-{index}",
                    "status": "accepted",
                    "module_override": "通信安全",
                }])
                ab.update_bank(bank_path, out)
                ab.update_bank(bank_path, out)

            bank = ab.load_bank(bank_path)

        self.assertEqual(bank["modules"]["通信安全"]["count"], 2)
        self.assertEqual(ab.module_vocabulary(bank), ["通信安全"])

    def test_harvest_accept_and_reject(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed_out(tmp)
            bank_path = tmp / "bank.json"
            report = ab.update_bank(bank_path, tmp)
            self.assertEqual(report["accepted_total"], 1)
            self.assertEqual(report["rejected_total"], 1)
            bank = ab.load_bank(bank_path)
            ex = next(iter(bank["accepted"].values()))
            self.assertEqual(ex["module"], "时钟")
            self.assertIn("5 秒", ex["description"])
            neg = next(iter(bank["rejected"].values()))
            self.assertEqual(neg["reason"], "抽取噪声")

    def test_harvest_idempotent_latest_wins(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            seed_out(tmp)
            bank_path = tmp / "bank.json"
            ab.update_bank(bank_path, tmp)
            report = ab.update_bank(bank_path, tmp)          # 重复收割不膨胀
            self.assertEqual(report["accepted_total"], 1)

    def test_latest_rejection_removes_previously_accepted_exemplar(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bank_path = tmp / "bank.json"
            rid = seed_transition(tmp, "accepted")
            ab.update_bank(bank_path, tmp)

            seed_transition(tmp, "rejected")
            ab.update_bank(bank_path, tmp)
            bank = ab.load_bank(bank_path)

            self.assertNotIn(rid, bank["accepted"])
            self.assertIn(rid, bank["rejected"])
            self.assertEqual(ab.select_exemplars(bank, "clock", "clock accuracy"), [])

    def test_latest_acceptance_removes_previously_rejected_example(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bank_path = tmp / "bank.json"
            rid = seed_transition(tmp, "rejected")
            ab.update_bank(bank_path, tmp)

            seed_transition(tmp, "accepted")
            ab.update_bank(bank_path, tmp)
            bank = ab.load_bank(bank_path)

            self.assertIn(rid, bank["accepted"])
            self.assertNotIn(rid, bank["rejected"])

    def test_non_final_or_suspicious_status_removes_stale_exemplar(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bank_path = tmp / "bank.json"
            rid = seed_transition(tmp, "accepted")
            ab.update_bank(bank_path, tmp)

            seed_transition(tmp, "needs_discussion")
            ab.update_bank(bank_path, tmp)
            bank = ab.load_bank(bank_path)
            self.assertNotIn(rid, bank["accepted"])
            self.assertNotIn(rid, bank["rejected"])

            seed_transition(tmp, "accepted")
            ab.update_bank(bank_path, tmp)
            seed_transition(tmp, "accepted", suspicious=True)
            ab.update_bank(bank_path, tmp)
            bank = ab.load_bank(bank_path)
            self.assertNotIn(rid, bank["accepted"])
            self.assertNotIn(rid, bank["rejected"])

    def test_missing_current_decision_keeps_cross_project_exemplar(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bank_path = tmp / "bank.json"
            rid = seed_transition(tmp, "accepted")
            ab.update_bank(bank_path, tmp)

            write_jsonl(tmp / "ai_review_states.jsonl", [])
            ab.update_bank(bank_path, tmp)

            self.assertIn(rid, ab.load_bank(bank_path)["accepted"])

    def test_legacy_overlapping_decisions_prefer_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            bank_path = Path(td) / "bank.json"
            rid = "AIR-legacy-overlap"
            bank_path.write_text(json.dumps({
                "version": 1,
                "accepted": {rid: {
                    "module": "clock",
                    "title": "Stale accepted exemplar",
                    "description": "clock accuracy requirement",
                    "source_quote": "clock accuracy",
                }},
                "rejected": {rid: {
                    "module": "clock",
                    "title": "Stale accepted exemplar",
                    "reason": "later rejected",
                }},
            }), encoding="utf-8")

            bank = ab.load_bank(bank_path)

            self.assertNotIn(rid, bank["accepted"])
            self.assertIn(rid, bank["rejected"])
            self.assertEqual(ab.select_exemplars(bank, "clock", "clock accuracy"), [])

    def test_select_exemplars_module_and_relevance(self) -> None:
        bank = {"accepted": {
            "a": {"module": "时钟", "title": "时钟精度要求", "description": "精度优于 5 秒",
                  "source_quote": "clock accuracy"},
            "b": {"module": "显示", "title": "轮显", "description": "显示轮显", "source_quote": "display"},
        }}
        hits = ab.select_exemplars(bank, "时钟", "时钟精度 clock accuracy 要求")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["title"], "时钟精度要求")     # 异模块不入选
        self.assertEqual(ab.select_exemplars(bank, "时钟", "毫无相关词汇"), [])   # 零重叠不注入

    def test_missing_bank_behaves_empty(self) -> None:
        bank = ab.load_bank(Path("/no/such/bank.json"))
        self.assertEqual(bank["accepted"], {})
        self.assertEqual(ab.select_exemplars(bank, "时钟", "任何"), [])


class EnrichInjectionTests(unittest.TestCase):
    def test_exemplars_and_answers_reach_prompt_and_key(self) -> None:
        from requirements_analysis_agent import build_analysis_prompt
        prompt = build_analysis_prompt([{"ai_req_id": "A"}], {"modules": []},
                                       exemplars="- 【时钟】范例甲：精度优于 5 秒",
                                       answers="问：上限？ 答：每天 5 秒")
        self.assertIn("专家已验收的同模块范例", prompt["user"])
        self.assertIn("范例甲", prompt["user"])
        self.assertIn("客户澄清答复", prompt["user"])
        self.assertIn("视为有据", prompt["user"])

        from requirements_analysis import _enrich_key
        req = {"source_quote": "q", "description": "d", "requirement": "r", "module": "时钟"}
        self.assertNotEqual(_enrich_key(req, "m", "ctxA"), _enrich_key(req, "m", "ctxB"))

    def test_negative_exemplars_reach_prompt_and_no_empty_shell(self) -> None:
        from requirements_analysis_agent import build_analysis_prompt
        prompt = build_analysis_prompt([{"ai_req_id": "A"}], {"modules": []},
                                       negative_exemplars="- 【时钟】被拒绝范例：标题\n  拒绝原因：噪声")
        self.assertIn("专家已拒绝的同模块范例", prompt["user"])
        self.assertIn("被拒绝范例", prompt["user"])
        self.assertIn("请勿重复同类问题", prompt["user"])

        prompt_empty = build_analysis_prompt([{"ai_req_id": "A"}], {"modules": []})
        self.assertNotIn("专家已拒绝", prompt_empty["user"])
        self.assertNotIn("请勿重复同类问题", prompt_empty["user"])

    def test_negative_exemplars_selected_by_rejected_bucket(self) -> None:
        bank = {
            "accepted": {
                "a": {"module": "时钟", "title": "时钟精度要求", "description": "精度优于 5 秒",
                      "source_quote": "clock accuracy"},
            },
            "rejected": {
                "b": {"module": "时钟", "title": "错误精度条目", "description": "clock accuracy 噪声",
                      "reason": "抽取噪声"},
                "c": {"module": "显示", "title": "显示轮显", "description": "显示轮显", "reason": "无关"},
            },
        }
        negs = ab.select_negative_exemplars(bank, "时钟", "时钟精度 clock accuracy 要求")
        self.assertEqual(len(negs), 1)
        self.assertEqual(negs[0]["title"], "错误精度条目")
        self.assertEqual(ab.select_negative_exemplars(bank, "时钟", "毫无相关词汇"), [])

    def test_negative_exemplars_render_format(self) -> None:
        rendered = ab.render_negative_exemplars([
            {"module": "时钟", "title": "噪声条目", "description": "应拒绝", "reason": "抽取噪声"},
        ])
        self.assertIn("专家拒绝", rendered)
        self.assertIn("噪声条目", rendered)
        self.assertIn("拒绝原因：抽取噪声", rendered)

    def test_negative_exemplars_end_to_end_in_analysis_prompt(self) -> None:
        """P0-8：rejected 负例经 adjudication_bank 真正进入 analyze 富化 prompt。"""
        from requirements_analysis_agent import build_analysis_prompt
        from adjudication_bank import render_negative_exemplars, select_negative_exemplars

        bank = {
            "accepted": {},
            "rejected": {
                "r1": {"module": "通信协议", "title": "垃圾 secure channel", "description": "不成立的 secure channel 需求",
                       "reason": "无来源依据"},
            },
        }
        negs = select_negative_exemplars(bank, "通信协议", "通信协议 security channel")
        prompt = build_analysis_prompt([{"ai_req_id": "A", "module": "通信协议"}],
                                       {"modules": []},
                                       negative_exemplars=render_negative_exemplars(negs))
        self.assertIn("专家已拒绝的同模块范例", prompt["user"])
        self.assertIn("垃圾 secure channel", prompt["user"])
        self.assertIn("无来源依据", prompt["user"])
