"""批注翻译子系统（M9 第 1 刀，2026-08-17 自 doc_annotation_export 机械抽取）。

逐字搬运：策略版本/护栏/批处理/journal+sidecar IO/编排。共享渲染态
（_active_translations/_active_translation_notes/_collected_marker_texts）
留在 doc_annotation_export——本模块不持有；generate 的无 texts 回退经惰性
import 调原模块 render。原模块重导出全部符号，测试 patch 目标
（ANNOTATION_TRANSLATION_GUARDS_VERSION/_read_translation_sidecar/
generate_annotation_translations/export_annotation_bundle）语义不变。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from api_server import (
    ANNOTATION_TRANSLATIONS,
    ANNOTATION_TRANSLATION_GUARDS_VERSION,
    TRANSLATION_LANGUAGE_REQUIREMENTS,
    translation_key as _translation_key,
)
from io_utils import read_jsonl
from result_package import governed_artifact_path, package_root_for_analysis_root


def _cleaned_marker_text(text: str) -> str:
    # 发送前做渲染同款清洁——清洁器本体（_clean_block_text 及其渲染正则）留在
    # doc_annotation_export（渲染层职责），此处惰性桥接，语义逐字等价
    import doc_annotation_export as _dae

    return " ".join(_dae._clean_block_text(text).split()) or " ".join(text.split())


def _missing_translation_tokens(drift_tokens: list[str]) -> list[str]:
    prefix = "缺失:"
    return sorted({token[len(prefix):] for token in drift_tokens if token.startswith(prefix)})

_TRANSLATION_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "fig.", "no.", "vs.")


def _dae_clean(text: str) -> str:
    import doc_annotation_export as _dae
    return _dae._clean_block_text(text)


def _split_translation_segments(text: str) -> list[str]:
    """保守分句；无法得到至少两个完整句段时不启用句级降级。"""
    # _clean_block_text 会折叠换行；逐行清洁后再拼回去，保留无标点列表/换行句段边界。
    cleaned_lines = [_dae_clean(line) for line in str(text).splitlines()]
    cleaned = "\n".join(line for line in cleaned_lines if line)
    if not cleaned:
        cleaned = _dae_clean(text) or " ".join(text.split())
    if not cleaned:
        return []
    raw_parts = [part.strip() for part in re.split(
        r"(?:\r?\n)+|(?<=[.;!?])\s+|(?<=[。；！？])", cleaned) if part.strip()]
    if len(raw_parts) < 2:
        return []

    parts: list[str] = []
    for part in raw_parts:
        if parts and (parts[-1].casefold().endswith(_TRANSLATION_ABBREVIATIONS)
                      or re.search(r"\b[A-Za-z]\.$", parts[-1])):
            parts[-1] = f"{parts[-1]} {part}"
        else:
            parts.append(part)
    if len(parts) < 2 or any(len(re.sub(r"\W", "", part)) < 2 for part in parts):
        return []
    # 分隔符全是零宽边界；此不变量防止以后调整正则时静默丢字。
    if re.sub(r"\s+", "", "".join(parts)) != re.sub(r"\s+", "", cleaned):
        return []
    return parts


def _required_translation_tokens(source: str) -> list[str]:
    """Return the exact source tokens that the strict guard expects to survive."""
    from api_server import _protected_units
    from cosem_behavior_spec import extract_codes, extract_ints

    return sorted({str(token) for token in (
        extract_codes(source)
        | extract_ints(_norm_int_text(source))
        | _protected_units(source)
    )})


_TRANSLATION_BATCH = 8

ANNOTATION_TRANSLATION_STRATEGY_VERSION = "annotation-translation-v3-segment-fallback"

TRANSLATION_BATCH_PROMPT_VERSION = "translation-prompt-v5"

ANNOTATION_TRANSLATION_STRATEGY_VERSION_OPTIMIZED = (
    f"{TRANSLATION_BATCH_PROMPT_VERSION}-greedy-splithalf"
)

_TRANSLATION_BATCH_MAX_CHARS_DEFAULT = 8000

_TRANSLATION_SPLIT_ROUNDS = 2   # 批次 JSON 非法时拆半重试轮数上限（≤2 轮后回退逐条）

_TRANSLATION_SIDECAR_VERSION = 2

_TRANSLATION_JOURNAL_NAME = "annotation_translations.journal.jsonl"

_TRANSLATION_JOURNAL_VERSION = 1

_TRANSLATION_JOURNAL_COMPACT_BYTES = 256 * 1024   # 日志超过 256KiB 触发一次中途压实

_TRANSLATION_REPLACE_ATTEMPTS = 5

_TRANSLATION_REPLACE_RETRY_S = 0.02

_TRANSLATION_JOURNAL_APPEND_ATTEMPTS = 8

_TRANSLATION_JOURNAL_APPEND_RETRY_S = 0.02

_TRANSLATION_LOCK_TIMEOUT_S = 10.0

_TRANSLATION_LOCK_STALE_AFTER_S = 300.0

_TRANSLATION_PROCESS_LOCKS: dict[Path, RLock] = {}

_TRANSLATION_PROCESS_LOCKS_GUARD = RLock()

def _translate_batch_count() -> int:
    """RATOMIZER_TRANSLATE_BATCH：默认 10；<=0 回退旧 batch=8；正整数启用优化批处理。

    硬上限 ≤10（方案规定，防注意力稀释）：>10 一律 clamp 到 10。非整数（如 3.5、abc）fail-safe
    关闭（回默认 0=OFF），不静默截断成歧义值。
    """
    raw = os.environ.get("RATOMIZER_TRANSLATE_BATCH")
    if raw is None or str(raw).strip() == "":
        return 10
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0                       # 非数字 → fail-safe 关闭
    if not value.is_integer():
        return 0                       # 非整数（3.5 等）→ fail-safe 关闭
    count = int(value)
    if count < 1:
        return 0                       # 0/负数 → OFF
    return min(count, 10)              # 硬上限 ≤10

def _translate_batch_max_chars() -> int:
    """优化批处理单批输入总字符上限（仅 _translate_batch_count()>0 时生效）。

    非整数（如 3.5、abc）fail-safe 回默认值，不静默截断；0/负数同样回默认值。
    """
    default = _TRANSLATION_BATCH_MAX_CHARS_DEFAULT
    raw = os.environ.get("RATOMIZER_TRANSLATE_BATCH_MAX_CHARS")
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logging.getLogger("requirement_atomizer").warning(
            "RATOMIZER_TRANSLATE_BATCH_MAX_CHARS=%r 不是数字，fail-safe 使用默认值 %s",
            raw, default)
        return default
    if not value.is_integer():
        logging.getLogger("requirement_atomizer").warning(
            "RATOMIZER_TRANSLATE_BATCH_MAX_CHARS=%r 不是整数，fail-safe 使用默认值 %s",
            raw, default)
        return default
    count = int(value)
    if count < 1:
        logging.getLogger("requirement_atomizer").warning(
            "RATOMIZER_TRANSLATE_BATCH_MAX_CHARS=%r ≤0，fail-safe 使用默认值 %s",
            raw, default)
        return default
    return count

def _active_translation_strategy_version() -> str:
    """当前启用的翻译策略版本：优化批处理开→「提示词版本-greedy-splithalf」（含有效配置指纹），否则单条策略版本。

    有效配置（clamp 后的条数 + 字符上限）拼进策略版本，因而同时进入 export-annotation-html
    阶段 producer 戳与逐条 sidecar strategy_version：
    - 阶段戳：10/8000 与 5/4000 不同 → 切配置即重跑阶段（不被当同一行为配置）。
    - 失败缓存：拒绝项绑定 strategy_version → 配置变化时旧拒绝不共键、可重试。
    已接受译文跨配置仍零调用复用（_translation_entry_is_reusable 的 accepted 分支只过护栏，不看策略版本）。
    """
    count = _translate_batch_count()
    if count <= 0:
        return ANNOTATION_TRANSLATION_STRATEGY_VERSION
    return f"{ANNOTATION_TRANSLATION_STRATEGY_VERSION_OPTIMIZED}-b{count}-c{_translate_batch_max_chars()}"

_DIGIT_GROUP_RE = re.compile(r"(?<=\d)[\s,  ](?=\d)")

_PAREN_ENUM_MARKER_RE = re.compile(
    r"(^[ \t]*|[\n\r.;；:：。！？!?][ \t]*)[(（]\d{1,2}[)）](?!\d)",
    re.MULTILINE,
)

_TRANSLATION_ENUM_MARKER_RE = re.compile(
    r"(^[ \t]*|[\n\r.;；:：,，、。！？!?][ \t]*)\d{1,2}\s*[.、)）](?!\d)",
    re.MULTILINE,
)

def _norm_int_text(text: str) -> str:
    """翻译护栏整数口径：两侧同样并组千分位并剥除列表枚举标号。"""
    from text_normalize import strip_enum_markers

    without_paren_enums = _PAREN_ENUM_MARKER_RE.sub(
        lambda match: f"{match.group(1)} ", str(text or "")
    )
    without_enums = _TRANSLATION_ENUM_MARKER_RE.sub(
        lambda match: f"{match.group(1)} ", without_paren_enums
    )
    return strip_enum_markers(_DIGIT_GROUP_RE.sub("", without_enums))

def _read_translation_journal(out_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """读回追加式翻译日志（崩溃恢复）：每行一个已完成条目的增量更新。

    撕裂的尾行（崩溃窗口内未写完）不是已完成项，跳过即恢复；版本不匹配的行
    同样跳过（日志是新增文件，旧代码不读它，不存在误解析面）。

    只按 LF 切行（不用 splitlines()）：U+2028/U+2029 是译文的合法字符，遗留
    行内一旦原样落盘，splitlines() 会在其上切行把一条记录撕成多段废行静默
    丢掉（已完成翻译的唯一来源）。行尾 \r 由下方 strip() 兜底兼容。
    """
    try:
        path = governed_artifact_path(
            out_dir, _TRANSLATION_JOURNAL_NAME, category="cache", for_write=False
        )
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    updates: list[tuple[str, dict[str, Any]]] = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (not isinstance(row, dict)
                or row.get("version") != _TRANSLATION_JOURNAL_VERSION
                or not isinstance(row.get("key"), str)
                or not isinstance(row.get("entry"), dict)):
            continue
        updates.append((row["key"], dict(row["entry"])))
    return updates

def _translation_journal_nonempty(out_dir: Path) -> bool:
    try:
        path = governed_artifact_path(
            out_dir, _TRANSLATION_JOURNAL_NAME, category="cache", for_write=False
        )
        return path.stat().st_size > 0
    except OSError:
        return False

def _truncate_torn_journal_tail(journal_path: Path) -> None:
    """追加前截掉崩溃撕裂的尾行（无结尾 LF 的残段，读端本就跳过它）。

    不截断的话，"a" 模式续写会把新记录拼在残行后面，两行都变非法 → 都被
    静默跳过 → 已完成的付费翻译永久丢失（日志是它崩溃恢复的唯一来源）。
    截到上一个 LF+1（无 LF 则清空）：残行按定义不是已完成条目，截掉零损失。
    必须在 _translation_sidecar_lock 内调用（与追加同锁序）。
    """
    try:
        with journal_path.open("r+b") as handle:
            data = handle.read()
            if not data or data.endswith(b"\n"):
                return
            handle.seek(data.rfind(b"\n") + 1)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
    except PermissionError:
        # 截断被共享冲突挡住时绝不能静默跳过——否则随后的 "a" 续写会把新行拼在
        # 残行后面（两行俱废）。上抛给调用方（_append_translation_sidecar）的
        # PermissionError 重试预算统一处理。
        raise
    except OSError:
        # 文件不存在（首次追加）或其它截断失败（退化为旧行为：读端仍会跳过残行，
        # 只损失本批新行）——都不阻断追加主路径。
        return

def _read_translation_sidecar(out_dir: Path) -> dict[str, dict[str, Any]]:
    """生成侧读完整条目（含被拒留账的）；是否复用由当前策略版本决定。

    JSON 本体之后按追加顺序重放翻译日志（与逐批整档写等价的折叠序），崩溃后
    已完成的真实译文不丢；下一次整档重写（压实）会清掉日志。
    """
    try:
        path = governed_artifact_path(
            out_dir, ANNOTATION_TRANSLATIONS, category="cache", for_write=False
        )
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    items = data.get("items") if isinstance(data, dict) else None
    merged = ({str(k): dict(v) for k, v in items.items() if isinstance(v, dict)}
              if isinstance(items, dict) else {})
    for key, entry in _read_translation_journal(out_dir):
        merged[key] = _merge_translation_update(merged.get(key), entry)
    return merged

def _translation_guard_source(text: str) -> str:
    """Use the exact normalized text visible to the translation model."""
    return _cleaned_marker_text(text)

def _batch_translation_prompt(numbered: list[dict[str, Any]], *, optimized: bool) -> tuple[str, str]:
    system = "你是电表/燃气表等技术标准文档的翻译助手。"
    rules = [
        "把下列标准原文逐条忠实翻译成中文。规则：",
        "- 逐条对应，不合并、不拆分、不遗漏；",
    ]
    if optimized:
        # 优化批处理：明令逐条独立、不得跨条借鉴——与逐条护栏（_fabricated_translation_tokens）
        # 配套，防长批里相邻条目数字/编号互相串味后被护栏整批拒掉。
        rules += [
            "- 逐条独立翻译：不得跨条借鉴、挪用或合并数字、编号、协议代码、单位或任何内容；",
            "- 忠实原文：不得新增原文没有的数字、编号、协议代码、单位或任何建议/解释；",
            "- 原文中的每个阿拉伯数字、编号、协议代码和单位必须在对应译文中原样保留，不得省略、改写为中文数字或约数；",
            "- 专有名词与缩写（如 M-Bus、DLMS、OBIS 及设备/机构缩写）保留原文；",
            "- 只输出 JSON 对象 {\"items\":[{\"id\":1,\"translation\":\"...\"}]}，"
            "items 数量与输入条数一致。",
        ]
    else:
        rules += [
            "- 忠实原文：不得新增原文没有的数字、编号、协议代码、单位或任何建议/解释；",
            "- 专有名词与缩写（如 M-Bus、DLMS、OBIS 及设备/机构缩写）保留原文；",
            "- 只输出 JSON 对象 {\"items\":[{\"id\":1,\"translation\":\"...\"}]}。",
        ]
    rules += [TRANSLATION_LANGUAGE_REQUIREMENTS, "原文条目 JSON:", json.dumps(numbered, ensure_ascii=False)]
    return system, "\n".join(rules)

def _translate_marker_batch(chat: Any, batch: list[tuple[str, str, str]], *,
                            optimized: bool = False) -> tuple[dict[int, str], bool]:
    numbered = [{"id": i, "text": _cleaned_marker_text(text)}
                for i, (_key, _owner, text) in enumerate(batch, start=1)]
    system, user = _batch_translation_prompt(numbered, optimized=optimized)
    payload = chat(system, user)
    items = payload.get("items") if isinstance(payload, dict) else None
    result: dict[int, str] = {}
    # parseable = 模型回了一个 items 列表（哪怕缺条/多条/乱序都算结构合法）。
    # 只有结构非法（非 dict、无 items 键、items 非列表）才由上层 _translate_batch_with_splits 拆半。
    parseable = isinstance(items, list)
    size = len(batch)
    seen: set[int] = set()
    ambiguous: set[int] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        # 越界 id（含 0/负数/超过本批长度）：忽略，不落表、不污染任何合法位。
        if item_id < 1 or item_id > size:
            continue
        # 重复 id：歧义信号（模型可能串条），fail-closed 丢弃该 id 的全部回填——
        # 既然后续单条重试取回干净译文，也不让重复项覆盖合法条目。合法条目互不染。
        if item_id in ambiguous:
            continue
        if item_id in seen:
            result.pop(item_id, None)
            seen.discard(item_id)
            ambiguous.add(item_id)
            continue
        seen.add(item_id)
        result[item_id] = str(item.get("translation") or "").strip()
    return result, parseable

def _translate_batch_with_splits(chat: Any, batch: list[tuple[str, str, str]], *,
                                 split_rounds: int) -> tuple[dict[int, str], int, int]:
    """优化批处理：整批非法（调用异常或 items 结构缺失）时拆半重试 ≤split_rounds 轮。

    返回 ``(result, calls, failed)``，永不抛异常：
    - result: 本（子）批内 1..N 位置 → 译文；成功条目照常回填，缺条留空交逐条级联。
    - calls: 实际发起的 LLM 调用数（含拆半递归）。
    - failed: 结构非法/抛异常的调用数（成本审计用）。

    拆半只对「整批非法」生效；部分缺条（items 列表存在但少几条）不算非法，照常逐条降级。
    单条自身（len==1）无法再拆，回退逐条级联。id 偏移：左半 1..mid 原位，右半 local+mid。
    """
    calls = 0
    failed = 0
    result: dict[int, str] = {}
    try:
        result, parseable = _translate_marker_batch(chat, batch, optimized=True)
        calls += 1
        if parseable:
            return result, calls, failed
        failed += 1   # items 结构缺失 = 整批非法
    except Exception:
        calls += 1
        failed += 1
    if split_rounds > 0 and len(batch) > 1:
        mid = len(batch) // 2
        left, lc, lf = _translate_batch_with_splits(chat, batch[:mid], split_rounds=split_rounds - 1)
        right, rc, rf = _translate_batch_with_splits(chat, batch[mid:], split_rounds=split_rounds - 1)
        merged = dict(left)
        for local_id, translation in right.items():
            merged[mid + local_id] = translation
        return merged, calls + lc + rc, failed + lf + rf
    return result, calls, failed

def _pack_translation_batches(pending_list: list[tuple[str, str, str]], *,
                              count_limit: int, max_chars: int
                              ) -> list[list[tuple[str, str, str]]]:
    """顺序贪心装包：条数与字符双上限，任一触发即封包；单条自身超字符上限整条单独发（宁超勿截）。

    count_limit<=0 时回到旧 batch=8 简单切片（OFF 路径；批次响应解析仍保留 fail-closed
    的越界/重复 id 卫生处理，对正常响应无影响）。
    """
    if count_limit <= 0:
        return [pending_list[start:start + _TRANSLATION_BATCH]
                for start in range(0, len(pending_list), _TRANSLATION_BATCH)]
    batches: list[list[tuple[str, str, str]]] = []
    current: list[tuple[str, str, str]] = []
    current_chars = 0
    for item in pending_list:
        item_chars = len(_cleaned_marker_text(item[2]))
        # 单条自身超字符上限：先封掉当前包，再整条单独成一包（不截断、宁超勿截）。
        if item_chars > max_chars:
            if current:
                batches.append(current)
                current = []
                current_chars = 0
            batches.append([item])
            continue
        would_count = len(current) + 1
        would_chars = current_chars + item_chars
        if current and (would_count > count_limit or would_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        batches.append(current)
    return batches

def _translate_marker_single(chat: Any, text: str, *, forbidden_tokens: list[str],
                             required_tokens: list[str] | None = None,
                             segment_label: str = "", retry_reason: str = "") -> str:
    cleaned = _cleaned_marker_text(text)
    system = "你是电表/燃气表等技术标准文档的翻译助手。"
    retry_kind = f"句段重试（{segment_label}）" if segment_label else "单条整段重试"
    retry_feedback = (
        "上一版译文因引入原文没有的编码/数字而被拒绝。"
        if forbidden_tokens else
        f"上一轮没有得到可校验的译文（{retry_reason or '未返回译文'}）。"
    )
    user = "\n".join([
        f"这是一次{retry_kind}。{retry_feedback}",
        "只翻译下面这一条原文，不得借用此前批次或其他条目的数字、编号、协议代码或单位。",
        "必须忠实原文，不新增建议、解释或推断；专有名词与缩写保留原文。",
        "以下 token 已由护栏判定为原文不存在，译文中严禁再次出现：",
        json.dumps(forbidden_tokens, ensure_ascii=False),
        "以下 token 来自原文，译文中必须逐个原样保留，不得省略、改写为中文数字或约数：",
        json.dumps(required_tokens or [], ensure_ascii=False),
        "只输出 JSON 对象 {\"items\":[{\"id\":1,\"translation\":\"...\"}]}。",
        TRANSLATION_LANGUAGE_REQUIREMENTS,
        "唯一原文 JSON:",
        json.dumps({"id": 1, "text": cleaned}, ensure_ascii=False),
    ])
    payload = chat(system, user)
    items = payload.get("items") if isinstance(payload, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if item_id == 1:
            return str(item.get("translation") or "").strip()
    return ""

def _fabricated_translation_tokens(source: str, translation: str) -> list[str]:
    from cosem_behavior_spec import extract_codes, extract_ints

    basis = _norm_int_text(source)
    fabricated = ((extract_codes(translation) - extract_codes(source))
                  | (extract_ints(_norm_int_text(translation)) - extract_ints(basis)))
    return sorted(str(token) for token in fabricated)

def _translation_drift(source: str, translation: str, *, strict: bool
                       ) -> tuple[list[str], list[str]]:
    """逐条防漂移护栏，返回 ``(drift_tokens, fabricated_tokens)``。

    - ``drift_tokens``：判定漂移的全部违规 token。
      * 非严格（显式 OFF 回退）= 仅译文新增（编码/整数），与既有
        ``_fabricated_translation_tokens`` 完全同口径、行为逐字节不变。
      * 严格（默认优化批处理）= **双向**：在译文新增之上，补「原文受保护 token 缺失」
        （编码/数值/单位）与「单位新增」。整数两侧均先并组千分位并剥除枚举标号，
        物理单位符号复用 api_server._protected_units。
    - ``fabricated_tokens``：始终只含译文新增，供单条重试 forbidden_tokens 反馈
      （「严禁再次出现」只对新增语义成立；缺失方向由重试给模型再一次机会，不由 forbidden 抑制）。

    严格模式超集非严格：任何 v2 会拒的译文，v3 同样拒；v3 额外拦截原文 token 丢失。
    """
    # 经原模块命名空间调用：tests 以 patch.object(dae, "_fabricated_translation_tokens")
    # 注入守卫计数——本函数定义已移至此模块，直接调用会绕过 patch（拆分保真约定）
    import doc_annotation_export as _dae

    fabricated = _dae._fabricated_translation_tokens(source, translation)
    if not strict:
        return fabricated, fabricated
    from api_server import _protected_units
    from cosem_behavior_spec import extract_codes, extract_ints

    source_codes, trans_codes = extract_codes(source), extract_codes(translation)
    source_ints = extract_ints(_norm_int_text(source))
    trans_ints = extract_ints(_norm_int_text(translation))
    source_units, trans_units = _protected_units(source), _protected_units(translation)
    missing = ((source_codes - trans_codes)
               | (source_ints - trans_ints)
               | (source_units - trans_units))
    fabricated_units = trans_units - source_units
    drift = (set(fabricated)
             | {f"缺失:{token}" for token in missing}
             | {f"新增单位:{unit}" for unit in fabricated_units})
    return sorted(drift), fabricated

def _translation_entry_is_reusable(entry: dict[str, Any], source_text: str, *,
                                   strategy_version: str = ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                                   strict: bool = False) -> bool:
    # 已接受译文可零调用迁移，但必须用当前护栏重新验证（v3 严格双向护栏也会在此拦下
    # v2 接受但缺失 token 的旧译文——零调用复用前提是通过当前护栏）；拒绝只在同策略+护栏内复用。
    if str(entry.get("translation") or "").strip() and not entry.get("rejected"):
        drift, _fabricated = _translation_drift(
            _translation_guard_source(source_text), str(entry.get("translation") or ""),
                                                strict=strict)
        return not drift
    return bool(entry.get("rejected")
                and entry.get("strategy_version") == strategy_version
                and entry.get("guards_version") == ANNOTATION_TRANSLATION_GUARDS_VERSION)

def _adopt_full_sidecar_translations(out_dir: Path, sidecar: dict[str, dict[str, Any]],
                                     pending: dict[str, tuple[str, str]],
                                     *, strategy_version: str) -> set[str]:
    """full 模式（§13）：从全文 sidecar 确定性采纳已验收译文。

    键位同源（api_server.translation_key），采纳条目逐条过本模块当前护栏
    （数字/编码不得漂移），provenance 如实记 ``full_translation_sidecar``——
    绝不把采纳条目标成 marker 路径产物。护栏不过则不采纳（留给 marker 路径）。
    """
    full_path = governed_artifact_path(
        out_dir, "document_translations.jsonl", category="pipeline", for_write=False)
    if not full_path.is_file():
        return set()
    full_entries: dict[str, dict[str, Any]] = {}
    try:
        for row in read_jsonl(full_path):
            key = str(row.get("translation_key") or "")
            translation = str(row.get("translation") or "").strip()
            if key and translation and not row.get("rejected"):
                full_entries[key] = row
    except OSError:
        return set()
    adopted: set[str] = set()
    for key, (owner, text) in pending.items():
        row = full_entries.get(key)
        if row is None:
            continue
        translation = str(row.get("translation") or "").strip()
        drift, _fabricated = _translation_drift(
            _translation_guard_source(text), translation, strict=False)
        if drift:
            continue
        sidecar[key] = {
            "owner": owner,
            "translation": translation,
            "rejected": False,
            "model": str(row.get("model") or ""),
            "provenance": "full_translation_sidecar",
            "strategy_version": strategy_version,
            "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
        }
        adopted.add(key)
    return adopted

def _resolve_export_translation_mode(explicit: str | None = None) -> tuple[str, str]:
    """export 的翻译模式解析。返回 (effective_mode, requested_mode)。

    env 默认 full 时**保持既有 marker 行为**（默认行为面零变化，M6 纪律）；
    显式传参 full 才启用严格 full（sidecar 采纳优先）。off/markers 语义一致。
    """
    from pipeline_plan import resolve_translation_mode

    requested = resolve_translation_mode(override=explicit)
    if requested == "full" and explicit is None:
        return "markers", requested
    return requested, requested

def _translation_process_lock_for(out_dir: Path) -> RLock:
    with _TRANSLATION_PROCESS_LOCKS_GUARD:
        return _TRANSLATION_PROCESS_LOCKS.setdefault(out_dir, RLock())

@contextmanager
def _translation_sidecar_lock(out_dir: Path) -> Iterator[None]:
    out_dir = Path(out_dir).expanduser().resolve()
    lock_path = governed_artifact_path(
        out_dir, "annotation_translations.lock", category="cache"
    )
    with _translation_process_lock_for(lock_path.parent):
        deadline = time.monotonic() + _TRANSLATION_LOCK_TIMEOUT_S
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    stale = time.time() - lock_path.stat().st_mtime >= _TRANSLATION_LOCK_STALE_AFTER_S
                except FileNotFoundError:
                    continue
                if stale:
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for translation sidecar lock: {lock_path}")
                time.sleep(0.01)
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

def _merge_translation_update(existing: dict[str, Any] | None,
                              incoming: dict[str, Any]) -> dict[str, Any]:
    """并发冲突时已接受译文优先；拒绝项仍可被新策略接受结果替换。"""
    if not existing:
        return dict(incoming)
    existing_accepted = bool(str(existing.get("translation") or "").strip()
                             and not existing.get("rejected"))
    incoming_accepted = bool(str(incoming.get("translation") or "").strip()
                             and not incoming.get("rejected"))
    if existing_accepted:
        invalidated_sha256 = str(incoming.get("invalidated_translation_sha256") or "")
        existing_translation = str(existing.get("translation") or "").strip()
        if (not incoming_accepted
                and incoming.get("status") == "unresolved"
                and invalidated_sha256
                and hashlib.sha256(existing_translation.encode("utf-8")).hexdigest()
                == invalidated_sha256):
            # CAS：只替换本轮严格护栏实际复验过的那份旧译文。若另一进程已写入
            # 不同的成功译文，哈希不匹配，继续保留磁盘上的新结果。
            return dict(incoming)
        # 当前护栏重新验证的结果可以取代旧护栏下的成功项。否则旧译文即使被
        # 新护栏判定不安全，也会被“已接受优先”的并发规则永久保留下来。
        if (existing.get("guards_version") != ANNOTATION_TRANSLATION_GUARDS_VERSION
                and incoming.get("guards_version") == ANNOTATION_TRANSLATION_GUARDS_VERSION):
            return dict(incoming)
        # 零调用复验只更新版本元数据；相同译文不是并发冲突。
        if (incoming_accepted
                and str(existing.get("translation") or "").strip()
                == str(incoming.get("translation") or "").strip()):
            return {**existing, **incoming}
        return dict(existing)
    if incoming_accepted:
        return dict(incoming)
    return dict(incoming)

def _write_translation_sidecar(out_dir: Path, sidecar: dict[str, dict[str, Any]], model: str,
                               updated_keys: set[str], *,
                               strategy_version: str = ANNOTATION_TRANSLATION_STRATEGY_VERSION) -> None:
    """整档原子重写（压实地）：读回 JSON+日志合并态 → 单次 fsync + os.replace。

    成功替换后删除翻译日志——日志条目已并入 JSON，重放等价（幂等合并），删日志
    只是为了不再重复重放。崩溃发生在 replace 与删除之间时，下一轮重放同一批
    条目，结果不变。
    """
    out_dir = Path(out_dir).expanduser().resolve()
    target = governed_artifact_path(
        out_dir, ANNOTATION_TRANSLATIONS, category="cache"
    )
    with _translation_sidecar_lock(out_dir):
        latest = _read_translation_sidecar(out_dir)
        for key in updated_keys:
            latest[key] = _merge_translation_update(latest.get(key), sidecar[key])
        sidecar.clear()
        sidecar.update(latest)
        payload = {
            "version": _TRANSLATION_SIDECAR_VERSION,
            "strategy_version": strategy_version,
            "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
            "model": model,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "items": latest,
        }
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{id(sidecar)}.tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(_TRANSLATION_REPLACE_ATTEMPTS):
                try:
                    os.replace(tmp, target)
                except PermissionError:
                    if attempt + 1 >= _TRANSLATION_REPLACE_ATTEMPTS:
                        raise
                    time.sleep(_TRANSLATION_REPLACE_RETRY_S)
                    continue
                # 替换成功后清日志；Windows 读端短暂占用导致删除失败时留账无害
                # （重放走幂等合并），绝不当成替换失败重试。
                journal_path = governed_artifact_path(
                    out_dir, _TRANSLATION_JOURNAL_NAME, category="cache",
                    for_write=False,
                )
                try:
                    journal_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return
        finally:
            tmp.unlink(missing_ok=True)

def _append_translation_sidecar(out_dir: Path, sidecar: dict[str, dict[str, Any]], model: str,
                                updated_keys: set[str], *,
                                strategy_version: str = ANNOTATION_TRANSLATION_STRATEGY_VERSION) -> None:
    """批次完成热路径：每个已完成条目追加一行日志（fsync），不整档重写。

    崩溃不丢已完成翻译（行级 fsync）；日志超过阈值时在锁外触发一次整档压实
    （_write_translation_sidecar 重新取锁，文件锁不可重入）。跨进程并发合并
    语义不变：重放/压实都走 _merge_translation_update（已接受优先 + CAS）。
    """
    out_dir = Path(out_dir).expanduser().resolve()
    journal_path = governed_artifact_path(
        out_dir, _TRANSLATION_JOURNAL_NAME, category="cache"
    )
    # 日志是机器专用崩溃恢复缓存，唯一的读端是 _read_translation_journal
    # （json.loads 对 \u 转义透明）。强制 ensure_ascii=True：文件字节纯 ASCII，
    # U+2028/U+2029 等行分隔符类字符物理上不可能原样落盘撕裂行结构。
    lines = [
        json.dumps({
            "version": _TRANSLATION_JOURNAL_VERSION,
            "model": model,
            "strategy_version": strategy_version,
            "key": key,
            "entry": sidecar[key],
        }, ensure_ascii=True)
        for key in sorted(updated_keys)
    ]
    with _translation_sidecar_lock(out_dir):
        # P2：Windows AV/索引器瞬时占用日志时，裸 open 的 PermissionError 会从批次
        # 完成路径直接中止整个付费翻译运行（异常穿出批次循环）。与
        # review_state._replace_with_retry 同口径：8 次尝试 × 0.02s×(1..7) 线性退避，
        # 预算耗尽后原样重抛——响亮失败，由调用方既有错误处理决定运行去留。
        # 幂等性（重试不产生重复/胶着字节）：_truncate_torn_journal_tail 对已完好
        # （以 LF 结尾或不存在）的文件是 no-op，重试不会二次截断好行；行只在成功
        # open 后写一次——若写中途失败留下半行，下一次尝试先经撕裂尾截断清掉那些
        # 残字节再续写，文件任何时刻都保持行完好（无 glued 行）。
        for attempt in range(_TRANSLATION_JOURNAL_APPEND_ATTEMPTS):
            try:
                _truncate_torn_journal_tail(journal_path)
                with journal_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write("\n".join(lines) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                break
            except PermissionError:
                if attempt + 1 >= _TRANSLATION_JOURNAL_APPEND_ATTEMPTS:
                    raise
                time.sleep(_TRANSLATION_JOURNAL_APPEND_RETRY_S * (attempt + 1))
        try:
            compact = journal_path.stat().st_size >= _TRANSLATION_JOURNAL_COMPACT_BYTES
        except OSError:
            compact = False
    if compact:
        _write_translation_sidecar(out_dir, sidecar, model, updated_keys,
                                   strategy_version=strategy_version)

def _resolve_guarded_translation(chat: Any, *, owner: str, text: str,
                                 batch_translation: str, model: str,
                                 batch_failure: str = "",
                                 strategy_version: str = ANNOTATION_TRANSLATION_STRATEGY_VERSION,
                                 strict: bool = False
                                 ) -> tuple[dict[str, Any], dict[str, int]]:
    attempts = {"batch": 1, "single": 0, "sentence": 0}
    metrics = {"single_retries": 0, "segment_retries": 0,
               "segment_calls": 0, "retry_calls": 0, "failed_calls": 0}
    rejections: list[dict[str, Any]] = []
    base: dict[str, Any] = {
        "owner": owner,
        "model": model,
        "source_head": " ".join(text.split())[:120],
        "strategy_version": strategy_version,
        "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
    }
    # strict（v3）= 双向护栏（缺失+新增）；非 strict（v2）= 仅新增，行为不变。
    guard_reason = "drift_tokens" if strict else "fabricated_tokens"

    guard_text = _translation_guard_source(text)
    batch_drift, batch_fabricated = (
        _translation_drift(guard_text, batch_translation, strict=strict)
        if batch_translation else ([], []))
    if batch_translation and not batch_drift and not batch_failure:
        return ({**base, "translation": batch_translation, "rejected": False,
                 "status": "accepted", "strategy": "batch", "attempts": attempts,
                 "retry_count": 0, "rejections": rejections}, metrics)
    if batch_drift:
        rejections.append({"strategy": "batch", "reason": guard_reason,
                           "drift_tokens": batch_drift, "fabricated_tokens": batch_fabricated})
    else:
        rejections.append({"strategy": "batch", "reason": batch_failure or "missing_translation"})

    attempts["single"] = 1
    metrics["single_retries"] = 1
    metrics["retry_calls"] = 1
    # forbidden_tokens 只取译文新增（「严禁再次出现」仅对新增语义成立；缺失方向由重试再给一次机会）。
    forbidden_tokens = list(batch_fabricated)
    required_tokens = _missing_translation_tokens(batch_drift)
    try:
        single = _translate_marker_single(
            chat, text, forbidden_tokens=forbidden_tokens,
            required_tokens=required_tokens,
            retry_reason=batch_failure or "批次漏回本条")
    except Exception as exc:
        single = ""
        metrics["failed_calls"] += 1
        rejections.append({"strategy": "single", "reason": "call_failed",
                           "detail": str(exc)[:160]})
    if single:
        single_drift, single_fabricated = _translation_drift(
            guard_text, single, strict=strict)
        if not single_drift:
            return ({**base, "translation": single, "rejected": False,
                     "status": "accepted", "strategy": "single", "attempts": attempts,
                     "retry_count": 1, "rejections": rejections}, metrics)
        forbidden_tokens = sorted(set(forbidden_tokens) | set(single_fabricated))
        required_tokens = _missing_translation_tokens(single_drift)
        rejections.append({"strategy": "single", "reason": guard_reason,
                           "drift_tokens": single_drift, "fabricated_tokens": single_fabricated})
    elif not any(item.get("strategy") == "single" for item in rejections):
        rejections.append({"strategy": "single", "reason": "missing_translation"})

    segments = _split_translation_segments(guard_text)
    if len(segments) < 2:
        had_guard_rejection = any(
            item.get("reason") in ("fabricated_tokens", "drift_tokens") for item in rejections)
        reason_prefix = (
            "翻译存在受保护编码/数值/单位漂移" if strict and had_guard_rejection
            else "翻译含无据编码/数字" if had_guard_rejection
            else "翻译调用未得到可校验结果"
        )
        reason = f"{reason_prefix}；单条重试仍未通过，且原文无法可靠切成多个句段"
        unresolved = not had_guard_rejection
        return ({**base, "translation": "", "rejected": not unresolved,
                 "status": "unresolved" if unresolved else "rejected",
                 "strategy": "single", "reason": reason, "attempts": attempts,
                 "retry_count": attempts["single"], "rejections": rejections}, metrics)

    metrics["segment_retries"] = 1
    translated_segments: list[str] = []
    segment_failure = ""
    for index, segment in enumerate(segments, start=1):
        attempts["sentence"] += 1
        metrics["segment_calls"] += 1
        metrics["retry_calls"] += 1
        label = f"第 {index}/{len(segments)} 句段"
        try:
            translated = _translate_marker_single(
                chat, segment, forbidden_tokens=forbidden_tokens,
                required_tokens=_required_translation_tokens(segment), segment_label=label,
                retry_reason="此前重试未返回可校验译文")
        except Exception as exc:
            metrics["failed_calls"] += 1
            segment_failure = f"{label}调用失败: {str(exc)[:120]}"
            rejections.append({"strategy": "sentence", "segment": index,
                               "reason": "call_failed", "detail": str(exc)[:160]})
            break
        if not translated:
            segment_failure = f"{label}未返回译文"
            rejections.append({"strategy": "sentence", "segment": index,
                               "reason": "missing_translation"})
            break
        segment_drift, _seg_fabricated = _translation_drift(segment, translated, strict=strict)
        if segment_drift:
            segment_failure = f"{label}仍含漂移 token: {', '.join(segment_drift[:6])}"
            rejections.append({"strategy": "sentence", "segment": index,
                               "reason": guard_reason, "drift_tokens": segment_drift})
            break
        translated_segments.append(translated)

    if not segment_failure and len(translated_segments) == len(segments):
        assembled = "".join(translated_segments)
        assembled_drift, _asm_fabricated = _translation_drift(
            guard_text, assembled, strict=strict)
        if not assembled_drift:
            return ({**base, "translation": assembled, "rejected": False,
                     "status": "accepted", "strategy": "sentence", "attempts": attempts,
                     "retry_count": attempts["single"] + attempts["sentence"],
                     "rejections": rejections}, metrics)
        segment_failure = f"组装译文仍含漂移 token: {', '.join(assembled_drift[:6])}"
        rejections.append({"strategy": "sentence_assembled", "reason": guard_reason,
                           "drift_tokens": assembled_drift})

    had_guard_rejection = any(
        item.get("reason") in ("fabricated_tokens", "drift_tokens") for item in rejections)
    reason_prefix = (
        "翻译存在受保护编码/数值/单位漂移" if strict and had_guard_rejection
        else "翻译含无据编码/数字" if had_guard_rejection
        else "翻译调用未得到可校验结果"
    )
    reason = f"{reason_prefix}；句段降级未全部通过（{segment_failure}）"
    return ({**base, "translation": "", "rejected": had_guard_rejection,
             "status": "rejected" if had_guard_rejection else "unresolved",
             "strategy": "sentence", "reason": reason, "attempts": attempts,
             "retry_count": attempts["single"] + attempts["sentence"],
             "rejections": rejections}, metrics)

def generate_annotation_translations(out_dir: Path, *, route: str | None,
                                     texts: dict[str, tuple[str, str]] | None = None,
                                     chat: Any = None,
                                     translation_mode: str = "markers") -> dict[str, Any]:
    """块级"说明"标记的原文中文翻译（评审卡三段式：归类原因/原文翻译/原文引用）。

    翻译只在此处生成、按内容哈希写 annotation_translations.json；渲染层只读缓存，
    保持确定性（裁决回流免 LLM 重建不受影响）。护栏同硬件翻译通路（检查单 #2）：
    忠实翻译不会引入源文没有的编码/数字；批次被拒后按单条、句段两级降级，所有层级
    逐条过同一护栏。旧成功缓存先过当前护栏再零调用复用，旧策略拒绝项会重新尝试。

    翻译交付模式（方案 §13，M6）：
    - ``markers``（默认，既有行为）：补齐批注 marker；
    - ``off``：只做缓存维护/迁移/失效，**绝不发起 provider 调用**（真实路由也一样）；
    - ``full``：先从全文 sidecar（document_translations.jsonl，同 translation_key
      键位）确定性采纳已验收译文（逐条过本模块同一护栏），采纳后剩余 marker 仍走
      marker 路径——full 完成后 export 只在覆盖缺口时补调，不重复翻译已交付内容。
    """
    out_dir = Path(out_dir).expanduser().resolve()
    if translation_mode not in ("off", "markers", "full"):
        raise ValueError(f"未知翻译交付模式: {translation_mode}")
    if texts is None:
        # 渲染态（marker 收集字典）由 doc_annotation_export 持有——惰性回调原模块，
        # 避免顶层循环导入（dae 对本模块是重导出关系）
        import doc_annotation_export as _dae

        _dae.render_annotation_html(out_dir)   # 收集本文档全部说明标记文本
        texts = dict(_dae._collected_marker_texts)
    # 优化批处理默认 10；显式 0 回退旧 batch=8。两条路径都保留越界/重复 id
    # fail-closed 卫生处理，优化路径增加双上限装包、拆半降级与严格逐条护栏。
    optimized_count = _translate_batch_count()
    optimized = optimized_count > 0
    strategy_version = _active_translation_strategy_version()
    sidecar = _read_translation_sidecar(out_dir)
    reusable = {
        key for key, (_owner, text) in texts.items()
        if key in sidecar
        and _translation_entry_is_reusable(sidecar[key], text,
                                           strategy_version=strategy_version, strict=optimized)
    }
    invalidated_keys = {
        key for key, (_owner, text) in texts.items()
        if key in sidecar
        and key not in reusable
        and str(sidecar[key].get("translation") or "").strip()
        and not sidecar[key].get("rejected")
        and _translation_drift(
            _translation_guard_source(text),
            str(sidecar[key].get("translation") or ""), strict=optimized)[0]
    }
    migrated_keys = {
        key for key in reusable
        if not sidecar[key].get("rejected")
        and sidecar[key].get("guards_version") != ANNOTATION_TRANSLATION_GUARDS_VERSION
    }
    for key in migrated_keys:
        sidecar[key]["guards_version"] = ANNOTATION_TRANSLATION_GUARDS_VERSION
    for key in invalidated_keys:
        owner, text = texts[key]
        unsafe_translation = str(sidecar[key].get("translation") or "")
        sidecar[key] = {
            **sidecar[key],
            "owner": owner,
            "translation": "",
            "rejected": False,
            "status": "unresolved",
            "reason": "旧缓存译文未通过当前数字/编码护栏，等待重新翻译",
            "fabricated_tokens": _fabricated_translation_tokens(text, unsafe_translation),
            "invalidated_translation_sha256": hashlib.sha256(
                unsafe_translation.encode("utf-8")
            ).hexdigest(),
            "strategy_version": strategy_version,
            "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
        }
    pending = {key: value for key, value in texts.items() if key not in reusable}
    cached_rejected = sum(1 for key in reusable if sidecar[key].get("rejected"))
    summary: dict[str, Any] = {
        "route": "stub", "model": "", "total_markers": len(texts),
        "translation_mode": translation_mode,
        "strategy_version": strategy_version,
        "guards_version": ANNOTATION_TRANSLATION_GUARDS_VERSION,
        "cached": len(reusable), "cached_accepted": len(reusable) - cached_rejected,
        "cached_rejected": cached_rejected, "translated": 0, "rejected": 0,
        "cache_invalidated": len(invalidated_keys), "cache_migrated": len(migrated_keys),
        "unresolved": 0, "failed_calls": 0, "batch_calls": 0,
        "single_retries": 0, "segment_retries": 0, "segment_calls": 0,
        "retry_calls": 0,
    }
    if not pending:
        # 无新文本：不必解析 LLM 配置；缓存条目本就全部来自真 LLM。除零调用迁移外，
        # 上次崩溃残留的日志也在此压回 JSON（读侧 JSON-only，压实后恢复完整可见性）。
        summary["route"] = "openai_compatible" if summary["cached"] else "stub"
        if migrated_keys or _translation_journal_nonempty(out_dir):
            model = next((str(entry.get("model") or "") for entry in sidecar.values()), "")
            _write_translation_sidecar(out_dir, sidecar, model, migrated_keys,
                                       strategy_version=strategy_version)
        return summary
    metadata_keys = migrated_keys | invalidated_keys
    if metadata_keys:
        model = next((str(sidecar[key].get("model") or "") for key in metadata_keys), "")
        _write_translation_sidecar(out_dir, sidecar, model, metadata_keys,
                                   strategy_version=strategy_version)
    if translation_mode == "off":
        # off 模式（§13）：迁移/失效已写盘，未覆盖 marker 保持未翻译——绝不调用
        summary["translation_mode"] = "off"
        summary["skipped_by_mode"] = len(pending)
        return summary
    if translation_mode == "full":
        adopted = _adopt_full_sidecar_translations(out_dir, sidecar, pending,
                                                   strategy_version=strategy_version)
        if adopted:
            summary["adopted_from_full_sidecar"] = len(adopted)
            _write_translation_sidecar(
                out_dir, sidecar,
                next((str(sidecar[key].get("model") or "") for key in adopted), ""),
                adopted, strategy_version=strategy_version)
            pending = {key: value for key, value in pending.items() if key not in adopted}
            reusable |= adopted
            summary["cached"] = len(reusable)
            summary["cached_accepted"] = (
                len(reusable) - sum(1 for key in reusable if sidecar[key].get("rejected")))
            if not pending:
                summary["translation_mode"] = "full"
                return summary
        summary["translation_mode"] = "full"
    from functional_synthesis import _resolve_catalog_chat
    invoke, executed = _resolve_catalog_chat(route, chat)
    if invoke is None:
        summary["unresolved"] = len(pending)   # 诚实降级：stub 绝不虚标（检查单 #4）
        return summary
    summary["route"] = "openai_compatible"
    summary["model"] = executed.split(":", 1)[1] if executed.startswith("llm:") else executed
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from context_submit import submit_with_context

    pending_list = [(key, owner, text) for key, (owner, text) in pending.items()]
    if optimized:
        batches = _pack_translation_batches(
            pending_list, count_limit=optimized_count,
            max_chars=_translate_batch_max_chars())
        summary["batch_calls"] = 0   # 拆半可能追加调用，按实际累计
    else:
        batches = [pending_list[start:start + _TRANSLATION_BATCH]
                   for start in range(0, len(pending_list), _TRANSLATION_BATCH)]
        summary["batch_calls"] = len(batches)
    try:
        from ai_extract import resolve_concurrency
        workers = resolve_concurrency(None)
    except Exception:  # pragma: no cover - 兜底串行
        workers = 1
    # 并发批次 + 每批完成即追加日志落盘（分析富化 288 条串行数小时+零落盘的教训，同对策；
    # 追加而非整档重写：全档翻译的读-合-写累积成本是 O(N²)，且锁内序列化所有并发完成）
    journal_keys: set[str] = set()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        if optimized:
            futures = {submit_with_context(
                           executor, _translate_batch_with_splits, invoke, batch,
                           split_rounds=_TRANSLATION_SPLIT_ROUNDS): batch
                       for batch in batches}
        else:
            futures = {submit_with_context(
                           executor, _translate_marker_batch, invoke, batch): batch
                       for batch in batches}
        for future in as_completed(futures):
            batch = futures[future]
            batch_failure = ""
            if optimized:
                # _translate_batch_with_splits 永不抛异常；返回 (result, calls, failed)。
                translations, calls, failed = future.result()
                summary["batch_calls"] += calls
                summary["failed_calls"] += failed
                if not translations and failed:
                    batch_failure = "batch_unparseable"
            else:
                try:
                    translations, _parseable = future.result()
                except Exception as exc:
                    translations = {}
                    batch_failure = f"batch_call_failed: {str(exc)[:160]}"
                    summary["failed_calls"] += 1
            changed_keys: set[str] = set()
            for index, (key, owner, text) in enumerate(batch, start=1):
                translation = translations.get(index, "")
                entry, metrics = _resolve_guarded_translation(
                    invoke, owner=owner, text=text, batch_translation=translation,
                    model=summary["model"], strategy_version=strategy_version,
                    strict=optimized,
                    batch_failure=batch_failure or ("batch_missing_item" if not translation else ""))
                for metric, value in metrics.items():
                    summary[metric] += value
                if entry.get("status") == "unresolved":
                    summary["unresolved"] += 1
                    continue
                if entry.get("rejected"):
                    summary["rejected"] += 1
                else:
                    summary["translated"] += 1
                sidecar[key] = entry
                changed_keys.add(key)
            if changed_keys:
                journal_keys |= changed_keys
                _append_translation_sidecar(out_dir, sidecar, summary["model"], changed_keys,
                                            strategy_version=strategy_version)
                # 每批完成即 fsync 落日志，中途被杀不丢已完成的真实调用。
    if journal_keys:
        # 运行收尾整档压实：JSON-only 读侧（api_server/渲染层）看到完整终态，
        # 崩溃窗口只损失“最后一批尚未压实”的可见性，不损失已完成翻译。
        _write_translation_sidecar(out_dir, sidecar, summary["model"], journal_keys,
                                   strategy_version=strategy_version)
    return summary
