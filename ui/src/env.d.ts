/// <reference types="vite/client" />

declare module "*.vue"
declare module "katex"

declare global {
  interface Window {
    ratomizerDesktop?: {
      openDocument: () => Promise<string | null>
      openOutput: () => Promise<string | null>
      openPath: (targetPath: string) => Promise<void>
    }
  }
}

export {}
