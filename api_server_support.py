"""api_server 支撑层（M9 第 3 刀，2026-08-17）：请求解析/鉴权 + 引句匹配 + 审阅摘要。

从 ``api_server.py`` 逐字搬运的帮助函数族——零执行语义变化，``api_server`` 原名
重导出（调用方/测试的 ``api_server.X`` 访问面不变）。选族纪律（M9 蓝图红线）：
本模块**不包含**任何测试 patch 目标（``out/m9-patch-targets.json`` api_server 20 个
全部留在 ``api_server.py``），且不反向依赖 ``api_server``（无环）：
- 解析/鉴权族：one/parse_int/parse_claim_page_value/is_allowed_origin/token_is_valid
  （+ TOKEN_HEADER、build_allowed_origins）；
- 引句匹配族：_norm_text/compute_echo_block_ids/quote_matched_block_ids/anchor_block_id；
- 审阅摘要族：load_review_insights/_consistency_markers/_row_consistency_flags/
  _load_ai_requirements/index_by_requirement_identity/requirement_identity_keys/
  build_review_summary。

翻译族（translation_key/_protected_*/load_annotation_translations）**不随搬**：
annotation_translations/doc_annotation_export/full_translation 顶层 import
``api_server.translation_key`` 等，搬走会引入 api_server↔翻译子系统循环导入。
"""
from __future__ import annotations

import hmac
import json
import re
from pathlib import Path
from typing import Mapping

from io_utils import read_jsonl
from result_package import governed_artifact_path

TOKEN_HEADER = "X-Requirement-Atomizer-Token"


def one(params: dict[str, list[str]], name: str) -> str:
    values = params.get(name) or [""]
    return values[0]


def parse_int(value: str, *, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def parse_claim_page_value(
    value: str,
    *,
    name: str,
    kind: str,
    default: int,
) -> int:
    """Parse the strict pagination contract used by all Claim Ledger GETs.

    ``kind`` ("limit" | "offset") drives validation; ``name`` is only the
    query field echoed in error messages.
    """
    if not value:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid claim {name}") from exc
    if kind == "limit":
        if not 1 <= parsed <= 500:
            raise ValueError(f"claim {name} must be between 1 and 500")
    elif kind == "offset":
        if parsed < 0:
            raise ValueError(f"claim {name} must be non-negative")
    else:  # pragma: no cover - internal programming error
        raise ValueError(f"unknown claim pagination kind: {kind}")
    return parsed


def is_allowed_origin(origin: str, allowed_origins: set[str]) -> bool:
    if not origin:
        return True
    if origin == "file://" or origin.startswith("file://"):
        return True
    return origin in allowed_origins


def token_is_valid(expected_token: str, headers: Mapping[str, str], params: dict[str, list[str]]) -> bool:
    if not expected_token:
        return True
    header_token = headers.get(TOKEN_HEADER, "")
    # 常量时间比较，避免字符串 == 短路造成的时序侧信道（token 是 server-wide 长期令牌）。
    # compare_digest 仅接受 ASCII/bytes，统一按 UTF-8 编码。
    try:
        return hmac.compare_digest(header_token.encode("utf-8"), expected_token.encode("utf-8"))
    except (UnicodeEncodeError, TypeError):
        return False


_WS_RE = re.compile(r"\s+")


def _norm_text(s: object) -> str:
    return _WS_RE.sub(" ", str(s or "")).strip().lower()


def compute_echo_block_ids(req: dict, blocks: list[dict]) -> list[str]:
    """同文重复出现的回声锚点(视图层专用字段,**不进** source_block_ids 溯源数据)。

    真实案例(0715 电表招标):同一段产品描述在 Scope 与 3.1 各出现一次,条目锚在
    首次出现,批注视图里第二次出现无任何标注 → 用户以为整段没解析出。
    两条匹配路:① 引句互含(全剥空白底座——PDF 碎词两次出现拆点不同,保留空白的
    归一化对不上;引句 ≥30 字);② 锚点原文对原文近重复(原文两次出现本身就有措辞
    微差:"measurement of"↔"measuring",且 LLM 引句尾部意译时路①失效)——剥空白
    相等,或 J≥0.8+数字多重集守卫(真实文档全对探针:目标对 0.97/真重复 0.84 保住,
    0.72 的跨章节相似句排除)。防噪:参照块与候选块剥空白后均 ≥60 字;跳过噪声块
    与已在 source_block_ids/anchor 里的块。"""
    from merged_consistency import reliable_echo_block_ids

    return reliable_echo_block_ids(req, blocks)


def quote_matched_block_ids(
    req: dict,
    text_by_block: dict[str, str],
    *,
    noise_block_ids: set[str] | None = None,
) -> list[str]:
    """原句匹配块集：source_quote 在来源块上的确定性匹配全集（锚点只是首块）。

    视图层证据区应覆盖原句实际跨越的全部块——多段引句只亮首块会丢后半段
    （test5 实证：引句跨 097+098 两块，蓝区只亮 097，与原句左右不一致）。
    噪声块 id 随行：页码/水印夹缝不再掐死窗口匹配（test7 实证）。
    """
    noise = noise_block_ids or set()
    span = [str(b) for b in (req.get("source_block_ids") or [])]
    from merged_consistency import compact_source_text, match_source_quote_blocks

    source_blocks = [
        {"block_id": block_id, "order": order,
         "text": text_by_block.get(block_id, ""), "noise": block_id in noise}
        for order, block_id in enumerate(span)
    ]
    matched, _mapping = match_source_quote_blocks(req.get("source_quote"), source_blocks)
    return [str(b) for b in matched]


def anchor_block_id(
    req: dict,
    text_by_block: dict[str, str],
    *,
    noise_block_ids: set[str] | None = None,
) -> str:
    """需求精确锚点：含其 source_quote 原句的那一小段（段落级），否则回退 source_block_ids 首块。

    批注挂在需求实际所在的小段上（而非整章节段首），符合"一小段一个需求点"。
    """
    span = [str(b) for b in (req.get("source_block_ids") or [])]
    matched = quote_matched_block_ids(req, text_by_block, noise_block_ids=noise_block_ids)
    if matched:
        return matched[0]
    from merged_consistency import compact_source_text

    quote = compact_source_text(req.get("source_quote"))
    if quote:
        # LLM 引用偶有尾部偏差。保留旧的“含空格前 40 字”兜底，并额外支持 PDF
        # 词内空格漂移；两者都只决定锚点，不扩大覆盖判定。
        normalized_prefix = _norm_text(req.get("source_quote"))[:40]
        compact_prefix = quote[:30]
        if normalized_prefix or compact_prefix:
            for bid in span:
                block_text = text_by_block.get(bid, "")
                if (
                    normalized_prefix and normalized_prefix in _norm_text(block_text)
                ) or (
                    compact_prefix and compact_prefix in compact_source_text(block_text)
                ):
                    return bid
    return span[0] if span else ""


def load_review_insights(output_dir: Path) -> dict:
    """裁决复盘建议（review_insights.json,裁决回流自动刷新）——0714 批次二 E5。

    此前该产物全链零消费者:专家改判提炼的规则改进建议(≥3 次同模式)永远躺磁盘,
    裁决学习回路事实断开。缺失/损坏 → available=false（老输出目录/未裁决时的正常态）。"""
    path = output_dir / "review_insights.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "suggestions": []}
    if not isinstance(payload, dict):
        return {"available": False, "suggestions": []}
    return {
        "available": True,
        "suggestions": [str(s) for s in payload.get("suggestions") or []],
        "decided_states": payload.get("decided_states"),
        "module_transitions": payload.get("module_transitions") or [],
        "ownership_transitions": payload.get("ownership_transitions") or [],
    }


def _consistency_markers(output_dir: Path) -> tuple[dict[str, int], set[str]]:
    """一致性闭环：读 consistency_report.json（P1b critic 产物），供批注视图标记。

    返回 (归一 source_quote → 重复组大小, 数值待核的 OBIS 集合)。报表缺失/损坏 → 空标记
    （视图与此前完全一致）。按 quote/OBIS 内容连接——报表成员是 merged REQ-id、视图行是
    AIR-id，内容键是两者天然共有的。
    """
    import re as _re
    path = output_dir / "consistency_report.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, set()
    if not isinstance(report, dict):
        return {}, set()

    def norm(s: object) -> str:
        return _re.sub(r"\s+", " ", str(s or "")).strip().lower()

    dup_quotes = {norm(g.get("source_quote")): int(g.get("count") or 0)
                  for g in report.get("duplicate_groups") or [] if g.get("source_quote")}
    differ_codes = {str(g.get("obis") or "") for g in report.get("obis_coreference") or []
                    if g.get("values_differ") and g.get("obis")}
    return dup_quotes, differ_codes


def _row_consistency_flags(row: dict, dup_quotes: dict[str, int], differ_codes: set[str]) -> list[str]:
    import re as _re
    flags: list[str] = []
    quote = _re.sub(r"\s+", " ", str(row.get("source_quote") or "")).strip().lower()
    if quote and quote in dup_quotes:
        flags.append(f"跨章重复×{dup_quotes[quote]}")
    if differ_codes:
        text = " ".join(str(row.get(k) or "") for k in ("title", "description", "source_quote"))
        hits = sorted(code for code in differ_codes if code in text)
        if hits:
            flags.append(f"OBIS 数值待核：{'、'.join(hits[:3])}")
    return flags


def _load_ai_requirements(output_dir: Path) -> list[dict]:
    # 批注视图优先读**原始** ai_requirements.jsonl：merged_spec 现在会剔除 rejected
    # （裁决回流交付物），若视图读 merged，被拒条目会从视图消失、无法反悔。
    raw = read_jsonl(output_dir / "ai_requirements.jsonl")
    if raw:
        return raw
    doc_path = output_dir / "merged_spec_requirements.json"
    if doc_path.exists():
        data = json.loads(doc_path.read_text(encoding="utf-8"))
        return list(data.get("requirements") or [])
    alt = output_dir / "ai_requirements_doc.json"
    if alt.exists():
        data = json.loads(alt.read_text(encoding="utf-8"))
        return list(data.get("requirements") or [])
    return []


def index_by_requirement_identity(rows: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        for key in requirement_identity_keys(row):
            indexed[key] = row
    return indexed


def requirement_identity_keys(row: dict) -> list[str]:
    keys: list[str] = []
    for name in ("stable_req_id", "requirement_id", "req_id"):
        value = row.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    for name in ("stable_req_id", "req_id"):
        value = metadata.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    return keys


def build_review_summary(output_dir: Path) -> dict:
    reviews = read_jsonl(output_dir / "llm_review_results.jsonl")
    states = read_jsonl(governed_artifact_path(
        output_dir, "review_states.jsonl", category="state", for_write=False,
    ))
    decision_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for review in reviews:
        decision = str(review.get("decision") or "unknown")
        risk = str(review.get("risk") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
    for state in states:
        status = str(state.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "counts": {
            "reviews": len(reviews),
            "review_states": len(states),
        },
        "decision_counts": decision_counts,
        "risk_counts": risk_counts,
        "status_counts": status_counts,
        "files": {
            "llm_review_results": "llm_review_results.jsonl",
            "review_states": "review_states.jsonl",
        },
    }


def build_allowed_origins(host: str, port: int, extra_origins: list[str]) -> set[str]:
    """"null" origin（file:///沙箱 iframe）不再无条件放行（2026-07-08 审计 6-A）：
    裸跑无 token 时 GET 端点吐客户文档全文，任何网页的沙箱 iframe 都能跨源读取。
    需要 file:// 场景（本地批注 HTML 本身自包含、不调 API）可显式 --allow-origin null。"""
    origins = {f"http://{host}:{port}", f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    origins.update(origin for origin in extra_origins if origin)
    return origins
