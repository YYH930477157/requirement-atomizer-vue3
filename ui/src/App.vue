<template>
  <n-config-provider>
    <div class="shell">
      <aside class="side-nav">
        <div class="nav-mark">标</div>
        <button
          v-for="item in phaseNavItems"
          :key="item.id"
          class="nav-button"
          :class="{ active: activeNav === item.id }"
          :data-testid="`nav-${item.label}`"
          type="button"
          @click="handleNavAction(item.id)"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </button>
      </aside>

      <main class="main">
        <header class="app-bar">
          <div class="brand-line">
            <div class="brand-text">
              <div class="product-name">标准需求抽取与审查平台</div>
              <div class="doc-name">{{ documentDisplayName }}</div>
            </div>
            <div class="phase-pill">GUI Phase 1</div>
          </div>

          <div class="app-actions">
            <button class="button primary" type="button" data-testid="action-run-pipeline" :disabled="isRunning" @click="handleRunPipeline">
              {{ isRunning ? "运行中" : "运行" }}
            </button>
            <button class="button" type="button" data-testid="action-open-document" @click="handleOpenDocument">导入文档</button>
            <button class="button" type="button" data-testid="action-select-output-dir" @click="handleOpenOutput">选择输出目录</button>
            <button class="button" type="button" data-testid="action-export" @click="handleExport">导出</button>
            <label class="llm-toggle">
              <input v-model="llmMode" type="checkbox" data-testid="llm-mode-toggle" />
              <span>LLM 富化</span>
            </label>
            <button class="button primary" type="button" data-testid="action-assemble" @click="handleAssemble">装配规格</button>
          </div>
        </header>

        <section class="selection-bar">
          <div class="selection-item">
            <span>导入文档</span>
            <strong data-testid="selected-input-path">{{ currentInputPath || "尚未选择文档" }}</strong>
          </div>
          <div class="selection-item">
            <span>输出目录</span>
            <strong data-testid="selected-output-dir">{{ currentOutputDir || "尚未选择输出目录" }}</strong>
          </div>
          <div class="run-meter" data-testid="run-progress">
            <div class="run-meter-head">
              <span>{{ runStage }}</span>
              <strong>{{ runProgress }}%</strong>
            </div>
            <div class="run-meter-track">
              <div class="run-meter-fill" :style="{ width: `${runProgress}%` }"></div>
            </div>
          </div>
        </section>

        <section class="stat-strip" data-testid="phase1-stats">
          <button
            v-for="card in phaseStats"
            :key="card.label"
            class="stat-card"
            :class="{ active: card.active }"
            type="button"
            @click="applyStatFilter(card.filter)"
          >
            <span>
              <span class="stat-label">{{ card.label }}</span>
              <strong class="stat-value">{{ card.value.toLocaleString("zh-CN") }}</strong>
            </span>
            <span class="stat-hint">{{ card.hint }}</span>
          </button>
        </section>

        <section class="filter-bar">
          <select v-model="typeFilter" class="filter-select" aria-label="类型">
            <option v-for="item in typeOptions" :key="item" :value="item">类型：{{ item }}</option>
          </select>
          <select v-model="statusFilter" class="filter-select" aria-label="状态">
            <option v-for="item in statusOptions" :key="item" :value="item">状态：{{ statusOptionLabel(item) }}</option>
          </select>
          <select v-model.number="confidenceFilter" class="filter-select" aria-label="置信度">
            <option :value="0">置信度：全部</option>
            <option :value="0.7">置信度 ≥ 0.70</option>
            <option :value="0.8">置信度 ≥ 0.80</option>
            <option :value="0.9">置信度 ≥ 0.90</option>
          </select>
          <label class="switch-label">
            <input v-model="ambiguousOnly" type="checkbox" />
            <span>仅歧义</span>
          </label>
          <input v-model="searchText" class="search-input" type="search" placeholder="搜索需求、对象或编号" />
        </section>

        <section class="workspace">
          <section class="table-panel">
            <div class="panel-head">
              <div>
                <div class="panel-title">需求表格</div>
                <div class="panel-subtitle">中文界面显示，底层状态与类型仍按后端原值处理</div>
              </div>
              <div class="panel-subtitle">{{ tableFooterText }}</div>
            </div>

            <div class="table-wrap" data-testid="requirement-table">
              <table>
                <thead>
                  <tr>
                    <th class="col-id">编号</th>
                    <th class="col-type">类型</th>
                    <th class="col-object">对象</th>
                    <th>需求</th>
                    <th class="col-confidence">置信度</th>
                    <th class="col-status">状态</th>
                    <th class="col-amb">歧义</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="filteredRequirements.length === 0" data-testid="empty-requirements">
                    <td class="empty-cell" colspan="7">当前输出目录暂无需求</td>
                  </tr>
                  <tr
                    v-for="row in filteredRequirements"
                    :key="row.id"
                    :class="{ selected: row.id === selectedRequirementId }"
                    :data-testid="`row-${row.id}`"
                    @click="selectRequirement(row.id)"
                  >
                    <td class="id-cell">{{ row.id }}</td>
                    <td><span class="type-tag" :class="typeToneClass(row.type)">{{ row.type }}</span></td>
                    <td>{{ row.object }}</td>
                    <td><div class="requirement-cell">{{ row.chineseText }}</div></td>
                    <td><div class="confidence-cell">{{ row.confidence.toFixed(2) }}</div></td>
                    <td>
                      <span class="status-tag" :class="statusToneClass(row.status)" :data-testid="`row-status-${row.id}`">{{ statusDisplay(row.status) }}</span>
                    </td>
                    <td><span class="ambiguity-tag" :class="riskToneClass(row.ambiguity.level)">{{ row.ambiguity.level }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <aside class="detail-panel" data-testid="detail-panel">
            <div class="panel-head">
              <div>
                <div class="panel-title" data-testid="detail-title">{{ selectedRequirement.id }}</div>
                <div class="panel-subtitle">{{ selectedRequirement.object }} · {{ selectedRequirement.sourceDocument }}</div>
              </div>
              <span class="status-tag" :class="statusToneClass(selectedRequirement.status)" data-testid="detail-status">{{ statusDisplay(selectedRequirement.status) }}</span>
            </div>

            <div class="detail-content">
              <section class="readonly-card">
                <div class="readonly-head">① 原始需求</div>
                <div class="readonly-body">{{ selectedRequirement.originalText }}</div>
              </section>

              <section class="readonly-card">
                <div class="readonly-head">
                  <span>② 中文翻译</span>
                  <button class="mini-button" type="button" disabled>翻译</button>
                </div>
                <div class="readonly-body muted">{{ translationText }}</div>
              </section>

              <section class="readonly-card">
                <div class="readonly-head">③ AI 理解的需求</div>
                <div class="readonly-body">{{ aiUnderstandingText }}</div>
              </section>

              <section class="metadata">
                <div v-for="item in metadataRows" :key="item.key" class="metadata-item">
                  <span class="metadata-key">{{ item.key }}</span>
                  <strong class="metadata-value">{{ item.value }}</strong>
                </div>
              </section>

              <section class="mini-row">
                <div class="mini-head">溯源原文</div>
                <div class="mini-body">{{ selectedRequirement.sourceDocument }} · {{ selectedRequirement.sourceLocation }}</div>
              </section>

              <section class="mini-row">
                <div class="mini-head">知识库匹配</div>
                <div class="mini-body">{{ knowledgeMatches }}</div>
              </section>

              <section class="review-box">
                <div class="mini-head">评审</div>
                <div class="review-body">
                  <p>裁决：{{ statusDisplay(selectedRequirement.status) }}</p>
                  <p>风险：{{ selectedRequirement.ambiguity.level }} 风险</p>
                  <p>{{ reviewNote }}</p>
                  <ul v-if="selectedRequirement.ambiguity.reasons.length > 0" class="bullet-list">
                    <li v-for="reason in selectedRequirement.ambiguity.reasons" :key="reason">{{ reason }}</li>
                  </ul>
                </div>
              </section>

              <div class="detail-actions">
                <button class="button" type="button" data-testid="decision-accepted" @click="updateStatus('accepted')">接受</button>
                <button class="button" type="button" data-testid="decision-rejected" @click="updateStatus('rejected')">拒绝</button>
                <button class="button" type="button" @click="updateStatus('needs_discussion')">讨论</button>
                <button class="button" type="button" @click="updateStatus('expert_pending')">专家</button>
              </div>
              <textarea class="comment-box" placeholder="请输入审查意见" />
              <div v-if="apiMessage" class="api-message" data-testid="api-message">{{ apiMessage }}</div>
            </div>
          </aside>
        </section>

        <footer class="status-bar">
          <span>输出目录：{{ currentOutputDir || "尚未选择输出目录" }}</span>
          <span class="kbd-hints">快捷键：A 接受 · R 拒绝 · D 讨论 · P 固定</span>
        </footer>
      </main>
    </div>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { NConfigProvider } from "naive-ui"
import { RequirementApiClient } from "./api-client"
import { requirements as mockRequirements } from "./mock-data"
import { applyReviewState, mapBackendRequirement, statusDisplay as displayStatus } from "./requirement-mapper"
import type { Requirement, ReviewStatus } from "./types"

type PhaseNavId = "review" | "document" | "export" | "settings"
type StatFilter = "all" | "accepted" | "expert_pending" | "ambiguous"

const phaseNavItems: Array<{ id: PhaseNavId; label: string; icon: string }> = [
  { id: "review", label: "审查", icon: "▣" },
  { id: "document", label: "文档", icon: "▤" },
  { id: "export", label: "导出", icon: "↧" },
  { id: "settings", label: "设置", icon: "⚙" },
]

const activeNav = ref<PhaseNavId>("review")
const llmMode = ref(false)
const apiClient = ref<RequirementApiClient | null>(null)
const apiMessage = ref("")
const currentInputPath = ref("")
const currentOutputDir = ref("")
const isRunning = ref(false)
const runProgress = ref(0)
const runStage = ref("待运行")
const latestTaskSummary = ref<Record<string, unknown> | null>(null)

const abntPreset = {
  chunkChars: 3500,
  kbPaths: [
    "knowledge_bases/energy_metering.json",
    "knowledge_bases/energy_metering_protocol_layer.json",
    "knowledge_bases/energy_metering_cosem_classes.json",
  ],
  domainPackDir: "domain_packs/dlms_cosem",
}

const emptyRequirement: Requirement = {
  id: "未选择需求",
  backendId: "",
  type: "功能",
  object: "-",
  chineseText: "当前输出目录暂无需求。",
  originalText: "请选择文档运行抽取，或打开包含 atomic_requirements.jsonl 的输出目录。",
  sourceDocument: "-",
  sourceLocation: "-",
  confidence: 0,
  risk: "低",
  status: "candidate",
  keyPoints: [],
  ambiguity: { level: "低", reasons: [] },
}

const requirementRows = ref<Requirement[]>(
  mockRequirements.map((item) => ({
    ...item,
    keyPoints: [...item.keyPoints],
    ambiguity: { ...item.ambiguity, reasons: [...item.ambiguity.reasons] },
    specMapping: item.specMapping ? { ...item.specMapping } : undefined,
  })),
)
const selectedRequirementId = ref(requirementRows.value[1].id)

const typeFilter = ref("全部")
const statusFilter = ref("全部")
const confidenceFilter = ref(0.7)
const ambiguousOnly = ref(false)
const searchText = ref("")

const typeOptions = computed(() => ["全部", ...Array.from(new Set(requirementRows.value.map((item) => item.type)))])
const statusOptions: Array<ReviewStatus | "全部"> = ["全部", "candidate", "llm_reviewed", "accepted", "rejected", "expert_pending", "needs_discussion", "needs_rework", "flagged", "frozen"]

const filteredRequirements = computed(() => requirementRows.value.filter((item) => {
  if (typeFilter.value !== "全部" && item.type !== typeFilter.value) return false
  if (statusFilter.value !== "全部" && item.status !== statusFilter.value) return false
  if (item.confidence < confidenceFilter.value) return false
  if (ambiguousOnly.value && item.ambiguity.level === "低") return false
  if (searchText.value) {
    const haystack = [item.id, item.type, item.object, item.chineseText, item.originalText].join(" ").toLowerCase()
    if (!haystack.includes(searchText.value.toLowerCase())) return false
  }
  return true
}))

const selectedRequirement = computed(() => requirementRows.value.find((item) => item.id === selectedRequirementId.value) ?? requirementRows.value[0] ?? emptyRequirement)
const documentDisplayName = computed(() => {
  if (currentInputPath.value) return `当前文档：${fileName(currentInputPath.value)}`
  if (currentOutputDir.value) return `当前输出：${currentOutputDir.value}`
  if (selectedRequirement.value.sourceDocument && selectedRequirement.value.sourceDocument !== "-") {
    return `当前文档：${selectedRequirement.value.sourceDocument}`
  }
  return "当前文档：尚未导入"
})
const tableFooterText = computed(() => {
  const total = filteredRequirements.value.length
  if (total === 0) return "显示第 0 条，共 0 条"
  return `显示第 1-${total} 条，共 ${total} 条`
})
const reviewNote = computed(() => {
  if (selectedRequirement.value.status === "rejected") return "当前条目被拒绝，建议补充重写。"
  if (selectedRequirement.value.status === "expert_pending") return "建议交给专家进一步确认。"
  if (selectedRequirement.value.status === "needs_discussion") return "当前条目正在讨论中。"
  return "系统理解已抽取，可继续审查。"
})
const phaseStats = computed(() => {
  const total = requirementRows.value.length
  const accepted = countStatus("accepted")
  const expert = countStatus("expert_pending")
  const ambiguous = requirementRows.value.filter((item) => item.ambiguity.level !== "低").length
  return [
    { label: "总数", value: total, hint: "全部", filter: "all" as StatFilter, active: statusFilter.value === "全部" && !ambiguousOnly.value },
    { label: "已接受", value: accepted, hint: "筛选", filter: "accepted" as StatFilter, active: statusFilter.value === "accepted" },
    { label: "待专家", value: expert, hint: "筛选", filter: "expert_pending" as StatFilter, active: statusFilter.value === "expert_pending" },
    { label: "歧义", value: ambiguous, hint: "筛选", filter: "ambiguous" as StatFilter, active: ambiguousOnly.value },
  ]
})
const translationText = computed(() => "（尚未翻译，将在后续版本接入）")
const aiUnderstandingText = computed(() => selectedRequirement.value.chineseText || "（尚未经过 AI 审查）")
const metadataRows = computed(() => [
  { key: "编号", value: selectedRequirement.value.id },
  { key: "类型", value: selectedRequirement.value.type },
  { key: "对象", value: selectedRequirement.value.object },
  { key: "置信度", value: selectedRequirement.value.confidence.toFixed(2) },
  { key: "歧义", value: selectedRequirement.value.ambiguity.level },
  { key: "状态", value: statusDisplay(selectedRequirement.value.status) },
])
const knowledgeMatches = computed(() => {
  const points = selectedRequirement.value.keyPoints
  return points.length > 0 ? points.join(" · ") : "暂无知识库匹配"
})

onMounted(() => {
  loadInitialApiSession()
})

function handleNavAction(item: PhaseNavId) {
  activeNav.value = item
  if (item === "document") {
    void handleOpenDocument()
  } else if (item === "export") {
    void handleExport()
  } else if (item === "settings") {
    apiMessage.value = "设置将在后续版本接入。"
  }
}

function selectRequirement(id: string) {
  selectedRequirementId.value = id
}

function applyStatFilter(filter: StatFilter) {
  if (filter === "all") {
    statusFilter.value = "全部"
    ambiguousOnly.value = false
  } else if (filter === "ambiguous") {
    statusFilter.value = "全部"
    ambiguousOnly.value = true
  } else {
    statusFilter.value = filter
    ambiguousOnly.value = false
  }
}

async function updateStatus(status: ReviewStatus) {
  const row = requirementRows.value.find((item) => item.id === selectedRequirementId.value)
  if (!row) return
  apiMessage.value = ""
  if (!apiClient.value) {
    row.status = status
    return
  }
  try {
    const state = await apiClient.value.applyReviewAction({
      requirementId: row.backendId,
      status,
      actor: "vue3-ui",
      reason: `set ${status} from Vue3 UI`,
    })
    const index = requirementRows.value.findIndex((item) => item.id === row.id)
    if (index >= 0) {
      requirementRows.value[index] = applyReviewState(row, state)
    }
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "审查状态写入失败"
  }
}

function statusDisplay(status: ReviewStatus) {
  return displayStatus(status)
}

function statusOptionLabel(status: ReviewStatus | "全部") {
  return status === "全部" ? status : statusDisplay(status)
}

function statusToneClass(status: ReviewStatus) {
  return {
    accept: status === "accepted" || status === "frozen",
    reject: status === "rejected" || status === "needs_rework",
    warning: status === "expert_pending" || status === "flagged",
    review: status === "candidate" || status === "llm_reviewed",
    discuss: status === "needs_discussion",
  }
}

function riskToneClass(level: string) {
  return {
    low: level === "低",
    middle: level === "中",
    high: level === "高",
  }
}

function typeToneClass(type: string) {
  return {
    functional: type === "功能",
    performance: type === "性能",
    security: type === "安全",
    interface: type === "接口",
    data: type === "数据",
    environment: type === "环境",
    constraint: type === "约束",
  }
}

async function handleOpenDocument() {
  const path = await window.ratomizerDesktop?.openDocument()
  if (path) {
    currentInputPath.value = path
    apiMessage.value = `已选择文档：${path}`
    runStage.value = "待运行"
    runProgress.value = 0
  }
}

async function handleOpenOutput() {
  if (window.ratomizerDesktop?.selectOutputDir) {
    const path = await window.ratomizerDesktop.selectOutputDir()
    if (path) {
      currentOutputDir.value = path
      apiMessage.value = `已选择输出目录：${path}`
      runStage.value = "待运行"
    }
    return
  }
  const session = await window.ratomizerDesktop?.openOutput?.()
  if (session && typeof session === "object" && "baseUrl" in session) {
    await loadFromSession(session)
  }
}

async function handleRunPipeline() {
  if (isRunning.value) return
  try {
    if (!currentInputPath.value) {
      apiMessage.value = "请先导入文档"
      runStage.value = "等待导入文档"
      runProgress.value = 0
      return
    }
    if (!currentInputPath.value || !window.ratomizerDesktop?.runPipeline) return
    const outDir = currentOutputDir.value || defaultOutputDir(currentInputPath.value)
    currentOutputDir.value = outDir
    isRunning.value = true
    runProgress.value = 8
    runStage.value = "准备运行"
    apiMessage.value = "正在运行抽取与审查..."
    await nextUiTick()
    runProgress.value = 18
    runStage.value = "运行后端解析"
    const payload = await window.ratomizerDesktop.runPipeline({
      inputPath: currentInputPath.value,
      outDir,
      skipReview: false,
      ...abntPreset,
    })
    runProgress.value = 82
    runStage.value = "加载解析结果"
    latestTaskSummary.value = objectValue(payload.summary)
    currentOutputDir.value = String(payload.out_dir || payload.outDir || outDir)
    await refreshAfterDesktopTask(currentOutputDir.value)
    runProgress.value = 100
    runStage.value = "运行完成"
    apiMessage.value = "抽取与审查完成"
  } catch (error) {
    runStage.value = "运行失败"
    apiMessage.value = error instanceof Error ? error.message : "抽取与审查失败"
  } finally {
    isRunning.value = false
  }
}

async function handleExport() {
  if (!currentOutputDir.value || !window.ratomizerDesktop?.exportRequirements) return
  try {
    const payload = await window.ratomizerDesktop.exportRequirements({ outDir: currentOutputDir.value, formats: ["csv", "md"] })
    latestTaskSummary.value = objectValue(payload.summary)
    apiMessage.value = `已导出：${(payload.written || []).join(", ")}`
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "导出失败"
  }
}

async function handleAssemble() {
  if (!currentOutputDir.value || !window.ratomizerDesktop?.assembleSpec) return
  try {
    const payload = await window.ratomizerDesktop.assembleSpec({
      outDir: currentOutputDir.value,
      formats: ["xlsx", "docx", "md"],
      enrichRoute: llmMode.value ? "openai_compatible" : undefined,
    })
    latestTaskSummary.value = objectValue(payload.summary)
    apiMessage.value = `已装配实现规格：${payload.count ?? 0} 条`
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "装配实现规格失败"
  }
}

async function loadInitialApiSession() {
  const session = await window.ratomizerDesktop?.getApiSession?.()
  if (session) {
    await loadFromSession(session)
  }
}

async function loadFromSession(session: { baseUrl: string; token: string; outputDir?: string }) {
  apiMessage.value = session.outputDir ? `已连接输出目录：${session.outputDir}` : ""
  currentOutputDir.value = session.outputDir || currentOutputDir.value
  const client = new RequirementApiClient({ baseUrl: session.baseUrl, token: session.token })
  apiClient.value = client
  try {
    const rows = (await client.loadRequirements()).map(mapBackendRequirement)
    requirementRows.value = rows
    selectedRequirementId.value = rows[0]?.id ?? ""
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "需求加载失败"
    throw error
  }
}

async function refreshAfterDesktopTask(outDir: string) {
  const session = await window.ratomizerDesktop?.startApiSession?.(outDir)
  if (session) {
    await loadFromSession(session)
  }
}

function defaultOutputDir(inputPath: string) {
  const stem = inputPath.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, "") || "run"
  return `E:\\Codex\\requirement-atomizer-runs\\${stem}`
}

function countStatus(status: ReviewStatus) {
  return requirementRows.value.filter((item) => item.status === status).length
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function nextUiTick() {
  return new Promise<void>((resolve) => window.setTimeout(resolve, 0))
}

function fileName(path: string) {
  return path.split(/[\\/]/).pop() || path
}
</script>
<style scoped>
.shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  min-height: 100vh;
  background: #f5f7fb;
  color: #0f172a;
}

.sidebar {
  background: linear-gradient(180deg, #071d36 0%, #08284b 100%);
  color: #eaf2ff;
  padding: 18px 14px;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 54px;
}

.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #1d4ed8, #3b82f6);
  display: grid;
  place-items: center;
  font-weight: 900;
  font-size: 20px;
  box-shadow: 0 14px 28px rgba(37, 99, 235, 0.35);
}

.brand-title {
  font-size: 15px;
  font-weight: 800;
  line-height: 1.25;
}

.brand-subtitle {
  margin-top: 4px;
  color: #93c5fd;
  font-size: 12px;
}

.nav-groups {
  display: flex;
  flex-direction: column;
  gap: 18px;
  flex: 1;
}

.nav-group-title {
  margin: 0 0 8px;
  color: #8aa8ca;
  font-size: 12px;
  font-weight: 800;
}

.nav-item {
  display: block;
  width: 100%;
  margin: 3px 0;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #cbd5e1;
  padding: 11px 12px;
  text-align: left;
  cursor: pointer;
}

.nav-item.active,
.nav-item:hover {
  background: rgba(37, 99, 235, 0.72);
  color: white;
  font-weight: 800;
}

.sidebar-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  padding-top: 14px;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
  display: grid;
  place-items: center;
  font-weight: 900;
}

.user-name {
  font-weight: 800;
}

.user-role {
  color: #a6bdd6;
  font-size: 12px;
}

.main-panel {
  min-width: 0;
  padding: 18px 18px 20px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.title-area {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  font-size: 22px;
  font-weight: 900;
  letter-spacing: 0;
}

.page-badge {
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  color: #1d4ed8;
  background: #eff6ff;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 800;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.action,
.toolbar-button,
.decision-button {
  border: 1px solid #d9e2ef;
  border-radius: 8px;
  background: #fff;
  color: #1e293b;
  min-height: 34px;
  padding: 0 12px;
  cursor: pointer;
  font-weight: 800;
}

.action.primary,
.toolbar-button.primary {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
  box-shadow: 0 10px 20px rgba(37, 99, 235, 0.2);
}

.llm-toggle,
.switch-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #334155;
  font-weight: 700;
  font-size: 13px;
}

.workflow-card {
  background: white;
  border: 1px solid #e5edf7;
  border-radius: 14px;
  padding: 14px;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.05);
  margin-bottom: 16px;
}

.workflow-stepper {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  border-bottom: 1px solid #edf2f8;
  padding-bottom: 14px;
}

.workflow-step {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  position: relative;
}

.workflow-step:not(:last-child)::after {
  content: "";
  height: 1px;
  background: #cdd9e8;
  position: absolute;
  right: 8px;
  left: 112px;
  top: 15px;
}

.workflow-circle {
  width: 30px;
  height: 30px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: #e8eef7;
  color: #64748b;
  font-weight: 900;
  z-index: 1;
}

.workflow-step.done .workflow-circle {
  background: #2563eb;
  color: white;
}

.workflow-step.active .workflow-circle {
  background: #16a34a;
  color: white;
}

.workflow-title {
  font-size: 14px;
  font-weight: 900;
}

.workflow-subtitle {
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.summary-card {
  background: #fff;
  border: 1px solid #e5edf7;
  border-radius: 12px;
  min-height: 112px;
  padding: 16px 18px;
}

.summary-label {
  color: #475569;
  font-size: 13px;
  font-weight: 900;
}

.summary-value {
  margin-top: 8px;
  font-size: 30px;
  font-weight: 900;
}

.summary-delta {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.summary-card.tone-blue .summary-value { color: #1d4ed8; }
.summary-card.tone-green .summary-value { color: #16a34a; }
.summary-card.tone-orange .summary-value { color: #f97316; }
.summary-card.tone-purple .summary-value { color: #7c3aed; }
.summary-card.tone-red .summary-value { color: #dc2626; }

.distribution-card {
  grid-column: span 1;
}

.distribution-list {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.distribution-track {
  height: 8px;
  border-radius: 999px;
  background: #eef2f7;
  overflow: hidden;
}

.distribution-fill {
  height: 100%;
  border-radius: inherit;
}

.distribution-fill.tone-green { background: #16a34a; }
.distribution-fill.tone-blue { background: #2563eb; }
.distribution-fill.tone-red { background: #ef4444; }

.distribution-caption {
  font-size: 11px;
  color: #64748b;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 430px;
  gap: 16px;
}

.table-card,
.detail-card {
  min-width: 0;
  background: white;
  border: 1px solid #e5edf7;
  border-radius: 14px;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.05);
}

.table-card {
  overflow: hidden;
}

.filters-panel {
  border-bottom: 1px solid #edf2f8;
  padding: 14px;
  display: grid;
  gap: 12px;
}

.filter-row,
.toolbar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-select,
.search-input {
  height: 34px;
  border: 1px solid #d9e2ef;
  border-radius: 8px;
  background: white;
  color: #1e293b;
  padding: 0 10px;
  font-weight: 700;
}

.search-input {
  width: 260px;
}

.toolbar-note {
  margin-left: auto;
  color: #64748b;
  font-size: 12px;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 1060px;
  border-collapse: collapse;
  table-layout: fixed;
}

th,
td {
  border-bottom: 1px solid #edf2f8;
  padding: 12px 10px;
  text-align: left;
  vertical-align: middle;
  font-size: 13px;
}

th {
  background: #f8fbff;
  color: #475569;
  font-size: 12px;
  font-weight: 900;
}

tbody tr {
  cursor: pointer;
}

tbody tr:hover,
tbody tr.selected {
  background: #f3f7ff;
}

.check-col {
  width: 44px;
  text-align: center;
}

.id-cell {
  color: #1d4ed8;
  font-weight: 900;
}

.type-tag,
.status-tag,
.ambiguity-tag,
.risk-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.type-tag.functional { color: #1d4ed8; background: #eff6ff; }
.type-tag.performance { color: #15803d; background: #ecfdf5; }
.type-tag.security { color: #dc2626; background: #fef2f2; }
.type-tag.interface { color: #a855f7; background: #f5f3ff; }
.type-tag.data { color: #0f766e; background: #f0fdfa; }
.type-tag.environment { color: #c2410c; background: #fff7ed; }
.type-tag.constraint { color: #b45309; background: #fffbeb; }

.status-tag.accept { color: #15803d; background: #ecfdf5; border: 1px solid #bbf7d0; }
.status-tag.reject { color: #dc2626; background: #fef2f2; border: 1px solid #fecaca; }
.status-tag.warning { color: #d97706; background: #fff7ed; border: 1px solid #fed7aa; }
.status-tag.review { color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; }
.status-tag.discuss { color: #7c3aed; background: #f5f3ff; border: 1px solid #ddd6fe; }

.ambiguity-tag.low,
.risk-badge.low { color: #15803d; background: #ecfdf5; }
.ambiguity-tag.middle,
.risk-badge.middle { color: #d97706; background: #fffbeb; }
.ambiguity-tag.high,
.risk-badge.high { color: #dc2626; background: #fef2f2; }

.confidence-cell {
  font-weight: 900;
  font-variant-numeric: tabular-nums;
}

.empty-cell {
  height: 96px;
  text-align: center;
  color: #64748b;
  font-weight: 800;
  cursor: default;
}

.row-action {
  color: #2563eb;
  font-weight: 900;
}

.table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #64748b;
  padding: 12px 16px;
  font-size: 13px;
}

.pagination {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page {
  min-width: 28px;
  height: 28px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  color: #334155;
}

.page.active {
  background: #2563eb;
  color: white;
}

.detail-card {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.detail-id {
  font-size: 20px;
  font-weight: 900;
}

.detail-subtitle {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.detail-tabs {
  display: flex;
  gap: 16px;
  border-bottom: 1px solid #edf2f8;
}

.detail-tab {
  border: 0;
  background: transparent;
  color: #334155;
  padding: 10px 0;
  cursor: pointer;
  font-weight: 900;
}

.detail-tab.active {
  color: #2563eb;
  box-shadow: inset 0 -2px #2563eb;
}

.detail-stack {
  display: grid;
  gap: 10px;
}

.detail-section {
  border: 1px solid #e5edf7;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.section-title {
  margin-bottom: 8px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 900;
}

.detail-body p {
  margin: 8px 0;
  line-height: 1.7;
}

.meta-line {
  color: #64748b;
  font-size: 12px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.metrics-grid div {
  background: #f8fbff;
  border-radius: 10px;
  padding: 9px;
}

.metrics-grid span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.metrics-grid strong {
  display: block;
  margin-top: 4px;
}

.progress-wrap {
  margin-top: 10px;
}

.progress-label {
  color: #64748b;
  font-size: 12px;
  margin-bottom: 6px;
}

.progress-track {
  height: 8px;
  border-radius: 999px;
  background: #e8edf5;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: #16a34a;
}

.bullet-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  line-height: 1.6;
}

.risk-list {
  margin-top: 8px;
  color: #b45309;
}

.note-box {
  margin-top: 10px;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  background: #eff6ff;
  color: #1e3a8a;
  padding: 10px;
  font-size: 13px;
  line-height: 1.6;
}

.decision-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.decision-button {
  min-height: 38px;
}

.decision-button.accept { color: #15803d; border-color: #86efac; background: #f0fdf4; }
.decision-button.reject { color: #dc2626; border-color: #fecaca; background: #fef2f2; }
.decision-button.discuss { color: #d97706; border-color: #fed7aa; background: #fff7ed; }
.decision-button.expert { color: #1d4ed8; border-color: #bfdbfe; background: #eff6ff; }

.comment-box {
  width: 100%;
  min-height: 88px;
  resize: vertical;
  border: 1px solid #d9e2ef;
  border-radius: 10px;
  padding: 10px;
  color: #1e293b;
}

.module-page {
  min-height: 520px;
  background: white;
  border: 1px solid #e5edf7;
  border-radius: 14px;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.05);
  padding: 24px;
}

.module-hero {
  border-bottom: 1px solid #edf2f8;
  padding-bottom: 22px;
  margin-bottom: 22px;
}

.module-kicker {
  color: #2563eb;
  font-size: 12px;
  font-weight: 900;
}

.module-hero h2 {
  margin: 8px 0 8px;
  font-size: 26px;
  letter-spacing: 0;
}

.module-hero p {
  margin: 0;
  max-width: 680px;
  color: #475569;
  line-height: 1.7;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.module-card {
  min-height: 136px;
  border: 1px solid #e5edf7;
  border-radius: 12px;
  background: #f8fbff;
  padding: 18px;
}

.module-card-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 900;
}

.module-card-body {
  margin-top: 10px;
  color: #64748b;
  line-height: 1.7;
  font-size: 13px;
}
@media (max-width: 1480px) {
  .shell {
    grid-template-columns: 94px minmax(0, 1fr);
  }

  .brand-copy,
  .nav-group-title,
  .user-chip div:not(.user-avatar) {
    display: none;
  }

  .nav-item {
    text-align: center;
    padding: 12px 6px;
    font-size: 12px;
  }

  .summary-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .distribution-card {
    grid-column: span 3;
  }

  .workspace-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .module-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    display: none;
  }

  .workflow-stepper,
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .module-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* Phase 1 Chinese dashboard shell */
.shell {
  display: grid;
  grid-template-columns: 108px minmax(0, 1fr);
  min-height: 100vh;
  background: #f6f7f9;
  color: #1f2937;
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
  letter-spacing: 0;
}

.side-nav {
  background: #edf1f5;
  border-right: 1px solid #dfe5ec;
  padding: 18px 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.nav-mark {
  width: 44px;
  height: 44px;
  margin: 2px auto 10px;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 22px;
  font-weight: 900;
  background: linear-gradient(145deg, #2563eb, #0f9f93);
  border-radius: 12px;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.2);
}

.nav-button {
  position: relative;
  min-height: 72px;
  padding: 10px 6px 8px;
  border: 1px solid transparent;
  border-radius: 10px;
  color: #4b5565;
  display: grid;
  justify-items: center;
  align-content: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 700;
  background: transparent;
  cursor: pointer;
}

.nav-button:hover,
.nav-button.active {
  color: #2563eb;
  background: #fff;
  border-color: #b9cdfb;
  box-shadow: 0 5px 14px rgba(37, 99, 235, 0.08);
}

.nav-button.active::before {
  content: "";
  position: absolute;
  left: -12px;
  top: 14px;
  width: 4px;
  height: 44px;
  border-radius: 0 4px 4px 0;
  background: #2563eb;
}

.nav-icon {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  color: currentColor;
  font-size: 18px;
  line-height: 1;
}

.main {
  min-width: 0;
  display: grid;
  grid-template-rows: 78px auto 118px 72px minmax(0, 1fr) 32px;
}

.app-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 26px;
  background: #fff;
  border-bottom: 1px solid #dfe5ec;
}

.brand-line {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-text {
  min-width: 0;
}

.product-name {
  color: #172033;
  font-size: 24px;
  line-height: 1.2;
  font-weight: 900;
  white-space: nowrap;
}

.doc-name {
  margin-top: 4px;
  color: #687386;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.phase-pill {
  flex: 0 0 auto;
  height: 28px;
  display: inline-flex;
  align-items: center;
  padding: 0 10px;
  border: 1px solid #d3dbe6;
  border-radius: 999px;
  color: #526070;
  background: #f8fafc;
  font-size: 12px;
  font-weight: 800;
}

.app-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.selection-bar {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.2fr) minmax(260px, 0.8fr);
  gap: 14px;
  padding: 12px 26px;
  background: #fff;
  border-bottom: 1px solid #dfe5ec;
}

.selection-item {
  min-width: 0;
  height: 52px;
  display: grid;
  align-content: center;
  gap: 5px;
  border: 1px solid #dfe5ec;
  border-radius: 8px;
  background: #f8fafc;
  padding: 8px 12px;
}

.selection-item span,
.run-meter-head span {
  color: #687386;
  font-size: 12px;
  font-weight: 800;
}

.selection-item strong {
  min-width: 0;
  color: #172033;
  font-size: 13px;
  font-weight: 900;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.run-meter {
  min-width: 0;
  height: 52px;
  display: grid;
  align-content: center;
  gap: 8px;
  border: 1px solid #b9cdfb;
  border-radius: 8px;
  background: #eef4ff;
  padding: 8px 12px;
}

.run-meter-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.run-meter-head strong {
  color: #2156c7;
  font-size: 13px;
  font-weight: 900;
  font-variant-numeric: tabular-nums;
}

.run-meter-track {
  height: 8px;
  border-radius: 999px;
  background: #d8e5ff;
  overflow: hidden;
}

.run-meter-fill {
  height: 100%;
  border-radius: inherit;
  background: #2563eb;
  transition: width 180ms ease;
}

.button {
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid #ccd5df;
  border-radius: 8px;
  color: #273344;
  background: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
  cursor: pointer;
}

.button.primary {
  color: #fff;
  border-color: #1d57d3;
  background: #2563eb;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.22);
}

.button:disabled,
.mini-button:disabled {
  color: #97a1af;
  background: #f2f4f7;
  border-color: #e0e5eb;
  box-shadow: none;
  cursor: default;
}

.llm-toggle,
.switch-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #445066;
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
}

.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  padding: 18px 26px;
  background: #f6f7f9;
  border-bottom: 1px solid #dfe5ec;
}

.stat-card {
  min-width: 0;
  height: 82px;
  padding: 15px 18px;
  border: 1px solid #dfe5ec;
  border-radius: 10px;
  background: #fff;
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 12px;
  text-align: left;
  cursor: pointer;
}

.stat-card.active {
  border-color: #b9cdfb;
  background: linear-gradient(180deg, #fff 0%, #f5f8ff 100%);
}

.stat-label {
  color: #687386;
  font-size: 13px;
  font-weight: 800;
}

.stat-value {
  display: block;
  margin-top: 5px;
  color: #172033;
  font-size: 30px;
  line-height: 1;
  font-weight: 900;
}

.stat-hint {
  align-self: start;
  height: 24px;
  padding: 0 8px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  color: #587099;
  background: #eef4ff;
  font-size: 12px;
  font-weight: 800;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 26px;
  background: #fff;
  border-bottom: 1px solid #dfe5ec;
}

.filter-select,
.search-input {
  height: 38px;
  border: 1px solid #ccd5df;
  border-radius: 8px;
  background: #fff;
  color: #273344;
  padding: 0 11px;
  font-size: 13px;
  font-weight: 700;
}

.filter-select {
  min-width: 152px;
}

.search-input {
  flex: 1 1 auto;
  min-width: 280px;
}

.workspace {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 430px;
  background: #f6f7f9;
}

.table-panel,
.detail-panel {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  background: #fff;
}

.table-panel {
  border-right: 1px solid #dfe5ec;
}

.panel-head {
  min-height: 52px;
  padding: 10px 20px;
  border-bottom: 1px solid #dfe5ec;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.panel-title {
  color: #172033;
  font-size: 15px;
  font-weight: 900;
}

.panel-subtitle {
  color: #687386;
  font-size: 12px;
  font-weight: 700;
}

.table-wrap {
  min-height: 0;
  overflow: auto;
}

table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 13px;
}

thead th {
  height: 42px;
  padding: 0 12px;
  color: #536173;
  background: #f8fafc;
  border-bottom: 1px solid #dfe5ec;
  text-align: left;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

tbody td {
  height: 62px;
  padding: 8px 12px;
  border-bottom: 1px solid #edf1f5;
  color: #293445;
  vertical-align: middle;
  overflow: hidden;
  text-overflow: ellipsis;
}

tbody tr {
  cursor: pointer;
}

tbody tr.selected td,
tbody tr:hover td {
  background: #f2f7ff;
}

.col-id {
  width: 120px;
}

.col-type {
  width: 150px;
}

.col-object {
  width: 142px;
}

.col-confidence {
  width: 96px;
}

.col-status {
  width: 112px;
}

.col-amb {
  width: 72px;
}

.requirement-cell {
  line-height: 1.35;
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.type-tag,
.status-tag,
.ambiguity-tag,
.risk-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  max-width: 100%;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.type-tag.functional,
.type-tag.interface,
.type-tag.data,
.type-tag.environment,
.type-tag.constraint {
  color: #2156c7;
  background: #e7efff;
}

.type-tag.security,
.type-tag.performance {
  color: #6d4aff;
  background: #f1edff;
}

.status-tag.accept {
  color: #148451;
  background: #eaf7f1;
  border: 1px solid #bbf7d0;
}

.status-tag.reject {
  color: #b42318;
  background: #fff0ed;
  border: 1px solid #fecaca;
}

.status-tag.warning {
  color: #a46105;
  background: #fff4df;
  border: 1px solid #fed7aa;
}

.status-tag.review {
  color: #2156c7;
  background: #e7efff;
  border: 1px solid #bfdbfe;
}

.status-tag.discuss {
  color: #6d4aff;
  background: #f1edff;
  border: 1px solid #ddd6fe;
}

.ambiguity-tag.low,
.risk-badge.low {
  color: #148451;
  background: #eaf7f1;
}

.ambiguity-tag.middle,
.risk-badge.middle {
  color: #a46105;
  background: #fff4df;
}

.ambiguity-tag.high,
.risk-badge.high {
  color: #b42318;
  background: #fff0ed;
}

.id-cell,
.confidence-cell {
  font-weight: 900;
  font-variant-numeric: tabular-nums;
}

.id-cell {
  color: #2563eb;
}

.empty-cell {
  height: 96px;
  text-align: center;
  color: #64748b;
  font-weight: 800;
  cursor: default;
}

.detail-panel {
  grid-template-rows: auto minmax(0, 1fr);
}

.detail-content {
  min-height: 0;
  padding: 16px 18px 18px;
  overflow: auto;
  display: grid;
  grid-auto-rows: max-content;
  gap: 12px;
  background: #fbfcfe;
}

.readonly-card,
.mini-row,
.review-box {
  border: 1px solid #dfe5ec;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}

.readonly-head,
.mini-head {
  min-height: 34px;
  padding: 8px 12px 7px;
  color: #293445;
  background: #f7f9fc;
  border-bottom: 1px solid #e7ecf2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  font-weight: 900;
}

.readonly-body,
.mini-body,
.review-body {
  padding: 11px 12px 12px;
  color: #293445;
  font-size: 13px;
  line-height: 1.55;
}

.readonly-body.muted {
  color: #7b8796;
}

.mini-button {
  height: 26px;
  padding: 0 10px;
  border: 1px solid #ccd5df;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 800;
}

.metadata {
  border: 1px solid #dfe5ec;
  border-radius: 10px;
  background: #fff;
  padding: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 10px;
}

.metadata-item {
  min-width: 0;
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  font-size: 12px;
}

.metadata-key {
  color: #687386;
  font-weight: 800;
}

.metadata-value {
  min-width: 0;
  color: #273344;
  font-weight: 900;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-body p {
  margin: 0 0 6px;
}

.bullet-list {
  margin: 8px 0 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
  line-height: 1.6;
}

.detail-actions {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.comment-box {
  width: 100%;
  min-height: 72px;
  resize: vertical;
  border: 1px solid #ccd5df;
  border-radius: 10px;
  padding: 10px;
  color: #1e293b;
  font-family: inherit;
}

.api-message {
  color: #2156c7;
  background: #eef4ff;
  border: 1px solid #b9cdfb;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  font-weight: 800;
}

.status-bar {
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  color: #647084;
  background: #fff;
  border-top: 1px solid #dfe5ec;
  font-size: 12px;
  font-weight: 700;
}

.kbd-hints {
  color: #8792a3;
}

@media (max-width: 1180px) {
  .main {
    grid-template-rows: auto auto auto auto minmax(0, 1fr) 32px;
  }

  .app-bar,
  .filter-bar {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .selection-bar {
    grid-template-columns: minmax(0, 1fr);
  }

  .stat-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workspace {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>




