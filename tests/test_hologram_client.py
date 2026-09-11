import unittest
from unittest.mock import patch

from hologram_client import HologramApiClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class HologramApiClientTests(unittest.TestCase):
    def setUp(self):
        self.client = HologramApiClient()

    def test_decimal_gb_and_billing_period(self):
        self.assertEqual(self.client._bytes_to_gb(10_095_141_716), 10.1)
        self.assertEqual(
            self.client._billing_period("2026-09-19 06:01:42"),
            ("2026-08-20 06:01:42", "2026-09-19 06:01:42"),
        )

    @patch("hologram_client.requests.get")
    def test_calendar_month_usage_sums_all_pages(self, mock_get):
        mock_get.side_effect = [
            FakeResponse({
                "data": [{"bytes": 1_500_000_000}, {"bytes": 500_000_000}],
                "continues": True,
                "lastid": 123,
            }),
            FakeResponse({
                "data": [{"bytes": 2_665_642_967}],
                "continues": False,
            }),
        ]

        self.assertEqual(self.client._get_calendar_month_usage(5378298), 4_665_642_967)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[0].kwargs["params"]["linkid"], 5378298)
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["startafter"], 123)

    @patch.object(HologramApiClient, "_get_calendar_month_usage", side_effect=RuntimeError("unavailable"))
    @patch("hologram_client.requests.get")
    def test_usage_failure_keeps_sim_and_billing_data(self, mock_get, _mock_usage):
        mock_get.side_effect = [
            FakeResponse({"data": [{
                "id": 5378298,
                "deviceid": 4696520,
                "devicename": "HB100654US",
                "sim": "test-iccid",
                "imsi": 123,
                "state": "LIVE",
            }]}),
            FakeResponse({"data": {
                "name": "HB100654US",
                "links": {"cellular": [{
                    "id": 5378298,
                    "whenexpires": "2026-09-19 06:01:42",
                    "cur_billing_data_used": 10_095_141_716,
                    "plan": {"name": "Test Plan"},
                }]},
            }}),
        ]

        result = self.client.get_hologram_sim_info("test-iccid", "")

        self.assertIsNotNone(result)
        self.assertEqual(result["Monthly Data (GB)"], 0.0)
        self.assertEqual(result["Billing Period Data (GB)"], 10.1)
        self.assertEqual(result["Billing Period Start"], "2026-08-20 06:01:42")
        self.assertEqual(result["Billing Period End"], "2026-09-19 06:01:42")


if __name__ == "__main__":
    unittest.main()
