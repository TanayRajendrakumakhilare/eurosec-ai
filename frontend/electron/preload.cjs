const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("eurosec", {
  selectFolder: () => ipcRenderer.invoke("select-folder"),
  selectFile: () => ipcRenderer.invoke("select-file"),
});
