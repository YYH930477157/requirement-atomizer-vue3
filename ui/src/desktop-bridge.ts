export type DesktopTaskPayload = {
  kind: string
  outDir?: string
  out_dir?: string
  input?: string
  manifest?: unknown
  review?: unknown
  summary?: unknown
  written?: string[]
  count?: number
  analysis?: unknown
  breakdown?: unknown
}

export type PipelineTaskInput = {
  inputPath: string
  outDir: string
  skipReview?: boolean
  llmRoute?: string
  reviewScope?: string
  chunkChars?: number
  kbPaths?: string[]
  domainPackDir?: string
}

export type ExportTaskInput = {
  outDir: string
  formats: string[]
}

export type AssembleTaskInput = {
  outDir: string
  formats: string[]
  enrichRoute?: string
}

export type LlmSettingsInput = {
  enabled: boolean
  baseUrl: string
  model: string
  apiKeyEnv: string
  apiKey?: string
  temperature: number
  maxTokens: number
  timeoutS: number
  maxRetries: number
}

export type LlmSettingsPayload = Omit<LlmSettingsInput, "apiKey">

export type DesktopBridge = {
  getLlmSettings?: () => Promise<LlmSettingsPayload | null>
  saveLlmSettings?: (input: LlmSettingsInput) => Promise<LlmSettingsPayload>
  testLlmConnection?: (input: LlmSettingsInput) => Promise<{ ok: boolean; message: string }>
  runPipeline: (input: PipelineTaskInput) => Promise<DesktopTaskPayload>
  exportRequirements: (input: ExportTaskInput) => Promise<DesktopTaskPayload>
  assembleSpec: (input: AssembleTaskInput) => Promise<DesktopTaskPayload>
}

type DesktopTaskBridge = Pick<DesktopBridge, "runPipeline" | "exportRequirements" | "assembleSpec">

export async function runDesktopTask<K extends keyof DesktopTaskBridge>(
  bridge: Pick<DesktopTaskBridge, K>,
  task: K,
  input: Parameters<DesktopTaskBridge[K]>[0],
): Promise<DesktopTaskPayload> {
  const handler = bridge[task] as (value: typeof input) => Promise<DesktopTaskPayload>
  return handler(input)
}
