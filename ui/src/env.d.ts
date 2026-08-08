/// <reference types="vite/client" />

declare module "*.vue"
declare module "katex"

// Vite ?url 后缀把资源以 URL 字符串导入（pdf.js worker 等静态分包用）。
declare module "*?url" {
  const src: string
  export default src
}

declare global {
  type RequirementAtomizerApiSession = {
    baseUrl: string
    token: string
    outputDir?: string
  }

  type RequirementAtomizerRecentSession = {
    outputDir: string
    label: string
    openedAt: string
    exists: boolean
    isOutput: boolean
    classification?: {
      kind: "package_v1" | "legacy" | "invalid" | "not_output"
      analysisStatus: "completed" | "incomplete" | "running" | "legacy" | "invalid"
      reason: string
      displayName?: string
    }
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
    internal_imported?: number
    readiness?: unknown
    results?: unknown
    analysis?: unknown
    template?: unknown
    api_warning?: string
    analysis_root?: string
    package?: unknown
    layout?: string
  }

  interface Window {
    ratomizerDesktop?: {
      openDocument: () => Promise<string | null>
      selectOutputDir: () => Promise<string | null>
      openOutput: () => Promise<RequirementAtomizerApiSession | null>
      openPath: (targetPath: string) => Promise<void>
      getApiSession: () => Promise<RequirementAtomizerApiSession | null>
      getDefaultOutputRoot: () => Promise<string>
      startApiSession: (outDir: string) => Promise<RequirementAtomizerApiSession | null>
      getRecentSessions: () => Promise<RequirementAtomizerRecentSession[]>
      onApiSessionReady?: (handler: (session: RequirementAtomizerApiSession) => void) => () => void
      getLlmSettings: () => Promise<{
        enabled: boolean
        visionCapable: boolean
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
        visionCapable: boolean
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
        visionCapable: boolean
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
        visionCapable: boolean
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
      startResultPackage: (input: { outDir: string; inputPath: string; stages: string[] }) => Promise<RequirementAtomizerTaskPayload>
      completeResultPackage: (input: { outDir: string; runId: string; completedStages: string[] }) => Promise<RequirementAtomizerTaskPayload>
      failResultPackage: (input: { outDir: string; runId: string; error: string }) => Promise<RequirementAtomizerTaskPayload>
      getOutputSummary: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      aiExtract: (input: { outDir: string; llmRoute?: string; limitSections?: number; sampleRatio?: number }) => Promise<RequirementAtomizerTaskPayload>
      exportAnnotationHtml: (input: { outDir: string; route?: string; layoutMode?: "optimized" | "pdf_original" }) => Promise<RequirementAtomizerTaskPayload>
      importAiDecisions: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      assembleSpec: (input: { outDir: string; enrichRoute?: string }) => Promise<RequirementAtomizerTaskPayload>
      composeEngineering: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      runRequirementsAnalysis: (input: { outDir: string; llmRoute?: string; templatePath?: string }) => Promise<RequirementAtomizerTaskPayload>
      writeTemplate: (input: { outDir: string; templatePath: string }) => Promise<RequirementAtomizerTaskPayload>
      clarificationReport: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      runChain: (input: { outDir: string; stages: string[]; llmRoute?: string; templatePath?: string; sampleRatio?: number; annotationLayoutMode?: "optimized" | "pdf_original" }) => Promise<RequirementAtomizerTaskPayload>
      importClarificationAnswers: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      readArtifact: (input: {
        outDir: string
        category: "pipeline" | "state" | "cache" | "logs" | "stages"
        filename: string
      }) => Promise<{
        ok: boolean
        missing?: boolean
        path?: string | null
        format?: "json" | "jsonl"
        content?: unknown
        reason?: string
        detail?: string
      }>
      selectTemplate: () => Promise<string>
      openLogsDir: () => Promise<{ dir: string }>
      // 真渲染器读文件字节：传入绝对路径，主进程校验后返回字节。非 Electron 环境缺失→渲染器诚实降级。
      readFileBytes?: (input: { path: string }) => Promise<{
        ok: boolean
        bytes?: Uint8Array
        reason?: string
        detail?: string
      }>
    }
  }
}

export {}
