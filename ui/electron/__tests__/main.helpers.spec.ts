import { mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { describe, expect, it } from "vitest"
import path from "node:path"

import {
  PROGRESS_PREFIX,
  buildLlmEnvironment,
  buildRunPipelineArgs,
  drainProgressLines,
  loadLlmSettingsConfig,
  normalizeLlmSettings,
  resolveBackendCommand,
  resolvePythonScriptPath,
  saveLlmSettingsConfig,
} from "../main.helpers.cjs"

describe("Electron main helpers", () => {
  it("builds run pipeline args with ABNT preset inputs", () => {
    expect(buildRunPipelineArgs({
      inputPath: "C:\\input\\Appendix 9.docx",
      outDir: "E:\\out\\abnt",
      skipReview: false,
      llmRoute: "openai_compatible",
      reviewScope: "targeted",
      llmReviewLimit: 50,
      chunkChars: 3500,
      kbPaths: [
        "knowledge_bases/energy_metering.json",
        "knowledge_bases/energy_metering_protocol_layer.json",
        "knowledge_bases/energy_metering_cosem_classes.json",
        "knowledge_bases/compiled_from_obsidian.json",
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
      "--llm-review-limit",
      "50",
      "--chunk-chars",
      "3500",
      "--kb",
      "knowledge_bases/energy_metering.json",
      "--kb",
      "knowledge_bases/energy_metering_protocol_layer.json",
      "--kb",
      "knowledge_bases/energy_metering_cosem_classes.json",
      "--kb",
      "knowledge_bases/compiled_from_obsidian.json",
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

  it("prefers packaged backend executable over a system Python runtime", () => {
    const resourcesPath = "C:\\Program Files\\Requirement Atomizer\\resources"
    const backendExe = path.resolve(resourcesPath, "backend", "ratomizer-desktop.exe")

    const command = resolveBackendCommand("desktop_tasks.py", {
      dirname: "C:\\Program Files\\Requirement Atomizer\\resources\\app.asar\\electron",
      resourcesPath,
      existsSync: (candidate: string) => candidate === backendExe,
      env: {},
      platform: "win32",
    })

    expect(command).toEqual({
      command: backendExe,
      args: [],
      cwd: path.dirname(backendExe),
      packaged: true,
    })
  })

  it("falls back to Python source execution during development", () => {
    const scriptPath = path.resolve("D:\\Codex\\requirement-atomizer-vue3", "desktop_tasks.py")

    const command = resolveBackendCommand("desktop_tasks.py", {
      dirname: "D:\\Codex\\requirement-atomizer-vue3\\ui\\electron",
      resourcesPath: "",
      existsSync: (candidate: string) => candidate === scriptPath,
      env: { RATOMIZER_PYTHON: "py -3.12" },
      platform: "win32",
    })

    expect(command).toEqual({
      command: "py -3.12",
      args: [scriptPath],
      cwd: path.dirname(scriptPath),
      packaged: false,
    })
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
      RATOMIZER_LLM_CONCURRENCY: "4",
      ZHIPU_API_KEY: "sk-secret",
    })
  })

  it("clamps AI-extract concurrency to 1..16 and exposes it to Python", () => {
    expect(normalizeLlmSettings({ concurrency: 99 }).concurrency).toBe(16)
    expect(normalizeLlmSettings({ concurrency: 0 }).concurrency).toBe(1)
    expect(normalizeLlmSettings({ concurrency: "abc" }).concurrency).toBe(4) // 默认
    expect(normalizeLlmSettings({ concurrency: 2 }).concurrency).toBe(2)
    expect(buildLlmEnvironment({ concurrency: 2 })).toMatchObject({ RATOMIZER_LLM_CONCURRENCY: "2" })
  })

  it("defaults completeness self-check on and exposes the toggle to Python", () => {
    expect(normalizeLlmSettings({}).selfCheck).toBe(true)            // 旧配置无此字段 → 默认开
    expect(normalizeLlmSettings({ selfCheck: false }).selfCheck).toBe(false)
    expect(buildLlmEnvironment({ selfCheck: false })).toMatchObject({ RATOMIZER_AI_SELFCHECK: "0" })
    expect(buildLlmEnvironment({})).toMatchObject({ RATOMIZER_AI_SELFCHECK: "1" })
  })

  it("persists OpenAI-compatible API settings in a config file with an encrypted API key", () => {
    const configDir = mkdtempSync(path.join(tmpdir(), "ratomizer-settings-"))
    const configPath = path.join(configDir, "llm-settings.json")
    const safeStorage = {
      isEncryptionAvailable: () => true,
      encryptString: (value: string) => Buffer.from(`encrypted:${value}`, "utf8"),
      decryptString: (value: Buffer) => value.toString("utf8").replace(/^encrypted:/, ""),
    }

    try {
      const saved = saveLlmSettingsConfig(configPath, {
        enabled: true,
        baseUrl: " https://open.bigmodel.cn/api/paas/v4 ",
        model: " glm-4-plus ",
        apiKeyEnv: " ZHIPU_API_KEY ",
        apiKey: " sk-secret ",
        temperature: "0.2",
        maxTokens: "2048",
        timeoutS: "15",
        maxRetries: "0",
      }, safeStorage)

      expect(saved.settings).toMatchObject({
        enabled: true,
        baseUrl: "https://open.bigmodel.cn/api/paas/v4",
        model: "glm-4-plus",
        apiKeyEnv: "ZHIPU_API_KEY",
      })
      expect(saved.apiKey).toBe("sk-secret")

      const rawConfig = readFileSync(configPath, "utf8")
      expect(rawConfig).toContain("apiKeyProtected")
      expect(rawConfig).not.toContain("sk-secret")

      const loaded = loadLlmSettingsConfig(configPath, safeStorage)

      expect(loaded.settings).toMatchObject({
        enabled: true,
        baseUrl: "https://open.bigmodel.cn/api/paas/v4",
        model: "glm-4-plus",
        apiKeyEnv: "ZHIPU_API_KEY",
      })
      expect(loaded.apiKey).toBe("sk-secret")
    } finally {
      rmSync(configDir, { recursive: true, force: true })
    }
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
