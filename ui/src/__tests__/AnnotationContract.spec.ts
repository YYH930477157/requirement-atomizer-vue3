// 双渲染器契约（F6，Vue 侧）：与 tests/fixtures/annotation_contract.json 共用同一夹具，
// Python 侧锁 HTML 导出器结构；本测试锁应用内 DocumentReview 的编号/子项/选中语义。
import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import DocumentReview from "../DocumentReview.vue"

const fixture = JSON.parse(
  readFileSync(resolve(__dirname, "../../../tests/fixtures/annotation_contract.json"), "utf-8"),
)

function makeClient() {
  return {
    loadDocument: vi.fn().mockResolvedValue({ count: fixture.blocks.length, blocks: fixture.blocks }),
    loadAiRequirements: vi.fn().mockResolvedValue(fixture.requirements),
    applyAiReviewAction: vi.fn(),
    loadPdfAnnotation: vi.fn().mockResolvedValue({ available: false, reason: "影印页尚未生成" }),
    loadPdfPageBlob: vi.fn(async (file: string) => `blob:fake-${file}`),
  }
}

async function flushPromises() {
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 0))
}

describe("annotation renderer contract (Vue side)", () => {
  it("parent numbering follows the shared contract", async () => {
    const wrapper = mount(DocumentReview, { props: { client: makeClient(), active: true } })
    await flushPromises()
    const chipTexts = wrapper.findAll(".anno-chip").map((c) => c.text())
    for (const number of fixture.expect.parent_numbers) {
      expect(chipTexts.some((t: string) => t.startsWith(number)), `缺一级编号 ${number}`).toBe(true)
    }
  })

  it("table block renders a real table per contract", async () => {
    const wrapper = mount(DocumentReview, { props: { client: makeClient(), active: true } })
    await flushPromises()
    const table = wrapper.find('[data-testid="doc-table"]')
    expect(table.exists()).toBe(true)
    expect(table.find("figcaption").text()).toContain(fixture.expect.table_caption)
    expect(table.find(".table-badge").text()).toBe(fixture.expect.table_badge)
    const headers = table.findAll("th").map((c) => c.text())
    expect(headers).toEqual(fixture.expect.table_header_cells)
    const firstRow = table.findAll("tbody tr")[0].findAll("td").map((c) => c.text())
    expect(firstRow).toEqual(fixture.expect.table_first_row)
  })

  it("renders merge badge / consistency / conflict signals per contract", async () => {
    // 0714 批次一（E1c）：三信号双渲染器同源——文案与夹具 expect 逐字一致
    const wrapper = mount(DocumentReview, { props: { client: makeClient(), active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-merge"]').text()).toContain(fixture.expect.merge_badge_text)
    expect(wrapper.find('[data-testid="dd-merge"]').classes()).toContain("dd-suspicion") // 置信 0.75 < 0.9 → 警示样式
    expect(wrapper.find('[data-testid="dd-consistency"]').text()).toContain(fixture.expect.consistency_flag_text)
    expect(wrapper.find('[data-testid="dd-conflict"]').text()).toContain(fixture.expect.conflict_flag_text)
    expect(wrapper.find('[data-testid="dd-functional"]').text()).toContain("阀门关闭控制")
    // AIR-2 无功能合成字段 → 三信号全部不出现（单源/无冲突不显示）
    await wrapper.find('[data-testid="anno-AIR-2"]').trigger("click")
    expect(wrapper.find('[data-testid="dd-merge"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="dd-functional"]').exists()).toBe(false)
  })

  it("selecting AIR-1 lights the analyzed span and marks anchor evidence", async () => {
    const wrapper = mount(DocumentReview, { props: { client: makeClient(), active: true } })
    await flushPromises()
    await wrapper.find('[data-testid="anno-AIR-1"]').trigger("click")
    expect(wrapper.findAll(".doc-block.in-span").length)
      .toBe(fixture.expect.select_air1_span_blocks)
    expect(wrapper.findAll(".doc-block.in-span.evidence").length)
      .toBe(fixture.expect.select_air1_evidence_blocks)
    // 子项契约：详情面板必须列出与 sub_chip_labels 同源的子项
    const subItems = wrapper.find('[data-testid="dd-subitems"]')
    expect(subItems.exists()).toBe(true)
    for (const label of fixture.requirements[0].sub_items.map((s: { label: string }) => s.label)) {
      expect(subItems.text()).toContain(`${label})`)
    }
  })
})
