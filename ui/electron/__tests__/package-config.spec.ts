import { describe, expect, it } from "vitest"
import packageJson from "../../package.json"

describe("Electron packaging config", () => {
  it("packages Python backend resources outside the app asar", () => {
    expect(packageJson.scripts["desktop:pack"]).toBe("npm run build && electron-builder --win portable")
    expect(packageJson.devDependencies).toHaveProperty("electron-builder")
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
})
