<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue"
import type { AiRequirement, DocumentBlock, PdfAnnotationPayload, PdfZoneRect, RequirementApiClient } from "./api-client"

// 镜像后端 ai_extract.MODULE_VOCAB（受控模块词表）。改模块下拉用；taxonomy 变动时两边同步。
const MODULE_VOCAB = [
  "计量", "时钟", "事件记录", "曲线", "需量", "费率", "结算", "状态字", "窃电", "电网质量",
  "预付费", "CIU", "门限范围", "Push", "显示", "升级", "负控", "节假日", "通信协议", "安全",
  "环境可靠性", "附加功能", "机械结构", "计量精度", "数据存储", "测试合规", "其它",
]

const STATUS_LABELS: Record<string, string> = {
  draft: "待审", accepted: "已接受", rejected: "已拒绝",
  needs_discussion: "待讨论", expert_pending: "专家待定",
}

// 结构化子集（避免 class 私有成员 + ref 解包导致的名义类型不匹配）
type DocClient = Pick<RequirementApiClient,
  "loadDocument" | "loadAiRequirements" | "applyAiReviewAction" | "loadPdfAnnotation" | "loadPdfPageBlob">
const props = defineProps<{ client: DocClient | null; active: boolean }>()

const blocks = ref<DocumentBlock[]>([])
const requirements = ref<AiRequirement[]>([])
const loading = ref(false)
const message = ref("")
const selectedId = ref("")
const isSaving = ref(false)
const comment = ref("")
const moduleEdit = ref("")
const ownershipEdit = ref("")

// 与后端 requirements_analysis_schema 的三值归属一致
const OWNERSHIP_OPTIONS = [
  { value: "software", label: "软件" },
  { value: "hardware", label: "硬件" },
  { value: "co_design", label: "软硬件协同" },
]
let loadedOnce = false

async function load() {
  if (!props.client) {
    message.value = "未连接输出目录——先运行管线 + AI 抽取"
    return
  }
  loading.value = true
  message.value = ""
  try {
    const [doc, reqs] = await Promise.all([props.client.loadDocument(), props.client.loadAiRequirements()])
    blocks.value = doc.blocks || []
    requirements.value = reqs || []
    if (!requirements.value.length) {
      message.value = "暂无 AI 抽取需求——请先开 LLM 跑「AI 抽取」"
    }
    loadedOnce = true
  } catch (error) {
    message.value = error instanceof Error ? error.message : "加载失败"
  } finally {
    loading.value = false
  }
}

watch(() => props.active, (on) => { if (on && (!loadedOnce || !requirements.value.length)) void load() }, { immediate: true })

// 每条需求锚到含其 source_quote 原句的那一小段（后端 anchor_block_id，段落级精确），
// 回退 source_block_ids 首块。批注钉在需求实际所在的小段，不分散到整章节。
const anchorByBlock = computed(() => {
  const map = new Map<string, AiRequirement[]>()
  for (const req of requirements.value) {
    const anchor = req.anchor_block_id || (req.source_block_ids || [])[0]
    if (!anchor) continue
    const list = map.get(anchor) || []
    list.push(req)
    map.set(anchor, list)
  }
  return map
})

// 回声段（同文重复出现的其他段落）：不重复挂批注（0716 用户裁定:批注不过度显示,
// 汇总层才归并）——只用于免遗漏判定 + 点击时给"重复段"卡片指向汇总条目。
const echoByBlock = computed(() => {
  const map = new Map<string, AiRequirement[]>()
  for (const req of requirements.value) {
    for (const echo of req.echo_block_ids || []) {
      const list = map.get(echo) || []
      if (!list.some((item) => item.ai_req_id === req.ai_req_id)) list.push(req)
      map.set(echo, list)
    }
  }
  return map
})

// 被任意需求覆盖的块集合（含整段 source_block_ids 与回声段），用于遗漏判定。
const coveredBlocks = computed(() => {
  const s = new Set<string>()
  for (const req of requirements.value) {
    for (const b of req.source_block_ids || []) s.add(b)
    for (const b of req.echo_block_ids || []) s.add(b)
  }
  return s
})

const selectedReq = computed(() => requirements.value.find((r) => r.ai_req_id === selectedId.value) || null)

// 块级三段式卡片：未覆盖段/背景段（与导出 HTML 同语义/同文案——双渲染器契约）。
// 目标：全文每一段都有分析结果——需求段有批注,其余段点开能看到为什么没生成需求+翻译+引用。
const OMISSION_REASON = "该段含规范性措辞（shall/must/应…），被判为疑似需求，但没有任何已抽取需求的来源范围覆盖它。可能原因：抽取遗漏（自检未补回）或该句实为背景说明。确属需求请反馈补抽；背景说明可忽略。"
const CONTEXT_REASON = "该段未检出规范性措辞（shall/must/应…），被判定为背景/说明性内容，因此没有生成研发需求；其信息会作为上下文供相邻需求的分析使用。如认为该段实际包含需求，请反馈补抽。"
// 与导出 HTML 同文案（双渲染器契约）
const ECHO_REASON = "该段与已抽取需求的来源段落内容重复（同文多次出现）。解析已汇总至对应需求条目，本段不重复挂批注；点击「重复·见」角标或下方链接可跳转查看该条目。"
const selectedBlockId = ref("")
const selectedBlock = computed(() => blocks.value.find((b) => b.block_id === selectedBlockId.value) || null)
const selectedBlockKind = computed(() => {
  if (!selectedBlock.value) return "context"
  if (echoByBlock.value.has(selectedBlock.value.block_id)) return "echo"
  return isOmission(selectedBlock.value) ? "omission" : "context"
})
const selectedEchoReqs = computed(() =>
  (selectedBlock.value && echoByBlock.value.get(selectedBlock.value.block_id)) || [])
function selectBlockCard(b: DocumentBlock) {
  if (selectedBlockId.value === b.block_id) {  // 再点一下 → 取消选中
    selectedBlockId.value = ""
    return
  }
  selectedBlockId.value = b.block_id
  selectedId.value = ""
}
function onBlockClick(b: DocumentBlock) {
  const anchored = anchorByBlock.value.get(b.block_id)
  if (anchored?.length) {
    select(anchored[0])
    return
  }
  if (isHeading(b) || b.noise || isTable(b) || !(b.text || "").trim()) return
  selectBlockCard(b)
}

// 原版影印模式（2026-07-14）：数据与分享 HTML 同源（几何缓存/百分比换算共用后端实现），
// 右栏详情与裁决两种模式完全共用——双渲染器等价。页图缺失时提示先跑一次影印导出。
const viewMode = ref<"text" | "pdf">("text")
const pdfData = ref<PdfAnnotationPayload | null>(null)
const pdfLoading = ref(false)
const pdfPageUrls = ref<Record<string, string>>({})
let pdfPageLoadGeneration = 0
let pdfPageLoadsDisposed = false

function revokePdfPageUrl(url: string) {
  if (typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(url)
  }
}

async function loadPdfPages(payload: PdfAnnotationPayload) {
  if (pdfPageLoadsDisposed) return
  const generation = ++pdfPageLoadGeneration
  // 顺序拉取页图(带鉴权头 fetch→blob;token 不进 URL——仓库安全锁);单页失败不阻断其余
  for (const page of payload.pages || []) {
    if (pdfPageUrls.value[page.file] || !props.client) continue
    try {
      const url = await props.client.loadPdfPageBlob(page.file)
      if (pdfPageLoadsDisposed || generation !== pdfPageLoadGeneration) {
        revokePdfPageUrl(url)
        continue
      }
      pdfPageUrls.value = { ...pdfPageUrls.value, [page.file]: url }
    } catch {
      /* 页图缺失/网络抖动:保留占位框,不影响其它页 */
    }
  }
}

onUnmounted(() => {
  pdfPageLoadsDisposed = true
  pdfPageLoadGeneration += 1
  const urls = new Set(Object.values(pdfPageUrls.value))
  pdfPageUrls.value = {}
  for (const url of urls) revokePdfPageUrl(url)
})
async function switchMode(mode: "text" | "pdf") {
  viewMode.value = mode
  if (mode === "pdf" && !pdfData.value && props.client && !pdfLoading.value) {
    pdfLoading.value = true
    try {
      pdfData.value = await props.client.loadPdfAnnotation()
      if (pdfData.value?.available) void loadPdfPages(pdfData.value)
    } catch (error) {
      pdfData.value = { available: false, reason: error instanceof Error ? error.message : "影印数据加载失败" }
    } finally {
      pdfLoading.value = false
    }
  }
}
type PdfMarker = { kind: "req" | "omission"; id: string; rect: PdfZoneRect; laneOffset: number }
const pdfMarkersByPage = computed(() => {
  const byPage = new Map<number, PdfMarker[]>()
  const push = (page: number, kind: "req" | "omission", id: string, rect: PdfZoneRect) => {
    const list = byPage.get(page) || []
    list.push({ kind, id, rect, laneOffset: 0 })
    byPage.set(page, list)
  }
  for (const m of pdfData.value?.requirement_markers || []) push(m.page, "req", m.req_id, m.rect)
  for (const m of pdfData.value?.omission_markers || []) push(m.page, "omission", m.block_id, m.rect)
  for (const list of byPage.values()) {
    list.sort((a, b) => a.rect.top - b.rect.top)
    let prevTop = -100
    let lane = 0
    for (const m of list) {   // 与导出 HTML 同规则：垂直间距 <2.6% 换道错开,防标记叠死
      lane = m.rect.top - prevTop < 2.6 ? lane + 1 : 0
      prevTop = m.rect.top
      m.laneOffset = lane * 25
    }
  }
  return byPage
})
// 全段落热区（0714「点一段出翻译和解析」）：kind 语义由后端 _pdf_block_zones 唯一定义,
// 这里只做渲染与路由——req→需求卡 / omission·context→块级卡（卡种由 selectedBlockKind 判定）
type PdfBlockZone = { block_id: string; page: number; rect: PdfZoneRect
                      kind: "req" | "echo" | "omission" | "context";
                      req_id?: string; req_ids?: string[] }
const pdfZonesByPage = computed(() => {
  const byPage = new Map<number, PdfBlockZone[]>()
  for (const z of pdfData.value?.block_zones || []) {
    const list = byPage.get(z.page) || []
    list.push(z)
    byPage.set(z.page, list)
  }
  return byPage
})
function pdfZoneClick(z: PdfBlockZone) {
  if (z.kind === "req" && z.req_id) {
    const req = requirements.value.find((r) => r.ai_req_id === z.req_id)
    if (req) select(req)
    return
  }
  const block = blocks.value.find((b) => b.block_id === z.block_id)
  if (block) selectBlockCard(block)
}
function pdfZoneSelected(z: PdfBlockZone): boolean {
  if (z.kind === "req") return !!z.req_id && z.req_id === selectedId.value
  if (z.kind === "echo" && selectedId.value) return (z.req_ids || []).includes(selectedId.value)
  return z.block_id === selectedBlockId.value
}
function pdfZoneTitle(z: PdfBlockZone): string {
  if (z.kind === "req") return "查看需求批注"
  if (z.kind === "echo") return "重复段·点击查看汇总需求"
  return z.kind === "omission" ? "疑似需求未覆盖·点击查看" : "查看该段翻译与解析"
}

function pdfMarkerClick(m: PdfMarker) {
  if (m.kind === "req") {
    const req = requirements.value.find((r) => r.ai_req_id === m.id)
    if (req) select(req)
    return
  }
  const block = blocks.value.find((b) => b.block_id === m.id)
  if (block) selectBlockCard(block)
}
function pdfMarkerLabel(m: PdfMarker): string {
  if (m.kind === "omission") return "!"
  const req = requirements.value.find((r) => r.ai_req_id === m.id)
  return req ? reqNumber(req) : "--"
}
function pdfMarkerSelected(m: PdfMarker): boolean {
  return m.kind === "req" ? m.id === selectedId.value : m.id === selectedBlockId.value
}
function pdfSelectedZone(page: number): PdfZoneRect | null {
  const markers = pdfMarkersByPage.value.get(page) || []
  const hit = markers.find((m) => pdfMarkerSelected(m))
  return hit ? hit.rect : null
}
// 只高亮选中的片段（锚点小段），不把整个章节跨度刷蓝
const evidenceBlocks = computed(() => {
  // 证据块（蓝填充）= 引用所在锚点段；其余跨度块仅左侧细条 = 分析上下文（模型通读范围）
  const r = selectedReq.value
  const anchor = r?.anchor_block_id || (r?.source_block_ids || [])[0]
  return new Set(anchor ? [anchor as string] : [])
})
const selectedSpan = computed(() => {
  // 整个被分析的跨度都亮淡底（source_block_ids），引句黄标只在锚点段内——
  // 只黄一句会让"分析了一整段"的需求看起来像没选中（真实反馈）
  const r = selectedReq.value
  const anchor = r?.anchor_block_id || (r?.source_block_ids || [])[0]
  const ids = [...(r?.source_block_ids || []), ...(r?.echo_block_ids || []), anchor]
    .filter(Boolean) as string[]
  return new Set(ids)
})

// 全文连续编号（按锚点块在文档中的顺序）——与分享 HTML 的 01/02 编号一致
const reqNumbers = computed(() => {
  const order = new Map(blocks.value.map((b, i) => [b.block_id, i]))
  const anchored = requirements.value.filter((r) => r.anchor_block_id || (r.source_block_ids || [])[0])
  const sorted = [...anchored].sort((a, b) =>
    (order.get(String(a.anchor_block_id || (a.source_block_ids || [])[0])) ?? 1e9) -
    (order.get(String(b.anchor_block_id || (b.source_block_ids || [])[0])) ?? 1e9))
  return new Map(sorted.map((r, i) => [r.ai_req_id, i + 1]))
})
function reqNumber(r: AiRequirement): string {
  const n = reqNumbers.value.get(r.ai_req_id)
  return n ? String(n).padStart(2, "0") : "--"
}

function orderedEchoReqs(reqs: AiRequirement[]): AiRequirement[] {
  return [...reqs].sort((a, b) =>
    (reqNumbers.value.get(a.ai_req_id) ?? 1e9) - (reqNumbers.value.get(b.ai_req_id) ?? 1e9))
}
const orderedSelectedEchoReqs = computed(() => orderedEchoReqs(selectedEchoReqs.value))
function echoReqsForBlock(blockId: string): AiRequirement[] {
  return orderedEchoReqs(echoByBlock.value.get(blockId) || [])
}
function echoLabel(reqs: AiRequirement[]): string {
  const numbers = orderedEchoReqs(reqs).map((req) => reqNumber(req)).filter((value) => value !== "--")
  return numbers.length ? `重复·见${numbers.join("/")}` : "重复段"
}
function pdfEchoLabel(zone: PdfBlockZone): string {
  const ids = new Set(zone.req_ids || [])
  return echoLabel(requirements.value.filter((req) => ids.has(req.ai_req_id)))
}
function jumpToEchoReq(req: AiRequirement) {
  selectedBlockId.value = ""
  selectedId.value = req.ai_req_id   // 直接选中(不走 select 的再点取消语义)
}

// 排版保真：噪声（页眉/页脚/水印）不渲染；跨页处画分页线（与自包含 HTML 同语义）
const visibleBlocks = computed(() => blocks.value.filter((b) => !b.noise))

// 表格块渲染真 <table>（旧 out_dir 无 data_rows 时回退扁平文字段落）
const LIST_ITEM_RE = /^(?:[a-z0-9]{1,3}[).]|[•▪—–-])\s/
const NOTE_RE = /^NOTE(?:\s|$)/i
function isTable(b: DocumentBlock): boolean {
  return b.type === "table" && Boolean((b.data_rows || []).length || (b.header_rows || []).length)
}
function isListItem(b: DocumentBlock): boolean {
  return LIST_ITEM_RE.test(b.text || "")
}
function isNote(b: DocumentBlock): boolean {
  return NOTE_RE.test(b.text || "")
}
function padRow(b: DocumentBlock, row: string[]): string[] {
  const ncols = Math.max(...[...(b.header_rows || []), ...(b.data_rows || [])].map((r) => r.length), 0)
  return [...row, ...Array(Math.max(0, ncols - row.length)).fill("")]
}
function pageBreakBefore(index: number): number | null {
  const cur = visibleBlocks.value[index]
  const prev = visibleBlocks.value[index - 1]
  if (!cur || !prev) return null
  return cur.page_number != null && prev.page_number != null && cur.page_number !== prev.page_number
    ? Number(cur.page_number) : null
}

// 覆盖/遗漏统一口径（E3b）：服务端 coverage_candidate（剔除标题/引用书目/非正文假阳性）;
// 旧后端 payload 无该字段时回退宽口径,行为同旧版
function isCoverageCandidate(b: DocumentBlock): boolean {
  return b.coverage_candidate !== undefined
    ? Boolean(b.coverage_candidate)
    : Boolean(b.requirement_like) && !b.noise
}

const omissionCount = computed(
  () => blocks.value.filter((b) => isCoverageCandidate(b) && !coveredBlocks.value.has(b.block_id)).length,
)

const stats = computed(() => ({
  reqs: requirements.value.length,
  anchored: requirements.value.filter((r) => (r.source_block_ids || []).length).length,
  omissions: omissionCount.value,
}))

function isHeading(b: DocumentBlock): boolean {
  return b.type === "heading" || (b.section_path?.length ? b.text === b.section_path[b.section_path.length - 1] : false)
}
function isOmission(b: DocumentBlock): boolean {
  return isCoverageCandidate(b) && !coveredBlocks.value.has(b.block_id)
}
function moduleOf(r: AiRequirement): string {
  return String(r.module_effective || r.module || (r.labels || [])[0] || "未分模块")
}
function statusOf(r: AiRequirement): string {
  return String(r.status || "draft")
}
function ownershipOf(r: AiRequirement): string {
  return String(r.ownership_effective || r.ownership || "software")
}
const OWNERSHIP_LABELS: Record<string, string> = { software: "软件", hardware: "硬件", co_design: "软硬件协同" }
function devGuidanceOf(r: AiRequirement): string[] {
  if (ownershipOf(r) === "hardware") return []
  return r.dev_guidance || []
}
function acceptanceOf(r: AiRequirement): string[] {
  if (ownershipOf(r) === "hardware") return []
  return r.acceptance_criteria || []
}
function ownershipReasonOf(r: AiRequirement): string {
  return String(r.ownership_reason || "")
}
// 跨章合并徽章（双渲染器契约字段——与 doc_annotation_export functionalMergeBadge 同语义,
// 契约夹具锁文案）：单源不显示（置信恒 1.0 是噪声）;置信 < 0.9 提示核对（弱合并最易错并）
function mergeBadgeOf(r: AiRequirement): string {
  const count = Number(r.functional_source_count || 0)
  const method = String(r.functional_merge_method || "")
  if (!method || count < 2) return ""
  const conf = Number(r.functional_merge_confidence == null ? 1 : r.functional_merge_confidence)
  return `跨章合并 ${count} 条（${method}，置信 ${conf}）${conf < 0.9 ? "——建议核对合并是否恰当" : ""}`
}
function mergeWarnOf(r: AiRequirement): boolean {
  return Number(r.functional_merge_confidence == null ? 1 : r.functional_merge_confidence) < 0.9
}
function ownershipOverrideNote(r: AiRequirement): string {
  const base = String(r.ownership || "")
  const effective = String(r.ownership_effective || base)
  if (!base || base === effective) return ""
  return `已被人工覆盖为${OWNERSHIP_LABELS[effective] || effective}（原判${OWNERSHIP_LABELS[base] || base}）`
}
// 硬件卡翻译诚实回退（与导出 HTML 同语义,2026-07-12）：候选含中文才用,
// 否则回退锚点块的全文翻译,再无返回空串(模板显示空态);绝不拿英文冒充中文翻译。
function hardwareTranslationOf(r: AiRequirement): string {
  const cjk = /[一-鿿]/
  for (const candidate of [r.hardware_summary, r.hardware_translation]) {
    if (candidate && cjk.test(String(candidate))) return String(candidate)
  }
  const anchor = String(r.anchor_block_id || (r.source_block_ids || [])[0] || "")
  const block = blocks.value.find((b) => b.block_id === anchor)
  return block?.translation || ""
}

function select(req: AiRequirement) {
  selectedBlockId.value = ""
  if (selectedId.value === req.ai_req_id) {  // 再点一下 → 取消选中
    selectedId.value = ""
    return
  }
  selectedId.value = req.ai_req_id
  comment.value = String(req.review_state?.reason || "")
  moduleEdit.value = moduleOf(req)
  ownershipEdit.value = ownershipOf(req)
}

// 选中需求时，在锚段内的块里高亮 source_quote 原句；选中未覆盖/背景段时整段=引用本体 → 全黄。
function segments(b: DocumentBlock): Array<{ text: string; mark: boolean }> {
  const text = b.text || ""
  if (b.block_id === selectedBlockId.value) return [{ text, mark: true }]
  const quote = selectedReq.value?.source_quote || ""
  if (!quote || !selectedSpan.value.has(b.block_id) || !text.includes(quote)) return [{ text, mark: false }]
  const i = text.indexOf(quote)
  return [
    { text: text.slice(0, i), mark: false },
    { text: quote, mark: true },
    { text: text.slice(i + quote.length), mark: false },
  ].filter((s) => s.text.length)
}

async function decide(status: "accepted" | "rejected" | "needs_discussion") {
  const req = selectedReq.value
  if (!req || !props.client || isSaving.value) return
  isSaving.value = true
  try {
    const state = await props.client.applyAiReviewAction({
      aiReqId: req.ai_req_id, status,
      moduleOverride: moduleEdit.value !== moduleOf(req) ? moduleEdit.value : "",
      // 选回规则初判值 → 发空串清除覆盖，归属回落规则判定
      ownershipOverride: ownershipEdit.value !== (req.ownership || "") ? ownershipEdit.value : "",
      reason: comment.value, actor: "reviewer",
    })
    req.review_state = state
    req.status = state.status
    if (state.module_override) req.module_effective = state.module_override
    req.ownership_effective = state.ownership_override || req.ownership
    message.value = `已${STATUS_LABELS[status] || status}：${req.title || req.ai_req_id}`
  } catch (error) {
    message.value = error instanceof Error ? error.message : "裁决写入失败"
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <section class="doc-review" data-testid="doc-review">
    <header class="doc-toolbar">
      <div class="doc-stats">
        <span>需求 <strong data-testid="doc-stat-reqs">{{ stats.reqs }}</strong></span>
        <span>已挂载 <strong>{{ stats.anchored }}</strong></span>
        <span class="omission-stat" :class="{ warn: stats.omissions > 0 }">
          疑似遗漏 <strong data-testid="doc-stat-omissions">{{ stats.omissions }}</strong>
        </span>
      </div>
      <div class="doc-toolbar-actions">
        <div class="mode-toggle">
          <button type="button" :class="{ active: viewMode === 'text' }" data-testid="mode-text"
                  @click="switchMode('text')">文字重排</button>
          <button type="button" :class="{ active: viewMode === 'pdf' }" data-testid="mode-pdf"
                  @click="switchMode('pdf')">原版影印</button>
        </div>
        <button class="button" type="button" data-testid="doc-reload" :disabled="loading" @click="load">
          {{ loading ? "加载中" : "刷新" }}
        </button>
      </div>
    </header>

    <div v-if="message" class="doc-message" data-testid="doc-message">{{ message }}</div>

    <div class="doc-body">
      <article v-if="viewMode === 'pdf'" class="doc-paper pdf-paper" data-testid="pdf-paper">
        <div v-if="pdfLoading" class="doc-detail-empty">影印数据加载中…</div>
        <div v-else-if="!pdfData || !pdfData.available" class="doc-detail-empty" data-testid="pdf-unavailable">
          {{ pdfData?.reason || "影印数据不可用" }}
        </div>
        <template v-else>
          <section v-for="p in pdfData.pages" :key="p.page_number" class="pdf-page"
                   :style="{ aspectRatio: String(p.width / Math.max(1, p.height)) }">
            <img v-if="pdfPageUrls[p.file]" :src="pdfPageUrls[p.file]"
                 :alt="`PDF 第 ${p.page_number} 页`" decoding="async" />
            <div v-else class="pdf-page-loading">第 {{ p.page_number }} 页加载中…</div>
            <div class="pdf-overlay">
              <button v-for="(z, zi) in (pdfZonesByPage.get(p.page_number) || [])"
                      :key="'z-' + z.block_id + '-' + zi" type="button"
                      class="pdf-block-zone" :class="['zone-' + z.kind, { sel: pdfZoneSelected(z) }]"
                      :style="{ left: z.rect.left + '%', top: z.rect.top + '%',
                                width: z.rect.width + '%', height: z.rect.height + '%' }"
                      :data-testid="`pdf-zone-${z.block_id}`"
                      :title="pdfZoneTitle(z)"
                      @click.stop="pdfZoneClick(z)">
                <span v-if="z.kind === 'echo'" class="pdf-echo-tag">{{ pdfEchoLabel(z) }}</span>
              </button>
              <span v-if="pdfSelectedZone(p.page_number)" class="pdf-zone"
                    :style="{ left: pdfSelectedZone(p.page_number)!.left + '%', top: pdfSelectedZone(p.page_number)!.top + '%',
                              width: pdfSelectedZone(p.page_number)!.width + '%', height: pdfSelectedZone(p.page_number)!.height + '%' }" />
              <button v-for="m in (pdfMarkersByPage.get(p.page_number) || [])"
                      :key="m.kind + m.id" type="button" class="pdf-marker"
                      :class="[m.kind === 'omission' ? 'marker-omission' : 'marker-req', { sel: pdfMarkerSelected(m) }]"
                      :style="{ top: `calc(${m.rect.top}% + ${m.laneOffset}px)` }"
                      :data-testid="m.kind === 'req' ? `pdf-marker-${m.id}` : undefined"
                      @click.stop="pdfMarkerClick(m)">{{ pdfMarkerLabel(m) }}</button>
            </div>
            <span class="pdf-page-label">{{ p.page_number }}</span>
          </section>
        </template>
      </article>
      <article v-else class="doc-paper" data-testid="doc-paper">
        <template v-for="(b, bi) in visibleBlocks" :key="b.block_id">
          <div v-if="pageBreakBefore(bi) !== null" class="page-break"><span>第 {{ pageBreakBefore(bi) }} 页</span></div>
          <div
            :class="['doc-block',
                     { heading: isHeading(b), omission: isOmission(b), note: isNote(b),
                       'list-item': isListItem(b),
                       anchored: anchorByBlock.get(b.block_id)?.length,
                       'in-span': selectedSpan.has(b.block_id) || b.block_id === selectedBlockId,
                       evidence: evidenceBlocks.has(b.block_id) || b.block_id === selectedBlockId }]"
            :data-testid="isOmission(b) ? 'omission-block' : undefined"
            @click="onBlockClick(b)"
          >
            <div class="doc-gutter">
              <button
                v-for="r in (anchorByBlock.get(b.block_id) || [])"
                :key="r.ai_req_id"
                class="anno-chip"
                :class="['st-' + statusOf(r), { sel: r.ai_req_id === selectedId }]"
                type="button"
                :data-testid="`anno-${r.ai_req_id}`"
                :title="`${moduleOf(r)} · ${r.title}`"
                @click.stop="select(r)"
              >{{ reqNumber(r) }} · {{ moduleOf(r) }}</button>
            </div>
            <figure v-if="isTable(b)" class="doc-table" data-testid="doc-table">
              <figcaption v-if="b.table_title">{{ b.table_title }}<span v-if="b.table_source === 'text_layout'" class="table-badge">无画线重建</span></figcaption>
              <div class="table-scroll">
                <table>
                  <thead v-if="(b.header_rows || []).length">
                    <tr v-for="(hr, hi) in b.header_rows" :key="hi"><th v-for="(c, ci) in padRow(b, hr)" :key="ci">{{ c }}</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, ri) in b.data_rows" :key="ri"><td v-for="(c, ci) in padRow(b, row)" :key="ci">{{ c }}</td></tr>
                  </tbody>
                </table>
              </div>
              <button
                v-if="isOmission(b)"
                class="omission-tag table-omission-tag"
                :class="{ sel: b.block_id === selectedBlockId }"
                type="button"
                data-testid="omission-tag"
                title="疑似需求但未被任何抽取需求覆盖，点击查看说明"
                @click.stop="selectBlockCard(b)"
              >未覆盖</button>
              <button
                v-if="echoReqsForBlock(b.block_id).length && !(anchorByBlock.get(b.block_id) || []).length"
                class="echo-tag"
                type="button"
                :data-testid="`echo-tag-${b.block_id}`"
                title="本段与已抽取需求的来源段落内容重复，点击查看汇总条目"
                @click.stop="selectBlockCard(b)"
              >{{ echoLabel(echoReqsForBlock(b.block_id)) }}</button>
            </figure>
            <p v-else class="doc-text" :class="{ 'list-item': isListItem(b) }">
              <template v-for="(seg, i) in segments(b)" :key="i"><mark v-if="seg.mark">{{ seg.text }}</mark><span v-else>{{ seg.text }}</span></template>
              <button
                v-if="isOmission(b)"
                class="omission-tag"
                :class="{ sel: b.block_id === selectedBlockId }"
                type="button"
                data-testid="omission-tag"
                title="疑似需求但未被任何抽取需求覆盖，点击查看说明"
                @click.stop="selectBlockCard(b)"
              >未覆盖</button>
              <button
                v-if="echoReqsForBlock(b.block_id).length && !(anchorByBlock.get(b.block_id) || []).length"
                class="echo-tag"
                type="button"
                :data-testid="`echo-tag-${b.block_id}`"
                title="本段与已抽取需求的来源段落内容重复，点击查看汇总条目"
                @click.stop="selectBlockCard(b)"
              >{{ echoLabel(echoReqsForBlock(b.block_id)) }}</button>
            </p>
          </div>
        </template>
      </article>

      <aside class="doc-detail" data-testid="doc-detail">
        <div v-if="!selectedReq && !selectedBlock" class="doc-detail-empty">点左侧 💬 批注查看需求详情</div>
        <div v-else-if="selectedBlock" class="doc-detail-card"
             :data-testid="selectedBlockKind === 'omission' ? 'omission-card' : (selectedBlockKind === 'echo' ? 'echo-card' : 'context-card')">
          <div class="dd-head">
            <span class="dd-module">{{ selectedBlockKind === "omission" ? "未覆盖" : (selectedBlockKind === "echo" ? "重复段" : "背景/上下文") }}</span>
            <span class="dd-status">说明</span>
          </div>
          <h3 class="dd-title">{{ selectedBlockKind === "omission" ? "为什么标为未覆盖" : (selectedBlockKind === "echo" ? "该段解析已汇总" : "为什么没有生成研发需求") }}</h3>
          <div class="dd-section"><div class="dd-body">{{ selectedBlockKind === "omission" ? OMISSION_REASON : (selectedBlockKind === "echo" ? ECHO_REASON : CONTEXT_REASON) }}</div></div>
          <div v-if="selectedBlockKind === 'echo' && orderedSelectedEchoReqs.length" class="dd-section">
            <button v-for="req in orderedSelectedEchoReqs" :key="req.ai_req_id"
                    class="echo-jump" data-testid="echo-jump" type="button"
                    @click.stop="jumpToEchoReq(req)">
              查看批注 {{ reqNumber(req) }}《{{ req.title }}》
            </button>
          </div>
          <div class="dd-section">
            <div class="dd-label">原文翻译</div>
            <div v-if="selectedBlock.translation" class="dd-body" data-testid="omission-translation">{{ selectedBlock.translation }}</div>
            <div v-else-if="selectedBlock.translation_note" class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（{{ selectedBlock.translation_note }}）</div>
            <div v-else class="dd-body dd-empty">未生成翻译（开启 LLM 后点「导出批注HTML」可自动补齐，刷新即见）</div>
          </div>
          <div class="dd-section">
            <div class="dd-label">原文引用</div>
            <div class="dd-quote">{{ selectedBlock.text }}</div>
          </div>
        </div>
        <div v-else-if="selectedReq" class="doc-detail-card">
          <div class="dd-head">
            <span class="dd-module" data-testid="dd-module">{{ moduleOf(selectedReq) }}</span>
            <span class="dd-status" :class="'st-' + statusOf(selectedReq)">{{ STATUS_LABELS[statusOf(selectedReq)] || statusOf(selectedReq) }}</span>
          </div>
          <h3 class="dd-title">{{ selectedReq.title }}</h3>
          <div class="dd-meta">{{ selectedReq.type }} · {{ selectedReq.priority }} · {{ selectedReq.source_section }}</div>
          <div v-if="(selectedReq.suspicion_reasons || []).length" class="dd-suspicion" data-testid="dd-suspicion">
            ⚠ 建议优先复核：{{ (selectedReq.suspicion_reasons || []).join("、") }}
          </div>
          <div v-if="(selectedReq.consistency_flags || []).length" class="dd-consistency" data-testid="dd-consistency">
            ⇄ 全文档一致性：{{ (selectedReq.consistency_flags || []).join("；") }}
          </div>

          <div class="dd-legend">正文标记：<span style="background:#f3d9a0;padding:0 4px">黄=引用依据</span> · <span style="background:#eef2ff;padding:0 4px">蓝=证据段</span> · 左侧细条=分析上下文</div>
          <div class="dd-section" v-if="ownershipOf(selectedReq) !== 'hardware' && selectedReq.functional_requirement_id" data-testid="dd-functional">
            <div class="dd-label">所属研发功能</div>
            <div class="dd-body"><strong>{{ selectedReq.functional_title || selectedReq.functional_requirement_id }}</strong></div>
            <div v-if="mergeBadgeOf(selectedReq)" :class="mergeWarnOf(selectedReq) ? 'dd-suspicion' : 'dd-consistency'"
                 data-testid="dd-merge">⧉ {{ mergeBadgeOf(selectedReq) }}</div>
            <div v-if="selectedReq.functional_objective" class="dd-body">{{ selectedReq.functional_objective }}</div>
            <template v-if="(selectedReq.functional_behaviors || []).length">
              <div class="dd-label">功能行为</div>
              <ul class="dd-list"><li v-for="(b, i) in selectedReq.functional_behaviors" :key="i">{{ b }}</li></ul>
            </template>
            <template v-if="(selectedReq.functional_preconditions || []).length">
              <div class="dd-label">前置条件</div>
              <ul class="dd-list"><li v-for="(p, i) in selectedReq.functional_preconditions" :key="i">{{ p }}</li></ul>
            </template>
            <template v-if="(selectedReq.functional_data_constraints || []).length">
              <div class="dd-label">数据约束</div>
              <ul class="dd-list"><li v-for="(c, i) in selectedReq.functional_data_constraints" :key="i">{{ c }}</li></ul>
            </template>
            <template v-if="(selectedReq.functional_variants || []).length">
              <div class="dd-label">功能变体</div>
              <ul class="dd-list"><li v-for="(v, i) in selectedReq.functional_variants" :key="i"><strong>{{ v.name || "变体" }}</strong>：{{ v.behavior || "" }}</li></ul>
            </template>
            <div v-if="(selectedReq.functional_conflict_flags || []).length" class="dd-suspicion"
                 data-testid="dd-conflict">待澄清冲突：{{ (selectedReq.functional_conflict_flags || []).join("；") }}</div>
          </div>
          <div class="dd-section" v-else-if="ownershipOf(selectedReq) !== 'hardware'" data-testid="dd-requirement-summary">
            <div class="dd-label">需求摘要</div>
            <div class="dd-body">{{ selectedReq.description || "未生成需求摘要" }}</div>
          </div>
          <div class="dd-section" v-if="ownershipOf(selectedReq) === 'hardware'">
            <div class="dd-label">中文翻译 / 说明</div>
            <div v-if="hardwareTranslationOf(selectedReq)" class="dd-body" data-testid="dd-hw-translation">{{ hardwareTranslationOf(selectedReq) }}</div>
            <div v-else class="dd-body dd-empty">未生成翻译（开启 LLM 后点「导出批注HTML」可自动补齐，刷新即见）</div>
          </div>
          <div class="dd-section" v-if="(selectedReq.sub_items || []).length">
            <div class="dd-label">子项要求（二级）</div>
            <ul class="dd-list" data-testid="dd-subitems">
              <li v-for="(it, i) in selectedReq.sub_items" :key="i"><strong>{{ it.label || "·" }})</strong> {{ it.text }}</li>
            </ul>
          </div>
          <div class="dd-section" v-if="selectedReq.threshold_table && (selectedReq.threshold_table.rows || []).length">
            <div class="dd-label">参数表（数值原样照抄原文）</div>
            <table class="dd-table" data-testid="dd-threshold">
              <thead v-if="(selectedReq.threshold_table.columns || []).length">
                <tr><th v-for="(c, i) in selectedReq.threshold_table.columns" :key="i">{{ c }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in selectedReq.threshold_table.rows" :key="ri">
                  <td v-for="(cell, ci) in (Array.isArray(row) ? row : [row])" :key="ci">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="dd-section" v-if="devGuidanceOf(selectedReq).length">
            <div class="dd-label">研发指引 / 落地实现</div>
            <ul class="dd-list"><li v-for="(g, i) in devGuidanceOf(selectedReq)" :key="i">{{ g }}</li></ul>
          </div>
          <div class="dd-section" v-if="acceptanceOf(selectedReq).length">
            <div class="dd-label">测试指引 / 验收</div>
            <ul class="dd-list"><li v-for="(c, i) in acceptanceOf(selectedReq)" :key="i">{{ c }}</li></ul>
          </div>
          <div class="dd-section" v-if="selectedReq.source_quote">
            <div class="dd-label">原文引用</div><div class="dd-quote">{{ selectedReq.source_quote }}</div>
          </div>
          <div class="dd-section" v-if="ownershipReasonOf(selectedReq)">
            <div class="dd-label">为什么判为{{ OWNERSHIP_LABELS[ownershipOf(selectedReq)] || ownershipOf(selectedReq) }}</div>
            <div class="dd-body" data-testid="dd-ownership-reason">{{ ownershipReasonOf(selectedReq) }}</div>
            <div v-if="ownershipOverrideNote(selectedReq)" class="dd-body dd-empty">{{ ownershipOverrideNote(selectedReq) }}</div>
          </div>

          <div class="dd-section">
            <div class="dd-label">模块（可改）</div>
            <select v-model="moduleEdit" class="dd-select" data-testid="dd-module-select">
              <option v-for="m in MODULE_VOCAB" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          <div class="dd-section">
            <div class="dd-label">归属（可改，规则初判：{{ OWNERSHIP_OPTIONS.find(o => o.value === selectedReq?.ownership)?.label || "软件" }}）</div>
            <select v-model="ownershipEdit" class="dd-select" data-testid="dd-ownership-select">
              <option v-for="o in OWNERSHIP_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
          <textarea v-model="comment" class="dd-comment" data-testid="dd-comment" placeholder="审查意见（可选）" />
          <div class="dd-actions">
            <button class="button primary" type="button" data-testid="dd-accept" :disabled="isSaving" @click="decide('accepted')">接受</button>
            <button class="button" type="button" data-testid="dd-reject" :disabled="isSaving" @click="decide('rejected')">拒绝</button>
            <button class="button" type="button" data-testid="dd-discuss" :disabled="isSaving" @click="decide('needs_discussion')">讨论</button>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.doc-review { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.doc-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 8px 14px; border-bottom: 1px solid #e6e9f0; }
.doc-stats { display: flex; gap: 18px; font-size: 13px; color: #5c6675; }
.doc-stats strong { color: #1a2233; }
.omission-stat.warn strong { color: #5c6675; }
.doc-message { padding: 6px 14px; font-size: 12px; color: #b45309; background: #fdf3e3; }
.doc-body { display: grid; grid-template-columns: 1fr 360px; gap: 0; flex: 1; min-height: 0; }
.doc-paper { overflow: auto; padding: 12px 18px; background: #ffffff; }
.doc-toolbar-actions { display: flex; align-items: center; gap: 10px; }
.mode-toggle { display: flex; gap: 2px; padding: 2px; background: #eef1f6; border-radius: 8px; }
.mode-toggle button { border: 0; border-radius: 6px; padding: 4px 10px; font-size: 12px; color: #5c6675;
  background: transparent; cursor: pointer; }
.mode-toggle button.active { background: #ffffff; color: #1e41c9; box-shadow: 0 1px 2px rgba(0,0,0,.08); }
/* 原版影印：页图 + 百分比批注覆盖层（与分享 HTML 同源数据） */
.pdf-paper { background: #eceef2; padding: 16px; }
.pdf-page { position: relative; margin: 0 auto 14px; max-width: 920px; background: #ffffff;
  box-shadow: 0 2px 10px rgba(0,0,0,.10); border-radius: 4px; overflow: hidden; }
.pdf-page img { display: block; width: 100%; height: auto; }
.pdf-page-loading { position: absolute; inset: 0; display: flex; align-items: center;
  justify-content: center; color: #98a1b3; font-size: 12px; }
.pdf-overlay { position: absolute; inset: 0; }
.pdf-zone { position: absolute; background: rgba(89,120,247,.14); outline: 2px solid rgba(89,120,247,.55);
  border-radius: 2px; pointer-events: none; }
.pdf-marker { position: absolute; right: 6px; min-width: 26px; height: 22px; border-radius: 11px;
  border: 1px solid #cbd5e1; background: #ffffff; color: #1e41c9; font-size: 11px; font-weight: 700;
  cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,.14); z-index: 3; }
.pdf-marker.marker-omission { color: #b45309; border-color: #ecd9ae; background: #fdf3e3; }
.pdf-marker.sel { outline: 2px solid #5978f7; }
/* 全段落热区（0714）：透明可点,悬停淡蓝提示——点一段出翻译和解析;标记浮在热区上层 */
.pdf-block-zone { position: absolute; z-index: 1; margin: 0; padding: 0; border: 1px solid transparent;
  background: transparent; cursor: pointer; border-radius: 3px;
  transition: background .12s, border-color .12s; }
.pdf-block-zone:hover { background: rgba(89, 120, 247, .08); border-color: rgba(89, 120, 247, .5); }
.pdf-block-zone.sel { background: rgba(89, 120, 247, .12); border-color: rgba(89, 120, 247, .85); }
.pdf-block-zone.zone-omission:hover { background: rgba(204, 137, 37, .10); border-color: rgba(204, 137, 37, .55); }
.pdf-block-zone.zone-omission.sel { background: rgba(204, 137, 37, .14); border-color: rgba(180, 83, 9, .8); }
.pdf-block-zone.zone-echo:hover, .pdf-block-zone.zone-echo.sel {
  background: rgba(15,118,110,.08); border-color: rgba(15,118,110,.55); }
.pdf-echo-tag { position: absolute; right: 2px; top: -13px; display: inline-block; padding: 0 2px 1px;
  border-bottom: 1px dashed #667085; color: #4b5563; background: rgba(255,255,255,.92);
  font-size: 9px; font-weight: 600; line-height: 1.15; white-space: nowrap; pointer-events: none; }
.pdf-page-label { position: absolute; left: 8px; bottom: 6px; font-size: 10px; color: #98a1b3;
  background: rgba(255,255,255,.85); border-radius: 6px; padding: 1px 6px; }
.doc-block { display: grid; grid-template-columns: 108px 1fr; gap: 8px; padding: 1px 4px; margin-bottom: 0; border-left: 2px solid transparent; cursor: default; }
.doc-block:not(.heading):not(.list-item) { margin-bottom: 6px; }
.doc-block.list-item { margin-bottom: 1px; }
.doc-block.list-item + .doc-block:not(.list-item):not(.heading) { margin-top: 5px; }
.doc-block.heading .doc-text { font-weight: 700; color: #1a2233; margin-top: 6px; }
.doc-block.anchored { cursor: pointer; border-left-color: #5978f7; background: #fafbfd; }
.page-break { display: flex; align-items: center; gap: 10px; margin: 16px 0 10px; color: #98a1b3; font-size: 11px; }
.page-break::before, .page-break::after { content: ""; flex: 1; border-top: 1px dashed #e6e9f0; }

/* 阅读排版：正文两端对齐、列表悬挂缩进、真表格（与自包含 HTML 同视觉） */
.doc-block:not(.heading) .doc-text { text-align: justify; hyphens: none; }
.doc-text.list-item { padding-left: 1.6em; text-indent: -1.6em; text-align: left; }
.doc-block.note .doc-text { padding-left: 3.4em; text-indent: -3.4em; }
.doc-table { margin: 10px 0 12px; }
.doc-table figcaption { font-size: 12px; font-weight: 600; color: #7a8496; margin-bottom: 6px; letter-spacing: .02em; }
.doc-table .table-badge { font-size: 10px; font-weight: 500; color: #b06f12; background: #fdf3e3;
  border: 1px solid #f3d9a0; border-radius: 999px; padding: 1px 7px; margin-left: 8px; vertical-align: 1px; }
.doc-table .table-scroll { overflow-x: auto; border: 1px solid #e6e9f0; border-radius: 8px; }
.doc-table table { border-collapse: collapse; width: 100%; font-size: 12.5px; line-height: 1.5; }
.doc-table th, .doc-table td { border: 0; border-bottom: 1px solid #eceff5; border-right: 1px solid #f1f3f8;
  padding: 6px 10px; text-align: left; vertical-align: top; min-width: 52px; }
.doc-table th:last-child, .doc-table td:last-child { border-right: 0; }
.doc-table thead th { background: #fafbfd; font-weight: 650; color: #3f4a61; }
.doc-table tbody tr:nth-child(even) td { background: #fafbfd; }
.doc-table tbody tr:last-child td { border-bottom: 0; }

.doc-block.in-span { box-shadow: inset 3px 0 0 #c7d3fc; }
.doc-block.in-span.evidence { background: #eef2ff; box-shadow: none; }
.dd-legend { font-size: 11px; color: #98a1b3; margin: 4px 0 8px; }
.doc-block.omission:hover { background: #fcfbf7; }
.doc-gutter { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
.doc-text { margin: 0; font-size: 13px; line-height: 1.48; color: #3f4a61; white-space: pre-wrap; }
.doc-text mark { background: #f3d9a0; padding: 0 1px; }
.anno-chip { font-size: 11px; border: 1px solid #cbd5e1; border-radius: 10px; padding: 1px 7px; background: #ffffff; cursor: pointer; max-width: 124px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anno-chip.sel { outline: 2px solid #5978f7; }
.anno-chip.st-accepted { border-color: #1d8a5c; color: #1d8a5c; }
.anno-chip.st-rejected { border-color: #d63a40; color: #d63a40; }
.anno-chip.st-needs_discussion { border-color: #b06f12; color: #b06f12; }
.omission-tag { display: inline-flex; margin-left: 6px; padding: 0 2px 1px; border: 0;
  border-bottom: 1px dotted #cbd5e1; border-radius: 0; background: transparent; color: #98a1b3;
  font-size: 9px; line-height: 1; cursor: pointer; vertical-align: super; }
.omission-tag:hover, .omission-tag.sel { color: #b06f12; border-color: #b06f12; background: #fff9ec; }
.echo-tag { display: inline-flex; margin-left: 6px; padding: 0 2px 1px; border: 0;
  border-bottom: 1px dashed #cbd5e1; border-radius: 0; background: transparent; color: #7a8496;
  font-size: 9px; line-height: 1; cursor: pointer; vertical-align: super; }
.echo-tag:hover { color: #1f5f58; border-color: #1f5f58; }
.echo-jump { display: block; margin: 3px 0; padding: 0; border: 0; background: transparent;
  color: #1d7a5b; font: inherit; text-align: left; text-decoration: underline dotted; cursor: pointer; }
.table-omission-tag { margin-top: 4px; vertical-align: baseline; }
.dd-empty { color: #98a1b3; }
.dd-prewrap { white-space: pre-wrap; }
.src-badge { font-size: 10px; text-transform: none; color: #1e41c9; background: #eef2ff;
  border: 1px solid #dbe3fb; border-radius: 8px; padding: 0 6px; margin-left: 4px; }
.src-badge.quiet { color: #98a1b3; background: transparent; border-color: #e6e9f0; }
.doc-detail { border-left: 1px solid #e6e9f0; overflow: auto; padding: 14px; background: #fafbfd; }
.doc-detail-empty { color: #98a1b3; font-size: 13px; padding-top: 40px; text-align: center; }
.dd-head { display: flex; justify-content: space-between; align-items: center; }
.dd-module { font-weight: 700; color: #1e41c9; }
.dd-status { font-size: 12px; padding: 1px 8px; border-radius: 8px; background: #e6e9f0; }
.dd-status.st-accepted { background: #e6f6ef; color: #1d8a5c; }
.dd-status.st-rejected { background: #fdecec; color: #991b1b; }
.dd-title { margin: 8px 0 2px; font-size: 15px; }
.dd-meta { font-size: 12px; color: #7a8496; margin-bottom: 8px; }
.dd-suspicion { font-size: 12px; color: #b06f12; background: #fdf3e3; border-radius: 6px; padding: 4px 8px; margin-bottom: 8px; }
.dd-consistency { font-size: 12px; color: #1e41c9; background: #eef2ff; border-radius: 6px; padding: 4px 8px; margin-bottom: 8px; }
.dd-table { border-collapse: collapse; font-size: 12px; width: 100%; }
.dd-table th, .dd-table td { border: 1px solid #e6e9f0; padding: 3px 8px; text-align: left; }
.dd-table th { background: #fafbfd; font-weight: 600; }
.dd-section { margin: 10px 0; }
.dd-label { font-size: 11px; color: #98a1b3; text-transform: uppercase; margin-bottom: 3px; }
.dd-body { font-size: 13px; line-height: 1.55; color: #3f4a61; }
.dd-list { margin: 0; padding-left: 18px; font-size: 13px; color: #3f4a61; }
.dd-quote { font-size: 12px; color: #5c6675; border-left: 3px solid #cbd5e1; padding-left: 8px; font-style: italic; }
.dd-select, .dd-comment { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px; font-size: 13px; }
.dd-comment { min-height: 56px; margin-top: 8px; resize: vertical; }
.dd-actions { display: flex; gap: 8px; margin-top: 10px; }
</style>
