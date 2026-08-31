import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

import requests

from config import DM_BASE_URL, DM_CLIENT_ID, DM_CLIENT_SECRET, DM_USERNAME, DM_PASSWORD


class InHandApiClient:
    """InHand API client (fully aligned with official router.py), fetches router details and 4G signal info"""

    def __init__(self):
        self.base_url = DM_BASE_URL
        self.client_id = DM_CLIENT_ID
        self.client_secret = DM_CLIENT_SECRET
        self.username = DM_USERNAME
        self.password = DM_PASSWORD
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.SIGNAL_TIME_RANGE = 5

    def _get_new_token(self, grant_type, payload):
        url = f"{self.base_url}/oauth2/access_token"
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
        data = {
            "grant_type": grant_type,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        data.update(payload)

        response = requests.post(url, headers=headers, data=data, timeout=10)
        response.raise_for_status()

        token_data = response.json()
        self.access_token = token_data.get("access_token")
        self.refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        self.token_expiry = datetime.now() + timedelta(seconds=expires_in)

    def authenticate_with_password(self):
        payload = {
            "username": self.username,
            "password": self.password,
            "password_type": 1,
        }
        self._get_new_token("password", payload)

    def _refresh_token(self):
        if not self.refresh_token:
            self.authenticate_with_password()
            return
        payload = {"refresh_token": self.refresh_token}
        self._get_new_token("refresh_token", payload)

    def _make_request(self, method, endpoint, params=None, json_data=None):
        if self.access_token is None or datetime.now() >= self.token_expiry:
            self._refresh_token()

        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as err:
            if err.response.status_code == 401:
                self._refresh_token()
                headers["Authorization"] = f"Bearer {self.access_token}"
                response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=10)
                response.raise_for_status()
                return response.json()
            else:
                raise

    def get_router_by_sn(self, target_sn: str) -> Dict[str, Any]:
        params = {"serial_number": target_sn, "cursor": 0, "limit": 10, "verbose": 50}

        response = self._make_request("GET", "/api/devices", params=params)
        total_devices = response.get("total", 0)

        if total_devices == 0:
            raise Exception(f"Device with SN [{target_sn}] not found on InHand platform")

        router_data = response["result"][0]
        info_dict = router_data.get("info") or {}

        return {
            "Router SN": target_sn,
            "Device ID (InHand)": router_data["_id"],
            "Online Status": "[Online]" if router_data.get("online") == 1 else "[Offline]",
            "IMEI": info_dict.get("imei", router_data.get("imei", "Not Found")),
            "ICCID": info_dict.get("iccid", router_data.get("iccid", "Not Found")),
            "Device Model": router_data.get("model", "-"),
            "Firmware Version": router_data.get("firmware_version", "-"),
            "Address": router_data.get("address", "-"),
        }

    def get_4g_signal_info(self, device_id: str) -> Dict[str, Any]:
        end_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        start_time = (datetime.now(timezone.utc) - timedelta(minutes=self.SIGNAL_TIME_RANGE)).replace(
            tzinfo=None
        ).isoformat() + "Z"

        endpoint = f"/api/devices/{device_id}/signal-quality"
        params = {"start": start_time, "end": end_time, "verbose": 100}

        try:
            response = self._make_request("GET", endpoint, params=params)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise Exception(f"Signal query endpoint path error, returned 404")
            else:
                raise

        signal_result = response.get("result", {})
        values = signal_result.get("values", [])
        columns = signal_result.get("columns", [])

        if not values or not columns:
            raise Exception("No 4G signal data obtained. Possible causes: 1.Device offline 2.Device not reporting signal 3.No data in time range")

        # The API ignores the start/end window and returns cached samples in
        # ascending time order (oldest → newest). Pick the sample with the latest
        # timestamp rather than trusting the array order, so the report reflects
        # the device's *current* signal instead of a stale sample from days ago.
        time_idx = columns.index("time") if "time" in columns else 0
        latest_signal = dict(zip(columns, sorted(values, key=lambda row: row[time_idx])[-1]))

        signal_info = {
            "Latest Signal Time": latest_signal.get("time", "Unknown"),
            "RSRP (dBm)": latest_signal.get("rsrp", "Not reported"),
            "SNR (dB)": latest_signal.get("sinr", "Not reported"),
            "RSSI (dBm)": latest_signal.get("rssi", "Not reported"),
            "4G Band": latest_signal.get("band", "Not reported"),
        }

        # The signal-quality series has no "band" column, and `info.cell` is null
        # for this device. The current band lives in the top-level `signalStrength`
        # snapshot of the device detail endpoint instead.
        if signal_info["4G Band"] == "Not reported":
            device_detail = self._make_request("GET", f"/api/devices/{device_id}", params={"verbose": 100})
            signal_strength = device_detail["result"].get("signalStrength", {}) or {}
            signal_info["4G Band"] = signal_strength.get("band", "Not reported")

        return signal_info
