import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import App from "../App.vue"

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
    Reflect.deleteProperty(window, "ratomizerDesktop")
    localStorage.clear()
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

    expect(wrapper.find('[data-testid="run-paths-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-board"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-atomize"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-llm-review"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-ai-extract"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="run-stage-functional-synthesis"]').exists()).toBe(true)

    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    progressHandler({ stage: "pipeline_stage", step: "atomize", status: "ok", percent: 100 })
    progressHandler({ stage: "llm_review", completed: 1, total: 2, percent: 50 })
    await flushPromises()

    expect(wrapper.find('[data-testid="run-stage-atomize"]').text()).toContain("已完成")
    expect(wrapper.find('[data-testid="run-stage-llm-review"]').text()).toContain("50%")
  })

  it("updates the selected requirement status from review decisions", async () => {
    const wrapper = mount(App)
    await openReview(wrapper)

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
          visionCapable: false,
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

    await wrapper.find('[data-testid="settings-llm-mode"]').setValue(true)
    await wrapper.find('[data-testid="settings-vision-capable"]').setValue(true)
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

    await wrapper.find('[data-testid="settings-test"]').trigger("click")
    expect(window.ratomizerDesktop?.testLlmConnection).toHaveBeenCalledWith({
      enabled: true,
      visionCapable: true,
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      model: "glm-4-plus",
      apiKeyEnv: "ZHIPU_API_KEY",
      apiKey: "",
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

  it("uses optimized annotation layout when the configured model is visual", async () => {
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
        layoutMode: "optimized",
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

    expect(fetchMock).toHaveBeenCalledTimes(3)   // requirements + review-insights + action
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

    expect(fetchMock).toHaveBeenCalledTimes(3)   // requirements + review-insights + action
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

  it("runs pipeline then the enabled AI-extract stage as one chain from the Run button", async () => {
    // 开启 AI 抽取阶段：点一次「运行」应先跑 runPipeline 再自动接 aiExtract
    localStorage.setItem("ratomizer.runStages.v2",
      JSON.stringify({ aiExtract: true, assemble: false, analyze: false, compose: false, annotationHtml: false }))
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

  function deliverableBridge(overrides: Record<string, unknown> = {}) {
    return {
      getApiSession: vi.fn().mockResolvedValue(null),
      // 已保存 LLM 设置：onMounted 恢复（2026-07-08 审计 A2）——链条测试借此走 LLM 开启路径
      getLlmSettings: vi.fn().mockResolvedValue({
        enabled: true, baseUrl: "http://127.0.0.1:11434/v1", model: "m", apiKeyEnv: "",
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
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")

    await vi.waitFor(() => {
      const card = wrapper.find('[data-testid="run-stage-functional-synthesis"]').text()
      expect(card).toContain("未启用")
      expect(card).not.toContain("待完成")
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
})
