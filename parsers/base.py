from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from doc_ir import DocumentIR


class DocumentParser(ABC):
    source_format: str

    @abstractmethod
    def parse(self, path: Path) -> DocumentIR:
        """Parse a source document into DocumentIR."""
