"""Install the bundled OfficeCLI runtime for macOS or Windows."""
from __future__ import annotations
import platform, shutil, stat, sys, urllib.request
from pathlib import Path

VERSION = "1.0.148"
ROOT = Path(__file__).resolve().parent / "vendor" / "officecli"

def asset() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "officecli-mac-arm64" if machine in {"arm64", "aarch64"} else "officecli-mac-x64"
    if sys.platform == "win32":
        return "officecli-win-arm64.exe" if machine in {"arm64", "aarch64"} else "officecli-win-x64.exe"
    raise RuntimeError("OfficeCLI 内置运行时仅支持 macOS 和 Windows")

def main() -> int:
    name = asset()
    target = ROOT / ("officecli.exe" if sys.platform == "win32" else "officecli")
    if target.is_file() and target.stat().st_size:
        print(f"OfficeCLI {VERSION} 已安装: {target}")
        return 0
    ROOT.mkdir(parents=True, exist_ok=True)
    urls = [f"https://d.officecli.ai/releases/download/v{VERSION}/{name}", f"https://github.com/iOfficeAI/OfficeCLI/releases/download/v{VERSION}/{name}"]
    last = None
    for url in urls:
        try:
            print(f"下载 {url}")
            with urllib.request.urlopen(url, timeout=300) as response, target.open("wb") as out:
                shutil.copyfileobj(response, out)
            if target.stat().st_size == 0: raise RuntimeError("下载文件为空")
            if sys.platform != "win32": target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            print(f"OfficeCLI {VERSION} 已安装: {target}")
            return 0
        except Exception as exc:
            last = exc
            try: target.unlink()
            except FileNotFoundError: pass
    raise RuntimeError(f"OfficeCLI 下载失败: {last}")

if __name__ == "__main__": raise SystemExit(main())
