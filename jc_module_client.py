import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple

import requests

from config import DEVICE_INFO_LOGIN_URL, DEVICE_INFO_USER, DEVICE_INFO_PWD, JC_MODULE_LOG_URL
from temperature_client import DashTemperatureClient


_TELEMETRY_ONLINE_WINDOW = timedelta(minutes=15)


def _parse_api_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        # Dash currently returns local server timestamps without an offset. Keep
        # those comparable with datetime.now(); use UTC for offset-aware values.
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _is_recent_telemetry(value: Any, now: datetime | None = None) -> bool:
    reported_at = _parse_api_time(value)
    if reported_at is None:
        return False
    if reported_at.tzinfo:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        else:
            current = current.astimezone(timezone.utc)
    else:
        current = now or datetime.now()
        if current.tzinfo is not None:
            current = current.replace(tzinfo=None)
    age = current - reported_at
    return timedelta(0) <= age <= _TELEMETRY_ONLINE_WINDOW


class JCModuleClient:
    """4G module (built into main controller) client.

    Queries the vendera.ai IoT platform for 4G network metrics when the
    device's routerCode starts with 'JC' — a 4G module embedded in the
    main controller rather than a standalone InHand/Hongdian router.
    """

    def __init__(self):
        self._token: str | None = None

    # ------------------------------------------------------------------
    # Auth (same Octopus-Token flow as DeviceInfoFetcher)
    # ------------------------------------------------------------------

    def _get_auth_token(self) -> str | None:
        if self._token:
            return self._token

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        login_data = {"username": DEVICE_INFO_USER, "password": DEVICE_INFO_PWD}

        try:
            resp = requests.post(DEVICE_INFO_LOGIN_URL, json=login_data, headers=headers, timeout=10)
            resp.raise_for_status()
            token = (
                resp.headers.get("Octopus-Token")
                or resp.json().get("data", {}).get("token")
                or resp.json().get("token")
            )
            if token:
                logging.info("JC module client — login successful, obtained Octopus-Token")
                self._token = token
                return token
            logging.error(
                "JC module client — login rejected (code=%s, message=%s)",
                resp.json().get("code"),
                resp.json().get("msg") or resp.json().get("message") or "no token",
            )
            return None
        except Exception as e:
            logging.error(f"JC module client — login failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _query_network_status(self, machine_code: str) -> Dict[str, Any]:
        """POST /iot/machine/logs/network/status and return the latest record."""
        token = self._get_auth_token()
        if not token:
            return {}

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Octopus-Token": token,
            "Origin": "https://iot-usa.zanbianli.cn",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        now = datetime.now()
        payload: Dict[str, Any] = {
            "machineCode": machine_code,
            "startDate": now.strftime("%Y-%m-%d 00:00:00"),
            "endDate": now.strftime("%Y-%m-%d %H:%M:%S"),
            "currPage": 1,
            "pageSize": 10,
            "status": "",
        }

        try:
            resp = requests.post(JC_MODULE_LOG_URL, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "200" and data.get("data"):
                inner = data["data"]
                # Response may have a 'list' or 'records' array — take the first entry
                records = inner.get("list") or inner.get("records") or []
                if records:
                    return records[0]
                # Or the data itself might be a single record dict
                if isinstance(inner, dict) and not records:
                    return inner
            logging.warning(f"JC module — network status query returned no data for {machine_code}")
            return {}
        except Exception as e:
            logging.error(f"JC module — network status query failed: {e}")
            return {}

    def _telemetry_fallback(self, machine_code: str) -> Dict[str, Any]:
        """Use recent device telemetry as connectivity evidence.

        This fallback does not invent modem metrics. It only prevents an IoT
        authentication or network-log failure from being reported as Offline.
        """
        try:
            telemetry = DashTemperatureClient().get_temperature(machine_code)
            current = (telemetry or {}).get("current_temperature") or {}
            updated_at = current.get("updatedAt") or current.get("occurredAt")
            if _is_recent_telemetry(updated_at):
                logging.info(
                    "JC module — recent Dash telemetry confirms device connectivity for %s",
                    machine_code,
                )
                return {"online": True, "updated_at": updated_at}
        except Exception as e:
            logging.warning("JC module — telemetry fallback failed: %s", e)
        return {"online": False, "updated_at": None}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_4g_module_info(
        self, router_sn: str, machine_code: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Return (router_info, signal_info) for a JC-prefix 4G module.

        Parameters:
            router_sn: The JC-prefixed router serial number from SmartCabinet.
            machine_code: The vendera.ai machine code (device_id).
        """
        record = self._query_network_status(machine_code)

        if not record:
            telemetry = self._telemetry_fallback(machine_code)
            return {
                "Router SN": router_sn,
                "Online Status": (
                    "[Online (recent device telemetry)]" if telemetry["online"] else "[Unknown]"
                ),
                "Status Source": (
                    "Dash temperature telemetry"
                    if telemetry["online"]
                    else "IoT module status unavailable"
                ),
                "Device Model": "4G Module (Built-in)",
                "IMEI": "Not Found",
                "ICCID": "Not Found",
                "Firmware Version": "-",
                "Last Active Time": telemetry["updated_at"] or "-",
            }, {}

        # --- Build router_info dict (same keys as InHand/Hongdian clients) ---
        status_val = record.get("status")
        status_name = str(record.get("statusName", "")).strip()
        if status_val in (1, "1", True) or status_name in (
            "正常", "Normal", "Online", "Connected", "在线"
        ):
            online_status = "[Online]"
        elif status_val in (0, "0", False) or status_name in (
            "异常", "Offline", "Disconnected", "离线"
        ):
            online_status = "[Offline]"
        else:
            online_status = "[Unknown]"

        network_type = record.get("networkType", "")
        # networkType is a numeric string like "13" (LTE); keep as-is

        router_info = {
            "Router SN": router_sn,
            "Online Status": online_status,
            "Device Model": "4G Module (Built-in)",
            "IMEI": record.get("imei", "Not Found"),
            "ICCID": record.get("iccid", "Not Found"),
            "Firmware Version": "-",
            "Last Active Time": record.get("createTime", "-"),
            "Network Type": network_type,
            "Network Latency": record.get("networkDelay", "-"),
            "SIM Carrier": record.get("simOperatorName", "-"),
            "Module Serial No": router_sn,
        }

        # --- Build signal_info dict ---
        # The vendera.ai log endpoint only provides networkDbm (RSRP-equivalent).
        # SNR, RSSI, and Band are not available from this API.
        dbm = record.get("networkDbm", "")
        signal_info = {
            "Latest Signal Time": record.get("reportTime", "-"),
            "RSRP (dBm)": dbm if dbm else "Not reported",
            "SNR (dB)": "Not reported",
            "RSSI (asu)": "Not reported",
            "4G Band": "Not reported",
        }

        return router_info, signal_info
