<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue"
import { Ban, Check, ChevronLeft, ChevronRight, Image, MessageSquareText, MessagesSquare, RefreshCw, Rows3, Wand2 } from "@lucide/vue"
import type {
  AiExtractionStatusPayload,
  AiRequirement,
  ClaimAnnotationRecord,
  ClaimAnnotationZone,
  ClarificationInternalChecksPayload,
  DocumentBlock,
  OmissionActionState,
  OmissionActionStatus,
  PdfAnnotationPayload,
  PdfCellContext,
  PdfZoneRect,
  RequirementApiClient,
} from "./api-client"
import { isNeedsReconfirmationError } from "./api-client"
import { useReviewShortcuts } from "./useReviewShortcuts"

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
  & Partial<Pick<RequirementApiClient,
    "loadHealth" | "loadAiExtractionStatus" | "loadOmissionActions" | "applyOmissionAction" | "reextractOmission" |
    "loadClarificationInternalChecks" | "applyClarificationCheckBatch" | "spotExtract">>
const props = withDefaults(defineProps<{
  client: DocClient | null
  active: boolean
  refreshToken?: number
  sessionKey?: string
  focusBlockId?: string
}>(), { refreshToken: 0, sessionKey: "", focusBlockId: "" })

const blocks = ref<DocumentBlock[]>([])
const requirements = ref<AiRequirement[]>([])
const moduleOptions = ref<string[]>([...MODULE_VOCAB])
const loading = ref(false)
const message = ref("")
const selectedId = ref("")
const isSaving = ref(false)
const comment = ref("")
const moduleEdit = ref("")
const ownershipEdit = ref("")
const extractionStatus = ref<AiExtractionStatusPayload | null>(null)
const omissionStates = ref<OmissionActionState[]>([])
const omissionSaving = ref(false)
const omissionNote = ref("")
// 点解析（WP-B）：在飞的 "blockId:rowIndex" 键，空串=空闲；按钮不隐藏，无 LLM 配置点击返回真实错误
const spotExtracting = ref("")
const internalChecks = ref<ClarificationInternalChecksPayload | null>(null)
const internalCheckSignal = ref("")
const internalCheckSaving = ref(false)
// D7 预备：文本模式删除开关（默认保留；后端 /health 下发）
const textModeEnabled = ref(true)
type RequirementDraft = { comment: string; module: string; ownership: string }
const requirementDrafts = new Map<string, RequirementDraft>()
const omissionDrafts = new Map<string, string>()

// 与后端 requirements_analysis_schema 的三值归属一致
const OWNERSHIP_OPTIONS = [
  { value: "software", label: "软件" },
  { value: "hardware", label: "硬件" },
  { value: "co_design", label: "软硬件协同" },
]
let loadedOnce = false
let contentLoadGeneration = 0
let reviewOperationGeneration = 0
let omissionOperationGeneration = 0
let internalCheckOperationGeneration = 0

function stashRequirementDraft(id = selectedId.value) {
  if (!id) return
  requirementDrafts.set(id, {
    comment: comment.value,
    module: moduleEdit.value,
    ownership: ownershipEdit.value,
  })
}

function stashOmissionDraft(blockId = selectedBlockId.value) {
  if (!blockId) return
  omissionDrafts.set(blockId, omissionNote.value)
}

function clearRequirementEditor() {
  comment.value = ""
  moduleEdit.value = ""
  ownershipEdit.value = ""
}

function replaceRequirements(rows: AiRequirement[]) {
  requirements.value = rows
  if (selectedId.value && !rows.some((row) => row.ai_req_id === selectedId.value)) {
    stashRequirementDraft()
    selectedId.value = ""
    clearRequirementEditor()
  }
}

function setOmissionStates(states: OmissionActionState[] | undefined) {
  omissionStates.value = Array.isArray(states) ? states : []
}

function setInternalChecks(payload: ClarificationInternalChecksPayload | null) {
  internalChecks.value = payload
  const groups = payload?.groups || []
  if (!groups.some((group) => group.signal === internalCheckSignal.value)) {
    internalCheckSignal.value = groups[0]?.signal || ""
  }
}

async function load() {
  const client = props.client
  if (!client) {
    message.value = "未连接输出目录——先运行管线 + AI 抽取"
    return
  }
  const generation = ++contentLoadGeneration
  loading.value = true
  message.value = ""
  try {
    const [doc, reqs, partial, omissionPayload, checksPayload] = await Promise.all([
      client.loadDocument(),
      client.loadAiRequirements(),
      client.loadAiExtractionStatus?.().catch(() => null) ?? Promise.resolve(null),
      client.loadOmissionActions?.().catch(() => null) ?? Promise.resolve(null),
      client.loadClarificationInternalChecks?.().catch(() => null) ?? Promise.resolve(null),
    ])
    if (client !== props.client || generation !== contentLoadGeneration) return
    blocks.value = doc.blocks || []
    moduleOptions.value = [...new Set([...MODULE_VOCAB, ...(doc.module_vocabulary || [])])]
    loadedOnce = true
    extractionStatus.value = partial
    replaceRequirements(partial?.run_id && !partial.complete ? partial.rows || [] : reqs || [])
    setOmissionStates(omissionPayload?.states)
    setInternalChecks(checksPayload)
    if (!requirements.value.length) {
      message.value = "暂无 AI 抽取需求——请先开 LLM 跑「AI 抽取」"
    }
    // F4：blocks 就绪后兑现挂起的来源块定位（functional 评审跳转先于 load 到达）
    if (pendingFocusBlockId) {
      const target = pendingFocusBlockId
      pendingFocusBlockId = ""
      void applyFocusBlock(target)
    }
  } catch (error) {
    if (client === props.client && generation === contentLoadGeneration) {
      message.value = error instanceof Error ? error.message : "加载失败"
    }
  } finally {
    if (client === props.client && generation === contentLoadGeneration) loading.value = false
  }
}

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

// 来源跨度中除锚点外的段落也参与了需求解析。点击时应展示关联需求，不能误称为背景。
// section_fallback 行只认原句匹配块——跨小节回退跨度若整段计入，无关清单段会被
// 误标"分析范围"（test5 "- DAY1" 实证）。
const coveredByBlock = computed(() => {
  const map = new Map<string, AiRequirement[]>()
  for (const req of requirements.value) {
    const anchor = req.anchor_block_id || (req.source_block_ids || [])[0]
    const span = req.source_mapping === "section_fallback"
      ? (req.quote_block_ids || [])
      : (req.source_block_ids || [])
    for (const source of span) {
      if (!source || source === anchor) continue
      const list = map.get(source) || []
      if (!list.some((item) => item.ai_req_id === req.ai_req_id)) list.push(req)
      map.set(source, list)
    }
  }
  return map
})

// 后端用可靠 source_quote/source_mapping 计算覆盖集合；旧 API 才回退本地字段。
const coveredBlocks = computed(() => {
  const s = new Set<string>()
  const hasServerCoverage = blocks.value.some((block) => block.covered_by_requirement !== undefined)
  if (hasServerCoverage) {
    for (const block of blocks.value) {
      if (block.covered_by_requirement) s.add(block.block_id)
    }
    return s
  }
  for (const req of requirements.value) {
    const mapping = String(req.source_mapping || "")
    const reliable = new Set(["exact", "contains", "multi_block", "fuzzy"]).has(mapping)
    if (reliable || !mapping) {
      for (const b of req.source_block_ids || []) s.add(b)
    }
    for (const b of req.echo_block_ids || []) s.add(b)
  }
  return s
})

const selectedReq = computed(() => requirements.value.find((r) => r.ai_req_id === selectedId.value) || null)

// 块级三段式卡片：未覆盖段/背景段（与导出 HTML 同语义/同文案——双渲染器契约）。
// 目标：全文每一段都有分析结果——需求段有批注,其余段点开能看到为什么没生成需求+翻译+引用。
const OMISSION_REASON = "该段含规范性措辞（shall/must/应…），被判为疑似需求，但没有任何已抽取需求的来源范围覆盖它。可能原因：抽取遗漏（自检未补回）或该句实为背景说明。确属需求请反馈补抽；背景说明可忽略。"
const CONTEXT_REASON = "该段未检出规范性措辞（shall/must/应…），被判定为背景/说明性内容，因此没有生成研发需求；其信息会作为上下文供相邻需求的分析使用。如认为该段实际包含需求，请反馈补抽。"
const FAILED_EXTRACTION_REASON = "该章节的 AI 抽取调用失败，当前段落没有得到完整分析。失败通常来自端点、密钥、限流或超时；请在重跑成功前不要把这里的空白视为“无需求”。"
const COVERED_REASON = "该段已纳入一条或多条抽取需求的来源范围，用于补充完整语义、条件或约束；它不是独立锚点，因此不重复挂页边编号。可从下方查看关联需求。"
const REQ_GROUP_REASON = "该段原文解析出了多条独立需求。为避免只展示第一条，下面列出该段的全部解析结果。"
// 与导出 HTML 同文案（双渲染器契约）
const ECHO_REASON = "该段与已抽取需求的来源段落内容重复（同文多次出现）。解析已汇总至对应需求条目，本段不重复挂批注；点击「重复·见」角标或下方链接可跳转查看该条目。"
const selectedBlockId = ref("")
// 表格行选中态（v12 行级热区，"<block_id>#R<行号>"，与后端行卡片键同源）——
// 声明必须在 immediate watch 之前（watch 首次同步执行会清空它）
const selectedRowKey = ref("")
// 单元格选中态（v14 cell 级闭环，"<block_id>#<cell_id>"，与后端 cell_context 键同源）
const selectedCellKey = ref("")
const selectedClaimId = ref("")
// F4：来源块定位（functional 评审跳转传入）——瞬时高亮环 + 滚动；blocks 未就绪时挂起等 load 完成
const focusedBlockId = ref("")
let pendingFocusBlockId = ""
let focusRingTimer: ReturnType<typeof setTimeout> | undefined
const selectedBlock = computed(() => blocks.value.find((b) => b.block_id === selectedBlockId.value) || null)
const selectedBlockKind = computed(() => {
  if (!selectedBlock.value) return "context"
  if (selectedBlock.value.extraction_failed) return "failed"
  if ((anchorByBlock.value.get(selectedBlock.value.block_id) || []).length > 1) return "req_group"
  if (echoByBlock.value.has(selectedBlock.value.block_id)) return "echo"
  if (coveredByBlock.value.has(selectedBlock.value.block_id)) return "covered"
  return isOmission(selectedBlock.value) ? "omission" : "context"
})
const selectedRepairEvents = computed(() =>
  (selectedBlock.value?.text_repairs || []).filter((event) => event && typeof event === "object"))
function repairEventText(event: Record<string, unknown>, key: "before" | "after" | "rule"): string {
  return String(event[key] || "")
}
function repairRulesOf(block: DocumentBlock): string {
  return [...new Set((block.text_repairs || []).map((event) => String(event.rule || "")).filter(Boolean))].join("、")
}
const selectedRelatedReqs = computed(() => {
  if (!selectedBlock.value) return []
  const blockId = selectedBlock.value.block_id
  if (selectedBlockKind.value === "req_group") return anchorByBlock.value.get(blockId) || []
  return (selectedBlockKind.value === "covered" ? coveredByBlock.value.get(blockId) : echoByBlock.value.get(blockId)) || []
})
function selectBlockCard(b: DocumentBlock) {
  stashRequirementDraft()
  stashOmissionDraft()
  selectedRowKey.value = ""
  selectedCellKey.value = ""
  selectedClaimId.value = ""
  if (selectedBlockId.value === b.block_id) {  // 再点一下 → 取消选中
    selectedBlockId.value = ""
    omissionNote.value = ""
    return
  }
  selectedBlockId.value = b.block_id
  selectedId.value = ""
  clearRequirementEditor()
  omissionNote.value = omissionDrafts.get(b.block_id) || ""
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
const viewMode = ref<"text" | "pdf">("pdf")
const pdfData = ref<PdfAnnotationPayload | null>(null)
const selectedClaim = computed(() =>
  (pdfData.value?.claim_records || []).find((row) => row.claim_id === selectedClaimId.value) || null)
type ClaimSourceField = { name: string; value: string }
type ClaimSourceValueGroup = { label: string; value: string }
const SYNTHETIC_CLAIM_FIELD_RE = /^column_\d+$/i
const CLAUSE_INDEX_RE = /^\d+(?:\.\d+)+(?:[.)])?$/
const selectedClaimSourceFields = computed<ClaimSourceField[]>(() => {
  const fields = selectedClaim.value?.table_context?.fields
  if (!Array.isArray(fields)) return []
  return fields
    .map((field) => ({ name: String(field?.name || ""), value: String(field?.value || "") }))
    .filter((field) => field.value.trim())
})
const selectedClaimHasRowIdentity = computed(() => {
  const fields = selectedClaimSourceFields.value
  return fields.length >= 2 && CLAUSE_INDEX_RE.test(fields[0].value.trim())
})
const selectedClaimDisplayTitle = computed(() => {
  const fields = selectedClaimSourceFields.value
  if (selectedClaimHasRowIdentity.value) return `${fields[0].value} · ${fields[1].value}`
  return selectedClaim.value?.text || selectedClaim.value?.claim_id || ""
})
const selectedClaimSourceValues = computed<ClaimSourceValueGroup[]>(() => {
  const fields = selectedClaimSourceFields.value
  const source = selectedClaimHasRowIdentity.value ? fields.slice(2) : fields
  const groups: Array<ClaimSourceValueGroup & { first: number; last: number; synthetic: boolean }> = []
  source.forEach((field, index) => {
    const ordinal = index + 1
    const synthetic = SYNTHETIC_CLAIM_FIELD_RE.test(field.name)
    const previous = groups.at(-1)
    if (previous && previous.value === field.value && previous.synthetic === synthetic) {
      previous.last = ordinal
      if (!synthetic && field.name && !previous.label.split("、").includes(field.name)) {
        previous.label += `、${field.name}`
      }
      return
    }
    groups.push({
      label: synthetic ? "" : field.name,
      value: field.value,
      first: ordinal,
      last: ordinal,
      synthetic,
    })
  })
  return groups.map((group) => ({
    label: group.synthetic
      ? `值 ${group.first}${group.last > group.first ? `–${group.last}` : ""}`
      : (group.label || `值 ${group.first}`),
    value: group.value,
  }))
})
const pdfLoading = ref(false)
const pdfPageUrls = ref<Record<string, string>>({})
let pdfPageLoadGeneration = 0
let pdfDataLoadGeneration = 0
let pdfDataLoadPromise: Promise<boolean> | null = null
let workspaceLoadGeneration = 0
let modeSelectionGeneration = 0
let pdfPageLoadsDisposed = false
let textModeWasFallback = false

function revokePdfPageUrl(url: string) {
  if (typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(url)
  }
}

const PDF_PAGE_CONCURRENCY = 6   // 页图并发上限（顺序拉取 82 页实测数秒,限流并发≈6x 提速;
                                 // 带鉴权头 fetch→blob 的安全约束不变,token 仍不进 URL）

async function loadPdfPages(payload: PdfAnnotationPayload, client = props.client) {
  if (pdfPageLoadsDisposed || !client) return
  const activeClient = client   // 固化非空引用（异步闭包内 TS narrowing 不穿透）
  const generation = ++pdfPageLoadGeneration
  // 限流并发拉取页图（原顺序拉取——82 页文档逐页 await,实测数秒才出第一屏）。
  // 按文档序处理（首屏页先好）;单页失败不阻断其余;世代/销毁守卫与原版一致。
  const queue = [...(payload.pages || [])]
  let cursor = 0
  async function worker() {
    while (true) {
      if (pdfPageLoadsDisposed || generation !== pdfPageLoadGeneration || activeClient !== props.client) return
      const index = cursor++
      if (index >= queue.length) return
      const page = queue[index]
      if (pdfPageUrls.value[page.file]) continue
      try {
        const url = await activeClient.loadPdfPageBlob(page.file)
        if (pdfPageLoadsDisposed || generation !== pdfPageLoadGeneration || activeClient !== props.client) {
          revokePdfPageUrl(url)
          return
        }
        pdfPageUrls.value = { ...pdfPageUrls.value, [page.file]: url }
      } catch {
        /* 页图缺失/网络抖动:保留占位框,不影响其它页 */
      }
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(PDF_PAGE_CONCURRENCY, queue.length) }, () => worker()),
  )
}

function applyPdfMetadata(payload: PdfAnnotationPayload, client: DocClient) {
  const files = new Set((payload.pages || []).map((page) => page.file))
  const retained: Record<string, string> = {}
  for (const [file, url] of Object.entries(pdfPageUrls.value)) {
    if (files.has(file)) retained[file] = url
    else revokePdfPageUrl(url)
  }
  pdfPageUrls.value = retained
  pdfData.value = payload
  if (payload.available) void loadPdfPages(payload, client)
}

async function refreshPdfMetadata(client: DocClient, workspaceGeneration = workspaceLoadGeneration) {
  const generation = ++pdfDataLoadGeneration
  pdfDataLoadPromise = null
  pdfLoading.value = false
  try {
    const payload = await client.loadPdfAnnotation()
    if (pdfPageLoadsDisposed || client !== props.client || generation !== pdfDataLoadGeneration
        || workspaceGeneration !== workspaceLoadGeneration) return
    applyPdfMetadata(payload, client)
  } catch {
    // 增量刷新只更新标记元数据；短暂失败时保留当前可核对页面。
  }
}

async function ensurePdfData(): Promise<boolean> {
  if (pdfData.value) return Boolean(pdfData.value.available)
  if (pdfDataLoadPromise) return pdfDataLoadPromise
  const client = props.client
  if (!client || pdfPageLoadsDisposed) return false
  const generation = pdfDataLoadGeneration
  pdfLoading.value = true
  const request = client.loadPdfAnnotation()
    .then((payload) => {
      if (pdfPageLoadsDisposed || generation !== pdfDataLoadGeneration || client !== props.client) return false
      applyPdfMetadata(payload, client)
      return Boolean(payload.available)
    })
    .catch((error: unknown) => {
      if (pdfPageLoadsDisposed || generation !== pdfDataLoadGeneration || client !== props.client) return false
      pdfData.value = { available: false, reason: error instanceof Error ? error.message : "影印数据加载失败" }
      return false
    })
    .finally(() => {
      if (generation === pdfDataLoadGeneration && pdfDataLoadPromise === request) {
        pdfDataLoadPromise = null
        pdfLoading.value = false
      }
    })
  pdfDataLoadPromise = request
  return request
}

async function loadWorkspace() {
  const workspaceGeneration = ++workspaceLoadGeneration
  const modeGeneration = modeSelectionGeneration
  await load()
  if (workspaceGeneration !== workspaceLoadGeneration || viewMode.value !== "pdf") return
  const available = await ensurePdfData()
  if (workspaceGeneration !== workspaceLoadGeneration || modeGeneration !== modeSelectionGeneration) return
  if (!available && viewMode.value === "pdf") {
    viewMode.value = "text"
    textModeWasFallback = true
  }
}

async function reloadWorkspace() {
  const workspaceGeneration = ++workspaceLoadGeneration
  const modeGeneration = modeSelectionGeneration
  const shouldRestorePdf = viewMode.value === "pdf" || textModeWasFallback
  pdfDataLoadGeneration += 1
  pdfDataLoadPromise = null
  pdfLoading.value = false
  pdfPageLoadGeneration += 1
  const urls = new Set(Object.values(pdfPageUrls.value))
  pdfPageUrls.value = {}
  for (const url of urls) revokePdfPageUrl(url)
  pdfData.value = null
  await load()
  if (workspaceGeneration !== workspaceLoadGeneration || !shouldRestorePdf || modeGeneration !== modeSelectionGeneration) return
  const available = await ensurePdfData()
  if (workspaceGeneration !== workspaceLoadGeneration || modeGeneration !== modeSelectionGeneration) return
  if (available) {
    viewMode.value = "pdf"
    textModeWasFallback = false
  } else {
    viewMode.value = "text"
    textModeWasFallback = true
  }
}

watch([() => props.active, () => props.client, () => props.sessionKey], ([on, client, sessionKey], previous) => {
  const clientChanged = client !== previous?.[1]
  const previousSessionKey = String(previous?.[2] || "")
  const identityChanged = !previous
    || (sessionKey || previousSessionKey ? sessionKey !== previousSessionKey : clientChanged)
  if (clientChanged) {
    loadedOnce = false
    workspaceLoadGeneration += 1
    contentLoadGeneration += 1
    reviewOperationGeneration += 1
    omissionOperationGeneration += 1
    isSaving.value = false
    omissionSaving.value = false
    pdfDataLoadGeneration += 1
    pdfDataLoadPromise = null
    pdfLoading.value = false
    pdfPageLoadGeneration += 1
    pdfData.value = null
  }
  if (identityChanged) {
    internalCheckOperationGeneration += 1
    internalCheckSaving.value = false
    blocks.value = []
    requirements.value = []
    moduleOptions.value = [...MODULE_VOCAB]
    extractionStatus.value = null
    omissionStates.value = []
    setInternalChecks(null)
    selectedId.value = ""
    selectedBlockId.value = ""
    selectedRowKey.value = ""
    selectedCellKey.value = ""
    selectedClaimId.value = ""
    omissionNote.value = ""
    clearRequirementEditor()
    requirementDrafts.clear()
    omissionDrafts.clear()
    message.value = ""
    const urls = new Set(Object.values(pdfPageUrls.value))
    pdfPageUrls.value = {}
    for (const url of urls) revokePdfPageUrl(url)
  }
  if (on && (clientChanged || !loadedOnce || !requirements.value.length)) void loadWorkspace()
}, { immediate: true })

watch(() => props.refreshToken, (token, previous) => {
  if (token !== previous) scheduleIncrementalRefresh()
})

onUnmounted(() => {
  uninstallReviewShortcuts()
  if (incrementalRefreshTimer !== undefined) clearTimeout(incrementalRefreshTimer)
  if (focusRingTimer !== undefined) clearTimeout(focusRingTimer)
  pdfPageLoadsDisposed = true
  workspaceLoadGeneration += 1
  contentLoadGeneration += 1
  reviewOperationGeneration += 1
  omissionOperationGeneration += 1
  pdfDataLoadGeneration += 1
  pdfDataLoadPromise = null
  pdfLoading.value = false
  pdfPageLoadGeneration += 1
  const urls = new Set(Object.values(pdfPageUrls.value))
  pdfPageUrls.value = {}
  for (const url of urls) revokePdfPageUrl(url)
})
async function switchMode(mode: "text" | "pdf") {
  modeSelectionGeneration += 1
  textModeWasFallback = false
  viewMode.value = mode
  if (mode === "pdf") await ensurePdfData()
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
  for (const m of pdfData.value?.omission_markers || []) {
    if (!omissionIsClosed(omissionStateFor(m.block_id))) push(m.page, "omission", m.block_id, m.rect)
  }
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
// 这里只做渲染与路由——req→需求卡 / omission·context→块级卡（卡种由 selectedBlockKind 判定）;
// v12 表格行热区带 row_index → 行级卡（table-row 修饰类与块热区分辨选中态）
type PdfBlockZone = { block_id: string; page: number; rect: PdfZoneRect
                      kind: "req" | "covered" | "echo" | "omission" | "context";
                      row_index?: number; req_id?: string; req_ids?: string[] }
const pdfZonesByPage = computed(() => {
  const byPage = new Map<number, PdfBlockZone[]>()
  for (const raw of pdfData.value?.block_zones || []) {
    const z: PdfBlockZone = raw.kind === "omission" && omissionIsClosed(omissionStateFor(raw.block_id))
      ? { ...raw, kind: "context" }
      : raw
    const list = byPage.get(z.page) || []
    list.push(z)
    byPage.set(z.page, list)
  }
  return byPage
})
const pdfClaimZonesByPage = computed(() => {
  const byPage = new Map<number, ClaimAnnotationZone[]>()
  for (const zone of pdfData.value?.claim_zones || []) {
    const list = byPage.get(zone.page) || []
    list.push(zone)
    byPage.set(zone.page, list)
  }
  return byPage
})
const mappedClaimsByBlock = computed(() => {
  const byBlock = new Map<string, ClaimAnnotationRecord[]>()
  for (const claim of pdfData.value?.claim_records || []) {
    if (!claim.mapped) continue
    const rows = byBlock.get(claim.block_id) || []
    rows.push(claim)
    byBlock.set(claim.block_id, rows)
  }
  for (const rows of byBlock.values()) {
    rows.sort((a, b) => (a.start ?? 1e9) - (b.start ?? 1e9) || a.claim_id.localeCompare(b.claim_id))
  }
  return byBlock
})
const CLAIM_RESOLUTION_LABELS: Record<string, string> = {
  covered: "已覆盖", excluded: "已排除", uncertain: "待确认",
}
function claimFocusKind(claim: ClaimAnnotationRecord): string {
  return String(claim.focus?.kind || claim.source_kind || "")
}
function selectClaimCard(claimId: string) {
  const claim = (pdfData.value?.claim_records || []).find((row) => row.claim_id === claimId)
  if (!claim) return
  stashRequirementDraft()
  stashOmissionDraft()
  if (selectedClaimId.value === claimId) {
    selectedClaimId.value = ""
    return
  }
  selectedClaimId.value = claimId
  selectedId.value = ""
  selectedBlockId.value = ""
  selectedRowKey.value = ""
  selectedCellKey.value = ""
  clearRequirementEditor()
  omissionNote.value = ""
}
function claimsForDataRow(blockId: string, rowIndex: number): ClaimAnnotationRecord[] {
  return (mappedClaimsByBlock.value.get(blockId) || []).filter(
    (claim) => (claim.data_row_indexes || []).includes(rowIndex),
  )
}
// v15 cell 级：block+物理 R×C 全量 cell_context 索引——标题/表头/数据格全覆盖
//（v14 只索引 data_row_index 非空的格,标题/表头 cell claim 在 UI 不可达）
const cellContextByPhysical = computed(() => {
  const index = new Map<string, PdfCellContext>()
  for (const entry of Object.values(pdfData.value?.cell_context || {})) {
    if (!entry) continue
    index.set(`${entry.block_id}:R${entry.row_index}C${entry.column_index}`, entry)
  }
  return index
})
// 每个 block 的 covered 坐标集（合并覆盖格）：不渲染独立 td、不可点
const coveredCellIndex = computed(() => {
  const map = new Map<string, Set<string>>()
  for (const entry of Object.values(pdfData.value?.cell_context || {})) {
    if (!entry) continue
    let set = map.get(entry.block_id)
    if (!set) {
      set = new Set<string>()
      map.set(entry.block_id, set)
    }
    for (const pair of entry.covered_coordinates || []) {
      if (Array.isArray(pair) && pair.length === 2) set.add(`R${pair[0]}C${pair[1]}`)
    }
  }
  return map
})
// 数据区行号 → 物理行（优先 cell_context 实测对照,旧产物按 标题数+表头数 顺序回退）
const dataRowPhysicalIndex = computed(() => {
  const map = new Map<string, Map<number, number>>()
  for (const entry of Object.values(pdfData.value?.cell_context || {})) {
    if (!entry || entry.data_row_index == null) continue
    let rows = map.get(entry.block_id)
    if (!rows) {
      rows = new Map<number, number>()
      map.set(entry.block_id, rows)
    }
    rows.set(entry.data_row_index, entry.row_index)
  }
  return map
})
function headerPhysicalRow(b: DocumentBlock, hi: number): number {
  const indexes = b.header_row_indexes || []
  if (indexes.length > hi) return indexes[hi]
  return (b.title_row_indexes || []).length + hi + 1
}
function dataPhysicalRow(b: DocumentBlock, dataRowIndex: number): number {
  const measured = dataRowPhysicalIndex.value.get(b.block_id)?.get(dataRowIndex)
  if (measured) return measured
  const titles = (b.title_row_indexes || []).length
  const headers = (b.header_row_indexes || []).length || (b.header_rows || []).length
  return titles + headers + dataRowIndex
}
type GridCell = {
  text: string
  colIndex: number
  physicalRow: number
  entry: PdfCellContext | null
  colspan: number
  rowspan: number
}
// 一行渲染描述：covered 坐标不渲染（anchor 的 colspan/rowspan 已覆盖其面积），
// 其余格带 cell_context 条目（有则渲染 cell 按钮）与真实合并跨度
function gridRowCells(b: DocumentBlock, row: string[], physicalRow: number): GridCell[] {
  const covered = coveredCellIndex.value.get(b.block_id)
  const cells: GridCell[] = []
  row.forEach((text, ci) => {
    const colIndex = ci + 1
    if (covered?.has(`R${physicalRow}C${colIndex}`)) return
    const entry = cellContextByPhysical.value.get(`${b.block_id}:R${physicalRow}C${colIndex}`) || null
    cells.push({
      text,
      colIndex,
      physicalRow,
      entry,
      colspan: Math.max(1, entry?.column_span || 1),
      rowspan: Math.max(1, entry?.row_span || 1),
    })
  })
  return cells
}
// 标题行 cell（title role）：figcaption 旁渲染 cell 按钮,标题格 claim 不再不可达
function titleCellsFor(b: DocumentBlock): PdfCellContext[] {
  const rows = new Set(b.title_row_indexes || [])
  return Object.values(pdfData.value?.cell_context || {})
    .filter((entry) => entry && entry.block_id === b.block_id
      && (rows.size ? rows.has(entry.row_index) : entry.structural_role === "title"))
    .sort((x, y) => x.row_index - y.row_index || x.column_index - y.column_index)
}
// 整表网格模型缓存：blocks/cell_context 变化时整表重算一次,模板不再逐格重复扫描
type TableGrid = { headerRows: GridCell[][]; bodyRows: GridCell[][] }
const tableGrids = computed(() => {
  const grids = new Map<string, TableGrid>()
  for (const b of blocks.value) {
    if (b.type !== "table") continue
    const headerRows = (b.header_rows || []).map((hr, hi) =>
      gridRowCells(b, padRow(b, hr), headerPhysicalRow(b, hi)))
    const bodyRows = (b.data_rows || []).map((row, ri) =>
      gridRowCells(b, padRow(b, row), dataPhysicalRow(b, ri + 1)))
    grids.set(b.block_id, { headerRows, bodyRows })
  }
  return grids
})
function tableGridFor(b: DocumentBlock): TableGrid {
  return tableGrids.value.get(b.block_id) || { headerRows: [], bodyRows: [] }
}
function claimsForCell(cellId: string): ClaimAnnotationRecord[] {
  return (pdfData.value?.claim_records || []).filter((claim) => claim.table_cell_id === cellId)
}
function selectCellCard(cellId: string) {
  stashRequirementDraft()
  stashOmissionDraft()
  if (selectedCellKey.value === cellId) {
    selectedCellKey.value = ""
    return
  }
  selectedCellKey.value = cellId
  selectedRowKey.value = ""
  selectedClaimId.value = ""
  selectedId.value = ""
  selectedBlockId.value = ""
  clearRequirementEditor()
  omissionNote.value = ""
}
const selectedCell = computed(() => {
  const cellId = selectedCellKey.value
  if (!cellId) return null
  const entry = Object.values(pdfData.value?.cell_context || {}).find((row) => row.cell_id === cellId)
  if (!entry) return null
  const block = blocks.value.find((b) => b.block_id === entry.block_id) || null
  return { entry, block, claims: claimsForCell(cellId) }
})
// 表格行选中态辅助（键声明见 selectedBlockId 旁——immediate watch 时序要求）
function rowZoneKey(z: PdfBlockZone): string {
  return z.row_index != null ? `${z.block_id}#R${z.row_index}` : z.block_id
}
function selectRowCard(z: PdfBlockZone) {
  stashRequirementDraft()
  stashOmissionDraft()
  const key = rowZoneKey(z)
  if (selectedRowKey.value === key) {  // 再点一下 → 取消选中
    selectedRowKey.value = ""
    return
  }
  selectedRowKey.value = key
  selectedCellKey.value = ""
  selectedClaimId.value = ""
  selectedId.value = ""
  selectedBlockId.value = ""
  clearRequirementEditor()
  omissionNote.value = ""
}
// 行级卡片数据：优先后端 row_context（行原文/翻译同源实现）；旧后端缺省时用块 data_rows 兜底渲染
const selectedRow = computed(() => {
  const key = selectedRowKey.value
  if (!key) return null
  const splitAt = key.lastIndexOf("#R")
  const blockId = key.slice(0, splitAt)
  const rowIndex = Number(key.slice(splitAt + 2)) || 0
  const block = blocks.value.find((b) => b.block_id === blockId)
  if (!block || rowIndex < 1) return null
  const zone = (pdfData.value?.block_zones || []).find((z) => rowZoneKey(z) === key)
  const record = pdfData.value?.row_context?.[key] || null
  const row = (block.data_rows || [])[rowIndex - 1]
  const width = Math.max((block.header_rows || [])[0]?.length || 0, (row || []).length)
  const fallbackText = row ? (row as string[]).slice(0, width).join(" | ") : ""
  const text = record?.text || fallbackText
  if (!text.trim()) return null
  const kind = (record?.kind || zone?.kind || "context") as PdfBlockZone["kind"]
  const reqIds = (zone?.req_ids || record?.covered_req_ids || record?.req_ids || []) as string[]
  return {
    key, block, rowIndex, text, kind,
    page: record?.page || zone?.page || 0,
    translation: record?.translation || "",
    translationNote: record?.translation_note || "",
    reqIds,
    section: (block.section_path || []).filter(Boolean).pop() || block.table_title || "",
  }
})
function pdfZoneClick(z: PdfBlockZone) {
  if (z.kind === "req" && z.req_id) {
    if ((z.req_ids || []).length > 1) {
      if (z.row_index != null) { selectRowCard(z); return }
      const block = blocks.value.find((b) => b.block_id === z.block_id)
      if (block) selectBlockCard(block)
      return
    }
    const req = requirements.value.find((r) => r.ai_req_id === z.req_id)
    if (req) select(req)
    return
  }
  if (z.row_index != null) { selectRowCard(z); return }
  const block = blocks.value.find((b) => b.block_id === z.block_id)
  if (block) selectBlockCard(block)
}
function pdfZoneSelected(z: PdfBlockZone): boolean {
  if (z.row_index != null) {
    if (selectedRowKey.value) return selectedRowKey.value === rowZoneKey(z)
    return z.kind === "req" && !!z.req_id && z.req_id === selectedId.value
  }
  if (z.kind === "req") {
    return (!!z.req_id && z.req_id === selectedId.value) ||
      ((z.req_ids || []).length > 1 && z.block_id === selectedBlockId.value)
  }
  if (z.kind === "echo" && selectedId.value) return (z.req_ids || []).includes(selectedId.value)
  return z.block_id === selectedBlockId.value
}
// 选中需求时把原句跨越的块全部框出（test8 实证：只框锚点块，原句后半段出框）——
// quote_block_ids 是后端原句确定性匹配全集；框 = 轻量高亮（quote-sel），锚点仍是主框。
// 表格行热区不参与 quote-sel：引句块即整表,逐行刷虚线框是纯噪声（行选中态由 sel 承担）
const selectedQuoteBlockIds = computed(
  () => new Set((selectedReq.value?.quote_block_ids || []) as string[]),
)
function pdfZoneQuoteHighlighted(z: PdfBlockZone): boolean {
  if (z.row_index != null) return false
  return !!selectedId.value && selectedQuoteBlockIds.value.has(z.block_id)
}
function pdfZoneTitle(z: PdfBlockZone): string {
  if (z.row_index != null) {
    if (z.kind === "req") return "查看需求批注"
    if (z.kind === "covered") return "该行已纳入需求解析·点击查看关联需求"
    return "查看该行翻译与解析"
  }
  if (z.kind === "req") return (z.req_ids || []).length > 1 ? "查看该段的全部需求解析" : "查看需求批注"
  if (z.kind === "covered") return "查看该段关联的需求解析"
  if (z.kind === "echo") return "重复段·点击查看汇总需求"
  return z.kind === "omission" ? "疑似需求未覆盖·点击查看" : "查看该段翻译与解析"
}
function pdfZoneBlock(z: PdfBlockZone): DocumentBlock | undefined {
  return blocks.value.find((block) => block.block_id === z.block_id)
}
// 行级卡的关联需求（covered/多需求行）：由行热区 req_ids 路由,与块级 echo-jump 同交互
const selectedRowRelatedReqs = computed(() => {
  const row = selectedRow.value
  if (!row) return []
  const ids = new Set(row.reqIds)
  const ordered = requirements.value.filter((r) => ids.has(r.ai_req_id))
  return [...ordered].sort((a, b) =>
    (reqNumbers.value.get(a.ai_req_id) ?? 1e9) - (reqNumbers.value.get(b.ai_req_id) ?? 1e9))
})

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
// 只高亮选中的片段（原句实际跨越的块集），不把整个章节跨度刷蓝
const evidenceBlocks = computed(() => {
  // 证据块（蓝填充）= 原句实际跨越的块集（quote_block_ids，多段引句不再丢后半段——
  // test5 实证：引句跨 097+098，只亮首块与原句左右不一致）；其余跨度块仅左侧细条
  const r = selectedReq.value
  const anchor = r?.anchor_block_id || (r?.source_block_ids || [])[0]
  const quoteIds = (r?.quote_block_ids || []).filter(Boolean) as string[]
  return new Set(quoteIds.length ? quoteIds : (anchor ? [anchor as string] : []))
})
const selectedSpan = computed(() => {
  // 整个被分析的跨度都亮淡底（source_block_ids；section_fallback 行只认原句匹配块——
  // 跨小节回退跨度会把无关清单段刷进"分析范围"，test5 "- DAY1" 实证），引句黄标只在
  // 锚点段内——只黄一句会让"分析了一整段"的需求看起来像没选中（真实反馈）
  const r = selectedReq.value
  const anchor = r?.anchor_block_id || (r?.source_block_ids || [])[0]
  const spanIds = (r?.source_mapping === "section_fallback"
    ? (r?.quote_block_ids || [])
    : (r?.source_block_ids || []))
  const ids = [...spanIds, ...(r?.echo_block_ids || []), anchor]
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
const orderedSelectedRelatedReqs = computed(() => orderedEchoReqs(selectedRelatedReqs.value))
function echoReqsForBlock(blockId: string): AiRequirement[] {
  return orderedEchoReqs(echoByBlock.value.get(blockId) || [])
}
function echoLabel(reqs: AiRequirement[]): string {
  const numbers = orderedEchoReqs(reqs).map((req) => reqNumber(req)).filter((value) => value !== "--")
  return numbers.length ? `重复·见${numbers.join("/")}` : "重复段"
}
function pdfLinkedLabel(zone: PdfBlockZone): string {
  const ids = new Set(zone.req_ids || [])
  const reqs = requirements.value.filter((req) => ids.has(req.ai_req_id))
  if (zone.kind === "covered") {
    const numbers = orderedEchoReqs(reqs).map((req) => reqNumber(req)).filter((value) => value !== "--")
    return numbers.length ? `关联·见${numbers.join("/")}` : "分析范围"
  }
  return echoLabel(reqs)
}
function jumpToRelatedReq(req: AiRequirement) {
  activateReq(req)   // 直接选中(不走 select 的再点取消语义)
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
  () => blocks.value.filter((b) => isOmission(b)).length,
)

const stats = computed(() => ({
  reqs: requirements.value.length,
  anchored: requirements.value.filter((r) => (r.source_block_ids || []).length).length,
  omissions: omissionCount.value,
}))
const internalCheckGroups = computed(() => internalChecks.value?.groups || [])
const selectedInternalChecks = computed(() =>
  (internalChecks.value?.entries || []).filter((entry) => entry.signal === internalCheckSignal.value))
const INTERNAL_CHECK_LABELS: Record<string, string> = {
  "suspicion:引用": "原文引用核对",
  "suspicion:self_check_added": "自检补抽核对",
  "consistency:duplicate": "跨章重复核对",
  "consistency:compliance_uncovered": "合规漏项核对",
  "parse_audit:noise_char_ratio": "解析噪声核对",
  "parse_audit:body_ratio": "正文区域核对",
}
function internalCheckLabel(signal: string): string {
  return INTERNAL_CHECK_LABELS[signal] || signal.replace(/^.*:/, "") || "未分类"
}
async function acknowledgeInternalCheckGroup() {
  const client = props.client
  const selected = selectedInternalChecks.value
  if (!client?.applyClarificationCheckBatch || !selected.length || internalCheckSaving.value) return
  const generation = ++internalCheckOperationGeneration
  const signal = internalCheckSignal.value
  internalCheckSaving.value = true
  try {
    const result = await client.applyClarificationCheckBatch({
      checks: selected.map((entry) => ({
        clarificationId: entry.clarification_id,
        evidenceFingerprint: entry.evidence_fingerprint,
      })),
      action: "verified_ok",
      actor: "reviewer",
      note: `批量确认：${internalCheckLabel(signal)}`,
    })
    if (client !== props.client || generation !== internalCheckOperationGeneration) return
    const refreshed = await client.loadClarificationInternalChecks?.() || null
    if (client !== props.client || generation !== internalCheckOperationGeneration) return
    setInternalChecks(refreshed)
    const rejected = [
      ["证据过期", result.stale.length],
      ["已不存在", result.missing.length],
      ["不适用", result.ineligible.length],
      ["重复提交", result.duplicates.length],
    ].filter(([, count]) => Number(count) > 0)
    message.value = `已确认 ${result.applied} 项${rejected.length
      ? `；未写入：${rejected.map(([label, count]) => `${label} ${count} 项`).join("、")}`
      : ""}`
  } catch (error) {
    if (client === props.client && generation === internalCheckOperationGeneration) {
      if (isNeedsReconfirmationError(error)) {
        const refreshed = await client.loadClarificationInternalChecks?.().catch(() => null) || null
        if (client === props.client && generation === internalCheckOperationGeneration) {
          setInternalChecks(refreshed)
          message.value = "内部核对证据已变化，已刷新，请重新确认"
        }
      } else {
        message.value = error instanceof Error ? error.message : "批量确认失败"
      }
    }
  } finally {
    if (client === props.client && generation === internalCheckOperationGeneration) {
      internalCheckSaving.value = false
    }
  }
}

function isHeading(b: DocumentBlock): boolean {
  return b.type === "heading" || (b.section_path?.length ? b.text === b.section_path[b.section_path.length - 1] : false)
}
const omissionStateByBlock = computed(() => new Map(
  omissionStates.value.map((state) => [state.block_id, state]),
))
function omissionStateFor(blockId: string): OmissionActionState | undefined {
  return omissionStateByBlock.value.get(blockId)
}
function omissionIsClosed(state: OmissionActionState | undefined): boolean {
  return state?.status === "non_requirement" || state?.status === "resolved"
}
function omissionStatusLabel(blockId: string): string {
  const status = omissionStateFor(blockId)?.status
  return status ? OMISSION_STATUS_LABELS[status] : ""
}
function isOmission(b: DocumentBlock): boolean {
  return isCoverageCandidate(b)
    && !coveredBlocks.value.has(b.block_id)
    && !omissionIsClosed(omissionStateFor(b.block_id))
}
function moduleOf(r: AiRequirement): string {
  return String(r.module_effective || originalModuleOf(r))
}
function originalModuleOf(r: AiRequirement): string {
  return String(r.module || (r.labels || [])[0] || "未分模块")
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

function activateReq(req: AiRequirement) {
  stashRequirementDraft()
  stashOmissionDraft()
  selectedBlockId.value = ""
  selectedRowKey.value = ""
  selectedCellKey.value = ""
  selectedClaimId.value = ""
  omissionNote.value = ""
  selectedId.value = req.ai_req_id
  const draft = requirementDrafts.get(req.ai_req_id)
  comment.value = draft?.comment ?? String(req.review_state?.reason || "")
  moduleEdit.value = draft?.module ?? moduleOf(req)
  ownershipEdit.value = draft?.ownership ?? ownershipOf(req)
}

function select(req: AiRequirement) {
  if (selectedId.value === req.ai_req_id) {  // 再点一下 → 取消选中
    stashRequirementDraft()
    selectedId.value = ""
    clearRequirementEditor()
    return
  }
  activateReq(req)
}

// 顺序过审导航：按页边批注号（文档顺序）逐条前进/后退，首尾循环
const orderedReqs = computed(() => [...requirements.value].sort((a, b) =>
  (reqNumbers.value.get(a.ai_req_id) ?? 1e9) - (reqNumbers.value.get(b.ai_req_id) ?? 1e9)))
const selectedReqIndex = computed(() => orderedReqs.value.findIndex((r) => r.ai_req_id === selectedId.value))
async function stepReq(delta: number) {
  const list = orderedReqs.value
  if (!list.length) return
  const current = selectedReqIndex.value
  const nextIndex = current < 0 ? (delta > 0 ? 0 : list.length - 1) : (current + delta + list.length) % list.length
  const req = list[nextIndex]
  activateReq(req)
  await nextTick()
  const anchor = String(req.anchor_block_id || (req.source_block_ids || [])[0] || "")
  if (!anchor) return
  const el = rootEl.value?.querySelector(`[data-block-id="${anchor}"]`)
    || rootEl.value?.querySelector(`[data-testid="pdf-zone-${anchor}"]`)
  el?.scrollIntoView?.({ behavior: "smooth", block: "center" })
}

const rootEl = ref<HTMLElement | null>(null)

// 疑似遗漏是审查的核心风险入口：点击统计数字循环定位下一处未覆盖段（文本/影印两模式通用）
const omissionBlocks = computed(() => blocks.value.filter((b) => isOmission(b)))
const omissionJumpIndex = ref(-1)
async function jumpToNextOmission() {
  const list = omissionBlocks.value
  if (!list.length) return
  omissionJumpIndex.value = (omissionJumpIndex.value + 1) % list.length
  const block = list[omissionJumpIndex.value]
  selectBlockCard(block)
  await nextTick()
  const el = rootEl.value?.querySelector(`[data-block-id="${block.block_id}"]`)
    || rootEl.value?.querySelector(`[data-testid="pdf-zone-${block.block_id}"]`)
  el?.scrollIntoView({ behavior: "smooth", block: "center" })
  message.value = `疑似遗漏 ${omissionJumpIndex.value + 1}/${list.length}`
}

// F4：来源块定位（functional 评审 emit focus-block → App 传入 focusBlockId）。
// 选中 + 滚动 + 瞬时高亮环；blocks 未就绪时挂起，load() 完成后兑现。不改裁决逻辑。
async function applyFocusBlock(blockId: string) {
  const target = String(blockId || "").trim()
  if (!target) return
  const block = blocks.value.find((b) => b.block_id === target)
  if (!block) {
    // blocks 尚未加载——挂起等 load() 兑现
    pendingFocusBlockId = target
    return
  }
  pendingFocusBlockId = ""
  selectBlockCard(block)
  await nextTick()
  const el = rootEl.value?.querySelector(`[data-block-id="${target}"]`)
    || rootEl.value?.querySelector(`[data-testid="pdf-zone-${target}"]`)
  el?.scrollIntoView({ behavior: "smooth", block: "center" })
  // 瞬时高亮环（与选中态区分：选中是用户点击的持续态，focus 环是外部跳转的短暂强调）
  focusedBlockId.value = target
  if (focusRingTimer !== undefined) clearTimeout(focusRingTimer)
  focusRingTimer = setTimeout(() => { focusedBlockId.value = "" }, 2600)
}

watch(() => props.focusBlockId, (id) => {
  if (id) void applyFocusBlock(id)
}, { immediate: true })

const OMISSION_STATUS_LABELS: Record<OmissionActionStatus, string> = {
  non_requirement: "已判定非需求",
  needs_extraction: "等待补抽",
  issue_confirmed: "已确认遗漏",
  resolved: "已补抽",
}

function replaceOmissionState(state: OmissionActionState) {
  const next = omissionStates.value.filter((item) => item.block_id !== state.block_id)
  next.push(state)
  omissionStates.value = next
}

async function refreshReviewData(client: DocClient, includeDocument = false): Promise<boolean> {
  const generation = ++contentLoadGeneration
  const workspaceGeneration = workspaceLoadGeneration
  const [doc, reqs, partial, omissionPayload, checksPayload] = await Promise.all([
    includeDocument ? client.loadDocument() : Promise.resolve(null),
    client.loadAiRequirements(),
    client.loadAiExtractionStatus?.().catch(() => null) ?? Promise.resolve(null),
    client.loadOmissionActions?.().catch(() => null) ?? Promise.resolve(null),
    client.loadClarificationInternalChecks?.().catch(() => null) ?? Promise.resolve(null),
  ])
  if (client !== props.client || generation !== contentLoadGeneration
      || workspaceGeneration !== workspaceLoadGeneration) return false
  if (doc) {
    blocks.value = doc.blocks || []
    moduleOptions.value = [...new Set([...MODULE_VOCAB, ...(doc.module_vocabulary || [])])]
  }
  extractionStatus.value = partial
  replaceRequirements(partial?.run_id && !partial.complete ? partial.rows || [] : reqs || [])
  if (omissionPayload) setOmissionStates(omissionPayload.states)
  if (checksPayload) setInternalChecks(checksPayload)
  await refreshPdfMetadata(client, workspaceGeneration)
  return client === props.client && generation === contentLoadGeneration
    && workspaceGeneration === workspaceLoadGeneration
}

function omissionRequestIsCurrent(client: DocClient, generation: number) {
  return client === props.client && generation === omissionOperationGeneration
}

async function applyOmissionDisposition(status: "non_requirement" | "issue_confirmed") {
  const block = selectedBlock.value
  const client = props.client
  if (!block || !client?.applyOmissionAction || omissionSaving.value) return
  const generation = ++omissionOperationGeneration
  const blockId = block.block_id
  const note = omissionNote.value
  stashOmissionDraft(blockId)
  omissionSaving.value = true
  try {
    const previous = omissionStateFor(block.block_id)
    const omissionId = previous?.omission_id || block.omission_id
    const sourceFingerprint = block.omission_source_fingerprint
    if (!omissionId || !sourceFingerprint) {
      message.value = "遗漏身份已变化，请刷新后重试"
      return
    }
    const state = await client.applyOmissionAction({
      omissionId,
      blockId,
      sourceFingerprint,
      status,
      reason: note,
      actor: "reviewer",
    })
    if (!omissionRequestIsCurrent(client, generation)
        || state.block_id !== blockId || state.omission_id !== omissionId) return
    replaceOmissionState(state)
    omissionDrafts.delete(blockId)
    if (selectedBlockId.value === blockId) omissionNote.value = ""
    message.value = status === "non_requirement"
      ? "已记为非需求，不再计入疑似遗漏"
      : "已确认遗漏，可直接执行定点补抽"
  } catch (error) {
    if (!omissionRequestIsCurrent(client, generation)) return
    if (isNeedsReconfirmationError(error)) {
      await refreshReviewData(client, true).catch(() => false)
      if (omissionRequestIsCurrent(client, generation)) {
        message.value = "遗漏来源已变化，已刷新当前证据，请核对后重新处置"
      }
    } else {
      message.value = error instanceof Error ? error.message : "遗漏处置写入失败"
    }
  } finally {
    if (omissionRequestIsCurrent(client, generation)) omissionSaving.value = false
  }
}

async function reextractSelectedOmission() {
  const block = selectedBlock.value
  const client = props.client
  if (!block || !client?.reextractOmission || omissionSaving.value) return
  const generation = ++omissionOperationGeneration
  const blockId = block.block_id
  const note = omissionNote.value
  stashOmissionDraft(blockId)
  omissionSaving.value = true
  try {
    const previous = omissionStateFor(block.block_id)
    const omissionId = previous?.omission_id || block.omission_id
    const sourceFingerprint = block.omission_source_fingerprint
    if (!omissionId || !sourceFingerprint) {
      message.value = "遗漏身份已变化，请刷新后重试"
      return
    }
    const payload = await client.reextractOmission({
      omissionId,
      blockId,
      sourceFingerprint,
      focusLines: [(block.text || "").trim()].filter(Boolean),
      actor: "reviewer",
      reason: note,
    })
    if (!omissionRequestIsCurrent(client, generation)
        || payload.omission.block_id !== blockId || payload.omission.omission_id !== omissionId) return
    replaceOmissionState(payload.omission)
    await refreshReviewData(client)
    if (!omissionRequestIsCurrent(client, generation)) return
    omissionDrafts.delete(blockId)
    if (selectedBlockId.value === blockId) omissionNote.value = ""
    message.value = payload.requirements > 0
      ? `定点补抽完成：新增或更新 ${payload.requirements} 条需求`
      : "定点补抽完成，未发现可通过护栏的新需求"
  } catch (error) {
    if (!omissionRequestIsCurrent(client, generation)) return
    if (isNeedsReconfirmationError(error)) {
      await refreshReviewData(client, true).catch(() => false)
      if (omissionRequestIsCurrent(client, generation)) {
        message.value = "遗漏来源已变化，已刷新当前证据，请核对后重新补抽"
      }
    } else {
      message.value = error instanceof Error ? error.message : "定点补抽失败"
    }
  } finally {
    if (omissionRequestIsCurrent(client, generation)) omissionSaving.value = false
  }
}

// 点解析（WP-B）：批注视图单行/单块定向解析。产出 draft + 澄清待确认（先人工确认再转正）；
// 失败如实 toast 错误原因（含无 LLM 配置的 503），不假装可用。
async function spotExtractBlock(b: DocumentBlock, rowIndex?: number, cellId?: string) {
  const client = props.client
  if (!client?.spotExtract || spotExtracting.value) return
  const key = cellId ? `${b.block_id}:${cellId}` : `${b.block_id}:${rowIndex ?? ""}`
  spotExtracting.value = key
  try {
    const payload = await client.spotExtract({ blockId: b.block_id, rowIndex, cellId, actor: "reviewer" })
    if (spotExtracting.value !== key) return
    if (payload.drafts > 0) {
      message.value = `已生成 ${payload.drafts} 条 draft 需求，进澄清待确认`
      await refreshReviewData(client).catch(() => false)
    } else {
      message.value = "该段未发现新需求（可能已被现有需求覆盖）"
    }
  } catch (error) {
    if (spotExtracting.value === key) {
      message.value = error instanceof Error ? error.message : "点解析失败"
    }
  } finally {
    if (spotExtracting.value === key) spotExtracting.value = ""
  }
}

// 选中需求时，在锚段内的块里高亮 source_quote 原句；选中未覆盖/背景段时整段=引用本体 → 全黄。
function segments(b: DocumentBlock): Array<{ text: string; mark: boolean; claim?: ClaimAnnotationRecord }> {
  const text = b.text || ""
  const claims = (mappedClaimsByBlock.value.get(b.block_id) || []).filter((claim) => {
    const kind = claimFocusKind(claim)
    return (kind === "text_span" || kind === "list_item")
      && Number.isInteger(claim.start) && Number.isInteger(claim.end)
      && (claim.start as number) >= 0 && (claim.end as number) > (claim.start as number)
      && (claim.end as number) <= text.length
      && text.slice(claim.start, claim.end) === (claim.rendered_text || claim.text)
  })
  const quote = selectedReq.value?.source_quote || ""
  const quoteStart = quote && selectedSpan.value.has(b.block_id) ? text.indexOf(quote) : -1
  const quoteEnd = quoteStart >= 0 ? quoteStart + quote.length : -1
  const boundaries = new Set<number>([0, text.length])
  for (const claim of claims) {
    boundaries.add(claim.start as number)
    boundaries.add(claim.end as number)
  }
  if (quoteStart >= 0) {
    boundaries.add(quoteStart)
    boundaries.add(quoteEnd)
  }
  const points = [...boundaries].sort((a, b) => a - b)
  return points.slice(0, -1).map((start, index) => {
    const end = points[index + 1]
    const claim = claims.find((row) => (row.start as number) <= start && (row.end as number) >= end)
    return {
      text: text.slice(start, end),
      mark: b.block_id === selectedBlockId.value || (quoteStart >= 0 && start >= quoteStart && end <= quoteEnd),
      claim,
    }
  }).filter((segment) => segment.text.length)
}

async function decide(status: "accepted" | "rejected" | "needs_discussion", advance = false) {
  const req = selectedReq.value
  const client = props.client
  if (!req || !client || isSaving.value) return
  const moduleName = moduleEdit.value.trim()
  if (!moduleName) {
    message.value = "模块不能为空"
    return
  }
  if (Array.from(moduleName).length > 20) {
    message.value = "模块最多 20 字"
    return
  }
  const generation = ++reviewOperationGeneration
  stashRequirementDraft(req.ai_req_id)
  isSaving.value = true
  try {
    const state = await client.applyAiReviewAction({
      aiReqId: req.ai_req_id, status,
      sourceFingerprint: req.source_fingerprint,
      reviewSubjectFingerprint: req.review_subject_fingerprint,
      expectedTargetFingerprint: req.target_fingerprint,
      expectedTargetPublicationRevision: req.target_publication_revision,
      expectedTargetAuthorityWriteRevision: req.target_authority_write_revision,
      // 与规则初判比较：重复裁决时保留既有覆盖；选回初判值才发空串清除。
      moduleOverride: moduleName !== originalModuleOf(req) ? moduleName : undefined,
      clearModuleOverride: moduleName === originalModuleOf(req) && Boolean(req.review_state?.module_override),
      // 选回规则初判值 → 发空串清除覆盖，归属回落规则判定
      ownershipOverride: ownershipEdit.value !== (req.ownership || "") ? ownershipEdit.value : "",
      reason: comment.value, actor: "reviewer",
    })
    if (client !== props.client || generation !== reviewOperationGeneration
        || state.ai_req_id !== req.ai_req_id) return
    req.review_state = state
    req.target_authority_write_revision = state.target_authority_write_revision
      || req.target_authority_write_revision
    req.target_publication_revision = state.target_publication_revision
      || req.target_publication_revision
    req.needs_reconfirmation = false
    req.status = state.status
    req.module_effective = state.module_override || originalModuleOf(req)
    req.ownership_effective = state.ownership_override || req.ownership
    moduleEdit.value = moduleOf(req)
    ownershipEdit.value = ownershipOf(req)
    message.value = `已${STATUS_LABELS[status] || status}：${req.title || req.ai_req_id}`
    if (advance && selectedId.value === req.ai_req_id) await stepReq(1)
  } catch (error) {
    if (client !== props.client || generation !== reviewOperationGeneration) return
    if (isNeedsReconfirmationError(error)) {
      await refreshReviewData(client).catch(() => false)
      if (client === props.client && generation === reviewOperationGeneration) {
        message.value = "需求证据或解析内容已变化，已刷新，请核对后重新裁决"
      }
    } else {
      message.value = error instanceof Error ? error.message : "裁决写入失败"
    }
  } finally {
    if (client === props.client && generation === reviewOperationGeneration) isSaving.value = false
  }
}

let incrementalRefreshTimer: ReturnType<typeof setTimeout> | undefined
let incrementalRefreshRunning = false
let incrementalRefreshQueued = false

function partialRowsIdentity(rows: AiRequirement[]) {
  return rows.map((row) => [
    row.ai_req_id,
    row.extraction_fingerprint || "",
    row.source_fingerprint || "",
    row.review_subject_fingerprint || "",
    row.target_publication_revision || "",
    row.target_authority_write_revision || "",
  ].join(":")).join("|")
}

async function refreshIncremental() {
  const client = props.client
  if (!client?.loadAiExtractionStatus || incrementalRefreshRunning) {
    if (incrementalRefreshRunning) incrementalRefreshQueued = true
    return
  }
  const generation = ++contentLoadGeneration
  const workspaceGeneration = workspaceLoadGeneration
  incrementalRefreshRunning = true
  try {
    const [partial, omissionPayload] = await Promise.all([
      client.loadAiExtractionStatus(),
      client.loadOmissionActions?.().catch(() => null) ?? Promise.resolve(null),
    ])
    if (client !== props.client || generation !== contentLoadGeneration
        || workspaceGeneration !== workspaceLoadGeneration) return
    const previous = extractionStatus.value
    extractionStatus.value = partial
    setOmissionStates(omissionPayload?.states ?? omissionStates.value)
    const changed = partial.run_id !== previous?.run_id
      || partial.completed !== previous?.completed
      || partial.complete !== previous?.complete
      || partial.failed !== previous?.failed
      || partialRowsIdentity(partial.rows) !== partialRowsIdentity(previous?.rows || [])
    if (changed && partial.run_id) {
      const rows = partial.complete ? await client.loadAiRequirements() : partial.rows
      if (client !== props.client || generation !== contentLoadGeneration
          || workspaceGeneration !== workspaceLoadGeneration) return
      replaceRequirements(rows || [])
      await refreshPdfMetadata(client, workspaceGeneration)
    }
  } catch (error) {
    if (client === props.client && generation === contentLoadGeneration
        && workspaceGeneration === workspaceLoadGeneration) {
      message.value = error instanceof Error ? error.message : "增量结果刷新失败"
    }
  } finally {
    incrementalRefreshRunning = false
    if (incrementalRefreshQueued) {
      incrementalRefreshQueued = false
      scheduleIncrementalRefresh()
    }
  }
}

function scheduleIncrementalRefresh() {
  if (!props.active || !props.client?.loadAiExtractionStatus) return
  if (incrementalRefreshTimer !== undefined) clearTimeout(incrementalRefreshTimer)
  incrementalRefreshTimer = setTimeout(() => {
    incrementalRefreshTimer = undefined
    void refreshIncremental()
  }, 180)
}

// 评审键盘流（j/k 导航、a/r/d 裁决）：与 FunctionalReview 共用 useReviewShortcuts，
// 守卫与键位映射单点维护（此前为本组件内联 handleReviewShortcut）。
const { install: installReviewShortcuts, uninstall: uninstallReviewShortcuts } = useReviewShortcuts({
  isActive: () => props.active,
  hasItems: () => orderedReqs.value.length > 0,
  step: (delta) => { void stepReq(delta) },
  decisions: {
    hasSelection: () => Boolean(selectedReq.value) && Boolean(props.client),
    isBusy: () => isSaving.value,
    decide: (status) => { void decide(status, true) },
  },
})

async function loadTextModeSwitch() {
  // D7 预备：后端 /health 携带 text_mode 开关，缺省保留文本模式
  if (!props.client?.loadHealth) return
  try {
    const health = await props.client.loadHealth()
    if (typeof health.text_mode === "boolean") {
      textModeEnabled.value = health.text_mode
    }
  } catch {
    // /health 失败不影响核心功能，默认保留文本模式
  }
}

onMounted(() => {
  installReviewShortcuts()
  void loadTextModeSwitch()
})
</script>

<template>
  <section ref="rootEl" class="doc-review" data-testid="doc-review">
    <header class="doc-toolbar">
      <div class="doc-stats">
        <span>需求 <strong data-testid="doc-stat-reqs">{{ stats.reqs }}</strong></span>
        <span>已挂载 <strong>{{ stats.anchored }}</strong></span>
        <span v-if="extractionStatus?.run_id && extractionStatus.failed"
              class="partial-status failed" data-testid="partial-status">
          抽取不完整 <strong>{{ extractionStatus.completed }}/{{ extractionStatus.total }}</strong>
        </span>
        <span v-else-if="extractionStatus?.run_id && !extractionStatus.complete"
              class="partial-status" data-testid="partial-status">
          抽取中 <strong>{{ extractionStatus.completed }}/{{ extractionStatus.total }}</strong>
        </span>
        <button type="button" class="omission-stat omission-jump" :class="{ warn: stats.omissions > 0 }"
                :disabled="!stats.omissions" data-testid="omission-jump"
                title="疑似需求但未被任何抽取覆盖——点击循环定位下一处"
                @click="jumpToNextOmission">
          疑似遗漏 <strong data-testid="doc-stat-omissions">{{ stats.omissions }}</strong>
        </button>
      </div>
      <div class="doc-toolbar-actions">
        <div v-if="internalCheckGroups.length && props.client?.applyClarificationCheckBatch"
             class="internal-check-batch" data-testid="internal-check-batch">
          <select v-model="internalCheckSignal" aria-label="内部核对类别">
            <option v-for="group in internalCheckGroups" :key="group.signal" :value="group.signal">
              {{ internalCheckLabel(group.signal) }} · {{ group.count }}
            </option>
          </select>
          <button type="button" :disabled="internalCheckSaving || !selectedInternalChecks.length"
                  data-testid="internal-check-acknowledge"
                  :title="`确认当前类别 ${selectedInternalChecks.length} 项证据均已逐项核对无误`"
                  @click="acknowledgeInternalCheckGroup">
            <Check :size="14" aria-hidden="true" />{{ internalCheckSaving ? "写入中" : `确认 ${selectedInternalChecks.length} 项` }}
          </button>
        </div>
        <div class="mode-toggle">
          <button v-if="textModeEnabled" type="button" :class="{ active: viewMode === 'text' }" data-testid="mode-text"
                  @click="switchMode('text')"><Rows3 :size="14" aria-hidden="true" />解析文本</button>
          <button type="button" :class="{ active: viewMode === 'pdf' }" data-testid="mode-pdf"
                  @click="switchMode('pdf')"><Image :size="14" aria-hidden="true" />原版核对</button>
        </div>
        <button class="button" type="button" data-testid="doc-reload" :disabled="loading" @click="reloadWorkspace">
          <RefreshCw :class="{ spin: loading }" :size="14" aria-hidden="true" />{{ loading ? "加载中" : "刷新" }}
        </button>
      </div>
    </header>

    <div v-if="message" class="doc-message" data-testid="doc-message">{{ message }}</div>

    <div class="doc-body">
      <article v-if="viewMode === 'pdf'" class="doc-paper pdf-paper" data-testid="pdf-paper">
        <div v-if="loading || pdfLoading" class="doc-detail-empty" data-testid="pdf-loading">影印数据加载中…</div>
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
                      class="pdf-block-zone" :class="['zone-' + z.kind, { sel: pdfZoneSelected(z), 'quote-sel': pdfZoneQuoteHighlighted(z), 'table-row': z.row_index != null }]"
                      :style="{ left: z.rect.left + '%', top: z.rect.top + '%',
                                width: z.rect.width + '%', height: z.rect.height + '%' }"
                      :data-testid="z.row_index != null ? `pdf-zone-${z.block_id}-r${z.row_index}` : `pdf-zone-${z.block_id}`"
                      :title="pdfZoneTitle(z)"
                      :aria-label="pdfZoneTitle(z)"
                      :aria-pressed="pdfZoneSelected(z)"
                      @click.stop="pdfZoneClick(z)">
                <span v-if="z.kind === 'echo' || z.kind === 'covered'" class="pdf-echo-tag">{{ pdfLinkedLabel(z) }}</span>
                <span v-if="pdfZoneBlock(z)?.text_repaired" class="pdf-audit-tag tag-repair">修复</span>
                <span v-if="pdfZoneBlock(z)?.extraction_failed" class="pdf-audit-tag tag-failed">失败</span>
              </button>
              <button v-for="(z, zi) in (pdfClaimZonesByPage.get(p.page_number) || [])"
                      :key="'claim-' + z.claim_id + '-' + zi" type="button"
                      class="claim-zone-pdf"
                      :class="['claim-' + z.resolution, { sel: z.claim_id === selectedClaimId }]"
                      :style="{ left: z.rect.left + '%', top: z.rect.top + '%',
                                width: z.rect.width + '%', height: z.rect.height + '%' }"
                      :data-testid="`pdf-claim-${z.claim_id}`"
                      :title="`Claim ${z.claim_id} · ${CLAIM_RESOLUTION_LABELS[z.resolution] || z.resolution}`"
                      @click.stop="selectClaimCard(z.claim_id)" />
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
                       'extraction-failed': b.extraction_failed,
                       anchored: anchorByBlock.get(b.block_id)?.length,
                       'in-span': selectedSpan.has(b.block_id) || b.block_id === selectedBlockId,
                       evidence: evidenceBlocks.has(b.block_id) || b.block_id === selectedBlockId,
                       'block-focused': focusedBlockId === b.block_id }]"
            :data-block-id="b.block_id"
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
              <figcaption v-if="b.table_title || titleCellsFor(b).length"><template
                v-if="titleCellsFor(b).length"><button
                v-for="titleCell in titleCellsFor(b)" :key="titleCell.cell_id"
                type="button"
                class="cell-btn title-cell-btn"
                :class="{ 'has-claims': claimsForCell(titleCell.cell_id).length, 'cell-sel': titleCell.cell_id === selectedCellKey }"
                :data-testid="`cell-${b.block_id}-R${titleCell.row_index}-C${titleCell.column_index}`"
                :title="`单元格 R${titleCell.row_index}C${titleCell.column_index} · ${titleCell.cell_id}`"
                @click.stop="selectCellCard(titleCell.cell_id)"
              >{{ titleCell.text || b.table_title }}</button></template><template
                v-else>{{ b.table_title }}</template><span v-if="b.table_source === 'text_layout'" class="table-badge">无画线重建</span></figcaption>
              <div class="table-scroll">
                <table>
                  <thead v-if="tableGridFor(b).headerRows.length">
                    <tr v-for="(headerCells, hi) in tableGridFor(b).headerRows" :key="hi"><th
                        v-for="cell in headerCells" :key="cell.colIndex"
                        :colspan="cell.colspan > 1 ? cell.colspan : undefined"
                        :rowspan="cell.rowspan > 1 ? cell.rowspan : undefined"
                        :class="{ 'cell-hot': cell.entry, 'cell-sel': cell.entry && cell.entry.cell_id === selectedCellKey }"><template
                        v-if="cell.entry"><button
                        type="button"
                        class="cell-btn"
                        :class="{ 'has-claims': claimsForCell(cell.entry.cell_id).length }"
                        :data-testid="`cell-${b.block_id}-R${cell.physicalRow}-C${cell.colIndex}`"
                        :title="`单元格 R${cell.physicalRow}C${cell.colIndex} · ${cell.entry.cell_id}`"
                        @click.stop="selectCellCard(cell.entry.cell_id)"
                      >{{ cell.text }}</button></template><template v-else>{{ cell.text }}</template></th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(bodyCells, ri) in tableGridFor(b).bodyRows" :key="ri"
                        :class="{ 'claim-table-row': claimsForDataRow(b.block_id, ri + 1).length }"><td
                        v-for="(cell, cellIdx) in bodyCells" :key="cell.colIndex"
                        :colspan="cell.colspan > 1 ? cell.colspan : undefined"
                        :rowspan="cell.rowspan > 1 ? cell.rowspan : undefined"
                        :class="{ 'cell-hot': cell.entry, 'cell-sel': cell.entry && cell.entry.cell_id === selectedCellKey }"><button
                      v-if="cellIdx === 0 && props.client?.spotExtract"
                      type="button"
                      class="spot-extract-btn spot-row-btn"
                      :data-testid="`spot-extract-row-${b.block_id}-${ri + 1}`"
                      :disabled="spotExtracting === `${b.block_id}:${ri + 1}`"
                      title="解析此行：生成 draft 需求进澄清待确认"
                      :aria-label="`解析此行（第 ${ri + 1} 行）`"
                      @click.stop="spotExtractBlock(b, ri + 1)"
                    ><Wand2 :size="11" aria-hidden="true" /></button><template
                      v-if="cell.entry"><button
                      type="button"
                      class="cell-btn"
                      :class="{ 'has-claims': claimsForCell(cell.entry.cell_id).length }"
                      :data-testid="`cell-${b.block_id}-R${cell.physicalRow}-C${cell.colIndex}`"
                      :title="`单元格 R${cell.physicalRow}C${cell.colIndex} · ${cell.entry.cell_id}`"
                      @click.stop="selectCellCard(cell.entry.cell_id)"
                    >{{ cell.text }}</button></template><template v-else>{{ cell.text }}</template><span
                      v-if="cellIdx === bodyCells.length - 1 && claimsForDataRow(b.block_id, ri + 1).length"
                      class="claim-row-controls"><button
                        v-for="claim in claimsForDataRow(b.block_id, ri + 1)" :key="claim.claim_id"
                        type="button" class="claim-row-chip"
                        :class="['claim-' + claim.resolution, { sel: claim.claim_id === selectedClaimId }]"
                        :data-testid="`claim-row-${claim.claim_id}`"
                        :title="`Claim ${claim.claim_id} · ${CLAIM_RESOLUTION_LABELS[claim.resolution] || claim.resolution}`"
                        @click.stop="selectClaimCard(claim.claim_id)"><i /></button></span></td></tr>
                  </tbody>
                </table>
              </div>
              <button
                v-if="b.text_repaired"
                class="repair-tag"
                type="button"
                data-testid="repair-tag"
                :title="`原文断词已做 ${b.text_repairs?.length || 0} 处确定性修复，点击查看审计记录`"
                @click.stop="selectBlockCard(b)"
              >原文修复</button>
              <button
                v-if="b.extraction_failed"
                class="failed-extraction-tag"
                type="button"
                data-testid="failed-extraction-tag"
                title="该章节 AI 抽取失败，点击定位"
                @click.stop="selectBlockCard(b)"
              >抽取失败</button>
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
              <template v-for="(seg, i) in segments(b)" :key="i"><span v-if="seg.claim"
                :class="['claim-span-zone', 'claim-' + seg.claim.resolution, { sel: seg.claim.claim_id === selectedClaimId }]"
                role="button" tabindex="0" :data-testid="`claim-span-${seg.claim.claim_id}`"
                @click.stop="selectClaimCard(seg.claim.claim_id)"
                @keydown.enter.stop.prevent="selectClaimCard(seg.claim.claim_id)"
                @keydown.space.stop.prevent="selectClaimCard(seg.claim.claim_id)"><mark v-if="seg.mark">{{ seg.text }}</mark><template v-else>{{ seg.text }}</template></span><span v-else><mark v-if="seg.mark">{{ seg.text }}</mark><template v-else>{{ seg.text }}</template></span></template>
              <button
                v-if="b.text_repaired"
                class="repair-tag"
                type="button"
                data-testid="repair-tag"
                :title="`原文断词已做 ${b.text_repairs?.length || 0} 处确定性修复，点击查看审计记录`"
                @click.stop="selectBlockCard(b)"
              >原文修复</button>
              <button
                v-if="b.extraction_failed"
                class="failed-extraction-tag"
                type="button"
                data-testid="failed-extraction-tag"
                title="该章节 AI 抽取失败，点击定位"
                @click.stop="selectBlockCard(b)"
              >抽取失败</button>
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
              <button
                v-if="props.client?.spotExtract && !isHeading(b)"
                class="spot-extract-btn"
                type="button"
                :data-testid="`spot-extract-${b.block_id}`"
                :disabled="spotExtracting === `${b.block_id}:`"
                title="解析此段：生成 draft 需求进澄清待确认"
                @click.stop="spotExtractBlock(b)"
              >解析此段</button>
            </p>
          </div>
        </template>
      </article>

      <aside class="doc-detail" data-testid="doc-detail">
        <div v-if="!selectedReq && !selectedBlock && !selectedRow && !selectedClaim && !selectedCell" class="doc-detail-empty"><MessageSquareText :size="26" :stroke-width="1.6" aria-hidden="true" /><span>点击原文段落或页边编号查看解析结果</span></div>
        <div v-else-if="selectedClaim" class="doc-detail-card" data-testid="claim-card">
          <div class="dd-head">
            <span class="dd-module">Claim Ledger</span>
            <span class="dd-status" :class="'claim-' + selectedClaim.resolution">{{ CLAIM_RESOLUTION_LABELS[selectedClaim.resolution] || selectedClaim.resolution }}</span>
          </div>
          <h3 class="dd-title">{{ selectedClaimDisplayTitle }}</h3>
          <div class="dd-meta">{{ selectedClaim.claim_id }} · {{ claimFocusKind(selectedClaim) }}</div>
          <div class="dd-section">
            <div class="dd-label">账本状态</div>
            <div class="dd-body">{{ CLAIM_RESOLUTION_LABELS[selectedClaim.resolution] || selectedClaim.resolution }}<template v-if="selectedClaim.classification"> · {{ selectedClaim.classification }}</template></div>
          </div>
          <div v-if="selectedClaim.mapping_error" class="dd-suspicion">定位失败：{{ selectedClaim.mapping_error }}</div>
          <div v-if="selectedClaim.authority_status === 'catalog_only'" class="dd-suspicion" data-testid="claim-catalog-only">
            原文结构已更新；AI 抽取仍属于上一版解析，本条暂按待确认展示。
          </div>
          <div class="dd-section">
            <div class="dd-label">Claim 原文</div>
            <div v-if="selectedClaimSourceFields.length" class="claim-source-table" data-testid="claim-source-table">
              <div v-if="selectedClaimHasRowIdentity" class="claim-source-title" data-testid="claim-source-title">
                <span>{{ selectedClaimSourceFields[0].value }}</span>
                <strong>{{ selectedClaimSourceFields[1].value }}</strong>
              </div>
              <div class="claim-source-values">
                <div v-for="field in selectedClaimSourceValues" :key="`${field.label}:${field.value}`"
                     class="claim-source-value" data-testid="claim-source-value">
                  <div class="claim-source-value-label">{{ field.label }}</div>
                  <div class="claim-source-value-text">{{ field.value }}</div>
                </div>
              </div>
              <details class="claim-source-raw" data-testid="claim-source-raw">
                <summary>查看权威扁平原文</summary>
                <div class="dd-quote">{{ selectedClaim.text }}</div>
              </details>
            </div>
            <div v-else class="dd-quote">{{ selectedClaim.text }}</div>
          </div>
        </div>
        <div v-else-if="selectedRow" class="doc-detail-card" data-testid="table-row-card">
          <div class="dd-head">
            <span class="dd-module">{{ selectedRow.kind === "covered" ? "表格行 · 分析范围" : (selectedRow.kind === "req" ? "表格行 · 解析结果" : "表格行 · 背景") }}</span>
            <span class="dd-status">第 {{ selectedRow.rowIndex }} 行</span>
          </div>
          <h3 class="dd-title">{{ selectedRow.kind === "covered" ? "该行已纳入需求解析" : (selectedRow.kind === "req" ? `该行解析出 ${selectedRowRelatedReqs.length} 条需求` : "该行没有单独生成研发需求") }}</h3>
          <div v-if="selectedRow.section || selectedRow.page" class="dd-meta" data-testid="row-meta">
            {{ selectedRow.section }}<template v-if="selectedRow.page"> · PDF 第 {{ selectedRow.page }} 页</template>
          </div>
          <div class="dd-section"><div class="dd-body">{{ selectedRow.kind === "covered"
            ? "该表格行已纳入一条或多条抽取需求的来源范围（引句或描述覆盖了行内容），它不是独立锚点，因此不重复挂批注。可从下方查看关联需求。"
            : (selectedRow.kind === "req"
              ? "该表格行的原文解析出了多条独立需求。为避免只展示第一条，下面列出该行的全部解析结果。"
              : "该表格行未被任何已抽取需求的引句或来源范围覆盖，因此没有单独生成研发需求。如认为该行实际包含需求，可点下方「解析此行」做定点解析（结果进澄清待确认）。") }}</div></div>
          <div v-if="selectedRowRelatedReqs.length" class="dd-section">
            <button v-for="req in selectedRowRelatedReqs" :key="req.ai_req_id"
                    class="echo-jump" data-testid="row-echo-jump" type="button"
                    @click.stop="jumpToRelatedReq(req)">
              查看批注 {{ reqNumber(req) }}《{{ req.title }}》
            </button>
          </div>
          <div class="dd-section">
            <div class="dd-label">原文（表格行）</div>
            <div class="dd-quote" data-testid="row-quote">{{ selectedRow.text }}</div>
          </div>
          <div class="dd-section">
            <div class="dd-label">中文翻译</div>
            <div v-if="selectedRow.translation" class="dd-body" data-testid="row-translation">{{ selectedRow.translation }}</div>
            <div v-else-if="selectedRow.translationNote" class="dd-body dd-empty">翻译未通过防幻觉校验，保留原文（{{ selectedRow.translationNote }}）</div>
            <div v-else class="dd-body dd-empty" data-testid="row-translation-empty">暂无翻译</div>
          </div>
          <div v-if="props.client?.spotExtract" class="dd-section">
            <button class="button" type="button" data-testid="row-spot-extract"
                    :disabled="spotExtracting === `${selectedRow.block.block_id}:${selectedRow.rowIndex}`"
                    title="解析此行：生成 draft 需求进澄清待确认"
                    @click.stop="spotExtractBlock(selectedRow.block, selectedRow.rowIndex)">
              <Wand2 :size="14" aria-hidden="true" />{{ spotExtracting === `${selectedRow.block.block_id}:${selectedRow.rowIndex}` ? "解析中" : "解析此行" }}
            </button>
          </div>
        </div>
        <div v-else-if="selectedCell" class="doc-detail-card" data-testid="table-cell-card">
          <div class="dd-head">
            <span class="dd-module">单元格 · {{ selectedCell.entry.structural_role || "data" }}</span>
            <span class="dd-status">R{{ selectedCell.entry.row_index }}C{{ selectedCell.entry.column_index }}</span>
          </div>
          <h3 class="dd-title">{{ selectedCell.entry.table_title || "表格单元格" }}</h3>
          <div class="dd-meta" data-testid="cell-meta">
            {{ selectedCell.entry.cell_id }}<template v-if="selectedCell.entry.a1_address"> · {{ selectedCell.entry.sheet_name }}!{{ selectedCell.entry.a1_address }}</template><template v-else-if="selectedCell.entry.page"> · PDF 第 {{ selectedCell.entry.page }} 页</template>
          </div>
          <div class="dd-section" v-if="(selectedCell.entry.header_path || []).length">
            <div class="dd-label">列头</div>
            <div class="dd-body" data-testid="cell-header-path">{{ (selectedCell.entry.header_path || []).join(" / ") }}</div>
          </div>
          <div class="dd-section" v-if="(selectedCell.entry.row_header_context || []).length">
            <div class="dd-label">行头</div>
            <div class="dd-body" data-testid="cell-row-header">{{ (selectedCell.entry.row_header_context || []).join(" / ") }}</div>
          </div>
          <div class="dd-section">
            <div class="dd-label">单元格正文</div>
            <div class="dd-quote" data-testid="cell-text">{{ selectedCell.entry.text }}</div>
          </div>
          <div v-if="selectedCell.claims.length" class="dd-section">
            <div class="dd-label">关联 Claim</div>
            <button v-for="claim in selectedCell.claims" :key="claim.claim_id"
                    type="button" class="echo-jump"
                    :data-testid="`cell-claim-${claim.claim_id}`"
                    @click.stop="selectClaimCard(claim.claim_id)">
              Claim {{ claim.claim_id }} · {{ CLAIM_RESOLUTION_LABELS[claim.resolution] || claim.resolution }}
            </button>
          </div>
          <div v-if="props.client?.spotExtract && selectedCell.block" class="dd-section">
            <button class="button" type="button" data-testid="cell-spot-extract"
                    :disabled="spotExtracting === `${selectedCell.entry.block_id}:${selectedCell.entry.cell_id}`"
                    title="解析此格：生成 draft 需求进澄清待确认（携带表标题+行头+列头上下文）"
                    @click.stop="spotExtractBlock(selectedCell.block, undefined, selectedCell.entry.cell_id)">
              <Wand2 :size="14" aria-hidden="true" />{{ spotExtracting === `${selectedCell.entry.block_id}:${selectedCell.entry.cell_id}` ? "解析中" : "解析此格" }}
            </button>
          </div>
        </div>
        <div v-else-if="selectedBlock" class="doc-detail-card"
             :data-testid="selectedBlockKind === 'failed' ? 'failed-card' : (selectedBlockKind === 'omission' ? 'omission-card' : (selectedBlockKind === 'echo' ? 'echo-card' : (selectedBlockKind === 'covered' ? 'covered-card' : (selectedBlockKind === 'req_group' ? 'req-group-card' : 'context-card'))))">
          <div class="dd-head">
            <span class="dd-module">{{ selectedBlockKind === "failed" ? "抽取失败" : (selectedBlockKind === "omission" ? "未覆盖" : (selectedBlockKind === "echo" ? "重复段" : (selectedBlockKind === "covered" ? "分析范围" : (selectedBlockKind === "req_group" ? "解析结果" : "背景/上下文")))) }}</span>
            <span class="dd-status">说明</span>
          </div>
          <h3 class="dd-title">{{ selectedBlockKind === "failed" ? "该段所在章节未完成抽取" : (selectedBlockKind === "omission" ? "为什么标为未覆盖" : (selectedBlockKind === "echo" ? "该段解析已汇总" : (selectedBlockKind === "covered" ? "该段已纳入需求解析" : (selectedBlockKind === "req_group" ? `该段解析出 ${orderedSelectedRelatedReqs.length} 条需求` : "为什么没有生成研发需求")))) }}</h3>
          <div class="dd-section"><div class="dd-body">{{ selectedBlockKind === "failed" ? FAILED_EXTRACTION_REASON : (selectedBlockKind === "omission" ? OMISSION_REASON : (selectedBlockKind === "echo" ? ECHO_REASON : (selectedBlockKind === "covered" ? COVERED_REASON : (selectedBlockKind === "req_group" ? REQ_GROUP_REASON : CONTEXT_REASON)))) }}</div></div>
          <div v-if="selectedBlock.text_repaired" class="dd-section repair-audit" data-testid="repair-audit">
            <div class="dd-label">原文修复 · {{ selectedRepairEvents.length }} 处</div>
            <div v-if="repairRulesOf(selectedBlock)" class="repair-rules">{{ repairRulesOf(selectedBlock) }}</div>
            <div class="repair-compare">
              <div><span>修复前</span><p>{{ selectedBlock.raw_text || "" }}</p></div>
              <div><span>修复后</span><p>{{ selectedBlock.text || "" }}</p></div>
            </div>
            <div v-if="selectedRepairEvents.length" class="repair-events">
              <div v-for="(event, index) in selectedRepairEvents" :key="index">
                <code>{{ repairEventText(event, "before") }}</code>
                <span>→</span>
                <code>{{ repairEventText(event, "after") }}</code>
                <small>{{ repairEventText(event, "rule") }}</small>
              </div>
            </div>
          </div>
          <div v-if="selectedBlockKind === 'omission' && (props.client?.applyOmissionAction || props.client?.reextractOmission)"
               class="dd-section omission-actions" data-testid="omission-actions">
            <div class="dd-label">遗漏处置</div>
            <div v-if="omissionStateFor(selectedBlock.block_id)" class="omission-state" data-testid="omission-state">
              {{ omissionStatusLabel(selectedBlock.block_id) }}
            </div>
            <textarea v-model="omissionNote" class="dd-comment" data-testid="omission-note" placeholder="处置备注（可选）" />
            <div class="omission-action-row">
              <button v-if="props.client?.applyOmissionAction" class="button" type="button"
                      data-testid="omission-non-requirement" :disabled="omissionSaving"
                      @click="applyOmissionDisposition('non_requirement')">非需求</button>
              <button v-if="props.client?.applyOmissionAction" class="button" type="button"
                      data-testid="omission-confirm" :disabled="omissionSaving"
                      @click="applyOmissionDisposition('issue_confirmed')">确认遗漏</button>
              <button v-if="props.client?.reextractOmission" class="button primary" type="button"
                      data-testid="omission-reextract" :disabled="omissionSaving"
                      @click="reextractSelectedOmission">
                <RefreshCw :class="{ spin: omissionSaving }" :size="14" aria-hidden="true" />定点补抽
              </button>
            </div>
          </div>
          <div v-if="(selectedBlockKind === 'echo' || selectedBlockKind === 'covered' || selectedBlockKind === 'req_group') && orderedSelectedRelatedReqs.length" class="dd-section">
            <button v-for="req in orderedSelectedRelatedReqs" :key="req.ai_req_id"
                    class="echo-jump" data-testid="echo-jump" type="button"
                    @click.stop="jumpToRelatedReq(req)">
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
          <div class="dd-nav">
            <span class="dd-anno-no" data-testid="dd-anno-no">批注 {{ reqNumber(selectedReq) }}<template v-if="selectedReqIndex >= 0"> · {{ selectedReqIndex + 1 }}/{{ orderedReqs.length }}</template></span>
            <span class="dd-nav-btns">
              <button type="button" class="dd-nav-btn" data-testid="dd-prev" title="上一条批注" aria-keyshortcuts="K" @click="stepReq(-1)"><ChevronLeft :size="15" aria-hidden="true" /></button>
              <button type="button" class="dd-nav-btn" data-testid="dd-next" title="下一条批注" aria-keyshortcuts="J" @click="stepReq(1)"><ChevronRight :size="15" aria-hidden="true" /></button>
            </span>
          </div>
          <h3 class="dd-title">{{ selectedReq.title }}</h3>
          <div class="dd-meta">{{ selectedReq.type }} · {{ selectedReq.priority }} · {{ selectedReq.source_section }}</div>
          <div v-if="(selectedReq.suspicion_reasons || []).length" class="dd-suspicion" data-testid="dd-suspicion">
            ⚠ 建议优先复核：{{ (selectedReq.suspicion_reasons || []).join("、") }}
          </div>
          <div v-if="(selectedReq.consistency_flags || []).length" class="dd-consistency" data-testid="dd-consistency">
            ⇄ 全文档一致性：{{ (selectedReq.consistency_flags || []).join("；") }}
          </div>
          <div v-if="selectedReq.needs_reconfirmation" class="dd-reconfirmation" data-testid="dd-reconfirmation">
            需复核：来源证据或解析内容已变化，历史裁决与覆盖值未沿用。
          </div>

          <div class="dd-legend">{{ viewMode === "pdf" ? "左侧原版页面为核对依据，右侧为解析结果" : "解析文本可能丢失原版字形与间距，请用原版核对来源" }}</div>
          <div class="dd-section dd-result-primary" data-testid="dd-requirement-summary">
            <div class="dd-label">抽取需求</div>
            <div class="dd-body">{{ selectedReq.description || "未生成需求摘要" }}</div>
          </div>
          <div class="dd-section" v-if="selectedReq.source_quote">
            <div class="dd-label">抽取原句（对照左页）</div><div class="dd-quote">{{ selectedReq.source_quote }}</div>
          </div>
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
          <div class="dd-section" v-if="ownershipReasonOf(selectedReq)">
            <div class="dd-label">为什么判为{{ OWNERSHIP_LABELS[ownershipOf(selectedReq)] || ownershipOf(selectedReq) }}</div>
            <div class="dd-body" data-testid="dd-ownership-reason">{{ ownershipReasonOf(selectedReq) }}</div>
            <div v-if="ownershipOverrideNote(selectedReq)" class="dd-body dd-empty">{{ ownershipOverrideNote(selectedReq) }}</div>
          </div>

          <div class="dd-section">
            <div class="dd-label">模块（可改）</div>
            <input v-model.trim="moduleEdit" class="dd-select" data-testid="dd-module-select"
                   list="review-module-options" autocomplete="off" maxlength="20" />
            <datalist id="review-module-options">
              <option v-for="m in moduleOptions" :key="m" :value="m" />
            </datalist>
          </div>
          <div class="dd-section">
            <div class="dd-label">归属（可改，规则初判：{{ OWNERSHIP_OPTIONS.find(o => o.value === selectedReq?.ownership)?.label || "软件" }}）</div>
            <select v-model="ownershipEdit" class="dd-select" data-testid="dd-ownership-select">
              <option v-for="o in OWNERSHIP_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
          <textarea v-model="comment" class="dd-comment" data-testid="dd-comment" placeholder="审查意见（可选）" />
          <div class="dd-actions">
            <button class="button primary" type="button" data-testid="dd-accept" aria-keyshortcuts="A" :disabled="isSaving" @click="decide('accepted')"><Check :size="14" aria-hidden="true" />接受</button>
            <button class="button reject" type="button" data-testid="dd-reject" aria-keyshortcuts="R" :disabled="isSaving" @click="decide('rejected')"><Ban :size="14" aria-hidden="true" />拒绝</button>
            <button class="button" type="button" data-testid="dd-discuss" aria-keyshortcuts="D" :disabled="isSaving" @click="decide('needs_discussion')"><MessagesSquare :size="14" aria-hidden="true" />讨论</button>
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
/* 疑似遗漏统计即跳转入口 */
.omission-jump { border: 0; background: none; padding: 0; font: inherit; color: inherit; cursor: pointer; }
.omission-jump:disabled { cursor: default; }
.omission-jump:not(:disabled):hover { color: #b45309; }
.omission-jump:not(:disabled):hover strong { color: #b45309; text-decoration: underline; }
.doc-message { padding: 6px 14px; font-size: 12px; color: #b45309; background: #fdf3e3; }
.doc-body { display: grid; grid-template-columns: 1fr 360px; gap: 0; flex: 1; min-height: 0; }
.doc-paper { overflow: auto; padding: 12px 18px; background: #ffffff; }
.doc-toolbar-actions { display: flex; align-items: center; gap: 10px; }
.internal-check-batch { display: flex; align-items: center; gap: 4px; padding-right: 8px;
  border-right: 1px solid #e6e9f0; }
.internal-check-batch select { max-width: 154px; height: 28px; border: 1px solid #d8dde6;
  border-radius: 6px; padding: 0 6px; color: #5c6675; background: #fff; font-size: 11px; }
.internal-check-batch button { height: 28px; display: inline-flex; align-items: center; gap: 4px;
  border: 1px solid #cfd6e2; border-radius: 6px; padding: 0 7px; color: #465568;
  background: #fff; font-size: 11px; cursor: pointer; }
.internal-check-batch button:disabled { opacity: .55; cursor: default; }
.mode-toggle { display: flex; gap: 2px; padding: 2px; background: #eef1f6; border-radius: 8px; }
.mode-toggle button { border: 0; border-radius: 6px; padding: 4px 10px; font-size: 12px; color: #5c6675;
  background: transparent; cursor: pointer; }
.mode-toggle button.active { background: #ffffff; color: #1e41c9; box-shadow: 0 1px 2px rgba(0,0,0,.08); }
/* 原版影印：页图 + 百分比批注覆盖层（与分享 HTML 同源数据） */
.pdf-paper { background: #eceef2; padding: 16px 48px 16px 16px; }
.pdf-page { position: relative; margin: 0 auto 14px; max-width: 920px; background: #ffffff;
  box-shadow: 0 2px 10px rgba(0,0,0,.10); border-radius: 4px; overflow: visible; }
.pdf-page > img { border-radius: 4px; }
.pdf-page img { display: block; width: 100%; height: auto; }
.pdf-page-loading { position: absolute; inset: 0; display: flex; align-items: center;
  justify-content: center; color: #98a1b3; font-size: 12px; }
.pdf-overlay { position: absolute; inset: 0; }
.pdf-marker { position: absolute; right: -32px; min-width: 26px; height: 22px; border-radius: 11px;
  border: 1px solid #cbd5e1; background: #ffffff; color: #1e41c9; font-size: 11px; font-weight: 700;
  cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,.14); z-index: 3; }
.pdf-marker.marker-omission { color: #b45309; border-color: #ecd9ae; background: #fdf3e3; }
.pdf-marker.sel { outline: 2px solid #5978f7; }
/* 全段落热区（0714）：透明可点,悬停淡蓝提示——点一段出翻译和解析;标记浮在热区上层 */
.pdf-block-zone { position: absolute; z-index: 1; margin: 0; padding: 0; border: 1px solid transparent;
  background: transparent; cursor: pointer; pointer-events: auto; border-radius: 3px;
  transition: background .12s, border-color .12s; }
.pdf-block-zone:hover { background: rgba(89, 120, 247, .04); border-color: rgba(89, 120, 247, .42); }
.pdf-block-zone.sel { background: rgba(89, 120, 247, .06); border-color: rgba(89, 120, 247, .72); }
.pdf-block-zone.quote-sel { background: rgba(89, 120, 247, .04); border-color: rgba(89, 120, 247, .55); border-style: dashed; }
.pdf-block-zone.zone-omission:hover { background: rgba(204, 137, 37, .05); border-color: rgba(204, 137, 37, .48); }
.pdf-block-zone.zone-omission.sel { background: rgba(204, 137, 37, .07); border-color: rgba(180, 83, 9, .7); }
.pdf-block-zone.zone-echo:hover, .pdf-block-zone.zone-echo.sel {
  background: rgba(15,118,110,.05); border-color: rgba(15,118,110,.5); }
.pdf-block-zone.zone-covered:hover, .pdf-block-zone.zone-covered.sel {
  background: rgba(10,132,255,.045); border-color: rgba(10,132,255,.5); }
/* 表格行级热区（v12）：与段落块热区的蓝区分开,行用青色细框 */
.pdf-block-zone.table-row:hover { background: rgba(15,118,110,.05); border-color: rgba(15,118,110,.45); }
.pdf-block-zone.table-row.sel { background: rgba(15,118,110,.08); border-color: rgba(15,118,110,.78); }
.claim-zone-pdf { position: absolute; z-index: 4; margin: 0; padding: 0; border: 1px solid transparent;
  border-radius: 2px; background: transparent; cursor: pointer; }
.claim-zone-pdf:hover, .claim-zone-pdf.sel { border-color: currentColor; }
.claim-covered { color: #2f6842; }
.claim-excluded { color: #6b7280; }
.claim-uncertain { color: #9a6700; }
.pdf-audit-tag { position: absolute; left: 2px; top: -13px; padding: 1px 3px; border-radius: 3px;
  background: rgba(255,255,255,.94); font-size: 8px; font-weight: 650; line-height: 1.15;
  pointer-events: none; opacity: .72; }
.pdf-audit-tag.tag-repair { color: #53606f; border-bottom: 1px dotted #8793a1; }
.pdf-audit-tag.tag-failed { left: auto; right: 2px; color: #a23b3f; border-bottom: 1px solid #d9a6a8; }
.pdf-echo-tag { position: absolute; right: 2px; top: -13px; display: inline-block; padding: 0 2px 1px;
  border-bottom: 1px dashed #667085; color: #4b5563; background: rgba(255,255,255,.92);
  z-index: 2; font-size: 9px; font-weight: 600; line-height: 1.15; white-space: nowrap;
  pointer-events: auto; cursor: pointer; opacity: 0; transition: opacity .12s; }
.pdf-block-zone.zone-echo:hover .pdf-echo-tag,
.pdf-block-zone.zone-echo.sel .pdf-echo-tag,
.pdf-block-zone.zone-covered:hover .pdf-echo-tag,
.pdf-block-zone.zone-covered.sel .pdf-echo-tag { opacity: 1; }
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
/* F4：来源块定位的瞬时高亮环（functional 评审跳转传入；与选中态区分，外部跳转的短暂强调） */
.doc-block.block-focused { animation: fr-focus-ring 2.6s ease-out 1; border-radius: 8px; }
@keyframes fr-focus-ring {
  0% { box-shadow: 0 0 0 0 rgba(29, 78, 216, 0.55); background: #eef2ff; }
  35% { box-shadow: 0 0 0 5px rgba(29, 78, 216, 0.30); background: #eef2ff; }
  100% { box-shadow: 0 0 0 0 rgba(29, 78, 216, 0); background: transparent; }
}
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
.doc-block.extraction-failed { box-shadow: inset 2px 0 0 rgba(193, 52, 58, .48); }
.dd-legend { font-size: 11px; color: #98a1b3; margin: 4px 0 8px; }
.doc-block.omission:hover { background: #fcfbf7; }
.doc-gutter { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
.doc-text { margin: 0; font-size: 13px; line-height: 1.48; color: #3f4a61; white-space: pre-wrap; }
.doc-text mark { background: #f3d9a0; padding: 0 1px; }
.claim-span-zone { border-radius: 2px; cursor: pointer; box-decoration-break: clone;
  -webkit-box-decoration-break: clone; }
.claim-span-zone.claim-covered { box-shadow: inset 0 -2px 0 rgba(47,104,66,.55); }
.claim-span-zone.claim-excluded { box-shadow: inset 0 -2px 0 rgba(107,114,128,.45); }
.claim-span-zone.claim-uncertain { background: rgba(246,239,216,.62); box-shadow: inset 0 -2px 0 rgba(154,103,0,.58); }
.claim-span-zone.sel { outline: 2px solid currentColor; outline-offset: 1px; }
.claim-row-controls { display: inline-flex; gap: 3px; margin-left: 6px; vertical-align: middle; }
.claim-row-chip { width: 14px; height: 14px; padding: 0; border: 0; background: transparent; cursor: pointer; }
.claim-row-chip i { display: block; width: 7px; height: 7px; margin: auto; border-radius: 50%; background: currentColor; }
.claim-row-chip.sel { outline: 2px solid currentColor; outline-offset: 1px; }
.anno-chip { font-size: 11px; border: 1px solid #cbd5e1; border-radius: 10px; padding: 1px 7px; background: #ffffff; cursor: pointer; max-width: 124px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anno-chip.sel { outline: 2px solid #5978f7; }
.anno-chip.st-accepted { border-color: #1d8a5c; color: #1d8a5c; }
.anno-chip.st-rejected { border-color: #d63a40; color: #d63a40; }
.anno-chip.st-needs_discussion { border-color: #b06f12; color: #b06f12; }
.omission-tag { display: inline-flex; margin-left: 6px; padding: 0 2px 1px; border: 0;
  border-bottom: 1px dotted #cbd5e1; border-radius: 0; background: transparent; color: #98a1b3;
  font-size: 9px; line-height: 1; cursor: pointer; vertical-align: super; }
.omission-tag:hover, .omission-tag.sel { color: #b06f12; border-color: #b06f12; background: #fff9ec; }
.repair-tag, .failed-extraction-tag { display: inline-flex; margin-left: 6px; padding: 0 2px 1px;
  border: 0; border-bottom: 1px dotted #aeb6c2; border-radius: 0; background: transparent;
  color: #7a8496; font-size: 9px; line-height: 1; cursor: pointer; vertical-align: super; }
.repair-tag:hover { color: #465568; border-color: #465568; }
.failed-extraction-tag { color: #a23b3f; border-color: #d6a4a6; }
.failed-extraction-tag:hover { color: #7f1f24; border-color: #7f1f24; }
.echo-tag { display: inline-flex; margin-left: 6px; padding: 0 2px 1px; border: 0;
  border-bottom: 1px dashed #cbd5e1; border-radius: 0; background: transparent; color: #7a8496;
  font-size: 9px; line-height: 1; cursor: pointer; vertical-align: super; }
.echo-tag:hover { color: #1f5f58; border-color: #1f5f58; }
/* 点解析（WP-B）：行/块悬停显现；无 LLM 配置不隐藏，点击返回真实错误 */
.spot-extract-btn { display: inline-flex; align-items: center; margin-left: 6px; padding: 0 2px 1px;
  border: 0; border-bottom: 1px dotted #b6c3f0; border-radius: 0; background: transparent;
  color: #98a1b3; font-size: 9px; line-height: 1; cursor: pointer; vertical-align: super;
  opacity: 0; pointer-events: none; transition: opacity .12s; }
.doc-block:hover .spot-extract-btn, .doc-table tr:hover .spot-row-btn,
.spot-extract-btn:focus-visible, .spot-extract-btn:disabled { opacity: 1; pointer-events: auto; }
.spot-extract-btn:hover { color: #1e41c9; border-color: #1e41c9; background: #eef2ff; }
.spot-extract-btn:disabled { cursor: wait; color: #b6c3f0; }
.spot-row-btn { margin: 0 4px 0 0; vertical-align: middle; }
/* v15 cell 级闭环：有 cell_context 的格可点出 cell 卡片（R×C + 双表头上下文）;
   标题/表头格同式（th/figcaption 一并着色） */
.cell-btn { display: inline; padding: 0 1px; border: 0; border-bottom: 1px dotted transparent;
  background: transparent; font: inherit; text-align: left; cursor: pointer; }
td.cell-hot .cell-btn, th.cell-hot .cell-btn { border-bottom-color: #b6c3f0; }
td.cell-hot .cell-btn:hover, th.cell-hot .cell-btn:hover { background: #eef2ff; border-bottom-color: #1e41c9; }
td.cell-sel, th.cell-sel { outline: 2px solid #5978f7; outline-offset: -2px; }
.cell-btn.has-claims { border-bottom-color: #1d8a5c; }
.title-cell-btn { font-weight: inherit; margin-right: 6px; }
.title-cell-btn.cell-sel { outline: 2px solid #5978f7; outline-offset: -1px; }
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
/* 顺序过审导航：批注号 + 上一条/下一条 */
.dd-nav { display: flex; justify-content: space-between; align-items: center; margin: 6px 0 2px; }
.dd-anno-no { font-size: 12px; font-weight: 650; color: #1e41c9; }
.dd-nav-btns { display: flex; gap: 4px; }
.dd-nav-btn { width: 26px; height: 24px; border: 1px solid #e6e9f0; border-radius: 6px; background: #fff;
  color: #5c6675; display: grid; place-items: center; cursor: pointer; }
.dd-nav-btn:hover { background: #eef2ff; color: #1e41c9; }
.dd-module { font-weight: 700; color: #1e41c9; }
.dd-status { font-size: 12px; padding: 1px 8px; border-radius: 8px; background: #e6e9f0; }
.dd-status.st-accepted { background: #e6f6ef; color: #1d8a5c; }
.dd-status.st-rejected { background: #fdecec; color: #991b1b; }
.dd-title { margin: 8px 0 2px; font-size: 15px; }
.dd-meta { font-size: 12px; color: #7a8496; margin-bottom: 8px; }
.dd-suspicion { font-size: 12px; color: #b06f12; background: #fdf3e3; border-radius: 6px; padding: 4px 8px; margin-bottom: 8px; }
.dd-consistency { font-size: 12px; color: #1e41c9; background: #eef2ff; border-radius: 6px; padding: 4px 8px; margin-bottom: 8px; }
.dd-reconfirmation { font-size: 12px; color: #8a4b12; background: #fff4dd; border: 1px solid #efd39b; border-radius: 6px; padding: 6px 8px; margin-bottom: 8px; }
.dd-table { border-collapse: collapse; font-size: 12px; width: 100%; }
.dd-table th, .dd-table td { border: 1px solid #e6e9f0; padding: 3px 8px; text-align: left; }
.dd-table th { background: #fafbfd; font-weight: 600; }
.dd-section { margin: 10px 0; }
.dd-label { font-size: 11px; color: #98a1b3; text-transform: uppercase; margin-bottom: 3px; }
.dd-body { font-size: 13px; line-height: 1.55; color: #3f4a61; }
.repair-rules { margin-bottom: 6px; color: #7a8496; font: 11px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace; }
.repair-compare { display: grid; gap: 6px; }
.repair-compare > div { padding: 7px 8px; border: 1px solid #e6e9f0; border-radius: 6px; background: #fff; }
.repair-compare span { color: #98a1b3; font-size: 10px; }
.repair-compare p { margin: 2px 0 0; color: #3f4a61; font-size: 12px; line-height: 1.45; white-space: pre-wrap; }
.repair-events { margin-top: 7px; max-height: 150px; overflow: auto; }
.repair-events > div { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center; gap: 5px; padding: 3px 0; border-bottom: 1px solid #f0f2f5; font-size: 11px; }
.repair-events code { overflow-wrap: anywhere; color: #465568; }
.repair-events small { grid-column: 1 / -1; color: #98a1b3; }
.dd-list { margin: 0; padding-left: 18px; font-size: 13px; color: #3f4a61; }
.dd-quote { font-size: 12px; color: #5c6675; border-left: 3px solid #cbd5e1; padding-left: 8px; font-style: italic; }
.dd-select, .dd-comment { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px; font-size: 13px; }
.dd-comment { min-height: 56px; margin-top: 8px; resize: vertical; }
.dd-actions { display: flex; gap: 8px; margin-top: 10px; }
.omission-action-row { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 8px; }
.omission-state { display: inline-flex; padding: 2px 7px; border-radius: 6px; font-size: 12px; color: #985f0b; background: #fff3d8; }
.partial-status { color: #2563a6; }
.partial-status.failed { color: #b45309; }

/* iOS-style document workspace */
.doc-review {
  --doc-blue: #0a84ff;
  --doc-blue-strong: #0071e3;
  --doc-ink: #1d1d1f;
  --doc-secondary: #6e6e73;
  --doc-tertiary: #98989d;
  --doc-border: rgba(60, 60, 67, 0.14);
  --doc-glass: rgba(255, 255, 255, 0.76);
  --doc-motion: cubic-bezier(0.22, 1, 0.36, 1);
  background: #f1f3f7;
  color: var(--doc-ink);
}

.doc-toolbar {
  min-height: 52px;
  padding: 9px 16px;
  border-color: var(--doc-border);
  background: rgba(255, 255, 255, 0.72);
  box-shadow: 0 1px rgba(255, 255, 255, 0.72), 0 8px 22px rgba(31, 35, 48, 0.035);
  backdrop-filter: blur(24px) saturate(170%);
  -webkit-backdrop-filter: blur(24px) saturate(170%);
}

.doc-stats {
  gap: 0;
  color: var(--doc-secondary);
}

.doc-stats > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 12px;
  border-right: 1px solid var(--doc-border);
}

.doc-stats > span:first-child { padding-left: 0; }
.doc-stats > span:last-child { border-right: 0; }
.doc-stats strong { color: var(--doc-ink); font-variant-numeric: tabular-nums; }
.omission-stat.warn strong { color: #d58a18; }

.doc-toolbar-actions {
  gap: 8px;
}

.mode-toggle {
  gap: 0;
  padding: 2px;
  border: 1px solid rgba(60, 60, 67, 0.08);
  border-radius: 8px;
  background: rgba(118, 118, 128, 0.1);
}

.mode-toggle button {
  min-height: 29px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 7px;
  padding: 4px 10px;
  color: var(--doc-secondary);
  font-weight: 600;
  transition: color 160ms ease, background 160ms ease, box-shadow 180ms ease, transform 220ms var(--doc-motion);
}

.mode-toggle button:hover {
  color: var(--doc-ink);
}

.mode-toggle button:active {
  transform: scale(0.97);
}

.mode-toggle button.active {
  color: var(--doc-blue-strong);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 3px 9px rgba(31, 35, 48, 0.09), inset 0 0 0 1px rgba(60, 60, 67, 0.06);
}

.button {
  min-height: 33px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid var(--doc-border);
  border-radius: 8px;
  padding: 0 11px;
  color: #30313a;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 1px 2px rgba(31, 35, 48, 0.045), inset 0 1px rgba(255, 255, 255, 0.75);
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
  transition: color 160ms ease, border-color 160ms ease, background 160ms ease, box-shadow 180ms ease, transform 220ms var(--doc-motion);
}

.button:hover:not(:disabled) {
  color: var(--doc-ink);
  border-color: rgba(60, 60, 67, 0.22);
  background: #fff;
  box-shadow: 0 6px 15px rgba(31, 35, 48, 0.09);
  transform: translateY(-1px);
}

.button:active:not(:disabled) { transform: scale(0.965); }
.button:disabled { opacity: 0.48; cursor: default; }

.button.primary {
  color: #fff;
  border-color: rgba(0, 94, 214, 0.72);
  background: var(--doc-blue);
  box-shadow: 0 7px 16px rgba(10, 132, 255, 0.22), inset 0 1px rgba(255, 255, 255, 0.22);
}

.button.primary:hover:not(:disabled) {
  color: #fff;
  background: var(--doc-blue-strong);
}

.button.reject { color: #c7373d; }
.spin { animation: doc-spin 900ms linear infinite; }

.doc-message {
  margin: 8px 14px 0;
  padding: 8px 11px;
  border: 1px solid rgba(213, 138, 24, 0.18);
  border-radius: 8px;
  color: #9a6413;
  background: rgba(255, 248, 232, 0.86);
  box-shadow: 0 6px 18px rgba(165, 104, 15, 0.06);
  backdrop-filter: blur(16px) saturate(150%);
  -webkit-backdrop-filter: blur(16px) saturate(150%);
}

.doc-body {
  grid-template-columns: minmax(0, 1fr) clamp(390px, 32vw, 480px);
}

.doc-paper {
  padding: 16px 22px;
  background: rgba(255, 255, 255, 0.72);
}

.pdf-paper {
  background: #e8eaef;
}

.doc-paper.pdf-paper {
  padding: 16px 48px 16px 16px;
}

.pdf-page {
  margin-bottom: 16px;
  border: 1px solid rgba(60, 60, 67, 0.12);
  border-radius: 6px;
  box-shadow: 0 14px 38px rgba(31, 35, 48, 0.13), 0 2px 8px rgba(31, 35, 48, 0.08);
}

.pdf-block-zone {
  transition: background 150ms ease, border-color 150ms ease, box-shadow 180ms ease;
}

.pdf-block-zone:hover {
  box-shadow: 0 0 0 2px rgba(10, 132, 255, 0.08);
}

.pdf-marker {
  border-color: var(--doc-border);
  color: var(--doc-blue-strong);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 5px 14px rgba(31, 35, 48, 0.13);
  backdrop-filter: blur(12px) saturate(150%);
  -webkit-backdrop-filter: blur(12px) saturate(150%);
  transition: transform 220ms var(--doc-motion), box-shadow 180ms ease;
}

.pdf-marker:hover { transform: translateY(-1px) scale(1.03); }

.doc-block {
  border-radius: 4px;
  transition: background 150ms ease, box-shadow 150ms ease;
}

.doc-block.anchored {
  border-left-color: var(--doc-blue);
  background: rgba(10, 132, 255, 0.035);
}

.doc-block.anchored:hover,
.doc-block.in-span.evidence {
  background: rgba(10, 132, 255, 0.075);
}

.doc-text {
  color: #3f4149;
  line-height: 1.56;
}

.doc-text mark {
  border-radius: 3px;
  background: rgba(255, 199, 64, 0.43);
  box-shadow: inset 0 -1px rgba(184, 121, 0, 0.12);
}

.anno-chip {
  border-color: var(--doc-border);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 2px 7px rgba(31, 35, 48, 0.045);
  transition: color 150ms ease, border-color 150ms ease, background 150ms ease, transform 220ms var(--doc-motion);
}

.anno-chip:hover {
  border-color: rgba(10, 132, 255, 0.3);
  background: #fff;
  transform: translateX(1px);
}

.anno-chip.sel {
  outline: 0;
  border-color: rgba(10, 132, 255, 0.42);
  background: rgba(10, 132, 255, 0.09);
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.1);
}

.doc-detail {
  border-left-color: var(--doc-border);
  padding: 16px;
  background: rgba(246, 247, 250, 0.78);
  backdrop-filter: blur(20px) saturate(150%);
  -webkit-backdrop-filter: blur(20px) saturate(150%);
}

.doc-detail-empty {
  min-height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  color: var(--doc-tertiary);
}

.doc-detail-card {
  animation: detail-enter 300ms var(--doc-motion) both;
}

.dd-module { color: var(--doc-blue-strong); }

.dd-status,
.dd-suspicion,
.dd-consistency {
  border-radius: 7px;
}

.dd-section {
  margin: 12px 0;
}

.dd-result-primary {
  padding: 11px 12px;
  border-left: 3px solid var(--doc-blue);
  border-radius: 0 6px 6px 0;
  background: rgba(10, 132, 255, 0.055);
}

.dd-result-primary .dd-label { color: var(--doc-blue-strong); font-weight: 700; }
.dd-result-primary .dd-body { color: var(--doc-ink); font-size: 14px; line-height: 1.65; }

.dd-label {
  color: var(--doc-tertiary);
  letter-spacing: 0;
  text-transform: none;
}

.dd-body,
.dd-list {
  color: #3f4149;
  line-height: 1.6;
}

.dd-quote {
  border-left-color: rgba(10, 132, 255, 0.35);
  color: var(--doc-secondary);
  background: rgba(10, 132, 255, 0.035);
  border-radius: 0 6px 6px 0;
  padding: 7px 9px;
}

.claim-source-table {
  margin-top: 7px;
  overflow: hidden;
  border: 1px solid var(--doc-border);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.72);
}

.claim-source-title {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 9px;
  align-items: start;
  padding: 10px 11px;
  border-bottom: 1px solid var(--doc-border);
  background: rgba(10, 132, 255, 0.055);
}

.claim-source-title span {
  padding: 2px 6px;
  border-radius: 5px;
  color: var(--doc-blue-strong);
  background: rgba(10, 132, 255, 0.1);
  font-size: 11px;
  font-weight: 750;
}

.claim-source-title strong {
  min-width: 0;
  color: var(--doc-ink);
  font-size: 12px;
  line-height: 1.45;
}

.claim-source-values {
  display: grid;
}

.claim-source-value {
  display: grid;
  grid-template-columns: 62px minmax(0, 1fr);
  gap: 8px;
  padding: 9px 11px;
  border-bottom: 1px solid rgba(60, 60, 67, 0.09);
}

.claim-source-value:last-child { border-bottom: 0; }
.claim-source-value-label { color: var(--doc-tertiary); font-size: 10px; font-weight: 700; }
.claim-source-value-text { min-width: 0; color: #3f4149; font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.claim-source-raw { padding: 7px 11px 9px; border-top: 1px solid var(--doc-border); }
.claim-source-raw summary { color: var(--doc-tertiary); cursor: pointer; font-size: 10px; }
.claim-source-raw .dd-quote { margin-top: 7px; overflow-wrap: anywhere; }

.dd-select,
.dd-comment {
  border-color: var(--doc-border);
  border-radius: 8px;
  color: var(--doc-ink);
  background: rgba(255, 255, 255, 0.78);
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.dd-select:focus,
.dd-comment:focus {
  outline: 0;
  border-color: rgba(10, 132, 255, 0.5);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.12);
}

.dd-actions {
  position: sticky;
  bottom: -1px;
  z-index: 4;
  margin: 12px -4px -4px;
  padding: 10px 4px 4px;
  background: rgba(246, 247, 250, 0.82);
  backdrop-filter: blur(18px) saturate(150%);
  -webkit-backdrop-filter: blur(18px) saturate(150%);
}

@keyframes detail-enter {
  from { opacity: 0; transform: translateX(8px); }
  to { opacity: 1; transform: translateX(0); }
}

@keyframes doc-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1080px) {
  .doc-body { grid-template-columns: minmax(0, 1fr) 340px; }
  .doc-paper { padding-inline: 14px; }
  .doc-paper.pdf-paper { padding: 14px 44px 14px 12px; }
}

@media (max-width: 820px) {
  .doc-toolbar { align-items: flex-start; gap: 8px; flex-wrap: wrap; }
  .doc-body { grid-template-columns: minmax(0, 1fr); overflow: auto; }
  .doc-paper { min-height: 58vh; overflow: visible; }
  .doc-detail { max-height: 42vh; border-left: 0; border-top: 1px solid var(--doc-border); }
  .doc-stats > span { padding-inline: 7px; }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
