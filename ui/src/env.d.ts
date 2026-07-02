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
    merged?: unknown
    failed_sections?: number
    note?: string
    path?: string
    applied?: number
    skipped?: number
    canceled?: boolean
    rebuilt?: unknown
    quality?: unknown
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
      onTaskProgress: (handler: (event: { stage: string; completed?: number; total?: number; percent?: number; model?: string }) => void) => () => void
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
      aiExtract: (input: { outDir: string; llmRoute?: string }) => Promise<RequirementAtomizerTaskPayload>
      exportAnnotationHtml: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
      importAiDecisions: (input: { outDir: string }) => Promise<RequirementAtomizerTaskPayload>
    }
  }
}

export {}
