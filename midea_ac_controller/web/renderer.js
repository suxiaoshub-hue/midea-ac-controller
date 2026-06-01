const API_PORT = new URLSearchParams(window.location.search).get("apiPort") || "18765";
const API_BASE = `http://127.0.0.1:${API_PORT}`;
const APP_TITLE = "白熊TT自用空调控制系统";
const WKS_ON_ICON = "./assets/wks/wks-classic-online-256.png";
const WKS_OFF_ICON = "./assets/wks/wks-classic-offline-256.png";

const state = {
  devices: [],
  serverDevices: [],
  wksGroups: {},
  loggedIn: false,
  deviceSignature: "",
  lastUpdatedAt: null,
  logsSignature: "",
  serverLogs: [],
  localLogs: [],
  loginPanelOpen: false,
  verifyTimer: null,
  activeCommand: null,
  commandQueue: [],
  statePollBusy: false,
  refreshPollBusy: false,
  interactingUntil: 0,
  autoPowerDefault: { mode: "manual", offline_delay_minutes: 10 },
  autoPowerRooms: {},
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

function commandSignature(command) {
  if (!command) return "";
  return `${command.deviceId}:${command.action}:${JSON.stringify(command.value)}`;
}

function commandQueueSignature() {
  return [state.activeCommand, ...state.commandQueue].map(commandSignature).join("|");
}

function normalizeWksName(value) {
  return String(value || "")
    .trim()
    .replace(/[（）]/g, (ch) => (ch === "（" ? "(" : ")"))
    .replace(/[－—–至]/g, "-")
    .replace(/\s+/g, "")
    .toLowerCase();
}

function mergeWksGroups(groups = {}) {
  state.wksGroups = groups && typeof groups === "object" ? groups : {};
  state.deviceSignature = "";
  renderDevices(state.devices);
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
    document.title = `${APP_TITLE} v${version} (${commit})`;
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

function currentTimeLabel() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

function logTimeValue(line) {
  const match = String(line || "").match(/^\[(\d{1,2}):(\d{2}):(\d{2})]/);
  if (!match) return null;
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
}

function combinedLogs() {
  const seen = new Set();
  const merged = [];
  [...state.serverLogs, ...state.localLogs].forEach((line, index) => {
    const value = String(line || "").trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    merged.push({ value, index, time: logTimeValue(value) });
  });
  return merged
    .sort((a, b) => {
      if (a.time !== null && b.time !== null && a.time !== b.time) return a.time - b.time;
      return a.index - b.index;
    })
    .map((item) => item.value);
}

function renderLogs(lines = null) {
  if (Array.isArray(lines)) {
    state.serverLogs = lines.filter(Boolean).slice(-50);
  }
  const box = el("logs");
  const visibleLines = combinedLogs().slice(-5);
  const signature = visibleLines.join("\n");
  if (signature === state.logsSignature) return;
  state.logsSignature = signature;
  box.textContent = signature;
  box.scrollTop = box.scrollHeight;
}

function appendLocalLog(line) {
  state.localLogs.push(`[${currentTimeLabel()}] ${line}`);
  state.localLogs = state.localLogs.slice(-50);
  renderLogs();
}

function renderStatus(data) {
  state.loggedIn = Boolean(data.logged_in);
  state.lastUpdatedAt = new Date();
  if (data.automation) renderAutoPower(data.automation);
  const queueCount = (state.activeCommand ? 1 : 0) + state.commandQueue.length;
  const deviceCount = data.device_count ?? state.serverDevices.length;
  el("statusBar").textContent = state.loggedIn
    ? `已登录，设备 ${deviceCount} 台${queueCount ? ` · 指令排队 ${queueCount} 条` : ""}`
    : "未登录";
  el("syncBar").textContent = state.lastUpdatedAt ? `最后更新 ${state.lastUpdatedAt.toLocaleTimeString()}` : "等待同步";
  updateLoginPanel();
  if (Array.isArray(data.logs)) {
    renderLogs(data.logs);
  } else {
    renderLogs();
  }
}

function renderAutoPower(automation = {}) {
  const config = automation.default || automation.config || {};
  state.autoPowerDefault = {
    mode: config.mode === "auto" ? "auto" : "manual",
    offline_delay_minutes: Number(config.offline_delay_minutes || 10),
  };
  state.autoPowerRooms = automation.rooms || {};
  el("autoPowerManual").classList.toggle("is-active", state.autoPowerDefault.mode === "manual");
  el("autoPowerAuto").classList.toggle("is-active", state.autoPowerDefault.mode === "auto");
  el("autoPowerDelay").value = String(state.autoPowerDefault.offline_delay_minutes);
  el("autoPowerSummary").textContent =
    state.autoPowerDefault.mode === "auto"
      ? `默认自动：未单独设置的包厢会自动开关，离线缓冲 ${state.autoPowerDefault.offline_delay_minutes} 分钟`
      : `默认手动：每个包厢可单独切换，默认离线缓冲 ${state.autoPowerDefault.offline_delay_minutes} 分钟`;
}

function autoPowerConfigFor(deviceId) {
  const room = state.autoPowerRooms[deviceId] || {};
  return {
    mode: room.mode || state.autoPowerDefault.mode || "manual",
    offline_delay_minutes: Number(room.offline_delay_minutes || state.autoPowerDefault.offline_delay_minutes || 10),
    host_count: Number(room.host_count || 0),
    online_count: Number(room.online_count || 0),
    offline_seconds: Number(room.offline_seconds || 0),
    offline_delay_seconds: Number(room.offline_delay_seconds || (room.offline_delay_minutes || state.autoPowerDefault.offline_delay_minutes || 10) * 60),
    desired_mode: room.desired_mode || "cool",
    desired_temperature: Number(room.desired_temperature || 26),
    desired_fan: room.desired_fan || "auto",
  };
}

function autoPowerLabel(device) {
  const room = autoPowerConfigFor(device.id);
  if (room.mode !== "auto") return "自动开关：手动";
  if (!room || !room.host_count) return "自动开关：未配置客户机";
  if (room.online_count > 0) return `自动开关：${room.online_count}/${room.host_count} 在线`;
  const delay = Math.max(1, Math.round(room.offline_delay_seconds / 60));
  const elapsed = Math.floor((room.offline_seconds || 0) / 60);
  return `自动开关：离线 ${elapsed}/${delay} 分钟`;
}

function autoPowerDetail(device) {
  const room = autoPowerConfigFor(device.id);
  if (room.mode !== "auto") return "自动设定：手动";
  return `自动设定：${formatTemp(room.desired_temperature)}° / ${translateMode(room.desired_mode)} / ${translateFan(room.desired_fan)}`;
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
      JSON.stringify(autoPowerConfigFor(d.id)),
      autoPowerLabel(d),
      wksHostsFor(d).map((item) => `${item.ip}:${item.online ? 1 : 0}`).join(","),
      commandQueueSignature(),
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

function wksHostsFor(device) {
  const exact = state.wksGroups[device.name];
  if (Array.isArray(exact)) return exact;
  const normalized = normalizeWksName(device.name);
  for (const [name, hosts] of Object.entries(state.wksGroups || {})) {
    if (normalizeWksName(name) === normalized && Array.isArray(hosts)) {
      return hosts;
    }
  }
  return device.wks_hosts || [];
}

function cloneDevices(devices = []) {
  return devices.map((device) => ({ ...device }));
}

function describeCommand(action, value) {
  if (action === "power") {
    const on = typeof value === "object" ? Boolean(value?.on) : Boolean(value);
    return on ? "开机" : "关机";
  }
  if (action === "temperature") return `温度 ${formatTemp(value)}°`;
  if (action === "mode") return `模式 ${translateMode(String(value))}`;
  if (action === "fan") return `风速 ${translateFan(String(value))}`;
  return action;
}

function getDeviceById(deviceId) {
  return state.devices.find((item) => item.id === deviceId) || state.serverDevices.find((item) => item.id === deviceId) || null;
}

function applyCommandToDevice(device, command) {
  if (!device || !command) return;
  if (command.action === "power") {
    const next = typeof command.value === "object" ? Boolean(command.value?.on) : Boolean(command.value);
    device.power_on = next;
    if (next && (!isKnownMode(device.current_mode) || device.current_mode === "off")) {
      const preferred = device.preferred_mode;
      if (isKnownMode(preferred) && preferred !== "off") {
        device.current_mode = preferred;
      }
    }
  } else if (command.action === "temperature") {
    const temp = Number(command.value);
    if (Number.isFinite(temp)) {
      device.target_temperature = temp;
    }
  } else if (command.action === "mode") {
    const mode = String(command.value);
    device.preferred_mode = mode;
    device.current_mode = mode;
  } else if (command.action === "fan") {
    device.fan_speed = String(command.value);
  }
}

function buildVisibleDevices(baseDevices = state.serverDevices) {
  const visible = sortDevices(cloneDevices(baseDevices));
  const commands = [state.activeCommand, ...state.commandQueue].filter(Boolean);
  for (const command of commands) {
    const device = visible.find((item) => item.id === command.deviceId);
    if (device) applyCommandToDevice(device, command);
  }
  return visible;
}

function syncVisibleDevices() {
  state.devices = buildVisibleDevices();
  state.deviceSignature = "";
  renderDevices(state.devices);
}

function queueStatusFor(deviceId) {
  if (state.activeCommand && state.activeCommand.deviceId === deviceId) {
    return "执行中";
  }
  const pendingCount = state.commandQueue.filter((command) => command.deviceId === deviceId).length;
  if (pendingCount <= 0) return "";
  return pendingCount > 1 ? `排队中 ×${pendingCount}` : "排队中";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderWksIcons(hosts = []) {
  return hosts
    .map((host) => {
      const icon = host.online ? WKS_ON_ICON : WKS_OFF_ICON;
      const stateLabel = host.online ? "在线" : "离线";
      const label = host.label || host.ip || "";
      const title = `${label} ${host.ip || ""} ${stateLabel}`;
      return `<img class="wks-node ${host.online ? "online" : "offline"}" src="${icon}" alt="${escapeHtml(label)}" title="${escapeHtml(title)}" />`;
    })
    .join("");
}

function renderDevices(devices = []) {
  if (document.activeElement && document.activeElement.matches("select[data-action], input[data-auto-delay]")) return;
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
    const busyText = queueStatusFor(d.id);
    const wksHosts = wksHostsFor(d);
    const wksOnlineCount = wksHosts.filter((host) => host.online).length;
    const wksHostCount = wksHosts.length;
    const wksSummary = wksHostCount ? `${wksOnlineCount}/${wksHostCount} 在线` : "未配置 WKS";
    const autoCfg = autoPowerConfigFor(d.id);
    const card = document.createElement("article");
    card.className = "card";
    card.innerHTML = `
      <div class="card-head">
        <div class="device-title">
          <span class="device-dot ${onlineClass}"></span>
          <h3>${d.name}</h3>
        </div>
        <div class="card-tools">
          ${wksHosts.length ? `<div class="wks-icons" aria-label="WKS电脑在线状态">${renderWksIcons(wksHosts)}</div>` : ""}
          <button class="more-btn" type="button" aria-label="设备菜单">··</button>
        </div>
      </div>
      <div class="device-meta">设备号：${d.id}</div>
      <div class="device-meta wks-meta">WKS电脑：${wksSummary}${wksHosts.length ? ` · ${escapeHtml(wksHosts.map((item) => item.label || item.ip.split(".").pop()).join(" / "))}` : ""}</div>
      <div class="device-meta">当前温度：${formatTemp(d.current_temperature)}° 目标温度：${formatTemp(d.target_temperature)}°</div>
      <div class="auto-power-card">
        <div class="mode-toggle auto-room-toggle" role="group" aria-label="当前包厢自动开关模式">
          <button type="button" class="${autoCfg.mode === "manual" ? "is-active" : ""}" data-auto-mode="manual" data-id="${escapeHtml(d.id)}">手动</button>
          <button type="button" class="${autoCfg.mode === "auto" ? "is-active" : ""}" data-auto-mode="auto" data-id="${escapeHtml(d.id)}">自动</button>
        </div>
        <label class="auto-delay-field">
          <span>离线</span>
          <input data-auto-delay data-id="${escapeHtml(d.id)}" type="number" min="1" max="180" step="1" value="${autoCfg.offline_delay_minutes}" />
          <span>分钟关</span>
        </label>
      </div>
      <div class="control-item">
        <span class="control-label">开机 / 关机</span>
        <button class="power-switch ${d.power_on ? "is-on" : ""}" data-action="power" data-id="${d.id}" aria-label="开关机">
          <span class="switch-track"><span class="switch-thumb"></span></span>
        </button>
      </div>
      <div class="temp-row">
        <button class="temp-btn" data-action="temp-down" data-id="${d.id}" aria-label="降低温度">−</button>
        <div class="temp-value">${formatTemp(d.target_temperature ?? 26)}°</div>
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
        <span>${busyText || (d.power_on ? "运行中" : "已关闭")}</span>
        <span>${autoPowerLabel(d)}</span>
        <span>${autoPowerDetail(d)}</span>
        <span>状态：${stateText} | 模式：${translateMode(modeValue)} | 风速：${translateFan(fanValue)}</span>
      </div>
    `;
    root.appendChild(card);
  }
}

async function refreshAll() {
  const data = await api("/api/state");
  state.serverDevices = data.devices || [];
  state.devices = buildVisibleDevices();
  renderStatus(data);
  renderDevices(state.devices);
}

async function refreshDevices(quiet = true, force = false) {
  if (!force && (state.commandQueue.length || state.activeCommand)) return;
  const data = await api("/api/refresh", "POST", { quiet });
  state.serverDevices = data.devices || [];
  state.devices = buildVisibleDevices();
  renderStatus(data.state || {});
  renderDevices(state.devices);
}

async function refreshWks() {
  try {
    const data = await api("/api/wks");
    mergeWksGroups(data.groups || {});
  } catch {
    // WKS icon status is optional; keep the last known state if polling fails.
  }
}

async function saveAutoPower(deviceId = "", mode = state.autoPowerDefault.mode, delay = state.autoPowerDefault.offline_delay_minutes) {
  const payload = {
    mode,
    offline_delay_minutes: Number(delay || 10),
  };
  if (deviceId) payload.device_id = deviceId;
  const data = await api("/api/auto-power", "POST", payload);
  if (data.ok === false) {
    throw new Error(data.error || "保存失败");
  }
  renderAutoPower(data.automation);
  state.deviceSignature = "";
  renderDevices(state.devices);
  const device = deviceId ? getDeviceById(deviceId) : null;
  const target = device ? device.name : "默认策略";
  appendLocalLog(`自动开关设置：${target} · ${mode === "auto" ? "自动" : "手动"}，离线缓冲 ${Number(delay || 10)} 分钟`);
}

async function login() {
  const payload = {
    server: el("server").value,
    account: el("account").value,
    password: el("password").value,
    proxy: el("proxy").value,
  };
  const data = await api("/api/login", "POST", payload);
  state.serverDevices = data.devices || [];
  state.devices = buildVisibleDevices();
  state.deviceSignature = "";
  state.loginPanelOpen = false;
  renderStatus(data.state || {});
  renderDevices(state.devices);
}

async function control(deviceId, action, value) {
  const data = await api("/api/control", "POST", { device_id: deviceId, action, value });
  if (data.ok === false) {
    throw new Error(data.error || "控制失败");
  }
  return data;
}

function queueControl(deviceId, action, value) {
  const command = {
    deviceId,
    action,
    value,
    label: describeCommand(action, value),
  };
  state.commandQueue.push(command);
  const device = getDeviceById(deviceId);
  appendLocalLog(`下发指令：${device ? device.name : deviceId} · ${command.label}`);
  syncVisibleDevices();
  processCommandQueue().catch((error) => {
    appendLocalLog(`队列异常：${error.message || error}`);
  });
}

async function processCommandQueue() {
  if (state.activeCommand) return;
  while (state.commandQueue.length) {
    state.activeCommand = state.commandQueue.shift();
    syncVisibleDevices();
    const command = state.activeCommand;
    try {
      const data = await control(command.deviceId, command.action, command.value);
      if (data.devices) {
        state.serverDevices = data.devices || [];
      }
      if (data.state) {
        renderStatus(data.state);
        if (Array.isArray(data.state.logs)) {
          renderLogs(data.state.logs);
        }
      }
      appendLocalLog(`执行完成：${command.label}`);
      if (command.action !== "power") {
        scheduleVerifyRefresh();
      }
    } catch (error) {
      appendLocalLog(`控制失败：${command.label} · ${error.message || error}`);
      await refreshDevices(true, true).catch(() => {});
    } finally {
      state.activeCommand = null;
      syncVisibleDevices();
    }
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
  if (state.commandQueue.length || state.activeCommand) return;
  if (state.statePollBusy) return;
  state.statePollBusy = true;
  try {
    const data = await api("/api/state");
    renderStatus(data);
    state.serverDevices = data.devices || [];
    state.devices = buildVisibleDevices();
    renderDevices(state.devices);
  } finally {
    state.statePollBusy = false;
  }
}

async function pollDevices() {
  if (Date.now() < state.interactingUntil) return;
  if (state.commandQueue.length || state.activeCommand) return;
  if (!state.loggedIn || state.refreshPollBusy) return;
  state.refreshPollBusy = true;
  try {
    await refreshDevices();
  } finally {
    state.refreshPollBusy = false;
  }
}

document.addEventListener("click", async (event) => {
  const autoModeBtn = event.target.closest("button[data-auto-mode]");
  if (autoModeBtn) {
    const card = autoModeBtn.closest(".auto-power-card");
    const delayInput = card ? card.querySelector("input[data-auto-delay]") : null;
    const delay = Number(delayInput?.value || autoPowerConfigFor(autoModeBtn.dataset.id).offline_delay_minutes || 10);
    await saveAutoPower(autoModeBtn.dataset.id, autoModeBtn.dataset.autoMode, delay).catch((error) => {
      appendLocalLog(`自动开关保存失败：${error.message || error}`);
    });
    return;
  }
  const btn = event.target.closest("button[data-action]");
  if (!btn) return;
  const deviceId = btn.dataset.id;
  const action = btn.dataset.action;
  const device = state.devices.find((item) => item.id === deviceId);
  if (!device) return;
  if (action === "power") {
    const next = !device.power_on;
    queueControl(deviceId, "power", next);
  } else if (action === "temp-down") {
    const nextTemp = tempStep(device.target_temperature || 26) - 1;
    queueControl(deviceId, "temperature", nextTemp);
  } else if (action === "temp-up") {
    const nextTemp = tempStep(device.target_temperature || 26) + 1;
    queueControl(deviceId, "temperature", nextTemp);
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  if (target.matches("input[data-auto-delay]")) {
    const deviceId = target.dataset.id;
    const config = autoPowerConfigFor(deviceId);
    await saveAutoPower(deviceId, config.mode, Number(target.value || config.offline_delay_minutes || 10)).catch((error) => {
      appendLocalLog(`自动开关保存失败：${error.message || error}`);
    });
    return;
  }
  if (!target.matches("select[data-action]")) return;
  holdDeviceRender(200);
  queueControl(target.dataset.id, target.dataset.action, target.value);
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
el("autoPowerManual").addEventListener("click", () => {
  state.autoPowerDefault.mode = "manual";
  renderAutoPower({ default: state.autoPowerDefault, rooms: state.autoPowerRooms });
});
el("autoPowerAuto").addEventListener("click", () => {
  state.autoPowerDefault.mode = "auto";
  renderAutoPower({ default: state.autoPowerDefault, rooms: state.autoPowerRooms });
});
el("btnSaveAutoPower").addEventListener("click", () => {
  saveAutoPower("", state.autoPowerDefault.mode, Number(el("autoPowerDelay").value || state.autoPowerDefault.offline_delay_minutes || 10)).catch((error) =>
    appendLocalLog(`自动开关保存失败：${error.message || error}`),
  );
});

loadVersion();
loadConfig();
refreshAll();
refreshWks();
setInterval(pollState, 5000);
setInterval(pollDevices, 30000);
setInterval(refreshWks, 3000);
