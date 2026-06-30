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
  noise?: boolean
  doc_region?: string
}

export type DocumentPayload = {
  blocks: DocumentBlock[]
  count: number
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
  labels?: string[]
  review_state?: { status?: string; module_override?: string | null; reason?: string } | null
}

export type AiReviewActionInput = {
  aiReqId: string
  status: ReviewStatus
  moduleOverride?: string
  reason?: string
  actor?: string
}

export type AiReviewStatePayload = {
  ai_req_id: string
  status: string
  module_override?: string | null
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
