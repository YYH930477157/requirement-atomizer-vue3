import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "../App.vue"

enableAutoUnmount(afterEach)

// 与 DeliverySettings.spec 同款基础链形状（aiExtract on → runChain 被调用）
const BASE_STAGES = { llmReview: true, aiExtract: true, assemble: false, analyze: false, compose: false, annotationHtml: false }

function mockBridge(chainPayload: Record<string, unknown>) {
  Object.defineProperty(window, "ratomizerDesktop", {
    configurable: true,
    value: {
      getApiSession: vi.fn().mockResolvedValue(null),
      openDocument: vi.fn().mockResolvedValue("C:\\input\\tender.pdf"),
      selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\sbd"),
      getOutputSettings: vi.fn().mockResolvedValue({
        baseUrl: "http://127.0.0.1:8770",
        token: "local-token",
        outputDir: "E:\\out\\sbd",
      }),
      getLlmSettings: vi.fn().mockResolvedValue({ enabled: true, baseUrl: "", model: "" }),
      saveLlmSettings: vi.fn(),
      runPipeline: vi.fn().mockResolvedValue({
        kind: "pipeline",
        out_dir: "E:\\out\\sbd",
        summary: { counts: { requirements: 1 } },
      }),
      runChain: vi.fn().mockResolvedValue({
        kind: "chain",
        out_dir: "E:\\out\\sbd",
        stages: [],
        results: {},
        skipped_stages: [],
        summary: {},
        ...chainPayload,
      }),
      startResultPackage: undefined,
      statDeliverables: vi.fn().mockResolvedValue({
        "document_annotation.html": { exists: false, path: null },
        "clarification_questions.xlsx": { exists: false, path: null },
        "run_manifest.json": { exists: true, path: "E:\\out\\sbd\\run_manifest.json" },
      }),
    },
  })
}

async function driveRun(wrapper: ReturnType<typeof mount>) {
  await wrapper.find('[data-testid="action-open-document"]').trigger("click")
  await wrapper.find('[data-testid="nav-运行"]').trigger("click")
  await flushPromises()
  await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
  await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
  await flushPromises()
}

describe("partial export（守恒未闭合）run summary honesty", () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem("ratomizer.runStages.v3", JSON.stringify(BASE_STAGES))
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response)
  })
  afterEach(() => {
    vi.restoreAllMocks()
    delete (window as unknown as { ratomizerDesktop?: unknown }).ratomizerDesktop
    localStorage.clear()
  })

  it("conservation-blocked：只报功能需求未闭合，不冒充分析表已出", async () => {
    mockBridge({
      conservation_blocked: true,
      conservation_block_error: "功能需求守恒核对未闭合（义务未覆盖 5）",
      partial_export: true,
      pending_marked_rows: 5,
    })
    const wrapper = mount(App)
    await driveRun(wrapper)

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain("功能需求守恒未闭合")
    })
    expect(wrapper.text()).not.toContain("需求分析已出")
    expect(wrapper.text()).not.toContain("需求分析已阻断")
    expect(wrapper.text()).not.toContain("待核分析")
    expect(wrapper.find('[data-testid="software-hint"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain("software_requirements.xlsx")
  })

  it("degraded-only：抽取降级挂在功能需求上，不冒充分析表", async () => {
    mockBridge({ pending_marked_rows: 2 })
    const wrapper = mount(App)
    await driveRun(wrapper)

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain("功能需求含 2 条抽取降级，待核对")
    })
    expect(wrapper.text()).not.toContain("需求分析已出")
    expect(wrapper.text()).not.toContain("需求分析已阻断")
    expect(wrapper.find('[data-testid="software-hint"]').exists()).toBe(false)
  })

  it("干净运行无待核行：不写待核/分析表字样", async () => {
    mockBridge({})
    const wrapper = mount(App)
    await driveRun(wrapper)

    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalled()
    })
    expect(wrapper.text()).not.toContain("待核分析")
    expect(wrapper.text()).not.toContain("需求分析已出")
    expect(wrapper.find('[data-testid="software-hint"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain("software_requirements.xlsx")
  })
})
