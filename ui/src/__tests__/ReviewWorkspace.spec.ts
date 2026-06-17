import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import App from "../App.vue"

describe("review workspace shell", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(window, "ratomizerDesktop")
  })

  it("renders the enterprise review workspace structure", () => {
    const wrapper = mount(App)

    expect(wrapper.text()).toContain("标准需求抽取与审查平台")
    expect(wrapper.text()).toContain("审查工作区")
    expect(wrapper.text()).toContain("人工审查")
    expect(wrapper.text()).toContain("需求详情")
    expect(wrapper.text()).toContain("REQ-2024-0001")
    expect(wrapper.find('[data-testid="workflow-stepper"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="requirement-table"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="detail-panel"]').exists()).toBe(true)
  })

  it("updates the selected requirement status from review decisions", async () => {
    const wrapper = mount(App)

    await wrapper.find('[data-testid="row-REQ-2024-0003"]').trigger("click")
    expect(wrapper.find('[data-testid="detail-title"]').text()).toContain("REQ-2024-0003")

    await wrapper.find('[data-testid="decision-rejected"]').trigger("click")

    expect(wrapper.find('[data-testid="detail-status"]').text()).toContain("已拒绝")
    expect(wrapper.find('[data-testid="row-status-REQ-2024-0003"]').text()).toContain("已拒绝")
  })

  it("switches sidebar modules instead of only highlighting navigation", async () => {
    const wrapper = mount(App)

    await wrapper.find('[data-testid="nav-文档管理"]').trigger("click")
    expect(wrapper.find('[data-testid="module-page"]').text()).toContain("文档管理")
    expect(wrapper.find('[data-testid="module-page"]').text()).toContain("文档解析记录")

    await wrapper.find('[data-testid="nav-质量分析"]').trigger("click")
    expect(wrapper.find('[data-testid="module-page"]').text()).toContain("质量分析")
    expect(wrapper.find('[data-testid="module-page"]').text()).toContain("低置信度分布")
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
    expect(wrapper.find('[data-testid="detail-status"]').text()).toContain("待专家确认")

    await wrapper.find('[data-testid="decision-accepted"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="detail-status"]').text()).toContain("已接受")
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it("runs pipeline, exports requirements, and assembles spec through the desktop bridge", async () => {
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
        runPipeline: vi.fn().mockResolvedValue({
          kind: "pipeline",
          out_dir: "E:\\out\\abnt",
          summary: { counts: { requirements: 1 } },
        }),
        exportRequirements: vi.fn().mockResolvedValue({
          kind: "export",
          written: ["requirements_export.csv", "requirements_export.md"],
        }),
        assembleSpec: vi.fn().mockResolvedValue({
          kind: "assemble",
          count: 1,
          written: ["dlms_cosem_spec_requirements.json"],
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
    await wrapper.find('[data-testid="action-run-pipeline"]').trigger("click")
    await vi.waitFor(() => {
      expect(window.ratomizerDesktop?.runPipeline).toHaveBeenCalledWith({
        inputPath: "C:\\input\\Appendix 9.docx",
        outDir: expect.stringContaining("requirement-atomizer-runs"),
        skipReview: false,
      })
    })
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="row-SREQ-RUN-1"]').exists()).toBe(true)
    })

    await wrapper.find('[data-testid="action-export"]').trigger("click")
    expect(window.ratomizerDesktop?.exportRequirements).toHaveBeenCalledWith({
      outDir: "E:\\out\\abnt",
      formats: ["csv", "md"],
    })

    await wrapper.find('[data-testid="action-assemble"]').trigger("click")
    expect(window.ratomizerDesktop?.assembleSpec).toHaveBeenCalledWith({
      outDir: "E:\\out\\abnt",
      formats: ["xlsx", "docx", "md"],
      enrichRoute: undefined,
    })
    expect(fetchMock).toHaveBeenCalled()
  })
})
