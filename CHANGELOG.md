# Changelog

## 2026-09-11

### SIM usage reporting

- Added current UTC calendar-month SIM usage aggregation from Hologram session records.
- Added current 30-day billing-period usage and billing-period start/end fields to the FastAPI response.
- Standardized Hologram usage display on decimal GB (`1 GB = 1,000,000,000 bytes`).
- Preserved partial SIM results when the calendar-month usage endpoint is unavailable.
