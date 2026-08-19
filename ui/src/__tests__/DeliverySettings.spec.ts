import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import App from "../App.vue"

// §20（quality-first 方案）：业务交付设置——翻译模式 off/markers/full；A/B 技术
// 选择收进高级折叠区；off/markers 不把 full-translation 排进链并显式透传模式。

const BASE_STAGES = { aiExtract: true, assemble: false, analyze: false, compose: false, annotationHtml: false }

function mockBridge(overrides: Record<string, unknown> = {}) {
  Object.defineProperty(window, "ratomizerDesktop", {
    configurable: true,
    value: {
      getApiSession: vi.fn().mockResolvedValue(null),
      openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
      selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\abnt"),
      openOutput: vi.fn(),
      openPath: vi.fn(),
      startApiSession: vi.fn().mockResolvedValue({
        baseUrl: "http://127.0.0.1:8770",
        token: "local-token",
        outputDir: "E:\\out\\abnt",
      }),
      getLlmSettings: vi.fn().mockResolvedValue({ enabled: true, baseUrl: "", model: "" }),
      saveLlmSettings: vi.fn(),
      runPipeline: vi.fn().mockResolvedValue({
        kind: "pipeline",
        out_dir: "E:\\out\\abnt",
        summary: { counts: { requirements: 1 } },
      }),
      runChain: vi.fn().mockResolvedValue({ kind: "chain", count: 1, results: {}, summary: {} }),
      ...overrides,
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

describe("delivery settings (§20)", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response)
  })
  afterEach(() => {
    vi.restoreAllMocks()
    delete (window as unknown as { ratomizerDesktop?: unknown }).ratomizerDesktop
  })

  it("exposes translation mode in the business section and keeps A/B toggles in the advanced area", async () => {
    mockBridge()
    const wrapper = mount(App)
    await wrapper.find('[data-testid="nav-设置"]').trigger("click")
    await flushPromises()

    const panel = wrapper.find('[data-testid="settings-panel"]')
    expect(panel.exists()).toBe(true)
    const modeSelect = panel.find('[data-testid="settings-translation-mode"]')
    expect(modeSelect.exists()).toBe(true)
    expect((modeSelect.element as HTMLSelectElement).value).toBe("full")
    // 业务区不含 A/B 技术项；它们在高级折叠区里且默认收起
    const advanced = panel.find('[data-testid="settings-advanced"]')
    expect(advanced.exists()).toBe(true)
    expect((advanced.element as HTMLDetailsElement).open).toBe(false)
    expect(advanced.find('[data-testid="stage-ai-extract"]').exists()).toBe(true)
    expect(advanced.find('[data-testid="stage-llm-review"]').exists()).toBe(true)
    expect(advanced.find('[data-testid="stage-assemble"]').exists()).toBe(true)

    await modeSelect.setValue("off")
    expect(localStorage.getItem("ratomizer.translationMode.v1")).toBe("off")
  })

  it("translation mode off excludes full-translation from the chain and passes the mode through", async () => {
    localStorage.setItem("ratomizer.runStages.v3", JSON.stringify(BASE_STAGES))
    localStorage.setItem("ratomizer.translationMode.v1", "off")
    mockBridge()
    const wrapper = mount(App)
    await driveRun(wrapper)

    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalled()
    })
    const call = (window.ratomizerDesktop?.runChain as ReturnType<typeof vi.fn>).mock.calls[0][0]
    expect(call.stages).not.toContain("full-translation")
    expect(call.translationMode).toBe("off")
    expect(call.llmRoute).toBe("openai_compatible")
  })

  it("default translation mode keeps the existing chain shape (full translation, no explicit mode key)", async () => {
    localStorage.setItem("ratomizer.runStages.v3", JSON.stringify(BASE_STAGES))
    mockBridge()
    const wrapper = mount(App)
    await driveRun(wrapper)

    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalled()
    })
    const call = (window.ratomizerDesktop?.runChain as ReturnType<typeof vi.fn>).mock.calls[0][0]
    expect(call.stages).toContain("full-translation")
    expect(call).not.toHaveProperty("translationMode")
  })

  it("defaults atom LLM review off so Run does not review shredded atoms", async () => {
    mockBridge()
    const wrapper = mount(App)
    await driveRun(wrapper)

    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalled()
    })
    expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalledWith(
      expect.objectContaining({ skipReview: true, llmRoute: undefined }),
    )
  })

  it("hides atom diagnostics from daily nav until the advanced setting is on", async () => {
    mockBridge()
    const wrapper = mount(App)
    await flushPromises()
    expect(wrapper.find('[data-testid="nav-审查工作台"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="nav-功能需求"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="nav-覆盖审计"]').exists()).toBe(true)

    await wrapper.find('[data-testid="nav-设置"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="settings-show-atom-diagnostics"]').setValue(true)
    await wrapper.find('[data-testid="settings-close"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[data-testid="nav-审查工作台"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="nav-审查工作台"]').text()).toContain("原子诊断")
    expect(localStorage.getItem("ratomizer.showAtomDiagnostics.v1")).toBe("1")
  })

  it("run overview leads with functional requirements, not atoms", async () => {
    mockBridge()
    const wrapper = mount(App)
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    const panel = wrapper.find('[data-testid="run-paths-panel"]')
    expect(panel.find('[data-testid="ov-functional"]').text()).toContain("功能需求")
    expect(panel.find('[data-testid="ov-deliverable"]').text()).toContain("交付状态")
    expect(panel.text()).not.toContain("原子需求")
  })
})
