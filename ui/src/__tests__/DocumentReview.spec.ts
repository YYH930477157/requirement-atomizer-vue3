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
        suspicion_reasons: ["数字漂移"], review_state: null,
      },
    ]),
    applyAiReviewAction: vi.fn().mockResolvedValue({ ai_req_id: "AIR-1", status: "accepted", module_override: null }),
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
    // 仅锚点块 in-span，跨度里的其它块不刷蓝
    const inSpan = wrapper.findAll(".doc-block.in-span")
    expect(inSpan.length).toBe(1)
    expect(inSpan[0].text()).toContain("measure volume")

    // 再点一下 → 取消选中：详情回空态、无 in-span
    await wrapper.find('[data-testid="anno-AIR-9"]').trigger("click")
    expect(wrapper.findAll(".doc-block.in-span").length).toBe(0)
    expect(wrapper.find('[data-testid="doc-detail"]').text()).toContain("点左侧")
  })

  it("guides the user when not connected to an output dir", async () => {
    const wrapper = mount(DocumentReview, { props: { client: null, active: true } })
    await flushPromises()
    expect(wrapper.find('[data-testid="doc-message"]').text()).toContain("先运行管线")
  })
})
