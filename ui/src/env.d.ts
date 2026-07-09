/// <reference types="vite/client" />

declare module "*.vue"
declare module "katex"

declare global {
  type RequirementAtomizerApiSession = {
    baseUrl: string
    token: string
    outputDir?: string
  }

  type RequirementAtomizerTaskPayload = {
    kind: string
    out_dir?: string
    outDir?: string
    summary?: unknown
    written?: string[]
    count?: number
    analysis?: unknown
    breakdown?: unknown
    merged?: unknown
    consistency?: unknown
    sampled?: unknown
    quality?: unknown
    failed_sections?: number
    note?: string
    stage_notes?: string[]
    path?: string
    applied?: number
    skipped?: number
    canceled?: boolean
    rebuilt?: unknown
    quality?: unknown
    report?: unknown
    questions?: number
    imported?: number
    readiness?: unknown
    results?: unknown
    analysis?: unknown
    template?: unknown
    api_warning?: string
  }

  interface Window {
    ratomizerDesktop?: {
      openDocument: () => Promise<string | null>
      selectOutputDir: () => Promise<string | null>
      openOutput: () => Promise<RequirementAtomizerApiSession | null>
      openPath: (targetPath: string) => Promise<void>
      getApiSession: () => Promise<RequirementAtomizerApiSession | null>
      startApiSession: (outDir: string) => Promise<RequirementAtomizerApiSession | null>
      getLlmSettings: () => Promise<{
        enabled: boolean
        baseUrl: string
        model: string
        apiKeyEnv: string
        temperature: number
        maxTokens: number
        timeoutS: number
        maxRetries: number
        concurrency: number
        selfCheck: boolean
      } | null>
      saveLlmSettings: (input: {
        enabled: boolean
        baseUrl: string
        model: string
        apiKeyEnv: string
        apiKey?: string
        temperature: number
        maxTokens: number
        timeoutS: number
        maxRetries: number
        concurrency: number
        selfCheck: boolean
      }) => Promise<{
        enabled: boolean
        baseUrl: string
        model: string
        apiKeyEnv: string
        temperature: number
        maxTokens: number
        timeoutS: number
        maxRetries: number
        concurrency: number
        selfCheck: boolean
      }>
      testLlmConnection: (input: {
        enabled: boolean
        baseUrl: string
        model: string
        apiKeyEnv: string
        apiKey?: string
        temperature: number
        maxTokens: number
        timeoutS: number
        maxRetries: number
        concurrency: number
        selfCheck: boolean
      }) => Promise<{ ok: boolean; message: string }>
      onTaskProgress: (handler: (event: { stage: string; step?: string; status?: string; completed?: number; total?: number; percent?: number; model?: string }) => void) => () => void
      runPipeline: (input: {
        inputPath: string
        outDir: string
        skipReview?: boolean
        llmRoute?: string
        reviewScope?: string
        llmReviewLimit?: number
        chunkChars?: number
        kbPaths?: string[]
        domainPackDir?: string
      }) => Promise<RequirementAtomizerTaskPayload>
      getOutputSummary: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      aiExtract: (input: { outDir: string; llmRoute?: string; limitSections?: number; sampleRatio?: number }) => Promise<RequirementAtomizerTaskPayload>
      exportAnnotationHtml: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      importAiDecisions: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      assembleSpec: (input: { outDir: string; enrichRoute?: string }) => Promise<RequirementAtomizerTaskPayload>
      composeEngineering: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      runRequirementsAnalysis: (input: { outDir: string; llmRoute?: string; templatePath?: string }) => Promise<RequirementAtomizerTaskPayload>
      writeTemplate: (input: { outDir: string; templatePath: string }) => Promise<RequirementAtomizerTaskPayload>
      clarificationReport: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      runChain: (input: { outDir: string; stages: string[]; llmRoute?: string; templatePath?: string; sampleRatio?: number }) => Promise<RequirementAtomizerTaskPayload>
      importClarificationAnswers: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      selectTemplate: () => Promise<string>
      openLogsDir: () => Promise<{ dir: string }>
    }
  }
}

export {}
