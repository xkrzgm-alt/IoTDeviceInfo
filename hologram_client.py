import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import requests

from config import HOLOGRAM_API_KEY, HOLOGRAM_BASE_URL, HOLOGRAM_ORG_ID
from device_info import translate_status


class HologramApiClient:
    """Hologram API client, query SIM card info"""

    def __init__(self):
        self.api_key = HOLOGRAM_API_KEY
        self.base_url = HOLOGRAM_BASE_URL

    @staticmethod
    def _bytes_to_gb(byte_count: int) -> float:
        """Convert bytes to Hologram's decimal (base-10) GB unit."""
        return round(byte_count / 1_000_000_000, 2)

    @staticmethod
    def _billing_period(when_expires: str) -> tuple[str, str]:
        """Derive the SIM's 30-day billing period from its renewal timestamp."""
        if not when_expires:
            return "Unknown", "Unknown"
        try:
            period_end = datetime.strptime(when_expires, "%Y-%m-%d %H:%M:%S")
            period_start = period_end - timedelta(days=30)
            return (
                period_start.strftime("%Y-%m-%d %H:%M:%S"),
                period_end.strftime("%Y-%m-%d %H:%M:%S"),
            )
        except (TypeError, ValueError):
            logging.warning("Unexpected Hologram whenexpires value: %r", when_expires)
            return "Unknown", str(when_expires)

    def _get_calendar_month_usage(self, link_id: int) -> int:
        """Sum session usage for the current UTC calendar month."""
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        params = {
            "linkid": link_id,
            "timestart": int(month_start.timestamp()),
            "timeend": int(now.timestamp()),
            "limit": 5000,
        }
        total_bytes = 0
        last_cursor = None

        while True:
            response = requests.get(
                f"{self.base_url}/usage/data",
                auth=("apikey", self.api_key),
                params=params,
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            total_bytes += sum(int(row.get("bytes", 0) or 0) for row in payload.get("data", []))

            if not payload.get("continues"):
                break
            cursor = payload.get("lastid")
            if cursor is None or cursor == last_cursor:
                raise ValueError("Hologram usage pagination returned an invalid cursor")
            last_cursor = cursor
            params["startafter"] = cursor

        return total_bytes

    def get_hologram_sim_info(self, iccid: str, imei: str) -> Optional[Dict[str, Any]]:
        logging.info(f"\n [Hologram] Querying SIM info (ICCID: {iccid} / IMEI: {imei})")
        search_value = str(iccid).strip() if iccid and iccid != "Not Found"else str(imei).strip()
        endpoint = f"{self.base_url}/links/cellular"
        params = {"limit": 5}
        if HOLOGRAM_ORG_ID:
            params["orgid"] = int(HOLOGRAM_ORG_ID)
        params["sim"if iccid and iccid != "Not Found"else "imei"] = search_value

        try:
            response = requests.get(endpoint, auth=("apikey", self.api_key), params=params, timeout=10)
            response.raise_for_status()
            sim_list = response.json().get("data", [])
            if not sim_list:
                logging.warning("No Hologram SIM card info found")
                return None

            sim_data = sim_list[0]
            device_id = sim_data.get("deviceid")
            device_data = {}
            if device_id:
                resp_dev = requests.get(
                    f"{self.base_url}/devices/{device_id}",
                    auth=("apikey", self.api_key),
                    timeout=10,
                )
                if resp_dev.status_code == 200:
                    device_data = resp_dev.json().get("data", {})

            device_cellular_link = {}
            if (
                device_data.get("links")
                and isinstance(device_data["links"].get("cellular"), list)
                and len(device_data["links"]["cellular"]) > 0
            ):
                device_cellular_link = device_data["links"]["cellular"][0]

            last_session = (
                device_data.get("lastsession")
                or device_data.get("last_session")
                or sim_data.get("last_session")
                or {}
            )
            last_active = last_session.get("session_begin") or device_cellular_link.get(
                "last_connect_time", "Never connected / Unknown"
            )

            billing_bytes = int(device_cellular_link.get("cur_billing_data_used", 0) or 0)
            billing_start, billing_end = self._billing_period(
                device_cellular_link.get("whenexpires") or sim_data.get("whenexpires", "")
            )
            calendar_month_bytes = 0
            link_id = device_cellular_link.get("id") or sim_data.get("id")
            if link_id:
                try:
                    calendar_month_bytes = self._get_calendar_month_usage(int(link_id))
                except Exception as e:
                    logging.warning(f"Hologram calendar-month usage query failed: {e}")

            return {
                "Device Name": translate_status(device_data.get("name") or sim_data.get("devicename", "Unknown")),
                "SIM Status": translate_status(sim_data.get("state", "Unknown")),
                "ICCID": sim_data.get("sim", "Unknown"),
                "IMSI": sim_data.get("imsi", "Unknown"),
                "Network": translate_status(last_session.get("network_name") or device_cellular_link.get("last_network_used", "Unknown")),
                "Data Plan": translate_status((device_cellular_link.get("plan", {}).get("name") or "Unknown").strip()),
                "Monthly Data (Bytes)": calendar_month_bytes,
                "Monthly Data (GB)": self._bytes_to_gb(calendar_month_bytes),
                "Billing Period Data (Bytes)": billing_bytes,
                "Billing Period Data (GB)": self._bytes_to_gb(billing_bytes),
                "Billing Period Start": billing_start,
                "Billing Period End": billing_end,
                "Last Active Time": translate_status(last_active),
                "Session Start Time": translate_status(last_session.get("session_begin", "Unknown")),
                "Session End Time": translate_status(last_session.get("session_end", "Unknown")),
                "Session Active": translate_status(last_session.get("active", "Unknown")),
            }
        except Exception as e:
            logging.error(f"Hologram API request error: {str(e)}")
            return None
