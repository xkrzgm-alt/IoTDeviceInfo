import logging
from typing import Optional, Dict, Any

import requests

from config import DEVICE_INFO_LOGIN_URL, DEVICE_INFO_USER, DEVICE_INFO_PWD

# Chinese → English translation map for API-returned status/type values
CN_TO_EN = {
    # Status / state
    "在线": "Online",
    "离线": "Offline",
    "正常": "Normal",
    "异常": "Abnormal",
    "已连接": "Connected",
    "未连接": "Disconnected",
    "连接": "Connected",
    "断开": "Disconnected",
    "未知": "Unknown",
    "从未连接": "Never Connected",
    "已投放": "Deployed",
    "未投放": "Not Deployed",
    # Run / operating status
    "运行中": "Running",
    "已停止": "Stopped",
    "停止": "Stopped",
    "运行": "Running",
    # Network status
    "网络正常": "Network Normal",
    "网络异常": "Network Abnormal",
    "网络已连接": "Network Connected",
    "网络未连接": "Network Disconnected",
    # Power status
    "供电正常": "Power Normal",
    "供电异常": "Power Abnormal",
    # Memory status
    "内存正常": "Memory Normal",
    "内存异常": "Memory Abnormal",
    # Device / cabinet types
    "智能柜": "Smart Cabinet",
    "售货机": "Vending Machine",
    "智能售卖柜": "Smart Vending Cabinet",
    "格子柜": "Locker Cabinet",
}


def translate_status(value: Any) -> str:
    """Translate Chinese status/type values to English. Returns the original value
    unchanged if no translation is found."""
    if isinstance(value, str) and value in CN_TO_EN:
        return CN_TO_EN[value]
    return str(value) if value is not None else "-"


def _channel_value(status_map: Any, channel: str) -> Any:
    """Read a channel value from the several naming styles used by the portal."""
    if not isinstance(status_map, dict):
        return None
    aliases = {
        "Left": ("Left", "left", "L", "R1", "r1", 1, "1"),
        "Right": ("Right", "right", "R", "R2", "r2", 2, "2"),
    }
    for key in aliases[channel]:
        if key in status_map:
            return status_map[key]
    return None


def _channel_report(info: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Return only channels present in the run payload, without inventing faults."""
    result: Dict[str, Dict[str, str]] = {}
    source_names = {
        "Power": "powerStatus",
        "Door": "doorStatus",
        "Lock": "lockStatus",
        "Camera": "cameraStatus",
    }
    for channel in ("Left", "Right"):
        values: Dict[str, str] = {}
        for label, source in source_names.items():
            raw_map = info.get(source)
            # powerStatusName is normally a scalar; powerStatus is the optional
            # per-channel form used by dual cabinets.
            value = _channel_value(raw_map, channel)
            if value is not None:
                values[f"{label} Status"] = translate_status(
                    "Normal" if value == 1 else "Abnormal" if value == 0 else value
                )
        if values:
            result[channel] = values
    return result


class DeviceInfoFetcher:
    """Fetch device basic info and operating info"""

    def get_auth_token(self) -> Optional[str]:
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://iot-usa.zanbianli.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        login_data = {"username": DEVICE_INFO_USER, "password": DEVICE_INFO_PWD}

        try:
            response = requests.post(DEVICE_INFO_LOGIN_URL, json=login_data, headers=headers, timeout=10)
            response.raise_for_status()
            token = (
                response.headers.get("Octopus-Token")
                or response.json().get("data", {}).get("token")
                or response.json().get("token")
            )
            if token:
                logging.info("Device info module - Login successful, obtained Octopus-Token")
                return token
            logging.error("Device info module - Login succeeded but no Token obtained")
            return None
        except Exception as e:
            logging.error(f"Device info module - Login failed: {str(e)}")
            return None

    def get_device_info(self, device_code: str, auth_token: str) -> Dict[str, Any]:
        """Return a dict with device basic info + operating info"""
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Octopus-Token": auth_token,
            "Origin": "https://iot-usa.zanbianli.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        # Step 1: Query device basic info
        list_url = "https://iot-usa.vendera.ai/iot/machine/page"
        payload = {"pageSize": 10, "currPage": 1, "code": device_code}
        device_base_info = {}
        internal_id = None

        try:
            response = requests.post(list_url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == "200" and data.get("data", {}).get("list"):
                device_data = data["data"]["list"][0]
                internal_id = device_data.get("id")
                device_base_info = {
                    "Device Code": device_data.get("code", device_code),
                    "Device Type": translate_status(device_data.get("cabinetTypeName", "-")),
                    "Device Status": translate_status(device_data.get("statusName", "-")),
                    "Board Serial No": device_data.get("serialNo", "-"),
                    "Device Login Time": device_data.get("apiLoginTime", "-"),
                    "MQ Login Time": device_data.get("loginTime", "-"),
                    "Upgrade Version": device_data.get("version", "-"),
                    "Current Version": device_data.get("currentVersion", "-"),
                    "Run Status": translate_status(device_data.get("runStatusName", "-")),
                    "Network Status": translate_status(device_data.get("networkStatusName", "-")),
                    "Add Time": device_data.get("createTime", device_data.get("addTime", "-")),
                }
            else:
                logging.error(f"Device [{device_code}] not found or insufficient permissions")
                return {"Basic Info": device_base_info, "Operating Info": {}}
        except Exception as e:
            logging.error(f"Failed to retrieve device basic info: {str(e)}")
            return {"Basic Info": device_base_info, "Operating Info": {}}

        # Step 2: Query device operating info
        device_run_info = {}
        if internal_id:
            detail_url = f"https://iot-usa.vendera.ai/iot/machine/run/{internal_id}"

            try:
                detail_response = requests.get(detail_url, headers=headers, timeout=10)
                detail_response.raise_for_status()
                detail_data = detail_response.json()
                if detail_data.get("code") == "200":
                    info = detail_data.get("data", {})
                    device_run_info = {
                        "Operating Status": translate_status(info.get("operateStatusName", "-")),
                        "Network Status": translate_status(info.get("networkStatusName", "-")),
                        "Power Status": translate_status(info.get("powerStatusName", "-")),
                        "Memory Status": translate_status(info.get("memoryStatusName", "-")),
                        "Device Temperature": info.get("deviceTemperature", "-"),
                        "Channels": _channel_report(info),
                    }
            except Exception as e:
                logging.error(f"Failed to retrieve device operating info: {str(e)}")

        return {"Basic Info": device_base_info, "Operating Info": device_run_info}
