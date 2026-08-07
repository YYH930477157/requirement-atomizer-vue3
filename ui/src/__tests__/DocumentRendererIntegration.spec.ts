import { describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import App from "../App.vue"

// WS-G G3：导入文档后直接进入渲染视图；依赖未安装时诚实降级到文档批注视图。
describe("DocumentRenderer integration", () => {
  it("makes the imported document reachable and renders the appropriate view", async () => {
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        getLlmSettings: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\spec.docx"),
        getRecentSessions: vi.fn().mockResolvedValue([]),
        getDefaultOutputRoot: vi.fn().mockResolvedValue("C:\\Users\\Tester\\Documents"),
      },
    })

    const wrapper = mount(App)
    await flushPromises()

    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await flushPromises()

    // 依赖未安装时降级到文档批注视图，但当前文档路径已生效
    expect(wrapper.text()).toContain("C:\\input\\spec.docx")
  })
})
