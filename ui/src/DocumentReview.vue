<script setup lang="ts">
import { computed, ref, watch } from "vue"
import type { AiRequirement, DocumentBlock, RequirementApiClient } from "./api-client"

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
type DocClient = Pick<RequirementApiClient, "loadDocument" | "loadAiRequirements" | "applyAiReviewAction">
const props = defineProps<{ client: DocClient | null; active: boolean }>()

const blocks = ref<DocumentBlock[]>([])
const requirements = ref<AiRequirement[]>([])
const loading = ref(false)
const message = ref("")
const selectedId = ref("")
const isSaving = ref(false)
const comment = ref("")
const moduleEdit = ref("")
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

// 被任意需求覆盖的块集合（含整段 source_block_ids），用于遗漏判定。
const coveredBlocks = computed(() => {
  const s = new Set<string>()
  for (const req of requirements.value) for (const b of req.source_block_ids || []) s.add(b)
  return s
})

const selectedReq = computed(() => requirements.value.find((r) => r.ai_req_id === selectedId.value) || null)
// 只高亮选中的片段（锚点小段），不把整个章节跨度刷蓝
const selectedSpan = computed(() => {
  const r = selectedReq.value
  const anchor = r?.anchor_block_id || (r?.source_block_ids || [])[0]
  return new Set(anchor ? [anchor] : [])
})

const omissionCount = computed(
  () => blocks.value.filter((b) => b.requirement_like && !b.noise && !coveredBlocks.value.has(b.block_id)).length,
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
  return Boolean(b.requirement_like) && !b.noise && !coveredBlocks.value.has(b.block_id)
}
function moduleOf(r: AiRequirement): string {
  return String(r.module_effective || r.module || (r.labels || [])[0] || "未分模块")
}
function statusOf(r: AiRequirement): string {
  return String(r.status || "draft")
}

function select(req: AiRequirement) {
  if (selectedId.value === req.ai_req_id) {  // 再点一下 → 取消选中
    selectedId.value = ""
    return
  }
  selectedId.value = req.ai_req_id
  comment.value = String(req.review_state?.reason || "")
  moduleEdit.value = moduleOf(req)
}

// 选中需求时，在锚段内的块里高亮 source_quote 原句。
function segments(b: DocumentBlock): Array<{ text: string; mark: boolean }> {
  const text = b.text || ""
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
      reason: comment.value, actor: "reviewer",
    })
    req.review_state = state
    req.status = state.status
    if (state.module_override) req.module_effective = state.module_override
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
      <button class="button" type="button" data-testid="doc-reload" :disabled="loading" @click="load">
        {{ loading ? "加载中" : "刷新" }}
      </button>
    </header>

    <div v-if="message" class="doc-message" data-testid="doc-message">{{ message }}</div>

    <div class="doc-body">
      <article class="doc-paper" data-testid="doc-paper">
        <template v-for="b in blocks" :key="b.block_id">
          <div
            :class="['doc-block',
                     { heading: isHeading(b), omission: isOmission(b),
                       anchored: anchorByBlock.get(b.block_id)?.length,
                       'in-span': selectedSpan.has(b.block_id) }]"
            :data-testid="isOmission(b) ? 'omission-block' : undefined"
            @click="anchorByBlock.get(b.block_id)?.length && select(anchorByBlock.get(b.block_id)![0])"
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
              >💬 {{ moduleOf(r) }}</button>
              <span v-if="isOmission(b)" class="omission-tag">⚠ 未覆盖</span>
            </div>
            <p class="doc-text">
              <template v-for="(seg, i) in segments(b)" :key="i"><mark v-if="seg.mark">{{ seg.text }}</mark><span v-else>{{ seg.text }}</span></template>
            </p>
          </div>
        </template>
      </article>

      <aside class="doc-detail" data-testid="doc-detail">
        <div v-if="!selectedReq" class="doc-detail-empty">点左侧 💬 批注查看需求详情</div>
        <div v-else class="doc-detail-card">
          <div class="dd-head">
            <span class="dd-module" data-testid="dd-module">{{ moduleOf(selectedReq) }}</span>
            <span class="dd-status" :class="'st-' + statusOf(selectedReq)">{{ STATUS_LABELS[statusOf(selectedReq)] || statusOf(selectedReq) }}</span>
          </div>
          <h3 class="dd-title">{{ selectedReq.title }}</h3>
          <div class="dd-meta">{{ selectedReq.type }} · {{ selectedReq.priority }} · {{ selectedReq.source_section }}</div>
          <div v-if="(selectedReq.suspicion_reasons || []).length" class="dd-suspicion" data-testid="dd-suspicion">
            ⚠ 建议优先复核：{{ (selectedReq.suspicion_reasons || []).join("、") }}
          </div>

          <div class="dd-section"><div class="dd-label">需求分析</div><div class="dd-body">{{ selectedReq.description }}</div></div>
          <div class="dd-section" v-if="(selectedReq.dev_guidance || []).length">
            <div class="dd-label">研发指引 / 落地实现</div>
            <ul class="dd-list"><li v-for="(g, i) in selectedReq.dev_guidance" :key="i">{{ g }}</li></ul>
          </div>
          <div class="dd-section" v-if="(selectedReq.acceptance_criteria || []).length">
            <div class="dd-label">测试指引 / 验收</div>
            <ul class="dd-list"><li v-for="(c, i) in selectedReq.acceptance_criteria" :key="i">{{ c }}</li></ul>
          </div>
          <div class="dd-section" v-if="selectedReq.source_quote">
            <div class="dd-label">原文引用</div><div class="dd-quote">{{ selectedReq.source_quote }}</div>
          </div>

          <div class="dd-section">
            <div class="dd-label">模块（可改）</div>
            <select v-model="moduleEdit" class="dd-select" data-testid="dd-module-select">
              <option v-for="m in MODULE_VOCAB" :key="m" :value="m">{{ m }}</option>
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
.doc-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 8px 14px; border-bottom: 1px solid #e2e8f0; }
.doc-stats { display: flex; gap: 18px; font-size: 13px; color: #475569; }
.doc-stats strong { color: #0f172a; }
.omission-stat.warn strong { color: #b45309; }
.doc-message { padding: 6px 14px; font-size: 12px; color: #b45309; background: #fffbeb; }
.doc-body { display: grid; grid-template-columns: 1fr 360px; gap: 0; flex: 1; min-height: 0; }
.doc-paper { overflow: auto; padding: 18px 22px; background: #fff; }
.doc-block { display: grid; grid-template-columns: 130px 1fr; gap: 10px; padding: 3px 6px; border-left: 3px solid transparent; cursor: default; }
.doc-block.heading .doc-text { font-weight: 700; color: #0f172a; margin-top: 8px; }
.doc-block.anchored { cursor: pointer; border-left-color: #3b82f6; background: #f8fafc; }
.doc-block.in-span { background: #eff6ff; }
.doc-block.omission { border-left-color: #f59e0b; border-left-style: dashed; }
.doc-gutter { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
.doc-text { margin: 0; font-size: 13px; line-height: 1.55; color: #334155; white-space: pre-wrap; }
.doc-text mark { background: #fde68a; padding: 0 1px; }
.anno-chip { font-size: 11px; border: 1px solid #cbd5e1; border-radius: 10px; padding: 1px 7px; background: #fff; cursor: pointer; max-width: 124px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anno-chip.sel { outline: 2px solid #3b82f6; }
.anno-chip.st-accepted { border-color: #16a34a; color: #16a34a; }
.anno-chip.st-rejected { border-color: #dc2626; color: #dc2626; }
.anno-chip.st-needs_discussion { border-color: #d97706; color: #d97706; }
.omission-tag { font-size: 10px; color: #b45309; }
.doc-detail { border-left: 1px solid #e2e8f0; overflow: auto; padding: 14px; background: #fafafa; }
.doc-detail-empty { color: #94a3b8; font-size: 13px; padding-top: 40px; text-align: center; }
.dd-head { display: flex; justify-content: space-between; align-items: center; }
.dd-module { font-weight: 700; color: #1d4ed8; }
.dd-status { font-size: 12px; padding: 1px 8px; border-radius: 8px; background: #e2e8f0; }
.dd-status.st-accepted { background: #dcfce7; color: #166534; }
.dd-status.st-rejected { background: #fee2e2; color: #991b1b; }
.dd-title { margin: 8px 0 2px; font-size: 15px; }
.dd-meta { font-size: 12px; color: #64748b; margin-bottom: 8px; }
.dd-suspicion { font-size: 12px; color: #92400e; background: #fef3c7; border-radius: 6px; padding: 4px 8px; margin-bottom: 8px; }
.dd-section { margin: 10px 0; }
.dd-label { font-size: 11px; color: #94a3b8; text-transform: uppercase; margin-bottom: 3px; }
.dd-body { font-size: 13px; line-height: 1.55; color: #334155; }
.dd-list { margin: 0; padding-left: 18px; font-size: 13px; color: #334155; }
.dd-quote { font-size: 12px; color: #475569; border-left: 3px solid #cbd5e1; padding-left: 8px; font-style: italic; }
.dd-select, .dd-comment { width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px; font-size: 13px; }
.dd-comment { min-height: 56px; margin-top: 8px; resize: vertical; }
.dd-actions { display: flex; gap: 8px; margin-top: 10px; }
</style>
