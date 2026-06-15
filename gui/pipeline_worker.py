from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from atomize import run_atomizer_pipeline
from export_requirements import export_requirements
from gui.requirements_model import load_output_bundle
from llm_pipeline import run_review_pipeline


class StageSignalHandler(logging.Handler):
    def __init__(self, worker: "PipelineWorker") -> None:
        super().__init__(logging.INFO)
        self.worker = worker

    def emit(self, record: logging.LogRecord) -> None:
        self.worker.stage.emit(record.getMessage())


class PipelineWorker(QObject):
    stage = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        *,
        input_path: Path | None = None,
        out_dir: Path,
        kb_paths: list[Path] | None = None,
        domain_pack_dir: Path | None = None,
        chunk_chars: int = 3500,
        skip_review: bool = False,
        export_formats: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.input_path = input_path
        self.out_dir = out_dir
        self.kb_paths = kb_paths or []
        self.domain_pack_dir = domain_pack_dir
        self.chunk_chars = chunk_chars
        self.skip_review = skip_review
        self.export_formats = export_formats or []

    @Slot()
    def run(self) -> None:
        logger = logging.getLogger("requirement_atomizer")
        handler = StageSignalHandler(self)
        old_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            payload: dict[str, Any] = {"out_dir": str(self.out_dir.expanduser().resolve())}
            if self.input_path is not None:
                manifest = run_atomizer_pipeline(
                    self.input_path,
                    self.out_dir,
                    chunk_chars=self.chunk_chars,
                    kb_paths=self.kb_paths,
                    domain_pack_dir=self.domain_pack_dir,
                )
                payload["manifest"] = manifest
                if not self.skip_review:
                    payload["review"] = run_review_pipeline(self.out_dir)
                if self.export_formats:
                    payload["exports"] = export_requirements(self.out_dir, formats=self.export_formats)
            payload["bundle"] = load_output_bundle(self.out_dir)
            self.finished.emit(payload)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)


class LoadOutputWorker(QObject):
    stage = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, out_dir: Path) -> None:
        super().__init__()
        self.out_dir = out_dir

    @Slot()
    def run(self) -> None:
        try:
            self.stage.emit("loading output files")
            self.finished.emit({"bundle": load_output_bundle(self.out_dir), "out_dir": str(self.out_dir.expanduser().resolve())})
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class AssembleSpecWorker(QObject):
    """后台装配《DLMS/COSEM 实现规格》：先 assemble() 写机器格式 JSON，
    再 export_spec() 写人读 Word/Markdown。离线确定性（读 out_dir 下的 atomizer
    产物 + 可选 llm_review_results.jsonl），不调实时 LLM。"""

    stage = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    ASSEMBLED_JSON = "dlms_cosem_spec_requirements.json"

    def __init__(self, *, out_dir: Path, formats: list[str] | None = None) -> None:
        super().__init__()
        self.out_dir = out_dir
        self.formats = formats if formats is not None else ["xlsx", "docx", "md"]

    @Slot()
    def run(self) -> None:
        import datetime
        import json

        from assemble_spec import assemble

        logger = logging.getLogger("requirement_atomizer")
        handler = StageSignalHandler(self)
        old_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            out = self.out_dir.expanduser().resolve()
            reviews = out / "llm_review_results.jsonl"
            reviews_path = reviews if reviews.exists() else None

            self.stage.emit("assembling implementation spec")
            doc, breakdown = assemble(
                out,
                reviews_path,
                source=out.name,
                extracted_at=datetime.datetime.now().isoformat(timespec="seconds"),
            )
            target = out / self.ASSEMBLED_JSON
            target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            written = [str(target)]

            if self.formats:
                self.stage.emit("exporting Word / Markdown")
                from spec_export import export_spec

                written += [str(out / name) for name in export_spec(out, formats=self.formats, reviews_path=reviews_path)]

            self.finished.emit(
                {
                    "kind": "assemble",
                    "out_dir": str(out),
                    "count": len(doc.get("requirements", [])),
                    "analysis": doc.get("analysis", {}),
                    "breakdown": breakdown,
                    "written": written,
                }
            )
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
