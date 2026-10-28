#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.lark_webhook import send_feishu_post
from src.report_image import render_markdown_long_image
from src.report_auction import build_auction_report
from src.watchlist import parse_manual_watchlist


def main() -> int:
    watch = parse_manual_watchlist()
    thermometer = os.environ.get("THERMOMETER", "").strip()
    from src.trade_calendar import beijing_session_yyyymmdd, fmt_date, weekday_cn

    session = beijing_session_yyyymmdd()
    title = f"{fmt_date(session)}（{weekday_cn(session)}）竞价快报"
    try:
        body = build_auction_report(watch, thermometer)
    except Exception as exc:
        body = (
            f"## ⏰ 竞价快报（生成异常）\n\n"
            f"> `{type(exc).__name__}`：请查看 Actions 日志。\n\n"
            f"观察名单：`{', '.join(watch)}` 体温计 `{thermometer}`"
        )
    try:
        img = render_markdown_long_image(body, title=title)
        send_feishu_post(body, title=title, image_path=img)
    except Exception as exc:
        print(f"Feishu send failed: {exc}", file=sys.stderr)
        return 1
    print("OK auction report sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
