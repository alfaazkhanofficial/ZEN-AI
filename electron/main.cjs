const { app, BrowserWindow, ipcMain, nativeTheme, shell, Menu } = require('electron');
const path = require('path');
const net = require('net');
const http = require('http');
const { spawn } = require('child_process');

const DEV = !!process.env.ZEN_DEV;
let backend = null, port = 0, win = null;

const freePort = () => new Promise((res, rej) => {
  const s = net.createServer();
  s.on('error', rej);
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
});

function startBackend() {
  const data = app.getPath('userData');
  let cmd, args;
  if (app.isPackaged) {
    cmd = path.join(process.resourcesPath, 'backend', process.platform === 'win32' ? 'zen-backend.exe' : 'zen-backend');
    args = ['--port', String(port), '--data-dir', data];
  } else {
    cmd = process.env.ZEN_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    args = [path.join(__dirname, '..', 'backend', 'server.py'), '--port', String(port), '--data-dir', data];
  }
  backend = spawn(cmd, args, { windowsHide: true, stdio: 'ignore' });
  backend.on('error', (e) => console.error('backend failed to start:', e.message));
}

const waitHealth = (tries = 120) => new Promise((resolve, reject) => {
  const tick = (n) => {
    http.get({ host: '127.0.0.1', port, path: '/api/health', timeout: 800 }, (r) => { r.resume(); r.statusCode === 200 ? resolve() : retry(n); })
      .on('error', () => retry(n)).on('timeout', function () { this.destroy(); });
  };
  const retry = (n) => (n <= 0 ? reject(new Error('Backend did not start')) : setTimeout(() => tick(n - 1), 250));
  tick(tries);
});

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 820, minWidth: 820, minHeight: 560, show: false, autoHideMenuBar: true,
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#212121' : '#ffffff',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false },
  });
  win.once('ready-to-show', () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith('http://localhost:5173') && !url.startsWith('file://')) { e.preventDefault(); shell.openExternal(url); } });
  if (DEV) win.loadURL('http://localhost:5173');
  else win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  ipcMain.on('zen:api-base', (e) => { e.returnValue = `http://127.0.0.1:${port}`; });
  ipcMain.on('zen:set-theme', (_e, t) => { if (['light', 'dark', 'system'].includes(t)) nativeTheme.themeSource = t; });
  ipcMain.handle('zen:open-external', (_e, u) => { if (/^https?:\/\//.test(u)) return shell.openExternal(u); });
  ipcMain.handle('zen:open-path', (_e, p) => { if (typeof p === 'string' && p.startsWith(app.getPath('userData'))) return shell.openPath(p); });
  app.whenReady().then(async () => {
    if (process.platform !== 'darwin') Menu.setApplicationMenu(null);
    port = await freePort();
    startBackend();
    try { await waitHealth(); } catch (e) { console.error(e.message); }
    createWindow();
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', () => { if (backend) backend.kill(); });
}
