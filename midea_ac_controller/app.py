from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .midea_client import SERVER_MEIJU, SERVER_MSMART, AcDevice, MideaAcClient


APP_DIR = Path.home() / ".midea_ac_controller"
CONFIG_FILE = APP_DIR / "config.json"


class TkLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        self.callback(self.format(record))


class MideaAcApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("白熊TT自用空调控制系统")
        self.root.geometry("1120x760")
        self.root.minsize(880, 620)

        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.client = MideaAcClient(APP_DIR, self.log)
        self.worker_queue: queue.Queue = queue.Queue()
        self.main_thread_id = threading.get_ident()
        self.async_loop = asyncio.new_event_loop()
        self.async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.async_thread.start()
        self.device_cards: dict[str, ttk.Frame] = {}
        self.devices: list[AcDevice] = []
        self.busy = BooleanVar(value=False)

        self.server_var = StringVar(value=SERVER_MEIJU)
        self.account_var = StringVar()
        self.password_var = StringVar()
        self.proxy_var = StringVar()
        self.status_var = StringVar(value="未登录")

        self._load_config()
        self._configure_style()
        self._build_ui()
        self._wire_logging()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._drain_worker_queue)

    def _configure_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 26, "bold"), foreground="#0f172a")
        style.configure("Card.TFrame", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("CardTitle.TLabel", background="#ffffff", font=("Microsoft YaHei UI", 14, "bold"), foreground="#111827")
        style.configure("CardText.TLabel", background="#ffffff", foreground="#475569")
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("On.TLabel", background="#ffffff", foreground="#16a34a", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Off.TLabel", background="#ffffff", foreground="#94a3b8", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=(24, 20))
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="白熊TT自用空调控制系统", style="Title.TLabel").pack(anchor="center", pady=(0, 18))

        login = ttk.Frame(main)
        login.pack(fill="x", pady=(0, 18))
        for idx in range(9):
            login.columnconfigure(idx, weight=1 if idx in {1, 3, 5, 7} else 0)

        ttk.Label(login, text="服务器").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Combobox(login, textvariable=self.server_var, values=[SERVER_MEIJU, SERVER_MSMART], width=10, state="readonly").grid(row=0, column=1, sticky="ew", padx=(0, 10))
        ttk.Label(login, text="账号").grid(row=0, column=2, sticky="w", padx=(0, 6))
        ttk.Entry(login, textvariable=self.account_var).grid(row=0, column=3, sticky="ew", padx=(0, 10))
        ttk.Label(login, text="密码").grid(row=0, column=4, sticky="w", padx=(0, 6))
        ttk.Entry(login, textvariable=self.password_var, show="*").grid(row=0, column=5, sticky="ew", padx=(0, 10))
        ttk.Label(login, text="代理").grid(row=0, column=6, sticky="w", padx=(0, 6))
        ttk.Entry(login, textvariable=self.proxy_var).grid(row=0, column=7, sticky="ew", padx=(0, 10))
        ttk.Button(login, text="登录账号", style="Primary.TButton", command=self.login).grid(row=0, column=8, sticky="ew")

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(0, 16))
        ttk.Button(actions, text="刷新全部设备", style="Primary.TButton", command=self.refresh).pack(side="left")
        ttk.Button(actions, text="保存登录信息", command=self.save_config).pack(side="left", padx=(10, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="left", padx=(18, 0))

        content = ttk.Frame(main)
        content.pack(fill="both", expand=True)
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)

        self.canvas = ttk.Frame(content)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self._build_scroll_area(self.canvas)

        log_panel = ttk.Frame(main)
        log_panel.pack(fill="x", pady=(18, 0))
        ttk.Label(log_panel, text="运行日志输出区", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        self.log_text = ScrolledText(log_panel, height=6, wrap="word", bg="#f8fafc", fg="#1e293b", relief="flat")
        self.log_text.pack(fill="x", pady=(8, 0))
        self.log_text.configure(state="disabled")

    def _build_scroll_area(self, parent):
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        canvas = __import__("tkinter").Canvas(outer, highlightthickness=0, bg="#eef3f8")
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.cards_frame = ttk.Frame(canvas, padding=8)
        self.cards_frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _wire_logging(self):
        handler = TkLogHandler(self.log)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def _run_async_loop(self):
        asyncio.set_event_loop(self.async_loop)
        self.async_loop.run_forever()

    def _load_config(self):
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            self.server_var.set(data.get("server") or SERVER_MEIJU)
            self.account_var.set(data.get("account") or "")
            self.password_var.set(data.get("password") or "")
            self.proxy_var.set(data.get("proxy") or "")
        except Exception:
            pass

    def save_config(self):
        data = {
            "server": self.server_var.get(),
            "account": self.account_var.get(),
            "password": self.password_var.get(),
            "proxy": self.proxy_var.get(),
        }
        CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log("登录信息已保存到本机用户目录")

    def login(self):
        account = self.account_var.get().strip()
        password = self.password_var.get()
        if not account or not password:
            messagebox.showwarning("缺少账号", "请输入美的美居或 MSmartHome 的账号和密码。")
            return
        self.save_config()
        self._run_task(self._login_and_load())

    async def _login_and_load(self):
        ok = await self.client.login(self.server_var.get(), self.account_var.get().strip(), self.password_var.get(), self.proxy_var.get().strip())
        if not ok:
            raise RuntimeError("登录失败，请检查账号、密码、服务器和网络")
        return await self.client.load_devices()

    def refresh(self):
        self._run_task(self._refresh())

    async def _refresh(self):
        return await self.client.refresh_devices()

    def _render_devices(self):
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self.device_cards.clear()
        if not self.devices:
            ttk.Label(self.cards_frame, text="暂无空调设备。请登录后刷新。").grid(row=0, column=0, sticky="w", padx=12, pady=12)
            return
        columns = 3 if self.root.winfo_width() < 1100 else 4
        for idx, device in enumerate(self.devices):
            row, col = divmod(idx, columns)
            card = ttk.Frame(self.cards_frame, style="Card.TFrame", padding=16)
            card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)
            self.cards_frame.columnconfigure(col, weight=1, uniform="cards")
            self._populate_card(card, device)

    def _populate_card(self, card: ttk.Frame, device: AcDevice):
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="●", style="On.TLabel" if device.online else "Off.TLabel").pack(side="left")
        ttk.Label(top, text=device.name, style="CardTitle.TLabel").pack(side="left", padx=(8, 0))
        ttk.Label(card, text=f"T0x{device.device_type:02X}  {device.id}", style="CardText.TLabel").pack(anchor="w", pady=(4, 12))

        power_text = "开机" if device.power_on else "关机"
        ttk.Button(card, text=power_text, command=lambda d=device: self._toggle_power(d)).pack(fill="x", pady=(0, 10))

        temp_row = ttk.Frame(card, style="Card.TFrame")
        temp_row.pack(fill="x", pady=(0, 10))
        ttk.Button(temp_row, text="-", width=3, command=lambda d=device: self._change_temp(d, -1)).pack(side="left")
        ttk.Label(temp_row, text=f"{device.target_temperature:g}°", style="CardTitle.TLabel").pack(side="left", expand=True)
        ttk.Button(temp_row, text="+", width=3, command=lambda d=device: self._change_temp(d, 1)).pack(side="right")

        mode_row = ttk.Frame(card, style="Card.TFrame")
        mode_row.pack(fill="x", pady=(0, 8))
        mode = StringVar(value=self._display_mode(device))
        ttk.Combobox(mode_row, textvariable=mode, values=["cool", "heat", "auto", "dry", "fan", "off"], state="readonly", width=8).pack(side="left", fill="x", expand=True)
        ttk.Button(mode_row, text="模式", command=lambda d=device, v=mode: self._set_mode(d, v.get())).pack(side="left", padx=(8, 0))

        fan_row = ttk.Frame(card, style="Card.TFrame")
        fan_row.pack(fill="x")
        fan = StringVar(value="auto")
        ttk.Combobox(fan_row, textvariable=fan, values=["auto", "low", "medium", "high"], state="readonly", width=8).pack(side="left", fill="x", expand=True)
        ttk.Button(fan_row, text="风速", command=lambda d=device, v=fan: self._set_fan(d, v.get())).pack(side="left", padx=(8, 0))

        current = device.current_temperature
        if current is not None:
            ttk.Label(card, text=f"当前室温 {current:g}°", style="CardText.TLabel").pack(anchor="w", pady=(10, 0))

    def _display_mode(self, device: AcDevice) -> str:
        if device.device_type == 0x21 or device.is_central_node:
            if not device.power_on:
                return device.preferred_mode or "off"
            return {"0": "off", "1": "fan", "2": "cool", "3": "heat", "4": "auto", "5": "dry"}.get(str(device.attrs.get("run_mode")), device.preferred_mode or "cool")
        if not device.power_on:
            return device.preferred_mode or "off"
        return str(device.attrs.get("mode") or device.attrs.get("mode.current") or device.preferred_mode or "cool")

    def _toggle_power(self, device: AcDevice):
        self._run_task(self.client.set_power(device.id, not device.power_on), refresh_after=True)

    def _change_temp(self, device: AcDevice, delta: int):
        self._run_task(self.client.set_temperature(device.id, device.target_temperature + delta), refresh_after=True)

    def _set_mode(self, device: AcDevice, mode: str):
        self._run_task(self.client.set_mode(device.id, mode), refresh_after=True)

    def _set_fan(self, device: AcDevice, fan: str):
        self._run_task(self.client.set_fan(device.id, fan), refresh_after=True)

    def _run_task(self, coro, refresh_after: bool = False):
        if self.busy.get():
            self.log("当前任务还在执行，请稍等")
            return
        self.busy.set(True)
        self.status_var.set("执行中 ...")

        async def wrapped():
            result = await coro
            if refresh_after:
                result = await self.client.refresh_devices()
            return result

        future = asyncio.run_coroutine_threadsafe(wrapped(), self.async_loop)

        def done(done_future):
            try:
                self.worker_queue.put(("ok", done_future.result()))
            except Exception as exc:
                self.worker_queue.put(("error", exc))

        future.add_done_callback(done)

    def _drain_worker_queue(self):
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "error":
                    self.busy.set(False)
                    self.status_var.set("执行失败")
                    self.log(f"错误: {payload}")
                    messagebox.showerror("执行失败", str(payload))
                else:
                    self.busy.set(False)
                    if isinstance(payload, list):
                        self.devices = payload
                    self.status_var.set(f"就绪，空调设备 {len(self.devices)} 台")
                    self._render_devices()
        except queue.Empty:
            pass
        self.root.after(100, self._drain_worker_queue)

    def log(self, message: str):
        if threading.get_ident() != self.main_thread_id:
            self.worker_queue.put(("log", message))
            return
        self._append_log(message)

    def _append_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def on_close(self):
        try:
            future = asyncio.run_coroutine_threadsafe(self.client.close(), self.async_loop)
            future.result(timeout=5)
        except Exception:
            pass
        self.async_loop.call_soon_threadsafe(self.async_loop.stop)
        self.root.destroy()


def main():
    root = Tk()
    MideaAcApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
