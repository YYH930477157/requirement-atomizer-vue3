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

// 被任意需求覆盖的块集合（含整段 source_block_ids），用于遗漏判定。
const coveredBlocks = computed(() => {
  const s = new Set<string>()
  for (const req of requirements.value) for (const b of req.source_block_ids || []) s.add(b)
  return s
})

const selectedReq = computed(() => requirements.value.find((r) => r.ai_req_id === selectedId.value) || null)

// 块级三段式卡片：未覆盖段/背景段（与导出 HTML 同语义/同文案——双渲染器契约）。
// 目标：全文每一段都有分析结果——需求段有批注,其余段点开能看到为什么没生成需求+翻译+引用。
const OMISSION_REASON = "该段含规范性措辞（shall/must/应…），被判为疑似需求，但没有任何已抽取需求的来源范围覆盖它。可能原因：抽取遗漏（自检未补回）或该句实为背景说明。确属需求请反馈补抽；背景说明可忽略。"
const CONTEXT_REASON = "该段未检出规范性措辞（shall/must/应…），被判定为背景/说明性内容，因此没有生成研发需求；其信息会作为上下文供相邻需求的分析使用。如认为该段实际包含需求，请反馈补抽。"
const selectedBlockId = ref("")
const selectedBlock = computed(() => blocks.value.find((b) => b.block_id === selectedBlockId.value) || null)
const selectedBlockKind = computed(() => (selectedBlock.value && isOmission(selectedBlock.value) ? "omission" : "context"))
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
  const ids = [...(r?.source_block_ids || []), anchor].filter(Boolean) as string[]
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

// 排版保真：噪声（页眉/页脚/水印）不渲染；跨页处画分页线（与自包含 HTML 同语义）
const visibleBlocks = computed(() => blocks.value.filter((b) => !b.noise))

// 表格块渲染真 <table>（旧 out_dir 无 data_rows 时回退扁平文字段落）
const LIST_ITEM_RE = /^(?:[a-z0-9]{1,3}[).]|[•▪—–-])\s/
function isTable(b: DocumentBlock): boolean {
  return b.type === "table" && Boolean((b.data_rows || []).length || (b.header_rows || []).length)
}
function isListItem(b: DocumentBlock): boolean {
  return LIST_ITEM_RE.test(b.text || "")
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
function ownershipOf(r: AiRequirement): string {
  return String(r.ownership_effective || r.ownership || "software")
}
const OWNERSHIP_LABELS: Record<string, string> = { software: "软件", hardware: "硬件", co_design: "软硬件协同" }
// 富化产物消费（与导出 HTML 同语义——双渲染器契约）：analysis_source=llm 且非空 → 富化优先
function useEnriched(r: AiRequirement): boolean {
  return r.analysis_source === "llm"
}
function analysisNarrative(r: AiRequirement): { text: string; enriched: boolean } {
  const enriched = String(r.analysis_software_requirement_text || "").trim()
  if (enriched && useEnriched(r)) return { text: enriched, enriched: true }
  return { text: String(r.description || ""), enriched: false }
}
function devGuidanceOf(r: AiRequirement): string[] {
  return useEnriched(r) && (r.analysis_dev_guidance || []).length ? r.analysis_dev_guidance! : (r.dev_guidance || [])
}
function acceptanceOf(r: AiRequirement): string[] {
  return useEnriched(r) && (r.analysis_acceptance_criteria || []).length
    ? r.analysis_acceptance_criteria! : (r.acceptance_criteria || [])
}
function ownershipReasonOf(r: AiRequirement): string {
  return String(r.analysis_ownership_reason || r.ownership_reason || "")
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
      <button class="button" type="button" data-testid="doc-reload" :disabled="loading" @click="load">
        {{ loading ? "加载中" : "刷新" }}
      </button>
    </header>

    <div v-if="message" class="doc-message" data-testid="doc-message">{{ message }}</div>

    <div class="doc-body">
      <article class="doc-paper" data-testid="doc-paper">
        <template v-for="(b, bi) in visibleBlocks" :key="b.block_id">
          <div v-if="pageBreakBefore(bi) !== null" class="page-break"><span>第 {{ pageBreakBefore(bi) }} 页</span></div>
          <div
            :class="['doc-block',
                     { heading: isHeading(b), omission: isOmission(b),
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
              <button
                v-if="isOmission(b)"
                class="omission-tag"
                :class="{ sel: b.block_id === selectedBlockId }"
                type="button"
                data-testid="omission-tag"
                title="疑似需求但未被任何抽取需求覆盖，点击查看说明"
                @click.stop="selectBlockCard(b)"
              >⚠ 未覆盖</button>
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
            </figure>
            <p v-else class="doc-text" :class="{ 'list-item': isListItem(b) }">
              <template v-for="(seg, i) in segments(b)" :key="i"><mark v-if="seg.mark">{{ seg.text }}</mark><span v-else>{{ seg.text }}</span></template>
            </p>
          </div>
        </template>
      </article>

      <aside class="doc-detail" data-testid="doc-detail">
        <div v-if="!selectedReq && !selectedBlock" class="doc-detail-empty">点左侧 💬 批注查看需求详情</div>
        <div v-else-if="selectedBlock" class="doc-detail-card"
             :data-testid="selectedBlockKind === 'omission' ? 'omission-card' : 'context-card'">
          <div class="dd-head">
            <span class="dd-module">{{ selectedBlockKind === "omission" ? "未覆盖" : "背景/上下文" }}</span>
            <span class="dd-status">说明</span>
          </div>
          <h3 class="dd-title">{{ selectedBlockKind === "omission" ? "为什么标为未覆盖" : "为什么没有生成研发需求" }}</h3>
          <div class="dd-section"><div class="dd-body">{{ selectedBlockKind === "omission" ? OMISSION_REASON : CONTEXT_REASON }}</div></div>
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
          <div class="dd-section">
            <div class="dd-label">需求分析
              <span class="src-badge" :class="{ quiet: !analysisNarrative(selectedReq).enriched }" data-testid="dd-analysis-badge">
                {{ analysisNarrative(selectedReq).enriched ? "富化(LLM)" : "抽取" }}
              </span>
            </div>
            <div class="dd-body dd-prewrap" data-testid="dd-analysis-text">{{ analysisNarrative(selectedReq).text }}</div>
          </div>
          <div class="dd-section" v-if="(selectedReq.analysis_enrichment_warnings || []).length">
            <div class="dd-suspicion" data-testid="dd-enrich-warnings">⚠ 富化待核：{{ (selectedReq.analysis_enrichment_warnings || []).join("；") }}</div>
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
            <div class="dd-label">研发指引 / 落地实现
              <span v-if="useEnriched(selectedReq)" class="src-badge">富化(LLM)</span>
            </div>
            <ul class="dd-list"><li v-for="(g, i) in devGuidanceOf(selectedReq)" :key="i">{{ g }}</li></ul>
          </div>
          <div class="dd-section" v-if="acceptanceOf(selectedReq).length">
            <div class="dd-label">测试指引 / 验收
              <span v-if="useEnriched(selectedReq)" class="src-badge">富化(LLM)</span>
            </div>
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
.omission-stat.warn strong { color: #b45309; }
.doc-message { padding: 6px 14px; font-size: 12px; color: #b45309; background: #fdf3e3; }
.doc-body { display: grid; grid-template-columns: 1fr 360px; gap: 0; flex: 1; min-height: 0; }
.doc-paper { overflow: auto; padding: 18px 22px; background: #ffffff; }
.doc-block { display: grid; grid-template-columns: 130px 1fr; gap: 10px; padding: 3px 6px; border-left: 3px solid transparent; cursor: default; }
.doc-block.heading .doc-text { font-weight: 700; color: #1a2233; margin-top: 8px; }
.doc-block.anchored { cursor: pointer; border-left-color: #5978f7; background: #fafbfd; }
.page-break { display: flex; align-items: center; gap: 10px; margin: 22px 0 14px; color: #98a1b3; font-size: 11px; }
.page-break::before, .page-break::after { content: ""; flex: 1; border-top: 1px dashed #e6e9f0; }

/* 阅读排版：正文两端对齐、列表悬挂缩进、真表格（与自包含 HTML 同视觉） */
.doc-block:not(.heading) .doc-text { text-align: justify; hyphens: none; }
.doc-text.list-item { padding-left: 1.6em; text-indent: -1.6em; text-align: left; }
.doc-table { margin: 14px 0 18px; }
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
.doc-block.omission { border-left-color: #cc8925; border-left-style: dashed; }
.doc-gutter { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
.doc-text { margin: 0; font-size: 13px; line-height: 1.55; color: #3f4a61; white-space: pre-wrap; }
.doc-text mark { background: #f3d9a0; padding: 0 1px; }
.anno-chip { font-size: 11px; border: 1px solid #cbd5e1; border-radius: 10px; padding: 1px 7px; background: #ffffff; cursor: pointer; max-width: 124px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anno-chip.sel { outline: 2px solid #5978f7; }
.anno-chip.st-accepted { border-color: #1d8a5c; color: #1d8a5c; }
.anno-chip.st-rejected { border-color: #d63a40; color: #d63a40; }
.anno-chip.st-needs_discussion { border-color: #b06f12; color: #b06f12; }
.omission-tag { font-size: 10px; color: #b45309; background: #fdf3e3; border: 1px solid #ecd9ae;
  border-radius: 10px; padding: 1px 7px; cursor: pointer; }
.omission-tag:hover, .omission-tag.sel { border-color: #b45309; background: #f9e8c6; }
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
