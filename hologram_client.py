import logging
from typing import Optional, Dict, Any

import requests

from config import HOLOGRAM_API_KEY, HOLOGRAM_BASE_URL, HOLOGRAM_ORG_ID
from device_info import translate_status


class HologramApiClient:
    """Hologram API client, query SIM card info"""

    def __init__(self):
        self.api_key = HOLOGRAM_API_KEY
        self.base_url = HOLOGRAM_BASE_URL

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

            return {
                "Device Name": translate_status(device_data.get("name") or sim_data.get("devicename", "Unknown")),
                "SIM Status": translate_status(sim_data.get("state", "Unknown")),
                "ICCID": sim_data.get("sim", "Unknown"),
                "IMSI": sim_data.get("imsi", "Unknown"),
                "Network": translate_status(last_session.get("network_name") or device_cellular_link.get("last_network_used", "Unknown")),
                "Data Plan": translate_status((device_cellular_link.get("plan", {}).get("name") or "Unknown").strip()),
                "Monthly Data (Bytes)": device_cellular_link.get("cur_billing_data_used", 0),
                "Monthly Data (GB)": round(device_cellular_link.get("cur_billing_data_used", 0) / (1024 ** 3), 2),
                "Last Active Time": translate_status(last_active),
                "Session Start Time": translate_status(last_session.get("session_begin", "Unknown")),
                "Session End Time": translate_status(last_session.get("session_end", "Unknown")),
                "Session Active": translate_status(last_session.get("active", "Unknown")),
            }
        except Exception as e:
            logging.error(f"Hologram API request error: {str(e)}")
            return None
