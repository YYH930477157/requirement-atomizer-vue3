import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { describe, expect, it } from "vitest"
import path from "node:path"

import {
  PROGRESS_PREFIX,
  RECENT_SESSIONS_LIMIT,
  bindAmbientLlmCredential,
  buildChainArgs,
  buildExportAnnotationArgs,
  buildLlmEnvironment,
  buildRunPipelineArgs,
  drainProgressLines,
  isLikelyOutputDir,
  listRecentSessions,
  loadLlmSettingsConfig,
  loadRecentSessions,
  normalizeLlmEndpoint,
  normalizeLlmSettings,
  recordRecentSession,
  resolveAutoRestoreCandidates,
  resolveAutoRestoreDir,
  resolveBackendCommand,
  resolveBoundLlmApiKey,
  resolveLlmTestConnection,
  resolvePythonScriptPath,
  saveLlmSettingsConfig,
  SESSION_API_KEY_ENV,
  sameLlmCredentialScope,
  shouldReuseApiSession,
} from "../main.helpers.cjs"

describe("Electron main helpers", () => {
  it("forwards annotation layout modes to standalone and chain commands", () => {
    expect(buildExportAnnotationArgs({
      outDir: "E:\\out\\abnt",
      route: "openai_compatible",
      layoutMode: "pdf_original",
    })).toEqual([
      "export-annotation-html", "--out", "E:\\out\\abnt",
      "--route", "openai_compatible", "--layout-mode", "pdf_original",
    ])

    expect(buildChainArgs({
      outDir: "E:\\out\\abnt",
      stages: ["compose", "export-annotation-html"],
      llmRoute: "stub",
      annotationLayoutMode: "optimized",
    })).toEqual([
      "chain", "--out", "E:\\out\\abnt", "--stages", "compose,export-annotation-html",
      "--llm-route", "stub", "--annotation-layout-mode", "optimized",
    ])
  })

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

  it("reuses a live API session for the same output directory", () => {
    const session = {
      baseUrl: "http://127.0.0.1:8770",
      token: "local-token",
      outputDir: "E:\\out\\abnt",
    }
    const liveProcess = { killed: false, exitCode: null }

    expect(shouldReuseApiSession(session, liveProcess, "E:\\out\\abnt")).toBe(true)
    expect(shouldReuseApiSession(session, liveProcess, "E:\\out\\other")).toBe(false)
    expect(shouldReuseApiSession(session, { killed: true, exitCode: null }, "E:\\out\\abnt")).toBe(false)
    expect(shouldReuseApiSession(session, { killed: false, exitCode: 1 }, "E:\\out\\abnt")).toBe(false)
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

    const childEnv = buildLlmEnvironment({ ...settings, apiKey: "sk-secret" }, {})
    expect(childEnv).toMatchObject({
      RATOMIZER_LLM_BASE_URL: "https://open.bigmodel.cn/api/paas/v4",
      RATOMIZER_LLM_MODEL: "glm-4-plus",
      RATOMIZER_LLM_API_KEY_ENV: SESSION_API_KEY_ENV,
      RATOMIZER_LLM_TEMPERATURE: "0.2",
      RATOMIZER_LLM_MAX_TOKENS: "2048",
      RATOMIZER_LLM_TIMEOUT_S: "15",
      RATOMIZER_LLM_MAX_RETRIES: "0",
      RATOMIZER_LLM_CONCURRENCY: "8",
      [SESSION_API_KEY_ENV]: "sk-secret",
    })
    expect(childEnv).not.toHaveProperty("ZHIPU_API_KEY")
  })

  it("normalizes and validates LLM endpoints before credentials can be attached", () => {
    expect(normalizeLlmEndpoint(" HTTPS://API.Example.com:443/v1/ "))
      .toBe("https://api.example.com/v1")
    expect(normalizeLlmEndpoint("http://localhost:11434/v1/"))
      .toBe("http://localhost:11434/v1")
    expect(normalizeLlmEndpoint("http://127.0.0.1:11434/v1"))
      .toBe("http://127.0.0.1:11434/v1")

    expect(() => normalizeLlmEndpoint("ftp://api.example.com/v1")).toThrow(/http or https/)
    expect(() => normalizeLlmEndpoint("http://api.example.com/v1")).toThrow(/must use https/)
    expect(() => normalizeLlmEndpoint("https://user:secret@api.example.com/v1"))
      .toThrow(/credentials/)
  })

  it("reuses a session key only within the saved endpoint and API-key variable scope", () => {
    const saved = {
      baseUrl: "https://api.example.com/v1",
      apiKeyEnv: "EXAMPLE_API_KEY",
      model: "saved-model",
    }
    const sameScope = resolveLlmTestConnection({
      baseUrl: "https://API.EXAMPLE.com:443/v1/",
      apiKeyEnv: "EXAMPLE_API_KEY",
      model: "new-model",
    }, saved, "session-secret")

    expect(sameScope.apiKey).toBe("session-secret")
    expect(sameScope.settings.baseUrl).toBe("https://api.example.com/v1")
    expect(sameLlmCredentialScope(sameScope.settings, saved)).toBe(true)

    const previousEnvKey = process.env.EXAMPLE_API_KEY
    process.env.EXAMPLE_API_KEY = "ambient-secret"
    try {
      expect(resolveLlmTestConnection({
        baseUrl: saved.baseUrl,
        apiKeyEnv: saved.apiKeyEnv,
      }, saved, "").apiKey).toBe("")
    } finally {
      if (previousEnvKey == null) delete process.env.EXAMPLE_API_KEY
      else process.env.EXAMPLE_API_KEY = previousEnvKey
    }

    expect(() => resolveLlmTestConnection({
      baseUrl: "https://attacker.example/v1",
      apiKeyEnv: "EXAMPLE_API_KEY",
    }, saved, "session-secret")).toThrow(/explicit API key/)
    expect(() => resolveLlmTestConnection({
      baseUrl: saved.baseUrl,
      apiKeyEnv: "UNRELATED_SECRET",
    }, saved, "session-secret")).toThrow(/explicit API key/)

    const explicit = resolveLlmTestConnection({
      baseUrl: "https://other.example/v1",
      apiKeyEnv: "OTHER_API_KEY",
      apiKey: "explicit-secret",
    }, saved, "session-secret")
    expect(explicit.apiKey).toBe("explicit-secret")
  })

  it("does not persist an old key when its endpoint or variable scope changes", () => {
    const configDir = mkdtempSync(path.join(tmpdir(), "ratomizer-scope-"))
    const configPath = path.join(configDir, "llm-settings.json")
    const safeStorage = {
      isEncryptionAvailable: () => true,
      encryptString: (value: string) => Buffer.from(`encrypted:${value}`, "utf8"),
      decryptString: (value: Buffer) => value.toString("utf8").replace(/^encrypted:/, ""),
    }
    const originalSettings = {
      baseUrl: "https://api.example.com/v1",
      apiKeyEnv: "EXAMPLE_API_KEY",
      model: "model-a",
    }

    try {
      const sameScope = saveLlmSettingsConfig(
        configPath,
        { ...originalSettings, baseUrl: "https://API.EXAMPLE.com:443/v1/" },
        safeStorage,
        "old-secret",
        originalSettings,
      )
      expect(sameScope.apiKey).toBe("old-secret")

      const changedEndpoint = saveLlmSettingsConfig(
        configPath,
        { ...originalSettings, baseUrl: "https://other.example/v1" },
        safeStorage,
        "old-secret",
        originalSettings,
      )
      expect(changedEndpoint.apiKey).toBe("")
      expect(loadLlmSettingsConfig(configPath, safeStorage).apiKey).toBe("")
      expect(readFileSync(configPath, "utf8")).not.toContain("apiKeyProtected")

      const changedVariable = saveLlmSettingsConfig(
        configPath,
        { ...originalSettings, apiKeyEnv: "OTHER_API_KEY" },
        safeStorage,
        "old-secret",
        originalSettings,
      )
      expect(changedVariable.apiKey).toBe("")
    } finally {
      rmSync(configDir, { recursive: true, force: true })
    }
  })

  it("never selects a renderer-named ambient variable as the child API key", () => {
    const childEnv = buildLlmEnvironment({
      baseUrl: "https://attacker.example/v1",
      apiKeyEnv: "AWS_SECRET_ACCESS_KEY",
    }, {
      AWS_SECRET_ACCESS_KEY: "ambient-secret",
      [SESSION_API_KEY_ENV]: "stale-session-secret",
    })

    expect(childEnv.RATOMIZER_LLM_API_KEY_ENV).toBe(SESSION_API_KEY_ENV)
    expect(childEnv[SESSION_API_KEY_ENV]).toBeUndefined()
    expect(childEnv[childEnv.RATOMIZER_LLM_API_KEY_ENV]).not.toBe("ambient-secret")
  })

  it("binds an ambient API key to the startup endpoint scope only", () => {
    const startupSettings = {
      baseUrl: "https://api.example.com/v1",
      apiKeyEnv: "EXAMPLE_API_KEY",
    }
    const binding = bindAmbientLlmCredential(startupSettings, {
      EXAMPLE_API_KEY: "startup-secret",
      AWS_SECRET_ACCESS_KEY: "unrelated-secret",
    })

    expect(binding?.apiKey).toBe("startup-secret")
    expect(resolveBoundLlmApiKey(startupSettings, "", binding)).toBe("startup-secret")
    expect(resolveBoundLlmApiKey({
      ...startupSettings,
      baseUrl: "https://attacker.example/v1",
    }, "", binding)).toBe("")
    expect(resolveBoundLlmApiKey({
      ...startupSettings,
      apiKeyEnv: "OTHER_API_KEY",
    }, "", binding)).toBe("")
    expect(resolveBoundLlmApiKey(startupSettings, "safe-storage-secret", binding))
      .toBe("safe-storage-secret")

    expect(bindAmbientLlmCredential({
      baseUrl: "https://api.example.com/v1",
      apiKeyEnv: "AWS_SECRET_ACCESS_KEY",
    }, { AWS_SECRET_ACCESS_KEY: "unrelated-secret" })).toBeNull()
  })

  it("clamps AI-extract concurrency to 1..16 and exposes it to Python", () => {
    expect(normalizeLlmSettings({ concurrency: 99 }).concurrency).toBe(16)
    expect(normalizeLlmSettings({ concurrency: 0 }).concurrency).toBe(1)
    expect(normalizeLlmSettings({ concurrency: "abc" }).concurrency).toBe(8) // 默认
    expect(normalizeLlmSettings({ concurrency: 2 }).concurrency).toBe(2)
    expect(buildLlmEnvironment({ concurrency: 2 })).toMatchObject({ RATOMIZER_LLM_CONCURRENCY: "2" })
  })

  it("defaults completeness self-check on and exposes the toggle to Python", () => {
    expect(normalizeLlmSettings({}).selfCheck).toBe(true)            // 旧配置无此字段 → 默认开
    expect(normalizeLlmSettings({ selfCheck: false }).selfCheck).toBe(false)
    expect(buildLlmEnvironment({ selfCheck: false })).toMatchObject({ RATOMIZER_AI_SELFCHECK: "0" })
    expect(buildLlmEnvironment({})).toMatchObject({ RATOMIZER_AI_SELFCHECK: "1" })
  })

  it("defaults legacy settings to a non-visual model and preserves an explicit visual capability", () => {
    expect(normalizeLlmSettings({}).visionCapable).toBe(false)
    expect(normalizeLlmSettings({ visionCapable: true }).visionCapable).toBe(true)
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
        visionCapable: true,
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
        visionCapable: true,
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
        visionCapable: true,
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

describe("appendBackendLog", () => {
  const { appendBackendLog, backendLogPath } = require("../main.helpers.cjs")

  it("writes date-rolled file with timestamped label prefix", () => {
    const writes: Array<{ file: string; data: string }> = []
    const fakeFs = {
      mkdirSync: () => undefined,
      appendFileSync: (file: string, data: string) => writes.push({ file, data }),
    }
    const now = new Date("2026-07-04T10:20:30Z")
    appendBackendLog("/logs", "task", "line-a\r\nline-b\n", { fs: fakeFs, now })

    expect(writes).toHaveLength(1)
    expect(writes[0].file.replace(/\\/g, "/")).toBe("/logs/backend-2026-07-04.log")
    expect(writes[0].data).toContain("[task] line-a")
    expect(writes[0].data).toContain("[task] line-b")
    expect(writes[0].data).not.toContain("\r")
  })

  it("skips empty chunks and never throws on fs errors", () => {
    const boomFs = { mkdirSync: () => { throw new Error("boom") }, appendFileSync: () => undefined }
    expect(() => appendBackendLog("/logs", "api", "  \n", { fs: boomFs })).not.toThrow()
    expect(() => appendBackendLog("/logs", "api", "text", { fs: boomFs })).not.toThrow()
    expect(backendLogPath("/logs", new Date("2026-01-02T00:00:00Z")).replace(/\\/g, "/"))
      .toBe("/logs/backend-2026-01-02.log")
  })
})


describe("recent sessions helpers", () => {
  it("loads an empty history for missing or corrupt files", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "ratomizer-recent-"))
    try {
      const file = path.join(dir, "recent-sessions.json")
      expect(loadRecentSessions(file)).toEqual([])
      writeFileSync(file, "{ not json", "utf8")
      expect(loadRecentSessions(file)).toEqual([])
      // 条目缺 outputDir 的行被丢弃
      writeFileSync(file, JSON.stringify({ entries: [{ openedAt: "2026-01-01" }, { outputDir: "  " }] }), "utf8")
      expect(loadRecentSessions(file)).toEqual([])
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it("records deduped most-recent-first entries capped at the limit", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "ratomizer-recent-"))
    try {
      const file = path.join(dir, "recent-sessions.json")
      for (let index = 0; index < 10; index += 1) {
        recordRecentSession(file, path.join(dir, `out-${index}`), {
          now: new Date(Date.UTC(2026, 0, index + 1)),
        })
      }
      const entries = loadRecentSessions(file)
      expect(entries).toHaveLength(RECENT_SESSIONS_LIMIT)
      expect(entries[0].outputDir).toBe(path.join(dir, "out-9"))
      // 再次打开同一条目 → 提到最前且不重复
      recordRecentSession(file, path.join(dir, "out-5"), { now: new Date("2026-02-01T00:00:00Z") })
      const bumped = loadRecentSessions(file)
      expect(bumped[0].outputDir).toBe(path.join(dir, "out-5"))
      expect(bumped.filter((entry) => entry.outputDir === path.join(dir, "out-5"))).toHaveLength(1)
      expect(bumped[0].openedAt).toBe("2026-02-01T00:00:00.000Z")
      // 原子写：不残留 tmp 文件，主体是合法 JSON
      expect(readdirSync(dir).filter((name) => name.endsWith(".tmp"))).toEqual([])
      expect(JSON.parse(readFileSync(file, "utf8")).version).toBe(1)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it("detects likely output dirs by marker files only", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "ratomizer-recent-"))
    try {
      const outDir = path.join(dir, "out")
      mkdirSync(outDir, { recursive: true })
      expect(isLikelyOutputDir(outDir)).toBe(false)
      writeFileSync(path.join(outDir, "blocks.jsonl"), "", "utf8")
      expect(isLikelyOutputDir(outDir)).toBe(true)
      expect(isLikelyOutputDir(path.join(dir, "missing"))).toBe(false)
      expect(isLikelyOutputDir("")).toBe(false)
      // 标记也可以是 B 轨产物
      const bDir = path.join(dir, "b-track")
      mkdirSync(bDir, { recursive: true })
      writeFileSync(path.join(bDir, "ai_requirements.jsonl"), "", "utf8")
      expect(isLikelyOutputDir(bDir)).toBe(true)

      const corrupt = path.join(dir, "corrupt")
      mkdirSync(corrupt, { recursive: true })
      writeFileSync(path.join(corrupt, "manifest.json"), "{broken", "utf8")
      writeFileSync(path.join(corrupt, "blocks.jsonl"), "", "utf8")
      expect(isLikelyOutputDir(corrupt)).toBe(false)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it("labels recents from the manifest input and flags missing dirs", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "ratomizer-recent-"))
    try {
      const outDir = path.join(dir, "run-001")
      mkdirSync(outDir, { recursive: true })
      writeFileSync(
        path.join(outDir, "manifest.json"),
        JSON.stringify({ input: "D:/standards/ABNT NBR 16968.docx" }),
        "utf8",
      )
      const goneDir = path.join(dir, "gone")
      const file = path.join(dir, "recent-sessions.json")
      recordRecentSession(file, outDir, { now: new Date("2026-01-01T00:00:00Z") })
      recordRecentSession(file, goneDir, { now: new Date("2026-01-02T00:00:00Z") })

      const listed = listRecentSessions(file)
      expect(listed).toHaveLength(2)
      expect(listed[0].outputDir).toBe(goneDir)
      expect(listed[0].exists).toBe(false)
      expect(listed[0].isOutput).toBe(false)
      expect(listed[0].label).toBe("gone")
      expect(listed[1].exists).toBe(true)
      expect(listed[1].isOutput).toBe(true)
      expect(listed[1].label).toBe("ABNT NBR 16968.docx")
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it("auto-restore picks the first surviving output dir or none", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "ratomizer-recent-"))
    try {
      const gone = path.join(dir, "gone")
      const plain = path.join(dir, "plain")
      mkdirSync(plain, { recursive: true })
      const valid = path.join(dir, "valid")
      mkdirSync(valid, { recursive: true })
      writeFileSync(path.join(valid, "manifest.json"), "{}", "utf8")
      const file = path.join(dir, "recent-sessions.json")
      recordRecentSession(file, valid, { now: new Date("2026-01-01T00:00:00Z") })
      recordRecentSession(file, plain, { now: new Date("2026-01-02T00:00:00Z") })
      recordRecentSession(file, gone, { now: new Date("2026-01-03T00:00:00Z") })
      // 最新的已删除、次新的不是输出目录 → 跳过，落到最早的有效目录
      expect(resolveAutoRestoreDir(file)).toBe(valid)
      rmSync(valid, { recursive: true, force: true })
      expect(resolveAutoRestoreDir(file)).toBe("")
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it("returns surviving output candidates in recent order for startup fallback", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "ratomizer-recent-"))
    try {
      const first = path.join(dir, "first")
      const second = path.join(dir, "second")
      const missing = path.join(dir, "missing")
      mkdirSync(first, { recursive: true })
      mkdirSync(second, { recursive: true })
      writeFileSync(path.join(first, "manifest.json"), JSON.stringify({ input: "first.docx" }), "utf8")
      writeFileSync(path.join(second, "manifest.json"), JSON.stringify({ input: "second.docx" }), "utf8")
      const file = path.join(dir, "recent-sessions.json")
      recordRecentSession(file, first, { now: new Date("2026-01-01T00:00:00Z") })
      recordRecentSession(file, second, { now: new Date("2026-01-02T00:00:00Z") })
      recordRecentSession(file, missing, { now: new Date("2026-01-03T00:00:00Z") })

      expect(resolveAutoRestoreCandidates(file)).toEqual([second, first])
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})
