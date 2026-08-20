import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import App from "../App.vue"

function mockBridge(overrides: Record<string, unknown> = {}) {
  Object.defineProperty(window, "ratomizerDesktop", {
    configurable: true,
    value: {
      getApiSession: vi.fn().mockResolvedValue(null),
      getLlmSettings: vi.fn().mockResolvedValue(null),
      openDocument: vi.fn(),
      selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\abnt"),
      openOutput: vi.fn(),
      openPath: vi.fn(),
      startApiSession: vi.fn().mockResolvedValue(null),
      getOutputSummary: vi.fn().mockResolvedValue({ summary: {} }),
      statDeliverables: vi.fn().mockResolvedValue({
        "软件需求列表-成文.xlsx": { exists: false, path: null },
        "document_annotation.html": { exists: true, path: "E:\\out\\abnt\\document_annotation.html" },
        "clarification_questions.xlsx": { exists: false, path: null },
        "run_manifest.json": { exists: true, path: "E:\\out\\abnt\\.ratomizer\\stages\\run_manifest.json" },
      }),
      ...overrides,
    },
  })
}

async function openRunPanel(wrapper: ReturnType<typeof mount>) {
  await wrapper.find('[data-testid="nav-运行"]').trigger("click")
  await flushPromises()
  await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
  await flushPromises()
}

describe("deliverable presence panel", () => {
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

  it("grays missing files and keeps present files openable", async () => {
    mockBridge()
    const wrapper = mount(App)
    await flushPromises()
    await openRunPanel(wrapper)

    const panel = wrapper.find('[data-testid="deliverable-html"]')
    expect(panel.exists()).toBe(true)
    const rows = panel.findAll(".dl-file")
    expect(rows).toHaveLength(4)

    const missingXlsx = rows.find((row) => row.text().includes("软件需求列表-成文.xlsx"))
    expect(missingXlsx?.classes()).toContain("is-missing")
    expect(missingXlsx?.text()).toContain("未生成")
    expect(missingXlsx?.find("button").attributes("disabled")).toBeDefined()

    const presentHtml = rows.find((row) => row.text().includes("document_annotation.html"))
    expect(presentHtml?.classes()).not.toContain("is-missing")
    expect(presentHtml?.text()).not.toContain("未生成")
    expect(presentHtml?.find("button").attributes("disabled")).toBeUndefined()
  })

  it("renders all four files as missing when none exist", async () => {
    mockBridge({
      statDeliverables: vi.fn().mockResolvedValue({
        "软件需求列表-成文.xlsx": { exists: false, path: null },
        "document_annotation.html": { exists: false, path: null },
        "clarification_questions.xlsx": { exists: false, path: null },
        "run_manifest.json": { exists: false, path: null },
      }),
    })
    const wrapper = mount(App)
    await flushPromises()
    await openRunPanel(wrapper)

    const rows = wrapper.find('[data-testid="deliverable-html"]').findAll(".dl-file")
    expect(rows).toHaveLength(4)
    for (const row of rows) {
      expect(row.classes()).toContain("is-missing")
      expect(row.text()).toContain("未生成")
      expect(row.find("button").attributes("disabled")).toBeDefined()
    }
  })
})
