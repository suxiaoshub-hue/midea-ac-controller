const state = {
  devices: [],
  loggedIn: false,
  deviceSignature: "",
  lastUpdatedAt: null,
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
  box.textContent = lines.join("\n");
  box.scrollTop = box.scrollHeight;
}

function renderStatus(data) {
  state.loggedIn = Boolean(data.logged_in);
  state.lastUpdatedAt = new Date();
  el("statusBar").textContent = state.loggedIn ? `已登录，设备 ${data.device_count} 台` : "未登录";
  el("syncBar").textContent = state.lastUpdatedAt ? `最后更新 ${state.lastUpdatedAt.toLocaleTimeString()}` : "等待同步";
  renderLogs(data.logs || []);
}

function buildOptions(options, value) {
  return options.map((item) => `<option value="${item}" ${item === value ? "selected" : ""}>${item}</option>`).join("");
}

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
            ${buildOptions(["cool", "heat", "auto", "dry", "fan", "off"], modeValue)}
          </select>
        </label>
        <label>
          <span>风速</span>
          <select data-action="fan" data-id="${d.id}">
            ${buildOptions(["auto", "low", "medium", "high", "silent", "full"], fanValue)}
          </select>
        </label>
      </div>
      <div class="card-foot">
        <span>${d.power_on ? "运行中" : "已关闭"}</span>
        <span>${modeValue}</span>
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

async function refreshDevices() {
  const data = await api("/api/refresh", "POST", {});
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
  renderStatus(data.state || {});
  renderDevices(state.devices);
}

async function control(deviceId, action, value) {
  const data = await api("/api/control", "POST", { device_id: deviceId, action, value });
  state.devices = data.devices || [];
  state.deviceSignature = "";
  renderStatus(data.state || {});
  renderDevices(state.devices);
}

async function pollState() {
  if (state.statePollBusy) return;
  state.statePollBusy = true;
  try {
    const data = await api("/api/state");
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
    await control(deviceId, "power", !device.power_on);
  } else if (action === "temp-down") {
    await control(deviceId, "temperature", (device.target_temperature || 26) - 1);
  } else if (action === "temp-up") {
    await control(deviceId, "temperature", (device.target_temperature || 26) + 1);
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  if (!target.matches("select[data-action]")) return;
  await control(target.dataset.id, target.dataset.action, target.value);
});

el("btnLogin").addEventListener("click", login);
el("btnRefresh").addEventListener("click", () => (state.loggedIn ? refreshDevices() : refreshAll()));

refreshAll();
setInterval(pollState, 1200);
setInterval(pollDevices, 7000);
