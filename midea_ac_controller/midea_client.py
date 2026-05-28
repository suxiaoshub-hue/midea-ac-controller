from __future__ import annotations

import asyncio
import json
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
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def is_central_node(self) -> bool:
        return self.parent_appliance_code is not None and self.nodeid is not None

    @property
    def power_on(self) -> bool:
        if self.device_type == 0x21 or self.is_central_node:
            return str(self.attrs.get("run_mode", "0")) != "0"
        return _truthy_on(self.attrs.get("power"))

    @property
    def target_temperature(self) -> float:
        if self.device_type == 0x21 or self.is_central_node:
            mode = str(self.attrs.get("run_mode", "2"))
            key = "heat_temp_set" if mode == "3" else "cool_temp_set"
            return _as_float(self.attrs.get(key), 26.0) or 26.0
        base = _as_float(self.attrs.get("temperature"), None)
        if base is None:
            base = _as_float(self.attrs.get("temperature.current"), 26.0)
        dec = _as_float(self.attrs.get("small_temperature"), 0.0) or 0.0
        return float(base or 26.0) + dec

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
            return run_modes.get(str(self.attrs.get("run_mode", "2")), str(self.attrs.get("run_mode", "2")))
        mode = self.attrs.get("mode")
        if isinstance(mode, str) and mode:
            return mode
        if not self.power_on:
            return "off"
        return "cool"

    @property
    def fan_speed(self) -> str:
        if self.device_type == 0x21 or self.is_central_node:
            fan_modes = {"0": "off", "1": "low", "3": "medium", "5": "high", "8": "auto"}
            return fan_modes.get(str(self.attrs.get("fan_speed", "8")), str(self.attrs.get("fan_speed", "8")))
        fan = self.attrs.get("wind_speed")
        reverse = {20: "silent", 40: "low", 60: "medium", 80: "high", 100: "full", 102: "auto"}
        if isinstance(fan, str):
            try:
                fan = int(float(fan))
            except (TypeError, ValueError):
                return fan
        return reverse.get(int(fan), "auto") if fan is not None else "auto"

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
        self.log = log or (lambda message: None)
        self.session: ClientSession | None = None
        self.cloud: MeijuCloud | MSmartHomeCloud | None = None
        self.server = SERVER_MEIJU
        self.devices: dict[str, AcDevice] = {}

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
        self.log("正在读取家庭和设备列表 ...")
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
            self.log(f"{home_name}: 找到 {len(appliances)} 个设备")
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
                )
                all_devices[device.id] = device
        self.devices = all_devices
        await self.refresh_devices()
        return list(self.devices.values())

    async def refresh_devices(self) -> list[AcDevice]:
        if self.cloud is None:
            raise RuntimeError("请先登录账号")
        if not self.devices:
            return []
        self.log("正在刷新空调状态 ...")
        base_devices = list(self.devices.values())
        central_gateways = [d for d in base_devices if d.device_type == 0x21 and not d.is_central_node]
        if central_gateways:
            await self._refresh_central_gateways(central_gateways)
        for device in list(self.devices.values()):
            if device.device_type == 0x21 or device.is_central_node:
                continue
            await self._refresh_regular_ac(device)
        return list(self.devices.values())

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
            device.attrs.update(_flatten_status(status))
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
            gateway.attrs.update(_flatten_status(attr))
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
                )
                self.devices[device_id] = node
            node.attrs.update(_flatten_status(event))
            if isinstance(event.get("condition_attribute"), dict):
                node.attrs.update(_flatten_status(event["condition_attribute"]))

    async def set_power(self, device_id: str, on: bool) -> None:
        device = self.devices[device_id]
        if device.device_type == 0x21 or device.is_central_node:
            await self._send_central_control(device, {"run_mode": "2" if on else "0"})
        else:
            await self._send_regular_control(device, {"power": "on" if on else "off"})

    async def set_temperature(self, device_id: str, temperature: float) -> None:
        device = self.devices[device_id]
        temperature = max(17.0, min(30.0, float(temperature)))
        if device.device_type == 0x21 or device.is_central_node:
            mode = str(device.attrs.get("run_mode", "2"))
            control = {"cooling_temp": str(temperature)}
            if mode == "3":
                control["heating_temp"] = str(temperature)
            await self._send_central_control(device, control)
            return
        temp_int = int(temperature)
        control = {"temperature": temp_int, "small_temperature": round(temperature - temp_int, 1)}
        await self._send_regular_control(device, control)

    async def set_mode(self, device_id: str, mode: str) -> None:
        device = self.devices[device_id]
        if device.device_type == 0x21 or device.is_central_node:
            run_modes = {"off": "0", "fan": "1", "cool": "2", "heat": "3", "auto": "4", "dry": "5"}
            await self._send_central_control(device, {"run_mode": run_modes[mode]})
        else:
            await self._send_regular_control(device, {"power": "off"} if mode == "off" else {"power": "on", "mode": mode})

    async def set_fan(self, device_id: str, fan: str) -> None:
        device = self.devices[device_id]
        if device.device_type == 0x21 or device.is_central_node:
            fan_modes = {"off": "0", "low": "1", "medium": "3", "high": "5", "auto": "8"}
            await self._send_central_control(device, {"fan_speed": fan_modes[fan]})
        else:
            fan_modes = {"silent": 20, "low": 40, "medium": 60, "high": 80, "full": 100, "auto": 102}
            await self._send_regular_control(device, {"wind_speed": fan_modes[fan]})

    async def _send_regular_control(self, device: AcDevice, control: dict[str, Any]) -> None:
        if self.cloud is None:
            raise RuntimeError("请先登录账号")
        self.log(f"{device.name}: 下发控制 {json.dumps(control, ensure_ascii=False)}")
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
                status=device.attrs,
            )
        elif isinstance(self.cloud, MeijuCloud):
            ok = await self.cloud.send_device_control(device.appliance_code, control=nested, status=device.attrs)
        if not ok:
            raise RuntimeError(f"{device.name}: 控制失败")
        device.attrs.update(control)

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
        self.log(f"{device.name}: 下发中央空调控制 {json.dumps(full_control, ensure_ascii=False)}")
        ok = await self.cloud.send_central_ac_control(int(master_id), nodeid, modelid, int(idtype), full_control)
        if not ok:
            raise RuntimeError(f"{device.name}: 控制失败")
        device.attrs.update(control)

    def snapshot(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "logged_in": self.cloud is not None,
            "nickname": getattr(self.cloud, "nickname", None) if self.cloud else None,
            "device_count": len(self.devices),
            "devices": [device.to_dict() for device in self.devices.values()],
        }


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
