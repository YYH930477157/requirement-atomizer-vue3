const { app, BrowserWindow, Menu, dialog, ipcMain, safeStorage, shell } = require("electron");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const {
  DEFAULT_LLM_SETTINGS,
  acquireSingleInstanceLock,
  appendBackendLog,
  bindAmbientLlmCredential,
  buildChainArgs,
  buildExportAnnotationArgs,
  buildLlmEnvironment,
  buildRunPipelineArgs,
  classifyOutputDir,
  drainProgressLines,
  listRecentSessions,
  loadLlmSettingsConfig,
  parseTaskErrorEnvelope,
  planResultPackageStart,
  probeApiSessionContent,
  readGovernedArtifact,
  recordRecentSession,
  resolveAutoRestoreCandidates,
  resolveBackendCommand,
  resolveBoundLlmApiKey,
  resolveLlmTestConnection,
  saveLlmSettingsConfig,
  shouldReuseApiSession,
} = require("./main.helpers.cjs");

let mainWindow = null;
let apiProcess = null;
let apiSession = null;
let llmSettings = null;
let sessionApiKey = "";
let startupAmbientCredential = null;
let applicationResourcesCleanedUp = false;
const API_STARTUP_ATTEMPTS = 3;
const API_STARTUP_TIMEOUT_MS = 30000;
const API_STARTUP_RETRY_DELAY_MS = 750;

function createWindow() {
  Menu.setApplicationMenu(null);
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 980,
    minWidth: 1280,
    minHeight: 820,
    title: "标准需求抽取与审查平台",
    backgroundColor: "#f6f8fb",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (!app.isPackaged) {
    mainWindow.loadURL("http://127.0.0.1:5173");
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }

  if (process.argv.includes("--smoke")) {
    setImmediate(() => app.quit());
  }

}

function focusMainWindow() {
  if (!mainWindow) {
    createWindow();
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.focus();
}

// S7：单实例——两个窗口各自起 API 进程会对同一输出目录互相抢写锁
//（extraction operation lease / recent-sessions read-modify-write 丢更新）。
// 锁拿不到时 acquireSingleInstanceLock 内部已 app.quit()，此分支直接不再注册启动。
if (acquireSingleInstanceLock(app, focusMainWindow)) {
  app.whenReady().then(createWindow);

  app.whenReady().then(() => {
    llmSettings = loadLlmSettings();
  });

  // 开发/演示入口：`npx electron . --out-dir <path>` 启动后直接连接该输出目录
  app.whenReady().then(() => {
    const flagIndex = process.argv.indexOf("--out-dir");
    const outDir = flagIndex >= 0 ? process.argv[flagIndex + 1] : "";
    if (outDir) {
      void startApiServer(outDir, { notifyRenderer: true }).catch(() => undefined);
      return;
    }
    // 自动恢复上次结果：重启后不必重跑管线，也不必手动找目录。
    // 无历史 / 目录已删除 / 目录不是输出产物时静默跳过，停在首页（最近结果列表仍可手动打开）。
    void autoRestoreRecentSession(resolveAutoRestoreCandidates(recentSessionsPath()));
  });

  app.on("window-all-closed", () => {
    stopApiServer();
    if (process.platform !== "darwin") {
      app.quit();
    }
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });

  app.on("before-quit", cleanupApplicationResources);
  app.on("will-quit", cleanupApplicationResources);
}

ipcMain.handle("dialog:open-document", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [{ name: "Documents", extensions: ["docx", "xlsx", "pdf"] }],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("dialog:open-output", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory"],
  });
  if (result.canceled) {
    return null;
  }
  const outputDir = result.filePaths[0];
  const classification = classifyOutputDir(outputDir);
  if (!["package_v1", "legacy"].includes(classification.kind)) {
    const reason = classification.kind === "invalid"
      ? "结果目录标志已损坏或版本不受支持"
      : "所选文件夹不是需求分析结果目录";
    throw new Error(reason);
  }
  if (classification.kind === "package_v1") {
    // S5：打开已有结果时显式完整校验（重算交付物/完成证据 SHA）——哈希权威实现
    // 单源在 Python 侧，JS 不重新实现，避免契约漂移（2026-08-03 清单 S16 同口径）
    try {
      await runDesktopTaskProcess(["result-package-status", "--out", outputDir, "--verify"]);
    } catch (error) {
      const envelope = parseTaskErrorEnvelope(error);
      if (envelope?.error?.type === "result_package_modified") {
        throw new Error(String(envelope.error.message || "结果文件已被修改"));
      }
      throw error;
    }
  }
  return startApiServer(outputDir);
});

ipcMain.handle("dialog:select-output-dir", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory", "createDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("shell:open-path", async (_event, targetPath) => {
  if (!targetPath || !apiSession || !isInside(apiSession.outputDir, targetPath)) {
    return;
  }
  await shell.openPath(targetPath);
});

// S16：默认输出根目录跟随系统"文档"目录派生，绝不硬编码开发者机器路径
ipcMain.handle("app:get-default-output-root", async () => {
  try {
    return path.join(app.getPath("documents"), "requirement-atomizer-runs");
  } catch {
    return path.join(app.getPath("userData"), "requirement-atomizer-runs");
  }
});
ipcMain.handle("api:get-session", async () => apiSession);
ipcMain.handle("api:start-session", async (_event, outDir) => startApiServer(outDir));
ipcMain.handle("session:get-recent", async () => listRecentSessions(recentSessionsPath()));
ipcMain.handle("llm:get-settings", async () => loadLlmSettings());
ipcMain.handle("llm:save-settings", async (_event, input) => saveLlmSettings(input));
ipcMain.handle("llm:test-connection", async (_event, input) => testLlmConnection(input));
ipcMain.handle("task:result-package-start", async (_event, input) => {
  // I5：legacy 扁平目录按旧管线运行，不创建 marker/.ratomizer——
  // Python initialize_result_package 保持 fail-closed，由 Electron 先行分类分流
  const legacyPlan = planResultPackageStart(input.outDir);
  if (legacyPlan) {
    return legacyPlan;
  }
  return runDesktopTaskProcess([
    "result-package-start",
    "--out", input.outDir,
    "--input", input.inputPath,
    "--stages", (input.stages || []).join(","),
  ]);
});
ipcMain.handle("task:result-package-complete", async (_event, input) => {
  try {
    const payload = await runAndRememberOutput([
      "result-package-complete",
      "--out", input.outDir,
      "--run-id", input.runId,
      "--completed-stages", (input.completedStages || []).join(","),
    ], input.outDir);
    await startApiServer(input.outDir, { forceRestart: true });
    return payload;
  } catch (error) {
    // I6：部分阶段降级不是运行失败——透传稳定错误码，渲染层显示
    // "分析未完成（部分阶段降级）"；其余错误维持 reject
    const envelope = parseTaskErrorEnvelope(error);
    if (envelope?.error?.type === "requested_stage_partial") {
      await startApiServer(input.outDir, { forceRestart: true });
      return {
        kind: "result_package_complete",
        ok: false,
        code: "requested_stage_partial",
        message: String(envelope.error.message || "requested stage partial"),
        out_dir: input.outDir,
      };
    }
    throw error;
  }
});
ipcMain.handle("task:result-package-fail", async (_event, input) => runDesktopTaskProcess([
  "result-package-fail",
  "--out", input.outDir,
  "--run-id", input.runId,
  "--error", String(input.error || "analysis failed"),
]));
ipcMain.handle("task:run-pipeline", async (_event, input) => {
  const payload = await runDesktopTaskProcess(buildRunPipelineArgs(input));
  const outDir = String(payload.out_dir || input.outDir);
  // 结果已经生成就先登记，API 启动失败也不能让重启后的历史入口丢失。
  rememberRecentSession(outDir);
  try {
    await startApiServer(outDir, { forceRestart: true });
  } catch (error) {
    const message = `本地 API 连接失败，输出目录成果已保留，可稍后重新连接输出目录：${error.message}`;
    appendBackendLog(logsDirPath(), "api", message);
    payload.api_warning = message;
  }
  return payload;
});
ipcMain.handle("task:ai-extract", async (_event, input) => runAndRememberOutput([
  "ai-extract",
  "--out",
  input.outDir,
  ...(input.llmRoute ? ["--llm-route", input.llmRoute] : []),
  ...(input.limitSections ? ["--limit-sections", String(input.limitSections)] : []),
  ...(input.sampleRatio ? ["--sample-ratio", String(input.sampleRatio)] : []),
], input.outDir));

ipcMain.handle("logs:open", async () => {
  const dir = logsDirPath();
  fs.mkdirSync(dir, { recursive: true });
  await shell.openPath(dir);
  return { dir };
});

ipcMain.handle("task:assemble", async (_event, input) => runAndRememberOutput([
  "assemble",
  "--out",
  input.outDir,
  ...(input.enrichRoute ? ["--enrich-route", input.enrichRoute] : []),
], input.outDir));

ipcMain.handle("task:compose", async (_event, input) =>
  runAndRememberOutput(["compose", "--out", input.outDir], input.outDir));

ipcMain.handle("task:requirements-analysis", async (_event, input) => runAndRememberOutput([
  "requirements-analysis",
  "--out",
  input.outDir,
  ...(input.llmRoute ? ["--llm-route", input.llmRoute] : []),
  ...(input.templatePath ? ["--template", input.templatePath] : []),
], input.outDir));

// 交付物链单命令编排（编排在后端，UI 只发一条命令 + 渲染进度）
ipcMain.handle("task:chain", async (_event, input) =>
  runAndRememberOutput(buildChainArgs(input), input.outDir));

// 澄清清单：全链疑问信号聚合 + 就绪判定（确定性零 LLM）
ipcMain.handle("task:clarification-report", async (_event, input) =>
  runAndRememberOutput(["clarification-report", "--out", input.outDir], input.outDir));

// 成文：analyze 结果按公司标准化需求列表格式追加进对应模块 sheet（确定性零 LLM）
ipcMain.handle("task:template-write", async (_event, input) => runAndRememberOutput([
  "template-write",
  "--out",
  input.outDir,
  "--template",
  input.templatePath,
], input.outDir));

ipcMain.handle("dialog:open-template", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [{ name: "需求列表模板", extensions: ["xlsx"] }],
  });
  return result.canceled ? "" : result.filePaths[0];
});

ipcMain.handle("task:export-annotation-html", async (_event, input) =>
  runAndRememberOutput(buildExportAnnotationArgs(input), input.outDir));

ipcMain.handle("task:summary", async (_event, input) =>
  runDesktopTaskProcess(["summary", "--out", input.outDir]));

ipcMain.handle("task:import-ai-decisions", async (_event, input) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [{ name: "AI 裁决 JSON", extensions: ["json"] }],
  });
  if (result.canceled || !result.filePaths.length) {
    return { kind: "ai_decisions_import", applied: 0, skipped: 0, canceled: true };
  }
  return runAndRememberOutput(["import-ai-decisions", "--out", input.outDir, "--file", result.filePaths[0]], input.outDir);
});

// 澄清处置回灌：同一工作簿同时导入客户答复与内部核对动作。
ipcMain.handle("task:import-clarification-answers", async (_event, input) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [{ name: "澄清清单(已填写)", extensions: ["xlsx"] }],
  });
  if (result.canceled || !result.filePaths.length) {
    return { kind: "clarification_answers", imported: 0, canceled: true };
  }
  return runAndRememberOutput(["import-clarification-answers", "--out", input.outDir, "--file", result.filePaths[0]], input.outDir);
});

// WS-F：governed 产物读取（无 HTTP 读取端点的文件：functional_requirements.json /
// manual_requirements.jsonl / requirement_lifecycle_events.jsonl）。主进程读盘回灌渲染进程，
// 只读、不创建目录、不写盘——后端 result_package.governed_artifact_path 是路径权威。
ipcMain.handle("task:read-artifact", async (_event, input) => {
  try {
    return readGovernedArtifact(input && input.outDir, input && input.category, input && input.filename);
  } catch (err) {
    return {
      ok: false, missing: true, path: null, reason: "handler_error",
      detail: String((err && err.message) || err),
    };
  }
});

// 会话启动串行化：所有 startApiServer 调用（自动恢复 / 用户选目录 / 管线完成回连 /
// 保存 LLM 设置重连）排入同一条 promise 链。否则自动恢复的重试回路可能在用户已另选
// 目录后仍在跑，启动完成后的接管步骤会反杀用户的新会话。
let sessionStartQueue = Promise.resolve();

function startApiServer(outputDir, options = {}) {
  const run = sessionStartQueue.then(() => startApiServerExclusive(outputDir, options));
  // 链本身永不 reject（失败只影响本次调用方，后续排队照常进行）
  sessionStartQueue = run.catch(() => undefined);
  return run;
}

async function startApiServerExclusive(outputDir, options = {}) {
  if (shouldReuseApiSession(apiSession, apiProcess, outputDir, options)) {
    try {
      await probeApiSessionContent(apiSession);
      rememberRecentSession(outputDir);
      notifyApiSessionReady(apiSession, options);
      return apiSession;
    } catch (error) {
      appendBackendLog(logsDirPath(), "api", `existing session probe failed; restarting: ${error.message}`);
    }
  }
  let lastError = null;
  for (let attempt = 1; attempt <= API_STARTUP_ATTEMPTS; attempt += 1) {
    let candidate = null;
    try {
      candidate = await spawnApiServer(outputDir);
      const session = await waitForApiReady(
        candidate.child, candidate.port, candidate.token, outputDir, API_STARTUP_TIMEOUT_MS,
      );
      // S8：新 API 成功就绪后才接管——启动失败时旧会话进程与状态原样保留，
      // 渲染层不会因为一次失败的"打开已有结果"丢掉当前审查会话
      // R3：就绪 ≠ 能读内容（损坏产物会让 /requirements 直接断连）——
      // 接管前实际探测关键端点，探测失败走 catch 只杀候选进程，旧会话保留
      await probeApiSessionContent(session);
      stopApiServer();
      apiProcess = candidate.child;
      apiSession = session;
      candidate = null;
      rememberRecentSession(outputDir);
      notifyApiSessionReady(session, options);
      return session;
    } catch (error) {
      lastError = error;
      if (candidate?.child) {
        candidate.child.kill();
      }
      appendBackendLog(logsDirPath(), "api",
        `startup attempt ${attempt}/${API_STARTUP_ATTEMPTS} failed: ${error.message}`);
      if (attempt < API_STARTUP_ATTEMPTS) {
        await delay(API_STARTUP_RETRY_DELAY_MS * attempt);
      }
    }
  }
  throw new Error(`API server startup failed after ${API_STARTUP_ATTEMPTS} attempts: ${lastError?.message || "unknown error"}`);
}

async function autoRestoreRecentSession(candidates) {
  let lastError = null;
  for (const outputDir of candidates || []) {
    try {
      await startApiServer(outputDir, { notifyRenderer: true });
      return;
    } catch (error) {
      lastError = error;
      appendBackendLog(logsDirPath(), "api", `auto-restore candidate skipped (${outputDir}): ${error.message}`);
    }
  }
  if (lastError) {
    appendBackendLog(logsDirPath(), "api", `auto-restore skipped: ${lastError.message}`);
  }
}

function notifyApiSessionReady(session, options = {}) {
  if (!options.notifyRenderer || !session) return;
  mainWindow?.webContents.send("api:session-ready", session);
}

async function runAndRememberOutput(args, fallbackOutDir) {
  const payload = await runDesktopTaskProcess(args);
  const outputDir = String(payload?.out_dir || payload?.outDir || fallbackOutDir || "");
  rememberRecentSession(outputDir);
  return payload;
}

function rememberRecentSession(outputDir) {
  try {
    recordRecentSession(recentSessionsPath(), outputDir);
  } catch (error) {
    // 历史登记失败绝不阻断会话本身
    appendBackendLog(logsDirPath(), "api", `recent-session record failed: ${error.message}`);
  }
}

function recentSessionsPath() {
  return path.join(app.getPath("userData"), "recent-sessions.json");
}

// 只 spawn 候选进程并等待就绪，绝不触碰 apiProcess/apiSession——
// 是否接管由调用方在就绪成功后决定（S8 swap-after-ready）
async function spawnApiServer(outputDir) {
  const token = crypto.randomBytes(24).toString("hex");
  const port = await findFreePort();
  const backend = resolveBackendCommand("api_server.py", { dirname: __dirname, resourcesPath: process.resourcesPath, existsSync: fs.existsSync });
  const child = spawn(backend.command, [
    ...backend.args,
    ...(backend.packaged ? ["--serve-api"] : []),
    "--out",
    outputDir,
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
    "--allow-origin",
    "http://127.0.0.1:5173",
    "--allow-origin",
    "file://",
    "--token",
    token,
  ], {
    cwd: backend.cwd,
    env: buildCurrentLlmEnvironment(),
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });

  return { child, port, token };
}

function stopApiServer() {
  if (apiProcess) {
    apiProcess.kill();
    apiProcess = null;
  }
  apiSession = null;
}

function cleanupApplicationResources() {
  if (applicationResourcesCleanedUp) return;
  applicationResourcesCleanedUp = true;
  stopApiServer();
}

function waitForApiReady(child, port, token, outputDir, timeoutMs = API_STARTUP_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback(value);
    };
    const timer = setTimeout(() => finish(reject, new Error(`API server startup timed out after ${timeoutMs}ms: ${stderr}`)), timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
      const parsed = drainProgressLines(stdout);
      stdout = `${parsed.output}${parsed.remaining}`;
      for (const event of parsed.events) {
        mainWindow?.webContents.send("task:progress", event);
      }
      const jsonStart = stdout.indexOf("{");
      const jsonEnd = stdout.lastIndexOf("}");
      if (jsonStart >= 0 && jsonEnd > jsonStart) {
        try {
          JSON.parse(stdout.slice(jsonStart, jsonEnd + 1));
          finish(resolve, { baseUrl: `http://127.0.0.1:${port}`, token, outputDir });
        } catch {
          // Keep waiting until the startup JSON is complete.
        }
      }
    });
    child.stderr.on("data", (chunk) => {
      const text = chunk.toString("utf8");
      stderr += text;
      appendBackendLog(logsDirPath(), "api", text);
    });
    child.once("error", (error) => {
      finish(reject, error);
    });
    child.once("exit", (code) => {
      finish(reject, new Error(`API server exited with code ${code}: ${stderr}`));
    });
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function findFreePort() {
  const net = require("node:net");
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
    server.on("error", reject);
  });
}

function runDesktopTaskProcess(args) {
  const backend = resolveBackendCommand("desktop_tasks.py", { dirname: __dirname, resourcesPath: process.resourcesPath, existsSync: fs.existsSync });
  return new Promise((resolve, reject) => {
    const child = spawn(backend.command, [...backend.args, ...args], {
      cwd: backend.cwd,
      env: buildCurrentLlmEnvironment(),
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stdoutTail = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      const parsed = drainProgressLines(stdoutTail + chunk.toString("utf8"));
      stdout += parsed.output;
      stdoutTail = parsed.remaining;
      for (const event of parsed.events) {
        mainWindow?.webContents.send("task:progress", event);
      }
    });
    child.stderr.on("data", (chunk) => {
      const text = chunk.toString("utf8");
      stderr += text;
      appendBackendLog(logsDirPath(), "task", text);
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || `desktop task exited with code ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(`${stdout}${stdoutTail}`.trim()));
      } catch (error) {
        reject(new Error(`desktop task returned invalid JSON: ${error.message}`));
      }
    });
  });
}

function loadLlmSettings() {
  if (llmSettings) {
    return llmSettings;
  }
  const loaded = loadLlmSettingsConfig(llmSettingsPath(), safeStorage);
  llmSettings = loaded.settings;
  sessionApiKey = loaded.apiKey;
  startupAmbientCredential = bindAmbientLlmCredential(llmSettings, process.env);
  return llmSettings;
}

function saveLlmSettings(input) {
  const previousSettings = loadLlmSettings();
  const saved = saveLlmSettingsConfig(
    llmSettingsPath(), input, safeStorage, sessionApiKey, previousSettings,
  );
  llmSettings = saved.settings;
  sessionApiKey = saved.apiKey;
  if (apiSession?.outputDir) {
    void startApiServer(apiSession.outputDir).catch(() => undefined);
  }
  return llmSettings;
}

async function testLlmConnection(input) {
  const savedSettings = loadLlmSettings();
  const { settings, apiKey } = resolveLlmTestConnection(
    input,
    savedSettings,
    resolveBoundLlmApiKey(savedSettings, sessionApiKey, startupAmbientCredential),
  );
  const body = JSON.stringify({
    model: settings.model,
    messages: [{ role: "user", content: "ping" }],
    max_tokens: 1,
    temperature: 0,
  });
  const headers = { "Content-Type": "application/json", Accept: "application/json" };
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }
  const response = await fetch(`${settings.baseUrl.replace(/\/+$/, "")}/chat/completions`, {
    method: "POST",
    headers,
    body,
    signal: AbortSignal.timeout(Math.max(1000, settings.timeoutS * 1000)),
  });
  const text = await response.text();
  if (!response.ok) {
    return { ok: false, message: `调用失败：HTTP ${response.status} ${text.slice(0, 180)}` };
  }
  try {
    const payload = JSON.parse(text);
    payload.choices[0].message.content;
  } catch (error) {
    return { ok: false, message: `已连接，但返回不是标准 OpenAI Chat 响应：${error.message}` };
  }
  return { ok: true, message: `调用成功：模型 ${settings.model} 可用` };
}

function buildCurrentLlmEnvironment() {
  const settings = loadLlmSettings();
  const apiKey = resolveBoundLlmApiKey(settings, sessionApiKey, startupAmbientCredential);
  return buildLlmEnvironment({ ...settings, apiKey }, process.env);
}

function logsDirPath() {
  return path.join(app.getPath("userData"), "logs");
}

function llmSettingsPath() {
  return path.join(app.getPath("userData"), "llm-settings.json");
}

function isInside(rootPath, targetPath) {
  const root = path.resolve(rootPath);
  const target = path.resolve(targetPath);
  const relative = path.relative(root, target);
  return relative === "" || Boolean(relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}
