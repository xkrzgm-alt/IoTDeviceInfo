import logging
from typing import Any, Optional

import requests

from config import DASH_API_BASE_URL, DASH_USER, DASH_PWD


class DashTemperatureClient:
    """Fetch current and historical machine temperatures from dash.vendera.ai."""

    def __init__(self):
        self.token: Optional[str] = None

    def get_auth_token(self) -> Optional[str]:
        try:
            response = requests.post(
                f"{DASH_API_BASE_URL}/auth/login",
                json={"username": DASH_USER, "password": DASH_PWD},
                headers={
                    "accept": "application/json, text/plain, */*",
                    "content-type": "application/json;charset=UTF-8",
                },
                timeout=10,
            )
            response.raise_for_status()
            body = response.json()
            self.token = (body.get("data") or {}).get("token")
            if self.token:
                return self.token
            logging.error("Dash temperature login returned no token: %s", body.get("message"))
        except Exception as exc:
            logging.error("Dash temperature login failed: %s", exc)
        return None

    def get_temperature(self, device_id: str, range_hours: int = 24) -> Optional[dict[str, Any]]:
        if not self.token and not self.get_auth_token():
            return None

        url = f"{DASH_API_BASE_URL}/machines/{device_id}/temperature"
        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"rangeHours": range_hours}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 401:
                self.token = None
                if not self.get_auth_token():
                    return None
                headers["Authorization"] = f"Bearer {self.token}"
                response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            body = response.json()
            if body.get("code") != 200 or not isinstance(body.get("data"), dict):
                logging.warning(
                    "Dash temperature query failed for device [%s]: %s",
                    device_id,
                    body.get("message", "Unknown error"),
                )
                return None

            data = body["data"]
            return {
                "range_hours": range_hours,
                "binding": data.get("binding"),
                "policy": data.get("policy"),
                "current_temperature": data.get("currentTemperature"),
                "records": data.get("records") or [],
            }
        except Exception as exc:
            logging.error("Dash temperature query failed for device [%s]: %s", device_id, exc)
            return None
