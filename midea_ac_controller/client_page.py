from __future__ import annotations


def build_client_page() -> str:
    return """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>白熊TT客户机空调控制端</title>
  <style>
    * { box-sizing: border-box; }
    :root {
      --bg: #edf4fb;
      --panel: rgba(255, 255, 255, 0.93);
      --line: rgba(130, 151, 176, 0.22);
      --text: #0e1726;
      --muted: #6a788b;
      --blue: #2277f2;
      --green: #29b56d;
      --shadow: 0 18px 44px rgba(19, 38, 67, 0.12);
    }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 12% 8%, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.52) 24%, transparent 43%),
        linear-gradient(135deg, #f8fbff 0%, var(--bg) 58%, #e5edf8 100%);
    }
    .shell {
      width: min(1140px, calc(100vw - 40px));
      margin: 0 auto;
      padding: 28px 0 34px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 22px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
      min-width: 0;
    }
    .logo {
      width: 58px;
      height: 58px;
      border-radius: 17px;
      display: grid;
      place-items: center;
      background: linear-gradient(180deg, #2e7cff 0%, #1d64c8 100%);
      color: #fff;
      font-size: 27px;
      font-weight: 900;
      box-shadow: 0 14px 28px rgba(34, 119, 242, 0.20);
    }
    .brand h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.12;
    }
    .brand p {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border: 1px solid rgba(41, 181, 109, 0.24);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.78);
      color: #167a49;
      font-size: 13px;
      font-weight: 800;
      box-shadow: 0 10px 26px rgba(19, 38, 67, 0.08);
      white-space: nowrap;
    }
    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 0 5px rgba(41, 181, 109, 0.12);
    }
    .summary {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr 0.8fr;
      gap: 14px;
      margin-bottom: 16px;
    }
    .summary-item {
      min-height: 86px;
      padding: 18px 20px;
      border: 1px solid rgba(255, 255, 255, 0.74);
      border-radius: 18px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .summary-item span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 8px;
    }
    .summary-item strong {
      font-size: 25px;
      line-height: 1;
    }
    .card-wrap {
      display: flex;
      justify-content: center;
    }
    .card {
      width: min(560px, 100%);
      min-height: 404px;
      padding: 22px;
      border: 1px solid rgba(255, 255, 255, 0.78);
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.94);
      box-shadow: var(--shadow);
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      gap: 14px;
    }
    .card-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }
    .room h2 {
      margin: 0;
      font-size: 28px;
      line-height: 1.15;
    }
    .room p {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }
    .power {
      width: 82px;
      height: 40px;
      border: 0;
      border-radius: 999px;
      background: linear-gradient(180deg, #85e5ae, var(--green));
      box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.12);
      position: relative;
      flex: 0 0 auto;
    }
    .power::after {
      content: "";
      position: absolute;
      top: 4px;
      right: 4px;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 5px 14px rgba(15, 23, 42, 0.18);
      transition: right 0.18s ease;
    }
    .power.off {
      background: #cbd5e1;
    }
    .power.off::after {
      right: 46px;
    }
    .meta-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }
    .mode-chip {
      padding: 6px 9px;
      border-radius: 999px;
      background: #edf6ff;
      color: #1d64c8;
    }
    .temperature {
      display: grid;
      justify-items: center;
      align-content: center;
      gap: 14px;
      padding: 10px 0;
    }
    .temp-main {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 18px;
      width: 100%;
    }
    .temp-btn {
      width: 66px;
      height: 58px;
      border: 1px solid var(--line);
      border-radius: 17px;
      background: #fff;
      color: var(--text);
      font-size: 30px;
      font-weight: 900;
      box-shadow: 0 10px 22px rgba(19, 38, 67, 0.08);
    }
    .temp-display {
      width: 156px;
      text-align: center;
    }
    .temp-display strong {
      display: block;
      font-size: 66px;
      line-height: 0.94;
      letter-spacing: 0;
    }
    .temp-display span {
      display: block;
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }
    .range {
      width: 100%;
    }
    .range-track {
      height: 10px;
      border-radius: 999px;
      background: linear-gradient(90deg, #bdebd4 0%, #7dcfff 55%, #ffd388 100%);
      position: relative;
      overflow: hidden;
    }
    .range-thumb {
      position: absolute;
      top: 50%;
      left: 46%;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #fff;
      border: 4px solid var(--blue);
      transform: translate(-50%, -50%);
      box-shadow: 0 5px 12px rgba(34, 119, 242, 0.28);
    }
    .range-labels {
      display: flex;
      justify-content: space-between;
      margin-top: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
    }
    .actions {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 9px;
    }
    .action {
      min-height: 46px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fff;
      color: var(--text);
      font-size: 13px;
      font-weight: 900;
    }
    .action.active {
      border-color: rgba(34, 119, 242, 0.32);
      background: #eaf3ff;
      color: #1d64c8;
    }
    .card.busy {
      border-color: rgba(34, 119, 242, 0.30);
      box-shadow: 0 18px 44px rgba(34, 119, 242, 0.14);
    }
    .card.busy .power,
    .card.busy .temp-btn,
    .card.busy .action {
      transform: translateY(0);
    }
    .card.disabled {
      opacity: 0.72;
    }
    .card.disabled .temperature,
    .card.disabled .actions {
      filter: grayscale(0.25);
    }
    .footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-top: 18px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }
    .footer strong {
      color: var(--blue);
    }
    .overlay {
      display: none;
      margin-top: 14px;
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.8);
      color: #7a5c0b;
      font-weight: 800;
      box-shadow: var(--shadow);
    }
    .overlay.show {
      display: block;
    }
    @media (max-width: 980px) {
      .summary {
        grid-template-columns: 1fr;
      }
      .topbar {
        align-items: flex-start;
        flex-direction: column;
      }
      .room h2 {
        font-size: 24px;
      }
      .temp-display strong {
        font-size: 58px;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="logo">TT</div>
        <div>
          <h1>白熊TT客户机空调控制端</h1>
          <p>仅允许控制本包厢</p>
        </div>
      </div>
      <div id="statusPill" class="status-pill"><span class="status-dot"></span> 网关在线 · 等待授权</div>
    </header>

    <section class="summary">
      <div class="summary-item">
        <span>当前包厢</span>
        <strong id="roomName">--</strong>
      </div>
      <div class="summary-item">
        <span>允许温度</span>
        <strong id="policy">23-28°C</strong>
      </div>
      <div class="summary-item">
        <span>同步状态</span>
        <strong id="syncState">等待连接</strong>
      </div>
    </section>

    <main class="card-wrap">
      <article id="roomCard" class="card disabled">
        <div class="card-head">
          <div class="room">
            <h2 id="cardTitle">未授权</h2>
            <p id="cardSubtitle">当前电脑未绑定包厢</p>
          </div>
          <button id="powerBtn" class="power off" type="button" aria-label="开关"></button>
        </div>
        <div class="meta-row">
          <span id="tempMeta">室温 --</span>
          <span id="modeChip" class="mode-chip">未授权</span>
        </div>
        <section class="temperature">
          <div class="temp-main">
            <button id="tempDown" class="temp-btn" type="button">−</button>
            <div class="temp-display">
              <strong id="targetTemp">--</strong>
              <span>目标温度</span>
            </div>
            <button id="tempUp" class="temp-btn" type="button">+</button>
          </div>
          <div class="range">
            <div class="range-track"><span id="thumb" class="range-thumb"></span></div>
            <div class="range-labels"><span id="minTemp">23°</span><span id="maxTemp">28°</span></div>
          </div>
        </section>
        <div class="actions">
          <button class="action" data-mode="cool" type="button">制冷</button>
          <button class="action" data-mode="heat" type="button">制热</button>
          <button class="action" data-fan="auto" type="button">自动风</button>
        </div>
      </article>
    </main>

    <div id="overlay" class="overlay"></div>

    <footer class="footer">
      <span id="gateway">网关：--</span>
      <span>客户机策略：<strong id="policyFoot">23-28°C</strong></span>
    </footer>
  </div>

  <script>
    const API_BASE = "";
    const state = {
      room: null,
      policy: { min_temperature: 23, max_temperature: 28 },
      logged_in: false,
      authorized: false,
      client_ip: "",
      message: "",
      loading: false,
      activeCommand: null,
      commandQueue: [],
      pollBusy: false,
    };

    function el(id) {
      return document.getElementById(id);
    }

    function clampTemp(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) return state.room ? Number(state.room.target_temperature || 25) : 25;
      return Math.max(state.policy.min_temperature, Math.min(state.policy.max_temperature, Math.round(num)));
    }

    function tempToThumb(value) {
      const min = state.policy.min_temperature;
      const max = state.policy.max_temperature;
      if (max <= min) return "50%";
      const pct = ((clampTemp(value) - min) / (max - min)) * 100;
      return `${Math.max(0, Math.min(100, pct))}%`;
    }

    function modeLabel(mode) {
      return { cool: "制冷", heat: "制热", auto: "自动", dry: "除湿", fan: "送风", off: "关闭" }[mode] || mode || "--";
    }

    function fanLabel(fan) {
      return { auto: "自动风", low: "低风", medium: "中风", high: "高风", silent: "静音", full: "强风" }[fan] || fan || "--";
    }

    function describeCommand(command) {
      if (!command) return "";
      if (command.action === "power") return command.value ? "开机" : "关机";
      if (command.action === "temperature") return `温度 ${clampTemp(command.value)}°`;
      if (command.action === "mode") return `模式 ${modeLabel(command.value)}`;
      if (command.action === "fan") return `风速 ${fanLabel(command.value)}`;
      return command.action;
    }

    function pendingCommands() {
      return [state.activeCommand, ...state.commandQueue].filter(Boolean);
    }

    function applyCommand(room, command) {
      if (!room || !command) return;
      if (command.action === "power") {
        room.power_on = Boolean(command.value);
        if (!room.power_on) return;
        if (!room.current_mode || room.current_mode === "off") {
          room.current_mode = "cool";
        }
      } else if (command.action === "temperature") {
        room.target_temperature = clampTemp(command.value);
      } else if (command.action === "mode") {
        room.current_mode = String(command.value);
        if (room.current_mode !== "off") room.power_on = true;
      } else if (command.action === "fan") {
        room.fan_speed = String(command.value);
      }
    }

    function visibleRoom() {
      if (!state.room) return null;
      const room = { ...state.room };
      pendingCommands().forEach((command) => applyCommand(room, command));
      return room;
    }

    function render(data) {
      if (data) {
        state.room = data.room || null;
        state.policy = data.policy || state.policy;
        state.logged_in = Boolean(data.logged_in);
        state.authorized = Boolean(data.authorized);
        state.client_ip = data.client_ip || "";
        state.message = data.message || data.error || "";
      }
      renderState();
    }

    function renderState() {
      const room = visibleRoom();
      const queueCount = pendingCommands().length;
      const busyText = state.activeCommand
        ? `执行中：${describeCommand(state.activeCommand)}`
        : state.commandQueue.length
          ? `排队中：${state.commandQueue.length} 条`
          : "";

      el("policy").textContent = `${state.policy.min_temperature}-${state.policy.max_temperature}°C`;
      el("policyFoot").textContent = `${state.policy.min_temperature}-${state.policy.max_temperature}°C`;
      el("syncState").textContent = busyText || state.message || (state.authorized ? "刚刚更新" : "等待授权");
      el("statusPill").innerHTML = state.authorized
        ? `<span class="status-dot"></span> 网关在线 · ${queueCount ? "指令同步中" : "已授权"}`
        : '<span class="status-dot" style="background:#f59e0b; box-shadow:0 0 0 5px rgba(245,158,11,.12)"></span> 网关在线 · 未授权';

      if (!state.authorized || !room) {
        el("roomName").textContent = "--";
        el("cardTitle").textContent = state.authorized ? "未绑定包厢" : "未授权";
        el("cardSubtitle").textContent = state.authorized ? "当前电脑未绑定包厢" : "当前电脑无权访问";
        el("tempMeta").textContent = "室温 --";
        el("modeChip").textContent = state.authorized ? "等待绑定" : "未授权";
        el("targetTemp").textContent = "--";
        el("gateway").textContent = "网关：--";
        el("roomCard").classList.add("disabled");
        el("roomCard").classList.remove("busy");
        return;
      }

      el("roomName").textContent = room.name || "--";
      el("cardTitle").textContent = room.name || "--";
      el("cardSubtitle").textContent = room.device_id ? `设备号 ${room.device_id}` : "当前包厢空调";
      el("tempMeta").textContent = `室温 ${room.current_temperature == null ? "--" : Math.round(room.current_temperature)}°C`;
      el("modeChip").textContent = `${modeLabel(room.current_mode)} · ${fanLabel(room.fan_speed)}`;
      el("targetTemp").textContent = `${clampTemp(room.target_temperature)}°`;
      el("thumb").style.left = tempToThumb(room.target_temperature);
      el("gateway").textContent = `客户机：${state.client_ip || "--"}`;
      el("powerBtn").classList.toggle("off", !room.power_on);
      el("roomCard").classList.remove("disabled");
      el("roomCard").classList.toggle("busy", queueCount > 0);
      el("powerBtn").setAttribute("aria-label", room.power_on ? "关机" : "开机");
      el("minTemp").textContent = `${state.policy.min_temperature}°`;
      el("maxTemp").textContent = `${state.policy.max_temperature}°`;
      document.querySelectorAll(".action[data-mode]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.mode === room.current_mode);
      });
      document.querySelectorAll(".action[data-fan]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.fan === room.fan_speed);
      });
    }

    async function api(path, method = "GET", body) {
      const res = await fetch(`${API_BASE}${path}`, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      return res.json();
    }

    async function refresh() {
      if (state.activeCommand || state.commandQueue.length || state.pollBusy) return;
      state.pollBusy = true;
      try {
        const suffix = window.location.search || "";
        const data = await api(`/api/client/state${suffix}`);
        render(data);
      } catch (error) {
        render({ authorized: false, error: error.message || String(error) });
      } finally {
        state.pollBusy = false;
      }
    }

    function queueControl(action, value) {
      if (!state.authorized || !state.room) return;
      state.commandQueue.push({
        action,
        value,
      });
      state.message = `已加入队列：${describeCommand({ action, value })}`;
      renderState();
      processQueue();
    }

    async function processQueue() {
      if (state.activeCommand) return;
      while (state.commandQueue.length) {
        state.activeCommand = state.commandQueue.shift();
        renderState();
        const payload = {
          device_id: state.room.device_id,
          action: state.activeCommand.action,
          value: state.activeCommand.value,
        };
        try {
          const suffix = window.location.search || "";
          const data = await api(`/api/client/control${suffix}`, "POST", payload);
          if (!data.ok) throw new Error(data.error || "控制失败");
          state.room = data.room || state.room;
          state.policy = data.policy || state.policy;
          state.message = `已执行：${describeCommand(state.activeCommand)}`;
        } catch (error) {
          el("overlay").textContent = error.message || String(error);
          el("overlay").classList.add("show");
          setTimeout(() => el("overlay").classList.remove("show"), 2400);
          state.commandQueue = [];
          await refreshAfterFailure();
          break;
        } finally {
          state.activeCommand = null;
          renderState();
        }
      }
    }

    async function refreshAfterFailure() {
      try {
        const suffix = window.location.search || "";
        const data = await api(`/api/client/state${suffix}`);
        render(data);
      } catch {
        // Keep the optimistic state visible; the next poll will recover.
      }
    }

    el("powerBtn").addEventListener("click", () => {
      const room = visibleRoom();
      if (!room) return;
      queueControl("power", !room.power_on);
    });
    el("tempDown").addEventListener("click", () => {
      const room = visibleRoom();
      if (!room) return;
      queueControl("temperature", clampTemp(room.target_temperature) - 1);
    });
    el("tempUp").addEventListener("click", () => {
      const room = visibleRoom();
      if (!room) return;
      queueControl("temperature", clampTemp(room.target_temperature) + 1);
    });
    document.querySelectorAll(".action[data-mode]").forEach((btn) => {
      btn.addEventListener("click", () => queueControl("mode", btn.dataset.mode));
    });
    document.querySelectorAll(".action[data-fan]").forEach((btn) => {
      btn.addEventListener("click", () => queueControl("fan", btn.dataset.fan));
    });

    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
    """.replace("__TITLE__", "白熊TT客户机空调控制端").strip()
