"""配置注册表强制核对（F5）：代码里出现的 RATOMIZER_* 环境变量必须全部登记在 config.ENV_REGISTRY。"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from config import ENV_NAMES

REPO = Path(__file__).resolve().parent.parent
_ENV_RE = re.compile(r"RATOMIZER_[A-Z_]+")
# 非环境变量的同前缀标识符（协议前缀等）
_EXCLUDED = {"RATOMIZER_PROGRESS__", "RATOMIZER_PROGRESS", "RATOMIZER_",
             "RATOMIZER_LLM_"}   # llm_pipeline 里的动态前缀拼接，非独立变量


def _scan() -> set[str]:
    found: set[str] = set()
    files = list(REPO.glob("*.py")) + list((REPO / "ui" / "electron").glob("*.cjs"))
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in _ENV_RE.finditer(text):
            found.add(m.group(0))
    return found - _EXCLUDED


class ConfigRegistryTests(unittest.TestCase):
    def test_all_env_vars_registered(self) -> None:
        unregistered = sorted(_scan() - ENV_NAMES)
        self.assertEqual(unregistered, [],
                         f"发现未登记的环境变量（先在 config.ENV_REGISTRY 登记）: {unregistered}")

    def test_registry_names_actually_used(self) -> None:
        """反向：注册表里的名字须在代码里真实存在（防注册表烂尾成文档摆设）。"""
        used = _scan()
        stale = sorted(name for name in ENV_NAMES
                       if name not in used and name != "RATOMIZER_ADJUDICATION_BANK")
        self.assertEqual(stale, [], f"注册表中未被代码使用的名字: {stale}")

    def test_describe_renders(self) -> None:
        from config import describe
        table = describe()
        self.assertIn("RATOMIZER_LLM_CONCURRENCY", table)
