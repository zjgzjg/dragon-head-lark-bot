#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.lark_webhook import send_feishu_post
from src.market_data import latest_trade_date
from src.report_close import build_close_report, maybe_llm_polish


def main() -> int:
    date = os.environ.get("TRADE_DATE") or latest_trade_date()
    watch = [c.strip() for c in os.environ.get("WATCHLIST", "603278,603028,603528").split(",") if c.strip()]
    thermometer = os.environ.get("THERMOMETER", "603278").strip()

    body = build_close_report(date, watch, thermometer)
    body = maybe_llm_polish(body)
    title = f"收盘复盘 {date[4:6]}-{date[6:8]}"
    send_feishu_post(body, title=title)
    print("OK close report sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
