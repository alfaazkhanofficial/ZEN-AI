const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('zen', {
  apiBase: ipcRenderer.sendSync('zen:api-base'),
  setTheme: (t) => ipcRenderer.send('zen:set-theme', t),
  openExternal: (u) => ipcRenderer.invoke('zen:open-external', u),
  openPath: (p) => ipcRenderer.invoke('zen:open-path', p),
});
