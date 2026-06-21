export type ReviewStatus =
  | "candidate"
  | "llm_reviewed"
  | "expert_pending"
  | "accepted"
  | "rejected"
  | "needs_discussion"
  | "needs_rework"
  | "flagged"
  | "frozen"

export type RequirementType =
  | "功能"
  | "性能"
  | "安全"
  | "接口"
  | "数据"
  | "环境"
  | "约束"

export type WorkflowStepStatus = "done" | "active" | "pending"

export type Requirement = {
  id: string
  backendId: string
  type: RequirementType
  module?: string
  moduleCode?: string
  category?: string
  categoryCode?: string
  object: string
  chineseText: string
  originalText: string
  translation?: string
  sourceDocument: string
  sourceLocation: string
  domainTags?: string[]
  sectionPath?: string[]
  confidence: number
  risk: "低" | "中" | "高"
  status: ReviewStatus
  keyPoints: string[]
  specMapping?: {
    name: string
    source: string
    matchRate: number
  }
  ambiguity: {
    level: "低" | "中" | "高"
    reasons: string[]
  }
}

export type SummaryCard = {
  label: string
  value: number
  delta?: string
  tone: "blue" | "green" | "orange" | "purple" | "red"
}

export type DistributionItem = {
  label: string
  value: number
  percent: number
  tone: "green" | "blue" | "red"
}
