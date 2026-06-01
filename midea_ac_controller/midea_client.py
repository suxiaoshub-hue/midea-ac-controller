from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aiohttp import ClientSession

from .vendor.midea_core.cloud import MSmartHomeCloud, MeijuCloud, get_midea_cloud


AIR_CONDITIONER_TYPES = {0xAC, 0xCC, 0x21}
SERVER_MEIJU = "美的美居"
SERVER_MSMART = "MSmartHome"


def _truthy_on(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "on", "true", "yes", "2", "3", "4", "5"}


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_temperature(value: Any) -> float | None:
    temperature = _as_float(value, None)
    if temperature is None:
        return None
    if 10.0 <= temperature <= 40.0:
        return temperature
    return None


def _first_temperature(attrs: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        temperature = _as_temperature(attrs.get(key))
        if temperature is not None:
            return temperature
    return None


def _normalize_set_temperature(value: Any) -> int:
    return int(max(17, min(30, round(float(value)))))


def _control_status(attrs: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attrs.items() if not str(key).startswith("_")}


def _nest_dot_keys(values: dict[str, Any]) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    for key, value in values.items():
        if "." not in key:
            nested[key] = value
            continue
        current = nested
        parts = key.split(".")
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        current[parts[-1]] = value
    return nested


def _first_present(attrs: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = attrs.get(key)
        if value is not None and value != "":
            return value
    return None


@dataclass
class AcDevice:
    id: str
    name: str
    appliance_code: int
    device_type: int
    online: bool
    server: str
    sn: str = ""
    subtype: int | None = None
    model_number: str | None = None
    manufacturer_code: str = "0000"
    smart_product_id: str | None = None
    parent_appliance_code: int | None = None
    master_id: str | None = None
    nodeid: str | None = None
    modelid: str | None = None
    idtype: int | None = None
    preferred_mode: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def is_central_node(self) -> bool:
        return self.parent_appliance_code is not None and self.nodeid is not None

    @property
    def power_on(self) -> bool:
        if self.device_type == 0x21 or self.is_central_node:
            return str(self.attrs.get("run_mode", "0")) != "0"
        for key in ("power", "power.current", "power_on", "power.status"):
            if key in self.attrs:
                return _truthy_on(self.attrs.get(key))
        return False

    @property
    def target_temperature(self) -> float:
        local_target = _as_temperature(self.attrs.get("_local_target_temperature"))
        if self.device_type == 0x21 or self.is_central_node:
            mode = str(self.attrs.get("run_mode", "2"))
            mode_keys = ("heat_temp_set", "heating_temp") if mode == "3" else ("cool_temp_set", "cooling_temp")
            explicit = _first_temperature(self.attrs, (*mode_keys, "target_temperature", "temperature.set", "set_temperature", "temp_set"))
            return explicit or local_target or 26.0

        mode = str(_first_present(self.attrs, ("mode_current", "mode.current", "mode")) or "cool")
        mode_keys = ("heat_temp_set", "heating_temp") if mode == "heat" else ("cool_temp_set", "cooling_temp")
        explicit = _first_temperature(
            self.attrs,
            (
                *mode_keys,
                "target_temperature",
                "temperature.target",
                "temperature.set",
                "temperature.current",
                "temperature_setting",
                "temperature_current",
                "set_temperature",
                "temp_set",
                "target_temp",
                "set_temp",
            ),
        )
        if explicit is not None:
            return explicit
        if local_target is not None:
            return local_target
        return _as_temperature(self.attrs.get("temperature")) or 26.0

    @property
    def current_temperature(self) -> float | None:
        for key in ("indoor_temperature", "temperature.room", "room_temp"):
            value = _as_float(self.attrs.get(key), None)
            if value is not None:
                return value
        return None

    @property
    def current_mode(self) -> str:
        if self.device_type == 0x21 or self.is_central_node:
            run_modes = {"0": "off", "1": "fan", "2": "cool", "3": "heat", "4": "auto", "5": "dry"}
            if not self.power_on:
                return "off"
            mode = self.attrs.get("run_mode", "2")
            resolved = run_modes.get(str(mode), str(mode))
            return resolved if resolved != "off" else "off"
        if not self.power_on:
            return "off"
        mode = _first_present(self.attrs, ("mode_current", "mode.current", "mode"))
        if isinstance(mode, str) and mode and mode != "off":
            return mode
        return "off"

    @property
    def fan_speed(self) -> str:
        if self.device_type == 0x21 or self.is_central_node:
            fan_modes = {"0": "off", "1": "low", "3": "medium", "5": "high", "8": "auto"}
            return fan_modes.get(str(self.attrs.get("fan_speed", "8")), str(self.attrs.get("fan_speed", "8")))
        fan = _first_present(self.attrs, ("wind_speed_level", "wind_speed.level", "wind_speed"))
        if isinstance(fan, str) and fan in {"auto", "silent", "low", "medium", "high", "full"}:
            return fan
        reverse = {20: "silent", 40: "low", 60: "medium", 80: "high", 100: "full", 102: "auto"}
        level_reverse = {1: "low", 2: "low", 3: "medium", 4: "medium", 5: "high", 6: "auto", 8: "auto"}
        if isinstance(fan, str):
            try:
                fan = int(float(fan))
            except (TypeError, ValueError):
                return fan
        if fan is None:
            return "auto"
        fan_int = int(fan)
        if "wind_speed.level" in self.attrs or "wind_speed_level" in self.attrs:
            return level_reverse.get(fan_int, reverse.get(fan_int, "auto"))
        return reverse.get(fan_int, level_reverse.get(fan_int, "auto"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "appliance_code": self.appliance_code,
            "device_type": self.device_type,
            "online": self.online,
            "server": self.server,
            "sn": self.sn,
            "subtype": self.subtype,
            "model_number": self.model_number,
            "manufacturer_code": self.manufacturer_code,
            "smart_product_id": self.smart_product_id,
            "parent_appliance_code": self.parent_appliance_code,
            "master_id": self.master_id,
            "nodeid": self.nodeid,
            "modelid": self.modelid,
            "idtype": self.idtype,
            "preferred_mode": self.preferred_mode,
            "preferred_temperature": self.attrs.get("_preferred_temperature"),
            "preferred_fan": self.attrs.get("_preferred_fan"),
            "power_on": self.power_on,
            "current_mode": self.current_mode,
            "fan_speed": self.fan_speed,
            "target_temperature": self.target_temperature,
            "current_temperature": self.current_temperature,
            "attrs": self.attrs,
        }


class MideaAcClient:
    def __init__(self, data_dir: Path, log: Callable[[str], None] | None = None):
        self.data_dir = data_dir
        self.device_prefs_file = data_dir / "device_prefs.json"
        self.log = log or (lambda message: None)
        self.session: ClientSession | None = None
        self.cloud: MeijuCloud | MSmartHomeCloud | None = None
        self.server = SERVER_MEIJU
        self.devices: dict[str, AcDevice] = {}
        self.device_prefs: dict[str, dict[str, Any]] = self._load_device_prefs()

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def login(self, server: str, account: str, password: str, proxy: str | None = None) -> bool:
        await self.close()
        self.server = server
        self.session = ClientSession()
        self.cloud = get_midea_cloud(server, self.session, account, password, proxy=proxy or None)
        if self.cloud is None:
            raise RuntimeError(f"不支持的服务器: {server}")
        self.log(f"正在登录 {server} ...")
        ok = await self.cloud.login()
        if not ok:
            await self.close()
            self.cloud = None
            return False
        self.log(f"登录成功: {self.cloud.nickname}")
        return True

    async def load_devices(self) -> list[AcDevice]:
        if self.cloud is None:
            raise RuntimeError("请先登录账号")
        homes = await self.cloud.list_home()
        all_devices: dict[str, AcDevice] = {}
        if homes:
            home_items = list(homes.items())
        else:
            home_items = [(None, "默认家庭")]
        for home_id, home_name in home_items:
            appliances = await self.cloud.list_appliances(home_id)
            if not appliances:
                continue
            for code, info in appliances.items():
                device_type = int(info.get("type") or 0)
                if device_type not in AIR_CONDITIONER_TYPES:
                    continue
                device = AcDevice(
                    id=str(code),
                    name=info.get("name") or f"空调 {code}",
                    appliance_code=int(code),
                    device_type=device_type,
                    online=bool(info.get("online")),
                    server=self.server,
                    sn=info.get("sn") or "",
                    subtype=_parse_optional_int(info.get("model_number")),
                    model_number=info.get("model_number"),
                    manufacturer_code=info.get("manufacturer_code") or "0000",
                    smart_product_id=info.get("smart_product_id"),
                    preferred_mode=self._preferred_mode(str(code)),
                )
                all_devices[device.id] = device
        self.devices = all_devices
        await self.refresh_devices(log_refresh=False)
        self.log(f"设备同步完成：找到 {len(self.devices)} 台空调")
        return sorted(self.devices.values(), key=_device_sort_key)

    async def refresh_devices(self, log_refresh: bool = True) -> list[AcDevice]:
        if self.cloud is None:
            raise RuntimeError("请先登录账号")
        if not self.devices:
            return []
        if log_refresh:
            self.log("手动刷新设备状态")
        base_devices = list(self.devices.values())
        central_gateways = [d for d in base_devices if d.device_type == 0x21 and not d.is_central_node]
        if central_gateways:
            await self._refresh_central_gateways(central_gateways)
        for device in list(self.devices.values()):
            if device.device_type == 0x21 or device.is_central_node:
                continue
            await self._refresh_regular_ac(device)
        return sorted(self.devices.values(), key=_device_sort_key)

    async def _refresh_regular_ac(self, device: AcDevice) -> None:
        if self.cloud is None:
            return
        status = None
        if isinstance(self.cloud, MSmartHomeCloud):
            status = await self.cloud.get_device_status(
                appliance_code=device.appliance_code,
                device_type=device.device_type,
                sn=device.sn,
                model_number=device.model_number,
                manufacturer_code=device.manufacturer_code,
                query={},
            )
        elif isinstance(self.cloud, MeijuCloud):
            status = await self.cloud.get_device_status(device.appliance_code, query={})
        if isinstance(status, dict):
            device.attrs = _flatten_status(status)
            device.online = True

    async def _refresh_central_gateways(self, gateways: list[AcDevice]) -> None:
        if self.cloud is None or not hasattr(self.cloud, "get_central_ac_status"):
            return
        status_data = await self.cloud.get_central_ac_status([d.appliance_code for d in gateways])
        if not isinstance(status_data, dict):
            return
        appliances = status_data.get("appliances") or []
        gateway_by_code = {str(d.appliance_code): d for d in gateways}
        for appliance in appliances:
            if appliance.get("type") != "0x21":
                continue
            code = str(appliance.get("id") or appliance.get("applianceCode") or "")
            gateway = gateway_by_code.get(code)
            if gateway is None:
                continue
            attr = ((appliance.get("extraData") or {}).get("attr") or {})
            gateway.attrs = _flatten_status(attr)
            gateway.master_id = str(attr.get("masterId") or gateway.appliance_code)
            gateway.nodeid = attr.get("nodeid") or gateway.nodeid
            gateway.modelid = attr.get("modelid") or gateway.modelid
            gateway.idtype = _parse_optional_int(attr.get("idType")) or gateway.idtype
            self._upsert_central_nodes(gateway, attr)

    def _upsert_central_nodes(self, gateway: AcDevice, attr: dict[str, Any]) -> None:
        endpoints = attr.get("endlist")
        if not isinstance(endpoints, list) or not endpoints:
            return
        for index, endpoint in enumerate(endpoints, start=1):
            event = endpoint.get("event") if isinstance(endpoint, dict) else None
            if not isinstance(event, dict):
                continue
            endpoint_id = endpoint.get("endpoint") or endpoint.get("id") or index
            nodeid = endpoint.get("nodeid") or event.get("nodeid") or attr.get("nodeid")
            device_id = f"{gateway.appliance_code}:{nodeid or endpoint_id}"
            node = self.devices.get(device_id)
            if node is None:
                node = AcDevice(
                    id=device_id,
                    name=endpoint.get("name") or f"{gateway.name}-{endpoint_id}",
                    appliance_code=gateway.appliance_code,
                    parent_appliance_code=gateway.appliance_code,
                    device_type=0x21,
                    online=gateway.online,
                    server=gateway.server,
                    master_id=gateway.master_id or str(gateway.appliance_code),
                    nodeid=str(nodeid or endpoint_id),
                    modelid=endpoint.get("modelid") or attr.get("modelid"),
                    idtype=_parse_optional_int(endpoint.get("idType") or attr.get("idType")),
                    preferred_mode=self._preferred_mode(device_id),
                )
                self.devices[device_id] = node
            node.attrs = _flatten_status(event)
            if isinstance(event.get("condition_attribute"), dict):
                node.attrs.update(_flatten_status(event["condition_attribute"]))

    async def set_power(self, device_id: str, on: bool) -> None:
        device = self.devices[device_id]
        if device.device_type == 0x21 or device.is_central_node:
            preferred_mode = self._active_preferred_mode(device)
            next_mode = self._central_run_mode(preferred_mode or "cool") if on else "0"
            await self._send_central_control(device, {"run_mode": next_mode})
            applied = await self._verify_power_applied(device_id, on)
            if not applied:
                actual = "开机" if self.devices[device_id].power_on else "关机"
                raise RuntimeError(f"{device.name}: 电源未生效，设备仍为{actual}")
            if on and preferred_mode:
                mode_applied = await self._verify_mode_applied(device_id, preferred_mode)
                if not mode_applied:
                    actual = self._reported_mode(self.devices[device_id]) or "未知"
                    raise RuntimeError(f"{device.name}: 恢复模式未生效，设备仍为 {_mode_label(actual)}")
        else:
            await self._send_regular_control(device, {"power": "on" if on else "off"})
            applied = await self._verify_power_applied(device_id, on)
            if not applied:
                actual = "开机" if self.devices[device_id].power_on else "关机"
                raise RuntimeError(f"{device.name}: 电源未生效，设备仍为{actual}")
            if on:
                preferred_mode = self._active_preferred_mode(device)
                if preferred_mode:
                    self.log(f"{device.name}: 恢复模式 {_mode_label(preferred_mode)}")
                    await asyncio.sleep(0.5)
                    await self.set_mode(device_id, preferred_mode)
        self.log(f"{device.name}: {'开机' if on else '关机'}")

    async def set_temperature(self, device_id: str, temperature: float) -> None:
        device = self.devices[device_id]
        temperature = _normalize_set_temperature(temperature)
        if device.device_type == 0x21 or device.is_central_node:
            mode = self._temperature_mode(device)
            control = {"cooling_temp": str(temperature)}
            if mode == "heat":
                control["heating_temp"] = str(temperature)
            await self._send_central_control(device, control)
            applied = await self._verify_temperature_applied(device_id, temperature, mode)
            if not applied:
                actual = format_temperature(self.devices[device_id].target_temperature)
                raise RuntimeError(f"{device.name}: 温度未生效，设备目标温度仍为 {actual}°")
            self._remember_preferred_temperature(self.devices[device_id], temperature)
            self.log(f"{device.name}: 设置温度 {temperature:g}°")
            return
        mode = self._temperature_mode(device)
        control = self._regular_temperature_control(device, temperature)
        await self._send_regular_control(device, control)
        applied = await self._verify_temperature_applied(device_id, temperature, mode)
        if not applied:
            actual = format_temperature(self.devices[device_id].target_temperature)
            raise RuntimeError(f"{device.name}: 温度未生效，设备目标温度仍为 {actual}°")
        self._remember_preferred_temperature(self.devices[device_id], temperature)
        self.log(f"{device.name}: 设置温度 {temperature:g}°")

    async def set_mode(self, device_id: str, mode: str) -> None:
        device = self.devices[device_id]
        if device.device_type == 0x21 or device.is_central_node:
            run_modes = {"off": "0", "fan": "1", "cool": "2", "heat": "3", "auto": "4", "dry": "5"}
            await self._send_central_control(device, {"run_mode": run_modes[mode]})
        else:
            await self._send_regular_control(device, {"power": "off"} if mode == "off" else self._regular_mode_control(device, mode))
        if mode == "off":
            applied = await self._verify_power_applied(device_id, False)
            if not applied:
                actual = "开机" if self.devices[device_id].power_on else "关机"
                raise RuntimeError(f"{device.name}: 关机未生效，设备仍为{actual}")
        else:
            applied = await self._verify_mode_applied(device_id, mode)
            if not applied:
                actual = self._reported_mode(self.devices[device_id]) or "未知"
                self.log(f"{device.name}: 模式未生效，设备仍为 {_mode_label(actual)}")
                raise RuntimeError(f"{device.name}: 模式未生效，设备仍为 {_mode_label(actual)}")
            self._remember_preferred_mode(device, mode)
        self.log(f"{device.name}: 设置模式 {_mode_label(mode)}")

    async def set_fan(self, device_id: str, fan: str) -> None:
        device = self.devices[device_id]
        if device.device_type == 0x21 or device.is_central_node:
            fan_modes = {"off": "0", "low": "1", "medium": "3", "high": "5", "auto": "8"}
            await self._send_central_control(device, {"fan_speed": fan_modes[fan]})
        else:
            await self._send_regular_control(device, self._regular_fan_control(device, fan))
        applied = await self._verify_fan_applied(device_id, fan)
        if not applied:
            actual = self.devices[device_id].fan_speed
            raise RuntimeError(f"{device.name}: 风速未生效，设备仍为 {_fan_label(actual)}")
        self._remember_preferred_fan(self.devices[device_id], fan)
        self.log(f"{device.name}: 设置风速 {_fan_label(fan)}")

    async def _send_regular_control(self, device: AcDevice, control: dict[str, Any]) -> None:
        if self.cloud is None:
            raise RuntimeError("请先登录账号")
        nested = _nest_dot_keys(control)
        ok = False
        if isinstance(self.cloud, MSmartHomeCloud):
            ok = await self.cloud.send_device_control(
                appliance_code=device.appliance_code,
                device_type=device.device_type,
                sn=device.sn,
                model_number=device.model_number,
                manufacturer_code=device.manufacturer_code,
                control=nested,
                status=_control_status(device.attrs),
            )
        elif isinstance(self.cloud, MeijuCloud):
            ok = await self.cloud.send_device_control(device.appliance_code, control=nested, status=_control_status(device.attrs))
        if not ok:
            raise RuntimeError(f"{device.name}: 控制失败")

    async def _send_central_control(self, device: AcDevice, control: dict[str, Any]) -> None:
        if self.cloud is None:
            raise RuntimeError("请先登录账号")
        master_id = device.master_id or str(device.appliance_code)
        nodeid = device.nodeid
        modelid = device.modelid or "0"
        idtype = device.idtype if device.idtype is not None else 0
        if not nodeid:
            raise RuntimeError(f"{device.name}: 缺少中央空调 nodeid，请先刷新设备")
        full_control = {
            "run_mode": str(device.attrs.get("run_mode", "2")),
            "cooling_temp": str(device.attrs.get("cool_temp_set") or device.attrs.get("cooling_temp") or 26),
            "heating_temp": str(device.attrs.get("heat_temp_set") or device.attrs.get("heating_temp") or 20),
            "fan_speed": str(device.attrs.get("fan_speed", "8")),
            "extflag": str(device.attrs.get("extflag", "0")),
        }
        full_control.update(control)
        ok = await self.cloud.send_central_ac_control(int(master_id), nodeid, modelid, int(idtype), full_control)
        if not ok:
            raise RuntimeError(f"{device.name}: 控制失败")

    def snapshot(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "logged_in": self.cloud is not None,
            "nickname": getattr(self.cloud, "nickname", None) if self.cloud else None,
            "device_count": len(self.devices),
            "devices": [device.to_dict() for device in self.device_list()],
        }

    def device_list(self) -> list[AcDevice]:
        return sorted(self.devices.values(), key=_device_sort_key)

    def _load_device_prefs(self) -> dict[str, dict[str, Any]]:
        if not self.device_prefs_file.exists():
            return {}
        try:
            raw = json.loads(self.device_prefs_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        prefs: dict[str, dict[str, Any]] = {}
        for device_id, payload in raw.items():
            preferred_mode: str | None = None
            if isinstance(payload, dict):
                preferred_mode = payload.get("preferred_mode")
            elif isinstance(payload, str):
                preferred_mode = payload
            if isinstance(preferred_mode, str) and preferred_mode and preferred_mode != "off":
                prefs[str(device_id)] = {"preferred_mode": preferred_mode}
            if isinstance(payload, dict):
                preferred_temperature = _as_temperature(payload.get("preferred_temperature"))
                preferred_fan = payload.get("preferred_fan")
                if preferred_temperature is not None:
                    prefs.setdefault(str(device_id), {})["preferred_temperature"] = int(round(preferred_temperature))
                if isinstance(preferred_fan, str) and preferred_fan:
                    prefs.setdefault(str(device_id), {})["preferred_fan"] = preferred_fan
        return prefs

    def _save_device_prefs(self) -> None:
        try:
            self.device_prefs_file.write_text(json.dumps(self.device_prefs, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.log(f"保存设备偏好失败：{exc}")

    def _preferred_mode(self, device_id: str) -> str | None:
        payload = self.device_prefs.get(str(device_id)) or {}
        preferred_mode = payload.get("preferred_mode")
        if isinstance(preferred_mode, str) and preferred_mode and preferred_mode != "off":
            return preferred_mode
        return None

    def _preferred_temperature(self, device_id: str) -> int | None:
        payload = self.device_prefs.get(str(device_id)) or {}
        preferred_temperature = _as_temperature(payload.get("preferred_temperature"))
        if preferred_temperature is None:
            return None
        return _normalize_set_temperature(preferred_temperature)

    def _preferred_fan(self, device_id: str) -> str | None:
        payload = self.device_prefs.get(str(device_id)) or {}
        preferred_fan = payload.get("preferred_fan")
        if isinstance(preferred_fan, str) and preferred_fan:
            return preferred_fan
        return None

    def _remember_preferred_mode(self, device: AcDevice, mode: str) -> None:
        if not isinstance(mode, str) or not mode or mode == "off":
            return
        device.preferred_mode = mode
        prefs = self.device_prefs.setdefault(str(device.id), {})
        prefs["preferred_mode"] = mode
        device.attrs["_preferred_mode"] = mode
        self._save_device_prefs()

    def _remember_preferred_temperature(self, device: AcDevice, temperature: int) -> None:
        temperature = _normalize_set_temperature(temperature)
        prefs = self.device_prefs.setdefault(str(device.id), {})
        prefs["preferred_temperature"] = temperature
        device.attrs["_preferred_temperature"] = temperature
        device.attrs["_local_target_temperature"] = temperature
        self._save_device_prefs()

    def _remember_preferred_fan(self, device: AcDevice, fan: str) -> None:
        if not isinstance(fan, str) or not fan:
            return
        prefs = self.device_prefs.setdefault(str(device.id), {})
        prefs["preferred_fan"] = fan
        device.attrs["_preferred_fan"] = fan
        self._save_device_prefs()

    def _active_preferred_mode(self, device: AcDevice) -> str | None:
        if isinstance(device.preferred_mode, str) and device.preferred_mode and device.preferred_mode != "off":
            return device.preferred_mode
        return self._preferred_mode(device.id)

    def desired_settings(self, device_id: str) -> dict[str, Any]:
        device = self.devices[device_id]
        mode = self._active_preferred_mode(device)
        if not mode:
            mode = device.current_mode if device.current_mode != "off" else self._reported_mode(device)
        if not mode or mode == "off":
            mode = "cool"
        temperature = self._preferred_temperature(device_id)
        if temperature is None:
            temperature = _normalize_set_temperature(device.target_temperature)
        fan = self._preferred_fan(device_id) or device.fan_speed or "auto"
        return {
            "mode": mode,
            "temperature": temperature,
            "fan": fan,
        }

    async def apply_desired_settings(self, device_id: str) -> None:
        device = self.devices[device_id]
        desired = self.desired_settings(device_id)
        mode = str(desired["mode"])
        temperature = int(desired["temperature"])
        fan = str(desired["fan"])
        if mode and mode != "off" and self._reported_mode(device) != mode:
            await self.set_mode(device_id, mode)
        if temperature:
            await self.set_temperature(device_id, temperature)
        if fan and fan != "off":
            await self.set_fan(device_id, fan)

    def _central_run_mode(self, mode: str) -> str:
        return {"cool": "2", "heat": "3", "auto": "4", "dry": "5", "fan": "1"}.get(mode, "2")

    def _temperature_mode(self, device: AcDevice) -> str:
        if device.power_on:
            mode = self._reported_mode(device)
            if mode and mode != "off":
                return mode
        preferred_mode = self._active_preferred_mode(device)
        if preferred_mode:
            return preferred_mode
        mode = self._reported_mode(device)
        return mode if mode and mode != "off" else "cool"

    def _regular_mode_control(self, device: AcDevice, mode: str) -> dict[str, Any]:
        key = "mode"
        if "mode_current" in device.attrs:
            key = "mode_current"
        elif "mode.current" in device.attrs:
            key = "mode.current"
        return {"power": "on", key: mode}

    def _regular_temperature_control(self, device: AcDevice, temperature: int) -> dict[str, Any]:
        mode = self._temperature_mode(device)
        if mode == "heat":
            if "heat_temp_set" in device.attrs:
                return {"heat_temp_set": temperature}
            if "heating_temp" in device.attrs:
                return {"heating_temp": temperature}
        else:
            if "cool_temp_set" in device.attrs:
                return {"cool_temp_set": temperature}
            if "cooling_temp" in device.attrs:
                return {"cooling_temp": temperature}
        if "temperature_current" in device.attrs:
            return {"temperature_current": temperature}
        if "temperature.current" in device.attrs:
            return {"temperature.current": temperature}
        return {"temperature": temperature, "small_temperature": 0}

    def _regular_fan_control(self, device: AcDevice, fan: str) -> dict[str, Any]:
        if "wind_speed_level" in device.attrs:
            fan_modes = {"low": 1, "medium": 3, "high": 5, "auto": "auto", "silent": 1, "full": 5}
            return {"wind_speed_level": fan_modes[fan]}
        if "wind_speed.level" in device.attrs:
            fan_modes = {"low": 1, "medium": 3, "high": 5, "auto": 6, "silent": 1, "full": 5}
            return {"wind_speed.level": fan_modes[fan]}
        fan_modes = {"silent": 20, "low": 40, "medium": 60, "high": 80, "full": 100, "auto": 102}
        return {"wind_speed": fan_modes[fan]}

    async def _verify_power_applied(self, device_id: str, expected_on: bool) -> bool:
        for delay in (0.8, 1.6, 2.4):
            await asyncio.sleep(delay)
            await self.refresh_devices(log_refresh=False)
            if self.devices[device_id].power_on is expected_on:
                return True
        return False

    async def _verify_mode_applied(self, device_id: str, expected_mode: str) -> bool:
        for delay in (0.8, 1.6, 2.4):
            await asyncio.sleep(delay)
            await self.refresh_devices(log_refresh=False)
            actual_mode = self._reported_mode(self.devices[device_id])
            if actual_mode == expected_mode:
                return True
        return False

    def _reported_mode(self, device: AcDevice) -> str | None:
        if device.device_type == 0x21 or device.is_central_node:
            run_modes = {"0": "off", "1": "fan", "2": "cool", "3": "heat", "4": "auto", "5": "dry"}
            mode = device.attrs.get("run_mode")
            return run_modes.get(str(mode), str(mode)) if mode is not None else None
        mode = _first_present(device.attrs, ("mode_current", "mode.current", "mode"))
        return str(mode) if mode is not None else None

    async def _verify_temperature_applied(self, device_id: str, expected_temperature: int, expected_mode: str | None = None) -> bool:
        for delay in (0.8, 1.6, 2.4):
            await asyncio.sleep(delay)
            await self.refresh_devices(log_refresh=False)
            device = self.devices[device_id]
            actual_values = self._reported_temperature_values(device, expected_mode)
            if any(_normalize_set_temperature(value) == expected_temperature for value in actual_values):
                return True
        return False

    def _reported_temperature_values(self, device: AcDevice, expected_mode: str | None) -> list[float]:
        if expected_mode == "heat":
            keys = ("heat_temp_set", "heating_temp", "target_temperature", "temperature.target", "temperature.set", "temperature.current", "temperature_current", "temperature")
        elif expected_mode:
            keys = ("cool_temp_set", "cooling_temp", "target_temperature", "temperature.target", "temperature.set", "temperature.current", "temperature_current", "temperature")
        else:
            keys = (
                "target_temperature",
                "temperature.target",
                "temperature.set",
                "temperature.current",
                "temperature_current",
                "heat_temp_set",
                "heating_temp",
                "cool_temp_set",
                "cooling_temp",
                "temperature",
            )
        values = [_as_temperature(device.attrs.get(key)) for key in keys]
        values = [value for value in values if value is not None]
        if values:
            return values
        return [device.target_temperature]

    async def _verify_fan_applied(self, device_id: str, expected_fan: str) -> bool:
        for delay in (0.8, 1.6, 2.4):
            await asyncio.sleep(delay)
            await self.refresh_devices(log_refresh=False)
            actual = self.devices[device_id].fan_speed
            if actual == expected_fan:
                return True
        return False


def run_async(coro):
    return asyncio.run(coro)


def _parse_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flatten_status(status: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in status.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_status(value, name))
        else:
            flat[name] = value
            if prefix:
                flat[str(key)] = value
    return flat


def _mode_label(mode: str) -> str:
    return {
        "cool": "制冷",
        "heat": "制热",
        "auto": "自动",
        "dry": "除湿",
        "fan": "送风",
        "off": "关闭",
    }.get(mode, mode)


def _fan_label(fan: str) -> str:
    return {
        "auto": "自动",
        "low": "低风",
        "medium": "中风",
        "high": "高风",
        "silent": "静音",
        "full": "强风",
        "off": "关闭",
    }.get(fan, fan)


def format_temperature(value: float | None) -> str:
    if value is None:
        return "未知"
    return str(round(value))


_DEVICE_ORDER_RE = re.compile(r"[（(]\s*(\d+)(?:\s*[-~－—至]\s*\d+)?\s*[)）]")


def _device_sort_key(device: AcDevice) -> tuple[int, int, str]:
    match = _DEVICE_ORDER_RE.search(device.name or "")
    if match:
        return (0, int(match.group(1)), device.name.lower())
    return (1, 10**9, device.name.lower())
