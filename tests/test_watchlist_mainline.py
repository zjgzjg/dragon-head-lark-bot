# -*- coding: utf-8 -*-
import os
import unittest

import pandas as pd

from src.watchlist import mainline_pool, pick_auto_thermometer, pick_auto_watch_codes


def _sample_pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "代码": "600838",
                "名称": "上海九百",
                "连板数": 5,
                "封单比": 2.8,
                "炸板次数": 0,
                "换手率": 8.0,
                "首次封板时间": 92500,
                "所属行业": "商业百货",
            },
            {
                "代码": "000678",
                "名称": "襄阳轴承",
                "连板数": 4,
                "封单比": 1.7,
                "炸板次数": 1,
                "换手率": 20.6,
                "首次封板时间": 93400,
                "所属行业": "汽车零部件",
            },
            {
                "代码": "603528",
                "名称": "多伦科技",
                "连板数": 4,
                "封单比": 1.7,
                "炸板次数": 1,
                "换手率": 11.7,
                "首次封板时间": 92500,
                "所属行业": "软件服务",
            },
            {
                "代码": "002820",
                "名称": "桂发祥",
                "连板数": 2,
                "封单比": 2.0,
                "炸板次数": 0,
                "换手率": 17.9,
                "首次封板时间": 101100,
                "所属行业": "食品",
            },
        ]
    )


class MainlineWatchlistTest(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()
        os.environ["MAINLINE_KEYWORD"] = "机器人"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_thermometer_not_consumer_height(self):
        df = _sample_pool()
        therm = pick_auto_thermometer(df)
        self.assertIn(therm, {"000678", "603528"})
        self.assertNotEqual(therm, "600838")

    def test_watchlist_excludes_consumer_2board_when_robot_tiers_exist(self):
        df = _sample_pool()
        therm = pick_auto_thermometer(df)
        codes = pick_auto_watch_codes(df, therm, max_n=5)
        self.assertNotIn("600838", codes)
        self.assertNotIn("002820", codes)
        self.assertTrue(len(codes) >= 1)


class MainlineReasonMatchTest(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()
        os.environ["MAINLINE_KEYWORD"] = "机器人"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_match_on_limit_reason(self):
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
                    "涨停原因": "大消费",
                },
            ]
        )
        pool = mainline_pool(df)
        self.assertEqual(len(pool), 1)
        self.assertEqual(str(pool.iloc[0]["代码"]), "603028")


if __name__ == "__main__":
    unittest.main()
