import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import App from "../App.vue"

describe("review workspace shell", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(window, "ratomizerDesktop")
  })

  it("renders the Phase 1 Chinese dashboard structure", () => {
    const wrapper = mount(App)

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

  it("keeps details on the right while the table can scroll horizontally", () => {
    const wrapper = mount(App)

    const workspace = wrapper.find('[data-testid="workspace"]')
    const tableScroll = wrapper.find('[data-testid="requirement-table"]')
    expect(workspace.exists()).toBe(true)
    expect(workspace.classes()).toContain("right-detail-workspace")
    expect(tableScroll.exists()).toBe(true)
    expect(tableScroll.classes()).toContain("independent-table-scroll")
    expect(wrapper.find('[data-testid="detail-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="detail-scroll"]').classes()).toContain("independent-detail-scroll")
  })

  it("updates the selected requirement status from review decisions", async () => {
    const wrapper = mount(App)

    await wrapper.find('[data-testid="row-REQ-2024-0003"]').trigger("click")
    expect(wrapper.find('[data-testid="detail-title"]').text()).toContain("REQ-2024-0003")

    await wrapper.find('[data-testid="decision-rejected"]').trigger("click")

    expect(wrapper.find('[data-testid="detail-status"]').text()).toContain("已拒绝")
    expect(wrapper.find('[data-testid="row-status-REQ-2024-0003"]').text()).toContain("已拒绝")
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

    await wrapper.find('[data-testid="nav-设置"]').trigger("click")
    expect(wrapper.find('[data-testid="settings-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="settings-panel"]').text()).toContain("设置")
    expect(wrapper.find('[data-testid="settings-panel"]').text()).toContain("LLM 富化")

    await wrapper.find('[data-testid="settings-close"]').trigger("click")
    expect(wrapper.find('[data-testid="settings-panel"]').exists()).toBe(false)
  })

  it("saves and tests OpenAI-compatible API settings from the settings panel", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        getLlmSettings: vi.fn().mockResolvedValue({
          enabled: false,
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
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      model: "glm-4-plus",
      apiKeyEnv: "ZHIPU_API_KEY",
      apiKey: "sk-secret",
      temperature: 0.2,
      maxTokens: 2048,
      timeoutS: 20,
      maxRetries: 0,
      concurrency: 2,
    })

    await wrapper.find('[data-testid="settings-test"]').trigger("click")
    expect(window.ratomizerDesktop?.testLlmConnection).toHaveBeenCalledWith({
      enabled: true,
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      model: "glm-4-plus",
      apiKeyEnv: "ZHIPU_API_KEY",
      apiKey: "",
      temperature: 0.2,
      maxTokens: 2048,
      timeoutS: 20,
      maxRetries: 0,
      concurrency: 2,
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="settings-status"]').text()).toContain("调用成功")
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
        })
        return {
          ok: true,
          json: async () => ({ requirement_id: "SREQ-UI-1", status: "accepted" }),
        } as Response
      }
      throw new Error(`Unexpected request: ${String(input)}`)
    })

    const wrapper = mount(App)
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

    expect(fetchMock).toHaveBeenCalledTimes(2)
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
      throw new Error(`Unexpected request: ${String(input)}`)
    })

    const wrapper = mount(App)
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="row-SREQ-TRANSLATE-1"]').exists()).toBe(true)
    })

    await wrapper.find('[data-testid="action-translate"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="translation-text"]').text()).toContain("读取客户端应支持 xDLMS 服务")
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
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
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="empty-requirements"]').exists()).toBe(true)
    })

    expect(wrapper.find('[data-testid="row-REQ-2024-0001"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="detail-title"]').text()).toContain("未选择需求")
  })

  it("runs pipeline, exports requirements, and assembles spec through the desktop bridge", async () => {
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
        aiExtract: vi.fn().mockResolvedValue({
          kind: "ai_extract",
          count: 2,
          merged: { total: 5, ai_behavioral: 2, deterministic_structural: 3 },
          written: ["merged_spec_requirements.json", "merged_spec.xlsx"],
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
          "knowledge_bases/energy_metering.json",
          "knowledge_bases/energy_metering_protocol_layer.json",
          "knowledge_bases/energy_metering_cosem_classes.json",
          "knowledge_bases/compiled_from_obsidian.json",
        ],
        domainPackDir: "domain_packs/dlms_cosem",
      })
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="row-SREQ-RUN-1"]').exists()).toBe(true)
    })
    expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("100%")

    await wrapper.find('[data-testid="action-ai-extract"]').trigger("click")
    expect(window.ratomizerDesktop?.aiExtract).toHaveBeenCalledWith({
      outDir: "E:\\out\\abnt",
      llmRoute: "stub",
    })
    expect(wrapper.find('[data-testid="api-message"]').text()).toContain("2")
    expect(fetchMock).toHaveBeenCalled()
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
          "knowledge_bases/energy_metering.json",
          "knowledge_bases/energy_metering_protocol_layer.json",
          "knowledge_bases/energy_metering_cosem_classes.json",
          "knowledge_bases/compiled_from_obsidian.json",
        ],
        domainPackDir: "domain_packs/dlms_cosem",
      })
    })
    expect(wrapper.find('[data-testid="run-progress-detail"]').text()).toContain("50")
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

  it("keeps the API loading error visible when results cannot be loaded after a run", async () => {
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
    await wrapper.find('[data-testid="action-select-output-dir"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("Origin not allowed")
      expect(wrapper.find('[data-testid="run-progress"]').text()).toContain("运行失败")
    })
    expect(wrapper.find('[data-testid="api-message"]').text()).not.toContain("抽取与审查完成")
  })

  it("passes the LLM enrichment route when assembling with LLM mode enabled", async () => {
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
        aiExtract: vi.fn().mockResolvedValue({ kind: "ai_extract", count: 1, merged: {}, written: [] }),
      },
    })
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response)

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalled()
    })

    await wrapper.find('[data-testid="llm-mode-toggle"]').setValue(true)
    await wrapper.find('[data-testid="action-ai-extract"]').trigger("click")

    expect(window.ratomizerDesktop?.aiExtract).toHaveBeenCalledWith({
      outDir: "E:\\out\\abnt",
      llmRoute: "openai_compatible",
    })
  })

  it("surfaces desktop task failures without leaving the UI silent", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\Appendix 9.docx"),
        openOutput: vi.fn(),
        openPath: vi.fn(),
        runPipeline: vi.fn().mockRejectedValue(new Error("backend exploded")),
      },
    })

    const wrapper = mount(App)
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="api-message"]').text()).toContain("backend exploded")
    })
  })
})
