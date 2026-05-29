const { app, BrowserWindow, Menu, Tray, nativeImage } = require("electron");
const http = require("http");
const net = require("net");
const path = require("path");
const { spawn } = require("child_process");

const APP_TITLE = "白熊TT自用空调控制系统";
let mainWindow;
let backend;
let tray;
let isQuitting = false;
let backendPort = 18765;
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.exit(0);
}

function createTrayIcon() {
  const iconPath = path.join(__dirname, "build", "icon.png");
  const image = nativeImage.createFromPath(iconPath);
  return image.isEmpty() ? nativeImage.createFromPath(path.join(__dirname, "build", "icon.ico")) : image.resize({ width: 20, height: 20 });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 980,
    minHeight: 700,
    title: APP_TITLE,
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
  mainWindow.loadFile(app.isPackaged ? packagedWeb : devWeb, {
    query: { apiPort: String(backendPort) },
  });
  mainWindow.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    mainWindow.hide();
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
  tray.setToolTip(APP_TITLE);
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

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 18765;
      server.close(() => resolve(port));
    });
  });
}

function waitForBackend(port) {
  return new Promise((resolve) => {
    const deadline = Date.now() + 12000;
    const check = () => {
      const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) {
          resolve(true);
        } else if (Date.now() > deadline) {
          resolve(false);
        } else {
          setTimeout(check, 300);
        }
      });
      req.setTimeout(800, () => {
        req.destroy();
        if (Date.now() > deadline) resolve(false);
        else setTimeout(check, 300);
      });
      req.on("error", () => {
        if (Date.now() > deadline) resolve(false);
        else setTimeout(check, 300);
      });
    };
    check();
  });
}

function startBackend(port) {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, "backend", "midea_backend.exe");
    backend = spawn(exe, ["--port", String(port)], { stdio: "ignore", windowsHide: true });
    return;
  }
  const projectRoot = path.resolve(__dirname, "..", "..");
  const python = process.platform === "win32" ? "python" : "python3";
  backend = spawn(python, ["-m", "midea_ac_controller.server", "--port", String(port)], {
    cwd: projectRoot,
    stdio: "inherit",
  });
}

app.whenReady().then(async () => {
  if (!gotTheLock) return;
  backendPort = await getFreePort();
  startBackend(backendPort);
  await waitForBackend(backendPort);
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
