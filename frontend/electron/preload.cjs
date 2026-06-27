const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // Dialog APIs
  selectFolder: () => ipcRenderer.invoke('dialog:selectFolder'),
  selectFile: () => ipcRenderer.invoke('dialog:selectFile'),
  
  // File System APIs
  readFile: (filePath) => ipcRenderer.invoke('fs:readFile', filePath),
  writeFile: (filePath, content) => ipcRenderer.invoke('fs:writeFile', filePath, content),
  readDir: (dirPath) => ipcRenderer.invoke('fs:readDir', dirPath),
  createDir: (dirPath) => ipcRenderer.invoke('fs:createDir', dirPath),
  deleteFile: (filePath) => ipcRenderer.invoke('fs:deleteFile', filePath),
  
  // App APIs
  isElectron: () => ipcRenderer.invoke('app:isElectron'),
  getVersion: () => ipcRenderer.invoke('app:getVersion')
});
