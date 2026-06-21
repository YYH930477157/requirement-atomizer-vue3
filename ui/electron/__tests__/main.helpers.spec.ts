import { describe, expect, it } from "vitest"
import path from "node:path"

import {
  PROGRESS_PREFIX,
  buildLlmEnvironment,
  buildRunPipelineArgs,
  drainProgressLines,
  normalizeLlmSettings,
  resolvePythonScriptPath,
} from "../main.helpers.cjs"

describe("Electron main helpers", () => {
  it("builds run pipeline args with ABNT preset inputs", () => {
    expect(buildRunPipelineArgs({
      inputPath: "C:\\input\\Appendix 9.docx",
      outDir: "E:\\out\\abnt",
      skipReview: false,
      llmRoute: "openai_compatible",
      reviewScope: "targeted",
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
      "--llm-route",
      "openai_compatible",
      "--review-scope",
      "targeted",
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

  it("normalizes API settings and exposes them to Python child processes without persisting secrets", () => {
    const settings = normalizeLlmSettings({
      enabled: true,
      baseUrl: " https://open.bigmodel.cn/api/paas/v4 ",
      model: " glm-4-plus ",
      apiKeyEnv: " ZHIPU_API_KEY ",
      apiKey: " sk-secret ",
      temperature: "0.2",
      maxTokens: "2048",
      timeoutS: "15",
      maxRetries: "0",
    })

    expect(settings).toMatchObject({
      enabled: true,
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      model: "glm-4-plus",
      apiKeyEnv: "ZHIPU_API_KEY",
      temperature: 0.2,
      maxTokens: 2048,
      timeoutS: 15,
      maxRetries: 0,
    })
    expect(settings).not.toHaveProperty("apiKey")

    expect(buildLlmEnvironment({ ...settings, apiKey: "sk-secret" })).toMatchObject({
      RATOMIZER_LLM_BASE_URL: "https://open.bigmodel.cn/api/paas/v4",
      RATOMIZER_LLM_MODEL: "glm-4-plus",
      RATOMIZER_LLM_API_KEY_ENV: "ZHIPU_API_KEY",
      RATOMIZER_LLM_TEMPERATURE: "0.2",
      RATOMIZER_LLM_MAX_TOKENS: "2048",
      RATOMIZER_LLM_TIMEOUT_S: "15",
      RATOMIZER_LLM_MAX_RETRIES: "0",
      ZHIPU_API_KEY: "sk-secret",
    })
  })

  it("drains progress lines while preserving final task JSON stdout", () => {
    const first = drainProgressLines(
      `${PROGRESS_PREFIX}{"stage":"llm_review","completed":2,"total":5,"percent":40}\n{\n  "kind": "pipeline",\n`
    )

    expect(first.events).toEqual([{ stage: "llm_review", completed: 2, total: 5, percent: 40 }])
    expect(`${first.output}${first.remaining}`).toBe('{\n  "kind": "pipeline",\n')

    const second = drainProgressLines(`${first.remaining}  "out_dir": "E:\\\\out"\n}\n`)

    expect(second.events).toEqual([])
    expect(`${first.output}${second.output}${second.remaining}`.trim()).toBe('{\n  "kind": "pipeline",\n  "out_dir": "E:\\\\out"\n}')
  })
})
