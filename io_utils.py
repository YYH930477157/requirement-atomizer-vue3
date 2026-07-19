"""共用 JSONL 读取助手（D1 去重：此前 read_jsonl 在 10 处模块各复制一份，且已出现行为分叉——
engineering_composer 用 utf-8-sig 防御 BOM，其余用 utf-8。统一在此一处，utf-8-sig 是
utf-8 的超集（无 BOM 时行为完全一致），合并零风险。）

常规写入仍由 output_writer.write_jsonl / write_json 提供；这里只在确认追加式缓存的
最后一行是未完成写入时原子移除该残片。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any


LOGGER = logging.getLogger("requirement_atomizer")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读 JSONL：跳过空行，每行一个 JSON 对象。文件不存在返回 []。

    用 utf-8-sig 读：兼容带 BOM 的文件（engineering_composer 的防御需求），无 BOM 时与
    utf-8 行为一致，是安全超集。
    """
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def read_jsonl_recover_torn_tail(path: Path) -> list[dict[str, Any]]:
    """Read an append-only JSONL cache and repair one interrupted final write.

    A recoverable record must be the final physical line and must not have a
    line terminator. Invalid records in the middle, or invalid records that
    were fully terminated, still raise so persistent corruption is visible.
    """
    path = Path(path)
    if not path.exists():
        return []

    raw = path.read_bytes()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    body = raw[len(bom):]
    lines = body.splitlines(keepends=True)
    rows: list[dict[str, Any]] = []

    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            line = stripped.decode("utf-8")
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            is_unterminated_tail = (
                index == len(lines) - 1
                and not raw_line.endswith((b"\n", b"\r"))
            )
            if not is_unterminated_tail:
                raise
            _atomic_replace_bytes(path, bom + b"".join(lines[:index]))
            LOGGER.warning("repaired interrupted final JSONL cache record: %s", path)
            return rows
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row must be an object: {path}:{index + 1}")
        rows.append(row)
    return rows


def _atomic_replace_bytes(path: Path, payload: bytes) -> None:
    """Replace ``path`` atomically with bytes written in the same directory."""
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.{os.getpid()}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
