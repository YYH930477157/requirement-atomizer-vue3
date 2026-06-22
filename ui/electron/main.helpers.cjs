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
    ...(input.chunkChars ? ["--chunk-chars", String(input.chunkChars)] : []),
    ...arrayArgs("--kb", input.kbPaths),
    ...(input.domainPackDir ? ["--domain-pack", input.domainPackDir] : []),
  ];
}

const DEFAULT_LLM_SETTINGS = {
  enabled: false,
  baseUrl: "http://127.0.0.1:11434/v1",
  model: "qwen2.5:14b",
  apiKeyEnv: "RATOMIZER_LLM_API_KEY",
  temperature: 0,
  maxTokens: 1024,
  timeoutS: 60,
  maxRetries: 3,
};

const SECRET_PREFIX = "safeStorage:v1:";

function normalizeLlmSettings(input = {}) {
  return {
    enabled: Boolean(input.enabled),
    baseUrl: stringValue(input.baseUrl, DEFAULT_LLM_SETTINGS.baseUrl),
    model: stringValue(input.model, DEFAULT_LLM_SETTINGS.model),
    apiKeyEnv: stringValue(input.apiKeyEnv, DEFAULT_LLM_SETTINGS.apiKeyEnv),
    temperature: numberValue(input.temperature, DEFAULT_LLM_SETTINGS.temperature),
    maxTokens: integerValue(input.maxTokens, DEFAULT_LLM_SETTINGS.maxTokens),
    timeoutS: numberValue(input.timeoutS, DEFAULT_LLM_SETTINGS.timeoutS),
    maxRetries: integerValue(input.maxRetries, DEFAULT_LLM_SETTINGS.maxRetries),
  };
}

function buildLlmEnvironment(settings, env = process.env) {
  const normalized = normalizeLlmSettings(settings);
  const result = {
    ...env,
    RATOMIZER_LLM_BASE_URL: normalized.baseUrl,
    RATOMIZER_LLM_MODEL: normalized.model,
    RATOMIZER_LLM_API_KEY_ENV: normalized.apiKeyEnv,
    RATOMIZER_LLM_TEMPERATURE: String(normalized.temperature),
    RATOMIZER_LLM_MAX_TOKENS: String(normalized.maxTokens),
    RATOMIZER_LLM_TIMEOUT_S: String(normalized.timeoutS),
    RATOMIZER_LLM_MAX_RETRIES: String(normalized.maxRetries),
  };
  const apiKey = typeof settings?.apiKey === "string" ? settings.apiKey.trim() : "";
  if (apiKey) {
    result[normalized.apiKeyEnv] = apiKey;
  } else if (env[normalized.apiKeyEnv]) {
    result[normalized.apiKeyEnv] = env[normalized.apiKeyEnv];
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

function saveLlmSettingsConfig(configPath, input, safeStorage, previousApiKey = "") {
  const settings = normalizeLlmSettings(input);
  const explicitApiKey = typeof input?.apiKey === "string" ? input.apiKey.trim() : "";
  const apiKey = explicitApiKey || previousApiKey;
  const payload = { ...settings };
  const protectedKey = encryptApiKey(apiKey, safeStorage);
  if (protectedKey) {
    payload.apiKeyProtected = protectedKey;
  }
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, JSON.stringify(payload, null, 2), "utf8");
  return { settings, apiKey };
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

module.exports = {
  DEFAULT_LLM_SETTINGS,
  PROGRESS_PREFIX,
  buildLlmEnvironment,
  buildRunPipelineArgs,
  drainProgressLines,
  loadLlmSettingsConfig,
  normalizeLlmSettings,
  resolvePythonScriptPath,
  saveLlmSettingsConfig,
};
