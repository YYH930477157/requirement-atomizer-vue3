"""T2-2/T2-4 编排环循环 + 演示门禁测试。

用依赖注入的 state_reader/action_runner 驱动循环，证明：
- 缺口计数（extract_working）单调下降直至收敛或达上限；
- 达上限 → NEEDS WORK；预算/授权缺失 → 缺口如实转人工而非伪造完成；
- 失败动作记 error；trace 全部过 schema；verification 候选幂等落人工队列。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator, FormatChecker

from orchestration_gaps import (
    ACTION_HUMAN_REVIEW,
    ACTION_SPOT_EXTRACT,
    Gap,
    GapReport,
    VerificationCandidate,
)
from orchestration_loop import (
    ORCHESTRATION_TRACE_FILE,
    ORCHESTRATION_CANDIDATES_FILE,
    run_orchestration_loop,
    main,
)
from decide_trace import decide_trace_lock  # noqa: F401  -- 确保锁模块可用


_SCHEMA = Draft202012Validator(
    json.loads((Path(__file__).resolve().parent.parent / "schemas"
                / "orchestration_trace.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


def _read_traces(out: Path) -> list[dict]:
    path = out / ORCHESTRATION_TRACE_FILE
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _gap(target: str, *, kind: str = "conservation_open", route: str = "extract",
         action: str = "spot_extract", severity: str = "high", block_id: str = "B2") -> Gap:
    return Gap(kind=kind, target_id=target, severity=severity, route=route,
               action=action, block_id=block_id, evidence={"reason": "test"})


def _report(*, extract=(), human=(), verification=()) -> GapReport:
    gaps = tuple(extract) + tuple(human)
    counts = {k: 0 for k in ("clarification_blocking", "conservation_open",
                             "sampling_escalate", "weakness")}
    for g in gaps:
        counts[g.kind] = counts.get(g.kind, 0) + 1
    return GapReport(
        version="orchestration-gap-v1",
        gaps=gaps,
        counts_by_kind=counts,
        sources_available={"functional_requirements": bool(extract)},
        readiness={"verdict": "NEEDS WORK" if (extract or human) else "READY", "reasons": []},
        verification_candidates=tuple(verification),
    )


def _ok_runner(root: Path, gap: Gap, action: str, actor: str, run_id: str) -> dict:
    return {"status": "ok", "summary": f"fake {action} on {gap.target_id}"}


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        # run_orchestration_loop 需要 blocks.jsonl 用于 _resolve_run_id 兜底与 block 查找
        (self.out / "blocks.jsonl").write_text(
            json.dumps({"block_id": "B2", "text": "shall report", "order": 1}) + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, report, *, max_rounds=8, allow_llm=True, runner=_ok_runner):
        reader = mock.Mock(return_value=report)
        return run_orchestration_loop(
            self.out, max_rounds=max_rounds, allow_llm=allow_llm,
            state_reader=reader, action_runner=runner,
        )


class OrchestrationConvergenceTests(_Base):
    def test_convergence_demo_monotonic_decrease(self) -> None:
        report = _report(extract=(_gap("A"), _gap("B")))
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            summary = self._run(report, max_rounds=8)
        traces = _read_traces(self.out)
        working = [t["state_digest"]["extract_working"] for t in traces]
        # 单调不增，末轮（stop）为 0
        self.assertEqual(working, sorted(working, reverse=True))
        self.assertEqual(working[-1], 0)
        # 三轮：两动作 + 一收敛 stop
        self.assertEqual(len(traces), 3)
        self.assertEqual([t["action"] for t in traces], ["spot_extract", "spot_extract", "stop"])
        self.assertEqual(summary["termination"], "converged")
        self.assertEqual(summary["extract_gaps_addressed"], 2)

    def test_rounds_exhausted_routes_to_needs_work(self) -> None:
        report = _report(extract=(_gap("A"), _gap("B"), _gap("C")))
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            summary = self._run(report, max_rounds=2)
        self.assertEqual(summary["termination"], "rounds_exhausted")
        self.assertTrue(summary["needs_work"])
        self.assertEqual(summary["readiness"], "NEEDS WORK")
        traces = _read_traces(self.out)
        # 2 轮动作都用完，未到 stop
        self.assertEqual(len(traces), 2)
        self.assertTrue(all(t["action"] != "stop" for t in traces))
        working = [t["state_digest"]["extract_working"] for t in traces]
        self.assertEqual(working, [3, 2])  # 单调下降但未到 0

    def test_all_gaps_addressed_at_cap_is_converged_not_exhausted(self) -> None:
        # 用尽轮次但缺口恰好全部处置完 → converged（不过度告警 rounds_exhausted）
        report = _report(extract=(_gap("A"), _gap("B")))
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            summary = self._run(report, max_rounds=2)
        self.assertEqual(summary["termination"], "converged")
        self.assertEqual(summary["extract_gaps_addressed"], 2)

    def test_no_extract_gaps_stops_immediately(self) -> None:
        report = _report()  # 既无 extract 也无 human
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            summary = self._run(report, max_rounds=8)
        self.assertEqual(summary["termination"], "no_extract_gaps")
        self.assertFalse(summary["needs_work"])
        traces = _read_traces(self.out)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["action"], "stop")
        self.assertEqual(traces[0]["state_digest"]["extract_working"], 0)


class OrchestrationAuthorizationTests(_Base):
    def test_unauthorized_routes_extract_gaps_to_human_honestly(self) -> None:
        report = _report(extract=(_gap("A"), _gap("B")))
        runner = mock.Mock(return_value={"status": "ok", "summary": "should not be called"})
        # allow_llm=False → authorized=False（不依赖 _llm_authorized）
        summary = self._run(report, max_rounds=8, allow_llm=False, runner=runner)
        self.assertEqual(summary["termination"], "unauthorized")
        self.assertTrue(summary["needs_work"])
        runner.assert_not_called()  # 绝不发起 LLM 补抽
        traces = _read_traces(self.out)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["action"], "human_review")
        self.assertEqual(traces[0]["result"]["status"], "skipped")  # 不伪造完成
        self.assertFalse(traces[0]["budget"]["llm_authorized"])

    def test_authorized_flag_false_with_llm_env_present_still_unauthorized(self) -> None:
        # allow_llm=True 但 _llm_authorized()=False（无 key）→ 仍走 unauthorized
        report = _report(extract=(_gap("A"),))
        runner = mock.Mock()
        with mock.patch("orchestration_loop._llm_authorized", return_value=False):
            summary = self._run(report, allow_llm=True, runner=runner)
        self.assertEqual(summary["termination"], "unauthorized")
        runner.assert_not_called()


class OrchestrationHonestyTests(_Base):
    def test_failed_action_recorded_as_error_not_completed(self) -> None:
        report = _report(extract=(_gap("A"), _gap("B")))

        def failing(root, gap, action, actor, run_id):
            raise RuntimeError("LLM 端点 503")

        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            summary = self._run(report, runner=failing)
        traces = _read_traces(self.out)
        # 失败动作如实记 error，绝不报 completed；后续轮次继续处置别的缺口
        statuses = [t["result"]["status"] for t in traces if t["action"] != "stop"]
        self.assertTrue(all(s == "error" for s in statuses))
        self.assertEqual(summary["termination"], "converged")  # addressed 集合仍推进收敛
        self.assertEqual(len(summary["failed_actions"]), 2)

    def test_human_gaps_keep_needs_work_even_when_extract_converged(self) -> None:
        report = _report(
            extract=(_gap("A"),),
            human=(Gap("clarification_blocking", "CLR-1", "high", "human", "human_review"),),
        )
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            summary = self._run(report)
        self.assertEqual(summary["termination"], "converged")
        self.assertTrue(summary["needs_work"])  # 人工轨缺口仍在
        self.assertEqual(summary["human_gaps_total"], 1)


class OrchestrationTraceSchemaTests(_Base):
    def test_every_trace_validates_against_schema(self) -> None:
        report = _report(extract=(_gap("A"), _gap("B")))
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            self._run(report)
        traces = _read_traces(self.out)
        self.assertGreaterEqual(len(traces), 2)
        for trace in traces:
            errors = sorted(_SCHEMA.iter_errors(trace), key=lambda e: list(e.absolute_path))
            self.assertEqual(errors, [], f"trace invalid: {errors}")
            self.assertIn(trace["action"], trace["candidates"])


class OrchestrationVerificationCandidatesTests(_Base):
    def test_revision_candidates_written_idempotent(self) -> None:
        cand = VerificationCandidate(
            requirement_id="AIR-001", reason="test_not_completed",
            detail="测试未完成", evidence={"test_completed": False},
        )
        report = _report(extract=(_gap("A"),), verification=(cand,))
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            self._run(report)
        path = self.out / ORCHESTRATION_CANDIDATES_FILE
        self.assertTrue(path.is_file())
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["requirement_id"], "AIR-001")
        self.assertTrue(rows[0]["provenance"].startswith("orchestration:"))

        # 第二次运行：幂等（不重复写）
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            self._run(report)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 1)


class OrchestrationDefaultRunnerTests(_Base):
    def _run_default(self, report, *, max_rounds=8):
        """不注入 action_runner——走真实 _default_action_runner（仅 mock 底层 LLM 调用）。"""
        reader = mock.Mock(return_value=report)
        with mock.patch("orchestration_loop._llm_authorized", return_value=True):
            return run_orchestration_loop(
                self.out, max_rounds=max_rounds, allow_llm=True,
                state_reader=reader,
            )

    def test_targeted_reextract_falls_back_to_spot_extract_when_not_omission_candidate(self) -> None:
        report = _report(extract=(_gap("A", action="targeted_reextract"),))
        with mock.patch("omission_actions.current_omission_candidate_ids", return_value=set()), \
                mock.patch("orchestration_loop._run_spot_extract",
                           return_value={"status": "ok", "summary": "spot ok"}) as mock_spot:
            self._run_default(report)
        # 块不是 omission 候选 → _run_targeted_reextract 抛 _OmissionIneligible → 降级 spot_extract
        mock_spot.assert_called_once()

    def test_extract_gap_without_block_routed_to_human(self) -> None:
        gap = Gap("conservation_open", "doc-only", "high", "extract", "spot_extract", block_id="")
        report = _report(extract=(gap,))
        with mock.patch("orchestration_loop._run_spot_extract") as mock_spot:
            summary = self._run_default(report)
        mock_spot.assert_not_called()  # 无 block_id 不发起补抽
        traces = _read_traces(self.out)
        action_traces = [t for t in traces if t["action"] != "stop"]
        self.assertEqual(action_traces[0]["result"]["status"], "skipped")


class OrchestrationCliTests(_Base):
    def test_main_envelope_ok(self) -> None:
        # 种完整最小文档（blocks + ai_requirements，无 suspicion/守恒/采样/弱词缺口）
        # → 真实 read_gaps 返回 0 缺口 → no_extract_gaps → ok envelope，exit 0
        (self.out / "ai_requirements.jsonl").write_text(
            json.dumps({"ai_req_id": "AIR-1", "title": "x", "source_section": "1",
                        "source_quote": "x", "source_block_ids": ["B2"],
                        "suspicion_reasons": []}) + "\n",
            encoding="utf-8",
        )
        buf = StringIO()
        with redirect_stdout(buf), mock.patch("orchestration_loop._llm_authorized",
                                              return_value=False):
            code = main(["--out-dir", str(self.out), "--max-rounds", "4"])
        self.assertEqual(code, 0)
        envelope = json.loads(buf.getvalue())
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["command"], "orchestrate")
        self.assertEqual(envelope["summary"]["termination"], "no_extract_gaps")

    def test_main_input_error_exit_2(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = main(["--out-dir", str(self.out), "--max-rounds", "999"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(buf.getvalue())["ok"])

    def test_main_missing_artifacts_exit_3(self) -> None:
        empty = Path(tempfile.mkdtemp())
        try:
            buf = StringIO()
            with redirect_stdout(buf):
                code = main(["--out-dir", str(empty)])
            self.assertEqual(code, 3)
            envelope = json.loads(buf.getvalue())
            self.assertFalse(envelope["ok"])
        finally:
            empty.rmdir()


class OrchestrationDesktopWiringTests(_Base):
    def test_orchestrate_task_runs_via_desktop_tasks(self) -> None:
        import desktop_tasks

        (self.out / "ai_requirements.jsonl").write_text(
            json.dumps({"ai_req_id": "AIR-1", "title": "x", "source_section": "1",
                        "source_quote": "x", "source_block_ids": ["B2"],
                        "suspicion_reasons": []}) + "\n",
            encoding="utf-8",
        )
        with mock.patch("orchestration_loop._llm_authorized", return_value=False):
            payload = desktop_tasks.orchestrate_task(self.out, max_rounds=4, allow_llm=False)
        self.assertEqual(payload["kind"], "orchestrate")
        self.assertEqual(payload["summary"]["termination"], "no_extract_gaps")
        self.assertIn("orchestration_trace.jsonl", payload["written"])

    def test_orchestrate_task_env_override_max_rounds(self) -> None:
        import desktop_tasks

        (self.out / "ai_requirements.jsonl").write_text(
            json.dumps({"ai_req_id": "AIR-1", "title": "x", "source_section": "1",
                        "source_quote": "x", "source_block_ids": ["B2"],
                        "suspicion_reasons": []}) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict("os.environ", {"RATOMIZER_ORCHESTRATION_MAX_ROUNDS": "3"}), \
                mock.patch("orchestration_loop._llm_authorized", return_value=False):
            payload = desktop_tasks.orchestrate_task(self.out, allow_llm=False)
        self.assertEqual(payload["summary"]["rounds_max"], 3)


if __name__ == "__main__":
    unittest.main()
