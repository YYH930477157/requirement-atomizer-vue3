"""Artifact repository facade —— governed 路径 + JSONL/JSON 读写的单一接口层（T3-3）。

为什么要这一层
================

``result_package.governed_artifact_path`` 已经把 ``root / "foo.jsonl"`` 式的裸拼寻址收口到
``package_v1`` 的 ``.ratomizer/<category>/`` 布局。但读写纪律（跨进程锁 + 原子替换 +
Windows ``PermissionError`` 重试 + append-only）仍散落在 ``review_state.py``、
``ai_review_actions.py``、``functional_extract._write_cache_entry``、``desktop_tasks`` 等多处，
每处各复制一份 ``_atomic_write_jsonl`` / ``_replace_with_retry``。2026-08-03 的 B1 启动维护
静默失效、以及 WS-F 新代码里 ``root / "*.jsonl"`` 裸拼的重现，都是「寻址/读写纪律靠人肉记忆」
的结构性后果——本层把它们聚合成一个 repository 接口，新代码一律走这里，老代码暂不迁移。

设计取舍（与既有实现并存，不做原地替换）
========================================

* **门面而非重写**：本模块**不改动**任何既有读写实现。``ArtifactStore`` 在内部复用
  ``result_package.governed_artifact_path`` 做寻址、``process_file_lock.process_file_lock``
  做跨进程锁，并把原子替换 + ``PermissionError`` 重试 + append-only 收口为一处。既有调用点
  （``review_state`` / ``ai_review_actions`` / ``functional_extract`` 等）继续用自己的实现，
  行为逐字节不变；新代码用本门面。
* **逐步迁移指南**：新写的共享状态文件（append-only 事件流、CAS 快照、缓存）应优先用
  ``ArtifactStore``。迁移老文件时，逐文件把「裸拼 + 自带锁 + 自带原子替换」替换为
  ``with store.locked(): store.write_jsonl(...)``，**一次一个文件**，每步跑该文件的专项测试，
  确认产物字节不变再迁移下一个——不要批量替换。
* **寻址纪律不动**：``ArtifactStore.path`` 直接委托 ``governed_artifact_path``，
  ``for_write`` 语义、category 推断、package_v1 vs legacy 的双路径解析全部沿用既有契约。
  本层不发明新寻址规则。

契约 lint（禁止新增裸拼）
==========================

``scan_bare_artifact_joins`` 用 AST 扫描源码里的 ``<root> / "<governed>.jsonl|.lock"`` 式
裸拼（``ast.BinOp(Div, right=Constant(str))``）。``tests/test_artifact_store.py`` 冻结当前
合法用法的 (file, filename) 基线集合：基线内的现存裸拼被「收编」为白名单，新出现的裸拼
（基线之外）即令测试失败，提示作者改走 ``ArtifactStore``。这是把「寻址靠纪律」升级为
「寻址靠门禁」——B1 类错误不能再靠人眼拦截。

本模块自身的锁/临时文件路径用 ``Path.with_name(...)`` 构造，不落 ``root / "x.lock"`` 裸拼，
因此不会触发自己的扫描器。
"""
from __future__ import annotations

import ast
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

# governed 文件名后缀：扫描器只盯这些后缀的裸拼（共享状态 / append-only / 原子替换文件）。
# ``.json`` 不收（配置/产物读取面太广，误伤多于收益）；``.jsonl``/``.lock`` 是共享状态纪律的核心。
_GOVERNED_SUFFIXES = (".jsonl", ".lock")

_REPLACE_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_S = 0.02


@dataclass(frozen=True)
class BareArtifactJoin:
    """一处 ``<root> / "<governed>"`` 裸拼的静态定位（lint 报告单元）。"""

    file: str
    line: int
    filename: str
    left: str  # 除号左侧的源码片段（诊断用，不稳定，不进基线键）


def _replace_with_retry(source: Path, target: Path) -> None:
    """Retry short-lived Windows sharing violations without weakening atomic replacement.

    与 review_state._replace_with_retry 同实现：Windows 读者会短暂阻塞 ``os.replace``，
    指数式重试几次即可，不放松原子语义。
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_RETRY_DELAY_S)


def _atomic_write_text(target: Path, text: str) -> None:
    """同卷暂存 + fsync + 原子替换（``\\n`` 换行，UTF-8）。"""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix="." + target.name + ".", suffix=".tmp", dir=str(parent)
    )
    os.close(fd)  # mkstemp 返回的 fd 立即关闭：用 with-open 另开句柄写，避免 Windows 上 fd 泄漏锁文件
    tmp = Path(tmp_name)
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, target)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


class ArtifactStore:
    """一个 output root 上的共享产物仓库门面（governed 寻址 + 锁 + 原子读写）。

    用法（新代码）::

        store = ArtifactStore(out_dir, category="state")
        rows = store.read_jsonl("requirement_rtm_edges.jsonl", tolerant=True)
        with store.locked():
            store.append_jsonl("requirement_rtm_edges.jsonl", event)

    既有调用点不必改动；本类是给新代码的单一入口，逐步迁移老代码（见模块 docstring）。
    """

    def __init__(
        self,
        root: Path | str,
        *,
        category: str | None = None,
        lock_filename: str | None = None,
    ) -> None:
        self._root = Path(root).expanduser().resolve()
        self._category = category
        # 锁文件名稳定且与具体产物解耦：默认用一个 category 级锁，避免每个产物自带锁文件散落。
        # 调用方可显式覆盖（与既有 review_states.lock / verification_states.lock 同名即可复用）。
        self._lock_filename = lock_filename or "artifact_store.lock"

    # ------------------------------------------------------------------ 寻址
    def path(self, filename: str, *, for_write: bool = False) -> Path:
        """governed 解析（直接委托 ``result_package.governed_artifact_path``）。

        ``for_write=False``（默认）纯解析不落盘——只读路径不得自称无副作用却建空目录。
        """
        from result_package import governed_artifact_path

        return governed_artifact_path(
            self._root, filename, category=self._category, for_write=for_write
        )

    # ------------------------------------------------------------------ 锁
    @contextmanager
    def locked(self, *, timeout_s: float = 10.0) -> Iterator[None]:
        """跨进程锁（``process_file_lock``）+ 进程内 RLock（同进程多线程先于 OS 锁串行）。

        与 ``review_state.review_state_lock`` 同型。**不要嵌套** ``locked()``：OS 锁非可重入，
        同线程二次获取同一锁文件会超时；read-modify-write 在单个 ``with`` 内完成即可。
        锁文件落 governed ``state`` 路径，用 ``with_name`` 构造，不裸拼。
        """
        from process_file_lock import process_file_lock
        from result_package import governed_artifact_path

        lock_path = governed_artifact_path(
            self._root, self._lock_filename, category="state", for_write=True
        )
        rlock = _process_rlock(self._root)
        with rlock:
            with process_file_lock(
                lock_path, timeout_s=timeout_s, label="artifact_store"
            ):
                yield

    # ------------------------------------------------------------------ JSONL
    def read_jsonl(
        self, filename: str, *, tolerant: bool = False
    ) -> list[dict[str, Any]]:
        """读 JSONL。``tolerant=True`` 跳过坏行（与 ``review_state._read_jsonl_tolerant`` 同纪律）；
        默认严格（``io_utils.read_jsonl``：坏行抛错）。文件缺失返回 ``[]``。
        """
        path = self.path(filename, for_write=False)
        if not path.is_file():
            return []
        if tolerant:
            rows: list[dict[str, Any]] = []
            with path.open(encoding="utf-8-sig") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
            return rows
        from io_utils import read_jsonl

        return read_jsonl(path)

    def write_jsonl(self, filename: str, rows: list[dict[str, Any]]) -> Path:
        """整文件原子替换写 JSONL（锁内调用更安全；本身做原子替换但不自带锁）。"""
        path = self.path(filename, for_write=True)
        text = "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in rows
        )
        _atomic_write_text(path, text)
        return path

    def append_jsonl(self, filename: str, row: dict[str, Any]) -> Path:
        """append-only 追加一行（锁内调用更安全；本身只做追加，不做 read-modify-write）。"""
        path = self.path(filename, for_write=True)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return path

    # ------------------------------------------------------------------ JSON
    def read_json(
        self, filename: str, *, default: Any = None
    ) -> Any:
        path = self.path(filename, for_write=False)
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def write_json(self, filename: str, payload: Any) -> Path:
        path = self.path(filename, for_write=True)
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return path


# ---------------------------------------------------------------- 进程内锁池
_PROCESS_LOCKS: dict[Path, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()


def _process_rlock(root: Path) -> RLock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(root, RLock())


# ===========================================================================
# 契约 lint：扫描源码裸拼 ``<root> / "<governed>.jsonl|.lock"``
# ---------------------------------------------------------------------------
# 用 AST（正则分不清「除法」与「路径拼接」）定位 ``BinOp(Div, right=Constant(str))``，
# 右字符串以 ``.jsonl``/``.lock`` 结尾即报。测试冻结 (file, filename) 基线，基线外的新裸拼
# 失败——把「寻址靠纪律」升级为「寻址靠门禁」。``left`` 仅供诊断，不进基线键（不稳定）。
# ===========================================================================
def is_governed_filename(name: str) -> bool:
    return isinstance(name, str) and name.endswith(_GOVERNED_SUFFIXES)


def scan_bare_artifact_joins(source: str, *, file: str = "<src>") -> list[BareArtifactJoin]:
    """扫描一段 Python 源码里的 governed 裸拼，返回所有命中点。

    命中条件：``<expr> / "<...jsonl|lock>"``（``ast.BinOp`` 除法，右操作数为 governed
    文件名字符串字面量）。``<expr>`` 的具体形态（``root`` / ``out_dir`` / ``governed_artifact_path(...)``）
    不影响命中——基线冻结负责收编现存合法用法，新出现的命中即需走 ``ArtifactStore``。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    hits: list[BareArtifactJoin] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        right = node.right
        if not isinstance(right, ast.Constant) or not isinstance(right.value, str):
            continue
        if not is_governed_filename(right.value):
            continue
        try:
            left_src = ast.unparse(node.left)
        except Exception:  # noqa: BLE001 — unparse 在老语法上偶发失败，诊断字段可空
            left_src = "<?>"
        hits.append(BareArtifactJoin(file, node.lineno, right.value, left_src))
    return hits


def scan_repo_bare_joins(root: Path | str) -> list[BareArtifactJoin]:
    """扫描仓库顶层 ``*.py`` 的全部 governed 裸拼（供基线冻结测试使用）。"""
    base = Path(root)
    hits: list[BareArtifactJoin] = []
    for path in sorted(base.glob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        hits.extend(scan_bare_artifact_joins(source, file=str(path)))
    return hits
