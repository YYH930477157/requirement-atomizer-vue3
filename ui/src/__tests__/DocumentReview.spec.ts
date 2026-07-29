import { describe, it, expect, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import DocumentReview from "../DocumentReview.vue"
import { RequirementApiError } from "../api-client"

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
          section_path: ["4 Requirements"], requirement_like: true, noise: false,
          omission_id: "OM-B3", omission_source_fingerprint: "source-B3" },
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
  it("shows auditable text repairs and failed extraction locations", async () => {
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 1,
        failed_section_ids: ["4"],
        blocks: [{
          block_id: "B2", order: 1, type: "paragraph", text: "is obliged",
          raw_text: "i sobliged", text_repaired: true, extraction_failed: true,
          section_path: ["4"], requirement_like: true, noise: false,
          text_repairs: [{
            rule: "wordlist_fragment_repair", before: "i sobliged", after: "is obliged",
          }],
        }],
      }),
      loadAiRequirements: vi.fn().mockResolvedValue([]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="repair-tag"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="failed-extraction-tag"]').exists()).toBe(true)
    await wrapper.find('[data-testid="repair-tag"]').trigger("click")
    const repair = wrapper.find('[data-testid="repair-audit"]')
    expect(repair.text()).toContain("i sobliged")
    expect(repair.text()).toContain("is obliged")
    expect(repair.text()).toContain("wordlist_fragment_repair")
    expect(wrapper.find('[data-testid="failed-card"]').text()).toContain("该章节的 AI 抽取调用失败")
  })

  it("batch acknowledges one internal-check category with evidence fingerprints", async () => {
    const loadChecks = vi.fn()
      .mockResolvedValueOnce({
        schema: "clarification-internal-checks/v1", total: 2, unresolved: 2,
        groups: [{ signal: "suspicion:引用", count: 2, blocking: 0, modules: { 计量: 2 } }],
        entries: [
          { clarification_id: "CLR-1", evidence_fingerprint: "FP-1", signal: "suspicion:引用" },
          { clarification_id: "CLR-2", evidence_fingerprint: "FP-2", signal: "suspicion:引用" },
        ],
      })
      .mockResolvedValueOnce({
        schema: "clarification-internal-checks/v1", total: 2, unresolved: 0,
        groups: [], entries: [],
      })
    const applyBatch = vi.fn().mockResolvedValue({
      requested: 2, applied: 2, stale: [], missing: [], ineligible: [], duplicates: [],
      by_signal: { "suspicion:引用": 2 }, by_module: { 计量: 2 }, readiness: null,
    })
    const client = makeClient({
      loadClarificationInternalChecks: loadChecks,
      applyClarificationCheckBatch: applyBatch,
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="internal-check-acknowledge"]').trigger("click")
    await flushPromises()

    expect(applyBatch).toHaveBeenCalledWith(expect.objectContaining({
      checks: [
        { clarificationId: "CLR-1", evidenceFingerprint: "FP-1" },
        { clarificationId: "CLR-2", evidenceFingerprint: "FP-2" },
      ],
      action: "verified_ok",
    }))
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("已确认 2 项")
  })

  it("reports each rejected batch category separately", async () => {
    const loadChecks = vi.fn()
      .mockResolvedValueOnce({
        schema: "clarification-internal-checks/v1", total: 4, unresolved: 4,
        groups: [{ signal: "suspicion:引用", count: 4, blocking: 0 }],
        entries: [
          { clarification_id: "CLR-1", evidence_fingerprint: "FP-1", signal: "suspicion:引用" },
          { clarification_id: "CLR-2", evidence_fingerprint: "FP-2", signal: "suspicion:引用" },
          { clarification_id: "CLR-3", evidence_fingerprint: "FP-3", signal: "suspicion:引用" },
          { clarification_id: "CLR-4", evidence_fingerprint: "FP-4", signal: "suspicion:引用" },
        ],
      })
      .mockResolvedValueOnce({
        schema: "clarification-internal-checks/v1", total: 4, unresolved: 3,
        groups: [{ signal: "suspicion:引用", count: 3, blocking: 0 }], entries: [],
      })
    const client = makeClient({
      loadClarificationInternalChecks: loadChecks,
      applyClarificationCheckBatch: vi.fn().mockResolvedValue({
        requested: 4, applied: 1,
        stale: ["CLR-1"], missing: ["CLR-2"], ineligible: ["CLR-3"], duplicates: ["CLR-4"],
        by_signal: {}, by_module: {}, readiness: null,
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="internal-check-acknowledge"]').trigger("click")
    await flushPromises()

    const message = wrapper.find('[data-testid="doc-message"]').text()
    expect(message).toContain("证据过期 1 项")
    expect(message).toContain("已不存在 1 项")
    expect(message).toContain("不适用 1 项")
    expect(message).toContain("重复提交 1 项")
  })

  it("refreshes internal checks after a structured batch reconfirmation conflict", async () => {
    const initial = {
      schema: "clarification-internal-checks/v1" as const, total: 1, unresolved: 1,
      groups: [{ signal: "suspicion:引用", count: 1, blocking: 0 }],
      entries: [{ clarification_id: "CLR-1", evidence_fingerprint: "FP-1", signal: "suspicion:引用" }],
    }
    const refreshed = {
      ...initial,
      entries: [{ clarification_id: "CLR-1", evidence_fingerprint: "FP-2", signal: "suspicion:引用" }],
    }
    const loadChecks = vi.fn().mockResolvedValueOnce(initial).mockResolvedValueOnce(refreshed)
    const client = makeClient({
      loadClarificationInternalChecks: loadChecks,
      applyClarificationCheckBatch: vi.fn().mockRejectedValue(new RequirementApiError(409, {
        error: "clarification evidence changed",
        needs_reconfirmation: true,
      })),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="internal-check-acknowledge"]').trigger("click")
    await flushPromises()

    expect(loadChecks).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("证据已变化，已刷新")
  })

  it("selects a valid internal-check category after workspace refresh", async () => {
    const loadChecks = vi.fn()
      .mockResolvedValueOnce({
        schema: "clarification-internal-checks/v1", total: 1, unresolved: 1,
        groups: [{ signal: "suspicion:引用", count: 1, blocking: 0 }],
        entries: [{ clarification_id: "CLR-1", evidence_fingerprint: "FP-1", signal: "suspicion:引用" }],
      })
      .mockResolvedValueOnce({
        schema: "clarification-internal-checks/v1", total: 1, unresolved: 1,
        groups: [{ signal: "parse_audit:body_ratio", count: 1, blocking: 1 }],
        entries: [{ clarification_id: "CLR-2", evidence_fingerprint: "FP-2", signal: "parse_audit:body_ratio" }],
      })
    const client = makeClient({
      loadClarificationInternalChecks: loadChecks,
      applyClarificationCheckBatch: vi.fn(),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="doc-reload"]').trigger("click")
    await flushPromises()

    const select = wrapper.find('[aria-label="内部核对类别"]')
    expect((select.element as HTMLSelectElement).value).toBe("parse_audit:body_ratio")
    expect(wrapper.find('[data-testid="internal-check-acknowledge"]').text()).toContain("确认 1 项")
  })

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

  it("evidence zone covers every quote-matched block and fallback span stays scoped", async () => {
    // 锚点一致性（test5 实证）：证据区 = 原句实际跨越的块集（不再只亮首块，否则与原句
    // 左右不一致）；section_fallback 行的"分析范围"只认原句匹配块——跨小节回退跨度
    // 不会把无关清单段（"- DAY1"）刷进跨度。
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 4,
        blocks: [
          { block_id: "B1", order: 1, type: "paragraph", text: "- DAY1",
            section_path: ["3.4.4 Marking"], requirement_like: false, noise: false },
          { block_id: "B2", order: 2, type: "paragraph",
            text: "The terminal box must be supplied with crosshead screws.",
            section_path: ["3.4.5 Screws"], requirement_like: true, noise: false },
          { block_id: "B3", order: 3, type: "paragraph",
            text: "Condition upon delivery - screws must be firmly tightened.",
            section_path: ["3.4.5 Screws"], requirement_like: true, noise: false },
          { block_id: "B4", order: 4, type: "paragraph", text: "3.4.6 Packaging",
            section_path: ["3.4.6 Packaging"], requirement_like: false, noise: false },
        ],
      }),
      loadAiRequirements: vi.fn().mockResolvedValue([
        {
          ai_req_id: "AIR-1", title: "螺丝要求", description: "螺丝要求", module: "机械结构",
          module_effective: "机械结构", type: "constraint", priority: "P1", status: "draft",
          source_section: "3.4.5 Screws",
          source_quote: "The terminal box must be supplied with crosshead screws.\nCondition upon delivery - screws must be firmly tightened.",
          source_block_ids: ["B1", "B2", "B3", "B4"], source_mapping: "section_fallback",
          anchor_block_id: "B2", quote_block_ids: ["B2", "B3"],
          acceptance_criteria: [], dev_guidance: [], labels: ["机械结构"],
          ownership: "hardware", ownership_effective: "hardware", review_state: null,
        },
      ]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find(".anno-chip").trigger("click")
    const block = (id: string) => wrapper.find(`.doc-block[data-block-id="${id}"]`)
    // 证据区 = 原句跨越块集（B2+B3），不再只亮首块
    expect(block("B2").classes()).toContain("evidence")
    expect(block("B3").classes()).toContain("evidence")
    // section_fallback：无关清单段 B1 与下一节 B4 不进分析跨度
    expect(block("B1").classes()).not.toContain("in-span")
    expect(block("B4").classes()).not.toContain("in-span")
    // 无关块也不显示"分析范围"卡片语义（未被 coveredByBlock 收录即不刷细条）
    expect(block("B2").classes()).toContain("in-span")
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

  it("selecting a requirement highlights every quote block zone in pdf mode", async () => {
    // 影印模式选中高亮（test8 实证）：原句跨越的块全部框出（quote-sel），不再只框锚点标题块
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([
        { ai_req_id: "AIR-1", title: "端子标记", description: "d", module: "机械结构",
          module_effective: "机械结构", type: "functional", priority: "P1", status: "draft",
          source_section: "3.4.4", source_quote: "q",
          source_block_ids: ["B1", "B2", "B3"], anchor_block_id: "B1",
          quote_block_ids: ["B1", "B2", "B3"],
          acceptance_criteria: [], labels: [], review_state: null },
      ]),
      loadPdfAnnotation: vi.fn().mockResolvedValue({
        available: true,
        pages: [{ page_number: 1, file: "page-0001.png", width: 595, height: 842 }],
        requirement_markers: [], omission_markers: [],
        block_zones: [
          { block_id: "B1", page: 1, rect: { left: 8, top: 10, width: 60, height: 4 },
            kind: "req", req_id: "AIR-1", req_ids: ["AIR-1"] },
          { block_id: "B2", page: 1, rect: { left: 8, top: 20, width: 60, height: 4 },
            kind: "covered", req_ids: ["AIR-1"] },
          { block_id: "B3", page: 1, rect: { left: 8, top: 30, width: 60, height: 4 }, kind: "context" },
          { block_id: "B4", page: 1, rect: { left: 8, top: 40, width: 60, height: 4 }, kind: "context" },
        ],
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="mode-pdf"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="pdf-zone-B1"]').trigger("click")

    // 锚点主框 + 原句跨越块全部 quote-sel；无关块不框
    expect(wrapper.find('[data-testid="pdf-zone-B1"]').classes()).toContain("sel")
    expect(wrapper.find('[data-testid="pdf-zone-B2"]').classes()).toContain("quote-sel")
    expect(wrapper.find('[data-testid="pdf-zone-B3"]').classes()).toContain("quote-sel")
    expect(wrapper.find('[data-testid="pdf-zone-B4"]').classes()).not.toContain("quote-sel")
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

  it("accepts a free-text module outside the suggested vocabulary", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    await wrapper.find('[data-testid="dd-module-select"]').setValue("通信安全")
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    await flushPromises()

    expect(client.applyAiReviewAction).toHaveBeenCalledWith(
      expect.objectContaining({ aiReqId: "AIR-1", moduleOverride: "通信安全" }),
    )
  })

  it("renders custom module vocabulary returned by the document endpoint", async () => {
    const seedClient = makeClient()
    const document = await seedClient.loadDocument()
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({ ...document, module_vocabulary: ["通信安全"] }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")

    expect(wrapper.findAll('#review-module-options option').map((option) => option.attributes("value")))
      .toContain("通信安全")
  })

  it("rejects blank and overlong free-text modules before submission", async () => {
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")

    await wrapper.find('[data-testid="dd-module-select"]').setValue("   ")
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("模块不能为空")

    await wrapper.find('[data-testid="dd-module-select"]').setValue("模".repeat(21))
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("最多 20 字")
    expect(client.applyAiReviewAction).not.toHaveBeenCalled()
  })

  it("preserves an existing module override when deciding the requirement again", async () => {
    const seedClient = makeClient()
    const reqs = await seedClient.loadAiRequirements()
    const applyAiReviewAction = vi.fn().mockResolvedValue({
      ai_req_id: "AIR-1", status: "rejected", module_override: "计量精度", ownership_override: null,
    })
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([{
        ...reqs[0], module: "计量", module_effective: "计量精度",
        review_state: { status: "accepted", module_override: "计量精度" },
      }]),
      applyAiReviewAction,
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    await wrapper.find('[data-testid="dd-reject"]').trigger("click")
    await flushPromises()

    expect(applyAiReviewAction).toHaveBeenCalledWith(
      expect.objectContaining({ aiReqId: "AIR-1", status: "rejected", moduleOverride: "计量精度" }),
    )
    expect(wrapper.find('[data-testid="dd-module"]').text()).toBe("计量精度")
  })

  it("clears an existing module override when selecting the original module", async () => {
    const seedClient = makeClient()
    const reqs = await seedClient.loadAiRequirements()
    const applyAiReviewAction = vi.fn().mockResolvedValue({
      ai_req_id: "AIR-1", status: "accepted", module_override: null, ownership_override: null,
    })
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([{
        ...reqs[0], module: "计量", module_effective: "计量精度",
        review_state: { status: "rejected", module_override: "计量精度" },
      }]),
      applyAiReviewAction,
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    await wrapper.find('[data-testid="dd-module-select"]').setValue("计量")
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    await flushPromises()

    expect(applyAiReviewAction).toHaveBeenCalledWith(
      expect.objectContaining({ aiReqId: "AIR-1", status: "accepted", clearModuleOverride: true }),
    )
    expect(wrapper.find('[data-testid="dd-module"]').text()).toBe("计量")
    expect((wrapper.find('[data-testid="dd-module-select"]').element as HTMLInputElement).value).toBe("计量")
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

  it("pdf mode table-row zones: click a data row for row card with spot extract", async () => {
    // v12 表格行级热区：整表块不发区,数据行按 row_index 发区——点行出行级卡
    // （原文/翻译/章节/解析此行）,covered 行可跳关联需求,req 行直达需求卡。
    const spotExtract = vi.fn().mockResolvedValue({
      schema: "spot-extract/v1", block_id: "B1", row_index: 3, strategy: "deterministic_param_row",
      drafts: 1, draft_ids: ["SPOT-B1-R3"], already_covered: false, written: [],
    })
    const client = makeClient({
      spotExtract,
      loadDocument: vi.fn().mockResolvedValue({
        count: 1,
        blocks: [
          { block_id: "B1", order: 1, type: "table", text: "No. | Parameter | Requirement\n1. | Rated voltage | The meter shall operate at 230 V.",
            section_path: ["4 Requirements"], table_title: "Table 4.1 — Parameters",
            header_rows: [["No.", "Parameter", "Requirement"]],
            data_rows: [
              ["1.", "Rated voltage", "The meter shall operate at 230 V."],
              ["2.", "Display", "The meter shall provide a display for measured values."],
              ["3.", "Alarm", "The meter shall report an alarm on overflow."],
            ],
            requirement_like: false, noise: false },
        ],
      }),
      loadAiRequirements: vi.fn().mockResolvedValue([
        { ai_req_id: "AIR-1", title: "额定电压", description: "应工作在 230 V", module: "计量",
          module_effective: "计量", type: "functional", priority: "P1", status: "draft",
          source_section: "4", source_quote: "1. | Rated voltage | The meter shall operate at 230 V.",
          source_block_ids: ["B1"], anchor_block_id: "B1",
          acceptance_criteria: [], labels: ["计量"], review_state: null },
      ]),
      loadPdfAnnotation: vi.fn().mockResolvedValue({
        available: true,
        pages: [{ page_number: 1, file: "page-0001.png", width: 595, height: 842 }],
        requirement_markers: [], omission_markers: [],
        block_zones: [
          { block_id: "B1", row_index: 1, page: 1, rect: { left: 8, top: 12, width: 60, height: 4 },
            kind: "req", req_id: "AIR-1", req_ids: ["AIR-1"] },
          { block_id: "B1", row_index: 2, page: 1, rect: { left: 8, top: 16, width: 60, height: 4 },
            kind: "covered", req_ids: ["AIR-1"] },
          { block_id: "B1", row_index: 3, page: 1, rect: { left: 8, top: 20, width: 60, height: 4 },
            kind: "context" },
        ],
        row_context: {
          "B1#R1": { text: "1. | Rated voltage | The meter shall operate at 230 V.",
                     translation: "仪表应工作在 230 V。", page: 1, kind: "req", row_index: 1 },
          "B1#R2": { text: "2. | Display | The meter shall provide a display for measured values.",
                     translation: "", page: 1, kind: "covered", row_index: 2,
                     covered_req_ids: ["AIR-1"] },
          "B1#R3": { text: "3. | Alarm | The meter shall report an alarm on overflow.",
                     translation: "", page: 1, kind: "context", row_index: 3 },
        },
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    // 行热区渲染：table-row 修饰类 + 行级 testid；整表块本身无区
    const rowZone = wrapper.find('[data-testid="pdf-zone-B1-r3"]')
    expect(rowZone.exists()).toBe(true)
    expect(rowZone.classes()).toContain("table-row")
    expect(wrapper.find('[data-testid="pdf-zone-B1"]').exists()).toBe(false)

    // context 行 → 行级卡：原文/章节/暂无翻译/解析此行
    await rowZone.trigger("click")
    const card = wrapper.find('[data-testid="table-row-card"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain("该行没有单独生成研发需求")
    expect(wrapper.find('[data-testid="row-quote"]').text())
      .toContain("3. | Alarm | The meter shall report an alarm on overflow.")
    expect(wrapper.find('[data-testid="row-meta"]').text()).toContain("4 Requirements")
    expect(wrapper.find('[data-testid="row-translation-empty"]').text()).toContain("暂无翻译")
    expect(rowZone.classes()).toContain("sel")

    // 「解析此行」→ 现有 spotExtract 通道（blockId + rowIndex）
    await wrapper.find('[data-testid="row-spot-extract"]').trigger("click")
    await flushPromises()
    expect(spotExtract).toHaveBeenCalledWith(expect.objectContaining({ blockId: "B1", rowIndex: 3 }))
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("已生成 1 条 draft 需求")

    // req 行（单需求）→ 直达需求卡
    await wrapper.find('[data-testid="pdf-zone-B1-r1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-module"]').text()).toContain("计量")
    expect(wrapper.find('[data-testid="table-row-card"]').exists()).toBe(false)

    // covered 行 → 关联需求卡,可跳转批注
    await wrapper.find('[data-testid="pdf-zone-B1-r2"]').trigger("click")
    const coveredCard = wrapper.find('[data-testid="table-row-card"]')
    expect(coveredCard.text()).toContain("该行已纳入需求解析")
    expect(coveredCard.find('[data-testid="row-echo-jump"]').text()).toContain("额定电压")
    await coveredCard.find('[data-testid="row-echo-jump"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-module"]').text()).toContain("计量")

    // 再点同一行 → 取消选中（与块级同语义）
    await wrapper.find('[data-testid="pdf-zone-B1-r3"]').trigger("click")
    await wrapper.find('[data-testid="pdf-zone-B1-r3"]').trigger("click")
    expect(wrapper.find('[data-testid="table-row-card"]').exists()).toBe(false)
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

  it("navigates requirements sequentially with prev/next and shows annotation position", async () => {
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([
        { ai_req_id: "AIR-1", title: "体积计量", module: "计量", status: "draft",
          source_quote: "The meter shall measure volume.", source_block_ids: ["B2"], labels: ["计量"] },
        { ai_req_id: "AIR-2", title: "保持要求", module: "计量", status: "draft",
          source_quote: "An uncovered requirement shall hold.", source_block_ids: ["B3"], labels: ["计量"] },
      ]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-anno-no"]').text()).toContain("批注 01")
    expect(wrapper.find('[data-testid="dd-anno-no"]').text()).toContain("1/2")

    await wrapper.find('[data-testid="dd-next"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-anno-no"]').text()).toContain("批注 02")
    expect(wrapper.find(".dd-title").text()).toBe("保持要求")

    await wrapper.find('[data-testid="dd-next"]').trigger("click")   // 尾部循环回第一条
    expect(wrapper.find('[data-testid="dd-anno-no"]').text()).toContain("批注 01")
    await wrapper.find('[data-testid="dd-prev"]').trigger("click")   // 首部后退循环到尾部
    expect(wrapper.find('[data-testid="dd-anno-no"]').text()).toContain("批注 02")
  })

  it("supports scoped review shortcuts and advances after a keyboard decision", async () => {
    Element.prototype.scrollIntoView = vi.fn()
    const applyAiReviewAction = vi.fn().mockResolvedValue({
      ai_req_id: "AIR-1", status: "accepted", module_override: null, ownership_override: null,
    })
    const client = makeClient({
      applyAiReviewAction,
      loadAiRequirements: vi.fn().mockResolvedValue([
        { ai_req_id: "AIR-1", title: "体积计量", module: "计量", status: "draft",
          source_quote: "The meter shall measure volume.", source_block_ids: ["B2"], labels: ["计量"] },
        { ai_req_id: "AIR-2", title: "保持要求", module: "计量", status: "draft",
          source_quote: "An uncovered requirement shall hold.", source_block_ids: ["B3"], labels: ["计量"] },
      ]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "j" }))
    await flushPromises()
    expect(wrapper.find(".dd-title").text()).toBe("体积计量")
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "j" }))
    await flushPromises()
    expect(wrapper.find(".dd-title").text()).toBe("保持要求")
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "k" }))
    await flushPromises()
    expect(wrapper.find(".dd-title").text()).toBe("体积计量")

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }))
    await flushPromises()
    expect(applyAiReviewAction).toHaveBeenCalledWith(expect.objectContaining({
      aiReqId: "AIR-1", status: "accepted",
    }))
    expect(wrapper.find(".dd-title").text()).toBe("保持要求")
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    wrapper.unmount()
  })

  it("ignores review shortcuts while editing or composing text", async () => {
    const applyAiReviewAction = vi.fn()
    const client = makeClient({ applyAiReviewAction })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")

    const comment = wrapper.find('[data-testid="dd-comment"]')
    comment.element.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true }))
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "r", isComposing: true }))
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "d", ctrlKey: true }))
    await flushPromises()

    expect(applyAiReviewAction).not.toHaveBeenCalled()
    expect(wrapper.find(".dd-title").text()).toBe("体积计量")
    wrapper.unmount()
  })

  it("jumps to suspected omissions from the stats entry", async () => {
    Element.prototype.scrollIntoView = vi.fn()
    const client = makeClient()
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    const jump = wrapper.find('[data-testid="omission-jump"]')
    expect(jump.text()).toContain("1")
    await jump.trigger("click")
    await flushPromises()

    expect(wrapper.find('[data-testid="omission-card"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("疑似遗漏 1/1")
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })

  it("refreshes terminal chapter snapshots without reloading the document or losing local edits", async () => {
    const base = await makeClient().loadAiRequirements()
    const second = {
      ...base[0], ai_req_id: "AIR-2", title: "保持要求",
      source_quote: "An uncovered requirement shall hold.", source_block_ids: ["B3"],
    }
    const loadAiExtractionStatus = vi.fn()
      .mockResolvedValueOnce({
        schema: "ai-requirements-partial/v1", run_id: "run-1",
        completed: 1, total: 2, complete: false, rows: base,
      })
      .mockResolvedValueOnce({
        schema: "ai-requirements-partial/v1", run_id: "run-1",
        completed: 2, total: 2, complete: false, rows: [...base, second],
      })
    const client = makeClient({ loadAiExtractionStatus })
    const wrapper = mount(DocumentReview, { props: { client, active: true, refreshToken: 0 } })
    await flushPromises()

    expect(wrapper.find('[data-testid="partial-status"]').text()).toContain("1/2")
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    await wrapper.find('[data-testid="dd-comment"]').setValue("尚未保存的核对意见")

    await wrapper.setProps({ refreshToken: 1 })
    await new Promise((resolve) => setTimeout(resolve, 220))
    await flushPromises()

    expect(wrapper.find('[data-testid="partial-status"]').text()).toContain("2/2")
    expect(wrapper.find('[data-testid="doc-stat-reqs"]').text()).toBe("2")
    expect(wrapper.find('[data-testid="dd-comment"]').element).toHaveProperty("value", "尚未保存的核对意见")
    expect(client.loadDocument).toHaveBeenCalledTimes(1)
    expect(client.loadPdfAnnotation).toHaveBeenCalledTimes(2)
  })

  it("shows a terminal incomplete state instead of claiming extraction is still running", async () => {
    const base = await makeClient().loadAiRequirements()
    const client = makeClient({
      loadAiExtractionStatus: vi.fn().mockResolvedValue({
        schema: "ai-requirements-partial/v1",
        run_id: "run-failed",
        completed: 2,
        total: 3,
        complete: true,
        failed: true,
        error: "1 section failed",
        rows: base,
      }),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="partial-status"]').text()).toContain("抽取不完整 2/3")
    expect(wrapper.find('[data-testid="partial-status"]').classes()).toContain("failed")
  })

  it("does not let a delayed initial snapshot overwrite a newer incremental snapshot", async () => {
    const base = await makeClient().loadAiRequirements()
    const second = {
      ...base[0], ai_req_id: "AIR-2", title: "保持要求",
      source_quote: "An uncovered requirement shall hold.", source_block_ids: ["B3"],
    }
    const staleInitial = deferred<{
      schema: "ai-requirements-partial/v1"; run_id: string; completed: number
      total: number; complete: boolean; rows: typeof base
    }>()
    const loadAiExtractionStatus = vi.fn()
      .mockImplementationOnce(() => staleInitial.promise)
      .mockResolvedValueOnce({
        schema: "ai-requirements-partial/v1", run_id: "run-1",
        completed: 2, total: 2, complete: false, rows: [...base, second],
      })
    const client = makeClient({ loadAiExtractionStatus })
    const wrapper = mount(DocumentReview, { props: { client, active: true, refreshToken: 0 } })
    await flushPromises()

    await wrapper.setProps({ refreshToken: 1 })
    await new Promise((resolve) => setTimeout(resolve, 220))
    await flushPromises()
    expect(wrapper.find('[data-testid="doc-stat-reqs"]').text()).toBe("2")

    staleInitial.resolve({
      schema: "ai-requirements-partial/v1", run_id: "run-1",
      completed: 1, total: 2, complete: false, rows: base,
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="doc-stat-reqs"]').text()).toBe("2")
    expect(wrapper.find('[data-testid="partial-status"]').text()).toContain("2/2")
  })

  it("refreshes PDF markers for a partial snapshot while reusing the existing page blob", async () => {
    const base = await makeClient().loadAiRequirements()
    const second = {
      ...base[0], ai_req_id: "AIR-2", title: "保持要求",
      source_quote: "An uncovered requirement shall hold.", source_block_ids: ["B3"],
    }
    const loadAiExtractionStatus = vi.fn()
      .mockResolvedValueOnce({
        schema: "ai-requirements-partial/v1", run_id: "run-1",
        completed: 1, total: 2, complete: false, rows: base,
      })
      .mockResolvedValueOnce({
        schema: "ai-requirements-partial/v1", run_id: "run-1",
        completed: 2, total: 2, complete: false, rows: [...base, second],
      })
    const page = { page_number: 1, file: "page-0001.png", width: 595, height: 842 }
    const loadPdfAnnotation = vi.fn()
      .mockResolvedValueOnce({
        available: true, pages: [page], omission_markers: [], block_zones: [],
        requirement_markers: [{ req_id: "AIR-1", page: 1, rect: { left: 90, top: 20, width: 4, height: 3 } }],
      })
      .mockResolvedValueOnce({
        available: true, pages: [page], omission_markers: [], block_zones: [],
        requirement_markers: [
          { req_id: "AIR-1", page: 1, rect: { left: 90, top: 20, width: 4, height: 3 } },
          { req_id: "AIR-2", page: 1, rect: { left: 90, top: 30, width: 4, height: 3 } },
        ],
      })
    const client = makeClient({ loadAiExtractionStatus, loadPdfAnnotation })
    const wrapper = mount(DocumentReview, { props: { client, active: true, refreshToken: 0 } })
    await flushPromises()
    expect(wrapper.find('[data-testid="pdf-marker-AIR-2"]').exists()).toBe(false)

    await wrapper.setProps({ refreshToken: 1 })
    await new Promise((resolve) => setTimeout(resolve, 220))
    await flushPromises()

    expect(wrapper.find('[data-testid="pdf-marker-AIR-2"]').exists()).toBe(true)
    expect(client.loadPdfPageBlob).toHaveBeenCalledTimes(1)
    expect(client.loadPdfPageBlob).toHaveBeenCalledWith("page-0001.png")
  })

  it("keeps selected item and per-item drafts when the same document session reconnects", async () => {
    const first = await makeClient().loadAiRequirements()
    const second = { ...first[0], ai_req_id: "AIR-2", title: "备用要求" }
    const rows = [...first, second]
    const client1 = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue(rows), applyOmissionAction: vi.fn(),
    })
    const client2 = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue(rows), applyOmissionAction: vi.fn(),
    })
    const wrapper = mount(DocumentReview, {
      props: { client: client1, active: true, sessionKey: "output:e:/out/run" },
    })
    await flushPromises()

    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    await wrapper.find('[data-testid="dd-comment"]').setValue("AIR-1 未保存意见")
    await wrapper.find('[data-testid="dd-module-select"]').setValue("安全")
    await wrapper.find('[data-testid="dd-ownership-select"]').setValue("hardware")
    await wrapper.find('[data-testid="anno-AIR-2"]').trigger("click")
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-comment"]').element).toHaveProperty("value", "AIR-1 未保存意见")

    await wrapper.find('[data-testid="omission-tag"]').trigger("click")
    await wrapper.find('[data-testid="omission-note"]').setValue("B3 未保存备注")
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    await wrapper.setProps({ client: client2 })
    await flushPromises()

    expect(wrapper.find(".dd-title").text()).toBe("体积计量")
    expect(wrapper.find('[data-testid="dd-comment"]').element).toHaveProperty("value", "AIR-1 未保存意见")
    expect(wrapper.find('[data-testid="dd-module-select"]').element).toHaveProperty("value", "安全")
    expect(wrapper.find('[data-testid="dd-ownership-select"]').element).toHaveProperty("value", "hardware")
    await wrapper.find('[data-testid="omission-tag"]').trigger("click")
    expect(wrapper.find('[data-testid="omission-note"]').element).toHaveProperty("value", "B3 未保存备注")
  })

  it("ignores a late omission response from a replaced client generation", async () => {
    const pending = deferred<{ omission_id: string; block_id: string; status: "non_requirement" }>()
    const client1 = makeClient({ applyOmissionAction: vi.fn(() => pending.promise) })
    const client2 = makeClient({ applyOmissionAction: vi.fn() })
    const wrapper = mount(DocumentReview, {
      props: { client: client1, active: true, sessionKey: "output:e:/out/run" },
    })
    await flushPromises()
    await wrapper.find('[data-testid="omission-tag"]').trigger("click")
    await wrapper.find('[data-testid="omission-note"]').setValue("仍需核对")
    await wrapper.find('[data-testid="omission-non-requirement"]').trigger("click")

    await wrapper.setProps({ client: client2 })
    await flushPromises()
    pending.resolve({ omission_id: "OM-B3", block_id: "B3", status: "non_requirement" })
    await flushPromises()

    expect(wrapper.find('[data-testid="doc-stat-omissions"]').text()).toBe("1")
    expect(wrapper.find('[data-testid="omission-note"]').element).toHaveProperty("value", "仍需核对")
  })

  it("handles a structured reconfirmation conflict by refreshing evidence and retaining the draft", async () => {
    const oldRow = {
      ...(await makeClient().loadAiRequirements())[0],
      source_fingerprint: "source-v1", review_subject_fingerprint: "subject-v1",
    }
    const newRow = {
      ...oldRow, title: "体积计量（证据已更新）", source_fingerprint: "source-v2",
      review_subject_fingerprint: "subject-v2", needs_reconfirmation: true,
    }
    const loadAiRequirements = vi.fn()
      .mockResolvedValueOnce([oldRow])
      .mockResolvedValueOnce([newRow])
    const client = makeClient({
      loadAiRequirements,
      applyAiReviewAction: vi.fn().mockRejectedValue(new RequirementApiError(409, {
        error: "AI requirement changed; refresh before adjudicating",
        needs_reconfirmation: true,
      })),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    await wrapper.find('[data-testid="dd-comment"]').setValue("保留这条核对意见")
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    await flushPromises()

    expect(wrapper.find(".dd-title").text()).toBe("体积计量（证据已更新）")
    expect(wrapper.find('[data-testid="dd-reconfirmation"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="dd-comment"]').element).toHaveProperty("value", "保留这条核对意见")
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("已刷新")
  })

  it("shows reconfirmation state and submits the current evidence fingerprints", async () => {
    const client = makeClient({
      loadAiRequirements: vi.fn().mockResolvedValue([{
        ai_req_id: "AIR-1", title: "体积计量", description: "应计量体积", module: "计量",
        status: "draft", source_quote: "The meter shall measure volume.", source_block_ids: ["B2"],
        source_fingerprint: "source-v2", review_subject_fingerprint: "subject-v2",
        needs_reconfirmation: true, review_state: { status: "accepted", module_override: "计量精度" },
      }]),
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-reconfirmation"]').text()).toContain("历史裁决与覆盖值未沿用")
    await wrapper.find('[data-testid="dd-accept"]').trigger("click")
    await flushPromises()

    expect(client.applyAiReviewAction).toHaveBeenCalledWith(expect.objectContaining({
      aiReqId: "AIR-1",
      sourceFingerprint: "source-v2",
      reviewSubjectFingerprint: "subject-v2",
    }))
    expect(wrapper.find('[data-testid="dd-reconfirmation"]').exists()).toBe(false)
  })

  it("triages non-requirements and removes them from the omission count", async () => {
    const applyOmissionAction = vi.fn().mockResolvedValue({
      omission_id: "OM-B3", block_id: "B3", status: "non_requirement", actor: "reviewer",
    })
    const client = makeClient({
      loadOmissionActions: vi.fn().mockResolvedValue({ schema: "omission-actions/v1", states: [] }),
      applyOmissionAction,
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="omission-jump"]').trigger("click")
    await wrapper.find('[data-testid="omission-note"]').setValue("背景说明")
    await wrapper.find('[data-testid="omission-non-requirement"]').trigger("click")
    await flushPromises()

    expect(applyOmissionAction).toHaveBeenCalledWith(expect.objectContaining({
      blockId: "B3", status: "non_requirement", reason: "背景说明",
    }))
    expect(wrapper.find('[data-testid="doc-stat-omissions"]').text()).toBe("0")
  })

  it("runs targeted re-extraction and refreshes requirements and PDF metadata", async () => {
    const first = await makeClient().loadAiRequirements()
    const added = {
      ...first[0], ai_req_id: "AIR-2", title: "保持要求",
      source_quote: "An uncovered requirement shall hold.", source_block_ids: ["B3"],
    }
    const loadAiRequirements = vi.fn()
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce([...first, added])
    const reextractOmission = vi.fn().mockResolvedValue({
      schema: "omission-reextract/v1",
      omission: { omission_id: "OM-B3", block_id: "B3", status: "resolved" },
      supplement: {}, requirements: 1, effective_count: 2, written: ["ai_supplements.jsonl"],
    })
    const client = makeClient({ loadAiRequirements, reextractOmission })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="omission-jump"]').trigger("click")
    await wrapper.find('[data-testid="omission-reextract"]').trigger("click")
    await flushPromises()

    expect(reextractOmission).toHaveBeenCalledWith(expect.objectContaining({
      blockId: "B3", focusLines: ["An uncovered requirement shall hold."],
    }))
    expect(wrapper.find('[data-testid="doc-stat-reqs"]').text()).toBe("2")
    expect(wrapper.find('[data-testid="doc-stat-omissions"]').text()).toBe("0")
    expect(client.loadDocument).toHaveBeenCalledTimes(1)
    expect(client.loadPdfAnnotation).toHaveBeenCalledTimes(2)
  })

  it("keeps page-edge markers and PDF paragraph zones interactive", () => {
    // 工作区可能以 CRLF 签出（core.autocrlf），断言针对 CSS 内容而非行尾
    const source = readFileSync(resolve(__dirname, "../DocumentReview.vue"), "utf-8").replace(/\r\n/g, "\n")
    expect(source).toContain(".doc-paper.pdf-paper {\n  padding: 16px 48px 16px 16px;")
    expect(source).toContain(".doc-paper.pdf-paper { padding: 14px 44px 14px 12px; }")
    expect(source).toContain("cursor: pointer; pointer-events: auto; border-radius: 3px;")
  })

  // 点解析（WP-B）：段落块/表格行按钮 → /spot-extract；成功 toast + 刷新，失败如实原因
  it("spot-extracts a paragraph block and toasts the draft count", async () => {
    const spotExtract = vi.fn().mockResolvedValue({
      schema: "spot-extract/v1", block_id: "B3", row_index: null,
      strategy: "llm", drafts: 2, draft_ids: ["SPOT-B3", "SPOT-B3-2"],
      already_covered: false, written: ["ai_requirements.jsonl"],
    })
    const client = makeClient({ spotExtract })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    const button = wrapper.find('[data-testid="spot-extract-B3"]')
    expect(button.exists()).toBe(true)
    await button.trigger("click")
    await flushPromises()

    expect(spotExtract).toHaveBeenCalledWith(expect.objectContaining({ blockId: "B3" }))
    expect(wrapper.find('[data-testid="doc-message"]').text())
      .toContain("已生成 2 条 draft 需求，进澄清待确认")
  })

  it("spot-extracts a table row with its 1-based row index", async () => {
    const spotExtract = vi.fn().mockResolvedValue({
      schema: "spot-extract/v1", block_id: "T1", row_index: 2,
      strategy: "deterministic_param_row", drafts: 1, draft_ids: ["SPOT-T1-R2"],
      already_covered: false, written: ["ai_requirements.jsonl"],
    })
    const client = makeClient({
      loadDocument: vi.fn().mockResolvedValue({
        count: 1,
        blocks: [{
          block_id: "T1", order: 1, type: "table", text: "No. | P | Req",
          headers: ["No.", "Parameter", "Requirement"],
          header_rows: [["No.", "Parameter", "Requirement"]],
          data_rows: [["1.", "Voltage", "230 V"], ["2.", "Frequency", "50 Hz"]],
          section_path: ["4"], requirement_like: true, noise: false,
        }],
      }),
      spotExtract,
    })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    const button = wrapper.find('[data-testid="spot-extract-row-T1-2"]')
    expect(button.exists()).toBe(true)
    await button.trigger("click")
    await flushPromises()

    expect(spotExtract).toHaveBeenCalledWith(expect.objectContaining({ blockId: "T1", rowIndex: 2 }))
    expect(wrapper.find('[data-testid="doc-message"]').text())
      .toContain("已生成 1 条 draft 需求，进澄清待确认")
  })

  it("surfaces the honest backend error when spot extraction is unavailable", async () => {
    const spotExtract = vi.fn().mockRejectedValue(
      new RequirementApiError(503, { error: "openai_compatible route is not configured" }))
    const client = makeClient({ spotExtract })
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    await wrapper.find('[data-testid="spot-extract-B2"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[data-testid="doc-message"]').text())
      .toContain("openai_compatible route is not configured")
  })

  it("hides spot-extract buttons when the client lacks the capability", async () => {
    const client = makeClient()   // 无 spotExtract 方法
    const wrapper = mount(DocumentReview, { props: { client, active: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="spot-extract-B2"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="spot-extract-B3"]').exists()).toBe(false)
  })
})
