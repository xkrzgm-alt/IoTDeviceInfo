import logging
from typing import Dict, Any, Tuple

import requests
import urllib3

from config import HONGDIAN_BASE_URL, HONGDIAN_TOKEN
from device_info import translate_status

# Northbound API uses self-signed certificate, disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _extract_address(result):
    """Extract address from Hongdian API response.

    Hongdian returns address as either a string or a dict like
    {'lat': None, 'lng': None, 'address': 'USA'}.  Normalize to string.
    """
    addr = result.get("address") or result.get("location")
    if addr is None:
        return "-"
    if isinstance(addr, dict):
        return addr.get("address") or "-"
    return str(addr)


def _extract_firmware_version(version):
    """Extract firmware version string from API response.

    The Hongdian API returns version as either a string or a nested dict
    like {'app': 'H8959_APP_V7.2.6_SDN-V2_2510160905', 'boot': ...}.
    We extract the 'app' field if it's a dict.
    """
    if isinstance(version, dict):
        return version.get("app", "-")
    if version:
        return str(version)
    return "-"


class HongdianApiClient:
    """Hongdian router northbound API client"""

    def __init__(self):
        self.base_url = HONGDIAN_BASE_URL
        self.token = HONGDIAN_TOKEN

    def get_profile_signal_info(self, target_sn: str) -> Dict[str, Any]:
        """Return safe modem signal fields from the Hongdian profile endpoint.

        The profile response also contains the router's full configuration, so
        this method deliberately extracts only modem telemetry and never logs or
        returns the raw profile payload.
        """
        endpoint = f"{self.base_url}/api/profile/get"
        try:
            response = requests.get(
                endpoint,
                headers={"Authentication": self.token},
                params={"idSn": target_sn},
                verify=False,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not data.get("success"):
                logging.warning(
                    "[Hongdian] Profile signal query returned no usable result for %s",
                    target_sn,
                )
                return {}

            props = data.get("result", {}).get("profile", {}).get("props", {})
            # Hongdian profile layouts vary by firmware. Newer H8959 devices
            # place the modem under props.system.net; older devices use
            # props.net. Support both without exposing the full profile.
            net = props.get("system", {}).get("net") or props.get("net") or {}
            modem = net.get("modem", {}) if isinstance(net, dict) else {}
            if not isinstance(modem, dict):
                return {}

            extracted: Dict[str, Any] = {}
            for input_key, output_key in (
                ("rsrp", "RSRP (dBm)"),
                ("rsrq", "RSRQ (dB)"),
                ("sinr", "SNR (dB)"),
                ("rssi", "RSSI (dBm)"),
                ("netBand", "4G Band"),
            ):
                if input_key in modem and modem[input_key] not in (None, ""):
                    extracted[output_key] = modem[input_key]
            if "SNR (dB)" not in extracted and modem.get("snr") not in (None, ""):
                extracted["SNR (dB)"] = modem["snr"]
            if extracted:
                extracted["Network Type"] = modem.get("netType") or modem.get("netMode")
                extracted = {
                    key: value for key, value in extracted.items()
                    if value not in (None, "")
                }
            return extracted
        except Exception as e:
            # Profile telemetry is supplemental; device queries must still work
            # when this endpoint is unavailable or unsupported by a model.
            logging.warning("[Hongdian] Profile signal query failed: %s", e)
            return {}

    def get_router_by_sn(self, target_sn: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        logging.info(f"[Hongdian] Querying device SN [{target_sn}]...")

        endpoint = f"{self.base_url}/api/device/get"
        params = {"sn": target_sn}
        headers = {"Authentication": self.token}

        try:
            response = requests.get(endpoint, headers=headers, params=params, verify=False, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise Exception(f"Northbound API returned unexpected response type: {type(data).__name__}")

            if not data.get("success"):
                raise Exception(f"Northbound API business error: {data.get('message', 'Unknown error')}")

            result = data.get("result") or {}

            # Log all top-level result keys for field discovery
            logging.info(f"[Hongdian] Result top-level keys: {list(result.keys())}")

            online_str = result.get("onlineStatus", "").lower()
            is_online = online_str == "online"

            net_info = result.get("netInfo") or {}

            # Log all netInfo keys for 4G field discovery
            if net_info:
                logging.info(f"[Hongdian] netInfo keys for SN [{target_sn}]: {list(net_info.keys())}")

            router_info = {
                "Router SN": target_sn,
                "Online Status": "[Online]" if is_online else "[Offline]",
                "Device Name": translate_status(result.get("name", "-")),
                "Last Active Time": translate_status(result.get("lastLiveTime", "-")),
                "IMEI": net_info.get("imei", "Not Found"),
                "ICCID": translate_status(result.get("sim1", "Not Found")),
                "Device Model": translate_status(result.get("productModel", "-")),
                "Firmware Version": translate_status(_extract_firmware_version(result.get("version"))),
                "Signal Quality (CSQ)": net_info.get("csq", "Not Found"),
                "Network Type": net_info.get("netType", "Not Found"),
                "Address": _extract_address(result),
            }

            # --- Extract 4G signal info from netInfo ---
            signal_info: Dict[str, Any] = {}
            if net_info:
                extracted: Dict[str, Any] = {}
                if "rsrp" in net_info:
                    extracted["RSRP (dBm)"] = net_info["rsrp"]
                if "sinr" in net_info:
                    extracted["SNR (dB)"] = net_info["sinr"]
                elif "snr" in net_info:
                    extracted["SNR (dB)"] = net_info["snr"]
                if "rssi" in net_info:
                    extracted["RSSI (asu)"] = net_info["rssi"]
                if "band" in net_info:
                    extracted["4G Band"] = net_info["band"]
                if extracted:
                    extracted["Latest Signal Time"] = result.get("lastLiveTime", "Unknown")
                    signal_info = extracted

            # /api/profile/get contains modem telemetry that /api/device/get
            # often omits, including LTE band, RSRP, RSRQ and SINR.
            profile_signal = self.get_profile_signal_info(target_sn)
            for key, value in profile_signal.items():
                if key == "Network Type":
                    if value and router_info.get("Network Type") in (None, "", "Not Found", "modem"):
                        router_info["Network Type"] = value
                else:
                    signal_info[key] = value
            if signal_info:
                signal_info.setdefault("Latest Signal Time", result.get("lastLiveTime", "Unknown"))

            logging.info(
                f"[Hongdian] Device {target_sn} query successful, signal fields extracted: {list(signal_info.keys())}"
            )
            return router_info, signal_info

        except requests.exceptions.HTTPError as e:
            logging.error(f"[Hongdian] HTTP error: {str(e)}")
            raise
        except Exception as e:
            logging.error(f"[Hongdian] Request exception: {str(e)}")
            raise
