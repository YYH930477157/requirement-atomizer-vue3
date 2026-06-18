import { describe, expect, it } from "vitest"
import path from "node:path"

import { buildRunPipelineArgs, resolvePythonScriptPath } from "../main.helpers.cjs"

describe("Electron main helpers", () => {
  it("builds run pipeline args with ABNT preset inputs", () => {
    expect(buildRunPipelineArgs({
      inputPath: "C:\\input\\Appendix 9.docx",
      outDir: "E:\\out\\abnt",
      skipReview: false,
      chunkChars: 3500,
      kbPaths: [
        "knowledge_bases/energy_metering.json",
        "knowledge_bases/energy_metering_protocol_layer.json",
        "knowledge_bases/energy_metering_cosem_classes.json",
      ],
      domainPackDir: "domain_packs/dlms_cosem",
    })).toEqual([
      "run",
      "--input",
      "C:\\input\\Appendix 9.docx",
      "--out",
      "E:\\out\\abnt",
      "--chunk-chars",
      "3500",
      "--kb",
      "knowledge_bases/energy_metering.json",
      "--kb",
      "knowledge_bases/energy_metering_protocol_layer.json",
      "--kb",
      "knowledge_bases/energy_metering_cosem_classes.json",
      "--domain-pack",
      "domain_packs/dlms_cosem",
    ])
  })

  it("resolves unpacked Python scripts from packaged Electron resources", () => {
    const resourcesPath = "C:\\Program Files\\Requirement Atomizer\\resources"
    const unpackedScript = path.resolve(resourcesPath, "app.asar.unpacked", "desktop_tasks.py")

    const resolved = resolvePythonScriptPath("desktop_tasks.py", {
      dirname: "C:\\Program Files\\Requirement Atomizer\\resources\\app.asar\\electron",
      resourcesPath,
      existsSync: (candidate: string) => candidate === unpackedScript,
    })

    expect(resolved).toBe(unpackedScript)
  })
})
