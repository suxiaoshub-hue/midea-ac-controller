const { app, BrowserWindow, Menu, Tray, nativeImage } = require("electron");
const http = require("http");
const path = require("path");
const { spawn } = require("child_process");

let mainWindow;
let backend;
let tray;
let isQuitting = false;
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.exit(0);
}

function createTrayIcon() {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
      <rect width="32" height="32" rx="8" fill="#1f7af5"/>
      <path d="M9 12h14a3 3 0 0 1 3 3v3a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3v-3a3 3 0 0 1 3-3Z" fill="#fff"/>
      <path d="M11 20v3M16 20v3M21 20v3" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
      <circle cx="23" cy="16" r="1.5" fill="#1f7af5"/>
    </svg>
  `;
  return nativeImage.createFromDataURL(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 980,
    minHeight: 700,
    icon: path.join(__dirname, "build", "icon.ico"),
    backgroundColor: "#eef4fb",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  const packagedWeb = path.join(__dirname, "web", "index.html");
  const devWeb = path.join(__dirname, "..", "web", "index.html");
  mainWindow.loadFile(app.isPackaged ? packagedWeb : devWeb);
  mainWindow.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    mainWindow.minimize();
  });
}

function showMainWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function createTray() {
  tray = new Tray(createTrayIcon());
  tray.setToolTip("美的美居多设备控制端");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "打开主界面", click: showMainWindow },
    { type: "separator" },
    {
      label: "退出软件",
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]));
  tray.on("click", showMainWindow);
}

function isBackendRunning() {
  return new Promise((resolve) => {
    const req = http.get("http://127.0.0.1:18765/api/health", (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.setTimeout(800, () => {
      req.destroy();
      resolve(false);
    });
    req.on("error", () => resolve(false));
  });
}

function startBackend() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, "backend", "midea_backend.exe");
    backend = spawn(exe, [], { stdio: "ignore", windowsHide: true });
    return;
  }
  const projectRoot = path.resolve(__dirname, "..", "..");
  const python = process.platform === "win32" ? "python" : "python3";
  backend = spawn(python, ["-m", "midea_ac_controller.server"], {
    cwd: projectRoot,
    stdio: "inherit",
  });
}

app.whenReady().then(async () => {
  if (!gotTheLock) return;
  if (!(await isBackendRunning())) {
    startBackend();
  }
  createWindow();
  createTray();
});

app.on("second-instance", () => {
  if (mainWindow) {
    showMainWindow();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
});

app.on("will-quit", () => {
  if (backend) backend.kill();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
