from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from resources import package_root


class ResourcePathTests(unittest.TestCase):
    def test_package_root_uses_source_module_directory_when_not_frozen(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(package_root(), Path(__file__).resolve().parents[1])

    def test_package_root_uses_executable_directory_when_frozen(self) -> None:
        exe_path = Path("D:/dist/RequirementAtomizer/ratomizer.exe")

        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(exe_path)):
            self.assertEqual(package_root(), exe_path.parent)


if __name__ == "__main__":
    unittest.main()
