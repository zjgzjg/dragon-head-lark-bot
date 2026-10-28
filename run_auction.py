#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.lark_webhook import send_feishu_post
from src.report_auction import build_auction_report


def main() -> int:
    watch = [c.strip() for c in os.environ.get("WATCHLIST", "603278,603028,603528").split(",") if c.strip()]
    thermometer = os.environ.get("THERMOMETER", "603278").strip()
    body = build_auction_report(watch, thermometer)
    title = "竞价快报"
    send_feishu_post(body, title=title)
    print("OK auction report sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
