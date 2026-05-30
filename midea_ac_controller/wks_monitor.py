from __future__ import annotations

import json
import platform
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable


DEFAULT_INTERVAL_SECONDS = 3.0
DEFAULT_TIMEOUT_MS = 800


class WksMonitor:
    def __init__(self, data_dir: Path, log: Callable[[str], None] | None = None):
        self.data_dir = data_dir
        self.config_file = data_dir / "wks_hosts.json"
        self.log = log or (lambda message: None)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=12, thread_name_prefix="wks-ping")
        self._groups: dict[str, list[dict[str, Any]]] = {}
        self._settings = {
            "interval_seconds": DEFAULT_INTERVAL_SECONDS,
            "timeout_ms": DEFAULT_TIMEOUT_MS,
        }
        self._last_error = ""
        self._ensure_config_file()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "config_path": str(self.config_file),
                "settings": dict(self._settings),
                "groups": {name: [dict(item) for item in hosts] for name, hosts in self._groups.items()},
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._refresh_once()
            except Exception as exc:
                self._log_error_once(f"WKS 在线状态刷新失败：{exc}")
            interval = float(self._settings.get("interval_seconds") or DEFAULT_INTERVAL_SECONDS)
            self._stop.wait(max(1.0, interval))

    def _ensure_config_file(self) -> None:
        if self.config_file.exists():
            return
        payload = {
            "_interval": int(DEFAULT_INTERVAL_SECONDS),
            "_timeout": DEFAULT_TIMEOUT_MS,
        }
        self.config_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_config(self) -> dict[str, Any] | None:
        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log_error_once(f"WKS 配置读取失败：{exc}")
            return None
        if not isinstance(raw, dict):
            self._log_error_once("WKS 配置格式不正确：根节点必须是对象")
            return None
        return raw

    def _refresh_once(self) -> None:
        config = self._load_config()
        if config is None:
            with self._lock:
                self._groups = {}
            return
        interval_seconds = float(config.pop("_interval", DEFAULT_INTERVAL_SECONDS) or DEFAULT_INTERVAL_SECONDS)
        timeout_ms = int(config.pop("_timeout", DEFAULT_TIMEOUT_MS) or DEFAULT_TIMEOUT_MS)
        groups: dict[str, list[dict[str, Any]]] = {}
        for group_name, hosts in config.items():
            if not isinstance(group_name, str) or not group_name or group_name.startswith("_"):
                continue
            normalized_hosts = self._normalize_hosts(hosts)
            if not normalized_hosts:
                continue
            groups[group_name] = self._refresh_group(normalized_hosts, timeout_ms)
        with self._lock:
            self._groups = groups
            self._settings = {
                "interval_seconds": interval_seconds,
                "timeout_ms": timeout_ms,
            }
        self._last_error = ""

    def _normalize_hosts(self, hosts: Any) -> list[dict[str, str]]:
        if not isinstance(hosts, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in hosts:
            if isinstance(item, str):
                ip = item.strip()
                label = self._label_from_ip(ip)
            elif isinstance(item, dict):
                ip = str(item.get("ip") or "").strip()
                label = str(item.get("label") or "").strip() or self._label_from_ip(ip)
            else:
                continue
            if not ip:
                continue
            normalized.append({"ip": ip, "label": label})
        return normalized

    def _refresh_group(self, hosts: list[dict[str, str]], timeout_ms: int) -> list[dict[str, Any]]:
        futures = [self._executor.submit(self._ping_host, host["ip"], timeout_ms) for host in hosts]
        results: list[dict[str, Any]] = []
        for host, future in zip(hosts, futures):
            online = False
            try:
                online = bool(future.result(timeout=max(1.0, timeout_ms / 1000 + 1.5)))
            except Exception:
                online = False
            results.append(
                {
                    "label": host["label"],
                    "ip": host["ip"],
                    "online": online,
                }
            )
        return results

    def _ping_host(self, ip: str, timeout_ms: int) -> bool:
        if not ip:
            return False
        system = platform.system().lower()
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
            timeout = max(1.5, timeout_ms / 1000 + 1.0)
        else:
            cmd = ["ping", "-c", "1", ip]
            timeout = max(1.5, timeout_ms / 1000 + 1.5)
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
            return completed.returncode == 0
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return False

    def _label_from_ip(self, ip: str) -> str:
        tail = ip.rsplit(".", 1)[-1] if "." in ip else ip
        return tail or ip

    def _log_error_once(self, message: str) -> None:
        if message == self._last_error:
            return
        self._last_error = message
        self.log(message)
