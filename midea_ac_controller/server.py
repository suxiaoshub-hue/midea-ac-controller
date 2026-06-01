from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .midea_client import SERVER_MEIJU, MideaAcClient
from .wks_monitor import WksMonitor, normalize_wks_group_name
from .client_page import build_client_page


APP_DIR = Path.home() / ".midea_ac_controller"
CONFIG_FILE = APP_DIR / "config.json"
AUTO_POWER_FILE = APP_DIR / "auto_power.json"
CLIENT_SUBNET = ipaddress.ip_network("192.168.88.0/24")
CLIENT_MIN_TEMPERATURE = 23
CLIENT_MAX_TEMPERATURE = 28
AUTO_POWER_DEFAULT_DELAY_MINUTES = 10
AUTO_POWER_CHECK_INTERVAL_SECONDS = 5
ROOM_RANGE_RE = re.compile(r"[（(]\s*(\d+)(?:\s*[-~－—–至]\s*(\d+))?\s*[)）]")
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class ApiState:
    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.logs: list[str] = []
        self.client = MideaAcClient(APP_DIR, self.log)
        self.auto_login_attempted = False
        self.wks = WksMonitor(APP_DIR, self.log)
        self.control_lock = threading.Lock()
        self.auto_power_lock = threading.Lock()
        self.auto_power_stop = threading.Event()
        self.auto_power_offline_since: dict[str, float] = {}
        self.auto_power_last_error = ""
        self.auto_power_last_refresh = 0.0
        self.auto_power_thread = threading.Thread(target=self._run_auto_power_loop, daemon=True)
        self.auto_power_thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def log(self, message: str):
        self.logs.append(message)
        self.logs[:] = self.logs[-50:]
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

    def load_auto_power_config(self) -> dict[str, Any]:
        if not AUTO_POWER_FILE.exists():
            config = self._normalize_auto_power_config({})
            AUTO_POWER_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            return config
        try:
            raw = json.loads(AUTO_POWER_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            raw = {}
        return self._normalize_auto_power_config(raw if isinstance(raw, dict) else {})

    def save_auto_power_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load_auto_power_config()
        device_id = str(payload.get("device_id") or "").strip()
        if device_id:
            room_config = self._normalize_auto_power_room_config(payload, current.get("default") or self._default_auto_power_room_config())
            current.setdefault("rooms", {})[device_id] = room_config
            device = self.client.devices.get(device_id)
            room_label = device.name if device else device_id
            self.log(
                f"自动开关空调：{room_label} 已切换为{'自动' if room_config['mode'] == 'auto' else '手动'}模式，"
                f"离线关机缓冲 {room_config['offline_delay_minutes']} 分钟"
            )
            if room_config["mode"] == "manual":
                with self.auto_power_lock:
                    self.auto_power_offline_since.pop(device_id, None)
        else:
            default_config = self._normalize_auto_power_room_config(payload, current.get("default") or self._default_auto_power_room_config())
            current["default"] = default_config
            self.log(
                f"自动开关空调：默认策略已切换为{'自动' if default_config['mode'] == 'auto' else '手动'}模式，"
                f"离线关机缓冲 {default_config['offline_delay_minutes']} 分钟"
            )
            if default_config["mode"] == "manual":
                with self.auto_power_lock:
                    self.auto_power_offline_since.clear()
        normalized = self._normalize_auto_power_config(current)
        AUTO_POWER_FILE.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        return normalized

    def _default_auto_power_room_config(self) -> dict[str, Any]:
        return {
            "mode": "manual",
            "offline_delay_minutes": AUTO_POWER_DEFAULT_DELAY_MINUTES,
        }

    def _normalize_auto_power_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        default_config = self._default_auto_power_room_config()
        rooms: dict[str, dict[str, Any]] = {}
        raw_default = payload.get("default") if isinstance(payload.get("default"), dict) else None
        if raw_default:
            default_config = self._normalize_auto_power_room_config(raw_default, default_config)
        elif "mode" in payload or "offline_delay_minutes" in payload:
            default_config = self._normalize_auto_power_room_config(payload, default_config)
        raw_rooms = payload.get("rooms") if isinstance(payload.get("rooms"), dict) else {}
        for device_id, room_payload in raw_rooms.items():
            if not isinstance(room_payload, dict):
                continue
            rooms[str(device_id)] = self._normalize_auto_power_room_config(room_payload, default_config)
        return {
            "default": default_config,
            "rooms": rooms,
            "check_interval_seconds": AUTO_POWER_CHECK_INTERVAL_SECONDS,
        }

    def _normalize_auto_power_room_config(
        self,
        payload: dict[str, Any],
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fallback = fallback or self._default_auto_power_room_config()
        mode = str(payload.get("mode", fallback.get("mode") or "manual")).strip().lower()
        if mode not in {"manual", "auto"}:
            mode = str(fallback.get("mode") or "manual")
        try:
            offline_delay_minutes = int(
                round(float(payload.get("offline_delay_minutes", fallback.get("offline_delay_minutes", AUTO_POWER_DEFAULT_DELAY_MINUTES))))
            )
        except (TypeError, ValueError):
            offline_delay_minutes = int(fallback.get("offline_delay_minutes", AUTO_POWER_DEFAULT_DELAY_MINUTES))
        offline_delay_minutes = max(1, min(180, offline_delay_minutes))
        return {
            "mode": mode,
            "offline_delay_minutes": offline_delay_minutes,
        }

    def ensure_logged_in_from_config(self) -> None:
        if self.client.cloud is not None or self.auto_login_attempted:
            return
        self.auto_login_attempted = True
        config = self.load_config()
        account = config.get("account") or ""
        password = config.get("password") or ""
        if not account or not password:
            return
        server = config.get("server") or SERVER_MEIJU
        proxy = config.get("proxy") or ""
        self.log("正在使用已保存账号自动登录 ...")
        ok = self.run(self.client.login(server, account, password, proxy))
        if not ok:
            self.log("自动登录失败，请重新登录账号")
            return
        self.run(self.client.load_devices())

    def auto_power_snapshot(self) -> dict[str, Any]:
        config = self.load_auto_power_config()
        now = time.monotonic()
        rooms: dict[str, dict[str, Any]] = {}
        wks_groups = self._normalized_wks_groups()
        with self.auto_power_lock:
            offline_since = dict(self.auto_power_offline_since)
        for device in self.client.device_list():
            hosts = wks_groups.get(normalize_wks_group_name(device.name), [])
            online_count = sum(1 for host in hosts if host.get("online"))
            since = offline_since.get(device.id)
            offline_seconds = max(0, int(now - since)) if since is not None else 0
            room_config = self._auto_power_room_config(config, device.id)
            rooms[device.id] = {
                "mode": room_config["mode"],
                "offline_delay_minutes": room_config["offline_delay_minutes"],
                "host_count": len(hosts),
                "online_count": online_count,
                "offline_seconds": offline_seconds,
                "offline_delay_seconds": room_config["offline_delay_minutes"] * 60,
            }
        return {
            "default": config["default"],
            "rooms": rooms,
            "config_path": str(AUTO_POWER_FILE),
        }

    def _auto_power_room_config(self, config: dict[str, Any], device_id: str) -> dict[str, Any]:
        default_config = config.get("default") or self._default_auto_power_room_config()
        rooms = config.get("rooms") if isinstance(config.get("rooms"), dict) else {}
        room = rooms.get(device_id)
        if isinstance(room, dict):
            return self._normalize_auto_power_room_config(room, default_config)
        return self._normalize_auto_power_room_config(default_config, default_config)

    def _run_auto_power_loop(self) -> None:
        while not self.auto_power_stop.is_set():
            try:
                self._auto_power_tick()
                self.auto_power_last_error = ""
            except Exception as exc:
                self._log_auto_power_error_once(f"自动开关空调检查失败：{exc}")
            self.auto_power_stop.wait(AUTO_POWER_CHECK_INTERVAL_SECONDS)

    def _auto_power_tick(self) -> None:
        config = self.load_auto_power_config()
        self.ensure_logged_in_from_config()
        if self.client.cloud is None or not self.client.devices:
            return
        now = time.monotonic()
        if now - self.auto_power_last_refresh >= 30:
            with self.control_lock:
                self.run(self.client.refresh_devices(log_refresh=False))
            self.auto_power_last_refresh = now
        wks_groups = self._normalized_wks_groups()
        for device in self.client.device_list():
            room_config = self._auto_power_room_config(config, device.id)
            if room_config["mode"] != "auto":
                with self.auto_power_lock:
                    self.auto_power_offline_since.pop(device.id, None)
                continue
            hosts = wks_groups.get(normalize_wks_group_name(device.name), [])
            if not hosts or not device.online:
                with self.auto_power_lock:
                    self.auto_power_offline_since.pop(device.id, None)
                continue
            online_count = sum(1 for host in hosts if host.get("online"))
            if online_count > 0:
                with self.auto_power_lock:
                    self.auto_power_offline_since.pop(device.id, None)
                if not self.client.devices[device.id].power_on:
                    with self.control_lock:
                        self.run(self.client.set_power(device.id, True))
                    self.log(f"自动开关空调：{device.name} 检测到客户机在线，自动开机")
                continue
            with self.auto_power_lock:
                offline_since = self.auto_power_offline_since.setdefault(device.id, now)
            offline_delay_seconds = room_config["offline_delay_minutes"] * 60
            if now - offline_since < offline_delay_seconds:
                continue
            if self.client.devices[device.id].power_on:
                with self.control_lock:
                    self.run(self.client.set_power(device.id, False))
                self.log(f"自动开关空调：{device.name} 客户机离线超过 {room_config['offline_delay_minutes']} 分钟，自动关机")

    def _normalized_wks_groups(self) -> dict[str, list[dict[str, Any]]]:
        wks_snapshot = self.wks.snapshot()
        groups = wks_snapshot.get("groups") or {}
        return {normalize_wks_group_name(name): hosts for name, hosts in groups.items() if isinstance(hosts, list)}

    def _log_auto_power_error_once(self, message: str) -> None:
        if message == self.auto_power_last_error:
            return
        self.auto_power_last_error = message
        self.log(message)

    def close(self):
        self.auto_power_stop.set()
        self.auto_power_thread.join(timeout=2)
        try:
            self.run(self.client.close())
        except Exception:
            pass
        try:
            self.wks.close()
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


STATE = ApiState()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "MideaAcController/1.0"

    def do_OPTIONS(self):
        path = urlparse(self.path).path
        self._send_empty(cors=not path.startswith("/api/client"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                self._send_json({"ok": True})
            elif path in {"/client", "/client/"}:
                self._send_text(build_client_page(), content_type="text/html; charset=utf-8", cors=False)
            elif path == "/api/config":
                self._require_local_access(path)
                self._send_json(STATE.load_config())
            elif path == "/api/wks":
                self._require_local_access(path)
                self._send_json(STATE.wks.snapshot())
            elif path == "/api/auto-power":
                self._require_local_access(path)
                self._send_json(STATE.auto_power_snapshot())
            elif path == "/api/state":
                self._require_local_access(path)
                STATE.ensure_logged_in_from_config()
                include_logs = "logs=0" not in parsed.query
                self._send_json(self._snapshot(include_logs=include_logs))
            elif path == "/api/devices":
                self._require_local_access(path)
                self._send_json({"devices": [d.to_dict() for d in STATE.client.devices.values()]})
            elif path == "/api/client/state":
                self._send_json(self._client_state(parsed), cors=False)
            else:
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error(exc)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self._read_json()
            if path == "/api/login":
                self._require_local_access(path)
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
                self._send_json({"ok": True, "devices": [d.to_dict() for d in STATE.client.device_list()], "state": self._snapshot()})
            elif path == "/api/refresh":
                self._require_local_access(path)
                STATE.ensure_logged_in_from_config()
                quiet = bool(payload.get("quiet"))
                devices = STATE.run(STATE.client.refresh_devices(log_refresh=not quiet))
                self._send_json({"ok": True, "devices": [d.to_dict() for d in devices], "state": self._snapshot(include_logs=not quiet)})
            elif path == "/api/auto-power":
                self._require_local_access(path)
                STATE.save_auto_power_config(payload)
                self._send_json({"ok": True, "automation": STATE.auto_power_snapshot()})
            elif path == "/api/control":
                self._require_local_access(path)
                device_id = payload.get("device_id")
                action = payload.get("action")
                value = payload.get("value")
                if not device_id:
                    raise ValueError("缺少设备 ID")
                with STATE.control_lock:
                    if action == "power":
                        if isinstance(value, dict):
                            STATE.run(STATE.client.set_power(device_id, bool(value.get("on"))))
                        else:
                            STATE.run(STATE.client.set_power(device_id, bool(value)))
                    elif action == "temperature":
                        STATE.run(STATE.client.set_temperature(device_id, float(value)))
                    elif action == "mode":
                        STATE.run(STATE.client.set_mode(device_id, str(value)))
                    elif action == "fan":
                        STATE.run(STATE.client.set_fan(device_id, str(value)))
                    else:
                        raise ValueError(f"未知控制动作: {action}")
                devices = STATE.client.device_list()
                self._send_json({"ok": True, "devices": [d.to_dict() for d in devices], "state": self._snapshot()})
            elif path == "/api/client/control":
                self._require_client_origin()
                self._send_json(self._client_control(payload, parsed), cors=False)
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

    def _send_empty(self, cors: bool = True):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_headers(cors=cors)
        self.end_headers()

    def _send_json(self, data: dict[str, Any], status: int = HTTPStatus.OK, cors: bool = True):
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_headers(cors=cors)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error(self, exc: Exception):
        logging.exception("API error")
        status = HTTPStatus.FORBIDDEN if isinstance(exc, PermissionError) else HTTPStatus.BAD_REQUEST
        self._send_json({"ok": False, "error": str(exc)}, status, cors=not self._is_client_path())

    def _send_headers(self, cors: bool = True):
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_text(self, text: str, status: int = HTTPStatus.OK, content_type: str = "text/plain; charset=utf-8", cors: bool = True):
        encoded = text.encode("utf-8")
        self.send_response(status)
        self._send_headers(cors=cors)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _is_client_path(self) -> bool:
        path = urlparse(self.path).path
        return path in {"/client", "/client/"} or path.startswith("/api/client")

    def _require_local_access(self, path: str) -> None:
        if self._is_local_request():
            return
        raise PermissionError(f"{path} 仅允许本机访问")

    def _require_client_origin(self) -> None:
        origin = self.headers.get("Origin") or ""
        host = self.headers.get("Host") or ""
        if not origin:
            raise PermissionError("客户机接口需要同源访问")
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != host:
            raise PermissionError("客户机接口仅允许同源访问")

    def _is_local_request(self) -> bool:
        host = self.client_address[0]
        if host in LOCAL_HOSTS:
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return ip.is_loopback

    def _client_request_ip(self, parsed) -> str:
        query = parse_qs(parsed.query or "")
        override = query.get("ip", [""])[0].strip()
        if override and self._is_local_request():
            return override
        return self.client_address[0]

    def _room_range_from_name(self, name: str) -> tuple[int, int] | None:
        match = ROOM_RANGE_RE.search(str(name or ""))
        if not match:
            return None
        start = int(match.group(1))
        end = int(match.group(2) or match.group(1))
        if end < start:
            start, end = end, start
        return start, end

    def _device_for_client(self, client_ip: str):
        try:
            ip = ipaddress.ip_address(client_ip)
        except ValueError:
            return None
        if not isinstance(ip, ipaddress.IPv4Address):
            return None
        if ip not in CLIENT_SUBNET:
            return None
        last_octet = int(str(ip).rsplit(".", 1)[-1])
        for device in STATE.client.device_list():
            room_range = self._room_range_from_name(device.name)
            if room_range and room_range[0] <= last_octet <= room_range[1]:
                return device
        return None

    def _client_snapshot(self, device) -> dict[str, Any]:
        if device is None:
            return {
                "ok": False,
                "authorized": False,
                "error": "当前电脑未绑定包厢或不在允许网段",
                "policy": {
                    "min_temperature": CLIENT_MIN_TEMPERATURE,
                    "max_temperature": CLIENT_MAX_TEMPERATURE,
                },
            }
        room = {
            "device_id": device.id,
            "name": device.name,
            "online": device.online,
            "power_on": device.power_on,
            "current_mode": device.current_mode,
            "fan_speed": device.fan_speed,
            "target_temperature": round(device.target_temperature),
            "current_temperature": device.current_temperature,
        }
        return {
            "ok": True,
            "authorized": True,
            "policy": {
                "min_temperature": CLIENT_MIN_TEMPERATURE,
                "max_temperature": CLIENT_MAX_TEMPERATURE,
            },
            "room": room,
        }

    def _client_payload(self, device, ip: str, message: str | None = None) -> dict[str, Any]:
        payload = self._client_snapshot(device)
        payload["client_ip"] = ip
        payload["logged_in"] = STATE.client.cloud is not None
        payload["device_count"] = len(STATE.client.devices)
        payload["logs"] = STATE.logs[-5:]
        if message:
            payload["message"] = message
        return payload

    def _client_state(self, parsed) -> dict[str, Any]:
        STATE.ensure_logged_in_from_config()
        client_ip = self._client_request_ip(parsed)
        device = self._device_for_client(client_ip)
        return self._client_payload(device, client_ip)

    def _client_control(self, payload: dict[str, Any], parsed) -> dict[str, Any]:
        STATE.ensure_logged_in_from_config()
        client_ip = self._client_request_ip(parsed)
        device = self._device_for_client(client_ip)
        if device is None:
            raise PermissionError("当前电脑无权控制空调")
        requested_device_id = str(payload.get("device_id") or "").strip()
        if requested_device_id and requested_device_id != device.id:
            raise PermissionError("不能控制其他包厢的空调")
        action = str(payload.get("action") or "").strip()
        value = payload.get("value")
        if action == "temperature":
            temperature = int(round(float(value)))
            if temperature < CLIENT_MIN_TEMPERATURE or temperature > CLIENT_MAX_TEMPERATURE:
                raise ValueError(f"温度只能设置 {CLIENT_MIN_TEMPERATURE}-{CLIENT_MAX_TEMPERATURE} 度")
            with STATE.control_lock:
                STATE.run(STATE.client.set_temperature(device.id, temperature))
        elif action == "power":
            with STATE.control_lock:
                if isinstance(value, dict):
                    STATE.run(STATE.client.set_power(device.id, bool(value.get("on"))))
                else:
                    STATE.run(STATE.client.set_power(device.id, bool(value)))
        elif action == "mode":
            mode = str(value)
            if mode not in {"cool", "heat", "auto", "dry", "fan", "off"}:
                raise ValueError("不支持的模式")
            with STATE.control_lock:
                STATE.run(STATE.client.set_mode(device.id, mode))
        elif action == "fan":
            fan = str(value)
            if fan not in {"auto", "low", "medium", "high", "silent", "full"}:
                raise ValueError("不支持的风速")
            with STATE.control_lock:
                STATE.run(STATE.client.set_fan(device.id, fan))
        else:
            raise ValueError(f"未知控制动作: {action}")
        STATE.run(STATE.client.refresh_devices(log_refresh=False))
        return {"ok": True, **self._client_payload(device, client_ip, "控制已下发")}

    def _snapshot(self, include_logs: bool = True):
        data = STATE.client.snapshot()
        wks_snapshot = STATE.wks.snapshot()
        wks_groups = wks_snapshot.get("groups") or {}
        normalized_wks_groups = {normalize_wks_group_name(name): hosts for name, hosts in wks_groups.items()}
        for device in data.get("devices") or []:
            device["wks_hosts"] = normalized_wks_groups.get(normalize_wks_group_name(device.get("name")), [])
            device["wks_online_count"] = sum(1 for host in device["wks_hosts"] if host.get("online"))
            device["wks_host_count"] = len(device["wks_hosts"])
        data["wks"] = wks_snapshot
        data["automation"] = STATE.auto_power_snapshot()
        if include_logs:
            data["logs"] = STATE.logs[-5:]
        return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
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
