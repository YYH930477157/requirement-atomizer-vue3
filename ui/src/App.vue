<template>
  <n-config-provider>
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">标</div>
          <div class="brand-copy">
            <div class="brand-title">标准需求抽取与审查平台</div>
            <div class="brand-subtitle">GUI Phase 1</div>
          </div>
        </div>

        <nav class="nav-groups">
          <section v-for="group in navGroups" :key="group.title" class="nav-group">
            <h3 v-if="group.title" class="nav-group-title">{{ group.title }}</h3>
            <button
              v-for="item in group.items"
              :key="item"
              class="nav-item"
              :class="{ active: activeNav === item }"
              :data-testid="'nav-' + item"
              @click="setModule(item)"
            >
              {{ item }}
            </button>
          </section>
        </nav>

        <div class="sidebar-footer">
          <div class="user-chip">
            <div class="user-avatar">审</div>
            <div>
              <div class="user-name">审查员</div>
              <div class="user-role">zhangsan</div>
            </div>
          </div>
        </div>
      </aside>

      <main class="main-panel">
        <header class="topbar">
          <div class="title-area">
            <div class="page-title">标准需求抽取与审查平台</div>
            <div class="page-badge">GUI Phase 1</div>
          </div>

          <div class="top-actions">
            <button class="action primary" type="button" data-testid="action-run-pipeline" @click="handleRunPipeline">运行抽取</button>
            <button class="action" type="button" data-testid="action-open-document" @click="handleOpenDocument">导入文档</button>
            <button class="action" type="button" @click="handleOpenOutput">打开输出目录</button>
            <button class="action" type="button" data-testid="action-export" @click="handleExport">导出</button>
            <label class="llm-toggle">
              <input v-model="llmMode" type="checkbox" />
              <span>LLM 富化模式</span>
            </label>
            <button class="action primary" type="button" data-testid="action-assemble" @click="handleAssemble">装配实现规格</button>
          </div>
        </header>

        <section class="workflow-card" data-testid="workflow-stepper">
          <div class="workflow-stepper">
            <div
              v-for="step in workflowSteps"
              :key="step.id"
              class="workflow-step"
              :class="step.status"
            >
              <div class="workflow-circle">{{ step.id }}</div>
              <div class="workflow-copy">
                <div class="workflow-title">{{ step.title }}</div>
                <div class="workflow-subtitle">{{ step.subtitle }}</div>
              </div>
            </div>
          </div>

          <div class="summary-grid">
            <article v-for="card in liveSummaryCards" :key="card.label" class="summary-card" :class="`tone-${card.tone}`">
              <div class="summary-label">{{ card.label }}</div>
              <div class="summary-value">{{ card.value }}</div>
              <div v-if="card.delta !== undefined" class="summary-delta">{{ card.delta }}</div>
            </article>

            <article class="summary-card distribution-card">
              <div class="summary-label">置信度分布</div>
              <div class="distribution-list">
                <div v-for="item in liveConfidenceDistribution" :key="item.label" class="distribution-row">
                  <div class="distribution-track">
                    <div class="distribution-fill" :class="`tone-${item.tone}`" :style="{ width: `${item.percent}%` }" />
                  </div>
                  <div class="distribution-caption">{{ item.label }} {{ item.value }} ({{ item.percent }}%)</div>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section v-if="isReviewWorkspace" class="workspace-grid">
          <section class="table-card">
            <div class="filters-panel">
              <div class="filter-row">
                <select v-model="typeFilter" class="filter-select">
                  <option v-for="item in typeOptions" :key="item" :value="item">{{ item }}</option>
                </select>
                <select v-model="statusFilter" class="filter-select">
                  <option v-for="item in statusOptions" :key="item" :value="item">{{ statusOptionLabel(item) }}</option>
                </select>
                <select v-model.number="confidenceFilter" class="filter-select">
                  <option :value="0">全部置信度</option>
                  <option :value="0.7">≥ 0.70</option>
                  <option :value="0.8">≥ 0.80</option>
                  <option :value="0.9">≥ 0.90</option>
                </select>
                <label class="switch-label">
                  <input v-model="ambiguousOnly" type="checkbox" />
                  <span>仅看歧义</span>
                </label>
                <input v-model="searchText" class="search-input" type="search" placeholder="搜索需求、对象或编号" />
              </div>

              <div class="toolbar-row">
                <button class="toolbar-button primary" type="button">批量审查</button>
                <button class="toolbar-button" type="button">接受</button>
                <button class="toolbar-button" type="button">拒绝</button>
                <button class="toolbar-button" type="button">标记歧义</button>
                <button class="toolbar-button" type="button">发起讨论</button>
                <div class="toolbar-note">已选择 0 项</div>
              </div>
            </div>

            <div class="table-wrap" data-testid="requirement-table">
              <table>
                <thead>
                  <tr>
                    <th class="check-col"></th>
                    <th>编号</th>
                    <th>类型</th>
                    <th>对象</th>
                    <th>需求（中文）</th>
                    <th>置信度</th>
                    <th>状态</th>
                    <th>歧义</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in filteredRequirements"
                    :key="row.id"
                    :class="{ selected: row.id === selectedRequirementId }"
                    :data-testid="`row-${row.id}`"
                    @click="selectRequirement(row.id)"
                  >
                    <td class="check-col">
                      <input type="checkbox" :checked="row.id === selectedRequirementId" @click.stop="selectRequirement(row.id)" />
                    </td>
                    <td class="id-cell">{{ row.id }}</td>
                    <td>
                      <span class="type-tag" :class="typeToneClass(row.type)">{{ row.type }}</span>
                    </td>
                    <td>{{ row.object }}</td>
                    <td>{{ row.chineseText }}</td>
                    <td>
                      <div class="confidence-cell">{{ row.confidence.toFixed(2) }}</div>
                    </td>
                    <td>
                      <span class="status-tag" :class="statusToneClass(row.status)" :data-testid="`row-status-${row.id}`">{{ statusDisplay(row.status) }}</span>
                    </td>
                    <td>
                      <span class="ambiguity-tag" :class="riskToneClass(row.ambiguity.level)">{{ row.ambiguity.level }}</span>
                    </td>
                    <td>
                      <span class="row-action">查看</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <footer class="table-footer">
              <div>{{ tableFooterText }}</div>
              <div class="pagination">
                <span>20 条/页</span>
                <span class="page active">1</span>
                <span class="page">2</span>
                <span class="page">3</span>
                <span class="page">4</span>
                <span class="page">5</span>
                <span class="page">…</span>
                <span class="page">6</span>
              </div>
            </footer>
          </section>

          <aside class="detail-card" data-testid="detail-panel">
            <div class="detail-head">
              <div>
                <div class="detail-id" data-testid="detail-title">{{ selectedRequirement.id }}</div>
                <div class="detail-subtitle">{{ selectedRequirement.object }} · {{ selectedRequirement.sourceDocument }}</div>
              </div>
              <span class="status-tag" :class="statusToneClass(selectedRequirement.status)" data-testid="detail-status">{{ statusDisplay(selectedRequirement.status) }}</span>
            </div>

            <div class="detail-tabs">
              <button v-for="tab in detailTabs" :key="tab" class="detail-tab" :class="{ active: currentTab === tab }" @click="currentTab = tab">
                {{ tab }}
              </button>
            </div>

            <div class="detail-stack">
              <section class="detail-section">
                <div class="section-title">原始需求（来自文档）</div>
                <div class="detail-body">
                  <div class="meta-line">来源：{{ selectedRequirement.sourceDocument }} · 位置：{{ selectedRequirement.sourceLocation }}</div>
                  <p>{{ selectedRequirement.originalText }}</p>
                </div>
              </section>

              <section class="detail-section">
                <div class="section-title">AI 抽取结果</div>
                <div class="detail-body">
                  <p>{{ selectedRequirement.chineseText }}</p>
                  <div class="metrics-grid">
                    <div><span>类型</span><strong>{{ selectedRequirement.type }}</strong></div>
                    <div><span>对象</span><strong>{{ selectedRequirement.object }}</strong></div>
                    <div><span>置信度</span><strong>{{ selectedRequirement.confidence.toFixed(2) }}</strong></div>
                  </div>
                  <div class="progress-wrap">
                    <div class="progress-label">置信度</div>
                    <div class="progress-track">
                      <div class="progress-fill" :style="{ width: `${selectedRequirement.confidence * 100}%` }" />
                    </div>
                  </div>
                </div>
              </section>

              <section class="detail-section">
                <div class="section-title">AI 理解与要点</div>
                <ul class="bullet-list">
                  <li v-for="point in selectedRequirement.keyPoints" :key="point">{{ point }}</li>
                </ul>
                <div class="note-box">{{ reviewNote }}</div>
              </section>

              <section class="detail-section">
                <div class="section-title">歧义风险提示</div>
                <span class="risk-badge" :class="riskToneClass(selectedRequirement.ambiguity.level)">{{ selectedRequirement.ambiguity.level }} 风险</span>
                <ul class="bullet-list risk-list">
                  <li v-for="reason in selectedRequirement.ambiguity.reasons" :key="reason">{{ reason }}</li>
                </ul>
              </section>

              <section class="detail-section">
                <div class="section-title">审查决策</div>
                <div class="decision-grid">
                  <button class="decision-button accept" type="button" data-testid="decision-accepted" @click="updateStatus('accepted')">接受</button>
                  <button class="decision-button reject" type="button" data-testid="decision-rejected" @click="updateStatus('rejected')">拒绝</button>
                  <button class="decision-button discuss" type="button" @click="updateStatus('needs_discussion')">发起讨论</button>
                  <button class="decision-button expert" type="button" @click="updateStatus('expert_pending')">交给专家</button>
                </div>
                <textarea class="comment-box" placeholder="请输入审查意见，支持 @ 提及回事，/ 快捷操作" />
                <div v-if="apiMessage" class="api-message">{{ apiMessage }}</div>
              </section>
            </div>
          </aside>
        </section>

        <section v-else class="module-page" data-testid="module-page">
          <div class="module-hero">
            <div class="module-kicker">{{ currentModule }}</div>
            <h2>{{ currentModule }}</h2>
            <p>{{ moduleDescriptions[currentModule] }}</p>
          </div>

          <div class="module-grid">
            <article v-for="item in modulePanels[currentModule]" :key="item.title" class="module-card">
              <div class="module-card-title">{{ item.title }}</div>
              <div class="module-card-body">{{ item.body }}</div>
            </article>
          </div>
        </section>
      </main>
    </div>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { NConfigProvider } from "naive-ui"
import { RequirementApiClient } from "./api-client"
import { confidenceDistribution, navGroups, requirements as mockRequirements, summaryCards, workflowSteps } from "./mock-data"
import { applyReviewState, mapBackendRequirement, statusDisplay as displayStatus } from "./requirement-mapper"
import type { DistributionItem, Requirement, ReviewStatus, SummaryCard } from "./types"

const activeNav = ref("审查工作区")
const currentModule = ref(activeNav.value)
const llmMode = ref(false)
const currentTab = ref("需求详情")
const apiClient = ref<RequirementApiClient | null>(null)
const apiMessage = ref("")
const currentInputPath = ref("")
const currentOutputDir = ref("")
const latestTaskSummary = ref<Record<string, unknown> | null>(null)

const moduleDescriptions: Record<string, string> = {
  工作台: "总览当前任务、流程和系统状态。",
  审查工作区: "在这里进行逐条审查、决策和讨论。",
  专家工作区: "转交复杂或高风险需求给专家。",
  装配规格: "把已审查需求映射到实现规格。",
  "术语/词库": "维护标准术语与同义词。",
  文档管理: "查看文档解析记录、版本和来源。",
  版本管理: "跟踪输出版本与差异。",
  审查统计: "查看审查进度、通过率和待处理数量。",
  质量分析: "分析低置信度、歧义和风险分布。",
  用户管理: "管理审查员和专家账号。",
  权限管理: "控制模块与动作权限。",
  设置中心: "调整本地工具与界面设置。",
}

const modulePanels: Record<string, Array<{ title: string; body: string }>> = {
  工作台: [{ title: "当前任务", body: "1 份文档正在审查，2 份待处理。" }],
  审查工作区: [{ title: "当前文档", body: "需求规格说明书_v2.1.docx" }],
  专家工作区: [{ title: "待专家确认", body: "高风险或歧义需求会在这里集中处理。" }],
  装配规格: [{ title: "规格映射", body: "从审查结果进入实现规格装配。" }],
  "术语/词库": [{ title: "术语同步", body: "支持标准术语、缩写和同义词维护。" }],
  文档管理: [{ title: "文档解析记录", body: "显示导入、抽取、审核和导出的文档链路。" }, { title: "版本列表", body: "按版本号查看文档快照与差异。" }],
  版本管理: [{ title: "输出版本", body: "管理每次导出的审查版本。" }],
  审查统计: [{ title: "审查进度", body: "展示待审查、已接受、待专家确认的汇总。" }],
  质量分析: [{ title: "低置信度分布", body: "帮助快速定位需要人工复核的需求。" }, { title: "歧义热点", body: "按对象、类型和风险聚类。" }],
  用户管理: [{ title: "用户列表", body: "审查员、专家和管理员账号。" }],
  权限管理: [{ title: "角色权限", body: "定义可见模块和可执行操作。" }],
  设置中心: [{ title: "界面设置", body: "配置主题、语言和桌面行为。" }],
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

const detailTabs = ["需求详情", "审查记录", "关联信息", "讨论 (2)"]
const typeOptions = computed(() => ["全部", ...Array.from(new Set(requirementRows.value.map((item) => item.type)))])
const statusOptions: Array<ReviewStatus | "全部"> = ["全部", "candidate", "llm_reviewed", "accepted", "rejected", "expert_pending", "needs_discussion", "needs_rework", "flagged", "frozen"]
const isReviewWorkspace = computed(() => currentModule.value === "审查工作区")

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

const selectedRequirement = computed(() => requirementRows.value.find((item) => item.id === selectedRequirementId.value) ?? requirementRows.value[0])
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
const liveSummaryCards = computed<SummaryCard[]>(() => {
  const total = requirementRows.value.length
  const accepted = countStatus("accepted")
  const expert = countStatus("expert_pending")
  const rejected = countStatus("rejected")
  const ambiguous = requirementRows.value.filter((item) => item.ambiguity.level !== "低").length
  if (!apiClient.value && !latestTaskSummary.value) return summaryCards
  return [
    { label: "总需求", value: total, tone: "blue" },
    { label: "待审查", value: countStatus("candidate") + countStatus("llm_reviewed"), tone: "orange" },
    { label: "已审查", value: accepted + expert + rejected, delta: total > 0 ? `${(((accepted + expert + rejected) / total) * 100).toFixed(1)}%` : "0.0%", tone: "green" },
    { label: "待专家确认", value: expert, tone: "purple" },
    { label: "岐义需求", value: ambiguous, tone: "red" },
  ]
})
const liveConfidenceDistribution = computed<DistributionItem[]>(() => {
  if (!apiClient.value && !latestTaskSummary.value) return confidenceDistribution
  const total = Math.max(1, requirementRows.value.length)
  const high = requirementRows.value.filter((item) => item.confidence >= 0.9).length
  const medium = requirementRows.value.filter((item) => item.confidence >= 0.7 && item.confidence < 0.9).length
  const low = requirementRows.value.filter((item) => item.confidence < 0.7).length
  return [
    { label: "≥ 0.90", value: high, percent: percentage(high, total), tone: "green" },
    { label: "0.70 - 0.90", value: medium, percent: percentage(medium, total), tone: "blue" },
    { label: "< 0.70", value: low, percent: percentage(low, total), tone: "red" },
  ]
})

onMounted(() => {
  loadInitialApiSession()
})

function setModule(item: string) {
  activeNav.value = item
  currentModule.value = item
}

function selectRequirement(id: string) {
  selectedRequirementId.value = id
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
  }
}

async function handleOpenOutput() {
  const session = await window.ratomizerDesktop?.openOutput()
  if (session && typeof session === "object" && "baseUrl" in session) {
    await loadFromSession(session)
  }
}

async function handleRunPipeline() {
  if (!currentInputPath.value) {
    await handleOpenDocument()
  }
  if (!currentInputPath.value || !window.ratomizerDesktop?.runPipeline) return
  apiMessage.value = "正在运行抽取与审查..."
  const outDir = currentOutputDir.value || defaultOutputDir(currentInputPath.value)
  const payload = await window.ratomizerDesktop.runPipeline({
    inputPath: currentInputPath.value,
    outDir,
    skipReview: false,
  })
  latestTaskSummary.value = objectValue(payload.summary)
  currentOutputDir.value = String(payload.out_dir || payload.outDir || outDir)
  apiMessage.value = "抽取与审查完成"
  await refreshAfterDesktopTask(currentOutputDir.value)
}

async function handleExport() {
  if (!currentOutputDir.value || !window.ratomizerDesktop?.exportRequirements) return
  const payload = await window.ratomizerDesktop.exportRequirements({ outDir: currentOutputDir.value, formats: ["csv", "md"] })
  latestTaskSummary.value = objectValue(payload.summary)
  apiMessage.value = `已导出：${(payload.written || []).join(", ")}`
}

async function handleAssemble() {
  if (!currentOutputDir.value || !window.ratomizerDesktop?.assembleSpec) return
  const payload = await window.ratomizerDesktop.assembleSpec({
    outDir: currentOutputDir.value,
    formats: ["xlsx", "docx", "md"],
    enrichRoute: undefined,
  })
  latestTaskSummary.value = objectValue(payload.summary)
  apiMessage.value = `已装配实现规格：${payload.count ?? 0} 条`
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
    if (rows.length > 0) {
      requirementRows.value = rows
      selectedRequirementId.value = rows[0].id
    }
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "需求加载失败"
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

function percentage(value: number, total: number) {
  return Number(((value / total) * 100).toFixed(1))
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null
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
</style>




