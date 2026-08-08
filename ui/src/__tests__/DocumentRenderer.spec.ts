import { describe, expect, it } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { nextTick } from "vue"
import * as XLSX from "xlsx"
import DocumentRenderer from "../DocumentRenderer.vue"

// WS-G 展示层回归：渲染器真实读文件字节渲染（PDF/DOCX/XLSX），异常时诚实降级。
// 旧版是死代码（new Function 动态 import + 只写占位文字）；这里用真实小文件字节断言渲染产物。

async function settle(ms = 60): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms))
  await flushPromises()
}

/** 用 SheetJS 现场构造一份真实 .xlsx 字节（含已知单元格值），供渲染器读取。 */
function buildRealXlsxBytes(): Uint8Array {
  const wb = XLSX.utils.book_new()
  const ws = XLSX.utils.aoa_to_sheet([
    ["参数", "数值"],
    ["电压", "230 V"],
    ["电流", "5 A"],
  ])
  XLSX.utils.book_append_sheet(wb, ws, "电气参数")
  return XLSX.write(wb, { type: "array", bookType: "xlsx" }) as Uint8Array
}

describe("DocumentRenderer", () => {
  it("renders toolbar with type badge and path", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/spec.html",
        fileType: "html",
        active: true,
      },
    })
    await nextTick()
    await settle()
    expect(wrapper.find('[data-testid="document-renderer"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="renderer-type"]').text()).toContain("HTML")
    expect(wrapper.find('[data-testid="renderer-path"]').text()).toBe("C:/docs/spec.html")
  })

  it("shows scanned PDF badge with source label when isScanned is true", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/scanned.pdf",
        fileType: "pdf",
        isScanned: true,
        scannedSource: "影印通道：无文字层",
        loadBytes: async () => new Uint8Array([0xff]),
        active: true,
      },
    })
    await nextTick()
    const badge = wrapper.find('[data-testid="scanned-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain("扫描件")
    expect(badge.text()).toContain("无文字层")
  })

  it("renders XLSX from real file bytes — asserts real cell values, not placeholder text", async () => {
    const bytes = buildRealXlsxBytes()
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/params.xlsx",
        fileType: "xlsx",
        loadBytes: async () => bytes,
        active: true,
      },
    })
    await nextTick()
    await settle()

    // 真实降级路径不应触发
    expect(wrapper.emitted("fallback")).toBeFalsy()
    expect(wrapper.find('[data-testid="renderer-error"]').exists()).toBe(false)

    // 渲染产物来自真实字节：单元格值与工作表名都来自现场构造的 xlsx
    const sheet = wrapper.find('[data-testid="xlsx-sheet"]')
    expect(sheet.exists()).toBe(true)
    const text = sheet.text()
    expect(text).toContain("电气参数")
    expect(text).toContain("电压")
    expect(text).toContain("230 V")
    expect(text).toContain("电流")
    // 工作表计数来自真实解析
    expect(wrapper.find('[data-testid="renderer-sheet-count"]').text()).toContain("工作表 1")
  })

  it("degrades honestly when docx bytes are invalid (docx-preview really tried to parse)", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/broken.docx",
        fileType: "docx",
        // 非 zip 字节——docx-preview 经 JSZip 解析必抛
        loadBytes: async () => new Uint8Array([0x4e, 0x6f, 0x74, 0x5a, 0x69, 0x70]),
        active: true,
      },
    })
    await nextTick()
    await settle()

    expect(wrapper.emitted("fallback")).toBeTruthy()
    const err = wrapper.find('[data-testid="renderer-error"]')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain("已诚实降级")
  })

  it("degrades honestly when the byte source is unavailable (no loadBytes, no bridge)", async () => {
    // 确保全局无 Electron 桥
    const bridge = (window as unknown as { ratomizerDesktop?: unknown }).ratomizerDesktop
    ;(window as unknown as { ratomizerDesktop?: unknown }).ratomizerDesktop = undefined
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/missing.pdf",
        fileType: "pdf",
        active: true,
      },
    })
    await nextTick()
    await settle()
    ;(window as unknown as { ratomizerDesktop?: unknown }).ratomizerDesktop = bridge

    expect(wrapper.emitted("fallback")).toBeTruthy()
    expect(wrapper.find('[data-testid="renderer-error"]').text()).toContain("已诚实降级")
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
    await settle()
    const overlay = wrapper.find('[data-testid="annotation-overlay"]')
    expect(overlay.exists()).toBe(true)
    expect(overlay.text()).toContain("标注叠加层就绪")
  })

  it("falls back by extension when fileType is unknown", async () => {
    const wrapper = mount(DocumentRenderer, {
      props: {
        filePath: "C:/docs/data.xlsx",
        active: true,
        loadBytes: async () => buildRealXlsxBytes(),
      },
    })
    await nextTick()
    await settle()
    expect(wrapper.find('[data-testid="renderer-type"]').text()).toContain("XLSX")
    // 扩展名推断出的 xlsx 同样走真实字节渲染
    expect(wrapper.find('[data-testid="xlsx-sheet"]').exists()).toBe(true)
  })
})
