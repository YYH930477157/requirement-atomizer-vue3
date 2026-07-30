<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue"
import {
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  Clock3,
  Database,
  Link2,
  Play,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Undo2,
  X,
} from "@lucide/vue"
import type {
  AiExtractionStatusPayload,
  ClaimCatalogViewPayload,
  ClaimCatalogViewRow,
  ClaimCoverageGroupView,
  ClaimMetricsViewPayload,
  ClaimQueueProposal,
  ClaimQueueViewPayload,
  ClaimRatioMetric,
  ClaimResolution,
  ClaimReviewEventView,
  ClaimViewEnvelope,
  RequirementApiClient,
} from "./api-client"

type ClaimLedgerClient = Pick<RequirementApiClient,
  "loadClaimCatalog" | "loadClaimLedger" | "loadClaimCoverageGroups" |
  "loadClaimMetrics" | "loadClaimReviewEvents" | "loadClaimQueue">
  & Partial<Pick<RequirementApiClient,
    "loadAiExtractionStatus" | "executeClaimQueue" | "applyClaimAdjudication" |
    "confirmClaimStructuralOverride">>

const props = withDefaults(defineProps<{
  client: ClaimLedgerClient | null
  active: boolean
  refreshToken?: number
  sessionKey?: string
}>(), { refreshToken: 0, sessionKey: "" })

type LedgerTab = "claims" | "queue"

const PAGE_SIZE = 25
const activeTab = ref<LedgerTab>("claims")
const resolutionFilter = ref<ClaimResolution | "">("")
const ownerFilter = ref("")
const offset = ref(0)
const loading = ref(false)
const detailLoading = ref(false)
const message = ref("")
const available = ref(false)
const catalog = ref<ClaimCatalogViewPayload | null>(null)
const metrics = ref<ClaimMetricsViewPayload | null>(null)
const queue = ref<ClaimQueueViewPayload | null>(null)
const extractionStatus = ref<AiExtractionStatusPayload | null>(null)
const revisionPin = ref("")
const selectedClaim = ref<ClaimCatalogViewRow | null>(null)
const detailGroups = ref<ClaimCoverageGroupView[]>([])
const detailEvents = ref<ClaimReviewEventView[]>([])
const queueBusyId = ref("")
const pendingQueueProposal = ref<ClaimQueueProposal | null>(null)
const queueAllowLlm = ref(false)
const queueMaxCalls = ref(4)
const queueTokenBudget = ref(50000)
const adjudicationBusy = ref(false)
const adjudicationReason = ref("")
const exclusionReason = ref<"scope_statement" | "definition" | "informative" | "example" | "instrument_only">("informative")
const structuralOverrideAllowLlm = ref(false)
let overviewGeneration = 0
let detailGeneration = 0

const rows = computed(() => catalog.value?.rows || [])
const total = computed(() => catalog.value?.total || 0)
const pageNumber = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const canGoBack = computed(() => offset.value > 0 && !loading.value)
const canGoForward = computed(() => offset.value + rows.value.length < total.value && !loading.value)
const ownerOptions = computed(() => {
  const values = new Set(catalog.value?.owner_unit_ids || [])
  for (const row of rows.value) {
    if (row.owner_unit_id) values.add(row.owner_unit_id)
  }
  if (ownerFilter.value) values.add(ownerFilter.value)
  return [...values].sort()
})

const metricCards = computed(() => {
  const effective = metrics.value?.effective_metrics
  return [
    { key: "inventory", label: "目录入账", metric: effective?.inventory_accounted_ratio },
    { key: "coverage", label: "验证覆盖", metric: effective?.verified_coverage_ratio },
    { key: "exclusion", label: "验证排除", metric: effective?.verified_exclusion_ratio },
    { key: "resolution", label: "有效结论", metric: effective?.eligible_resolution_ratio },
  ]
})

const legacyQuality = computed(() => extractionStatus.value?.quality || null)
const currentRevisionLabel = computed(() => {
  const revision = revisionPin.value.replace(/^sha256:/, "")
  return revision ? revision.slice(0, 12) : "—"
})

function sameEffectiveRevision(envelopes: ClaimViewEnvelope[]): boolean {
  return new Set(envelopes.map((payload) => payload.document_effective_revision)).size <= 1
}

function ratioLabel(metric?: ClaimRatioMetric): string {
  if (!metric || metric.value == null) return "—"
  return `${(metric.value * 100).toFixed(1)}%`
}

function ratioFraction(metric?: ClaimRatioMetric): string {
  if (!metric) return "—"
  return `${metric.numerator.toLocaleString("zh-CN")} / ${metric.denominator.toLocaleString("zh-CN")}`
}

function legacyPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—"
  return `${Number(value).toFixed(1)}%`
}

function resolutionLabel(value: ClaimResolution): string {
  if (value === "covered") return "已覆盖"
  if (value === "excluded") return "已排除"
  return "待确认"
}

function eventLabel(value: ClaimReviewEventView["event_kind"]): string {
  if (value === "target_invalidated") return "目标失效"
  if (value === "target_reactivated") return "目标恢复"
  if (value === "expert_adjudication") return "专家裁决"
  if (value === "audit_conflict") return "裁决冲突"
  return "结构复核"
}

function formatLocator(locator: ClaimCatalogViewRow["locator"] | undefined): string {
  if (!locator) return "—"
  const parts = [locator.block_id]
  if (locator.row_index != null) parts.push(`row ${locator.row_index}`)
  if (locator.line != null) parts.push(`line ${locator.line}`)
  if (locator.start != null || locator.end != null) {
    parts.push(`${locator.start ?? "?"}:${locator.end ?? "?"}`)
  }
  return parts.filter(Boolean).join(" · ")
}

function evidenceText(group: ClaimCoverageGroupView): string[] {
  return group.edges.flatMap((edge) => (edge.produced_evidence || [])
    .map((evidence) => String(evidence.text || "").trim())
    .filter(Boolean))
}

function groupIsReused(group: ClaimCoverageGroupView): boolean {
  return group.reused === true || group.validation_reused === true || group.effective_reused === true
}

function newIdempotencyKey(prefix: string): string {
  const suffix = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${suffix}`
}

function queueLifecycleLabel(proposal: ClaimQueueProposal): string {
  if (proposal.lifecycle === "executing") return "执行中"
  if (proposal.lifecycle === "executed") return "已执行"
  if (proposal.lifecycle === "rebuild_pending") return "待重建"
  if (proposal.latest_attempt?.lifecycle === "failed") return "上次失败"
  if (proposal.latest_attempt?.lifecycle === "aborted_stale") return "输入已变化"
  if (proposal.latest_attempt?.lifecycle === "interrupted") return "上次中断"
  return "待执行"
}

function canExecuteProposal(proposal: ClaimQueueProposal): boolean {
  return !proposal.focus_error
    && ["open", "rebuild_pending"].includes(proposal.lifecycle)
    && !queueBusyId.value
}

const queueAuthorizationValid = computed(() => queueAllowLlm.value
    && Number.isInteger(queueMaxCalls.value)
    && queueMaxCalls.value > 0
    && Number.isInteger(queueTokenBudget.value)
    && queueTokenBudget.value > 0)

function resetQueueAuthorization(): void {
  pendingQueueProposal.value = null
  queueAllowLlm.value = false
}

function requestProposalExecution(proposal: ClaimQueueProposal): void {
  if (!props.client?.executeClaimQueue || !canExecuteProposal(proposal)) return
  resetQueueAuthorization()
  pendingQueueProposal.value = proposal
}

async function executeProposal(): Promise<void> {
  const client = props.client
  const proposal = pendingQueueProposal.value
  if (!client?.executeClaimQueue || !proposal || !canExecuteProposal(proposal) || !queueAuthorizationValid.value) return
  queueBusyId.value = proposal.proposal_id
  message.value = ""
  try {
    const requestKey = proposal.lifecycle === "rebuild_pending"
      ? String(proposal.latest_attempt?.request_idempotency_key || "")
      : newIdempotencyKey("claim-queue")
    if (!requestKey) throw new Error("重建恢复缺少原请求标识")
    const result = await client.executeClaimQueue({
      proposalId: proposal.proposal_id,
      expectedClaimEffectiveRevision: proposal.claim_effective_revision,
      actor: "reviewer",
      allowLlm: true,
      route: "openai_compatible",
      maximumCalls: queueMaxCalls.value,
      totalTokenBudget: queueTokenBudget.value,
      requestIdempotencyKey: requestKey,
    })
    message.value = result.lifecycle === "executed"
      ? "Claim 已执行并完成账本重建"
      : `Claim 状态：${result.lifecycle}`
    await loadOverview(false)
  } catch (error) {
    message.value = error instanceof Error ? error.message : "Claim 执行失败"
    await loadOverview(false)
  } finally {
    queueBusyId.value = ""
    resetQueueAuthorization()
  }
}

function currentExpertFactHashes(): string[] {
  return detailEvents.value
    .filter((event) => event.event_kind === "expert_adjudication")
    .map((event) => String(event.event_hash || ""))
    .filter(Boolean)
    .slice(-1)
}

function supersededFactHashes(row: ClaimCatalogViewRow): string[] {
  const base = row.base_resolution_fact_hashes || {}
  const positiveFacts = base.positive || []
  const negativeFacts = base.negative || []
  const baseFacts = positiveFacts.length && negativeFacts.length
    ? [...positiveFacts, ...negativeFacts]
    : row.resolution === "covered"
      ? positiveFacts
      : row.resolution === "excluded"
        ? negativeFacts
        : []
  return [...new Set([...baseFacts, ...currentExpertFactHashes()])]
}

async function adjudicateClaim(
  adjudication: "covered" | "excluded_non_normative" | "reopen",
): Promise<void> {
  const client = props.client
  const row = selectedClaim.value
  const reason = adjudicationReason.value.trim()
  if (!client?.applyClaimAdjudication || !row || !row.claim_hash || !row.claim_effective_revision || !reason) {
    message.value = "请填写裁决理由并刷新 Claim 详情"
    return
  }
  let evidence
  if (adjudication === "covered") {
    const group = detailGroups.value.find((item) =>
      (item.effective_status || item.status) === "validated" && item.coverage_group_hash)
    if (!group?.coverage_group_hash) {
      message.value = "当前没有可用于裁决的已验证 coverage group"
      return
    }
    evidence = {
      kind: "coverage_group" as const,
      coverage_group_id: group.coverage_group_id,
      coverage_group_hash: group.coverage_group_hash,
    }
  } else {
    if (!row.source_text_hash) {
      message.value = "当前 Claim 缺少可复核的源证据哈希"
      return
    }
    evidence = {
      kind: "source_exclusion" as const,
      source_locator: row.locator,
      source_text_hash: row.source_text_hash,
      exclusion_reason: exclusionReason.value,
    }
  }
  adjudicationBusy.value = true
  message.value = ""
  try {
    await client.applyClaimAdjudication({
      claimId: row.claim_id,
      claimHash: row.claim_hash,
      adjudication,
      reason,
      evidence,
      actor: "reviewer",
      expectedClaimEffectiveRevision: row.claim_effective_revision,
      supersedesFactHashes: supersededFactHashes(row),
      requestIdempotencyKey: newIdempotencyKey("claim-adjudication"),
    })
    adjudicationReason.value = ""
    closeDetails()
    await loadOverview(false)
  } catch (error) {
    message.value = error instanceof Error ? error.message : "Claim 裁决失败"
    await loadOverview(false)
  } finally {
    adjudicationBusy.value = false
  }
}

const structuralOverrideReason = computed(() => {
  const exclusion = selectedClaim.value?.exclusion
  if (!exclusion || typeof exclusion !== "object") return ""
  return String((exclusion as Record<string, unknown>).reason || "")
})

const structuralVerifierBudgetValid = computed(() => !structuralOverrideAllowLlm.value || (
  Number.isInteger(queueMaxCalls.value)
  && queueMaxCalls.value > 0
  && Number.isInteger(queueTokenBudget.value)
  && queueTokenBudget.value > 0
))

async function confirmStructuralOverride(): Promise<void> {
  const client = props.client
  const row = selectedClaim.value
  const reason = adjudicationReason.value.trim()
  if (
    !client?.confirmClaimStructuralOverride
    || !row?.claim_hash
    || !row.claim_effective_revision
    || structuralOverrideReason.value !== "repeated_page_furniture"
    || !catalog.value?.catalog_generation_id
    || !reason
    || !structuralVerifierBudgetValid.value
  ) return
  const allowLlm = structuralOverrideAllowLlm.value
  adjudicationBusy.value = true
  try {
    await client.confirmClaimStructuralOverride({
      claimId: row.claim_id,
      claimHash: row.claim_hash,
      expectedCatalogGenerationId: catalog.value.catalog_generation_id,
      expectedClaimEffectiveRevision: row.claim_effective_revision,
      priorStructuralReason: "repeated_page_furniture",
      reason,
      actor: "reviewer",
      requestIdempotencyKey: newIdempotencyKey("claim-structural"),
      allowLlm,
      route: allowLlm ? "openai_compatible" : "stub",
      verifierMaxCalls: allowLlm ? queueMaxCalls.value : 0,
      verifierMaxTotalTokens: allowLlm ? queueTokenBudget.value : 0,
    })
    closeDetails()
    await loadOverview(false)
  } catch (error) {
    message.value = error instanceof Error ? error.message : "结构复核失败"
    await loadOverview(false)
  } finally {
    adjudicationBusy.value = false
  }
}

async function loadOverview(allowRetry = true): Promise<boolean> {
  const client = props.client
  if (!client) {
    available.value = false
    message.value = "未连接输出目录"
    return false
  }
  const generation = ++overviewGeneration
  loading.value = true
  message.value = ""
  try {
    const [nextCatalog, nextMetrics, nextQueue, nextExtraction] = await Promise.all([
      client.loadClaimCatalog({
        resolution: resolutionFilter.value,
        ownerUnitId: ownerFilter.value,
        limit: PAGE_SIZE,
        offset: offset.value,
      }),
      client.loadClaimMetrics(),
      client.loadClaimQueue(),
      client.loadAiExtractionStatus?.().catch(() => null) ?? Promise.resolve(null),
    ])
    if (generation !== overviewGeneration || client !== props.client) return false
    if (!sameEffectiveRevision([nextCatalog, nextMetrics, nextQueue])) {
      if (allowRetry) return loadOverview(false)
      message.value = "账本版本正在切换，本次响应已丢弃"
      return false
    }

    catalog.value = nextCatalog
    metrics.value = nextMetrics
    queue.value = nextQueue
    extractionStatus.value = nextExtraction
    revisionPin.value = nextCatalog.document_effective_revision || ""
    available.value = nextCatalog.available && nextMetrics.available && nextQueue.available
    if (!available.value) {
      selectedClaim.value = null
      detailGroups.value = []
      detailEvents.value = []
      message.value = nextCatalog.reason || nextMetrics.reason || nextQueue.reason || "当前输出目录没有 Claim Ledger"
      return true
    }

    if (selectedClaim.value) {
      const refreshed = nextCatalog.rows.find((row) => row.claim_id === selectedClaim.value?.claim_id)
      selectedClaim.value = refreshed || null
      if (!refreshed) {
        detailGroups.value = []
        detailEvents.value = []
      }
    }
    if (!nextMetrics.effective_fresh) message.value = "账本待刷新：当前显示的是最近一次已提交快照"
    return true
  } catch (error) {
    if (generation === overviewGeneration && client === props.client) {
      message.value = error instanceof Error ? error.message : "Claim Ledger 加载失败"
    }
    return false
  } finally {
    if (generation === overviewGeneration) loading.value = false
  }
}

async function applyFilters() {
  offset.value = 0
  closeDetails()
  await loadOverview()
}

async function goPage(direction: -1 | 1) {
  const nextOffset = Math.max(0, offset.value + direction * PAGE_SIZE)
  if (nextOffset === offset.value) return
  offset.value = nextOffset
  closeDetails()
  await loadOverview()
}

async function openDetails(row: ClaimCatalogViewRow) {
  adjudicationReason.value = ""
  structuralOverrideAllowLlm.value = false
  selectedClaim.value = row
  detailGroups.value = []
  detailEvents.value = []
  await loadDetails(row.claim_id, true)
}

async function loadDetails(claimId: string, allowRefresh: boolean): Promise<void> {
  const client = props.client
  if (!client || !revisionPin.value) return
  const expectedRevision = revisionPin.value
  const generation = ++detailGeneration
  detailLoading.value = true
  try {
    const [groups, events] = await Promise.all([
      client.loadClaimCoverageGroups(claimId),
      client.loadClaimReviewEvents(claimId),
    ])
    if (generation !== detailGeneration || client !== props.client) return
    const revisionMatches = groups.document_effective_revision === expectedRevision
      && events.document_effective_revision === expectedRevision
      && revisionPin.value === expectedRevision
    if (!revisionMatches) {
      detailGroups.value = []
      detailEvents.value = []
      message.value = "详情与主列表版本不同，异代响应已丢弃"
      if (allowRefresh) {
        const refreshed = await loadOverview(false)
        if (refreshed && selectedClaim.value?.claim_id === claimId) {
          await loadDetails(claimId, false)
        }
      }
      return
    }
    detailGroups.value = groups.groups || []
    detailEvents.value = events.events || []
  } catch (error) {
    if (generation === detailGeneration) {
      message.value = error instanceof Error ? error.message : "Claim 详情加载失败"
    }
  } finally {
    if (generation === detailGeneration) detailLoading.value = false
  }
}

function closeDetails() {
  detailGeneration += 1
  selectedClaim.value = null
  detailGroups.value = []
  detailEvents.value = []
  adjudicationReason.value = ""
  structuralOverrideAllowLlm.value = false
  detailLoading.value = false
}

function selectLedgerTab(tab: LedgerTab): void {
  if (tab !== activeTab.value) resetQueueAuthorization()
  activeTab.value = tab
}

watch(
  [() => props.active, () => props.client, () => props.sessionKey, () => props.refreshToken],
  ([active]) => {
    resetQueueAuthorization()
    if (active) void loadOverview()
  },
  { immediate: true },
)

onUnmounted(() => {
  overviewGeneration += 1
  detailGeneration += 1
})
</script>

<template>
  <section class="claim-ledger" data-testid="claim-ledger">
    <header class="ledger-head">
      <div>
        <div class="ledger-title-row">
          <h4>Claim Ledger</h4>
          <span class="observation-badge">双写观察期 · 不影响 READY 判定</span>
        </div>
        <p>Revision <code>{{ currentRevisionLabel }}</code></p>
      </div>
      <button class="icon-command" type="button" aria-label="刷新 Claim Ledger" title="刷新 Claim Ledger"
              :disabled="loading || !client" data-testid="claim-refresh" @click="loadOverview()">
        <RefreshCw :size="17" :class="{ spin: loading }" aria-hidden="true" />
      </button>
    </header>

    <div v-if="message" class="ledger-message" role="status" data-testid="claim-message">
      <TriangleAlert :size="16" aria-hidden="true" />
      <span>{{ message }}</span>
    </div>

    <div v-if="!client" class="ledger-empty">
      <Database :size="28" aria-hidden="true" />
      <strong>未连接输出目录</strong>
    </div>
    <div v-else-if="!available && !loading" class="ledger-empty" data-testid="claim-unavailable">
      <Database :size="28" aria-hidden="true" />
      <strong>当前目录没有可用账本</strong>
    </div>

    <template v-else>
      <section class="ledger-status" aria-label="账本状态">
        <span class="status-item" :class="metrics?.document_ready ? 'ok' : 'neutral'">
          <CircleCheck :size="15" aria-hidden="true" />
          Ledger Ready：{{ metrics?.document_ready == null ? "—" : metrics.document_ready ? "是" : "否" }}
          <small>仅观察</small>
        </span>
        <span class="status-item" :class="metrics?.effective_fresh ? 'ok' : 'warn'">
          <Clock3 :size="15" aria-hidden="true" />
          {{ metrics?.effective_fresh ? "快照已同步" : "账本待刷新" }}
        </span>
      </section>

      <section class="metric-grid" aria-label="Claim Ledger 指标">
        <article v-for="card in metricCards" :key="card.key" class="metric-card"
                 :data-testid="`claim-metric-${card.key}`">
          <span>{{ card.label }}</span>
          <strong>{{ ratioLabel(card.metric) }}</strong>
          <small>{{ ratioFraction(card.metric) }}</small>
        </article>
      </section>

      <section class="comparison-band" aria-label="新旧覆盖口径对比">
        <article class="comparison-column">
          <header><span>旧覆盖口径</span><small>ai_extract_quality.json</small></header>
          <div class="comparison-values">
            <div><span>coverage_pct</span><strong>{{ legacyPercent(legacyQuality?.coverage_pct) }}</strong></div>
            <div><span>core_coverage_pct</span><strong>{{ legacyPercent(legacyQuality?.core_coverage_pct) }}</strong></div>
          </div>
        </article>
        <article class="comparison-column new">
          <header><span>Claim Ledger 口径</span><small>{{ metrics?.effective_metrics_version || "claim-effective-ledger/v1" }}</small></header>
          <div class="comparison-values">
            <div><span>verified_coverage_ratio</span><strong>{{ ratioLabel(metrics?.effective_metrics.verified_coverage_ratio) }}</strong></div>
            <div><span>eligible_resolution_ratio</span><strong>{{ ratioLabel(metrics?.effective_metrics.eligible_resolution_ratio) }}</strong></div>
          </div>
        </article>
      </section>

      <div class="ledger-tabs" role="tablist" aria-label="账本视图">
        <button type="button" role="tab" :aria-selected="activeTab === 'claims'"
                :class="{ active: activeTab === 'claims' }" @click="selectLedgerTab('claims')">Claims</button>
        <button type="button" role="tab" :aria-selected="activeTab === 'queue'"
                :class="{ active: activeTab === 'queue' }" @click="selectLedgerTab('queue')">执行队列</button>
      </div>

      <section v-if="activeTab === 'claims'" class="claim-table-section">
        <div class="claim-filters">
          <select v-model="resolutionFilter" aria-label="Claim 结论" @change="applyFilters">
            <option value="">结论：全部</option>
            <option value="covered">结论：已覆盖</option>
            <option value="excluded">结论：已排除</option>
            <option value="uncertain">结论：待确认</option>
          </select>
          <select v-model="ownerFilter" aria-label="Claim owner" @change="applyFilters">
            <option value="">Owner：全部</option>
            <option v-for="owner in ownerOptions" :key="owner" :value="owner">{{ owner }}</option>
          </select>
          <span class="claim-total">{{ total.toLocaleString("zh-CN") }} claims</span>
        </div>

        <div class="claim-table-wrap">
          <table class="claim-table">
            <thead><tr><th>结论</th><th>Claim</th><th>命题文本</th><th>精确定位</th><th>Owner</th></tr></thead>
            <tbody>
              <tr v-for="row in rows" :key="row.claim_id" tabindex="0" data-testid="claim-row"
                  @click="openDetails(row)" @keydown.enter="openDetails(row)">
                <td><span class="resolution-chip" :class="row.resolution">{{ resolutionLabel(row.resolution) }}</span></td>
                <td class="claim-id">{{ row.claim_id }}</td>
                <td class="claim-text">{{ row.text }}</td>
                <td class="locator">{{ formatLocator(row.locator) }}</td>
                <td class="owner">{{ row.owner_unit_id || "—" }}</td>
              </tr>
              <tr v-if="!rows.length && !loading"><td colspan="5" class="table-empty">当前过滤条件下没有 Claim</td></tr>
            </tbody>
          </table>
        </div>

        <footer class="pagination">
          <span>第 {{ pageNumber }} / {{ pageCount }} 页</span>
          <div>
            <button class="icon-command" type="button" :disabled="!canGoBack" aria-label="上一页" title="上一页" @click="goPage(-1)"><ChevronLeft :size="17" aria-hidden="true" /></button>
            <button class="icon-command" type="button" :disabled="!canGoForward" aria-label="下一页" title="下一页" @click="goPage(1)"><ChevronRight :size="17" aria-hidden="true" /></button>
          </div>
        </footer>
      </section>

      <section v-else class="queue-view" data-testid="claim-queue">
        <div class="queue-section">
          <header><h5>Claim 提案</h5><span>{{ queue?.proposals.length || 0 }}</span></header>
          <div class="queue-budget" data-testid="claim-queue-budget">
            <label>调用上限<input v-model.number="queueMaxCalls" type="number" min="1" step="1" /></label>
            <label>Token 上限<input v-model.number="queueTokenBudget" type="number" min="1" step="1000" /></label>
          </div>
          <div v-for="proposal in queue?.proposals || []" :key="proposal.proposal_id" class="queue-row">
            <span class="lifecycle-badge" :class="proposal.lifecycle">{{ queueLifecycleLabel(proposal) }}</span>
            <div>
              <strong>{{ proposal.claim_id }}</strong>
              <small>{{ formatLocator(proposal.locator) }}</small>
              <small v-if="proposal.focus_error" class="queue-error">{{ proposal.focus_error }}</small>
              <small v-else-if="proposal.latest_attempt?.outcome?.message">{{ proposal.latest_attempt.outcome.message }}</small>
            </div>
            <button class="execute-command" type="button"
                    :disabled="!canExecuteProposal(proposal)"
                    :title="proposal.lifecycle === 'rebuild_pending' ? '恢复账本重建' : '执行 Claim 定向抽取'"
                    :data-testid="`claim-execute-${proposal.claim_id}`"
                    @click="requestProposalExecution(proposal)">
              <RefreshCw v-if="queueBusyId === proposal.proposal_id" class="spin" :size="15" aria-hidden="true" />
              <Play v-else :size="15" aria-hidden="true" />
              {{ proposal.lifecycle === "rebuild_pending" ? "恢复" : "执行" }}
            </button>
          </div>
          <p v-if="!queue?.proposals.length" class="queue-empty">没有待处理 Claim 提案</p>
        </div>
        <div class="queue-section compat">
          <header><h5>兼容遗漏</h5><span>{{ queue?.compat_omissions.length || 0 }}</span></header>
          <div v-for="(omission, index) in queue?.compat_omissions || []"
               :key="omission.omission_id || omission.block_id || index" class="queue-row">
            <span class="dry-run-badge">dry-run</span>
            <div><strong>{{ omission.omission_id || omission.block_id || "整块遗漏" }}</strong><small>{{ omission.reason || "whole-block compatibility" }}</small></div>
            <code>compat_whole_block</code>
          </div>
          <p v-if="!queue?.compat_omissions.length" class="queue-empty">没有兼容遗漏项</p>
        </div>
      </section>
    </template>

    <div v-if="pendingQueueProposal" class="queue-confirm-layer" @click.self="resetQueueAuthorization">
      <section class="queue-confirm" role="dialog" aria-modal="true" aria-label="确认 Claim 队列执行"
               data-testid="claim-queue-confirm">
        <header>
          <div><h5>确认执行 Claim</h5><code>{{ pendingQueueProposal.claim_id }}</code></div>
          <button class="icon-command" type="button" aria-label="关闭执行确认" title="关闭"
                  :disabled="Boolean(queueBusyId)" @click="resetQueueAuthorization">
            <X :size="17" aria-hidden="true" />
          </button>
        </header>
        <p>本次定向补抽会调用 LLM。调用与 Token 均受以下上限约束。</p>
        <dl>
          <div><dt>Route</dt><dd><code>openai_compatible</code></dd></div>
          <div><dt>调用上限</dt><dd>{{ queueMaxCalls }}</dd></div>
          <div><dt>Token 上限</dt><dd>{{ queueTokenBudget.toLocaleString("zh-CN") }}</dd></div>
        </dl>
        <label class="queue-authorization">
          <input v-model="queueAllowLlm" type="checkbox" data-testid="claim-queue-allow-llm" />
          <span>我确认授权本次 LLM 调用及上述成本上限</span>
        </label>
        <footer>
          <button type="button" :disabled="Boolean(queueBusyId)" data-testid="claim-queue-cancel"
                  @click="resetQueueAuthorization">取消</button>
          <button class="execute-command" type="button"
                  :disabled="Boolean(queueBusyId) || !queueAuthorizationValid"
                  data-testid="claim-queue-confirm-execute" @click="executeProposal">
            <RefreshCw v-if="queueBusyId" class="spin" :size="15" aria-hidden="true" />
            <Play v-else :size="15" aria-hidden="true" />
            确认执行
          </button>
        </footer>
      </section>
    </div>

    <div v-if="selectedClaim" class="drawer-layer" @click.self="closeDetails">
      <aside class="claim-drawer" role="dialog" aria-modal="true" aria-label="Claim 详情" data-testid="claim-detail">
        <header class="drawer-head">
          <div><span class="resolution-chip" :class="selectedClaim.resolution">{{ resolutionLabel(selectedClaim.resolution) }}</span><h5>{{ selectedClaim.claim_id }}</h5></div>
          <button class="icon-command" type="button" aria-label="关闭详情" title="关闭详情" @click="closeDetails"><X :size="17" aria-hidden="true" /></button>
        </header>
        <div class="drawer-body">
          <section class="claim-source">
            <h6>Claim</h6>
            <p>{{ selectedClaim.text }}</p>
            <dl>
              <div><dt>Locator</dt><dd>{{ formatLocator(selectedClaim.locator) }}</dd></div>
              <div><dt>Owner</dt><dd>{{ selectedClaim.owner_unit_id || "—" }}</dd></div>
              <div><dt>Revision</dt><dd><code>{{ selectedClaim.claim_effective_revision || revisionPin }}</code></dd></div>
            </dl>
          </section>

          <div v-if="detailLoading" class="detail-loading"><RefreshCw class="spin" :size="18" aria-hidden="true" />加载同代详情</div>
          <template v-else>
            <section class="detail-section">
              <h6><Link2 :size="15" aria-hidden="true" />Coverage groups <span>{{ detailGroups.length }}</span></h6>
              <article v-for="group in detailGroups" :key="group.coverage_group_id" class="group-row" data-testid="claim-group">
                <header><strong>{{ group.coverage_group_id }}</strong><span>{{ group.validation_method }}</span><em v-if="groupIsReused(group)">reused</em></header>
                <p>{{ group.effective_status || group.status }}<span v-if="group.effective_reason || group.invalid_reason"> · {{ group.effective_reason || group.invalid_reason }}</span></p>
                <div v-for="edge in group.edges" :key="edge.edge_id || edge.target_requirement_id" class="edge-row">
                  <b>{{ edge.target_requirement_id || "target" }}</b>
                  <span>{{ edge.relation || "—" }} · {{ edge.target_review_eligibility || "unknown" }}</span>
                </div>
                <blockquote v-for="(text, index) in evidenceText(group)" :key="index">{{ text }}</blockquote>
              </article>
              <p v-if="!detailGroups.length" class="detail-empty">没有 coverage group</p>
            </section>

            <section class="detail-section">
              <h6><Clock3 :size="15" aria-hidden="true" />Review events <span>{{ detailEvents.length }}</span></h6>
              <ol class="event-list">
                <li v-for="event in detailEvents" :key="event.event_id" data-testid="claim-event">
                  <span class="event-dot"></span>
                  <div><strong>{{ eventLabel(event.event_kind) }}</strong><small>{{ event.recorded_at }}</small><p>{{ event.target_requirement_id || "—" }}<span v-if="event.reason"> · {{ event.reason }}</span></p></div>
                </li>
              </ol>
              <p v-if="!detailEvents.length" class="detail-empty">没有 review event</p>
            </section>

            <section v-if="client?.applyClaimAdjudication" class="detail-section adjudication-panel"
                     data-testid="claim-adjudication">
              <h6><ShieldCheck :size="15" aria-hidden="true" />专家裁决</h6>
              <textarea v-model="adjudicationReason" rows="3" placeholder="裁决理由" aria-label="Claim 裁决理由"></textarea>
              <div class="adjudication-row">
                <select v-model="exclusionReason" aria-label="非规范内容类型">
                  <option value="scope_statement">范围说明</option>
                  <option value="definition">术语定义</option>
                  <option value="informative">资料性内容</option>
                  <option value="example">示例</option>
                  <option value="instrument_only">仅仪器说明</option>
                </select>
                <button type="button" :disabled="adjudicationBusy || !adjudicationReason.trim()"
                        data-testid="claim-adjudicate-covered" @click="adjudicateClaim('covered')">
                  <ShieldCheck :size="15" aria-hidden="true" />确认覆盖
                </button>
                <button type="button" :disabled="adjudicationBusy || !adjudicationReason.trim()"
                        data-testid="claim-adjudicate-excluded" @click="adjudicateClaim('excluded_non_normative')">
                  <X :size="15" aria-hidden="true" />排除
                </button>
                <button v-if="selectedClaim.resolution !== 'uncertain'" type="button"
                        :disabled="adjudicationBusy || !adjudicationReason.trim()"
                        data-testid="claim-adjudicate-reopen" @click="adjudicateClaim('reopen')">
                  <Undo2 :size="15" aria-hidden="true" />重开
                </button>
              </div>
              <div v-if="structuralOverrideReason === 'repeated_page_furniture'"
                   class="structural-review" data-testid="claim-structural-review">
                <label class="structural-mode">
                  <input v-model="structuralOverrideAllowLlm" type="checkbox"
                         data-testid="claim-structural-llm" />
                  <span data-testid="claim-structural-mode">
                    {{ structuralOverrideAllowLlm ? "LLM 语义复核" : "确定性重建 · 0 LLM" }}
                  </span>
                </label>
                <div v-if="structuralOverrideAllowLlm" class="structural-budget"
                     data-testid="claim-structural-budget">
                  <label>调用上限<input v-model.number="queueMaxCalls" type="number" min="1" step="1" /></label>
                  <label>Token 上限<input v-model.number="queueTokenBudget" type="number" min="1" step="1000" /></label>
                </div>
                <button class="structural-command" type="button"
                        :disabled="adjudicationBusy || !adjudicationReason.trim() || !structuralVerifierBudgetValid"
                        data-testid="claim-structural-override" @click="confirmStructuralOverride">
                  <Undo2 :size="15" aria-hidden="true" />撤销页眉页脚排除
                </button>
              </div>
            </section>
          </template>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.claim-ledger {
  min-height: 100%;
  padding: 16px 20px 28px;
  color: #202124;
  background: #f6f7f9;
  overflow: auto;
}

.ledger-head {
  position: sticky;
  z-index: 3;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 58px;
  margin: -16px -20px 14px;
  padding: 10px 20px;
  border-bottom: 1px solid #dfe2e7;
  background: rgba(246, 247, 249, 0.94);
  backdrop-filter: blur(16px);
}

.ledger-title-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ledger-title-row h4 { margin: 0; font-size: 18px; letter-spacing: 0; }
.ledger-head p { margin: 3px 0 0; color: #70757d; font-size: 11px; }
.ledger-head code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }

.observation-badge,
.dry-run-badge,
.lifecycle-badge,
.resolution-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  border-radius: 5px;
  padding: 2px 7px;
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}

.observation-badge { color: #76520e; border: 1px solid #e1c375; background: #fff7d9; }
.dry-run-badge { color: #73480d; border: 1px solid #e1bf83; background: #fff6e5; }
.lifecycle-badge { color: #4d5560; border: 1px solid #cfd4da; background: #f5f6f7; }
.lifecycle-badge.executing { color: #145b78; border-color: #8ec6da; background: #edf8fc; }
.lifecycle-badge.executed { color: #24623f; border-color: #9bc9ad; background: #eef8f1; }
.lifecycle-badge.rebuild_pending { color: #7a4c08; border-color: #dfbd78; background: #fff7e7; }

.icon-command {
  display: inline-grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid #d5d9df;
  border-radius: 7px;
  color: #4a5058;
  background: #fff;
  cursor: pointer;
}
.icon-command:hover:not(:disabled) { border-color: #9aa2ad; color: #202124; }
.icon-command:disabled { opacity: .42; cursor: default; }

.ledger-message {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  border-left: 3px solid #d99a21;
  padding: 9px 11px;
  color: #70490d;
  background: #fff8e8;
  font-size: 13px;
}

.ledger-empty {
  display: grid;
  place-items: center;
  gap: 8px;
  min-height: 280px;
  color: #777d86;
}

.ledger-status { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.status-item { display: inline-flex; align-items: center; gap: 6px; min-height: 30px; padding: 4px 9px; border: 1px solid #dfe2e7; border-radius: 6px; background: #fff; font-size: 12px; }
.status-item small { color: #8a9098; }
.status-item.ok { color: #17663c; border-color: #b9dcc8; background: #edf8f1; }
.status-item.warn { color: #81520a; border-color: #ead19b; background: #fff8e8; }
.status-item.neutral { color: #555b64; }

.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.metric-card { min-width: 0; border: 1px solid #dfe2e7; border-radius: 7px; padding: 12px 14px; background: #fff; }
.metric-card > span { display: block; color: #686e76; font-size: 12px; }
.metric-card strong { display: block; margin: 7px 0 3px; font-size: 23px; letter-spacing: 0; }
.metric-card small { color: #8a9098; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }

.comparison-band { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 10px; border: 1px solid #dfe2e7; border-radius: 7px; background: #fff; overflow: hidden; }
.comparison-column { min-width: 0; padding: 13px 14px; }
.comparison-column + .comparison-column { border-left: 1px solid #dfe2e7; }
.comparison-column.new { box-shadow: inset 3px 0 #2b7a56; }
.comparison-column header { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.comparison-column header > span { font-weight: 680; }
.comparison-column header small { max-width: 55%; color: #8a9098; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.comparison-values { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 11px; }
.comparison-values div { min-width: 0; padding: 8px 9px; background: #f6f7f9; }
.comparison-values span { display: block; color: #6d737c; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.comparison-values strong { display: block; margin-top: 4px; font-size: 17px; }

.ledger-tabs { display: inline-flex; margin: 16px 0 10px; padding: 2px; border: 1px solid #d6dae0; border-radius: 7px; background: #e9ebef; }
.ledger-tabs button { min-height: 30px; border: 0; border-radius: 5px; padding: 5px 13px; color: #646a73; background: transparent; cursor: pointer; }
.ledger-tabs button.active { color: #1d2126; background: #fff; box-shadow: 0 1px 3px rgba(30, 34, 40, .12); }

.claim-table-section { border-top: 1px solid #dfe2e7; }
.claim-filters { display: flex; align-items: center; gap: 8px; min-height: 50px; }
.claim-filters select { min-height: 32px; max-width: 260px; border: 1px solid #d5d9df; border-radius: 6px; padding: 4px 30px 4px 9px; color: #343940; background: #fff; }
.claim-total { margin-left: auto; color: #747a83; font-size: 12px; }
.claim-table-wrap { border: 1px solid #dfe2e7; background: #fff; overflow-x: auto; }
.claim-table { width: 100%; min-width: 920px; border-collapse: collapse; table-layout: fixed; }
.claim-table th { height: 34px; padding: 7px 9px; color: #686e76; background: #f1f3f5; font-size: 11px; text-align: left; font-weight: 650; }
.claim-table th:nth-child(1) { width: 86px; }
.claim-table th:nth-child(2) { width: 180px; }
.claim-table th:nth-child(4) { width: 190px; }
.claim-table th:nth-child(5) { width: 180px; }
.claim-table td { height: 48px; border-top: 1px solid #eceef1; padding: 8px 9px; vertical-align: middle; font-size: 12px; }
.claim-table tbody tr { cursor: pointer; }
.claim-table tbody tr:hover, .claim-table tbody tr:focus { outline: none; background: #f3f8f5; }
.claim-id, .locator, .owner { color: #5e646d; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.claim-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resolution-chip.covered { color: #17663c; background: #e8f5ed; }
.resolution-chip.excluded { color: #5f6368; background: #eceef1; }
.resolution-chip.uncertain { color: #8b5108; background: #fff0d4; }
.table-empty { height: 110px !important; text-align: center; color: #858b93; }
.pagination { display: flex; align-items: center; justify-content: space-between; min-height: 48px; color: #6c727a; font-size: 12px; }
.pagination > div { display: flex; gap: 6px; }

.queue-view { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; border-top: 1px solid #dfe2e7; padding-top: 12px; }
.queue-section { min-width: 0; border: 1px solid #dfe2e7; border-radius: 7px; background: #fff; overflow: hidden; }
.queue-section > header { display: flex; align-items: center; justify-content: space-between; min-height: 42px; padding: 8px 12px; border-bottom: 1px solid #e5e7eb; background: #f2f4f6; }
.queue-section h5 { margin: 0; font-size: 13px; }
.queue-section > header > span { color: #747a83; font-size: 12px; }
.queue-budget { display: flex; align-items: end; gap: 10px; padding: 9px 11px; border-bottom: 1px solid #e5e7eb; }
.queue-budget label { display: grid; gap: 4px; color: #656b74; font-size: 10px; }
.queue-budget input { width: 112px; min-height: 30px; border: 1px solid #cfd4da; border-radius: 5px; padding: 4px 7px; background: #fff; }
.queue-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 10px; min-height: 58px; padding: 8px 11px; border-top: 1px solid #eef0f2; }
.queue-row:first-of-type { border-top: 0; }
.queue-row > div { min-width: 0; }
.queue-row strong, .queue-row small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue-row strong { font-size: 12px; }
.queue-row small { margin-top: 3px; color: #7a8088; font-size: 11px; }
.queue-row code { color: #5f6670; font-size: 10px; }
.queue-error { color: #a23c35 !important; white-space: normal !important; }
.execute-command,
.adjudication-row button,
.structural-command {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  border: 1px solid #aeb5bf;
  border-radius: 6px;
  padding: 5px 10px;
  color: #30363d;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
}
.execute-command:hover:not(:disabled),
.adjudication-row button:hover:not(:disabled),
.structural-command:hover:not(:disabled) { border-color: #567966; color: #24533a; background: #f1f8f3; }
.execute-command:disabled,
.adjudication-row button:disabled,
.structural-command:disabled { opacity: .45; cursor: default; }
.queue-empty { margin: 0; padding: 28px 12px; color: #858b93; text-align: center; }

.queue-confirm-layer { position: fixed; z-index: 35; inset: 0; display: grid; place-items: center; padding: 18px; background: rgba(28, 31, 36, .3); }
.queue-confirm { width: min(460px, 100%); border: 1px solid #d7dbe0; border-radius: 7px; padding: 16px; background: #fff; box-shadow: 0 16px 48px rgba(35, 39, 45, .22); }
.queue-confirm > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.queue-confirm h5 { margin: 0 0 4px; font-size: 15px; }
.queue-confirm > p { margin: 14px 0 10px; color: #5f6670; font-size: 12px; line-height: 1.5; }
.queue-confirm dl { margin: 0; border-block: 1px solid #e5e7eb; padding: 7px 0; }
.queue-confirm dl > div { display: grid; grid-template-columns: 100px minmax(0, 1fr); gap: 10px; padding: 4px 0; font-size: 12px; }
.queue-confirm dt { color: #737982; }
.queue-confirm dd { margin: 0; text-align: right; }
.queue-authorization { display: flex; align-items: flex-start; gap: 8px; margin: 13px 0; color: #5f4a23; font-size: 12px; line-height: 1.4; }
.queue-authorization input { flex: 0 0 auto; width: 16px; height: 16px; margin: 1px 0 0; accent-color: #3e7158; }
.queue-confirm > footer { display: flex; justify-content: flex-end; gap: 8px; }
.queue-confirm > footer > button { min-height: 32px; border: 1px solid #aeb5bf; border-radius: 6px; padding: 5px 11px; background: #fff; cursor: pointer; }
.queue-confirm > footer > button:disabled { opacity: .45; cursor: default; }

.drawer-layer { position: fixed; z-index: 30; inset: 0; display: flex; justify-content: flex-end; background: rgba(28, 31, 36, .26); }
.claim-drawer { width: min(620px, 94vw); height: 100%; border-left: 1px solid #d7dbe0; background: #fff; box-shadow: -12px 0 36px rgba(35, 39, 45, .18); overflow: hidden; }
.drawer-head { display: flex; align-items: center; justify-content: space-between; min-height: 62px; padding: 10px 16px; border-bottom: 1px solid #dfe2e7; }
.drawer-head > div { display: flex; align-items: center; gap: 9px; min-width: 0; }
.drawer-head h5 { margin: 0; font-size: 14px; }
.drawer-body { height: calc(100% - 62px); padding: 16px; overflow: auto; }
.claim-source h6, .detail-section h6 { margin: 0 0 8px; color: #444a52; font-size: 12px; text-transform: uppercase; }
.claim-source > p { margin: 0; padding: 11px 12px; border-left: 3px solid #4b876b; background: #f2f7f4; line-height: 1.55; }
.claim-source dl { margin: 11px 0 0; }
.claim-source dl > div { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 8px; padding: 5px 0; border-bottom: 1px solid #eef0f2; }
.claim-source dt { color: #7a8088; font-size: 11px; }
.claim-source dd { margin: 0; min-width: 0; overflow-wrap: anywhere; font-size: 11px; }
.detail-loading { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 160px; color: #70767f; }
.detail-section { margin-top: 20px; }
.detail-section h6 { display: flex; align-items: center; gap: 6px; }
.detail-section h6 span { margin-left: auto; color: #858b93; }
.adjudication-panel { border-top: 1px solid #dfe2e7; padding-top: 16px; }
.adjudication-panel textarea { width: 100%; resize: vertical; border: 1px solid #cfd4da; border-radius: 6px; padding: 8px; color: #202124; background: #fff; font: inherit; }
.adjudication-row { display: flex; align-items: center; gap: 8px; margin-top: 9px; flex-wrap: wrap; }
.adjudication-row select { min-height: 32px; border: 1px solid #cfd4da; border-radius: 6px; padding: 4px 7px; background: #fff; }
.structural-review { display: grid; gap: 9px; margin-top: 9px; border: 1px solid #ead9b8; border-radius: 6px; padding: 9px; background: #fffbf2; }
.structural-mode { display: flex; align-items: center; gap: 7px; color: #5f4a23; font-size: 11px; }
.structural-mode input { width: 16px; height: 16px; margin: 0; accent-color: #3e7158; }
.structural-budget { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.structural-budget label { display: grid; gap: 4px; color: #656b74; font-size: 10px; }
.structural-budget input { width: 100%; min-width: 0; min-height: 30px; border: 1px solid #cfd4da; border-radius: 5px; padding: 4px 7px; background: #fff; }
.structural-command { justify-self: start; border-color: #d2aa63; color: #6f470b; background: #fff8e9; }
.group-row { margin-top: 8px; border: 1px solid #dfe2e7; border-radius: 6px; padding: 10px; }
.group-row header { display: flex; align-items: center; gap: 8px; }
.group-row header strong { margin-right: auto; font-size: 11px; }
.group-row header span, .group-row header em { padding: 2px 5px; border-radius: 4px; background: #eef1f4; color: #626872; font-size: 10px; font-style: normal; }
.group-row header em { color: #17663c; background: #e6f4ec; }
.group-row > p { margin: 7px 0; color: #666d76; font-size: 11px; }
.edge-row { display: flex; justify-content: space-between; gap: 8px; padding: 6px 0; border-top: 1px solid #eef0f2; font-size: 11px; }
.edge-row span { color: #757b84; }
.group-row blockquote { margin: 6px 0 0; border-left: 2px solid #b9c4ce; padding-left: 8px; color: #515861; font-size: 11px; }
.event-list { margin: 0; padding: 0; list-style: none; }
.event-list li { position: relative; display: grid; grid-template-columns: 14px minmax(0, 1fr); gap: 7px; padding-bottom: 14px; }
.event-list li:not(:last-child)::before { content: ""; position: absolute; top: 12px; bottom: 0; left: 5px; width: 1px; background: #d6dbe0; }
.event-dot { z-index: 1; width: 11px; height: 11px; margin-top: 2px; border: 2px solid #fff; border-radius: 50%; background: #5d806f; box-shadow: 0 0 0 1px #aeb8b1; }
.event-list strong, .event-list small { display: block; }
.event-list strong { font-size: 12px; }
.event-list small { margin-top: 2px; color: #858b93; font-size: 10px; }
.event-list p { margin: 4px 0 0; color: #626872; font-size: 11px; }
.detail-empty { padding: 14px; color: #858b93; background: #f6f7f9; text-align: center; font-size: 11px; }
.spin { animation: claim-spin 900ms linear infinite; }
@keyframes claim-spin { to { transform: rotate(360deg); } }

@media (max-width: 920px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .comparison-band, .queue-view { grid-template-columns: minmax(0, 1fr); }
  .comparison-column + .comparison-column { border-top: 1px solid #dfe2e7; border-left: 0; }
  .comparison-column.new { box-shadow: inset 0 3px #2b7a56; }
}

@media (max-width: 620px) {
  .claim-ledger { padding-inline: 12px; }
  .ledger-head { margin-inline: -12px; padding-inline: 12px; }
  .metric-grid { grid-template-columns: minmax(0, 1fr); }
  .comparison-values { grid-template-columns: minmax(0, 1fr); }
  .claim-filters { align-items: stretch; flex-direction: column; padding-block: 10px; }
  .claim-filters select { width: 100%; max-width: none; }
  .claim-total { margin-left: 0; }
}
</style>
