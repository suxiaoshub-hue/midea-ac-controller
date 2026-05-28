const state = {
  devices: [],
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
  el("logs").textContent = lines.join("\n");
}

function renderStatus(data) {
  el("statusBar").textContent = data.logged_in ? `已登录，设备 ${data.device_count} 台` : "未登录";
  renderLogs(data.logs || []);
}

function renderDevices(devices = []) {
  const root = el("devices");
  root.innerHTML = "";
  for (const d of devices) {
    const card = document.createElement("article");
    card.className = "card";
    card.innerHTML = `
      <h3>${d.name}</h3>
      <div>设备号：${d.id}</div>
      <div>温度：${d.current_temperature ?? "-"} / ${d.target_temperature ?? "-"}</div>
      <div class="row">
        <button data-action="power" data-id="${d.id}">${d.power_on ? "关机" : "开机"}</button>
        <button data-action="temp-down" data-id="${d.id}">-</button>
        <button data-action="temp-up" data-id="${d.id}">+</button>
      </div>
      <div class="row">
        <select data-action="mode" data-id="${d.id}">
          ${["cool","heat","auto","dry","fan","off"].map(v => `<option value="${v}" ${v === "cool" ? "selected" : ""}>${v}</option>`).join("")}
        </select>
      </div>
      <div class="row">
        <select data-action="fan" data-id="${d.id}">
          ${["auto","low","medium","high"].map(v => `<option value="${v}">${v}</option>`).join("")}
        </select>
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

async function login() {
  const payload = {
    server: el("server").value,
    account: el("account").value,
    password: el("password").value,
    proxy: el("proxy").value,
  };
  const data = await api("/api/login", "POST", payload);
  state.devices = data.devices || [];
  renderStatus(data.state || {});
  renderDevices(state.devices);
}

async function control(deviceId, action, value) {
  const data = await api("/api/control", "POST", { device_id: deviceId, action, value });
  state.devices = data.devices || [];
  renderStatus(data.state || {});
  renderDevices(state.devices);
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
el("btnRefresh").addEventListener("click", refreshAll);

refreshAll();
