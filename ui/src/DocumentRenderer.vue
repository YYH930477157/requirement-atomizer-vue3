<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue"
import { FileText, FileSpreadsheet, FileType2, Image, AlertTriangle, MonitorX } from "@lucide/vue"
// 静态 import：让 Vite 真正把三个依赖打进产物（旧版用 new Function("return import(...)")
// 是死代码——Vite 不分析它，产物不含依赖；裸说明符运行时也必抛）。
import * as pdfjsLib from "pdfjs-dist"
// worker 以 ?url 形式交 Vite 静态分包；真实 Chromium 下 pdf.js 启用 worker 渲染页面。
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url"
import * as docxPreview from "docx-preview"
import * as XLSX from "xlsx"

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

// G1-G8 展示层：三种格式渲染器 + 统一标注叠加 + 扫描件徽标 + 诚实降级。
// 渲染器真实读文件字节：PDF 走 pdf.js 页渲染、DOCX 走 docx-preview、XLSX 走 SheetJS 网格。
// 字节来源经 loadBytes 回调（App.vue 接 Electron readFileBytes 桥）；缺失/异常时诚实降级。

type RendererType = "pdf" | "docx" | "xlsx" | "html" | "unknown"

const props = withDefaults(defineProps<{
  filePath: string
  fileType?: RendererType
  isScanned?: boolean
  scannedSource?: string
  annotations?: Record<string, unknown>
  client?: Record<string, unknown> | null
  active?: boolean
  /** 字节源：传入文件绝对路径返回其字节。未提供时回退 window.ratomizerDesktop.readFileBytes。 */
  loadBytes?: (path: string) => Promise<ArrayBuffer | Uint8Array>
}>(), {
  fileType: "unknown",
  isScanned: false,
  scannedSource: "",
  annotations: () => ({}),
  client: null,
  active: true,
})

const emit = defineEmits<{
  (e: "fallback"): void
}>()

const loading = ref(false)
const error = ref("")
const renderer = ref<RendererType>("unknown")
const pageCount = ref(0)
const sheetCount = ref(0)
const containerRef = ref<HTMLElement | null>(null)

const displayType = computed((): RendererType => {
  if (props.fileType && props.fileType !== "unknown") return props.fileType
  const ext = props.filePath.split(".").pop()?.toLowerCase()
  if (ext === "pdf") return "pdf"
  if (ext === "docx") return "docx"
  if (ext === "xlsx" || ext === "xls" || ext === "csv") return "xlsx"
  if (ext === "html" || ext === "htm") return "html"
  return "unknown"
})

function reset() {
  error.value = ""
  renderer.value = "unknown"
  pageCount.value = 0
  sheetCount.value = 0
  if (containerRef.value) containerRef.value.innerHTML = ""
}

/** 读取真实字节：优先 prop 回调，其次 Electron 桥；都没有则抛错触发诚实降级。 */
async function readBytes(): Promise<Uint8Array> {
  let bytes: ArrayBuffer | Uint8Array | undefined
  if (typeof props.loadBytes === "function") {
    bytes = await props.loadBytes(props.filePath)
  } else if (typeof window !== "undefined" && window.ratomizerDesktop?.readFileBytes) {
    const resp = await window.ratomizerDesktop.readFileBytes({ path: props.filePath })
    if (!resp || !resp.ok || !resp.bytes) {
      throw new Error(`读取文件字节失败：${resp?.reason || "unknown"}`)
    }
    bytes = resp.bytes
  }
  if (!bytes) {
    throw new Error("无可用的文件字节源（未提供 loadBytes 且 Electron 桥缺失）")
  }
  return bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
}

async function renderPdf(bytes: Uint8Array) {
  // pdf.js 真实解析字节并逐页渲染到 <canvas>。无 canvas 后端（如 jsdom）时逐页如实降级占位，
  // 但页数来自真实解析，证明字节确被读取。
  const doc = await pdfjsLib.getDocument({ data: bytes }).promise
  pageCount.value = doc.numPages
  const host = containerRef.value
  if (!host) return
  host.innerHTML = ""
  const pagesWrap = document.createElement("div")
  pagesWrap.className = "pdf-pages"
  pagesWrap.setAttribute("data-testid", "pdf-pages")
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i)
    const viewport = page.getViewport({ scale: 1.2 })
    const canvas = document.createElement("canvas")
    canvas.className = "pdf-page-canvas"
    canvas.width = Math.floor(viewport.width)
    canvas.height = Math.floor(viewport.height)
    canvas.setAttribute("data-testid", `pdf-page-${i}`)
    const ctx = canvas.getContext("2d")
    if (ctx) {
      await page.render({ canvasContext: ctx, viewport, canvas } as Parameters<typeof page.render>[0]).promise
    } else {
      // 无 canvas 2D 上下文（测试环境）——如实标注，但仍挂出真实页号
      canvas.dataset.canvasUnavailable = "true"
    }
    pagesWrap.appendChild(canvas)
  }
  host.appendChild(pagesWrap)
}

async function renderDocx(bytes: Uint8Array) {
  const host = containerRef.value
  if (!host) return
  host.innerHTML = ""
  // docx-preview 真实把 docx 字节渲染为 HTML（JSZip 解析 + 段落/表格/样式重建）
  await docxPreview.renderAsync(bytes, host, undefined, {
    className: "docx-body",
    inWrapper: true,
    ignoreWidth: false,
    ignoreHeight: false,
  })
  host.setAttribute("data-testid", "docx-rendered")
}

async function renderXlsx(bytes: Uint8Array) {
  const host = containerRef.value
  if (!host) return
  host.innerHTML = ""
  // SheetJS 真实解析工作簿，逐 sheet 转 HTML 表格（单元格值为真实字节内容）
  const wb = XLSX.read(bytes, { type: "array" })
  sheetCount.value = wb.SheetNames.length
  const wrap = document.createElement("div")
  wrap.className = "xlsx-sheets"
  wrap.setAttribute("data-testid", "xlsx-sheets")
  wb.SheetNames.forEach((name) => {
    const ws = wb.Sheets[name]
    if (!ws) return
    const sheetBox = document.createElement("div")
    sheetBox.className = "xlsx-sheet"
    sheetBox.setAttribute("data-testid", "xlsx-sheet")
    const caption = document.createElement("div")
    caption.className = "xlsx-sheet-name"
    caption.textContent = name
    sheetBox.appendChild(caption)
    const html = XLSX.utils.sheet_to_html(ws, { id: `xlsx-sheet-${name}`, editable: false })
    const tpl = document.createElement("template")
    tpl.innerHTML = html
    sheetBox.appendChild(tpl.content)
    wrap.appendChild(sheetBox)
  })
  host.appendChild(wrap)
  host.setAttribute("data-testid", "xlsx-rendered")
}

function renderHtml() {
  renderer.value = "html"
  if (containerRef.value) {
    containerRef.value.innerHTML = `<div class="renderer-html-placeholder">HTML 工作副本占位</div>`
  }
}

async function render() {
  if (!props.active || !props.filePath) return
  reset()
  loading.value = true
  try {
    const type = displayType.value
    if (type === "unknown") throw new Error(`不支持的文件类型：${type}`)
    // HTML 工作副本无源文件字节——直接占位，不读字节、不触发降级
    if (type === "html") {
      renderHtml()
      renderer.value = "html"
      return
    }
    const bytes = await readBytes()
    if (type === "pdf") await renderPdf(bytes)
    else if (type === "docx") await renderDocx(bytes)
    else if (type === "xlsx") await renderXlsx(bytes)
    else throw new Error(`不支持的文件类型：${type}`)
    renderer.value = type
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
    emit("fallback")
  } finally {
    loading.value = false
  }
}

watch([() => props.filePath, () => props.fileType, () => props.active], () => {
  void render()
}, { immediate: true })

onUnmounted(() => reset())
</script>

<template>
  <section class="document-renderer" data-testid="document-renderer">
    <header class="renderer-toolbar">
      <span class="renderer-type-badge" data-testid="renderer-type">
        <FileType2 v-if="displayType === 'docx'" :size="14" aria-hidden="true" />
        <FileSpreadsheet v-else-if="displayType === 'xlsx'" :size="14" aria-hidden="true" />
        <FileText v-else-if="displayType === 'html'" :size="14" aria-hidden="true" />
        <Image v-else :size="14" aria-hidden="true" />
        {{ displayType.toUpperCase() }}
      </span>
      <span v-if="isScanned" class="scanned-badge" data-testid="scanned-badge">
        <AlertTriangle :size="13" aria-hidden="true" />
        仅展示 · 扫描件<span v-if="scannedSource" class="scanned-source">（{{ scannedSource }}）</span>
      </span>
      <span v-if="pageCount" class="renderer-meta" data-testid="renderer-page-count">页数 {{ pageCount }}</span>
      <span v-if="sheetCount" class="renderer-meta" data-testid="renderer-sheet-count">工作表 {{ sheetCount }}</span>
      <span class="renderer-path" data-testid="renderer-path">{{ filePath }}</span>
    </header>

    <div v-if="loading" class="renderer-loading" data-testid="renderer-loading">
      正在加载 {{ displayType.toUpperCase() }} 渲染器…
    </div>

    <div v-else-if="error" class="renderer-error" data-testid="renderer-error">
      <MonitorX :size="20" aria-hidden="true" />
      <p>渲染器不可用：{{ error }}</p>
      <p class="renderer-error-hint">已诚实降级到既有 HTML 批注视图。</p>
    </div>

    <div
      v-show="!loading && !error"
      ref="containerRef"
      class="renderer-canvas"
      data-testid="renderer-canvas"
    ></div>

    <!-- G2 统一标注叠加层：当后端提供标注数据时渲染（随 pdf.js 等渲染后叠加） -->
    <div
      v-if="Object.keys(annotations || {}).length && !loading && !error"
      class="annotation-overlay"
      data-testid="annotation-overlay"
    >
      <span class="annotation-overlay-hint">标注叠加层就绪（{{ Object.keys(annotations).length }} 组）</span>
    </div>
  </section>
</template>

<style scoped>
.document-renderer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}
.renderer-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
  font-size: 13px;
}
.renderer-type-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: #e0e7ff;
  color: #3730a3;
  border-radius: 4px;
  font-weight: 600;
}
.scanned-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: #fef3c7;
  color: #92400e;
  border-radius: 4px;
  font-weight: 600;
}
.scanned-source {
  font-weight: 400;
  opacity: 0.85;
}
.renderer-meta {
  padding: 2px 8px;
  background: #ecfdf5;
  color: #065f46;
  border-radius: 4px;
  font-weight: 600;
}
.renderer-path {
  margin-left: auto;
  color: #6b7280;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.renderer-loading,
.renderer-error {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #6b7280;
  padding: 24px;
  text-align: center;
}
.renderer-error {
  color: #b91c1c;
}
.renderer-error-hint {
  color: #6b7280;
  font-size: 12px;
  margin-top: 8px;
}
.renderer-canvas {
  flex: 1;
  padding: 16px;
  overflow: auto;
}
.renderer-canvas :deep(.pdf-pages) {
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: center;
}
.renderer-canvas :deep(.pdf-page-canvas) {
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
  background: #fff;
  max-width: 100%;
}
.renderer-canvas :deep(.docx-body) {
  font-size: 13px;
  line-height: 1.5;
}
.renderer-canvas :deep(.docx-body .docx-wrapper) {
  background: #fff;
  padding: 8px;
}
.renderer-canvas :deep(.xlsx-sheets) {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.renderer-canvas :deep(.xlsx-sheet-name) {
  font-weight: 600;
  font-size: 13px;
  color: #1f2937;
  margin-bottom: 6px;
}
.renderer-canvas :deep(.xlsx-sheet table) {
  border-collapse: collapse;
  font-size: 12px;
}
.renderer-canvas :deep(.xlsx-sheet td),
.renderer-canvas :deep(.xlsx-sheet th) {
  border: 1px solid #d1d5db;
  padding: 3px 6px;
  white-space: nowrap;
}
.renderer-canvas :deep(.renderer-html-placeholder) {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  border: 2px dashed #cbd5e1;
  border-radius: 6px;
  color: #64748b;
  font-size: 14px;
}
.annotation-overlay {
  position: absolute;
  bottom: 12px;
  right: 12px;
  background: rgba(15, 23, 42, 0.8);
  color: #fff;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  pointer-events: none;
}
.annotation-overlay-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
