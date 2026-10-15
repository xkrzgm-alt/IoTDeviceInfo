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
2. **Router** — `inhand_client.py` (OAuth2, prefix `RF*`), `jc_module_client.py` (Octopus-Token, prefix `JC*`, vendera.ai IoT), or `hongdian_client.py` (Hongdian `Authentication` token, other prefixes) → IMEI/ICCID/firmware + 4G signal. Hongdian signal enrichment also calls `/api/profile/get?idSn=<router_sn>` and safely extracts modem `netBand`, `rsrp`, `rsrq`, and `sinr` without returning the full profile configuration.
3. **SIM** — `hologram_client.py`: Hologram cellular API (API key) → SIM state, data plan, usage
4. **POS** — `pos_client.py`: dash.vendera.ai (Bearer login) → POS reader info

All API clients self-handle auth (token refresh on 401). GUI queries run in background thread.

### Backend (`backend/`)

FastAPI serving `POST /api/query` (accepts `device_id`/`router_sn`, returns aggregated results) for two consumers:
- **miniprogram-1** — calls vendera.ai device info directly with user token; all other APIs proxied through backend
- **HWProgM `/device-search`** — proxies to backend for router/signal/SIM/POS; queries vendera.ai device info locally

Graceful degradation: each sub-query wrapped in try/except, partial results returned on failure.

Production: `iot-backend.service` runs Uvicorn on `127.0.0.1:8080` at `/root/IoTdeviceInfo/` on Aliyun ECS, with Nginx proxying `/api/query` and `/health`.

### Deployment workflow

> `docker-compose.yml` is an existing container deployment definition, but it is not the current production process. It builds `Dockerfile`, loads `.env.deploy`, maps host port `8000` to container port `8000`, and uses `restart: unless-stopped`. The current Aliyun deployment runs Uvicorn directly on host port `8080`; `docker compose ps` currently shows no active IoT container. Do not switch deployment methods without also coordinating the port, environment file, and process ownership.

1. Run the local checks: `python -m pytest -q tests` and `python -m compileall -q .`. The repeatable deployment command is `./deploy_fastapi.sh` (or `SKIP_TESTS=1 ./deploy_fastapi.sh` after local checks).
2. `deploy_fastapi.sh` backs up code, uploads `config.py`, `hongdian_client.py`, `jc_module_client.py`, `backend/routers/query.py`, and `backend/models/schemas.py`, compiles remotely, restarts `iot-backend.service` via systemd, and retries `curl http://127.0.0.1:8080/health`. Deployment of the authenticated query endpoint must be coordinated with backend/dashboard secrets and the Mini Program release.
3. Manage credentials separately using `ops/credentials/sync_aliyun.py` (SOPS-encrypted inventory). It writes root-only `/etc/vendera/common.env` and `/etc/vendera/iotdeviceinfo.env` for the systemd service. Do not use `UPDATE_DEVICE_CREDENTIALS=1`: it now fails by design. The old remote `.env` is retained until migration verification; restrict it to mode 0600 and remove it later. The `/api/query` endpoint requires a user Octopus token or server-only `BACKEND_SERVICE_TOKEN`.
4. If manual deployment is required, back up remote files before copying, compile remotely, restart `iot-backend.service` via systemd, verify the health endpoint, and confirm the unit with `systemctl status iot-backend`.

Router lookup deployment behavior: dash.vendera.ai is the default source, using `DASH_USER` / `DASH_PWD`; app-boss is the fallback, using the SmartCabinet credentials. Dash `code` is mapped to `Router SN`, and dash router metadata is returned in both GUI and FastAPI results.

### Key files

| File | Role |
|------|------|
| `main.py` | GUI + orchestrator |
| `config.py` | Env vars via python-dotenv (workspace cascade loading) |
| `device_info.py` | vendera.ai IoT client + `translate_status()` CN→EN |
| `backend/main.py` | FastAPI app with CORS |
| `backend/routers/query.py` | Orchestration mirroring `collect_device_data()` |
| `deploy_fastapi.sh` | Automated Aliyun backup, upload, restart, and health-check workflow |
| `8959Test.py` | Standalone CLI prototype (not imported by GUI) |

Status labels translated via `CN_TO_EN` dict in `device_info.py`. `config.py` uses `os.environ.get()` with hardcoded fallbacks.
