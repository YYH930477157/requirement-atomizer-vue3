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

// --- 最近会话（重启后直接查看上次结果）---------------------------------------
// 持久化在 <userData>/recent-sessions.json（机器本地，只含输出目录路径与时间，无敏感内容）。
// 每次成功连接审查会话（含复用）都登记；重启时主进程自动恢复最近一个仍然存在的输出目录，
// 渲染进程的 loadInitialApiSession 轮询 getApiSession 自然接上——查看历史结果不必重跑管线。
const OUTPUT_DIR_MARKERS = ["manifest.json", "blocks.jsonl", "ai_requirements.jsonl"];
const RESULT_PACKAGE_SCHEMA = "ratomizer-result-package/v1";
const OUTPUT_LAYOUT_VERSION = "result-layout-v1";
const RECENT_SESSIONS_LIMIT = 8;
const RECENT_SESSIONS_VERSION = 1;

function containedPackagePath(dir, relativePath) {
  if (typeof relativePath !== "string" || !relativePath.trim() || path.isAbsolute(relativePath)) {
    return null;
  }
  const root = path.resolve(dir);
  const target = path.resolve(root, relativePath);
  const relative = path.relative(root, target);
  if (!relative || relative.startsWith(`..${path.sep}`) || relative === ".." || path.isAbsolute(relative)) {
    return null;
  }
  return target;
}

// S16（review-2026-08-03）：本函数在 JS 侧重实现 result-package marker 契约的
// 一个子集（schema/layout_version/analysis_status/workspace/deliverables/
// completion_evidence 存在性）。权威校验在 Python result_package._validate_package
// （与 schemas/result_package.schema.json 对齐）——此处只做打开前的快速分类，
// 绝不替代权威校验；任何一侧契约改动必须同步检查另一侧。
function classifyOutputDir(dirPath, deps = {}) {
  const fsImpl = deps.fs || fs;
  const dir = String(dirPath || "").trim();
  if (!dir) return { kind: "not_output", analysisStatus: "invalid", reason: "empty_path" };
  try {
    if (!fsImpl.statSync(dir).isDirectory()) {
      return { kind: "not_output", analysisStatus: "invalid", reason: "not_directory" };
    }
  } catch {
    return { kind: "not_output", analysisStatus: "invalid", reason: "missing_directory" };
  }
  const packagePath = path.join(dir, "result-package.json");
  if (fsImpl.existsSync(packagePath)) {
    try {
      if (!fsImpl.statSync(packagePath).isFile()) {
        return { kind: "invalid", analysisStatus: "invalid", reason: "marker_not_file" };
      }
      const marker = JSON.parse(fsImpl.readFileSync(packagePath, "utf8"));
      if (marker?.schema !== RESULT_PACKAGE_SCHEMA || marker?.layout_version !== OUTPUT_LAYOUT_VERSION) {
        return { kind: "invalid", analysisStatus: "invalid", reason: "unsupported_marker" };
      }
      if (!["running", "incomplete", "completed"].includes(marker?.analysis_status)) {
        return { kind: "invalid", analysisStatus: "invalid", reason: "invalid_status" };
      }
      if (marker?.workspace !== ".ratomizer" || !marker?.input?.display_name) {
        return { kind: "invalid", analysisStatus: "invalid", reason: "invalid_contract" };
      }
      const workspacePath = containedPackagePath(dir, marker.workspace);
      if (!workspacePath || !fsImpl.statSync(workspacePath).isDirectory()) {
        return { kind: "invalid", analysisStatus: "invalid", reason: "missing_workspace" };
      }
      const publicationJournal = path.join(
        workspacePath, "stages", ".result-package-publication.json",
      );
      if (fsImpl.existsSync(publicationJournal)) {
        return {
          kind: "invalid",
          analysisStatus: "invalid",
          reason: "interrupted_publication",
        };
      }
      if (!Array.isArray(marker?.deliverables)) {
        return { kind: "invalid", analysisStatus: "invalid", reason: "invalid_deliverables" };
      }
      for (const deliverable of marker.deliverables) {
        const deliverablePath = containedPackagePath(dir, deliverable?.path);
        if (!deliverablePath || !fsImpl.existsSync(deliverablePath)) {
          return { kind: "invalid", analysisStatus: "invalid", reason: "missing_deliverable" };
        }
      }
      if (marker.analysis_status === "completed") {
        const evidence = marker?.analysis?.completion_evidence;
        if (!Array.isArray(evidence) || evidence.length === 0) {
          return { kind: "invalid", analysisStatus: "invalid", reason: "missing_completion_evidence" };
        }
        for (const item of evidence) {
          const evidencePath = containedPackagePath(dir, item?.path);
          if (!evidencePath || !fsImpl.statSync(evidencePath).isFile()) {
            return { kind: "invalid", analysisStatus: "invalid", reason: "missing_completion_evidence" };
          }
        }
      }
      const effectiveStatus = marker?.active_attempt?.status === "running"
        ? "running"
        : marker.analysis_status;
      return {
        kind: "package_v1",
        analysisStatus: effectiveStatus,
        reason: "",
        displayName: String(marker.input.display_name),
      };
    } catch {
      return { kind: "invalid", analysisStatus: "invalid", reason: "corrupt_marker" };
    }
  }
  // manifest 一旦存在就必须可解析；否则即使还有 blocks/AI 文件，也不能把半截目录
  // 选成自动恢复目标。没有 manifest 的旧 B 轨目录仍可由其他阶段产物恢复。
  const manifestPath = path.join(dir, "manifest.json");
  if (fsImpl.existsSync(manifestPath)) {
    try {
      if (!fsImpl.statSync(manifestPath).isFile()) {
        return { kind: "invalid", analysisStatus: "invalid", reason: "legacy_manifest_not_file" };
      }
      const manifest = JSON.parse(fsImpl.readFileSync(manifestPath, "utf8"));
      if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
        return { kind: "invalid", analysisStatus: "invalid", reason: "legacy_manifest_invalid" };
      }
    } catch {
      return { kind: "invalid", analysisStatus: "invalid", reason: "legacy_manifest_corrupt" };
    }
  }
  const legacy = OUTPUT_DIR_MARKERS
    .filter((marker) => marker !== "manifest.json")
    .some((marker) => {
      try {
        return fsImpl.statSync(path.join(dir, marker)).isFile();
      } catch {
        return false;
      }
    }) || fsImpl.existsSync(manifestPath);
  return legacy
    ? { kind: "legacy", analysisStatus: "legacy", reason: "" }
    : { kind: "not_output", analysisStatus: "invalid", reason: "no_output_markers" };
}

function isLikelyOutputDir(dirPath, deps = {}) {
  return ["package_v1", "legacy"].includes(classifyOutputDir(dirPath, deps).kind);
}

// I5（2026-08-03 清单）：legacy 扁平目录重跑直接按 legacy pipeline 运行——
// Electron 在调用 result-package-start 前先分类，legacy 目录不创建
// marker/.ratomizer（Python initialize_result_package 保持 fail-closed 不放宽）。
// 返回 null 表示走正常 package 启动路径（空目录初始化 / package_v1 续跑）。
function planResultPackageStart(outDir, deps = {}) {
  const classification = classifyOutputDir(outDir, deps);
  if (classification.kind !== "legacy") {
    return null;
  }
  return {
    kind: "result_package_start",
    ok: true,
    out_dir: String(outDir),
    layout: "legacy",
    package: null,
  };
}

// S7：单实例锁——双开桌面端会让两个 API 进程对同一输出目录互相抢锁/写
// recent-sessions read-modify-write 也丢更新。锁拿不到即退出并让既有实例聚焦，
// 不再为 recent-sessions 另加跨进程文件锁。注入 appLike 便于测试（无锁 API 的
// 运行环境视为已持有，行为与旧版多实例一致）。
function acquireSingleInstanceLock(appLike, onSecondInstance) {
  if (!appLike || typeof appLike.requestSingleInstanceLock !== "function") {
    return true;
  }
  const acquired = appLike.requestSingleInstanceLock();
  if (!acquired) {
    if (typeof appLike.quit === "function") {
      appLike.quit();
    }
    return false;
  }
  if (typeof appLike.on === "function") {
    appLike.on("second-instance", () => {
      if (typeof onSecondInstance === "function") {
        onSecondInstance();
      }
    });
  }
  return true;
}

// I6：后端失败 envelope 同时落 stdout 与 stderr（desktop_tasks._fail_with_envelope），
// runDesktopTaskProcess 非零退出时以 stderr 文本为 Error.message——从中解析回
// 结构化 envelope，让稳定错误码（如 requested_stage_partial）能透传到渲染层。
function parseTaskErrorEnvelope(error) {
  const text = String(error?.message || error || "");
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) {
    return null;
  }
  try {
    const parsed = JSON.parse(text.slice(start, end + 1));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    const envelopeError = parsed.error;
    if (!envelopeError || typeof envelopeError !== "object" || !envelopeError.type) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function loadRecentSessions(filePath, deps = {}) {
  const fsImpl = deps.fs || fs;
  try {
    const payload = JSON.parse(fsImpl.readFileSync(filePath, "utf8"));
    const entries = Array.isArray(payload?.entries) ? payload.entries : [];
    return entries
      .map((entry) => ({
        outputDir: String(entry?.outputDir || "").trim(),
        openedAt: String(entry?.openedAt || "").trim(),
      }))
      .filter((entry) => entry.outputDir);
  } catch {
    // 缺失/损坏按"无历史"处理——下次成功连接自愈，绝不影响应用启动
    return [];
  }
}

function recordRecentSession(filePath, outputDir, deps = {}) {
  const fsImpl = deps.fs || fs;
  const now = deps.now || new Date();
  const dir = String(outputDir || "").trim();
  if (!dir) return loadRecentSessions(filePath, deps);
  const normalized = normalizeFsPath(dir);
  // 按归一化路径去重（大小写/分隔符变体同一条），最新在前，封顶 8 条
  const rest = loadRecentSessions(filePath, deps)
    .filter((entry) => normalizeFsPath(entry.outputDir) !== normalized);
  const entries = [{ outputDir: dir, openedAt: now.toISOString() }, ...rest]
    .slice(0, RECENT_SESSIONS_LIMIT);
  // tmp+rename 原子写：崩溃不留半截 JSON（损坏即当无历史，下次成功连接自愈）
  fsImpl.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmp = `${filePath}.${process.pid}.tmp`;
  fsImpl.writeFileSync(
    tmp,
    JSON.stringify({ version: RECENT_SESSIONS_VERSION, entries }, null, 2),
    "utf8",
  );
  fsImpl.renameSync(tmp, filePath);
  return entries;
}

function recentSessionLabel(outputDir, deps = {}) {
  const fsImpl = deps.fs || fs;
  const classification = classifyOutputDir(outputDir, deps);
  if (classification.kind === "package_v1" && classification.displayName) {
    return classification.displayName;
  }
  // 优先用 manifest 里的源文档名作展示标签（"哪份标准的结果"一眼可辨）；
  // 无 manifest（如纯 B 轨目录）或损坏时退回目录名
  try {
    const manifest = JSON.parse(
      fsImpl.readFileSync(path.join(outputDir, "manifest.json"), "utf8"),
    );
    const input = String(manifest?.input || "").trim();
    if (input) return path.basename(input);
  } catch {
    /* fall through to directory name */
  }
  return path.basename(outputDir) || outputDir;
}

function listRecentSessions(filePath, deps = {}) {
  const fsImpl = deps.fs || fs;
  return loadRecentSessions(filePath, deps).map((entry) => ({
    ...entry,
    label: recentSessionLabel(entry.outputDir, deps),
    exists: fsImpl.existsSync(entry.outputDir),
    isOutput: isLikelyOutputDir(entry.outputDir, deps),
    classification: classifyOutputDir(entry.outputDir, deps),
  }));
}

function resolveAutoRestoreCandidates(filePath, deps = {}) {
  return listRecentSessions(filePath, deps)
    .filter((entry) => entry.exists && entry.isOutput)
    .map((entry) => entry.outputDir);
}

function resolveAutoRestoreDir(filePath, deps = {}) {
  return resolveAutoRestoreCandidates(filePath, deps)[0] || "";
}

module.exports = {
  DEFAULT_LLM_SETTINGS,
  acquireSingleInstanceLock,
  OUTPUT_DIR_MARKERS,
  PROGRESS_PREFIX,
  RECENT_SESSIONS_LIMIT,
  appendBackendLog,
  backendLogPath,
  bindAmbientLlmCredential,
  buildLlmEnvironment,
  buildChainArgs,
  buildExportAnnotationArgs,
  buildRunPipelineArgs,
  classifyOutputDir,
  drainProgressLines,
  isLikelyOutputDir,
  listRecentSessions,
  loadLlmSettingsConfig,
  loadRecentSessions,
  normalizeLlmEndpoint,
  normalizeLlmSettings,
  parseTaskErrorEnvelope,
  planResultPackageStart,
  recordRecentSession,
  recentSessionLabel,
  resolveAutoRestoreCandidates,
  resolveAutoRestoreDir,
  resolveLlmTestConnection,
  resolveBackendCommand,
  resolveBoundLlmApiKey,
  resolvePythonScriptPath,
  saveLlmSettingsConfig,
  SESSION_API_KEY_ENV,
  sameLlmCredentialScope,
  shouldReuseApiSession,
};
