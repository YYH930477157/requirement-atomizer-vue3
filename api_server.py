from __future__ import annotations

import argparse
import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from review_actions import apply_review_action
from ai_review_actions import apply_ai_review_action, read_ai_review_states, source_ai_requirement_id
from io_utils import read_jsonl
from llm_client import LLMConnectionError, LLMResponseError, chat_json
from llm_pipeline import DEFAULT_PIPELINE_PATH, llm_config_from_route, load_review_pipeline
from requirement_kb.matching import clean_text as normalize_text


DEFAULT_OUTPUT = Path("out/abnt_nbr_16968_atomizer_v5")
DEFAULT_ALLOWED_ORIGINS = {"http://127.0.0.1:8770", "http://localhost:8770"}
TOKEN_HEADER = "X-Requirement-Atomizer-Token"


class RequirementAPIHandler(BaseHTTPRequestHandler):
    output_dir: Path = DEFAULT_OUTPUT
    allowed_origins: set[str] = set(DEFAULT_ALLOWED_ORIGINS)
    local_token: str = ""

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        if parsed.path == "/health":
            self.send_json({"ok": True, "service": "requirement-atomizer-api"})
            return
        if not token_is_valid(self.local_token, self.headers, params):
            self.send_json({"error": "unauthorized"}, status=401)
            return
        if parsed.path == "/document/pdf":
            # 惰性反向导入（同 _clean_block_text 先例）：影印批注数据的唯一权威实现在导出侧,
            # 应用内视图与分享 HTML 共用同一份几何/换算——双渲染器等价靠同源,不靠各写一份
            from doc_annotation_export import build_pdf_annotation_payload
            self.send_json(build_pdf_annotation_payload(self.output_dir))
            return
        if parsed.path.startswith("/document/pages/"):
            filename = parsed.path.rsplit("/", 1)[-1]
            # 文件名白名单（防路径穿越）：只放行导出侧生成的 page-NNNN.png
            if not re.fullmatch(r"page-\d{4}\.png", filename):
                self.send_json({"error": "invalid page name"}, status=403)
                return
            target = self.output_dir / "document_pages" / filename
            if not target.is_file():
                self.send_json({"error": "page not found"}, status=404)
                return
            raw = target.read_bytes()
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/manifest":
            self.send_file_json("manifest.json")
            return
        if parsed.path == "/quality":
            self.send_file_json("quality_report.json")
            return
        if parsed.path == "/requirements":
            limit = parse_int(one(params, "limit"), default=50)
            requirement_type = one(params, "type")
            rows = read_jsonl(self.output_dir / "atomic_requirements.jsonl")
            if requirement_type:
                rows = [row for row in rows if row.get("requirement_type") == requirement_type]
            self.send_json(enrich_requirements(rows[:limit], self.output_dir))
            return
        if parsed.path == "/reviews":
            limit = parse_int(one(params, "limit"), default=50)
            self.send_json(read_jsonl(self.output_dir / "llm_review_results.jsonl")[:limit])
            return
        if parsed.path == "/review-states":
            limit = parse_int(one(params, "limit"), default=50)
            status = one(params, "status")
            rows = read_jsonl(self.output_dir / "review_states.jsonl")
            if status:
                rows = [row for row in rows if row.get("status") == status]
            self.send_json(rows[:limit])
            return
        if parsed.path == "/review-summary":
            self.send_json(build_review_summary(self.output_dir))
            return
        if parsed.path == "/document":
            self.send_json(build_document_blocks(self.output_dir))
            return
        if parsed.path == "/ai-requirements":
            self.send_json(build_ai_requirements(self.output_dir))
            return
        self.send_error(404, "Unknown endpoint")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        if not self.local_token or not token_is_valid(self.local_token, self.headers, params):
            self.send_json({"error": "unauthorized"}, status=401)
            return
        if parsed.path == "/translations":
            self.handle_translation()
            return
        if parsed.path == "/ai-review-actions":
            self.handle_ai_review_action()
            return
        if parsed.path != "/review-actions":
            self.send_error(404, "Unknown endpoint")
            return

        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(payload.get("requirement_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        actor = str(payload.get("actor") or "").strip() or None
        reason = str(payload.get("reason") or "").strip()
        if not requirement_id or not status:
            self.send_json({"error": "requirement_id and status are required"}, status=400)
            return
        try:
            state = apply_review_action(self.output_dir, requirement_id, status, actor=actor, reason=reason)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=409)
            return
        self.send_json(state)

    def handle_translation(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(payload.get("requirement_id") or "").strip()
        text = str(payload.get("text") or "").strip()
        if not text:
            self.send_json({"error": "text is required"}, status=400)
            return
        try:
            translation = translate_requirement_text(text, requirement_id=requirement_id, output_dir=self.output_dir)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (LLMConnectionError, LLMResponseError) as exc:
            self.send_json({"error": str(exc)}, status=502)
            return
        self.send_json({"requirement_id": requirement_id, "translation": translation})

    def handle_ai_review_action(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        req_id = str(payload.get("ai_req_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        module_override = str(payload.get("module_override") or "").strip() or None
        ownership_override = str(payload.get("ownership_override") or "").strip() or None
        reason = str(payload.get("reason") or "").strip()
        actor = str(payload.get("actor") or "").strip() or None
        if not req_id or not status:
            self.send_json({"error": "ai_req_id and status are required"}, status=400)
            return
        try:
            state = apply_ai_review_action(self.output_dir, req_id, status,
                                           module_override=module_override,
                                           ownership_override=ownership_override,
                                           reason=reason, actor=actor)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=409)
            return
        # 裁决即时回流交付物：重建 merged_spec（免 LLM，秒级）。失败不影响裁决本身。
        if (self.output_dir / "ai_requirements.jsonl").exists():
            try:
                from ai_extract import rebuild_merged_spec
                rebuild_merged_spec(self.output_dir)
            except Exception as exc:  # pragma: no cover - 重建失败仅记日志
                import logging
                logging.getLogger("requirement_atomizer").warning("裁决后重建交付物失败：%s", exc)
        self.send_json(state)

    def read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "invalid content length"}, status=400)
            return None
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "invalid json body"}, status=400)
            return None
        if not isinstance(payload, dict):
            self.send_json({"error": "json body must be an object"}, status=400)
            return None
        return payload

    def send_file_json(self, filename: str) -> None:
        path = self.output_dir / filename
        if not path.exists():
            self.send_error(404, f"Missing file: {filename}")
            return
        self.send_json(json.loads(path.read_text(encoding="utf-8")))

    def send_json(self, payload, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin and is_allowed_origin(origin, self.allowed_origins):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif "null" in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {TOKEN_HEADER}")

    def log_message(self, format: str, *args) -> None:
        return


def one(params: dict[str, list[str]], name: str) -> str:
    values = params.get(name) or [""]
    return values[0]


def parse_int(value: str, *, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


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


def enrich_requirements(requirements: list[dict], output_dir: Path) -> list[dict]:
    reviews_by_requirement = index_by_requirement_identity(read_jsonl(output_dir / "llm_review_results.jsonl"))
    states_by_requirement = index_by_requirement_identity(read_jsonl(output_dir / "review_states.jsonl"))
    enriched: list[dict] = []
    for requirement in requirements:
        row = dict(requirement)
        for key in requirement_identity_keys(row):
            if key in reviews_by_requirement:
                row["review"] = reviews_by_requirement[key]
                break
        for key in requirement_identity_keys(row):
            if key in states_by_requirement:
                row["review_state"] = states_by_requirement[key]
                break
        enriched.append(row)
    return enriched


_BLOCK_FIELDS = ("block_id", "order", "type", "text", "section_path",
                 "page_number", "requirement_like", "noise", "doc_region",
                 # 表格块渲染真表格所需（旧 blocks.jsonl 无这些字段 → None，前端回退扁平文字）
                 "table_title", "table_source", "header_rows", "data_rows")

# 块级中文翻译缓存（内容哈希键,仅由真 LLM 写入;详见 doc_annotation_export 的生成侧）。
# 键函数与加载器放这里作为唯一实现——批注导出与本 API 两个渲染面共用,防分叉。
ANNOTATION_TRANSLATIONS = "annotation_translations.json"


def translation_key(text: object) -> str:
    import hashlib
    return hashlib.sha1(" ".join(str(text or "").split()).encode("utf-8")).hexdigest()


def load_annotation_translations(output_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """annotation_translations.json → (可嵌入译文, 被拒条目原因)。缺失/损坏 → 空（视图无翻译照常）。"""
    try:
        data = json.loads((Path(output_dir) / ANNOTATION_TRANSLATIONS).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    items = data.get("items") if isinstance(data, dict) else None
    translations: dict[str, str] = {}
    notes: dict[str, str] = {}
    if isinstance(items, dict):
        for key, entry in items.items():
            if not isinstance(entry, dict):
                continue
            translation = str(entry.get("translation") or "").strip()
            if translation and not entry.get("rejected"):
                translations[str(key)] = translation
            elif entry.get("rejected"):
                notes[str(key)] = str(entry.get("reason") or "翻译未通过防幻觉校验")
    return translations, notes


def build_document_blocks(output_dir: Path) -> dict:
    """供文档批注视图：blocks 按 order 排序、只留渲染需要的字段（去掉 kb_matches 等重负载）。

    附带块级中文翻译（内容哈希查缓存）：未覆盖段/说明标记的三段式卡片（原因/翻译/引用）
    在应用内视图与导出 HTML 同语义。"""
    blocks = read_jsonl(output_dir / "blocks.jsonl")
    trimmed = [{k: b.get(k) for k in _BLOCK_FIELDS} for b in blocks]
    translations, notes = load_annotation_translations(output_dir)
    clean_block_text = None
    if translations or notes:
        # 键同源（0714 评审跟进）：导出侧写缓存的键 = 渲染清洗后文本的哈希;此前 API 只按
        # 原始文本取键,含 leader-dots/私用字形的块在应用内查不到译文（两评审面译文有无不一致）。
        # 惰性反向导入写侧的唯一权威实现（doc_annotation_export 顶层 import 本模块,函数级
        # 导入在运行期无环）;先按原始键查（旧缓存兼容）,未命中再按清洗键查。
        from doc_annotation_export import _clean_block_text as clean_block_text
    for block in trimmed:
        original_text = block.get("text")
        if translations or notes:
            keys = [translation_key(original_text)]
            if clean_block_text is not None:
                cleaned_key = translation_key(clean_block_text(str(original_text or "")))
                if cleaned_key != keys[0]:
                    keys.append(cleaned_key)
            for key in keys:
                if key in translations:
                    block["translation"] = translations[key]
                    break
                if key in notes:
                    block["translation_note"] = notes[key]
                    break
        block["text"] = normalize_text(original_text)
    trimmed.sort(key=lambda b: b.get("order") or 0)
    return {"blocks": trimmed, "count": len(trimmed)}


_WS_RE = re.compile(r"\s+")


def _norm_text(s: object) -> str:
    return _WS_RE.sub(" ", str(s or "")).strip().lower()


def anchor_block_id(req: dict, text_by_block: dict[str, str]) -> str:
    """需求精确锚点：含其 source_quote 原句的那一小段（段落级），否则回退 source_block_ids 首块。

    批注挂在需求实际所在的小段上（而非整章节段首），符合"一小段一个需求点"。
    """
    span = [str(b) for b in (req.get("source_block_ids") or [])]
    quote = _norm_text(req.get("source_quote"))
    if quote:
        for bid in span:
            if quote in _norm_text(text_by_block.get(bid, "")):
                return bid
        prefix = quote[:40]  # LLM 引用偶有尾部偏差，用前缀兜一层
        if prefix:
            for bid in span:
                if prefix in _norm_text(text_by_block.get(bid, "")):
                    return bid
    return span[0] if span else ""


def _functional_membership(output_dir: Path) -> dict[str, dict]:
    path = output_dir / "functional_requirements.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    mapping: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        projected = {
            "functional_requirement_id": item.get("functional_requirement_id"),
            "functional_title": item.get("title"),
            "functional_objective": item.get("objective"),
            "functional_behaviors": item.get("behaviors") or [],
            "functional_preconditions": item.get("preconditions") or [],
            "functional_data_constraints": item.get("data_constraints") or [],
            "functional_variants": item.get("variants") or [],
            "functional_exceptions": item.get("exceptions") or [],
            "functional_related_dlms_objects": item.get("related_dlms_objects") or [],
            "functional_merge_method": item.get("merge_method"),
            "functional_merge_confidence": item.get("merge_confidence"),
            "functional_conflict_flags": item.get("conflict_flags") or [],
        }
        for source_id in item.get("source_ai_requirement_ids") or []:
            mapping[str(source_id)] = projected
    return mapping


def _analysis_enrichment(output_dir: Path) -> dict[str, dict]:
    """engineering_analysis.json → AIR id 一对多投影（analysis_ 前缀,批注视图消费）。

    此前富化正文只落 xlsx/成文,批注卡显示的"需求分析"一直是抽取轨浅描述——用户
    体感"分析不如聊天 AI"的最大一块其实是好内容没上墙。缺失/坏 JSON/异源 producer
    → 空 merge(裁决回流免 LLM 重建语义不受影响,视图与旧行为逐字节一致)。"""
    path = output_dir / "engineering_analysis.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    producer = str((payload.get("provenance") or {}).get("producer") or payload.get("producer") or "")
    if producer and not producer.startswith(("requirements_analysis", "analyze")):
        import logging
        logging.getLogger("requirement_atomizer").warning(
            "engineering_analysis.json producer 异源（%s），批注视图不合并其内容", producer)
        return {}
    items = payload.get("items")
    if not isinstance(items, list):
        return {}
    mapping: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        projected: dict = {
            "analysis_id": item.get("analysis_id"),
            "analysis_source": item.get("analysis_source"),
            "analysis_software_requirement_text": str(item.get("software_requirement_text") or ""),
            "analysis_dev_guidance": [str(v) for v in item.get("developer_guidance") or []],
            "analysis_design_options": [str(v) for v in item.get("design_options") or []],
            "analysis_acceptance_criteria": [str(v) for v in item.get("acceptance_criteria") or []],
            "analysis_open_questions": [str(v) for v in item.get("open_questions") or []],
            "analysis_assumptions": [str(v) for v in item.get("assumptions") or []],
            "analysis_enrichment_warnings": [str(v) for v in item.get("enrichment_warnings") or []],
            "analysis_ownership": item.get("ownership"),
            "analysis_ownership_reason": str(item.get("ownership_reason") or ""),
            "analysis_ownership_source": item.get("ownership_source"),
            "analysis_ownership_reason_source": item.get("ownership_reason_source"),
        }
        if str(item.get("hardware_translation") or "").strip():
            projected["hardware_translation"] = item.get("hardware_translation")
            projected["hardware_summary"] = item.get("hardware_summary")
        # 一对多展开：functional 合并后一个分析 item 携带 N 条 AIR id,N 张批注卡
        # 共享同一份分析;重复 sid 首见者胜(items 按 analysis_id 有序,确定性)
        for source_id in item.get("source_requirement_ids") or []:
            mapping.setdefault(str(source_id), projected)
    return mapping


def build_ai_requirements(output_dir: Path) -> list[dict]:
    """供文档批注视图：merged_spec 需求 + 内容稳定 ai_req_id + 精确锚点 + 当前裁决态。

    优先读 merged_spec_requirements.json（双引擎交付物），回退 ai_requirements_doc.json /
    ai_requirements.jsonl。anchor_block_id = 含 source_quote 的具体段落（段落级精确）。
    """
    requirements = _load_ai_requirements(output_dir)
    states = read_ai_review_states(output_dir)
    membership = _functional_membership(output_dir)
    analysis_map = _analysis_enrichment(output_dir)
    text_by_block = {str(b.get("block_id")): (b.get("text") or "")
                     for b in read_jsonl(output_dir / "blocks.jsonl")}
    from requirements_analysis_rules import classify_ownership  # 规则初判（确定性、零 LLM）
    dup_quotes, differ_codes = _consistency_markers(output_dir)

    enriched: list[dict] = []
    for req in requirements:
        rid = source_ai_requirement_id(req)
        state = states.get(rid)
        row = dict(req)
        row["ai_req_id"] = rid
        row.update(membership.get(rid, {}))
        row.update(analysis_map.get(rid, {}))   # 富化正文/归属原因上墙（缺失=空 merge）
        row["anchor_block_id"] = anchor_block_id(req, text_by_block)
        row["review_state"] = state
        # 专家改过模块则以 override 为准（module 字段保持原值供追溯）
        if state and state.get("module_override"):
            row["module_effective"] = state["module_override"]
        else:
            row["module_effective"] = req.get("module") or (req.get("labels") or [None])[0]
        # 归属单源化（真实反馈 2026-07-12,test18）：视图层与分析层各判一次会分叉——
        # 视图规则判 hardware、分析层判 software 时,硬件卡拿不到翻译、理由却是软件论证。
        # 优先采用分析层判定（含 override 生效后的值,与 analysis_ownership_reason 同源）,
        # 无分析产物才回退规则兜底;review_state 的 override 仍是最终权威（effective 逻辑不动）。
        if not row.get("ownership") and str(row.get("analysis_ownership") or "").strip():
            row["ownership"] = str(row["analysis_ownership"])
            row.setdefault("ownership_reason", str(row.get("analysis_ownership_reason") or ""))
            row.setdefault("ownership_source", row.get("analysis_ownership_source"))
        if not row.get("ownership"):
            verdict = classify_ownership(req)
            row["ownership"] = verdict["ownership"]
            for key in ("ownership_reason", "ownership_source", "ownership_confidence"):
                row.setdefault(key, verdict.get(key))
        if state and state.get("ownership_override"):
            row["ownership_effective"] = state["ownership_override"]
        else:
            row["ownership_effective"] = row["ownership"]
        row["status"] = (state or {}).get("status") or "draft"
        flags = _row_consistency_flags(row, dup_quotes, differ_codes)
        if flags:
            row["consistency_flags"] = flags
        enriched.append(row)
    return enriched


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
    states = read_jsonl(output_dir / "review_states.jsonl")
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


TRANSLATION_SYSTEM_PROMPT = """You are a technical translator for DLMS/COSEM requirements.
Translate English requirement text into concise Simplified Chinese.
Preserve identifiers, quoted service names, OBIS codes, class names, attribute names, and protocol acronyms.
Return only JSON with one string field: translation."""


def translate_requirement_text(text: str, *, requirement_id: str = "", output_dir: Path | None = None) -> str:
    pipeline = load_review_pipeline(DEFAULT_PIPELINE_PATH)
    route_payload = dict(pipeline.model_routes.get("openai_compatible") or {})
    config = llm_config_from_route(route_payload)
    payload = chat_json(
        config,
        TRANSLATION_SYSTEM_PROMPT,
        json.dumps(
            {
                "requirement_id": requirement_id,
                "text": text,
            },
            ensure_ascii=False,
        ),
    )
    translation = str(payload.get("translation") or "").strip()
    if not translation:
        raise LLMResponseError("LLM translation response missing translation")
    return translation


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve requirement atomizer output over a local HTTP API.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="Allowed browser Origin. Can be provided multiple times.",
    )
    parser.add_argument("--token", default="", help="Optional local API token required for data endpoints.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from desktop_tasks import setup_run_logging
    setup_run_logging(args.out)  # 长驻 API 的裁决回流/重建告警同样落 run.log + stderr
    RequirementAPIHandler.output_dir = args.out.expanduser().resolve()
    RequirementAPIHandler.allowed_origins = build_allowed_origins(args.host, args.port, args.allow_origin)
    RequirementAPIHandler.local_token = args.token
    server = ThreadingHTTPServer((args.host, args.port), RequirementAPIHandler)
    print(
        json.dumps(
            {
                "host": args.host,
                "port": args.port,
                "output_dir": str(RequirementAPIHandler.output_dir),
                "allowed_origins": sorted(RequirementAPIHandler.allowed_origins),
                "token_required": bool(RequirementAPIHandler.local_token),
            },
            indent=2,
        ),
        flush=True,
    )
    server.serve_forever()
    return 0


def build_allowed_origins(host: str, port: int, extra_origins: list[str]) -> set[str]:
    """"null" origin（file:///沙箱 iframe）不再无条件放行（2026-07-08 审计 6-A）：
    裸跑无 token 时 GET 端点吐客户文档全文，任何网页的沙箱 iframe 都能跨源读取。
    需要 file:// 场景（本地批注 HTML 本身自包含、不调 API）可显式 --allow-origin null。"""
    origins = {f"http://{host}:{port}", f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    origins.update(origin for origin in extra_origins if origin)
    return origins


if __name__ == "__main__":
    raise SystemExit(main())
