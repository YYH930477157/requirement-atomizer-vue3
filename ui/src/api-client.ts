import type { ReviewStatus } from "./types"

export type BackendRequirement = Record<string, unknown>

export type ReviewStatePayload = {
  requirement_id: string
  status: ReviewStatus
  history?: Array<Record<string, unknown>>
  metadata?: Record<string, unknown>
}

export type ReviewActionInput = {
  requirementId: string
  status: ReviewStatus
  actor: string
  reason: string
}

export type TranslationInput = {
  requirementId: string
  text: string
  context?: string
}

export type TranslationPayload = {
  requirement_id: string
  translation: string
  model?: string
}

export type DocumentBlock = {
  block_id: string
  order: number
  type?: string
  text?: string
  section_path?: string[]
  page_number?: number
  requirement_like?: boolean
  coverage_candidate?: boolean   // 覆盖/遗漏统一口径(E3b,服务端计算);旧后端缺省→前端回退宽口径
  noise?: boolean
  doc_region?: string
  // 表格块（type="table"）：批注视图渲染真表格；旧 out_dir 无 data_rows 回退扁平文字
  table_title?: string
  table_source?: string
  header_rows?: string[][]
  data_rows?: string[][]
  // 块级中文翻译（annotation_translations.json 内容哈希缓存,后端装配时附带）
  translation?: string
  translation_note?: string
}

export type DocumentPayload = {
  blocks: DocumentBlock[]
  count: number
}

// 原版影印批注数据（/document/pdf,与分享 HTML 同源）
export type PdfZoneRect = { left: number; top: number; width: number; height: number }
export type PdfAnnotationPayload = {
  available: boolean
  reason?: string
  pages?: Array<{ page_number: number; file: string; width: number; height: number }>
  requirement_markers?: Array<{ req_id: string; page: number; rect: PdfZoneRect }>
  omission_markers?: Array<{ block_id: string; page: number; rect: PdfZoneRect }>
}

export type AiRequirement = Record<string, unknown> & {
  ai_req_id: string
  anchor_block_id?: string
  title?: string
  description?: string
  module?: string
  module_effective?: string
  type?: string
  priority?: string
  status?: string
  source_section?: string
  source_quote?: string
  source_block_ids?: string[]
  acceptance_criteria?: string[]
  dev_guidance?: string[]
  labels?: string[]
  suspicion_reasons?: string[]
  consistency_flags?: string[]
  threshold_table?: { columns?: string[]; rows?: unknown[][] } | null
  sub_items?: Array<{ label?: string; text?: string }>
  self_check_added?: boolean
  ownership?: string
  ownership_effective?: string
  ownership_reason?: string
  ownership_source?: string
  review_state?: { status?: string; module_override?: string | null; ownership_override?: string | null; reason?: string } | null
  // 功能合成产物（functional_requirements.json,后端按 AIR id 投影;缺失=字段不存在）
  functional_requirement_id?: string
  functional_title?: string
  functional_objective?: string
  functional_behaviors?: string[]
  functional_preconditions?: string[]
  functional_data_constraints?: string[]
  functional_variants?: Array<{ name?: string; behavior?: string }>
  functional_merge_method?: string
  functional_merge_confidence?: number
  functional_source_count?: number
  functional_conflict_flags?: string[]
  // 需求分析富化产物（engineering_analysis.json,后端按 AIR id 合并;缺失=字段不存在,回退抽取内容）
  analysis_id?: string
  analysis_source?: string
  analysis_software_requirement_text?: string
  analysis_dev_guidance?: string[]
  analysis_design_options?: string[]
  analysis_acceptance_criteria?: string[]
  analysis_open_questions?: string[]
  analysis_assumptions?: string[]
  analysis_enrichment_warnings?: string[]
  analysis_ownership?: string
  analysis_ownership_reason?: string
  analysis_ownership_source?: string
  analysis_ownership_reason_source?: string
  hardware_translation?: string
  hardware_summary?: string
}

export type AiReviewActionInput = {
  aiReqId: string
  status: ReviewStatus
  moduleOverride?: string
  ownershipOverride?: string
  reason?: string
  actor?: string
}

export type AiReviewStatePayload = {
  ai_req_id: string
  status: string
  module_override?: string | null
  ownership_override?: string | null
  reason?: string
  actor?: string | null
}

type FetchLike = typeof fetch

type RequirementApiClientOptions = {
  baseUrl: string
  token: string
  fetchImpl?: FetchLike
}

export class RequirementApiClient {
  private readonly baseUrl: string
  private readonly token: string
  private readonly fetchImpl: FetchLike

  constructor(options: RequirementApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "")
    this.token = options.token
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis)
  }

  async loadRequirements(limit = 5000): Promise<BackendRequirement[]> {
    return this.request<BackendRequirement[]>(`/requirements?limit=${limit}`)
  }

  async applyReviewAction(input: ReviewActionInput): Promise<ReviewStatePayload> {
    return this.request<ReviewStatePayload>("/review-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        requirement_id: input.requirementId,
        status: input.status,
        actor: input.actor,
        reason: input.reason,
      }),
    })
  }

  async loadDocument(): Promise<DocumentPayload> {
    return this.request<DocumentPayload>("/document")
  }

  // 原版影印批注数据（后端与分享 HTML 同源:同几何缓存/百分比换算——双渲染器等价）
  async loadPdfAnnotation(): Promise<PdfAnnotationPayload> {
    return this.request<PdfAnnotationPayload>("/document/pdf")
  }

  // 页图走带鉴权头的 fetch → blob URL。仓库安全锁:token 绝不进 URL/查询参数
  // (test_platform_scaffold 锁定查询 token 必须拒绝——防 token 落日志/历史)。
  async loadPdfPageBlob(file: string): Promise<string> {
    const headers: Record<string, string> = {}
    if (this.token) {
      headers["X-Requirement-Atomizer-Token"] = this.token
    }
    const response = await this.fetchImpl.call(
      globalThis, `${this.baseUrl}/document/pages/${encodeURIComponent(file)}`, { headers })
    if (!response.ok) {
      throw new Error(`页图加载失败(${response.status})`)
    }
    const blob = await response.blob()
    return URL.createObjectURL(blob)
  }

  async loadAiRequirements(): Promise<AiRequirement[]> {
    return this.request<AiRequirement[]>("/ai-requirements")
  }

  async applyAiReviewAction(input: AiReviewActionInput): Promise<AiReviewStatePayload> {
    return this.request<AiReviewStatePayload>("/ai-review-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ai_req_id: input.aiReqId,
        status: input.status,
        module_override: input.moduleOverride || "",
        ownership_override: input.ownershipOverride || "",
        reason: input.reason || "",
        actor: input.actor || "",
      }),
    })
  }

  async translateRequirement(input: TranslationInput): Promise<TranslationPayload> {
    return this.request<TranslationPayload>("/translations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        requirement_id: input.requirementId,
        text: input.text,
        context: input.context || "",
      }),
    })
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = headersToObject(init.headers)
    if (this.token) {
      headers["X-Requirement-Atomizer-Token"] = this.token
    }
    const response = await this.fetchImpl.call(globalThis, `${this.baseUrl}${path}`, { ...init, headers })
    if (!response.ok) {
      // 后端对每个错误路径都返回 {"error": "..."}（如 409 冻结、400 缺字段、502 LLM 故障）。
      // 透出该信息而不是只显示状态码，让审查者看到可操作的原因。
      const body = (await response.json().catch(() => null)) as { error?: string } | null
      throw new Error(body?.error || `API request failed: ${response.status}`)
    }
    return response.json() as Promise<T>
  }
}

function headersToObject(headers: HeadersInit | undefined): Record<string, string> {
  if (!headers) return {}
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries())
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers)
  }
  return { ...headers }
}
