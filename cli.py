from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from atomize import AtomizerInputError, AtomizerPipelineError, run_atomizer_pipeline
from export_requirements import export_requirements
from llm_pipeline import run_review_pipeline
from version import __version__


SCHEMA_VERSION = "1.0"
TOOL_NAME = "requirement-atomizer"
LOGGER_NAME = "requirement_atomizer"
SUPPORTED_EXPORT_FORMATS = {"md", "csv"}


def configure_stdio() -> None:
    for stream, kwargs in (
        (sys.stdout, {"encoding": "utf-8"}),
        (sys.stderr, {"encoding": "utf-8", "errors": "replace"}),
    ):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(**kwargs)


class RelativeSecondsFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return f"[{record.relativeCreated / 1000:.3f}s] {record.getMessage()}"


def configure_logging(args: argparse.Namespace) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.propagate = False
    level = logging.INFO
    if getattr(args, "quiet", False):
        level = logging.WARNING
    elif getattr(args, "verbose", False):
        level = logging.DEBUG
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(RelativeSecondsFormatter())
    logger.addHandler(handler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ratomizer", description="Requirement Atomizer command line interface.")
    parser.add_argument("--version", action="store_true", help="Print the requirement-atomizer version and exit.")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Run atomize, review, and optional exports.")
    add_atomize_arguments(run)
    run.add_argument("--skip-review", action="store_true")
    run.add_argument("--export", default="", help="Comma-separated export formats: md,csv")
    add_verbosity_arguments(run)

    atomize = subparsers.add_parser("atomize", help="Run only the atomizer stage.")
    add_atomize_arguments(atomize)
    add_verbosity_arguments(atomize)

    review = subparsers.add_parser("review", help="Run only the review stage.")
    review.add_argument("--out", type=Path, required=True)
    add_verbosity_arguments(review)

    export = subparsers.add_parser("export", help="Export atomic requirements.")
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--format", choices=["md", "csv"], required=True)
    export.add_argument("--status", default="all")
    add_verbosity_arguments(export)

    args = parser.parse_args(argv)
    if args.version:
        return args
    if args.command is None:
        parser.error("a command is required")
    return args


def add_atomize_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kb", type=Path, action="append", default=[])
    parser.add_argument("--domain-pack", type=Path, default=None)
    parser.add_argument("--chunk-chars", type=int, default=3500)


def add_verbosity_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--quiet", action="store_true")
    group.add_argument("--verbose", action="store_true")


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(argv)
    if getattr(args, "version", False):
        print(__version__)
        return 0
    configure_logging(args)

    started = time.perf_counter()
    timing_ms: dict[str, int] = {}
    try:
        if args.command == "run":
            envelope = command_run(args, started, timing_ms)
        elif args.command == "atomize":
            envelope = command_atomize(args, started, timing_ms)
        elif args.command == "review":
            envelope = command_review(args, started, timing_ms)
        elif args.command == "export":
            envelope = command_export(args, started, timing_ms)
        else:
            raise AtomizerInputError(f"Unknown command: {args.command}")
    except AtomizerInputError as exc:
        return write_error(args.command or "", "input_error", str(exc), 2)
    except (AtomizerPipelineError, OSError, ValueError) as exc:
        return write_error(args.command or "", "pipeline_error", str(exc), 3)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return write_error(args.command or "", "unexpected_error", str(exc), 1)

    print(json.dumps(envelope, ensure_ascii=False))
    return 0


def command_run(args: argparse.Namespace, started: float, timing_ms: dict[str, int]) -> dict[str, Any]:
    export_formats = parse_export_formats(args.export)

    atomize_started = time.perf_counter()
    manifest = run_atomizer_pipeline(
        args.input,
        args.out,
        chunk_chars=args.chunk_chars,
        kb_paths=args.kb,
        domain_pack_dir=args.domain_pack,
    )
    timing_ms["atomize"] = elapsed_ms(atomize_started)

    review_summary = None
    if not args.skip_review:
        review_started = time.perf_counter()
        review_summary = run_review_pipeline(args.out)
        timing_ms["review"] = elapsed_ms(review_started)

    exports: list[str] = []
    if export_formats:
        export_started = time.perf_counter()
        exports = export_requirements(args.out, formats=export_formats)
        timing_ms["export"] = elapsed_ms(export_started)

    timing_ms["total"] = elapsed_ms(started)
    return success_envelope(
        "run",
        args.out,
        manifest=manifest,
        review=review_summary,
        exports=exports,
        timing_ms=timing_ms,
    )


def command_atomize(args: argparse.Namespace, started: float, timing_ms: dict[str, int]) -> dict[str, Any]:
    manifest = run_atomizer_pipeline(
        args.input,
        args.out,
        chunk_chars=args.chunk_chars,
        kb_paths=args.kb,
        domain_pack_dir=args.domain_pack,
    )
    timing_ms["atomize"] = elapsed_ms(started)
    timing_ms["total"] = timing_ms["atomize"]
    return success_envelope("atomize", args.out, manifest=manifest, timing_ms=timing_ms)


def command_review(args: argparse.Namespace, started: float, timing_ms: dict[str, int]) -> dict[str, Any]:
    review_summary = run_review_pipeline(args.out)
    timing_ms["review"] = elapsed_ms(started)
    timing_ms["total"] = timing_ms["review"]
    return success_envelope("review", args.out, review=review_summary, timing_ms=timing_ms)


def command_export(args: argparse.Namespace, started: float, timing_ms: dict[str, int]) -> dict[str, Any]:
    exports = export_requirements(args.out, formats=[args.format], status=args.status)
    timing_ms["export"] = elapsed_ms(started)
    timing_ms["total"] = timing_ms["export"]
    return success_envelope("export", args.out, exports=exports, timing_ms=timing_ms)


def success_envelope(
    command: str,
    out_dir: Path,
    *,
    manifest: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    exports: list[str] | None = None,
    timing_ms: dict[str, int] | None = None,
) -> dict[str, Any]:
    quality_summary = quality_summary_for(out_dir)
    return {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "ok": True,
        "output_dir": str(out_dir.expanduser().resolve()),
        "manifest": manifest,
        "review": review,
        "quality_summary": quality_summary,
        "exports": exports or [],
        "timing_ms": timing_ms or {},
    }


def quality_summary_for(out_dir: Path) -> dict[str, Any]:
    path = out_dir.expanduser().resolve() / "quality_report.json"
    if not path.exists():
        return {}
    quality = json.loads(path.read_text(encoding="utf-8"))
    counts = quality.get("counts", {})
    coverage = quality.get("coverage", {})
    return {
        "atomic_requirements": counts.get("atomic_requirements", 0),
        "ambiguous": counts.get("ambiguous_atomic_requirements", 0),
        "low_confidence": counts.get("low_confidence_atomic_requirements", 0),
        "body_table_candidate_ratio": coverage.get("body_table_candidate_ratio", 0),
    }


def write_error(command: str, error_type: str, message: str, exit_code: int) -> int:
    print(message, file=sys.stderr)
    print(
        json.dumps(
            {
                "tool": TOOL_NAME,
                "schema_version": SCHEMA_VERSION,
                "command": command,
                "ok": False,
                "error": {"type": error_type, "message": message},
            },
            ensure_ascii=False,
        )
    )
    return exit_code


def parse_export_formats(value: str) -> list[str]:
    if not value:
        return []
    formats = [item.strip().lower() for item in value.split(",") if item.strip()]
    unsupported = [item for item in formats if item not in SUPPORTED_EXPORT_FORMATS]
    if unsupported:
        supported = ", ".join(sorted(SUPPORTED_EXPORT_FORMATS))
        raise AtomizerInputError(f"Unsupported export format: {', '.join(unsupported)}. Supported formats: {supported}.")
    return formats


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
