"""ai_extract 二遍语义复核子系统（M9 第 4 刀，2026-08-17）。

从 ``ai_extract.py`` 逐字搬运的语义复核（verify）簇：八类语义错误清单、复核
system prompt、双侧锚定采纳与三只纯 helper（``_anchored``/``_entry_produced_text``
/``_append_note``——最后者为全模块共享笔记 helper，原名重导出回 ai_extract）。
``ai_extract`` 原名重导出全部符号，调用面零变化。

选族纪律（M9 蓝图红线）：本簇不含任何测试 patch 目标（``out/m9-patch-targets.json``
ai_extract 25 个全部留守 ``ai_extract.py``，含 ``resolve_verify_enabled``/
``critique_section``）；依赖只有 extract_guards（``_norm_ws``）与 llm_client
（``LLMError``）——不反向依赖 ai_extract，无环。SYSTEM_PROMPT 留守：它拼接
MODULE_VOCAB/OTHER_MODULE（模块词表权威在 ai_extract）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from extract_guards import _norm_ws
from llm_client import LLMError

LOGGER = logging.getLogger("requirement_atomizer")
ChatFn = Callable[[str, str], dict[str, Any]]


def _append_note(req: dict[str, Any], note: str) -> None:
    req["notes"] = f"{req['notes']}；{note}" if req.get("notes") else note


# --- 二遍语义复核(0715:v6 审计残余差评全是语义理解错误,确定性护栏无法核验,
# prompt v18 针对性约束实证挡不住——独立对抗性核查视角是剩下的机制层手段) ----

_VERIFY_KINDS = {
    "exemption_reversal": "免责从句反转",
    "direction": "方向或上下限反转",
    "quantifier": "数量词范围改写",
    "subject": "主体或受试对象错置",
    "value_pairing": "数值条件配对",
    "step_ref": "步骤编号错位",
    "attribution": "条款或标准归属",
    "obligation_framing": "产品义务主体缺失",
}

VERIFY_SYSTEM_PROMPT = (
    "你是需求抽取的语义复核员。对照【章节原文】逐条核查【已抽需求】,只查八类语义错误:"
    "① 免责/例外从句方向(unless/without/except/provided that——豁免条件被写成禁止项或独立义务,"
    "如\"不得漂移超限——除非显示错误标志\"被写成\"不得显示错误标志\");"
    "② 范围/方向(\"at least X to Y\"的覆盖语义:声明范围须覆盖[X,Y]即下限≤X 且上限≥Y;"
    "不小于/不大于、上下限方向);"
    "③ 数量词(one or more/any/all/each 与产出的\"全部/任一/至少\"是否对应,"
    "\"one or more of the following\"写成\"全部必备\"是典型错误);"
    "④ 主体/受试对象错置(原文约束甲对象,产出写成乙对象);"
    "⑤ 数值与适用条件配对(型号/压力/温度档张冠李戴:甲条件配了乙限值);"
    "⑥ 步骤编号引用(产出引用\"步骤 n\"时与原文该步骤内容是否对应,比较基准错位会误判合格品);"
    "⑦ 条款/标准号归属(产出引用的编号是否确属原文所述标准/条款);"
    "⑧ 产品义务主体缺失(原文是产品应提供的可配置/可选择能力，产出却只写角色“可以做什么”，"
    "没有写产品应支持或允许该能力；同时核对角色和具体对象是否保留)。"
    "**只报实错**:每个发现必须同时给出原文逐字片段(evidence_source,从章节原文原样复制)"
    "与产出逐字片段(evidence_produced,从该需求文本原样复制),两者对照能直接看出矛盾;"
    "吃不准/需要推测的不报;纯表述风格、翻译措辞、粒度、遗漏问题都不报；产品规范义务主体缺失"
    "属于上述第八类语义错误，不按风格问题忽略。"
    "每条已抽需求都带 verify_slot。发现必须原样回填对应 verify_slot；title 仅作辅助核对。"
    "correction 可选:给出把 evidence_produced 改正后的最小建议文本——只改错的部分,"
    "不新增原文没有的内容,数值/编码只准来自原文；系统只留痕建议,不会自动改写需求。"
    "只输出 JSON:{\"findings\": [{\"verify_slot\": 1, \"title\": \"<该需求 title 原样回填>\", \"kind\": "
    "\"exemption_reversal|direction|quantifier|subject|value_pairing|step_ref|attribution|obligation_framing\", "
    "\"evidence_source\": \"…\", \"evidence_produced\": \"…\", \"correction\": \"<可选>\"}]}"
    "。无发现输出 {\"findings\": []}。"
)


def _anchored(fragment: str, hay: str, min_len: int = 8) -> bool:
    """全剥空白后的包含式锚定(证据片段必须逐字可定位;短于 min_len 不算证据)。

    剥空白而非归并:CJK 产出无空格,模型复制证据时插入的空格不该导致锚定失败。"""
    frag = re.sub(r"\s+", "", str(fragment or ""))
    return len(frag) >= min_len and frag.casefold() in re.sub(r"\s+", "", str(hay or "")).casefold()


def _entry_produced_text(req: dict[str, Any]) -> str:
    return " ".join([str(req.get("title") or ""), str(req.get("description") or "")]
                    + [str(s.get("text") or "") for s in req.get("sub_items") or []]
                    + [str(s.get("text") or "") for s in req.get("compliance_obligations") or []]
                    + [str(x) for x in req.get("acceptance_criteria") or []])


def _verify_section(section: dict[str, Any], results: list[dict[str, Any]], chat: ChatFn,
                    rounds: int = 1) -> int:
    """对本章节最终条目做 N 轮语义复核投票,并集采纳双侧锚定的发现。返回采纳数。

    多轮取并集:单轮对细微语义错误命中率实测 ~1/3(模型判断随机性),并集是
    机制性提召回;锚定门不随轮数放宽(精度不掉)。同(slot,kind)跨轮去重,
    发现全部收集完再统一采纳(轮间无顺序效应)。
    契约:复核**绝不新增或自动改写**需求内容;锚定成立 → 软标+双证据留痕;
    correction 只作为模型复核建议记录,由人工裁决。"""
    if not results:
        return 0
    entries = []
    for i, r in enumerate(results, 1):
        subs = "; ".join(str(s.get("text") or "") for s in r.get("sub_items") or [])[:400]
        acc = "; ".join(str(x) for x in r.get("acceptance_criteria") or [])[:600]
        entries.append(
            f"[{i}] verify_slot: {i}\ntitle: {r.get('title', '')}\n描述: {str(r.get('description') or '')[:800]}"
            + (f"\n子项: {subs}" if subs else "")
            + (f"\n验收: {acc}" if acc else "")
            + f"\n引句: {str(r.get('source_quote') or '')[:300]}")
    user = ("【章节原文】\n" + str(section.get("text") or "")
            + "\n\n【已抽需求】\n" + "\n\n".join(entries))
    by_slot = {i: r for i, r in enumerate(results, 1)}
    slots_by_title: dict[str, list[int]] = {}
    for slot, req in by_slot.items():
        title_key = _norm_ws(req.get("title"))
        if title_key:
            slots_by_title.setdefault(title_key, []).append(slot)
    # 收集期:N 轮调用,锚定过滤,(slot,kind) 去重——首个锚定证据胜出
    accepted: dict[tuple[int, str], dict[str, str]] = {}
    for round_no in range(max(1, rounds)):
        try:
            payload = chat(VERIFY_SYSTEM_PROMPT, user)
        except LLMError as exc:  # 单轮失败不吞掉其他轮(首轮失败仍尝试后续轮)
            LOGGER.warning("二遍复核第 %d 轮失败：%s", round_no + 1, exc)
            continue
        findings = payload.get("findings") if isinstance(payload, dict) else None
        if not isinstance(findings, list):
            continue
        for f in findings:
            if not isinstance(f, dict):
                continue
            title_key = _norm_ws(f.get("title"))
            try:
                slot = int(f.get("verify_slot"))
            except (TypeError, ValueError):
                slot = 0
            req = by_slot.get(slot)
            if req is None:
                title_slots = slots_by_title.get(title_key) or []
                if len(title_slots) == 1:
                    slot = title_slots[0]
                    req = by_slot[slot]
            kind = _VERIFY_KINDS.get(str(f.get("kind") or "").strip())
            src_ev = str(f.get("evidence_source") or "").strip()
            prod_ev = str(f.get("evidence_produced") or "").strip()
            if req is None or kind is None or (slot, kind) in accepted:
                continue
            # 双侧锚定:原文侧在章节原文、产出侧在该条目文本,都逐字可定位才算证据
            if not _anchored(src_ev, section.get("text", "")) or not _anchored(prod_ev, _entry_produced_text(req)):
                LOGGER.info("二遍复核发现无锚定证据,丢弃：%s(%s)", str(f.get("title") or "")[:30], kind)
                continue
            accepted[(slot, kind)] = {"src": src_ev, "prod": prod_ev,
                                      "corr": str(f.get("correction") or "").strip()}
    # 采纳期:统一挂标、留证据与建议,不改写自然语言需求
    applied = 0
    for (slot, kind), ev in accepted.items():
        req = by_slot[slot]
        req["suspicion_reasons"] = list(dict.fromkeys(
            list(req.get("suspicion_reasons") or []) + [f"二遍复核:{kind}"]))
        _append_note(req, f"二遍复核（{kind}）：原文「{ev['src'][:80]}」vs 产出「{ev['prod'][:80]}」")
        applied += 1
        corr, prod_ev = ev["corr"], ev["prod"]
        if corr and corr != prod_ev:
            _append_note(req, f"复核建议（未自动改写）：{corr[:160]}")
    return applied
