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
            <button class="button primary" type="button" data-testid="action-run-pipeline" :disabled="isRunning" @click="() => handleRunPipeline()">
              {{ isRunning ? "运行中" : "运行" }}
            </button>
            <button class="button" type="button" data-testid="action-test-pipeline" :disabled="isRunning" @click="handleRunPipeline({ llmReviewLimit: TEST_LLM_REVIEW_LIMIT })">测试运行</button>
            <button class="button" type="button" data-testid="action-open-document" @click="handleOpenDocument">导入文档</button>
            <button class="button" type="button" data-testid="action-select-output-dir" @click="handleOpenOutput">选择输出目录</button>
            <label class="llm-toggle">
              <input v-model="llmMode" type="checkbox" data-testid="llm-mode-toggle" />
              <span>LLM</span>
            </label>
            <button class="button primary" type="button" data-testid="action-ai-extract" :disabled="isRunning" @click="handleAiExtract">AI 抽取（双引擎）</button>
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
            <div class="run-meter-detail" data-testid="run-progress-detail">{{ runProgressDetail }}</div>
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
          <select v-model="moduleFilter" class="filter-select" aria-label="模块">
            <option v-for="item in moduleOptions" :key="item" :value="item">模块：{{ item }}</option>
          </select>
          <select v-model="categoryFilter" class="filter-select" aria-label="细分类">
            <option v-for="item in categoryOptions" :key="item" :value="item">细分类：{{ item }}</option>
          </select>
          <select v-model="typeFilter" class="filter-select" aria-label="类型">
            <option v-for="item in typeOptions" :key="item" :value="item">大类：{{ item }}</option>
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

        <section class="workspace right-detail-workspace" data-testid="workspace">
          <section class="table-panel">
            <div class="panel-head">
              <div>
                <div class="panel-title">需求表格</div>
                <div class="panel-subtitle">中文界面显示，底层状态与类型仍按后端原值处理</div>
              </div>
              <div class="panel-subtitle">{{ tableFooterText }}</div>
            </div>

            <div class="table-wrap independent-table-scroll" data-testid="requirement-table">
              <table>
                <thead>
                  <tr>
                    <th class="col-id">编号</th>
                    <th class="col-module">模块</th>
                    <th class="col-category">细分类</th>
                    <th class="col-type">大类</th>
                    <th class="col-object">对象</th>
                    <th>需求</th>
                    <th class="col-confidence">置信度</th>
                    <th class="col-status">状态</th>
                    <th class="col-amb">歧义</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="filteredRequirements.length === 0" data-testid="empty-requirements">
                    <td class="empty-cell" colspan="9">当前输出目录暂无需求</td>
                  </tr>
                  <tr
                    v-for="row in filteredRequirements"
                    :key="row.id"
                    :class="{ selected: row.id === selectedRequirementId }"
                    :data-testid="`row-${row.id}`"
                    @click="selectRequirement(row.id)"
                  >
                    <td class="id-cell">{{ row.id }}</td>
                    <td><span class="module-chip">{{ row.module || "未分模块" }}</span></td>
                    <td><span class="category-chip" :title="row.categoryCode">{{ row.category || row.categoryCode || "未分类" }}</span></td>
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

            <div class="detail-content independent-detail-scroll" data-testid="detail-scroll">
              <section class="readonly-card">
                <div class="readonly-head">① 原始需求</div>
                <div class="readonly-body">{{ selectedRequirement.originalText }}</div>
              </section>

              <section class="readonly-card">
                <div class="readonly-head">
                  <span>② 中文翻译</span>
                  <button
                    class="mini-button"
                    type="button"
                    data-testid="action-translate"
                    :disabled="isTranslating || selectedRequirement.id === emptyRequirement.id"
                    @click="handleTranslate"
                  >
                    {{ isTranslating ? "翻译中" : "翻译" }}
                  </button>
                </div>
                <div class="readonly-body muted" data-testid="translation-text">{{ translationText }}</div>
              </section>

              <section class="readonly-card">
                <div class="readonly-head">③ 原子化需求</div>
                <div class="readonly-body">{{ atomizedRequirementText }}</div>
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

              <section class="mini-row">
                <div class="mini-head">领域标签</div>
                <div class="mini-body">{{ domainTagText }}</div>
              </section>

              <section class="mini-row">
                <div class="mini-head">来源章节</div>
                <div class="mini-body">{{ sectionPathText }}</div>
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
                <button class="button" type="button" :disabled="isSubmitting" data-testid="decision-accepted" @click="updateStatus('accepted')">接受</button>
                <button class="button" type="button" :disabled="isSubmitting" data-testid="decision-rejected" @click="updateStatus('rejected')">拒绝</button>
                <button class="button" type="button" :disabled="isSubmitting" @click="updateStatus('needs_discussion')">讨论</button>
                <button class="button" type="button" :disabled="isSubmitting" @click="updateStatus('expert_pending')">专家</button>
              </div>
              <textarea v-model="reviewComment" class="comment-box" placeholder="请输入审查意见" />
              <div v-if="apiMessage" class="api-message" data-testid="api-message">{{ apiMessage }}</div>
            </div>
          </aside>
        </section>

        <footer class="status-bar">
          <span>输出目录：{{ currentOutputDir || "尚未选择输出目录" }}</span>
          <span class="kbd-hints">快捷键：A 接受 · R 拒绝 · D 讨论 · P 固定</span>
        </footer>
      </main>

      <div
        v-if="showSettingsPanel"
        class="settings-overlay"
        data-testid="settings-panel"
        role="dialog"
        aria-modal="true"
        aria-label="设置"
        @click.self="closeSettingsPanel"
      >
        <section class="settings-dialog">
          <header class="settings-head">
            <div>
              <div class="settings-title">设置</div>
              <div class="settings-subtitle">本地运行、LLM 富化和 ABNT 预设</div>
            </div>
            <button class="icon-button" type="button" data-testid="settings-close" aria-label="关闭设置" @click="closeSettingsPanel">×</button>
          </header>

          <div class="settings-body">
            <section class="settings-section">
              <div class="settings-section-title">运行模式与模型 API</div>
              <label class="settings-toggle">
                <input v-model="llmMode" type="checkbox" data-testid="settings-llm-mode" />
                <span>
                  <strong>LLM 富化</strong>
                  <small>开启后，翻译、装配规格富化和后续 LLM 审查都使用 openai_compatible 配置。</small>
                </span>
              </label>
              <div class="settings-form-grid">
                <label class="settings-field wide">
                  <span>Base URL</span>
                  <input v-model="llmSettings.baseUrl" data-testid="settings-base-url" type="url" placeholder="http://127.0.0.1:11434/v1" />
                </label>
                <label class="settings-field">
                  <span>模型名</span>
                  <input v-model="llmSettings.model" data-testid="settings-model" type="text" placeholder="qwen2.5:14b" />
                </label>
                <label class="settings-field">
                  <span>API Key 环境变量</span>
                  <input v-model="llmSettings.apiKeyEnv" data-testid="settings-api-key-env" type="text" placeholder="RATOMIZER_LLM_API_KEY" />
                </label>
                <label class="settings-field wide">
                  <span>API Key</span>
                  <input v-model="llmApiKey" data-testid="settings-api-key" type="password" placeholder="加密保存到本机配置文件" />
                </label>
                <label class="settings-field">
                  <span>Temperature</span>
                  <input v-model.number="llmSettings.temperature" data-testid="settings-temperature" type="number" min="0" max="2" step="0.1" />
                </label>
                <label class="settings-field">
                  <span>Max Tokens</span>
                  <input v-model.number="llmSettings.maxTokens" data-testid="settings-max-tokens" type="number" min="1" step="1" />
                </label>
                <label class="settings-field">
                  <span>超时（秒）</span>
                  <input v-model.number="llmSettings.timeoutS" data-testid="settings-timeout" type="number" min="1" step="1" />
                </label>
                <label class="settings-field">
                  <span>重试次数</span>
                  <input v-model.number="llmSettings.maxRetries" data-testid="settings-max-retries" type="number" min="0" step="1" />
                </label>
                <label class="settings-field">
                  <span>AI 抽取并发</span>
                  <input v-model.number="llmSettings.concurrency" data-testid="settings-concurrency" type="number" min="1" max="16" step="1" title="AI 抽取同时调用 LLM 的章节数；端点限流(429)时调低到 1-2" />
                </label>
              </div>
              <div class="settings-actions">
                <button class="button primary" type="button" data-testid="settings-save" :disabled="isSavingSettings" @click="handleSaveLlmSettings">
                  {{ isSavingSettings ? "保存中" : "保存配置" }}
                </button>
                <button class="button" type="button" data-testid="settings-test" :disabled="isTestingSettings" @click="handleTestLlmConnection">
                  {{ isTestingSettings ? "测试中" : "测试连接" }}
                </button>
                <span class="settings-status" data-testid="settings-status">{{ settingsStatus }}</span>
              </div>
            </section>

            <section class="settings-section">
              <div class="settings-section-title">当前会话</div>
              <div class="settings-row">
                <span>API 连接</span>
                <strong>{{ apiClient ? "已连接" : "未连接" }}</strong>
              </div>
              <div class="settings-row">
                <span>导入文档</span>
                <strong>{{ currentInputPath || "尚未选择" }}</strong>
              </div>
              <div class="settings-row">
                <span>输出目录</span>
                <strong>{{ currentOutputDir || "尚未选择" }}</strong>
              </div>
            </section>

            <section class="settings-section">
              <div class="settings-section-title">ABNT 默认预设</div>
              <div class="settings-row">
                <span>切片长度</span>
                <strong>{{ abntPreset.chunkChars.toLocaleString("zh-CN") }} 字符</strong>
              </div>
              <div class="settings-row">
                <span>领域包</span>
                <strong>{{ abntPreset.domainPackDir }}</strong>
              </div>
              <div class="settings-kb-list">
                <span>知识库</span>
                <ul>
                  <li v-for="path in abntPreset.kbPaths" :key="path">{{ path }}</li>
                </ul>
              </div>
            </section>
          </div>
        </section>
      </div>
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

type PhaseNavId = "review" | "document" | "ai" | "settings"
type StatFilter = "all" | "accepted" | "expert_pending" | "ambiguous"
type LlmSettings = {
  enabled: boolean
  baseUrl: string
  model: string
  apiKeyEnv: string
  temperature: number
  maxTokens: number
  timeoutS: number
  maxRetries: number
  concurrency: number
}

const phaseNavItems: Array<{ id: PhaseNavId; label: string; icon: string }> = [
  { id: "review", label: "审查", icon: "▣" },
  { id: "document", label: "文档", icon: "▤" },
  { id: "ai", label: "AI 抽取", icon: "✨" },
  { id: "settings", label: "设置", icon: "⚙" },
]

const activeNav = ref<PhaseNavId>("review")
const llmMode = ref(false)
const apiClient = ref<RequirementApiClient | null>(null)
const apiMessage = ref("")
const currentInputPath = ref("")
const currentOutputDir = ref("")
const isRunning = ref(false)
const isTranslating = ref(false)
const isSubmitting = ref(false)
const reviewComment = ref("")
const showSettingsPanel = ref(false)
const isSavingSettings = ref(false)
const isTestingSettings = ref(false)
const translationError = ref("")
const settingsStatus = ref("")
const llmApiKey = ref("")
const llmSettings = ref<LlmSettings>({
  enabled: false,
  baseUrl: "http://127.0.0.1:11434/v1",
  model: "qwen2.5:14b",
  apiKeyEnv: "RATOMIZER_LLM_API_KEY",
  temperature: 0,
  maxTokens: 1024,
  timeoutS: 60,
  maxRetries: 3,
  concurrency: 4,
})
const runProgress = ref(0)
const runStage = ref("待运行")
const runProgressDetail = ref("等待开始")
const latestTaskSummary = ref<Record<string, unknown> | null>(null)

const abntPreset = {
  chunkChars: 3500,
  kbPaths: [
    "knowledge_bases/energy_metering.json",
    "knowledge_bases/energy_metering_protocol_layer.json",
    "knowledge_bases/energy_metering_cosem_classes.json",
    "knowledge_bases/compiled_from_obsidian.json",
  ],
  domainPackDir: "domain_packs/dlms_cosem",
}
const TEST_LLM_REVIEW_LIMIT = 50

const emptyRequirement: Requirement = {
  id: "未选择需求",
  backendId: "",
  type: "功能",
  module: "未分模块",
  moduleCode: "",
  category: "未分类",
  categoryCode: "",
  object: "-",
  chineseText: "当前输出目录暂无需求。",
  originalText: "请选择文档运行抽取，或打开包含 atomic_requirements.jsonl 的输出目录。",
  translation: "",
  sourceDocument: "-",
  sourceLocation: "-",
  domainTags: [],
  sectionPath: [],
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
const moduleFilter = ref("全部")
const categoryFilter = ref("全部")
const statusFilter = ref("全部")
const confidenceFilter = ref(0)
const ambiguousOnly = ref(false)
const searchText = ref("")

const typeOptions = computed(() => ["全部", ...Array.from(new Set(requirementRows.value.map((item) => item.type)))])
const moduleOptions = computed(() => ["全部", ...Array.from(new Set(requirementRows.value.map((item) => item.module || "未分模块"))).sort()])
const categoryOptions = computed(() => ["全部", ...Array.from(new Set(requirementRows.value.map((item) => item.category || item.categoryCode || "未分类"))).sort()])
const statusOptions: Array<ReviewStatus | "全部"> = ["全部", "candidate", "llm_reviewed", "accepted", "rejected", "expert_pending", "needs_discussion", "needs_rework", "flagged", "frozen"]

const filteredRequirements = computed(() => requirementRows.value.filter((item) => {
  if (moduleFilter.value !== "全部" && (item.module || "未分模块") !== moduleFilter.value) return false
  if (categoryFilter.value !== "全部" && (item.category || item.categoryCode || "未分类") !== categoryFilter.value) return false
  if (typeFilter.value !== "全部" && item.type !== typeFilter.value) return false
  if (statusFilter.value !== "全部" && item.status !== statusFilter.value) return false
  if (item.confidence < confidenceFilter.value) return false
  if (ambiguousOnly.value && item.ambiguity.level === "低") return false
  if (searchText.value) {
    const haystack = [
      item.id,
      item.type,
      item.module,
      item.moduleCode,
      item.category,
      item.categoryCode,
      item.object,
      item.chineseText,
      item.originalText,
      ...(item.domainTags || []),
      ...(item.sectionPath || []),
    ].join(" ").toLowerCase()
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
const translationText = computed(() => {
  if (translationError.value) return translationError.value
  if (selectedRequirement.value.translation) return selectedRequirement.value.translation
  return "（尚未翻译，点击右上角“翻译”生成中文译文）"
})
const atomizedRequirementText = computed(() => selectedRequirement.value.chineseText || "（尚未生成原子化需求）")
const metadataRows = computed(() => [
  { key: "编号", value: selectedRequirement.value.id },
  { key: "模块", value: selectedRequirement.value.module || "未分模块" },
  { key: "细分类", value: selectedRequirement.value.category || selectedRequirement.value.categoryCode || "未分类" },
  { key: "原始分类", value: selectedRequirement.value.categoryCode || "-" },
  { key: "大类", value: selectedRequirement.value.type },
  { key: "对象", value: selectedRequirement.value.object },
  { key: "置信度", value: selectedRequirement.value.confidence.toFixed(2) },
  { key: "歧义", value: selectedRequirement.value.ambiguity.level },
  { key: "状态", value: statusDisplay(selectedRequirement.value.status) },
])
const domainTagText = computed(() => {
  const tags = selectedRequirement.value.domainTags || []
  return tags.length > 0 ? tags.join(" · ") : "暂无领域标签"
})
const sectionPathText = computed(() => {
  const path = selectedRequirement.value.sectionPath || []
  return path.length > 0 ? path.join(" > ") : "暂无章节路径"
})
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
  } else if (item === "ai") {
    void handleAiExtract()
  } else if (item === "settings") {
    showSettingsPanel.value = true
    void loadLlmSettings()
  }
}

function closeSettingsPanel() {
  showSettingsPanel.value = false
  if (activeNav.value === "settings") {
    activeNav.value = "review"
  }
}

async function loadLlmSettings() {
  const saved = await window.ratomizerDesktop?.getLlmSettings?.()
  if (saved) {
    applyLlmSettings(saved)
    settingsStatus.value = "已加载本机 API 设置"
  }
}

async function handleSaveLlmSettings() {
  isSavingSettings.value = true
  settingsStatus.value = ""
  try {
    const saved = await window.ratomizerDesktop?.saveLlmSettings?.(buildLlmSettingsPayload(true))
    if (saved) {
      applyLlmSettings(saved)
    }
    llmApiKey.value = ""
    settingsStatus.value = "配置已保存，API Key 已加密写入本机配置文件"
  } catch (error) {
    settingsStatus.value = error instanceof Error ? error.message : "保存配置失败"
  } finally {
    isSavingSettings.value = false
  }
}

async function handleTestLlmConnection() {
  isTestingSettings.value = true
  settingsStatus.value = ""
  try {
    const payload = await window.ratomizerDesktop?.testLlmConnection?.(buildLlmSettingsPayload(false))
    settingsStatus.value = payload?.message || "测试完成"
  } catch (error) {
    settingsStatus.value = error instanceof Error ? error.message : "测试连接失败"
  } finally {
    isTestingSettings.value = false
  }
}

function buildLlmSettingsPayload(includeApiKey: boolean): LlmSettings & { apiKey: string } {
  const payload = normalizeUiLlmSettings({
    ...llmSettings.value,
    enabled: llmMode.value,
  })
  return {
    ...payload,
    apiKey: includeApiKey ? llmApiKey.value.trim() : "",
  }
}

function applyLlmSettings(payload: Partial<LlmSettings>) {
  const normalized = normalizeUiLlmSettings(payload)
  llmSettings.value = normalized
  llmMode.value = normalized.enabled
}

function normalizeUiLlmSettings(payload: Partial<LlmSettings>): LlmSettings {
  return {
    enabled: Boolean(payload.enabled),
    baseUrl: stringOr(payload.baseUrl, "http://127.0.0.1:11434/v1"),
    model: stringOr(payload.model, "qwen2.5:14b"),
    apiKeyEnv: stringOr(payload.apiKeyEnv, "RATOMIZER_LLM_API_KEY"),
    temperature: numberOr(payload.temperature, 0),
    maxTokens: integerOr(payload.maxTokens, 1024),
    timeoutS: numberOr(payload.timeoutS, 60),
    maxRetries: integerOr(payload.maxRetries, 3),
    concurrency: Math.max(1, Math.min(16, integerOr(payload.concurrency, 4))),
  }
}

function stringOr(value: unknown, fallback: string) {
  const text = typeof value === "string" ? value.trim() : ""
  return text || fallback
}

function numberOr(value: unknown, fallback: number) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function integerOr(value: unknown, fallback: number) {
  const parsed = Number.parseInt(String(value), 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

function selectRequirement(id: string) {
  selectedRequirementId.value = id
  translationError.value = ""
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
  if (isSubmitting.value) return
  const row = requirementRows.value.find((item) => item.id === selectedRequirementId.value)
  if (!row) return
  apiMessage.value = ""
  if (!apiClient.value) {
    row.status = status
    return
  }
  isSubmitting.value = true
  try {
    const state = await apiClient.value.applyReviewAction({
      requirementId: row.backendId,
      status,
      actor: "vue3-ui",
      reason: reviewComment.value.trim() || `set ${status} from Vue3 UI`,
    })
    const index = requirementRows.value.findIndex((item) => item.id === row.id)
    if (index >= 0) {
      requirementRows.value[index] = applyReviewState(row, state)
    }
    reviewComment.value = ""
  } catch (error) {
    apiMessage.value = error instanceof Error ? error.message : "审查状态写入失败"
  } finally {
    isSubmitting.value = false
  }
}

async function handleTranslate() {
  const row = selectedRequirement.value
  if (!apiClient.value) {
    translationError.value = "请先连接输出目录后再翻译。"
    return
  }
  const sourceText = row.chineseText && row.chineseText !== "-" ? row.chineseText : row.originalText
  if (!sourceText || sourceText === "-") {
    translationError.value = "当前条目没有可翻译文本。"
    return
  }
  isTranslating.value = true
  translationError.value = ""
  apiMessage.value = ""
  try {
    const payload = await apiClient.value.translateRequirement({
      requirementId: row.backendId || row.id,
      text: sourceText,
      context: row.object,
    })
    const index = requirementRows.value.findIndex((item) => item.id === row.id)
    if (index >= 0) {
      requirementRows.value[index] = {
        ...requirementRows.value[index],
        translation: payload.translation,
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "翻译失败"
    translationError.value = message
    apiMessage.value = message
  } finally {
    isTranslating.value = false
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

async function handleRunPipeline(options: { llmReviewLimit?: number } = {}) {
  if (isRunning.value) return
  let stopProgress: (() => void) | undefined
  try {
    if (!currentInputPath.value) {
      apiMessage.value = "请先导入文档"
      runStage.value = "等待导入文档"
      runProgress.value = 0
      runProgressDetail.value = "尚未选择导入文档"
      return
    }
    if (!currentInputPath.value || !window.ratomizerDesktop?.runPipeline) return
    stopProgress = window.ratomizerDesktop.onTaskProgress?.(handleTaskProgress)
    const outDir = currentOutputDir.value || defaultOutputDir(currentInputPath.value)
    currentOutputDir.value = outDir
    isRunning.value = true
    runProgress.value = 8
    runStage.value = "准备运行"
    runProgressDetail.value = options.llmReviewLimit ? `测试运行：最多 AI 审查 ${options.llmReviewLimit} 条` : "准备启动本地任务"
    apiMessage.value = options.llmReviewLimit ? `正在测试运行，最多 AI 审查 ${options.llmReviewLimit} 条...` : "正在运行抽取与审查..."
    await nextUiTick()
    runProgress.value = 18
    runStage.value = "运行后端解析"
    runProgressDetail.value = "正在抽取原子化需求"
    const useLlmReview = llmMode.value || Boolean(options.llmReviewLimit)
    const payload = await window.ratomizerDesktop.runPipeline({
      inputPath: currentInputPath.value,
      outDir,
      skipReview: false,
      llmRoute: useLlmReview ? "openai_compatible" : undefined,
      reviewScope: useLlmReview ? "targeted" : undefined,
      ...(options.llmReviewLimit ? { llmReviewLimit: options.llmReviewLimit } : {}),
      ...abntPreset,
    })
    runProgress.value = 82
    runStage.value = "加载解析结果"
    runProgressDetail.value = "正在加载结果文件"
    latestTaskSummary.value = objectValue(payload.summary)
    currentOutputDir.value = String(payload.out_dir || payload.outDir || outDir)
    await refreshAfterDesktopTask(currentOutputDir.value)
    runProgress.value = 100
    runStage.value = "运行完成"
    runProgressDetail.value = options.llmReviewLimit ? `测试运行完成：最多 AI 审查 ${options.llmReviewLimit} 条` : "全部阶段完成"
    apiMessage.value = options.llmReviewLimit ? "测试运行完成" : "抽取与审查完成"
  } catch (error) {
    runStage.value = "运行失败"
    runProgressDetail.value = "请查看错误信息"
    apiMessage.value = error instanceof Error ? error.message : "抽取与审查失败"
  } finally {
    stopProgress?.()
    isRunning.value = false
  }
}

function handleTaskProgress(event: { stage: string; completed?: number; total?: number; percent?: number; model?: string }) {
  const completed = Math.max(0, Number(event.completed || 0))
  const total = Math.max(0, Number(event.total || 0))
  const percent = Number.isFinite(Number(event.percent)) ? Math.max(0, Math.min(100, Number(event.percent))) : 0
  if (event.stage === "ai_extract") {
    runStage.value = total ? `AI 抽取 ${completed}/${total} 章节` : "AI 抽取"
    runProgress.value = percent
    runProgressDetail.value = event.model ? `模型：${event.model} · 逐章节调用 LLM` : "逐章节调用 LLM 抽取行为需求"
    return
  }
  if (event.stage !== "llm_review") return
  runStage.value = total ? `AI 审查 ${completed}/${total}` : "AI 审查"
  runProgress.value = percent
  runProgressDetail.value = event.model ? `模型：${event.model}` : "模型正在逐条审查需求"
}

async function handleAiExtract() {
  if (isRunning.value) return
  if (!window.ratomizerDesktop?.aiExtract) {
    apiMessage.value = "当前环境不支持 AI 抽取（仅桌面应用可用）"
    return
  }
  if (!currentOutputDir.value) {
    runStage.value = "无法 AI 抽取"
    runProgressDetail.value = "请先「运行」管线生成输出目录，再执行 AI 抽取"
    apiMessage.value = "请先运行管线生成输出目录，再执行 AI 抽取"
    return
  }
  const usingLlm = llmMode.value
  let stopProgress: (() => void) | undefined
  isRunning.value = true
  stopProgress = window.ratomizerDesktop.onTaskProgress?.(handleTaskProgress)
  runStage.value = "AI 抽取（双引擎）"
  runProgress.value = usingLlm ? 5 : 40
  runProgressDetail.value = usingLlm
    ? "正在调用 LLM 抽取行为需求 + 合并确定性结构…（逐章节进度见上）"
    : "LLM 未启用：仅装配确定性结构规格…"
  try {
    const payload = await window.ratomizerDesktop.aiExtract({
      outDir: currentOutputDir.value,
      llmRoute: usingLlm ? "openai_compatible" : "stub",
    })
    latestTaskSummary.value = objectValue(payload.summary)
    const written = Array.isArray(payload.written) ? payload.written : []
    const merged = objectValue(payload.merged) as
      | { total?: number; ai_behavioral?: number; deterministic_structural?: number }
      | null
    const failed = Math.max(0, Number(payload.failed_sections || 0))
    runProgress.value = 100
    if (written.length === 0) {
      runStage.value = "AI 抽取未产出文件"
      runProgressDetail.value = "未写出任何交付物——请确认输出目录已先运行管线"
      apiMessage.value = "AI 抽取未写出文件：请确认已先运行管线"
      return
    }
    const total = merged?.total ?? payload.count ?? 0
    const breakdown =
      merged?.ai_behavioral != null || merged?.deterministic_structural != null
        ? `（AI 行为 ${merged?.ai_behavioral ?? 0} + 确定性结构 ${merged?.deterministic_structural ?? 0}）`
        : ""
    runStage.value = failed > 0 ? "AI 抽取完成（部分章节失败）" : "AI 抽取完成"
    runProgressDetail.value = `已写出 ${written.length} 个文件：${written.join("、")}`
    const failedNote = failed > 0
      ? `；${failed} 个章节 LLM 调用失败（请用「测试连接」确认端点/Key/超时）`
      : ""
    apiMessage.value = `AI 抽取${usingLlm ? "（双引擎）" : "（仅确定性结构）"}完成：共 ${total} 条${breakdown}，已产 ${written.join("、")}${failedNote}`
  } catch (error) {
    runStage.value = "AI 抽取失败"
    const message = error instanceof Error ? error.message : "AI 抽取失败"
    runProgressDetail.value = message
    apiMessage.value = message
  } finally {
    stopProgress?.()
    isRunning.value = false
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
  height: 100vh;
  overflow: hidden;
  background: #f6f7f9;
  color: #1f2937;
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
  letter-spacing: 0;
}

.side-nav {
  min-height: 0;
  overflow: auto;
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
  height: 100vh;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: 78px auto 118px 72px minmax(0, 1fr) 32px;
  overflow: hidden;
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
  min-height: 64px;
  display: grid;
  align-content: center;
  gap: 5px;
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

.run-meter-detail {
  min-width: 0;
  color: #526070;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 400px;
  background: #f6f7f9;
}

.table-panel,
.detail-panel {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
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
  overflow-x: auto;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable both-edges;
}

table {
  width: 100%;
  min-width: 1260px;
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
  width: 116px;
}

.col-module {
  width: 108px;
}

.col-category {
  width: 132px;
}

.col-type {
  width: 76px;
}

.col-object {
  width: 150px;
}

.col-confidence {
  width: 86px;
}

.col-status {
  width: 96px;
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
.module-chip,
.category-chip,
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

.module-chip,
.category-chip {
  color: #23506e;
  background: #eaf4f8;
}

.category-chip {
  color: #5b4b8f;
  background: #f1edff;
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
  min-height: 0;
}

.detail-content {
  min-height: 0;
  padding: 16px 18px 18px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
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

.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 28px;
  background: rgba(15, 23, 42, 0.36);
}

.settings-dialog {
  width: min(720px, 100%);
  max-height: min(760px, calc(100vh - 56px));
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.22);
}

.settings-head {
  min-height: 70px;
  padding: 16px 18px;
  border-bottom: 1px solid #dfe5ec;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.settings-title {
  color: #172033;
  font-size: 20px;
  line-height: 1.2;
  font-weight: 900;
}

.settings-subtitle {
  margin-top: 4px;
  color: #687386;
  font-size: 13px;
  font-weight: 700;
}

.icon-button {
  width: 34px;
  height: 34px;
  border: 1px solid #ccd5df;
  border-radius: 8px;
  background: #fff;
  color: #334155;
  display: grid;
  place-items: center;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}

.icon-button:hover {
  color: #1d57d3;
  border-color: #b9cdfb;
  background: #f8fbff;
}

.settings-body {
  min-height: 0;
  overflow: auto;
  padding: 18px;
  display: grid;
  gap: 14px;
  background: #f8fafc;
}

.settings-section {
  border: 1px solid #dfe5ec;
  border-radius: 10px;
  background: #fff;
  padding: 14px;
  display: grid;
  gap: 10px;
}

.settings-section-title {
  color: #172033;
  font-size: 14px;
  font-weight: 900;
}

.settings-toggle {
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid #e7ecf2;
  border-radius: 8px;
  background: #fbfcfe;
  padding: 10px 12px;
  color: #273344;
}

.settings-toggle input {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
}

.settings-toggle span {
  display: grid;
  gap: 3px;
}

.settings-toggle strong,
.settings-row strong,
.settings-kb-list li {
  color: #273344;
  font-size: 13px;
  font-weight: 900;
}

.settings-toggle small {
  color: #687386;
  font-size: 12px;
  line-height: 1.45;
}

.settings-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 12px;
}

.settings-field {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.settings-field.wide {
  grid-column: 1 / -1;
}

.settings-field span {
  color: #687386;
  font-size: 12px;
  font-weight: 800;
}

.settings-field input {
  width: 100%;
  height: 36px;
  border: 1px solid #ccd5df;
  border-radius: 8px;
  background: #fff;
  color: #273344;
  padding: 0 10px;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
}

.settings-field input:focus {
  outline: none;
  border-color: #7aa2f7;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

.settings-actions {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.settings-status {
  min-width: 0;
  color: #2156c7;
  font-size: 12px;
  font-weight: 800;
  overflow-wrap: anywhere;
}

.settings-row,
.settings-kb-list {
  min-width: 0;
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.settings-row span,
.settings-kb-list > span {
  color: #687386;
  font-size: 12px;
  font-weight: 800;
}

.settings-row strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.settings-kb-list ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 5px;
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




