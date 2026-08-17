"""PaidCacheStore：统一付费缓存机械（quality-first 方案 §16.1，M7 第一批）。

统一既有零散裸 append 付费缓存（spec_enrich / ai_extract 外围）所需的全部纪律：
governed addressing、跨进程锁 + 进程内 RLock、fsync、原子替换、Windows retry、
撕裂尾行恢复、successful-only（failed/partial 绝不缓存）、命中/未命中/失效遥测。

本模块只提供机械；**迁移既有缓存消费者是逐个进行的**（第一批 spec_enrich），
未迁移的消费者行为零变化。缓存键语义（§16.2 两层缓存 request_identity → 原始
响应 / response_hash + postprocess versions → 派生结果）由调用方通过
``fingerprint`` 字段自带——本存储不猜键。
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from artifact_store import ArtifactStore
from io_utils import read_jsonl_recover_torn_tail

PAID_CACHE_STORE_VERSION = "paid-cache-store-v1"
PAID_CACHE_TELEMETRY_SCHEMA = "paid-cache-telemetry/v1"

_REPLACE_ATTEMPTS = 8
_REPLACE_RETRY_DELAY_S = 0.02


@dataclass
class CacheTelemetry:
    """命中/未命中/失效/写入计数（进程内累积；snapshot 供运行报告）。"""
    hits: int = 0
    misses: int = 0
    invalidations: int = 0
    writes: int = 0
    recovered_torn_tail_lines: int = 0
    dropped_not_successful: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": PAID_CACHE_TELEMETRY_SCHEMA,
            "hits": self.hits,
            "misses": self.misses,
            "invalidations": self.invalidations,
            "writes": self.writes,
            "recovered_torn_tail_lines": self.recovered_torn_tail_lines,
            "dropped_not_successful": self.dropped_not_successful,
        }

    def _event(self, kind: str, fingerprint: str) -> None:
        self.events.append({"kind": kind, "fingerprint": fingerprint,
                            "ts": time.time()})
        # 事件环形截断：遥测不无限增长
        if len(self.events) > 2000:
            del self.events[:1000]


class PaidCacheStore:
    """JSONL 付费缓存：fingerprint → payload（successful-only）。"""

    def __init__(self, out_dir, filename: str, *, category: str = "cache") -> None:
        self._store = ArtifactStore(out_dir, category=category)
        self._resolved_path: Path | None = None
        self.filename = filename
        self.telemetry = CacheTelemetry()

    @classmethod
    def from_file(cls, resolved_path: Path) -> "PaidCacheStore":
        """用已解析（governed）的绝对路径构造——不重复走 governed 寻址。

        供迁移中的既有消费者使用：它们手里已经是 governed_artifact_path 的结果；
        此时 ArtifactStore 的 category 推断会造成二次嵌套寻址，故此类直接持路径。
        锁文件落在缓存文件旁（with_name 构造，不裸拼输出根）。
        """
        store = cls.__new__(cls)
        store._store = None
        store._resolved_path = Path(resolved_path).expanduser().resolve()
        store.filename = store._resolved_path.name
        store.telemetry = CacheTelemetry()
        return store

    def _cache_path(self, *, for_write: bool = False) -> Path:
        if self._resolved_path is not None:
            if for_write:
                self._resolved_path.parent.mkdir(parents=True, exist_ok=True)
            return self._resolved_path
        return self._store.path(self.filename, for_write=for_write)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self._resolved_path is not None:
            from process_file_lock import process_file_lock

            lock_path = self._resolved_path.with_name(
                self._resolved_path.name + ".lock")
            from artifact_store import _process_rlock

            rlock = _process_rlock(self._resolved_path.parent)
            with rlock:
                with process_file_lock(lock_path, timeout_s=10.0,
                                       label="paid_cache_store"):
                    yield
        else:
            with self._store.locked():
                yield

    # ---- 读路径 -----------------------------------------------------------
    def _rows(self) -> list[dict[str, Any]]:
        path = self._cache_path()
        if not path.is_file():
            return []
        # io_utils.read_jsonl_recover_torn_tail 自带原子修复（去残片）——此处只在
        # 修复前预检计数供遥测；中部损坏仍由 io_utils 响亮抛错（持久损坏不静默）
        if _torn_tail_lines(path):
            self.telemetry.recovered_torn_tail_lines += 1
        return read_jsonl_recover_torn_tail(path)

    def lookup(self, fingerprint: str) -> dict[str, Any] | None:
        """按 fingerprint 精确查找。只返回 successful 记录。"""
        if not fingerprint:
            raise ValueError("paid cache fingerprint 不能为空")
        for row in self._rows():
            if row.get("fingerprint") == fingerprint:
                if row.get("success") is True:
                    self.telemetry.hits += 1
                    self.telemetry._event("hit", fingerprint)
                    return row
                self.telemetry.invalidations += 1
                self.telemetry._event("invalidation", fingerprint)
                return None  # 命中失败残留——视为未命中且已计数失效
        self.telemetry.misses += 1
        self.telemetry._event("miss", fingerprint)
        return None

    # ---- 写路径 -----------------------------------------------------------
    def record(self, fingerprint: str, payload: dict[str, Any], *,
               meta: dict[str, Any] | None = None) -> None:
        """写一条缓存。``success=False`` 的结果（failed/partial/证据不完整）拒绝写
        入（successful-only——为追零调用缓存失败结果是 §2.1 非目标）。"""
        self.record_many([(fingerprint, payload, meta)])

    def record_many(self, rows: list[tuple[str, dict[str, Any], dict[str, Any] | None]]) -> None:
        """批量写（单锁单次读-合并-重写）：迁移消费者按批次落盘的路径。

        rows = [(fingerprint, payload, meta), ...]；同指纹后者覆盖前者（与旧
        append 语义的 last-wins 等价），整文件原子替换 + fsync + Windows 退避。
        """
        entries: dict[str, dict[str, Any]] = {}
        for fingerprint, payload, meta in rows:
            if not fingerprint:
                raise ValueError("paid cache fingerprint 不能为空")
            row = {
                "schema": PAID_CACHE_STORE_VERSION,
                "fingerprint": fingerprint,
                "success": True,
                "payload": payload,
                "ts": time.time(),
            }
            if meta:
                row["meta"] = meta
            entries[str(fingerprint)] = row
        if not entries:
            return
        with self._locked():
            merged = {str(row.get("fingerprint") or ""): row
                      for row in self._rows() if row.get("fingerprint")}
            merged.update(entries)
            self._atomic_rewrite(list(merged.values()))
            self.telemetry.writes += len(entries)

    def record_failure(self, fingerprint: str, reason: str) -> None:
        """失败只计遥测，绝不落缓存（读路径自然 miss）。"""
        self.telemetry.dropped_not_successful += 1
        self.telemetry._event("dropped_failure", fingerprint)
        _ = reason  # 遥测事件已有 fingerprint；不持久化失败详情（含敏感 prompt 风险）

    def _atomic_rewrite(self, rows: list[dict[str, Any]]) -> None:
        """整文件原子替换 + fsync（Windows 读者会阻塞 os.replace——线性退避重试）。"""
        path = self._cache_path(for_write=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        with open(temp, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        last_error: OSError | None = None
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(temp, path)
                return
            except PermissionError as exc:  # Windows 读者占用
                last_error = exc
                time.sleep(_REPLACE_RETRY_DELAY_S * (attempt + 1))
        raise last_error  # type: ignore[misc]


def _safe_json_loads(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def read_dual_format(path: Path) -> dict[str, dict[str, Any]]:
    """双格式缓存读（M9 收敛）：旧顶层行 + PaidCacheStore payload 行 → 按指纹键的
    旧形态字典（payload 行解包平铺）。迁移期消费者的唯一读入口，撕裂尾行经
    io_utils 修复；**中部持久损坏响亮抛错**（io_utils 纪律——静默吞掉会让缓存
    损坏伪装成全量 miss）；文件缺失返回空。
    """
    from io_utils import read_jsonl_recover_torn_tail

    cache: dict[str, dict[str, Any]] = {}
    for row in read_jsonl_recover_torn_tail(Path(path)):
        key = str(row.get("fingerprint") or "")
        if not key:
            continue
        payload = row.get("payload")
        if row.get("schema") == PAID_CACHE_STORE_VERSION and isinstance(payload, dict):
            cache[key] = {"fingerprint": key, **payload}
        else:
            cache[key] = row
    return cache


def _torn_tail_lines(path: Path) -> int:
    """末行无终止符且不可解析 = 一次可恢复的撕裂写（io_utils 同口径预检）。"""
    raw = path.read_bytes()
    if not raw or raw.endswith(b"\n"):
        return 0
    last = raw.splitlines()[-1].decode("utf-8", "replace")
    return 0 if _safe_json_loads(last) is not None else 1
