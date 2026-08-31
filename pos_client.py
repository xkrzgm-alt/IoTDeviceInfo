import logging
from typing import Optional

import requests

from config import POS_USER, POS_PWD, POS_LOGIN_URL, POS_QUERY_URL


class POSClient:
    """Fetch POS reader info from dash.vendera.ai for a given machine/device ID."""

    def __init__(self):
        self.username = POS_USER
        self.password = POS_PWD
        self.token: Optional[str] = None

    def get_auth_token(self) -> Optional[str]:
        try:
            payload = {"username": self.username, "password": self.password}
            headers = {
                "accept": "application/json, text/plain, */*",
                "content-type": "application/json;charset=UTF-8",
            }
            response = requests.post(POS_LOGIN_URL, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("data", {}).get("token")
                if self.token:
                    logging.info("POS module - Login successful, obtained Bearer Token")
                    return self.token
            logging.error(f"POS module - Login failed, status={response.status_code}")
            return None
        except Exception as e:
            logging.error(f"POS module - Login exception: {str(e)}")
            return None

    def get_pos_info(self, machine_id: str) -> dict:
        if not self.token:
            self.get_auth_token()
        if not self.token:
            return {}

        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"machineId": machine_id}

        try:
            response = requests.get(POS_QUERY_URL, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                records = data.get("data", {}).get("records", [])
                if not records:
                    logging.warning(f"POS module - No POS reader found for machine [{machine_id}]")
                    return {}
                pos_data = records[0]

                logging.info(f"POS module - Retrieved POS info for machine [{machine_id}]")
                return {
                    "POS Serial No": pos_data.get("posSn", "-"),
                    "POS Type": pos_data.get("posType", "-"),
                    "Merchant ID": pos_data.get("merchantId", "-"),
                    "App Version": pos_data.get("appVersion", "-"),
                    "Machine ID": pos_data.get("machineId", "-"),
                    "Commercial Use Status": pos_data.get("commercialUseStatusLabel", "-"),
                    "Pre-Auth Amount": f"${pos_data.get('preAuthAmount', 0):.2f}",
                    "POS Status": pos_data.get("posStatusLabel", "-"),
                    "Network Status": pos_data.get("posNetStatusLabel", "-"),
                    "Cancelled": pos_data.get("isCancelLabel", "-"),
                    "Created": pos_data.get("createTime", "-"),
                }
            logging.error(f"POS module - Query failed, status={response.status_code}")
            return {}
        except Exception as e:
            logging.error(f"POS module - Query exception: {str(e)}")
            return {}
