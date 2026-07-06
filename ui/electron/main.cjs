const { app, BrowserWindow, Menu, dialog, ipcMain, safeStorage, shell } = require("electron");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const {
  DEFAULT_LLM_SETTINGS,
  appendBackendLog,
  buildLlmEnvironment,
  buildRunPipelineArgs,
  drainProgressLines,
  loadLlmSettingsConfig,
  normalizeLlmSettings,
  resolveBackendCommand,
  saveLlmSettingsConfig,
} = require("./main.helpers.cjs");

let mainWindow = null;
let apiProcess = null;
let apiSession = null;
let llmSettings = null;
let sessionApiKey = "";

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

app.whenReady().then(createWindow);

app.whenReady().then(() => {
  llmSettings = loadLlmSettings();
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
  return startApiServer(result.filePaths[0]);
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

ipcMain.handle("api:get-session", async () => apiSession);
ipcMain.handle("api:start-session", async (_event, outDir) => startApiServer(outDir));
ipcMain.handle("llm:get-settings", async () => loadLlmSettings());
ipcMain.handle("llm:save-settings", async (_event, input) => saveLlmSettings(input));
ipcMain.handle("llm:test-connection", async (_event, input) => testLlmConnection(input));
ipcMain.handle("task:run-pipeline", async (_event, input) => {
  const payload = await runDesktopTaskProcess(buildRunPipelineArgs(input));
  await startApiServer(String(payload.out_dir || input.outDir));
  return payload;
});
ipcMain.handle("task:ai-extract", async (_event, input) => runDesktopTaskProcess([
  "ai-extract",
  "--out",
  input.outDir,
  ...(input.llmRoute ? ["--llm-route", input.llmRoute] : []),
  ...(input.limitSections ? ["--limit-sections", String(input.limitSections)] : []),
  ...(input.sampleRatio ? ["--sample-ratio", String(input.sampleRatio)] : []),
]));

ipcMain.handle("logs:open", async () => {
  const dir = logsDirPath();
  fs.mkdirSync(dir, { recursive: true });
  await shell.openPath(dir);
  return { dir };
});

ipcMain.handle("task:assemble", async (_event, input) => runDesktopTaskProcess([
  "assemble",
  "--out",
  input.outDir,
  ...(input.enrichRoute ? ["--enrich-route", input.enrichRoute] : []),
]));

ipcMain.handle("task:compose", async (_event, input) =>
  runDesktopTaskProcess(["compose", "--out", input.outDir]));

ipcMain.handle("task:requirements-analysis", async (_event, input) => runDesktopTaskProcess([
  "requirements-analysis",
  "--out",
  input.outDir,
  ...(input.llmRoute ? ["--llm-route", input.llmRoute] : []),
  ...(input.templatePath ? ["--template", input.templatePath] : []),
]));

// 交付物链单命令编排（编排在后端，UI 只发一条命令 + 渲染进度）
ipcMain.handle("task:chain", async (_event, input) => runDesktopTaskProcess([
  "chain",
  "--out",
  input.outDir,
  "--stages",
  (input.stages || []).join(","),
  ...(input.llmRoute ? ["--llm-route", input.llmRoute] : []),
  ...(input.templatePath ? ["--template", input.templatePath] : []),
  ...(input.sampleRatio ? ["--sample-ratio", String(input.sampleRatio)] : []),
]));

// 澄清清单：全链疑问信号聚合 + 就绪判定（确定性零 LLM）
ipcMain.handle("task:clarification-report", async (_event, input) =>
  runDesktopTaskProcess(["clarification-report", "--out", input.outDir]));

// 成文：analyze 结果按公司标准化需求列表格式追加进对应模块 sheet（确定性零 LLM）
ipcMain.handle("task:template-write", async (_event, input) => runDesktopTaskProcess([
  "template-write",
  "--out",
  input.outDir,
  "--template",
  input.templatePath,
]));

ipcMain.handle("dialog:open-template", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [{ name: "需求列表模板", extensions: ["xlsx"] }],
  });
  return result.canceled ? "" : result.filePaths[0];
});

ipcMain.handle("task:export-annotation-html", async (_event, input) =>
  runDesktopTaskProcess(["export-annotation-html", "--out", input.outDir]));

ipcMain.handle("task:import-ai-decisions", async (_event, input) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [{ name: "AI 裁决 JSON", extensions: ["json"] }],
  });
  if (result.canceled || !result.filePaths.length) {
    return { kind: "ai_decisions_import", applied: 0, skipped: 0, canceled: true };
  }
  return runDesktopTaskProcess(["import-ai-decisions", "--out", input.outDir, "--file", result.filePaths[0]]);
});

// 澄清答复回灌：评审会填好的 clarification_questions.xlsx 导回（闭环另一半）
ipcMain.handle("task:import-clarification-answers", async (_event, input) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [{ name: "澄清清单(已填答复)", extensions: ["xlsx"] }],
  });
  if (result.canceled || !result.filePaths.length) {
    return { kind: "clarification_answers", imported: 0, canceled: true };
  }
  return runDesktopTaskProcess(["import-clarification-answers", "--out", input.outDir, "--file", result.filePaths[0]]);
});

async function startApiServer(outputDir) {
  stopApiServer();
  const token = crypto.randomBytes(24).toString("hex");
  const port = await findFreePort();
  const backend = resolveBackendCommand("api_server.py", { dirname: __dirname, resourcesPath: process.resourcesPath, existsSync: fs.existsSync });
  apiProcess = spawn(backend.command, [
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

  apiSession = await waitForApiReady(apiProcess, port, token, outputDir);
  return apiSession;
}

function stopApiServer() {
  if (apiProcess) {
    apiProcess.kill();
    apiProcess = null;
  }
  apiSession = null;
}

function waitForApiReady(child, port, token, outputDir) {
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
    const timer = setTimeout(() => finish(reject, new Error(`API server startup timed out: ${stderr}`)), 10000);

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
  if (sessionApiKey) {
    process.env[llmSettings.apiKeyEnv] = sessionApiKey;
  }
  return llmSettings;
}

function saveLlmSettings(input) {
  const saved = saveLlmSettingsConfig(llmSettingsPath(), input, safeStorage, sessionApiKey);
  llmSettings = saved.settings;
  sessionApiKey = saved.apiKey;
  if (sessionApiKey) {
    process.env[llmSettings.apiKeyEnv] = sessionApiKey;
  }
  if (apiSession?.outputDir) {
    void startApiServer(apiSession.outputDir).catch(() => undefined);
  }
  return llmSettings;
}

async function testLlmConnection(input) {
  const settings = normalizeLlmSettings(input || loadLlmSettings());
  const apiKey = typeof input?.apiKey === "string" && input.apiKey.trim() ? input.apiKey.trim() : sessionApiKey;
  const env = buildLlmEnvironment({ ...settings, apiKey }, process.env);
  const body = JSON.stringify({
    model: settings.model,
    messages: [{ role: "user", content: "ping" }],
    max_tokens: 1,
    temperature: 0,
  });
  const headers = { "Content-Type": "application/json", Accept: "application/json" };
  const key = env[settings.apiKeyEnv] || "";
  if (key) {
    headers.Authorization = `Bearer ${key}`;
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
  return buildLlmEnvironment({ ...loadLlmSettings(), apiKey: sessionApiKey }, process.env);
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
