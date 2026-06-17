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

export type DesktopBridge = {
  runPipeline: (input: PipelineTaskInput) => Promise<DesktopTaskPayload>
  exportRequirements: (input: ExportTaskInput) => Promise<DesktopTaskPayload>
  assembleSpec: (input: AssembleTaskInput) => Promise<DesktopTaskPayload>
}

export async function runDesktopTask<K extends keyof DesktopBridge>(
  bridge: Pick<DesktopBridge, K>,
  task: K,
  input: Parameters<DesktopBridge[K]>[0],
): Promise<DesktopTaskPayload> {
  const handler = bridge[task] as (value: typeof input) => Promise<DesktopTaskPayload>
  return handler(input)
}
