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
  access_control: "安全",
  communication: "接口",
  interface: "接口",
  data: "数据",
  environment: "环境",
  constraint: "约束",
  cosem_attribute_access: "接口",
  cosem_object_instance: "数据",
  cosem_object: "数据",
  cosem_security_policy: "安全",
  event: "功能",
  event_definition: "功能",
  event_group_retention: "功能",
  capability_matrix: "约束",
  association_security_matrix: "安全",
  security_suite_definition: "安全",
  security_policy_bit: "安全",
  security_policy_state: "安全",
  table_value_matrix: "数据",
  measurement_quantity_unit: "数据",
  flag_definition: "数据",
}

const CATEGORY_LABELS: Record<string, string> = {
  functional: "功能要求",
  function: "功能要求",
  behavior: "行为要求",
  performance: "性能要求",
  security: "安全要求",
  access_control: "访问控制",
  communication: "通信要求",
  interface: "接口要求",
  data: "数据要求",
  environment: "环境要求",
  constraint: "约束要求",
  cosem_attribute_access: "COSEM 属性访问",
  cosem_object_instance: "COSEM 对象实例",
  cosem_object: "COSEM 对象",
  cosem_security_policy: "COSEM 安全策略",
  event: "事件要求",
  event_definition: "事件定义",
  event_group_retention: "事件组留存",
  capability_matrix: "能力矩阵",
  association_security_matrix: "关联安全矩阵",
  security_suite_definition: "安全套件定义",
  security_policy_bit: "安全策略位",
  security_policy_state: "安全策略状态",
  table_value_matrix: "表值矩阵",
  measurement_quantity_unit: "测量量与单位",
  flag_definition: "标志位定义",
}

const MODULE_LABELS: Record<string, string> = {
  access_control: "访问控制",
  alarm: "告警",
  association: "关联/客户端",
  billing_profile: "计费档案",
  communication_profile: "通信配置",
  cosem_class: "COSEM 类",
  cosem_object: "COSEM 对象",
  data_model: "数据模型",
  error: "错误处理",
  event: "事件",
  firmware_update: "固件升级",
  general: "通用",
  irregularity: "异常处理",
  load_profile: "负荷曲线",
  measurement_quantity: "测量量",
  meter_function: "电表功能",
  obis_code: "OBIS 编码",
  power_quality: "电能质量",
  register: "寄存器",
  security_policy: "安全策略",
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
  const categoryCode = textValue(row.requirement_type) || textValue(row.type)
  const moduleCode = textValue(row.domain)
  const risk = riskLevel(textValue(review.risk) || textValue(row.risk))
  const reasons = stringArray(review.review_notes).concat(stringArray(review.expert_questions))
  const sourceRefs = stringArray(row.source_refs)
  const sectionPath = stringArray(row.section_path)
  const domainTags = stringArray(row.domain_tags)

  return {
    id,
    backendId,
    type: typeLabel(categoryCode),
    module: moduleLabel(moduleCode, sectionPath),
    moduleCode,
    category: categoryLabel(categoryCode),
    categoryCode,
    object: textValue(row.object_name) || textValue(row.object) || textValue(row.class_name) || "-",
    chineseText: textValue(row.description) || textValue(row.requirement) || textValue(review.revised_requirement) || "-",
    originalText: textValue(row.source_quote) || textValue(row.original_text) || textValue(row.text) || "-",
    sourceDocument: textValue(row.source_document) || textValue(row.document) || "当前输出目录",
    sourceLocation: textValue(row.source_ref) || textValue(row.source_location) || sourceRefs.join(" · ") || textValue(row.block_id) || "-",
    domainTags,
    sectionPath,
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

function categoryLabel(value: string): string {
  const normalized = value.toLowerCase()
  return CATEGORY_LABELS[value] ?? CATEGORY_LABELS[normalized] ?? (value || "未分类")
}

function moduleLabel(value: string, sectionPath: string[]): string {
  const normalized = value.toLowerCase()
  if (value) return MODULE_LABELS[value] ?? MODULE_LABELS[normalized] ?? value
  return sectionPath[0] || "未分模块"
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
