"""V3 WS-A A3：整篇对账（reconcile，第三遍；默认关闭）。

``merged_consistency`` 升级为两段式的第二段载体：**规则筛疑 + LLM 裁定**。
确定性规则（``merged_consistency.screen_reconcile_suspects``，复用既有跨章重复 /
OBIS 数值分歧 / 覆盖缺口三类检测器）先筛出疑似集；LLM **只对疑似集做裁定投票**，
不自由扫描。裁定结果与硬依据分层：

* **编码零漂移硬依据**：疑似成员的受保护编码（OBIS/hex/class_id/标准号）必须能在来源块
  中逐字回指（复用 ``cosem_behavior_spec.extract_codes`` + ``match_source_quote_blocks``
  取证）；无法回指即硬失败，**一票否决** LLM 的放行票（``hard_veto``）。
* **守恒门**：覆盖缺口类疑似本身即守恒证据，硬层不否决、只交由 LLM 语义投票。
* **LLM 仅语义投票**：verdict ∈ confirmed_issue / not_an_issue / uncertain；rationale 里
  臆造来源没有的编码 → 硬拦剔除、该票判 ``invalid_llm_code_drift``，不得形成 cleared 结论。
* **LLM 不可用**（stub/无 key/调用失败/预算耗尽）→ 仅规则筛疑部分产出，
  ``provenance_mode`` 如实标 ``rules_only``，不伪造裁定。

输出 ``reconcile_report.json``（封闭 schema ``reconcile-report/v1``，写盘前 jsonschema
校验落地，governed pipeline 路径 + 原子写），并把摘要并入根目录 ``quality_report.json``
（既有字段零改动，原子替换）。入口开关 ``RATOMIZER_RECONCILE``（默认 ``0``）。测试中
禁止真实 LLM 调用。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Sequence

from cosem_behavior_spec import extract_codes
from requirement_record import provenance

RECONCILE_VERSION = "reconcile-v1"
RECONCILE_PROMPT_VERSION = "reconcile-prompt-v1"
RECONCILE_SCHEMA = "reconcile-report/v1"
RECONCILE_FILENAME = "reconcile_report.json"

LOGGER = logging.getLogger("requirement_atomizer")

# 入口开关（config.ENV_REGISTRY 登记）：默认 0=不跑第三遍对账。
ENTRY_SWITCH_ENV = "RATOMIZER_RECONCILE"

ExtractChat = Callable[[str, str], dict[str, Any]]

# LLM 裁定投票枚举（仅语义投票；硬依据在确定性层）
_LLM_VERDICTS = ("confirmed_issue", "not_an_issue", "uncertain")
_LLM_BATCH = 24  # 单次裁定投票的疑似条数上限（与 claim verifier 批次同量级）

# A-4（2026-08-07）：产物封闭 schema 运行时校验落地。docstring 原声称封闭 schema 但
# 运行时零执行（仅 test_reconcile 在测试侧校验）；现将写盘前 jsonschema 校验接上，
# 构造方与 schema 漂移即 fail-loud，绝不落盘畸形报告。
_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
_SCHEMA_VALIDATOR_CACHE: dict[str, Any] = {}


def _payload_validator(schema_filename: str):
    validator = _SCHEMA_VALIDATOR_CACHE.get(schema_filename)
    if validator is not None:
        return validator
    from jsonschema import Draft202012Validator

    schema = json.loads((_SCHEMA_DIR / schema_filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    _SCHEMA_VALIDATOR_CACHE[schema_filename] = validator
    return validator


def _validate_payload_schema(payload: Any, schema_filename: str, *, label: str) -> None:
    """写盘前对产物做封闭 schema 校验；违例 fail-loud。"""
    errors = sorted(
        _payload_validator(schema_filename).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    raise ValueError(
        f"reconcile {label} 违反封闭 schema {schema_filename} @ {location}: {error.message}"
    )

_SYSTEM_PROMPT = (
    "你是技术标准合并需求的对账裁定员。输入是确定性规则筛出的疑似不一致集合"
    "（跨章重复 / OBIS 数值分歧 / 覆盖缺口），每条带只读证据（引句/编码/章节/成员）。"
    "你只能对给出的疑似条逐条投票，不得扫描或新增疑似：\n"
    "①confirmed_issue=语义上确为冲突/重复/遗漏；②not_an_issue=语义等价或误报；"
    "③uncertain=证据不足。rationale 一句话，只能引用输入证据中出现的编码与表述，"
    "禁止臆造 OBIS/hex/class_id/标准号/数值。拿不准一律 uncertain（宁缺勿猜）。\n"
    "输出 JSON：{\"votes\":[{\"suspect_id\",\"verdict\",\"rationale\"}]}。"
)


# ---------------------------------------------------------------------------
# 入口开关
# ---------------------------------------------------------------------------

def reconcile_enabled(value: str | None = None) -> bool:
    """RATOMIZER_RECONCILE 是否开启（默认关）。"""
    raw = os.environ.get(ENTRY_SWITCH_ENV) if value is None else value
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# 硬依据层（确定性，零 LLM）：编码零漂移逐字回指
# ---------------------------------------------------------------------------

def hard_evidence_check(
    suspect: dict[str, Any],
    requirements_by_id: dict[str, dict[str, Any]],
    source_blocks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """疑似条的硬依据核对：成员文本里的受保护编码必须在来源块逐字回指。

    返回 {"status": "pass"|"fail", "failures": [...]}。覆盖缺口类疑似是守恒证据本身，
    硬层不否决（pass）。回指语料 = 引句匹配块文本 ∪ 声明 source_block_ids 块文本；
    编码在语料中逐字缺席 → ``code_without_verbatim_source`` 硬失败。
    """
    from merged_consistency import match_source_quote_blocks

    kind = str(suspect.get("kind") or "")
    if kind == "coverage_gap":
        return {"status": "pass", "failures": []}
    blocks = [b for b in (source_blocks or []) if isinstance(b, dict)]
    text_by_id = {str(b.get("block_id") or ""): str(b.get("text") or "") for b in blocks}
    failures: list[dict[str, Any]] = []
    for member in suspect.get("members") or []:
        requirement = requirements_by_id.get(str(member))
        if requirement is None:
            continue
        member_text = " ".join(str(requirement.get(k) or "")
                               for k in ("title", "description", "source_quote"))
        codes = sorted(extract_codes(member_text))
        if not codes:
            continue
        corpus_ids = {
            str(b) for b in (requirement.get("source_block_ids") or []) if str(b)
        }
        quote = str(requirement.get("source_quote") or "")
        if quote.strip():
            matched, _method = match_source_quote_blocks(quote, blocks)
            corpus_ids.update(matched)
        corpus = "\n".join(text_by_id.get(bid, "") for bid in sorted(corpus_ids))
        corpus_codes = extract_codes(corpus)
        for code in codes:
            if code not in corpus_codes:
                failures.append({
                    "member": str(member),
                    "code": code,
                    "reason": "code_without_verbatim_source",
                })
    return {"status": "fail" if failures else "pass", "failures": failures}


# ---------------------------------------------------------------------------
# LLM 裁定层（只对疑似集投票；rationale 幻觉编码硬拦）
# ---------------------------------------------------------------------------

def _build_vote_prompt(suspects: Sequence[dict[str, Any]]) -> str:
    compact = [
        {
            "suspect_id": s["suspect_id"],
            "kind": s["kind"],
            "members": s["members"],
            "sections": s["sections"],
            "evidence": s["evidence"],
        }
        for s in suspects
    ]
    return "对以下疑似集逐条投票：\n" + json.dumps({"suspects": compact}, ensure_ascii=False)


def _adjudicate_batch(
    chat: ExtractChat,
    suspects: Sequence[dict[str, Any]],
    source_corpus_codes: set[str],
) -> tuple[dict[str, dict[str, Any]], bool]:
    """单批投票。返回 ({suspect_id: vote}, 返回是否合法)。"""
    raw = chat(_SYSTEM_PROMPT, _build_vote_prompt(suspects))
    if not isinstance(raw, dict) or not isinstance(raw.get("votes"), list):
        return {}, False
    known = {s["suspect_id"] for s in suspects}
    votes: dict[str, dict[str, Any]] = {}
    for entry in raw["votes"]:
        if not isinstance(entry, dict):
            return {}, False
        suspect_id = str(entry.get("suspect_id") or "")
        if suspect_id not in known:
            continue  # LLM 新增/篡改疑似 ID：忽略（只对疑似集投票的纪律）
        verdict = str(entry.get("verdict") or "").strip()
        if verdict not in _LLM_VERDICTS:
            return {}, False
        rationale = str(entry.get("rationale") or "").strip()
        # 幻觉编码硬拦：rationale 里来源全文没有的编码剔除留痕，票判 invalid
        drifted = sorted(extract_codes(rationale) - source_corpus_codes)
        for code in drifted:
            rationale = rationale.replace(code, "")
        votes[suspect_id] = {
            "verdict": "invalid_llm_code_drift" if drifted else verdict,
            "rationale": rationale,
            "rejected_codes": drifted,
        }
    return votes, True


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_reconcile(
    out_dir: Path | str,
    *,
    requirements: Sequence[dict[str, Any]] | None = None,
    blocks: Sequence[dict[str, Any]] | None = None,
    req_like_blocks: Sequence[dict[str, Any]] | None = None,
    route: str | None = "stub",
    chat: ExtractChat | None = None,
    expert_excluded_block_ids: set[str] | None = None,
) -> dict[str, Any]:
    """运行整篇对账，写 reconcile_report.json 并把摘要并入 quality_report.json。"""
    import merged_consistency
    from functional_extract import _resolve_extract_chat

    out_dir = Path(out_dir).expanduser().resolve()
    if requirements is None:
        requirements = _load_requirements(out_dir)
    requirements = [r for r in requirements if isinstance(r, dict)]
    if blocks is None:
        blocks = _load_blocks(out_dir)
    blocks = [b for b in blocks or [] if isinstance(b, dict)]
    if req_like_blocks is None and blocks:
        from extract_units import clean_block_text
        req_like_blocks = [
            b for b in merged_consistency.coverage_denominator_blocks(blocks)
            if clean_block_text(b)
        ]

    suspects = merged_consistency.screen_reconcile_suspects(
        list(requirements),
        list(req_like_blocks) if req_like_blocks is not None else None,
        source_blocks=blocks,
        expert_excluded_block_ids=expert_excluded_block_ids,
    )
    requirements_by_id = {_req_key(r): r for r in requirements}
    source_corpus_codes: set[str] = set()
    for block in blocks:
        source_corpus_codes.update(extract_codes(str(block.get("text") or "")))

    # 硬依据层（确定性）：编码零漂移回指
    hard_by_id: dict[str, dict[str, Any]] = {}
    for suspect in suspects:
        hard_by_id[suspect["suspect_id"]] = hard_evidence_check(
            suspect, requirements_by_id, blocks,
        )

    # LLM 裁定层（只对疑似集投票）
    active_chat, executed_route = _resolve_extract_chat(route, chat)
    votes_by_id: dict[str, dict[str, Any]] = {}
    llm_unavailable_reason: str | None = None
    if active_chat is not None and suspects:
        import llm_client
        try:
            for start in range(0, len(suspects), _LLM_BATCH):
                batch = suspects[start:start + _LLM_BATCH]
                votes, valid = _adjudicate_batch(chat=active_chat, suspects=batch,
                                                 source_corpus_codes=source_corpus_codes)
                if not valid:
                    llm_unavailable_reason = "invalid_llm_payload"
                    break
                votes_by_id.update(votes)
        except llm_client.LLMBudgetExceeded as exc:
            LOGGER.warning("reconcile 预算耗尽，退回 rules_only：%s", exc)
            llm_unavailable_reason = "budget_exhausted"
        except Exception as exc:
            LOGGER.warning("reconcile LLM 裁定失败，退回 rules_only：%s", exc)
            llm_unavailable_reason = "llm_call_failed"
    elif active_chat is None:
        llm_unavailable_reason = "llm_unavailable" if route not in (None, "stub") else None

    mode = "rules_plus_llm" if votes_by_id else "rules_only"

    adjudications: list[dict[str, Any]] = []
    for suspect in suspects:
        hard = hard_by_id[suspect["suspect_id"]]
        vote = votes_by_id.get(suspect["suspect_id"])
        llm_vote = vote["verdict"] if vote else None
        final = _final_outcome(hard["status"], llm_vote, mode)
        adjudications.append({
            "suspect_id": suspect["suspect_id"],
            "kind": suspect["kind"],
            "members": suspect["members"],
            "sections": suspect["sections"],
            "evidence": suspect["evidence"],
            "rule_screen": "suspect",
            "hard_evidence": hard["status"],
            "hard_failures": hard["failures"],
            "llm_vote": llm_vote,
            "llm_rationale": vote["rationale"] if vote else "",
            "rejected_codes": vote["rejected_codes"] if vote else [],
            "final": final,
        })

    summary = {
        "suspects": len(adjudications),
        "hard_veto": sum(1 for a in adjudications if a["final"] == "hard_veto"),
        "llm_confirmed": sum(1 for a in adjudications if a["final"] == "llm_confirmed_issue"),
        "llm_cleared": sum(1 for a in adjudications if a["final"] == "llm_cleared"),
        "uncertain": sum(
            1 for a in adjudications
            if a["final"] in {"llm_uncertain", "llm_vote_invalid"}
        ),
        "rules_only": mode == "rules_only",
    }
    payload: dict[str, Any] = {
        "schema_version": RECONCILE_SCHEMA,
        "producer": RECONCILE_VERSION,
        "prompt_version": RECONCILE_PROMPT_VERSION,
        "provenance": provenance("reconcile", RECONCILE_VERSION),
        "provenance_mode": mode,
        "llm_unavailable_reason": llm_unavailable_reason,
        "route_requested": route or "stub",
        "route": executed_route,
        "requirements_count": len(requirements),
        "summary": summary,
        "adjudications": adjudications,
    }
    _write_report(out_dir, payload)
    attached = _attach_to_quality_report(out_dir, summary, mode)
    return {
        "kind": "reconcile",
        "out_dir": str(out_dir),
        "mode": mode,
        "llm_unavailable_reason": llm_unavailable_reason,
        "summary": summary,
        "quality_report_attached": attached,
        "written": [RECONCILE_FILENAME],
    }


def _final_outcome(hard_status: str, llm_vote: str | None, mode: str) -> str:
    """分层终态：硬依据失败一票否决；LLM 仅语义投票；幻觉票不形成 cleared。"""
    if hard_status == "fail":
        return "hard_veto"
    if llm_vote is None:
        return "rules_only_suspect"
    if llm_vote == "invalid_llm_code_drift":
        return "llm_vote_invalid"
    if llm_vote == "confirmed_issue":
        return "llm_confirmed_issue"
    if llm_vote == "not_an_issue":
        return "llm_cleared"
    return "llm_uncertain"


def _req_key(requirement: dict[str, Any]) -> str:
    for key in ("id", "requirement_id", "ai_req_id", "stable_req_id"):
        value = str(requirement.get(key) or "").strip()
        if value:
            return value
    return str(requirement.get("title") or "")[:40]


# ---------------------------------------------------------------------------
# 产物写盘 / quality_report 摘要并入（原子替换 + PermissionError 重试）
# ---------------------------------------------------------------------------

def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= 5:
                raise
            import time
            time.sleep(0.02 * (attempt + 1))


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    from result_package import governed_artifact_path

    # A-4：写盘前按封闭 schema 校验报告（reconcile-report/v1，additionalProperties 全闭）。
    _validate_payload_schema(payload, "reconcile_report.schema.json", label=RECONCILE_FILENAME)
    target = governed_artifact_path(out_dir, RECONCILE_FILENAME, category="pipeline")
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _replace_with_retry(tmp, target)
    return target


def _attach_to_quality_report(
    out_dir: Path,
    summary: dict[str, Any],
    mode: str,
) -> bool:
    """把对账摘要并入根目录 quality_report.json（既有字段零改动；缺失则不创建）。

    quality_report.json 是根交付物（非 governed 内部产物），沿用 atomize 的根目录寻址；
    写盘走跨进程锁 + 原子替换（与仓库共享状态文件纪律一致）。
    """
    target = out_dir / "quality_report.json"
    if not target.is_file():
        return False
    from process_file_lock import process_file_lock
    from result_package import governed_artifact_path

    lock_path = governed_artifact_path(
        out_dir, "quality_report.lock", category="state", for_write=True
    )
    try:
        with process_file_lock(lock_path, timeout_s=10.0, label="quality_report_reconcile"):
            report = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                return False
            report["reconcile"] = {
                "report_file": RECONCILE_FILENAME,
                "version": RECONCILE_VERSION,
                "mode": mode,
                "suspects": summary["suspects"],
                "hard_veto": summary["hard_veto"],
                "llm_confirmed": summary["llm_confirmed"],
                "llm_cleared": summary["llm_cleared"],
                "uncertain": summary["uncertain"],
            }
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            _replace_with_retry(tmp, target)
        return True
    except Exception as exc:  # noqa: BLE001 — 摘要并入失败不阻断对账产物
        LOGGER.warning("reconcile 摘要并入 quality_report 失败（忽略）：%s", exc)
        return False


# ---------------------------------------------------------------------------
# 输入惰性加载（只读既有产物，不改上游）
# ---------------------------------------------------------------------------

def _load_requirements(out_dir: Path) -> list[dict[str, Any]]:
    merged_path = out_dir / "merged_spec_requirements.json"
    if merged_path.is_file():
        try:
            payload = json.loads(merged_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("requirements"), list):
            return payload["requirements"]
    # 兜底：功能直抽产物（WS2 旁路）
    from result_package import governed_artifact_path

    functional_path = governed_artifact_path(
        out_dir, "functional_requirements.json", category="pipeline", for_write=False
    )
    if functional_path.is_file():
        try:
            payload = json.loads(functional_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return payload["items"]
    return []


def _load_blocks(out_dir: Path) -> list[dict[str, Any]]:
    from io_utils import read_jsonl
    from result_package import governed_artifact_path

    path = governed_artifact_path(out_dir, "blocks.jsonl", category="pipeline", for_write=False)
    return read_jsonl(path) if path.is_file() else []
