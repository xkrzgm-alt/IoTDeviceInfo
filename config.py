import os
import sys
import logging
from pathlib import Path

from dotenv import dotenv_values

# --- Resolve paths (works in both dev and PyInstaller-frozen builds) ---
if getattr(sys, "frozen", False):
    # PyInstaller exe is typically in dist/ subdirectory
    _EXE_DIR = Path(sys.executable).resolve().parent
    _PROJECT_ROOT = _EXE_DIR.parent  # go up from dist/ to project root
else:
    _PROJECT_ROOT = Path(__file__).resolve().parent

# Local cascade: common → project, with external (systemd) environment highest.
_workspace = _PROJECT_ROOT.parent
_external_keys = set(os.environ)
for _p in (_workspace / ".env.vendera", _PROJECT_ROOT / ".env"):
    if _p.exists():
        for _key, _value in dotenv_values(_p).items():
            if _key not in _external_keys and _value is not None:
                os.environ[_key] = _value

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")


def _require(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


# --- Device_Info config (Octopus-Token login) ---
DEVICE_INFO_LOGIN_URL = os.environ.get("DEVICE_INFO_LOGIN_URL", "https://iot-usa.vendera.ai/iot/user/login")
DEVICE_INFO_USER = _require("DEVICE_INFO_USER")
DEVICE_INFO_PWD = _require("DEVICE_INFO_PWD")

# --- SmartCabinet / Router Code config (Bearer Token login) ---
# Loaded from ../.env.vendera (shared); override in project .env if needed
ROUTER_CODE_LOGIN_URL = os.environ.get(
    "SMARTCABINET_LOGIN_URL",
    "https://app-boss-usa.vendera.ai/prod-api/auth/login",
)
ROUTER_CODE_CLIENT_ID = _require("SMARTCABINET_CLIENT_ID")
ROUTER_CODE_TENANT_ID = _require("SMARTCABINET_TENANT_ID")
ROUTER_CODE_PUB_KEY = _require("SMARTCABINET_PUB_KEY")
ROUTER_CODE_USER = _require("SMARTCABINET_USER")
ROUTER_CODE_PWD = _require("SMARTCABINET_PWD")
ROUTER_CODE_QUERY_URL = os.environ.get(
    "SMARTCABINET_QUERY_URL",
    "https://app-boss-usa.vendera.ai/prod-api/cabinet/routerInfo/list",
)

# --- Dash.vendera.ai config ---
DASH_USER = _require("DASH_USER")
DASH_PWD = _require("DASH_PWD")
DASH_API_BASE_URL = os.environ.get("DASH_API_BASE_URL", "https://dash.vendera.ai/api")
POS_LOGIN_URL = os.environ.get("POS_LOGIN_URL", f"{DASH_API_BASE_URL}/auth/login")
POS_QUERY_URL = os.environ.get("POS_QUERY_URL", f"{DASH_API_BASE_URL}/pos")
DASH_ROUTER_LOGIN_URL = os.environ.get("DASH_ROUTER_LOGIN_URL", f"{DASH_API_BASE_URL}/auth/login")
DASH_ROUTER_QUERY_URL = os.environ.get(
    "DASH_ROUTER_QUERY_URL", "https://dash.vendera.ai/api/routers"
)

# --- InHand Device Manager config ---
DM_BASE_URL = os.environ.get("DM_BASE_URL", "https://iot.inhandnetworks.com")
DM_CLIENT_ID = _require("DM_CLIENT_ID")
DM_CLIENT_SECRET = _require("DM_CLIENT_SECRET")
DM_USERNAME = _require("DM_USERNAME")
DM_PASSWORD = _require("DM_PASSWORD")

# --- Hologram config ---
HOLOGRAM_API_KEY = _require("HOLOGRAM_API_KEY")
HOLOGRAM_BASE_URL = os.environ.get("HOLOGRAM_BASE_URL", "https://dashboard.hologram.io/api/1")
HOLOGRAM_ORG_ID = _require("HOLOGRAM_ORG_ID")
HOLOGRAM_USAGE_CACHE_TTL = int(os.environ.get("HOLOGRAM_USAGE_CACHE_TTL", "300"))

# --- Hongdian router northbound API config ---
HONGDIAN_BASE_URL = os.environ.get("HONGDIAN_BASE_URL", "https://sandora.hongdian.com")
HONGDIAN_TOKEN = _require("HONGDIAN_TOKEN")

# --- JC 4G Module config (vendera.ai IoT network logs) ---
# Reuses DEVICE_INFO_USER / DEVICE_INFO_PWD for Octopus-Token auth.
JC_MODULE_LOG_URL = os.environ.get(
    "JC_MODULE_LOG_URL",
    "https://iot-usa.vendera.ai/iot/machine/logs/network/status",
)
