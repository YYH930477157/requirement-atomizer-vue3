from __future__ import annotations

import unittest

from requirement_schema import VALID_LABELS, map_labels


class LabelMappingTests(unittest.TestCase):
    def primary(self, text: str) -> str:
        return map_labels(text)[0]

    def test_object_names_map_to_correct_primary_domain(self) -> None:
        cases = {
            "Clock (OBIS 0-0:1.0.0.255)": "时钟",
            "Active energy import (+A) incremental": "计量",
            "Special Days Table": "节假日",
            "Tariffication script table": "费率",
            "Security Setup": "安全",
            "Disconnect control object": "负控",
            "Threshold for voltage sag": "门限范围",
            "Firmware Image transfer": "升级",
            "Billing reset lockout time": "结算",
        }
        for text, expected in cases.items():
            self.assertEqual(self.primary(text), expected, text)

    def test_false_friends_go_to_event_not_metering(self) -> None:
        # "current" 在对象名里是「当前/正在」而非电流；事件记录排在计量前应先赢
        self.assertEqual(self.primary("Duration of current long power failures in phase L1"), "事件记录")
        self.assertEqual(self.primary("Event Object - Export Power Contract Event Log"), "事件记录")

    def test_unmatched_object_model_falls_back_to_communication(self) -> None:
        self.assertEqual(map_labels("Association LN / SAP assignment"), ["通信协议"])

    def test_labels_always_valid_and_nonempty(self) -> None:
        for text in ("", "随便一个没有关键词的标题", "Global Meter Reset"):
            labels = map_labels(text)
            self.assertTrue(labels)
            for label in labels:
                self.assertIn(label, VALID_LABELS)


if __name__ == "__main__":
    unittest.main()
