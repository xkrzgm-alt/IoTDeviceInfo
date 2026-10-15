from datetime import datetime, timedelta
from unittest.mock import patch

from jc_module_client import JCModuleClient, _is_recent_telemetry


def test_recent_naive_telemetry_is_online():
    now = datetime(2026, 10, 15, 10, 5)
    assert _is_recent_telemetry("2026-10-15T10:04:22.502", now)
    assert not _is_recent_telemetry("2026-10-15T09:40:00", now)


def test_missing_network_record_uses_recent_telemetry():
    telemetry = {
        "current_temperature": {
            "updatedAt": (datetime.now() - timedelta(minutes=2)).isoformat()
        }
    }
    client = JCModuleClient()
    with (
        patch.object(client, "_query_network_status", return_value={}),
        patch(
            "jc_module_client.DashTemperatureClient.get_temperature",
            return_value=telemetry,
        ),
    ):
        router, signal = client.get_4g_module_info("JC123", "HB123")

    assert router["Online Status"] == "[Online (recent device telemetry)]"
    assert router["Status Source"] == "Dash temperature telemetry"
    assert signal == {}


def test_missing_network_record_without_recent_telemetry_is_unknown():
    client = JCModuleClient()
    with (
        patch.object(client, "_query_network_status", return_value={}),
        patch(
            "jc_module_client.DashTemperatureClient.get_temperature",
            return_value={"current_temperature": {"updatedAt": "2020-01-01T00:00:00"}},
        ),
    ):
        router, _ = client.get_4g_module_info("JC123", "HB123")

    assert router["Online Status"] == "[Unknown]"
    assert router["Status Source"] == "IoT module status unavailable"


def test_unrecognized_explicit_status_is_unknown():
    client = JCModuleClient()
    with patch.object(
        client,
        "_query_network_status",
        return_value={"status": None, "statusName": "-", "reportTime": "now"},
    ):
        router, _ = client.get_4g_module_info("JC123", "HB123")

    assert router["Online Status"] == "[Unknown]"
