const state = {
  devices: [],
  loggedIn: false,
  deviceSignature: "",
  lastUpdatedAt: null,
  logsSignature: "",
  loginPanelOpen: false,
  verifyTimer: null,
  statePollBusy: false,
  refreshPollBusy: false,
};

async function api(path, method = "GET", body) {
  const res = await fetch(`http://127.0.0.1:18765${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

function el(id) {
  return document.getElementById(id);
}

function renderLogs(lines = []) {
  const box = el("logs");
  const signature = lines.join("\n");
  if (signature === state.logsSignature) return;
  state.logsSignature = signature;
  box.textContent = signature;
  box.scrollTop = box.scrollHeight;
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
      d.fan_speed,
      d.current_temperature,
      d.target_temperature,
    ]),
  );
}

function renderDevices(devices = []) {
  const root = el("devices");
  const signature = deviceStateSignature(devices);
  if (signature === state.deviceSignature) return;
  state.deviceSignature = signature;
  root.innerHTML = "";
  for (const d of devices) {
    const modeValue = d.current_mode || "cool";
    const fanValue = d.fan_speed || "auto";
    const onlineClass = d.online ? "online" : "offline";
    const stateText = d.power_on ? "开" : "关";
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
      <div class="device-meta">当前温度：${d.current_temperature ?? "-"}° 目标温度：${d.target_temperature ?? "-"}°</div>
      <div class="control-item">
        <span class="control-label">开机 / 关机</span>
        <button class="power-switch ${d.power_on ? "is-on" : ""}" data-action="power" data-id="${d.id}" aria-label="开关机">
          <span class="switch-track"><span class="switch-thumb"></span></span>
        </button>
      </div>
      <div class="temp-row">
        <button class="temp-btn" data-action="temp-down" data-id="${d.id}" aria-label="降低温度">−</button>
        <div class="temp-value">${Math.round(d.target_temperature ?? 26)}°</div>
        <button class="temp-btn" data-action="temp-up" data-id="${d.id}" aria-label="升高温度">+</button>
      </div>
      <div class="select-grid">
        <label>
          <span>模式</span>
          <select data-action="mode" data-id="${d.id}">
            ${buildOptions(MODE_OPTIONS, modeValue)}
          </select>
        </label>
        <label>
          <span>风速</span>
          <select data-action="fan" data-id="${d.id}">
            ${buildOptions(FAN_OPTIONS, fanValue)}
          </select>
        </label>
      </div>
      <div class="card-foot">
        <span>${d.power_on ? "运行中" : "已关闭"}</span>
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
  const data = await api("/api/control", "POST", { device_id: deviceId, action, value });
  state.devices = data.devices || [];
  state.deviceSignature = "";
  renderStatus(data.state || {});
  renderDevices(state.devices);
  if (data.state && Array.isArray(data.state.logs)) {
    renderLogs(data.state.logs.slice(-80));
  }
  scheduleVerifyRefresh();
}

function scheduleVerifyRefresh() {
  if (!state.loggedIn) return;
  if (state.verifyTimer) clearTimeout(state.verifyTimer);
  state.verifyTimer = setTimeout(() => {
    refreshDevices(true).catch(() => {});
  }, 1800);
}

function updateLocalDevice(deviceId, updates) {
  const device = state.devices.find((item) => item.id === deviceId);
  if (!device) return;
  Object.assign(device, updates);
  state.deviceSignature = "";
  renderDevices(state.devices);
}

async function pollState() {
  if (state.statePollBusy) return;
  state.statePollBusy = true;
  try {
    const data = await api("/api/state?logs=0");
    renderStatus(data);
    renderDevices(data.devices || []);
  } finally {
    state.statePollBusy = false;
  }
}

async function pollDevices() {
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
    updateLocalDevice(deviceId, { power_on: next, current_mode: next ? (device.current_mode === "off" ? "cool" : device.current_mode) : "off" });
    await control(deviceId, "power", next);
  } else if (action === "temp-down") {
    const nextTemp = (device.target_temperature || 26) - 1;
    updateLocalDevice(deviceId, { target_temperature: nextTemp });
    await control(deviceId, "temperature", nextTemp);
  } else if (action === "temp-up") {
    const nextTemp = (device.target_temperature || 26) + 1;
    updateLocalDevice(deviceId, { target_temperature: nextTemp });
    await control(deviceId, "temperature", nextTemp);
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  if (!target.matches("select[data-action]")) return;
  const updates = target.dataset.action === "mode" ? { current_mode: target.value, power_on: target.value !== "off" } : { fan_speed: target.value };
  updateLocalDevice(target.dataset.id, updates);
  await control(target.dataset.id, target.dataset.action, target.value);
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

refreshAll();
setInterval(pollState, 5000);
setInterval(pollDevices, 30000);
