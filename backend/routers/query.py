import logging
import os
import hmac
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException, Header, Depends

# Allow importing from the parent IoTdeviceInfo package
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from device_info import DeviceInfoFetcher, translate_status
from router_code import RouterCodeFetcher
from inhand_client import InHandApiClient
from hongdian_client import HongdianApiClient
from jc_module_client import JCModuleClient
from hologram_client import HologramApiClient
from pos_client import POSClient
from temperature_client import DashTemperatureClient

from backend.models.schemas import (
    QueryRequest,
    QueryResponse,
    RouterInfoOut,
    SignalInfoOut,
    TemperatureInfoOut,
    SimInfoOut,
    PosInfoOut,
)

router = APIRouter()
_QUERY_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="api-query")


def authorize_query(octopus_token: str | None = Header(default=None),
                    x_service_token: str | None = Header(default=None)) -> None:
    """Never trust a client-supplied API key; Mini Program supplies its user token."""
    service_secret = os.environ.get("BACKEND_SERVICE_TOKEN", "")
    if x_service_token and service_secret and hmac.compare_digest(x_service_token, service_secret):
        return
    if not octopus_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        response = requests.post(
            "https://iot-usa.vendera.ai/iot/machine/page",
            json={"pageSize": 1, "currPage": 1},
            headers={"Octopus-Token": octopus_token}, timeout=5,
        )
        if response.status_code == 200 and str(response.json().get("code")) == "200":
            return
    except (requests.RequestException, ValueError):
        raise HTTPException(status_code=503, detail="Authentication service unavailable") from None
    raise HTTPException(status_code=401, detail="Invalid or expired token")


def _timed_call(stage: str, func, *args, **kwargs):
    started = time.perf_counter()
    try:
        return func(*args, **kwargs)
    finally:
        logging.info("Query stage %s completed in %.3fs", stage, time.perf_counter() - started)


# ---------------------------------------------------------------------------
# Normalization helpers — convert dicts from existing clients into Pydantic models
# ---------------------------------------------------------------------------

def _normalize_router_info(
    raw: dict, platform: str
) -> RouterInfoOut | None:
    if not raw:
        return None
    return RouterInfoOut(
        platform=platform,
        router_sn=raw.get("Router SN", ""),
        online_status=raw.get("Online Status", "Unknown"),
        imei=raw.get("IMEI", "Not Found"),
        iccid=raw.get("ICCID", "Not Found"),
        device_model=raw.get("Device Model", "-"),
        firmware_version=raw.get("Firmware Version", "-"),
        signal_quality_csq=str(raw.get("Signal Quality (CSQ)")) if raw.get("Signal Quality (CSQ)") is not None else None,
        address=raw.get("Address"),
        last_active_time=raw.get("Last Active Time"),
        network_type=raw.get("Network Type"),
        network_latency=raw.get("Network Latency"),
        sim_carrier=raw.get("SIM Carrier"),
        module_serial_no=raw.get("Module Serial No"),
        metadata=raw.get("Router Metadata", {}),
    )


def _normalize_signal_info(raw: dict) -> SignalInfoOut | None:
    if not raw or raw.get("Status"):
        return None
    return SignalInfoOut(
        latest_signal_time=raw.get("Latest Signal Time", "Unknown"),
        rsrp=str(raw.get("RSRP (dBm)", "Not reported")),
        rsrq=str(raw.get("RSRQ (dB)", "Not reported")),
        snr=str(raw.get("SNR (dB)", "Not reported")),
        rssi=str(raw.get("RSSI (dBm)") or raw.get("RSSI (asu)", "Not reported")),
        band=str(raw.get("4G Band", "Not reported")),
    )


def _normalize_sim_info(raw: dict) -> SimInfoOut | None:
    if not raw:
        return None
    return SimInfoOut(
        device_name=str(raw.get("Device Name", "Unknown")),
        sim_status=str(raw.get("SIM Status", "Unknown")),
        iccid=str(raw.get("ICCID", "Unknown")),
        imsi=str(raw.get("IMSI", "Unknown")),
        network=str(raw.get("Network", "Unknown")),
        data_plan=str(raw.get("Data Plan", "Unknown")),
        monthly_data_bytes=raw.get("Monthly Data (Bytes)", 0),
        monthly_data_gb=float(raw.get("Monthly Data (GB)", 0)),
        billing_period_data_bytes=raw.get("Billing Period Data (Bytes)", 0),
        billing_period_data_gb=float(raw.get("Billing Period Data (GB)", 0)),
        billing_period_start=str(raw.get("Billing Period Start", "Unknown")),
        billing_period_end=str(raw.get("Billing Period End", "Unknown")),
        last_active_time=str(raw.get("Last Active Time", "Unknown")),
        session_start_time=str(raw.get("Session Start Time", "Unknown")),
        session_end_time=str(raw.get("Session End Time", "Unknown")),
        session_active=str(raw.get("Session Active", "Unknown")),
    )


def _normalize_pos_info(raw: dict) -> PosInfoOut | None:
    if not raw:
        return None
    return PosInfoOut(
        pos_sn=str(raw.get("POS Serial No", "-")),
        pos_type=str(raw.get("POS Type", "-")),
        merchant_id=str(raw.get("Merchant ID", "-")),
        app_version=str(raw.get("App Version", "-")),
        machine_id=str(raw.get("Machine ID", "-")),
        commercial_use_status=str(raw.get("Commercial Use Status", "-")),
        pre_auth_amount=str(raw.get("Pre-Auth Amount", "-")),
        pos_status=str(raw.get("POS Status", "-")),
        pos_net_status=str(raw.get("Network Status", "-")),
        cancelled=str(raw.get("Cancelled", "-")),
        created=str(raw.get("Created", "-")),
    )


# ---------------------------------------------------------------------------
# Individual API call wrappers (graceful degradation on failure)
# ---------------------------------------------------------------------------

def _resolve_ids(
    device_id: str | None, router_sn: str | None
) -> tuple[str | None, str | None, dict]:
    """Resolve device/router IDs through dash, with app-boss fallback."""
    fetcher = RouterCodeFetcher()

    if device_id and not router_sn:
        record = fetcher.get_router_record(device_id)
        sn = record.get("code") if record else None
        if sn:
            return device_id, sn, record or {}
        logging.warning(f"SmartCabinet forward lookup: no router SN found for device {device_id}")
        return device_id, None, {}

    if router_sn and not device_id:
        record = fetcher.get_router_record_by_code(router_sn)
        did = record.get("machineId") if record else None
        if did:
            return did, router_sn, record or {}
        logging.warning(f"SmartCabinet reverse lookup: no device ID found for router SN {router_sn}")
        return None, router_sn, {}

    record = fetcher.get_router_record_by_code(router_sn) if router_sn else {}
    return device_id, router_sn, record or {}


def _fetch_router(router_sn: str, device_id: str | None = None) -> tuple[dict | None, dict | None, str]:
    """Fetch router metadata + signal info. Returns (router_dict, signal_dict, platform)."""
    if router_sn.upper().startswith("RF"):
        try:
            client = InHandApiClient()
            router_info = client.get_router_by_sn(router_sn)
            internal_id = router_info.get("Device ID (InHand)", "")
            signal_info = {}
            if internal_id:
                try:
                    signal_info = client.get_4g_signal_info(internal_id)
                except Exception as e:
                    logging.warning(f"InHand signal query failed: {e}")
            return router_info, signal_info, "inhand"
        except Exception as e:
            logging.error(f"InHand router query failed: {e}")
            return None, None, "inhand"
    elif router_sn.upper().startswith("JC"):
        try:
            client = JCModuleClient()
            machine_code = device_id or ""
            router_info, signal_info = client.get_4g_module_info(router_sn, machine_code)
            return router_info, signal_info if signal_info else None, "jc_module"
        except Exception as e:
            logging.error(f"JC 4G module query failed: {e}")
            return None, None, "jc_module"
    else:
        try:
            client = HongdianApiClient()
            router_info, signal_info = client.get_router_by_sn(router_sn)
            return router_info, signal_info if signal_info else None, "hongdian"
        except Exception as e:
            logging.error(f"Hongdian router query failed: {e}")
            return None, None, "hongdian"


def _fetch_sim(router_info: dict | None) -> dict | None:
    if not router_info:
        return None
    iccid = router_info.get("ICCID", "")
    imei = router_info.get("IMEI", "")
    if not iccid or iccid == "Not Found":
        if not imei or imei == "Not Found":
            return None
    try:
        client = HologramApiClient()
        return client.get_hologram_sim_info(iccid, imei)
    except Exception as e:
        logging.error(f"Hologram SIM query failed: {e}")
        return None


def _fetch_temperature(device_id: str) -> dict | None:
    try:
        return DashTemperatureClient().get_temperature(device_id)
    except Exception as e:
        logging.error(f"Dash temperature query failed: {e}")
        return None


def _fetch_pos(device_id: str) -> dict | None:
    try:
        client = POSClient()
        result = client.get_pos_info(device_id)
        return result if result else None
    except Exception as e:
        logging.error(f"POS query failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@router.post("/api/query", response_model=QueryResponse, dependencies=[Depends(authorize_query)])
def handle_query(req: QueryRequest) -> QueryResponse:
    device_id = req.device_id.strip() if req.device_id else None
    router_sn = req.router_sn.strip() if req.router_sn else None

    if not device_id and not router_sn:
        raise HTTPException(
            status_code=400,
            detail="At least one of device_id or router_sn is required",
        )

    # Step 1: Resolve IDs via SmartCabinet if needed. Keep this record and pass it
    # through the rest of the request; otherwise the association is queried again.
    device_id, router_sn, router_metadata = _timed_call(
        "router-association", _resolve_ids, device_id, router_sn
    )

    # Step 1b: Temperature and POS are independent and both require device_id.
    temperature_info = None
    pos_info = None
    if device_id:
        futures = {
            "temperature": _QUERY_EXECUTOR.submit(
                _timed_call, "temperature", _fetch_temperature, device_id
            ),
            "pos": _QUERY_EXECUTOR.submit(
                _timed_call, "pos", _fetch_pos, device_id
            ),
        }
        try:
            raw_temperature = futures["temperature"].result()
            temperature_info = TemperatureInfoOut(**raw_temperature) if raw_temperature else None
        except Exception as e:
            logging.error("Temperature query failed: %s", e)
        try:
            raw_pos = futures["pos"].result()
            pos_info = _normalize_pos_info(raw_pos)
        except Exception as e:
            logging.error("POS query failed: %s", e)

    # Step 2: Router metadata + signal
    router_info = None
    signal_info = None
    platform = "unknown"
    if router_sn:
        raw_router, raw_signal, platform = _timed_call(
            "router-signal", _fetch_router, router_sn, device_id
        )
        if raw_router is None:
            raw_router = {}
        if router_metadata:
            raw_router.update({
                "Router SN": router_metadata.get("code", router_sn),
                "Router Metadata": router_metadata,
            })
            raw_router.setdefault("IMEI", router_metadata.get("imei", "Not Found"))
            raw_router.setdefault(
                "Device Model",
                router_metadata.get("model") or router_metadata.get("brand") or "-",
            )
        router_info = _normalize_router_info(raw_router, platform) if (raw_router or router_metadata) else None
        signal_info = _normalize_signal_info(raw_signal) if raw_signal else None

    # Step 3: SIM info via Hologram (requires router metadata)
    sim_info = None
    if router_sn:
        raw_sim = _timed_call("hologram-sim", _fetch_sim, raw_router) if raw_router else None
        sim_info = _normalize_sim_info(raw_sim)

    return QueryResponse(
        device_id=device_id or None,
        router_sn=router_sn or None,
        router_info=router_info,
        signal_info=signal_info,
        temperature_info=temperature_info,
        sim_info=sim_info,
        pos_info=pos_info,
    )
