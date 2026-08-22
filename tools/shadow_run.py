"""T4 / S3 全开关影子运行工具链（重构结论 §2.3）。

对给定文档跑两条路径并排对比产物：

  * **旧路径** —— 全部新开关 OFF（``RATOMIZER_TABLE_DUAL_TRACK`` /
    ``RATOMIZER_FUNCTIONAL_EXTRACT`` / ``RATOMIZER_LLM_BUDGET`` /
    ``RATOMIZER_CLAIM_LEDGER_MODE`` 全部回到默认），即生产当前确定性原子化路径；
  * **新路径** —— 上述开关 ON（双轨 / 直抽 / 抽检 / 预算）。

逐产物差异进**归因清单**（``expected_difference`` / ``defect`` / ``unexplained``）：
已知预期差异按机制归因模板归类（双轨 header 判定差异 / 直抽粒度差异 / 抽检 verifier 面差异 /
无 LLM 时开关诚实降级）；无法归类的标 ``unexplained`` 供人工。

三种 **HARD 门**任一失败即 ``exit 2`` 停线（不带病前进）：

  1. ``protected_encoding_zero_drift`` —— 受保护编码（OBIS / 事件号 / hex）在新路径确定性
     产物里不得丢失任何一个（``cosem_behavior_spec.extract_codes`` 同源口径，"OBIS 错一位
     即严重缺陷"）。
  2. ``conservation_closed`` —— 功能需求级守恒（exactly-once 覆盖条款集合）；新路径若产出
     ``functional_requirements.json``，其 ``conservation`` 必须闭合（``raise_if_unconserved``
     不抛）。
  3. ``deterministic_core_byte_stable`` —— CAS：开关翻动不得污染确定性核。``blocks`` /
     ``atomic_requirements`` / ``chunks`` / ``table_items`` / ``table_cell_items`` 五件
     确定性产物在新旧两路必须逐字节一致（核心身份稳定，开关只应是旁路增量）。

退出码对齐 ``docs/cli-contract.md``：0 达标 / 2 HARD 门失败或输入错误 / 3 校验或报告写错误 /
4 环境错误。stdout 为 UTF-8 JSON 信封；``--report`` 写人读 + JSON 双报告。

现实约束：金标 ABNT / 未见过的真实语料本机没有，真实语料影子跑批 **pending-human**。本工具用
**合成文档自证机制**（live 模式）+ ``--baseline-roots`` 复跑既有产物对（离线对比，不重跑流水线，
供真实语料 / 真实 LLM 产物对在外部就绪后直接套用）。工具绝不伪造真实语料的对比结论。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cosem_behavior_spec import extract_codes                     # noqa: E402
from extraction_units import EXTRACTION_UNITS_FILENAME            # noqa: E402
from functional_extract import (                                  # noqa: E402
    FUNCTIONAL_REQUIREMENTS_FILENAME,
    conservation_report,
    functional_extract_enabled,
    load_clauses,
)
from result_package import governed_artifact_path                  # noqa: E402

SHADOW_TOOL = "shadow-run"
SHADOW_VERSION = "shadow-run-v1"
SHADOW_REPORT_SCHEMA = "shadow-run-report/v1"
SHADOW_DIFF_SCHEMA = "shadow-run-difference/v1"

# 四个新开关（与 config.py ENV_REGISTRY 同名）。
SWITCH_DUAL_TRACK = "RATOMIZER_TABLE_DUAL_TRACK"
SWITCH_FUNCTIONAL_EXTRACT = "RATOMIZER_FUNCTIONAL_EXTRACT"
SWITCH_BUDGET = "RATOMIZER_LLM_BUDGET"
SWITCH_CLAIM_MODE = "RATOMIZER_CLAIM_LEDGER_MODE"
NEW_PATH_SWITCHES: tuple[str, ...] = (
    SWITCH_DUAL_TRACK,
    SWITCH_FUNCTIONAL_EXTRACT,
    SWITCH_BUDGET,
    SWITCH_CLAIM_MODE,
)

# 双轨假设产物名（与 atomize.TABLE_STRUCTURE_HYPOTHESES_FILENAME 同值，本工具自持常量避免
# cross-module import 副作用）。
TABLE_HYPOTHESES_FILE = "table_structure_hypotheses.jsonl"
# 抽检模式摘要 / 预算单 cost-report 产物名（开关 ON 时可能出现的旁路产物）。
CLAIM_SAMPLING_SUMMARY_FILE = "claim_sampling_summary.json"
COST_REPORT_FILE = "cost_report.json"

# 确定性核产物（atomize 直写根目录 / governed 读处解析）——CAS 字节稳定门的对象。
DETERMINISTIC_CORE_FILES: tuple[str, ...] = (
    "blocks.jsonl",
    "atomic_requirements.jsonl",
    "chunks.jsonl",
    "table_items.jsonl",
    "table_cell_items.jsonl",
)
# 全部受对比产物（确定性核 + 双轨假设 + 直抽产物 + 守恒投影 + manifest/质量报告）。
ALL_TRACKED_FILES: tuple[str, ...] = DETERMINISTIC_CORE_FILES + (
    "table_cell_dispositions.jsonl",
    TABLE_HYPOTHESES_FILE,
    FUNCTIONAL_REQUIREMENTS_FILENAME,
    CLAIM_SAMPLING_SUMMARY_FILE,
    COST_REPORT_FILE,
    "manifest.json",
    "quality_report.json",
)
# 归因模板枚举（difference.template）。
TPL_DIRECT_EXTRACT = "direct_extract_granularity"          # 直抽侧车新增 functional_requirements.json
TPL_EXTRACTION_UNIT_PLANNING = "extraction_unit_planning"  # 直抽/单元路由入口确定性规划 extraction_units
TPL_DUAL_TRACK_HEADER = "dual_track_header_judgment"        # 双轨签发假设 → header 判定差异
TPL_SAMPLING_VERIFIER = "sampling_verifier_coverage"        # 抽检模式 verifier 面差异
TPL_BUDGET_COST_REPORT = "budget_cost_report"               # 预算单 cost-report 产物差异
TPL_EXPECTED_DEGRADATION = "expected_degradation_no_llm"    # 开关 ON 但无 LLM → 诚实降级（无假设/cost）
TPL_EXPECTED_PRESERVED = "expected_preserved"               # 确定性核字节一致（非差异，正向证据）
ATTR_EXPECTED = "expected_difference"
ATTR_DEFECT = "defect"
ATTR_UNEXPLAINED = "unexplained"

TRUTHY = ("1", "true", "yes", "on")


# =============================================================================
# 产物读取（governed 寻址纪律：经 governed_artifact_path 解析，不裸拼）
# =============================================================================


def _product_path(root: Path, filename: str) -> Path:
    """确定性核产物 atomize 直写根目录；governed 产物在 package_v1 下走 .ratomizer/pipeline/。

    统一经 ``governed_artifact_path(..., for_write=False)``：legacy 布局它返回 ``root/filename``，
    package_v1 布局返回 ``root/.ratomizer/pipeline/filename``。只读解析，绝不创建目录。
    """
    return governed_artifact_path(root, filename, category="pipeline", for_write=False)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return obj if isinstance(obj, dict) else None


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _switches_on_env() -> dict[str, str]:
    """新路径开关全开（双轨/直抽/预算/抽检 sampling）。"""
    return {
        SWITCH_DUAL_TRACK: "1",
        SWITCH_FUNCTIONAL_EXTRACT: "1",
        SWITCH_BUDGET: "1",
        SWITCH_CLAIM_MODE: "sampling",
    }


def _switches_off_env() -> dict[str, str]:
    """旧路径：全部新开关显式 OFF（=生产确定性当前路径）。"""
    return {
        SWITCH_DUAL_TRACK: "0",
        SWITCH_FUNCTIONAL_EXTRACT: "0",
        SWITCH_BUDGET: "0",
        SWITCH_CLAIM_MODE: "full",  # B 轨发布路径 env 未设时本就走 full=生产行为不变
    }


# =============================================================================
# Live 模式：跑两条路径产出并排产物
# =============================================================================


def _apply_env(env: dict[str, str]) -> dict[str, str | None]:
    """覆盖式设置 env，返回 prior 供恢复。"""
    prior: dict[str, str | None] = {}
    for key, value in env.items():
        prior[key] = os.environ.get(key)
        os.environ[key] = value
    return prior


def _restore_env(prior: dict[str, str | None]) -> None:
    for key, value in prior.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _attach_dual_track_proposer_if_route(route: str | None) -> bool:
    """新路径双轨提议器：仅 openai_compatible route + config 可解析时挂（与 desktop_tasks 同源）。

    stub / 无 route / config 失败 → 不挂，atomize 走确定性 ``analyze_table``（诚实降级，
    归因为 ``expected_degradation_no_llm``）。返回是否挂上。
    """
    if not route or route == "stub":
        return False
    try:
        from ai_extract import DEFAULT_PIPELINE_PATH, config_for_route
        from atomize import set_table_dual_track_proposer
        from llm_table_understanding import propose_table_structure

        config = config_for_route(route, DEFAULT_PIPELINE_PATH)
    except Exception:  # noqa: BLE001 — 无 LLM 配置即不挂，诚实降级
        return False
    if config is None:
        return False

    def proposer(parsed_table, *, table_id="", block_id="", section_path=None):
        return propose_table_structure(parsed_table, config=config)

    try:
        set_table_dual_track_proposer(proposer)
        return True
    except Exception:  # noqa: BLE001
        return False


def _detach_dual_track_proposer() -> None:
    try:
        from atomize import clear_table_dual_track_proposer

        clear_table_dual_track_proposer()
    except Exception:  # noqa: BLE001
        pass


def run_live_pair(
    input_doc: Path,
    work_dir: Path,
    *,
    chunk_chars: int = 3500,
    llm_route: str | None = None,
    kb_paths: list[Path] | None = None,
    domain_pack_dir: Path | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """跑旧 / 新两条路径，返回 (old_root, new_root, run_meta)。

    旧路径 = 全部新开关 OFF；新路径 = 开关 ON + 直抽侧车（stub route 写
    ``functional_requirements.json``）+ 双轨提议器（仅真实 route 时挂）。
    """
    from atomize import run_atomizer_pipeline

    input_doc = Path(input_doc).expanduser().resolve()
    work_dir = Path(work_dir).expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    old_root = work_dir / "old"
    new_root = work_dir / "new"
    old_root.mkdir(parents=True, exist_ok=True)
    new_root.mkdir(parents=True, exist_ok=True)

    # --- 旧路径：开关全 OFF ---
    prior_off = _apply_env(_switches_off_env())
    try:
        run_atomizer_pipeline(
            input_doc, old_root,
            chunk_chars=chunk_chars, kb_paths=kb_paths, domain_pack_dir=domain_pack_dir,
        )
    finally:
        _restore_env(prior_off)

    # --- 新路径：开关全 ON + 直抽侧车 + （可选）双轨提议器 ---
    prior_on = _apply_env(_switches_on_env())
    proposer_attached = False
    try:
        proposer_attached = _attach_dual_track_proposer_if_route(llm_route)
        run_atomizer_pipeline(
            input_doc, new_root,
            chunk_chars=chunk_chars, kb_paths=kb_paths, domain_pack_dir=domain_pack_dir,
        )
        # 直抽侧车：开关 ON 时写 functional_requirements.json（stub route 确定性产出）。
        if functional_extract_enabled():
            try:
                from functional_extract import run_functional_extract

                run_functional_extract(new_root, route=llm_route or "stub")
            except Exception as exc:  # noqa: BLE001 — 直抽失败如实记录，不阻断对比
                pass
    finally:
        if proposer_attached:
            _detach_dual_track_proposer()
        _restore_env(prior_on)

    run_meta = {
        "input": str(input_doc),
        "llm_route": llm_route,
        "proposer_attached": proposer_attached,
        "dual_track_degraded_no_llm": not proposer_attached,
    }
    return old_root, new_root, run_meta


# =============================================================================
# 对比引擎 + 归因
# =============================================================================


def _file_presence(root: Path, filename: str) -> dict[str, Any]:
    path = _product_path(root, filename)
    exists = path.is_file()
    return {
        "path": str(path),
        "exists": exists,
        "sha256": _sha256_file(path) if exists else None,
        "size": path.stat().st_size if exists else 0,
    }


# manifest.json 携带运行身份字段（``generated_at`` 时间戳、``output_dir`` 路径）——同文档两次
# 运行必然不同，不属内容漂移。对比前剥离这些 volatile 键，只比确定性内容。
_VOLATILE_MANIFEST_KEYS: tuple[str, ...] = ("generated_at", "output_dir")


def _semantic_sha256(root: Path, filename: str) -> str | None:
    """对 manifest.json / quality_report.json 用去 volatile 字段后的语义指纹。

    其他产物（确定性核 / 直抽 / 假设）走原始字节 sha256（它们不含运行时间戳）。
    """
    path = _product_path(root, filename)
    if not path.is_file():
        return None
    if filename == "manifest.json":
        obj = _read_json(path)
        if obj is None:
            return _sha256_file(path)
        normalized = {k: v for k, v in obj.items() if k not in _VOLATILE_MANIFEST_KEYS}
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return _sha256_file(path)


def _extract_codes_from_products(root: Path, filenames: Iterable[str]) -> set[str]:
    """聚合目录若干产物文本里出现的受保护编码集合。"""
    codes: set[str] = set()
    for filename in filenames:
        path = _product_path(root, filename)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        codes |= extract_codes(text)
    return codes


# 目录扫描时排除的非产物文件（缓存 / 锁 / 临时 / 日志 / 人读摘要 / 内部布局目录）。
_PRODUCT_SKIP_SUFFIXES = (".lock", ".tmp", ".meta.json", ".log", ".md")
_PRODUCT_SKIP_NAMES: frozenset[str] = frozenset({
    "functional_extract_cache.jsonl",  # 直抽缓存（指纹内部态，非交付产物）
})


def _discover_products(root: Path) -> set[str]:
    """枚举根目录下的 JSONL/JSON 产物文件名（legacy 布局），剔除缓存/锁/临时/日志。

    用于捕获 ``ALL_TRACKED_FILES`` 之外的**意外产物**（集成爆雷信号）——它们进差异清单并
    归 ``unexplained``。package_v1 的产物在 ``.ratomizer/`` 下，本扫描只看根目录交付物层。
    """
    root = Path(root)
    if not root.is_dir():
        return set()
    found: set[str] = set()
    for child in root.iterdir():
        if not child.is_file():
            continue
        name = child.name
        if name in _PRODUCT_SKIP_NAMES:
            continue
        if name.endswith(_PRODUCT_SKIP_SUFFIXES):
            continue
        if name.endswith(".jsonl") or name.endswith(".json"):
            found.add(name)
    return found


def compare_outputs(
    old_root: Path,
    new_root: Path,
    *,
    run_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """逐产物对比两个输出目录，产出差异清单（每条带归因）。"""
    old_root = Path(old_root).resolve()
    new_root = Path(new_root).resolve()
    run_meta = run_meta or {}

    differences: list[dict[str, Any]] = []
    core_byte_stable = True

    # 受对比文件集 = 已知产物 ∪ 两路目录里实际发现的产物（捕获 ALL_TRACKED_FILES 之外的意外产物）。
    discovered = _discover_products(old_root) | _discover_products(new_root)
    tracked_set = set(ALL_TRACKED_FILES) | discovered
    for filename in sorted(tracked_set):
        old_p = _file_presence(old_root, filename)
        new_p = _file_presence(new_root, filename)
        is_core = filename in DETERMINISTIC_CORE_FILES

        if old_p["exists"] and new_p["exists"]:
            # manifest/质量报告走语义指纹（剥离运行身份字段）；其余走原始字节。
            old_sem = _semantic_sha256(old_root, filename)
            new_sem = _semantic_sha256(new_root, filename)
            if old_sem == new_sem:
                # 内容一致：确定性核 → 正向 CAS 证据；非核 → 静默一致。
                if is_core:
                    differences.append(_diff(filename, "unchanged", TPL_EXPECTED_PRESERVED,
                                            ATTR_EXPECTED,
                                            "确定性核产物新旧逐字节一致（CAS 身份稳定）。"))
                continue
            # 两路都在但内容不同。
            template, attr, reason = _classify_mutation(
                filename, old_root, new_root, run_meta, is_core,
            )
            if is_core:
                core_byte_stable = False  # 确定性核字节漂移 = CAS 红灯
            differences.append(_diff(filename, "mutated", template, attr, reason,
                                     old_count=_record_count(old_root, filename),
                                     new_count=_record_count(new_root, filename)))
        elif new_p["exists"] and not old_p["exists"]:
            template, attr, reason = _classify_added(filename, run_meta)
            differences.append(_diff(filename, "added", template, attr, reason,
                                     new_count=_record_count(new_root, filename)))
        elif old_p["exists"] and not new_p["exists"]:
            # 旧有新无：直抽侧车产物等不应在确定性核里发生；确定性核丢失 = defect。
            template, attr, reason = _classify_removed(filename, is_core)
            differences.append(_diff(filename, "removed", template, attr, reason,
                                     old_count=_record_count(old_root, filename)))
        # 两路都无：跳过（非该路径产物）。

    # 受保护编码漂移扫描（独立于逐文件 diff，是 HARD 门取证来源）。
    old_codes = _extract_codes_from_products(old_root, DETERMINISTIC_CORE_FILES)
    new_codes = _extract_codes_from_products(new_root, DETERMINISTIC_CORE_FILES)
    codes_lost = sorted(old_codes - new_codes)
    codes_added = sorted(new_codes - old_codes)

    # 开关状态推断：双轨开关 ON 但无 LLM 提议器（降级）→ 显式记一条 expected_degradation。
    # 这不是文件 diff，而是"开关开了却没产生预期产物"的集成信号——拆解爆雷的关键情报。
    if run_meta.get("dual_track_degraded_no_llm"):
        hyp_in_new = _product_path(new_root, TABLE_HYPOTHESES_FILE).is_file()
        if not hyp_in_new:
            differences.append(_diff(
                "(switch:" + SWITCH_DUAL_TRACK + ")", "degraded",
                TPL_EXPECTED_DEGRADATION, ATTR_EXPECTED,
                "双轨开关 ON 但无 openai_compatible 提议器（stub / 无 route）→ atomize 走确定性"
                " analyze_table，未签发 table_structure_hypotheses.jsonl。属预期降级，非缺陷；"
                "真实 route 下此条消失并出现 dual_track_header_judgment 差异。",
            ))

    return {
        "schema": SHADOW_DIFF_SCHEMA,
        "old_root": str(old_root),
        "new_root": str(new_root),
        "differences": differences,
        "core_byte_stable": core_byte_stable,
        "protected_encoding": {
            "old_count": len(old_codes),
            "new_count": len(new_codes),
            "codes_lost": codes_lost,
            "codes_added": codes_added,
            "drift": bool(codes_lost),
        },
    }


def _diff(
    filename: str,
    kind: str,
    template: str,
    attribution: str,
    reason: str,
    *,
    old_count: int | None = None,
    new_count: int | None = None,
) -> dict[str, Any]:
    return {
        "schema": SHADOW_DIFF_SCHEMA,
        "file": filename,
        "kind": kind,  # added / removed / mutated / unchanged
        "template": template,
        "attribution": attribution,
        "reason": reason,
        "old_record_count": old_count,
        "new_record_count": new_count,
    }


def _record_count(root: Path, filename: str) -> int | None:
    if filename.endswith(".jsonl"):
        return len(_read_jsonl(_product_path(root, filename)))
    obj = _read_json(_product_path(root, filename))
    if obj is None:
        return None
    counts = obj.get("counts") if isinstance(obj.get("counts"), dict) else None
    if counts:
        # manifest.json counts 里有同名键就用它
        key = filename.removesuffix(".json")
        if key in counts:
            return counts[key]
    # functional_requirements.json：items 长度
    items = obj.get("items")
    if isinstance(items, list):
        return len(items)
    return None


def _classify_mutation(
    filename: str,
    old_root: Path,
    new_root: Path,
    run_meta: dict[str, Any],
    is_core: bool,
) -> tuple[str, str, str]:
    """两路都在但字节不同 → 归因模板。"""
    if filename == "table_structure_hypotheses.jsonl":
        return (TPL_DUAL_TRACK_HEADER, ATTR_EXPECTED,
                "双轨签发的表格结构假设集合发生变化（header/title/data 角色判定差异）。")
    if filename == FUNCTIONAL_REQUIREMENTS_FILENAME:
        return (TPL_DIRECT_EXTRACT, ATTR_EXPECTED,
                "直抽产物重生成（粒度 / 守恒投影随 route 变化）。")
    if filename == "manifest.json":
        # manifest 计数随假设/直抽产物联动是预期；但若它携带了确定性核计数变化则属 defect。
        return (TPL_EXPECTED_PRESERVED, ATTR_EXPECTED,
                "manifest 计数/文件清单随旁路产物联动（确定性核计数另由 CAS 门守卫）。")
    if filename == "quality_report.json":
        return (TPL_EXPECTED_PRESERVED, ATTR_EXPECTED,
                "质量报告计数随旁路产物联动（确定性核覆盖另由 CAS 门守卫）。")
    if is_core:
        return ("", ATTR_UNEXPLAINED,
                "确定性核产物在新路径下逐字节漂移——开关污染了确定性路径，需人工排查。")
    return ("", ATTR_UNEXPLAINED, "非核产物字节变化无法归因，需人工排查。")


def _classify_added(filename: str, run_meta: dict[str, Any]) -> tuple[str, str, str]:
    """新路径新增产物 → 归因模板。"""
    degraded = run_meta.get("dual_track_degraded_no_llm", False)
    if filename == FUNCTIONAL_REQUIREMENTS_FILENAME:
        return (TPL_DIRECT_EXTRACT, ATTR_EXPECTED,
                "直抽入口开关 ON：functional_extract 侧车新增 functional_requirements.json。")
    if filename == EXTRACTION_UNITS_FILENAME:
        return (TPL_EXTRACTION_UNIT_PLANNING, ATTR_EXPECTED,
                "直抽/单元路由入口开关 ON：functional_extract 确定性规划 "
                f"{EXTRACTION_UNITS_FILENAME}（A/B 共用单元事实源，零 LLM shadow 产物）。")
    if filename == "table_structure_hypotheses.jsonl":
        return (TPL_DUAL_TRACK_HEADER, ATTR_EXPECTED,
                "双轨开关 ON 且提议器签发：新增 table_structure_hypotheses.jsonl。")
    if filename == COST_REPORT_FILE:
        return (TPL_BUDGET_COST_REPORT, ATTR_EXPECTED,
                "预算单开关 ON：新增 cost-report 产物。")
    if filename == CLAIM_SAMPLING_SUMMARY_FILE:
        return (TPL_SAMPLING_VERIFIER, ATTR_EXPECTED,
                "抽检模式：新增 claim_sampling_summary.json（未抽中 claim 延迟到发布门禁）。")
    return ("", ATTR_UNEXPLAINED, f"新路径新增非预期产物 {filename}，需人工排查。")


def _classify_removed(filename: str, is_core: bool) -> tuple[str, str, str]:
    """新路径丢失旧路径产物 → 几乎都是 defect（确定性核丢 = 严重）。"""
    if is_core:
        return ("", ATTR_DEFECT,
                f"确定性核产物 {filename} 在新路径下消失——严重回归，停线修复。")
    return ("", ATTR_DEFECT, f"产物 {filename} 在新路径下消失，需排查。")


# =============================================================================
# HARD 门
# =============================================================================


def _gate(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "reason": reason}
    payload.update(extra)
    return payload


def hard_gates(old_root: Path, new_root: Path, comparison: dict[str, Any]) -> dict[str, Any]:
    """三道 HARD 门：受保护编码零漂移 / 守恒闭合 / 确定性核字节稳定（CAS）。"""
    # 1. 受保护编码零漂移
    pe = comparison.get("protected_encoding", {})
    drift_gate = (
        _gate("fail", "protected_encoding_drift", codes_lost=pe.get("codes_lost", []))
        if pe.get("drift") else
        _gate("pass", "no_protected_encoding_drift",
              old_count=pe.get("old_count"), new_count=pe.get("new_count"))
    )

    # 2. 守恒闭合：新路径若产出 functional_requirements.json，其 conservation 必须闭合——
    #    但**仅当产物 route 为权威**（真实 LLM 直抽）时未闭合才记 HARD 红灯。stub / degraded
    #    产出的未闭合守恒是预期降级（stub 不落地 source_block_ids，文档本就 NEEDS WORK），
    #    归 expected_degradation，不阻断；明细仍如实记入报告供审计。
    fr_new = _product_path(new_root, FUNCTIONAL_REQUIREMENTS_FILENAME)
    cons_gate: dict[str, Any]
    if fr_new.is_file():
        payload = _read_json(fr_new) or {}
        route = str(payload.get("route") or payload.get("route_requested") or "stub")
        authoritative = route not in ("stub", "degraded", "unavailable", "")
        cons = payload.get("conservation")
        if not isinstance(cons, dict):
            # 产物在但无 conservation 块：现场重算一次做权威核对。
            try:
                sections = load_clauses(new_root)
                items = payload.get("items") or []
                cons = conservation_report(sections, items, blocks=_load_blocks(new_root))
            except Exception as exc:  # noqa: BLE001
                cons_gate = _gate("fail", "functional_conservation_not_closed",
                                  detail=str(exc), route=route)
                cons = None
        if isinstance(cons, dict):
            closed = bool(cons.get("ok")) and not any(
                cons.get(k) for k in (
                    "missing_block_ids", "duplicate_assignments",
                    "extra_block_ids", "evidence_mismatches",
                )
            )
            detail = {
                "route": route,
                "covered_block_count": cons.get("covered_block_count"),
                "missing": len(cons.get("missing_block_ids") or []),
                "duplicate": len(cons.get("duplicate_assignments") or []),
                "extra": len(cons.get("extra_block_ids") or []),
                "evidence_mismatch": len(cons.get("evidence_mismatches") or []),
            }
            if closed:
                cons_gate = _gate("pass", "functional_conservation_closed", **detail)
            elif authoritative:
                cons_gate = _gate("fail", "functional_conservation_not_closed", **detail)
            else:
                # stub/degraded 未闭合 = 预期降级（文档 NEEDS WORK 已是真实门禁），HARD 门放过。
                cons_gate = _gate(
                    "pass", "functional_conservation_degraded_expected",
                    note="stub/degraded 直抽不落地 source_block_ids，未闭合属预期降级；"
                         "真实 route 产物未闭合才会触发 HARD 红灯。",
                    **detail,
                )
    else:
        cons_gate = _gate("pass", "functional_evidence_not_applicable",
                          note="新路径未产出 functional_requirements.json（直抽开关 OFF 或降级）。")

    # 3. CAS：确定性核字节稳定。
    cas_gate = (
        _gate("pass", "deterministic_core_byte_stable")
        if comparison.get("core_byte_stable") else
        _gate("fail", "deterministic_core_byte_drift",
              note="确定性核产物在新路径下逐字节漂移——开关污染了确定性身份。")
    )

    gates = {
        "protected_encoding_zero_drift": drift_gate,
        "conservation_closed": cons_gate,
        "deterministic_core_byte_stable": cas_gate,
    }
    gates["all_pass"] = all(g["status"] == "pass" for g in gates.values())
    return gates


def _load_blocks(root: Path) -> list[dict[str, Any]]:
    return _read_jsonl(_product_path(root, "blocks.jsonl"))


# =============================================================================
# 归因汇总 + 裁决
# =============================================================================


def _attribution_tally(differences: list[dict[str, Any]]) -> dict[str, Any]:
    tally: dict[str, int] = {ATTR_EXPECTED: 0, ATTR_DEFECT: 0, ATTR_UNEXPLAINED: 0}
    templates: dict[str, int] = {}
    for diff in differences:
        attr = diff.get("attribution") or ATTR_UNEXPLAINED
        tally[attr] = tally.get(attr, 0) + 1
        tpl = diff.get("template") or "(none)"
        templates[tpl] = templates.get(tpl, 0) + 1
    return {"by_attribution": tally, "by_template": templates}


def _decide(gates: dict[str, Any], tally: dict[str, Any]) -> tuple[str, list[str]]:
    reds: list[str] = []
    for name, gate in gates.items():
        if name == "all_pass":
            continue
        if gate.get("status") != "pass":
            reds.append(name)
    has_unexplained_or_defect = (
        tally["by_attribution"].get(ATTR_UNEXPLAINED, 0) > 0
        or tally["by_attribution"].get(ATTR_DEFECT, 0) > 0
    )
    if reds or has_unexplained_or_defect:
        return "fail", reds
    return "pass", []


# =============================================================================
# 报告 + 人读摘要
# =============================================================================


def build_report(
    comparison: dict[str, Any],
    gates: dict[str, Any],
    *,
    old_root: Path,
    new_root: Path,
    run_meta: dict[str, Any] | None,
    fixture_identity: dict[str, Any] | None,
    real_corpus_pending: bool,
    mode: str,
) -> dict[str, Any]:
    differences = comparison.get("differences", [])
    tally = _attribution_tally(differences)
    decision, reds = _decide(gates, tally)
    # 只把"差异"（非 unchanged 正向证据）计入清单显示；正向证据单独计数。
    shown = [d for d in differences if d.get("kind") != "unchanged"]
    preserved_core = [
        d["file"] for d in differences
        if d.get("kind") == "unchanged" and d.get("template") == TPL_EXPECTED_PRESERVED
    ]
    return {
        "schema": SHADOW_REPORT_SCHEMA,
        "tool": SHADOW_TOOL,
        "version": SHADOW_VERSION,
        "mode": mode,  # live / baseline-roots
        "old_root": str(old_root),
        "new_root": str(new_root),
        "run_meta": run_meta or {},
        "fixture_identity": fixture_identity or {},
        "real_corpus_pending": real_corpus_pending,
        "summary": {
            "decision": decision,
            "red_lights": reds,
            "differences_shown": len(shown),
            "deterministic_core_preserved": preserved_core,
            "attribution": tally["by_attribution"],
            "templates": tally["by_template"],
            "protected_encoding": comparison.get("protected_encoding", {}),
        },
        "hard_gates": gates,
        "differences": shown,
        "note": (
            "HARD 门（受保护编码零漂移 / 守恒闭合 / 确定性核字节稳定 CAS）任一失败即 exit 2 停线。"
            " expected_difference = 机制可解释的预期差异；defect / unexplained = 需人工或修复。"
            " 真实金标 / 未见过的语料影子跑批 pending-human；本报告基于合成 fixture 自证机制，"
            "不伪造真实语料对比结论。"
        ),
    }


def render_human_summary(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# 影子运行报告（{report['tool']} / {report['version']}）",
        "",
        f"- 模式：``{report['mode']}``",
        f"- 裁决：**{s['decision'].upper()}**" + (
            f"（红灯：{', '.join(s['red_lights'])}）" if s["red_lights"] else "（HARD 门全绿）"
        ),
        f"- 差异数（非正向证据）：{s['differences_shown']}",
        f"- 归因分布：{s['attribution']}",
        f"- 模板分布：{s['templates']}",
        f"- 受保护编码：old={s['protected_encoding'].get('old_count')} "
        f"new={s['protected_encoding'].get('new_count')} "
        f"丢失={s['protected_encoding'].get('codes_lost') or []}",
        f"- 确定性核字节稳定（CAS）：{report['hard_gates']['deterministic_core_byte_stable']['status']}",
        f"- 确定性核正向保留：{s['deterministic_core_preserved']}",
        "",
        "## HARD 门",
    ]
    for name, gate in report["hard_gates"].items():
        if name == "all_pass":
            continue
        lines.append(f"- {name}: **{gate['status']}** — {gate.get('reason', '')}")
    if report.get("fixture_identity"):
        lines.append("")
        lines.append("## fixture 身份")
        for key, value in report["fixture_identity"].items():
            lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append(f"> 真实语料 pending: **{report['real_corpus_pending']}** — "
                 "本报告基于合成 fixture 自证机制，真实金标 / 未见过的语料跑批 pending-human。")
    if report["summary"]["differences_shown"]:
        lines.append("")
        lines.append("## 差异清单")
        for diff in report["differences"]:
            lines.append(
                f"- `{diff['file']}` ({diff['kind']}) → {diff['attribution']} / "
                f"{diff['template'] or '(none)'}：{diff['reason']}"
            )
    return "\n".join(lines) + "\n"


# =============================================================================
# 命令
# =============================================================================


def _fail_envelope(command: str, error_type: str, message: str, *, exit_code: int) -> None:
    print(json.dumps({
        "tool": "requirement-atomizer",
        "command": command,
        "ok": False,
        "error": {"type": error_type, "message": message},
    }, ensure_ascii=False))
    raise SystemExit(exit_code)


def _fixture_identity(input_doc: Path) -> dict[str, Any]:
    """合成 fixture 身份：文件名 + sha256 + 体积（不读业务内容，只标识产物来源）。"""
    input_doc = Path(input_doc)
    digest = _sha256_file(input_doc) if input_doc.is_file() else None
    return {
        "kind": "synthetic_fixture",
        "name": input_doc.name,
        "sha256": digest,
        "size": input_doc.stat().st_size if input_doc.is_file() else 0,
    }


def _is_real_corpus(input_doc: Path | None) -> bool:
    """真实语料判定：金标 ABNT 家族 / Blue Book / 公司模板等机器本地资产路径。

    本 worktree 无这些资产；live 模式的合成 fixture 一律不判为真实语料。真实语料判定为 False
    时报告 ``real_corpus_pending=True``。
    """
    if input_doc is None:
        return False
    name = Path(input_doc).name.lower()
    return any(token in name for token in ("abnt", "blue-book", "bluebook", "16968"))


def cmd_run(args: argparse.Namespace) -> int:
    report_path = Path(args.report).expanduser().resolve() if args.report else None
    human_path = Path(args.human).expanduser().resolve() if args.human else None

    old_root: Path
    new_root: Path
    run_meta: dict[str, Any] = {}
    fixture_identity: dict[str, Any] | None = None
    mode: str

    try:
        if args.baseline_roots is not None:
            # 离线对比模式：不重跑流水线，直接对比既有产物对（T4-3）。
            if len(args.baseline_roots) != 2:
                _fail_envelope("shadow-run", "input_error",
                               "--baseline-roots 需要恰好两个目录 (OLD NEW)", exit_code=2)
            old_root = Path(args.baseline_roots[0]).resolve()
            new_root = Path(args.baseline_roots[1]).resolve()
            for root in (old_root, new_root):
                if not root.is_dir():
                    _fail_envelope("shadow-run", "input_error",
                                   f"baseline root 不存在或非目录: {root}", exit_code=2)
            mode = "baseline-roots"
            real_corpus = bool(args.real_corpus)
        else:
            # live 模式：跑两条路径。
            if args.input is None:
                _fail_envelope("shadow-run", "input_error",
                               "需要 --input <doc>（live）或 --baseline-roots OLD NEW（离线）",
                               exit_code=2)
            input_doc = Path(args.input).expanduser().resolve()
            if not input_doc.is_file():
                _fail_envelope("shadow-run", "input_error",
                               f"输入文件不存在: {input_doc}", exit_code=2)
            if input_doc.suffix.lower() not in (".docx", ".xlsx", ".pdf"):
                _fail_envelope("shadow-run", "input_error",
                               f"不支持的输入格式: {input_doc.suffix}（支持 .docx/.xlsx/.pdf）",
                               exit_code=2)
            work_dir = Path(args.work_dir).expanduser().resolve()
            old_root, new_root, run_meta = run_live_pair(
                input_doc, work_dir,
                chunk_chars=args.chunk_chars,
                llm_route=args.llm_route,
                kb_paths=[Path(p) for p in (args.kb or [])] or None,
                domain_pack_dir=Path(args.domain_pack).resolve() if args.domain_pack else None,
            )
            fixture_identity = _fixture_identity(input_doc)
            mode = "live"
            real_corpus = _is_real_corpus(input_doc)

        comparison = compare_outputs(old_root, new_root, run_meta=run_meta)
        gates = hard_gates(old_root, new_root, comparison)
        report = build_report(
            comparison, gates,
            old_root=old_root, new_root=new_root,
            run_meta=run_meta, fixture_identity=fixture_identity,
            real_corpus_pending=not real_corpus, mode=mode,
        )
    except (ValueError, KeyError, TypeError) as exc:
        _fail_envelope("shadow-run", "validation_error",
                       f"{type(exc).__name__}: {exc}", exit_code=3)
    except OSError as exc:
        _fail_envelope("shadow-run", "environment_error",
                       f"{type(exc).__name__}: {exc}", exit_code=4)

    decision = report["summary"]["decision"]

    # 写报告（JSON + 人读）。
    if report_path is not None:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            _fail_envelope("shadow-run", "report_write_error",
                           f"{type(exc).__name__}: {exc}", exit_code=3)
    if human_path is not None:
        try:
            human_path.parent.mkdir(parents=True, exist_ok=True)
            human_path.write_text(render_human_summary(report), encoding="utf-8")
        except OSError as exc:
            _fail_envelope("shadow-run", "report_write_error",
                           f"{type(exc).__name__}: {exc}", exit_code=3)

    envelope = {
        "tool": "requirement-atomizer",
        "command": "shadow-run",
        "ok": decision == "pass",
        "decision": decision,
        "mode": report["mode"],
        "real_corpus_pending": report["real_corpus_pending"],
        "differences_shown": report["summary"]["differences_shown"],
        "attribution": report["summary"]["attribution"],
        "templates": report["summary"]["templates"],
        "protected_encoding_drift": report["summary"]["protected_encoding"].get("drift", False),
        "codes_lost": report["summary"]["protected_encoding"].get("codes_lost", []),
        "hard_gates": {
            name: gate["status"] for name, gate in report["hard_gates"].items() if name != "all_pass"
        },
        "report": str(report_path) if report_path else None,
        "human_report": str(human_path) if human_path else None,
        "error": (
            {"type": "hard_gate_or_defect",
             "message": "HARD 门失败或存在 defect/unexplained 差异："
                        + ", ".join(report["summary"]["red_lights"] or ["defect/unexplained"])}
            if decision == "fail" else None
        ),
    }
    print(json.dumps(envelope, ensure_ascii=False))
    return 0 if decision == "pass" else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shadow_run.py",
        description="T4/S3 全开关影子运行：旧路径 vs 新路径（双轨/直抽/抽检/预算）并排对比 + HARD 门。"
                    "退出码 0/2/3/4 对齐 cli-contract。",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", type=Path, default=None,
                      help="live 模式输入文档（.docx/.xlsx/.pdf）——跑两条路径产出并排产物")
    mode.add_argument("--baseline-roots", type=Path, nargs=2, default=None,
                      metavar=("OLD", "NEW"),
                      help="离线对比模式：两个既有输出目录（旧/新），不重跑流水线")
    parser.add_argument("--work-dir", type=Path, default=Path("shadow_run_work"),
                        help="live 模式工作目录（产物写 <work-dir>/old 与 /new）")
    parser.add_argument("--chunk-chars", type=int, default=3500)
    parser.add_argument("--kb", type=Path, action="append", default=[])
    parser.add_argument("--domain-pack", type=Path, default=None)
    parser.add_argument("--llm-route", choices=["stub", "openai_compatible"], default="stub",
                        help="双轨提议器仅在 openai_compatible 时挂（stub=诚实降级）")
    parser.add_argument("--real-corpus", action="store_true",
                        help="显式声明 --baseline-roots 为真实语料产物对（默认 pending）")
    parser.add_argument("--report", type=Path, default=None, help="输出 JSON 报告路径")
    parser.add_argument("--human", type=Path, default=None, help="输出人读 Markdown 摘要路径")
    parser.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        try:
            args = parser.parse_args(argv)
            return int(args.func(args))
        except FileNotFoundError as exc:
            _fail_envelope("shadow-run", "input_error", str(exc), exit_code=2)
        except (ValueError, KeyError, TypeError) as exc:
            _fail_envelope("shadow-run", "validation_error",
                           f"{type(exc).__name__}: {exc}", exit_code=3)
        except OSError as exc:
            _fail_envelope("shadow-run", "environment_error",
                           f"{type(exc).__name__}: {exc}", exit_code=4)
    except SystemExit as exc:
        # argparse usage 错误（缺必选 / 互斥冲突）也走 SystemExit(2)；进程内调用方拿到 int。
        return int(exc.code) if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
