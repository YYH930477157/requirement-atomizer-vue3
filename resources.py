from __future__ import annotations

import sys
from pathlib import Path


def package_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        meipass = getattr(sys, "_MEIPASS", "")
        meipass_dir = Path(meipass).resolve() if meipass else None
        # PyInstaller onefile：_MEIPASS 是运行时解压出来的独立临时目录（与 exe 本体不同），
        # datas（schemas/llm_agents/...）的权威位置在这里。必须先于 backend 启发式判定，
        # 否则 electron 把 onefile exe 放进 <resources>/backend/ 且 <resources>/llm_agents
        # 存在时（electron-builder extraResources 复制的），会被误指到 <resources>/——
        # 而 extraResources 没复制 schemas/，导致 marker schema 加载报 No such file or directory。
        if meipass_dir is not None and meipass_dir != executable_dir:
            return meipass_dir
        # onedir / 文件夹冻结（ratomizer.spec COLLECT）：exe 落在 backend/ 子目录，
        # datas 与 exe 父目录同级；用 llm_agents 作存在性标志确认该布局。
        if executable_dir.name == "backend" and (executable_dir.parent / "llm_agents").exists():
            return executable_dir.parent
        if meipass_dir is not None:
            return meipass_dir
        return executable_dir
    return Path(__file__).resolve().parent
