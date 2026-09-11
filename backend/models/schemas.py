from typing import Optional
from pydantic import BaseModel


class QueryRequest(BaseModel):
    device_id: Optional[str] = None
    router_sn: Optional[str] = None


class RouterInfoOut(BaseModel):
    platform: str  # "inhand" | "hongdian" | "jc_module"
    router_sn: str
    online_status: str
    imei: str
    iccid: str
    device_model: str
    firmware_version: str
    signal_quality_csq: Optional[str] = None  # Hongdian only
    address: Optional[str] = None  # InHand only
    last_active_time: Optional[str] = None
    network_type: Optional[str] = None  # Hongdian only (e.g. "4G", "LTE")
    network_latency: Optional[str] = None  # JC module only
    sim_carrier: Optional[str] = None  # JC module only
    module_serial_no: Optional[str] = None  # JC module only


class SignalInfoOut(BaseModel):
    latest_signal_time: str
    rsrp: str
    snr: str
    rssi: str
    band: str


class SimInfoOut(BaseModel):
    device_name: str
    sim_status: str
    iccid: str
    imsi: str
    network: str
    data_plan: str
    monthly_data_bytes: int
    monthly_data_gb: float
    last_active_time: str
    billing_period_data_bytes: int
    billing_period_data_gb: float
    billing_period_start: str
    billing_period_end: str
    session_start_time: str
    session_end_time: str
    session_active: str


class PosInfoOut(BaseModel):
    pos_sn: str
    pos_type: str
    merchant_id: str
    app_version: str
    machine_id: str
    commercial_use_status: str
    pre_auth_amount: str
    pos_status: str
    pos_net_status: str
    cancelled: str
    created: str


class QueryResponse(BaseModel):
    device_id: Optional[str] = None
    router_sn: Optional[str] = None
    router_info: Optional[RouterInfoOut] = None
    signal_info: Optional[SignalInfoOut] = None
    sim_info: Optional[SimInfoOut] = None
    pos_info: Optional[PosInfoOut] = None
