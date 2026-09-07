"""Execution boundary between intact functional requirements and legacy atoms.

Old result directories have no track declaration. Keep them readable without
inventing provenance; only a new, explicit functional manifest forbids A stages.
"""
from __future__ import annotations

import json
from pathlib import Path

LEGACY_STAGES = frozenset({"llm-review", "assemble", "compose"})


def resolve_run_track(track: str | None, *, skip_review: bool) -> str:
    if track not in {None, "functional", "legacy_a"}:
        raise ValueError(f"未知需求流程：{track}")
    if track == "functional" and not skip_review:
        raise ValueError("完整需求流程不支持逐原子审查；请使用 --skip-review，或显式选择 --track legacy_a。")
    if track is not None:
        return track
    # Compatibility for older desktop bridges and scripts. New UI sends track.
    from functional_extract import functional_extract_enabled

    return "functional" if functional_extract_enabled() and skip_review else "legacy_a"


def result_track(out_dir: Path) -> str:
    from result_package import resolve_analysis_root

    manifest_path = resolve_analysis_root(out_dir) / "manifest.json"
    if not manifest_path.exists():
        return "unknown"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("结果 manifest 必须是 JSON 对象")
    track = manifest.get("track")
    if track is None:
        return "unknown"
    if not isinstance(track, str) or track not in {"functional", "legacy_a"}:
        raise ValueError(f"结果包含未知需求流程：{track}")
    return track


def require_legacy_track(out_dir: Path, stage: str) -> None:
    if result_track(out_dir) == "functional":
        raise ValueError(
            f"{stage} 仅支持旧兼容流程，当前结果为完整需求流程。"
            "完整需求请使用 functional-extract；如需旧流程，请重新运行文档解析"
            "（命令行：run --track legacy_a）；不能在完整需求结果上补跑原子阶段。"
        )


def track_contract(out_dir: Path) -> dict:
    track = result_track(out_dir)
    return {
        "schema": "pipeline-track/v1",
        "track": track,
        "source": "manifest" if track != "unknown" else "undeclared",
        "functional_requirements_endpoint": "/functional-requirements",
        "legacy_requirements_endpoint": "/requirements",
        "legacy_stages_allowed": track != "functional",
    }
