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

    def test_answers_extend_drift_basis(self) -> None:
        from requirements_analysis_agent import validate_llm_item
        source = {"source_quote": "the meter shall sync", "description": "", "requirement": "",
                  "clarification_answers_text": "答：同步周期 900 秒"}
        item = {"software_requirement_text": "同步周期 900 秒执行一次时钟同步。"}
        issues = validate_llm_item(item, source)
        self.assertFalse(any("fabricated number" in x for x in issues))   # 答复里的数值=有据


if __name__ == "__main__":
    unittest.main()
