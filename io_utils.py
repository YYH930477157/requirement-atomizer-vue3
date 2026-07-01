"""共用 JSONL 读取助手（D1 去重：此前 read_jsonl 在 10 处模块各复制一份，且已出现行为分叉——
engineering_composer 用 utf-8-sig 防御 BOM，其余用 utf-8。统一在此一处，utf-8-sig 是
utf-8 的超集（无 BOM 时行为完全一致），合并零风险。）

写入侧仍由 output_writer.write_jsonl / write_json 提供，不在此重复。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
