"""表格结构与单元格级需求闭环底座（table-structure-v6）。

集中管理此前散落在 atomize.py / ai_extract.py / spot_extract.py / extract_units.py 的
表格角色识别（标题/表头/行头/数据/分组标题）与粒度规划（row/cell/mixed leaf plan）。

红线：
- 纯确定性。LLM 绝不参与标题、表头、合并关系或源坐标的判定。
- 一个非空物理单元格（或合并区域）只生成一个 canonical cell；合并格仅存左上角
  anchor，其余坐标进 covered_coordinates，禁止复制文本冒充多个单元格。
- 行数只是分类置信证据，任何规范性内容不得因行数/单元格计数硬门而静默丢失。

v3（审核闭环）：结构角色与内容资格解耦（标题/表头位的规范性句按格成 claim，
裸 marker 只作 context）；合成表头（column_N）不参与矩阵事实判定；同格逐字节
    重复的句子按合并拼接伪影去重，不再误判多义务。

v5（证据契约）：矩阵事实列只接受受控操作轴或明确的轴成员，不再把任意缩写、
数字或名词后缀当作能力维度；无 merge 几何只表示证据不可用，不再启用旧分组标题
启发式；冒号规格的句形检测与需求资格分离，元数据不会被提升为正式需求。

v6（候选闭环）：已知元数据冒号规格继续作为确定性 context，类型化技术规格继续
形成 claim，其余冒号规格与被拒收矩阵维度中的 marker 形成默认排除、可定位、可由
专家提升或确认排除的结构审核候选，不再只留一个 needs_review 计数。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

TABLE_STRUCTURE_VERSION = "table-structure-v6"
TABLE_CELL_ITEM_SCHEMA = "table-cell-item/v1"

STRUCTURAL_ROLES = ("title", "header", "row_header", "data", "group_header")
TABLE_KINDS = ("parameter", "mapping_matrix", "prose_grid", "other")
LEAF_MODES = ("row", "cell", "mixed")
HEADER_DETECTION_STATUSES = ("explicit", "inferred", "ambiguous")

# --- 分类证据正则（集中自 ai_extract.py，保持判定口径不变）------------------------
PARAM_REQ_CELL_RE = re.compile(
    r"requirement|technical|characteristic|value|spec(?:ification)?|min(?:imum)?|max(?:imum)?"
    r"|limit|rating|nominal|tolerance|range|unit"
    r"|要求|指标|参数值|参数|规格|额定|限值|最小|最大|公差|单位|范围|值",
    re.IGNORECASE,
)
PARAM_DEF_CELL_RE = re.compile(r"^(term|definition|术语|定义|abbreviation|缩略语)", re.IGNORECASE)
PARAM_SECTION_RE = re.compile(
    r"terms|definitions|abbreviations|术语|定义|缩略语|bibliography|参考文献", re.IGNORECASE
)
PARAM_INDEX_CELL_RE = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s*$")
# Note 列是普通叙述列，其中的 mandatory/required/X 不是矩阵 marker（"1 shall support Note." 事故）
NOTE_HEADER_RE = re.compile(r"note|备注|说明|注释|comment|remark", re.IGNORECASE)
# 处置词表头不是能力维度（"Voltage shall support Status." 幻觉事故）：status/result/
# required/check 等列的 X 是检查结果或处置状态，不是"对象应支持该列"的义务；
# requirement/value 是行内容的泛称包装词（"Voltage shall support Requirement." 同源），
# 同样不提供二维能力维度
_DISPOSITION_HEADER_RE = re.compile(
    r"^\s*(?:status|state|result|required|check(?:ed)?|ok|n/?a|remarks?"
    r"|requirements?|values?|状态|结果|检查|备注)\s*$",
    re.IGNORECASE,
)

_POSITIVE_MARKERS = {"x", "yes", "true", "required", "mandatory", "applicable"}
_MATRIX_DIMENSION_MAX_LEN = 24
_MATRIX_MARKER_MIN_RATIO = 0.30
_PROSE_CELL_MIN_MEDIAN_LEN = 40
# 合成列名（unique_headers 对无表头/歧义表头的回退）——column_N 不是列维度证据：
# 无真实表头标签时矩阵分类与事实列判定一律不成立（内容保留，不合成句式）
_SYNTHETIC_HEADER_RE = re.compile(r"^column_\d+$")
# 前置标识格长度上限：标识格是对象名/短标签（"Logger"、"Voltage"），
# 超过此长度的前置格是兄弟义务句而非身份标识，不进上下文
_IDENTITY_CONTEXT_MAX_LEN = 120

_NORMATIVE_RE = re.compile(
    r"\bshall\b|\bmust\b|\bshould\b|\brequired\b|\bmandatory\b|\bshall\s+not\b|\bmust\s+not\b"
    r"|应当|必须|不得|应满足|应支持|须符合",
    re.IGNORECASE,
)
# atomize.is_requirement_like 同族的定义性约束（非 modal 的义务句式）
_NORMATIVE_PATTERN_RE = re.compile(
    r"\bcan\s+be\s+(?:valid\s+for|one\s+of|assigned|used\s+for)\b"
    r"|\b(?:default|factory)\s+value\s+of\b"
    r"|\balways\s+(?:begins|ends)\b|\bends\s+on\b"
    r"|\bvalid\s+for\b[^.;:]*\b\d+\b[^.;:]*\b(?:day|days|month|months|year|years|hour|hours)\b",
    re.IGNORECASE,
)
# 散文句：≥5 词且以句读结尾——表头标签不会以句号收尾（"Outputs can be assigned…"）
_SENTENCE_RE = re.compile(r"[.!?。！？]\s*$")
# 冒号规格："Battery service life: 15 years"——字母标签（无数字）+ 含数字/罗马数字/
# 全大写枚举的值（"Insulation class: II"、"Protection degree: IP54" 同为规格行）
_COLON_SPEC_RE = re.compile(
    r"^(?P<label>[A-Za-z][^:\d]{2,60}):\s+"
    r"(?P<value>(?:\S*\d|[IVX]{1,6}\b|[A-Z]{2,}\b).*)$"
)

# 结构化规格不天然等于需求。只有工程量/产品属性标签与可验证技术值同时成立时，
# 才授予确定性需求资格；Owner/Revision/Status 等文档元数据仍可被识别为 colon_spec，
# 但不会进入 claim 面。
_TECHNICAL_SPEC_LABEL_RE = re.compile(
    r"\b(?:accuracy|battery|capacity|class|consumption|current|degree|dimensions?|"
    r"frequency|humidity|ingress|insulation|lifetime|mass|power|protection|range|"
    r"rating|resolution|service\s+life|supply|temperature|tolerance|voltage|weight)\b",
    re.IGNORECASE,
)
_TECHNICAL_SPEC_VALUE_RE = re.compile(
    r"(?:\d(?:[\d.,]*)(?:\s*(?:%|A|Ah|dB|g|h|Hz|kg|m|mm|ms|s|V|VA|W|Wh|"
    r"day|days|hour|hours|month|months|year|years|°C))?\b|IP\d{2,3}\b|"
    r"[IVX]{1,6}\b)",
    re.IGNORECASE,
)
_METADATA_SPEC_LABEL_RE = re.compile(
    r"^\s*(?:approval|approved\s+by|author|date|document|owner|reference|revision|status)\s*$",
    re.IGNORECASE,
)


def is_technical_spec_text(text: str) -> bool:
    """Whether a colon specification is a typed, testable product property."""
    match = _COLON_SPEC_RE.fullmatch(str(text or "").strip())
    if match is None:
        return False
    return bool(
        _TECHNICAL_SPEC_LABEL_RE.search(match.group("label"))
        and _TECHNICAL_SPEC_VALUE_RE.search(match.group("value"))
    )


def is_metadata_spec_text(text: str) -> bool:
    """Whether a colon specification is document/workflow metadata."""
    match = _COLON_SPEC_RE.fullmatch(str(text or "").strip())
    return bool(match and _METADATA_SPEC_LABEL_RE.fullmatch(match.group("label")))


def is_untyped_colon_spec_text(text: str) -> bool:
    """Colon-shaped content that is neither metadata nor a typed technical fact."""
    return bool(
        obligation_signal(text) == "colon_spec"
        and not is_metadata_spec_text(text)
        and not is_technical_spec_text(text)
    )


def obligation_signal(text: str) -> str:
    """义务信号六值（内容资格维度的唯一来源，与结构角色/句形正交）。

    - "marker"：受控 marker 词（X/yes/required…）
    - "modal"：modal 动词（shall/must/应当/必须…）
    - "pattern"：定义性/能力句式（can be assigned / default value of…，无句号也算）
    - "colon_spec"：冒号规格（Battery service life: 15 years）
    - "sentence_shape"：仅句形（≥5 词有句读、无义务词）——弱信号。说明句不是
      义务（"说明句被登记为正式 claim"事故），弱信号内容走 ambiguous/needs_review
    - "none"：无信号
    """
    value = str(text or "")
    if not value.strip():
        return "none"
    if is_positive_marker(value):
        return "marker"
    if _NORMATIVE_RE.search(value):
        return "modal"
    if _NORMATIVE_PATTERN_RE.search(value):
        return "pattern"
    if _COLON_SPEC_RE.match(value.strip()):
        return "colon_spec"
    if _SENTENCE_RE.search(value) and len(value.split()) >= 5:
        return "sentence_shape"
    return "none"


# 强义务信号：只有这些构成需求资格；sentence_shape 是弱信号（ambiguous 证据）
_STRONG_OBLIGATION_SIGNALS = frozenset({"modal", "pattern"})


def is_normative_text(text: str) -> bool:
    """结构层规范性判定（保守子集：modal/定义性约束/冒号规格）。

    atomize.is_requirement_like 是更宽的领域判定；结构层回答"这段内容是否可能是
    义务"——用于决定标题/表头/单元格是否必须生成 claim（规范性内容绝不静默丢失）。
    判不出时保持非规范，但结构歧义会以 ambiguous/needs_review 呈现，不靠静默。"""
    signal = obligation_signal(text)
    return signal in _STRONG_OBLIGATION_SIGNALS or (
        signal == "colon_spec" and is_technical_spec_text(text)
    )


def is_positive_marker(value: str) -> bool:
    return normalize_header_part(value) in _POSITIVE_MARKERS


def normalize_header_part(value: Any) -> str:
    text = re.sub(r"[\s_\-]+", " ", str(value or "").strip().lower())
    return text


def clean_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _median_len(values: Iterable[str]) -> float:
    lengths = sorted(len(v) for v in values)
    if not lengths:
        return 0.0
    mid = len(lengths) // 2
    if len(lengths) % 2:
        return float(lengths[mid])
    return (lengths[mid - 1] + lengths[mid]) / 2.0


def column_letter(index: int) -> str:
    """1-based 列号 → Excel 列字母。"""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters or "A"


def a1_address(row: int, column: int) -> str:
    return f"{column_letter(column)}{row}"


def pad_row(row: list[str], width: int) -> list[str]:
    return [row[index] if index < len(row) else "" for index in range(width)]


def row_is_normative(row: list[str]) -> bool:
    return any(is_normative_text(cell) for cell in row if str(cell or "").strip())


def row_is_weak_signal(row: list[str]) -> bool:
    """整行唯一的规范性是句形弱信号（说明句）——不构成义务、也不许冒充列名/标题。"""
    return any(
        obligation_signal(cell) == "sentence_shape"
        for cell in row
        if str(cell or "").strip()
    )


def row_bears_normative_sentence(row: list[str]) -> bool:
    """modal/能力句式才算"义务句"——冒号规格/短标签不算（DLMS 服务名表头），
    句形说明句也不算（弱信号走 ambiguous，不作 claim 或列名的依据）。

    用于区分"表头位混入了真正的义务句"（危险，列名须降级 column_N）与
    "表头标签本身命中规格模式"（"xDLMS Service: GET" 服务名表头——合法
    维度名，降级会灭失服务维度使矩阵事实全部消失）。"""
    return any(
        obligation_signal(cell) in {"modal", "pattern"}
        for cell in row
        if str(cell or "").strip()
    )


# --- 合并证据 ---------------------------------------------------------------------

def normalize_merge_ranges(
    merge_ranges: Iterable[Iterable[int]] | None,
) -> list[tuple[int, int, int, int]]:
    """统一为 (min_row, min_col, max_row, max_col)，1-based 闭区间。"""
    normalized: list[tuple[int, int, int, int]] = []
    for entry in merge_ranges or []:
        values = [int(v) for v in entry]
        if len(values) != 4:
            continue
        min_row, min_col, max_row, max_col = values
        if max_row < min_row or max_col < min_col:
            continue
        normalized.append((min_row, min_col, max_row, max_col))
    return sorted(normalized)


def merge_anchor_for(
    row: int, column: int, merge_ranges: list[tuple[int, int, int, int]]
) -> tuple[int, int, int, int] | None:
    for min_row, min_col, max_row, max_col in merge_ranges:
        if min_row <= row <= max_row and min_col <= column <= max_col:
            return (min_row, min_col, max_row, max_col)
    return None


def covered_coordinates(
    merge_ranges: list[tuple[int, int, int, int]],
) -> set[tuple[int, int]]:
    """所有被合并覆盖的非 anchor 坐标。"""
    covered: set[tuple[int, int]] = set()
    for min_row, min_col, max_row, max_col in merge_ranges:
        for row in range(min_row, max_row + 1):
            for column in range(min_col, max_col + 1):
                if (row, column) != (min_row, min_col):
                    covered.add((row, column))
    return covered


def merge_ranges_overlap(
    merge_ranges: Iterable[Iterable[int]],
) -> bool:
    """合并证据矛盾检测：去重后任两 range 面积相交（含包含）即矛盾。

    完全相同的重复 range 是幂等证据（先去重）；其余任何共享坐标都说明上游
    几何解析自相矛盾——调用方必须放弃精确合并（保留文本），不得照常使用。"""
    normalized = sorted({tuple(entry) for entry in normalize_merge_ranges(merge_ranges)})
    owners: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for entry in normalized:
        min_row, min_col, max_row, max_col = entry
        for row in range(min_row, max_row + 1):
            for column in range(min_col, max_col + 1):
                if (row, column) in owners:
                    return True
                owners[(row, column)] = entry
    return False


def validate_merge_text(
    matrix: list[list[str]],
    merge_ranges: Iterable[Iterable[int]],
) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, int, int, int]]]:
    """被覆盖格文本校验（B6）：合并不仅要有几何证据，被覆盖格还必须文本兼容。

    返回 (valid_ranges, conflict_ranges)。冲突判据：被覆盖坐标存在非空文本且
    与 anchor 文本不逐字一致（clean_cell 归一后）——说明该 range 覆盖了另一条
    独立内容，照常合并会让被覆盖内容随 covered 坐标删除而消失（审计计数全零
    的静默丢失）。冲突 range 被整体拒收（保留全部格为独立 cell），合法 range
    不受影响。被覆盖格为空或与 anchor 同文（解析器重复填充）均合法。"""
    valid: list[tuple[int, int, int, int]] = []
    conflict: list[tuple[int, int, int, int]] = []
    for entry in normalize_merge_ranges(merge_ranges):
        min_row, min_col, max_row, max_col = entry
        anchor_text = ""
        if min_row - 1 < len(matrix) and min_col - 1 < len(matrix[min_row - 1]):
            anchor_text = clean_cell(matrix[min_row - 1][min_col - 1])
        conflicting = False
        for row in range(min_row, max_row + 1):
            if conflicting:
                break
            for column in range(min_col, max_col + 1):
                if (row, column) == (min_row, min_col):
                    continue
                if row - 1 >= len(matrix) or column - 1 >= len(matrix[row - 1]):
                    continue
                covered_text = clean_cell(matrix[row - 1][column - 1])
                if covered_text and covered_text != anchor_text:
                    conflicting = True
                    break
        (conflict if conflicting else valid).append(entry)
    return valid, conflict


def inherit_merged_text(
    matrix: list[list[str]],
    merge_ranges: Iterable[Iterable[int]] | None,
) -> list[list[str]]:
    """covered 坐标继承 anchor 文本的"有效矩阵"（判定专用，不冒充物理内容）。

    docx 扁平矩阵本就把合并值填充到覆盖格；xlsx/pdf 的覆盖格是空串——继承使
    三种格式的分类/表头/上下文判定口径一致（纵向合并的对象名对后续行可见）。
    仅用于分类、表头合成与上下文继承；块渲染与 cell 正文恒用真实矩阵。"""
    normalized = normalize_merge_ranges(merge_ranges)
    if not normalized:
        return [list(row) for row in matrix]
    effective = [list(row) for row in matrix]
    for min_row, min_col, max_row, max_col in normalized:
        if min_row - 1 >= len(matrix) or min_col - 1 >= len(matrix[min_row - 1]):
            continue
        anchor_text = clean_cell(matrix[min_row - 1][min_col - 1])
        if not anchor_text:
            continue
        for row in range(min_row, max_row + 1):
            for column in range(min_col, max_col + 1):
                if (row, column) == (min_row, min_col):
                    continue
                if row - 1 < len(effective) and column - 1 < len(effective[row - 1]):
                    if not clean_cell(effective[row - 1][column - 1]):
                        effective[row - 1][column - 1] = matrix[min_row - 1][min_col - 1]
    return effective


_ABBREVIATIONS = frozenset({
    "e.g.", "i.e.", "etc.", "fig.", "no.", "dr.", "mr.", "mrs.", "ms.",
    "prof.", "vs.", "approx.", "incl.", "excl.", "cf.", "st.",
})


def _dot_is_boundary(text: str, index: int) -> bool:
    if (
        index
        and index + 1 < len(text)
        and text[index - 1].isalnum()
        and text[index + 1].isalnum()
    ):
        return False
    prefix = text[max(0, index - 12):index + 1].casefold()
    if any(prefix.endswith(abbreviation) for abbreviation in _ABBREVIATIONS):
        return False
    return True


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """按句切分（不归一化源文本；返回的 span 恰好拼成原文）。

    结构层与 claim 层共用同一切句器（多义务格判定与 cell claim 按句出 claim
    必须同口径，否则归属与切分会分叉）。"""
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        boundary = char in "!?;。！？；\n\r"
        if char == ".":
            boundary = _dot_is_boundary(text, index)
        if boundary:
            end = index + 1
            while end < len(text) and text[end] in ".!?;。！？；":
                end += 1
            while end < len(text) and text[end].isspace():
                end += 1
            if end > start and text[start:end].strip():
                spans.append((start, end))
                start = end
            index = end
            continue
        index += 1
    if start < len(text):
        if spans and not text[start:].strip():
            left_start, _ = spans[-1]
            spans[-1] = (left_start, len(text))
        else:
            spans.append((start, len(text)))
    if not spans:
        return [(0, len(text))]

    # PDF repair can leave punctuation-only fragments between otherwise valid
    # sentences. Keep those characters in the source partition, but attach them
    # to a neighboring lexical span instead of manufacturing a standalone claim.
    merged: list[tuple[int, int]] = []
    leading_start: int | None = None
    for span_start, span_end in spans:
        if any(char.isalnum() for char in text[span_start:span_end]):
            if leading_start is not None:
                span_start = leading_start
                leading_start = None
            merged.append((span_start, span_end))
        elif merged:
            merged[-1] = (merged[-1][0], span_end)
        elif leading_start is None:
            leading_start = span_start
    return merged or [(0, len(text))]


def full_width_merge_row(
    row_index: int, width: int, merge_ranges: list[tuple[int, int, int, int]]
) -> tuple[int, int, int, int] | None:
    """该行是否是一个跨满整表宽度的合并区域的 anchor 行。"""
    if width <= 0:
        return None
    for min_row, min_col, max_row, max_col in merge_ranges:
        if min_row == row_index and min_col == 1 and max_col >= width:
            return (min_row, min_col, max_row, max_col)
    return None


def is_group_header_row(
    row: list[str],
    row_index: int,
    *,
    width: int,
    merge_ranges: list[tuple[int, int, int, int]] | None,
) -> bool:
    """分组标题行：全宽合并 anchor + 所有非空格同值 + 文本非规范性。

    "所有单元格值相同"只有在共享同一 merge anchor 且文本非规范性时才判分组标题；
    规范性全宽行是标题/义务行，必须生成 claim；无合并证据的同值行按数据行处理。"""
    non_empty = [clean_cell(cell) for cell in row if clean_cell(cell)]
    if not non_empty or len(set(non_empty)) != 1:
        return False
    # 分组标题必须有正向全宽 merge 证据。None 在当前解析链表示几何不可用，
    # 不是授予旧启发式的许可证；旧产物由版本迁移门处理。
    if not merge_ranges or full_width_merge_row(row_index, width, merge_ranges) is None:
        return False
    return not is_normative_text(non_empty[0])


# --- 结构识别 ---------------------------------------------------------------------

def detect_title_rows(
    matrix: list[list[str]],
    *,
    width: int,
    merge_ranges: list[tuple[int, int, int, int]] | None,
) -> tuple[list[int], list[str]]:
    """标题行：表顶部全宽合并行（合并证据是硬条件，删除"首行一个非空格即标题"硬规则）。

    v4 起删除 single_cell_inferred 弱推断分支（P0-5 复审）：无合并/题注/样式证据的
    首行单格一律不静默判标题——它留在结构里由 ambiguous_structure_rows 机制成
    "可定位的歧义资格候选"（context + 计数 + needs_review），内容资格由
    structural_row 逐格保全；唯一硬证据是全宽合并。"""
    title_rows: list[int] = []
    evidence: list[str] = []
    if merge_ranges:
        for offset, row in enumerate(matrix):
            row_index = offset + 1
            non_empty = [clean_cell(cell) for cell in row if clean_cell(cell)]
            if not non_empty:
                break
            if (
                full_width_merge_row(row_index, width, merge_ranges) is not None
                and len(set(non_empty)) == 1
            ):
                title_rows.append(row_index)
                evidence.append(f"full_width_merge:R{row_index}")
                continue
            break
    return title_rows, evidence


def detect_header_rows(
    matrix: list[list[str]],
    *,
    width: int,
    title_row_indexes: list[int],
    explicit_header_rows: list[int] | None,
    merge_ranges: list[tuple[int, int, int, int]] | None,
) -> tuple[list[int], str, list[str]]:
    """表头行识别。返回 (header_row_indexes, status, evidence)。

    - explicit：Excel Table 定义 / DOCX tblHeader 等确定性证据。
    - inferred：延续表头启发式（原 infer_header_row_count 口径）；首两行都呈需求句
      时走 headerless（0 表头行，首行不得丢失）。
    - ambiguous：证据冲突（如首行呈规范性却落在表头位）；结构进审核，内容完整保留。
    """
    title_set = set(title_row_indexes)
    body = [(index + 1, row) for index, row in enumerate(matrix) if (index + 1) not in title_set]
    if not body:
        return [], "inferred", ["no_body_rows"]

    if explicit_header_rows is not None:
        # 显式证据（Excel Table 定义/DOCX tblHeader）：空列表 = 显式 headerless，
        # 不得退回推断把首行数据误判为表头
        explicit = sorted(r for r in explicit_header_rows if r not in title_set and r <= len(matrix))
        if explicit or not explicit_header_rows:
            return explicit, "explicit", [
                f"explicit_header_rows:{','.join(str(r) for r in explicit) or 'headerless'}"
            ]

    first_index, first_row = body[0]
    second_row = body[1][1] if len(body) > 1 else None
    first_normative = row_is_normative(first_row)
    second_normative = row_is_normative(second_row) if second_row is not None else False

    if first_normative and (second_row is None or second_normative):
        # headerless：首两行都呈需求句（或全表只有一行规范性内容）→ 无表头，
        # column_1... 生效，首行进数据区——规范性内容绝不因表头推断而静默丢失；
        # 单行表结构无法确证，标 ambiguous 进审核
        evidence = ["first_two_rows_normative:headerless"]
        status = "inferred"
        if second_row is None:
            evidence.append("single_normative_row:ambiguous")
            status = "ambiguous"
        return [], status, evidence

    first_non_empty = [clean_cell(cell) for cell in first_row if clean_cell(cell)]
    if (
        width >= 2
        and second_row is not None
        and not second_normative
        and len(first_non_empty) == 1
        and obligation_signal(first_non_empty[0]) not in {"modal", "pattern"}
    ):
        # 首行单格题注候选 + 次行是真实表头（P0-5 后续实测回归）：v4 首版让
        # 单格行独占表头位，列名整表坍缩成 column_N 合成表头，真实表头行
        # （Label/Value/Formula）连带掉进数据区。单格行仍走
        # _ambiguous_structure_rows 计数待审（不静默判标题/表头）；列名改由
        # 次行供给（atomize 按行过滤命名，义务句/弱信号/单格行永不命名）。
        # modal/pattern 单格首行不进此分支——义务句保留 cell claim 路径。
        return (
            [first_index, body[1][0]],
            "inferred",
            [
                "first_row_single_cell:ambiguous",
                f"header_after_single_cell:R{body[1][0]}",
            ],
        )

    header_rows = [first_index]
    evidence = ["first_row_header:default"]
    status = "inferred"
    if first_normative:
        # 首行呈规范性却被判为表头——结构与内容角色冲突，进审核（内容仍完整保留）。
        # 仅冒号规格/短标签命中（DLMS "xDLMS Service: GET" 服务名表头）不算句子：
        # 标 inferred 保留列名，不降级 column_N（降级灭失服务维度 → 矩阵事实全灭，
        # golden capability_matrix 漂移实证）
        if row_bears_normative_sentence(first_row):
            status = "ambiguous"
            evidence.append("first_row_normative:ambiguous")
        else:
            evidence.append("first_row_label_spec:header")
    elif row_is_weak_signal(first_row):
        # 弱信号（句形说明句）首行：既不足以当义务、也不许冒充列名（内容可能
        # 因此从 claim 面消失）——降级 column_N + ambiguous 待审，原文保留
        status = "ambiguous"
        evidence.append("first_row_sentence_shape:ambiguous")

    # 多级表头延续（原 is_continuation_header_row 口径，上限 3 行）
    first_header = pad_row(first_row, width)
    for next_index, candidate in body[1:3]:
        if len(header_rows) >= 3:
            break
        if not is_continuation_header_row(first_header, pad_row(candidate, width)):
            break
        header_rows.append(next_index)
        evidence.append(f"continuation_header:R{next_index}")
    return header_rows, status, evidence


def is_continuation_header_row(first_header: list[str], candidate: list[str]) -> bool:
    if not first_header or not candidate:
        return False
    if any(is_positive_marker(value) for value in candidate):
        return False
    top_values = [normalize_header_part(value) for value in first_header if normalize_header_part(value)]
    has_repeated_top_header = len(top_values) != len(set(top_values))
    if not has_repeated_top_header:
        return False
    first_top = normalize_header_part(first_header[0])
    first_candidate = normalize_header_part(candidate[0])
    if first_top and first_candidate == first_top:
        return True
    if not first_candidate and any(clean_cell(value) for value in candidate[1:]):
        return True
    return False


def unique_headers(raw_headers: list[str], width: int) -> list[str]:
    headers: list[str] = []
    counts: dict[str, int] = {}
    for index in range(width):
        base = clean_cell(raw_headers[index]) if index < len(raw_headers) else ""
        if not base:
            base = f"column_{index + 1}"
        counts[base] = counts.get(base, 0) + 1
        headers.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return headers


def effective_headers(header_rows: list[list[str]], width: int) -> list[str]:
    if not header_rows:
        return unique_headers([], width)
    headers: list[str] = []
    for column_index in range(width):
        parts: list[str] = []
        seen: set[str] = set()
        for row in header_rows:
            value = clean_cell(row[column_index] if column_index < len(row) else "")
            key = normalize_header_part(value)
            if not key or key in seen:
                continue
            seen.add(key)
            parts.append(value)
        headers.append(" ".join(parts))
    return unique_headers(headers, width)


def _ambiguous_structure_rows(
    matrix: list[list[str]],
    *,
    width: int,
    title_rows: list[int],
    header_rows: list[int],
    explicit_header_rows: list[int] | None,
    merge_ranges: list[tuple[int, int, int, int]] | None,
) -> list[int]:
    """无结构证据支撑的单格标题/表头行（P0-5 复审）——"可定位的歧义资格候选"。

    被判为标题/表头的行若只有一个非空格、且没有任何硬结构证据（全宽合并、
    调用方显式声明），关闭为标题/表头就等于把一格内容从 claim 面静默删除
    （"Configurable auxiliary output" 类单格能力 0 claim + 审计全零 + ok）。
    这类行不静默关闭：modal/pattern 义务句仍走 structural_row 的 cell claim
    （规范性绝不静默丢失），其余信号（none/sentence_shape/colon_spec/marker）
    由 plan_table_leaves 计 ambiguous_structure_cells → needs_review。
    宽度 ≥2 的多列表里单格行无法命名其他列；1×1 退化表同样无证据可依。"""
    explicit = set(explicit_header_rows or [])
    ambiguous: list[int] = []
    for row_index in [*title_rows, *header_rows]:
        if row_index in explicit:
            continue
        if row_index < 1 or row_index > len(matrix):
            continue
        if merge_ranges and full_width_merge_row(row_index, width, merge_ranges):
            continue  # 全宽合并 = 硬结构证据（真实标题/真实分组）
        non_empty = [
            clean_cell(cell)
            for cell in matrix[row_index - 1]
            if clean_cell(cell)
        ]
        if len(non_empty) != 1:
            continue
        if obligation_signal(non_empty[0]) in {"modal", "pattern"}:
            continue  # 义务句保留 cell claim 路径（fixture 钉串，绝不回收）
        if width >= 2 or len(matrix) == 1:
            ambiguous.append(row_index)
    return sorted(ambiguous)


def analyze_table(
    matrix: list[list[str]],
    *,
    merge_ranges: Iterable[Iterable[int]] | None = None,
    explicit_header_rows: list[int] | None = None,
) -> dict[str, Any]:
    """确定性表格结构识别：标题/表头/数据区 + 检测状态与证据。"""
    # v4（P0-5 复审）：区分"已知无 merge"（[]，解析器确认无合并）与
    # "旧产物无证据"（None）——`normalized or None` 会把 [] 坍缩成 None，
    # 使已知无合并的单格数据行落入旧同值启发式被误判分组标题而静默消失
    normalized_merges = normalize_merge_ranges(merge_ranges)
    merge_evidence = None if merge_ranges is None else normalized_merges
    width = max((len(row) for row in matrix), default=0)
    title_rows, title_evidence = detect_title_rows(
        matrix, width=width, merge_ranges=merge_evidence
    )
    header_rows, status, header_evidence = detect_header_rows(
        matrix,
        width=width,
        title_row_indexes=title_rows,
        explicit_header_rows=explicit_header_rows,
        merge_ranges=merge_evidence,
    )
    ambiguous_structure_rows = _ambiguous_structure_rows(
        matrix,
        width=width,
        title_rows=title_rows,
        header_rows=header_rows,
        explicit_header_rows=explicit_header_rows,
        merge_ranges=merge_evidence,
    )
    if ambiguous_structure_rows and status == "inferred":
        # 单格"标题/表头"无任何结构证据——不静默关闭，如实 ambiguous 待审
        status = "ambiguous"
        header_evidence = [
            *header_evidence,
            "single_cell_structure:ambiguous:R"
            + ",".join(str(row_index) for row_index in ambiguous_structure_rows),
        ]
    title_set = set(title_rows)
    header_set = set(header_rows)
    data_row_indexes = [
        index + 1
        for index in range(len(matrix))
        if (index + 1) not in title_set and (index + 1) not in header_set
    ]
    return {
        "width": width,
        "height": len(matrix),
        "title_row_indexes": title_rows,
        "header_row_indexes": header_rows,
        "header_row_count": len(header_rows),
        "data_row_indexes": data_row_indexes,
        "header_detection_status": status,
        "header_detection_evidence": title_evidence + header_evidence,
        "ambiguous_structure_rows": ambiguous_structure_rows,
    }


# --- 表型分类 ---------------------------------------------------------------------

def is_parameter_table(
    headers: list[str],
    data_rows: list[list[str]],
    section_path: list[str] | None,
) -> bool:
    """需求型参数表判定（保守，宁漏勿错）。

    table-structure-v2 起删除 ≥3 数据行硬门：行数只是分类置信证据，行数不足的
    规范性内容改由 cell 层兜底，绝不静默丢失。判据：有表头；表头非术语/定义类；
    至少一列要求类表头；叶子章节不在术语/参考文献区。"""
    if not headers or not data_rows:
        return False
    if any(PARAM_DEF_CELL_RE.search(str(h or "")) for h in headers):
        return False
    if not any(PARAM_REQ_CELL_RE.search(str(h or "")) for h in headers):
        return False
    leaf = next(
        (str(s) for s in reversed([s for s in (section_path or []) if str(s).strip()])),
        "",
    )
    return not PARAM_SECTION_RE.search(leaf)


def is_mapping_matrix(headers: list[str], data_rows: list[list[str]]) -> bool:
    """映射/对照/矩阵表：行列各为维度、每格独立事实。与 parameter 互斥。

    marker（X/mandatory/required…）占比是硬证据——无 marker 的短值表（价格表/
    清单表）保持 other 按行，不炸开。"""
    if len(data_rows) < 2 or len(headers) < 2:
        return False
    if all(_SYNTHETIC_HEADER_RE.fullmatch(str(h or "").strip()) for h in headers):
        # 全部合成列名 = 无列维度证据（headerless/歧义表头），不判矩阵
        return False
    if any(PARAM_DEF_CELL_RE.search(str(h or "")) for h in headers):
        return False
    if any(PARAM_REQ_CELL_RE.search(str(h or "")) for h in headers):
        return False
    first_col = [clean_cell(row[0]) for row in data_rows if row and clean_cell(row[0])]
    if len(first_col) < 2 or _median_len(first_col) > _MATRIX_DIMENSION_MAX_LEN:
        return False
    if all(re.fullmatch(r"[\d.,/\-\s]+", value) for value in first_col):
        # 首列全是纯数字/日期 = 编号或测量值序列，不是对象维度——编号清单表的
        # X 不是"对象应支持该列"的二维事实
        return False
    body = [clean_cell(cell) for row in data_rows for cell in row[1:] if clean_cell(cell)]
    if not body:
        return False
    marker_ratio = sum(1 for cell in body if is_positive_marker(cell)) / len(body)
    if marker_ratio < _MATRIX_MARKER_MIN_RATIO:
        return False
    if not matrix_fact_columns(headers, data_rows):
        # B3：marker 只出现在无效列（合成列名/Note/Status/表头即 marker 词）=
        # 行列不构成二维能力维度——`Item | Status | Required` 类处置表不判矩阵，
        # 保持 other 按行，裸 X 绝不变成"对象应支持 Required"的伪义务
        return False
    return True


def is_prose_grid(headers: list[str], data_rows: list[list[str]]) -> bool:
    """散文网格：规范性长文分布在多列，行级合并会混淆独立义务 → 按格。"""
    cells: list[tuple[int, str]] = []
    for row in data_rows:
        for column_index, cell in enumerate(row):
            text = clean_cell(cell)
            if text:
                cells.append((column_index, text))
    if len(cells) < 2:
        return False
    normative_columns = {column for column, text in cells if is_normative_text(text)}
    if len(normative_columns) < 2:
        return False
    return _median_len([text for _column, text in cells]) > _PROSE_CELL_MIN_MEDIAN_LEN


def classify_table_kind(
    headers: list[str],
    data_rows: list[list[str]],
    section_path: list[str] | None,
) -> str:
    """mapping_matrix > prose_grid > parameter > other。

    prose_grid 先于 parameter：双列都承载规范性长文的表不是"每行一个对象的属性表"
    （同行多个独立义务必须分别闭环）；普通参数表的规范性内容集中在一列，不受影响。
    """
    if is_mapping_matrix(headers, data_rows):
        return "mapping_matrix"
    if is_prose_grid(headers, data_rows):
        return "prose_grid"
    if is_parameter_table(headers, data_rows, section_path):
        return "parameter"
    return "other"


def marker_majority_columns(headers: list[str], data_rows: list[list[str]]) -> set[int]:
    """marker 占多数的列（0-based，不含首列）——只看值分布，不审表头维度资格。"""
    columns: set[int] = set()
    width = len(headers)
    for column_index in range(1, width):
        values = [
            clean_cell(row[column_index])
            for row in data_rows
            if column_index < len(row) and clean_cell(row[column_index])
        ]
        if not values:
            continue
        markers = sum(1 for value in values if is_positive_marker(value))
        if markers and markers >= len(values) / 2:
            columns.add(column_index)
    return columns


def matrix_fact_columns(headers: list[str], data_rows: list[list[str]]) -> set[int]:
    """矩阵事实列（0-based 列号）：marker 为主且表头不是 Note 类叙述列。

    mandatory/required/X 只有位于矩阵事实列时才是 marker；普通 Note 列保持原文。
    v4 起（P0-4 复审）改为只消费共享的正向维度证据 `matrix_dimension_evidence`：
    "marker 多数减黑名单"会把任何不在黑名单里的词（"Supported"/"Approved"…）
    当成能力维度，确定性制造 "Encryption shall support Supported." 伪需求；
    正向证据要求表头自带维度形态（标识符/维度名/冒号规格），判不出维度资格的
    列一律不合成义务。"""
    return set(matrix_dimension_evidence(headers, data_rows))


# 正向维度证据：只有受控操作或“轴名 + 成员”结构可以驱动自然语言合成。
# 任意大写缩写/数字只能证明“像标识符”，不能证明它是能力轴；未知列保留原文并
# 进入结构审核，遵循宁漏勿错。
_CONTROLLED_MATRIX_OPERATION_RE = re.compile(
    r'^\s*["\']?(?:GET|SET|ACTION|READ|WRITE|NOTIFY|PUSH|PULL|CREATE|DELETE|EXECUTE)'
    r'["\']?\s*$',
    re.IGNORECASE,
)
_MATRIX_AXIS_MEMBER_RE = re.compile(
    r"^\s*(?:mode|attr(?:ibute)?|channel|profile|suite|level|role|class|interface|"
    r"protocol|version|key)\s*(?:[/#:._-]\s*)?(?:[A-Z]|\d+|[A-Za-z]+\d+)\s*$",
    re.IGNORECASE,
)
_QUALIFIED_MATRIX_OPERATION_RE = re.compile(
    r'^\s*(?:xDLMS\s+service|(?:xDLMS\s+)?service\s*[/#:._-]\s*["\']?'
    r'(?:GET|SET|ACTION|READ|WRITE)["\']?)\s*$',
    re.IGNORECASE,
)
_NUMERIC_HEADER_RE = re.compile(r"[\d.,/\-\s]+")


def matrix_dimension_tag(header: str) -> str | None:
    """单个表头的正向维度资格标签；无资格返回 None（先过既有黑名单，再要正向形态）。"""
    text = clean_cell(header)
    if not text:
        return None
    if _SYNTHETIC_HEADER_RE.fullmatch(text.strip()):
        return None  # 合成列名 = 无列维度证据
    if NOTE_HEADER_RE.search(text):
        return None
    if is_positive_marker(text) or _DISPOSITION_HEADER_RE.search(text):
        return None  # marker 词/处置词（Status/Result/检查…）不是能力维度
    if _NUMERIC_HEADER_RE.fullmatch(text):
        return None  # 纯数字/日期表头是刻度不是维度名
    if _CONTROLLED_MATRIX_OPERATION_RE.fullmatch(text):
        return "operation"
    if _MATRIX_AXIS_MEMBER_RE.fullmatch(text):
        return "axis_member"
    if _QUALIFIED_MATRIX_OPERATION_RE.fullmatch(text):
        return "qualified_operation"
    return None


def matrix_dimension_evidence(
    headers: list[str], data_rows: list[list[str]]
) -> dict[int, str]:
    """共享的正向矩阵维度证据：{0-based 列号: 证据标签}。

    唯一权威来源——表型分类（is_mapping_matrix）、leaf plan 事实列、A 轨
    marker 句式合成全部只消费本结果，禁止下游用别的口径重新推导事实列。
    只有"值分布上 marker 占多数"且"表头自带正向维度形态"的列才成立。"""
    evidence: dict[int, str] = {}
    for column_index in sorted(marker_majority_columns(headers, data_rows)):
        tag = matrix_dimension_tag(str(headers[column_index] or ""))
        if tag:
            evidence[column_index] = tag
    return evidence


def normative_sentence_count(text: str) -> int:
    """正文切句后规范性句的条数（多义务格判定与 cell claim 切句同口径）。

    逐字节重复的句子只计一次：DOCX 合并把两格文本拼进同一 tc（同句重复是
    拼接伪影不是两条义务），编辑性整句照抄同理——不同义务才计数。"""
    seen: set[str] = set()
    count = 0
    for start, end in sentence_spans(text):
        sentence = text[start:end]
        if not is_normative_text(sentence):
            continue
        key = " ".join(sentence.split())
        if key in seen:
            continue
        seen.add(key)
        count += 1
    return count


# --- 粒度规划 ---------------------------------------------------------------------

def plan_table_leaves(
    structure: dict[str, Any],
    matrix: list[list[str]],
    *,
    table_kind: str,
    merge_ranges: Iterable[Iterable[int]] | None = None,
    headers: list[str] | None = None,
    fact_columns: set[int] | None = None,
) -> dict[str, Any]:
    """唯一 leaf plan：同一物理内容只能有一个 owner。

    返回 {mode, row_leaves: [物理行号], cell_leaves: [(row, col)], context_cells: [(row, col)]}：
    - parameter / other → 每个数据行一个 row leaf（单格规范性行也必须保留）；
    - mapping_matrix / prose_grid → 每个有效事实格/规范性单元格一个 cell leaf；
    - 组合表（parameter + 真实矩阵事实列，如 DLMS 属性×服务矩阵）→ mixed：
      行 own 属性字段，事实列的 marker 格各自 own 一条 cell leaf；
    - 标题/表头中的规范性句生成 cell leaf；普通标题/表头只作 context；
    - 全宽合并分组标题（非规范性）作 context；规范性全宽行生成 cell leaf。
    """
    normalized_merges = normalize_merge_ranges(merge_ranges)
    # 同 analyze_table：[]（已知无合并）与 None（旧产物无证据）必须区分传递，
    # 否则已知无合并的单格数据行会被旧同值启发式误判成分组标题静默消失
    merge_evidence = None if merge_ranges is None else normalized_merges
    width = int(structure.get("width") or 0)
    title_rows = list(structure.get("title_row_indexes") or [])
    header_rows = list(structure.get("header_row_indexes") or [])
    data_rows = list(structure.get("data_row_indexes") or [])
    ambiguous_structure_rows = set(structure.get("ambiguous_structure_rows") or [])
    covered = covered_coordinates(normalized_merges)
    fact_columns = fact_columns or set()

    row_leaves: list[int] = []
    cell_leaves: list[tuple[int, int]] = []
    context_cells: list[tuple[int, int]] = []
    multi_duty_cells: list[tuple[int, int]] = []
    weak_signal_cells: list[tuple[int, int]] = []
    unsignaled_data_cells: list[tuple[int, int]] = []
    ambiguous_structure_cells: list[tuple[int, int]] = []
    untyped_colon_spec_cells: list[tuple[int, int]] = []

    def _context(row_index: int, column_index: int, text: str) -> None:
        """内容降级为 context 时登记弱信号证据（B5 第三维：content preservation）。

        弱信号（句形说明句）落入 context 单独计数——它最像义务却不是义务，
        静默 context 化正是"说明句消失/误登记"两类事故的共生面；计数进
        leaf plan，由账本审计把零计数从"看起来 ok"变成如实证据。"""
        context_cells.append((row_index, column_index))
        if obligation_signal(text) == "sentence_shape":
            weak_signal_cells.append((row_index, column_index))

    def structural_row(row_index: int, role: str) -> None:
        row = matrix[row_index - 1]
        for column_index in range(1, width + 1):
            if (row_index, column_index) in covered:
                continue
            text = clean_cell(row[column_index - 1]) if column_index - 1 < len(row) else ""
            if not text:
                continue
            if row_index in ambiguous_structure_rows:
                # P0-5：无结构证据的单格"标题/表头"——可定位的歧义资格候选：
                # 原文留在 context（可定位），逐格计数（审计不再是全零），
                # 结构状态 ambiguous → needs_review；绝不静默关闭为标题/表头。
                # 句形说明句同时计弱信号（B5 口径——两类计数回答的问题不同：
                # "说明句落 context" 与 "无结构证据单格行落 context" 同为真）
                ambiguous_structure_cells.append((row_index, column_index))
                if is_technical_spec_text(text):
                    # 技术规格在结构角色不确定时仍形成逐字 claim，同时保留结构待审；
                    # 元数据 colon_spec 不走此分支，只保留为可定位 context。
                    cell_leaves.append((row_index, column_index))
                else:
                    context_cells.append((row_index, column_index))
                    if is_untyped_colon_spec_text(text):
                        untyped_colon_spec_cells.append((row_index, column_index))
                if obligation_signal(text) == "sentence_shape":
                    weak_signal_cells.append((row_index, column_index))
            elif is_untyped_colon_spec_text(text):
                context_cells.append((row_index, column_index))
                untyped_colon_spec_cells.append((row_index, column_index))
            elif is_positive_marker(text):
                # marker 词（X/required/…）是矩阵记号不是义务——标题/表头位的
                # marker 格只作 context，永不单独成 claim（裸词 claim 事故）
                context_cells.append((row_index, column_index))
            elif row_bears_normative_sentence([text]) or is_technical_spec_text(text):
                # 标题/表头位只有句子型规范性内容（modal/句读句）才单独成 claim；
                # 冒号规格/短标签（"xDLMS Service: GET" 服务名表头）是维度名——
                # 内容已由矩阵事实/行 claim 承载，单列会再造裸标签伪需求
                cell_leaves.append((row_index, column_index))
            else:
                _context(row_index, column_index, text)

    for row_index in title_rows:
        structural_row(row_index, "title")
    for row_index in header_rows:
        structural_row(row_index, "header")

    cell_mode = table_kind in {"mapping_matrix", "prose_grid"}
    for row_index in data_rows:
        row = matrix[row_index - 1]
        padded = pad_row([clean_cell(cell) for cell in row], width)
        anchor_cells = [
            (row_index, column_index)
            for column_index in range(1, width + 1)
            if (row_index, column_index) not in covered and padded[column_index - 1]
        ]
        if not anchor_cells:
            continue
        if is_group_header_row(
            padded, row_index, width=width, merge_ranges=merge_evidence
        ):
            # 分组标题行：非规范性全宽合并 → context（规范性在上面已被判为非分组）
            context_cells.extend(anchor_cells)
            continue
        if not cell_mode:
            # 组合表：真实矩阵事实列（DLMS 属性×服务矩阵）的 marker 格按 cell 闭环，
            # 行仍 own 其余属性字段——同一物理内容只有一个 owner（marker 格不进 row 文本）
            fact_cells = [
                (row_index, column)
                for _r, column in anchor_cells
                if (column - 1) in fact_columns and is_positive_marker(padded[column - 1])
            ]
            non_fact = [
                (row_index, column)
                for _r, column in anchor_cells
                if (row_index, column) not in set(fact_cells)
            ]
            untyped_colon_cells = [
                (row_index, column)
                for _r, column in non_fact
                if is_untyped_colon_spec_text(padded[column - 1])
            ]
            if untyped_colon_cells:
                untyped_colon_spec_cells.extend(untyped_colon_cells)
                context_cells.extend(untyped_colon_cells)
                non_fact = [
                    (row_index, column)
                    for _r, column in non_fact
                    if (row_index, column) not in set(untyped_colon_cells)
                ]
            if fact_cells:
                cell_leaves.extend(fact_cells)
            # 多义务格：同格按句切出 ≥2 条独立规范性句 → 该格按句出 cell claim
            # （owner=cell），行仍 own 其余字段——两条义务不再骑墙在一个 row claim 里
            multi_duty = [
                (row_index, column)
                for _r, column in non_fact
                if normative_sentence_count(padded[column - 1]) >= 2
            ]
            if multi_duty:
                cell_leaves.extend(multi_duty)
                multi_duty_cells.extend(multi_duty)
                non_fact = [
                    (row_index, column)
                    for _r, column in non_fact
                    if (row_index, column) not in set(multi_duty)
                ]
            if table_kind == "parameter":
                # 参数表每行皆需求（用户裁定 2026-07-27）：两个以上实质格即成行资格
                row_eligible = len(non_fact) >= 2 or any(
                    is_normative_text(padded[column - 1]) for _row, column in non_fact
                )
            else:
                # P1-1 复审：other 表资格不得由单元格数量决定（len(non_fact)>=2 会把
                # 普通说明行登记成正式 claim）——只有强义务信号（modal/pattern/
                # colon_spec）授权成行；说明句/无信号格进 context、计数并待审
                row_eligible = any(
                    is_normative_text(padded[column - 1]) for _row, column in non_fact
                )
            if row_eligible:
                # 单格行只要包含规范性内容就必须保留（不受"至少两个非空格"限制）
                row_leaves.append(row_index)
            else:
                claim_columns = {
                    column for _r, column in cell_leaves if _r == row_index
                }
                metadata_row = any(
                    is_metadata_spec_text(padded[column - 1])
                    for _r, column in non_fact
                )
                for _r, column in non_fact:
                    text = padded[column - 1]
                    _context(row_index, column, text)
                    if metadata_row:
                        # 文档/流程元数据是确定性 context，不制造 claim，也不占用
                        # 结构审核队列。整行保留在原始表格与 cell artifact 中。
                        continue
                    if obligation_signal(text) != "none":
                        continue
                    # 被同行 cell claim 消费为身份上下文的前置标识格不算"消失"
                    # （"Logger" 进 claim 的 row_header_context）；只有既无信号又
                    # 未进任何 claim 面的数据格才计 unsignaled → needs_review
                    consumed_as_identity = (
                        not is_positive_marker(text)
                        and len(text) <= _IDENTITY_CONTEXT_MAX_LEN
                        and any(column < leaf_col for leaf_col in claim_columns)
                    )
                    if not consumed_as_identity:
                        unsignaled_data_cells.append((row_index, column))
            continue
        # cell 模式：行头列（首列短标签）与 Note 叙述列只作 context（保持原文），
        # 其余非空 anchor 格各自成 leaf
        for _row, column in anchor_cells:
            text = padded[column - 1]
            header_text = ""
            if headers and column - 1 < len(headers):
                header_text = str(headers[column - 1] or "")
            if is_untyped_colon_spec_text(text):
                context_cells.append((row_index, column))
                untyped_colon_spec_cells.append((row_index, column))
            elif column == 1 and table_kind == "mapping_matrix":
                context_cells.append((row_index, column))
            elif (
                column == 1
                and table_kind == "prose_grid"
                and not is_normative_text(text)
            ):
                context_cells.append((row_index, column))
            elif table_kind == "mapping_matrix" and NOTE_HEADER_RE.search(header_text):
                context_cells.append((row_index, column))
            elif (
                table_kind == "mapping_matrix"
                and is_positive_marker(text)
                and (column - 1) not in fact_columns
            ):
                # B3：marker 只在有效事实列承载"对象×维度"事实；Status/Result 等
                # 处置列的 X 是检查结果原文——保持 context，绝不合成义务句式
                context_cells.append((row_index, column))
            elif obligation_signal(text) == "sentence_shape":
                # 弱信号说明句绝不单独成 claim（B5：说明句被登记为正式 claim 的反例）
                _context(row_index, column, text)
            else:
                cell_leaves.append((row_index, column))

    if row_leaves and cell_leaves:
        mode = "mixed"
    elif cell_leaves:
        mode = "cell"
    else:
        mode = "row"
    return {
        "mode": mode,
        "row_leaves": row_leaves,
        "cell_leaves": cell_leaves,
        "context_cells": context_cells,
        "multi_duty_cells": multi_duty_cells,
        "weak_signal_cells": weak_signal_cells,
        "unsignaled_data_cells": unsignaled_data_cells,
        "ambiguous_structure_cells": ambiguous_structure_cells,
        "untyped_colon_spec_cells": untyped_colon_spec_cells,
    }


# --- canonical cell items ----------------------------------------------------------

def structural_role_for(
    row_index: int,
    column_index: int,
    *,
    structure: dict[str, Any],
    table_kind: str,
    group_header_rows: set[int],
) -> str:
    if row_index in set(structure.get("title_row_indexes") or []):
        return "title"
    if row_index in set(structure.get("header_row_indexes") or []):
        return "header"
    if row_index in group_header_rows:
        return "group_header"
    if table_kind in {"mapping_matrix", "prose_grid"} and column_index == 1:
        return "row_header"
    return "data"


def build_cell_items(
    matrix: list[list[str]],
    raw_matrix: list[list[str]] | None,
    structure: dict[str, Any],
    plan: dict[str, Any],
    *,
    table_id: str,
    block_id: str,
    table_title: str,
    section_path: list[str],
    headers: list[str],
    table_kind: str,
    source_format: str,
    merge_ranges: Iterable[Iterable[int]] | None = None,
    sheet_name: str | None = None,
    a1_origin: tuple[int, int] | None = None,
    page_number: int | None = None,
    cell_bboxes: dict[tuple[int, int], Any] | None = None,
    geometry_kind: str | None = None,
    fact_columns: set[int] | None = None,
) -> list[dict[str, Any]]:
    """每个非空物理单元格/合并区域一个 canonical cell（schema table-cell-item/v1）。"""
    normalized_merges = normalize_merge_ranges(merge_ranges)
    covered = covered_coordinates(normalized_merges)
    width = int(structure.get("width") or 0)
    data_rows = list(structure.get("data_row_indexes") or [])
    data_position = {row_index: offset for offset, row_index in enumerate(data_rows, start=1)}
    cell_leaf_set = {tuple(coord) for coord in plan.get("cell_leaves") or []}
    context_set = {tuple(coord) for coord in plan.get("context_cells") or []}
    row_leaf_set = set(plan.get("row_leaves") or [])
    group_header_rows = {
        row_index
        for row_index in data_rows
        if is_group_header_row(
            pad_row([clean_cell(c) for c in matrix[row_index - 1]], width),
            row_index,
            width=width,
            # 同 analyze/plan：[]（已知无合并）不得坍缩成 None（旧产物无证据），
            # 否则已知无合并的单格行被旧同值启发式误判分组标题（P0-5）
            merge_ranges=None if merge_ranges is None else normalized_merges,
        )
    }

    cells: list[dict[str, Any]] = []
    for row_index in range(1, len(matrix) + 1):
        row = matrix[row_index - 1]
        raw_row = (raw_matrix or matrix)[row_index - 1] if row_index - 1 < len(raw_matrix or matrix) else row
        for column_index in range(1, width + 1):
            if (row_index, column_index) in covered:
                continue  # 合并覆盖坐标不冒充单元格
            text = clean_cell(row[column_index - 1]) if column_index - 1 < len(row) else ""
            if not text:
                continue
            raw_text = str(raw_row[column_index - 1] or "") if column_index - 1 < len(raw_row) else text
            anchor = merge_anchor_for(row_index, column_index, normalized_merges)
            row_span = (anchor[2] - anchor[0] + 1) if anchor else 1
            column_span = (anchor[3] - anchor[1] + 1) if anchor else 1
            anchor_covered = [
                [r, c]
                for r in range(anchor[0], anchor[2] + 1)
                for c in range(anchor[1], anchor[3] + 1)
                if (r, c) != (row_index, column_index)
            ] if anchor else []
            role = structural_role_for(
                row_index, column_index,
                structure=structure, table_kind=table_kind,
                group_header_rows=group_header_rows,
            )
            header_path = [headers[column_index - 1]] if column_index - 1 < len(headers) else [
                f"column_{column_index}"
            ]
            identity_entries = _row_identity_entries(
                matrix, row_index, column_index,
                structure=structure, table_kind=table_kind,
                group_header_rows=group_header_rows, width=width,
                merge_ranges=normalized_merges,
                headers=headers,
            )
            row_header_context = [
                render_identity_entry(header, value)
                for header, value in identity_entries
            ]
            if (row_index, column_index) in cell_leaf_set:
                leaf_kind = "cell"
            elif (row_index, column_index) in context_set:
                leaf_kind = "context"
            elif row_index in row_leaf_set:
                leaf_kind = "row"
            else:
                leaf_kind = "context"
            cell: dict[str, Any] = {
                "schema": TABLE_CELL_ITEM_SCHEMA,
                "cell_id": f"{table_id}-R{row_index:06d}-C{column_index:06d}",
                "table_id": table_id,
                "table_block_id": block_id,
                "table_title": table_title,
                "section_path": list(section_path),
                "row_index": row_index,
                "column_index": column_index,
                "data_row_index": data_position.get(row_index),
                "row_span": row_span,
                "column_span": column_span,
                "covered_coordinates": anchor_covered,
                "structural_role": role,
                "text": text,
                "raw_text": raw_text,
                "header_path": header_path,
                "row_header_context": row_header_context,
                "row_header_entries": [
                    {"header": header, "value": value}
                    for header, value in identity_entries
                ],
                "source_format": source_format,
                "requirement_like": is_normative_text(text),
                "leaf_kind": leaf_kind,
                "table_structure_version": TABLE_STRUCTURE_VERSION,
            }
            if sheet_name is not None:
                cell["sheet_name"] = sheet_name
            if a1_origin is not None:
                cell["a1_address"] = a1_address(
                    a1_origin[0] + row_index - 1, a1_origin[1] + column_index - 1
                )
            if page_number is not None:
                cell["page_number"] = page_number
            bbox = (cell_bboxes or {}).get((row_index, column_index))
            if bbox is not None:
                cell["bbox"] = bbox
                cell["geometry_kind"] = geometry_kind or "pdfplumber_cell"
            elif geometry_kind is not None:
                cell["geometry_kind"] = geometry_kind
            cells.append(cell)
    return cells


def _row_identity_entries(
    matrix: list[list[str]],
    row_index: int,
    column_index: int,
    *,
    structure: dict[str, Any],
    table_kind: str,
    group_header_rows: set[int],
    width: int,
    merge_ranges: list[tuple[int, int, int, int]],
    headers: list[str] | None = None,
) -> list[tuple[str, str]]:
    """行标识条目 [(header, value)]：上方最近分组标题 + 同行全部前置标识格（B1）。

    前置标识格 = 列号小于本格、角色为 row_header 或文本为短标签（≤120 字符）
    的非空格；合并覆盖坐标回溯 anchor 继承文本（继承不复制：cell 仍只存
    anchor，继承只用于上下文与判定）。marker 格与强义务信号前置格是兄弟义务/
    矩阵记号而非身份标识，一律不进上下文。返回结构化条目而非拼接串——消费方
    （claim 上下文渲染 / A 轨 subject 提取）各取所需，不反解析显示文本。
    """
    entries: list[tuple[str, str]] = []
    row = matrix[row_index - 1]
    # 上方最近分组标题行（全宽合并 anchor）
    for candidate in sorted(group_header_rows, reverse=True):
        if candidate >= row_index:
            continue
        candidate_row = pad_row([clean_cell(c) for c in matrix[candidate - 1]], width)
        text = next((value for value in candidate_row if value), "")
        if text:
            entries.append(("", text))
        break
    for column in range(1, column_index):
        value = clean_cell(row[column - 1]) if column - 1 < len(row) else ""
        if not value and merge_ranges:
            # 合并覆盖坐标前置格为空——回溯 merge anchor 继承对象值
            anchor = merge_anchor_for(row_index, column, merge_ranges)
            if anchor is not None and (anchor[0], anchor[1]) != (row_index, column):
                anchor_row = matrix[anchor[0] - 1] if anchor[0] - 1 < len(matrix) else []
                if anchor[1] - 1 < len(anchor_row):
                    value = clean_cell(anchor_row[anchor[1] - 1])
        if not value or is_positive_marker(value):
            continue  # marker 是矩阵记号，不是身份标识
        role = structural_role_for(
            row_index, column,
            structure=structure, table_kind=table_kind,
            group_header_rows=group_header_rows,
        )
        if role != "row_header":
            if len(value) > _IDENTITY_CONTEXT_MAX_LEN:
                continue  # 长文前置格 = 兄弟义务，不是身份标识
            if obligation_signal(value) in _STRONG_OBLIGATION_SIGNALS:
                continue  # 强信号前置格是兄弟义务句（长度以内也一样），不冒充身份
        header = ""
        if headers and column - 1 < len(headers):
            candidate_header = str(headers[column - 1] or "").strip()
            if candidate_header and not _SYNTHETIC_HEADER_RE.fullmatch(candidate_header):
                header = candidate_header
        if (header, value) not in entries:
            entries.append((header, value))
    return entries


def render_identity_entry(header: str, value: str) -> str:
    """标识条目的 claim 上下文形态：Header=Value（无列头时只存 Value）。"""
    return f"{header}={value}" if header else value


def cell_context_text(cell: dict[str, Any]) -> str:
    """cell 输入的强制上下文形态：表标题 + 行头 + 列头 + 单元格正文（禁止裸格）。"""
    parts = [str(cell.get("table_title") or "").strip()]
    parts.extend(str(value) for value in (cell.get("row_header_context") or []) if str(value).strip())
    parts.extend(str(value) for value in (cell.get("header_path") or []) if str(value).strip())
    prefix = " | ".join(part for part in parts if part)
    body = str(cell.get("text") or "").strip()
    return f"{prefix} = {body}" if prefix else body
