/* frontend/electron/main.cjs */

const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");

// ----------------------------
// Mode detection
// - app.isPackaged is false when running locally
// - so we add EUROSEC_FORCE_DIST=1 for "prod-like" local run
// ----------------------------
const forceDist = process.env.EUROSEC_FORCE_DIST === "1";
const isDev = !app.isPackaged && !forceDist;

// Frontend dev URL (Vite)
const devUrl = process.env.EUROSEC_DEV_URL || "http://127.0.0.1:5173";

// Backend config
const backendHost = process.env.EUROSEC_BACKEND_HOST || "127.0.0.1";
const backendPort = Number(process.env.EUROSEC_BACKEND_PORT || 48155);
const backendHealthUrl = `http://${backendHost}:${backendPort}/health`;

let mainWindow = null;
let backendProc = null;

function exists(p) {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

// ----------------------------
// NEW: Resolve packaged backend binary (PyInstaller output)
// This is what you ship inside Electron via electron-builder extraResources.
// Path inside packaged app:
//   process.resourcesPath/backend/eurosec_backend(.exe)
// ----------------------------
function resolveBackendBinary() {
  const exeName = process.platform === "win32" ? "eurosec_backend.exe" : "eurosec_backend";

  // In packaged app, extraResources are copied under process.resourcesPath
  const packagedPath = path.join(process.resourcesPath, "backend", exeName);
  if (exists(packagedPath)) return packagedPath;

  // For "prod-like local run" (EUROSEC_FORCE_DIST=1), you may still want to test the binary
  // from repo backend/dist (optional).
  const repoRoot = path.resolve(__dirname, "..");             // frontend/
  const backendDir = path.resolve(repoRoot, "..", "backend"); // backend/
  const localBinary = path.join(backendDir, "dist", exeName);
  if (exists(localBinary)) return localBinary;

  return null;
}

function resolveBackendPython() {
  // Allow override
  if (process.env.EUROSEC_PYTHON && exists(process.env.EUROSEC_PYTHON)) {
    return process.env.EUROSEC_PYTHON;
  }

  const repoRoot = path.resolve(__dirname, "..");             // frontend/
  const backendDir = path.resolve(repoRoot, "..", "backend"); // backend/

  const candidates =
    process.platform === "win32"
      ? [
          path.join(backendDir, ".venv", "Scripts", "python.exe"),
          path.join(backendDir, ".venv", "Scripts", "python"),
        ]
      : [
          path.join(backendDir, ".venv", "bin", "python3"),
          path.join(backendDir, ".venv", "bin", "python"),
        ];

  for (const c of candidates) {
    if (exists(c)) return c;
  }

  // Fallback (if no venv found)
  return process.platform === "win32" ? "python" : "python3";
}

function startBackend() {
  if (backendProc) return;

  const repoRoot = path.resolve(__dirname, "..");             // frontend/
  const backendDir = path.resolve(repoRoot, "..", "backend"); // backend/

  // ----------------------------
  // NEW: Prefer packaged binary when app is packaged
  // Dev mode keeps your existing venv+uvicorn flow.
  // ----------------------------
  const backendBinary = app.isPackaged ? resolveBackendBinary() : null;

  if (backendBinary) {
    console.log(`[backend] starting packaged binary: ${backendBinary}`);

    // Pass host/port via env so your backend can read it (recommended in entrypoint.py)
    // If your binary ignores these env vars, set EUROSEC_BACKEND_PORT to match its default.
    backendProc = spawn(backendBinary, [], {
      cwd: backendDir, // not strictly needed, but fine
      env: {
        ...process.env,
        EUROSEC_BACKEND_HOST: backendHost,
        EUROSEC_BACKEND_PORT: String(backendPort),
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });

    backendProc.stdout.on("data", (d) => console.log(`[backend] ${String(d).trimEnd()}`));
    backendProc.stderr.on("data", (d) => console.error(`[backend] ${String(d).trimEnd()}`));

    backendProc.on("exit", (code, signal) => {
      console.log(`[backend] exited code=${code} signal=${signal}`);
      backendProc = null;
    });

    return;
  }

  // ----------------------------
  // Existing dev flow: run uvicorn via python venv (unchanged)
  // ----------------------------
  const py = resolveBackendPython();

  const args = [
    "-m",
    "uvicorn",
    "eurosec_ai.main:app",
    "--host",
    backendHost,
    "--port",
    String(backendPort),
  ];

  // ✅ reload only in dev
  if (isDev) args.push("--reload");

  console.log(`[backend] starting: ${py} ${args.join(" ")} (cwd=${backendDir})`);

  backendProc = spawn(py, args, {
    cwd: backendDir,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProc.stdout.on("data", (d) => console.log(`[backend] ${String(d).trimEnd()}`));
  backendProc.stderr.on("data", (d) => console.error(`[backend] ${String(d).trimEnd()}`));

  backendProc.on("exit", (code, signal) => {
    console.log(`[backend] exited code=${code} signal=${signal}`);
    backendProc = null;
  });
}

function stopBackend() {
  if (!backendProc) return;

  const pid = backendProc.pid;
  console.log(`[backend] stopping pid=${pid}`);

  if (process.platform === "win32") {
    spawn("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    try {
      backendProc.kill("SIGTERM");
    } catch {
      // ignore
    }
  }
  backendProc = null;
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      const ok = res.statusCode && res.statusCode >= 200 && res.statusCode < 300;
      res.resume();
      if (ok) resolve(true);
      else reject(new Error(`HTTP ${res.statusCode}`));
    });
    req.on("error", reject);
    req.setTimeout(1000, () => req.destroy(new Error("timeout")));
  });
}

async function waitForBackendHealth({ timeoutMs = 20000, intervalMs = 250 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      await httpGet(backendHealthUrl);
      return true;
    } catch {
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }
  return false;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (isDev) {
    // ✅ Dev mode: load Vite
    console.log(`[electron] dev mode -> loading ${devUrl}`);
    mainWindow.loadURL(devUrl);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    // ✅ Prod-like mode: load dist build (no Vite needed)
    const indexPath = path.join(__dirname, "../dist/index.html");
    console.log(`[electron] dist mode -> loading ${indexPath}`);
    mainWindow.loadFile(indexPath);
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  // Start backend automatically
  startBackend();

  const ok = await waitForBackendHealth();
  if (!ok) {
    dialog.showErrorBox(
      "Backend failed to start",
      `Backend did not become ready.\nTried: ${backendHealthUrl}\n\nIf packaged: check backend binary exists in resources/backend.\nIf dev: check backend venv + requirements.`
    );
  }

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => {
  stopBackend();
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

// ----------------------------
// IPC: pick workspace folder
// ----------------------------
ipcMain.handle("select-folder", async () => {
  const res = await dialog.showOpenDialog({ properties: ["openDirectory"] });
  if (res.canceled || res.filePaths.length === 0) return null;
  return res.filePaths[0];
});

// ----------------------------
// IPC: pick file
// ----------------------------
ipcMain.handle("select-file", async () => {
  const res = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [
      { name: "Documents", extensions: ["pdf", "docx", "txt", "xlsx"] },
      { name: "All Files", extensions: ["*"] },
    ],
  });
  if (res.canceled || res.filePaths.length === 0) return null;
  return res.filePaths[0];
});
