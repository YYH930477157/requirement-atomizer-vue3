from __future__ import annotations

import sys
from pathlib import Path


def package_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        if executable_dir.name == "backend" and (executable_dir.parent / "llm_agents").exists():
            return executable_dir.parent
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass).resolve()
        return executable_dir
    return Path(__file__).resolve().parent
