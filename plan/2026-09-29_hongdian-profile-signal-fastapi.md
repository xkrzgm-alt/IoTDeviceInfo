# Plan: Add Hongdian profile signal data to FastAPI

## Context
`GET /api/device/get` does not provide detailed LTE metrics for Hongdian routers. Testing showed `GET /api/profile/get?idSn=<router_sn>` returns modem data under `result.profile.props.net.modem`, including `netBand`, `rsrp`, `rsrq`, and `sinr`. The existing FastAPI backend in `IoTdeviceInfo/backend/` is consumed by the other project and should expose these additional values without returning the sensitive router profile/configuration.

## Approach
1. Extend the Hongdian client with a focused profile request using the existing `HONGDIAN_BASE_URL` and `HONGDIAN_TOKEN` configuration.
2. Extract only safe modem fields from `result.profile.props.net.modem`:
   - Band: `netBand`
   - RSRP: `rsrp`
   - RSRQ: `rsrq`
   - SINR: `sinr`
   - Optionally preserve useful context such as operator, network mode/type, CSQ, IMEI, and ICCID.
3. Merge profile signal values with the existing `/api/device/get` result for Hongdian routers. Keep graceful degradation: if the profile request fails, return the existing router data and signal values.
4. Update `backend/models/schemas.py` so the FastAPI response exposes Band, RSRP, RSRQ, and SINR consistently. Preserve compatibility with the current response shape and existing consumers.
5. Update the desktop-facing normalization/display path if needed so the GUI and backend use the same signal field names, while ensuring the full profile response and credentials are never logged or returned.
6. Add tests using mocked Hongdian responses for: successful profile extraction, missing modem data, profile request failure, and correct merging/normalization.
7. Update project documentation/deployment notes if the endpoint behavior or returned fields changes.

## Files expected to change
- `hongdian_client.py` — profile endpoint request and safe field extraction.
- `backend/routers/query.py` — invoke profile lookup and normalize the extra metrics.
- `backend/models/schemas.py` — add response fields for Band/RSRP/RSRQ/SINR as appropriate.
- `main.py` — display the additional fields in the GUI if the shared client result is expanded.
- `tests/` — mocked API and FastAPI response coverage.
- `CLAUDE.md` or relevant API documentation — describe the new Hongdian signal source and fallback behavior.

## Verification
- Run `python -m pytest -q IoTdeviceInfo/tests`.
- Run `python -m compileall -q IoTdeviceInfo`.
- Exercise `POST /api/query` with a known HD router and verify Band/RSRP/RSRQ/SINR are returned.
- Verify behavior when `/api/profile/get` is unavailable or returns no modem section.
- Confirm logs and API responses do not contain the raw profile configuration, passwords, keys, or other sensitive fields.
- If deploying, follow the existing IoTdeviceInfo backup/upload/restart/health-check procedure and separately coordinate the other project's deployment.
