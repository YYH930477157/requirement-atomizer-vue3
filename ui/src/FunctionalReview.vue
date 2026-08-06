<script setup lang="ts">
/**
 * WS-F 功能需求级评审工作台。
 *
 * 评审对象从原子级条目切换为**功能需求级条目**（objective / behaviors / preconditions 等
 * functional_catalog 字段 + 三级追溯 source_quote / source_section / source_block_ids），
 * 原子级下钻条目（drilled_subatoms）作为功能需求的子级展示。旧原子视图保留为可切换模式
 * （右上「视图」开关 → 原子级），不删除（App.vue 的「审查工作台」nav 仍为完整原子裁决面）。
 *
 * 四项能力（全部走 api_server HTTP + 一条 governed 产物读取 IPC）：
 *  1. 功能需求级呈现 + 追溯链跳转（block_id → emit focus-block → App 切到文档批注）。
 *  2. verification 六列展示/编辑（确认人+时间戳）+ 四态状态机（回退人工确认 + append-only 事件时间线）。
 *  3. 手工建需求入口（provenance=manual，「无文档来源」明示、追溯列留空）。
 *  4. 需求库相似历史参考列表（采纳/忽略）+ dependencies 候选逐条接受/拒绝（拒绝不落库）。
 *
 * 数据契约见 ui/src/api-client.ts（WS4 段）与后端 api_server.py WS4 端点。CAS 冲突按
 * isNeedsReconfirmationError 处理；后端错误字段（detail/note/reason）一律透出（table-review
 * recompute_error 教训：错误必须在 UI 可见）。异步带 generation guard（loadInitialApiSession
 * 测试隔离教训：跨 await 后必须复查 generation）。
 */
import { computed, ref, watch } from "vue"
import { Check, ChevronDown, ChevronRight, Plus, RefreshCw, RotateCcw, Search, X } from "@lucide/vue"
import {
  isNeedsReconfirmationError,
  RequirementApiError,
  type BackendRequirement,
  type DependencyCandidate,
  type DependencyCandidatesPayload,
  type DependencyDecisionPayload,
  type FunctionalRequirementsPayload,
  type LifecycleEventsPayload,
  type LifecycleState,
  type ManualRequirementPayload,
  type ManualRequirementsPayload,
  type RequirementLibraryAdoptPayload,
  type RequirementLibraryEntry,
  type RequirementLibrarySearchPayload,
  type VerificationActionPayload,
  type VerificationStateRow,
  type VerificationStatesPayload,
  type VerificationSubobject,
  type VerificationTriple,
} from "./api-client"
import type { RequirementApiClient } from "./api-client"

type FunctionalClient = Pick<RequirementApiClient,
  | "loadVerificationStates"
  | "applyVerificationAction"
  | "rollbackRequirement"
  | "createManualRequirement"
  | "loadDependencyCandidates"
  | "decideDependency"
  | "searchRequirementLibrary"
  | "adoptRequirementLibrary"
  | "loadFunctionalRequirements"
  | "loadManualRequirements"
  | "loadLifecycleEvents"
  | "loadRequirements">

const props = defineProps<{
  client: FunctionalClient | null
  sessionKey: string
  active: boolean
  refreshToken: number
  outputDir: string
}>()

const emit = defineEmits<{
  (event: "focus-block", blockId: string): void
}>()

type Subatom = {
  text?: string
  source_quote?: string
  source_section?: string
  source_block_ids?: string[]
}

type FunctionalItem = {
  functional_requirement_id: string
  objective?: string
  title?: string
  behaviors?: string[]
  preconditions?: string[]
  data_constraints?: string[]
  variants?: string[]
  exceptions?: string[]
  related_dlms_objects?: string[]
  description?: string
  module?: string
  priority?: string
  source_section?: string
  source_quote?: string
  source_block_ids?: string[]
  drilled_subatoms?: Subatom[]
  drilldown_signals?: string[]
  conflict_flags?: string[]
  source_kind?: string
  manual_actor?: string
  notes?: string
  ownership_override?: string
  _origin: "functional" | "manual"
}

type LifecycleEvent = {
  requirement_id?: string
  from_state?: string
  to_state?: string
  kind?: string
  actor?: string
  reason?: string
  timestamp?: string
}

type ArtifactRead = {
  ok: boolean
  missing?: boolean
  path?: string | null
  format?: "json" | "jsonl"
  content?: unknown
  reason?: string
  detail?: string
}

const LIFECYCLE_LABELS: Record<LifecycleState, string> = {
  draft: "草稿",
  confirmed: "已确认",
  implemented: "已实现",
  verified: "已验证",
}
const LIFECYCLE_ORDER: LifecycleState[] = ["draft", "confirmed", "implemented", "verified"]
const CONFIRM_ROLES: Array<{ key: "project_manager_confirm" | "test_lead_confirm" | "dev_test_confirm"; label: string }> = [
  { key: "project_manager_confirm", label: "项目负责人" },
  { key: "test_lead_confirm", label: "测试负责人" },
  { key: "dev_test_confirm", label: "研发测试" },
]

const mode = ref<"functional" | "atomic">("functional")
const functionalItems = ref<FunctionalItem[]>([])
const verificationStates = ref<Record<string, VerificationStateRow>>({})
const lifecycleEvents = ref<LifecycleEvent[]>([])
const dependencyCandidates = ref<DependencyCandidate[]>([])
const atomicRequirements = ref<BackendRequirement[]>([])
const selectedId = ref("")
const apiMessage = ref("")
const loading = ref(false)
const expandedChildren = ref<Set<string>>(new Set())

// 手工建需求表单
const manualOpen = ref(false)
const manualForm = ref({
  objective: "",
  behaviorsText: "",
  module: "",
  ownership: "",
  priority: "P1",
  notes: "",
})
const manualSubmitting = ref(false)

// verification 编辑草稿——始终非空（避免 v-model 在 Ref<T|null> 上的窄化风险）；
// hasVerification 标记当前选中条目是否已有/可编辑验证状态。
const hasVerification = ref(false)
const verificationEdit = ref<VerificationSubobject>(defaultVerification())
const verificationSaving = ref(false)

// 回退对话框（人工确认 + append-only 留痕）
const rollbackOpen = ref(false)
const rollbackTarget = ref<LifecycleState>("draft")
const rollbackActor = ref("")
const rollbackReason = ref("")
const rollbackSubmitting = ref(false)

// 需求库检索
const libraryResults = ref<RequirementLibraryEntry[]>([])
const libraryNote = ref("")
const libraryLoading = ref(false)

// 需求库「采纳」对话框（actor/reason 必填——经 reviewer_override 通道留痕）
const adoptOpen = ref(false)
const adoptTarget = ref<RequirementLibraryEntry | null>(null)
const adoptActor = ref("")
const adoptReason = ref("")
const adoptSubmitting = ref(false)

// generation guard（loadInitialApiSession 测试隔离教训）
let loadGeneration = 0
let opGeneration = 0

const selectedItem = computed<FunctionalItem | null>(() =>
  functionalItems.value.find((item) => item.functional_requirement_id === selectedId.value) ?? null,
)

const selectedState = computed<VerificationStateRow | null>(() =>
  verificationStates.value[selectedId.value] ?? null,
)

const selectedEvents = computed<LifecycleEvent[]>(() => {
  const rid = selectedId.value
  if (!rid) return []
  return lifecycleEvents.value
    .filter((event) => event.requirement_id === rid)
    .slice()
    .sort((a, b) => String(a.timestamp || "").localeCompare(String(b.timestamp || "")))
})

const selectedCandidates = computed<DependencyCandidate[]>(() => {
  const rid = selectedId.value
  if (!rid) return []
  return dependencyCandidates.value.filter((candidate) => candidate.from === rid || candidate.to === rid)
})

const rollbackTargets = computed<LifecycleState[]>(() => {
  const current = selectedState.value?.lifecycle_state ?? "draft"
  const currentRank = LIFECYCLE_ORDER.indexOf(current)
  return LIFECYCLE_ORDER.filter((_, index) => index < currentRank)
})

function lifecycleTone(state: LifecycleState | undefined): string {
  switch (state) {
    case "verified": return "tone-verified"
    case "implemented": return "tone-implemented"
    case "confirmed": return "tone-confirmed"
    default: return "tone-draft"
  }
}

function defaultVerification(): VerificationSubobject {
  const empty = (): VerificationTriple => ({ confirmed: false, by: "", at: "" })
  return {
    project_manager_confirm: empty(),
    test_lead_confirm: empty(),
    dev_test_confirm: empty(),
    implemented: "not_started",
    test_case_ids: [],
    test_completed: false,
  }
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry ?? "").trim()).filter(Boolean)
  }
  if (value === null || value === undefined) return []
  const text = String(value).trim()
  return text ? [text] : []
}

function readField(row: BackendRequirement, key: string): string {
  const value = row ? row[key] : undefined
  if (value === null || value === undefined) return ""
  return String(value)
}

function confirmSummary(triple: VerificationTriple | undefined): string {
  if (!triple || !triple.confirmed) return ""
  const person = String(triple.by || "").trim() || "已确认"
  const at = String(triple.at || "").trim()
  return at ? `${person} · ${at}` : person
}

function isManualItem(item: FunctionalItem): boolean {
  return item._origin === "manual" || item.source_kind === "manual"
}

function hasNoDocSource(item: FunctionalItem): boolean {
  return isManualItem(item) || !String(item.source_quote || "").trim()
}

function lifecycleLabelOf(state: string | undefined): string {
  return (state && LIFECYCLE_LABELS[state as LifecycleState]) || state || ""
}

function atomicId(row: BackendRequirement, idx: number): string {
  return readField(row, "stable_req_id") || readField(row, "requirement_id") || readField(row, "id") || `row-${idx}`
}

function atomicText(row: BackendRequirement): string {
  return readField(row, "chinese_text")
    || readField(row, "original_text")
    || readField(row, "requirement")
    || readField(row, "object")
    || readField(row, "text")
    || ""
}

function atomicStatus(row: BackendRequirement): string {
  return readField(row, "status") || readField(row, "decision") || "draft"
}

function coerceFunctionalItem(raw: unknown, origin: "functional" | "manual"): FunctionalItem | null {
  if (!raw || typeof raw !== "object") return null
  const record = raw as Record<string, unknown>
  const id = String(record.functional_requirement_id || "").trim()
  if (!id) return null
  return {
    functional_requirement_id: id,
    objective: String(record.objective || "").trim() || undefined,
    title: String(record.title || "").trim() || undefined,
    behaviors: asStringList(record.behaviors),
    preconditions: asStringList(record.preconditions),
    data_constraints: asStringList(record.data_constraints),
    variants: asStringList(record.variants),
    exceptions: asStringList(record.exceptions),
    related_dlms_objects: asStringList(record.related_dlms_objects),
    description: String(record.description || "").trim() || undefined,
    module: String(record.module || "").trim() || undefined,
    priority: String(record.priority || "").trim() || undefined,
    source_section: String(record.source_section || "").trim() || undefined,
    source_quote: String(record.source_quote || "").trim() || undefined,
    source_block_ids: asStringList(record.source_block_ids),
    drilled_subatoms: Array.isArray(record.drilled_subatoms) ? (record.drilled_subatoms as Subatom[]) : undefined,
    drilldown_signals: asStringList(record.drilldown_signals),
    conflict_flags: asStringList(record.conflict_flags),
    source_kind: String(record.source_kind || "").trim() || undefined,
    manual_actor: String(record.manual_actor || "").trim() || undefined,
    notes: String(record.notes || "").trim() || undefined,
    ownership_override: String(record.ownership_override || "").trim() || undefined,
    _origin: origin,
  }
}

async function readArtifact(category: "pipeline" | "state", filename: string): Promise<ArtifactRead> {
  if (!props.outputDir || !window.ratomizerDesktop?.readArtifact) {
    return { ok: false, missing: true, reason: "no_bridge" }
  }
  try {
    return await window.ratomizerDesktop.readArtifact({ outDir: props.outputDir, category, filename })
  } catch (err) {
    return { ok: false, missing: false, reason: "bridge_error", detail: String((err && (err as Error).message) || err) }
  }
}

function indexVerificationStates(payload: VerificationStatesPayload | null): Record<string, VerificationStateRow> {
  const index: Record<string, VerificationStateRow> = {}
  if (!payload || !Array.isArray(payload.states)) return index
  for (const row of payload.states) {
    if (row && row.requirement_id) index[row.requirement_id] = row
  }
  return index
}

function describeError(err: unknown, fallback: string): string {
  if (err instanceof RequirementApiError) {
    return `${fallback}：${err.details.detail || err.details.error || err.message}`
  }
  return err instanceof Error ? `${fallback}：${err.message}` : fallback
}

// HTTP 优先、IPC 兜底：旧后端无对应 GET 端点（404）或无后端进程（网络错误）时降级到
// Electron readArtifact 直读 governed 产物文件，界面不崩。其他 HTTP 错误（400/409/5xx）
// 不降级——如实透出，避免把真实故障伪装成“无数据”。
function shouldFallBackToIpc(err: unknown): boolean {
  if (err instanceof RequirementApiError) return err.status === 404
  // 非 RequirementApiError = fetch 层抛出（TypeError 网络错误 / 后端未起）
  return err instanceof Error
}

// 功能需求条目：HTTP /functional-requirements 优先，降级 readArtifact(pipeline)
async function loadFunctionalItems(client: FunctionalClient): Promise<{ items: FunctionalItem[]; error?: string }> {
  try {
    const payload: FunctionalRequirementsPayload = await client.loadFunctionalRequirements()
    return { items: coerceItems(payload.items || [], "functional") }
  } catch (err) {
    if (!shouldFallBackToIpc(err)) return { items: [], error: describeError(err, "功能需求读取失败") }
    const read = await readArtifact("pipeline", "functional_requirements.json")
    if (read.ok && read.content) {
      const payload = read.content as { items?: unknown[] }
      return { items: coerceItems(Array.isArray(payload.items) ? payload.items : [], "functional") }
    }
    return { items: [], error: undefined }  // 文件确实不存在≠错误（如实空列表）
  }
}

// 手工需求条目：HTTP /manual-requirements 优先，降级 readArtifact(state)
async function loadManualItems(client: FunctionalClient): Promise<{ items: FunctionalItem[]; error?: string }> {
  try {
    const payload: ManualRequirementsPayload = await client.loadManualRequirements()
    return { items: coerceItems(payload.items || [], "manual") }
  } catch (err) {
    if (!shouldFallBackToIpc(err)) return { items: [], error: describeError(err, "手工需求读取失败") }
    const read = await readArtifact("state", "manual_requirements.jsonl")
    if (read.ok && Array.isArray(read.content)) {
      return { items: coerceItems(read.content, "manual") }
    }
    return { items: [], error: undefined }
  }
}

// 生命周期事件：HTTP /lifecycle-events 优先，降级 readArtifact(state)
async function loadLifecycleEventList(client: FunctionalClient): Promise<{ events: LifecycleEvent[]; error?: string }> {
  try {
    const payload: LifecycleEventsPayload = await client.loadLifecycleEvents()
    return { events: (payload.events || []) as LifecycleEvent[] }
  } catch (err) {
    if (!shouldFallBackToIpc(err)) return { events: [], error: describeError(err, "生命周期事件读取失败") }
    const read = await readArtifact("state", "requirement_lifecycle_events.jsonl")
    if (read.ok && Array.isArray(read.content)) {
      return { events: read.content as LifecycleEvent[] }
    }
    return { events: [], error: undefined }
  }
}

function coerceItems(raws: unknown[], origin: "functional" | "manual"): FunctionalItem[] {
  const items: FunctionalItem[] = []
  for (const raw of raws) {
    const item = coerceFunctionalItem(raw, origin)
    if (item) items.push(item)
  }
  return items
}

async function loadAll() {
  const generation = ++loadGeneration
  apiMessage.value = ""
  if (!props.active || !props.outputDir) return
  const client = props.client
  if (!client) {
    apiMessage.value = "未连接当前输出目录的审查会话"
    return
  }
  loading.value = true
  try {
    const [functionalResult, manualResult, statesResult, candidatesResult, eventsResult] = await Promise.all([
      loadFunctionalItems(client),
      loadManualItems(client),
      client.loadVerificationStates().catch((err: unknown) => err),
      client.loadDependencyCandidates().catch((err: unknown) => err),
      loadLifecycleEventList(client),
    ])
    if (generation !== loadGeneration) return

    const items: FunctionalItem[] = [...functionalResult.items, ...manualResult.items]

    if (statesResult instanceof Error) {
      apiMessage.value = describeError(statesResult, "验证状态读取失败")
      verificationStates.value = {}
    } else {
      verificationStates.value = indexVerificationStates(statesResult as VerificationStatesPayload | null)
    }

    // verification_states（reviewer_override 通道）可能携带需求库采纳留痕的 ownership/module
    // override——回叠到条目，使采纳后的归属/模块在重载后仍可见。
    for (const item of items) {
      const state = verificationStates.value[item.functional_requirement_id]
      if (!state) continue
      const ownership = String(state.ownership_override || "").trim()
      if (ownership) item.ownership_override = ownership
    }

    functionalItems.value = items

    if (functionalResult.error) apiMessage.value = functionalResult.error
    if (manualResult.error && !apiMessage.value) apiMessage.value = manualResult.error

    if (candidatesResult instanceof Error) {
      dependencyCandidates.value = []
      if (!apiMessage.value) apiMessage.value = describeError(candidatesResult, "依赖候选读取失败")
    } else {
      const candidatesPayload = candidatesResult as DependencyCandidatesPayload | null
      dependencyCandidates.value = candidatesPayload && Array.isArray(candidatesPayload.candidates)
        ? candidatesPayload.candidates
        : []
    }

    lifecycleEvents.value = eventsResult.events
    if (eventsResult.error && !apiMessage.value) apiMessage.value = eventsResult.error

    if (items.length && !items.some((item) => item.functional_requirement_id === selectedId.value)) {
      selectedId.value = items[0].functional_requirement_id
    } else if (!items.length) {
      selectedId.value = ""
    }
    syncVerificationEdit()
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function ensureAtomicLoaded() {
  if (atomicRequirements.value.length || !props.client?.loadRequirements) return
  const generation = ++loadGeneration
  try {
    const rows = await props.client.loadRequirements()
    if (generation !== loadGeneration) return
    atomicRequirements.value = Array.isArray(rows) ? rows : []
  } catch (err) {
    if (generation !== loadGeneration) return
    apiMessage.value = describeError(err, "原子需求读取失败")
  }
}

function normalizeEditFrom(source: Partial<VerificationSubobject> | undefined): VerificationSubobject {
  const base = defaultVerification()
  if (!source) return base
  // 防御：verification 文件从盘读取，可能被手改为缺字段——补齐默认，避免模板访问 .confirmed 崩
  return {
    project_manager_confirm: source.project_manager_confirm ?? base.project_manager_confirm,
    test_lead_confirm: source.test_lead_confirm ?? base.test_lead_confirm,
    dev_test_confirm: source.dev_test_confirm ?? base.dev_test_confirm,
    implemented: source.implemented ?? base.implemented,
    test_case_ids: Array.isArray(source.test_case_ids) ? [...source.test_case_ids] : [],
    test_completed: source.test_completed ?? base.test_completed,
  }
}

function syncVerificationEdit() {
  const state = selectedState.value
  if (!state) {
    hasVerification.value = false
    verificationEdit.value = defaultVerification()
    return
  }
  hasVerification.value = true
  verificationEdit.value = normalizeEditFrom(state.verification)
}

watch(selectedId, () => {
  syncVerificationEdit()
  rollbackOpen.value = false
})

watch(() => [props.active, props.outputDir] as const, () => {
  if (props.active && props.outputDir) void loadAll()
}, { immediate: true })

watch(() => props.refreshToken, () => {
  if (props.active) void loadAll()
})

watch(mode, (next) => {
  if (next === "atomic") void ensureAtomicLoaded()
})

function focusBlock(blockId: string) {
  if (!blockId) return
  emit("focus-block", blockId)
}

function toggleConfirm(roleKey: "project_manager_confirm" | "test_lead_confirm" | "dev_test_confirm", checked: boolean) {
  verificationEdit.value[roleKey].confirmed = checked
}

function setTestCaseIds(text: string) {
  verificationEdit.value.test_case_ids = text
    .split(/[\n,，;；]/)
    .map((entry) => entry.trim())
    .filter(Boolean)
}

async function saveVerification() {
  const client = props.client
  const item = selectedItem.value
  if (!client || !item || verificationSaving.value) return
  const generation = ++opGeneration
  verificationSaving.value = true
  apiMessage.value = ""
  try {
    const state = selectedState.value
    const payload: VerificationActionPayload = await client.applyVerificationAction({
      requirementId: item.functional_requirement_id,
      verification: JSON.parse(JSON.stringify(verificationEdit.value)) as VerificationSubobject,
      // CAS opt-in：有既有 evidence_fingerprint 才发 expected（首次回写省略 → 后端跳过校验）
      expectedEvidenceFingerprint: state?.evidence_fingerprint,
    })
    if (generation !== opGeneration) return
    verificationStates.value = {
      ...verificationStates.value,
      [item.functional_requirement_id]: {
        ...(verificationStates.value[item.functional_requirement_id]
          || { requirement_id: item.functional_requirement_id, evidence_fingerprint: "", schema: "verification-state/v1" }),
        requirement_id: item.functional_requirement_id,
        verification: payload.verification,
        lifecycle_state: payload.lifecycle_state,
        // S1-6：用响应回传的最新指纹同步本地行——否则下次保存必携旧（空）指纹触发假 409。
        // 后端回传指纹时直接采用；旧后端不回传（undefined）时保留本地既有指纹，不回退已持有的真实值。
        evidence_fingerprint: payload.evidence_fingerprint
          ?? verificationStates.value[item.functional_requirement_id]?.evidence_fingerprint
          ?? "",
      },
    }
    syncVerificationEdit()
    apiMessage.value = `已保存验证状态，生命周期：${LIFECYCLE_LABELS[payload.lifecycle_state]}`
  } catch (err) {
    if (generation !== opGeneration) return
    if (isNeedsReconfirmationError(err) && client === props.client) {
      await refreshVerificationStates()
      apiMessage.value = "需求内容已变化（证据指纹失配），已刷新验证状态，请重新核对后再保存"
    } else {
      apiMessage.value = describeError(err, "验证保存失败")
    }
  } finally {
    if (generation === opGeneration) verificationSaving.value = false
  }
}

async function refreshVerificationStates() {
  if (!props.client) return
  try {
    const states = await props.client.loadVerificationStates()
    verificationStates.value = indexVerificationStates(states)
    syncVerificationEdit()
  } catch (err) {
    apiMessage.value = describeError(err, "验证状态刷新失败")
  }
}

function openRollback() {
  rollbackTarget.value = rollbackTargets.value[rollbackTargets.value.length - 1] ?? "draft"
  rollbackActor.value = ""
  rollbackReason.value = ""
  rollbackOpen.value = true
}

async function submitRollback() {
  const client = props.client
  const item = selectedItem.value
  if (!client || !item || rollbackSubmitting.value) return
  if (!rollbackActor.value.trim() || !rollbackReason.value.trim()) {
    apiMessage.value = "回退需填写操作者与原因（append-only 事件流留痕）"
    return
  }
  const generation = ++opGeneration
  rollbackSubmitting.value = true
  apiMessage.value = ""
  try {
    const target = rollbackTarget.value
    await client.rollbackRequirement({
      requirementId: item.functional_requirement_id,
      target,
      actor: rollbackActor.value.trim(),
      reason: rollbackReason.value.trim(),
    })
    if (generation !== opGeneration) return
    rollbackOpen.value = false
    await Promise.all([refreshVerificationStates(), loadLifecycleEvents()])
    apiMessage.value = `已回退至 ${LIFECYCLE_LABELS[target]}（已记入 append-only 事件流，不可抹除）`
  } catch (err) {
    if (generation !== opGeneration) return
    apiMessage.value = describeError(err, "回退失败")
  } finally {
    if (generation === opGeneration) rollbackSubmitting.value = false
  }
}

async function loadLifecycleEvents() {
  const client = props.client
  if (!client) return
  const result = await loadLifecycleEventList(client)
  lifecycleEvents.value = result.events
}

function openManual() {
  manualForm.value = { objective: "", behaviorsText: "", module: "", ownership: "", priority: "P1", notes: "" }
  manualOpen.value = true
}

async function submitManual() {
  const client = props.client
  if (!client || manualSubmitting.value) return
  const objective = manualForm.value.objective.trim()
  if (!objective) {
    apiMessage.value = "目标（objective）必填"
    return
  }
  const generation = ++opGeneration
  manualSubmitting.value = true
  apiMessage.value = ""
  try {
    const payload: ManualRequirementPayload = await client.createManualRequirement({
      objective,
      behaviors: manualForm.value.behaviorsText
        .split(/[\n,，;；]/)
        .map((entry) => entry.trim())
        .filter(Boolean),
      module: manualForm.value.module.trim(),
      ownership: manualForm.value.ownership.trim(),
      priority: manualForm.value.priority.trim() || "P1",
      notes: manualForm.value.notes.trim(),
    })
    if (generation !== opGeneration) return
    manualOpen.value = false
    apiMessage.value = `已新建手工需求 ${payload.functional_requirement_id}（无文档来源，追溯列留空）`
    await loadManualRequirements()
    selectedId.value = payload.functional_requirement_id
  } catch (err) {
    if (generation !== opGeneration) return
    apiMessage.value = describeError(err, "手工建需求失败")
  } finally {
    if (generation === opGeneration) manualSubmitting.value = false
  }
}

async function loadManualRequirements() {
  const client = props.client
  if (!client) return
  const result = await loadManualItems(client)
  const byId = new Map<string, FunctionalItem>()
  for (const item of functionalItems.value) byId.set(item.functional_requirement_id, item)
  for (const item of result.items) byId.set(item.functional_requirement_id, item)
  functionalItems.value = Array.from(byId.values())
}

async function runLibrarySearch() {
  const client = props.client
  const item = selectedItem.value
  if (!client || !item) return
  const query = [item.objective || item.title || "", ...(item.behaviors || [])].join(" ").trim()
  if (!query) {
    libraryResults.value = []
    libraryNote.value = "当前条目无可用于检索的文本"
    return
  }
  const generation = ++opGeneration
  libraryLoading.value = true
  libraryNote.value = ""
  try {
    const payload: RequirementLibrarySearchPayload = await client.searchRequirementLibrary({ query, limit: 10 })
    if (generation !== opGeneration) return
    libraryResults.value = Array.isArray(payload.results) ? payload.results : []
    // 后端在未配置 RATOMIZER_REQUIREMENT_LIBRARY 时返回 200 + note（非错误，必须如实展示）
    libraryNote.value = payload.note || (libraryResults.value.length ? "" : "未命中相似历史需求")
  } catch (err) {
    if (generation !== opGeneration) return
    libraryResults.value = []
    libraryNote.value = describeError(err, "检索失败")
  } finally {
    if (generation === opGeneration) libraryLoading.value = false
  }
}

function adoptLibraryEntry(entry: RequirementLibraryEntry) {
  const item = selectedItem.value
  if (!item) return
  // 打开确认对话框：actor/reason 必填——后端经既有 reviewer_override 通道（verification_states）
  // 留痕，不新造写路径。历史归属/模块作为初值预览，提交后才落库。
  adoptTarget.value = entry
  adoptActor.value = ""
  adoptReason.value = ""
  adoptOpen.value = true
}

async function submitAdopt() {
  const client = props.client
  const item = selectedItem.value
  const entry = adoptTarget.value
  if (!client || !item || !entry || adoptSubmitting.value) return
  if (!adoptActor.value.trim() || !adoptReason.value.trim()) {
    apiMessage.value = "采纳需填写操作者与原因（经 reviewer_override 通道留痕）"
    return
  }
  const generation = ++opGeneration
  adoptSubmitting.value = true
  apiMessage.value = ""
  try {
    const ownership = String(entry.ownership || "").trim()
    const moduleText = String(entry.module || "").trim()
    const payload: RequirementLibraryAdoptPayload = await client.adoptRequirementLibrary({
      functionalRequirementId: item.functional_requirement_id,
      ownership,
      module: moduleText,
      actor: adoptActor.value.trim(),
      reason: adoptReason.value.trim(),
    })
    if (generation !== opGeneration) return
    // 回叠到当前条目（与 loadAll 的回叠口径一致）
    const persistedOwnership = String(payload.ownership_override || "").trim()
    if (persistedOwnership) item.ownership_override = persistedOwnership
    adoptOpen.value = false
    apiMessage.value = `已采纳历史条目${persistedOwnership ? `（归属：${persistedOwnership}）` : ""}${payload.module_override ? `（模块：${payload.module_override}）` : ""}——已写入 reviewer_override 通道（verification_states）`
    // 刷新验证状态，使留痕字段在状态行同步可见
    await refreshVerificationStates()
  } catch (err) {
    if (generation !== opGeneration) return
    apiMessage.value = describeError(err, "采纳失败")
  } finally {
    if (generation === opGeneration) adoptSubmitting.value = false
  }
}

function ignoreLibraryEntry(entry: RequirementLibraryEntry) {
  // 忽略仅本地移除该参考项，不落库、不调后端
  libraryResults.value = libraryResults.value.filter((row) => row !== entry)
}

async function decideCandidate(candidate: DependencyCandidate, accept: boolean) {
  const client = props.client
  if (!client) return
  const generation = ++opGeneration
  apiMessage.value = ""
  try {
    const result: DependencyDecisionPayload = await client.decideDependency({
      from: candidate.from,
      to: candidate.to,
      kind: candidate.kind,
      accept,
    })
    if (generation !== opGeneration) return
    if (accept && result.written) {
      const target = dependencyCandidates.value.find((row) =>
        row.from === candidate.from && row.to === candidate.to && row.kind === candidate.kind)
      if (target) target.status = "accepted"
      dependencyCandidates.value = [...dependencyCandidates.value]
      apiMessage.value = `已接受候选（${candidate.from} → ${candidate.to}），已写入 dependency_decisions`
    } else {
      apiMessage.value = `已忽略候选（${candidate.from} → ${candidate.to}）——未落库`
    }
  } catch (err) {
    if (generation !== opGeneration) return
    apiMessage.value = describeError(err, "依赖裁决失败")
  }
}

function toggleChildren(itemId: string) {
  const next = new Set(expandedChildren.value)
  if (next.has(itemId)) next.delete(itemId)
  else next.add(itemId)
  expandedChildren.value = next
}
</script>

<template>
  <section class="functional-review" data-testid="functional-review">
    <header class="fr-header">
      <div class="fr-title-area">
        <h2 class="fr-title">功能需求评审</h2>
        <p class="fr-subtitle">评审对象以功能需求级条目呈现；原子级下钻为子级，旧原子视图可切换保留</p>
      </div>
      <div class="fr-actions">
        <div class="mode-toggle" role="tablist" aria-label="评审视图模式">
          <button
            type="button"
            role="tab"
            :class="['mode-btn', { active: mode === 'functional' }]"
            data-testid="mode-functional"
            @click="mode = 'functional'"
          >功能需求</button>
          <button
            type="button"
            role="tab"
            :class="['mode-btn', { active: mode === 'atomic' }]"
            data-testid="mode-atomic"
            @click="mode = 'atomic'"
          >原子级</button>
        </div>
        <button class="fr-button" type="button" :disabled="!client || loading" data-testid="fr-refresh" @click="loadAll">
          <RefreshCw :size="14" aria-hidden="true" />刷新
        </button>
        <button class="fr-button primary" type="button" :disabled="!client" data-testid="fr-new-manual" @click="openManual">
          <Plus :size="14" aria-hidden="true" />新建条目
        </button>
      </div>
    </header>

    <div v-if="apiMessage" class="fr-message" data-testid="fr-message">{{ apiMessage }}</div>

    <!-- 功能需求级视图 -->
    <div v-if="mode === 'functional'" class="fr-split">
      <div class="fr-list" data-testid="functional-list">
        <div v-if="!functionalItems.length && !loading" class="fr-empty" data-testid="functional-empty">
          当前输出目录暂无功能需求条目。请先在「运行」页执行功能合成（functional-synthesis），或通过「新建条目」手工录入。
        </div>
        <button
          v-for="item in functionalItems"
          :key="item.functional_requirement_id"
          type="button"
          :class="['fr-card', { selected: item.functional_requirement_id === selectedId }]"
          :data-testid="`functional-card-${item.functional_requirement_id}`"
          @click="selectedId = item.functional_requirement_id"
        >
          <div class="fr-card-head">
            <span class="fr-card-id">{{ item.functional_requirement_id }}</span>
            <span
              v-if="verificationStates[item.functional_requirement_id]?.lifecycle_state"
              :class="['lifecycle-badge', lifecycleTone(verificationStates[item.functional_requirement_id].lifecycle_state)]"
              :data-testid="`lifecycle-${item.functional_requirement_id}`"
            >{{ lifecycleLabelOf(verificationStates[item.functional_requirement_id].lifecycle_state) }}</span>
            <span v-if="hasNoDocSource(item)" class="origin-badge manual" data-testid="manual-badge">无文档来源</span>
            <span v-if="item.conflict_flags?.length" class="origin-badge conflict">冲突 {{ item.conflict_flags.length }}</span>
          </div>
          <div class="fr-card-objective">{{ item.objective || item.title || "（未填写目标）" }}</div>
          <div class="fr-card-meta">
            <span v-if="item.module" class="meta-chip">{{ item.module }}</span>
            <span v-if="item.priority" class="meta-chip">{{ item.priority }}</span>
            <span v-if="item.drilled_subatoms?.length" class="meta-chip">下钻 {{ item.drilled_subatoms.length }}</span>
          </div>
        </button>
      </div>

      <aside class="fr-detail" data-testid="functional-detail">
        <div v-if="!selectedItem" class="fr-empty">选择左侧功能需求查看详情</div>
        <template v-else>
          <header class="detail-head">
            <div>
              <h3 class="detail-id">{{ selectedItem.functional_requirement_id }}</h3>
              <p class="detail-objective">{{ selectedItem.objective || selectedItem.title || "（未填写目标）" }}</p>
            </div>
            <span
              v-if="selectedState?.lifecycle_state"
              :class="['lifecycle-badge', lifecycleTone(selectedState.lifecycle_state)]"
            >{{ lifecycleLabelOf(selectedState.lifecycle_state) }}</span>
          </header>

          <!-- 功能字段 -->
          <section class="detail-block">
            <h4 class="block-title">功能描述</h4>
            <div v-if="selectedItem.behaviors?.length" class="field">
              <span class="field-label">行为</span>
              <ul class="field-list"><li v-for="(line, idx) in selectedItem.behaviors" :key="`b-${idx}`">{{ line }}</li></ul>
            </div>
            <div v-if="selectedItem.preconditions?.length" class="field">
              <span class="field-label">前置条件</span>
              <ul class="field-list"><li v-for="(line, idx) in selectedItem.preconditions" :key="`p-${idx}`">{{ line }}</li></ul>
            </div>
            <div v-if="selectedItem.data_constraints?.length" class="field">
              <span class="field-label">数据约束</span>
              <ul class="field-list"><li v-for="(line, idx) in selectedItem.data_constraints" :key="`d-${idx}`">{{ line }}</li></ul>
            </div>
            <div v-if="selectedItem.variants?.length" class="field">
              <span class="field-label">变体</span>
              <ul class="field-list"><li v-for="(line, idx) in selectedItem.variants" :key="`v-${idx}`">{{ line }}</li></ul>
            </div>
            <div v-if="selectedItem.exceptions?.length" class="field">
              <span class="field-label">异常</span>
              <ul class="field-list"><li v-for="(line, idx) in selectedItem.exceptions" :key="`e-${idx}`">{{ line }}</li></ul>
            </div>
            <div v-if="selectedItem.related_dlms_objects?.length" class="field">
              <span class="field-label">关联 DLMS 对象</span>
              <ul class="field-list"><li v-for="(line, idx) in selectedItem.related_dlms_objects" :key="`r-${idx}`">{{ line }}</li></ul>
            </div>
          </section>

          <!-- 三级追溯链 -->
          <section class="detail-block">
            <h4 class="block-title">追溯链</h4>
            <div v-if="hasNoDocSource(selectedItem)" class="no-source" data-testid="no-doc-source">
              无文档来源（手工录入或来源缺失）——追溯列以空明示，不伪引原文。
            </div>
            <template v-else>
              <div v-if="selectedItem.source_quote" class="field">
                <span class="field-label">原文引句</span>
                <blockquote class="source-quote">{{ selectedItem.source_quote }}</blockquote>
              </div>
              <div v-if="selectedItem.source_section" class="field">
                <span class="field-label">章节</span>
                <span class="meta-chip">{{ selectedItem.source_section }}</span>
              </div>
              <div v-if="selectedItem.source_block_ids?.length" class="field">
                <span class="field-label">来源块（点击跳转文档批注）</span>
                <div class="block-chips">
                  <button
                    v-for="blockId in selectedItem.source_block_ids"
                    :key="blockId"
                    type="button"
                    class="block-chip"
                    :data-testid="`block-chip-${blockId}`"
                    @click="focusBlock(blockId)"
                  >{{ blockId }}</button>
                </div>
              </div>
            </template>
          </section>

          <!-- 原子级下钻子条目（parent/children） -->
          <section v-if="selectedItem.drilled_subatoms?.length" class="detail-block">
            <button type="button" class="collapse-toggle" data-testid="toggle-children" @click="toggleChildren(selectedItem.functional_requirement_id)">
              <component :is="expandedChildren.has(selectedItem.functional_requirement_id) ? ChevronDown : ChevronRight" :size="14" aria-hidden="true" />
              原子级下钻（{{ selectedItem.drilled_subatoms.length }} 条子原子）
              <span v-if="selectedItem.drilldown_signals?.length" class="signal-hint">信号：{{ selectedItem.drilldown_signals.join("、") }}</span>
            </button>
            <ul v-if="expandedChildren.has(selectedItem.functional_requirement_id)" class="subatom-list" data-testid="subatom-list">
              <li v-for="(sub, idx) in selectedItem.drilled_subatoms" :key="`sub-${idx}`" class="subatom-item">
                <div class="subatom-text">{{ sub.text || sub.source_quote }}</div>
                <div v-if="sub.source_block_ids?.length" class="block-chips">
                  <button
                    v-for="blockId in sub.source_block_ids"
                    :key="`sub-${idx}-${blockId}`"
                    type="button"
                    class="block-chip small"
                    @click="focusBlock(blockId)"
                  >{{ blockId }}</button>
                </div>
              </li>
            </ul>
          </section>

          <!-- verification 六列编辑（Cap2） -->
          <section class="detail-block" data-testid="verification-editor">
            <h4 class="block-title">验证六列 / 状态机</h4>
            <div v-if="!hasVerification" class="field-hint">该条目尚无既有验证状态——填写下方字段并保存即可初始化。</div>
            <div class="confirm-grid">
              <label
                v-for="role in CONFIRM_ROLES"
                :key="role.key"
                class="confirm-cell"
                :data-testid="`confirm-${role.key}`"
              >
                <input
                  type="checkbox"
                  :checked="verificationEdit[role.key].confirmed"
                  @change="toggleConfirm(role.key, ($event.target as HTMLInputElement).checked)"
                />
                <div class="confirm-meta">
                  <span class="confirm-label">{{ role.label }}</span>
                  <span class="confirm-stamp">{{ confirmSummary(verificationEdit[role.key]) }}</span>
                </div>
              </label>
            </div>
            <div class="form-row">
              <label class="form-field">
                <span class="field-label">功能是否实现</span>
                <select v-model="verificationEdit.implemented" data-testid="select-implemented">
                  <option value="not_started">未开始</option>
                  <option value="in_progress">进行中</option>
                  <option value="done">已完成</option>
                </select>
              </label>
              <label class="form-field">
                <span class="field-label">测试是否完成</span>
                <input
                  type="checkbox"
                  :checked="verificationEdit.test_completed"
                  data-testid="check-test-completed"
                  @change="verificationEdit.test_completed = ($event.target as HTMLInputElement).checked"
                />
              </label>
            </div>
            <label class="form-field wide">
              <span class="field-label">测试用例号（分号/逗号分隔）</span>
              <input
                type="text"
                :value="verificationEdit.test_case_ids.join('; ')"
                data-testid="input-test-case-ids"
                @input="setTestCaseIds(($event.target as HTMLInputElement).value)"
              />
            </label>
            <div class="inline-actions">
              <button
                class="fr-button primary"
                type="button"
                :disabled="verificationSaving"
                data-testid="save-verification"
                @click="saveVerification"
              ><Check :size="14" aria-hidden="true" />保存验证</button>
              <button
                v-if="rollbackTargets.length"
                class="fr-button warn"
                type="button"
                data-testid="open-rollback"
                @click="openRollback"
              ><RotateCcw :size="14" aria-hidden="true" />回退状态</button>
              <span v-if="selectedState?.timestamp" class="stamp-hint">最后改动：{{ selectedState.actor || "—" }} · {{ selectedState.timestamp }}</span>
            </div>
          </section>

          <!-- append-only 事件时间线（Cap2） -->
          <section v-if="selectedEvents.length" class="detail-block" data-testid="lifecycle-timeline">
            <h4 class="block-title">事件时间线（append-only，不可抹除）</h4>
            <ol class="timeline">
              <li v-for="(event, idx) in selectedEvents" :key="`evt-${idx}`" class="timeline-item">
                <span class="timeline-kind">{{ event.kind === "rollback" ? "回退" : event.kind }}</span>
                <span class="timeline-transition">{{ lifecycleLabelOf(event.from_state) }} → {{ lifecycleLabelOf(event.to_state) }}</span>
                <span class="timeline-actor">{{ event.actor || "—" }}</span>
                <span v-if="event.reason" class="timeline-reason">{{ event.reason }}</span>
                <span class="timeline-time">{{ event.timestamp }}</span>
              </li>
            </ol>
          </section>

          <!-- 依赖候选接受/拒绝（Cap4） -->
          <section v-if="selectedCandidates.length" class="detail-block" data-testid="dependency-candidates">
            <h4 class="block-title">依赖候选（{{ selectedCandidates.length }}）</h4>
            <ul class="candidate-list">
              <li v-for="(candidate, idx) in selectedCandidates" :key="`cand-${idx}`" class="candidate-item">
                <div class="candidate-meta">
                  <span :class="['kind-tag', `kind-${candidate.kind}`]">{{ candidate.kind }}</span>
                  <span class="candidate-pair">{{ candidate.from }} ↔ {{ candidate.to }}</span>
                  <span class="candidate-signal">{{ candidate.signal }}<template v-if="candidate.evidence?.length"> · {{ candidate.evidence.slice(0, 3).join(", ") }}</template></span>
                  <span v-if="candidate.status === 'accepted'" class="status-accepted">已接受</span>
                </div>
                <div v-if="candidate.status !== 'accepted'" class="candidate-actions">
                  <button class="fr-button small primary" type="button" :data-testid="`accept-candidate-${idx}`" @click="decideCandidate(candidate, true)">接受</button>
                  <button class="fr-button small" type="button" :data-testid="`reject-candidate-${idx}`" @click="decideCandidate(candidate, false)">忽略</button>
                </div>
              </li>
            </ul>
          </section>

          <!-- 需求库相似历史参考（Cap4） -->
          <section class="detail-block" data-testid="library-panel">
            <div class="block-head-row">
              <h4 class="block-title">相似历史需求</h4>
              <button class="fr-button small" type="button" :disabled="libraryLoading || !client" data-testid="run-library-search" @click="runLibrarySearch">
                <Search :size="13" aria-hidden="true" />检索
              </button>
            </div>
            <p v-if="libraryNote" class="field-hint">{{ libraryNote }}</p>
            <ul v-if="libraryResults.length" class="library-list">
              <li v-for="(entry, idx) in libraryResults" :key="`lib-${idx}`" class="library-item">
                <div class="library-head">
                  <span class="library-score">相似度 {{ ((entry.overlap_score || 0) * 100).toFixed(0) }}%</span>
                  <span v-if="entry.ownership_corrected" class="corrected-tag">归属已修正</span>
                  <span v-if="entry.project" class="library-project">{{ entry.project }}</span>
                </div>
                <div class="library-objective">{{ entry.objective || entry.title }}</div>
                <div v-if="entry.behaviors?.length" class="library-behaviors">{{ entry.behaviors.join("；") }}</div>
                <div class="candidate-actions">
                  <button class="fr-button small primary" type="button" :data-testid="`adopt-library-${idx}`" @click="adoptLibraryEntry(entry)">采纳</button>
                  <button class="fr-button small" type="button" :data-testid="`ignore-library-${idx}`" @click="ignoreLibraryEntry(entry)">忽略</button>
                </div>
              </li>
            </ul>
          </section>
        </template>
      </aside>
    </div>

    <!-- 原子级视图（旧原子视图保留为可切换模式） -->
    <div v-else class="fr-atomic" data-testid="atomic-view">
      <p class="field-hint">
        原子级视图（旧评审粒度，只读概览）。完整的原子裁决面仍保留在「审查工作台」入口。
      </p>
      <div v-if="!atomicRequirements.length" class="fr-empty">暂无原子需求</div>
      <table v-else class="atomic-table">
        <thead>
          <tr>
            <th>编号</th>
            <th>模块</th>
            <th>需求</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, idx) in atomicRequirements" :key="atomicId(row, idx)">
            <td>{{ atomicId(row, idx) }}</td>
            <td>{{ readField(row, 'module') || '未分模块' }}</td>
            <td>{{ atomicText(row) }}</td>
            <td>{{ atomicStatus(row) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 手工建需求表单（Cap3） -->
    <Transition name="sheet">
      <div v-if="manualOpen" class="manual-overlay" data-testid="manual-form" role="dialog" aria-modal="true" aria-label="新建手工需求" @click.self="manualOpen = false">
        <section class="manual-dialog">
          <header class="manual-head">
            <div>
              <div class="manual-title">新建功能需求（手工录入）</div>
              <div class="manual-subtitle">provenance=manual · 无文档来源 · 追溯列留空不伪引 · 走完全相同下游</div>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="manualOpen = false"><X :size="18" aria-hidden="true" /></button>
          </header>
          <div class="manual-body">
            <label class="form-field wide">
              <span class="field-label">目标（objective）<em class="req">*</em></span>
              <textarea v-model="manualForm.objective" rows="2" data-testid="manual-objective" placeholder="该需求存在的业务/技术目的，以「系统/表具应……」句式书写" />
            </label>
            <label class="form-field wide">
              <span class="field-label">行为（每行一条，或用逗号/分号分隔）</span>
              <textarea v-model="manualForm.behaviorsText" rows="3" data-testid="manual-behaviors" placeholder="可独立观测、可独立测试的系统行为" />
            </label>
            <div class="form-row">
              <label class="form-field">
                <span class="field-label">模块</span>
                <input v-model="manualForm.module" type="text" data-testid="manual-module" placeholder="如：计量、事件记录" />
              </label>
              <label class="form-field">
                <span class="field-label">归属</span>
                <select v-model="manualForm.ownership" data-testid="manual-ownership">
                  <option value="">不指定</option>
                  <option value="software">软件</option>
                  <option value="hardware">硬件</option>
                  <option value="co_design">协同</option>
                </select>
              </label>
              <label class="form-field">
                <span class="field-label">优先级</span>
                <select v-model="manualForm.priority" data-testid="manual-priority">
                  <option value="P0">P0</option>
                  <option value="P1">P1</option>
                  <option value="P2">P2</option>
                  <option value="P3">P3</option>
                </select>
              </label>
            </div>
            <label class="form-field wide">
              <span class="field-label">备注</span>
              <textarea v-model="manualForm.notes" rows="2" data-testid="manual-notes" placeholder="可选" />
            </label>
          </div>
          <footer class="manual-foot">
            <button class="fr-button" type="button" :disabled="manualSubmitting" @click="manualOpen = false">取消</button>
            <button class="fr-button primary" type="button" :disabled="manualSubmitting" data-testid="manual-submit" @click="submitManual">
              {{ manualSubmitting ? "提交中…" : "创建" }}
            </button>
          </footer>
        </section>
      </div>
    </Transition>

    <!-- 回退确认对话框（人工确认 + append-only 留痕） -->
    <Transition name="sheet">
      <div v-if="rollbackOpen" class="manual-overlay" data-testid="rollback-form" role="dialog" aria-modal="true" aria-label="回退生命周期" @click.self="rollbackOpen = false">
        <section class="manual-dialog">
          <header class="manual-head">
            <div>
              <div class="manual-title">回退生命周期状态</div>
              <div class="manual-subtitle">自动降级不存在——回退为人工操作，事件将写入 append-only 流（操作者/原因/时间，不可抹除）。</div>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="rollbackOpen = false"><X :size="18" aria-hidden="true" /></button>
          </header>
          <div class="manual-body">
            <label class="form-field wide">
              <span class="field-label">目标状态</span>
              <select v-model="rollbackTarget" data-testid="rollback-target">
                <option v-for="target in rollbackTargets" :key="target" :value="target">{{ lifecycleLabelOf(target) }}（{{ target }}）</option>
              </select>
            </label>
            <label class="form-field wide">
              <span class="field-label">操作者<em class="req">*</em></span>
              <input v-model="rollbackActor" type="text" data-testid="rollback-actor" placeholder="必填——记入 append-only 事件流" />
            </label>
            <label class="form-field wide">
              <span class="field-label">原因<em class="req">*</em></span>
              <textarea v-model="rollbackReason" rows="2" data-testid="rollback-reason" placeholder="必填——记入 append-only 事件流" />
            </label>
          </div>
          <footer class="manual-foot">
            <button class="fr-button" type="button" :disabled="rollbackSubmitting" @click="rollbackOpen = false">取消</button>
            <button class="fr-button warn" type="button" :disabled="rollbackSubmitting" data-testid="rollback-submit" @click="submitRollback">
              {{ rollbackSubmitting ? "提交中…" : "确认回退" }}
            </button>
          </footer>
        </section>
      </div>
    </Transition>

    <!-- 需求库「采纳」确认对话框（actor/reason 必填——经 reviewer_override 通道留痕） -->
    <Transition name="sheet">
      <div v-if="adoptOpen" class="manual-overlay" data-testid="adopt-form" role="dialog" aria-modal="true" aria-label="采纳历史条目" @click.self="adoptOpen = false">
        <section class="manual-dialog">
          <header class="manual-head">
            <div>
              <div class="manual-title">采纳历史条目</div>
              <div class="manual-subtitle">把历史条目的归属/模块套用到当前功能需求。经既有 reviewer_override 通道（verification_states）留痕，不新造写路径。</div>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="adoptOpen = false"><X :size="18" aria-hidden="true" /></button>
          </header>
          <div class="manual-body">
            <div v-if="adoptTarget" class="field" data-testid="adopt-preview">
              <span class="field-label">将套用</span>
              <div class="library-objective">{{ adoptTarget.objective || adoptTarget.title }}</div>
              <div class="candidate-meta">
                <span v-if="adoptTarget.ownership" class="meta-chip">归属：{{ adoptTarget.ownership }}</span>
                <span v-if="adoptTarget.module" class="meta-chip">模块：{{ adoptTarget.module }}</span>
              </div>
            </div>
            <label class="form-field wide">
              <span class="field-label">操作者<em class="req">*</em></span>
              <input v-model="adoptActor" type="text" data-testid="adopt-actor" placeholder="必填——记入 reviewer_override 留痕" />
            </label>
            <label class="form-field wide">
              <span class="field-label">原因<em class="req">*</em></span>
              <textarea v-model="adoptReason" rows="2" data-testid="adopt-reason" placeholder="必填——为什么采纳该历史条目的归属/模块" />
            </label>
          </div>
          <footer class="manual-foot">
            <button class="fr-button" type="button" :disabled="adoptSubmitting" @click="adoptOpen = false">取消</button>
            <button class="fr-button primary" type="button" :disabled="adoptSubmitting" data-testid="adopt-submit" @click="submitAdopt">
              {{ adoptSubmitting ? "提交中…" : "确认采纳" }}
            </button>
          </footer>
        </section>
      </div>
    </Transition>
  </section>
</template>

<style scoped>
.functional-review { display: flex; flex-direction: column; gap: 14px; height: 100%; min-height: 0; }
.fr-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.fr-title { margin: 0; font-size: 18px; font-weight: 620; }
.fr-subtitle { margin: 4px 0 0; font-size: 12.5px; color: #6b7280; }
.fr-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mode-toggle { display: inline-flex; border: 1px solid #d1d5db; border-radius: 8px; overflow: hidden; }
.mode-btn { border: none; background: transparent; padding: 6px 12px; font-size: 13px; cursor: pointer; color: #1f2937; }
.mode-btn.active { background: #dbeafe; color: #1d4ed8; font-weight: 600; }
.fr-button { display: inline-flex; align-items: center; gap: 6px; border: 1px solid #d1d5db; background: #fff; color: #1f2937; padding: 6px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.fr-button:disabled { opacity: 0.55; cursor: not-allowed; }
.fr-button.primary { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.fr-button.warn { background: #b45309; color: #fff; border-color: #b45309; }
.fr-button.small { padding: 4px 8px; font-size: 12px; }
.fr-message { background: #eef2ff; color: #3730a3; border: 1px solid #c7d2fe; padding: 8px 12px; border-radius: 8px; font-size: 13px; }
.fr-split { display: grid; grid-template-columns: minmax(280px, 360px) 1fr; gap: 14px; min-height: 0; flex: 1; }
.fr-list { display: flex; flex-direction: column; gap: 8px; overflow-y: auto; padding-right: 4px; }
.fr-empty { padding: 18px; border: 1px dashed #d1d5db; border-radius: 10px; color: #6b7280; font-size: 13px; }
.fr-card { text-align: left; border: 1px solid #e5e7eb; background: #fff; border-radius: 10px; padding: 10px 12px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; transition: border-color 0.15s, box-shadow 0.15s; }
.fr-card:hover { border-color: #1d4ed8; }
.fr-card.selected { border-color: #1d4ed8; box-shadow: 0 0 0 2px #dbeafe; }
.fr-card-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.fr-card-id { font-size: 12px; color: #6b7280; font-family: ui-monospace, monospace; }
.fr-card-objective { font-size: 13.5px; line-height: 1.45; }
.fr-card-meta { display: flex; gap: 6px; flex-wrap: wrap; }
.meta-chip { font-size: 11px; padding: 2px 7px; border-radius: 999px; background: #f3f4f6; color: #374151; }
.lifecycle-badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.tone-draft { background: #e5e7eb; color: #374151; }
.tone-confirmed { background: #dbeafe; color: #1d4ed8; }
.tone-implemented { background: #fef3c7; color: #92400e; }
.tone-verified { background: #dcfce7; color: #166534; }
.origin-badge { font-size: 11px; padding: 2px 7px; border-radius: 999px; }
.origin-badge.manual { background: #fce7f3; color: #9d174d; }
.origin-badge.conflict { background: #fee2e2; color: #b91c1c; }
.fr-detail { border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
.detail-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.detail-id { margin: 0; font-size: 13px; color: #6b7280; font-family: ui-monospace, monospace; }
.detail-objective { margin: 4px 0 0; font-size: 15px; font-weight: 600; line-height: 1.4; }
.detail-block { display: flex; flex-direction: column; gap: 8px; padding-top: 10px; border-top: 1px solid #f3f4f6; }
.detail-block:first-of-type { border-top: none; padding-top: 0; }
.block-title { margin: 0; font-size: 13px; font-weight: 620; color: #1f2937; }
.block-head-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 12px; color: #6b7280; }
.field-list { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.5; }
.field-list li { margin: 2px 0; }
.source-quote { margin: 0; padding: 8px 12px; background: #f9fafb; border-left: 3px solid #1d4ed8; font-size: 13px; line-height: 1.5; color: #1f2937; }
.no-source { font-size: 13px; color: #6b7280; padding: 8px 10px; background: #f9fafb; border-radius: 8px; }
.block-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.block-chip { font-size: 11.5px; font-family: ui-monospace, monospace; padding: 3px 8px; border-radius: 6px; border: 1px solid #bfdbfe; background: #eff6ff; color: #1d4ed8; cursor: pointer; }
.block-chip.small { font-size: 10.5px; padding: 2px 6px; }
.block-chip:hover { background: #1d4ed8; color: #fff; }
.collapse-toggle { display: inline-flex; align-items: center; gap: 6px; background: transparent; border: none; cursor: pointer; font-size: 13px; font-weight: 600; color: #1f2937; padding: 0; }
.signal-hint { font-size: 11px; color: #6b7280; font-weight: 400; }
.subatom-list { margin: 6px 0 0; padding-left: 8px; display: flex; flex-direction: column; gap: 6px; }
.subatom-item { border-left: 2px solid #e5e7eb; padding: 4px 10px; font-size: 12.5px; line-height: 1.45; }
.subatom-text { color: #1f2937; }
.confirm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }
.confirm-cell { display: flex; align-items: flex-start; gap: 8px; padding: 8px 10px; border: 1px solid #e5e7eb; border-radius: 8px; }
.confirm-meta { display: flex; flex-direction: column; gap: 2px; }
.confirm-label { font-size: 12.5px; font-weight: 600; }
.confirm-stamp { font-size: 11px; color: #6b7280; }
.form-row { display: flex; gap: 10px; flex-wrap: wrap; }
.form-field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 140px; }
.form-field.wide { width: 100%; }
.form-field input[type="text"], .form-field select, .form-field textarea { padding: 6px 8px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px; background: #fff; color: #1f2937; }
.inline-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.stamp-hint { font-size: 11px; color: #6b7280; }
.field-hint { font-size: 12.5px; color: #6b7280; }
.timeline { margin: 0; padding-left: 16px; display: flex; flex-direction: column; gap: 6px; }
.timeline-item { font-size: 12.5px; line-height: 1.5; list-style: disc; display: flex; flex-wrap: wrap; gap: 8px; }
.timeline-kind { font-weight: 600; }
.timeline-transition { color: #1d4ed8; }
.timeline-actor { color: #6b7280; }
.timeline-reason { color: #1f2937; }
.timeline-time { color: #6b7280; font-family: ui-monospace, monospace; font-size: 11px; }
.candidate-list, .library-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.candidate-item, .library-item { border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; }
.candidate-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; }
.kind-tag { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.kind-depend { background: #dbeafe; color: #1d4ed8; }
.kind-exclude { background: #fee2e2; color: #b91c1c; }
.kind-refine { background: #fef3c7; color: #92400e; }
.candidate-pair { font-family: ui-monospace, monospace; font-size: 11.5px; }
.candidate-signal { color: #6b7280; font-size: 11.5px; }
.status-accepted { font-size: 11px; color: #166534; background: #dcfce7; padding: 1px 7px; border-radius: 999px; }
.candidate-actions { display: flex; gap: 6px; }
.library-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.library-score { font-size: 12px; font-weight: 600; color: #1d4ed8; }
.corrected-tag { font-size: 10.5px; padding: 1px 6px; border-radius: 999px; background: #dcfce7; color: #166534; }
.library-project { font-size: 11px; color: #6b7280; }
.library-objective { font-size: 13px; line-height: 1.4; }
.library-behaviors { font-size: 12px; color: #6b7280; }
.fr-atomic { display: flex; flex-direction: column; gap: 10px; }
.atomic-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.atomic-table th, .atomic-table td { border: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }
.atomic-table thead { background: #f9fafb; }
.manual-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 60; padding: 18px; }
.manual-dialog { background: #fff; color: #1f2937; border-radius: 12px; max-width: 560px; width: 100%; max-height: 90vh; overflow-y: auto; display: flex; flex-direction: column; }
.manual-head { display: flex; align-items: flex-start; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #e5e7eb; }
.manual-title { font-size: 15px; font-weight: 620; }
.manual-subtitle { font-size: 12px; color: #6b7280; margin-top: 3px; }
.icon-button { border: none; background: transparent; cursor: pointer; color: #6b7280; }
.manual-body { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.manual-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid #e5e7eb; }
.req { color: #b91c1c; font-style: normal; margin-left: 2px; }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
</style>
