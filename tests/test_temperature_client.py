import unittest
from unittest.mock import patch

from temperature_client import DashTemperatureClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TemperatureClientTests(unittest.TestCase):
    @patch("temperature_client.requests.get")
    @patch("temperature_client.requests.post")
    def test_get_temperature_maps_dash_payload(self, mock_post, mock_get):
        mock_post.return_value = FakeResponse({"code": 200, "data": {"token": "token"}})
        mock_get.return_value = FakeResponse({
            "code": 200,
            "data": {
                "currentTemperature": {"fahrenheit": 41.0, "celsius": 5.0},
                "binding": {"deviceId": "MACHINE-1"},
                "policy": {},
                "records": [{"averageFahrenheit": 41.0}],
            },
        })

        result = DashTemperatureClient().get_temperature("MACHINE-1", range_hours=24)

        self.assertEqual(result["current_temperature"]["fahrenheit"], 41.0)
        self.assertEqual(mock_get.call_args.kwargs["params"], {"rangeHours": 24})

    @patch("temperature_client.requests.get")
    @patch("temperature_client.requests.post")
    def test_missing_machine_returns_none(self, mock_post, mock_get):
        mock_post.return_value = FakeResponse({"code": 200, "data": {"token": "token"}})
        mock_get.return_value = FakeResponse({"code": 500, "message": "Machine not found", "data": None})

        self.assertIsNone(DashTemperatureClient().get_temperature("MISSING"))


if __name__ == "__main__":
    unittest.main()
