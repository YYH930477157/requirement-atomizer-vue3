const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("ratomizerDesktop", {
  openDocument: () => ipcRenderer.invoke("dialog:open-document"),
  selectOutputDir: () => ipcRenderer.invoke("dialog:select-output-dir"),
  openOutput: () => ipcRenderer.invoke("dialog:open-output"),
  openPath: (targetPath) => ipcRenderer.invoke("shell:open-path", targetPath),
  getApiSession: () => ipcRenderer.invoke("api:get-session"),
  startApiSession: (outDir) => ipcRenderer.invoke("api:start-session", outDir),
  getLlmSettings: () => ipcRenderer.invoke("llm:get-settings"),
  saveLlmSettings: (input) => ipcRenderer.invoke("llm:save-settings", input),
  testLlmConnection: (input) => ipcRenderer.invoke("llm:test-connection", input),
  onTaskProgress: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("task:progress", listener);
    return () => ipcRenderer.removeListener("task:progress", listener);
  },
  runPipeline: (input) => ipcRenderer.invoke("task:run-pipeline", input),
  exportRequirements: (input) => ipcRenderer.invoke("task:export-requirements", input),
  assembleSpec: (input) => ipcRenderer.invoke("task:assemble-spec", input),
});
