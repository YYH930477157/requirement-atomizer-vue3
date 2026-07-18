import { describe, it, expect, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import DocumentReview from "../DocumentReview.vue"

function deferred<T>() {
  let resolvePromise!: (value: T | PromiseLike<T>) => void
  const promise = new Promise<T>((resolve) => { resolvePromise = resolve })
  return { promise, resolve: resolvePromise }
}

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
  it("shows a loading state instead of a false unavailable state during initial loading", async () => {
    const documentRequest = deferred<{ count: number; blocks: [] }>()
    const client = makeClient({ loadDocument: vi.fn(() => documentRequest.promise) })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="pdf-loading"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="pdf-unavailable"]').exists()).toBe(false)

    documentRequest.resolve({ count: 0, blocks: [] })
    await flushPromises()
  })

  it("prefers original PDF pages when available and labels reflow as parsed text", async () => {
    const client = makeClient({
      loadPdfAnnotation: vi.fn().mockResolvedValue({
        available: true,
        pages: [{ page_number: 1, file: "page-0001.png", width: 595, height: 842 }],
        requirement_markers: [], omission_markers: [], block_zones: [],
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="mode-text"]').text()).toContain("解析文本")
    expect(wrapper.find('[data-testid="mode-pdf"]').classes()).toContain("active")
    expect(wrapper.find('[data-testid="pdf-paper"]').exists()).toBe(true)
    expect(client.loadPdfAnnotation).toHaveBeenCalledTimes(1)
    expect(client.loadPdfPageBlob).toHaveBeenCalledWith("page-0001.png")
  })

  it("falls back to parsed text when original pages are unavailable", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="mode-text"]').classes()).toContain("active")
    expect(wrapper.find('[data-testid="doc-paper"]').exists()).toBe(true)
    await wrapper.find('[data-testid="mode-pdf"]').trigger("click")
    expect(wrapper.find('[data-testid="pdf-unavailable"]').text()).toContain("影印页尚未生成")
  })

  it("refreshes stale PDF data and returns to original pages when they become available", async () => {
    const loadPdfAnnotation = vi.fn()
      .mockResolvedValueOnce({ available: false, reason: "影印页尚未生成" })
      .mockResolvedValueOnce({
        available: true,
        pages: [{ page_number: 1, file: "page-new.png", width: 595, height: 842 }],
        requirement_markers: [], omission_markers: [], block_zones: [],
      })
    const client = makeClient({ loadPdfAnnotation })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="mode-text"]').classes()).toContain("active")
    await wrapper.find('[data-testid="doc-reload"]').trigger("click")
    await flushPromises()

    expect(loadPdfAnnotation).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="mode-pdf"]').classes()).toContain("active")
    expect(client.loadPdfPageBlob).toHaveBeenCalledWith("page-new.png")
  })

  it("invalidates an in-flight PDF metadata response when refresh starts", async () => {
    const staleRequest = deferred<{
      available: boolean; reason: string; pages: []; requirement_markers: []; omission_markers: []; block_zones: []
    }>()
    const loadPdfAnnotation = vi.fn()
      .mockImplementationOnce(() => staleRequest.promise)
      .mockResolvedValueOnce({
        available: true,
        pages: [{ page_number: 1, file: "page-0002.png", width: 595, height: 842 }],
        requirement_markers: [], omission_markers: [], block_zones: [],
      })
    const client = makeClient({ loadPdfAnnotation })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="doc-reload"]').trigger("click")
    await flushPromises()
    expect(loadPdfAnnotation).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="mode-pdf"]').classes()).toContain("active")

    staleRequest.resolve({
      available: false, reason: "旧请求不应回写", pages: [],
      requirement_markers: [], omission_markers: [], block_zones: [],
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="mode-pdf"]').classes()).toContain("active")
    expect(wrapper.find('[data-testid="pdf-unavailable"]').exists()).toBe(false)
    expect(client.loadPdfPageBlob).toHaveBeenCalledWith("page-0002.png")
  })

  it("does not override a parsed-text choice made while refresh is loading PDF metadata", async () => {
    const refreshRequest = deferred<{
      available: boolean; pages: []; requirement_markers: []; omission_markers: []; block_zones: []
    }>()
    const loadPdfAnnotation = vi.fn()
      .mockResolvedValueOnce({
        available: true, pages: [], requirement_markers: [], omission_markers: [], block_zones: [],
      })
      .mockImplementationOnce(() => refreshRequest.promise)
    const client = makeClient({ loadPdfAnnotation })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="doc-reload"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="mode-text"]').trigger("click")
    refreshRequest.resolve({
      available: true, pages: [], requirement_markers: [], omission_markers: [], block_zones: [],
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="mode-text"]').classes()).toContain("active")
    expect(wrapper.find('[data-testid="doc-paper"]').exists()).toBe(true)
  })

  it("keeps an explicit parsed-text selection after refresh", async () => {
    const client = makeClient({
      loadPdfAnnotation: vi.fn().mockResolvedValue({
        available: true,
        pages: [{ page_number: 1, file: "page-0001.png", width: 595, height: 842 }],
        requirement_markers: [], omission_markers: [], block_zones: [],
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="mode-text"]').trigger("click")
    await wrapper.find('[data-testid="doc-reload"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[data-testid="mode-text"]').classes()).toContain("active")
    expect(client.loadPdfAnnotation).toHaveBeenCalledTimes(1)
  })

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
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("应计量体积")  // 需求摘要回退
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("实现体积累计计量与本地存储")  // 研发指引
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("按 4.2 测试")  // 测试指引

    // 批注内裁决（接受）→ 调 applyAiReviewAction
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    await flushPromises()
    expect(client.applyAiReviewAction).toHaveBeenCalledWith(
      expect.objectContaining({ aiReqId: "AIR-1", status: "accepted" }),
    )
  })

  it("echo blocks list every linked requirement and stay highlighted after jumping", async () => {
    // 回声段(0715 电表招标实证 + 0716 用户裁定):同文重复出现处不再显示"未覆盖",
    // 也不重复挂完整批注——点击给"重复段"卡片,链接跳到汇总条目
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([
        {
          ai_req_id: "AIR-1", title: "体积计量", description: "应计量体积", module: "计量",
          module_effective: "计量", type: "functional", priority: "P1", status: "draft",
          source_section: "4", source_quote: "The meter shall measure volume.",
          source_block_ids: ["B2"], anchor_block_id: "B2",
          echo_block_ids: ["B3"],                       // B3 = 同文重复出现处
          acceptance_criteria: [], dev_guidance: [], labels: ["计量"],
          ownership: "software", ownership_effective: "software", review_state: null,
        },
        {
          ai_req_id: "AIR-2", title: "通信要求", description: "应支持通信", module: "通信协议",
          module_effective: "通信协议", type: "functional", priority: "P1", status: "draft",
          source_section: "4", source_quote: "4 Requirements",
          source_block_ids: ["B1"], anchor_block_id: "B1", echo_block_ids: ["B3"],
          acceptance_criteria: [], dev_guidance: [], labels: ["通信"],
          ownership: "software", ownership_effective: "software", review_state: null,
        },
      ]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    // 不计遗漏;chip 只在锚点段一枚(不过度显示)
    expect(wrapper.find('[data-testid="doc-stat-omissions"]').text()).toBe("0")
    expect(wrapper.findAll(".anno-chip").length).toBe(2)
    expect(wrapper.find('[data-testid="echo-tag-B3"]').text()).toContain("01/02")

    // 点击回声段 → "重复段"卡片(本段解析) + 跳转链接 → 选中汇总条目
    const echoBlock = wrapper.findAll(".doc-block").find((b) => b.text().includes("An uncovered requirement"))
    await wrapper.find('[data-testid="echo-tag-B3"]').trigger("click")
    expect(wrapper.find('[data-testid="echo-card"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="echo-jump"]')).toHaveLength(2)
    await wrapper.findAll('[data-testid="echo-jump"]')[1].trigger("click")
    expect(wrapper.find('[data-testid="dd-module"]').text()).toBe("计量")
    expect(echoBlock!.classes()).toContain("in-span")
  })

  it("pdf echo zones show a marker, open the echo card, and retain every target", async () => {
    const requirements = [
      { ai_req_id: "AIR-1", title: "需求一", description: "d1", module: "计量",
        module_effective: "计量", type: "functional", priority: "P1", status: "draft",
        source_section: "4", source_quote: "The meter shall measure volume.",
        source_block_ids: ["B2"], anchor_block_id: "B2", echo_block_ids: ["B3"],
        acceptance_criteria: [], labels: [], review_state: null },
      { ai_req_id: "AIR-2", title: "需求二", description: "d2", module: "通信协议",
        module_effective: "通信协议", type: "functional", priority: "P1", status: "draft",
        source_section: "4", source_quote: "4 Requirements",
        source_block_ids: ["B1"], anchor_block_id: "B1", echo_block_ids: ["B3"],
        acceptance_criteria: [], labels: [], review_state: null },
    ]
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue(requirements),
      loadPdfAnnotation: vi.fn().mockResolvedValue({
        available: true,
        pages: [{ page_number: 1, file: "page-0001.png", width: 595, height: 842 }],
        requirement_markers: [], omission_markers: [],
        block_zones: [{ block_id: "B3", page: 1,
          rect: { left: 8, top: 40, width: 60, height: 4 },
          kind: "echo", req_ids: ["AIR-1", "AIR-2"] }],
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="mode-pdf"]').trigger("click")
    await flushPromises()

    const zone = wrapper.find('[data-testid="pdf-zone-B3"]')
    expect(zone.text()).toContain("重复·见01/02")
    await zone.find(".pdf-echo-tag").trigger("click")
    expect(wrapper.find('[data-testid="echo-card"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="echo-jump"]')).toHaveLength(2)
    await wrapper.findAll('[data-testid="echo-jump"]')[0].trigger("click")
    expect(zone.classes()).toContain("sel")
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
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("查看解析结果")
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

  it("revokes loaded and late PDF page blob URLs and stops fetching after unmount", async () => {
    const revokeObjectURL = vi.fn()
    vi.stubGlobal("URL", { revokeObjectURL })
    let resolveLate: ((url: string) => void) | undefined
    const client = makeClient({
      loadPdfAnnotation: vi.fn().mockResolvedValue({
        available: true,
        pages: [
          { page_number: 1, file: "page-0001.png", width: 595, height: 842 },
          { page_number: 2, file: "page-0002.png", width: 595, height: 842 },
          { page_number: 3, file: "page-0003.png", width: 595, height: 842 },
        ],
        requirement_markers: [],
        omission_markers: [],
      }),
      loadPdfPageBlob: vi.fn((file: string) => {
        if (file === "page-0001.png") return Promise.resolve("blob:loaded")
        if (file === "page-0002.png") return new Promise<string>((resolve) => { resolveLate = resolve })
        return Promise.resolve("blob:must-not-load")
      }),
    })
    try {
      const wrapper = mount(DocumentReview, { props: { client, active: true } })
      await flushPromises()
      expect(client.loadPdfPageBlob).toHaveBeenCalledTimes(2)

      wrapper.unmount()
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:loaded")
      resolveLate?.("blob:late")
      await flushPromises()
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:late")
      expect(client.loadPdfPageBlob).toHaveBeenCalledTimes(2)
      expect(client.loadPdfPageBlob).not.toHaveBeenCalledWith("page-0003.png")
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("pdf mode full-block zones: click any paragraph for translation/analysis card", async () => {
    // 影印页全段落热区：锚点→需求卡，来源跨度→关联需求，普通段→背景卡。
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 4,
        blocks: [
          { block_id: "B1", order: 1, type: "paragraph", text: "The meter shall measure volume.",
            section_path: ["4"], requirement_like: true, noise: false, coverage_candidate: true,
            translation: "" },
          { block_id: "B2", order: 2, type: "paragraph", text: "Background prose paragraph.",
            section_path: ["4"], requirement_like: false, noise: false, coverage_candidate: false,
            translation: "背景说明段的中文翻译。" },
          { block_id: "B3", order: 3, type: "paragraph", text: "The result shall also be stored.",
            section_path: ["4"], requirement_like: true, noise: false, coverage_candidate: true,
            translation: "结果还应被存储。" },
          { block_id: "B4", order: 4, type: "paragraph", text: "An uncovered alarm shall be reported.",
            section_path: ["4"], requirement_like: true, noise: false, coverage_candidate: true,
            translation: "未覆盖的报警应被报告。" },
        ],
      }),
      loadAiRequirements: vi.fn().mockResolvedValue([
        { ai_req_id: "AIR-1", title: "计量", description: "d", module: "计量", module_effective: "计量",
          type: "functional", priority: "P1", status: "draft", source_section: "4",
          source_quote: "The meter shall measure volume.",
          source_block_ids: ["B1", "B3"], anchor_block_id: "B1",
          acceptance_criteria: [], labels: ["计量"], review_state: null },
        { ai_req_id: "AIR-2", title: "报警", description: "d2", module: "事件记录", module_effective: "事件记录",
          type: "functional", priority: "P1", status: "draft", source_section: "4",
          source_quote: "The meter shall measure volume.",
          source_block_ids: ["B1"], anchor_block_id: "B1",
          acceptance_criteria: [], labels: ["事件记录"], review_state: null },
      ]),
      loadPdfAnnotation: vi.fn().mockResolvedValue({
        available: true,
        pages: [{ page_number: 1, file: "page-0001.png", width: 595, height: 842 }],
        requirement_markers: [{ req_id: "AIR-1", page: 1, rect: { left: 8, top: 12, width: 60, height: 4 } }],
        omission_markers: [{ block_id: "B4", page: 1, rect: { left: 8, top: 56, width: 60, height: 4 } }],
        block_zones: [
          { block_id: "B1", page: 1, rect: { left: 8, top: 12, width: 60, height: 4 },
            kind: "req", req_id: "AIR-1", req_ids: ["AIR-1", "AIR-2"] },
          { block_id: "B2", page: 1, rect: { left: 8, top: 40, width: 60, height: 4 },
            kind: "context" },
          { block_id: "B3", page: 1, rect: { left: 8, top: 48, width: 60, height: 4 },
            kind: "covered", req_ids: ["AIR-1"] },
          { block_id: "B4", page: 1, rect: { left: 8, top: 56, width: 60, height: 4 },
            kind: "omission" },
        ],
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    // 背景段热区 → 三段式说明卡（原因/翻译/引用）
    await wrapper.find('[data-testid="pdf-zone-B2"]').trigger("click")
    const card = wrapper.find('[data-testid="context-card"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain("为什么没有生成研发需求")
    expect(card.text()).toContain("背景说明段的中文翻译。")
    expect(card.text()).toContain("Background prose paragraph.")
    expect(wrapper.find('[data-testid="pdf-zone-B2"]').classes()).toContain("sel")
    expect(wrapper.find(".pdf-zone").exists()).toBe(false)

    // 同一原文段解析出多条需求时先展示完整结果列表，避免只打开第一条。
    await wrapper.find('[data-testid="pdf-zone-B1"]').trigger("click")
    const reqGroupCard = wrapper.find('[data-testid="req-group-card"]')
    expect(reqGroupCard.text()).toContain("该段解析出 2 条需求")
    expect(reqGroupCard.findAll('[data-testid="echo-jump"]')).toHaveLength(2)
    expect(wrapper.find('[data-testid="pdf-zone-B1"]').classes()).toContain("sel")
    await reqGroupCard.findAll('[data-testid="echo-jump"]')[0].trigger("click")
    expect(wrapper.find('[data-testid="dd-module"]').text()).toContain("计量")

    // 非锚点来源段不能误报为背景；点原文应说明它已纳入需求，并可跳转关联需求。
    await wrapper.find('[data-testid="pdf-zone-B3"]').trigger("click")
    const coveredCard = wrapper.find('[data-testid="covered-card"]')
    expect(coveredCard.text()).toContain("该段已纳入需求解析")
    expect(coveredCard.text()).toContain("结果还应被存储。")
    expect(coveredCard.text()).toContain("查看批注 01《计量》")
    expect(wrapper.find('[data-testid="pdf-zone-B3"]').attributes("aria-pressed")).toBe("true")
    await coveredCard.find('[data-testid="echo-jump"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-module"]').text()).toContain("计量")

    // 再点一下背景段 → 打开;再点同段 → 取消（与重排块点击同语义）
    await wrapper.find('[data-testid="pdf-zone-B2"]').trigger("click")
    await wrapper.find('[data-testid="pdf-zone-B2"]').trigger("click")
    expect(wrapper.find('[data-testid="context-card"]').exists()).toBe(false)

    // 未覆盖段正文与页边 ! 使用同一遗漏卡路由。
    await wrapper.find('[data-testid="pdf-zone-B4"]').trigger("click")
    expect(wrapper.find('[data-testid="omission-card"]').text()).toContain("为什么标为未覆盖")
    expect(wrapper.find('[data-testid="pdf-zone-B4"]').classes()).toContain("sel")
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
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("查看解析结果")
  })

  it("omission card shows honest empty state without translation", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="omission-tag"]').trigger("click")
    const card = wrapper.find('[data-testid="omission-card"]')
    expect(card.text()).toContain("未生成翻译")
  })

  it("uses functional membership and extracted fields instead of legacy LLM enrichment", async () => {
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([
        {
          ai_req_id: "AIR-1", title: "体积计量", description: "抽取轨浅描述", module: "计量",
          module_effective: "计量", type: "functional", priority: "P1", status: "draft",
          source_section: "4", source_quote: "The meter shall measure volume.",
          source_block_ids: ["B2"], labels: ["计量"], review_state: null,
          ownership: "software", ownership_effective: "software",
          ownership_reason: "Matched software rule term: dlms",
          functional_requirement_id: "FREQ-1",
          functional_title: "体积计量管理",
          functional_objective: "对计量结果进行累计和存储。",
          functional_behaviors: ["累计体积计量结果"],
          dev_guidance: ["实现抽取阶段给出的计量逻辑"],
          acceptance_criteria: ["按原文计量场景验收"],
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
    expect(wrapper.find('[data-testid="dd-requirement-summary"]').text()).toContain("抽取需求")
    expect(wrapper.find('[data-testid="dd-requirement-summary"]').text()).toContain("抽取轨浅描述")
    expect(wrapper.find('[data-testid="dd-functional"]').text()).toContain("体积计量管理")
    expect(wrapper.find('[data-testid="dd-functional"]').text()).toContain("累计体积计量结果")
    expect(wrapper.find('[data-testid="dd-analysis-badge"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="dd-analysis-text"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="dd-enrich-warnings"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="dd-ownership-reason"]').text()).toContain("Matched software rule term")
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("实现抽取阶段给出的计量逻辑")
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("按原文计量场景验收")
    expect(wrapper.find('[data-testid="doc-detail"]').text()).not.toContain("富化正文第一段")
    expect(wrapper.find('[data-testid="doc-detail"]').text()).not.toContain("实现指引(富化)")
    expect(wrapper.find('[data-testid="doc-detail"]').text()).not.toContain("数字待核 42")
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("为什么判为软件")
  })

  it("shows an extracted requirement summary when functional membership is unavailable", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-functional"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="dd-requirement-summary"]').text()).toContain("抽取需求")
    expect(wrapper.find('[data-testid="dd-requirement-summary"]').text()).toContain("应计量体积")
    expect(wrapper.find('[data-testid="dd-analysis-badge"]').exists()).toBe(false)
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

  it("keeps page-edge markers and PDF paragraph zones interactive", () => {
    const source = readFileSync(resolve(__dirname, "../DocumentReview.vue"), "utf-8")
    expect(source).toContain(".doc-paper.pdf-paper {\n  padding: 16px 48px 16px 16px;")
    expect(source).toContain(".doc-paper.pdf-paper { padding: 14px 44px 14px 12px; }")
    expect(source).toContain("cursor: pointer; pointer-events: auto; border-radius: 3px;")
  })
})
