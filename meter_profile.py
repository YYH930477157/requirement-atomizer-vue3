"""从 atomizer 产出推断文档的表计类型 + 目标标准（确定性，零 LLM）。

assemble_spec / ai_extract 装配规格时用它取代写死的 electric + DLMS/COSEM/ABNT，
让燃气表/水表不再被套用电表框架（标题、目标标准是研发拿到规格第一眼看到的东西）。

判据（按置信度降序，确定性正则/计数，非 LLM 猜测）：
1. manifest.input 文件名/标题含明确表种词（"Gas meter"/"Water meter"/"electricity meter"）→ 直接定
2. 正文术语频次：某表种词显著多于其它 → 定该表种
3. 兜底 multi（不套用电表框架，留给专家/文档原文标注）

目标标准从 manifest.input 的标准号提取（EN 16314 / ABNT NBR 16968 / IEC 62056…），
提取不到就留空（不再写死电表的 ABNT）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from io_utils import read_jsonl


# 表种关键词（小写匹配）。electric 最易误判（meter 通用），故 electric 要求 electricity/electric 强信号。
_METER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "gas": ("gas meter", "gas volume", "gas flow", "gas conversion", "diaphragm gas", "turbine gas", "rotary gas"),
    "water": ("water meter", "cold water", "hot water", "water volume"),
    "electric": ("electricity meter", "electric meter", "active energy", "reactive energy", "apparent energy"),
}
# 标准号提取：EN 16314 / ABNT NBR 16968 / IEC 62056-5-3 / ISO/IEC 8802-2 …
# 前导 \b 防词内误伤（"GREEN 16968"→EN、"when 12345"→en、"specimen 4064"→en 都不再命中）；
# 子段 [0-9]{1,4} 容许单位数（IEC 62056-5-3 不再被截成 IEC 62056）。
_SPEC_RE = re.compile(r"\b((?:ISO/IEC|IEC|ISO|ABNT\s+NBR|EN|ITU-T)\s*[0-9]{3,5}(?:[-:][0-9]{1,4})*)", re.IGNORECASE)
# manifest.input 里的标准号常带全角冒号/年份，归一化
_YEAR_RE = re.compile(r"[:：]\s*\d{4}")


def _clean_norm(text: str) -> str:
    """归一化标准号：去全角冒号/年份、统一空格。EN 16314：2013 → EN 16314。"""
    text = _YEAR_RE.sub("", text)
    text = text.replace("：", ":").replace("  ", " ")
    return re.sub(r"\s+", " ", text).strip()


def infer_meter_type(out_dir: Path) -> str:
    """推断表计类型：gas / water / electric / multi。确定性，提取不到回退 multi。"""
    out_dir = Path(out_dir)
    manifest = _load_manifest(out_dir)
    filename = str(manifest.get("input") or "")
    lower_file = filename.lower()

    # 1) 文件名里的明确表种词（最高置信度）
    for meter_type, keywords in _METER_KEYWORDS.items():
        if any(kw in lower_file for kw in keywords):
            return meter_type

    # 2) 正文术语频次（取前 N 块文本，避免读全量）
    blocks = read_jsonl(out_dir / "blocks.jsonl")
    sample = " ".join(str(b.get("text") or "") for b in blocks[:300]).lower()
    scores = {
        meter_type: sum(sample.count(kw) for kw in keywords)
        for meter_type, keywords in _METER_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    # 显著占优（至少 2 次且不少于次名的 2 倍）才定，否则 multi（不乱猜）
    if scores[best] >= 2:
        runner_up = max(v for k, v in scores.items() if k != best)
        if scores[best] >= runner_up * 2:
            return best

    return "multi"


def infer_target_standards(out_dir: Path) -> list[str]:
    """从 manifest.input + 正文提取目标标准号。提取不到返回 []（让调用方决定默认）。"""
    out_dir = Path(out_dir)
    manifest = _load_manifest(out_dir)
    candidates: list[str] = []

    # 文件名里的标准号（通常最准）
    for match in _SPEC_RE.finditer(str(manifest.get("input") or "")):
        candidates.append(_clean_norm(match.group(1)))

    # 正文 Normative References 节里的标准号（补文件名没有的）
    if not candidates:
        blocks = read_jsonl(out_dir / "blocks.jsonl")
        for block in blocks[:400]:
            path = block.get("section_path") or []
            joined = " / ".join(str(p) for p in path).lower()
            if "normative reference" in joined or "bibliography" in joined:
                for match in _SPEC_RE.finditer(str(block.get("text") or "")):
                    norm = _clean_norm(match.group(1))
                    if norm not in candidates:
                        candidates.append(norm)

    # 去重（保序）。目标标准保留文档自身标准号（研发要知道本规格实现的是哪个标准），不做自引用剔除。
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result[:8]  # 最多 8 个，避免噪声


def infer_meter_profile(out_dir: Path) -> dict[str, Any]:
    """一次性推断 meter_type + target_standards。"""
    return {
        "meter_type": infer_meter_type(out_dir),
        "target_standards": infer_target_standards(out_dir),
    }


def _load_manifest(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir) / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
