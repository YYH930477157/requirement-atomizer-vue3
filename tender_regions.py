"""招标文件区域识别（A9-2）。

默认关闭；开启后扩展 doc_region 标记：
- tender_preface：前言/scope/总体说明
- tender_instructions：投标须知/资格/评审办法等程序性章节 → non_product_reference
- tender_technical：技术规范/Statement of Requirements → body（正常走 B 轨）
- tender_commercial：商务附件/价格/合同条款 → non_product_reference

non_product_reference 区域不被 include_regions={"body"} 消费，因此不进功能需求候选；
同时被 unextracted_registry 登记为参考类条目，汇入澄清报告供专家核对。
"""
from __future__ import annotations

import os
import re
from typing import Any

TENDER_REGION_FILTER_VERSION = "tender-region-filter-v2"

# --- 程序性章节词表（non_product_reference）-------------------------------------
# A-1 收窄（2026-08-07）：qualification/evaluation/assessment/scoring 这类泛词在
# 技术标准里同时存在程序义（投标人资格/评标）与技术义（设备 Qualification tests /
# 性能 Evaluation）。单词级匹配会把 "Qualification Tests" 这类技术章节整章踢出
# 功能需求候选（A9-2 召回事故）。故泛词收窄为短语/标题级匹配——裸泛词不得单独命中，
# 只保留明确的程序性短语（完整标题形态）。
_INSTRUCTIONS_RE = re.compile(
    r"\b(?:instructions?\s+to\s+bidders?|bidding\s+instructions?|instructions?\s+for\s+tender|"
    r"tender\s+instructions?|bid\s+submission|submission\s+of\s+tender|"
    r"qualification\s+(?:requirements?|conditions?|criteria|of\s+(?:the\s+)?(?:bidder|tenderer|contractor|supplier|manufacturer))|"
    r"qualifying\s+(?:conditions?|requirements?|criteria|bidder)|"
    r"pre\s*qualification|prequalification|"
    r"eligibility\s+(?:criteria|requirements?|of\s+(?:bidder|tenderer))|eligible\s+bidder|"
    r"evaluation\s+(?:criteria|methodology|method|process|procedure|committee|report|matrix|sheet)|"
    r"evaluation\s+of\s+(?:bid|bids|tender|tenders|proposal|proposals|offer|offers)|"
    r"(?:bid|tender)\s+evaluation|evaluation\s+and\s+award|"
    r"assessment\s+(?:criteria|methodology|matrix|sheet)|"
    r"assessment\s+of\s+(?:bid|bids|tender|proposal|proposals|offer|bidder|tenderer)|"
    r"(?:bid|tender)\s+assessment|"
    r"scoring\s+(?:criteria|sheet|matrix|methodology|method)|"
    r"award\s+criteria|selection\s+criteria|"
    r"general\s+conditions|conditions\s+of\s+tender|tender\s+conditions|"
    r"contract\s+conditions|terms\s+and\s+conditions|commercial\s+terms|"
    r"price\s+schedule|bill\s+of\s+quantities|boq|form\s+of\s+tender|tender\s+form|"
    r"bid\s+form|declaration|signatory|bank\s+guarantee|performance\s+bond|"
    r"tender\s+validity|validity\s+period|closing\s+date|opening\s+of\s+tender|"
    r"bid\s+opening|opening\s+of\s+(?:the\s+)?bids?|"
    r"tax\s+clearance|bid\s+security|bid\s+bond|"
    r"submission\s+deadline|procurement|purchasing|vendor\s+registration)"
    r"|^(?:投标须知|投标人须知|资格要求|评审办法|评标办法|合同条款|商务条款|"
    r"价格表|报价表|投标函|法定代表人|授权书|银行保函|履约保函|开标|评标|定标|"
    r"采购公告|招标公告|资格预审)",
    re.IGNORECASE,
)

# --- 技术规范章节词表（body，正常抽取）-----------------------------------------
# A-1：显式收录测试/验收类技术章节（qualification tests / type tests / acceptance
# test 等），确保设备验收章节优先判为 technical → body，即便 instructions 词表也匹配。
_TECHNICAL_RE = re.compile(
    r"\b(?:technical\s+specification|statement\s+of\s+requirements?|scope\s+of\s+work|"
    r"technical\s+requirements?|functional\s+requirements?|specification\s+of\s+supply|"
    r"supply\s+and\s+delivery|scope\s+of\s+supply|equipment\s+specification|"
    r"system\s+requirements?|performance\s+requirements?|technical\s+data|"
    r"service\s+specification|work\s+specification|"
    r"qualification\s+tests?|type\s+tests?|routine\s+tests?|acceptance\s+tests?|"
    r"witness\s+tests?|factory\s+acceptance|site\s+acceptance|"
    r"tests?\s+(?:procedures?|methods?|requirements?|conditions?|plans?|specifications?)|"
    r"testing\s+(?:requirements?|procedures?|methods?|specifications?))"
    r"|^(?:技术规范|技术规格|技术参数|技术要求|功能要求|供货范围|供货清单|"
    r"设备规格|系统要求|性能要求|技术数据|服务要求|工作范围|"
    r"型式试验|出厂试验|例行试验|验收试验|测试方法|试验方法)",
    re.IGNORECASE,
)

# --- 前言/总体说明词表（non_product_reference 参考类）---------------------------
_PREFACE_RE = re.compile(
    r"\b(?:preface|foreword|introduction|overview|general\s+information|"
    r"background|purpose|objective|intent|scope\s+of\s+document|document\s+scope)"
    r"|^(?:前言|序言|引言|简介|概述|总则|总说明|背景|目的|范围)"
    r"|^\s*1\.\s*(?:introduction|overview|scope|general)\s*$",
    re.IGNORECASE,
)

# --- 商务附件词表（non_product_reference）---------------------------------------
_COMMERCIAL_RE = re.compile(
    r"\b(?:commercial\s+schedule|commercial\s+proposal|price\s+schedule|"
    r"pricing\s+schedule|annexure\s+[a-z]\s*[-:]\s*commercial|"
    r"schedule\s+of\s+prices|bill\s+of\s+quantities|contract\s+data|"
    r"agreement|form\s+of\s+agreement|appendix\s+\w+\s+commercial)"
    r"|^(?:商务附件|商务部分|价格部分|报价部分|合同数据|协议|附录.*商务)",
    re.IGNORECASE,
)


def tender_region_filter_enabled() -> bool:
    """A9-2 开关：默认关闭。"""
    value = os.environ.get("RATOMIZER_TENDER_REGION_FILTER", "0").strip().lower()
    return value not in {"0", "false", "off", ""}


def _normalize_title(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text or "").lower()).strip()


def classify_tender_region(block: dict[str, Any]) -> str | None:
    """对单个 heading 块判定 tender 区域类型；非 heading 返回 None。

    仅当块类型为 heading 且命中 tender 词表时返回：
    - "tender_preface"
    - "tender_instructions"
    - "tender_technical"
    - "tender_commercial"
    """
    if str(block.get("type") or "") != "heading":
        return None
    text = _normalize_title(str(block.get("text") or ""))
    if not text:
        return None
    if _TECHNICAL_RE.search(text):
        return "tender_technical"
    if _INSTRUCTIONS_RE.search(text):
        return "tender_instructions"
    if _COMMERCIAL_RE.search(text):
        return "tender_commercial"
    if _PREFACE_RE.search(text):
        return "tender_preface"
    return None


def tender_region_to_doc_region(tender_region: str) -> str:
    """tender 区域 → doc_region。

    技术规范正常走 body；其余归为 non_product_reference（参考类，不进功能需求）。
    """
    if tender_region == "tender_technical":
        return "body"
    return "non_product_reference"


def apply_tender_regions(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """对 blocks 列表应用 tender 区域识别，直接修改 doc_region 字段。

    返回摘要：{version, region_counts}。
    """
    counts: dict[str, int] = {}
    for block in blocks:
        tender_region = classify_tender_region(block)
        if tender_region is None:
            continue
        doc_region = tender_region_to_doc_region(tender_region)
        block["doc_region"] = doc_region
        block["tender_region"] = tender_region
        counts[tender_region] = counts.get(tender_region, 0) + 1
    return {
        "version": TENDER_REGION_FILTER_VERSION,
        "region_counts": counts,
    }
