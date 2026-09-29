# Speed up IoTdeviceInfo device-info loading

## Context

The current GUI query runs `collect_device_data()` in one worker thread, but the individual network calls are mostly sequential. The FastAPI endpoint is a synchronous `def` handler and is also sequential, so each request occupies a worker while waiting on external APIs. Most clients create a fresh client and authenticate for every query.

Observed query paths:

- Device ID: Octopus login → device list → device run detail → router association lookup → POS login/query → router query → SIM lookup/device detail → calendar-month usage pagination.
- Router SN: router association lookup → Octopus device login/detail (if resolved) → POS → router/signal → SIM.
- Hologram alone can make up to four network operations: SIM search, device detail, and one or more usage pages.
- InHand signal lookup may add a second device request for the band.
- Dash router, Dash POS, and Dash temperature clients each authenticate independently.

## Main opportunities, prioritized

1. **Measure first and add timing telemetry**
   - Add per-stage elapsed-time logging and a request correlation ID in `main.py` and `backend/routers/query.py`.
   - Record cold vs warm auth, lookup, router, POS, temperature, SIM, and Hologram usage timings.
   - Test representative device IDs and router types (RF, JC, Hongdian), including API failures/timeouts, before changing behavior.

2. **Parallelize independent calls**
   - In `main.py`, after IDs/router metadata are known, run POS and router retrieval concurrently; run temperature where applicable in the backend concurrently as well.
   - After router data yields ICCID/IMEI, run SIM enrichment independently of unrelated formatting work.
   - Use a bounded `ThreadPoolExecutor` for the synchronous `requests` clients, preserve graceful degradation, and avoid unbounded threads per request.
   - For the backend, either keep the orchestration in a controlled thread pool or convert the endpoint/client stack consistently to async; do not mix ad hoc async wrappers with blocking calls.

3. **Reuse authenticated sessions/tokens**
   - Introduce shared, thread-safe client/session providers for the Dash family, Octopus, and InHand rather than logging in through each newly constructed client.
   - Use `requests.Session` for connection pooling and keep-alive.
   - Cache tokens with expiry/401 refresh and synchronize refresh so concurrent calls do not cause duplicate logins.
   - Ensure credentials and tokens never enter logs or cache keys.

4. **Reduce unnecessary calls and payload sizes**
   - Avoid duplicate router association lookups: retain the record resolved during ID normalization and pass it through the pipeline.
   - For a device-ID lookup, consider returning the router association and device data from a single backend aggregation/cache path.
   - Reduce list/page sizes to the minimum supported by each API and request only fields/records needed for the summary.
   - Make temperature history optional or request a current-only endpoint if the consumer does not render history.
   - Avoid Hologram calendar-month usage on the critical path by making it a “details/refresh usage” operation, or cache it for a short TTL; it is the most variable and potentially paginated call.
   - Avoid the extra InHand device-detail request when the signal endpoint already provides band, or make band enrichment optional.

5. **Add short-lived result caching and stale-while-refresh**
   - Cache router association, device metadata, POS, and relatively stable SIM identity fields by normalized ID with separate TTLs.
   - Use a short TTL for operating status/signal and a longer TTL for POS/router metadata; never cache credentials or unbounded Hologram usage pages.
   - For the GUI, show cached data immediately and refresh volatile fields in the background if product behavior permits.
   - Add explicit invalidation and bounded cache size to prevent stale associations and memory growth.

6. **Improve timeout and failure behavior**
   - Replace uniform 10-second timeouts with connect/read timeouts appropriate to each API and enforce an overall query deadline.
   - Fail or return partial results quickly for optional POS, temperature, and usage calls.
   - Add retry only for safe transient failures, with small bounded backoff; do not retry authentication or all 4xx responses.

## Files likely to change

- `IoTdeviceInfo/main.py`: staged/concurrent GUI orchestration, optional deferred usage, timing logs.
- `IoTdeviceInfo/backend/routers/query.py`: shared orchestration, bounded concurrency, duplicate lookup removal, request deadline.
- `IoTdeviceInfo/router_code.py`, `pos_client.py`, `temperature_client.py`: shared Dash session/token provider.
- `IoTdeviceInfo/device_info.py`, `jc_module_client.py`, `inhand_client.py`: shared auth/session and timeout handling.
- `IoTdeviceInfo/hologram_client.py`: separate fast SIM identity from usage aggregation and add TTL-aware usage behavior.
- `IoTdeviceInfo/config.py`: feature flags, TTLs, concurrency limits, and timeout settings.
- `IoTdeviceInfo/tests/`: deterministic timing/concurrency, token reuse, cache expiry, partial failure, and deadline tests.

## Recommended implementation order

1. Instrument and establish a latency baseline.
2. Remove duplicate calls and defer/paginate Hologram usage.
3. Reuse sessions/tokens.
4. Add bounded parallelism for independent stages.
5. Add carefully scoped TTL caches and stale-while-refresh if the measured latency still warrants it.
6. Tune timeouts/retries and verify production behavior.

## Verification

- Run `python -m pytest -q IoTdeviceInfo/tests` and `python -m compileall -q IoTdeviceInfo`.
- Add mocked tests asserting independent calls overlap, each auth endpoint is called once per token lifetime, duplicate router lookups are absent, and one slow/failed optional API does not block the complete response.
- Compare p50/p95 end-to-end latency for cold and warm queries by router type and input mode.
- Verify GUI responsiveness, FastAPI concurrent-request throughput, partial-result semantics, token refresh, cache invalidation, and no credential/token leakage in logs.
