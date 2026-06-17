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
  }

  interface Window {
    ratomizerDesktop?: {
      openDocument: () => Promise<string | null>
      openOutput: () => Promise<RequirementAtomizerApiSession | null>
      openPath: (targetPath: string) => Promise<void>
      getApiSession: () => Promise<RequirementAtomizerApiSession | null>
      startApiSession: (outDir: string) => Promise<RequirementAtomizerApiSession | null>
      runPipeline: (input: { inputPath: string; outDir: string; skipReview?: boolean }) => Promise<RequirementAtomizerTaskPayload>
      exportRequirements: (input: { outDir: string; formats: string[] }) => Promise<RequirementAtomizerTaskPayload>
      assembleSpec: (input: { outDir: string; formats: string[]; enrichRoute?: string }) => Promise<RequirementAtomizerTaskPayload>
    }
  }
}

export {}
