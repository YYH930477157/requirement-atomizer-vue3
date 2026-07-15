from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from difflib import SequenceMatcher
from typing import Any, Callable

_ACTION_TERMS = (
    "collect", "record", "store", "transmit", "report", "detect", "monitor", "support",
    "configure", "archive", "provide", "define", "manage", "synchronize", "sync",
    "采集", "收集", "记录", "存储", "远程传输", "传输", "上报", "报告", "检测", "监测",
    "支持", "配置", "归档", "提供", "定义", "管理", "同步", "要求", "功能",
    "远传", "发送", "通知", "执行", "控制", "查询", "读取", "获取", "保留", "触发",
)
_GENERIC_TERMS = (
    "the", "a", "an", "device", "meter", "system", "shall", "must", "should",
    "设备", "系统", "应", "必须", "须", "可", "相关", "数据对象", "及", "与", "和", "并", "将",
)
# 档位/型号变体识别(0715 通用化):原硬编码 (PM|PP) 是单一语料的档位前缀——用户禁令
# "不做单文档补丁"。通用形态=大写字母短前缀+数字(PM1/PV2/AFD3 类型号),紧贴或连字符
# (不允许空格分隔,防 "PAGE 3" 类误匹配);合并键仍是 模块+前缀+剥词概念 三重同值,
# 不同前缀/不同概念绝不跨并。
_PROFILE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,4})[-_]?(\d{1,3})(?![A-Za-z0-9])")
_PERIOD_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>分钟|分|小时|时|天|日|个月|月|秒|s|sec(?:ond)?s?|min(?:ute)?s?|h(?:our)?s?|days?|months?)",
    re.IGNORECASE,
)
_MEASURE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>L/h|m3/h|m\u00b3/h|%|\u00b0C|\u2103|V|A|Hz|bar|kPa|Pa|mm|cm|kg|g)(?![A-Za-z])",
    re.IGNORECASE,
)
_OBIS_RE = re.compile(r"\b\d+-\d+:[0-9.*xX]+(?:\.[0-9.*xX]+){1,4}\b")
_CLASS_RE = re.compile(r"(?:interface\s+class|class\s*id|class_id|接口类)\s*[:=]?\s*(\d+)", re.IGNORECASE)
_EVENT_RE = re.compile(r"([A-Za-z][A-Za-z\s-]{1,40}?\s+event|[\u4e00-\u9fffA-Za-z0-9_-]{1,20}事件)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def normalize_key(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _source_text(row: dict[str, Any]) -> str:
    return " ".join(str(row.get(key) or "") for key in (
        "title", "description", "requirement", "source_quote", "source_section"
    ))


def _strip_terms(text: str, terms: tuple[str, ...]) -> str:
    result = text.casefold()
    for term in sorted(terms, key=len, reverse=True):
        if re.fullmatch(r"[a-z]+", term):
            result = re.sub(rf"\b{re.escape(term)}\b", " ", result, flags=re.IGNORECASE)
        else:
            result = result.replace(term.casefold(), " ")
    return result


def _event_subject(text: str) -> str:
    candidates = _EVENT_RE.findall(text)
    if not candidates:
        return ""
    scored: list[tuple[int, str]] = []
    for candidate in candidates:
        cleaned = _strip_terms(candidate, _ACTION_TERMS + _GENERIC_TERMS)
        normalized = normalize_key(cleaned)
        if normalized:
            scored.append((len(normalized), normalized))
    return max(scored, default=(0, ""))[1]


def _variant_tokens(row: dict[str, Any]) -> list[str]:
    text = _source_text(row)
    # 档位/型号 token 只认标题(0715 通用化):标题里的型号是归组信号,
    # 正文里的字母数字组合(频率/模式/表格代号)是噪声
    title = str(row.get("title") or "") or text
    values: list[str] = []
    for prefix, number in _PROFILE_RE.findall(title):
        values.append(f"{prefix.upper()}{number}")
    for match in _PERIOD_RE.finditer(text):
        values.append(f"{match.group('value')} {match.group('unit')}")
    return _unique_strings(values)


def _protected_tokens(row: dict[str, Any]) -> list[str]:
    text = _source_text(row)
    values = list(_OBIS_RE.findall(text))
    values.extend(f"class {value}" for value in _CLASS_RE.findall(text))
    values.extend(_variant_tokens(row))
    return _unique_strings(values)


def _legacy_family(row: dict[str, Any]) -> tuple[str, str]:
    text = _source_text(row)
    module = normalize_key(row.get("module") or (_as_list(row.get("labels")) or [""])[0])
    profiles = _PROFILE_RE.findall(str(row.get("title") or "") or text)
    if profiles:
        prefixes = {prefix.upper() for prefix, _ in profiles}
        profile_family = sorted(prefixes)[0] if len(prefixes) == 1 else "PROFILE"
        stripped = _PROFILE_RE.sub(f" {profile_family} profile ", str(row.get("title") or text))
        concept = normalize_key(_strip_terms(stripped, _ACTION_TERMS + _GENERIC_TERMS))
        return f"{module}:profile:{profile_family}:{concept}", "protocol_profile_variant"

    periods = list(_PERIOD_RE.finditer(text))
    title = str(row.get("title") or row.get("description") or "")
    if periods and any(term in text.casefold() for term in ("archive", "归档", "曲线", "profile", "记录")):
        stripped = _PERIOD_RE.sub(" period ", title)
        concept = normalize_key(_strip_terms(stripped, _ACTION_TERMS + _GENERIC_TERMS))
        return f"{module}:period:{concept}", "period_variant"

    subject = _event_subject(title or text)
    if subject:
        return f"{module}:event:{subject}", "event_subject"

    stripped = _strip_terms(title, _ACTION_TERMS + _GENERIC_TERMS)
    concept = normalize_key(_PERIOD_RE.sub(" period ", _PROFILE_RE.sub(" profile ", stripped)))
    return f"{module}:concept:{concept or normalize_key(title)}", "legacy_concept"



_QUALIFIER_PAIRS = (
    (("不可更换", "non-replaceable", "not replaceable"), ("可更换", "replaceable")),
    (("非可选", "mandatory", "required"), ("可选", "optional")),
    (("禁止", "不得", "must not", "shall not"), ("允许", "may", "permitted")),
    (("正向", "进口", "import"), ("反向", "出口", "export")),
    (("本地", "local"), ("远程", "remote")),
)


def _family_identity(row: dict[str, Any]) -> tuple[str, str]:
    key, method = _legacy_family(row)
    parts = key.split(":", 2)
    return (parts[2] if len(parts) == 3 else key), method

def _opposed_qualifiers(a: dict[str, Any], b: dict[str, Any]) -> bool:
    text_a = _source_text(a).casefold()
    text_b = _source_text(b).casefold()
    for left, right in _QUALIFIER_PAIRS:
        a_left = any(term in text_a for term in left)
        a_right = any(term in text_a for term in right) and not a_left
        b_left = any(term in text_b for term in left)
        b_right = any(term in text_b for term in right) and not b_left
        if (a_left and b_right) or (a_right and b_left):
            return True
    return False

def _similar_legacy(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if _opposed_qualifiers(a, b):
        return False
    identity_a, method_a = _family_identity(a)
    identity_b, method_b = _family_identity(b)
    same_module = normalize_key(a.get("module")) == normalize_key(b.get("module"))
    if method_a == method_b and method_a in {"event_subject", "protocol_profile_variant", "period_variant"}:
        return identity_a == identity_b
    if not same_module or method_a != "legacy_concept" or method_b != "legacy_concept":
        return False
    if identity_a == identity_b:
        return True
    if min(len(identity_a), len(identity_b)) < 6:
        return False
    return SequenceMatcher(None, identity_a, identity_b).ratio() >= 0.88


def _numeric_constraints_by_unit(row: dict[str, Any]) -> dict[str, set[str]]:
    text = _source_text(row)
    constraints: dict[str, set[str]] = {}
    for pattern in (_PERIOD_RE, _MEASURE_RE):
        for match in pattern.finditer(text):
            unit = match.group("unit").casefold().replace("m\u00b3", "m3").replace("\u2103", "\u00b0c")
            constraints.setdefault(unit, set()).add(match.group("value"))
    return constraints


def _unqualified_parameter_conflicts(rows: list[dict[str, Any]], method: str) -> list[str]:
    if method in {"protocol_profile_variant", "period_variant"} or len(rows) < 2:
        return []
    by_row = [_numeric_constraints_by_unit(row) for row in rows]
    conflicts: list[str] = []
    units = {unit for values in by_row for unit in values}
    for unit in sorted(units):
        value_sets = {tuple(sorted(values.get(unit, set()))) for values in by_row if values.get(unit)}
        if len(value_sets) > 1:
            display_unit = {"l/h": "L/h", "m3/h": "m3/h", "°c": "°C"}.get(unit, unit)
            rendered = sorted({f"{value} {display_unit}" for values in value_sets for value in values})
            conflicts.append(f"同一功能存在未限定的冲突参数：{', '.join(rendered)}")
    return conflicts


def _group_has_unqualified_parameter_conflict(rows: list[dict[str, Any]], method: str) -> bool:
    return method != "explicit_key" and bool(_unqualified_parameter_conflicts(rows, method))

def _explicit_group_is_safe(rows: list[dict[str, Any]]) -> bool:
    if any(_opposed_qualifiers(row, other) for index, row in enumerate(rows) for other in rows[index + 1:]):
        return False
    key = normalize_key(rows[0].get("functional_key"))
    if key not in {"事件", "事件管理", "事件处理", "event", "eventmanagement"}:
        return True
    event_subjects = {_event_subject(_source_text(row)) for row in rows}
    event_subjects.discard("")
    return len(event_subjects) <= 1

def _catalog_groups(rows: list[dict[str, Any]]) -> list[tuple[list[dict[str, Any]], str]]:
    explicit: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
    legacy: list[dict[str, Any]] = []
    for row in rows:
        key = normalize_key(row.get("functional_key"))
        if key:
            explicit.setdefault(key, []).append(row)
        else:
            legacy.append(row)

    result: list[tuple[list[dict[str, Any]], str]] = []
    for group in explicit.values():
        if _explicit_group_is_safe(group):
            result.append((group, "explicit_key"))
        else:
            result.extend(([row], "singleton") for row in group)
    consumed: set[int] = set()
    for index, row in enumerate(legacy):
        if index in consumed:
            continue
        group = [row]
        consumed.add(index)
        changed = True
        while changed:
            changed = False
            for other_index, other in enumerate(legacy):
                if other_index in consumed:
                    continue
                if any(_similar_legacy(member, other) for member in group):
                    group.append(other)
                    consumed.add(other_index)
                    changed = True
        method = _legacy_family(group[0])[1] if len(group) > 1 else "singleton"
        if _group_has_unqualified_parameter_conflict(group, method):
            result.extend(([member], "singleton") for member in group)
        else:
            result.append((group, method))
    return result


def _variant_name(row: dict[str, Any]) -> str:
    tokens = _variant_tokens(row)
    if tokens:
        return " / ".join(tokens)
    return str(row.get("variant") or row.get("source_section") or row.get("title") or row.get("ai_req_id") or "variant").strip()


def _constraints(row: dict[str, Any]) -> list[str]:
    text = _source_text(row)
    values = _protected_tokens(row)
    for match in _PERIOD_RE.finditer(text):
        values.append(f"{match.group('value')} {match.group('unit')}")
    for field in ("threshold_table", "data_constraints"):
        value = row.get(field)
        if isinstance(value, dict):
            values.append(str(value))
        else:
            values.extend(str(item) for item in _as_list(value))
    return _unique_strings(values)


def _conflicts(rows: list[dict[str, Any]], variants: list[dict[str, Any]], method: str) -> list[str]:
    if len(rows) < 2 or variants or method in {"protocol_profile_variant", "period_variant"}:
        return []
    parameter_conflicts = _unqualified_parameter_conflicts(rows, method)
    if parameter_conflicts:
        return parameter_conflicts
    ownership = _unique_strings([row.get("ownership_override") for row in rows])
    if len(ownership) > 1:
        return [f"专家归属覆盖冲突：{', '.join(ownership)}"]
    return []


def _catalog_title(rows: list[dict[str, Any]], method: str) -> str:
    explicit = str(rows[0].get("functional_key") or "").strip()
    if explicit:
        return explicit
    if method == "event_subject":
        subject = _event_subject(" ".join(str(row.get("title") or "") for row in rows))
        return f"{subject}管理" if subject else str(rows[0].get("title") or "事件管理")
    if method == "protocol_profile_variant":
        prefix = _PROFILE_RE.search(str(rows[0].get("title") or "") or _source_text(rows[0]))
        return f"{prefix.group(1).upper()} 档位变体配置" if prefix else "协议档位配置"
    if method == "period_variant":
        title = _PERIOD_RE.sub("", str(rows[0].get("title") or "周期数据归档"))
        title = _WS_RE.sub(" ", title).strip(" -_/：:")
        return title or "周期数据归档"
    return str(rows[0].get("title") or rows[0].get("description") or "未命名功能").strip()


def _description(objective: str, behaviors: list[str], constraints: list[str], variants: list[dict[str, Any]],
                 design_options: list[str], conflicts: list[str]) -> str:
    parts = [f"目标：{objective}"]
    if behaviors:
        parts.append("行为：" + "；".join(behaviors))
    if constraints:
        parts.append("约束：" + "、".join(constraints))
    if variants:
        parts.append("变体：" + "；".join(f"{item['name']}（{item['behavior']}）" for item in variants))
    if design_options:
        parts.append("设计候选（非规范约束）：" + "；".join(design_options))
    if conflicts:
        parts.append("待澄清冲突：" + "；".join(conflicts))
    return "\n".join(parts)


_LIFECYCLE_ROLES = (
    ("collect", ("采集", "收集", "获取采样", "collect", "acquire", "sample")),
    ("configure", ("配置", "设置", "定义", "configure", "set ", "define")),
    ("detect", ("检测", "监测", "触发", "detect", "monitor", "trigger")),
    ("execute", ("执行", "控制", "计算", "execute", "control", "calculate")),
    ("store", ("存储", "记录", "归档", "保留", "store", "record", "archive", "retain")),
    ("query", ("查询", "读取", "获取", "query", "read", "retrieve", "get ")),
    ("report", ("上报", "传输", "发送", "通知", "report", "transmit", "send", "notify")),
    ("access", ("权限", "访问", "授权", "access", "authorize")),
    ("recover", ("恢复", "重试", "回退", "recover", "retry", "fallback")),
)


def _lifecycle_role(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "").casefold()
    description = str(row.get("description") or row.get("requirement") or "").casefold()
    first_sentence = re.split(r"[。.!?；;]", description, maxsplit=1)[0]
    for text in (title, first_sentence, description):
        matches: list[tuple[int, int, str]] = []
        for role_index, (role, terms) in enumerate(_LIFECYCLE_ROLES):
            for term in terms:
                position = text.find(term)
                if position >= 0:
                    matches.append((position, role_index, role))
        if matches:
            return min(matches)[2]
    return "behavior"


def _lifecycle_behaviors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "role": _lifecycle_role(row),
            "behavior": str(row.get("description") or row.get("requirement") or row.get("title") or "").strip(),
            "source_ai_requirement_ids": [str(row.get("ai_req_id") or "")],
            "source_block_ids": _unique_strings(_as_list(row.get("source_block_ids"))),
        }
        for row in rows
    ]

def _merge_group(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    source_ids = _unique_strings([row.get("ai_req_id") for row in rows])
    title = _catalog_title(rows, method)
    behaviors = _unique_strings([row.get("description") or row.get("requirement") or row.get("title") for row in rows])
    all_constraints = _unique_strings([value for row in rows for value in _constraints(row)])
    variant_rows = method in {"protocol_profile_variant", "period_variant"}
    variants = [
        {
            "name": _variant_name(row),
            "behavior": str(row.get("description") or row.get("title") or "").strip(),
            "constraints": _constraints(row),
            "source_ai_requirement_ids": [str(row.get("ai_req_id") or "")],
            "source_block_ids": _unique_strings(_as_list(row.get("source_block_ids"))),
        }
        for row in rows
    ] if variant_rows else []
    design_options = _unique_strings([value for row in rows for value in _as_list(row.get("design_options"))])
    conflicts = _conflicts(rows, variants, method)
    objective = f"实现{title}，并满足所有来源条款及适用变体。"
    evidence = [
        {
            "ai_req_id": str(row.get("ai_req_id") or ""),
            "source_section": str(row.get("source_section") or ""),
            "source_quote": str(row.get("source_quote") or ""),
            "source_block_ids": _unique_strings(_as_list(row.get("source_block_ids"))),
            "protected_tokens": _protected_tokens(row),
        }
        for row in rows
    ]
    stable = hashlib.sha1("\x1f".join(source_ids or [title]).encode("utf-8")).hexdigest()[:12]
    merge_confidence = 1.0 if method == "explicit_key" else (0.9 if method in {
        "event_subject", "protocol_profile_variant", "period_variant", "explicit_semantic"
    } else (0.75 if len(rows) > 1 else 1.0))
    reason = (
        "显式 functional_key 一致" if method == "explicit_key" else
        "跨章节共享同一事件主体与互补行为" if method == "event_subject" else
        "显式功能键措辞不同，但事件主体一致且约束兼容" if method == "explicit_semantic" else
        "同一协议家族的命名 profile 作为变体保留" if method == "protocol_profile_variant" else
        "同一归档功能的周期差异作为变体保留" if method == "period_variant" else
        "标题与功能主体高度一致" if len(rows) > 1 else
        "未找到足够安全的合并候选，保留单条"
    )
    related_objects = _unique_strings([
        value for row in rows for value in (
            _as_list(row.get("related_dlms_objects")) + _as_list(row.get("obis")) +
            [token for token in _protected_tokens(row) if _OBIS_RE.search(token) or token.startswith("class ")]
        )
    ])
    ownership = _unique_strings([row.get("ownership_override") for row in rows])
    return {
        "functional_requirement_id": f"FREQ-{stable}",
        "functional_key": (str(rows[0].get("functional_key") or "").strip() or
                           f"{str(rows[0].get('module') or '未分类').strip()}:{normalize_key(title)}"),
        "title": title,
        "objective": objective,
        "behaviors": behaviors,
        "lifecycle_behaviors": _lifecycle_behaviors(rows),
        "source_modules": _unique_strings([row.get("module") for row in rows]),
        "preconditions": _unique_strings([value for row in rows for value in _as_list(row.get("preconditions"))]),
        "data_constraints": all_constraints,
        "variants": variants,
        "exceptions": _unique_strings([value for row in rows for value in _as_list(row.get("exceptions"))]),
        "related_dlms_objects": related_objects,
        "description": _description(objective, behaviors, all_constraints, variants, design_options, conflicts),
        "module": str(rows[0].get("module") or "未分类"),
        "type": str(rows[0].get("type") or "functional"),
        "priority": str(rows[0].get("priority") or "P1"),
        "labels": _unique_strings([value for row in rows for value in _as_list(row.get("labels"))]),
        "source_ai_requirement_ids": source_ids,
        "source_block_ids": _unique_strings([value for row in rows for value in _as_list(row.get("source_block_ids"))]),
        "source_quotes": _unique_strings([row.get("source_quote") for row in rows]),
        "source_sections": _unique_strings([row.get("source_section") for row in rows]),
        "evidence": evidence,
        "developer_guidance": _unique_strings([value for row in rows for value in _as_list(row.get("developer_guidance") or row.get("dev_guidance"))]),
        "design_options": design_options,
        "acceptance_criteria": _unique_strings([value for row in rows for value in _as_list(row.get("acceptance_criteria"))]),
        "assumptions": _unique_strings([value for row in rows for value in _as_list(row.get("assumptions"))]),
        "ownership_override": ownership[0] if len(ownership) == 1 else None,
        "ownership_override_conflict": ownership if len(ownership) > 1 else [],
        "merge_method": method,
        "merge_confidence": merge_confidence,
        "synthesis_reason": reason,
        "conflict_flags": conflicts,
        "source_kind": "functional_synthesis",
    }



def _llm_group_is_safe(rows: list[dict[str, Any]]) -> bool:
    for index, row in enumerate(rows):
        if any(_opposed_qualifiers(row, other) for other in rows[index + 1:]):
            return False
    event_subjects = {_event_subject(_source_text(row)) for row in rows}
    event_subjects.discard("")
    if len(event_subjects) > 1:
        return False
    render_method = _llm_render_method(rows)
    return not _group_has_unqualified_parameter_conflict(rows, render_method)


def _llm_render_method(rows: list[dict[str, Any]]) -> str:
    profile_tokens = [_PROFILE_RE.findall(str(row.get("title") or "") or _source_text(row)) for row in rows]
    if len(rows) > 1 and all(tokens for tokens in profile_tokens):
        prefixes = {prefix.upper() for tokens in profile_tokens for prefix, _ in tokens}
        if len(prefixes) == 1:
            return "protocol_profile_variant"
    periods = [list(_PERIOD_RE.finditer(_source_text(row))) for row in rows]
    period_context = all(
        any(term in _source_text(row).casefold() for term in ("archive", "归档", "曲线", "profile", "记录"))
        for row in rows
    )
    if len(rows) > 1 and all(matches for matches in periods) and period_context:
        return "period_variant"
    return "llm_catalog"

CatalogChat = Callable[[str, str], dict[str, Any]]

_CATALOG_SYSTEM_PROMPT = (
    "你是需求功能目录编排器。只对给定原子需求分组，不改写需求内容。"
    "输出 JSON 对象 catalog[]；每项含 catalog_key、title、atom_ids、reason、confidence。"
    "每个 atom_id 必须且只能出现一次。相似但参数、协议 profile、方向或适用条件不同的条目，"
    "可以归入同一功能，但必须保留为后续变体；不同事件主体不得合并。"
)


def _llm_groups(rows: list[dict[str, Any]], chat: CatalogChat) -> list[tuple[list[dict[str, Any]], dict[str, Any]]] | None:
    expected = [str(row.get("ai_req_id") or "") for row in rows]
    if not expected or any(not value for value in expected) or len(expected) != len(set(expected)):
        return None
    compact = [{
        "atom_id": str(row.get("ai_req_id") or ""),
        "title": str(row.get("title") or ""),
        "description": str(row.get("description") or "")[:500],
        "source_section": str(row.get("source_section") or ""),
        "protected_tokens": _protected_tokens(row),
    } for row in rows]
    try:
        payload = chat(_CATALOG_SYSTEM_PROMPT, json.dumps({"atoms": compact}, ensure_ascii=False))
    except Exception:
        return None
    catalog = payload.get("catalog") if isinstance(payload, dict) else None
    if not isinstance(catalog, list) or not catalog:
        return None
    index = {str(row.get("ai_req_id") or ""): row for row in rows}
    seen: list[str] = []
    result: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    for item in catalog:
        if not isinstance(item, dict):
            return None
        atom_ids = [str(value or "") for value in _as_list(item.get("atom_ids"))]
        if not atom_ids or any(value not in index for value in atom_ids) or len(atom_ids) != len(set(atom_ids)):
            return None
        seen.extend(atom_ids)
        confidence = item.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return None
        if not 0.0 <= confidence <= 1.0 or (len(atom_ids) > 1 and confidence < 0.75):
            return None
        group_rows = [index[value] for value in atom_ids]
        if not _llm_group_is_safe(group_rows):
            return None
        result.append((group_rows, {
            "catalog_key": str(item.get("catalog_key") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
            "confidence": confidence,
        }))
    if sorted(seen) != sorted(expected) or len(seen) != len(set(seen)):
        return None
    return result

def _explicit_semantic_group_is_safe(rows: list[dict[str, Any]]) -> bool:
    if len(rows) < 2 or any(not normalize_key(row.get("functional_key")) for row in rows):
        return False
    if any(_opposed_qualifiers(row, other) for index, row in enumerate(rows) for other in rows[index + 1:]):
        return False
    subjects = [_event_subject(_source_text(row)) for row in rows]
    if any(not subject for subject in subjects) or len(set(subjects)) != 1:
        return False
    return not _group_has_unqualified_parameter_conflict(rows, "explicit_semantic")

def _consolidate_catalog_groups(
    source_groups: list[tuple[list[dict[str, Any]], str, dict[str, Any] | None]],
) -> list[tuple[list[dict[str, Any]], str, dict[str, Any] | None]]:
    consolidated = list(source_groups)
    changed = True
    while changed:
        changed = False
        for left_index in range(len(consolidated)):
            left_group, _left_method, _left_meta = consolidated[left_index]
            for right_index in range(left_index + 1, len(consolidated)):
                right_group, _right_method, _right_meta = consolidated[right_index]
                combined = left_group + right_group
                if _left_meta is not None or _right_meta is not None:
                    can_merge = _explicit_semantic_group_is_safe(combined)
                    merged_method = "explicit_semantic"
                else:
                    deterministic = _catalog_groups(combined)
                    can_merge = len(deterministic) == 1 and len(deterministic[0][0]) == len(combined)
                    merged_method = deterministic[0][1] if can_merge else ""
                    if not can_merge and _explicit_semantic_group_is_safe(combined):
                        can_merge = True
                        merged_method = "explicit_semantic"
                if not can_merge:
                    continue
                consolidated[left_index] = (combined, merged_method, None)
                consolidated.pop(right_index)
                changed = True
                break
            if changed:
                break
    return consolidated

def _title_is_source_safe(title: str, group: list[dict[str, Any]]) -> bool:
    """LLM 标题防漂移：标题里的受保护编码/数字必须在组内源文出现过（C2，0710 评审）。"""
    from cosem_behavior_spec import extract_codes, extract_ints
    basis = " ".join(
        " ".join(str(row.get(key) or "") for key in ("title", "description", "source_quote", "functional_key"))
        for row in group)
    return not (extract_codes(title) - extract_codes(basis)) and not (extract_ints(title) - extract_ints(basis))


def build_function_catalog(requirements: list[dict[str, Any]], *, chat: CatalogChat | None = None) -> list[dict[str, Any]]:
    rows = [dict(row) for row in requirements if isinstance(row, dict)]
    groups: list[tuple[list[dict[str, Any]], str, dict[str, Any] | None]] = []
    if chat is not None:
        by_module: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
        for row in rows:
            by_module.setdefault(str(row.get("module") or "未分类"), []).append(row)
        proposed: list[tuple[list[dict[str, Any]], str, dict[str, Any] | None]] = []
        for module_rows in by_module.values():
            mapped = _llm_groups(module_rows, chat)
            if mapped is None:
                proposed.extend((group, method, None) for group, method in _catalog_groups(module_rows))
            else:
                proposed.extend((group, "llm_catalog", meta) for group, meta in mapped)
        groups.extend(_consolidate_catalog_groups(proposed))
    else:
        groups.extend(_consolidate_catalog_groups([(group, method, None) for group, method in _catalog_groups(rows)]))

    items: list[dict[str, Any]] = []
    for group, method, meta in groups:
        render_method = _llm_render_method(group) if meta is not None else method
        item = _merge_group(group, render_method)
        if meta is not None:
            # C2（0710 评审）：LLM 标题是自由文本且直达交付「描述」列——含组内源文没有的
            # 编码/数字即弃用（保确定性标题）。编码/数字纪律对人读标题同样成立。
            if meta.get("title") and _title_is_source_safe(str(meta["title"]), group):
                item["title"] = meta["title"]
            # C2 同理（0711 评审）：catalog_key 是 LLM 自由文本，直达 functional_key 交付字段——
            # 含组内源文没有的编码/数字即弃用（保确定性 key），与 title 守卫同一基线。
            catalog_key = str(meta.get("catalog_key") or "")
            if catalog_key and _title_is_source_safe(catalog_key, group):
                item["functional_key"] = catalog_key
            item["synthesis_reason"] = meta.get("reason") or "文档级 LLM 功能目录映射"
            item["merge_confidence"] = meta.get("confidence", 0.0)
            item["merge_method"] = "llm_catalog"
            item["description"] = _description(
                item["objective"], item["behaviors"], item["data_constraints"],
                item["variants"], item["design_options"], item["conflict_flags"]
            )
        items.append(item)
    return items
