const API_PORT = new URLSearchParams(window.location.search).get("apiPort") || "18765";
const API_BASE = `http://127.0.0.1:${API_PORT}`;

const state = {
  devices: [],
  loggedIn: false,
  deviceSignature: "",
  lastUpdatedAt: null,
  logsSignature: "",
  loginPanelOpen: false,
  verifyTimer: null,
  busyDevices: {},
  statePollBusy: false,
  refreshPollBusy: false,
  interactingUntil: 0,
};

async function api(path, method = "GET", body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

function el(id) {
  return document.getElementById(id);
}

function isKnownMode(mode) {
  return MODE_OPTIONS.some((item) => item.value === mode);
}

function isKnownFan(fan) {
  return FAN_OPTIONS.some((item) => item.value === fan);
}

function formatBuildTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "local";
  return date.toLocaleString();
}

async function loadVersion() {
  try {
    const res = await fetch("./version.json", { cache: "no-store" });
    const info = await res.json();
    const version = info.version || "dev";
    const commit = info.commit || "local";
    const builtAt = formatBuildTime(info.built_at);
    el("versionBadge").textContent = `v${version} · ${commit} · ${builtAt}`;
    document.title = `美的美居多设备控制端 v${version} (${commit})`;
  } catch {
    el("versionBadge").textContent = "vdev · local";
  }
}

async function loadConfig() {
  try {
    const config = await api("/api/config");
    if (config.server) el("server").value = config.server;
    if (config.account) el("account").value = config.account;
    if (config.password) el("password").value = config.password;
    if (config.proxy) el("proxy").value = config.proxy;
  } catch {
    // The login form still works even when saved config cannot be loaded.
  }
}

function renderLogs(lines = []) {
  const box = el("logs");
  const visibleLines = lines.slice(-5);
  const signature = visibleLines.join("\n");
  if (signature === state.logsSignature) return;
  state.logsSignature = signature;
  box.textContent = signature;
  box.scrollTop = box.scrollHeight;
}

function appendLocalLog(line) {
  const current = el("logs").textContent ? el("logs").textContent.split("\n").filter(Boolean) : [];
  renderLogs([...current, line]);
}

function renderStatus(data) {
  state.loggedIn = Boolean(data.logged_in);
  state.lastUpdatedAt = new Date();
  el("statusBar").textContent = state.loggedIn ? `已登录，设备 ${data.device_count} 台` : "未登录";
  el("syncBar").textContent = state.lastUpdatedAt ? `最后更新 ${state.lastUpdatedAt.toLocaleTimeString()}` : "等待同步";
  updateLoginPanel();
  if (data.logs && data.logs.length) renderLogs(data.logs || []);
}

function updateLoginPanel() {
  const panel = document.querySelector(".login-panel");
  const loginButton = el("btnLogin");
  const shouldHide = state.loggedIn && !state.loginPanelOpen;
  panel.classList.toggle("is-hidden", shouldHide);
  loginButton.textContent = state.loggedIn && shouldHide ? "切换账号" : "登录账号";
}

function buildOptions(options, value) {
  return options.map((item) => `<option value="${item.value}" ${item.value === value ? "selected" : ""}>${item.label}</option>`).join("");
}

function formatTemp(value) {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return String(Math.round(num));
}

function tempStep(value) {
  const num = Number(value);
  return Number.isFinite(num) ? Math.round(num) : 26;
}

function translateMode(mode) {
  const map = {
    cool: "制冷",
    heat: "制热",
    auto: "自动",
    dry: "除湿",
    fan: "送风",
    off: "关闭",
  };
  return map[mode] || mode;
}

function translateFan(fan) {
  const map = {
    auto: "自动",
    low: "低风",
    medium: "中风",
    high: "高风",
    silent: "静音",
    full: "强风",
  };
  return map[fan] || fan;
}

const MODE_OPTIONS = [
  { value: "cool", label: "制冷" },
  { value: "heat", label: "制热" },
  { value: "auto", label: "自动" },
  { value: "dry", label: "除湿" },
  { value: "fan", label: "送风" },
  { value: "off", label: "关闭" },
];

const FAN_OPTIONS = [
  { value: "auto", label: "自动" },
  { value: "low", label: "低风" },
  { value: "medium", label: "中风" },
  { value: "high", label: "高风" },
  { value: "silent", label: "静音" },
  { value: "full", label: "强风" },
];

function deviceStateSignature(devices) {
  return JSON.stringify(
    devices.map((d) => [
      d.id,
      d.name,
      d.online,
      d.power_on,
      d.current_mode,
      d.preferred_mode,
      d.fan_speed,
      d.current_temperature,
      d.target_temperature,
      state.busyDevices[d.id] || "",
    ]),
  );
}

function extractSortNumber(name) {
  const match = String(name || "").match(/[（(]\s*(\d+)(?:\s*[-~－—至]\s*\d+)?\s*[)）]/);
  return match ? Number(match[1]) : Number.POSITIVE_INFINITY;
}

function sortDevices(devices) {
  return [...devices].sort((a, b) => {
    const an = extractSortNumber(a.name);
    const bn = extractSortNumber(b.name);
    if (an !== bn) return an - bn;
    return String(a.name || "").localeCompare(String(b.name || ""), "zh-Hans-CN");
  });
}

function renderDevices(devices = []) {
  if (document.activeElement && document.activeElement.matches("select[data-action]")) return;
  if (Date.now() < state.interactingUntil) return;
  const root = el("devices");
  const sortedDevices = sortDevices(devices);
  const signature = deviceStateSignature(sortedDevices);
  if (signature === state.deviceSignature) return;
  state.deviceSignature = signature;
  root.innerHTML = "";
  for (const d of sortedDevices) {
    const reportedMode = d.current_mode || (d.power_on ? "" : "off");
    const modeValue = isKnownMode(reportedMode) ? reportedMode : "off";
    const reportedFan = d.fan_speed || "auto";
    const fanValue = isKnownFan(reportedFan) ? reportedFan : "auto";
    const onlineClass = d.online ? "online" : "offline";
    const stateText = d.power_on ? "开" : "关";
    const busyText = state.busyDevices[d.id];
    const card = document.createElement("article");
    card.className = "card";
    card.innerHTML = `
      <div class="card-head">
        <div class="device-title">
          <span class="device-dot ${onlineClass}"></span>
          <h3>${d.name}</h3>
        </div>
        <button class="more-btn" type="button" aria-label="设备菜单">··</button>
      </div>
      <div class="device-meta">设备号：${d.id}</div>
      <div class="device-meta">当前温度：${formatTemp(d.current_temperature)}° 目标温度：${formatTemp(d.target_temperature)}°</div>
      <div class="control-item">
        <span class="control-label">开机 / 关机</span>
        <button class="power-switch ${d.power_on ? "is-on" : ""}" data-action="power" data-id="${d.id}" aria-label="开关机" ${busyText ? "disabled" : ""}>
          <span class="switch-track"><span class="switch-thumb"></span></span>
        </button>
      </div>
      <div class="temp-row">
        <button class="temp-btn" data-action="temp-down" data-id="${d.id}" aria-label="降低温度" ${busyText ? "disabled" : ""}>−</button>
        <div class="temp-value">${formatTemp(d.target_temperature ?? 26)}°</div>
        <button class="temp-btn" data-action="temp-up" data-id="${d.id}" aria-label="升高温度" ${busyText ? "disabled" : ""}>+</button>
      </div>
      <div class="select-grid">
        <label>
          <span>模式</span>
          <select data-action="mode" data-id="${d.id}" ${busyText ? "disabled" : ""}>
            ${buildOptions(MODE_OPTIONS, modeValue)}
          </select>
        </label>
        <label>
          <span>风速</span>
          <select data-action="fan" data-id="${d.id}" ${busyText ? "disabled" : ""}>
            ${buildOptions(FAN_OPTIONS, fanValue)}
          </select>
        </label>
      </div>
      <div class="card-foot">
        <span>${busyText || (d.power_on ? "运行中" : "已关闭")}</span>
        <span>状态：${stateText} | 模式：${translateMode(modeValue)} | 风速：${translateFan(fanValue)}</span>
      </div>
    `;
    root.appendChild(card);
  }
}

async function refreshAll() {
  const data = await api("/api/state");
  state.devices = data.devices || [];
  renderStatus(data);
  renderDevices(state.devices);
}

async function refreshDevices(quiet = true) {
  const data = await api("/api/refresh", "POST", { quiet });
  state.devices = data.devices || [];
  renderStatus(data.state || {});
  renderDevices(state.devices);
}

async function login() {
  const payload = {
    server: el("server").value,
    account: el("account").value,
    password: el("password").value,
    proxy: el("proxy").value,
  };
  const data = await api("/api/login", "POST", payload);
  state.devices = data.devices || [];
  state.deviceSignature = "";
  state.loginPanelOpen = false;
  renderStatus(data.state || {});
  renderDevices(state.devices);
}

async function control(deviceId, action, value) {
  try {
    const data = await api("/api/control", "POST", { device_id: deviceId, action, value });
    if (data.ok === false) {
      throw new Error(data.error || "控制失败");
    }
    state.devices = data.devices || [];
    state.deviceSignature = "";
    renderStatus(data.state || {});
    renderDevices(state.devices);
    if (data.state && Array.isArray(data.state.logs)) {
      renderLogs(data.state.logs);
    }
    if (action === "power") {
      await refreshDevices(true);
    } else {
      scheduleVerifyRefresh();
    }
  } catch (error) {
    appendLocalLog(`控制失败：${error.message || error}`);
    await refreshDevices(true).catch(() => {});
  } finally {
    delete state.busyDevices[deviceId];
    state.deviceSignature = "";
    renderDevices(state.devices);
  }
}

function scheduleVerifyRefresh() {
  if (!state.loggedIn) return;
  if (state.verifyTimer) clearTimeout(state.verifyTimer);
  state.verifyTimer = setTimeout(() => {
    refreshDevices(true).catch(() => {});
  }, 8000);
}

function holdDeviceRender(durationMs = 1200) {
  state.interactingUntil = Date.now() + durationMs;
}

async function pollState() {
  if (Date.now() < state.interactingUntil) return;
  if (state.statePollBusy) return;
  state.statePollBusy = true;
  try {
    const data = await api("/api/state?logs=0");
    renderStatus(data);
    state.devices = data.devices || [];
    renderDevices(state.devices);
  } finally {
    state.statePollBusy = false;
  }
}

async function pollDevices() {
  if (Date.now() < state.interactingUntil) return;
  if (!state.loggedIn || state.refreshPollBusy) return;
  state.refreshPollBusy = true;
  try {
    await refreshDevices();
  } finally {
    state.refreshPollBusy = false;
  }
}

document.addEventListener("click", async (event) => {
  const btn = event.target.closest("button[data-action]");
  if (!btn) return;
  const deviceId = btn.dataset.id;
  const action = btn.dataset.action;
  const device = state.devices.find((item) => item.id === deviceId);
  if (!device) return;
  if (action === "power") {
    const next = !device.power_on;
    state.busyDevices[deviceId] = next ? "开机中" : "关机中";
    state.deviceSignature = "";
    renderDevices(state.devices);
    await control(deviceId, "power", next);
  } else if (action === "temp-down") {
    const nextTemp = tempStep(device.target_temperature || 26) - 1;
    state.busyDevices[deviceId] = "设置温度中";
    state.deviceSignature = "";
    renderDevices(state.devices);
    await control(deviceId, "temperature", nextTemp);
  } else if (action === "temp-up") {
    const nextTemp = tempStep(device.target_temperature || 26) + 1;
    state.busyDevices[deviceId] = "设置温度中";
    state.deviceSignature = "";
    renderDevices(state.devices);
    await control(deviceId, "temperature", nextTemp);
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  if (!target.matches("select[data-action]")) return;
  holdDeviceRender(200);
  state.busyDevices[target.dataset.id] = target.dataset.action === "mode" ? "设置模式中" : "设置风速中";
  state.deviceSignature = "";
  setTimeout(() => renderDevices(state.devices), 250);
  await control(target.dataset.id, target.dataset.action, target.value);
});

document.addEventListener("pointerdown", (event) => {
  if (event.target.closest("select[data-action]")) {
    holdDeviceRender(2000);
  }
});

el("btnLogin").addEventListener("click", () => {
  if (state.loggedIn && !state.loginPanelOpen) {
    state.loginPanelOpen = true;
    updateLoginPanel();
    el("account").focus();
    return;
  }
  login();
});
el("btnRefresh").addEventListener("click", () => (state.loggedIn ? refreshDevices(false) : refreshAll()));

loadVersion();
loadConfig();
refreshAll();
setInterval(pollState, 5000);
setInterval(pollDevices, 30000);
