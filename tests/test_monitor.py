from __future__ import annotations

import unittest
from datetime import datetime, timezone

import monitor


class CompareTests(unittest.TestCase):
    def test_inventory_changes_and_window(self) -> None:
        old = {
            "1": {
                "name": "测试社区",
                "district": "南山区",
                "street": "粤海街道",
                "remaining": 0,
                "full_rented": True,
                "window_active": False,
            }
        }
        new = {
            "1": {
                "name": "测试社区",
                "district": "南山区",
                "street": "粤海街道",
                "remaining": 3,
                "full_rented": False,
                "window_active": True,
            }
        }
        changes = monitor.compare_villages(old, new)
        self.assertEqual(
            [item["type"] for item in changes],
            ["inventory_increased", "full_rented_changed", "window_active_changed"],
        )

    def test_only_watched_district_triggers_email(self) -> None:
        villages = {
            "1": {
                "name": "南山社区",
                "district": "南山区",
                "street": "粤海街道",
                "remaining": 2,
                "full_rented": False,
                "window_active": True,
            },
            "2": {
                "name": "福田社区",
                "district": "福田区",
                "street": "梅林街道",
                "remaining": 8,
                "full_rented": False,
                "window_active": True,
            },
        }
        changes = [
            {"type": "inventory_increased", "village_id": "1"},
            {"type": "inventory_increased", "village_id": "2"},
        ]
        self.assertEqual(
            monitor.watched_alert_ids(changes, villages, {"南山区"}), ["1"]
        )

    def test_decrease_does_not_trigger_email(self) -> None:
        villages = {
            "1": {
                "name": "测试社区",
                "district": "南山区",
                "street": "粤海街道",
                "remaining": 1,
                "full_rented": False,
                "window_active": True,
            }
        }
        changes = [{"type": "inventory_decreased", "village_id": "1"}]
        self.assertEqual(
            monitor.watched_alert_ids(changes, villages, {"南山区"}), []
        )


class ScheduleTests(unittest.TestCase):
    def test_next_run_is_01_minute(self) -> None:
        current = datetime(2026, 9, 17, 9, 59, 30, tzinfo=timezone.utc)
        actual = monitor.next_run_time(current, [1, 11, 21, 31, 41, 51])
        self.assertEqual(actual.hour, 10)
        self.assertEqual(actual.minute, 1)

    def test_next_run_is_11_minute(self) -> None:
        current = datetime(2026, 9, 17, 10, 1, 1, tzinfo=timezone.utc)
        actual = monitor.next_run_time(current, [1, 11, 21, 31, 41, 51])
        self.assertEqual(actual.hour, 10)
        self.assertEqual(actual.minute, 11)


class EmailTests(unittest.TestCase):
    def test_email_contains_building_details(self) -> None:
        villages = {
            "1": {
                "name": "高新区社区",
                "district": "南山区",
                "street": "粤海街道",
                "remaining": 2,
            }
        }
        buildings = {
            "1": [{"buildingName": "测试楼栋", "remainingQuota": 2}]
        }
        subject, body = monitor.build_email(
            "2026-09-17T22:01:00+08:00",
            ["1"],
            villages,
            buildings,
            "【测试】",
        )
        self.assertIn("高新区社区", subject)
        self.assertIn("测试楼栋：2", body)


if __name__ == "__main__":
    unittest.main()
