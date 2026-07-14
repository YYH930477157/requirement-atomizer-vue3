import json
from typing import Any


def slim_vocabulary(vocabulary: dict[str, Any], module: str) -> dict[str, Any]:
    """全量词表 → 本模块视图（W1-4，2026-07-12）：旧行为把所有模块的 submodule 全量 JSON
    逐条重复注入（~500-2000 tok/条），但内容只是分类名、零知识含量。瘦身为
    {本模块, 本模块 submodules, 全部模块名}——够模型做模块一致性核对即可。"""
    modules = [str(m) for m in vocabulary.get("modules") or []]
    submap = vocabulary.get("submodules_by_module") or {}
    submodules = [str(s) for s in (submap.get(module) or [])] if isinstance(submap, dict) else []
    return {"module": module, "submodules": submodules, "modules": modules}


def build_analysis_prompt(requirements: list[dict[str, Any]], vocabulary: dict[str, Any],
                          template_refs: str = "", *, exemplars: str = "",
                          answers: str = "", doc_context: str = "",
                          section_context: str = "", siblings: str = "") -> dict[str, str]:
    system = "你是电表软件需求分析工程师。你的任务不是翻译原文，而是基于可追溯的抽取结果推导软件研发需求。"
    lines: list[str] = []
    if doc_context:
        lines += [doc_context,
                  "（以上文档背景仅供术语与模块一致性参考，勿据此编造原文没有的编码/数字。）"]
    if section_context:
        lines += ["【所在条款原文——客户文档内容，引用其中的数值/编码视为有据】",
                  section_context]
    if siblings:
        lines += ["【同模块相邻需求标题——仅供避免重复/保持粒度一致，不得从中引用编码或数值】",
                  siblings]
    lines += [
        "请基于需求 JSON 和模板词表 JSON 输出 JSON 对象 {\"items\": [ ... ]}，items 与输入需求一一对应。",
        "ownership 只能是 `software`、`hardware`、`co_design`。",
        "hardware 需求只做简要说明。",
        "co_design 需求的软件侧必须详细说明，硬件依赖只做简要说明。",
        "不能只翻译原文；必须推导可研发、可验收的软件需求。",
        "不能修改数字、OBIS、DLMS class ID、阈值、时间、访问权限；只能引用原文已有的这些值，绝不新增。",
        "每个 item 的字段：",
        "  - source_requirement_ids: 原样回填输入需求的 ai_req_id（用于对齐）",
        "  - software_requirement_text: 软件需求正文——**连贯的自然段成文（2-4 段）**，依次覆盖："
        "输入/触发条件 → 处理逻辑（关键步骤、状态变化、数据流）→ 输出/状态变化 → 边界条件与异常处理"
        "（掉电、并发、越界、时序等落到具体场景）。禁止只写一句话或短语碎片罗列；术语采用上方对照表的统一译法。",
        "  - developer_guidance: 研发落地要点数组——每条**具体可执行**（点名涉及的对象/属性/接口/时序/存储布局），"
        "由原文/客户答复直接支持；公司标准做法可吸收但须以「公司通用做法：」前缀标注",
        "  - design_options: 原文未指定但可供研发选型的实现候选数组（队列/缓存/接口分层等）——"
        "每条附一句取舍理由（为什么选/什么场景不选）；不得带无依据容量或默认值",
        "  - acceptance_criteria: 可测的验收标准数组——每条给出操作步骤+预期结果；"
        "数值只能来自原文/所在条款原文/客户答复",
        "  - hardware_dependency: 硬件依赖简述（software 类留空字符串）",
        "  - open_questions: 需澄清的问题数组（无则空数组）",
        "  - assumptions: 推导中不得不假设的、原文没有的前提数组——**一律记录在此，绝不无声编入正文**（无则空数组）",
        "  - ownership_reason: 归属判断的一句话理由（引用原文关键词/依据）",
        "模板词表 JSON:",
        json.dumps(vocabulary, ensure_ascii=False),
    ]
    if exemplars:
        lines += [
            "【专家已验收的同模块范例——粒度/写法基准，内容不得搬运进本需求】",
            exemplars,
        ]
    if answers:
        lines += [
            "【客户澄清答复——权威输入：其中的数值/结论视为有据，应吸收进软件需求正文】",
            answers,
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


def validate_llm_item(item: dict[str, Any], source: dict[str, Any],
                      template_text: str = "", *, section_context: str = "",
                      context_text: str = "") -> list[str]:
    """LLM 分析产物防幻觉校验（方向与 ai_extract 双引擎护栏一致）。

    - 硬伤（编造）：分析文本里出现源文没有的受保护编码（OBIS/事件号/hex，原子匹配——
      换位 OBIS 也逃不掉）或数字。基线取 quote/description/requirement **并集**：
      任何源字段出现过的都算有据，防误伤。这是"OBIS 错一位即严重"纪律的主检查方向。
    - 软项（遗漏）：**优先源文**（quote 优先，其次 description/requirement，取首个非空）
      的数字在分析文本缺失——完整性提示，保留原有优先级语义（并集会把 fallback 字段
      的数字都变成噪声）。

    基线口径（W1-3，2026-07-12）：
    - section_context = 注入 prompt 的"所在条款原文"（≤帽值的那个字符串,逐字同源）——
      条款原文是客户文档内容,进编造基线是**有据范围补全**不是放宽;只收注入串,不收整章。
    - context_text = doc_context+siblings 合并串——其中的**普通整数**从软标里豁免
      （镜像 ai_extract 的 context_ints 先例:引用背景里的标准号是合理行为）;
      **受保护编码不豁免**——背景里的 OBIS 出现在正文仍整条硬拒。
    - 遗漏检测分母 priority_text **永不扩**（防稀释:遗漏语义=本条自身数字是否进正文）。
    - exemplars/模板默认值维持永不进 analysis_text 基线（防搬运）。
    """
    from cosem_behavior_spec import extract_codes, extract_ints

    union_text = " ".join(
        str(source.get(field) or "")
        for field in ("source_quote", "description", "requirement", "clarification_answers_text")
    ) + " " + (section_context or "")   # 澄清答复/条款原文=客户内容，其中数值视为有据
    priority_text = next(
        (str(source.get(field) or "") for field in ("source_quote", "description", "requirement")
         if str(source.get(field) or "").strip()),
        "",
    )
    context_ints = extract_ints(context_text) if context_text else set()
    analysis_text = " ".join(
        str(item.get(field, ""))
        for field in ("requirement", "software_requirement_text", "hardware_dependency", "ownership_reason")
    )
    # 交付列表字段（研发直接阅读执行）此前完全在校验盲区——编造 OBIS 可无检测落进
    # 成文 xlsx「说明示例」列（2026-07-08 审计）。guidance 按设计允许公司模板做法，
    # 所以其编码/数字基线是 源文 ∪ 模板注入；正文 analysis_text 基线仍不含模板（防搬运）。
    # open_questions 同为 LLM 可写、直达交付「待确认」列（2026-07-11 评审补漏），纳入扫描。
    delivery_text = " ".join(
        " ".join(str(x) for x in (item.get(field) or []) if str(x).strip())
        for field in ("developer_guidance", "design_options", "acceptance_criteria",
                      "assumptions", "open_questions")
    )
    guidance_basis = f"{union_text} {template_text or ''}"

    issues = []
    for code in sorted(extract_codes(analysis_text) - extract_codes(union_text)):
        issues.append(f"fabricated code not in source: {code}")
    for number in sorted(extract_ints(analysis_text) - extract_ints(union_text) - context_ints):
        issues.append(f"fabricated number not in source: {number}")
    for code in sorted(extract_codes(delivery_text) - extract_codes(guidance_basis)):
        issues.append(f"fabricated code not in source: {code} (guidance)")
    for number in sorted(extract_ints(delivery_text) - extract_ints(guidance_basis) - context_ints):
        issues.append(f"fabricated number in guidance: {number}")
    # 遗漏分母的格式归一（2026-07-14,test18 实测 25 条警告几乎全是条款号/列表标号拆散的
    # 小整数——真参数值遗漏被淹没）:剥除枚举标号与引用性编号(条款/附录/图表引用是"地址"
    # 不是"数值")。这与"分母永不扩"防稀释纪律不冲突:不引入外部文本,只剥排版/引用数字。
    from text_normalize import join_digit_groups, strip_enum_markers, strip_reference_numbers
    missing_basis = join_digit_groups(strip_reference_numbers(strip_enum_markers(priority_text)))
    for number in sorted(extract_ints(missing_basis) - extract_ints(join_digit_groups(analysis_text))):
        issues.append(f"source number {number} missing from analysis text")
    return issues
