"""Word/Excel 影印支路转换层：docx/xlsx → PDF（懒转换，只在批注导出阶段触发）。

首选 Office 自家排版引擎（Windows COM：Word SaveAs2 / Excel ExportAsFixedFormat，保真
最高），LibreOffice `soffice --headless --convert-to pdf` 兜底；两者均不可用返回 None，
调用方如实降级为文本批注视图（不得伪造页图）。

缓存：产物 `document_facsimile.pdf` 以输入文件内容指纹 + DOC_FACSIMILE_VERSION 为键
（sidecar `document_facsimile.pdf.meta.json`），指纹命中不重转。失败的转换如实记录
`facsimile: "unavailable:<reason>"` 进 sidecar 供报告层读取，不缓存失败（环境修复后
重导出即可恢复）。

pywin32 是 Windows 条件依赖；非 win 环境 import 失败必须优雅降级（_convert_via_com
返回 None），不得崩。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

DOC_FACSIMILE_VERSION = "doc-facsimile-v1"
FACSIMILE_PDF = "document_facsimile.pdf"
FACSIMILE_PDF_META = "document_facsimile.pdf.meta.json"
COM_TIMEOUT_S = 100.0
SOFFICE_TIMEOUT_S = 120.0
CONVERTIBLE_SUFFIXES = {".docx", ".xlsx"}
_SOFFICE_FALLBACK = "C:/Program Files/LibreOffice/program/soffice.exe"
# Word SaveAs2 FileFormat=17 (wdFormatPDF)；Excel ExportAsFixedFormat Type=0 (xlTypePDF)
_WORD_PDF_FORMAT = 17
_EXCEL_PDF_FORMAT = 0

LOGGER = logging.getLogger("requirement_atomizer")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def facsimile_sidecar_path(out_dir: Path) -> Path:
    return Path(out_dir) / FACSIMILE_PDF_META


def read_facsimile_status(out_dir: Path) -> str | None:
    """读取最近一次懒转换记录的引擎/降级原因（导出报告如实引用）。"""
    try:
        data = json.loads(facsimile_sidecar_path(out_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    status = data.get("facsimile") if isinstance(data, dict) else None
    return str(status) if status else None


def _cached_facsimile(
    input_path: Path, out_dir: Path, *, input_sha256: str | None = None
) -> Path | None:
    """指纹命中直接复用已转换 PDF；指纹不符/产物缺失 → 重转。

    input_sha256：调用方已算好的输入指纹（convert_to_pdf 每次运行只哈希输入
    一次，缓存判定与 sidecar 写入共用）；None 时现算。"""
    target = Path(out_dir) / FACSIMILE_PDF
    try:
        meta = json.loads(facsimile_sidecar_path(out_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = {
        "version": DOC_FACSIMILE_VERSION,
        "input_sha256": input_sha256 or _file_sha256(input_path),
    }
    if not isinstance(meta, dict) or any(meta.get(key) != value for key, value in expected.items()):
        return None
    try:
        if target.is_file() and target.stat().st_size > 0:
            return target
    except OSError:
        return None
    return None


def _write_facsimile_meta(
    out_dir: Path, *, input_path: Path, facsimile: str, input_sha256: str | None = None
) -> None:
    """原子写转换元数据（tmp + os.replace，Windows 读者锁短重试同既有惯例）。

    input_sha256：调用方已算好的输入指纹（避免转换路径上同一文件哈希两遍）；
    None 时现算。"""
    target = facsimile_sidecar_path(out_dir)
    payload: dict[str, Any] = {
        "version": DOC_FACSIMILE_VERSION,
        "input_sha256": input_sha256 or _file_sha256(input_path),
        "input_name": input_path.name,
        "facsimile": facsimile,
    }
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, target)
                break
            except PermissionError:
                if attempt >= 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)


def _office_app_name(input_path: Path) -> str | None:
    suffix = input_path.suffix.casefold()
    if suffix == ".docx":
        return "Word.Application"
    if suffix == ".xlsx":
        return "Excel.Application"
    return None


def _convert_via_com_inner(input_path: Path, target: Path) -> bool:
    """Office COM 转换：单线程、不可见、禁弹窗、finally 里 Quit + CoUninitialize。

    任何一步失败（无 Office / 非 Windows / pywin32 缺失 / 超时）都返回 False 走兜底，
    绝不把异常抛给调用方——但错误原因记日志，进程清理在 finally 里保证。
    """
    app_name = _office_app_name(input_path)
    if app_name is None:
        return False
    try:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]
    except ImportError:
        LOGGER.info("影印转换：pywin32 不可用，跳过 COM 路径（%s）", input_path.name)
        return False

    converted = False
    app = None
    document = None
    pythoncom.CoInitialize()
    try:
        try:
            app = win32com.client.Dispatch(app_name)
        except Exception as exc:
            LOGGER.info("影印转换：%s COM 不可用（%s），走 LibreOffice 兜底", app_name, exc)
            return False
        app.Visible = False
        try:
            app.DisplayAlerts = 0
        except Exception:  # Excel 部分版本 DisplayAlerts 为只读/异签名——尽力而为
            pass
        if app_name == "Word.Application":
            document = app.Documents.Open(str(input_path), ReadOnly=True)
        else:
            document = app.Workbooks.Open(str(input_path), ReadOnly=True)
        if app_name == "Word.Application":
            document.SaveAs2(str(target), FileFormat=_WORD_PDF_FORMAT)
        else:
            document.ExportAsFixedFormat(_EXCEL_PDF_FORMAT, str(target))
        converted = target.is_file() and target.stat().st_size > 0
        if not converted:
            LOGGER.warning("影印转换：%s COM 未产出 PDF（%s）", app_name, input_path.name)
        return converted
    except Exception as exc:
        LOGGER.warning("影印转换：%s COM 转换失败（%s）", app_name, exc)
        return False
    finally:
        # Office 进程不得残留：先关文档再 Quit，最后反初始化 COM
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _convert_via_com(input_path: Path, target: Path, *, timeout_s: float = COM_TIMEOUT_S) -> bool:
    """COM 转换的超时外壳（2026-08-08 实机 30 分钟卡死修复）。

    历史上的 `_convert_via_com`（现 `_convert_via_com_inner`）声明了 timeout_s 却从未
    使用——COM 调用（Dispatch/Open/SaveAs2）在 Word 弹不可见模态（文件恢复/宏警告/
    字体替换/激活窗）时可**无限期阻塞**，整条 export-annotation-html 流水线随之卡死。
    线程无法杀死一个阻塞中的 COM 调用，所以这里超时的是**等待**：超时即放弃 COM 路径
    走 soffice 兜底（其有真实子进程超时），流水线不再被单点模态锁死。残留的守护线程
    与隐藏 Word 进程可能稍后自行退出；流水线不等待它们。
    """
    outcome: dict[str, bool] = {}

    def _run() -> None:
        try:
            outcome["ok"] = _convert_via_com_inner(input_path, target)
        except Exception as exc:  # 兜底防线：COM 侧任何未预见异常都不得上抛
            LOGGER.warning("影印转换：COM 转换异常（%s）", exc)
            outcome["ok"] = False

    worker = threading.Thread(target=_run, name="doc-facsimile-com", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        LOGGER.warning(
            "影印转换：COM 超时（%.0fs）：%s——Word 可能存在不可见模态弹窗；"
            "放弃 COM 路径走 LibreOffice 兜底（隐藏 Word 进程可手动结束）",
            timeout_s, input_path.name,
        )
        return False
    return outcome.get("ok", False)


def find_soffice() -> str | None:
    """LibreOffice 探测：PATH 优先，其次 Windows 默认安装目录。"""
    found = shutil.which("soffice")
    if found:
        return found
    candidate = Path(_SOFFICE_FALLBACK)
    return str(candidate) if candidate.is_file() else None


def _convert_via_soffice(input_path: Path, out_dir: Path, target: Path,
                         *, timeout_s: float = SOFFICE_TIMEOUT_S) -> bool:
    """LibreOffice 兜底转换（子进程，超时杀进程）。soffice 以输入文件名出 PDF，
    完成后改名到目标指纹位。"""
    soffice = find_soffice()
    if not soffice:
        LOGGER.info("影印转换：LibreOffice 不可用（PATH 与默认目录均未找到 soffice）")
        return False
    work = Path(tempfile.mkdtemp(prefix="facsimile-soffice-", dir=str(out_dir)))
    try:
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf", "--outdir",
                 str(work), str(input_path)],
                check=True, capture_output=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            LOGGER.warning("影印转换：soffice 超时（%.0fs）：%s", timeout_s, input_path.name)
            return False
        except (subprocess.CalledProcessError, OSError) as exc:
            LOGGER.warning("影印转换：soffice 调用失败（%s）", exc)
            return False
        produced = work / f"{input_path.stem}.pdf"
        if not produced.is_file() or produced.stat().st_size <= 0:
            LOGGER.warning("影印转换：soffice 未产出 PDF（%s）", input_path.name)
            return False
        os.replace(produced, target)
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def convert_to_pdf(input_path: Path, work_dir: Path) -> Path | None:
    """docx/xlsx → out/document_facsimile.pdf。返回 (PDF 路径, None) 或 None（无转换器）。

    缓存键 = 输入内容指纹 + DOC_FACSIMILE_VERSION：命中即复用，不重转。
    引擎优先级：Office COM → LibreOffice；两边都不可用 → None（调用方如实降级）。
    转换结果（引擎或降级原因）如实写 sidecar，供导出 manifest/summary 报告。
    """
    input_path = Path(input_path).expanduser().resolve()
    out_dir = Path(work_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if input_path.suffix.casefold() not in CONVERTIBLE_SUFFIXES:
        LOGGER.info("影印转换：不支持的输入格式（%s）", input_path.suffix)
        return None
    if not input_path.is_file():
        LOGGER.warning("影印转换：输入文件不存在：%s", input_path)
        return None
    # 输入指纹每次运行只算一次：缓存判定与 sidecar 写入共用（此前转换路径上
    # 同一文件要哈希两遍）
    input_sha256 = _file_sha256(input_path)
    cached = _cached_facsimile(input_path, out_dir, input_sha256=input_sha256)
    if cached is not None:
        return cached

    target = out_dir / FACSIMILE_PDF
    engine = "unavailable:无可用转换器（Office COM 与 LibreOffice 均不可用）"
    if _convert_via_com(input_path, target):
        engine = "com"
    elif _convert_via_soffice(input_path, out_dir, target):
        engine = "libreoffice"
    if engine.startswith("unavailable"):
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        _write_facsimile_meta(
            out_dir, input_path=input_path, facsimile=engine, input_sha256=input_sha256)
        return None
    _write_facsimile_meta(
        out_dir, input_path=input_path, facsimile=engine, input_sha256=input_sha256)
    return target
