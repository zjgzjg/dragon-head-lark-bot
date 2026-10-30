# -*- coding: utf-8 -*-
import os
import unittest

import pandas as pd

from src.lianban_net import LianbanSummary
from src.mainline import detect_mainline
from src.watchlist import mainline_pool, pick_auto_thermometer


def _lb(themes: str) -> LianbanSummary:
    return LianbanSummary(
        date_iso="2026-10-29",
        zt=50,
        lianban=10,
        max_board=5,
        dt=2,
        seal_rate=70.0,
        zhaban=5,
        phase="修复期",
        temp=55.0,
        themes=themes,
        one_liner=None,
        url="https://lianban.net/",
    )


class MainlineDetectTest(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()
        os.environ.pop("MAINLINE_KEYWORD", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_em_leader_cross_confirmed_with_lianban(self):
        df = pd.DataFrame(
            [
                {
                    "代码": "603028",
                    "名称": "A",
                    "连板数": 3,
                    "封单比": 5.0,
                    "炸板次数": 0,
                    "换手率": 10.0,
                    "首次封板时间": 92500,
                    "所属行业": "专用设备",
                    "涨停原因": "机器人概念",
                    "成交额": 500_000_000,
                },
                {
                    "代码": "603029",
                    "名称": "B",
                    "连板数": 2,
                    "封单比": 4.0,
                    "炸板次数": 0,
                    "换手率": 8.0,
                    "首次封板时间": 93000,
                    "所属行业": "专用设备",
                    "涨停原因": "机器人概念",
                    "成交额": 300_000_000,
                },
                {
                    "代码": "600838",
                    "名称": "消费龙",
                    "连板数": 5,
                    "封单比": 3.0,
                    "炸板次数": 0,
                    "换手率": 8.0,
                    "首次封板时间": 92500,
                    "所属行业": "商业百货",
                    "涨停原因": "大消费",
                    "成交额": 800_000_000,
                },
            ]
        )
        d = detect_mainline(df, _lb("人形机器人、算力"))
        self.assertTrue(d.confirmed)
        self.assertIn("机器人", d.label)
        pool = mainline_pool(df, decision=d)
        self.assertNotIn("600838", pool["代码"].astype(str).tolist())

    def test_em_without_lianban_uses_eastmoney_only(self):
        df = pd.DataFrame(
            [
                {
                    "代码": "001",
                    "名称": "X",
                    "连板数": 2,
                    "封单比": 3.0,
                    "炸板次数": 0,
                    "换手率": 5.0,
                    "首次封板时间": 92500,
                    "涨停原因": "低空经济",
                    "成交额": 100,
                },
                {
                    "代码": "002",
                    "名称": "Y",
                    "连板数": 2,
                    "封单比": 3.0,
                    "炸板次数": 0,
                    "换手率": 5.0,
                    "首次封板时间": 93000,
                    "涨停原因": "低空经济",
                    "成交额": 200,
                },
            ]
        )
        d = detect_mainline(df, None)
        self.assertFalse(d.confirmed)
        self.assertIn("低空", d.label)


class MainlineKeywordPinTest(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()
        os.environ["MAINLINE_KEYWORD"] = "机器人"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_pin_overrides_auto(self):
        df = pd.DataFrame(
            [
                {
                    "代码": "603028",
                    "名称": "赛福天",
                    "连板数": 4,
                    "封单比": 1.0,
                    "炸板次数": 1,
                    "换手率": 10.0,
                    "首次封板时间": 92500,
                    "所属行业": "专用设备",
                    "涨停原因": "机器人概念",
                },
                {
                    "代码": "600838",
                    "名称": "上海九百",
                    "连板数": 5,
                    "封单比": 3.0,
                    "炸板次数": 0,
                    "换手率": 8.0,
                    "首次封板时间": 92500,
                    "所属行业": "商业百货",
                },
            ]
        )
        therm = pick_auto_thermometer(df)
        self.assertEqual(therm, "603028")


if __name__ == "__main__":
    unittest.main()
