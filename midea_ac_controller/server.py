from __future__ import annotations

import argparse
import asyncio
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .midea_client import SERVER_MEIJU, MideaAcClient


APP_DIR = Path.home() / ".midea_ac_controller"
CONFIG_FILE = APP_DIR / "config.json"


class ApiState:
    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.logs: list[str] = []
        self.client = MideaAcClient(APP_DIR, self.log)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def log(self, message: str):
        self.logs.append(message)
        self.logs[:] = self.logs[-300:]
        logging.info(message)

    def run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=90)

    def load_config(self) -> dict[str, Any]:
        if not CONFIG_FILE.exists():
            return {"server": SERVER_MEIJU, "account": "", "password": "", "proxy": ""}
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"server": SERVER_MEIJU, "account": "", "password": "", "proxy": ""}

    def save_config(self, payload: dict[str, Any]) -> None:
        data = {
            "server": payload.get("server") or SERVER_MEIJU,
            "account": payload.get("account") or "",
            "password": payload.get("password") or "",
            "proxy": payload.get("proxy") or "",
        }
        CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self):
        try:
            self.run(self.client.close())
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


STATE = ApiState()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "MideaAcController/1.0"

    def do_OPTIONS(self):
        self._send_empty()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                self._send_json({"ok": True})
            elif path == "/api/config":
                self._send_json(STATE.load_config())
            elif path == "/api/state":
                include_logs = "logs=0" not in parsed.query
                self._send_json(self._snapshot(include_logs=include_logs))
            elif path == "/api/devices":
                self._send_json({"devices": [d.to_dict() for d in STATE.client.devices.values()]})
            else:
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error(exc)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/login":
                server = payload.get("server") or SERVER_MEIJU
                account = payload.get("account") or ""
                password = payload.get("password") or ""
                proxy = payload.get("proxy") or ""
                if not account or not password:
                    raise ValueError("请输入账号和密码")
                STATE.save_config(payload)
                ok = STATE.run(STATE.client.login(server, account, password, proxy))
                if not ok:
                    raise RuntimeError("登录失败，请检查账号、密码、服务器和网络")
                devices = STATE.run(STATE.client.load_devices())
                self._send_json({"ok": True, "devices": [d.to_dict() for d in devices], "state": self._snapshot()})
            elif path == "/api/refresh":
                quiet = bool(payload.get("quiet"))
                devices = STATE.run(STATE.client.refresh_devices(log_refresh=not quiet))
                self._send_json({"ok": True, "devices": [d.to_dict() for d in devices], "state": self._snapshot(include_logs=not quiet)})
            elif path == "/api/control":
                device_id = payload.get("device_id")
                action = payload.get("action")
                value = payload.get("value")
                if not device_id:
                    raise ValueError("缺少设备 ID")
                if action == "power":
                    STATE.run(STATE.client.set_power(device_id, bool(value)))
                elif action == "temperature":
                    STATE.run(STATE.client.set_temperature(device_id, float(value)))
                elif action == "mode":
                    STATE.run(STATE.client.set_mode(device_id, str(value)))
                elif action == "fan":
                    STATE.run(STATE.client.set_fan(device_id, str(value)))
                else:
                    raise ValueError(f"未知控制动作: {action}")
                devices = list(STATE.client.devices.values())
                self._send_json({"ok": True, "devices": [d.to_dict() for d in devices], "state": self._snapshot()})
            else:
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error(exc)

    def log_message(self, fmt, *args):
        logging.debug(fmt, *args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def _send_empty(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_headers()
        self.end_headers()

    def _send_json(self, data: dict[str, Any], status: int = HTTPStatus.OK):
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error(self, exc: Exception):
        logging.exception("API error")
        self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _send_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _snapshot(self, include_logs: bool = True):
        data = STATE.client.snapshot()
        if include_logs:
            data["logs"] = STATE.logs[-80:]
        return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18765, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    httpd = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    logging.info("Midea AC API listening on http://%s:%s", args.host, args.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STATE.close()
        httpd.server_close()


if __name__ == "__main__":
    main()
