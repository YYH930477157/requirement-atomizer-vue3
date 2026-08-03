import type { ReviewStatus } from "./types"

export type BackendRequirement = Record<string, unknown>

export type ResultPackagePayload = {
  layout: "package_v1" | "legacy_flat" | "legacy" | "empty"
  package_root: string
  analysis_root: string
  package: Record<string, unknown> | null
  review?: Record<string, unknown>
}

export type ReviewStatePayload = {
  requirement_id: string
  status: ReviewStatus
  history?: Array<Record<string, unknown>>
  metadata?: Record<string, unknown>
  target_fingerprint?: string
  target_publication_revision?: string
  target_authority_write_revision?: string
}

export type ReviewActionInput = {
  requirementId: string
  status: ReviewStatus
  actor: string
  reason: string
  expectedTargetFingerprint?: string
  expectedTargetPublicationRevision?: string
  expectedTargetAuthorityWriteRevision?: string
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
  // 物理行坐标（1-based，v15）：thead/title 行的 cell_context 物理定位与合并跨度渲染所需；
  // 旧产物无此字段时前端按 title=0、header=header_rows.length 顺序回退
  title_row_indexes?: number[]
  header_row_indexes?: number[]
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
// 表格行级卡片数据（v12,键 "<block_id>#R<行号>"）：行原文/翻译/页码,翻译查不到如实空串
export type PdfRowContext = {
  text?: string
  translation?: string
  translation_note?: string
  page?: number
  kind?: string
  row_index?: number
  req_ids?: string[]
  covered_req_ids?: string[]
}
// 单元格级卡片数据（v15,键 "<block_id>#<cell_id>"）：表标题/行头/列头/正文 + 如实来源坐标
// + 合并跨度（row_span/column_span/covered_coordinates，DOM colspan/rowspan 渲染真实合并格，
// covered 坐标只读不可点）。没有真实 bbox 的 cell 只给 R×C 身份——前端只用表格 DOM 单元格，不伪造 PDF 几何
export type PdfCellContext = {
  cell_id: string
  block_id: string
  table_title?: string
  row_index: number
  column_index: number
  data_row_index?: number | null
  structural_role?: string
  row_span?: number
  column_span?: number
  covered_coordinates?: [number, number][]
  header_path?: string[]
  row_header_context?: string[]
  text?: string
  page?: number | null
  bbox?: number[] | null
  geometry_kind?: string
  sheet_name?: string | null
  a1_address?: string | null
}
export type ClaimAnnotationRecord = {
  claim_id: string
  claim_hash: string
  block_id: string
  source_kind: string
  text: string
  eligibility: string
  resolution: "covered" | "excluded" | "uncertain"
  classification?: string
  claim_effective_revision?: string
  mapped: boolean
  mapping_error?: string
  rendered_text?: string
  start?: number
  end?: number
  data_row_indexes?: number[]
  // v14 cell 级 claim：R×C + 双表头上下文
  table_cell_id?: string
  row_index?: number
  column_index?: number
  data_row_index?: number | null
  header_path?: string[]
  row_header_context?: string[]
  focus?: Record<string, unknown>
}
export type ClaimAnnotationZone = {
  claim_id: string
  claim_hash: string
  block_id: string
  page: number
  rect: PdfZoneRect
  resolution: "covered" | "excluded" | "uncertain"
  focus_kind: string
  row_index?: number
  start?: number
  end?: number
  marker_lane?: number
  marker_lanes?: number
}
export type PdfAnnotationPayload = {
  available: boolean
  reason?: string
  pages?: Array<{ page_number: number; file: string; width: number; height: number }>
  requirement_markers?: Array<{ req_id: string; page: number; rect: PdfZoneRect }>
  omission_markers?: Array<{ block_id: string; page: number; rect: PdfZoneRect }>
  // 全段落热区(0714):点一段出翻译和解析——kind 路由与重排模式块点击语义同源(后端唯一实现);
  // v12 起表格数据行带 row_index（整表块本身仍不发区）
  block_zones?: Array<{ block_id: string; page: number; rect: PdfZoneRect;
                        kind: "req" | "covered" | "echo" | "omission" | "context";
                        row_index?: number; req_id?: string; req_ids?: string[] }>
  row_context?: Record<string, PdfRowContext>
  cell_context?: Record<string, PdfCellContext>
  claim_annotation_version?: string
  claim_records?: ClaimAnnotationRecord[]
  claim_zones?: ClaimAnnotationZone[]
}

export type AiRequirement = Record<string, unknown> & {
  ai_req_id: string
  source_fingerprint?: string
  review_subject_fingerprint?: string
  extraction_fingerprint?: string
  needs_reconfirmation?: boolean
  target_fingerprint?: string
  target_publication_revision?: string
  target_review_revision?: string
  target_authority_write_revision?: string
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
  expectedTargetFingerprint?: string
  expectedTargetPublicationRevision?: string
  expectedTargetAuthorityWriteRevision?: string
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
  target_fingerprint?: string
  target_publication_revision?: string
  target_authority_write_revision?: string
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
  quality?: {
    coverage_pct?: number | null
    core_coverage_pct?: number | null
  }
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

// 点解析（WP-B）：批注视图单行/单格/单块定向解析，draft 进澄清待确认
export type SpotExtractInput = {
  blockId: string
  rowIndex?: number
  cellId?: string
  actor?: string
  reason?: string
  route?: string
}

export type SpotExtractPayload = {
  schema: "spot-extract/v1"
  block_id: string
  row_index: number | null
  cell_id?: string | null
  strategy: "deterministic_param_row" | "llm"
  drafts: number
  draft_ids: string[]
  already_covered: boolean
  written: string[]
}

export type ClaimResolution = "covered" | "excluded" | "uncertain"

export type ClaimLocator = {
  block_id: string
  line?: number | null
  start?: number | null
  end?: number | null
  position_basis?: string
  table_item_id?: string | null
  row_index?: number | null
  row_start?: number
  row_end?: number
  fallback_group_id?: string
  // v14 cell 级定位（position_basis = table_cell_text）
  table_cell_id?: string | null
  column_index?: number | null
  cell_start?: number | null
  cell_end?: number | null
}

export type ClaimViewEnvelope = {
  schema: string
  available: boolean
  phase: "production-dual-write-v1"
  document_effective_revision: string | null
  base_generation_id: string | null
  catalog_generation_id?: string | null
  event_prefix_sha256: string | null
  structural_candidate_decision_registry?: {
    version: string
    prefix_sha256: string
    prefix_count: number
  }
  effective_fresh: boolean
  reason?: string
}

export type ClaimCatalogViewRow = Record<string, unknown> & {
  claim_id: string
  claim_hash?: string
  text: string
  owner_unit_id: string | null
  locator: ClaimLocator
  eligibility?: "claim" | "excluded"
  resolution: ClaimResolution
  classification?: "normative" | "non_normative" | "unknown"
  classification_status?: "validated" | "needs_review" | "invalid" | "proposed"
  exclusion_kind?: "semantic" | "structural" | null
  claim_effective_revision?: string
  source_text_hash?: string
  base_resolution_fact_hashes?: {
    positive?: string[]
    negative?: string[]
    structural?: string[]
  }
  active_resolution_facts?: {
    fact_hash: string
    kind: string
    polarity: "positive" | "negative"
  }[]
  required_supersedes_fact_hashes?: Record<string, string[]>
  pending_structural_operation?: {
    operation_id: string
    lifecycle: string
    checkpoints: string[]
    route_requested: string
    route_model: string | null
    route_config_revision: string | null
    allow_llm: boolean
    verifier_budget: {
      max_calls: number
      max_total_tokens: number
      attempted_calls: number
      failed_calls: number
      used_tokens: number
      reserved_tokens: number
      remaining_calls: number
      remaining_tokens: number
      usage_complete: boolean
      unknown_remote_result: boolean
    }
    needs_reconfirmation: boolean
  } | null
  structural_review_status?: "pending_review" | "confirmed_excluded" | null
  structural_candidate_decision?: {
    decision_id: string
    decision: "confirm_exclusion"
    actor: string
    reason: string
    recorded_at: string
  } | null
}

export type ClaimEffectiveLedgerRow = Record<string, unknown> & {
  claim_id: string
  owner_unit_id: string | null
  resolution: ClaimResolution
  classification: "normative" | "non_normative" | "unknown"
  classification_status: "validated" | "needs_review" | "invalid" | "proposed"
  exclusion_kind: "semantic" | "structural" | null
  coverage_group_ids?: string[]
  invalid_reasons?: string[]
  claim_effective_revision: string
}

export type ClaimProducedEvidence = {
  field?: string
  item_index?: number | null
  start?: number
  end?: number
  text?: string
}

export type ClaimCoverageEdge = Record<string, unknown> & {
  edge_id?: string
  target_kind?: "ai_requirement" | "atomic_requirement"
  target_requirement_id?: string
  target_review_status?: string
  target_review_eligibility?: "active" | "rejected" | "unknown"
  relation?: "generated_from" | "merged_into"
  produced_evidence?: ClaimProducedEvidence[]
}

export type ClaimCoverageGroupView = Record<string, unknown> & {
  coverage_group_id: string
  coverage_group_hash?: string
  claim_id: string
  validation_method: "deterministic_verbatim" | "independent_semantic" | "expert"
  status: "proposed" | "validated" | "invalid"
  invalid_reason?: string
  effective_status?: string
  effective_reason?: string
  validation_reused?: boolean
  reused?: boolean
  edges: ClaimCoverageEdge[]
}

export type ClaimReviewEventView = Record<string, unknown> & {
  event_seq: number
  event_id: string
  claim_id: string
  event_kind: "target_invalidated" | "target_reactivated" |
    "expert_adjudication" | "audit_conflict" | "structural_falsification"
  recorded_at: string
  reason?: string
  target_requirement_id?: string
  eligibility_before?: "active" | "rejected" | "unknown"
  eligibility_after?: "active" | "rejected" | "unknown"
}

export type ClaimRatioMetric = {
  numerator: number
  denominator: number
  value: number | null
}

export type ClaimMetrics = Record<string, unknown> & {
  inventory_accounted_ratio?: ClaimRatioMetric
  verified_coverage_ratio?: ClaimRatioMetric
  verified_semantic_exclusion_ratio?: ClaimRatioMetric
  verified_exclusion_ratio?: ClaimRatioMetric
  eligible_resolution_ratio?: ClaimRatioMetric
  structural_exclusion_ratio?: ClaimRatioMetric
  uncertain_count?: number
}

export type ClaimQueueProposal = Record<string, unknown> & {
  proposal_id: string
  claim_id: string
  claim_hash?: string
  parent_block_id: string
  locator: ClaimLocator
  action: "needs_extraction"
  dry_run: false
  claim_effective_revision: string
  lifecycle: "open" | "executing" | "executed" | "rebuild_pending"
  focus?: Record<string, unknown>
  focus_error?: string | null
  latest_attempt?: {
    attempt_id: string
    request_idempotency_key?: string
    lifecycle: "executing" | "rebuild_pending" | "succeeded" |
      "failed" | "interrupted" | "aborted_stale"
    last_event_seq: number
    outcome?: { code: string; message: string; retryable: boolean } | null
  } | null
}

export type ClaimCompatOmission = Record<string, unknown> & {
  omission_id?: string
  block_id?: string
  status?: string
  reason?: string
  compat_whole_block: true
  dry_run: true
}

export type ClaimCatalogViewPayload = ClaimViewEnvelope & {
  rows: ClaimCatalogViewRow[]
  total: number
  limit: number
  offset: number
  owner_unit_ids?: string[]
}

export type ClaimLedgerViewPayload = ClaimViewEnvelope & {
  rows: ClaimEffectiveLedgerRow[]
  total: number
  limit: number
  offset: number
}

export type ClaimCoverageGroupsViewPayload = ClaimViewEnvelope & {
  groups: ClaimCoverageGroupView[]
  total: number
  limit: number
  offset: number
}

export type ClaimMetricsViewPayload = ClaimViewEnvelope & {
  generation_metrics: ClaimMetrics
  effective_metrics: ClaimMetrics
  generation_metrics_version?: string
  effective_metrics_version?: string
  document_ready: boolean | null
  structural_review_pending_count?: number
  structural_review_confirmed_exclusion_count?: number
  health?: Record<string, unknown>
}

export type ClaimReviewEventsViewPayload = ClaimViewEnvelope & {
  events: ClaimReviewEventView[]
  total: number
  limit: number
  offset: number
}

export type ClaimQueueRoutePreflight = {
  route: string
  configured: boolean
  model: string | null
  route_config_revision: string | null
}

export type ClaimQueueViewPayload = ClaimViewEnvelope & {
  proposals: ClaimQueueProposal[]
  compat_omissions: ClaimCompatOmission[]
  total: number
  limit: number
  offset: number
  compat_omission_total: number
  compat_omission_limit?: number
  compat_omission_offset?: number
  route_preflight?: ClaimQueueRoutePreflight | null
}

export type ClaimPageQuery = {
  limit?: number
  offset?: number
}

export type ClaimQueueQuery = ClaimPageQuery & {
  compatLimit?: number
  compatOffset?: number
}

export type ClaimCatalogQuery = {
  resolution?: ClaimResolution | ""
  ownerUnitId?: string
  limit?: number
  offset?: number
}

export type ClaimLedgerQuery = {
  resolution?: ClaimResolution | ""
  limit?: number
  offset?: number
}

export type ClaimQueueExecutionInput = {
  proposalId: string
  expectedClaimEffectiveRevision: string
  actor?: string
  allowLlm: boolean
  route: string
  maximumCalls: number
  totalTokenBudget: number
  requestIdempotencyKey: string
  expectedRouteConfigRevision?: string
}

export type ClaimQueueExecutionPayload = Record<string, unknown> & {
  schema: "claim-queue-execution/v1"
  proposal_id: string
  attempt_id: string
  lifecycle: "executed" | "rebuild_pending" | "failed" | "aborted_stale"
  resolution?: ClaimResolution
  retryable?: boolean
}

export type ClaimAdjudicationEvidence =
  | {
      kind: "coverage_group"
      coverage_group_id: string
      coverage_group_hash: string
    }
  | {
      kind: "source_exclusion"
      source_locator: ClaimLocator
      source_text_hash: string
      exclusion_reason: "scope_statement" | "definition" | "informative" | "example" | "instrument_only"
    }

export type ClaimAdjudicationInput = {
  claimId: string
  claimHash: string
  adjudication: "covered" | "excluded_non_normative" | "reopen"
  reason: string
  evidence: ClaimAdjudicationEvidence
  actor?: string
  expectedClaimEffectiveRevision: string
  supersedesFactHashes?: string[]
  requestIdempotencyKey?: string
}

export type ClaimAdjudicationPayload = Record<string, unknown> & {
  ok: boolean
  event?: ClaimReviewEventView
}

export type ClaimStructuralOverrideInput = {
  claimId: string
  claimHash: string
  expectedCatalogGenerationId: string
  expectedClaimEffectiveRevision: string
  priorStructuralReason: "repeated_page_furniture" |
    "ambiguous_table_structure" | "weak_signal_table_cell" |
    "unsignaled_table_cell" | "rejected_matrix_marker_cell" |
    "untyped_colon_spec_cell"
  decision: "promote_to_claim" | "confirm_exclusion"
  reason: string
  actor?: string
  requestIdempotencyKey: string
  allowLlm: boolean
  route: string
  verifierMaxCalls: number
  verifierMaxTotalTokens: number
  operationId?: string
  reconfirmPaidWork?: boolean
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

  async loadManifest(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/manifest")
  }

  async loadResultPackage(): Promise<ResultPackagePayload> {
    return this.request<ResultPackagePayload>("/result-package")
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
        ...(input.expectedTargetFingerprint !== undefined
          ? { expected_target_fingerprint: input.expectedTargetFingerprint }
          : {}),
        ...(input.expectedTargetPublicationRevision !== undefined
          ? {
              expected_target_publication_revision:
                input.expectedTargetPublicationRevision,
            }
          : {}),
        ...(input.expectedTargetAuthorityWriteRevision !== undefined
          ? {
              expected_target_authority_write_revision:
                input.expectedTargetAuthorityWriteRevision,
            }
          : {}),
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
        cell_id: input.cellId ?? null,
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

  async loadClaimCatalog(query: ClaimCatalogQuery = {}): Promise<ClaimCatalogViewPayload> {
    return this.requestClaimView<ClaimCatalogViewPayload>(`/claim-catalog${claimQueryString({
      limit: query.limit ?? 25,
      offset: query.offset ?? 0,
      resolution: query.resolution || undefined,
      owner_unit_id: query.ownerUnitId || undefined,
    })}`)
  }

  async loadClaimLedger(query: ClaimLedgerQuery = {}): Promise<ClaimLedgerViewPayload> {
    return this.requestClaimView<ClaimLedgerViewPayload>(`/claim-ledger${claimQueryString({
      limit: query.limit ?? 25,
      offset: query.offset ?? 0,
      resolution: query.resolution || undefined,
    })}`)
  }

  async loadClaimCoverageGroups(
    claimId: string,
    query: ClaimPageQuery = {},
  ): Promise<ClaimCoverageGroupsViewPayload> {
    return this.requestClaimView<ClaimCoverageGroupsViewPayload>(
      `/claim-coverage-groups${claimQueryString({
        claim_id: claimId,
        limit: query.limit ?? 100,
        offset: query.offset ?? 0,
      })}`,
    )
  }

  async loadClaimMetrics(): Promise<ClaimMetricsViewPayload> {
    return this.requestClaimView<ClaimMetricsViewPayload>("/claim-metrics")
  }

  async loadClaimReviewEvents(
    claimId: string,
    query: ClaimPageQuery = {},
  ): Promise<ClaimReviewEventsViewPayload> {
    return this.requestClaimView<ClaimReviewEventsViewPayload>(
      `/claim-review-events${claimQueryString({
        claim_id: claimId,
        limit: query.limit ?? 100,
        offset: query.offset ?? 0,
      })}`,
    )
  }

  async loadClaimQueue(query: ClaimQueueQuery = {}): Promise<ClaimQueueViewPayload> {
    return this.requestClaimView<ClaimQueueViewPayload>(
      `/claim-queue${claimQueryString({
        limit: query.limit ?? 100,
        offset: query.offset ?? 0,
        compat_limit: query.compatLimit ?? 100,
        compat_offset: query.compatOffset ?? 0,
      })}`,
    )
  }

  async executeClaimQueue(
    input: ClaimQueueExecutionInput,
  ): Promise<ClaimQueueExecutionPayload> {
    return this.request<ClaimQueueExecutionPayload>("/claim-queue/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proposal_id: input.proposalId,
        expected_claim_effective_revision: input.expectedClaimEffectiveRevision,
        expected_ledger_state: "uncertain",
        actor: input.actor || "reviewer",
        allow_llm: input.allowLlm,
        route: input.route,
        maximum_calls: input.maximumCalls,
        total_token_budget: input.totalTokenBudget,
        request_idempotency_key: input.requestIdempotencyKey,
        ...(input.expectedRouteConfigRevision
          ? { expected_route_config_revision: input.expectedRouteConfigRevision }
          : {}),
      }),
    })
  }

  async applyClaimAdjudication(
    input: ClaimAdjudicationInput,
  ): Promise<ClaimAdjudicationPayload> {
    return this.request<ClaimAdjudicationPayload>("/claim-adjudications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        claim_id: input.claimId,
        claim_hash: input.claimHash,
        adjudication: input.adjudication,
        reason: input.reason,
        evidence: input.evidence,
        actor: input.actor || "reviewer",
        expected_claim_effective_revision: input.expectedClaimEffectiveRevision,
        supersedes_fact_hashes: input.supersedesFactHashes || [],
        request_idempotency_key: input.requestIdempotencyKey || "",
      }),
    })
  }

  async confirmClaimStructuralOverride(
    input: ClaimStructuralOverrideInput,
  ): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/claim-structural-overrides", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        claim_id: input.claimId,
        claim_hash: input.claimHash,
        expected_catalog_generation_id: input.expectedCatalogGenerationId,
        expected_claim_effective_revision: input.expectedClaimEffectiveRevision,
        prior_structural_reason: input.priorStructuralReason,
        decision: input.decision,
        reason: input.reason,
        actor: input.actor || "reviewer",
        request_idempotency_key: input.requestIdempotencyKey,
        allow_llm: input.allowLlm,
        route: input.route,
        verifier_max_calls: input.verifierMaxCalls,
        verifier_max_total_tokens: input.verifierMaxTotalTokens,
        ...(input.operationId ? { operation_id: input.operationId } : {}),
        ...(input.reconfirmPaidWork !== undefined
          ? { reconfirm_paid_work: input.reconfirmPaidWork }
          : {}),
      }),
    })
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
        ...(input.expectedTargetFingerprint !== undefined
          ? { expected_target_fingerprint: input.expectedTargetFingerprint }
          : {}),
        ...(input.expectedTargetPublicationRevision !== undefined
          ? {
              expected_target_publication_revision:
                input.expectedTargetPublicationRevision,
            }
          : {}),
        ...(input.expectedTargetAuthorityWriteRevision !== undefined
          ? {
              expected_target_authority_write_revision:
                input.expectedTargetAuthorityWriteRevision,
            }
          : {}),
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

  private async requestClaimView<T extends ClaimViewEnvelope>(path: string): Promise<T> {
    const payload = await this.request<T>(path)
    if (!payload || typeof payload !== "object"
        || !Object.prototype.hasOwnProperty.call(payload, "document_effective_revision")
        || typeof payload.available !== "boolean"
        || (payload.available && typeof payload.document_effective_revision !== "string")
        || (!payload.available && payload.document_effective_revision !== null)) {
      throw new RequirementApiError(502, {
        error: "Claim ledger response is missing document_effective_revision",
        retryable: true,
      })
    }
    return payload
  }
}

function claimQueryString(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) params.set(key, String(value))
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ""
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
