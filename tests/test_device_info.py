import unittest
from unittest.mock import Mock, patch

from device_info import DeviceInfoFetcher, _channel_report


class DeviceInfoTests(unittest.TestCase):
    def test_dual_channel_report_uses_left_and_right(self):
        result = _channel_report({
            "powerStatus": {"R1": 1, "R2": 0},
            "doorStatus": {"R1": 1, "R2": 0},
            "lockStatus": {"R1": 0, "R2": 1},
            "cameraStatus": {"R1": 1, "R2": 1},
        })
        self.assertEqual(result["Left"]["Power Status"], "Normal")
        self.assertEqual(result["Right"]["Power Status"], "Abnormal")
        self.assertEqual(result["Left"]["Lock Status"], "Abnormal")
        self.assertEqual(result["Right"]["Camera Status"], "Normal")

    def test_missing_channel_is_not_reported_as_abnormal(self):
        result = _channel_report({"doorStatus": {"R1": 1}})
        self.assertEqual(result, {"Left": {"Door Status": "Normal"}})

    @patch("device_info.requests.get")
    @patch("device_info.requests.post")
    def test_basic_and_operating_info_are_fetched_independently(self, post, get):
        post.return_value = Mock(
            json=lambda: {"code": "200", "data": {"list": [{
                "id": 3620,
                "code": "HB120003US",
                "cabinetTypeName": "智能柜",
                "statusName": "已投放",
                "serialNo": "BOARD-1",
                "currentVersion": "1.0",
                "version": "1.1",
            }]}},
            raise_for_status=lambda: None,
        )
        get.return_value = Mock(
            json=lambda: {"code": "200", "data": {
                "powerStatusName": "供电正常",
                "doorStatus": {"Left": 1, "Right": 1},
                "lockStatus": {"Left": 1, "Right": 1},
                "cameraStatus": {"Left": 0},
            }},
            raise_for_status=lambda: None,
        )

        result = DeviceInfoFetcher().get_device_info("HB120003US", "token")
        self.assertEqual(result["Basic Info"]["Device Type"], "Smart Cabinet")
        self.assertEqual(result["Operating Info"]["Power Status"], "Power Normal")
        self.assertIn("Left", result["Operating Info"]["Channels"])
        self.assertIn("Right", result["Operating Info"]["Channels"])
        self.assertNotIn("Camera Status", result["Operating Info"]["Channels"]["Right"])


if __name__ == "__main__":
    unittest.main()
