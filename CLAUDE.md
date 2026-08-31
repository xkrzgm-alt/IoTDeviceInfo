# IoTdeviceInfo — Device Query Tool

Python 3.13 tkinter GUI + FastAPI backend for querying IoT vending-machine device status across multiple platforms.

## Commands

```bash
python main.py                              # GUI
uvicorn backend.main:app --reload --port 8000  # backend
python -m PyInstaller DeviceQueryTool.spec --distpath dist --workpath build --clean  # Windows .exe
```

## Architecture

### Query pipeline (GUI: `main.py` → `collect_device_data()`)

1. **Device info** — `device_info.py`: vendera.ai IoT platform (Octopus-Token auth) → device details + operating signals + Router SN lookup
2. **Router** — `inhand_client.py` (OAuth2, prefix `RF*`), `jc_module_client.py` (Octopus-Token, prefix `JC*`, vendera.ai IoT), or `hongdian_client.py` (bearer token, other prefixes) → IMEI/ICCID/firmware + 4G signal
3. **SIM** — `hologram_client.py`: Hologram cellular API (API key) → SIM state, data plan, usage
4. **POS** — `pos_client.py`: dash.vendera.ai (Bearer login) → POS reader info

All API clients self-handle auth (token refresh on 401). GUI queries run in background thread.

### Backend (`backend/`)

FastAPI serving `POST /api/query` (accepts `device_id`/`router_sn`, returns aggregated results) for two consumers:
- **miniprogram-1** — calls vendera.ai device info directly with user token; all other APIs proxied through backend
- **HWProgM `/device-search`** — proxies to backend for router/signal/SIM/POS; queries vendera.ai device info locally

Graceful degradation: each sub-query wrapped in try/except, partial results returned on failure.

Production: `uvicorn backend.main:app --host 0.0.0.0 --port 8080` at `/root/IoTdeviceInfo/` on Aliyun ECS.

### Key files

| File | Role |
|------|------|
| `main.py` | GUI + orchestrator |
| `config.py` | Env vars via python-dotenv (workspace cascade loading) |
| `device_info.py` | vendera.ai IoT client + `translate_status()` CN→EN |
| `backend/main.py` | FastAPI app with CORS |
| `backend/routers/query.py` | Orchestration mirroring `collect_device_data()` |
| `8959Test.py` | Standalone CLI prototype (not imported by GUI) |

Status labels translated via `CN_TO_EN` dict in `device_info.py`. `config.py` uses `os.environ.get()` with hardcoded fallbacks.
