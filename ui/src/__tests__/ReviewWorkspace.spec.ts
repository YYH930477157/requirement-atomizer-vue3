import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "../App.vue"

enableAutoUnmount(afterEach)

const ALL_STAGES_OFF = JSON.stringify({ aiExtract: false, assemble: false, analyze: false, compose: false, annotationHtml: false })

async function openReview(wrapper: ReturnType<typeof mount>) {
  await wrapper.find('[data-testid="nav-审查工作台"]').trigger("click")
  await flushPromises()
}

describe("review workspace shell", () => {
  beforeEach(() => {
    // 默认「运行」只跑基础解析+审查，不追加交付物链——各测试按需在 mount 前开启对应阶段
    localStorage.setItem("ratomizer.runStages.v2", ALL_STAGES_OFF)
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    Reflect.deleteProperty(window, "ratomizerDesktop")
    localStorage.clear()
    window.history.replaceState({}, "", "/")
  })

  it("renders the Phase 1 Chinese dashboard structure", async () => {
    const wrapper = mount(App)
    await openReview(wrapper)

    expect(wrapper.text()).toContain("标准需求抽取与审查平台")
    expect(wrapper.text()).toContain("GUI Phase 1")
    expect(wrapper.text()).toContain("总数")
    expect(wrapper.text()).toContain("已接受")
    expect(wrapper.text()).toContain("待专家")
    expect(wrapper.text()).toContain("① 原始需求")
    expect(wrapper.text()).toContain("② 中文翻译")
    expect(wrapper.text()).toContain("③ 原子化需求")
    expect(wrapper.text()).not.toContain("③ AI 理解的需求")
    expect(wrapper.text()).toContain("REQ-2024-0001")
    expect(wrapper.find('[data-testid="phase1-stats"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="requirement-table"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="detail-panel"]').exists()).toBe(true)
  })

  it("keeps details on the right while the table can scroll horizontally", async () => {
    const wrapper = mount(App)
    await openReview(wrapper)

    const workspace = wrapper.find('[data-testid="workspace"]')
    const tableScroll = wrapper.find('[data-testid="requirement-table"]')
    expect(workspace.exists()).toBe(true)
    expect(workspace.classes()).toContain("right-detail-workspace")
    expect(tableScroll.exists()).toBe(true)
    expect(tableScroll.classes()).toContain("independent-table-scroll")
    expect(wrapper.find('[data-testid="detail-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="detail-scroll"]').classes()).toContain("independent-detail-scroll")
  })

  it("lands on the functional review view by default (G9-4)", async () => {
    const wrapper = mount(App)
    await flushPromises()
    // 落地页默认「功能需求」评审视图；run 面板不再默认显示
    expect(wrapper.find('[data-testid="functional-review"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-paths-panel"]').exists()).toBe(false)
    const navBtn = wrapper.find('[data-testid="nav-功能需求"]')
    expect(navBtn.exists()).toBe(true)
    expect(navBtn.classes()).toContain("active")
  })

  it("groups nav items into collapsed visual sections without dropping entries (G9-7)", async () => {
    const wrapper = mount(App)
    await flushPromises()
    const navText = wrapper.find(".side-nav").text()
    // 评审相关项视觉收敛为分组标题
    expect(navText).toContain("评审")
    expect(navText).toContain("文档与账本")
    // 全部 nav 项 testid 保留——不删项、不改路由
    for (const label of ["运行", "审查工作台", "功能需求", "文档批注", "Claim 账本", "文档渲染"]) {
      expect(wrapper.find(`[data-testid="nav-${label}"]`).exists()).toBe(true)
    }
  })

  it("keeps translate enabled when a requirement is selected (G9-10 sentinel cleanup)", async () => {
    const wrapper = mount(App)
    await openReview(wrapper)
    // 有需求行时 hasSelectedRequirement=true；翻译按钮不再依赖 magic-string 哨兵比较
    expect(wrapper.find('[data-testid="action-translate"]').attributes("disabled")).toBeUndefined()
  })

  it("shows a run stage board with per-stage progress", async () => {
    type ProgressHandler = (event: { stage: string; step?: string; status?: string; completed?: number; total?: number; percent?: number }) => void
    let progressHandler: ProgressHandler = () => {
      throw new Error("progress handler was not registered")
    }
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        runPipeline: vi.fn().mockResolvedValue({ kind: "pipeline", out_dir: "E:\\out\\abnt", summary: {} }),
        startApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "E:\\out\\abnt",
        }),
        onTaskProgress: vi.fn((handler: ProgressHandler) => {
          progressHandler = handler
          return () => undefined
        }),
      },
    })
    const wrapper = mount(App)
    // 落地页默认 functional（G9-4）；run 面板需显式切到「运行」nav
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[data-testid="run-paths-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-board"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-atomize"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-llm-review"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-ai-extract"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-functional-synthesis"]').exists()).toBe(true)

    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    progressHandler({ stage: "pipeline_stage", step: "atomize", status: "ok", percent: 100 })
    progressHandler({ stage: "llm_review", completed: 1, total: 2, percent: 50 })
    await flushPromises()

    expect(wrapper.find('[data-testid="run-stage-atomize"]').text()).toContain("已完成")
    expect(wrapper.find('[data-testid="run-stage-llm-review"]').text()).toContain("50%")
    expect(wrapper.find('[data-testid="run-stage-llm-review"]').attributes("aria-current")).toBe("step")
    expect(wrapper.find('[data-testid="run-stage-llm-review"] .stage-signal').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-relay-atomize"]').classes()).toContain("relay-handoff")
    expect(wrapper.find('[data-testid="run-relay-llm-review"]').classes()).toContain("relay-bypass")

    progressHandler({ stage: "llm_review", completed: 2, total: 2, percent: 100 })
    await flushPromises()
    expect(wrapper.find('[data-testid="run-relay-atomize"]').classes()).toContain("relay-complete")
  })

  it("previews moving stage progress from the demo URL without a backend task", async () => {
    vi.useFakeTimers()
    window.history.replaceState({}, "", "/?demoProgress=1")
    const getApiSession = vi.fn().mockResolvedValue(null)
    const getLlmSettings = vi.fn().mockResolvedValue(null)
    const runPipeline = vi.fn()
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: { getApiSession, getLlmSettings, runPipeline },
    })
    const wrapper = mount(App)
    await flushPromises()

    const atomize = wrapper.find('[data-testid="run-stage-atomize"]')
    expect(atomize.classes()).toContain("stage-running")
    expect(atomize.find(".stage-bar").classes()).toContain("is-indeterminate")
    expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("动效演示 1/10")
    expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("0%")
    expect(getApiSession).not.toHaveBeenCalled()
    expect(getLlmSettings).not.toHaveBeenCalled()
    expect(runPipeline).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(atomize.find(".stage-bar").classes()).not.toContain("is-indeterminate")
    expect(atomize.text()).toContain("24%")

    wrapper.unmount()
  })

  it("disables review decisions and keeps local status unchanged without an API session", async () => {
    const wrapper = mount(App)
    await openReview(wrapper)

    await wrapper.find('[data-testid="row-REQ-2024-0003"]').trigger("click")
    expect(wrapper.find('[data-testid="detail-title"]').text()).toContain("REQ-2024-0003")
    const reject = wrapper.find('[data-testid="decision-rejected"]')
    expect(reject.attributes("disabled")).toBeDefined()
    const detailStatus = wrapper.find('[data-testid="detail-status"]').text()
    const rowStatus = wrapper.find('[data-testid="row-status-REQ-2024-0003"]').text()

    await reject.trigger("click")

    expect(wrapper.find('[data-testid="detail-status"]').text()).toBe(detailStatus)
    expect(wrapper.find('[data-testid="row-status-REQ-2024-0003"]').text()).toBe(rowStatus)
  })

  it("uses the Phase 1 side navigation for document, export, and settings actions", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        getLlmSettings: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        aiExtract: vi.fn(),
      },
    })
    const wrapper = mount(App)

    await wrapper.find('[data-testid="nav-文档批注"]').trigger("click")
    expect(wrapper.find('[data-testid="doc-review"]').exists()).toBe(true)  // 文档批注视图

    await wrapper.find('[data-testid="nav-Claim 账本"]').trigger("click")
    expect(wrapper.find('[data-testid="claim-ledger"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="claim-ledger"]').text()).toContain("双写观察期 · 结构待审阻断 Ledger Ready")

    await wrapper.find('[data-testid="nav-设置"]').trigger("click")
    expect(wrapper.find('[data-testid="settings-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="settings-panel"]').text()).toContain("设置")
    expect(wrapper.find('[data-testid="settings-panel"]').text()).toContain("LLM 富化")

    await wrapper.find('[data-testid="settings-close"]').trigger("click")
    expect(wrapper.find('[data-testid="settings-panel"]').exists()).toBe(false)
  })

  it("saves and tests API settings while preserving existing vision capability metadata", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        getLlmSettings: vi.fn().mockResolvedValue({
          enabled: false,
          visionCapable: true,
          baseUrl: "http://127.0.0.1:11434/v1",
          model: "qwen2.5:14b",
          apiKeyEnv: "RATOMIZER_LLM_API_KEY",
          temperature: 0,
          maxTokens: 1024,
          timeoutS: 60,
          maxRetries: 3,
        }),
        saveLlmSettings: vi.fn().mockResolvedValue({
          enabled: true,
          visionCapable: true,
          baseUrl: "https://open.bigmodel.cn/api/paas/v4",
          model: "glm-4-plus",
          apiKeyEnv: "ZHIPU_API_KEY",
          temperature: 0.2,
          maxTokens: 2048,
          timeoutS: 20,
          maxRetries: 0,
          concurrency: 2,
        }),
        testLlmConnection: vi.fn().mockResolvedValue({ ok: true, message: "调用成功" }),
      },
    })
    const wrapper = mount(App)

    await wrapper.find('[data-testid="nav-设置"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="settings-base-url"]').element).toHaveProperty("value", "http://127.0.0.1:11434/v1")
    })
    expect(wrapper.find('[data-testid="settings-vision-capable"]').exists()).toBe(false)

    await wrapper.find('[data-testid="settings-llm-mode"]').setValue(true)
    await wrapper.find('[data-testid="settings-base-url"]').setValue("https://open.bigmodel.cn/api/paas/v4")
    await wrapper.find('[data-testid="settings-model"]').setValue("glm-4-plus")
    await wrapper.find('[data-testid="settings-api-key-env"]').setValue("ZHIPU_API_KEY")
    await wrapper.find('[data-testid="settings-api-key"]').setValue("sk-secret")
    await wrapper.find('[data-testid="settings-temperature"]').setValue("0.2")
    await wrapper.find('[data-testid="settings-max-tokens"]').setValue("2048")
    await wrapper.find('[data-testid="settings-timeout"]').setValue("20")
    await wrapper.find('[data-testid="settings-max-retries"]').setValue("0")
    await wrapper.find('[data-testid="settings-concurrency"]').setValue("2")

    await wrapper.find('[data-testid="settings-save"]').trigger("click")
    expect(window.ratomizerDesktop?.saveLlmSettings).toHaveBeenCalledWith({
      enabled: true,
      visionCapable: true,
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      model: "glm-4-plus",
      apiKeyEnv: "ZHIPU_API_KEY",
      apiKey: "sk-secret",
      temperature: 0.2,
      maxTokens: 2048,
      timeoutS: 20,
      maxRetries: 0,
      concurrency: 2,
      selfCheck: true,
    })

    await wrapper.find('[data-testid="settings-api-key"]').setValue("sk-test-only")
    await wrapper.find('[data-testid="settings-test"]').trigger("click")
    expect(window.ratomizerDesktop?.testLlmConnection).toHaveBeenCalledWith({
      enabled: true,
      visionCapable: true,
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      model: "glm-4-plus",
      apiKeyEnv: "ZHIPU_API_KEY",
      apiKey: "sk-test-only",
      temperature: 0.2,
      maxTokens: 2048,
      timeoutS: 20,
      maxRetries: 0,
      concurrency: 2,
      selfCheck: true,
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="settings-status"]').text()).toContain("调用成功")
    })
  })

  it("keeps original PDF annotation layout when the configured model is visual", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        getLlmSettings: vi.fn().mockResolvedValue({ enabled: false, visionCapable: true }),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\abnt"),
        exportAnnotationHtml: vi.fn().mockResolvedValue({
          kind: "annotation_html",
          path: "E:\\out\\abnt\\document_annotation.html",
        }),
        openPath: vi.fn(),
      },
    })
    const wrapper = mount(App)
    await flushPromises()

    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await wrapper.find('[data-testid="nav-文档批注"]').trigger("click")
    await wrapper.find('[data-testid="action-export-html"]').trigger("click")

    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.exportAnnotationHtml).toHaveBeenCalledWith({
        outDir: "E:\\out\\abnt",
        route: undefined,
        layoutMode: "pdf_original",
      })
    })
  })

  it("loads real requirements from the desktop API session and persists decisions", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "E:\\Codex\\out\\run",
        }),
        openDocument: vi.fn(),
        openOutput: vi.fn(),
        openPath: vi.fn(),
      },
    })
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).endsWith("/requirements?limit=5000")) {
        expect(init?.headers).toMatchObject({ "X-Requirement-Atomizer-Token": "local-token" })
        return {
          ok: true,
          json: async () => [
            {
              stable_req_id: "SREQ-UI-1",
              requirement_type: "security",
              object_name: "Security Setup",
              description: "The meter shall reject invalid keys.",
              source_quote: "Invalid keys shall be rejected.",
              domain: "security_policy",
              domain_tags: ["security_policy", "key_management"],
              section_path: ["Security"],
              confidence: 0.91,
              target_fingerprint: "sha256:target-ui-1",
              target_publication_revision: "sha256:publication-ui-1",
              target_authority_write_revision: "sha256:authority-ui-1",
              review_state: { requirement_id: "SREQ-UI-1", status: "expert_pending" },
              review: { risk: "high", review_notes: ["Confirm key scope"] },
            },
          ],
        } as Response
      }
      if (String(input).endsWith("/review-actions")) {
        expect(init?.headers).toMatchObject({
          "Content-Type": "application/json",
          "X-Requirement-Atomizer-Token": "local-token",
        })
        expect(JSON.parse(String(init?.body))).toMatchObject({
          requirement_id: "SREQ-UI-1",
          status: "accepted",
          expected_target_fingerprint: "sha256:target-ui-1",
          expected_target_publication_revision: "sha256:publication-ui-1",
          expected_target_authority_write_revision: "sha256:authority-ui-1",
        })
        return {
          ok: true,
          json: async () => ({ requirement_id: "SREQ-UI-1", status: "accepted" }),
        } as Response
      }
      if (String(input).endsWith("/review-insights")) {
        return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
      }
      throw new Error(`Unexpected request: ${String(input)}`)
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="row-SREQ-UI-1"]').exists()).toBe(true)
    })

    expect(wrapper.text()).toContain("Security Setup")
    expect(wrapper.text()).toContain("安全策略")
    expect(wrapper.text()).toContain("安全要求")
    expect(wrapper.text()).toContain("security_policy · key_management")
    expect(wrapper.find('[data-testid="detail-status"]').text()).toContain("待专家确认")

    await wrapper.find('[data-testid="decision-accepted"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="detail-status"]').text()).toContain("已接受")
    })

    expect(fetchMock).toHaveBeenCalledTimes(5)   // requirements + table reviews + review-insights + result-package + action
  })

  it("shows only pending table structure reviews and confirms one table in a single action", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "E:\\Codex\\out\\run",
        }),
      },
    })
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith("/requirements?limit=5000")) {
        return { ok: true, json: async () => [] } as Response
      }
      if (url.endsWith("/table-reviews")) {
        return {
          ok: true,
          json: async () => ({
            schema: "table-review-view/v1",
            tables: [
              {
                table_id: "TBL-PENDING",
                title: "Auxiliary output",
                structure_review_status: "pending",
                review_mode: "pending",
                cell_count: 3,
                review_count: 1,
                evidence_fingerprint: "sha256:table-v1",
                cells: [
                  {
                    cell_id: "CELL-1",
                    text: "Mode",
                    row_index: 2,
                    column_index: 1,
                    role: "row_header",
                    disposition: "review",
                  },
                ],
              },
              {
                table_id: "TBL-READY",
                title: "Automatic table",
                structure_review_status: "ready",
                review_mode: "automatic",
                cell_count: 4,
                review_count: 0,
                evidence_fingerprint: "sha256:ready",
                cells: [],
              },
            ],
          }),
        } as Response
      }
      if (url.endsWith("/table-review-actions")) {
        expect(JSON.parse(String(init?.body))).toEqual({
          table_id: "TBL-PENDING",
          expected_evidence_fingerprint: "sha256:table-v1",
          role_mapping: {
            "CELL-1": { role: "row_header", disposition: "excluded" },
          },
          actor: "vue3-ui",
          reason: "Confirmed table structure in Vue3 UI",
        })
        return {
          ok: true,
          json: async () => ({
            table_id: "TBL-PENDING",
            structure_review_status: "ready",
          }),
        } as Response
      }
      if (url.endsWith("/review-insights")) {
        return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
      }
      if (url.endsWith("/result-package")) {
        return { ok: true, json: async () => ({ layout: "package_v1", package: null }) } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="table-review-band"]').exists()).toBe(true)
    })

    expect(wrapper.find('[data-testid="table-review-TBL-PENDING"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="table-review-TBL-READY"]').exists()).toBe(false)
    const decisionSelects = wrapper.findAll(
      '[data-testid="table-review-TBL-PENDING"] .table-review-cell select',
    )
    expect(decisionSelects).toHaveLength(1)
    expect(decisionSelects[0].findAll("option").map((option) => option.attributes("value")))
      .toEqual(["target", "excluded"])
    await wrapper.find('[data-testid="confirm-table-TBL-PENDING"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="table-review-band"]').exists()).toBe(false)
    })
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/table-review-actions"))).toHaveLength(1)
  })

  it("refreshes a partial table action and keeps only the remaining claim cell", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "E:\\Codex\\out\\run",
        }),
      },
    })
    let tableLoadCount = 0
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith("/requirements?limit=5000")) {
        return { ok: true, json: async () => [] } as Response
      }
      if (url.endsWith("/table-reviews")) {
        tableLoadCount += 1
        const cells = tableLoadCount === 1
          ? [
              { cell_id: "CELL-1", text: "Mode", row_index: 2, column_index: 1, role: "row_header", disposition: "review" },
              { cell_id: "CELL-2", text: "Enabled", row_index: 2, column_index: 2, role: "data", disposition: "review" },
            ]
          : [
              { cell_id: "CELL-2", text: "Enabled", row_index: 2, column_index: 2, role: "data", disposition: "review" },
            ]
        return {
          ok: true,
          json: async () => ({
            schema: "table-review-view/v1",
            tables: [{
              table_id: "TBL-PARTIAL",
              title: "Auxiliary output",
              structure_review_status: "pending",
              review_mode: "pending",
              cell_count: 2,
              review_count: cells.length,
              evidence_fingerprint: tableLoadCount === 1 ? "sha256:table-v1" : "sha256:table-v2",
              cells,
            }],
          }),
        } as Response
      }
      if (url.endsWith("/table-review-actions")) {
        return {
          ok: true,
          json: async () => ({
            table_id: "TBL-PARTIAL",
            structure_review_status: "pending",
            partial: true,
            completed_cell_ids: ["CELL-1"],
            remaining_cell_ids: ["CELL-2"],
            decision_error: {
              type: "TimeoutError",
              message: "synthetic second-cell failure",
              retryable: true,
            },
          }),
        } as Response
      }
      if (url.endsWith("/review-insights")) {
        return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
      }
      if (url.endsWith("/result-package")) {
        return { ok: true, json: async () => ({ layout: "package_v1", package: null }) } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => {
      expect(wrapper.findAll('[data-testid="table-review-TBL-PARTIAL"] .table-review-cell')).toHaveLength(2)
    })

    await wrapper.find('[data-testid="confirm-table-TBL-PARTIAL"]').trigger("click")
    await vi.waitFor(() => {
      const cells = wrapper.findAll('[data-testid="table-review-TBL-PARTIAL"] .table-review-cell')
      expect(cells).toHaveLength(1)
      expect(cells[0].text()).toContain("Enabled")
      expect(cells[0].text()).not.toContain("Mode")
    })
    expect(tableLoadCount).toBe(2)
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("已完成 1 个 Claim 裁决，仍有 1 个待确认")
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/table-review-actions"))).toHaveLength(1)
  })

  it("refreshes A-track evidence after a 409 and retains the review draft", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "E:\\Codex\\out\\run",
        }),
      },
    })
    let requirementsLoadCount = 0
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith("/requirements?limit=5000")) {
        requirementsLoadCount += 1
        const refreshed = requirementsLoadCount > 1
        return {
          ok: true,
          json: async () => [{
            stable_req_id: "SREQ-CONFLICT-1",
            requirement_type: "functional",
            object_name: refreshed ? "Updated interface" : "Original interface",
            description: refreshed ? "The refreshed requirement evidence." : "The original requirement evidence.",
            source_quote: refreshed ? "Refreshed source evidence." : "Original source evidence.",
            target_fingerprint: refreshed ? "sha256:target-v2" : "sha256:target-v1",
            target_publication_revision: refreshed ? "sha256:publication-v2" : "sha256:publication-v1",
            target_authority_write_revision: refreshed ? "sha256:authority-v2" : "sha256:authority-v1",
            review_state: { requirement_id: "SREQ-CONFLICT-1", status: "expert_pending" },
          }],
        } as Response
      }
      if (url.endsWith("/review-actions")) {
        expect(JSON.parse(String(init?.body))).toMatchObject({
          requirement_id: "SREQ-CONFLICT-1",
          expected_target_fingerprint: "sha256:target-v1",
          expected_target_publication_revision: "sha256:publication-v1",
          expected_target_authority_write_revision: "sha256:authority-v1",
        })
        return {
          ok: false,
          status: 409,
          json: async () => ({
            error: "requirement evidence changed",
            needs_reconfirmation: true,
          }),
        } as Response
      }
      if (url.endsWith("/review-insights")) {
        return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => expect(wrapper.text()).toContain("The original requirement evidence."))
    await wrapper.get("textarea.comment-box").setValue("保留这条 A 轨审查意见")
    await wrapper.get('[data-testid="decision-accepted"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.text()).toContain("The refreshed requirement evidence."))

    expect(requirementsLoadCount).toBe(2)
    expect(wrapper.get("textarea.comment-box").element).toHaveProperty("value", "保留这条 A 轨审查意见")
    expect(wrapper.get('[data-testid="api-message"]').text()).toContain("已刷新，请核对后重新裁决")
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/review-actions"))).toHaveLength(1)
  })

  it("translates the selected requirement through the local API", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "E:\\Codex\\out\\run",
        }),
        openDocument: vi.fn(),
        openOutput: vi.fn(),
        openPath: vi.fn(),
      },
    })
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).endsWith("/requirements?limit=5000")) {
        return {
          ok: true,
          json: async () => [
            {
              stable_req_id: "SREQ-TRANSLATE-1",
              requirement_type: "communication",
              object: "Reading client",
              requirement: 'Reading client shall support xDLMS Service: Block transfer with "GET".',
              source_quote: 'Reading client shall support xDLMS Service: Block transfer with "GET".',
              confidence: 0.82,
              review_state: { requirement_id: "SREQ-TRANSLATE-1", status: "candidate" },
            },
          ],
        } as Response
      }
      if (String(input).endsWith("/translations")) {
        expect(init?.headers).toMatchObject({
          "Content-Type": "application/json",
          "X-Requirement-Atomizer-Token": "local-token",
        })
        expect(JSON.parse(String(init?.body))).toMatchObject({
          requirement_id: "SREQ-TRANSLATE-1",
          text: 'Reading client shall support xDLMS Service: Block transfer with "GET".',
          context: "Reading client",
        })
        return {
          ok: true,
          json: async () => ({
            requirement_id: "SREQ-TRANSLATE-1",
            translation: "读取客户端应支持 xDLMS 服务：使用 GET 的块传输。",
          }),
        } as Response
      }
      if (String(input).endsWith("/review-insights")) {
        return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
      }
      throw new Error(`Unexpected request: ${String(input)}`)
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="row-SREQ-TRANSLATE-1"]').exists()).toBe(true)
    })

    await wrapper.find('[data-testid="action-translate"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="translation-text"]').text()).toContain("读取客户端应支持 xDLMS 服务")
    })

    const translationCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/translations"),
    )
    expect(translationCalls).toHaveLength(1)
  })

  it("restores a delayed desktop session through the ready event and opens the review workspace", async () => {
    let readyHandler: ((session: RequirementAtomizerApiSession) => void) | undefined
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        onApiSessionReady: vi.fn((handler: (session: RequirementAtomizerApiSession) => void) => {
          readyHandler = handler
          return () => undefined
        }),
        getRecentSessions: vi.fn().mockResolvedValue([]),
        getOutputSummary: vi.fn().mockResolvedValue({
          kind: "summary",
          out_dir: "E:\\out\\restored",
          summary: {
            run_manifest: {
              stages: {
                atomize: { status: "ok" },
                "ai-extract": { status: "ok" },
              },
            },
          },
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith("/requirements?limit=5000")) {
        return {
          ok: true,
          json: async () => [{
            stable_req_id: "SREQ-RESTORED",
            requirement_type: "functional",
            object_name: "Restored meter",
            description: "Restored requirement",
            review_state: { status: "candidate" },
          }],
        } as Response
      }
      if (url.endsWith("/review-insights")) {
        return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
      }
      if (url.endsWith("/manifest")) {
        return { ok: true, json: async () => ({ input: "C:\\input\\restored.docx" }) } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const wrapper = mount(App)
    expect(readyHandler).toBeDefined()
    readyHandler?.({
      baseUrl: "http://127.0.0.1:8770",
      token: "restored-token",
      outputDir: "E:\\out\\restored",
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="row-SREQ-RESTORED"]').exists()).toBe(true)
    })

    expect(wrapper.find('[data-testid="nav-审查工作台"]').classes()).toContain("active")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    expect(wrapper.find('[data-testid="selected-output-dir"]').text()).toContain("E:\\out\\restored")
    expect(wrapper.find('[data-testid="selected-input-path"]').text()).toContain("C:\\input\\restored.docx")
  })

  it("opens a persisted recent output without running the pipeline again", async () => {
    const startApiSession = vi.fn().mockResolvedValue({
      baseUrl: "http://127.0.0.1:8770",
      token: "recent-token",
      outputDir: "E:\\out\\previous",
    })
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        getRecentSessions: vi.fn().mockResolvedValue([{
          outputDir: "E:\\out\\previous",
          label: "standard.docx",
          openedAt: "2026-08-02T12:00:00.000Z",
          exists: true,
          isOutput: true,
        }]),
        startApiSession,
        getOutputSummary: vi.fn().mockResolvedValue({
          kind: "summary", out_dir: "E:\\out\\previous", summary: { run_manifest: { stages: {} } },
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith("/requirements?limit=5000")) {
        return { ok: true, json: async () => [{
          stable_req_id: "SREQ-HISTORY",
          requirement_type: "functional",
          object_name: "Historical meter",
          description: "Historical requirement",
          review_state: { status: "candidate" },
        }] } as Response
      }
      if (url.endsWith("/review-insights")) {
        return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
      }
      if (url.endsWith("/manifest")) {
        return { ok: true, json: async () => ({ input: "C:\\input\\previous.docx" }) } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const wrapper = mount(App)
    // 落地页默认 functional（G9-4）；recent sessions 在 run home，需切到「运行」nav
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-testid="recent-open-0"]').exists()).toBe(true))
    await wrapper.find('[data-testid="recent-open-0"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-testid="row-SREQ-HISTORY"]').exists()).toBe(true))

    expect(startApiSession).toHaveBeenCalledWith("E:\\out\\previous")
    expect(wrapper.find('[data-testid="nav-审查工作台"]').classes()).toContain("active")
  })

  it("clears mock rows when the connected API session has no requirements", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "E:\\Codex\\out\\empty",
        }),
        openDocument: vi.fn(),
        openOutput: vi.fn(),
        openPath: vi.fn(),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response)

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="empty-requirements"]').exists()).toBe(true)
    })

    expect(wrapper.find('[data-testid="row-REQ-2024-0001"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="detail-title"]').text()).toContain("未选择需求")
  })

  it("opens a user-selected existing output without rerunning analysis", async () => {
    const openOutput = vi.fn().mockResolvedValue({
      baseUrl: "http://127.0.0.1:8770",
      token: "existing-token",
      outputDir: "E:\\out\\existing",
    })
    const runPipeline = vi.fn()
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        getRecentSessions: vi.fn().mockResolvedValue([]),
        openOutput,
        runPipeline,
        getOutputSummary: vi.fn().mockResolvedValue({
          kind: "summary", out_dir: "E:\\out\\existing", summary: { run_manifest: {} },
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url.endsWith("/requirements?limit=5000")) {
        return { ok: true, json: async () => [{
          stable_req_id: "SREQ-EXISTING", requirement_type: "functional",
          object_name: "Existing meter", description: "Existing output requirement",
          review_state: { status: "candidate" },
        }] } as Response
      }
      if (url.endsWith("/review-insights")) {
        return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
      }
      if (url.endsWith("/manifest")) {
        return { ok: true, json: async () => ({ input: "C:\\input\\existing.docx" }) } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-existing-output"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-testid="row-SREQ-EXISTING"]').exists()).toBe(true))

    expect(openOutput).toHaveBeenCalledOnce()
    expect(runPipeline).not.toHaveBeenCalled()
  })

  it("tries the empty selected directory session without reusing the old review session", async () => {
    const startApiSession = vi.fn().mockResolvedValue(null)
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8765", token: "old-token", outputDir: "E:\\out\\old",
        }),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\new-empty"),
        getOutputSummary: vi.fn().mockResolvedValue({
          kind: "summary", out_dir: "E:\\out\\new-empty",
          summary: { counts: { requirements: 0, reviews: 0, review_states: 0 }, run_manifest: {} },
        }),
        startApiSession,
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).endsWith("/requirements?limit=5000")) {
        return { ok: true, json: async () => [{
          stable_req_id: "SREQ-OLD", requirement_type: "functional", object_name: "Old output",
          description: "Old requirement", review_state: { status: "accepted" },
        }] } as Response
      }
      return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => expect(wrapper.find('[data-testid="row-SREQ-OLD"]').exists()).toBe(true))

    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await flushPromises()

    expect(startApiSession).toHaveBeenCalledWith("E:\\out\\new-empty")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    expect(wrapper.find('[data-testid="selected-output-dir"]').text()).toContain("E:\\out\\new-empty")
    await openReview(wrapper)
    expect(wrapper.find('[data-testid="empty-requirements"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("裁决已禁用")
  })

  it("switches an existing output directory to its own API session and requirements", async () => {
    const startApiSession = vi.fn().mockResolvedValue({
      baseUrl: "http://127.0.0.1:8770", token: "new-token", outputDir: "E:\\out\\new",
    })
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8765", token: "old-token", outputDir: "E:\\out\\old",
        }),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\new"),
        getOutputSummary: vi.fn().mockResolvedValue({
          kind: "summary", out_dir: "E:\\out\\new",
          summary: { counts: { requirements: 1 }, run_manifest: {} },
        }),
        startApiSession,
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith("/requirements?limit=5000")) {
        const isNew = url.startsWith("http://127.0.0.1:8770")
        expect(init?.headers).toMatchObject({
          "X-Requirement-Atomizer-Token": isNew ? "new-token" : "old-token",
        })
        return { ok: true, json: async () => [{
          stable_req_id: isNew ? "SREQ-NEW" : "SREQ-OLD",
          requirement_type: "functional", object_name: isNew ? "New output" : "Old output",
          description: isNew ? "New requirement" : "Old requirement", review_state: { status: "draft" },
        }] } as Response
      }
      return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => expect(wrapper.find('[data-testid="row-SREQ-OLD"]').exists()).toBe(true))

    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await vi.waitFor(() => expect(wrapper.find('[data-testid="row-SREQ-NEW"]').exists()).toBe(true))

    expect(startApiSession).toHaveBeenCalledWith("E:\\out\\new")
    expect(wrapper.find('[data-testid="row-SREQ-OLD"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="decision-accepted"]').attributes("disabled")).toBeUndefined()
  })

  it("disconnects the old review client when the selected output session fails to start", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8765", token: "old-token", outputDir: "E:\\out\\old",
        }),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\broken"),
        getOutputSummary: vi.fn().mockResolvedValue({
          kind: "summary", out_dir: "E:\\out\\broken",
          summary: { counts: { requirements: 1 }, run_manifest: {} },
        }),
        startApiSession: vi.fn().mockRejectedValue(new Error("API server startup timed out")),
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).endsWith("/requirements?limit=5000")) {
        return { ok: true, json: async () => [{
          stable_req_id: "SREQ-OLD", requirement_type: "functional", object_name: "Old output",
          description: "Old requirement", review_state: { status: "accepted" },
        }] } as Response
      }
      return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => expect(wrapper.find('[data-testid="row-SREQ-OLD"]').exists()).toBe(true))

    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[data-testid="row-SREQ-OLD"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="empty-requirements"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("裁决已禁用")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("API server startup timed out")
  })

  it("runs pipeline then the enabled AI-extract stage as one chain from the Run button", async () => {
    // 开启 AI 抽取阶段：点一次「运行」应先跑 runPipeline 再自动接 aiExtract
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: true, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    const startResultPackage = vi.fn().mockResolvedValue({
      kind: "result_package_start",
      package: {
        analysis_status: "completed",
        active_attempt: { run_id: "RUN-ui-lifecycle", status: "running" },
      },
    })
    const completeResultPackage = vi.fn().mockResolvedValue({
      kind: "result_package_complete",
      package: { analysis_status: "completed", active_attempt: null },
    })
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
        startResultPackage,
        completeResultPackage,
        failResultPackage: vi.fn(),
        runPipeline: vi.fn().mockResolvedValue({
          kind: "pipeline",
          out_dir: "E:\\out\\abnt",
          summary: { counts: { requirements: 1 } },
        }),
        runChain: vi.fn().mockResolvedValue({
          kind: "chain",
          count: 2,
          results: {},
          summary: {},
        }),
      },
    })
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [
        {
          stable_req_id: "SREQ-RUN-1",
          requirement_type: "functional",
          object_name: "Meter",
          description: "The meter shall run.",
          source_quote: "The meter shall run.",
          confidence: 0.95,
          review_state: { requirement_id: "SREQ-RUN-1", status: "accepted" },
        },
      ],
    } as Response)

    const wrapper = mount(App)

    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalledWith({
        inputPath: "C:\\input\\Appendix 9.docx",
        outDir: "E:\\out\\abnt",
        skipReview: false,
        llmRoute: undefined,
        reviewScope: undefined,
        chunkChars: 3500,
        kbPaths: [
          "knowledge_bases/compiled_from_obsidian.json",
        ],
        domainPackDir: "domain_packs/dlms_cosem",
      })
    })
    // 单次 Run 自动接上后端 chain（LLM 关 → stub）
    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalledWith({
        outDir: "E:\\out\\abnt",
        stages: ["ai-extract"],
        llmRoute: "stub",
        templatePath: undefined,
      })
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("100%")
    })
    expect(startResultPackage).toHaveBeenCalledWith({
      outDir: "E:\\out\\abnt",
      inputPath: "C:\\input\\Appendix 9.docx",
      stages: ["atomize", "llm-review", "ai-extract"],
    })
    expect(completeResultPackage).toHaveBeenCalledWith({
      outDir: "E:\\out\\abnt",
      runId: "RUN-ui-lifecycle",
      completedStages: ["atomize", "llm-review", "ai-extract"],
    })
    expect(wrapper.find('[data-testid="result-package-status"]').text()).toContain("已完成")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("AI 抽取")
    await openReview(wrapper)
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="row-SREQ-RUN-1"]').exists()).toBe(true)
    })
    expect(fetchMock).toHaveBeenCalled()
  })

  it("keeps completed outputs when the API session refresh times out after a run", async () => {
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: false, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\abnt"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        startApiSession: vi.fn().mockRejectedValue(new Error("API server startup timed out")),
        runPipeline: vi.fn().mockResolvedValue({
          kind: "pipeline",
          out_dir: "E:\\out\\abnt",
          summary: { counts: { requirements: 1 } },
          api_warning: "API server startup timed out",
        }),
      },
    })

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalled()
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("100%")
    })
    expect(wrapper.find('[data-testid="run-progress-detail"]').text()).toContain("全部阶段完成")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("运行完成")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("输出目录")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("API")
  })

  it("reruns a legacy output directory without package tracking (I5)", async () => {
    // legacy 目录重跑：startResultPackage 返回 layout=legacy（主进程分类后不创建
    // marker/.ratomizer）——运行按旧管线完成，不要求 run_id，也不触 complete/fail
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: false, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    const startResultPackage = vi.fn().mockResolvedValue({
      kind: "result_package_start",
      ok: true,
      layout: "legacy",
      package: null,
    })
    const completeResultPackage = vi.fn()
    const failResultPackage = vi.fn()
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\legacy"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        startApiSession: vi.fn().mockRejectedValue(new Error("API server startup timed out")),
        startResultPackage,
        completeResultPackage,
        failResultPackage,
        runPipeline: vi.fn().mockResolvedValue({
          kind: "pipeline",
          out_dir: "E:\\out\\legacy",
          summary: { counts: { requirements: 1 } },
          api_warning: "API server startup timed out",
        }),
      },
    })

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("100%")
    })
    expect(startResultPackage).toHaveBeenCalledOnce()
    expect(completeResultPackage).not.toHaveBeenCalled()
    expect(failResultPackage).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="run-progress"]').text()).not.toContain("运行失败")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("运行完成")
    expect(wrapper.find('[data-testid="result-package-status"]').text()).toContain("旧版结果")
  })

  it("shows a partial-completion notice instead of a run failure (I6)", async () => {
    // 部分阶段降级：completeResultPackage 返回稳定错误码 requested_stage_partial——
    // UI 如实显示「分析未完成（部分阶段降级）」，不走「运行失败」也不把尝试记为失败
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: true, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    const startResultPackage = vi.fn().mockResolvedValue({
      kind: "result_package_start",
      package: {
        analysis_status: "running",
        active_attempt: { run_id: "RUN-partial", status: "running" },
      },
    })
    const completeResultPackage = vi.fn().mockResolvedValue({
      kind: "result_package_complete",
      ok: false,
      code: "requested_stage_partial",
      message: "requested stage is not complete: ai-extract (failed)",
    })
    const failResultPackage = vi.fn()
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
        startResultPackage,
        completeResultPackage,
        failResultPackage,
        runPipeline: vi.fn().mockResolvedValue({
          kind: "pipeline",
          out_dir: "E:\\out\\abnt",
          summary: { counts: { requirements: 1 } },
        }),
        runChain: vi.fn().mockResolvedValue({
          kind: "chain",
          count: 2,
          results: {},
          summary: {},
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      expect(completeResultPackage).toHaveBeenCalled()
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("分析未完成（部分阶段降级）")
    })
    expect(wrapper.find('[data-testid="run-progress"]').text()).not.toContain("运行失败")
    expect(failResultPackage).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="result-package-status"]').text()).toContain("未完成")
  })

  it("keeps the current review session when opening an existing output fails (S8)", async () => {
    // 选错目录/分类失败：保留当前审查会话——只有新 API 成功接管后才允许断开旧会话
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8765", token: "old-token", outputDir: "E:\\out\\old",
        }),
        openOutput: vi.fn().mockRejectedValue(new Error("结果目录标志已损坏或版本不受支持")),
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).endsWith("/requirements?limit=5000")) {
        return { ok: true, json: async () => [{
          stable_req_id: "SREQ-OLD", requirement_type: "functional", object_name: "Old output",
          description: "Old requirement", review_state: { status: "accepted" },
        }] } as Response
      }
      return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
    })

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => expect(wrapper.find('[data-testid="row-SREQ-OLD"]').exists()).toBe(true))

    await wrapper.find('[data-testid="action-open-existing-output"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[data-testid="row-SREQ-OLD"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("无法打开已有结果")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("结果目录标志已损坏")
  })

  it("surfaces a modified-result notice when explicit verification fails (S5)", async () => {
    // 打开已有结果的显式完整校验：交付物/完成证据哈希与 marker 不一致时，
    // 后端 503 result_package_modified——UI 如实显示「结果文件已被修改」，不静默吞掉
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8765", token: "old-token", outputDir: "E:\\out\\pkg",
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes("/result-package") && url.includes("verify=1")) {
        return {
          ok: false,
          status: 503,
          json: async () => ({
            error: "result_package_modified",
            detail: "结果文件已被修改：deliverable changed: summary.md",
            retryable: false,
          }),
        } as Response
      }
      if (url.endsWith("/requirements?limit=5000")) {
        return { ok: true, json: async () => [] } as Response
      }
      return { ok: true, json: async () => ({ available: false, suggestions: [] }) } as Response
    })

    const wrapper = mount(App)

    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("结果文件已被修改")
    })
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("summary.md")
  })

  it("derives the default output directory from the Electron documents root (S16)", async () => {
    // 未选输出目录时默认落到 Electron documents 派生目录——禁止硬编码 E:\Codex（换机即失效）
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: false, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    const runPipeline = vi.fn().mockResolvedValue({
      kind: "pipeline",
      out_dir: "C:\\Users\\Tester\\Documents\\requirement-atomizer-runs\\Appendix 9",
      summary: { counts: { requirements: 1 } },
      api_warning: "API server startup timed out",
    })
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        getDefaultOutputRoot: vi.fn().mockResolvedValue("C:\\Users\\Tester\\Documents\\requirement-atomizer-runs"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        startApiSession: vi.fn().mockRejectedValue(new Error("API server startup timed out")),
        runPipeline,
      },
    })

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.getDefaultOutputRoot).toHaveBeenCalled()
    })
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      expect(runPipeline).toHaveBeenCalled()
    })
    const usedOutDir = String(runPipeline.mock.calls[0][0].outDir)
    expect(usedOutDir).toBe("C:\\Users\\Tester\\Documents\\requirement-atomizer-runs\\Appendix 9")
    expect(usedOutDir).not.toContain("E:\\Codex")
  })

  it("collapses long global messages to one line with an expand toggle", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\demo"),
        startApiSession: vi.fn().mockRejectedValue(new Error(
          "API server startup timed out after 30000 ms while waiting for the local backend ready payload; retries exhausted")),
      },
    })

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("无法连接输出目录")
    })

    const toggle = wrapper.find('[data-testid="api-message-toggle"]')
    expect(toggle.exists()).toBe(true)
    expect(wrapper.find(".global-message-text").classes()).toContain("clamped")
    await toggle.trigger("click")
    expect(wrapper.find(".global-message-text").classes()).not.toContain("clamped")
    await toggle.trigger("click")
    expect(wrapper.find(".global-message-text").classes()).toContain("clamped")
  })

  function deliverableBridge(overrides: Record<string, unknown> = {}) {
    return {
      getApiSession: vi.fn().mockResolvedValue(null),
      // 已保存 LLM 设置：onMounted 恢复（2026-07-08 审计 A2）——链条测试借此走 LLM 开启路径
      getLlmSettings: vi.fn().mockResolvedValue({
        enabled: true, visionCapable: true,
        baseUrl: "http://127.0.0.1:11434/v1", model: "m", apiKeyEnv: "",
        temperature: 0.1, maxTokens: 2048, timeoutS: 60, maxRetries: 2, concurrency: 2, selfCheck: true,
      }),
      openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
      selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\abnt"),
      openOutput: vi.fn(),
      openPath: vi.fn(),
      startApiSession: vi.fn().mockResolvedValue({
        baseUrl: "http://127.0.0.1:8770", token: "local-token", outputDir: "E:\\out\\abnt",
      }),
      runPipeline: vi.fn().mockResolvedValue({ kind: "pipeline", out_dir: "E:\\out\\abnt", summary: {} }),
      aiExtract: vi.fn().mockResolvedValue({
        kind: "ai_extract", count: 2, merged: {}, written: ["merged_spec.xlsx"], summary: {},
        consistency: { duplicate_groups: 3, obis_values_differ: 1, uncovered_requirement_like: 5 },
      }),
      assembleSpec: vi.fn().mockResolvedValue({
        kind: "assemble", count: 42, written: ["assembled_spec.json", "dlms_cosem_spec.xlsx"], summary: {},
      }),
      runRequirementsAnalysis: vi.fn().mockResolvedValue({
        kind: "requirements_analysis",
        analysis: { analysis_count: 30, route: "stub", enriched: 0, enrich_degraded: 0 },
        written: ["software_requirements.xlsx", "engineering_analysis.json"], summary: {},
      }),
      composeEngineering: vi.fn().mockResolvedValue({
        kind: "compose", count: 12, written: ["engineering_requirements/engineering_requirements.json"], summary: {},
      }),
      runChain: vi.fn().mockResolvedValue({
        kind: "chain", count: 2,
        consistency: { duplicate_groups: 3, obis_values_differ: 1, uncovered_requirement_like: 5 },
        analysis: { analysis_count: 30, route: "stub", enriched: 0, enrich_degraded: 0 },
        readiness: { verdict: "READY", reasons: [] }, questions: 0,
        results: {}, summary: {},
      }),
      ...overrides,
    }
  }

  it("runs all enabled deliverable stages including annotation HTML as one Run chain", async () => {
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: true, assemble: true, analyze: true, compose: true, annotationHtml: true }))
    Object.defineProperty(window, "ratomizerDesktop", { configurable: true, value: deliverableBridge() })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => [] } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    // 一次 Run 发一条后端 chain 命令（编排在后端；LLM 关 → stub）
    await vi.waitFor(() =>
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalledWith({
        outDir: "E:\\out\\abnt",
        stages: ["ai-extract", "functional-synthesis", "assemble", "requirements-analysis", "clarification-report", "compose", "export-annotation-html"],
        // bridge 提供已保存 enabled 设置 → onMounted 恢复（审计 A2）→ 真 LLM 路由 + 分析阶段过门控
        llmRoute: "openai_compatible", templatePath: undefined,
        annotationLayoutMode: "pdf_original",
      }))
    await vi.waitFor(() =>
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("软件需求分析"))
    // 一致性闭环：AI 抽取阶段的报表摘要透出到跑完消息
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("疑似跨章重复 3 组")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("OBIS 数值待核 1")
  })

  it("disabled stages are skipped in the Run chain", async () => {
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: true, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    Object.defineProperty(window, "ratomizerDesktop", { configurable: true, value: deliverableBridge() })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => [] } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() =>
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalledWith(
        expect.objectContaining({ stages: ["ai-extract", "functional-synthesis"] })))
  })

  it("chain stages use openai_compatible routes when the LLM toggle is on", async () => {
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: true, assemble: true, analyze: true, compose: false, annotationHtml: false }))
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: deliverableBridge({
        runRequirementsAnalysis: vi.fn().mockResolvedValue({
          kind: "requirements_analysis",
          analysis: { analysis_count: 1, route: "openai_compatible", enriched: 1, enrich_degraded: 0 },
          written: ["software_requirements.xlsx"], summary: {},
        }),
      }),
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => [] } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="llm-mode-toggle"]').setValue(true)
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() =>
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalledWith(
        expect.objectContaining({
          stages: ["ai-extract", "functional-synthesis", "assemble", "requirements-analysis", "clarification-report"],
          llmRoute: "openai_compatible",
        })))
    await vi.waitFor(() =>
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("软件需求分析"))
  })

  it("surfaces review insights suggestions after session load", async () => {
    // E5（0714 批次二）：裁决复盘建议上屏——此前 review_insights.json 零消费者
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770", token: "t", outputDir: "E:\\out\\abnt",
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/review-insights")) {
        return {
          ok: true,
          json: async () => ({
            available: true,
            suggestions: ["模块「时钟」被专家改为「预付费」共 3 次——考虑调整关键词边界。"],
          }),
        } as Response
      }
      return { ok: true, json: async () => [] } as Response
    })

    const wrapper = mount(App)
    // 落地页默认 functional（G9-4）；review insights 在 run home，需切到「运行」nav
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await vi.waitFor(() => {
      const panel = wrapper.find('[data-testid="review-insights"]')
      expect(panel.exists()).toBe(true)
      expect(panel.text()).toContain("预付费")
      expect(panel.text()).toContain("裁决复盘建议（1）")
    })
  })

  it("runs a limited LLM test pass from the test button", async () => {
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
        runPipeline: vi.fn().mockResolvedValue({
          kind: "pipeline",
          out_dir: "E:\\out\\abnt",
          summary: { counts: { requirements: 1 } },
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response)

    const wrapper = mount(App)

    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await wrapper.find('[data-testid="llm-mode-toggle"]').setValue(true)
    await wrapper.find('[data-testid="action-test-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalledWith({
        inputPath: "C:\\input\\Appendix 9.docx",
        outDir: "E:\\out\\abnt",
        skipReview: false,
        llmRoute: "openai_compatible",
        reviewScope: "targeted",
        llmReviewLimit: 50,
        chunkChars: 3500,
        kbPaths: [
          "knowledge_bases/compiled_from_obsidian.json",
        ],
        domainPackDir: "domain_packs/dlms_cosem",
      })
    })
    expect(wrapper.find('[data-testid="run-progress-detail"]').text()).toContain("50")
  })

  it("test run appends a sampled AI extraction and reports sample stats", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\abnt"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        startApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770", token: "local-token", outputDir: "E:\\out\\abnt",
        }),
        runPipeline: vi.fn().mockResolvedValue({ kind: "pipeline", out_dir: "E:\\out\\abnt", summary: {} }),
        runChain: vi.fn().mockResolvedValue({
          kind: "chain", count: 12,
          sampled: { sections: 10, total_sections: 54 },
          quality: { coverage_pct: 78.5 },
          analysis: { analysis_count: 11, enriched: 9, enrich_degraded: 2, route: "openai_compatible" },
          readiness: { verdict: "READY", reasons: [] }, questions: 3,
          results: {}, summary: {},
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => [] } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-test-pipeline"]').trigger("click")

    // 测试运行 = 一条样本链命令（1/5 试抽 + 分析 + 澄清，强制 openai_compatible）
    await vi.waitFor(() =>
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalledWith({
        outDir: "E:\\out\\abnt",
        stages: ["ai-extract", "functional-synthesis", "requirements-analysis", "clarification-report"],
        llmRoute: "openai_compatible", templatePath: undefined, sampleRatio: 0.2,
      }))
    await vi.waitFor(() => {
      const message = wrapper.find('[data-testid="api-message"]').text()
      expect(message).toContain("试抽样本 10/54 章")
      expect(message).toContain("12 条")
      expect(message).toContain("78.5%")
      expect(message).toContain("软件需求 11 条")
      expect(message).toContain("富化 9、降级 2")   // 部分降级可见（0714 批次一 E1a）
      expect(message).toContain("software_requirements.xlsx")
      expect(message).toContain("就绪判定 READY")
      expect(message).toContain("必答澄清 3 条")
    })
  })

  it("disabling the rule-candidate LLM review skips review in both run modes", async () => {
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ llmReview: false, aiExtract: false, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        startApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770", token: "local-token", outputDir: "E:\\out\\abnt",
        }),
        runPipeline: vi.fn().mockResolvedValue({ kind: "pipeline", out_dir: "E:\\out\\abnt", summary: {} }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => [] } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="llm-mode-toggle"]').setValue(true)
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() =>
      expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalledWith(
        expect.objectContaining({ skipReview: true, llmRoute: undefined })))
  })

  it("shows module and precise backend classification for ABNT extracted rows", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "C:\\Users\\YYHwudi\\Desktop\\Canna-29\\test2",
        }),
        openDocument: vi.fn(),
        openOutput: vi.fn(),
        openPath: vi.fn(),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [
        {
          stable_req_id: "SREQ-ABNT-UI",
          requirement_type: "cosem_attribute_access",
          object: "Clock",
          requirement: "The Clock object shall expose time attributes.",
          domain: "access_control",
          domain_tags: ["access_control", "cosem_object", "meter_function"],
          section_path: ["2 20 Control of"],
          source_refs: ["BLK-002001"],
          confidence: 0.77,
          review_state: { requirement_id: "SREQ-ABNT-UI", status: "candidate" },
        },
      ],
    } as Response)

    const wrapper = mount(App)
    await openReview(wrapper)
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="row-SREQ-ABNT-UI"]').exists()).toBe(true)
    })

    expect(wrapper.find('[data-testid="requirement-table"]').text()).toContain("访问控制")
    expect(wrapper.find('[data-testid="requirement-table"]').text()).toContain("COSEM 属性访问")
    expect(wrapper.find('[data-testid="detail-panel"]').text()).toContain("模块")
    expect(wrapper.find('[data-testid="detail-panel"]').text()).toContain("细分类")
    expect(wrapper.find('[data-testid="detail-panel"]').text()).toContain("cosem_attribute_access")
    expect(wrapper.find('[data-testid="detail-panel"]').text()).toContain("access_control · cosem_object · meter_function")
    expect(wrapper.find('[data-testid="detail-panel"]').text()).toContain("2 20 Control of")
  })

  it("shows selected paths and waits for Run before parsing", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        selectOutputDir: vi.fn().mockResolvedValue("E:\\out\\abnt"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        runPipeline: vi.fn(),
      },
    })

    const wrapper = mount(App)

    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="selected-input-path"]').text()).toContain("C:\\input\\Appendix 9.docx")
    expect(window.ratomizerDesktop?.runPipeline).not.toHaveBeenCalled()

    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    expect(wrapper.find('[data-testid="selected-output-dir"]').text()).toContain("E:\\out\\abnt")
    expect(window.ratomizerDesktop?.runPipeline).not.toHaveBeenCalled()
  })

  it("shows percentage progress while a pipeline run is active", async () => {
    let resolveRun!: (payload: { kind: string; out_dir: string }) => void
    const runPromise = new Promise<{ kind: string; out_dir: string }>((resolve) => {
      resolveRun = resolve
    })
    type ProgressHandler = (event: { stage: string; completed: number; total: number; percent: number }) => void
    let progressHandler: ProgressHandler = () => {
      throw new Error("progress handler was not registered")
    }
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
        runPipeline: vi.fn().mockReturnValue(runPromise),
        onTaskProgress: vi.fn((handler: ProgressHandler) => {
          progressHandler = handler
          return vi.fn()
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")

    void wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("%")
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("运行")
      expect(window.ratomizerDesktop?.onTaskProgress).toHaveBeenCalled()
      expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalled()
    })
    progressHandler({ stage: "llm_review", completed: 2, total: 5, percent: 40 })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("AI 审查 2/5")
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("40%")
    })

    resolveRun({ kind: "pipeline", out_dir: "E:\\out\\abnt" })
    await flushPromises()
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("100%")
    })
  })

  it("keeps completed outputs when results cannot be loaded after a run", async () => {
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
        runPipeline: vi.fn().mockResolvedValue({ kind: "pipeline", out_dir: "E:\\out\\abnt" }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ error: "Origin not allowed" }),
    } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("Origin not allowed")
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("运行完成")
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("100%")
    })
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("输出目录")
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("无需重跑 AI")
  })

  it("passes the LLM enrichment route to the AI-extract stage when LLM mode is on", async () => {
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: true, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        startApiSession: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:8770",
          token: "local-token",
          outputDir: "E:\\out\\abnt",
        }),
        runPipeline: vi.fn().mockResolvedValue({ kind: "pipeline", out_dir: "E:\\out\\abnt" }),
        runChain: vi.fn().mockResolvedValue({ kind: "chain", count: 1, results: {}, summary: {} }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="llm-mode-toggle"]').setValue(true)
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runChain).toHaveBeenCalledWith(
        expect.objectContaining({
          outDir: "E:\\out\\abnt",
          stages: ["ai-extract", "functional-synthesis"],
          llmRoute: "openai_compatible",
        }))
    })
  })

  it("marks functional synthesis disabled when LLM and analysis are off", async () => {
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: true, assemble: false, analyze: false, compose: false, annotationHtml: false }))
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: deliverableBridge({ getLlmSettings: vi.fn().mockResolvedValue(null) }),
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => [] } as Response)

    const wrapper = mount(App)
    await flushPromises()
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      const card = wrapper.find('[data-testid="run-stage-functional-synthesis"]').text()
      expect(card).toContain("未启用")
      expect(card).not.toContain("待完成")
    })
  })

  it("surfaces desktop task failures without leaving the UI silent", async () => {
    type ProgressHandler = (event: { stage: string; step?: string; status?: string; percent?: number }) => void
    let progressHandler: ProgressHandler = () => {
      throw new Error("progress handler was not registered")
    }
    let rejectPipeline: (error: Error) => void = () => {
      throw new Error("pipeline reject handler was not registered")
    }
    const pipelineResult = new Promise<never>((_resolve, reject) => {
      rejectPipeline = reject
    })
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        runPipeline: vi.fn().mockReturnValue(pipelineResult),
        onTaskProgress: vi.fn((handler: ProgressHandler) => {
          progressHandler = handler
          return () => undefined
        }),
      },
    })

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    void wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.onTaskProgress).toHaveBeenCalled()
    })
    progressHandler({ stage: "pipeline_stage", step: "atomize", status: "running", percent: 35 })
    await flushPromises()
    expect(wrapper.find('[data-testid="run-stage-atomize"]').classes()).toContain("stage-running")
    expect(wrapper.find('[data-testid="run-relay-atomize"]').classes()).toContain("relay-ready")

    rejectPipeline(new Error("backend exploded"))
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("backend exploded")
    })
    expect(wrapper.find('[data-testid="run-stage-atomize"]').classes()).toContain("stage-failed")
    expect(wrapper.find('[data-testid="run-stage-atomize"]').attributes("aria-current")).toBeUndefined()
    expect(wrapper.find('[data-testid="run-relay-atomize"]').classes()).toContain("relay-blocked")
  })

  it("chain step transition marks previous stage done and keeps card percent from inner events", async () => {
    // 真实反馈 2026-07-14:AI抽取卡在"运行中 14%"而后台已完成——链级百分比(2/7)被
    // 写进阶段卡片、且完成的阶段没人翻绿。锁:步名变化→上一步翻绿;链百分比不进卡片。
    const runPromise = new Promise<{ kind: string; out_dir: string }>(() => {})
    type AnyEvent = { stage: string; step?: string; status?: string; completed?: number; total?: number; percent?: number }
    let progressHandler: (event: AnyEvent) => void = () => {
      throw new Error("progress handler was not registered")
    }
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\input\doc.pdf"),
        selectOutputDir: vi.fn().mockResolvedValue("E:\out\demo"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        startApiSession: vi.fn().mockResolvedValue(null),
        runPipeline: vi.fn().mockReturnValue(runPromise),
        onTaskProgress: vi.fn((handler: (event: AnyEvent) => void) => {
          progressHandler = handler
          return vi.fn()
        }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => [] } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    void wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.onTaskProgress).toHaveBeenCalled()
    })

    progressHandler({ stage: "ai_extract", completed: 40, total: 100, percent: 40 })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="run-stage-ai-extract"]').text()).toContain("40%")
    })
    progressHandler({ stage: "chain", step: "ai-extract", completed: 1, total: 7, percent: 14 })
    progressHandler({ stage: "chain", step: "functional-synthesis", completed: 1, total: 7, percent: 14 })
    await vi.waitFor(() => {
      const extractCard = wrapper.find('[data-testid="run-stage-ai-extract"]').text()
      expect(extractCard).toContain("已完成")             // 步名变化 → 上一步翻绿
      expect(extractCard).not.toContain("14%")            // 链百分比不覆盖卡片
      const synthCard = wrapper.find('[data-testid="run-stage-functional-synthesis"]').text()
      expect(synthCard).toContain("功能重组")
      expect(synthCard).not.toContain("14%")
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("2/7")
    })
  })

  it("warns when a running stage goes quiet instead of silently looking stuck", async () => {
    // 单章 LLM 调用可能数分钟无事件——超过阈值后界面必须区分"慢"与"死"
    vi.useFakeTimers()
    try {
      const runPromise = new Promise<{ kind: string; out_dir: string }>(() => {})
      type AnyEvent = { stage: string; step?: string; status?: string; completed?: number; total?: number; percent?: number }
      let progressHandler: (event: AnyEvent) => void = () => {
        throw new Error("progress handler was not registered")
      }
      Object.defineProperty(window, "ratomizerDesktop", {
        configurable: true,
        value: {
          getApiSession: vi.fn().mockResolvedValue(null),
          openDocument: vi.fn().mockResolvedValue("C:\input\doc.pdf"),
          selectOutputDir: vi.fn().mockResolvedValue("E:\out\demo"),
          openOutput: vi.fn(),
          openPath: vi.fn(),
          startApiSession: vi.fn().mockResolvedValue(null),
          runPipeline: vi.fn().mockReturnValue(runPromise),
          onTaskProgress: vi.fn((handler: (event: AnyEvent) => void) => {
            progressHandler = handler
            return vi.fn()
          }),
        },
      })
      vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => [] } as Response)

      const wrapper = mount(App)
      await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="nav-运行"]').trigger("click")
    await flushPromises()
      await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
      void wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
      await flushPromises()

      progressHandler({ stage: "ai_extract", completed: 11, total: 46, percent: 24 })
      await flushPromises()
      expect(wrapper.find('[data-testid="run-stage-ai-extract"]').text()).toContain("运行中 24%")
      expect(wrapper.find('[data-testid="run-stall-ai-extract"]').exists()).toBe(false)

      vi.advanceTimersByTime(70_000)   // 超过 60s 停滞阈值 + 5s 心跳
      await flushPromises()
      expect(wrapper.find('[data-testid="run-stage-ai-extract"]').text()).toContain("已用时")
      expect(wrapper.find('[data-testid="run-stall-ai-extract"]').text()).toContain("无新进度")
      expect(wrapper.find('[data-testid="run-stall-hint"]').text()).toContain("AI抽取")

      progressHandler({ stage: "ai_extract", completed: 12, total: 46, percent: 26 })
      await flushPromises()
      expect(wrapper.find('[data-testid="run-stall-ai-extract"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="run-stall-hint"]').exists()).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})
