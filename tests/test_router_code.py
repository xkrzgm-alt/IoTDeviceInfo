import unittest
from unittest.mock import patch

from router_code import DashRouterFetcher, RouterCodeFetcher


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class RouterCodeTests(unittest.TestCase):
    @patch("router_code.requests.get")
    @patch("router_code.requests.post")
    def test_dash_lookup_returns_router_metadata(self, mock_post, mock_get):
        mock_post.return_value = FakeResponse({"code": 200, "data": {"token": "dash-token"}})
        mock_get.return_value = FakeResponse({
            "code": 200,
            "data": {"records": [{
                "code": "ROUTER-1",
                "machineId": "MACHINE-1",
                "imei": "123",
                "brand": "Brand",
                "model": "Model",
            }]},
        })

        record = DashRouterFetcher().get_router_record("MACHINE-1")

        self.assertEqual(record["code"], "ROUTER-1")
        self.assertEqual(record["model"], "Model")
        self.assertEqual(mock_get.call_args.kwargs["params"]["machineId"], "MACHINE-1")

    @patch.object(DashRouterFetcher, "get_router_record", return_value=None)
    @patch("router_code.AppBossRouterFetcher.get_router_record")
    def test_app_boss_is_fallback(self, mock_app_boss, _mock_dash):
        mock_app_boss.return_value = {
            "code": "LEGACY-1",
            "machineId": "MACHINE-1",
        }

        record = RouterCodeFetcher().get_router_record("MACHINE-1")

        self.assertEqual(record["code"], "LEGACY-1")
        mock_app_boss.assert_called_once_with("MACHINE-1")


if __name__ == "__main__":
    unittest.main()
