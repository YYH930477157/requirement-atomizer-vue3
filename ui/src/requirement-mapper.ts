import type { BackendRequirement, ReviewStatePayload } from "./api-client"
import type { Requirement, RequirementType, ReviewStatus } from "./types"

const STATUS_LABELS: Record<ReviewStatus, string> = {
  candidate: "待审查",
  llm_reviewed: "AI 已审查",
  expert_pending: "待专家确认",
  accepted: "已接受",
  rejected: "已拒绝",
  needs_discussion: "讨论中",
  needs_rework: "需返工",
  flagged: "已标记",
  frozen: "已冻结",
}

const TYPE_LABELS: Record<string, RequirementType> = {
  functional: "功能",
  function: "功能",
  behavior: "功能",
  performance: "性能",
  security: "安全",
  interface: "接口",
  data: "数据",
  environment: "环境",
  constraint: "约束",
  cosem_attribute_access: "接口",
  cosem_object_instance: "数据",
  cosem_security_policy: "安全",
}

const VALID_STATUSES = new Set<ReviewStatus>([
  "candidate",
  "llm_reviewed",
  "expert_pending",
  "accepted",
  "rejected",
  "needs_discussion",
  "needs_rework",
  "flagged",
  "frozen",
])

export function mapBackendRequirement(row: BackendRequirement): Requirement {
  const reviewState = objectValue(row.review_state)
  const review = objectValue(row.review)
  const id = textValue(row.stable_req_id) || textValue(row.requirement_id) || textValue(row.req_id) || "REQ-UNKNOWN"
  const backendId = textValue(reviewState.requirement_id) || id
  const risk = riskLevel(textValue(review.risk) || textValue(row.risk))
  const reasons = stringArray(review.review_notes).concat(stringArray(review.expert_questions))

  return {
    id,
    backendId,
    type: typeLabel(textValue(row.requirement_type) || textValue(row.type)),
    object: textValue(row.object_name) || textValue(row.object) || textValue(row.class_name) || "-",
    chineseText: textValue(row.description) || textValue(row.requirement) || textValue(review.revised_requirement) || "-",
    originalText: textValue(row.source_quote) || textValue(row.original_text) || textValue(row.text) || "-",
    sourceDocument: textValue(row.source_document) || textValue(row.document) || "当前输出目录",
    sourceLocation: textValue(row.source_ref) || textValue(row.source_location) || textValue(row.block_id) || "-",
    confidence: numberValue(row.confidence) ?? numberValue(review.confidence) ?? 0,
    risk,
    status: statusValue(reviewState.status),
    keyPoints: keyPoints(row, review),
    ambiguity: {
      level: risk,
      reasons: reasons.length > 0 ? reasons : risk === "低" ? [] : ["需要人工复核"],
    },
  }
}

export function applyReviewState(requirement: Requirement, state: ReviewStatePayload): Requirement {
  return {
    ...requirement,
    backendId: state.requirement_id || requirement.backendId,
    status: statusValue(state.status),
  }
}

export function statusDisplay(status: ReviewStatus): string {
  return STATUS_LABELS[status]
}

export function toBackendStatus(status: ReviewStatus): ReviewStatus {
  return status
}

function statusValue(value: unknown): ReviewStatus {
  const status = textValue(value) as ReviewStatus
  return VALID_STATUSES.has(status) ? status : "candidate"
}

function typeLabel(value: string): RequirementType {
  return TYPE_LABELS[value] ?? TYPE_LABELS[value.toLowerCase()] ?? "功能"
}

function riskLevel(value: string): "低" | "中" | "高" {
  const normalized = value.toLowerCase()
  if (normalized === "high" || value === "高") return "高"
  if (normalized === "medium" || normalized === "middle" || value === "中") return "中"
  return "低"
}

function keyPoints(row: BackendRequirement, review: Record<string, unknown>): string[] {
  const labels = stringArray(row.labels)
  const acceptance = stringArray(review.acceptance)
  if (labels.length > 0) return labels
  if (acceptance.length > 0) return acceptance
  return ["来自真实输出目录"]
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : value === undefined || value === null ? "" : String(value)
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(textValue).filter(Boolean) : []
}
