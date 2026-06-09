from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DomainPack:
    pack_id: str
    name: str
    version: str
    root: Path
    payload: dict[str, Any]

    def resolve_file(self, key: str) -> Path:
        value = (self.payload.get("files") or {}).get(key)
        if not value:
            raise KeyError(f"Domain pack file key not found: {key}")
        return (self.root / str(value)).resolve()

    def knowledge_base_paths(self) -> list[Path]:
        return [(self.root / str(path)).resolve() for path in self.payload.get("knowledge_bases", [])]

    def capability_names(self, kind: str) -> list[str]:
        return list((self.payload.get("capabilities") or {}).get(kind, []))


def load_domain_pack(path: Path) -> DomainPack:
    resolved = path.expanduser().resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    return DomainPack(
        pack_id=str(payload["pack_id"]),
        name=str(payload.get("name") or payload["pack_id"]),
        version=str(payload.get("version") or ""),
        root=resolved.parent,
        payload=payload,
    )
