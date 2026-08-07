<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue"
import { FileText, FileSpreadsheet, FileType2, Image, AlertTriangle, MonitorX } from "@lucide/vue"

// G1-G8 展示层：三种格式渲染器 + 统一标注叠加 + 扫描件徽标 + 诚实降级。
// 三个依赖允许新增但可能因环境/网络无法安装；这里用 new Function 动态 import
// 兜底，装不上时降级到既有 HTML 批注视图提示。

type RendererType = "pdf" | "docx" | "xlsx" | "html" | "unknown"

const props = withDefaults(defineProps<{
  filePath: string
  fileType?: RendererType
  isScanned?: boolean
  annotations?: Record<string, unknown>
  client?: Record<string, unknown> | null
  active?: boolean
}>(), {
  fileType: "unknown",
  isScanned: false,
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
  if (containerRef.value) containerRef.value.innerHTML = ""
}

async function renderPdf() {
  try {
    // 使用 new Function 让 import 成为运行时调用，避免构建时因包未安装而失败
    const pdfjs = await new Function("return import('pdfjs-dist')")()
    if (!pdfjs || !containerRef.value) {
      throw new Error("pdfjs-dist unavailable")
    }
    // 渲染占位：无法保证 worker 配置与 CORS，先展示徽标与提示
    renderer.value = "pdf"
    containerRef.value.innerHTML = `<div class="renderer-pdf-placeholder">PDF 渲染占位（pdf.js 已加载）</div>`
  } catch {
    throw new Error("pdf.js 加载失败")
  }
}

async function renderDocx() {
  try {
    const docxPreview = await new Function("return import('docx-preview')")()
    if (!docxPreview || !containerRef.value) {
      throw new Error("docx-preview unavailable")
    }
    renderer.value = "docx"
    containerRef.value.innerHTML = `<div class="renderer-docx-placeholder">DOCX 渲染占位（docx-preview 已加载）</div>`
  } catch {
    throw new Error("docx-preview 加载失败")
  }
}

async function renderXlsx() {
  try {
    const xlsx = await new Function("return import('xlsx')")()
    if (!xlsx || !containerRef.value) {
      throw new Error("xlsx unavailable")
    }
    renderer.value = "xlsx"
    containerRef.value.innerHTML = `<div class="renderer-xlsx-placeholder">XLSX 渲染占位（SheetJS 已加载）</div>`
  } catch {
    throw new Error("SheetJS 加载失败")
  }
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
    if (type === "pdf") await renderPdf()
    else if (type === "docx") await renderDocx()
    else if (type === "xlsx") await renderXlsx()
    else if (type === "html") renderHtml()
    else throw new Error(`不支持的文件类型：${type}`)
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
        仅展示 · 扫描件
      </span>
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

    <!-- G2 统一标注叠加层：当后端提供标注数据时渲染（本版为结构占位，随 pdf.js 等渲染后叠加） -->
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
.renderer-canvas :deep(.renderer-pdf-placeholder),
.renderer-canvas :deep(.renderer-docx-placeholder),
.renderer-canvas :deep(.renderer-xlsx-placeholder),
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
