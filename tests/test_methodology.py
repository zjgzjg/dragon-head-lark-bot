# -*- coding: utf-8 -*-
import unittest

import pandas as pd

from src.methodology import (
    auction_open_verdict,
    close_context_vetoes,
    close_hard_fail_reasons,
    thermometer_auction_verdict,
)


class MethodologyAuctionTest(unittest.TestCase):
    def test_low_open_veto(self):
        self.assertIn("删", auction_open_verdict(-2.5))

    def test_high_open_no_chase(self):
        v = auction_open_verdict(5.0)
        self.assertIn("不追", v)
        self.assertNotIn("❌ 低开", v)

    def test_sweet_spot_observe(self):
        v = auction_open_verdict(1.5)
        self.assertIn("✅", v)
        self.assertIn("观察窗", v)

    def test_dump_risk(self):
        v = auction_open_verdict(1.0, dump_risk=True)
        self.assertIn("出货", v)

    def test_therm_limit_open(self):
        v = thermometer_auction_verdict(9.9, "603028")
        self.assertIn("线活", v)


class MethodologyCloseTest(unittest.TestCase):
    def test_late_seal_veto(self):
        row = pd.Series(
            {
                "连板数": 3,
                "封单比": 5.0,
                "炸板次数": 0,
                "换手率": 10.0,
                "首次封板时间": 143000,
            }
        )
        self.assertTrue(any("14:00" in x for x in close_hard_fail_reasons(row)))

    def test_dragon2_psychology(self):
        row = pd.Series(
            {
                "连板数": 2,
                "封单比": 5.0,
                "炸板次数": 0,
                "换手率": 10.0,
                "首次封板时间": 93000,
                "涨停原因": "行业景气",
            }
        )
        v = close_context_vetoes(row, max_height_in_pool=5, is_thermometer=False)
        self.assertTrue(any("龙二" in x for x in v))


if __name__ == "__main__":
    unittest.main()
