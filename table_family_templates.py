"""Table-family few-shot template library (WS1, plan §3.2.2 / §3.1.1).

Pure data layer for the dual-track table parser. ``llm_table_understanding`` (the
proposer) consumes matched templates to assemble structured few-shot context, and
the templates are available for the geometry validator to tune decision parameters
(protected-code columns, header-level expectations). Templates are DATA, not prompt
text — every field is a structured prior (header-level range, protected-code column
kinds, semantic-merge priors), never free prose that could smuggle a hallucination.

Three families are declared in ``domain_packs/dlms_cosem/table_family_templates.yaml``
to mirror the existing dlms_cosem table-pattern registry, organized by table FAMILY
(shape + protected-code locus) rather than by individual ``pattern_id`` (the per-
pattern match rules stay owned by ``table_pattern_engine.py``).

Scope: this module performs no LLM calls and no file writes. It loads YAML via the
same ``yaml.safe_load`` convention used by ``domain_pack`` / ``llm_pipeline`` and
locates the default template file relative to the package root (the same convention
as ``DEFAULT_DOMAIN_PACK_PATH``). Matching is deterministic header-indicator matching
only — it never assigns cell roles (that is the proposer's job, signed by the
validator).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from resources import package_root

TABLE_FAMILY_TEMPLATES_VERSION = "table-family-templates-v1"
TABLE_FAMILY_TEMPLATES_SCHEMA = "table-family-templates/v1"
DEFAULT_FAMILY_TEMPLATES_PATH = (
    package_root() / "domain_packs" / "dlms_cosem" / "table_family_templates.yaml"
)

# Protected-code column kinds recognised across all families. These are the
# encodings the geometry validator compares verbatim (reusing extract-stage guards);
# a family declares which kinds apply to it.
PROTECTED_CODE_KINDS = ("obis", "class_id", "event_code", "group_code", "hex")


@dataclass(frozen=True)
class HeaderLevelRange:
    min: int
    max: int

    def contains(self, value: int) -> bool:
        return self.min <= value <= self.max


@dataclass(frozen=True)
class ProtectedCodeColumn:
    column_kind: str
    header_indicators: tuple[str, ...] = ()
    encoding_format: str = ""
    verbatim: bool = True

    def matches_header(self, header: str) -> bool:
        token = str(header or "").strip().lower()
        if not token:
            return False
        return any(str(indicator or "").strip().lower() == token for indicator in self.header_indicators)


@dataclass(frozen=True)
class SemanticMergePrior:
    prior_id: str
    description: str = ""


@dataclass(frozen=True)
class DetectionHints:
    header_indicators: tuple[str, ...] = ()
    exclude_header_indicators: tuple[str, ...] = ()
    required_headers_any: tuple[tuple[str, ...], ...] = ()

    def header_score(self, headers: list[str]) -> int:
        """Count deterministic header-indicator hits (case-insensitive substring).

        Used only to pick the best-matching family for few-shot context; the score is
        advisory and never signs a structure decision.
        """
        normalized = [str(h or "").lower() for h in headers]
        score = 0
        for indicator in self.header_indicators:
            token = str(indicator or "").strip().lower()
            if token and any(token in header for header in normalized):
                score += 1
        for indicator in self.exclude_header_indicators:
            token = str(indicator or "").strip().lower()
            if token and any(token in header for header in normalized):
                score -= 1
        for required_set in self.required_headers_any:
            required_tokens = [str(h or "").strip().lower() for h in required_set]
            if required_tokens and all(
                any(token == header or token in header for header in normalized)
                for token in required_tokens
            ):
                score += len(required_tokens)
        return score


@dataclass(frozen=True)
class TableFamilyTemplate:
    family_id: str
    description: str = ""
    header_level_range: HeaderLevelRange = field(default_factory=lambda: HeaderLevelRange(1, 1))
    protected_code_columns: tuple[ProtectedCodeColumn, ...] = ()
    semantic_merge_priors: tuple[SemanticMergePrior, ...] = ()
    detection_hints: DetectionHints = field(default_factory=DetectionHints)

    @property
    def protected_code_kinds(self) -> tuple[str, ...]:
        kinds: list[str] = []
        for column in self.protected_code_columns:
            if column.column_kind and column.column_kind not in kinds:
                kinds.append(column.column_kind)
        return tuple(kinds)

    def has_protected_column(self, headers: list[str]) -> bool:
        return any(
            column.matches_header(header)
            for column in self.protected_code_columns
            for header in headers
        )


@dataclass(frozen=True)
class TableFamilyLibrary:
    version: str
    schema: str
    domain_pack_id: str
    families: tuple[TableFamilyTemplate, ...]

    def by_id(self, family_id: str) -> TableFamilyTemplate | None:
        target = str(family_id or "").strip()
        for family in self.families:
            if family.family_id == target:
                return family
        return None


def _header_level_range(payload: Any) -> HeaderLevelRange:
    if not isinstance(payload, dict):
        return HeaderLevelRange(1, 1)
    lo = int(payload.get("min", 1))
    hi = int(payload.get("max", lo))
    if hi < lo:
        lo, hi = hi, lo
    if lo < 0:
        lo = 0
    if hi < 0:
        hi = 0
    return HeaderLevelRange(lo, hi)


def _protected_columns(payload: Any) -> tuple[ProtectedCodeColumn, ...]:
    columns: list[ProtectedCodeColumn] = []
    for entry in payload or []:
        if not isinstance(entry, dict):
            continue
        columns.append(
            ProtectedCodeColumn(
                column_kind=str(entry.get("column_kind") or "").strip(),
                header_indicators=tuple(str(h) for h in (entry.get("header_indicators") or [])),
                encoding_format=str(entry.get("encoding_format") or ""),
                verbatim=bool(entry.get("verbatim", True)),
            )
        )
    return tuple(columns)


def _merge_priors(payload: Any) -> tuple[SemanticMergePrior, ...]:
    priors: list[SemanticMergePrior] = []
    for entry in payload or []:
        if not isinstance(entry, dict):
            continue
        priors.append(
            SemanticMergePrior(
                prior_id=str(entry.get("prior_id") or "").strip(),
                description=str(entry.get("description") or "").strip(),
            )
        )
    return tuple(priors)


def _detection_hints(payload: Any) -> DetectionHints:
    if not isinstance(payload, dict):
        return DetectionHints()
    required_any: list[tuple[str, ...]] = []
    for group in payload.get("required_headers_any") or []:
        if isinstance(group, list):
            required_any.append(tuple(str(h) for h in group))
    return DetectionHints(
        header_indicators=tuple(str(h) for h in (payload.get("header_indicators") or [])),
        exclude_header_indicators=tuple(
            str(h) for h in (payload.get("exclude_header_indicators") or [])
        ),
        required_headers_any=tuple(required_any),
    )


def _family_from_payload(payload: dict[str, Any]) -> TableFamilyTemplate:
    return TableFamilyTemplate(
        family_id=str(payload.get("family_id") or "").strip(),
        description=str(payload.get("description") or "").strip(),
        header_level_range=_header_level_range(payload.get("header_level_range")),
        protected_code_columns=_protected_columns(payload.get("protected_code_columns")),
        semantic_merge_priors=_merge_priors(payload.get("semantic_merge_priors")),
        detection_hints=_detection_hints(payload.get("detection_hints")),
    )


def load_table_family_templates(path: Path | None = None) -> TableFamilyLibrary:
    """Load the table-family template library from YAML.

    Defaults to ``DEFAULT_FAMILY_TEMPLATES_PATH``. An absent default file yields an
    empty library (the proposer treats empty as "no few-shot context" — never an
    error that blocks the pipeline). An explicitly-passed path that is missing raises
    FileNotFoundError (the caller asked for a specific file).
    """
    resolved = Path(path or DEFAULT_FAMILY_TEMPLATES_PATH).expanduser().resolve()
    explicit = path is not None
    if not resolved.is_file():
        if explicit:
            raise FileNotFoundError(f"table family templates not found: {resolved}")
        return TableFamilyLibrary(
            version=TABLE_FAMILY_TEMPLATES_VERSION,
            schema=TABLE_FAMILY_TEMPLATES_SCHEMA,
            domain_pack_id="",
            families=(),
        )
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    families = tuple(
        _family_from_payload(entry)
        for entry in (payload.get("families") or [])
        if isinstance(entry, dict) and str(entry.get("family_id") or "").strip()
    )
    return TableFamilyLibrary(
        version=str(payload.get("schema_version") or TABLE_FAMILY_TEMPLATES_VERSION),
        schema=TABLE_FAMILY_TEMPLATES_SCHEMA,
        domain_pack_id=str(payload.get("domain_pack_id") or ""),
        families=families,
    )


def match_table_family(
    headers: list[str],
    library: TableFamilyLibrary | None = None,
) -> TableFamilyTemplate | None:
    """Pick the best-matching family for a table by deterministic header score.

    Returns ``None`` when no family scores above zero (no indicator matched) — the
    caller then runs the proposer with no family-specific few-shot context. Ties are
    broken by declaration order (stable). This is advisory context selection only;
    it never assigns cell roles and never signs a structure decision.
    """
    lib = library if library is not None else load_table_family_templates()
    if not lib.families:
        return None
    best: TableFamilyTemplate | None = None
    best_score = 0
    for family in lib.families:
        score = family.detection_hints.header_score(headers)
        if score > best_score:
            best_score = score
            best = family
    return best


__all__ = [
    "TABLE_FAMILY_TEMPLATES_VERSION",
    "TABLE_FAMILY_TEMPLATES_SCHEMA",
    "DEFAULT_FAMILY_TEMPLATES_PATH",
    "PROTECTED_CODE_KINDS",
    "HeaderLevelRange",
    "ProtectedCodeColumn",
    "SemanticMergePrior",
    "DetectionHints",
    "TableFamilyTemplate",
    "TableFamilyLibrary",
    "load_table_family_templates",
    "match_table_family",
]
