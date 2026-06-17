const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("ratomizerDesktop", {
  openDocument: () => ipcRenderer.invoke("dialog:open-document"),
  openOutput: () => ipcRenderer.invoke("dialog:open-output"),
  openPath: (targetPath) => ipcRenderer.invoke("shell:open-path", targetPath),
});
