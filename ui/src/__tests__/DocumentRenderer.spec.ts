import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { nextTick } from "vue"
import DocumentRenderer from "../DocumentRenderer.vue"

// WS-G 展示层回归：动态导入可能失败，组件必须诚实降级。
describe("DocumentRenderer", () => {
  it("renders toolbar with type badge and path", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/spec.docx",
        fileType: "docx",
        active: true,
      },
    })
    await nextTick()
    expect(wrapper.find('[data-testid="document-renderer"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="renderer-type"]').text()).toContain("DOCX")
    expect(wrapper.find('[data-testid="renderer-path"]').text()).toBe("C:/docs/spec.docx")
  })

  it("shows scanned PDF badge when isScanned is true", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/scanned.pdf",
        fileType: "pdf",
        isScanned: true,
        active: true,
      },
    })
    await nextTick()
    const badge = wrapper.find('[data-testid="scanned-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain("扫描件")
  })

  it("emits fallback and shows honest降级 when dynamic import fails", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/spec.docx",
        fileType: "docx",
        active: true,
      },
    })
    // 等待异步 render 与动态 import 失败
    await new Promise((resolve) => setTimeout(resolve, 100))
    await nextTick()
    expect(wrapper.emitted("fallback")).toHaveLength(1)
    const error = wrapper.find('[data-testid="renderer-error"]')
    expect(error.exists()).toBe(true)
    expect(error.text()).toContain("已诚实降级")
  })

  it("shows annotation overlay when annotations provided", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/spec.html",
        fileType: "html",
        active: true,
        annotations: { B1: [{ id: "A1" }] },
      },
    })
    await nextTick()
    const overlay = wrapper.find('[data-testid="annotation-overlay"]')
    expect(overlay.exists()).toBe(true)
    expect(overlay.text()).toContain("标注叠加层就绪")
  })

  it("falls back by extension when fileType is unknown", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/data.xlsx",
        active: true,
      },
    })
    await nextTick()
    expect(wrapper.find('[data-testid="renderer-type"]').text()).toContain("XLSX")
  })
})
