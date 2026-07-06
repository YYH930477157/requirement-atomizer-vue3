"""xlsx 安全保存（架构债 F8）。

真实事故（2026-07-05）：用户开着 software_requirements.xlsx，整条链在最后写盘一步
PermissionError 崩掉。Windows 上 Excel 打开即独占锁——重试一次（用户可能刚好关掉），
仍锁则**加时间戳后缀另存**并如实返回实际路径，绝不让"文件被占用"弄死整跑。
"""
from __future__ import annotations

import datetime
import logging
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("requirement_atomizer")

_RETRY_DELAY_S = 0.5


def safe_save_workbook(workbook: Any, path: Path) -> Path:
    """保存 openpyxl 工作簿；目标被锁时重试一次，仍锁则另存带时间戳副本。

    返回**实际写入路径**（调用方须以返回值上报产物，别假设等于入参）。
    """
    path = Path(path)
    try:
        workbook.save(path)
        return path
    except PermissionError:
        time.sleep(_RETRY_DELAY_S)
        try:
            workbook.save(path)
            return path
        except PermissionError:
            stamp = datetime.datetime.now().strftime("%H%M%S")
            fallback = path.with_name(f"{path.stem}-{stamp}{path.suffix}")
            workbook.save(fallback)
            LOGGER.warning("目标文件被占用（Excel 未关？），已另存：%s", fallback)
            return fallback
