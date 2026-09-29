import unittest
from unittest.mock import patch

from hongdian_client import HongdianApiClient


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class HongdianApiClientTests(unittest.TestCase):
    @staticmethod
    def device_payload():
        return {
            "success": True,
            "result": {
                "onlineStatus": "online",
                "lastLiveTime": "2026-09-25 12:00:00",
                "productModel": "H8959",
                "netInfo": {"csq": 20, "imei": "123", "netType": "modem"},
                "sim1": "456",
            },
        }

    @staticmethod
    def profile_payload():
        return {
            "success": True,
            "result": {
                "profile": {
                    "props": {
                        "net": {
                            "modem": {
                                "netBand": "4",
                                "netType": "4G",
                                "rsrp": -87,
                                "rsrq": -8,
                                "sinr": 27,
                                "rssi": -65,
                            }
                        }
                    }
                }
            },
        }

    @patch("hongdian_client.requests.get")
    def test_profile_signal_fields_are_merged_without_returning_profile(self, mock_get):
        mock_get.side_effect = [
            FakeResponse(self.device_payload()),
            FakeResponse(self.profile_payload()),
        ]

        router, signal = HongdianApiClient().get_router_by_sn("HD-1")

        self.assertEqual(signal["4G Band"], "4")
        self.assertEqual(signal["RSRP (dBm)"], -87)
        self.assertEqual(signal["RSRQ (dB)"], -8)
        self.assertEqual(signal["SNR (dB)"], 27)
        self.assertEqual(signal["RSSI (dBm)"], -65)
        self.assertEqual(router["Network Type"], "4G")
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"], {"idSn": "HD-1"})

    @patch("hongdian_client.requests.get")
    def test_newer_profile_layout_extracts_system_net_modem(self, mock_get):
        mock_get.return_value = FakeResponse({
            "success": True,
            "result": {
                "profile": {
                    "props": {
                        "system": {
                            "net": {
                                "modem": {
                                    "netBand": "2",
                                    "netType": "4G",
                                    "rsrp": -95,
                                    "rsrq": -10,
                                    "sinr": 8,
                                    "csq": 17,
                                }
                            }
                        }
                    }
                }
            },
        })

        signal = HongdianApiClient().get_profile_signal_info("HD-1")

        self.assertEqual(signal["4G Band"], "2")
        self.assertEqual(signal["RSRP (dBm)"], -95)
        self.assertEqual(signal["RSRQ (dB)"], -10)
        self.assertEqual(signal["SNR (dB)"], 8)
        self.assertEqual(signal["Network Type"], "4G")

    @patch("hongdian_client.requests.get")
    def test_profile_failure_keeps_basic_device_query_working(self, mock_get):
        mock_get.side_effect = [
            FakeResponse(self.device_payload()),
            RuntimeError("profile unavailable"),
        ]

        router, signal = HongdianApiClient().get_router_by_sn("HD-1")

        self.assertEqual(router["Online Status"], "[Online]")
        self.assertNotIn("4G Band", signal)
        self.assertNotIn("RSRP (dBm)", signal)

    @patch("hongdian_client.requests.get")
    def test_profile_without_modem_returns_empty_signal(self, mock_get):
        mock_get.return_value = FakeResponse({
            "success": True,
            "result": {"profile": {"props": {"net": {"modem": None}}}},
        })

        self.assertEqual(HongdianApiClient().get_profile_signal_info("HD-1"), {})


if __name__ == "__main__":
    unittest.main()
