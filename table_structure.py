"""表格结构与单元格级需求闭环底座（table-structure-v2）。

集中管理此前散落在 atomize.py / ai_extract.py / spot_extract.py / extract_units.py 的
表格角色识别（标题/表头/行头/数据/分组标题）与粒度规划（row/cell/mixed leaf plan）。

红线：
- 纯确定性。LLM 绝不参与标题、表头、合并关系或源坐标的判定。
- 一个非空物理单元格（或合并区域）只生成一个 canonical cell；合并格仅存左上角
  anchor，其余坐标进 covered_coordinates，禁止复制文本冒充多个单元格。
- 行数只是分类置信证据，任何规范性内容不得因行数/单元格计数硬门而静默丢失。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

TABLE_STRUCTURE_VERSION = "table-structure-v2"
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

_POSITIVE_MARKERS = {"x", "yes", "true", "required", "mandatory", "applicable"}
_MATRIX_DIMENSION_MAX_LEN = 24
_MATRIX_MARKER_MIN_RATIO = 0.30
_PROSE_CELL_MIN_MEDIAN_LEN = 40

_NORMATIVE_RE = re.compile(
    r"\bshall\b|\bmust\b|\bshould\b|\brequired\b|\bmandatory\b|\bshall\s+not\b|\bmust\s+not\b"
    r"|应当|必须|不得|应满足|应支持|须符合",
    re.IGNORECASE,
)


def is_normative_text(text: str) -> bool:
    """结构层规范性判定（保守子集： modal 动词/中文义务词）。

    atomize.is_requirement_like 是更宽的领域判定；结构层只需要"这句话是否是义务"，
    用于决定标题/表头/单元格是否必须生成 claim（规范性内容绝不静默丢失）。"""
    return bool(_NORMATIVE_RE.search(str(text or "")))


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
    if merge_ranges is None:
        # 旧产物无合并证据：保留历史同值判定（guards-v16 口径），但规范性文本不判分组
        return not is_normative_text(non_empty[0])
    if full_width_merge_row(row_index, width, merge_ranges) is None:
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

    非规范性标题只作 context；规范性标题仍是标题行，但生成 cell claim。
    无合并证据时仅允许一条保守推断：首行恰好一个非空格、非规范性、且次行多格——
    记 inferred 证据；规范性单格首行永不判标题（留在数据区生成 claim）。"""
    title_rows: list[int] = []
    evidence: list[str] = []
    if merge_ranges:
        for offset, row in enumerate(matrix):
            row_index = offset + 1
            non_empty = [clean_cell(cell) for cell in row if clean_cell(cell)]
            if not non_empty:
                break
            if full_width_merge_row(row_index, width, merge_ranges) is not None and len(set(non_empty)) == 1:
                title_rows.append(row_index)
                evidence.append(f"full_width_merge:R{row_index}")
                continue
            break
    if not title_rows and len(matrix) >= 2:
        first_non_empty = [clean_cell(cell) for cell in matrix[0] if clean_cell(cell)]
        second_non_empty = [clean_cell(cell) for cell in matrix[1] if clean_cell(cell)]
        if (
            len(first_non_empty) == 1
            and not is_normative_text(first_non_empty[0])
            and len(second_non_empty) >= 2
            and width >= 2
        ):
            title_rows.append(1)
            evidence.append("single_cell_inferred:R1")
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

    if explicit_header_rows:
        explicit = sorted(r for r in explicit_header_rows if r not in title_set and r <= len(matrix))
        if explicit:
            return explicit, "explicit", [f"explicit_header_rows:{','.join(str(r) for r in explicit)}"]

    first_index, first_row = body[0]
    second_row = body[1][1] if len(body) > 1 else None
    first_normative = row_is_normative(first_row)
    second_normative = row_is_normative(second_row) if second_row is not None else False

    if first_normative and second_normative:
        # headerless：首两行都呈需求句 → 无表头，column_1... 生效，首行进数据区
        return [], "inferred", ["first_two_rows_normative:headerless"]

    header_rows = [first_index]
    evidence = ["first_row_header:default"]
    status = "inferred"
    if first_normative:
        # 首行呈规范性却被判为表头——结构与内容角色冲突，进审核（内容仍完整保留）
        status = "ambiguous"
        evidence.append("first_row_normative:ambiguous")

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


def analyze_table(
    matrix: list[list[str]],
    *,
    merge_ranges: Iterable[Iterable[int]] | None = None,
    explicit_header_rows: list[int] | None = None,
) -> dict[str, Any]:
    """确定性表格结构识别：标题/表头/数据区 + 检测状态与证据。"""
    normalized_merges = normalize_merge_ranges(merge_ranges)
    width = max((len(row) for row in matrix), default=0)
    title_rows, title_evidence = detect_title_rows(
        matrix, width=width, merge_ranges=normalized_merges or None
    )
    header_rows, status, header_evidence = detect_header_rows(
        matrix,
        width=width,
        title_row_indexes=title_rows,
        explicit_header_rows=explicit_header_rows,
        merge_ranges=normalized_merges or None,
    )
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
    if any(PARAM_DEF_CELL_RE.search(str(h or "")) for h in headers):
        return False
    if any(PARAM_REQ_CELL_RE.search(str(h or "")) for h in headers):
        return False
    first_col = [clean_cell(row[0]) for row in data_rows if row and clean_cell(row[0])]
    if len(first_col) < 2 or _median_len(first_col) > _MATRIX_DIMENSION_MAX_LEN:
        return False
    body = [clean_cell(cell) for row in data_rows for cell in row[1:] if clean_cell(cell)]
    if not body:
        return False
    marker_ratio = sum(1 for cell in body if is_positive_marker(cell)) / len(body)
    return marker_ratio >= _MATRIX_MARKER_MIN_RATIO


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


def matrix_fact_columns(headers: list[str], data_rows: list[list[str]]) -> set[int]:
    """矩阵事实列（0-based 列号）：marker 为主且表头不是 Note 类叙述列。

    mandatory/required/X 只有位于矩阵事实列时才是 marker；普通 Note 列保持原文。"""
    fact_columns: set[int] = set()
    width = len(headers)
    for column_index in range(1, width):
        header = str(headers[column_index] or "")
        if NOTE_HEADER_RE.search(header):
            continue
        values = [
            clean_cell(row[column_index])
            for row in data_rows
            if column_index < len(row) and clean_cell(row[column_index])
        ]
        if not values:
            continue
        markers = sum(1 for value in values if is_positive_marker(value))
        if markers and markers >= len(values) / 2:
            fact_columns.add(column_index)
    return fact_columns


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
    width = int(structure.get("width") or 0)
    title_rows = list(structure.get("title_row_indexes") or [])
    header_rows = list(structure.get("header_row_indexes") or [])
    data_rows = list(structure.get("data_row_indexes") or [])
    covered = covered_coordinates(normalized_merges)
    fact_columns = fact_columns or set()

    row_leaves: list[int] = []
    cell_leaves: list[tuple[int, int]] = []
    context_cells: list[tuple[int, int]] = []

    def structural_row(row_index: int, role: str) -> None:
        row = matrix[row_index - 1]
        for column_index in range(1, width + 1):
            if (row_index, column_index) in covered:
                continue
            text = clean_cell(row[column_index - 1]) if column_index - 1 < len(row) else ""
            if not text:
                continue
            if is_normative_text(text):
                cell_leaves.append((row_index, column_index))
            else:
                context_cells.append((row_index, column_index))

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
            padded, row_index, width=width, merge_ranges=normalized_merges or None
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
            if fact_cells:
                cell_leaves.extend(fact_cells)
            if len(non_fact) >= 2 or any(
                is_normative_text(padded[column - 1]) for _row, column in non_fact
            ):
                # 单格行只要包含规范性内容就必须保留（不受"至少两个非空格"限制）
                row_leaves.append(row_index)
            else:
                context_cells.extend(non_fact)
            continue
        # cell 模式：行头列（首列短标签）与 Note 叙述列只作 context（保持原文），
        # 其余非空 anchor 格各自成 leaf
        for _row, column in anchor_cells:
            header_text = ""
            if headers and column - 1 < len(headers):
                header_text = str(headers[column - 1] or "")
            if column == 1 and table_kind == "mapping_matrix":
                context_cells.append((row_index, column))
            elif (
                column == 1
                and table_kind == "prose_grid"
                and not is_normative_text(padded[column - 1])
            ):
                context_cells.append((row_index, column))
            elif table_kind == "mapping_matrix" and NOTE_HEADER_RE.search(header_text):
                context_cells.append((row_index, column))
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
            merge_ranges=normalized_merges or None,
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
            row_header_context = _row_header_context(
                matrix, row_index, column_index,
                structure=structure, table_kind=table_kind,
                group_header_rows=group_header_rows, width=width,
                merge_ranges=normalized_merges,
                include_first_column=(
                    table_kind in {"mapping_matrix", "prose_grid"}
                    or (fact_columns is not None and (column_index - 1) in fact_columns)
                ),
            )
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


def _row_header_context(
    matrix: list[list[str]],
    row_index: int,
    column_index: int,
    *,
    structure: dict[str, Any],
    table_kind: str,
    group_header_rows: set[int],
    width: int,
    merge_ranges: list[tuple[int, int, int, int]],
    include_first_column: bool = False,
) -> list[str]:
    """行头上下文：同行行头格 + 上方最近分组标题（不复制文本冒充，只引用真实 anchor）。"""
    context: list[str] = []
    row = matrix[row_index - 1]
    # 上方最近分组标题行（全宽合并 anchor）
    for candidate in sorted(group_header_rows, reverse=True):
        if candidate >= row_index:
            continue
        candidate_row = pad_row([clean_cell(c) for c in matrix[candidate - 1]], width)
        text = next((value for value in candidate_row if value), "")
        if text:
            context.append(text)
        break
    if include_first_column and column_index > 1 and row:
        first = clean_cell(row[0])
        if first and first not in context:
            context.append(first)
    return context


def cell_context_text(cell: dict[str, Any]) -> str:
    """cell 输入的强制上下文形态：表标题 + 行头 + 列头 + 单元格正文（禁止裸格）。"""
    parts = [str(cell.get("table_title") or "").strip()]
    parts.extend(str(value) for value in (cell.get("row_header_context") or []) if str(value).strip())
    parts.extend(str(value) for value in (cell.get("header_path") or []) if str(value).strip())
    prefix = " | ".join(part for part in parts if part)
    body = str(cell.get("text") or "").strip()
    return f"{prefix} = {body}" if prefix else body
