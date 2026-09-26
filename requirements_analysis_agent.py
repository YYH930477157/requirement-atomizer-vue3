import json
import re
from typing import Any


def _as_list(value: Any) -> list[Any]:
    """列表字段载荷归一（防幻觉红线修复 2026-08-15）：LLM 偶发把列表字段写成纯 str
    （如 design_options="方案引用 G-SGX-EY 事件对象"），而 _first_item 不做 schema
    校验——直接迭代 str 会逐字符拆散，受保护编码（OBIS/事件号/hex）被空格打碎后
    extract_codes 永不命中，编造码零检测直达交付/澄清通道。任何把列表字段渲染成
    文本做编码检测/采纳的路径都必须先过这里：None→[]；list 原样；tuple→list
    （JSON 载荷无 tuple，防御性接纳——与 requirements_analysis._as_list 同口径，
    两处实现必须保持一致）；其它标量（含 str）→ 单元素列表，使 str 载荷与等价
    list 载荷行为逐字节一致。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


# 遗漏校验只针对需求参数，不把条目/位置标识当成必须在正文重复的业务数值。
# 例如 ``task 0``、``AI-REQ-0012``、``block-7`` 是抽取对齐信息；若把它们算入
# 分母，会把正常的中文改写误报成数字遗漏。条款、表格、章节引用由
# text_normalize.strip_reference_numbers 另行处理。
_IDENTIFIER_NUMBER = re.compile(
    r"(?ix)\b(?:task|item|req(?:uirement)?|ai(?:_?req)?|block|record|row|column)"
    r"\s*[-_:#]?\s*\d+\b"
    r"|\b[A-Za-z][A-Za-z0-9_]*[-_]\d+\b"
)


def _requirement_parameter_numbers(text: object) -> set[int]:
    """Return numbers that are candidates for source-to-body completeness checks.

    The broad ``extract_ints`` scanner remains the authority for fabricated-number
    detection.  This narrower helper is only for the reverse direction ("did the
    generated body omit a source number?") where identifier numbers are not
    semantic parameters and should not make a valid paraphrase fail closed.
    """
    from text_normalize import join_digit_groups, strip_enum_markers, strip_reference_numbers
    from cosem_behavior_spec import extract_ints

    cleaned = _IDENTIFIER_NUMBER.sub(" ", str(text or ""))
    cleaned = join_digit_groups(strip_reference_numbers(strip_enum_markers(cleaned)))
    return extract_ints(cleaned)


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
                          negative_exemplars: str = "",
                          answers: str = "", doc_context: str = "",
                          section_context: str = "", siblings: str = "",
                          per_item_fields: bool = False) -> dict[str, str]:
    system = "你是电表软件需求分析工程师。你的任务是基于可追溯的抽取结果做证据保真富化，不是自由设计方案。"
    # 前缀缓存友好排序（0714 批次二 S6）：按稳定性降序——固定指令（全局同一）→ 文档背景
    # （全文档同一）→ 词表/范例/相邻标题（模块级）→ 答复/模板参考/条款原文（条级）→ 需求 JSON。
    # 此前条级内容排最前,服务端 KV 前缀缓存每次调用全 miss;语义内容一字不改,只动顺序。
    lines: list[str] = [
        "请基于需求 JSON 和模板词表 JSON 输出 JSON 对象 {\"items\": [ ... ]}，items 与输入需求一一对应。",
    ]
    if per_item_fields:
        # 合批模式（0714 批次一 S1）：条级上下文随条嵌进需求 JSON——护栏语义与单条完全一致,
        # 尤其"只能用于本条"是防跨条借数的关键指令（validate 仍逐条按本条基线硬拒/软标）
        lines += [
            "本次输入为同模块多条需求（合批）。每条需求 JSON 可能带以下随行字段：",
            "  - enrich_slot: 批内序号——每个输出 item 必须原样回填对应输入的 enrich_slot；",
            "  - section_context: 该需求所在条款原文（客户文档内容，引用其中数值/编码视为有据）"
            "——**只能用于本条，绝不跨条借用其它需求的条款原文**；",
            "  - template_refs: 该条的公司标准做法参考——数值/编码只准来自客户原文，"
            "样本默认值绝不写入需求正文；通用做法进 developer_guidance 并以「公司通用做法：」前缀标注；",
            "  - clarification_answers_text: 该条的客户澄清答复（权威输入，其中数值/结论视为有据，应吸收进正文）。",
        ]
    lines += [
        "每条需求 JSON 的 ownership 字段（software/hardware/co_design）已由规则与专家裁决**冻结**——"
        "原样回填、绝不改判；你的任务是按给定归属写出深度匹配的正文，不是重新判定归属。",
        "hardware 需求只做简要说明。",
        "co_design 需求的软件侧必须详细说明，硬件依赖只做简要说明。",
        "本步骤是证据保真富化，不是方案设计。优先忠实改写/翻译客户原文，"
        "不得为了看起来完整而补写工程常识。",
        "所有富化字段都必须逐条受客户原文证据约束。可以重排和改写原文已明确的处理步骤，但不得自行补充"
        "原文没有明确支持的状态、事件、日志、接口、存储、超时、容量、默认值或异常行为；"
        "无法从本条证据推出的内容只能放入 assumptions/open_questions，不能写进正文、研发指引或验收标准。",
        "不能修改数字、OBIS、DLMS class ID、阈值、时间、访问权限；只能引用原文已有的这些值，绝不新增。",
        "每个 item 的字段：",
        "  - source_requirement_ids: 原样回填输入需求的 ai_req_id（用于对齐）",
        "  - software_requirement_text: 软件需求正文——用 1-2 段忠实表达本条客户要求，"
        "只保留原文明确的对象、动作、条件、参数和结果；不要自行补写状态机、接口、日志、存储、"
        "超时、容量、默认值、并发、掉电或异常处理。若原文没有这些内容，不要为了凑完整度添加。",
        "  - developer_guidance: 研发落地要点数组——仅记录原文明确要求或客户答复明确给出的实现约束；"
        "没有直接依据时输出空数组。公司标准做法只能以「公司通用做法：」前缀标注，不能当成本条要求。",
        "  - design_options: 本阶段始终输出空数组；设计选项由后续专家/架构阶段单独处理。",
        "  - acceptance_criteria: 本阶段始终输出空数组；验收标准由后续专家/测试阶段单独处理。",
        "  - hardware_dependency: 硬件依赖简述（software 类留空字符串）",
        "  - open_questions: 需澄清的问题数组（无则空数组）",
        "  - assumptions: 推导中不得不假设的、原文没有的前提数组——**一律记录在此，绝不无声编入正文**（无则空数组）",
        "  - ownership_reason: 解释**给定归属**为何成立的一句话理由（引用原文关键词/依据）——"
        "不是重新判定；若你认为给定归属可疑，把疑问写进 open_questions，不要改 ownership",
    ]
    if doc_context:
        lines += [doc_context,
                  "（以上文档背景仅供术语与模块一致性参考，勿据此编造原文没有的编码/数字。）"]
    lines += [
        "模板词表 JSON:",
        json.dumps(vocabulary, ensure_ascii=False),
    ]
    if exemplars:
        lines += [
            "【专家已验收的同模块范例——粒度/写法基准，内容不得搬运进本需求】",
            exemplars,
        ]
    if negative_exemplars:
        lines += [
            "【专家已拒绝的同模块范例——请勿重复同类问题】",
            negative_exemplars,
        ]
    if siblings:
        lines += ["【同模块相邻需求标题——仅供避免重复/保持粒度一致，不得从中引用编码或数值】",
                  siblings]
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
    if section_context:
        lines += ["【所在条款原文——客户文档内容，引用其中的数值/编码视为有据】",
                  section_context]
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
    # 文档级背景只用于术语/模块一致性，不能成为本条需求数字的证据。
    # 条款级证据已经在 union_text（section_context）中按本条绑定注入；把整篇
    # doc_context 的数字放进豁免集合会让模型借用其它章节的参数。
    # 仅保留标准标识中的数字（EN/IEC/ISO 等），不把背景章节的参数值当证据。
    standard_context = " ".join(re.findall(
        r"(?i)(?:EN|IEC|ISO|DLMS)\s*[-:]?\s*\d+(?:[.\-]\d+)*", context_text or ""))
    context_ints = extract_ints(standard_context) if standard_context else set()
    analysis_text = " ".join(
        str(item.get(field, ""))
        for field in ("requirement", "software_requirement_text", "hardware_dependency", "ownership_reason")
    )
    # 交付列表字段（研发直接阅读执行）此前完全在校验盲区——编造 OBIS 可无检测落进
    # 成文 xlsx「说明示例」列（2026-07-08 审计）。guidance 按设计允许公司模板做法，
    # 所以其编码/数字基线是 源文 ∪ 模板注入；正文 analysis_text 基线仍不含模板（防搬运）。
    # open_questions 同为 LLM 可写、直达交付「待确认」列（2026-07-11 评审补漏），纳入扫描。
    # 载荷先 _as_list 归一（2026-08-15 P1）：模型把列表字段写成纯 str 时逐字符迭代会
    # 把编码空格打碎（extract_codes 永不命中）——str 载荷必须与等价 list 载荷同判。
    delivery_text = " ".join(
        " ".join(str(x) for x in _as_list(item.get(field)) if str(x).strip())
        for field in ("developer_guidance", "design_options", "acceptance_criteria",
                      "assumptions", "open_questions")
    )
    guidance_basis = f"{union_text} {template_text or ''}"

    issues = []
    for code in sorted(extract_codes(analysis_text) - extract_codes(union_text)):
        issues.append(f"fabricated code not in source: {code}")
    for number in sorted(extract_ints(analysis_text) - extract_ints(union_text) - context_ints):
        issues.append(f"fabricated number not in source: {number}")
    union_codes = extract_codes(union_text)
    template_codes = extract_codes(template_text or "")
    for code in sorted(extract_codes(delivery_text) - union_codes - template_codes):
        issues.append(f"fabricated code not in source: {code} (guidance)")
    # 收紧（0714 批次二 E4）：guidance 的受保护编码此前以"源文∪模板"为基线**无声放行**——
    # 模板里的 OBIS 可被搬进源文没有该码的需求指引,研发照错码实现无从察觉。改软标随行
    # （不硬拒:公司通用做法的宏/码本就允许进指引,但必须可见可核）;正文侧基线不变仍硬拒。
    for code in sorted((extract_codes(delivery_text) & template_codes) - union_codes):
        issues.append(f"template-sourced code in guidance: {code}（公司模板来源，请核对适用性）")
    for number in sorted(extract_ints(delivery_text) - extract_ints(guidance_basis) - context_ints):
        issues.append(f"fabricated number in guidance: {number}")
    # 遗漏分母的格式归一（2026-07-14,test18 实测 25 条警告几乎全是条款号/列表标号拆散的
    # 小整数——真参数值遗漏被淹没）:剥除枚举标号与引用性编号(条款/附录/图表引用是"地址"
    # 不是"数值")。这与"分母永不扩"防稀释纪律不冲突:不引入外部文本,只剥排版/引用数字。
    missing_basis = priority_text
    # 空洞确认语/短片段不是可交付的软件需求正文，必须走既有降级/待澄清通道。
    text = str(item.get("software_requirement_text") or "").strip()
    if text in {"好的", "收到", "明白", "可以", "ok", "OK", "N/A", "无"} or len(text) <= 2:
        issues.append("software requirement text is empty or non-substantive")
    # 遗漏检查只看 LLM 生成的软件正文。item["requirement"] 是确定性原始基底，
    # 若把它并入分母，模型即使完全漏掉源文数字也会因为基底仍含该数字而不报警。
    generated_software_text = str(item.get("software_requirement_text") or "")
    for number in sorted(_requirement_parameter_numbers(missing_basis)
                         - _requirement_parameter_numbers(generated_software_text)):
        issues.append(f"source number {number} missing from analysis text")
    return issues
