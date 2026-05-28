const { app, BrowserWindow } = require("electron");
const path = require("path");
const { spawn } = require("child_process");

let backend;

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 980,
    minHeight: 700,
    backgroundColor: "#eef4fb",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  const packagedWeb = path.join(__dirname, "web", "index.html");
  const devWeb = path.join(__dirname, "..", "web", "index.html");
  win.loadFile(app.isPackaged ? packagedWeb : devWeb);
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

app.whenReady().then(() => {
  startBackend();
  createWindow();
});

app.on("window-all-closed", () => {
  if (backend) backend.kill();
  if (process.platform !== "darwin") app.quit();
});
