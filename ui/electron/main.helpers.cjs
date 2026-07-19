const fs = require("node:fs");
const path = require("node:path");

const PROGRESS_PREFIX = "__RATOMIZER_PROGRESS__";

function buildRunPipelineArgs(input) {
  return [
    "run",
    "--input",
    input.inputPath,
    "--out",
    input.outDir,
    ...(input.skipReview ? ["--skip-review"] : []),
    ...(input.llmRoute ? ["--llm-route", input.llmRoute] : []),
    ...(input.reviewScope ? ["--review-scope", input.reviewScope] : []),
    ...(input.llmReviewLimit ? ["--llm-review-limit", String(input.llmReviewLimit)] : []),
    ...(input.chunkChars ? ["--chunk-chars", String(input.chunkChars)] : []),
    ...arrayArgs("--kb", input.kbPaths),
    ...(input.domainPackDir ? ["--domain-pack", input.domainPackDir] : []),
  ];
}

function buildChainArgs(input) {
  return [
    "chain",
    "--out",
    input.outDir,
    "--stages",
    (input.stages || []).join(","),
    ...(input.llmRoute ? ["--llm-route", input.llmRoute] : []),
    ...(input.templatePath ? ["--template", input.templatePath] : []),
    ...(input.sampleRatio ? ["--sample-ratio", String(input.sampleRatio)] : []),
    ...(input.annotationLayoutMode
      ? ["--annotation-layout-mode", input.annotationLayoutMode] : []),
  ];
}

function buildExportAnnotationArgs(input) {
  return [
    "export-annotation-html",
    "--out",
    input.outDir,
    ...(input.route ? ["--route", input.route] : []),
    ...(input.layoutMode ? ["--layout-mode", input.layoutMode] : []),
  ];
}

const DEFAULT_LLM_SETTINGS = {
  enabled: false,
  visionCapable: false,
  baseUrl: "http://127.0.0.1:11434/v1",
  model: "qwen2.5:14b",
  apiKeyEnv: "RATOMIZER_LLM_API_KEY",
  temperature: 0,
  maxTokens: 4096,
  timeoutS: 60,
  maxRetries: 3,
  concurrency: 8,
  selfCheck: true,
};

const MAX_CONCURRENCY = 16;

const SECRET_PREFIX = "safeStorage:v1:";
const SESSION_API_KEY_ENV = "RATOMIZER_LLM_SESSION_API_KEY";

function normalizeLlmSettings(input = {}) {
  return {
    enabled: Boolean(input.enabled),
    visionCapable: input.visionCapable == null
      ? DEFAULT_LLM_SETTINGS.visionCapable : Boolean(input.visionCapable),
    baseUrl: stringValue(input.baseUrl, DEFAULT_LLM_SETTINGS.baseUrl),
    model: stringValue(input.model, DEFAULT_LLM_SETTINGS.model),
    apiKeyEnv: stringValue(input.apiKeyEnv, DEFAULT_LLM_SETTINGS.apiKeyEnv),
    temperature: numberValue(input.temperature, DEFAULT_LLM_SETTINGS.temperature),
    maxTokens: integerValue(input.maxTokens, DEFAULT_LLM_SETTINGS.maxTokens),
    timeoutS: numberValue(input.timeoutS, DEFAULT_LLM_SETTINGS.timeoutS),
    maxRetries: integerValue(input.maxRetries, DEFAULT_LLM_SETTINGS.maxRetries),
    concurrency: Math.max(1, Math.min(MAX_CONCURRENCY,
      integerValue(input.concurrency, DEFAULT_LLM_SETTINGS.concurrency))),
    // 缺省（旧配置文件无此字段）回落默认开，显式 false 才关
    selfCheck: input.selfCheck == null ? DEFAULT_LLM_SETTINGS.selfCheck : Boolean(input.selfCheck),
  };
}

function normalizeLlmEndpoint(value) {
  const raw = stringValue(value, DEFAULT_LLM_SETTINGS.baseUrl);
  let endpoint;
  try {
    endpoint = new URL(raw);
  } catch {
    throw new TypeError("LLM endpoint must be a valid URL");
  }
  if (endpoint.protocol !== "http:" && endpoint.protocol !== "https:") {
    throw new TypeError("LLM endpoint must use http or https");
  }
  if (endpoint.username || endpoint.password) {
    throw new TypeError("LLM endpoint must not contain credentials");
  }
  const hostname = endpoint.hostname.toLowerCase();
  const isLoopback = hostname === "localhost"
    || hostname.endsWith(".localhost")
    || hostname === "127.0.0.1"
    || hostname === "[::1]";
  if (endpoint.protocol === "http:" && !isLoopback) {
    throw new TypeError("Remote LLM endpoints must use https");
  }
  if (endpoint.search || endpoint.hash) {
    throw new TypeError("LLM endpoint must not contain a query or fragment");
  }
  endpoint.pathname = endpoint.pathname.replace(/\/+$/, "");
  return endpoint.toString().replace(/\/$/, "");
}

function sameLlmCredentialScope(left, right) {
  if (!left || !right) return false;
  try {
    return normalizeLlmEndpoint(left.baseUrl) === normalizeLlmEndpoint(right.baseUrl)
      && stringValue(left.apiKeyEnv, DEFAULT_LLM_SETTINGS.apiKeyEnv)
        === stringValue(right.apiKeyEnv, DEFAULT_LLM_SETTINGS.apiKeyEnv);
  } catch {
    return false;
  }
}

function bindAmbientLlmCredential(settings, env = process.env) {
  const normalized = normalizeLlmSettings(settings);
  normalized.baseUrl = normalizeLlmEndpoint(normalized.baseUrl);
  // Ambient lookup is only for the startup config loaded by the main process.
  // Requiring an API-key-shaped name prevents generic secrets such as PATH or
  // AWS_SECRET_ACCESS_KEY from becoming bearer credentials even in that config.
  if (!/^[A-Za-z_][A-Za-z0-9_]*API_KEY$/i.test(normalized.apiKeyEnv)) {
    return null;
  }
  const apiKey = typeof env[normalized.apiKeyEnv] === "string"
    ? env[normalized.apiKeyEnv].trim() : "";
  if (!apiKey) return null;
  return {
    settings: { baseUrl: normalized.baseUrl, apiKeyEnv: normalized.apiKeyEnv },
    apiKey,
  };
}

function resolveBoundLlmApiKey(settings, sessionApiKey = "", ambientCredential = null) {
  const sessionKey = String(sessionApiKey || "").trim();
  if (sessionKey) return sessionKey;
  if (ambientCredential
      && sameLlmCredentialScope(settings, ambientCredential.settings)) {
    return String(ambientCredential.apiKey || "").trim();
  }
  return "";
}

function resolveLlmTestConnection(input, savedSettings, sessionApiKey = "") {
  const settings = normalizeLlmSettings({ ...(savedSettings || {}), ...(input || {}) });
  settings.baseUrl = normalizeLlmEndpoint(settings.baseUrl);
  const explicitApiKey = typeof input?.apiKey === "string" ? input.apiKey.trim() : "";
  const sameScope = sameLlmCredentialScope(settings, savedSettings);
  if (!explicitApiKey && !sameScope) {
    throw new Error("Testing a different LLM endpoint or API key variable requires an explicit API key");
  }
  return {
    settings,
    apiKey: explicitApiKey || (sameScope ? String(sessionApiKey || "").trim() : ""),
  };
}

function buildLlmEnvironment(settings, env = process.env) {
  const normalized = normalizeLlmSettings(settings);
  const result = {
    ...env,
    RATOMIZER_LLM_BASE_URL: normalized.baseUrl,
    RATOMIZER_LLM_MODEL: normalized.model,
    // Renderer-controlled apiKeyEnv is metadata only. Child processes always read the
    // safeStorage session key from a fixed variable, so arbitrary parent env values
    // cannot be selected and forwarded to a renderer-controlled endpoint.
    RATOMIZER_LLM_API_KEY_ENV: SESSION_API_KEY_ENV,
    RATOMIZER_LLM_TEMPERATURE: String(normalized.temperature),
    RATOMIZER_LLM_MAX_TOKENS: String(normalized.maxTokens),
    RATOMIZER_LLM_TIMEOUT_S: String(normalized.timeoutS),
    RATOMIZER_LLM_MAX_RETRIES: String(normalized.maxRetries),
    RATOMIZER_LLM_CONCURRENCY: String(normalized.concurrency),
    RATOMIZER_AI_SELFCHECK: normalized.selfCheck ? "1" : "0",
  };
  const apiKey = typeof settings?.apiKey === "string" ? settings.apiKey.trim() : "";
  if (apiKey) {
    result[SESSION_API_KEY_ENV] = apiKey;
  } else {
    delete result[SESSION_API_KEY_ENV];
  }
  return result;
}

function loadLlmSettingsConfig(configPath, safeStorage) {
  try {
    const payload = JSON.parse(fs.readFileSync(configPath, "utf8"));
    const settings = normalizeLlmSettings(payload);
    return {
      settings,
      apiKey: decryptApiKey(payload.apiKeyProtected, safeStorage),
    };
  } catch {
    return {
      settings: normalizeLlmSettings(DEFAULT_LLM_SETTINGS),
      apiKey: "",
    };
  }
}

function saveLlmSettingsConfig(
  configPath,
  input,
  safeStorage,
  previousApiKey = "",
  previousSettings = null,
) {
  const settings = normalizeLlmSettings(input);
  settings.baseUrl = normalizeLlmEndpoint(settings.baseUrl);
  const explicitApiKey = typeof input?.apiKey === "string" ? input.apiKey.trim() : "";
  const apiKey = explicitApiKey
    || (sameLlmCredentialScope(settings, previousSettings) ? previousApiKey : "");
  const payload = { ...settings };
  const protectedKey = encryptApiKey(apiKey, safeStorage);
  if (protectedKey) {
    payload.apiKeyProtected = protectedKey;
  }
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, JSON.stringify(payload, null, 2), "utf8");
  return { settings, apiKey };
}

function shouldReuseApiSession(session, apiProcess, outputDir) {
  if (!session?.baseUrl || !session?.token || !session?.outputDir || !outputDir) {
    return false;
  }
  if (!apiProcess || apiProcess.killed || apiProcess.exitCode != null) {
    return false;
  }
  return normalizeFsPath(session.outputDir) === normalizeFsPath(outputDir);
}

function normalizeFsPath(value) {
  return path.resolve(String(value || "")).replace(/\\/g, "/").toLowerCase();
}

function encryptApiKey(apiKey, safeStorage) {
  if (!apiKey) return "";
  if (!safeStorage?.isEncryptionAvailable?.()) return "";
  return `${SECRET_PREFIX}${safeStorage.encryptString(apiKey).toString("base64")}`;
}

function decryptApiKey(value, safeStorage) {
  if (typeof value !== "string" || !value.startsWith(SECRET_PREFIX)) return "";
  if (!safeStorage?.isEncryptionAvailable?.()) return "";
  try {
    return safeStorage.decryptString(Buffer.from(value.slice(SECRET_PREFIX.length), "base64"));
  } catch {
    return "";
  }
}

function resolvePythonScriptPath(filename, options = {}) {
  const dirname = options.dirname || __dirname;
  const resourcesPath = options.resourcesPath || process.resourcesPath || "";
  const existsSync = options.existsSync || fs.existsSync;
  const candidates = [
    path.resolve(dirname, "../..", filename),
    path.resolve(dirname, "../../..", filename),
    path.resolve(resourcesPath, filename),
    path.resolve(resourcesPath, "app.asar.unpacked", filename),
  ];
  return candidates.find((candidate) => existsSync(candidate)) || candidates[0];
}

function resolveBackendCommand(filename, options = {}) {
  const resourcesPath = options.resourcesPath || process.resourcesPath || "";
  const existsSync = options.existsSync || fs.existsSync;
  const platform = options.platform || process.platform;
  const env = options.env || process.env;
  const executableName = platform === "win32" ? "ratomizer-desktop.exe" : "ratomizer-desktop";
  const backendCandidates = [
    path.resolve(resourcesPath, "backend", executableName),
    path.resolve(resourcesPath, "app.asar.unpacked", "backend", executableName),
  ];
  const backendExe = backendCandidates.find((candidate) => existsSync(candidate));
  if (backendExe) {
    return {
      command: backendExe,
      args: [],
      cwd: path.dirname(backendExe),
      packaged: true,
    };
  }

  const scriptPath = resolvePythonScriptPath(filename, options);
  return {
    command: env.RATOMIZER_PYTHON || "python",
    args: [scriptPath],
    cwd: path.dirname(scriptPath),
    packaged: false,
  };
}

function drainProgressLines(buffer, prefix = PROGRESS_PREFIX) {
  const lines = buffer.split(/\r?\n/);
  const remaining = lines.pop() || "";
  const events = [];
  const output = [];
  for (const line of lines) {
    if (line.startsWith(prefix)) {
      try {
        events.push(JSON.parse(line.slice(prefix.length)));
      } catch {
        output.push(line);
      }
    } else {
      output.push(line);
    }
  }
  return {
    events,
    output: output.length ? `${output.join("\n")}\n` : "",
    remaining,
  };
}

function arrayArgs(flag, values) {
  return (values || []).flatMap((value) => [flag, value]);
}

function stringValue(value, fallback) {
  const text = typeof value === "string" ? value.trim() : "";
  return text || fallback;
}

function numberValue(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function integerValue(value, fallback) {
  const parsed = Number.parseInt(String(value), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

// 后端子进程 stderr 持久化（按日滚动）。此前 stderr 只攒内存：失败拼弹窗、成功整段丢弃——
// 排查"为什么慢/为什么降级"无迹可循。日志目录：<userData>/logs/backend-YYYY-MM-DD.log。
function backendLogPath(logsDir, now = new Date()) {
  const stamp = now.toISOString().slice(0, 10);
  return path.join(logsDir, `backend-${stamp}.log`);
}

function appendBackendLog(logsDir, label, chunk, deps = {}) {
  const fsImpl = deps.fs || fs;
  const now = deps.now || new Date();
  try {
    fsImpl.mkdirSync(logsDir, { recursive: true });
    const text = String(chunk || "").replace(/\r\n/g, "\n");
    if (!text.trim()) return;
    const stamp = now.toISOString().replace("T", " ").slice(0, 19);
    const prefixed = text.split("\n").filter(Boolean).map((line) => `${stamp} [${label}] ${line}`).join("\n");
    fsImpl.appendFileSync(backendLogPath(logsDir, now), prefixed + "\n", "utf8");
  } catch {
    /* 日志写失败绝不影响任务本身 */
  }
}

module.exports = {
  DEFAULT_LLM_SETTINGS,
  PROGRESS_PREFIX,
  appendBackendLog,
  backendLogPath,
  bindAmbientLlmCredential,
  buildLlmEnvironment,
  buildChainArgs,
  buildExportAnnotationArgs,
  buildRunPipelineArgs,
  drainProgressLines,
  loadLlmSettingsConfig,
  normalizeLlmEndpoint,
  normalizeLlmSettings,
  resolveLlmTestConnection,
  resolveBackendCommand,
  resolveBoundLlmApiKey,
  resolvePythonScriptPath,
  saveLlmSettingsConfig,
  SESSION_API_KEY_ENV,
  sameLlmCredentialScope,
  shouldReuseApiSession,
};
