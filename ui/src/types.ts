export type ReviewStatus =
  | "待审查"
  | "已接受"
  | "拒绝"
  | "待专家确认"
  | "讨论中"

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
  type: RequirementType
  object: string
  chineseText: string
  originalText: string
  sourceDocument: string
  sourceLocation: string
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
