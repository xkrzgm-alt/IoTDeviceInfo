import logging
from datetime import datetime
from typing import Any, Dict, Tuple

import requests

from config import DEVICE_INFO_LOGIN_URL, DEVICE_INFO_USER, DEVICE_INFO_PWD, JC_MODULE_LOG_URL


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
            logging.error("JC module client — login succeeded but no Token obtained")
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
            return {
                "Router SN": router_sn,
                "Online Status": "[Offline]",
                "Device Model": "4G Module (Built-in)",
                "IMEI": "Not Found",
                "ICCID": "Not Found",
                "Firmware Version": "-",
                "Last Active Time": "-",
            }, {}

        # --- Build router_info dict (same keys as InHand/Hongdian clients) ---
        status_val = record.get("status")
        status_name = record.get("statusName", "")
        if status_val == 1 or status_name in ("正常", "Normal", "Online", "Connected", "在线"):
            online_status = "[Online]"
        else:
            online_status = "[Offline]"

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
