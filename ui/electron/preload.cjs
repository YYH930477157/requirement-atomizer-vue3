const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("ratomizerDesktop", {
  openDocument: () => ipcRenderer.invoke("dialog:open-document"),
  selectOutputDir: () => ipcRenderer.invoke("dialog:select-output-dir"),
  openOutput: () => ipcRenderer.invoke("dialog:open-output"),
  openPath: (targetPath) => ipcRenderer.invoke("shell:open-path", targetPath),
  getApiSession: () => ipcRenderer.invoke("api:get-session"),
  startApiSession: (outDir) => ipcRenderer.invoke("api:start-session", outDir),
  getRecentSessions: () => ipcRenderer.invoke("session:get-recent"),
  onApiSessionReady: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("api:session-ready", listener);
    return () => ipcRenderer.removeListener("api:session-ready", listener);
  },
  getLlmSettings: () => ipcRenderer.invoke("llm:get-settings"),
  saveLlmSettings: (input) => ipcRenderer.invoke("llm:save-settings", input),
  testLlmConnection: (input) => ipcRenderer.invoke("llm:test-connection", input),
  onTaskProgress: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("task:progress", listener);
    return () => ipcRenderer.removeListener("task:progress", listener);
  },
  runPipeline: (input) => ipcRenderer.invoke("task:run-pipeline", input),
  startResultPackage: (input) => ipcRenderer.invoke("task:result-package-start", input),
  completeResultPackage: (input) => ipcRenderer.invoke("task:result-package-complete", input),
  failResultPackage: (input) => ipcRenderer.invoke("task:result-package-fail", input),
  getOutputSummary: (input) => ipcRenderer.invoke("task:summary", input),
  aiExtract: (input) => ipcRenderer.invoke("task:ai-extract", input),
  exportAnnotationHtml: (input) => ipcRenderer.invoke("task:export-annotation-html", input),
  importAiDecisions: (input) => ipcRenderer.invoke("task:import-ai-decisions", input),
  assembleSpec: (input) => ipcRenderer.invoke("task:assemble", input),
  composeEngineering: (input) => ipcRenderer.invoke("task:compose", input),
  runRequirementsAnalysis: (input) => ipcRenderer.invoke("task:requirements-analysis", input),
  writeTemplate: (input) => ipcRenderer.invoke("task:template-write", input),
  clarificationReport: (input) => ipcRenderer.invoke("task:clarification-report", input),
  runChain: (input) => ipcRenderer.invoke("task:chain", input),
  importClarificationAnswers: (input) => ipcRenderer.invoke("task:import-clarification-answers", input),
  selectTemplate: () => ipcRenderer.invoke("dialog:open-template"),
  openLogsDir: () => ipcRenderer.invoke("logs:open"),
});
