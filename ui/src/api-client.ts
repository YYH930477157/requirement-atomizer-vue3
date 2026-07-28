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
  omission_id?: string
  omission_source_fingerprint?: string
  order: number
  type?: string
  text?: string
  section_path?: string[]
  page_number?: number
  requirement_like?: boolean
  coverage_candidate?: boolean   // 覆盖/遗漏统一口径(E3b,服务端计算);旧后端缺省→前端回退宽口径
  covered_by_requirement?: boolean // 后端基于可靠 source_quote/source_mapping 计算
  noise?: boolean
  doc_region?: string
  raw_text?: string
  text_repaired?: boolean
  text_repair_checked?: boolean
  text_repair_version?: string
  text_repairs?: Array<Record<string, unknown>>
  extraction_failed?: boolean
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
  failed_section_ids?: string[]
  failed_section_block_ids?: string[]
  module_vocabulary?: string[]
}

export type ClarificationInternalCheck = {
  clarification_id: string
  evidence_fingerprint: string
  signal?: string
  module?: string
  blocker_level?: "blocking" | "important"
  question?: string
}

export type ClarificationInternalChecksPayload = {
  schema: string
  total: number
  unresolved: number
  entries: ClarificationInternalCheck[]
  groups: Array<{
    signal: string
    count: number
    blocking: number
    modules?: Record<string, number>
  }>
}

export type ClarificationCheckBatchPayload = {
  requested: number
  applied: number
  stale: string[]
  missing: string[]
  ineligible: string[]
  duplicates: string[]
  by_signal: Record<string, number>
  by_module: Record<string, number>
  readiness?: Record<string, unknown> | null
}

// 原版影印批注数据（/document/pdf,与分享 HTML 同源）
export type PdfZoneRect = { left: number; top: number; width: number; height: number }
export type PdfAnnotationPayload = {
  available: boolean
  reason?: string
  pages?: Array<{ page_number: number; file: string; width: number; height: number }>
  requirement_markers?: Array<{ req_id: string; page: number; rect: PdfZoneRect }>
  omission_markers?: Array<{ block_id: string; page: number; rect: PdfZoneRect }>
  // 全段落热区(0714):点一段出翻译和解析——kind 路由与重排模式块点击语义同源(后端唯一实现)
  block_zones?: Array<{ block_id: string; page: number; rect: PdfZoneRect;
                        kind: "req" | "covered" | "echo" | "omission" | "context";
                        req_id?: string; req_ids?: string[] }>
}

export type AiRequirement = Record<string, unknown> & {
  ai_req_id: string
  source_fingerprint?: string
  review_subject_fingerprint?: string
  extraction_fingerprint?: string
  needs_reconfirmation?: boolean
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
  source_mapping?: string
  quote_block_ids?: string[]
  echo_block_ids?: string[]
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
  // 需求分析兼容字段（当前默认不展示 LLM 叙述；保留供未来方案库重新接入）
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

export type ReviewInsightsPayload = {
  available?: boolean
  suggestions?: string[]
  decided_states?: number
  module_transitions?: Array<{ from?: string; to?: string; count?: number }>
  ownership_transitions?: Array<{ from?: string; to?: string; count?: number }>
}

export type AiReviewActionInput = {
  aiReqId: string
  status: ReviewStatus
  sourceFingerprint?: string
  reviewSubjectFingerprint?: string
  moduleOverride?: string
  clearModuleOverride?: boolean
  ownershipOverride?: string
  reason?: string
  actor?: string
}

export type AiReviewStatePayload = {
  ai_req_id: string
  status: string
  source_fingerprint?: string
  review_subject_fingerprint?: string
  module_override?: string | null
  ownership_override?: string | null
  reason?: string
  actor?: string | null
}

export type AiExtractionStatusPayload = {
  schema: "ai-requirements-partial/v1"
  run_id: string | null
  completed: number
  total: number
  complete: boolean
  failed?: boolean
  error?: string
  input_fingerprint?: string
  rows: AiRequirement[]
}

export type OmissionActionStatus =
  | "non_requirement"
  | "needs_extraction"
  | "issue_confirmed"
  | "resolved"

export type OmissionActionState = {
  omission_id: string
  block_id: string
  status: OmissionActionStatus
  reason?: string
  actor?: string | null
  source_fingerprint?: string
  recorded_at?: string
}

export type OmissionActionsPayload = {
  schema: "omission-actions/v1"
  states: OmissionActionState[]
}

export type OmissionActionInput = {
  omissionId?: string
  blockId: string
  sourceFingerprint: string
  status: OmissionActionStatus
  reason?: string
  actor?: string
}

export type OmissionReextractInput = {
  omissionId?: string
  blockId: string
  sourceFingerprint: string
  focusLines?: string[]
  actor?: string
  reason?: string
  route?: string
}

export type OmissionReextractPayload = {
  schema: "omission-reextract/v1"
  omission: OmissionActionState
  supplement: Record<string, unknown>
  requirements: number
  effective_count: number
  written: string[]
}

// 点解析（WP-B）：批注视图单行/单块定向解析，draft 进澄清待确认
export type SpotExtractInput = {
  blockId: string
  rowIndex?: number
  actor?: string
  reason?: string
  route?: string
}

export type SpotExtractPayload = {
  schema: "spot-extract/v1"
  block_id: string
  row_index: number | null
  strategy: "deterministic_param_row" | "llm"
  drafts: number
  draft_ids: string[]
  already_covered: boolean
  written: string[]
}

type FetchLike = typeof fetch

type RequirementApiClientOptions = {
  baseUrl: string
  token: string
  fetchImpl?: FetchLike
}

export type RequirementApiErrorDetails = {
  error?: string
  needs_reconfirmation?: boolean
  retryable?: boolean
  source_fingerprint?: string
  review_subject_fingerprint?: string
  [key: string]: unknown
}

export class RequirementApiError extends Error {
  readonly status: number
  readonly details: RequirementApiErrorDetails

  constructor(status: number, details: RequirementApiErrorDetails = {}) {
    super(details.error || `API request failed: ${status}`)
    this.name = "RequirementApiError"
    this.status = status
    this.details = details
  }

  get needsReconfirmation(): boolean {
    return this.status === 409 && this.details.needs_reconfirmation === true
  }
}

export function isNeedsReconfirmationError(error: unknown): error is RequirementApiError {
  return error instanceof RequirementApiError && error.needsReconfirmation
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

  async loadAiExtractionStatus(): Promise<AiExtractionStatusPayload> {
    return this.request<AiExtractionStatusPayload>("/ai-extraction-status")
  }

  async loadOmissionActions(): Promise<OmissionActionsPayload> {
    return this.request<OmissionActionsPayload>("/omission-actions")
  }

  async loadClarificationInternalChecks(): Promise<ClarificationInternalChecksPayload> {
    return this.request<ClarificationInternalChecksPayload>("/clarification-internal-checks")
  }

  async applyClarificationCheckBatch(input: {
    checks: Array<{ clarificationId: string; evidenceFingerprint: string }>
    action?: "verified_ok" | "issue_confirmed" | "deferred"
    actor?: string
    note?: string
  }): Promise<ClarificationCheckBatchPayload> {
    return this.request<ClarificationCheckBatchPayload>("/clarification-check-actions/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        checks: input.checks.map((row) => ({
          clarification_id: row.clarificationId,
          evidence_fingerprint: row.evidenceFingerprint,
        })),
        action: input.action || "verified_ok",
        actor: input.actor || "",
        note: input.note || "",
      }),
    })
  }

  async applyOmissionAction(input: OmissionActionInput): Promise<OmissionActionState> {
    return this.request<OmissionActionState>("/omission-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        omission_id: input.omissionId || "",
        block_id: input.blockId,
        source_fingerprint: input.sourceFingerprint,
        status: input.status,
        reason: input.reason || "",
        actor: input.actor || "",
      }),
    })
  }

  async reextractOmission(input: OmissionReextractInput): Promise<OmissionReextractPayload> {
    return this.request<OmissionReextractPayload>("/omission-reextract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        omission_id: input.omissionId || "",
        block_id: input.blockId,
        source_fingerprint: input.sourceFingerprint,
        focus_lines: input.focusLines || [],
        actor: input.actor || "",
        reason: input.reason || "",
        route: input.route || "",
      }),
    })
  }

  // 点解析（WP-B）：成功/失败都以 ok 标志+error 如实呈现——无 LLM 配置时按钮不隐藏，
  // 点击返回真实错误（后端 503 ok:false），不假装可用
  async spotExtract(input: SpotExtractInput): Promise<SpotExtractPayload> {
    return this.request<SpotExtractPayload>("/spot-extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        block_id: input.blockId,
        row_index: input.rowIndex ?? null,
        actor: input.actor || "",
        reason: input.reason || "",
        route: input.route || "",
      }),
    })
  }

  // 裁决复盘建议（review_insights.json,专家改判模式→规则改进建议）——E5:此前零消费者
  async loadReviewInsights(): Promise<ReviewInsightsPayload> {
    return this.request<ReviewInsightsPayload>("/review-insights")
  }

  async applyAiReviewAction(input: AiReviewActionInput): Promise<AiReviewStatePayload> {
    return this.request<AiReviewStatePayload>("/ai-review-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ai_req_id: input.aiReqId,
        status: input.status,
        source_fingerprint: input.sourceFingerprint || "",
        review_subject_fingerprint: input.reviewSubjectFingerprint || "",
        ...(input.moduleOverride !== undefined ? { module_override: input.moduleOverride } : {}),
        clear_module_override: input.clearModuleOverride === true,
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
      const parsed = await response.json().catch(() => null)
      const body = parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? parsed as RequirementApiErrorDetails
        : {}
      throw new RequirementApiError(response.status, body)
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
