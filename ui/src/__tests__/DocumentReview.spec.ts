import { describe, it, expect, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import DocumentReview from "../DocumentReview.vue"

function makeClient(over: Record<string, unknown> = {}) {
  return {
    loadDocument: vi.fn().mockResolvedValue({
      count: 3,
      blocks: [
        { block_id: "B1", order: 1, type: "heading", text: "4 Requirements",
          section_path: ["4 Requirements"], requirement_like: false, noise: false },
        { block_id: "B2", order: 2, type: "paragraph", text: "The meter shall measure volume.",
          section_path: ["4 Requirements"], requirement_like: true, noise: false },
        { block_id: "B3", order: 3, type: "paragraph", text: "An uncovered requirement shall hold.",
          section_path: ["4 Requirements"], requirement_like: true, noise: false },
      ],
    }),
    loadAiRequirements: vi.fn().mockResolvedValue([
      {
        ai_req_id: "AIR-1", title: "体积计量", description: "应计量体积", module: "计量",
        module_effective: "计量", type: "functional", priority: "P1", status: "draft",
        source_section: "4", source_quote: "The meter shall measure volume.",
        source_block_ids: ["B2"], acceptance_criteria: ["按 4.2 测试"],
        dev_guidance: ["实现体积累计计量与本地存储"], labels: ["计量"],
        suspicion_reasons: ["数字漂移"], ownership: "software", ownership_effective: "software",
        consistency_flags: ["跨章重复×2"],
        review_state: null,
      },
    ]),
    applyAiReviewAction: vi.fn().mockResolvedValue({ ai_req_id: "AIR-1", status: "accepted", module_override: null }),
    loadPdfAnnotation: vi.fn().mockResolvedValue({ available: false, reason: "影印页尚未生成" }),
    loadPdfPageBlob: vi.fn(async (file: string) => `blob:fake-${file}`),
    ...over,
  }
}

describe("DocumentReview", () => {
  it("renders the document, anchors annotations, flags omissions, and reviews in place", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    // 1 需求；B3 是 requirement_like 且未覆盖 → 1 遗漏（B2 被 AIR-1 覆盖、B1 是标题）
    expect(wrapper.find('[data-testid="doc-stat-reqs"]').text()).toBe("1")
    expect(wrapper.find('[data-testid="doc-stat-omissions"]').text()).toBe("1")
    expect(wrapper.find('[data-testid="omission-block"]').exists()).toBe(true)

    // 锚块上有批注 chip；点开 → 详情显示模块
    const chip = wrapper.find('[data-testid="anno-AIR-1"]')
    expect(chip.exists()).toBe(true)
    await chip.trigger("click")
    expect(wrapper.find('[data-testid="dd-module"]').text()).toContain("计量")
    expect(wrapper.find('[data-testid="dd-suspicion"]').text()).toContain("数字漂移")  // 可疑度徽标
    expect(wrapper.find('[data-testid="dd-consistency"]').text()).toContain("跨章重复×2")  // 一致性闭环标记
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("应计量体积")  // 需求分析
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("实现体积累计计量与本地存储")  // 研发指引
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("按 4.2 测试")  // 测试指引

    // 批注内裁决（接受）→ 调 applyAiReviewAction
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    await flushPromises()
    expect(client.applyAiReviewAction).toHaveBeenCalledWith(
      expect.objectContaining({ aiReqId: "AIR-1", status: "accepted" }),
    )
  })

  it("marks notes and list groups so paragraph rhythm is preserved", async () => {
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 5,
        blocks: [
          { block_id: "B1", order: 1, type: "paragraph", text: "NOTE Context for the scope.", noise: false },
          { block_id: "B2", order: 2, type: "paragraph", text: "The following locations apply:", noise: false },
          { block_id: "B3", order: 3, type: "paragraph", text: "- closed locations", noise: false },
          { block_id: "B4", order: 4, type: "paragraph", text: "- open locations", noise: false },
          { block_id: "B5", order: 5, type: "paragraph", text: "and in other locations.", noise: false },
        ],
      }),
      loadAiRequirements: vi.fn().mockResolvedValue([]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.findAll(".doc-block.note")).toHaveLength(1)
    expect(wrapper.findAll(".doc-block.list-item")).toHaveLength(2)
    expect(wrapper.findAll(".doc-text.list-item")).toHaveLength(2)
  })

  it("changing the module dropdown sends module_override on decide", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    await wrapper.find('[data-testid="dd-module-select"]').setValue("计量精度")
    await wrapper.find('[data-testid="dd-reject"]').trigger("click")
    await flushPromises()
    expect(client.applyAiReviewAction).toHaveBeenCalledWith(
      expect.objectContaining({ aiReqId: "AIR-1", status: "rejected", moduleOverride: "计量精度" }),
    )
  })

  it("changing the ownership dropdown sends ownership_override on decide", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    // 规则初判 software → 专家改判 硬件
    await wrapper.find('[data-testid="dd-ownership-select"]').setValue("hardware")
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    await flushPromises()
    expect(client.applyAiReviewAction).toHaveBeenCalledWith(
      expect.objectContaining({ aiReqId: "AIR-1", status: "accepted", ownershipOverride: "hardware" }),
    )
  })

  it("highlights only the anchor block and toggles deselect on second click", async () => {
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 3,
        blocks: [
          { block_id: "B1", order: 1, type: "paragraph", text: "The meter shall measure volume.",
            section_path: ["4"], requirement_like: true, noise: false },
          { block_id: "B2", order: 2, type: "paragraph", text: "Same section other paragraph.",
            section_path: ["4"], requirement_like: false, noise: false },
        ],
      }),
      loadAiRequirements: vi.fn().mockResolvedValue([
        { ai_req_id: "AIR-9", title: "T", description: "d", module: "计量", module_effective: "计量",
          type: "functional", priority: "P1", status: "draft", source_section: "4",
          source_quote: "The meter shall measure volume.",
          source_block_ids: ["B1", "B2"], anchor_block_id: "B1",   // 跨度两块，锚点 B1
          acceptance_criteria: [], labels: ["计量"], review_state: null },
      ]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="anno-AIR-9"]').trigger("click")
    // 整个被分析跨度（source_block_ids）亮淡底——只黄一句会让"分析了一整段"看着像没选中（真实反馈）
    const inSpan = wrapper.findAll(".doc-block.in-span")
    expect(inSpan.length).toBe(2)
    // 引句黄标只在锚点段内
    expect(wrapper.findAll(".doc-text mark").length).toBe(1)
    expect(wrapper.find(".doc-text mark").text()).toContain("measure volume")

    // 再点一下 → 取消选中：详情回空态、无 in-span
    await wrapper.find('[data-testid="anno-AIR-9"]').trigger("click")
    expect(wrapper.findAll(".doc-block.in-span").length).toBe(0)
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("点左侧")
  })

  it("pdf original mode renders pages with clickable markers sharing the detail panel", async () => {
    const client = makeClient({
      loadPdfAnnotation: vi.fn().mockResolvedValue({
        available: true,
        pages: [{ page_number: 1, file: "page-0001.png", width: 595, height: 842 }],
        requirement_markers: [{ req_id: "AIR-1", page: 1, rect: { left: 8, top: 12, width: 60, height: 4 } }],
        omission_markers: [{ block_id: "B3", page: 1, rect: { left: 8, top: 30, width: 60, height: 4 } }],
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="mode-pdf"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="pdf-paper"]').exists()).toBe(true)
    expect(wrapper.find(".pdf-page img").attributes("src")).toContain("page-0001.png")
    // 点批注标记 → 右栏详情(与文字模式共用,裁决可用)
    await wrapper.find('[data-testid="pdf-marker-AIR-1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-module"]').text()).toContain("计量")
    expect(wrapper.find('[data-testid="dd-accept"]').exists()).toBe(true)
    // 未覆盖标记 → 块级卡
    await wrapper.find(".pdf-marker.marker-omission").trigger("click")
    expect(wrapper.find('[data-testid="omission-card"]').exists()).toBe(true)
  })

  it("pdf mode shows honest hint when pages are not generated", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="mode-pdf"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="pdf-unavailable"]').text()).toContain("影印页尚未生成")
  })

  it("guides the user when not connected to an output dir", async () => {
    const wrapper = mount(DocumentReview, { props: { client: null, active: true } })
    await flushPromises()
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("先运行管线")
  })

  it("omission tag opens a three-part card: reason / translation / quote", async () => {
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 3,
        blocks: [
          { block_id: "B1", order: 1, type: "heading", text: "4 Requirements",
            section_path: ["4 Requirements"], requirement_like: false, noise: false },
          { block_id: "B2", order: 2, type: "paragraph", text: "The meter shall measure volume.",
            section_path: ["4 Requirements"], requirement_like: true, noise: false },
          { block_id: "B3", order: 3, type: "paragraph", text: "An uncovered requirement shall hold.",
            section_path: ["4 Requirements"], requirement_like: true, noise: false,
            translation: "一条未被覆盖的需求应当成立。" },
        ],
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    const inlineTag = wrapper.find('[data-testid="omission-block"] .doc-text [data-testid="omission-tag"]')
    expect(inlineTag.exists()).toBe(true)
    expect(inlineTag.text()).toBe("未覆盖")
    await inlineTag.trigger("click")
    const card = wrapper.find('[data-testid="omission-card"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain("为什么标为未覆盖")                       // 第一段：原因
    expect(card.text()).toContain("没有任何已抽取需求的来源范围覆盖它")
    expect(card.find('[data-testid="omission-translation"]').text())       // 第二段：翻译
      .toContain("一条未被覆盖的需求应当成立")
    expect(card.text()).toContain("An uncovered requirement shall hold.")  // 第三段：原文引用
    // 选中态：整段黄标 + 块蓝底
    expect(wrapper.findAll(".doc-block.evidence").length).toBe(1)
    expect(wrapper.find('[data-testid="omission-block"] .doc-text mark').text())
      .toContain("An uncovered requirement shall hold.")

    // 再点一下 → 取消选中
    await wrapper.find('[data-testid="omission-tag"]').trigger("click")
    expect(wrapper.find('[data-testid="omission-card"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("点左侧")
  })

  it("omission card shows honest empty state without translation", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="omission-tag"]').trigger("click")
    const card = wrapper.find('[data-testid="omission-card"]')
    expect(card.text()).toContain("未生成翻译")
  })

  it("prefers enriched analysis narrative with source badge and ownership reason", async () => {
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([
        {
          ai_req_id: "AIR-1", title: "体积计量", description: "抽取轨浅描述", module: "计量",
          module_effective: "计量", type: "functional", priority: "P1", status: "draft",
          source_section: "4", source_quote: "The meter shall measure volume.",
          source_block_ids: ["B2"], labels: ["计量"], review_state: null,
          ownership: "software", ownership_effective: "software",
          ownership_reason: "Matched software rule term: dlms",
          analysis_source: "llm",
          analysis_software_requirement_text: "富化正文第一段。\n第二段:边界条件与异常处理。",
          analysis_dev_guidance: ["实现指引(富化)"],
          analysis_acceptance_criteria: ["验收(富化)"],
          analysis_enrichment_warnings: ["数字待核 42"],
          analysis_ownership_reason: "纯数据处理逻辑,无硬件依赖",
        },
      ]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-analysis-badge"]').text()).toContain("富化(LLM)")
    expect(wrapper.find('[data-testid="dd-analysis-text"]').text()).toContain("富化正文第一段")
    expect(wrapper.find('[data-testid="dd-enrich-warnings"]').text()).toContain("数字待核 42")
    expect(wrapper.find('[data-testid="dd-ownership-reason"]').text()).toContain("纯数据处理逻辑")
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("实现指引(富化)")
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("为什么判为软件")
  })

  it("falls back to extraction description without analysis fields", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-analysis-badge"]').text()).toContain("抽取")
    expect(wrapper.find('[data-testid="dd-analysis-text"]').text()).toContain("应计量体积")
  })

  it("hardware card never shows english as translation, falls back to block translation", async () => {
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 1,
        blocks: [
          { block_id: "B1", order: 1, type: "paragraph", text: "The valve is mechanical.",
            section_path: ["4"], requirement_like: true, noise: false,
            translation: "该阀门为机械部件。" },
        ],
      }),
      loadAiRequirements: vi.fn().mockResolvedValue([
        { ai_req_id: "AIR-HW", title: "阀门", description: "The valve is mechanical.", module: "机械结构",
          module_effective: "机械结构", type: "functional", priority: "P1", status: "draft",
          source_section: "4", source_quote: "The valve is mechanical.",
          source_block_ids: ["B1"], anchor_block_id: "B1", labels: [], review_state: null,
          ownership: "hardware", ownership_effective: "hardware",
          hardware_translation: "The valve is mechanical.",   // 确定性兜底=英文,不得当翻译显示
        },
      ]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-HW"]').trigger("click")
    const shown = wrapper.find('[data-testid="dd-hw-translation"]')
    expect(shown.exists()).toBe(true)
    expect(shown.text()).toContain("该阀门为机械部件。")            // 块级翻译回退
    expect(shown.text()).not.toContain("The valve is mechanical")  // 英文绝不冒充翻译
  })

  it("hardware card does not fall back to extraction guidance or acceptance", async () => {
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([
        {
          ai_req_id: "AIR-HW", title: "阀门", description: "The valve is mechanical.", module: "机械结构",
          module_effective: "机械结构", type: "functional", priority: "P1", status: "draft",
          source_section: "4", source_quote: "The valve is mechanical.", source_block_ids: ["B2"],
          labels: [], review_state: null, ownership: "hardware", ownership_effective: "hardware",
          analysis_source: "llm", analysis_dev_guidance: [], analysis_acceptance_criteria: [],
          hardware_translation: "该阀门是机械部件。",
          dev_guidance: ["不应显示的软件研发指引"],
          acceptance_criteria: ["不应显示的软件验收建议"],
        },
      ]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-HW"]').trigger("click")

    const detail = wrapper.find('[data-testid="doc-detail"]').text()
    expect(wrapper.find('[data-testid="dd-hw-translation"]').text()).toContain("该阀门是机械部件")
    expect(detail).not.toContain("不应显示的软件研发指引")
    expect(detail).not.toContain("不应显示的软件验收建议")
  })

  it("plain background paragraph opens a context card on click", async () => {
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 2,
        blocks: [
          { block_id: "B1", order: 1, type: "paragraph", text: "Background drafting note.",
            section_path: ["Introduction"], requirement_like: false, noise: false,
            translation: "背景起草说明。" },
          { block_id: "B2", order: 2, type: "paragraph", text: "The meter shall measure volume.",
            section_path: ["4"], requirement_like: true, noise: false },
        ],
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.findAll(".doc-block")[0].trigger("click")
    const card = wrapper.find('[data-testid="context-card"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain("为什么没有生成研发需求")
    expect(card.text()).toContain("背景/说明性内容")
    expect(card.text()).toContain("背景起草说明。")
    expect(card.text()).toContain("Background drafting note.")
    // 再点一下 → 取消
    await wrapper.findAll(".doc-block")[0].trigger("click")
    expect(wrapper.find('[data-testid="context-card"]').exists()).toBe(false)
  })
})
