import { describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import * as XLSX from "xlsx"
import App from "../App.vue"

// WS-G G3：导入文档后直接进入渲染视图。旧版断言的是无关文本（路径在工具栏本就显示），
// 这里改为端到端实证：App 经 Electron readFileBytes 桥把真实文件字节喂给渲染器，
// SheetJS 真实解析并渲染出已知单元格值——证明渲染器在真实使用路径读字节、真渲染（非占位）。

function buildRealXlsxBytes(): Uint8Array {
  const wb = XLSX.utils.book_new()
  const ws = XLSX.utils.aoa_to_sheet([
    ["参数", "数值"],
    ["电压", "230 V"],
  ])
  XLSX.utils.book_append_sheet(wb, ws, "电气参数")
  return XLSX.write(wb, { type: "array", bookType: "xlsx" }) as Uint8Array
}

describe("DocumentRenderer integration", () => {
  it("renders the opened document from real bytes via the Electron byte bridge (App end-to-end)", async () => {
    const bytes = buildRealXlsxBytes()
    const readFileBytes = vi.fn().mockResolvedValue({ ok: true, bytes })
    Object.defineProperty(window, "ratomizerDesktop", {
      configurable: true,
      value: {
        getApiSession: vi.fn().mockResolvedValue(null),
        getLlmSettings: vi.fn().mockResolvedValue(null),
        openDocument: vi.fn().mockResolvedValue("C:\\input\\params.xlsx"),
        getRecentSessions: vi.fn().mockResolvedValue([]),
        getDefaultOutputRoot: vi.fn().mockResolvedValue("C:\\Users\\Tester\\Documents"),
        readFileBytes,
      },
    })

    const wrapper = mount(App)
    await flushPromises()

    // 导入文档——handleOpenDocument 选完即切到「文档渲染」视图
    await wrapper.find('[data-testid="action-open-document"]').trigger("click")
    await flushPromises()
    // 等待 readFileBytes 异步返回 + SheetJS 解析渲染
    await new Promise((resolve) => setTimeout(resolve, 80))
    await flushPromises()

    // App 确实经字节桥读取了所选文档
    expect(readFileBytes).toHaveBeenCalledWith({ path: "C:\\input\\params.xlsx" })

    // 渲染产物来自真实字节：单元格值与工作表名都是现场构造的 xlsx 内容（非占位文字）
    const sheet = wrapper.find('[data-testid="xlsx-sheet"]')
    expect(sheet.exists()).toBe(true)
    expect(sheet.text()).toContain("电气参数")
    expect(sheet.text()).toContain("电压")
    expect(sheet.text()).toContain("230 V")
    // 未触发诚实降级
    expect(wrapper.find('[data-testid="renderer-error"]').exists()).toBe(false)
  })

  it("degrades honestly to the document view when the byte bridge is unavailable", async () => {
    // 无 readFileBytes 桥（旧后端/非 Electron）——渲染器读不到字节，诚实降级回文档批注视图
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
    await new Promise((resolve) => setTimeout(resolve, 80))
    await flushPromises()

    // 渲染失败 → emit fallback → App 切回文档批注视图（activeNav 不再是 renderer）
    expect(wrapper.find('[data-testid="document-renderer"]').exists()).toBe(false)
  })
})
