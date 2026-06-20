import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import packageJson from "../../package.json"

describe("Electron packaging config", () => {
  it("packages Python backend resources outside the app asar", () => {
    expect(packageJson.scripts["desktop:pack"]).toBe("npm run build && electron-builder --win portable")
    expect(packageJson.devDependencies).toHaveProperty("electron-builder")
    expect(packageJson.build.productName).toBe("标准需求抽取与审查平台")
    expect(packageJson.build.win.signAndEditExecutable).toBe(false)

    const extraResources = packageJson.build.extraResources
    expect(extraResources).toEqual(expect.arrayContaining([
      { from: "..", to: ".", filter: ["*.py"] },
      { from: "../parsers", to: "parsers" },
      { from: "../domain_packs", to: "domain_packs" },
      { from: "../knowledge_bases", to: "knowledge_bases" },
      { from: "../llm_agents", to: "llm_agents" },
    ]))
  })

  it("builds renderer assets with relative paths for Electron file loading", () => {
    const viteConfig = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf-8")
    expect(viteConfig).toContain('base: "./"')
  })

  it("exposes output directory selection through the preload bridge", () => {
    const preload = readFileSync(resolve(__dirname, "../preload.cjs"), "utf-8")
    expect(preload).toContain("selectOutputDir")
    expect(preload).toContain("dialog:select-output-dir")
  })

  it("allows packaged file origins when starting the local API", () => {
    const mainProcess = readFileSync(resolve(__dirname, "../main.cjs"), "utf-8")
    expect(mainProcess).toContain('"--allow-origin",')
    expect(mainProcess).toContain('"file://",')
  })
})
