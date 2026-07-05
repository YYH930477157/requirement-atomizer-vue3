import json
from typing import Any


def build_analysis_prompt(requirements: list[dict[str, Any]], vocabulary: dict[str, Any],
                          template_refs: str = "") -> dict[str, str]:
    system = "你是电表软件需求分析工程师。你的任务不是翻译原文，而是基于可追溯的抽取结果推导软件研发需求。"
    lines = [
        "请基于需求 JSON 和模板词表 JSON 输出 JSON 对象 {\"items\": [ ... ]}，items 与输入需求一一对应。",
        "ownership 只能是 `software`、`hardware`、`co_design`。",
        "hardware 需求只做简要说明。",
        "software 需求必须给出输入/触发、处理逻辑、输出/状态变化、验收建议。",
        "co_design 需求的软件侧必须详细说明，硬件依赖只做简要说明。",
        "不能只翻译原文；必须推导可研发、可验收的软件需求。",
        "不能修改数字、OBIS、DLMS class ID、阈值、时间、访问权限；只能引用原文已有的这些值，绝不新增。",
        "每个 item 的字段：",
        "  - source_requirement_ids: 原样回填输入需求的 ai_req_id（用于对齐）",
        "  - software_requirement_text: 软件需求正文（输入/触发→处理逻辑→输出/状态变化）",
        "  - developer_guidance: 研发落地要点数组（如涉及的对象/属性/时序）",
        "  - acceptance_criteria: 可测的验收标准数组",
        "  - hardware_dependency: 硬件依赖简述（software 类留空字符串）",
        "  - open_questions: 需澄清的问题数组（无则空数组）",
        "  - assumptions: 推导中不得不假设的、原文没有的前提数组——**一律记录在此，绝不无声编入正文**（无则空数组）",
        "  - ownership_reason: 归属判断的一句话理由",
        "模板词表 JSON:",
        json.dumps(vocabulary, ensure_ascii=False),
    ]
    if template_refs:
        lines += [
            "【公司标准做法参考——该模块的标准化需求样本，仅供对齐粒度/术语/通用做法】",
            template_refs,
            "参考使用规则：software_requirement_text 里的数值/编码只能来自客户需求原文，"
            "样本里的默认值绝不写入需求正文；样本\"说明\"里的通用做法/宏定义/选项枚举应吸收进 "
            "developer_guidance，并以「公司通用做法：」前缀标注；写法上模仿样本的粒度与术语。",
        ]
    lines += [
        "需求 JSON:",
        json.dumps(requirements, ensure_ascii=False),
    ]
    return {"system": system, "user": "\n".join(lines)}


def validate_llm_item(item: dict[str, Any], source: dict[str, Any]) -> list[str]:
    """LLM 分析产物防幻觉校验（方向与 ai_extract 双引擎护栏一致）。

    - 硬伤（编造）：分析文本里出现源文没有的受保护编码（OBIS/事件号/hex，原子匹配——
      换位 OBIS 也逃不掉）或数字。基线取 quote/description/requirement **并集**：
      任何源字段出现过的都算有据，防误伤。这是"OBIS 错一位即严重"纪律的主检查方向。
    - 软项（遗漏）：**优先源文**（quote 优先，其次 description/requirement，取首个非空）
      的数字在分析文本缺失——完整性提示，保留原有优先级语义（并集会把 fallback 字段
      的数字都变成噪声）。
    """
    from cosem_behavior_spec import extract_codes, extract_ints

    union_text = " ".join(
        str(source.get(field) or "") for field in ("source_quote", "description", "requirement")
    )
    priority_text = next(
        (str(source.get(field) or "") for field in ("source_quote", "description", "requirement")
         if str(source.get(field) or "").strip()),
        "",
    )
    analysis_text = " ".join(
        str(item.get(field, ""))
        for field in ("requirement", "software_requirement_text", "hardware_dependency", "ownership_reason")
    )

    issues = []
    for code in sorted(extract_codes(analysis_text) - extract_codes(union_text)):
        issues.append(f"fabricated code not in source: {code}")
    for number in sorted(extract_ints(analysis_text) - extract_ints(union_text)):
        issues.append(f"fabricated number not in source: {number}")
    for number in sorted(extract_ints(priority_text) - extract_ints(analysis_text)):
        issues.append(f"source number {number} missing from analysis text")
    return issues
